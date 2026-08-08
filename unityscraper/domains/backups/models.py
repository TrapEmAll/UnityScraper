"""Backup domain data models and errors."""

from __future__ import annotations

from backup_manager import (
    BackupError,
    BackupItem,
    ConflictError,
    FtpTarget,
    InvalidPackageError,
    ScanResult,
    TransferResult,
    UnsafeArchiveError,
)

__all__ = [
    "BackupError",
    "BackupItem",
    "ConflictError",
    "FtpTarget",
    "InvalidPackageError",
    "ScanResult",
    "TransferResult",
    "UnsafeArchiveError",
]
