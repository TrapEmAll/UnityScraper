"""Desktop entry point for the package layout."""

from __future__ import annotations


def main() -> int:
    """Run the desktop app through the package-owned entry point."""
    from desktop_app import main as desktop_main

    return desktop_main()


__all__ = ["main"]
