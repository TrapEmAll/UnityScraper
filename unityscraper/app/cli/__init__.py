"""Command-line application adapters."""

from __future__ import annotations

from .commands import CliCommand, CliCommandRegistry
from .registry import build_cli_registry

__all__ = ["CliCommand", "CliCommandRegistry", "build_cli_registry"]
