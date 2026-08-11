"""Package-facing profile and save service exports."""

from __future__ import annotations

from profile_manager import (
    ProfileSaveConflict,
    ProfileSaveError,
    ProfileSaveManager,
    ProfileSaveScanner,
)

from .models import ProfileInfo, ProfileScanResult, RestoreResult, SaveInfo
from .operations import find_content_root, mask_identifier
from .gpd import (
    export_gpd_image,
    parse_gpd,
    parse_gpd_bytes,
    set_gpd_achievement_state,
    update_gpd_setting,
)

__all__ = [
    "ProfileInfo",
    "ProfileSaveConflict",
    "ProfileSaveError",
    "ProfileSaveManager",
    "ProfileSaveScanner",
    "ProfileScanResult",
    "RestoreResult",
    "SaveInfo",
    "find_content_root",
    "mask_identifier",
    "export_gpd_image",
    "parse_gpd",
    "parse_gpd_bytes",
    "set_gpd_achievement_state",
    "update_gpd_setting",
]
