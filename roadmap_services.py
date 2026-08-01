"""Release-readiness services for metadata, audits, reports, and corrections."""

from __future__ import annotations

import hashlib
import html
import json
import sqlite3
import zipfile
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app_paths import DATABASE_PATH
from database_migrations import ensure_application_schema
from knowledge_base import EntityRecord, Fact, Identifier, KnowledgeRepository, is_unknown


SNAPSHOT_SCHEMA = 1
MAX_SNAPSHOT_EXPANDED = 512 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RoadmapRepository:
    def __init__(self, db_path: str | Path = DATABASE_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            KnowledgeRepository(connection).ensure_schema()
            ensure_application_schema(connection)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


class MetadataSnapshotService(RoadmapRepository):
    """Export and merge portable metadata without profile or filesystem data."""

    def export(self, destination: str | Path) -> dict[str, Any]:
        target = Path(destination).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".partial")
        with self.connect() as connection:
            catalog = [dict(row) for row in connection.execute(
                "SELECT * FROM xboxunity_title_catalog ORDER BY titleid"
            ).fetchall()]
            records = self._export_records(connection)
            sources = [dict(row) for row in connection.execute(
                "SELECT slug, name, homepage_url, license_name, license_url, notes "
                "FROM knowledge_sources ORDER BY slug"
            ).fetchall()]
        payload = {
            "schema": SNAPSHOT_SCHEMA,
            "application": "UnityScraper",
            "created_at": utc_now(),
            "contains_personal_data": False,
            "sources": sources,
            "catalog": catalog,
            "records": records,
        }
        encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        try:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("metadata.json", encoded)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        digest = sha256_file(target)
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO metadata_snapshot_runs(
                       operation, snapshot_path, created_at, completed_at, catalog_count,
                       fact_count, status, sha256) VALUES ('export', ?, ?, ?, ?, ?, 'completed', ?)""",
                (str(target), utc_now(), utc_now(), len(catalog),
                 sum(len(item["facts"]) for item in records), digest),
            )
        return {"run_id": int(cursor.lastrowid or 0), "path": str(target),
                "sha256": digest, "catalog": len(catalog), "records": len(records)}

    def import_snapshot(self, source: str | Path) -> dict[str, Any]:
        path = Path(source).expanduser().resolve()
        payload = self._read_snapshot(path)
        sources = {item["slug"]: item for item in payload.get("sources", [])}
        catalog_count = 0
        fact_count = 0
        with self.connect() as connection:
            repository = KnowledgeRepository(connection)
            source_ids: dict[str, int] = {}
            for slug, item in sources.items():
                source_ids[slug] = repository.upsert_source(
                    slug, item.get("name", slug), item.get("homepage_url", ""),
                    item.get("license_name", ""), item.get("license_url", ""),
                    item.get("notes", ""),
                )
            for item in payload.get("catalog", []):
                if not _valid_titleid(str(item.get("titleid", ""))):
                    continue
                columns = (
                    "titleid", "name", "hb_titleid", "title_type", "link_enabled",
                    "covers_count", "updates_count", "media_id_count", "user_count",
                    "newest_content", "source_url", "raw_json", "fetched_at",
                )
                connection.execute(
                    f"""INSERT INTO xboxunity_title_catalog({','.join(columns)})
                        VALUES ({','.join('?' for _ in columns)})
                        ON CONFLICT(titleid) DO UPDATE SET
                        name=excluded.name, title_type=excluded.title_type,
                        covers_count=excluded.covers_count, updates_count=excluded.updates_count,
                        media_id_count=excluded.media_id_count, newest_content=excluded.newest_content,
                        raw_json=excluded.raw_json, fetched_at=excluded.fetched_at""",
                    tuple(item.get(column) for column in columns),
                )
                catalog_count += 1
            for item in payload.get("records", []):
                source_slug = str(item.get("source", "snapshot"))
                source_id = source_ids.get(source_slug)
                if source_id is None:
                    source_id = repository.upsert_source(
                        source_slug, source_slug, notes="Imported metadata snapshot"
                    )
                    source_ids[source_slug] = source_id
                record = EntityRecord(
                    entity_type=str(item.get("entity_type", "reference")),
                    canonical_name=str(item.get("canonical_name", "")).strip(),
                    identifiers=tuple(
                        Identifier(str(value["kind"]), str(value["value"]),
                                   float(value.get("confidence", 1.0)))
                        for value in item.get("identifiers", [])
                        if value.get("kind") and value.get("value")
                    ),
                    names=tuple(str(value) for value in item.get("names", []) if value),
                    facts=tuple(
                        Fact(str(value["property"]), str(value["value"]),
                             str(value.get("normalized_value", "")),
                             float(value.get("confidence", 1.0)),
                             str(value.get("source_url", "")),
                             str(value.get("source_title", "")))
                        for value in item.get("facts", [])
                        if value.get("property") and value.get("value")
                    ),
                )
                if record.canonical_name:
                    repository.upsert_entity_record(record, source_id)
                    fact_count += len(record.facts)
        digest = sha256_file(path)
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO metadata_snapshot_runs(
                       operation, snapshot_path, created_at, completed_at, catalog_count,
                       fact_count, status, sha256) VALUES ('import', ?, ?, ?, ?, ?, 'completed', ?)""",
                (str(path), utc_now(), utc_now(), catalog_count, fact_count, digest),
            )
        return {"run_id": int(cursor.lastrowid or 0), "catalog": catalog_count,
                "facts": fact_count, "sha256": digest}

    def _read_snapshot(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise FileNotFoundError(path)
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) != 1 or infos[0].filename != "metadata.json":
                raise ValueError("Metadata snapshot must contain only metadata.json")
            if infos[0].file_size > MAX_SNAPSHOT_EXPANDED:
                raise ValueError("Metadata snapshot exceeds the expanded-size limit")
            payload = json.loads(archive.read(infos[0]).decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != SNAPSHOT_SCHEMA:
            raise ValueError("Unsupported metadata snapshot schema")
        if payload.get("contains_personal_data") is not False:
            raise ValueError("Metadata snapshot does not declare a safe data boundary")
        return payload

    @staticmethod
    def _export_records(connection: sqlite3.Connection) -> list[dict[str, Any]]:
        entities = connection.execute(
            "SELECT id, entity_type, canonical_name FROM knowledge_entities ORDER BY id"
        ).fetchall()
        results: list[dict[str, Any]] = []
        for entity in entities:
            facts = connection.execute(
                """SELECT f.*, s.slug, c.source_url, c.source_title
                   FROM knowledge_facts f JOIN knowledge_sources s ON s.id=f.source_id
                   LEFT JOIN fact_citations c ON c.fact_id=f.id WHERE f.entity_id=?
                   ORDER BY s.slug, f.property""", (entity["id"],)
            ).fetchall()
            by_source: dict[str, list[sqlite3.Row]] = defaultdict(list)
            for fact in facts:
                by_source[fact["slug"]].append(fact)
            names = [row[0] for row in connection.execute(
                "SELECT name FROM entity_names WHERE entity_id=?", (entity["id"],)
            ).fetchall()]
            for slug, source_facts in by_source.items():
                identifiers = [dict(row) for row in connection.execute(
                    """SELECT identifier_type kind, identifier_value value, confidence
                       FROM entity_identifiers i JOIN knowledge_sources s ON s.id=i.source_id
                       WHERE entity_id=? AND s.slug=?""", (entity["id"], slug)
                ).fetchall()]
                results.append({
                    "entity_type": entity["entity_type"],
                    "canonical_name": entity["canonical_name"],
                    "source": slug,
                    "names": names,
                    "identifiers": identifiers,
                    "facts": [{
                        "property": row["property"], "value": row["value"],
                        "normalized_value": row["normalized_value"],
                        "confidence": row["confidence"], "source_url": row["source_url"] or "",
                        "source_title": row["source_title"] or "",
                    } for row in source_facts],
                })
        return results


class LibraryIntelligenceService(RoadmapRepository):
    def audit(self) -> dict[str, Any]:
        issues: list[dict[str, str]] = []
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT t.titleid, t.name, t.publisher,
                          COUNT(DISTINCT c.id) covers, COUNT(DISTINCT u.id) updates,
                          COALESCE(MAX(x.covers_count), 0) available_covers,
                          COALESCE(MAX(x.updates_count), 0) available_updates,
                          COALESCE(MAX(x.media_id_count), 0) media_ids
                   FROM titleids t
                   LEFT JOIN covers c ON c.titleid=t.titleid AND c.status='downloaded'
                   LEFT JOIN title_updates u ON u.titleid=t.titleid AND u.status='downloaded'
                   LEFT JOIN xboxunity_title_catalog x ON x.titleid=t.titleid
                   GROUP BY t.titleid ORDER BY t.name COLLATE NOCASE"""
            ).fetchall()
            for row in rows:
                title = row["name"] or row["titleid"]
                if is_unknown(row["name"]) or str(row["name"] or "").upper() == row["titleid"]:
                    issues.append(_issue(row["titleid"], title, "unknown-name", "Game name is unknown"))
                if is_unknown(row["publisher"]):
                    issues.append(_issue(row["titleid"], title, "unknown-publisher", "Publisher is unknown"))
                if row["available_covers"] and not row["covers"]:
                    issues.append(_issue(row["titleid"], title, "missing-cover", "Cover is available but not archived"))
                if row["available_updates"] and not row["updates"]:
                    issues.append(_issue(row["titleid"], title, "missing-update", "Title updates are available but not archived"))
                if row["available_updates"] and not row["media_ids"]:
                    issues.append(_issue(row["titleid"], title, "unknown-mediaid", "Update compatibility needs a MediaID"))
            summary = {
                "titles": len(rows), "issues": len(issues),
                "unknown_names": sum(item["kind"] == "unknown-name" for item in issues),
                "unknown_publishers": sum(item["kind"] == "unknown-publisher" for item in issues),
                "missing_covers": sum(item["kind"] == "missing-cover" for item in issues),
                "missing_updates": sum(item["kind"] == "missing-update" for item in issues),
            }
            cursor = connection.execute(
                "INSERT INTO library_intelligence_runs(created_at,title_count,issue_count,summary_json) "
                "VALUES (?,?,?,?)", (utc_now(), len(rows), len(issues), json.dumps(summary)),
            )
        return {"run_id": int(cursor.lastrowid or 0), "summary": summary, "issues": issues}


class PreservationReportService(RoadmapRepository):
    def export_html(self, destination: str | Path) -> dict[str, Any]:
        target = Path(destination).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        audit = LibraryIntelligenceService(self.db_path).audit()
        with self.connect() as connection:
            sources = [dict(row) for row in connection.execute(
                """SELECT s.name, s.license_name, COUNT(DISTINCT d.id) documents,
                          COUNT(DISTINCT f.id) facts
                   FROM knowledge_sources s LEFT JOIN source_documents d ON d.source_id=s.id
                   LEFT JOIN knowledge_facts f ON f.source_id=s.id GROUP BY s.id ORDER BY s.name"""
            ).fetchall()]
        issue_rows = "".join(
            f"<tr><td>{html.escape(item['titleid'])}</td><td>{html.escape(item['title'])}</td>"
            f"<td>{html.escape(item['kind'])}</td><td>{html.escape(item['message'])}</td></tr>"
            for item in audit["issues"]
        )
        source_rows = "".join(
            f"<tr><td>{html.escape(row['name'])}</td><td>{html.escape(row['license_name'] or 'Unspecified')}</td>"
            f"<td>{row['documents']}</td><td>{row['facts']}</td></tr>" for row in sources
        )
        summary = audit["summary"]
        target.write_text(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>UnityScraper Preservation Report</title><style>
body{{font:14px Segoe UI,Arial;background:#1e1e1e;color:#eee;margin:30px}}h1,h2{{font-weight:400}}
.bar{{height:4px;background:#007acc}}.metrics{{display:flex;gap:28px;margin:22px 0}}
.metric b{{display:block;font-size:26px;color:#4fc1ff}}table{{border-collapse:collapse;width:100%;margin-bottom:28px}}
th,td{{border:1px solid #3f3f46;padding:7px;text-align:left}}th{{background:#2d2d30}}
</style></head><body><h1>Xbox 360 Preservation Report</h1><div class="bar"></div>
<p>Generated {html.escape(utc_now())}. Personal profile identifiers and filesystem paths are excluded.</p>
<div class="metrics"><span class="metric"><b>{summary['titles']}</b>Titles</span>
<span class="metric"><b>{summary['issues']}</b>Items needing attention</span>
<span class="metric"><b>{len(sources)}</b>Knowledge sources</span></div>
<h2>Library attention</h2><table><thead><tr><th>TitleID</th><th>Game</th><th>Type</th><th>Details</th></tr></thead>
<tbody>{issue_rows}</tbody></table><h2>Source provenance</h2><table><thead><tr>
<th>Source</th><th>License</th><th>Documents</th><th>Facts</th></tr></thead><tbody>{source_rows}</tbody></table>
</body></html>""", encoding="utf-8")
        digest = sha256_file(target)
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO preservation_report_runs(destination,created_at,report_format,status,sha256) "
                "VALUES (?,?,'html','completed',?)", (str(target), utc_now(), digest),
            )
        return {"run_id": int(cursor.lastrowid or 0), "path": str(target), "sha256": digest}


class CorrectionPackageService(RoadmapRepository):
    def export(self, destination: str | Path) -> dict[str, Any]:
        target = Path(destination).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute(
                """SELECT entity_type, identifier_type, identifier_value, property, value, notes,
                          updated_at FROM metadata_overrides ORDER BY updated_at"""
            ).fetchall()]
        payload = {"schema": 1, "created_at": utc_now(), "contains_personal_data": False,
                   "corrections": rows}
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        digest = sha256_file(target)
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO correction_packages(operation,package_path,created_at,correction_count,status,sha256) "
                "VALUES ('export',?,?,?,'completed',?)", (str(target), utc_now(), len(rows), digest),
            )
        return {"run_id": int(cursor.lastrowid or 0), "path": str(target),
                "corrections": len(rows), "sha256": digest}


class HardwareInventoryService(RoadmapRepository):
    FIELDS = ("motherboard", "dvd_drive", "nand_type", "dashboard_version", "console_type")

    def save(self, label: str, **values: str) -> dict[str, Any]:
        clean_label = label.strip()
        if not clean_label:
            raise ValueError("A hardware record label is required")
        unknown = set(values) - set(self.FIELDS) - {"notes"}
        if unknown:
            raise ValueError(f"Unsupported hardware fields: {', '.join(sorted(unknown))}")
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO hardware_inventory_records(
                       label,motherboard,dvd_drive,nand_type,dashboard_version,console_type,
                       notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (clean_label, *(str(values.get(name, "")).strip() for name in self.FIELDS),
                 str(values.get("notes", "")).strip(), now, now),
            )
        return {"id": int(cursor.lastrowid or 0), "label": clean_label}

    def list(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM hardware_inventory_records ORDER BY updated_at DESC"
            ).fetchall()]


def _valid_titleid(value: str) -> bool:
    return len(value) == 8 and all(character in "0123456789ABCDEFabcdef" for character in value)


def _issue(titleid: str, title: str, kind: str, message: str) -> dict[str, str]:
    return {"titleid": titleid, "title": title, "kind": kind, "message": message}
