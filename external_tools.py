"""Safe process runner for user-supplied Xbox command-line tools."""

from __future__ import annotations

import os
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class ExternalToolError(RuntimeError):
    """Raised when an external tool cannot be configured or launched."""


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


def split_arguments(value: str, *, windows: bool | None = None) -> list[str]:
    """Split an editable argument template without passing it through a shell."""
    use_windows_rules = os.name == "nt" if windows is None else windows
    arguments = shlex.split(value, posix=not use_windows_rules)
    if use_windows_rules:
        return [
            argument[1:-1]
            if len(argument) >= 2 and argument[0] == argument[-1] == '"'
            else argument
            for argument in arguments
        ]
    return arguments


def format_command(command: Iterable[str], *, windows: bool | None = None) -> str:
    """Format an argument vector for display only."""
    values = list(command)
    use_windows_rules = os.name == "nt" if windows is None else windows
    return subprocess.list2cmdline(values) if use_windows_rules else shlex.join(values)


class ExternalToolRunner:
    """Run one selected executable at a time without shell interpretation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._cancel_requested = False

    def build_command(
        self,
        executable: str | Path,
        argument_template: Iterable[str],
        *,
        input_path: str | Path | None = None,
        output_path: str | Path | None = None,
        input_kind: str = "file",
        output_kind: str = "optional",
    ) -> tuple[str, ...]:
        tool = Path(executable).expanduser().resolve()
        if not tool.is_file():
            raise ExternalToolError(f"Tool executable was not found: {tool}")

        source = self._resolve_input(input_path, input_kind)
        output = self._resolve_output(output_path, output_kind)
        arguments: list[str] = []
        for value in argument_template:
            if "{input}" in value and source is None:
                raise ExternalToolError("This command requires an input file")
            if "{output}" in value and output is None:
                raise ExternalToolError("This command requires an output path")
            arguments.append(
                value.replace("{input}", str(source) if source else "")
                .replace("{output}", str(output) if output else "")
            )
        return (str(tool), *arguments)

    def launch_detached(
        self,
        executable: str | Path,
        argument_template: Iterable[str] = (),
        *,
        input_path: str | Path | None = None,
        output_path: str | Path | None = None,
        input_kind: str = "none",
        output_kind: str = "none",
    ) -> ToolLaunch:
        """Launch a GUI utility without waiting for it to exit."""
        command = self.build_command(
            executable,
            argument_template,
            input_path=input_path,
            output_path=output_path,
            input_kind=input_kind,
            output_kind=output_kind,
        )
        creation_flags = 0
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            process = subprocess.Popen(
                command,
                cwd=Path(command[0]).parent,
                shell=False,
                creationflags=creation_flags,
                close_fds=os.name != "nt",
            )
        except OSError as exc:
            raise ExternalToolError(f"Could not start external tool: {exc}") from exc
        return ToolLaunch(command, process.pid)

    def run(
        self,
        executable: str | Path,
        argument_template: Iterable[str],
        *,
        input_path: str | Path | None = None,
        output_path: str | Path | None = None,
        timeout: float = 300,
        input_kind: str = "file",
        output_kind: str = "optional",
    ) -> ToolResult:
        command = self.build_command(
            executable,
            argument_template,
            input_path=input_path,
            output_path=output_path,
            input_kind=input_kind,
            output_kind=output_kind,
        )
        source = self._resolve_input(input_path, input_kind)
        working_directory = source.parent if source else Path(command[0]).parent
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        started = time.monotonic()

        with self._lock:
            if self._process is not None:
                raise ExternalToolError("Another external tool is already running")
            self._cancel_requested = False
            try:
                self._process = subprocess.Popen(
                    command,
                    cwd=working_directory,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    shell=False,
                    creationflags=creation_flags,
                )
            except OSError as exc:
                raise ExternalToolError(f"Could not start external tool: {exc}") from exc
            process = self._process

        try:
            stdout, stderr = process.communicate(timeout=max(1, timeout))
        except subprocess.TimeoutExpired as exc:
            process.kill()
            stdout, stderr = process.communicate()
            raise ExternalToolError(
                f"External tool exceeded the {timeout:g}-second timeout"
            ) from exc
        finally:
            with self._lock:
                cancelled = self._cancel_requested
                self._process = None

        return ToolResult(
            command,
            process.returncode,
            stdout,
            stderr,
            time.monotonic() - started,
            cancelled,
        )

    def cancel(self) -> bool:
        """Terminate the active process, returning whether one was running."""
        with self._lock:
            if self._process is None:
                return False
            self._cancel_requested = True
            self._process.terminate()
            return True

    @staticmethod
    def _resolve_input(value: str | Path | None, kind: str = "file") -> Path | None:
        if kind not in {"file", "directory", "any", "optional", "none"}:
            raise ExternalToolError(f"Unsupported input path kind: {kind}")
        if kind == "none":
            return None
        if value is None or not str(value).strip():
            if kind not in {"none", "optional"}:
                raise ExternalToolError("This command requires an input path")
            return None
        path = Path(value).expanduser().resolve()
        if kind == "file" and not path.is_file():
            raise ExternalToolError(f"Input file was not found: {path}")
        if kind == "directory" and not path.is_dir():
            raise ExternalToolError(f"Input folder was not found: {path}")
        if kind in {"any", "optional"} and not path.exists():
            raise ExternalToolError(f"Input path was not found: {path}")
        return path

    @staticmethod
    def _resolve_output(value: str | Path | None, kind: str = "file") -> Path | None:
        if kind not in {"file", "directory", "optional", "none"}:
            raise ExternalToolError(f"Unsupported output path kind: {kind}")
        if kind == "none":
            return None
        if value is None or not str(value).strip():
            if kind not in {"none", "optional"}:
                raise ExternalToolError("This command requires an output path")
            return None
        path = Path(value).expanduser().resolve()
        if kind == "directory" and not path.is_dir():
            raise ExternalToolError(f"Output folder was not found: {path}")
        if kind != "directory" and not path.parent.is_dir():
            raise ExternalToolError(f"Output folder was not found: {path.parent}")
        return path
