"""Owned-content backup, inventory, and transfer domain."""

from __future__ import annotations

__all__ = [
    "BackupError",
    "BackupItem",
    "BackupRepository",
    "BackupService",
    "ConflictError",
    "FtpBackupClient",
    "FtpTarget",
    "InvalidPackageError",
    "ScanResult",
    "TransferResult",
    "UnsafeArchiveError",
    "ensure_backup_schema",
    "install_stfs_package",
    "scan_local_target",
    "verify_backup_item",
]


def __getattr__(name: str):
    if name == "ensure_backup_schema":
        from .migrations import ensure_backup_schema

        return ensure_backup_schema
    if name in {
        "BackupError",
        "BackupItem",
        "ConflictError",
        "FtpTarget",
        "InvalidPackageError",
        "ScanResult",
        "TransferResult",
        "UnsafeArchiveError",
    }:
        from . import models

        return getattr(models, name)
    if name in {
        "FtpBackupClient",
        "install_stfs_package",
        "scan_local_target",
        "verify_backup_item",
    }:
        from . import operations

        return getattr(operations, name)
    if name in {"BackupRepository", "BackupService"}:
        from . import service

        return getattr(service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
