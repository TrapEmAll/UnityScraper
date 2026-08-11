"""Bounded GDF/XISO image browsing and extraction."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable

from .errors import InvalidPackageError, UnsafeArchiveError

GDF_MAGIC = b"MICROSOFT*XBOX*MEDIA"
SECTOR_SIZE = 0x800
MAGIC_OFFSETS = (0, 0x10000, 0x1FB20, 0x30600, 0xFDA0000)
MAX_ENTRIES = 500_000
MAX_DEPTH = 128


@dataclass(frozen=True)
class GdfEntry:
    path: str
    name: str
    is_directory: bool
    start_sector: int
    size: int
    entry_offset: int


@dataclass(frozen=True)
class GdfImage:
    path: Path
    base_offset: int
    deviation: int
    root_sector: int
    root_size: int
    entries: tuple[GdfEntry, ...]


def inspect_gdf(path: str | Path, *, deviation: int = 0) -> GdfImage:
    source = Path(path).expanduser().resolve()
    size = source.stat().st_size
    with source.open("rb") as handle:
        base = _find_magic(handle, size)
        handle.seek(base + len(GDF_MAGIC))
        descriptor = handle.read(17)
        if len(descriptor) != 17:
            raise InvalidPackageError("GDF volume descriptor is truncated")
        root_sector = int.from_bytes(descriptor[:4], "little")
        root_size = int.from_bytes(descriptor[4:8], "little", signed=True)
        if root_size < 0:
            raise InvalidPackageError("GDF root directory size is invalid")
        entries = _read_directory(
            handle,
            size,
            base,
            deviation,
            root_sector,
            root_size,
            "",
            0,
            set(),
        )
    if len(entries) > MAX_ENTRIES:
        raise InvalidPackageError("GDF directory exceeds the safety limit")
    return GdfImage(source, base, deviation, root_sector, root_size, tuple(entries))


def extract_gdf(
    path: str | Path,
    destination: str | Path,
    selected_paths: Iterable[str] | None = None,
    *,
    deviation: int = 0,
    max_output_size: int = 128 * 1024 * 1024 * 1024,
) -> dict[str, object]:
    image = inspect_gdf(path, deviation=deviation)
    target = Path(destination).expanduser().resolve()
    requested = {item.replace("\\", "/").strip("/") for item in selected_paths or ()}
    files = [
        entry
        for entry in image.entries
        if not entry.is_directory and (not requested or entry.path in requested)
    ]
    missing = requested - {entry.path for entry in files}
    if missing:
        raise InvalidPackageError(f"GDF entries were not found: {', '.join(sorted(missing)[:5])}")
    if sum(entry.size for entry in files) > max_output_size:
        raise InvalidPackageError("Selected GDF output exceeds the safety limit")
    target.mkdir(parents=True, exist_ok=True)
    extracted: list[dict[str, object]] = []
    with image.path.open("rb") as handle:
        for entry in files:
            relative = _safe_member(entry.path)
            output = (target / relative).resolve()
            if not output.is_relative_to(target):
                raise UnsafeArchiveError(f"GDF path escapes destination: {entry.path}")
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_name(output.name + ".partial")
            digest = hashlib.sha256()
            data_offset = _data_offset(image.base_offset, deviation, entry.start_sector)
            if data_offset < 0 or data_offset + entry.size > image.path.stat().st_size:
                raise InvalidPackageError(f"GDF data points outside the image: {entry.path}")
            handle.seek(data_offset)
            remaining = entry.size
            try:
                with temporary.open("xb") as destination_handle:
                    while remaining:
                        chunk = handle.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise InvalidPackageError(f"GDF file is truncated: {entry.path}")
                        destination_handle.write(chunk)
                        digest.update(chunk)
                        remaining -= len(chunk)
                if output.exists():
                    raise FileExistsError(output)
                temporary.replace(output)
            finally:
                temporary.unlink(missing_ok=True)
            extracted.append(
                {
                    "path": entry.path,
                    "output": str(output),
                    "size": entry.size,
                    "sha256": digest.hexdigest(),
                }
            )
    return {"source": str(image.path), "extracted": extracted}


def _find_magic(handle: BinaryIO, size: int) -> int:
    for offset in MAGIC_OFFSETS:
        if offset + len(GDF_MAGIC) > size:
            continue
        handle.seek(offset)
        if handle.read(len(GDF_MAGIC)) == GDF_MAGIC:
            return offset
    raise InvalidPackageError("Not a supported GDF/XISO image")


def _read_directory(
    handle: BinaryIO,
    image_size: int,
    base: int,
    deviation: int,
    sector: int,
    size: int,
    parent: str,
    depth: int,
    visited_directories: set[tuple[int, int]],
) -> list[GdfEntry]:
    if depth > MAX_DEPTH:
        raise InvalidPackageError("GDF directory nesting exceeds the safety limit")
    directory_key = (sector, size)
    if directory_key in visited_directories:
        raise InvalidPackageError("GDF directory graph contains a loop")
    visited_directories.add(directory_key)
    directory_offset = _data_offset(base, deviation, sector)
    if directory_offset < 0 or directory_offset + size > image_size:
        raise InvalidPackageError("GDF directory points outside the image")
    entries: list[GdfEntry] = []
    pending = [0]
    visited_nodes: set[int] = set()
    while pending:
        node = pending.pop()
        if node in visited_nodes:
            continue
        visited_nodes.add(node)
        offset = directory_offset + node * 4
        if offset < directory_offset or offset + 14 > directory_offset + size:
            raise InvalidPackageError("GDF directory node points outside its table")
        handle.seek(offset)
        header = handle.read(14)
        left = int.from_bytes(header[:2], "little")
        right = int.from_bytes(header[2:4], "little")
        start_sector = int.from_bytes(header[4:8], "little")
        entry_size = int.from_bytes(header[8:12], "little", signed=True)
        attributes = header[12]
        name_length = header[13]
        if (
            entry_size < 0
            or name_length in {0, 0xFF}
            or offset + 14 + name_length > directory_offset + size
        ):
            raise InvalidPackageError("GDF directory entry is invalid")
        name = handle.read(name_length).decode("ascii", errors="replace")
        if any(character in name for character in "\\/\0") or name in {".", ".."}:
            raise InvalidPackageError("GDF directory contains an unsafe name")
        full_path = f"{parent}/{name}" if parent else name
        entry = GdfEntry(full_path, name, bool(attributes & 0x10), start_sector, entry_size, offset)
        entries.append(entry)
        if len(entries) > MAX_ENTRIES:
            raise InvalidPackageError("GDF directory exceeds the safety limit")
        if left:
            pending.append(left)
        if right:
            pending.append(right)
    for entry in tuple(entries):
        if entry.is_directory:
            entries.extend(
                _read_directory(
                    handle,
                    image_size,
                    base,
                    deviation,
                    entry.start_sector,
                    entry.size,
                    entry.path,
                    depth + 1,
                    visited_directories,
                )
            )
    visited_directories.remove(directory_key)
    return entries


def _data_offset(base: int, deviation: int, sector: int) -> int:
    result = sector * SECTOR_SIZE
    if deviation:
        result -= (deviation - 1) << 12
    if base > 0x10000:
        result += base
    return result


def _safe_member(value: str) -> Path:
    pure = PurePosixPath(value.replace("\\", "/"))
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise UnsafeArchiveError(f"Unsafe GDF path: {value}")
    if ":" in pure.parts[0]:
        raise UnsafeArchiveError(f"Unsafe GDF path: {value}")
    return Path(*pure.parts)


__all__ = ["GdfEntry", "GdfImage", "extract_gdf", "inspect_gdf"]
