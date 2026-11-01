"""Title update watchlist: re-check chosen games on XboxUnity and count new updates."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from unityscraper.core.paths import CONFIG_PATH, DATABASE_PATH
from unityscraper.core.scheduling import ScheduledTask

SCHEDULE_TASK = "title-update-watch"


@dataclass(frozen=True)
class WatchedTitle:
    """One watchlist entry with its display name and last check outcome."""

    titleid: str
    name: str
    added_at: str
    last_checked_at: str | None
    last_status: str | None
    last_error: str | None
    known_update_count: int
    new_update_count: int


@dataclass(frozen=True)
class UpdateCheckResult:
    """Outcome of checking one title; ``error`` is set when the check failed."""

    titleid: str
    name: str
    new_updates: int
    total_updates: int
    error: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UpdateWatchService:
    """Keep the title update watchlist and detect newly published title updates."""

    def __init__(self, database_path: str | Path = DATABASE_PATH) -> None:
        from database import DatabaseManager

        self.database_path = Path(database_path)
        # Creates the scraper tables (titleids, title_updates) and runs ensure_application_schema.
        DatabaseManager(str(self.database_path))

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _update_count(connection: sqlite3.Connection, titleid: str) -> int:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM title_updates WHERE UPPER(titleid)=?", (titleid,)
            ).fetchone()[0]
        )

    def is_watched(self, titleid: str) -> bool:
        with self._connect() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM title_update_watchlist WHERE titleid=?",
                    (titleid.strip().upper(),),
                ).fetchone()
                is not None
            )

    def set_watched(self, titleid: str, watched: bool) -> None:
        titleid = titleid.strip().upper()
        with self._connect() as connection:
            if not watched:
                connection.execute(
                    "DELETE FROM title_update_watchlist WHERE titleid=?", (titleid,)
                )
                return
            connection.execute(
                "INSERT INTO title_update_watchlist(titleid, added_at, known_update_count) "
                "VALUES (?, ?, ?) ON CONFLICT(titleid) DO NOTHING",
                (titleid, _now(), self._update_count(connection, titleid)),
            )

    def watched_titleids(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT titleid FROM title_update_watchlist").fetchall()
        return {row["titleid"] for row in rows}

    def watched(self) -> list[WatchedTitle]:
        from knowledge_base import is_unknown

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT w.*, t.name AS library_name, xc.name AS catalog_name
                FROM title_update_watchlist AS w
                LEFT JOIN titleids AS t ON UPPER(t.titleid) = w.titleid
                LEFT JOIN xboxunity_title_catalog AS xc ON UPPER(xc.titleid) = w.titleid
                """
            ).fetchall()
        titles = []
        for row in rows:
            name = next(
                (
                    candidate.strip()
                    for candidate in (row["library_name"], row["catalog_name"])
                    if not is_unknown(candidate)
                    and candidate.strip().upper() != row["titleid"]
                ),
                row["titleid"],
            )
            titles.append(
                WatchedTitle(
                    row["titleid"], name, row["added_at"], row["last_checked_at"],
                    row["last_status"], row["last_error"],
                    int(row["known_update_count"]), int(row["new_update_count"]),
                )
            )
        return sorted(titles, key=lambda title: (title.name.casefold(), title.titleid))

    def check(self, titleid: str, collect: Callable[[str], object]) -> UpdateCheckResult:
        """Run ``collect(titleid)`` and record how many ``title_updates`` rows it added."""
        titleid = titleid.strip().upper()
        name = next((t.name for t in self.watched() if t.titleid == titleid), titleid)
        with self._connect() as connection:
            before = self._update_count(connection, titleid)
        error: str | None = None
        try:
            if collect(titleid) is False:
                error = "XboxUnity did not return metadata for this title"
        except Exception as exc:
            error = str(exc) or type(exc).__name__
        with self._connect() as connection:
            if error is not None:
                connection.execute(
                    "UPDATE title_update_watchlist SET last_checked_at=?, "
                    "last_status='failed', last_error=? WHERE titleid=?",
                    (_now(), error, titleid),
                )
                return UpdateCheckResult(titleid, name, 0, before, error)
            after = self._update_count(connection, titleid)
            new = max(0, after - before)
            connection.execute(
                "UPDATE title_update_watchlist SET last_checked_at=?, last_status='ok', "
                "last_error=NULL, known_update_count=?, "
                "new_update_count=new_update_count+? WHERE titleid=?",
                (_now(), after, new, titleid),
            )
        return UpdateCheckResult(titleid, name, new, after, None)

    def check_all(
        self,
        collect: Callable[[str], object],
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> list[UpdateCheckResult]:
        """Check every watched title; ``on_progress(index, total, name)`` runs before each."""
        titles = self.watched()
        results = []
        for index, title in enumerate(titles, start=1):
            if on_progress is not None:
                on_progress(index, len(titles), title.name)
            results.append(self.check(title.titleid, collect))
        return results

    def acknowledge(self, titleid: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE title_update_watchlist SET new_update_count=0 WHERE titleid=?",
                (titleid.strip().upper(),),
            )

    def acknowledge_all(self) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE title_update_watchlist SET new_update_count=0")

    def schedule(self) -> ScheduledTask:
        return ScheduledTask(
            self.database_path,
            SCHEDULE_TASK,
            default_interval_hours=24,
            min_interval_hours=6,
            default_enabled=False,
        )

    def run_if_due(self, collect: Callable[[str], object]) -> dict[str, Any] | None:
        """Check all watched titles when the schedule is enabled and due."""
        return self.schedule().run_if_due(lambda: self.check_all(collect))


def make_xboxunity_collector() -> Callable[[str], bool]:
    """Return a collector that refreshes one title's XboxUnity metadata.

    The scraper is built on first use because its constructor tests the network;
    connection errors then surface per title through ``UpdateWatchService.check``.
    A failed construction is re-raised for later titles instead of retrying the network.
    """
    scraper: Any = None
    failure: Exception | None = None

    def collect(titleid: str) -> bool:
        nonlocal scraper, failure
        if failure is not None:
            raise failure
        if scraper is None:
            from database import DatabaseManager
            from main import Config, UnityScraper

            config = Config(str(CONFIG_PATH))
            config.refresh_interval_days = 0  # watched titles must always be re-fetched
            try:
                scraper = UnityScraper(config, DatabaseManager())
            except Exception as exc:
                failure = exc
                raise
        return scraper.collect_metadata(titleid)

    return collect
