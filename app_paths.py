"""
Application storage paths with optional portable-mode support.

Portable mode is enabled when either:
1. A file named ``portable.mode`` exists beside the executable/source files, or
2. The environment variable ``UNITYSCRAPER_PORTABLE`` is set to ``1``.

Normal installations continue to use %LOCALAPPDATA%\\UnityScraper.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "UnityScraper"


def app_root() -> Path:
    """Return the directory containing bundled application resources."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def executable_root() -> Path:
    """Return the writable directory beside the executable or source checkout."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def portable_mode_enabled() -> bool:
    """Return True when the application should store all data locally."""
    env_enabled = os.environ.get("UNITYSCRAPER_PORTABLE", "").strip() == "1"
    marker_enabled = (executable_root() / "portable.mode").exists()
    return env_enabled or marker_enabled


def _base_dir() -> Path:
    """Resolve the root directory used for mutable application data."""
    if portable_mode_enabled():
        return executable_root() / "UnityScraperData"

    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if root:
            return Path(root) / APP_NAME

    return Path.home() / ".unityscraper"


BASE_DIR = _base_dir()
DOWNLOADS_DIR = BASE_DIR / "downloads"
LOG_DIR = BASE_DIR / "logs"
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
EXPORTS_DIR = BASE_DIR / "exports"
DIAGNOSTICS_DIR = BASE_DIR / "diagnostics"

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
        EXPORTS_DIR,
        DIAGNOSTICS_DIR,
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
        f"Logs: {LOG_DIR}"
    )
