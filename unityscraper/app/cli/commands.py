"""CLI command registration contracts.

The current CLI is still implemented by the top-level ``main.py`` module. New
domain commands should register here first, then the legacy parser can shrink
as each feature moves to a package-owned command handler.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

CommandHandler = Callable[[list[str] | None], int | None]


@dataclass(frozen=True)
class CliCommand:
    """A UI-neutral command exposed by the command-line app."""

    name: str
    description: str
    handler: CommandHandler

    def run(self, argv: list[str] | None = None) -> int:
        result = self.handler(argv)
        return 0 if result is None else int(result)


@dataclass
class CliCommandRegistry:
    """Ordered registry for package-owned CLI commands."""

    commands: dict[str, CliCommand] = field(default_factory=dict)

    def register(self, command: CliCommand) -> None:
        if command.name in self.commands:
            raise ValueError(f"Duplicate CLI command: {command.name}")
        self.commands[command.name] = command

    def get(self, name: str) -> CliCommand:
        try:
            return self.commands[name]
        except KeyError as exc:
            raise KeyError(f"Unknown CLI command: {name}") from exc

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {
            name: {"name": command.name, "description": command.description}
            for name, command in sorted(self.commands.items())
        }


__all__ = ["CliCommand", "CliCommandRegistry", "CommandHandler"]
