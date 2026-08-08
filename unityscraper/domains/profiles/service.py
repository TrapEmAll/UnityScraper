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
]
