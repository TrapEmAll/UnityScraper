"""Xbox 360 profile, save, and achievement inspection domain."""

from __future__ import annotations

from .models import ProfileInfo, ProfileScanResult, RestoreResult, SaveInfo
from .gpd import (
    export_gpd_image,
    parse_gpd,
    parse_gpd_bytes,
    set_gpd_achievement_state,
    update_gpd_setting,
)
from .operations import find_content_root, mask_identifier
from .service import (
    ProfileSaveConflict,
    ProfileSaveError,
    ProfileSaveManager,
    ProfileSaveScanner,
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
