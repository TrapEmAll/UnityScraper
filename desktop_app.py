"""Cross-platform desktop entry point for UnityScraper."""

from __future__ import annotations

import sys
import traceback

from app_paths import LOG_DIR, ensure_app_dirs, ensure_user_titleids_file


def _write_startup_report(exc: BaseException) -> str:
    details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        (LOG_DIR / "fatal_startup.log").write_text(details, encoding="utf-8")
    except OSError:
        pass
    return details


def main() -> int:
    """Initialize writable storage and launch the desktop application."""
    if len(sys.argv) > 1 and sys.argv[1] == "--plugin-worker":
        from plugin_worker import main as plugin_worker_main

        return plugin_worker_main(sys.argv[2:])

    ensure_app_dirs()
    ensure_user_titleids_file()

    try:
        import tkinter as tk
        from modern_gui import main as gui_main
    except ImportError as exc:
        details = _write_startup_report(exc)
        print(
            "UnityScraper requires Tkinter. On Debian/Ubuntu install python3-tk; "
            "on Fedora install python3-tkinter.",
            file=sys.stderr,
        )
        print(details, file=sys.stderr)
        return 1

    try:
        gui_main()
    except tk.TclError as exc:
        details = _write_startup_report(exc)
        print(
            "UnityScraper could not connect to a graphical desktop. "
            "Start it from an X11 or Wayland session.",
            file=sys.stderr,
        )
        print(details, file=sys.stderr)
        return 1
    except Exception as exc:
        report = LOG_DIR / "fatal_startup.log"
        details = _write_startup_report(exc)
        try:
            from tkinter import messagebox

            messagebox.showerror(
                "UnityScraper could not start",
                f"A startup report was written to:\n{report}\n\n{exc}",
            )
        except tk.TclError:
            pass
        print(details, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
