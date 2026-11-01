"""Personal per-game data: favorites, play status, rating, notes and tags."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from unityscraper.core.paths import DATABASE_PATH

PLAY_STATUSES = ("", "Backlog", "Playing", "Completed", "Abandoned", "Wishlist")
TAG_MAX_LENGTH = 32


@dataclass(frozen=True)
class GameUserData:
    """The user's own data for one game; defaults when nothing was stored."""

    titleid: str
    favorite: bool = False
    play_status: str = ""
    rating: int | None = None
    notes: str = ""
    tags: tuple[str, ...] = ()


def normalize_titleid(titleid: str) -> str:
    value = str(titleid).strip().upper()
    if not value:
        raise ValueError("TitleID cannot be empty")
    return value


def normalize_tag(tag: str) -> str:
    """Strip and collapse whitespace; reject empty or over-long tags."""
    value = " ".join(str(tag).split())
    if not value:
        raise ValueError("Tag cannot be empty")
    if len(value) > TAG_MAX_LENGTH:
        raise ValueError(f"Tags can be at most {TAG_MAX_LENGTH} characters")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GameUserDataService:
    """Read and write ``game_user_data`` and ``game_tags``."""

    def __init__(self, database_path: str | Path = DATABASE_PATH) -> None:
        from database_migrations import ensure_application_schema

        self.database_path = Path(database_path)
        with self._connect() as connection:
            ensure_application_schema(connection)

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

    # ------------------------------------------------------------- reads

    def get(self, titleid: str) -> GameUserData:
        titleid = normalize_titleid(titleid)
        return self.get_many([titleid])[titleid]

    def get_many(self, titleids: Iterable[str]) -> dict[str, GameUserData]:
        """Return data for every requested TitleID (defaults when no row exists)."""
        wanted = {normalize_titleid(titleid) for titleid in titleids}
        if not wanted:
            return {}
        # Both tables only hold games the user touched, so a full read is small and
        # avoids SQLite's bound-parameter limit for large libraries.
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM game_user_data").fetchall()
            tag_rows = connection.execute(
                "SELECT titleid, tag FROM game_tags ORDER BY tag COLLATE NOCASE"
            ).fetchall()
        tags: dict[str, list[str]] = {}
        for row in tag_rows:
            tags.setdefault(row["titleid"], []).append(row["tag"])
        result = {
            titleid: GameUserData(titleid, tags=tuple(tags.get(titleid, ())))
            for titleid in wanted
        }
        for row in rows:
            titleid = row["titleid"]
            if titleid in wanted:
                result[titleid] = GameUserData(
                    titleid=titleid,
                    favorite=bool(row["favorite"]),
                    play_status=row["play_status"],
                    rating=row["rating"],
                    notes=row["notes"],
                    tags=tuple(tags.get(titleid, ())),
                )
        return result

    def all_tags(self) -> list[tuple[str, int]]:
        """Return ``(tag, game count)`` sorted by count, then name."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT tag, COUNT(*) AS uses FROM game_tags GROUP BY tag "
                "ORDER BY uses DESC, tag COLLATE NOCASE"
            ).fetchall()
        return [(row["tag"], int(row["uses"])) for row in rows]

    def favorite_count(self) -> int:
        with self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM game_user_data WHERE favorite = 1"
                ).fetchone()[0]
            )

    # ------------------------------------------------------------ writes

    def _upsert(self, titleids: Iterable[str], column: str, value: object) -> None:
        # ``column`` is always one of the literals below, never user input.
        updated = _now()
        rows = [(normalize_titleid(titleid), value, updated) for titleid in titleids]
        with self._connect() as connection:
            connection.executemany(
                f"INSERT INTO game_user_data(titleid, {column}, updated_at) VALUES (?, ?, ?) "
                f"ON CONFLICT(titleid) DO UPDATE SET {column} = excluded.{column}, "
                "updated_at = excluded.updated_at",
                rows,
            )

    def set_favorite(self, titleid: str, favorite: bool) -> None:
        self.set_favorite_many([titleid], favorite)

    def set_favorite_many(self, titleids: Iterable[str], favorite: bool) -> None:
        self._upsert(titleids, "favorite", int(bool(favorite)))

    def set_play_status(self, titleid: str, play_status: str) -> None:
        self.set_play_status_many([titleid], play_status)

    def set_play_status_many(self, titleids: Iterable[str], play_status: str) -> None:
        if play_status not in PLAY_STATUSES:
            raise ValueError(f"Unknown play status: {play_status!r}")
        self._upsert(titleids, "play_status", play_status)

    def set_rating(self, titleid: str, rating: int | None) -> None:
        if rating is not None and (
            isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5
        ):
            raise ValueError("Rating must be empty or a whole number from 1 to 5")
        self._upsert([titleid], "rating", rating)

    def set_notes(self, titleid: str, notes: str) -> None:
        self._upsert([titleid], "notes", str(notes))

    def add_tag(self, titleid: str, tag: str) -> str:
        """Attach a tag; returns the normalized tag. Case-insensitive duplicates are ignored."""
        return self.add_tag_many([titleid], tag)

    def add_tag_many(self, titleids: Iterable[str], tag: str) -> str:
        tag = normalize_tag(tag)
        created = _now()
        rows = [(normalize_titleid(titleid), tag, created) for titleid in titleids]
        with self._connect() as connection:
            # The tag column is COLLATE NOCASE, so the primary key rejects case variants.
            connection.executemany(
                "INSERT OR IGNORE INTO game_tags(titleid, tag, created_at) VALUES (?, ?, ?)",
                rows,
            )
        return tag

    def remove_tag(self, titleid: str, tag: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM game_tags WHERE titleid = ? AND tag = ?",
                (normalize_titleid(titleid), " ".join(str(tag).split())),
            )


__all__ = [
    "GameUserData",
    "GameUserDataService",
    "PLAY_STATUSES",
    "TAG_MAX_LENGTH",
    "normalize_tag",
]
