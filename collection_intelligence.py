"""Collection discovery, compatibility, preservation, and reporting services."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
import shutil
import sys
import zlib
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app_paths import DATABASE_PATH, EXPORTS_DIR, ensure_app_dirs
from backup_manager import BackupItem, ScanResult, scan_local_target
from knowledge_base import KnowledgeRepository


HEX8_RE = re.compile(r"^[0-9A-Fa-f]{8}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class UpdateCompatibility:
    title_id: str
    media_id: str
    status: str
    newest_version: str = ""
    update_count: int = 0
    reason: str = ""


@dataclass(frozen=True)
class CollectionIssue:
    severity: str
    code: str
    target: str
    message: str
    suggested_action: str
    destructive: bool = False


@dataclass
class CollectionAnalysis:
    result: ScanResult
    compatibility: dict[str, UpdateCompatibility] = field(default_factory=dict)
    issues: list[CollectionIssue] = field(default_factory=list)
    health_score: int = 100
    snapshot_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "schema": 1,
            "snapshot_id": self.snapshot_id,
            "health_score": self.health_score,
            "scan": self.result.to_dict(),
            "compatibility": {key: asdict(value) for key, value in self.compatibility.items()},
            "issues": [asdict(issue) for issue in self.issues],
        }


def discover_storage_roots() -> list[Path]:
    """Return mounted roots that are plausible console, USB, or archive targets."""
    candidates: list[Path] = []
    if os.name == "nt":
        import ctypes

        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for index in range(26):
            if mask & (1 << index):
                candidates.append(Path(f"{chr(65 + index)}:/"))
    elif sys.platform == "darwin":
        candidates.extend(_children(Path("/Volumes")))
    else:
        user = os.environ.get("USER", "")
        candidates.extend(_children(Path("/media") / user))
        candidates.extend(_children(Path("/run/media") / user))
        candidates.extend(_children(Path("/mnt")))

    scored: list[tuple[int, Path]] = []
    for path in dict.fromkeys(candidates):
        if not path.is_dir():
            continue
        score = sum(
            int((path / relative).exists())
            for relative in ("Content", "Games", "Xbox360", "Aurora", "Data")
        )
        scored.append((score, path))
    return [path for _, path in sorted(scored, key=lambda value: (-value[0], str(value[1])))]


def _children(path: Path) -> list[Path]:
    try:
        return [child for child in path.iterdir() if child.is_dir()]
    except OSError:
        return []


def import_aurora_database(path: str | Path) -> ScanResult:
    """Read a user-selected Aurora SQLite database in immutable, read-only mode."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    uri = f"{source.as_uri()}?mode=ro&immutable=1"
    items: list[BackupItem] = []
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            columns = {
                row[1].casefold(): row[1]
                for row in connection.execute(f"PRAGMA table_info({quoted})")
            }
            title_col = _column(columns, "titleid", "title_id", "title id")
            name_col = _column(columns, "name", "title", "displayname", "display_name")
            if not title_col or not name_col:
                continue
            media_col = _column(columns, "mediaid", "media_id")
            path_col = _column(columns, "path", "file_path", "contentpath", "content_path")
            selected = [title_col, name_col]
            selected.extend(value for value in (media_col, path_col) if value)
            column_sql = ", ".join('"' + value.replace('"', '""') + '"' for value in selected)
            for row in connection.execute(f"SELECT {column_sql} FROM {quoted}"):
                title_id = str(row[title_col] or "").strip().upper().replace("0X", "")
                if title_id and not HEX8_RE.fullmatch(title_id):
                    continue
                items.append(
                    BackupItem(
                        path=Path(str(row[path_col] or "")) if path_col else source,
                        title_id=title_id,
                        name=str(row[name_col] or title_id or "Unknown"),
                        format="Aurora database",
                        media_id=str(row[media_col] or "").strip().upper() if media_col else "",
                        size=0,
                    )
                )
            if items:
                break
    warnings = [] if items else ["No compatible Aurora title table was found"]
    return ScanResult(source, items, warnings, utc_now())


def _column(columns: dict[str, str], *aliases: str) -> str | None:
    return next((columns[alias] for alias in aliases if alias in columns), None)


class CollectionIntelligenceService:
    def __init__(self, db_path: str | Path = DATABASE_PATH) -> None:
        self.db_path = Path(db_path)
        if self.db_path == DATABASE_PATH:
            ensure_app_dirs()
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Use the application's complete initializer so CLI-only collection
        # workflows also have the legacy library and normalized knowledge tables.
        from database import DatabaseManager

        DatabaseManager(str(self.db_path))

    @contextmanager
    def _connect(self):
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

    def analyze(self, root: str | Path, title_lookup=None) -> CollectionAnalysis:
        return self.analyze_result(scan_local_target(root, title_lookup), "local")

    def analyze_aurora(self, path: str | Path) -> CollectionAnalysis:
        return self.analyze_result(import_aurora_database(path), "aurora")

    def analyze_result(self, result: ScanResult, source_kind: str) -> CollectionAnalysis:
        compatibility: dict[str, UpdateCompatibility] = {}
        issues: list[CollectionIssue] = []
        with self._connect() as connection:
            for item in result.items:
                compatibility[str(item.path)] = self._compatibility(connection, item)
                if item.status != "ready":
                    issues.append(
                        CollectionIssue(
                            "warning",
                            "incomplete",
                            str(item.path),
                            f"{item.name} is incomplete",
                            "Review the item and restore its missing base content.",
                        )
                    )
                if not item.title_id:
                    issues.append(
                        CollectionIssue(
                            "warning",
                            "unknown-titleid",
                            str(item.path),
                            f"{item.name} has no readable TitleID",
                            "Inspect its executable or add a metadata override.",
                        )
                    )
                if item.title_id and not item.media_id:
                    issues.append(
                        CollectionIssue(
                            "info",
                            "unknown-mediaid",
                            str(item.path),
                            f"{item.name} has no MediaID",
                            "Scan an executable or package before choosing a title update.",
                        )
                    )
                for note in item.notes:
                    if "missing" in note.casefold() or "could not" in note.casefold():
                        issues.append(
                            CollectionIssue(
                                "warning", "scan-note", str(item.path), note, "Verify this item."
                            )
                        )

            groups: dict[tuple[str, str], list[BackupItem]] = {}
            for item in result.items:
                if item.title_id:
                    groups.setdefault((item.title_id, item.media_id), []).append(item)
            for key, matches in groups.items():
                if len(matches) > 1:
                    issues.append(
                        CollectionIssue(
                            "info",
                            "duplicate-release",
                            key[0],
                            f"{len(matches)} copies share TitleID {key[0]} and "
                            f"MediaID {key[1] or 'unknown'}",
                            "Hash the copies and keep intentional regional or revision variants.",
                        )
                    )
                expected = max((item.disc_count for item in matches), default=0)
                present = {item.disc_number for item in matches if item.disc_number}
                for item in matches:
                    for note in item.notes:
                        disc_match = re.search(r"Discs found: ([0-9, ]+) of ([0-9]+)", note)
                        if disc_match:
                            present.update(
                                int(value.strip())
                                for value in disc_match.group(1).split(",")
                                if value.strip()
                            )
                            expected = max(expected, int(disc_match.group(2)))
                missing = sorted(set(range(1, expected + 1)) - present) if expected else []
                if missing:
                    issues.append(
                        CollectionIssue(
                            "warning",
                            "missing-disc",
                            key[0],
                            f"Missing disc(s) {', '.join(map(str, missing))} of {expected}",
                            "Locate or restore the missing disc backup.",
                        )
                    )
            score = max(
                0,
                100
                - sum(
                    {"error": 15, "warning": 7, "info": 2}.get(issue.severity, 1)
                    for issue in issues
                ),
            )
            analysis = CollectionAnalysis(result, compatibility, issues, score)
            analysis.snapshot_id = self._save_snapshot(connection, analysis, source_kind)
            connection.commit()
            return analysis

    @staticmethod
    def _compatibility(
        connection: sqlite3.Connection, item: BackupItem
    ) -> UpdateCompatibility:
        if not item.title_id:
            return UpdateCompatibility("", item.media_id, "unknown", reason="TitleID is unknown")
        rows = connection.execute(
            "SELECT media_id, version FROM title_updates WHERE titleid=? ORDER BY version DESC",
            (item.title_id,),
        ).fetchall()
        if not rows:
            return UpdateCompatibility(
                item.title_id, item.media_id, "none", reason="No title updates are catalogued"
            )
        exact = [
            row
            for row in rows
            if item.media_id and (row["media_id"] or "").upper() == item.media_id
        ]
        if exact:
            return UpdateCompatibility(
                item.title_id, item.media_id, "compatible", exact[0]["version"] or "", len(exact)
            )
        if not item.media_id:
            return UpdateCompatibility(
                item.title_id,
                "",
                "media-id-required",
                rows[0]["version"] or "",
                len(rows),
                "Updates exist, but exact compatibility requires a MediaID",
            )
        return UpdateCompatibility(
            item.title_id,
            item.media_id,
            "incompatible",
            rows[0]["version"] or "",
            len(rows),
            "No catalogued update matches this MediaID",
        )

    def _save_snapshot(
        self, connection: sqlite3.Connection, analysis: CollectionAnalysis, source_kind: str
    ) -> int:
        result = analysis.result
        cursor = connection.execute(
            """
            INSERT INTO collection_snapshots
                (source_kind, source_location, label, started_at, completed_at,
                 item_count, total_size, health_score, status, warnings_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?)
            """,
            (
                source_kind,
                str(result.root),
                result.root.name,
                result.scanned_at,
                utc_now(),
                len(result.items),
                result.total_size,
                analysis.health_score,
                json.dumps(result.warnings),
            ),
        )
        if cursor.lastrowid is None:
            raise sqlite3.DatabaseError("Collection snapshot did not return an ID")
        snapshot_id = int(cursor.lastrowid)
        for item in result.items:
            match = analysis.compatibility[str(item.path)]
            connection.execute(
                """
                INSERT INTO collection_items
                    (snapshot_id, titleid, media_id, name, format, content_type,
                     path, size, disc_number, disc_count, status, compatibility, notes_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    item.title_id,
                    item.media_id,
                    item.name,
                    item.format,
                    item.content_type,
                    str(item.path),
                    item.size,
                    item.disc_number,
                    item.disc_count,
                    item.status,
                    match.status,
                    json.dumps(item.notes),
                ),
            )
        return snapshot_id

    def create_repair_plan(self, analysis: CollectionAnalysis) -> int:
        """Persist a preview only; no filesystem operation is executed."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO repair_plans(snapshot_id, created_at, status, summary_json)
                VALUES (?, ?, 'preview', ?)
                """,
                (
                    analysis.snapshot_id,
                    utc_now(),
                    json.dumps({"health_score": analysis.health_score, "issues": len(analysis.issues)}),
                ),
            )
            plan_id = int(cursor.lastrowid)
            for issue in analysis.issues:
                connection.execute(
                    """
                    INSERT INTO repair_actions
                        (plan_id, action_type, target, reason, destructive, details_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan_id,
                        issue.code,
                        issue.target,
                        issue.message,
                        int(issue.destructive),
                        json.dumps(asdict(issue)),
                    ),
                )
            connection.commit()
            return plan_id

    def set_override(
        self,
        identifier_value: str,
        property_name: str,
        value: str,
        *,
        identifier_type: str = "titleid",
        entity_type: str = "game",
        notes: str = "",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO metadata_overrides
                    (entity_type, identifier_type, identifier_value, property,
                     value, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_type, identifier_type, identifier_value, property)
                DO UPDATE SET value=excluded.value, notes=excluded.notes,
                              updated_at=excluded.updated_at
                """,
                (
                    entity_type,
                    identifier_type,
                    identifier_value.upper(),
                    property_name,
                    value,
                    notes,
                    utc_now(),
                ),
            )
            connection.commit()

    def list_overrides(self, identifier_value: str | None = None) -> list[dict]:
        with self._connect() as connection:
            if identifier_value:
                rows = connection.execute(
                    """
                    SELECT * FROM metadata_overrides
                    WHERE identifier_value=? ORDER BY property
                    """,
                    (identifier_value.upper(),),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM metadata_overrides ORDER BY updated_at DESC"
                ).fetchall()
        return [dict(row) for row in rows]

    def hash_and_match(self, path: str | Path) -> list[dict]:
        source = Path(path).resolve()
        stat = source.stat()
        crc = 0
        hashes = (hashlib.md5(), hashlib.sha1(), hashlib.sha256())
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                crc = zlib.crc32(chunk, crc)
                for digest in hashes:
                    digest.update(chunk)
        values = {
            "crc32": f"{crc & 0xFFFFFFFF:08X}",
            "md5": hashes[0].hexdigest().upper(),
            "sha1": hashes[1].hexdigest().upper(),
            "sha256": hashes[2].hexdigest().upper(),
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO local_file_hashes
                    (path, size, modified_ns, crc32, md5, sha1, sha256, calculated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path, size, modified_ns) DO UPDATE SET
                    crc32=excluded.crc32, md5=excluded.md5, sha1=excluded.sha1,
                    sha256=excluded.sha256, calculated_at=excluded.calculated_at
                """,
                (
                    str(source),
                    stat.st_size,
                    stat.st_mtime_ns,
                    values["crc32"],
                    values["md5"],
                    values["sha1"],
                    values["sha256"],
                    utc_now(),
                ),
            )
            file_hash_id = int(
                connection.execute(
                    "SELECT id FROM local_file_hashes WHERE path=? AND size=? AND modified_ns=?",
                    (str(source), stat.st_size, stat.st_mtime_ns),
                ).fetchone()[0]
            )
            matches: list[dict] = []
            for kind, value in values.items():
                rows = connection.execute(
                    """
                    SELECT e.id, e.entity_type, e.canonical_name, i.identifier_type
                    FROM entity_identifiers i JOIN knowledge_entities e ON e.id=i.entity_id
                    WHERE i.identifier_type=? AND UPPER(i.normalized_value)=?
                    """,
                    (kind, value),
                ).fetchall()
                for row in rows:
                    match = dict(row)
                    match["matched_by"] = kind
                    matches.append(match)
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO preservation_matches
                            (file_hash_id, entity_id, identifier_type,
                             identifier_value, matched_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (file_hash_id, row["id"], kind, value, utc_now()),
                    )
            connection.commit()
        return matches

    def export_manifest(
        self, analysis: CollectionAnalysis, destination: str | Path | None = None
    ) -> Path:
        ensure_app_dirs()
        target = Path(destination) if destination else EXPORTS_DIR / "collection-manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = analysis.to_dict()
        payload.update({"generated_at": utc_now(), "application": "UnityScraper"})
        payload["metadata_overrides"] = self.list_overrides()
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return target

    def export_aurora_layout(
        self,
        analysis: CollectionAnalysis,
        destination: str | Path,
        artwork_directory: str | Path | None = None,
    ) -> Path:
        """Export an explicit Aurora-friendly Games and Assets layout."""
        target = Path(destination).expanduser().resolve()
        games = target / "Games"
        assets = target / "Assets"
        games.mkdir(parents=True, exist_ok=True)
        if artwork_directory:
            assets.mkdir(parents=True, exist_ok=True)
        exported: list[dict] = []
        for item in analysis.result.items:
            safe_name = re.sub(r'[<>:"/\\|?*]+', "_", item.name).strip(" .") or "Unknown"
            folder_name = f"{safe_name} [{item.title_id}]" if item.title_id else safe_name
            output = games / folder_name
            if output.exists():
                raise FileExistsError(f"Aurora export destination exists: {output}")
            if item.path.is_dir() and target.is_relative_to(item.path.resolve()):
                raise ValueError("Aurora export destination cannot be inside its source")
            if item.path.is_dir():
                shutil.copytree(item.path, output)
            elif item.path.is_file():
                output.mkdir(parents=True)
                shutil.copy2(item.path, output / item.path.name)
            else:
                continue
            artwork_files = []
            if artwork_directory and item.title_id:
                source_art = Path(artwork_directory)
                for extension in (".png", ".jpg", ".jpeg"):
                    candidate = source_art / f"{item.title_id}{extension}"
                    if candidate.is_file():
                        artwork_target = assets / item.title_id
                        artwork_target.mkdir(parents=True, exist_ok=True)
                        copied = artwork_target / candidate.name
                        shutil.copy2(candidate, copied)
                        artwork_files.append(str(copied.relative_to(target)))
            exported.append(
                {
                    "titleid": item.title_id,
                    "media_id": item.media_id,
                    "source": str(item.path),
                    "destination": str(output.relative_to(target)),
                    "artwork": artwork_files,
                }
            )
        (target / "unityscraper-aurora-manifest.json").write_text(
            json.dumps({"schema": 1, "generated_at": utc_now(), "items": exported}, indent=2),
            encoding="utf-8",
        )
        return target

    def export_html(
        self, analysis: CollectionAnalysis, destination: str | Path | None = None
    ) -> Path:
        ensure_app_dirs()
        target = Path(destination) if destination else EXPORTS_DIR / "collection-report.html"
        rows = []
        for item in analysis.result.items:
            compatibility = analysis.compatibility[str(item.path)]
            rows.append(
                "<tr>"
                f"<td>{html.escape(item.name)}</td><td>{html.escape(item.title_id)}</td>"
                f"<td>{html.escape(item.media_id)}</td><td>{html.escape(item.format)}</td>"
                f"<td>{html.escape(compatibility.status)}</td><td>{item.size}</td></tr>"
            )
        document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>UnityScraper Collection</title>
<style>body{{font:14px Segoe UI,system-ui;background:#1e1e1e;color:#f1f1f1;margin:2rem}}
h1{{color:#4fc1ff;font-weight:400}}table{{border-collapse:collapse;width:100%}}th,td{{padding:.55rem;
border-bottom:1px solid #3f3f46;text-align:left}}th{{background:#2d2d30}}.score{{font-size:2rem}}</style></head>
<body><h1>Xbox 360 Collection Report</h1>
<p class="score">Health score: {analysis.health_score}/100</p>
<p>Generated {html.escape(utc_now())}; source {html.escape(str(analysis.result.root))}</p>
<table><thead><tr><th>Game</th><th>TitleID</th><th>MediaID</th><th>Format</th>
<th>Title update</th><th>Bytes</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
</body></html>"""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document, encoding="utf-8")
        return target

    def export_provenance(self, destination: str | Path) -> Path:
        target = Path(destination)
        with self._connect() as connection:
            KnowledgeRepository(connection).ensure_schema()
            rows = connection.execute(
                """
                SELECT e.entity_type, e.canonical_name, f.property, f.value,
                       f.confidence, s.name source, c.source_url, c.source_title
                FROM knowledge_facts f
                JOIN knowledge_entities e ON e.id=f.entity_id
                JOIN knowledge_sources s ON s.id=f.source_id
                LEFT JOIN fact_citations c ON c.fact_id=f.id
                ORDER BY e.entity_type, e.canonical_name, f.property
                """
            ).fetchall()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"generated_at": utc_now(), "facts": [dict(row) for row in rows]}, indent=2),
            encoding="utf-8",
        )
        return target
