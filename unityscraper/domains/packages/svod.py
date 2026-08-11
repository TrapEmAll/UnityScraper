"""SVOD/Games-on-Demand inspection, verification, and payload extraction."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .errors import InvalidPackageError
from .stfs import STFS_MAGICS, inspect_stfs

BLOCK_SIZE = 0x1000
BLOCKS_PER_FILE = 0xA1C4
HASHES_PER_TABLE = 0xCC
MAX_DATA_FILES = 9999


@dataclass(frozen=True)
class SvodPackage:
    header_path: Path
    data_directory: Path | None
    magic: str
    title_id: str
    display_name: str
    block_count: int
    data_file_count: int
    data_size: int
    shifted: bool
    deviation: int
    data_files: tuple[Path, ...]


@dataclass(frozen=True)
class SvodIntegrityReport:
    checked_blocks: int
    valid_blocks: int
    mismatched_blocks: int
    missing_blocks: int

    @property
    def valid(self) -> bool:
        return self.mismatched_blocks == 0 and self.missing_blocks == 0


def inspect_svod(
    header_path: str | Path,
    data_directory: str | Path | None = None,
) -> SvodPackage:
    source = Path(header_path).expanduser().resolve()
    with source.open("rb") as handle:
        header = handle.read(0x3AD)
    if len(header) < 0x3AD or header[:4] not in STFS_MAGICS:
        raise InvalidPackageError("Not a supported SVOD header")
    if header[0x379:0x37D] != b"\x24\x05\x05\x11":
        raise InvalidPackageError("Package does not contain an SVOD descriptor")
    shifted = bool(header[0x391] & 0x40)
    block_count = int.from_bytes(header[0x392:0x395], "big")
    deviation = int.from_bytes(header[0x395:0x399], "little") if shifted else 0
    data_file_count = int.from_bytes(header[0x39D:0x3A1], "big")
    data_size = int.from_bytes(header[0x3A1:0x3A9], "big")
    if block_count <= 0:
        raise InvalidPackageError("SVOD block count is invalid")
    if data_file_count <= 0 or data_file_count > MAX_DATA_FILES:
        raise InvalidPackageError("SVOD data-file count is invalid")
    directory = _resolve_data_directory(source, data_directory)
    data_files: tuple[Path, ...] = ()
    if directory is not None:
        files = tuple(directory / f"Data{index:04d}" for index in range(data_file_count))
        missing = [item.name for item in files if not item.is_file()]
        if missing:
            raise InvalidPackageError(f"SVOD data files are missing: {', '.join(missing[:5])}")
        data_files = files
    metadata = inspect_stfs(source)
    return SvodPackage(
        source,
        directory,
        metadata.magic,
        metadata.title_id,
        metadata.display_name or metadata.title_name,
        block_count,
        data_file_count,
        data_size,
        shifted,
        deviation,
        data_files,
    )


def verify_svod(
    header_path: str | Path,
    data_directory: str | Path | None = None,
) -> SvodIntegrityReport:
    package = inspect_svod(header_path, data_directory)
    if not package.data_files:
        raise InvalidPackageError("Choose the SVOD data directory to verify its payload")
    checked = valid = mismatched = missing = 0
    handles = [path.open("rb") for path in package.data_files]
    try:
        for block in range(package.block_count):
            checked += 1
            handle = handles[block // BLOCKS_PER_FILE]
            try:
                stored = _read_exact(handle, _hash_offset(block, 0), 0x14)
                data = _read_exact(handle, _data_offset(block), BLOCK_SIZE)
            except InvalidPackageError:
                missing += 1
                continue
            if hashlib.sha1(data).digest() == stored:
                valid += 1
            else:
                mismatched += 1
    finally:
        for handle in handles:
            handle.close()
    return SvodIntegrityReport(checked, valid, mismatched, missing)


def extract_svod_payload(
    header_path: str | Path,
    destination: str | Path,
    data_directory: str | Path | None = None,
) -> Path:
    package = inspect_svod(header_path, data_directory)
    if not package.data_files:
        raise InvalidPackageError("Choose the SVOD data directory to extract its payload")
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial")
    handles = [path.open("rb") for path in package.data_files]
    try:
        with temporary.open("xb") as output:
            remaining = package.data_size or package.block_count * BLOCK_SIZE
            for block in range(package.block_count):
                handle = handles[block // BLOCKS_PER_FILE]
                chunk = _read_exact(handle, _data_offset(block), BLOCK_SIZE)
                write_size = min(remaining, BLOCK_SIZE)
                output.write(chunk[:write_size])
                remaining -= write_size
                if remaining <= 0:
                    break
        if target.exists():
            raise FileExistsError(target)
        temporary.replace(target)
    finally:
        for handle in handles:
            handle.close()
        temporary.unlink(missing_ok=True)
    return target


def _resolve_data_directory(source: Path, value: str | Path | None) -> Path | None:
    if value is not None:
        directory = Path(value).expanduser().resolve()
        if not directory.is_dir():
            raise FileNotFoundError(directory)
        return directory
    for candidate in (
        source.with_name(source.name + ".data"),
        source.parent / f"{source.stem}.data",
        source.parent / "data",
    ):
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _data_offset(block: int) -> int:
    local = block % BLOCKS_PER_FILE
    return 0x2000 + BLOCK_SIZE * local + BLOCK_SIZE * (local // HASHES_PER_TABLE)


def _hash_offset(block: int, level: int) -> int:
    local = block % BLOCKS_PER_FILE
    if level == 0:
        return 0x1000 + 0xCD000 * (local // HASHES_PER_TABLE) + 0x14 * (local % HASHES_PER_TABLE)
    if level == 1:
        return 0x14 * (local // HASHES_PER_TABLE)
    raise InvalidPackageError("Unsupported SVOD hash-tree level")


def _read_exact(handle: BinaryIO, offset: int, size: int) -> bytes:
    handle.seek(offset)
    value = handle.read(size)
    if len(value) != size:
        raise InvalidPackageError("SVOD data file is truncated")
    return value


__all__ = [
    "SvodIntegrityReport",
    "SvodPackage",
    "extract_svod_payload",
    "inspect_svod",
    "verify_svod",
]
