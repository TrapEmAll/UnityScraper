"""Package-facing Xbox package inspection exports."""

from __future__ import annotations

from .commands import InspectStfsPackage, InventoryStfsFileTable
from .inspectors import (
    extract_stfs_files,
    inspect_stfs,
    inspect_xbe,
    inspect_xex,
    list_stfs_entries,
)
from .models import (
    StfsEntry,
    StfsPackage,
    XbePackage,
    XexPackage,
)

__all__ = [
    "StfsEntry",
    "StfsPackage",
    "XbePackage",
    "XexPackage",
    "InspectStfsPackage",
    "InventoryStfsFileTable",
    "extract_stfs_files",
    "inspect_stfs",
    "inspect_xbe",
    "inspect_xex",
    "list_stfs_entries",
]
