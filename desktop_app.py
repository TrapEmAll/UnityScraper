"""Cross-platform desktop entry point for UnityScraper."""

from __future__ import annotations

import sys

from app_paths import ensure_app_dirs, ensure_user_titleids_file


def main() -> int:
    """Initialize writable storage and launch the desktop application."""
    ensure_app_dirs()
    ensure_user_titleids_file()

    try:
        import tkinter as tk
        from modern_gui import main as gui_main
    except ImportError as exc:
        print(
            "UnityScraper requires Tkinter. On Debian/Ubuntu install python3-tk; "
            "on Fedora install python3-tkinter.",
            file=sys.stderr,
        )
        print(f"Details: {exc}", file=sys.stderr)
        return 1

    try:
        gui_main()
    except tk.TclError as exc:
        print(
            "UnityScraper could not connect to a graphical desktop. "
            "Start it from an X11 or Wayland session.",
            file=sys.stderr,
        )
        print(f"Details: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
