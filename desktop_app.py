"""
Windows desktop entrypoint for UnityScraper.

This module keeps the packaged executable focused on the GUI while preserving
the original CLI in main.py for advanced users.
"""

from app_paths import describe_storage, ensure_app_dirs, ensure_user_titleids_file
from GUI import main as gui_main


def main():
    ensure_app_dirs()
    ensure_user_titleids_file()
    print("UnityScraper local storage")
    print(describe_storage())
    gui_main()


if __name__ == "__main__":
    main()
