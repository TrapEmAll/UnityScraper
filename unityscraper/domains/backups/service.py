"""Package-facing backup service exports."""

from __future__ import annotations

from backup_service import BackupRepository, BackupService, ensure_backup_schema

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
from unityscraper.domains.packages.models import StfsPackage

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
    "StfsPackage",
    "TransferResult",
    "UnsafeArchiveError",
    "ensure_backup_schema",
    "install_stfs_package",
    "scan_local_target",
    "verify_backup_item",
]
