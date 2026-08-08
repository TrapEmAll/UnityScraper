"""CLI entry point for the package layout."""

from __future__ import annotations

from .legacy import run_legacy_cli


def main() -> int:
    """Run the current CLI through the package-owned adapter."""
    return run_legacy_cli()

__all__ = ["main"]
