"""Persistent XboxUnity title catalog and offline autocomplete queries."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Generator, Iterable

import requests

from app_paths import DATABASE_PATH
from database_migrations import ensure_application_schema
from knowledge_base import is_unknown


XBOXUNITY_BASE_URL = "http://xboxunity.net"
TITLE_LIST_PATH = "/Resources/Lib/TitleList.php"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class TitleSuggestion:
    """One locally cached title shown by autocomplete."""

    titleid: str
    name: str
    title_type: str

    @property
    def label(self) -> str:
        suffix = f" [{self.title_type}]" if self.title_type else ""
        return f"{self.name} - {self.titleid}{suffix}"


@dataclass(frozen=True)
class CatalogSyncResult:
    """Summary of a completed XboxUnity catalog refresh."""

    pages_fetched: int
    items_upserted: int
    library_names_enriched: int


class XboxUnityTitleCatalog:
    """Sync XboxUnity's paginated title list and query it without network access."""

    def __init__(
        self,
        database_path: Path | str = DATABASE_PATH,
        *,
        session: requests.Session | None = None,
        base_url: str = XBOXUNITY_BASE_URL,
        request_interval: float = 0.35,
        timeout: float = 30,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url.startswith("http://"):
            raise ValueError("XboxUnity catalog access must remain HTTP-only")
        self.database_path = Path(database_path)
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self.request_interval = max(0.0, request_interval)
        self.timeout = timeout
        self.sleep = sleep
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connection() as connection:
            ensure_application_schema(connection)

    def count(self) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM xboxunity_title_catalog"
            ).fetchone()
        return int(row["count"])

    def is_stale(self, max_age_days: int = 7) -> bool:
        """Return whether no successful, sufficiently recent sync exists."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT completed_at
                FROM xboxunity_catalog_sync_runs
                WHERE status = 'completed'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None or not row["completed_at"]:
            return True
        try:
            completed = datetime.fromisoformat(row["completed_at"])
        except ValueError:
            return True
        if completed.tzinfo is None:
            completed = completed.replace(tzinfo=timezone.utc)
        return completed < cutoff

    def search(self, query: str, limit: int = 12) -> list[TitleSuggestion]:
        """Search cached names and TitleIDs, ranking prefixes ahead of substrings."""
        value = query.strip()
        if not value:
            return []
        lowered = value.lower()
        contains = f"%{lowered}%"
        prefix = f"{lowered}%"
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT titleid, name, COALESCE(title_type, '') AS title_type
                FROM xboxunity_title_catalog
                WHERE LOWER(titleid) LIKE ? OR LOWER(name) LIKE ?
                ORDER BY
                    CASE
                        WHEN LOWER(titleid) = ? THEN 0
                        WHEN LOWER(titleid) LIKE ? THEN 1
                        WHEN LOWER(name) LIKE ? THEN 2
                        ELSE 3
                    END,
                    name COLLATE NOCASE,
                    titleid
                LIMIT ?
                """,
                (contains, contains, lowered, prefix, prefix, max(1, limit)),
            ).fetchall()
        return [
            TitleSuggestion(row["titleid"], row["name"], row["title_type"])
            for row in rows
        ]

    def sync(
        self,
        *,
        progress: Callable[[int, int, int], None] | None = None,
        page_size: int = 100,
    ) -> CatalogSyncResult:
        """Refresh every title page, preserving the last usable cache on failure."""
        started_at = _now()
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE xboxunity_catalog_sync_runs
                SET completed_at = ?, status = 'interrupted',
                    error_message = COALESCE(
                        error_message,
                        'Application exited before catalog refresh completed'
                    )
                WHERE status = 'running'
                """,
                (started_at,),
            )
            cursor = connection.execute(
                """
                INSERT INTO xboxunity_catalog_sync_runs(started_at, status)
                VALUES (?, 'running')
                """,
                (started_at,),
            )
            run_id = _as_int(cursor.lastrowid)
            if run_id <= 0:
                raise RuntimeError("Could not create XboxUnity catalog sync run")

        pages_expected = 0
        pages_fetched = 0
        items_upserted = 0
        library_names_enriched = 0
        try:
            page = 0
            while page == 0 or page < pages_expected:
                payload, source_url = self._fetch_page(page, page_size)
                pages_expected = max(1, _as_int(payload.get("Pages")))
                items = payload.get("Items", [])
                if not isinstance(items, list):
                    raise ValueError("XboxUnity title list returned invalid Items data")
                items_upserted += self._store_page(items, source_url)
                pages_fetched += 1
                library_names_enriched += self.enrich_library_names()
                with self._connection() as connection:
                    connection.execute(
                        """
                        UPDATE xboxunity_catalog_sync_runs
                        SET pages_expected = ?, pages_fetched = ?, items_upserted = ?
                        WHERE id = ?
                        """,
                        (pages_expected, pages_fetched, items_upserted, run_id),
                    )
                if progress:
                    progress(pages_fetched, pages_expected, items_upserted)
                page += 1
                if page < pages_expected and self.request_interval:
                    self.sleep(self.request_interval)

            with self._connection() as connection:
                connection.execute(
                    "DELETE FROM xboxunity_title_catalog WHERE fetched_at < ?",
                    (started_at,),
                )
            library_names_enriched += self.enrich_library_names()
            with self._connection() as connection:
                connection.execute(
                    """
                    UPDATE xboxunity_catalog_sync_runs
                    SET completed_at = ?, status = 'completed',
                        pages_expected = ?, pages_fetched = ?, items_upserted = ?
                    WHERE id = ?
                    """,
                    (
                        _now(),
                        pages_expected,
                        pages_fetched,
                        items_upserted,
                        run_id,
                    ),
                )
            return CatalogSyncResult(
                pages_fetched,
                items_upserted,
                library_names_enriched,
            )
        except Exception as exc:
            with self._connection() as connection:
                connection.execute(
                    """
                    UPDATE xboxunity_catalog_sync_runs
                    SET completed_at = ?, status = 'failed',
                        pages_expected = ?, pages_fetched = ?,
                        items_upserted = ?, error_message = ?
                    WHERE id = ?
                    """,
                    (
                        _now(),
                        pages_expected,
                        pages_fetched,
                        items_upserted,
                        str(exc)[:1000],
                        run_id,
                    ),
                )
            raise

    def _fetch_page(self, page: int, page_size: int) -> tuple[dict[str, Any], str]:
        url = f"{self.base_url}{TITLE_LIST_PATH}"
        params: dict[str, str | int] = {
            "category": 0,
            "count": min(max(page_size, 10), 100),
            "direction": 1,
            "filter": 0,
            "page": page,
            "search": "",
            "sort": 3,
        }
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("XboxUnity title list returned a non-object response")
        return payload, response.url

    def _store_page(self, items: Iterable[Any], source_url: str) -> int:
        fetched_at = _now()
        records: list[tuple[Any, ...]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            titleid = str(item.get("TitleID", "")).strip().upper()
            name = str(item.get("Name", "")).strip()
            if len(titleid) != 8 or not name:
                continue
            records.append(
                (
                    titleid,
                    name,
                    str(item.get("HBTitleID", "")).strip().upper() or None,
                    str(item.get("TitleType", "")).strip() or None,
                    _as_int(item.get("LinkEnabled")),
                    _as_int(item.get("Covers")),
                    _as_int(item.get("Updates")),
                    _as_int(item.get("MediaIDCount")),
                    _as_int(item.get("UserCount")),
                    str(item.get("NewestContent", "")).strip() or None,
                    source_url,
                    json.dumps(item, sort_keys=True),
                    fetched_at,
                )
            )
        if not records:
            return 0
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT INTO xboxunity_title_catalog(
                    titleid, name, hb_titleid, title_type, link_enabled,
                    covers_count, updates_count, media_id_count, user_count,
                    newest_content, source_url, raw_json, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(titleid) DO UPDATE SET
                    name = excluded.name,
                    hb_titleid = excluded.hb_titleid,
                    title_type = excluded.title_type,
                    link_enabled = excluded.link_enabled,
                    covers_count = excluded.covers_count,
                    updates_count = excluded.updates_count,
                    media_id_count = excluded.media_id_count,
                    user_count = excluded.user_count,
                    newest_content = excluded.newest_content,
                    source_url = excluded.source_url,
                    raw_json = excluded.raw_json,
                    fetched_at = excluded.fetched_at
                """,
                records,
            )
        return len(records)

    def enrich_library_names(self) -> int:
        """Fill only missing, unknown, or TitleID-shaped library names."""
        changed = 0
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    t.titleid,
                    t.name AS current_name,
                    t.publisher,
                    t.metadata,
                    c.name AS catalog_name
                FROM titleids AS t
                JOIN xboxunity_title_catalog AS c ON c.titleid = t.titleid
                """
            ).fetchall()
            for row in rows:
                current = row["current_name"]
                if not (is_unknown(current) or str(current).upper() == row["titleid"]):
                    continue
                metadata = {}
                if row["metadata"]:
                    try:
                        metadata = json.loads(row["metadata"])
                    except json.JSONDecodeError:
                        metadata = {}
                metadata["title_source"] = "XboxUnity title catalog"
                connection.execute(
                    "UPDATE titleids SET name = ?, metadata = ? WHERE titleid = ?",
                    (
                        row["catalog_name"],
                        json.dumps(metadata, sort_keys=True),
                        row["titleid"],
                    ),
                )
                search_parts = [
                    row["titleid"],
                    row["catalog_name"],
                    row["publisher"] or "",
                    *(str(value) for value in metadata.values() if value),
                ]
                connection.execute(
                    """
                    INSERT INTO search_index(titleid, search_text)
                    VALUES (?, ?)
                    ON CONFLICT(titleid) DO UPDATE SET
                        search_text = excluded.search_text
                    """,
                    (
                        row["titleid"],
                        " ".join(search_parts).lower(),
                    ),
                )
                changed += 1
        return changed
