"""
Windows-friendly local storage paths for UnityScraper.

All mutable data lives under the current user's local application data folder
so a packaged desktop app can run from Program Files, Downloads, or any other
read-only install location.
"""

import os
import shutil
import sys
from pathlib import Path


APP_NAME = "UnityScraper"


def _base_dir() -> Path:
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

DATABASE_PATH = DATA_DIR / "unityscraper.db"
CONFIG_PATH = CONFIG_DIR / "config.json"
TITLEIDS_PATH = CONFIG_DIR / "JSON.txt"
CLI_LOG_PATH = LOG_DIR / "unityscraper.log"
GUI_LOG_PATH = LOG_DIR / "unityscraper_gui.log"


def app_root() -> Path:
    """Return the folder containing bundled application files."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def ensure_app_dirs() -> None:
    """Create the user-writable folder tree used by the app."""
    for path in (BASE_DIR, DOWNLOADS_DIR, LOG_DIR, CONFIG_DIR, DATA_DIR):
        path.mkdir(parents=True, exist_ok=True)


def ensure_user_titleids_file() -> Path:
    """
    Ensure the user's editable TitleID list exists.

    The repository ships a starter JSON.txt. On first run we copy that starter
    list into the user's config directory, then all future edits stay local.
    """
    ensure_app_dirs()
    if not TITLEIDS_PATH.exists():
        bundled = app_root() / "JSON.txt"
        if bundled.exists():
            shutil.copyfile(bundled, TITLEIDS_PATH)
        else:
            TITLEIDS_PATH.write_text("", encoding="utf-8")
    return TITLEIDS_PATH


def describe_storage() -> str:
    return (
        f"Data: {DATA_DIR}\n"
        f"Downloads: {DOWNLOADS_DIR}\n"
        f"Config: {CONFIG_DIR}\n"
        f"Logs: {LOG_DIR}"
    )
