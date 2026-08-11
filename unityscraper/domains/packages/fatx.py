"""Read-first FATX image browsing, extraction, and guarded replacement."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable

from .errors import InvalidPackageError, UnsafeArchiveError

FATX_MAGIC = b"FATX"
SECTOR_SIZE = 0x200
ENTRY_SIZE = 0x40
MAX_ENTRIES = 1_000_000
MAX_DEPTH = 128
KNOWN_PARTITIONS = (
    ("Memory Unit Content", 0x7FF000),
    ("Hard Drive System", 0x118EB0000),
    ("Hard Drive Compatibility", 0x120EB0000),
    ("Hard Drive Content", 0x130EB0000),
    ("USB Cache", 0x8000400),
    ("USB Content", 0x20000000),
    ("Image", 0),
)


@dataclass(frozen=True)
class FatxPartition:
    name: str
    offset: int
    size: int
    sectors_per_block: int
    block_size: int
    fat_entry_size: int
    fat_size: int
    data_offset: int
    root_block: int


@dataclass(frozen=True)
class FatxEntry:
    partition: str
    path: str
    name: str
    is_directory: bool
    start_block: int
    size: int
    entry_offset: int
    blocks: tuple[int, ...]


@dataclass(frozen=True)
class FatxImage:
    path: Path
    partitions: tuple[FatxPartition, ...]
    entries: tuple[FatxEntry, ...]


def inspect_fatx(path: str | Path) -> FatxImage:
    source = Path(path).expanduser().resolve()
    image_size = source.stat().st_size
    offsets = [(name, offset) for name, offset in KNOWN_PARTITIONS if offset + 4 <= image_size]
    partitions: list[FatxPartition] = []
    entries: list[FatxEntry] = []
    with source.open("rb") as handle:
        valid_offsets = []
        for name, offset in offsets:
            handle.seek(offset)
            if handle.read(4) == FATX_MAGIC:
                valid_offsets.append((name, offset))
        for index, (name, offset) in enumerate(valid_offsets):
            next_offset = min(
                (candidate for _, candidate in valid_offsets if candidate > offset),
                default=image_size,
            )
            partition = _read_partition(handle, name, offset, next_offset - offset)
            partitions.append(partition)
            entries.extend(
                _read_directory(
                    handle,
                    partition,
                    partition.root_block,
                    partition.name,
                    0,
                    set(),
                )
            )
    if not partitions:
        raise InvalidPackageError("No supported FATX partitions were found")
    return FatxImage(source, tuple(partitions), tuple(entries))


def extract_fatx(
    path: str | Path,
    destination: str | Path,
    selected_paths: Iterable[str] | None = None,
) -> dict[str, object]:
    image = inspect_fatx(path)
    target = Path(destination).expanduser().resolve()
    requested = {item.replace("\\", "/").strip("/") for item in selected_paths or ()}
    files = [
        entry
        for entry in image.entries
        if not entry.is_directory and (not requested or entry.path in requested)
    ]
    missing = requested - {entry.path for entry in files}
    if missing:
        raise InvalidPackageError(f"FATX entries were not found: {', '.join(sorted(missing)[:5])}")
    by_name = {partition.name: partition for partition in image.partitions}
    target.mkdir(parents=True, exist_ok=True)
    extracted: list[dict[str, object]] = []
    with image.path.open("rb") as handle:
        for entry in files:
            output = (target / _safe_member(entry.path)).resolve()
            if not output.is_relative_to(target):
                raise UnsafeArchiveError(f"FATX path escapes destination: {entry.path}")
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_name(output.name + ".partial")
            partition = by_name[entry.partition]
            remaining = entry.size
            try:
                with temporary.open("xb") as destination_handle:
                    for block in entry.blocks:
                        handle.seek(_block_offset(partition, block))
                        chunk = handle.read(min(remaining, partition.block_size))
                        if len(chunk) != min(remaining, partition.block_size):
                            raise InvalidPackageError(f"FATX file is truncated: {entry.path}")
                        destination_handle.write(chunk)
                        remaining -= len(chunk)
                if remaining:
                    raise InvalidPackageError(f"FATX chain ends early: {entry.path}")
                if output.exists():
                    raise FileExistsError(output)
                temporary.replace(output)
            finally:
                temporary.unlink(missing_ok=True)
            extracted.append({"path": entry.path, "output": str(output), "size": entry.size})
    return {"source": str(image.path), "extracted": extracted}


def replace_fatx_file(
    image_path: str | Path,
    internal_path: str,
    replacement: str | Path,
    *,
    output: str | Path,
) -> Path:
    """Replace a FATX file only when it fits the existing chain, into a new image."""
    source = Path(image_path).expanduser().resolve()
    incoming = Path(replacement).expanduser().resolve()
    target = Path(output).expanduser().resolve()
    if target == source:
        raise InvalidPackageError("FATX writes require a separate output image")
    image = inspect_fatx(source)
    normalized = internal_path.replace("\\", "/").strip("/")
    entry = next(
        (item for item in image.entries if item.path == normalized and not item.is_directory), None
    )
    if entry is None:
        raise InvalidPackageError(f"FATX file was not found: {normalized}")
    partition = next(item for item in image.partitions if item.name == entry.partition)
    if incoming.stat().st_size > len(entry.blocks) * partition.block_size:
        raise InvalidPackageError("Replacement exceeds the existing FATX allocation")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".partial", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        with incoming.open("rb") as source_handle, temporary.open("r+b") as handle:
            remaining = incoming.stat().st_size
            for block in entry.blocks:
                chunk = (
                    source_handle.read(min(remaining, partition.block_size)) if remaining else b""
                )
                handle.seek(_block_offset(partition, block))
                handle.write(chunk.ljust(partition.block_size, b"\0"))
                remaining -= len(chunk)
            handle.seek(entry.entry_offset + 0x30)
            handle.write(incoming.stat().st_size.to_bytes(4, "big"))
        if target.exists():
            raise FileExistsError(target)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _read_partition(handle: BinaryIO, name: str, offset: int, size: int) -> FatxPartition:
    handle.seek(offset + 8)
    values = handle.read(8)
    if len(values) != 8:
        raise InvalidPackageError("FATX partition header is truncated")
    sectors_per_block = int.from_bytes(values[:4], "big")
    root_block = int.from_bytes(values[4:], "big")
    if sectors_per_block <= 0 or sectors_per_block > 0x10000:
        raise InvalidPackageError("FATX sectors-per-block value is invalid")
    block_size = sectors_per_block * SECTOR_SIZE
    block_count = size // block_size
    fat_entry_size = 2 if block_count < 0xFFF5 else 4
    raw_fat_size = block_count * fat_entry_size
    fat_size = raw_fat_size + (0x1000 - raw_fat_size % 0x1000)
    data_offset = offset + 0x1000 + fat_size
    partition = FatxPartition(
        name,
        offset,
        size,
        sectors_per_block,
        block_size,
        fat_entry_size,
        fat_size,
        data_offset,
        root_block,
    )
    _block_offset(partition, root_block)
    return partition


def _read_directory(
    handle: BinaryIO,
    partition: FatxPartition,
    start_block: int,
    parent: str,
    depth: int,
    visited_directories: set[int],
) -> list[FatxEntry]:
    if depth > MAX_DEPTH or start_block in visited_directories:
        raise InvalidPackageError("FATX directory graph is invalid")
    visited_directories.add(start_block)
    entries: list[FatxEntry] = []
    for directory_block in _block_chain(handle, partition, start_block):
        base = _block_offset(partition, directory_block)
        for index in range(partition.block_size // ENTRY_SIZE):
            offset = base + index * ENTRY_SIZE
            handle.seek(offset)
            data = handle.read(ENTRY_SIZE)
            name_length = data[0] if data else 0
            if name_length == 0xE5:
                continue
            if name_length in {0, 0xFF}:
                break
            if name_length > 0x2A or len(data) != ENTRY_SIZE:
                raise InvalidPackageError("FATX directory entry is invalid")
            name = data[2 : 2 + name_length].decode("ascii", errors="replace")
            if any(character in name for character in "\\/\0") or name in {".", ".."}:
                raise InvalidPackageError("FATX directory contains an unsafe name")
            start = int.from_bytes(data[0x2C:0x30], "big")
            size = int.from_bytes(data[0x30:0x34], "big")
            is_directory = bool(data[1] & 0x10)
            blocks = _block_chain(handle, partition, start)
            full_path = f"{parent}/{name}" if parent else name
            entry = FatxEntry(
                partition.name, full_path, name, is_directory, start, size, offset, blocks
            )
            entries.append(entry)
            if len(entries) > MAX_ENTRIES:
                raise InvalidPackageError("FATX directory exceeds the safety limit")
    for entry in tuple(entries):
        if entry.is_directory:
            entries.extend(
                _read_directory(
                    handle,
                    partition,
                    entry.start_block,
                    entry.path,
                    depth + 1,
                    visited_directories,
                )
            )
    visited_directories.remove(start_block)
    return entries


def _block_chain(handle: BinaryIO, partition: FatxPartition, start: int) -> tuple[int, ...]:
    end = 0xFFFF if partition.fat_entry_size == 2 else 0xFFFFFFFF
    blocks: list[int] = []
    visited: set[int] = set()
    current = start
    max_blocks = partition.size // partition.block_size
    while current not in {0, end}:
        if current >= max_blocks or current in visited:
            raise InvalidPackageError("FATX allocation chain is invalid")
        visited.add(current)
        blocks.append(current)
        handle.seek(partition.offset + 0x1000 + current * partition.fat_entry_size)
        raw = handle.read(partition.fat_entry_size)
        if len(raw) != partition.fat_entry_size:
            raise InvalidPackageError("FATX allocation table is truncated")
        current = int.from_bytes(raw, "big")
    return tuple(blocks)


def _block_offset(partition: FatxPartition, block: int) -> int:
    max_blocks = partition.size // partition.block_size
    if block <= 0 or block >= max_blocks:
        raise InvalidPackageError("FATX block points outside the partition")
    return partition.data_offset + (block - 1) * partition.block_size


def _safe_member(value: str) -> Path:
    pure = PurePosixPath(value.replace("\\", "/"))
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise UnsafeArchiveError(f"Unsafe FATX path: {value}")
    if ":" in pure.parts[0]:
        raise UnsafeArchiveError(f"Unsafe FATX path: {value}")
    return Path(*pure.parts)


__all__ = [
    "FatxEntry",
    "FatxImage",
    "FatxPartition",
    "extract_fatx",
    "inspect_fatx",
    "replace_fatx_file",
]
