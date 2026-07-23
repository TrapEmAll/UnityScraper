"""Windows desktop entry point for the library-first UnityScraper interface."""
from app_paths import ensure_app_dirs, ensure_user_titleids_file
from modern_gui import main as gui_main

def main() -> None:
    ensure_app_dirs()
    ensure_user_titleids_file()
    gui_main()

if __name__ == "__main__":
    main()
