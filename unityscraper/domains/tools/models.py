"""Data contracts for external Xbox utility discovery and execution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolOperation:
    """One supported, reviewable action exposed by a tool."""

    id: str
    label: str
    arguments: tuple[str, ...] = ()
    input_kind: str = "none"
    output_kind: str = "none"
    detached: bool = False
    destructive: bool = False


@dataclass(frozen=True)
class ToolDefinition:
    """Metadata and discovery hints for a community utility."""

    id: str
    name: str
    author: str
    homepage: str
    platforms: tuple[str, ...]
    executable_names: tuple[str, ...]
    operations: tuple[ToolOperation, ...]
    bundled_path: tuple[str, ...] = ()

    def supports_current_platform(self) -> bool:
        from .catalog import platform_key

        return platform_key() in self.platforms or "all" in self.platforms


@dataclass(frozen=True)
class ToolResult:
    """Captured result from one external tool invocation."""

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    cancelled: bool


@dataclass(frozen=True)
class ToolLaunch:
    """Details for a detached graphical tool launch."""

    command: tuple[str, ...]
    pid: int

__all__ = ["ToolDefinition", "ToolLaunch", "ToolOperation", "ToolResult"]
