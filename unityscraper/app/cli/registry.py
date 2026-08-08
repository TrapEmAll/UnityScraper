"""Default command registry for the UnityScraper CLI."""

from __future__ import annotations

from .commands import CliCommand, CliCommandRegistry
from .legacy import run_legacy_cli


def build_cli_registry() -> CliCommandRegistry:
    """Build the CLI registry with the legacy command as the default surface."""
    registry = CliCommandRegistry()
    registry.register(
        CliCommand(
            name="legacy",
            description="Run the existing full UnityScraper CLI surface.",
            handler=run_legacy_cli,
        )
    )
    return registry


__all__ = ["build_cli_registry"]
