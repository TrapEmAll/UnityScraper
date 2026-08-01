"""Read-first Xenia content discovery and verified save migration plans."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PROFILE_ID_RE = re.compile(r"^[0-9A-Fa-f]{16}$")
TITLE_ID_RE = re.compile(r"^[0-9A-Fa-f]{8}$")
SAVE_DIRECTORY = "00000001"
COPY_CHUNK = 1024 * 1024


class XeniaBridgeError(RuntimeError):
    """Raised when a Xenia root or migration plan is unsafe."""


@dataclass(frozen=True)
class XeniaInstallation:
    executable: Path
    root: Path
    content_root: Path | None
    variant: str


@dataclass(frozen=True)
class XeniaSave:
    profile_id: str
    title_id: str
    path: Path
    relative_path: Path
    size: int
    sha256: str


@dataclass(frozen=True)
class MigrationItem:
    source: Path
    destination: Path
    relative_path: Path
    title_id: str
    size: int
    sha256: str
    action: str
    reason: str


@dataclass(frozen=True)
class MigrationPlan:
    source_profile_id: str
    target_profile_id: str
    destination_content: Path
    items: tuple[MigrationItem, ...]

    @property
    def copy_count(self) -> int:
        return sum(item.action == "copy" for item in self.items)

    @property
    def conflict_count(self) -> int:
        return sum(item.action == "conflict" for item in self.items)


def candidate_xenia_content_roots() -> tuple[Path, ...]:
    """Return conventional Xenia content locations without creating them."""
    home = Path.home()
    documents = Path(os.environ.get("USERPROFILE", home)) / "Documents"
    candidates = (
        documents / "xenia" / "content",
        documents / "Xenia" / "content",
        home / "Documents" / "xenia" / "content",
        home / ".local" / "share" / "xenia" / "content",
        home / ".config" / "xenia" / "content",
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return tuple(unique)


def find_xenia_content_root(path: str | Path | None = None) -> Path | None:
    """Locate a user-selected or conventional Xenia content directory."""
    candidates = (Path(path).expanduser(),) if path else candidate_xenia_content_roots()
    for candidate in candidates:
        root = candidate.resolve()
        if root.is_dir() and root.name.casefold() == "content":
            return root
        nested = root / "content"
        if nested.is_dir():
            return nested.resolve()
    return None


def find_xenia_installation(path: str | Path) -> XeniaInstallation | None:
    """Find a conventional Xenia executable without searching unrelated folders."""
    selected = Path(path).expanduser().resolve()
    candidates: list[Path] = []
    if selected.is_file():
        candidates.append(selected)
        root = selected.parent
    else:
        root = selected.parent if selected.name.casefold() == "content" else selected
        names = ("xenia_canary.exe", "xenia.exe", "xenia-canary", "xenia")
        candidates.extend(root / name for name in names)
        candidates.extend(root.parent / name for name in names if selected.name.casefold() == "content")
    executable = next((item for item in candidates if item.is_file()), None)
    if executable is None:
        return None
    content = find_xenia_content_root(root)
    variant = "Canary" if "canary" in executable.name.casefold() else "Master"
    return XeniaInstallation(executable, executable.parent, content, variant)


def launch_xenia(
    installation: XeniaInstallation,
    game_path: str | Path,
    *,
    fullscreen: bool = False,
) -> dict[str, object]:
    """Launch a user-selected title through an argument list, never a shell."""
    game = Path(game_path).expanduser().resolve()
    if not installation.executable.is_file():
        raise FileNotFoundError(installation.executable)
    if not game.is_file() and not game.is_dir():
        raise FileNotFoundError(game)
    command = [str(installation.executable), str(game)]
    if fullscreen:
        command.append("--fullscreen=true")
    process = subprocess.Popen(command, cwd=installation.root)
    return {"pid": process.pid, "variant": installation.variant,
            "executable": str(installation.executable), "game": str(game)}


def scan_xenia_saves(content_root: str | Path) -> tuple[XeniaSave, ...]:
    """Index visible save packages under a Xenia content tree."""
    root = Path(content_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    results: list[XeniaSave] = []
    for profile in root.iterdir():
        profile_id = profile.name.upper()
        if not profile.is_dir() or not PROFILE_ID_RE.fullmatch(profile_id):
            continue
        for title in profile.iterdir():
            title_id = title.name.upper()
            if not title.is_dir() or not TITLE_ID_RE.fullmatch(title_id):
                continue
            save_dir = _child_named(title, SAVE_DIRECTORY)
            if not save_dir:
                continue
            for package in save_dir.rglob("*"):
                if not package.is_file():
                    continue
                results.append(
                    XeniaSave(
                        profile_id,
                        title_id,
                        package,
                        package.relative_to(profile),
                        package.stat().st_size,
                        sha256_file(package),
                    )
                )
    return tuple(sorted(results, key=lambda item: str(item.path).casefold()))


def build_migration_plan(
    sources: Iterable[tuple[str | Path, str]],
    destination_content: str | Path,
    *,
    source_profile_id: str,
    target_profile_id: str,
) -> MigrationPlan:
    """Preview copies to Xenia without changing either side."""
    source_id = _profile_id(source_profile_id)
    target_id = _profile_id(target_profile_id)
    destination_root = Path(destination_content).expanduser().resolve()
    items: list[MigrationItem] = []
    for source_value, title_value in sources:
        source = Path(source_value).expanduser().resolve()
        title_id = title_value.strip().upper()
        if not source.is_file():
            raise FileNotFoundError(source)
        if not TITLE_ID_RE.fullmatch(title_id):
            raise XeniaBridgeError(f"Invalid TitleID: {title_id}")
        relative = _save_relative_path(source, source_id, title_id)
        destination = destination_root / target_id / relative
        digest = sha256_file(source)
        action, reason = "copy", "New file"
        if destination.exists():
            if not destination.is_file():
                action, reason = "conflict", "Destination is not a file"
            elif sha256_file(destination) == digest:
                action, reason = "skip", "Identical file already exists"
            else:
                action, reason = "conflict", "Different file already exists"
        items.append(
            MigrationItem(
                source,
                destination,
                relative,
                title_id,
                source.stat().st_size,
                digest,
                action,
                reason,
            )
        )
    return MigrationPlan(source_id, target_id, destination_root, tuple(items))


def execute_migration_plan(plan: MigrationPlan) -> tuple[int, int, int]:
    """Execute only non-conflicting plan items through verified atomic copies."""
    copied = skipped = conflicts = 0
    for item in plan.items:
        if item.action == "skip":
            skipped += 1
            continue
        if item.action != "copy":
            conflicts += 1
            continue
        item.destination.parent.mkdir(parents=True, exist_ok=True)
        partial = item.destination.with_name(item.destination.name + ".partial")
        try:
            with item.source.open("rb") as source, partial.open("wb") as output:
                shutil.copyfileobj(source, output, COPY_CHUNK)
            if sha256_file(partial) != item.sha256:
                raise XeniaBridgeError(f"Copy verification failed: {item.relative_path}")
            if item.destination.exists():
                conflicts += 1
                partial.unlink(missing_ok=True)
                continue
            partial.replace(item.destination)
            copied += 1
        finally:
            partial.unlink(missing_ok=True)
    return copied, skipped, conflicts


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(COPY_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _save_relative_path(source: Path, profile_id: str, title_id: str) -> Path:
    parts = source.parts
    folded = [part.casefold() for part in parts]
    try:
        profile_index = folded.index(profile_id.casefold())
        relative = Path(*parts[profile_index + 1 :])
        if (
            len(relative.parts) >= 3
            and relative.parts[0].casefold() == title_id.casefold()
            and relative.parts[1].casefold() == SAVE_DIRECTORY.casefold()
        ):
            return relative
    except ValueError:
        pass
    return Path(title_id) / SAVE_DIRECTORY / source.name


def _profile_id(value: str) -> str:
    normalized = value.strip().upper()
    if not PROFILE_ID_RE.fullmatch(normalized):
        raise XeniaBridgeError(f"Invalid profile ID: {value}")
    return normalized


def _child_named(parent: Path, name: str) -> Path | None:
    expected = name.casefold()
    try:
        return next(child for child in parent.iterdir() if child.name.casefold() == expected)
    except (OSError, StopIteration):
        return None
