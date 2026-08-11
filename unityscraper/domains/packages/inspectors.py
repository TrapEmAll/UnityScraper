"""Read-only package inspection operations."""

from __future__ import annotations

from .executables import inspect_xbe, inspect_xex
from .stfs import (
    extract_stfs_files,
    inspect_stfs,
    list_stfs_entries,
    read_stfs_layout,
    verify_stfs,
)

__all__ = [
    "extract_stfs_files",
    "inspect_stfs",
    "inspect_xbe",
    "inspect_xex",
    "list_stfs_entries",
    "read_stfs_layout",
    "verify_stfs",
]
