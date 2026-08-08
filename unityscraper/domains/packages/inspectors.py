"""Read-only package inspection operations."""

from __future__ import annotations

from backup_manager import (
    extract_stfs_files,
    inspect_stfs,
    inspect_xbe,
    inspect_xex,
    list_stfs_entries,
)

__all__ = [
    "extract_stfs_files",
    "inspect_stfs",
    "inspect_xbe",
    "inspect_xex",
    "list_stfs_entries",
]
