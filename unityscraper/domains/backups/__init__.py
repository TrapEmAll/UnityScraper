"""Owned-content backup, inventory, and transfer domain."""

from __future__ import annotations

from .models import (
    BackupError,
    BackupItem,
    ConflictError,
    FtpTarget,
    InvalidPackageError,
    ScanResult,
    TransferResult,
    UnsafeArchiveError,
)
from .operations import (
    FtpBackupClient,
    install_stfs_package,
    scan_local_target,
    verify_backup_item,
)
from .service import BackupRepository, BackupService, ensure_backup_schema

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
