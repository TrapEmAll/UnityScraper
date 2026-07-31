"""Conservative structured extraction from locally cached reference articles."""

from __future__ import annotations

import html
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import DATABASE_PATH
from database_migrations import ensure_application_schema


TAG_RE = re.compile(r"<[^>]+>")
ROW_RE = re.compile(
    r"<tr[^>]*>\s*<(?:th|td)[^>]*>(.*?)</(?:th|td)>\s*"
    r"<td[^>]*>(.*?)</td>\s*</tr>",
    re.IGNORECASE | re.DOTALL,
)
PAIR_RE = re.compile(r"^([A-Za-z][A-Za-z0-9 /_+#().-]{1,48})\s*[:=-]\s*(.{1,500})$")

RECORD_TYPES = (
    ("motherboard", ("motherboard", "xenon", "zephyr", "falcon", "jasper", "trinity", "corona")),
    ("dvd_drive", ("dvd drive", "lite-on", "hitachi", "benq", "samsung")),
    ("dashboard", ("dashboard", "kernel", "system update")),
    ("exploit", ("jtag", "rgh", "reset glitch", "exploit")),
    ("error_code", ("error code", "secondary error", "red ring")),
    ("file_format", ("file format", "stfs", "xex", "xbe", "fatx", "xcontent")),
    ("repair", ("repair", "reflow", "replace", "solder")),
    ("tool", ("tool", "utility", "homebrew", "application")),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StructuredKnowledgeService:
    """Extract useful fields while preserving the original source document."""

    def __init__(self, db_path: str | Path = DATABASE_PATH) -> None:
        self.db_path = Path(db_path)
        with self._connect() as connection:
            ensure_application_schema(connection)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def extract_cached_documents(self, limit: int = 0) -> dict[str, Any]:
        sql = """
            SELECT d.id, d.source_id, d.title, d.url, d.cache_path, d.metadata,
                   s.name source_name
            FROM source_documents d JOIN knowledge_sources s ON s.id=d.source_id
            WHERE d.cache_path IS NOT NULL AND d.cache_path <> ''
            ORDER BY d.id
        """
        values: tuple[Any, ...] = ()
        if limit > 0:
            sql += " LIMIT ?"
            values = (limit,)
        extracted = 0
        skipped = 0
        errors: list[str] = []
        with self._connect() as connection:
            rows = connection.execute(sql, values).fetchall()
            for row in rows:
                try:
                    path = Path(row["cache_path"])
                    if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
                        skipped += 1
                        continue
                    raw = path.read_text(encoding="utf-8", errors="replace")
                    title = (row["title"] or Path(row["url"]).name).strip()
                    properties = extract_properties(raw)
                    properties.update(
                        {"source": row["source_name"], "source_url": row["url"]}
                    )
                    record_type = infer_record_type(title, raw[:20_000])
                    connection.execute(
                        """
                        INSERT INTO structured_knowledge_records(
                            document_id, source_id, record_type, canonical_name,
                            normalized_name, properties_json, confidence, extracted_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(document_id, record_type, normalized_name) DO UPDATE SET
                            canonical_name=excluded.canonical_name,
                            properties_json=excluded.properties_json,
                            confidence=excluded.confidence,
                            extracted_at=excluded.extracted_at
                        """,
                        (
                            row["id"], row["source_id"], record_type, title,
                            normalize(title), json.dumps(properties, sort_keys=True),
                            0.80 if properties else 0.60, utc_now(),
                        ),
                    )
                    extracted += 1
                except (OSError, UnicodeError, sqlite3.Error, ValueError) as exc:
                    errors.append(f"{row['url']}: {exc}")
        return {"extracted": extracted, "skipped": skipped, "errors": errors}

    def list_records(self, record_type: str = "", query: str = "") -> list[dict]:
        clauses: list[str] = []
        values: list[Any] = []
        if record_type:
            clauses.append("r.record_type=?")
            values.append(record_type)
        if query.strip():
            clauses.append("(r.canonical_name LIKE ? OR r.properties_json LIKE ?)")
            term = f"%{query.strip()}%"
            values.extend((term, term))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT r.*, d.url source_url, s.name source_name
                FROM structured_knowledge_records r
                JOIN source_documents d ON d.id=r.document_id
                JOIN knowledge_sources s ON s.id=r.source_id
                """ + where + " ORDER BY r.record_type, r.canonical_name LIMIT 2000",
                values,
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["properties"] = json.loads(item.pop("properties_json"))
            result.append(item)
        return result


def extract_properties(raw: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for key, value in ROW_RE.findall(raw):
        _add_property(properties, clean_markup(key), clean_markup(value))
    plain = clean_markup(raw)
    for line in plain.splitlines():
        match = PAIR_RE.match(" ".join(line.split()))
        if match:
            _add_property(properties, match.group(1), match.group(2))
        if len(properties) >= 40:
            break
    return properties


def _add_property(properties: dict[str, str], key: str, value: str) -> None:
    normalized = normalize(key).replace(" ", "_")
    cleaned = " ".join(value.split())
    if normalized and cleaned and normalized not in properties and len(cleaned) <= 500:
        properties[normalized] = cleaned


def clean_markup(value: str) -> str:
    value = re.sub(r"<(?:br|/p|/li|/tr|/h\d)>\s*", "\n", value, flags=re.I)
    return html.unescape(TAG_RE.sub(" ", value)).replace("\r", "")


def infer_record_type(title: str, body: str) -> str:
    haystack = f"{title}\n{clean_markup(body)}".casefold()
    scores = [
        (sum(haystack.count(keyword) for keyword in keywords), kind)
        for kind, keywords in RECORD_TYPES
    ]
    score, kind = max(scores)
    return kind if score else "reference_article"


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())
