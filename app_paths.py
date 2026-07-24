"""Cross-platform application storage and bundled-resource paths."""

from __future__ import annotations

import os
import posixpath
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

APP_NAME = "UnityScraper"
APP_SLUG = "unityscraper"


@dataclass(frozen=True)
class StoragePaths:
    """Resolved writable directories for one UnityScraper installation."""

    base: Path
    downloads: Path
    logs: Path
    config: Path
    data: Path
    cache: Path
    exports: Path
    diagnostics: Path


def app_root() -> Path:
    """Return the directory containing bundled application resources."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def executable_root() -> Path:
    """Return the directory beside the executable or source checkout."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def portable_mode_enabled() -> bool:
    """Return True when the application should store all data locally."""
    env_enabled = os.environ.get("UNITYSCRAPER_PORTABLE", "").strip() == "1"
    marker_enabled = (executable_root() / "portable.mode").exists()
    return env_enabled or marker_enabled


def resolve_storage_paths(
    *,
    os_name: str | None = None,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    portable_root: Path | None = None,
) -> StoragePaths:
    """Resolve platform-native paths without creating them.

    Explicit parameters keep path behavior straightforward to test on any host.
    """
    current_os = os_name or os.name
    current_platform = platform_name or sys.platform
    env = environ if environ is not None else os.environ
    user_home = Path(home) if home is not None else Path.home()

    def xdg_path(variable: str, fallback: Path) -> Path:
        value = env.get(variable)
        if value:
            candidate = Path(value).expanduser()
            if posixpath.isabs(value):
                return candidate
        return fallback

    if portable_root is not None:
        base = Path(portable_root) / "UnityScraperData"
        return StoragePaths(
            base=base,
            downloads=base / "downloads",
            logs=base / "logs",
            config=base / "config",
            data=base / "data",
            cache=base / "cache",
            exports=base / "exports",
            diagnostics=base / "diagnostics",
        )

    if current_os == "nt":
        root = env.get("LOCALAPPDATA") or env.get("APPDATA")
        base = Path(root) / APP_NAME if root else user_home / APP_NAME
        return StoragePaths(
            base=base,
            downloads=base / "downloads",
            logs=base / "logs",
            config=base / "config",
            data=base / "data",
            cache=base / "cache",
            exports=base / "exports",
            diagnostics=base / "diagnostics",
        )

    if current_platform == "darwin":
        base = user_home / "Library" / "Application Support" / APP_NAME
        return StoragePaths(
            base=base,
            downloads=base / "downloads",
            logs=user_home / "Library" / "Logs" / APP_NAME,
            config=base / "config",
            data=base / "data",
            cache=user_home / "Library" / "Caches" / APP_NAME,
            exports=base / "exports",
            diagnostics=base / "diagnostics",
        )

    data_home = xdg_path("XDG_DATA_HOME", user_home / ".local" / "share")
    config_home = xdg_path("XDG_CONFIG_HOME", user_home / ".config")
    cache_home = xdg_path("XDG_CACHE_HOME", user_home / ".cache")
    state_home = xdg_path("XDG_STATE_HOME", user_home / ".local" / "state")
    base = data_home / APP_SLUG
    return StoragePaths(
        base=base,
        downloads=base / "downloads",
        logs=state_home / APP_SLUG / "logs",
        config=config_home / APP_SLUG,
        data=base / "data",
        cache=cache_home / APP_SLUG,
        exports=base / "exports",
        diagnostics=base / "diagnostics",
    )


_PATHS = resolve_storage_paths(
    portable_root=executable_root() if portable_mode_enabled() else None
)

BASE_DIR = _PATHS.base
DOWNLOADS_DIR = _PATHS.downloads
LOG_DIR = _PATHS.logs
CONFIG_DIR = _PATHS.config
DATA_DIR = _PATHS.data
CACHE_DIR = _PATHS.cache
EXPORTS_DIR = _PATHS.exports
DIAGNOSTICS_DIR = _PATHS.diagnostics
PROFILE_BACKUPS_DIR = DATA_DIR / "profile_backups"

DATABASE_PATH = DATA_DIR / "unityscraper.db"
CONFIG_PATH = CONFIG_DIR / "config.json"
TITLEIDS_PATH = CONFIG_DIR / "JSON.txt"
CLI_LOG_PATH = LOG_DIR / "unityscraper.log"
GUI_LOG_PATH = LOG_DIR / "unityscraper_gui.log"
FIRST_RUN_PATH = CONFIG_DIR / "first_run_complete"


def resource_path(*parts: str) -> Path:
    """Return a bundled resource path in source and PyInstaller builds."""
    return app_root().joinpath(*parts)


def ensure_app_dirs() -> None:
    """Create every writable application directory."""
    for path in (
        BASE_DIR,
        DOWNLOADS_DIR,
        LOG_DIR,
        CONFIG_DIR,
        DATA_DIR,
        CACHE_DIR,
        EXPORTS_DIR,
        DIAGNOSTICS_DIR,
        PROFILE_BACKUPS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def ensure_user_titleids_file() -> Path:
    """Create the user's editable TitleID list when it does not yet exist."""
    ensure_app_dirs()

    if not TITLEIDS_PATH.exists():
        bundled = resource_path("JSON.txt")
        if bundled.exists():
            shutil.copyfile(bundled, TITLEIDS_PATH)
        else:
            TITLEIDS_PATH.write_text("", encoding="utf-8")

    return TITLEIDS_PATH


def describe_storage() -> str:
    """Return a human-readable storage summary for diagnostics and the UI."""
    mode = "Portable" if portable_mode_enabled() else "Installed"
    return (
        f"Mode: {mode}\n"
        f"Data: {DATA_DIR}\n"
        f"Downloads: {DOWNLOADS_DIR}\n"
        f"Exports: {EXPORTS_DIR}\n"
        f"Config: {CONFIG_DIR}\n"
        f"Cache: {CACHE_DIR}\n"
        f"Logs: {LOG_DIR}"
    )
