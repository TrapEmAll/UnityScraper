"""Persistent, resumable console inventory and FTP synchronization."""

from __future__ import annotations

import ftplib
import hashlib
import json
import posixpath
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

from app_paths import DATABASE_PATH
from backup_manager import FtpBackupClient, FtpTarget
from backup_service import ensure_backup_schema
from database_migrations import ensure_application_schema


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TransferPaused(RuntimeError):
    """Raised internally after a job reaches a resumable pause point."""


@dataclass(frozen=True)
class ConsoleFile:
    path: str
    size: int | None
    modified_at: str = ""
    is_directory: bool = False


@dataclass(frozen=True)
class SyncComparison:
    only_on_pc: tuple[str, ...]
    only_on_console: tuple[str, ...]
    size_mismatches: tuple[str, ...]
    matching: tuple[str, ...]


class ConsoleSyncService:
    """Store sync state in SQLite and execute one explicit job at a time."""

    def __init__(self, db_path: str | Path = DATABASE_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pause = threading.Event()
        with self._connect() as connection:
            ensure_backup_schema(connection)
            ensure_application_schema(connection)
            connection.execute(
                """
                UPDATE console_transfer_jobs
                SET status='paused', error_message='Application exited during transfer',
                    updated_at=?
                WHERE status='transferring'
                """,
                (utc_now(),),
            )

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

    def enqueue(
        self,
        direction: str,
        local_path: str | Path,
        remote_path: str,
        *,
        target_id: int | None = None,
        priority: int = 100,
        bandwidth_limit: int = 0,
        expected_sha256: str = "",
    ) -> int:
        if direction not in {"upload", "download"}:
            raise ValueError("direction must be upload or download")
        local = Path(local_path).expanduser().resolve()
        total = local.stat().st_size if direction == "upload" and local.is_file() else 0
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO console_transfer_jobs
                    (target_id, direction, local_path, remote_path, total_bytes,
                     status, priority, bandwidth_limit, expected_sha256,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)
                """,
                (
                    target_id,
                    direction,
                    str(local),
                    _remote_path(remote_path),
                    total,
                    priority,
                    max(0, bandwidth_limit),
                    expected_sha256.lower(),
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def list_jobs(self, status: str | None = None) -> list[dict]:
        with self._connect() as connection:
            if status:
                rows = connection.execute(
                    """
                    SELECT * FROM console_transfer_jobs
                    WHERE status=? ORDER BY priority, created_at
                    """,
                    (status,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM console_transfer_jobs ORDER BY created_at DESC"
                ).fetchall()
        return [dict(row) for row in rows]

    def pause(self, job_id: int | None = None) -> None:
        self._pause.set()
        if job_id is not None:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE console_transfer_jobs SET status='paused', updated_at=?
                    WHERE id=? AND status IN ('queued', 'transferring')
                    """,
                    (utc_now(), job_id),
                )

    def resume(self, job_id: int) -> None:
        self._pause.clear()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE console_transfer_jobs
                SET status='queued', error_message=NULL, updated_at=?
                WHERE id=? AND status IN ('paused', 'failed')
                """,
                (utc_now(), job_id),
            )

    def run_next(
        self,
        target: FtpTarget,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM console_transfer_jobs
                WHERE status='queued' ORDER BY priority, created_at LIMIT 1
                """
            ).fetchone()
        return self.run_job(int(row["id"]), target, progress) if row else None

    def run_job(
        self,
        job_id: int,
        target: FtpTarget,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict:
        self._pause.clear()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM console_transfer_jobs WHERE id=?", (job_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown transfer job: {job_id}")
            if row["status"] not in {"queued", "paused", "failed"}:
                raise ValueError(f"Job {job_id} cannot run from status {row['status']}")
            connection.execute(
                """
                UPDATE console_transfer_jobs
                SET status='transferring', error_message=NULL, updated_at=? WHERE id=?
                """,
                (utc_now(), job_id),
            )
        job = dict(row)
        try:
            if job["direction"] == "upload":
                transferred, total = self._upload(job, target, progress)
            else:
                transferred, total = self._download(job, target, progress)
            self._verify(job, target, total)
            status, error = "completed", None
        except TransferPaused as exc:
            transferred = self._progress(job_id)
            total = int(job["total_bytes"])
            status, error = "paused", str(exc)
        except Exception as exc:
            transferred = self._progress(job_id)
            total = int(job["total_bytes"])
            status, error = "failed", str(exc)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE console_transfer_jobs SET transferred_bytes=?, total_bytes=?,
                    status=?, error_message=?, updated_at=? WHERE id=?
                """,
                (transferred, total, status, error, utc_now(), job_id),
            )
            result = connection.execute(
                "SELECT * FROM console_transfer_jobs WHERE id=?", (job_id,)
            ).fetchone()
        return dict(result)

    def _upload(self, job: dict, target: FtpTarget, progress) -> tuple[int, int]:
        local = Path(job["local_path"])
        if not local.is_file():
            raise FileNotFoundError(local)
        total = local.stat().st_size
        remote = _remote_path(job["remote_path"])
        partial = remote + ".partial"
        started = time.monotonic()
        with _ftp(target) as ftp:
            FtpBackupClient._mkdirs(ftp, str(PurePosixPath(remote).parent))
            offset = _remote_size(ftp, partial) or 0
            if offset > total:
                ftp.delete(partial)
                offset = 0
            job["_session_offset"] = offset
            with local.open("rb") as handle:
                handle.seek(offset)

                def callback(chunk: bytes) -> None:
                    current = handle.tell()
                    self._checkpoint(int(job["id"]), current, total, started, job, progress)

                ftp.storbinary(
                    f"STOR {partial}",
                    handle,
                    blocksize=64 * 1024,
                    callback=callback,
                    rest=offset or None,
                )
            if _remote_size(ftp, remote) is not None:
                ftp.delete(remote)
            ftp.rename(partial, remote)
        return total, total

    def _download(self, job: dict, target: FtpTarget, progress) -> tuple[int, int]:
        local = Path(job["local_path"])
        local.parent.mkdir(parents=True, exist_ok=True)
        partial = local.with_suffix(local.suffix + ".partial")
        remote = _remote_path(job["remote_path"])
        started = time.monotonic()
        with _ftp(target) as ftp:
            total = _remote_size(ftp, remote)
            if total is None:
                raise FileNotFoundError(remote)
            offset = partial.stat().st_size if partial.exists() else 0
            if offset > total:
                partial.unlink()
                offset = 0
            job["_session_offset"] = offset
            with partial.open("ab" if offset else "wb") as handle:

                def callback(chunk: bytes) -> None:
                    handle.write(chunk)
                    self._checkpoint(
                        int(job["id"]), handle.tell(), total, started, job, progress
                    )

                ftp.retrbinary(
                    f"RETR {remote}",
                    callback,
                    blocksize=64 * 1024,
                    rest=offset or None,
                )
        if partial.stat().st_size != total:
            raise IOError(f"Transfer size mismatch: {partial.stat().st_size} != {total}")
        partial.replace(local)
        return total, total

    def _checkpoint(self, job_id, current, total, started, job, progress) -> None:
        if self._pause.is_set():
            raise TransferPaused("Transfer paused; partial data was kept for resume")
        limit = int(job["bandwidth_limit"] or 0)
        if limit:
            expected = (current - int(job.get("_session_offset", 0))) / limit
            delay = expected - (time.monotonic() - started)
            if delay > 0:
                time.sleep(min(delay, 0.25))
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE console_transfer_jobs SET transferred_bytes=?, total_bytes=?,
                    updated_at=? WHERE id=?
                """,
                (current, total, utc_now(), job_id),
            )
        if progress:
            progress(current, total)

    def _verify(self, job: dict, target: FtpTarget, total: int) -> None:
        if job["direction"] == "upload":
            with _ftp(target) as ftp:
                actual = _remote_size(ftp, _remote_path(job["remote_path"]))
            if actual != total:
                raise IOError(f"Remote verification failed: {actual} != {total}")
        else:
            local = Path(job["local_path"])
            if local.stat().st_size != total:
                raise IOError("Local size verification failed")
            expected = (job["expected_sha256"] or "").lower()
            if expected and _sha256(local) != expected:
                raise IOError("Downloaded file failed SHA-256 verification")

    def _progress(self, job_id: int) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT transferred_bytes FROM console_transfer_jobs WHERE id=?", (job_id,)
            ).fetchone()
        return int(row[0]) if row else 0

    def capture_inventory(
        self,
        target: FtpTarget,
        root: str = "/Hdd1",
        *,
        target_id: int | None = None,
        max_entries: int = 100_000,
    ) -> int:
        """Capture a read-only remote inventory; no console file is changed."""
        root = _remote_path(root)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO console_inventory_snapshots
                    (target_id, label, root, captured_at, status)
                VALUES (?, ?, ?, ?, 'running')
                """,
                (target_id, target.host, root, utc_now()),
            )
            snapshot_id = int(cursor.lastrowid)
        try:
            with _ftp(target) as ftp:
                entries = list(_walk_ftp(ftp, root, max_entries))
            with self._connect() as connection:
                for entry in entries:
                    connection.execute(
                        """
                        INSERT INTO console_inventory_items
                            (snapshot_id, remote_path, size, modified_at, is_directory)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            snapshot_id,
                            entry.path,
                            entry.size,
                            entry.modified_at,
                            int(entry.is_directory),
                        ),
                    )
                connection.execute(
                    """
                    UPDATE console_inventory_snapshots
                    SET item_count=?, status='completed' WHERE id=?
                    """,
                    (len(entries), snapshot_id),
                )
            return snapshot_id
        except Exception as exc:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE console_inventory_snapshots
                    SET status='failed', error_message=? WHERE id=?
                    """,
                    (str(exc), snapshot_id),
                )
            raise

    def list_snapshots(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM console_inventory_snapshots
                ORDER BY captured_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def compare(self, local_root: str | Path, snapshot_id: int) -> SyncComparison:
        root = Path(local_root).resolve()
        local = {
            child.relative_to(root).as_posix(): child.stat().st_size
            for child in root.rglob("*")
            if child.is_file()
        }
        with self._connect() as connection:
            snapshot = connection.execute(
                "SELECT root FROM console_inventory_snapshots WHERE id=?", (snapshot_id,)
            ).fetchone()
            if not snapshot:
                raise KeyError(snapshot_id)
            remote_root = snapshot["root"].rstrip("/") + "/"
            rows = connection.execute(
                """
                SELECT remote_path, size FROM console_inventory_items
                WHERE snapshot_id=? AND is_directory=0
                """,
                (snapshot_id,),
            ).fetchall()
        remote = {
            row["remote_path"].removeprefix(remote_root): row["size"]
            for row in rows
        }
        local_names, remote_names = set(local), set(remote)
        common = local_names & remote_names
        mismatches = tuple(sorted(name for name in common if local[name] != remote[name]))
        return SyncComparison(
            tuple(sorted(local_names - remote_names)),
            tuple(sorted(remote_names - local_names)),
            mismatches,
            tuple(sorted(common - set(mismatches))),
        )


def _remote_path(path: str) -> str:
    normalized = posixpath.normpath("/" + path.replace("\\", "/").lstrip("/"))
    if normalized == "/.." or normalized.startswith("/../"):
        raise ValueError("Remote path escapes the configured root")
    return normalized


def _ftp(target: FtpTarget) -> ftplib.FTP:
    ftp = ftplib.FTP()
    ftp.connect(target.host, target.port, timeout=target.timeout)
    ftp.login(target.username, target.password)
    ftp.voidcmd("TYPE I")
    return ftp


def _remote_size(ftp: ftplib.FTP, path: str) -> int | None:
    try:
        return ftp.size(path)
    except ftplib.error_perm:
        return None


def _walk_ftp(ftp: ftplib.FTP, root: str, limit: int) -> Iterable[ConsoleFile]:
    pending = [root]
    seen = 0
    while pending:
        directory = pending.pop()
        try:
            entries = list(ftp.mlsd(directory))
        except (ftplib.error_perm, AttributeError):
            entries = []
            for name in ftp.nlst(directory):
                entries.append((PurePosixPath(name).name, {}))
        for name, facts in entries:
            if name in {".", ".."}:
                continue
            path = _remote_path(posixpath.join(directory, name))
            entry_type = facts.get("type", "")
            is_directory = entry_type == "dir"
            if not entry_type:
                current = ftp.pwd()
                try:
                    ftp.cwd(path)
                    is_directory = True
                except ftplib.error_perm:
                    is_directory = False
                finally:
                    ftp.cwd(current)
            size = None if is_directory else _remote_size(ftp, path)
            yield ConsoleFile(path, size, facts.get("modify", ""), is_directory)
            seen += 1
            if seen >= limit:
                raise RuntimeError(f"Remote inventory exceeded safety limit of {limit} entries")
            if is_directory:
                pending.append(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
