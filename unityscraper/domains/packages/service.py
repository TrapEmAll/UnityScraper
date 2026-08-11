"""Package-facing Xbox package inspection exports."""

from __future__ import annotations

from .commands import InspectStfsPackage, InventoryStfsFileTable, VerifyStfsPackage
from .inspectors import (
    extract_stfs_files,
    inspect_stfs,
    inspect_xbe,
    inspect_xex,
    list_stfs_entries,
    verify_stfs,
)
from .gdf import GdfEntry, GdfImage, extract_gdf, inspect_gdf
from .fatx import (
    FatxEntry,
    FatxImage,
    FatxPartition,
    extract_fatx,
    inspect_fatx,
    replace_fatx_file,
)
from .models import (
    StfsBlockVerification,
    StfsEntry,
    StfsHashRecord,
    StfsIntegrityReport,
    StfsMutationResult,
    StfsPackage,
    XbePackage,
    XexPackage,
)
from .mutations import edit_stfs_metadata, rehash_stfs, replace_stfs_file
from .svod import (
    SvodIntegrityReport,
    SvodPackage,
    extract_svod_payload,
    inspect_svod,
    verify_svod,
)

__all__ = [
    "StfsEntry",
    "GdfEntry",
    "GdfImage",
    "FatxEntry",
    "FatxImage",
    "FatxPartition",
    "StfsBlockVerification",
    "StfsHashRecord",
    "StfsIntegrityReport",
    "StfsMutationResult",
    "SvodIntegrityReport",
    "SvodPackage",
    "StfsPackage",
    "XbePackage",
    "XexPackage",
    "InspectStfsPackage",
    "InventoryStfsFileTable",
    "VerifyStfsPackage",
    "extract_stfs_files",
    "inspect_stfs",
    "inspect_xbe",
    "inspect_xex",
    "list_stfs_entries",
    "verify_stfs",
    "edit_stfs_metadata",
    "rehash_stfs",
    "replace_stfs_file",
    "extract_gdf",
    "inspect_gdf",
    "extract_fatx",
    "inspect_fatx",
    "replace_fatx_file",
    "extract_svod_payload",
    "inspect_svod",
    "verify_svod",
]
