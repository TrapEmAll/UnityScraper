"""Declarative catalog and conservative discovery for community Xbox tools."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Iterable

from unityscraper.core.paths import CONFIG_PATH, executable_root, resource_path

from .models import ToolDefinition, ToolOperation


TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "xextool",
        "XeXTool",
        "xorloser",
        "https://github.com/XboxChef/XexToolGUI",
        ("windows",),
        ("xextool.exe",),
        (
            ToolOperation(
                "extended-info", "Extended information", ("-l", "{input}"), "file"
            ),
            ToolOperation("basic-info", "Basic information", ("{input}",), "file"),
            ToolOperation(
                "custom", "Custom arguments", (), "optional", destructive=True
            ),
        ),
        ("assets", "tools", "xextool", "xextool.exe"),
    ),
    ToolDefinition(
        "extract-xiso",
        "extract-xiso",
        "XboxDev",
        "https://github.com/XboxDev/extract-xiso",
        ("windows", "linux", "macos"),
        ("extract-xiso.exe", "extract-xiso"),
        (
            ToolOperation("list", "List image contents", ("-l", "{input}"), "file"),
            ToolOperation(
                "extract",
                "Extract image",
                ("-x", "{input}", "-d", "{output}"),
                "file",
                "directory",
            ),
            ToolOperation(
                "create",
                "Create image",
                ("-c", "{input}", "{output}"),
                "directory",
                "file",
            ),
            ToolOperation(
                "rewrite",
                "Rewrite image",
                ("-r", "{input}"),
                "file",
                destructive=True,
            ),
        ),
    ),
    ToolDefinition(
        "xenia",
        "Xenia",
        "Xenia Project",
        "https://github.com/xenia-project/xenia",
        ("windows",),
        ("xenia.exe",),
        (
            ToolOperation(
                "launch-game", "Launch game", ("{input}",), "any", detached=True
            ),
            ToolOperation("open", "Open emulator", detached=True),
        ),
    ),
    ToolDefinition(
        "xenia-canary",
        "Xenia Canary",
        "Xenia Canary Project",
        "https://github.com/xenia-canary/xenia-canary",
        ("windows",),
        ("xenia_canary.exe", "xenia-canary.exe"),
        (
            ToolOperation(
                "launch-game", "Launch game", ("{input}",), "any", detached=True
            ),
            ToolOperation("open", "Open emulator", detached=True),
        ),
    ),
    ToolDefinition(
        "velocity",
        "Velocity",
        "Velocity contributors",
        "https://github.com/Gualdimar/Velocity",
        ("windows",),
        ("Velocity.exe",),
        (ToolOperation("open", "Open Velocity", detached=True),),
    ),
    ToolDefinition(
        "iso2god",
        "Iso2God",
        "Iso2God contributors",
        "https://github.com/r4dius/Iso2God",
        ("windows",),
        ("Iso2God.exe",),
        (ToolOperation("open", "Open Iso2God", detached=True),),
    ),
    ToolDefinition(
        "god2iso",
        "God2ISO",
        "Community utility",
        "",
        ("windows",),
        ("God2Iso.exe", "God2ISO.exe"),
        (ToolOperation("open", "Open God2ISO", detached=True),),
    ),
    ToolDefinition(
        "xbox-image-browser",
        "Xbox Image Browser",
        "Community utility",
        "",
        ("windows",),
        ("Xbox Image Browser.exe", "XboxImageBrowser.exe"),
        (ToolOperation("open", "Open Xbox Image Browser", detached=True),),
    ),
    ToolDefinition(
        "le-fluffie",
        "Le Fluffie",
        "Dalavin (DJ SkunkieButt)",
        "",
        ("windows",),
        ("Le Fluffie.exe", "LeFluffie.exe"),
        (ToolOperation("open", "Open Le Fluffie", detached=True),),
    ),
    ToolDefinition(
        "custom",
        "Custom CLI tool",
        "User supplied",
        "",
        ("all",),
        (),
        (
            ToolOperation(
                "custom",
                "Custom arguments",
                (),
                "optional",
                "optional",
                destructive=True,
            ),
        ),
    ),
)


def platform_key() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


class ToolCatalog:
    """Resolve built-in definitions and user-approved executable paths."""

    def __init__(self, config_path: Path | str = CONFIG_PATH) -> None:
        self.config_path = Path(config_path)
        self._definitions = {tool.id: tool for tool in TOOLS}

    def definitions(self, *, supported_only: bool = False) -> tuple[ToolDefinition, ...]:
        values = TOOLS
        if supported_only:
            values = tuple(tool for tool in values if tool.supports_current_platform())
        return values

    def get(self, tool_id: str) -> ToolDefinition:
        try:
            return self._definitions[tool_id]
        except KeyError as exc:
            raise KeyError(f"Unknown external tool: {tool_id}") from exc

    def configured_path(self, tool_id: str) -> Path | None:
        config = self._read_config()
        tools = config.get("external_tools", {})
        if not isinstance(tools, dict):
            return None
        paths = tools.get("paths", {})
        value = paths.get(tool_id, "") if isinstance(paths, dict) else ""
        if not value and tool_id == "xextool":
            value = tools.get("xextool_path", "")
        if not value and tool_id == "custom":
            value = tools.get("custom_tool_path", "")
        path = Path(str(value)).expanduser()
        return path.resolve() if path.is_file() else None

    def discover(self, tool_id: str) -> Path | None:
        tool = self.get(tool_id)
        if not tool.supports_current_platform():
            return None
        configured = self.configured_path(tool_id)
        if configured:
            return configured
        if tool.bundled_path:
            bundled = resource_path(*tool.bundled_path)
            if bundled.is_file():
                return bundled.resolve()
        for name in tool.executable_names:
            located = shutil.which(name)
            if located and Path(located).is_file():
                return Path(located).resolve()
        for candidate in self._conventional_candidates(tool):
            if candidate.is_file():
                return candidate.resolve()
        return None

    def save_path(self, tool_id: str, path: Path | str) -> Path:
        executable = Path(path).expanduser().resolve()
        if not executable.is_file():
            raise FileNotFoundError(executable)
        config = self._read_config()
        tools = config.setdefault("external_tools", {})
        if not isinstance(tools, dict):
            tools = {}
            config["external_tools"] = tools
        paths = tools.setdefault("paths", {})
        if not isinstance(paths, dict):
            paths = {}
            tools["paths"] = paths
        paths[tool_id] = str(executable)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return executable

    def checksum(self, path: Path | str) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().upper()

    def _read_config(self) -> dict[str, object]:
        if not self.config_path.exists():
            return {}
        try:
            value = json.loads(self.config_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _conventional_candidates(tool: ToolDefinition) -> Iterable[Path]:
        root = executable_root()
        home = Path.home()
        locations = [
            root,
            root / "tools" / tool.id,
            home / "Documents" / tool.name,
            home / "Downloads" / tool.name,
        ]
        if os.name == "nt":
            for variable in ("ProgramFiles", "ProgramFiles(x86)"):
                value = os.environ.get(variable)
                if value:
                    locations.append(Path(value) / tool.name)
        for location in locations:
            for name in tool.executable_names:
                yield location / name


def operation_for(tool: ToolDefinition, operation_id: str) -> ToolOperation:
    try:
        return next(item for item in tool.operations if item.id == operation_id)
    except StopIteration as exc:
        raise KeyError(f"{tool.name} does not support operation {operation_id}") from exc


__all__ = [
    "TOOLS",
    "ToolCatalog",
    "ToolDefinition",
    "ToolOperation",
    "operation_for",
    "platform_key",
]
