"""Bounded STFS parsing, fragmented block traversal, and integrity checks.

The block geometry follows Dalavin's GPLv3 X360 library while using a new,
cross-platform Python implementation with explicit bounds at every file read.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterable

from .errors import InvalidPackageError, UnsafeArchiveError
from .models import (
    StfsBlockVerification,
    StfsEntry,
    StfsHashRecord,
    StfsIntegrityReport,
    StfsPackage,
)

STFS_MAGICS = {b"CON ", b"LIVE", b"PIRS"}
CONTENT_TYPES = {
    0x00000001: ("Saved Game", "00000001"),
    0x00000002: ("DLC", "00000002"),
    0x00005000: ("Original Xbox Game", "00005000"),
    0x00007000: ("Xbox 360 Game", "00007000"),
    0x000B0000: ("Title Update", "000B0000"),
    0x000D0000: ("Xbox Live Arcade", "000D0000"),
    0x00010000: ("Profile", "00010000"),
}
STFS_END = 0xFFFFFF
BLOCK_SIZE = 0x1000
LEVEL0_BLOCKS = 0xAA
LEVEL1_BLOCKS = 0x70E4
MAX_BLOCKS = 0x4AF768


def _read_utf16be(data: bytes) -> str:
    return data.decode("utf-16-be", errors="ignore").split("\x00", 1)[0].strip()


def _read_exact(handle: BinaryIO, offset: int, size: int, package_size: int) -> bytes:
    if offset < 0 or size < 0 or offset + size > package_size:
        raise InvalidPackageError("STFS structure points outside the package")
    handle.seek(offset)
    value = handle.read(size)
    if len(value) != size:
        raise InvalidPackageError("STFS package is truncated")
    return value


@dataclass(frozen=True)
class StfsLayout:
    magic: bytes
    header_size: int
    block_separation: int
    table_blocks: int
    table_start: int
    block_count: int
    package_size: int
    shift: int
    top_table_index: int

    @property
    def base_offset(self) -> int:
        return (self.header_size + 0xFFF) & 0xFFFFF000

    @property
    def structure_type(self) -> int:
        return self.shift

    @property
    def spaces(self) -> tuple[int, int]:
        return (0xAB, 0x718F) if self.shift == 0 else (0xAC, 0x723A)

    def data_block(self, block: int) -> int:
        self._validate_block(block)
        result = (((block // LEVEL0_BLOCKS) + 1) << self.shift) + block
        if block >= LEVEL0_BLOCKS:
            result += ((block // LEVEL1_BLOCKS) + 1) << self.shift
        if block >= LEVEL1_BLOCKS:
            result += 1 << self.shift
        return result

    def data_offset(self, block: int) -> int:
        return self.base_offset + self.data_block(block) * BLOCK_SIZE

    def base_hash_block(self, block: int, level: int) -> int:
        self._validate_block(block)
        space0, space1 = self.spaces
        if level == 0:
            result = (block // LEVEL0_BLOCKS) * space0
            if block >= LEVEL0_BLOCKS:
                result += ((block // LEVEL1_BLOCKS) + 1) << self.shift
                if block >= LEVEL1_BLOCKS:
                    result += 1 << self.shift
            return result
        if level == 1:
            if block < LEVEL1_BLOCKS:
                return space0
            return space1 * (block // LEVEL1_BLOCKS) + (1 << self.shift)
        if level == 2:
            return space1
        raise InvalidPackageError("Unsupported STFS hash-tree level")

    def base_hash_offset(self, block: int, level: int) -> int:
        entry = (
            block % LEVEL0_BLOCKS
            if level == 0
            else (block // LEVEL0_BLOCKS) % LEVEL0_BLOCKS
            if level == 1
            else (block // LEVEL1_BLOCKS) % LEVEL0_BLOCKS
        )
        return self.base_offset + self.base_hash_block(block, level) * BLOCK_SIZE + entry * 0x18

    def active_hash_table_offset(self, handle: BinaryIO, block: int, level: int) -> int:
        table_index = self._active_table_index(handle, block, level)
        return (
            self.base_offset
            + self.base_hash_block(block, level) * BLOCK_SIZE
            + table_index * BLOCK_SIZE
        )

    def hash_record(self, handle: BinaryIO, block: int, level: int = 0) -> StfsHashRecord:
        table_index = self._active_table_index(handle, block, level)
        offset = self.base_hash_offset(block, level) + table_index * BLOCK_SIZE
        raw = _read_exact(handle, offset, 0x18, self.package_size)
        flags = int.from_bytes(raw[0x14:0x18], "big")
        return StfsHashRecord(
            block=block,
            level=level,
            stored_sha1=raw[:0x14].hex(),
            status=(flags >> 30) & 0x3,
            next_block=flags & 0xFFFFFF,
            table_index=(flags >> 30) & 0x1,
            offset=offset,
        )

    def block_chain(
        self,
        handle: BinaryIO,
        start: int,
        count: int,
        *,
        consecutive: bool = False,
    ) -> tuple[int, ...]:
        if count < 0 or count > self.block_count:
            raise InvalidPackageError("STFS block-chain length is invalid")
        if count == 0:
            return ()
        self._validate_allocated_block(start)
        if consecutive:
            end = start + count
            if end > self.block_count:
                raise InvalidPackageError("STFS consecutive allocation exceeds the package")
            return tuple(range(start, end))

        blocks: list[int] = []
        visited: set[int] = set()
        current = start
        for index in range(count):
            self._validate_allocated_block(current)
            if current in visited:
                raise InvalidPackageError("STFS block chain contains a loop")
            visited.add(current)
            blocks.append(current)
            if index == count - 1:
                break
            record = self.hash_record(handle, current, 0)
            if record.next_block == STFS_END:
                raise InvalidPackageError("STFS block chain ends before its declared length")
            current = record.next_block
        return tuple(blocks)

    def _active_table_index(self, handle: BinaryIO, block: int, level: int) -> int:
        if self.shift == 0:
            return 0
        if level == 2:
            return self.top_table_index
        if level == 1:
            if self.block_count > LEVEL1_BLOCKS:
                return self.hash_record(handle, block, 2).table_index
            return self.top_table_index
        if level == 0:
            if self.block_count > LEVEL0_BLOCKS:
                return self.hash_record(handle, block, 1).table_index
            return self.top_table_index
        raise InvalidPackageError("Unsupported STFS hash-tree level")

    def _validate_block(self, block: int) -> None:
        if block < 0 or block >= MAX_BLOCKS:
            raise InvalidPackageError("STFS block number is outside the supported range")

    def _validate_allocated_block(self, block: int) -> None:
        self._validate_block(block)
        if block >= self.block_count:
            raise InvalidPackageError("STFS block points beyond the allocated block count")


def read_stfs_layout(path: str | Path) -> StfsLayout:
    package = Path(path)
    package_size = package.stat().st_size
    with package.open("rb") as handle:
        header = _read_exact(handle, 0, 0x3AD, package_size)
    if header[:4] not in STFS_MAGICS:
        raise InvalidPackageError("Not a supported STFS package")
    if int.from_bytes(header[0x3A9:0x3AD], "big"):
        raise InvalidPackageError("SVOD packages do not contain an STFS file table")
    if header[0x379] != 0x24 or header[0x37A] != 0:
        raise InvalidPackageError("STFS volume descriptor is invalid")

    header_size = int.from_bytes(header[0x340:0x344], "big")
    separation = header[0x37B] & 0x3
    block_count = int.from_bytes(header[0x395:0x399], "big")
    if block_count <= 0 or block_count >= MAX_BLOCKS:
        raise InvalidPackageError("STFS allocated block count is invalid")
    shift = separation & 1
    top_index = (separation >> 1) & 1
    table_start = int.from_bytes(header[0x37E:0x381], "little")
    count_raw = header[0x37C:0x37E]
    candidates = tuple(
        dict.fromkeys((int.from_bytes(count_raw, "little"), int.from_bytes(count_raw, "big")))
    )
    table_blocks = 0
    for candidate in candidates:
        if not 0 < candidate <= 0x3FF:
            continue
        layout = StfsLayout(
            header[:4],
            header_size,
            separation,
            candidate,
            table_start,
            block_count,
            package_size,
            shift,
            top_index,
        )
        try:
            if layout.data_offset(table_start) + BLOCK_SIZE <= package_size:
                table_blocks = candidate
                break
        except InvalidPackageError:
            continue
    if not table_blocks:
        raise InvalidPackageError("STFS file-table size is invalid")
    return StfsLayout(
        header[:4],
        header_size,
        separation,
        table_blocks,
        table_start,
        block_count,
        package_size,
        shift,
        top_index,
    )


def inspect_stfs(path: str | Path) -> StfsPackage:
    package_path = Path(path)
    with package_path.open("rb") as handle:
        header = handle.read(0x1791)
    if len(header) < 0x1791 or header[:4] not in STFS_MAGICS:
        raise InvalidPackageError(f"{package_path.name} is not a supported STFS package")
    content_type = int.from_bytes(header[0x344:0x348], "big")
    content = CONTENT_TYPES.get(content_type)
    if content is None:
        raise InvalidPackageError(f"Unsupported STFS content type 0x{content_type:08X}")
    title_id = header[0x360:0x364].hex().upper()
    if title_id == "00000000" or len(title_id) != 8:
        raise InvalidPackageError("STFS package does not contain a usable TitleID")
    header_size = int.from_bytes(header[0x340:0x344], "big")
    block_count = int.from_bytes(header[0x395:0x399], "big")
    separation = header[0x37B] & 0x3
    structure_type = separation & 1
    return StfsPackage(
        path=package_path,
        magic=header[:4].decode("ascii").strip(),
        content_type=content_type,
        content_label=content[0],
        content_directory=content[1],
        title_id=title_id,
        media_id=header[0x354:0x358].hex().upper(),
        disc_number=header[0x366],
        disc_count=header[0x367],
        display_name=_read_utf16be(header[0x411:0x511]),
        title_name=_read_utf16be(header[0x1691:0x1791]),
        size=package_path.stat().st_size,
        save_game_id=header[0x368:0x36C].hex().upper(),
        console_id=header[0x36C:0x371].hex().upper(),
        profile_id=header[0x371:0x379].hex().upper(),
        device_id=header[0x3FD:0x411].hex().upper(),
        header_size=header_size,
        block_count=block_count,
        structure_type=structure_type,
    )


def list_stfs_entries(path: str | Path, max_entries: int = 100_000) -> list[StfsEntry]:
    package = Path(path)
    layout = read_stfs_layout(package)
    with package.open("rb") as handle:
        table_chain = layout.block_chain(
            handle, layout.table_start, layout.table_blocks, consecutive=False
        )
        raw_entries: list[dict[str, Any]] = []
        for logical_block in table_chain:
            table = _read_exact(
                handle, layout.data_offset(logical_block), BLOCK_SIZE, layout.package_size
            )
            for entry_offset in range(0, BLOCK_SIZE, 0x40):
                data = table[entry_offset : entry_offset + 0x40]
                if not any(data):
                    continue
                flags = data[0x28]
                name_length = flags & 0x3F
                if name_length == 0 or name_length > 0x28:
                    continue
                raw_entries.append(
                    {
                        "name": data[:name_length].decode("utf-8", errors="replace"),
                        "directory": bool(flags & 0x80),
                        "consecutive": bool(flags & 0x40),
                        "blocks": int.from_bytes(data[0x29:0x2C], "little"),
                        "start": int.from_bytes(data[0x2F:0x32], "little"),
                        "parent": int.from_bytes(data[0x32:0x34], "big"),
                        "size": int.from_bytes(data[0x34:0x38], "big"),
                        "table_offset": layout.data_offset(logical_block) + entry_offset,
                    }
                )
                if len(raw_entries) > max_entries:
                    raise InvalidPackageError("STFS file table exceeds the safety limit")

        entries: list[StfsEntry] = []
        for index, row in enumerate(raw_entries):
            ancestors: list[str] = []
            parent = row["parent"]
            visited: set[int] = set()
            while parent != 0xFFFF:
                if parent >= len(raw_entries) or parent in visited:
                    ancestors = ["[invalid-parent]"]
                    break
                visited.add(parent)
                ancestors.append(raw_entries[parent]["name"])
                parent = raw_entries[parent]["parent"]
            full_path = "/".join(reversed(ancestors))
            full_path = f"{full_path}/{row['name']}" if full_path else row["name"]
            block_count = (row["size"] + BLOCK_SIZE - 1) // BLOCK_SIZE
            if not row["directory"] and block_count > row["blocks"]:
                raise InvalidPackageError(
                    f"STFS entry exceeds its declared allocation: {full_path}"
                )
            if row["directory"]:
                block_count = 0
            blocks = (
                layout.block_chain(
                    handle,
                    row["start"],
                    block_count,
                    consecutive=row["consecutive"],
                )
                if block_count
                else ()
            )
            entries.append(
                StfsEntry(
                    index=index,
                    path=full_path,
                    name=row["name"],
                    is_directory=row["directory"],
                    consecutive=row["consecutive"],
                    allocated_blocks=row["blocks"],
                    starting_block=row["start"],
                    parent_index=row["parent"],
                    size=row["size"],
                    blocks=blocks,
                    table_offset=row["table_offset"],
                )
            )
    return entries


def verify_stfs(path: str | Path, *, max_issues: int = 10_000) -> StfsIntegrityReport:
    package = Path(path).expanduser().resolve()
    layout = read_stfs_layout(package)
    checked = valid = mismatched = unverifiable = 0
    issues: list[StfsBlockVerification] = []
    with package.open("rb") as handle:
        for block in range(layout.block_count):
            checked += 1
            try:
                record = layout.hash_record(handle, block)
                data = _read_exact(
                    handle, layout.data_offset(block), BLOCK_SIZE, layout.package_size
                )
            except InvalidPackageError as exc:
                mismatched += 1
                if len(issues) < max_issues:
                    issues.append(StfsBlockVerification(block, "invalid", message=str(exc)))
                continue
            calculated = hashlib.sha1(data).hexdigest()
            if not record.stored_sha1 or set(record.stored_sha1) == {"0"}:
                unverifiable += 1
                if len(issues) < max_issues:
                    issues.append(
                        StfsBlockVerification(
                            block,
                            "missing",
                            record.stored_sha1,
                            calculated,
                            "Hash record is empty",
                        )
                    )
            elif record.stored_sha1.lower() != calculated:
                mismatched += 1
                if len(issues) < max_issues:
                    issues.append(
                        StfsBlockVerification(
                            block,
                            "mismatch",
                            record.stored_sha1,
                            calculated,
                            "Stored SHA-1 does not match the data block",
                        )
                    )
            else:
                valid += 1
    return StfsIntegrityReport(
        package, layout.block_count, checked, valid, mismatched, unverifiable, tuple(issues)
    )


def extract_stfs_files(
    path: str | Path,
    destination: str | Path,
    selected_paths: Iterable[str] | None = None,
    *,
    max_output_size: int = 32 * 1024 * 1024 * 1024,
) -> dict[str, Any]:
    package = Path(path).expanduser().resolve()
    target = Path(destination).expanduser().resolve()
    if package == target or target.is_relative_to(package):
        raise InvalidPackageError("Extraction destination must be outside the package")
    requested = {item.replace("\\", "/") for item in selected_paths or ()}
    entries = list_stfs_entries(package)
    files = [
        entry
        for entry in entries
        if not entry.is_directory and (not requested or entry.path in requested)
    ]
    if requested - {entry.path for entry in files}:
        missing = sorted(requested - {entry.path for entry in files})
        raise InvalidPackageError(f"STFS entries were not found: {', '.join(missing[:5])}")
    if sum(entry.size for entry in files) > max_output_size:
        raise InvalidPackageError("Selected STFS output exceeds the safety limit")

    layout = read_stfs_layout(package)
    extracted: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    target.mkdir(parents=True, exist_ok=True)
    with package.open("rb") as handle:
        for entry in files:
            relative = _safe_member(entry.path)
            output = (target / relative).resolve()
            if not output.is_relative_to(target):
                raise UnsafeArchiveError(f"STFS path escapes destination: {entry.path}")
            if output.exists():
                skipped.append({"path": entry.path, "reason": "destination exists"})
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            partial = output.with_name(output.name + ".partial")
            digest = hashlib.sha256()
            remaining = entry.size
            try:
                with partial.open("xb") as destination_handle:
                    for block in entry.blocks:
                        size = min(remaining, BLOCK_SIZE)
                        chunk = _read_exact(
                            handle, layout.data_offset(block), size, layout.package_size
                        )
                        destination_handle.write(chunk)
                        digest.update(chunk)
                        remaining -= size
                if remaining:
                    raise InvalidPackageError(f"STFS data is truncated: {entry.path}")
                partial.replace(output)
            finally:
                partial.unlink(missing_ok=True)
            extracted.append(
                {
                    "path": entry.path,
                    "output": str(output),
                    "size": entry.size,
                    "sha256": digest.hexdigest(),
                    "blocks": list(entry.blocks),
                }
            )
    manifest = target / "unityscraper-stfs-extraction.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": 2,
                "source": str(package),
                "source_sha256": _sha256_file(package),
                "read_only": True,
                "supports_fragmented_files": True,
                "extracted": extracted,
                "skipped": skipped,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"manifest": str(manifest), "extracted": extracted, "skipped": skipped}


def _safe_member(value: str) -> Path:
    pure = PurePosixPath(value.replace("\\", "/"))
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise UnsafeArchiveError(f"Unsafe package path: {value}")
    if ":" in pure.parts[0]:
        raise UnsafeArchiveError(f"Unsafe package path: {value}")
    return Path(*pure.parts)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "CONTENT_TYPES",
    "STFS_MAGICS",
    "StfsLayout",
    "extract_stfs_files",
    "inspect_stfs",
    "list_stfs_entries",
    "read_stfs_layout",
    "verify_stfs",
]
