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
    ) -> tuple[str, ...]:
        tool = Path(executable).expanduser().resolve()
        if not tool.is_file():
            raise ExternalToolError(f"Tool executable was not found: {tool}")

        source = self._resolve_input(input_path)
        output = self._resolve_output(output_path)
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

    def run(
        self,
        executable: str | Path,
        argument_template: Iterable[str],
        *,
        input_path: str | Path | None = None,
        output_path: str | Path | None = None,
        timeout: float = 300,
    ) -> ToolResult:
        command = self.build_command(
            executable,
            argument_template,
            input_path=input_path,
            output_path=output_path,
        )
        source = self._resolve_input(input_path)
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
    def _resolve_input(value: str | Path | None) -> Path | None:
        if value is None or not str(value).strip():
            return None
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise ExternalToolError(f"Input file was not found: {path}")
        return path

    @staticmethod
    def _resolve_output(value: str | Path | None) -> Path | None:
        if value is None or not str(value).strip():
            return None
        path = Path(value).expanduser().resolve()
        if not path.parent.is_dir():
            raise ExternalToolError(f"Output folder was not found: {path.parent}")
        return path
