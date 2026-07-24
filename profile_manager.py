"""Read-first Xbox 360 profile and save inventory, snapshots, and restore."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Iterable, Literal

from app_paths import DATABASE_PATH, PROFILE_BACKUPS_DIR
from backup_manager import InvalidPackageError, StfsPackage, inspect_stfs
from database_migrations import ensure_application_schema


HEX8_RE = re.compile(r"^[0-9A-Fa-f]{8}$")
PROFILE_ID_RE = re.compile(r"^[0-9A-Fa-f]{16}$")
ZERO_PROFILE_ID = "0000000000000000"
PROFILE_TITLE_ID = "FFFE07D1"
SAVE_CONTENT_DIRECTORY = "00000001"
PROFILE_CONTENT_DIRECTORY = "00010000"
COPY_CHUNK = 1024 * 1024


class ProfileSaveError(RuntimeError):
    """Base error for profile and save operations."""


class ProfileSaveConflict(ProfileSaveError):
    """Raised when a restore would replace a different existing file."""


class _ClosingConnection(sqlite3.Connection):
    """Commit or roll back, then release the database file handle."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


@dataclass
class ProfileInfo:
    profile_id: str
    gamertag: str
    source_path: Path
    package_path: Path | None
    package_sha256: str
    console_id: str
    device_id: str
    profile_kind: str
    package_status: str
    save_count: int = 0
    total_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["source_path"] = str(self.source_path)
        result["package_path"] = str(self.package_path or "")
        return result


@dataclass
class SaveInfo:
    profile_id: str
    title_id: str
    name: str
    source_path: Path
    package_magic: str
    content_type: int
    save_game_id: str
    embedded_profile_id: str
    console_id: str
    device_id: str
    size: int
    modified_at: str
    sha256: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["source_path"] = str(self.source_path)
        return result


@dataclass
class ProfileScanResult:
    root: Path
    profiles: list[ProfileInfo]
    saves: list[SaveInfo]
    warnings: list[str]
    scanned_at: str


@dataclass(frozen=True)
class RestoreResult:
    snapshot_id: int
    destination: Path
    restored: int
    skipped: int
    conflicts: int


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mask_identifier(value: str, visible: int = 4) -> str:
    """Mask a personal identifier while keeping it distinguishable."""
    normalized = value.strip()
    if not normalized:
        return "Unknown"
    if len(normalized) <= visible:
        return "*" * len(normalized)
    return "*" * (len(normalized) - visible) + normalized[-visible:]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(COPY_CHUNK):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _last_row_id(cursor: sqlite3.Cursor) -> int:
    if cursor.lastrowid is None:
        raise ProfileSaveError("Database did not return a record identifier.")
    return int(cursor.lastrowid)


def _child_named(parent: Path, name: str) -> Path | None:
    if not parent.is_dir():
        return None
    expected = name.casefold()
    try:
        return next(child for child in parent.iterdir() if child.name.casefold() == expected)
    except (OSError, StopIteration):
        return None


def find_content_root(path: str | Path) -> Path:
    """Locate an extracted Xbox 360 Content directory."""
    root = Path(path).expanduser().resolve()
    if root.is_dir() and root.name.casefold() == "content":
        return root
    direct = _child_named(root, "Content")
    if direct:
        return direct
    hdd = _child_named(root, "Hdd1")
    nested = _child_named(hdd, "Content") if hdd else None
    if nested:
        return nested
    raise ProfileSaveError(
        "Choose an Xbox 360 Content directory or a folder containing Content."
    )


def _candidate_gamertag(package: StfsPackage | None, profile_id: str) -> str:
    if package is None:
        return ""
    generic = {
        "",
        profile_id.casefold(),
        "xbox 360 dashboard",
        "gamer profile",
        "profile",
    }
    for candidate in (package.display_name, package.title_name):
        cleaned = candidate.strip()
        if cleaned.casefold() not in generic:
            return cleaned
    return ""


class ProfileSaveScanner:
    """Scan extracted profile folders without changing source content."""

    def __init__(self, title_resolver: Callable[[str], str] | None = None) -> None:
        self.title_resolver = title_resolver or (lambda _title_id: "")

    def scan(self, path: str | Path) -> ProfileScanResult:
        content_root = find_content_root(path)
        profiles: list[ProfileInfo] = []
        saves: list[SaveInfo] = []
        warnings: list[str] = []

        for profile_dir in sorted(content_root.iterdir(), key=lambda item: item.name):
            profile_id = profile_dir.name.upper()
            if (
                not profile_dir.is_dir()
                or not PROFILE_ID_RE.fullmatch(profile_id)
                or profile_id == ZERO_PROFILE_ID
            ):
                continue
            profile, profile_warnings = self._scan_profile(profile_dir, profile_id)
            profile_saves, save_warnings = self._scan_saves(profile_dir, profile_id)
            profile.save_count = len(profile_saves)
            profile.total_size = sum(item.size for item in profile_saves)
            profiles.append(profile)
            saves.extend(profile_saves)
            warnings.extend(profile_warnings)
            warnings.extend(save_warnings)

        duplicate_hashes = {
            digest
            for digest in (item.sha256 for item in saves)
            if digest and sum(save.sha256 == digest for save in saves) > 1
        }
        for save in saves:
            if save.sha256 in duplicate_hashes and save.status == "header-valid":
                save.status = "duplicate"

        return ProfileScanResult(
            content_root,
            profiles,
            saves,
            warnings,
            utc_now(),
        )

    def _scan_profile(
        self, profile_dir: Path, profile_id: str
    ) -> tuple[ProfileInfo, list[str]]:
        warnings: list[str] = []
        package_path: Path | None = None
        package: StfsPackage | None = None
        dashboard = _child_named(profile_dir, PROFILE_TITLE_ID)
        package_dir = _child_named(dashboard, PROFILE_CONTENT_DIRECTORY) if dashboard else None
        if package_dir:
            try:
                package_path = next(path for path in package_dir.rglob("*") if path.is_file())
            except (OSError, StopIteration):
                package_path = None
        package_sha256 = ""
        package_status = "missing"
        if package_path:
            try:
                package = inspect_stfs(package_path)
                package_sha256 = sha256_file(package_path)
                package_status = "header-valid"
                if package.content_type != 0x00010000:
                    package_status = "unexpected-content-type"
                if package.profile_id not in {"", ZERO_PROFILE_ID, profile_id}:
                    package_status = "profile-mismatch"
                    warnings.append(
                        f"{mask_identifier(profile_id)} profile package identifies "
                        f"{mask_identifier(package.profile_id)}."
                    )
            except (InvalidPackageError, OSError) as exc:
                package_status = "invalid"
                warnings.append(f"{mask_identifier(profile_id)} profile: {exc}")

        return (
            ProfileInfo(
                profile_id=profile_id,
                gamertag=_candidate_gamertag(package, profile_id),
                source_path=profile_dir,
                package_path=package_path,
                package_sha256=package_sha256,
                console_id=package.console_id if package else "",
                device_id=package.device_id if package else "",
                profile_kind="profile-package" if package else "folder-only",
                package_status=package_status,
            ),
            warnings,
        )

    def _scan_saves(
        self, profile_dir: Path, profile_id: str
    ) -> tuple[list[SaveInfo], list[str]]:
        saves: list[SaveInfo] = []
        warnings: list[str] = []
        for title_dir in sorted(profile_dir.iterdir(), key=lambda item: item.name):
            title_id = title_dir.name.upper()
            if (
                not title_dir.is_dir()
                or title_id == PROFILE_TITLE_ID
                or not HEX8_RE.fullmatch(title_id)
            ):
                continue
            save_dir = _child_named(title_dir, SAVE_CONTENT_DIRECTORY)
            if not save_dir:
                continue
            for save_path in sorted(save_dir.rglob("*")):
                if not save_path.is_file():
                    continue
                try:
                    package = inspect_stfs(save_path)
                    digest = sha256_file(save_path)
                    embedded = package.profile_id
                    status = "header-valid"
                    if package.content_type != 0x00000001:
                        status = "unexpected-content-type"
                    elif package.title_id != title_id:
                        status = "title-mismatch"
                    elif embedded not in {"", ZERO_PROFILE_ID, profile_id}:
                        status = "profile-mismatch"
                    name = (
                        package.display_name
                        or self.title_resolver(title_id)
                        or package.title_name
                        or save_path.name
                    )
                    saves.append(
                        SaveInfo(
                            profile_id=profile_id,
                            title_id=title_id,
                            name=name,
                            source_path=save_path,
                            package_magic=package.magic,
                            content_type=package.content_type,
                            save_game_id=package.save_game_id,
                            embedded_profile_id=embedded,
                            console_id=package.console_id,
                            device_id=package.device_id,
                            size=save_path.stat().st_size,
                            modified_at=datetime.fromtimestamp(
                                save_path.stat().st_mtime, timezone.utc
                            ).isoformat(),
                            sha256=digest,
                            status=status,
                        )
                    )
                    if status.endswith("mismatch"):
                        warnings.append(f"{save_path.name}: {status.replace('-', ' ')}")
                except (InvalidPackageError, OSError) as exc:
                    warnings.append(f"{save_path}: {exc}")
        return saves, warnings


class ProfileSaveManager:
    """Persist profile inventories and create non-destructive save snapshots."""

    def __init__(
        self,
        db_path: str | Path = DATABASE_PATH,
        backup_root: str | Path = PROFILE_BACKUPS_DIR,
    ) -> None:
        self.db_path = Path(db_path)
        self.backup_root = Path(backup_root)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_root.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            ensure_application_schema(connection)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, factory=_ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _resolve_title(self, title_id: str) -> str:
        with self._connect() as connection:
            for query in (
                "SELECT name FROM titleids WHERE titleid = ?",
                "SELECT name FROM xboxunity_title_catalog WHERE titleid = ?",
            ):
                try:
                    row = connection.execute(query, (title_id,)).fetchone()
                except sqlite3.OperationalError:
                    continue
                if row and str(row[0]).strip() not in {"", title_id, "Unknown"}:
                    return str(row[0]).strip()
        return ""

    def scan(self, source: str | Path) -> ProfileScanResult:
        started = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO profile_scan_runs(source_root, started_at, status)
                VALUES (?, ?, 'running')
                """,
                (str(Path(source).expanduser()), started),
            )
            run_id = _last_row_id(cursor)
            connection.commit()
        try:
            result = ProfileSaveScanner(self._resolve_title).scan(source)
            self._store_scan(result)
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE profile_scan_runs
                    SET completed_at=?, status='completed', profile_count=?,
                        save_count=?, warning_count=?, warnings_json=?
                    WHERE id=?
                    """,
                    (
                        utc_now(),
                        len(result.profiles),
                        len(result.saves),
                        len(result.warnings),
                        json.dumps(result.warnings),
                        run_id,
                    ),
                )
                connection.commit()
            return result
        except Exception as exc:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE profile_scan_runs
                    SET completed_at=?, status='failed', error_message=?
                    WHERE id=?
                    """,
                    (utc_now(), str(exc), run_id),
                )
                connection.commit()
            raise

    def _store_scan(self, result: ProfileScanResult) -> None:
        seen = result.scanned_at
        with self._connect() as connection:
            for profile in result.profiles:
                connection.execute(
                    """
                    INSERT INTO xbox_profiles(
                        profile_id, gamertag, source_path, package_path,
                        package_sha256, console_id, device_id, profile_kind,
                        package_status, first_seen_at, last_seen_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(profile_id, source_path) DO UPDATE SET
                        gamertag=excluded.gamertag,
                        package_path=excluded.package_path,
                        package_sha256=excluded.package_sha256,
                        console_id=excluded.console_id,
                        device_id=excluded.device_id,
                        profile_kind=excluded.profile_kind,
                        package_status=excluded.package_status,
                        last_seen_at=excluded.last_seen_at,
                        metadata_json=excluded.metadata_json
                    """,
                    (
                        profile.profile_id,
                        profile.gamertag,
                        str(profile.source_path),
                        str(profile.package_path or ""),
                        profile.package_sha256,
                        profile.console_id,
                        profile.device_id,
                        profile.profile_kind,
                        profile.package_status,
                        seen,
                        seen,
                        json.dumps(
                            {
                                "save_count": profile.save_count,
                                "total_size": profile.total_size,
                            }
                        ),
                    ),
                )
            for save in result.saves:
                connection.execute(
                    """
                    INSERT INTO profile_saves(
                        profile_id, titleid, name, source_path, package_magic,
                        content_type, save_game_id, embedded_profile_id,
                        console_id, device_id, size, modified_at, sha256,
                        status, first_seen_at, last_seen_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_path) DO UPDATE SET
                        profile_id=excluded.profile_id,
                        titleid=excluded.titleid,
                        name=excluded.name,
                        package_magic=excluded.package_magic,
                        content_type=excluded.content_type,
                        save_game_id=excluded.save_game_id,
                        embedded_profile_id=excluded.embedded_profile_id,
                        console_id=excluded.console_id,
                        device_id=excluded.device_id,
                        size=excluded.size,
                        modified_at=excluded.modified_at,
                        sha256=excluded.sha256,
                        status=excluded.status,
                        last_seen_at=excluded.last_seen_at
                    """,
                    (
                        save.profile_id,
                        save.title_id,
                        save.name,
                        str(save.source_path),
                        save.package_magic,
                        save.content_type,
                        save.save_game_id,
                        save.embedded_profile_id,
                        save.console_id,
                        save.device_id,
                        save.size,
                        save.modified_at,
                        save.sha256,
                        save.status,
                        seen,
                        seen,
                        "{}",
                    ),
                )
            connection.commit()

    def list_profiles(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT p.*,
                    COUNT(s.id) AS save_count,
                    COALESCE(SUM(s.size), 0) AS total_size,
                    SUM(CASE WHEN s.status != 'header-valid' THEN 1 ELSE 0 END)
                        AS attention_count
                FROM xbox_profiles p
                LEFT JOIN profile_saves s ON s.profile_id = p.profile_id
                GROUP BY p.id
                ORDER BY COALESCE(NULLIF(p.gamertag, ''), p.profile_id)
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_saves(
        self, profile_id: str | None = None, search: str = ""
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[str] = []
        if profile_id:
            clauses.append("profile_id = ?")
            values.append(profile_id)
        if search.strip():
            clauses.append("(name LIKE ? OR titleid LIKE ?)")
            term = f"%{search.strip()}%"
            values.extend((term, term))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM profile_saves
                {where}
                ORDER BY name COLLATE NOCASE, modified_at DESC
                """,
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def list_snapshots(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM save_snapshots ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_snapshot(
        self,
        profile_id: str,
        *,
        save_ids: Iterable[int] | None = None,
        label: str = "",
    ) -> int:
        profile = self._profile(profile_id)
        files = self._snapshot_sources(profile, save_ids)
        if not files:
            raise ProfileSaveError("No profile or save files were found to back up.")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO save_snapshots(
                    profile_id, label, source_root, snapshot_path, created_at, status
                ) VALUES (?, ?, ?, ?, ?, 'creating')
                """,
                (profile_id, label.strip(), profile["source_path"], "pending", utc_now()),
            )
            snapshot_id = _last_row_id(cursor)
            snapshot_path = self.backup_root / (
                f"snapshot-{snapshot_id:06d}-{datetime.now():%Y%m%d-%H%M%S}"
            )
            connection.execute(
                "UPDATE save_snapshots SET snapshot_path=? WHERE id=?",
                (str(snapshot_path), snapshot_id),
            )
            connection.commit()

        operation_id = self._start_operation("snapshot", snapshot_id, snapshot_path)
        try:
            snapshot_path.mkdir(parents=True, exist_ok=False)
            manifest_files: list[dict[str, Any]] = []
            total_size = 0
            for source, relative, item_kind, title_id in files:
                destination = snapshot_path / "files" / relative
                digest = self._verified_copy(source, destination)
                stat = source.stat()
                total_size += stat.st_size
                item = {
                    "source_path": str(source),
                    "relative_path": relative.as_posix(),
                    "sha256": digest,
                    "size": stat.st_size,
                    "modified_at": datetime.fromtimestamp(
                        stat.st_mtime, timezone.utc
                    ).isoformat(),
                    "item_kind": item_kind,
                    "titleid": title_id,
                }
                manifest_files.append(item)
                with self._connect() as connection:
                    connection.execute(
                        """
                        INSERT INTO save_snapshot_files(
                            snapshot_id, source_path, relative_path, sha256, size,
                            modified_at, item_kind, titleid
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            snapshot_id,
                            item["source_path"],
                            item["relative_path"],
                            digest,
                            item["size"],
                            item["modified_at"],
                            item_kind,
                            title_id,
                        ),
                    )
                    connection.commit()

            manifest = {
                "schema": 1,
                "snapshot_id": snapshot_id,
                "created_at": utc_now(),
                "profile_id": profile_id,
                "source_root": profile["source_path"],
                "files": manifest_files,
                "attribution": (
                    "Profile/STFS model informed by Dalavin (DJ SkunkieButt)'s "
                    "GPLv3 X360 library and Le Fluffie."
                ),
            }
            manifest_path = snapshot_path / "manifest.json"
            self._write_json_atomic(manifest_path, manifest)
            manifest_sha = sha256_file(manifest_path)
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE save_snapshots
                    SET file_count=?, total_size=?, manifest_sha256=?,
                        status='complete'
                    WHERE id=?
                    """,
                    (len(manifest_files), total_size, manifest_sha, snapshot_id),
                )
                connection.commit()
            self._finish_operation(operation_id, "completed")
            return snapshot_id
        except Exception as exc:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE save_snapshots SET status='failed', notes=? WHERE id=?",
                    (str(exc), snapshot_id),
                )
                connection.commit()
            self._finish_operation(operation_id, "failed", str(exc))
            raise

    def restore_snapshot(
        self,
        snapshot_id: int,
        destination: str | Path,
        *,
        conflict: str = "keep_both",
    ) -> RestoreResult:
        if conflict not in {"keep_both", "skip"}:
            raise ValueError("Restore conflict policy must be keep_both or skip.")
        destination_root = Path(destination).expanduser().resolve()
        destination_root.mkdir(parents=True, exist_ok=True)
        snapshot = self._snapshot(snapshot_id)
        snapshot_root = Path(snapshot["snapshot_path"])
        operation_id = self._start_operation("restore", snapshot_id, destination_root)
        restored = 0
        skipped = 0
        conflicts = 0
        try:
            with self._connect() as connection:
                files = connection.execute(
                    """
                    SELECT * FROM save_snapshot_files
                    WHERE snapshot_id=? ORDER BY relative_path
                    """,
                    (snapshot_id,),
                ).fetchall()
            for row in files:
                relative = Path(str(row["relative_path"]))
                source = snapshot_root / "files" / relative
                if not source.is_file() or sha256_file(source) != row["sha256"]:
                    raise ProfileSaveError(
                        f"Snapshot file failed verification: {relative}"
                    )
                target = self._safe_target(destination_root, relative)
                restore_status = "restored"
                if target.exists():
                    if sha256_file(target) == row["sha256"]:
                        skipped += 1
                        restore_status = "already-present"
                        self._set_restore_status(int(row["id"]), restore_status)
                        continue
                    conflicts += 1
                    if conflict == "skip":
                        skipped += 1
                        restore_status = "conflict-skipped"
                        self._set_restore_status(int(row["id"]), restore_status)
                        continue
                    target = self._conflict_target(target)
                    restore_status = "restored-alongside-conflict"
                self._verified_copy(source, target)
                restored += 1
                self._set_restore_status(int(row["id"]), restore_status)
            self._finish_operation(
                operation_id,
                "completed",
                details={
                    "restored": restored,
                    "skipped": skipped,
                    "conflicts": conflicts,
                },
            )
            return RestoreResult(
                snapshot_id, destination_root, restored, skipped, conflicts
            )
        except Exception as exc:
            self._finish_operation(operation_id, "failed", str(exc))
            raise

    def export_manifest(self, snapshot_id: int, destination: str | Path) -> Path:
        snapshot = self._snapshot(snapshot_id)
        source = Path(snapshot["snapshot_path"]) / "manifest.json"
        if not source.is_file():
            raise ProfileSaveError("The selected snapshot has no manifest.")
        target = Path(destination)
        self._verified_copy(source, target)
        return target

    def _profile(self, profile_id: str) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM xbox_profiles
                WHERE profile_id=? ORDER BY last_seen_at DESC LIMIT 1
                """,
                (profile_id,),
            ).fetchone()
        if row is None:
            raise ProfileSaveError("The selected profile is no longer in the inventory.")
        return row

    def _snapshot(self, snapshot_id: int) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM save_snapshots WHERE id=?", (snapshot_id,)
            ).fetchone()
        if row is None:
            raise ProfileSaveError("Snapshot not found.")
        if row["status"] != "complete":
            raise ProfileSaveError("Only complete snapshots can be restored.")
        return row

    def _snapshot_sources(
        self,
        profile: sqlite3.Row,
        save_ids: Iterable[int] | None,
    ) -> list[tuple[Path, Path, str, str]]:
        profile_root = Path(profile["source_path"]).resolve()
        requested = [int(value) for value in save_ids or ()]
        if requested:
            placeholders = ",".join("?" for _ in requested)
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT * FROM profile_saves
                    WHERE profile_id=? AND id IN ({placeholders})
                    """,
                    [profile["profile_id"], *requested],
                ).fetchall()
            result: list[tuple[Path, Path, str, str]] = []
            for row in rows:
                source = Path(row["source_path"]).resolve()
                try:
                    relative = source.relative_to(profile_root)
                except ValueError:
                    relative = Path(row["titleid"]) / SAVE_CONTENT_DIRECTORY / source.name
                result.append((source, relative, "save", row["titleid"]))
            return result

        result = []
        for source in sorted(profile_root.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(profile_root)
            parts_upper = {part.upper() for part in relative.parts}
            item_kind = (
                "save" if SAVE_CONTENT_DIRECTORY in parts_upper else "profile"
            )
            title_id = next(
                (part.upper() for part in relative.parts if HEX8_RE.fullmatch(part)),
                "",
            )
            result.append((source, relative, item_kind, title_id))
        return result

    def _start_operation(
        self, operation_type: str, snapshot_id: int, target: Path
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO profile_save_operations(
                    operation_type, target_path, snapshot_id, status, started_at
                ) VALUES (?, ?, ?, 'running', ?)
                """,
                (operation_type, str(target), snapshot_id, utc_now()),
            )
            connection.commit()
            return _last_row_id(cursor)

    def _finish_operation(
        self,
        operation_id: int,
        status: str,
        error: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE profile_save_operations
                SET status=?, completed_at=?, details_json=?, error_message=?
                WHERE id=?
                """,
                (
                    status,
                    utc_now(),
                    json.dumps(details or {}),
                    error or None,
                    operation_id,
                ),
            )
            connection.commit()

    def _set_restore_status(self, file_id: int, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE save_snapshot_files SET restore_status=? WHERE id=?",
                (status, file_id),
            )
            connection.commit()

    @staticmethod
    def _safe_target(root: Path, relative: Path) -> Path:
        if relative.is_absolute() or ".." in relative.parts:
            raise ProfileSaveError("Snapshot contains an unsafe relative path.")
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ProfileSaveError("Snapshot path escapes the destination.") from exc
        return target

    @staticmethod
    def _conflict_target(path: Path) -> Path:
        for index in range(1, 10_000):
            candidate = path.with_name(f"{path.name}.restored-{index}")
            if not candidate.exists():
                return candidate
        raise ProfileSaveConflict(f"Could not create a conflict-safe path for {path}")

    @staticmethod
    def _verified_copy(source: Path, destination: Path) -> str:
        if not source.is_file():
            raise FileNotFoundError(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        expected = sha256_file(source)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=destination.name + ".",
            suffix=".partial",
            dir=destination.parent,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            shutil.copy2(source, temporary)
            if sha256_file(temporary) != expected:
                raise ProfileSaveError(f"Copied file failed verification: {source}")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return expected

    @staticmethod
    def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".partial")
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)
