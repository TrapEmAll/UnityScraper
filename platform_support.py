"""Small operating-system integration helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def desktop_font_family() -> str:
    """Return a sensible UI font family for the current desktop."""
    if os.name == "nt":
        return "Segoe UI"
    if sys.platform == "darwin":
        return "Helvetica Neue"
    return "DejaVu Sans"


def path_opener_command(
    *,
    os_name: str | None = None,
    platform_name: str | None = None,
) -> list[str] | None:
    """Return the available command used to open files on this platform."""
    current_os = os_name or os.name
    current_platform = platform_name or sys.platform
    if current_os == "nt":
        return None
    if current_platform == "darwin":
        return ["open"]
    for candidate in ("xdg-open", "gio"):
        if shutil.which(candidate):
            return [candidate, "open"] if candidate == "gio" else [candidate]
    return None


def open_path(path: Path | str) -> None:
    """Open a file or directory with the desktop's default application."""
    target = Path(path).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(target)

    if os.name == "nt":
        os.startfile(str(target))  # type: ignore[attr-defined]
        return

    command = path_opener_command()
    if command is None:
        raise RuntimeError("No desktop file opener was found (install xdg-utils or GLib).")
    subprocess.Popen(
        [*command, str(target)],
        close_fds=True,
        start_new_session=True,
    )
