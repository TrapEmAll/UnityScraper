"""Adapter for the existing top-level CLI implementation."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import contextmanager
import sys


@contextmanager
def _temporary_argv(argv: Sequence[str] | None):
    if argv is None:
        yield
        return
    original = sys.argv[:]
    sys.argv = [original[0], *argv]
    try:
        yield
    finally:
        sys.argv = original


def run_legacy_cli(argv: list[str] | None = None) -> int:
    """Run the legacy CLI while package-owned commands are extracted."""
    from main import main as legacy_main

    with _temporary_argv(argv):
        result = legacy_main()
    return 0 if result is None else int(result)


__all__ = ["run_legacy_cli"]
