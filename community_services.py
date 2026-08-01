"""Safe operational services for UnityScraper's community roadmap."""

from __future__ import annotations

import ftplib
import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from PIL import Image

from app_paths import DATABASE_PATH
from backup_manager import FtpTarget, inspect_stfs, inspect_xbe, list_stfs_entries
from console_sync import ConsoleSyncService
from database_migrations import ensure_application_schema
from plugins import PluginManifest


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


DASHBOARD_PRESETS: dict[str, dict[str, Any]] = {
    "aurora": {
        "name": "Aurora",
        "content_root": "/Hdd1/Content/0000000000000000",
        "games_root": "/Hdd1/Games",
        "supports_resume": True,
        "artwork_layout": "aurora-assets",
    },
    "freestyle": {
        "name": "Freestyle Dash",
        "content_root": "/Hdd1/Content/0000000000000000",
        "games_root": "/Hdd1/Games",
        "supports_resume": True,
        "artwork_layout": "freestyle-data",
    },
    "xexmenu": {
        "name": "XeXMenu",
        "content_root": "/Hdd1/Content/0000000000000000",
        "games_root": "/Hdd1/Games",
        "supports_resume": False,
        "artwork_layout": "none",
    },
    "stock": {
        "name": "Stock Content Layout",
        "content_root": "/Hdd1/Content/0000000000000000",
        "games_root": "/Hdd1/Content/0000000000000000",
        "supports_resume": False,
        "artwork_layout": "none",
    },
}


@dataclass(frozen=True)
class SyncAction:
    action: str
    local_path: str
    remote_path: str
    size: int
    reason: str


class CommunityRepository:
    def __init__(self, db_path: str | Path = DATABASE_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
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


class ConsolePlanService(CommunityRepository):
    """Build explicit PC-to-console plans without touching the console."""

    def create_plan(
        self,
        local_root: str | Path,
        snapshot_id: int,
        dashboard_slug: str = "aurora",
    ) -> dict[str, Any]:
        if dashboard_slug not in DASHBOARD_PRESETS:
            raise ValueError(f"Unknown dashboard preset: {dashboard_slug}")
        root = Path(local_root).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(root)
        preset = DASHBOARD_PRESETS[dashboard_slug]
        remote_root = str(preset["content_root"])
        local_files = {
            path.relative_to(root).as_posix(): (path, path.stat().st_size)
            for path in root.rglob("*") if path.is_file()
        }
        with self.connect() as connection:
            remote_rows = connection.execute(
                """
                SELECT remote_path, size FROM console_inventory_items
                WHERE snapshot_id=? AND is_directory=0
                """,
                (snapshot_id,),
            ).fetchall()
            if not remote_rows:
                raise ValueError("The selected console snapshot contains no files")
            remote_files: dict[str, tuple[str, int]] = {}
            for row in remote_rows:
                remote_path = str(row["remote_path"])
                prefix = remote_root.rstrip("/") + "/"
                relative = remote_path[len(prefix):] if remote_path.startswith(prefix) else PurePosixPath(remote_path).name
                remote_files[relative] = (remote_path, int(row["size"] or 0))
            actions: list[SyncAction] = []
            for relative, (path, size) in local_files.items():
                destination = remote_root.rstrip("/") + "/" + relative
                if relative not in remote_files:
                    actions.append(SyncAction("upload", str(path), destination, size, "Missing on console"))
                elif remote_files[relative][1] != size:
                    actions.append(SyncAction("upload", str(path), destination, size, "Size differs"))
            for relative, (remote_path, size) in remote_files.items():
                if relative not in local_files:
                    actions.append(SyncAction("review_remote", "", remote_path, size, "Only on console"))
            summary = {
                "dashboard": dashboard_slug,
                "uploads": sum(item.action == "upload" for item in actions),
                "remote_only": sum(item.action == "review_remote" for item in actions),
                "unchanged": len(set(local_files) & set(remote_files))
                - sum(item.reason == "Size differs" for item in actions),
            }
            cursor = connection.execute(
                """
                INSERT INTO console_sync_plans(
                    dashboard_slug, local_root, remote_root, snapshot_id,
                    created_at, summary_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (dashboard_slug, str(root), remote_root, snapshot_id, utc_now(),
                 json.dumps(summary, sort_keys=True)),
            )
            plan_id = int(cursor.lastrowid or 0)
            connection.executemany(
                """
                INSERT INTO console_sync_actions(
                    plan_id, action, local_path, remote_path, size, reason, selected
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ((plan_id, item.action, item.local_path, item.remote_path, item.size,
                  item.reason, int(item.action == "upload")) for item in actions),
            )
        return {"plan_id": plan_id, "summary": summary,
                "actions": [asdict(item) for item in actions], "preset": preset}

    def list_plans(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM console_sync_plans ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_snapshots(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT s.*, COUNT(i.id) item_count
                FROM console_inventory_snapshots s
                LEFT JOIN console_inventory_items i ON i.snapshot_id=s.id
                WHERE s.status='completed'
                GROUP BY s.id ORDER BY s.captured_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_ftp_targets(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='backup_targets'"
            ).fetchone()
            if exists is None:
                return []
            rows = connection.execute(
                "SELECT id, name, location FROM backup_targets WHERE kind='ftp' ORDER BY name"
            ).fetchall()
        return [dict(row) for row in rows]

    def queue_uploads(self, plan_id: int, target_id: int | None = None) -> dict[str, Any]:
        """Queue selected upload actions after revalidating their local files."""
        with self.connect() as connection:
            plan = connection.execute(
                "SELECT * FROM console_sync_plans WHERE id=?", (plan_id,)
            ).fetchone()
            if plan is None:
                raise KeyError(f"Unknown sync plan: {plan_id}")
            root = Path(plan["local_root"]).resolve()
            rows = connection.execute(
                """
                SELECT * FROM console_sync_actions
                WHERE plan_id=? AND action='upload' AND selected=1
                  AND status IN ('preview', 'failed')
                ORDER BY id
                """,
                (plan_id,),
            ).fetchall()
        sync = ConsoleSyncService(self.db_path)
        queued: list[int] = []
        failed: list[dict[str, Any]] = []
        for row in rows:
            local = Path(row["local_path"]).resolve()
            try:
                local.relative_to(root)
                if not local.is_file() or local.stat().st_size != int(row["size"]):
                    raise ValueError("Local file changed since the preview")
                job_id = sync.enqueue(
                    "upload", local, row["remote_path"], target_id=target_id
                )
            except (OSError, ValueError) as exc:
                failed.append({"action_id": row["id"], "error": str(exc)})
                with self.connect() as connection:
                    connection.execute(
                        "UPDATE console_sync_actions SET status='failed' WHERE id=?",
                        (row["id"],),
                    )
            else:
                queued.append(job_id)
                with self.connect() as connection:
                    connection.execute(
                        "UPDATE console_sync_actions SET status='queued' WHERE id=?",
                        (row["id"],),
                    )
        with self.connect() as connection:
            connection.execute(
                "UPDATE console_sync_plans SET status=? WHERE id=?",
                ("queued" if queued and not failed else "needs_review", plan_id),
            )
        return {"plan_id": plan_id, "queued_job_ids": queued, "failed": failed}


class PackageWorkspaceService(CommunityRepository):
    """Create auditable, read-only workspaces for user-supplied packages."""

    def inspect(self, package_path: str | Path) -> dict[str, Any]:
        package = inspect_stfs(package_path)
        result = asdict(package)
        result["path"] = str(package.path)
        result["sha256"] = _sha256(package.path)
        try:
            entries = list_stfs_entries(package.path)
        except Exception as exc:
            result["file_table"] = []
            result["file_table_status"] = f"unavailable: {exc}"
        else:
            result["file_table"] = [asdict(entry) for entry in entries]
            result["file_table_status"] = "read-only bounded inventory"
        result["mutation_ready"] = False
        result["required_before_rebuild"] = [
            "complete extraction and block/hash tree verification", "rehash", "signature",
            "post-build verification",
        ]
        return result

    def create_workspace(self, package_path: str | Path, destination: str | Path) -> Path:
        source = Path(package_path).expanduser().resolve()
        details = self.inspect(source)
        target = Path(destination).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        package_copy = target / "original" / source.name
        package_copy.parent.mkdir(parents=True, exist_ok=True)
        if package_copy.exists() and _sha256(package_copy) != details["sha256"]:
            raise FileExistsError(package_copy)
        if not package_copy.exists():
            shutil.copy2(source, package_copy)
        manifest = target / "unityscraper-package-workspace.json"
        manifest.write_text(
            json.dumps({"schema": 1, "created_at": utc_now(), "read_only": True,
                        "package": details}, indent=2), encoding="utf-8"
        )
        return manifest


class ArtworkService(CommunityRepository):
    PRESETS = {
        "aurora": "Assets/{titleid}/cover{extension}",
        "freestyle": "Data/GameData/{titleid}/boxart{extension}",
        "archive": "Artwork/{titleid}/cover{extension}",
    }

    def set_preference(
        self, titleid: str, source_path: str | Path, *, region: str = "", language: str = ""
    ) -> dict[str, Any]:
        tid = titleid.strip().upper()
        if len(tid) != 8 or any(ch not in "0123456789ABCDEF" for ch in tid):
            raise ValueError("TitleID must be eight hexadecimal digits")
        source = Path(source_path).expanduser().resolve()
        with Image.open(source) as image:
            image.verify()
        with Image.open(source) as image:
            width, height = image.size
        digest = _sha256(source)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO artwork_preferences(
                    titleid, source_path, region, language, width, height, sha256, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(titleid) DO UPDATE SET
                    source_path=excluded.source_path, region=excluded.region,
                    language=excluded.language, width=excluded.width,
                    height=excluded.height, sha256=excluded.sha256,
                    updated_at=excluded.updated_at
                """,
                (tid, str(source), region, language, width, height, digest, utc_now()),
            )
        return {"titleid": tid, "path": str(source), "width": width,
                "height": height, "sha256": digest}

    def export(self, destination: str | Path, preset: str = "aurora") -> dict[str, Any]:
        if preset not in self.PRESETS:
            raise ValueError(f"Unknown artwork preset: {preset}")
        target = Path(destination).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        exported: list[dict[str, str]] = []
        skipped: list[str] = []
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM artwork_preferences ORDER BY titleid").fetchall()
            for row in rows:
                source = Path(row["source_path"])
                if not source.is_file() or _sha256(source) != row["sha256"]:
                    skipped.append(row["titleid"])
                    continue
                extension = source.suffix.casefold() or ".png"
                relative = self.PRESETS[preset].format(titleid=row["titleid"], extension=extension)
                output = target / Path(relative)
                output.parent.mkdir(parents=True, exist_ok=True)
                if output.exists() and _sha256(output) != row["sha256"]:
                    skipped.append(row["titleid"])
                    continue
                if not output.exists():
                    shutil.copy2(source, output)
                exported.append({"titleid": row["titleid"], "path": relative,
                                 "sha256": row["sha256"]})
            manifest = target / "unityscraper-artwork-manifest.json"
            manifest.write_text(json.dumps({"schema": 1, "preset": preset,
                                "generated_at": utc_now(), "artwork": exported}, indent=2),
                                encoding="utf-8")
            cursor = connection.execute(
                """INSERT INTO artwork_export_runs(destination, preset, created_at,
                   exported_count, skipped_count, manifest_path, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'completed')""",
                (str(target), preset, utc_now(), len(exported), len(skipped), str(manifest)),
            )
        return {"run_id": int(cursor.lastrowid or 0), "exported": len(exported),
                "skipped": skipped, "manifest": str(manifest)}


class PreservationPlanningService(CommunityRepository):
    def audit_disc_sets(self, snapshot_id: int | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            selected = snapshot_id
            if selected is None:
                row = connection.execute(
                    "SELECT id FROM collection_snapshots WHERE status='completed' ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row is None:
                    return []
                selected = int(row["id"])
            rows = connection.execute(
                """
                SELECT titleid, media_id, MAX(COALESCE(disc_count, 1)) expected_count,
                       GROUP_CONCAT(DISTINCT COALESCE(disc_number, 1)) present
                FROM collection_items WHERE snapshot_id=? AND titleid IS NOT NULL
                GROUP BY titleid, media_id
                """,
                (selected,),
            ).fetchall()
            audits = []
            for row in rows:
                expected = max(1, int(row["expected_count"] or 1))
                present = sorted({int(value) for value in str(row["present"] or "1").split(",")})
                missing = sorted(set(range(1, expected + 1)) - set(present))
                status = "complete" if not missing else "incomplete"
                connection.execute(
                    """
                    INSERT INTO disc_set_audits(snapshot_id, titleid, media_id,
                        expected_count, present_json, missing_json, status, audited_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (selected, row["titleid"], row["media_id"], expected,
                     json.dumps(present), json.dumps(missing), status, utc_now()),
                )
                audits.append({"titleid": row["titleid"], "media_id": row["media_id"],
                               "expected": expected, "present": present, "missing": missing,
                               "status": status})
        return audits

    def create_dedup_plan(self, root: str | Path, max_files: int = 200_000) -> dict[str, Any]:
        directory = Path(root).expanduser().resolve()
        if not directory.is_dir():
            raise FileNotFoundError(directory)
        by_size: dict[int, list[Path]] = {}
        count = 0
        for path in directory.rglob("*"):
            if path.is_file() and not path.is_symlink():
                count += 1
                if count > max_files:
                    raise ValueError(f"Dedup scan exceeds the {max_files}-file safety limit")
                by_size.setdefault(path.stat().st_size, []).append(path)
        groups: list[tuple[str, list[Path], int]] = []
        for size, paths in by_size.items():
            if len(paths) < 2:
                continue
            digests: dict[str, list[Path]] = {}
            for path in paths:
                digests.setdefault(_sha256(path), []).append(path)
            groups.extend((digest, matches, size) for digest, matches in digests.items()
                          if len(matches) > 1)
        reclaimable = sum(size * (len(paths) - 1) for _, paths, size in groups)
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO dedup_plans(root, created_at, duplicate_groups,
                   reclaimable_bytes) VALUES (?, ?, ?, ?)""",
                (str(directory), utc_now(), len(groups), reclaimable),
            )
            plan_id = int(cursor.lastrowid or 0)
            for digest, paths, size in groups:
                keeper = min(paths, key=lambda item: (len(str(item)), str(item).casefold()))
                connection.executemany(
                    """INSERT INTO dedup_actions(plan_id, sha256, keeper_path,
                       duplicate_path, size) VALUES (?, ?, ?, ?, ?)""",
                    ((plan_id, digest, str(keeper), str(path), size)
                     for path in paths if path != keeper),
                )
        return {"plan_id": plan_id, "groups": len(groups),
                "reclaimable_bytes": reclaimable, "files_scanned": count}

    def apply_dedup_action(self, action_id: int, mode: str = "quarantine") -> dict[str, Any]:
        """Apply one revalidated duplicate action with a recoverable quarantine copy."""
        if mode not in {"quarantine", "hardlink"}:
            raise ValueError("mode must be quarantine or hardlink")
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT a.*, p.root FROM dedup_actions a
                JOIN dedup_plans p ON p.id=a.plan_id WHERE a.id=?
                """,
                (action_id,),
            ).fetchone()
            if row is None:
                raise KeyError(action_id)
            if row["status"] not in {"preview", "failed"}:
                raise ValueError("This duplicate action has already been handled")
        root = Path(row["root"]).resolve()
        keeper = Path(row["keeper_path"]).resolve()
        duplicate = Path(row["duplicate_path"]).resolve()
        keeper.relative_to(root)
        duplicate.relative_to(root)
        if not keeper.is_file() or not duplicate.is_file():
            raise FileNotFoundError("One of the duplicate files is missing")
        expected = row["sha256"]
        if _sha256(keeper) != expected or _sha256(duplicate) != expected:
            raise ValueError("A file changed since the duplicate preview")
        quarantine_root = root / ".unityscraper-dedup-quarantine" / str(row["plan_id"])
        relative = duplicate.relative_to(root)
        quarantined = quarantine_root / relative
        quarantined.parent.mkdir(parents=True, exist_ok=True)
        if quarantined.exists():
            raise FileExistsError(quarantined)
        duplicate.replace(quarantined)
        try:
            if mode == "hardlink":
                duplicate.hardlink_to(keeper)
        except Exception:
            quarantined.replace(duplicate)
            raise
        try:
            with self.connect() as connection:
                connection.execute(
                    "UPDATE dedup_actions SET action=?, status='completed' WHERE id=?",
                    (mode, action_id),
                )
                connection.execute(
                    """
                    INSERT INTO dedup_recovery_records(
                        action_id, original_path, quarantine_path, keeper_path,
                        mode, sha256, created_at, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'quarantined')
                    """,
                    (action_id, str(duplicate), str(quarantined), str(keeper),
                     mode, expected, utc_now()),
                )
        except Exception:
            if mode == "hardlink" and duplicate.exists():
                duplicate.unlink()
            if quarantined.exists() and not duplicate.exists():
                quarantined.replace(duplicate)
            raise
        return {"action_id": action_id, "mode": mode, "keeper": str(keeper),
                "duplicate": str(duplicate), "quarantine": str(quarantined)}

    def list_dedup_actions(self, plan_id: int | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            selected = plan_id
            if selected is None:
                row = connection.execute(
                    "SELECT id FROM dedup_plans ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row is None:
                    return []
                selected = int(row["id"])
            rows = connection.execute(
                """
                SELECT a.*, r.status recovery_status
                FROM dedup_actions a
                LEFT JOIN dedup_recovery_records r ON r.action_id=a.id
                WHERE a.plan_id=? ORDER BY a.size DESC, a.id
                """,
                (selected,),
            ).fetchall()
        return [dict(row) for row in rows]

    def restore_dedup_action(self, action_id: int) -> dict[str, Any]:
        """Restore a quarantined duplicate after validating every involved path."""
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT r.*, p.root FROM dedup_recovery_records r
                JOIN dedup_actions a ON a.id=r.action_id
                JOIN dedup_plans p ON p.id=a.plan_id
                WHERE r.action_id=?
                """,
                (action_id,),
            ).fetchone()
        if row is None:
            raise KeyError(action_id)
        if row["status"] != "quarantined":
            raise ValueError("This duplicate is not waiting in recovery quarantine")
        root = Path(row["root"]).resolve()
        original = Path(row["original_path"]).resolve()
        quarantine = Path(row["quarantine_path"]).resolve()
        keeper = Path(row["keeper_path"]).resolve()
        original.relative_to(root)
        quarantine.relative_to(root)
        keeper.relative_to(root)
        expected = row["sha256"]
        if not quarantine.is_file() or _sha256(quarantine) != expected:
            raise ValueError("The quarantined file is missing or changed")
        if original.exists():
            if row["mode"] != "hardlink":
                raise FileExistsError(original)
            if not original.is_file() or _sha256(original) != expected:
                raise ValueError("The replacement file changed; restore was refused")
            try:
                if not original.samefile(keeper):
                    raise ValueError("The replacement is not the expected hardlink")
            except OSError as exc:
                raise ValueError("The replacement hardlink could not be verified") from exc
            original.unlink()
        original.parent.mkdir(parents=True, exist_ok=True)
        quarantine.replace(original)
        try:
            with self.connect() as connection:
                connection.execute(
                    """UPDATE dedup_recovery_records
                       SET status='restored', restored_at=? WHERE action_id=?""",
                    (utc_now(), action_id),
                )
                connection.execute(
                    "UPDATE dedup_actions SET status='restored' WHERE id=?",
                    (action_id,),
                )
        except Exception:
            original.replace(quarantine)
            if row["mode"] == "hardlink":
                original.hardlink_to(keeper)
            raise
        return {"action_id": action_id, "restored": str(original)}


class StorageAndXboxService(CommunityRepository):
    FATX_OFFSETS = (0, 0x7FF000, 0x10C080000, 0x118EB0000, 0x120EB0000,
                    0x130EB0000, 0x8000400, 0x8115200, 0x12000400, 0x20000000)

    def audit_storage(self, source_path: str | Path) -> dict[str, Any]:
        source = Path(source_path).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(source)
        filesystem = "mounted-filesystem" if source.is_dir() else "unknown-image"
        details: dict[str, Any] = {"size": source.stat().st_size}
        if source.is_dir():
            usb_parts = sorted(
                path for path in (source / "Xbox360").glob("Data[0-9][0-9][0-9][0-9]")
                if path.is_file()
            )
            if usb_parts:
                filesystem = "Xbox 360 USB container"
                details["container_parts"] = len(usb_parts)
                details["container_size"] = sum(path.stat().st_size for path in usb_parts)
                details["container_files"] = [path.name for path in usb_parts]
        if source.is_file():
            partitions = []
            source_size = source.stat().st_size
            with source.open("rb") as handle:
                for offset in self.FATX_OFFSETS:
                    if offset + 16 > source_size:
                        continue
                    handle.seek(offset)
                    header = handle.read(16)
                    if header[:4] != b"XTAF":
                        continue
                    sectors_per_cluster = int.from_bytes(header[8:12], "big")
                    root_cluster = int.from_bytes(header[12:16], "big")
                    valid_cluster = (
                        sectors_per_cluster > 0
                        and sectors_per_cluster <= 0x10000
                        and sectors_per_cluster & (sectors_per_cluster - 1) == 0
                    )
                    partitions.append({
                        "offset": offset,
                        "partition_id": f"{int.from_bytes(header[4:8], 'big'):08X}",
                        "sectors_per_cluster": sectors_per_cluster,
                        "cluster_size": sectors_per_cluster * 512,
                        "root_directory_cluster": root_cluster,
                        "header_valid": valid_cluster and root_cluster > 0,
                    })
            if partitions:
                filesystem = "FATX"
                details["partitions"] = partitions
                details["signature_offset"] = partitions[0]["offset"]
        status = "recognized" if filesystem != "unknown-image" else "unrecognized"
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO storage_source_audits(source_path, source_kind,
                   filesystem, detected_at, status, details_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(source), "directory" if source.is_dir() else "image", filesystem,
                 utc_now(), status, json.dumps(details, sort_keys=True)),
            )
        return {"audit_id": int(cursor.lastrowid or 0), "path": str(source),
                "filesystem": filesystem, "access_mode": "read-only", "status": status,
                "details": details}

    def scan_original_xbox(self, root: str | Path) -> list[dict[str, Any]]:
        directory = Path(root).expanduser().resolve()
        if not directory.is_dir():
            raise FileNotFoundError(directory)
        records = []
        with self.connect() as connection:
            for path in directory.rglob("default.xbe"):
                try:
                    package = inspect_xbe(path)
                except (OSError, ValueError):
                    continue
                region_names = [
                    name for flag, name in (
                        (0x1, "North America"), (0x2, "Japan"),
                        (0x4, "Rest of World"), (0x80000000, "Manufacturing"),
                    ) if package.region_flags & flag
                ]
                regions = ", ".join(region_names) or "Unknown"
                item = {
                    "titleid": package.title_id, "title_name": package.title_name,
                    "xbe_path": str(package.path), "size": package.size,
                    "region_flags": f"0x{package.region_flags:08X}",
                    "regions": region_names, "version": package.version,
                    "disc_number": package.disc_number,
                    "allowed_media": f"0x{package.allowed_media:08X}",
                }
                connection.execute(
                    """
                    INSERT INTO original_xbox_records(
                        titleid, title_name, xbe_path, region_flags, version,
                        metadata_json, scanned_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(xbe_path) DO UPDATE SET titleid=excluded.titleid,
                        title_name=excluded.title_name, region_flags=excluded.region_flags,
                        version=excluded.version, metadata_json=excluded.metadata_json,
                        scanned_at=excluded.scanned_at
                    """,
                    (package.title_id, package.title_name, str(package.path), regions,
                     str(package.version), json.dumps(item, sort_keys=True), utc_now()),
                )
                records.append(item)
        return records


class PluginControlService(CommunityRepository):
    def install_package(self, archive_path: str | Path, plugin_root: str | Path) -> dict[str, Any]:
        archive = Path(archive_path).expanduser().resolve()
        root = Path(plugin_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as package:
            members = [item for item in package.infolist() if not item.is_dir()]
            if len(members) > 500 or sum(item.file_size for item in members) > 64 * 1024 * 1024:
                raise ValueError("Plugin archive exceeds the safety limit")
            for item in members:
                parts = Path(item.filename).parts
                if item.filename.startswith(("/", "\\")) or ".." in parts:
                    raise ValueError(f"Unsafe plugin archive path: {item.filename}")
            with tempfile.TemporaryDirectory(dir=root) as temporary:
                staging = Path(temporary)
                package.extractall(staging)
                manifests = list(staging.rglob("plugin.json"))
                if len(manifests) != 1:
                    raise ValueError("Plugin archive must contain exactly one plugin.json")
                manifest = PluginManifest.load(manifests[0])
                source_dir = manifests[0].parent
                entry = source_dir / manifest.entrypoint
                if not entry.is_file():
                    raise ValueError("Plugin entrypoint is missing")
                destination = root / manifest.plugin_id
                backup = None
                if destination.exists():
                    backup = root / f".{manifest.plugin_id}.backup-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    destination.replace(backup)
                try:
                    shutil.copytree(source_dir, destination)
                except Exception:
                    if backup and backup.exists() and not destination.exists():
                        backup.replace(destination)
                    raise
        self.set_state(manifest.plugin_id, False, destination / manifest.entrypoint,
                       manifest.permissions)
        return {"id": manifest.plugin_id, "name": manifest.name,
                "version": manifest.version, "path": str(destination),
                "enabled": False, "backup": str(backup) if backup else ""}

    def discover(self, plugin_root: str | Path) -> list[dict[str, Any]]:
        root = Path(plugin_root).expanduser().resolve()
        result = []
        if not root.is_dir():
            return result
        with self.connect() as connection:
            states = {row["plugin_id"]: dict(row) for row in
                      connection.execute("SELECT * FROM plugin_states").fetchall()}
        for manifest_path in root.glob("*/plugin.json"):
            try:
                manifest = PluginManifest.load(manifest_path)
                entry = manifest_path.parent / manifest.entrypoint
                digest = _sha256(entry) if entry.is_file() else ""
                state = states.get(manifest.plugin_id, {})
                result.append({"id": manifest.plugin_id, "name": manifest.name,
                               "version": manifest.version,
                               "permissions": list(manifest.permissions),
                               "entry_sha256": digest,
                               "enabled": bool(state.get("enabled", 0)),
                               "trusted": bool(digest and digest == state.get("trusted_sha256"))})
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                result.append({"id": manifest_path.parent.name, "error": str(exc),
                               "enabled": False, "trusted": False})
        return result

    def set_state(self, plugin_id: str, enabled: bool, entry_path: str | Path,
                  permissions: Iterable[str] = ()) -> None:
        entry = Path(entry_path).expanduser().resolve()
        if enabled and not entry.is_file():
            raise FileNotFoundError(entry)
        digest = _sha256(entry) if entry.is_file() else ""
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO plugin_states(plugin_id, enabled, trusted_sha256,
                   permissions_json, updated_at) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(plugin_id) DO UPDATE SET enabled=excluded.enabled,
                   trusted_sha256=excluded.trusted_sha256,
                   permissions_json=excluded.permissions_json,
                   updated_at=excluded.updated_at""",
                (plugin_id, int(enabled), digest, json.dumps(list(permissions)), utc_now()),
            )


class RecoveryService(CommunityRepository):
    def scan(self, roots: Iterable[str | Path]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        with self.connect() as connection:
            for root in roots:
                directory = Path(root).expanduser().resolve()
                if not directory.is_dir():
                    continue
                for path in directory.rglob("*.partial"):
                    events.append(self._record(connection, "partial_file", path, True,
                                               {"size": path.stat().st_size}))
            queries = (
                ("failed_transfer", "SELECT id, local_path source, error_message details FROM console_transfer_jobs WHERE status='failed'"),
                ("incomplete_snapshot", "SELECT id, snapshot_path source, status details FROM save_snapshots WHERE status<>'complete'"),
                ("failed_operation", "SELECT id, source, error_message details FROM backup_operations WHERE status='failed'"),
            )
            for event_type, sql in queries:
                for row in connection.execute(sql).fetchall():
                    events.append(self._record(connection, event_type, row["source"], True,
                                               {"record_id": row["id"], "details": row["details"]}))
        return events

    def list_open(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM recovery_events WHERE status='open' ORDER BY detected_at DESC"
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json"))
            result.append(item)
        return result

    def recover(self, event_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM recovery_events WHERE id=? AND status='open'", (event_id,)
            ).fetchone()
            if row is None:
                raise KeyError(event_id)
            details = json.loads(row["details_json"])
            event_type = row["event_type"]
            if event_type == "failed_transfer":
                connection.execute(
                    """UPDATE console_transfer_jobs SET status='queued', error_message=NULL,
                       updated_at=? WHERE id=? AND status='failed'""",
                    (utc_now(), int(details["record_id"])),
                )
                action = "Transfer returned to the queue"
            elif event_type == "partial_file":
                source = Path(row["source"])
                if not source.is_file():
                    action = "Partial file was already removed"
                else:
                    quarantine = source.parent / ".unityscraper-recovery"
                    quarantine.mkdir(exist_ok=True)
                    target = quarantine / source.name
                    if target.exists():
                        target = quarantine / f"{source.stem}-{event_id}{source.suffix}"
                    source.replace(target)
                    action = f"Partial file quarantined at {target}"
            else:
                action = "Event acknowledged; inspect its source before retrying"
            connection.execute(
                "UPDATE recovery_events SET status='resolved', resolved_at=? WHERE id=?",
                (utc_now(), event_id),
            )
        return {"event_id": event_id, "action": action}

    @staticmethod
    def _record(connection, event_type: str, source: str | Path, recoverable: bool,
                details: dict[str, Any]) -> dict[str, Any]:
        existing = connection.execute(
            """SELECT id FROM recovery_events WHERE event_type=? AND source=?
               AND status='open' LIMIT 1""", (event_type, str(source))
        ).fetchone()
        if existing:
            event_id = int(existing["id"])
        else:
            cursor = connection.execute(
                """INSERT INTO recovery_events(event_type, source, status, recoverable,
                   details_json, detected_at) VALUES (?, ?, 'open', ?, ?, ?)""",
                (event_type, str(source), int(recoverable), json.dumps(details), utc_now()),
            )
            event_id = int(cursor.lastrowid or 0)
        return {"id": event_id, "event_type": event_type, "source": str(source),
                "recoverable": recoverable, "details": details}


class DashboardCompatibilityService(CommunityRepository):
    def probe(self, dashboard_slug: str, target: FtpTarget) -> dict[str, Any]:
        if dashboard_slug not in DASHBOARD_PRESETS:
            raise ValueError(f"Unknown dashboard preset: {dashboard_slug}")
        results: dict[str, tuple[bool, str]] = {}
        with ftplib.FTP() as ftp:
            ftp.connect(target.host, target.port, timeout=target.timeout)
            ftp.login(target.username, target.password)
            results["connect"] = (True, ftp.getwelcome() or "Connected")
            try:
                features = ftp.sendcmd("FEAT")
            except ftplib.all_errors as exc:
                features = ""
                results["feat"] = (False, str(exc))
            else:
                results["feat"] = (True, features)
            upper = features.upper()
            results["resume"] = ("REST STREAM" in upper or "REST" in upper,
                                 "Advertised by FEAT" if "REST" in upper else "Not advertised")
            results["remote_hash"] = ("SHA-256" in upper or "XSHA256" in upper,
                                      "Advertised by FEAT" if "HASH" in upper or "SHA" in upper else "Not advertised")
            try:
                ftp.cwd(str(DASHBOARD_PRESETS[dashboard_slug]["content_root"]))
            except ftplib.all_errors as exc:
                results["content_root"] = (False, str(exc))
            else:
                results["content_root"] = (True, "Readable")
        with self.connect() as connection:
            for feature, (supported, details) in results.items():
                connection.execute(
                    """INSERT INTO dashboard_compatibility_results(
                       dashboard_slug, host_label, tested_at, feature, supported, details)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(dashboard_slug, host_label, feature) DO UPDATE SET
                       tested_at=excluded.tested_at, supported=excluded.supported,
                       details=excluded.details""",
                    (dashboard_slug, target.host, utc_now(), feature, int(supported), details),
                )
        return {key: {"supported": value[0], "details": value[1]}
                for key, value in results.items()}


class AccessibilityService(CommunityRepository):
    DEFAULTS = {"large_text": "0", "high_contrast": "0", "reduced_motion": "0",
                "keyboard_hints": "1"}

    def get(self) -> dict[str, bool]:
        values = dict(self.DEFAULTS)
        with self.connect() as connection:
            values.update({row["key"]: row["value"] for row in
                           connection.execute("SELECT key, value FROM accessibility_preferences")})
        return {key: value == "1" for key, value in values.items()}

    def set(self, key: str, enabled: bool) -> None:
        if key not in self.DEFAULTS:
            raise ValueError(f"Unknown accessibility preference: {key}")
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO accessibility_preferences(key, value, updated_at)
                   VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET
                   value=excluded.value, updated_at=excluded.updated_at""",
                (key, "1" if enabled else "0", utc_now()),
            )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()
