"""Xbox 360 backup discovery, package installation, verification, and transfer."""

from __future__ import annotations

import ftplib
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Iterator, Optional

from unityscraper.domains.packages.errors import (
    InvalidPackageError,
    PackageError as BackupError,
    UnsafeArchiveError,
)
from unityscraper.domains.packages.executables import (
    inspect_xbe as _domain_inspect_xbe,
    inspect_xex as _domain_inspect_xex,
)
from unityscraper.domains.packages.stfs import (
    extract_stfs_files as _domain_extract_stfs_files,
    inspect_stfs as _domain_inspect_stfs,
    list_stfs_entries as _domain_list_stfs_entries,
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
GAME_CONTENT_DIRECTORIES = {"00005000", "00007000", "000D0000"}
SUPPORT_CONTENT_DIRECTORIES = {"00000002", "000B0000"}
HEX8_RE = re.compile(r"^[0-9A-Fa-f]{8}$")
FOLDER_TITLE_ID_RE = re.compile(r"\[([0-9A-Fa-f]{8})\]\s*$")
COPY_CHUNK = 1024 * 1024
MAX_ARCHIVE_FILES = 200_000
MAX_ARCHIVE_EXPANDED_SIZE = 128 * 1024 * 1024 * 1024
FATX_INVALID_RE = re.compile(r'[<>:"/\\|?*]')


class ConflictError(BackupError):
    """Raised when a destination conflict cannot be resolved automatically."""


@dataclass(frozen=True)
class StfsPackage:
    path: Path
    magic: str
    content_type: int
    content_label: str
    content_directory: str
    title_id: str
    media_id: str
    disc_number: int
    disc_count: int
    display_name: str
    title_name: str
    size: int
    save_game_id: str
    console_id: str
    profile_id: str
    device_id: str


@dataclass(frozen=True)
class StfsEntry:
    index: int
    path: str
    name: str
    is_directory: bool
    consecutive: bool
    allocated_blocks: int
    starting_block: int
    parent_index: int
    size: int


@dataclass(frozen=True)
class XbePackage:
    path: Path
    title_id: str
    title_name: str
    size: int
    allowed_media: int
    region_flags: int
    disc_number: int
    version: int


@dataclass(frozen=True)
class XexPackage:
    path: Path
    title_id: str
    media_id: str
    version: str
    base_version: str
    disc_number: int
    disc_count: int
    module_flags: int
    size: int


@dataclass
class BackupItem:
    path: Path
    title_id: str
    name: str
    format: str
    size: int
    media_id: str = ""
    content_type: str = ""
    status: str = "ready"
    notes: list[str] = field(default_factory=list)
    disc_number: int = 0
    disc_count: int = 0

    def to_dict(self) -> dict:
        result = asdict(self)
        result["path"] = str(self.path)
        return result


@dataclass
class ScanResult:
    root: Path
    items: list[BackupItem]
    warnings: list[str]
    scanned_at: str

    @property
    def total_size(self) -> int:
        return sum(item.size for item in self.items)

    def to_dict(self) -> dict:
        return {
            "root": str(self.root),
            "scanned_at": self.scanned_at,
            "total_size": self.total_size,
            "warnings": self.warnings,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True)
class TransferResult:
    source: str
    destination: str
    bytes_copied: int
    sha256: str
    status: str


@dataclass(frozen=True)
class FtpTarget:
    host: str
    port: int = 21
    username: str = "xbox"
    password: str = "xbox"
    content_root: str = "/Hdd1/Content/0000000000000000"
    games_root: str = "/Hdd1/Games"
    timeout: float = 20.0


def _read_utf16be(data: bytes) -> str:
    return data.decode("utf-16-be", errors="ignore").split("\x00", 1)[0].strip()


def inspect_stfs(path: str | Path) -> StfsPackage:
    """Read public STFS header fields without extracting package contents."""
    package_path = Path(path)
    with package_path.open("rb") as handle:
        header = handle.read(0x1791)
    if len(header) < 0x1791 or header[:4] not in STFS_MAGICS:
        raise InvalidPackageError(f"{package_path.name} is not a supported STFS package")

    content_type = int.from_bytes(header[0x344:0x348], "big")
    content = CONTENT_TYPES.get(content_type)
    if content is None:
        raise InvalidPackageError(
            f"Unsupported STFS content type 0x{content_type:08X}"
        )
    title_id = header[0x360:0x364].hex().upper()
    if not HEX8_RE.fullmatch(title_id) or title_id == "00000000":
        raise InvalidPackageError("STFS package does not contain a usable TitleID")

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
    )


def _stfs_data_block_number(block: int, magic: bytes, header_size: int,
                            block_separation: int) -> int:
    if block < 0 or block > 0xFFFFFF:
        raise InvalidPackageError("STFS block number is outside the supported range")
    aligned_header = (header_size + 0xFFF) & 0xFFFFF000
    shift = 1 if aligned_header == 0xB000 else (0 if block_separation & 1 else 1)
    base = (block + 0xAA) // 0xAA
    if magic == b"CON ":
        base <<= shift
    result = base + block
    if block > 0xAA:
        base = (block + 0x70E4) // 0x70E4
        if magic == b"CON ":
            base <<= shift
        result += base
        if block > 0x70E4:
            base = (block + 0x4AF768) // 0x4AF768
            if magic == b"CON ":
                base <<= shift
            result += base
    return result


def list_stfs_entries(path: str | Path, max_entries: int = 100_000) -> list[StfsEntry]:
    """Read the bounded STFS file table without extracting or mutating content."""
    package_path = Path(path)
    package_size = package_path.stat().st_size
    with package_path.open("rb") as handle:
        header = handle.read(0x3AD)
        if len(header) < 0x3AD or header[:4] not in STFS_MAGICS:
            raise InvalidPackageError("Not a supported STFS package")
        if int.from_bytes(header[0x3A9:0x3AD], "big") != 0:
            raise InvalidPackageError("SVOD packages do not contain an STFS file table")
        header_size = int.from_bytes(header[0x340:0x344], "big")
        descriptor = header[0x379:0x39D]
        if descriptor[0] != 0x24:
            raise InvalidPackageError("STFS volume descriptor is invalid")
        block_separation = descriptor[2]
        table_blocks = int.from_bytes(descriptor[3:5], "big")
        table_start = int.from_bytes(descriptor[5:8], "big")
        if table_blocks <= 0 or table_blocks > 0x1000:
            raise InvalidPackageError("STFS file-table size is invalid")
        aligned_header = (header_size + 0xFFF) & 0xFFFFF000
        raw_entries: list[dict[str, Any]] = []
        for table_index in range(table_blocks):
            logical_block = table_start + table_index
            physical_block = _stfs_data_block_number(
                logical_block, header[:4], header_size, block_separation
            )
            offset = aligned_header + physical_block * 0x1000
            if offset + 0x1000 > package_size:
                raise InvalidPackageError("STFS file table points outside the package")
            handle.seek(offset)
            table = handle.read(0x1000)
            for entry_offset in range(0, 0x1000, 0x40):
                data = table[entry_offset:entry_offset + 0x40]
                if not any(data):
                    continue
                flags = data[0x28]
                name_length = flags & 0x3F
                if name_length == 0 or name_length > 0x28:
                    continue
                name = data[:name_length].decode("utf-8", errors="replace")
                raw_entries.append({
                    "name": name,
                    "directory": bool(flags & 0x80),
                    "consecutive": bool(flags & 0x40),
                    "blocks": int.from_bytes(data[0x29:0x2C], "little"),
                    "start": int.from_bytes(data[0x2F:0x32], "little"),
                    "parent": int.from_bytes(data[0x32:0x34], "big"),
                    "size": int.from_bytes(data[0x34:0x38], "big"),
                })
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
        entries.append(StfsEntry(
            index=index, path=full_path, name=row["name"],
            is_directory=row["directory"], consecutive=row["consecutive"],
            allocated_blocks=row["blocks"], starting_block=row["start"],
            parent_index=row["parent"], size=row["size"],
        ))
    return entries


def extract_stfs_files(
    path: str | Path,
    destination: str | Path,
    selected_paths: Iterable[str] | None = None,
    *,
    max_output_size: int = 32 * 1024 * 1024 * 1024,
) -> dict[str, Any]:
    """Extract consecutive STFS files read-only with path and size validation.

    Fragmented files are reported instead of guessed. This keeps extraction useful
    while making the unsupported block-chain case explicit and non-destructive.
    """
    package = Path(path).expanduser().resolve()
    target = Path(destination).expanduser().resolve()
    if package == target or target.is_relative_to(package):
        raise InvalidPackageError("Extraction destination must be outside the package")
    requested = {item.replace("\\", "/") for item in selected_paths or ()}
    entries = list_stfs_entries(package)
    files = [
        entry for entry in entries
        if not entry.is_directory and (not requested or entry.path in requested)
    ]
    if requested - {entry.path for entry in files}:
        missing = sorted(requested - {entry.path for entry in files})
        raise InvalidPackageError(f"STFS entries were not found: {', '.join(missing[:5])}")
    total_size = sum(entry.size for entry in files)
    if total_size > max_output_size:
        raise InvalidPackageError("Selected STFS output exceeds the extraction safety limit")

    with package.open("rb") as handle:
        header = handle.read(0x3AD)
        if len(header) < 0x3AD or header[:4] not in STFS_MAGICS:
            raise InvalidPackageError("Not a supported STFS package")
        header_size = int.from_bytes(header[0x340:0x344], "big")
        descriptor = header[0x379:0x39D]
        block_separation = descriptor[2]
        allocated = int.from_bytes(descriptor[0x1C:0x20], "big")
        aligned_header = (header_size + 0xFFF) & 0xFFFFF000
        target.mkdir(parents=True, exist_ok=True)
        extracted: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for entry in files:
            if not entry.consecutive and entry.allocated_blocks > 1:
                skipped.append({"path": entry.path, "reason": "fragmented block chain"})
                continue
            required_blocks = (entry.size + 0xFFF) // 0x1000
            if required_blocks > entry.allocated_blocks or entry.starting_block + required_blocks > allocated:
                skipped.append({"path": entry.path, "reason": "invalid block allocation"})
                continue
            relative = _safe_archive_member(entry.path)
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
                    for block in range(entry.starting_block, entry.starting_block + required_blocks):
                        physical = _stfs_data_block_number(
                            block, header[:4], header_size, block_separation
                        )
                        offset = aligned_header + physical * 0x1000
                        if offset + min(remaining, 0x1000) > package.stat().st_size:
                            raise InvalidPackageError(
                                f"STFS data points outside the package: {entry.path}"
                            )
                        handle.seek(offset)
                        chunk = handle.read(min(remaining, 0x1000))
                        if len(chunk) != min(remaining, 0x1000):
                            raise InvalidPackageError(f"STFS data is truncated: {entry.path}")
                        destination_handle.write(chunk)
                        digest.update(chunk)
                        remaining -= len(chunk)
                partial.replace(output)
            finally:
                partial.unlink(missing_ok=True)
            extracted.append({
                "path": entry.path,
                "output": str(output),
                "size": entry.size,
                "sha256": digest.hexdigest(),
            })
    manifest = target / "unityscraper-stfs-extraction.json"
    manifest.write_text(json.dumps({
        "schema": 1,
        "source": str(package),
        "source_sha256": sha256_file(package),
        "read_only": True,
        "extracted": extracted,
        "skipped": skipped,
    }, indent=2), encoding="utf-8")
    return {"manifest": str(manifest), "extracted": extracted, "skipped": skipped}


def _safe_archive_member(value: str) -> Path:
    normalized = value.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise UnsafeArchiveError(f"Unsafe package path: {value}")
    if ":" in pure.parts[0]:
        raise UnsafeArchiveError(f"Unsafe package path: {value}")
    return Path(*pure.parts)


def inspect_xbe(path: str | Path) -> XbePackage:
    """Read TitleID and title from an original Xbox executable certificate."""
    package_path = Path(path)
    with package_path.open("rb") as handle:
        header = handle.read(0x11C)
        if len(header) < 0x11C or header[:4] != b"XBEH":
            raise InvalidPackageError(f"{package_path.name} is not an XBE executable")
        base_address = int.from_bytes(header[0x104:0x108], "little")
        certificate_address = int.from_bytes(header[0x118:0x11C], "little")
        certificate_offset = certificate_address - base_address
        if certificate_offset < 0:
            raise InvalidPackageError("XBE certificate address is invalid")
        handle.seek(certificate_offset)
        certificate = handle.read(0xD0)
    if len(certificate) < 0xD0:
        raise InvalidPackageError("XBE certificate is incomplete")
    title_id = f"{int.from_bytes(certificate[0x8:0xC], 'little'):08X}"
    title_name = certificate[0xC:0x5C].decode("utf-16-le", errors="ignore")
    title_name = title_name.split("\x00", 1)[0].strip()
    return XbePackage(
        package_path, title_id, title_name, package_path.stat().st_size,
        int.from_bytes(certificate[0x9C:0xA0], "little"),
        int.from_bytes(certificate[0xA0:0xA4], "little"),
        int.from_bytes(certificate[0xA8:0xAC], "little"),
        int.from_bytes(certificate[0xAC:0xB0], "little"),
    )


def inspect_xex(path: str | Path) -> XexPackage:
    """Read the public XEX2 execution-info header without decrypting content."""
    package_path = Path(path)
    with package_path.open("rb") as handle:
        header = handle.read(0x4000)
    if len(header) < 0x18 or header[:4] != b"XEX2":
        raise InvalidPackageError(f"{package_path.name} is not an XEX2 executable")

    module_flags = int.from_bytes(header[4:8], "big")
    optional_count = int.from_bytes(header[0x14:0x18], "big")
    if optional_count > 4096 or 0x18 + optional_count * 8 > len(header):
        raise InvalidPackageError("XEX optional-header table is invalid")

    execution_offset = 0
    for index in range(optional_count):
        entry = 0x18 + index * 8
        key = int.from_bytes(header[entry : entry + 4], "big")
        value = int.from_bytes(header[entry + 4 : entry + 8], "big")
        if key == 0x00040006:
            execution_offset = value
            break
    if not execution_offset or execution_offset + 24 > len(header):
        raise InvalidPackageError("XEX execution metadata is unavailable")

    info = header[execution_offset : execution_offset + 24]

    def format_version(value: int) -> str:
        return (
            f"{(value >> 28) & 0xF}."
            f"{(value >> 24) & 0xF}."
            f"{(value >> 8) & 0xFFFF}."
            f"{value & 0xFF}"
        )

    return XexPackage(
        path=package_path,
        title_id=info[12:16].hex().upper(),
        media_id=info[0:4].hex().upper(),
        version=format_version(int.from_bytes(info[4:8], "big")),
        base_version=format_version(int.from_bytes(info[8:12], "big")),
        disc_number=info[18],
        disc_count=info[19],
        module_flags=module_flags,
        size=package_path.stat().st_size,
    )


# Compatibility exports. Package-format ownership lives in the packages domain.
inspect_stfs = _domain_inspect_stfs
list_stfs_entries = _domain_list_stfs_entries
extract_stfs_files = _domain_extract_stfs_files
inspect_xbe = _domain_inspect_xbe
inspect_xex = _domain_inspect_xex


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(COPY_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha1_file(path: str | Path) -> str:
    digest = hashlib.sha1()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(COPY_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def _content_root(root: Path) -> Path:
    nested = root / "Content" / "0000000000000000"
    return nested if nested.exists() else root


def scan_local_target(
    root: str | Path,
    title_lookup: Optional[Callable[[str], Optional[str]]] = None,
) -> ScanResult:
    """Inventory a console content root, USB drive, or archive directory."""
    target = Path(root).expanduser().resolve()
    if not target.is_dir():
        raise BackupError(f"Backup target does not exist: {target}")

    items: list[BackupItem] = []
    warnings: list[str] = []
    content_root = _content_root(target)
    if content_root.is_dir():
        for title_dir in sorted(content_root.iterdir()):
            if not title_dir.is_dir() or not HEX8_RE.fullmatch(title_dir.name):
                continue
            title_id = title_dir.name.upper()
            types = {
                child.name.upper()
                for child in title_dir.iterdir()
                if child.is_dir() and HEX8_RE.fullmatch(child.name)
            }
            game_types = sorted(types & GAME_CONTENT_DIRECTORIES)
            support_types = sorted(types & SUPPORT_CONTENT_DIRECTORIES)
            status = "ready" if game_types else "incomplete"
            notes = []
            package_names: list[str] = []
            media_ids: set[str] = set()
            disc_numbers: set[int] = set()
            disc_count = 0
            malformed = 0
            for type_name in sorted(types & set(CONTENT_TYPES[value][1] for value in CONTENT_TYPES)):
                for package_path in (title_dir / type_name).iterdir():
                    if not package_path.is_file() or package_path.name.endswith(".partial"):
                        continue
                    try:
                        package = inspect_stfs(package_path)
                    except (InvalidPackageError, OSError):
                        malformed += 1
                        continue
                    if package.media_id and package.media_id != "00000000":
                        media_ids.add(package.media_id)
                    if package.disc_number:
                        disc_numbers.add(package.disc_number)
                    disc_count = max(disc_count, package.disc_count)
                    candidate_name = package.title_name or package.display_name
                    if candidate_name:
                        package_names.append(candidate_name)
            if support_types and not game_types:
                notes.append("Only add-on or update content was found")
                warnings.append(f"{title_id} has support content but no base game")
            if malformed:
                notes.append(f"{malformed} package header(s) could not be identified")
            if disc_count:
                notes.append(
                    f"Discs found: {', '.join(str(value) for value in sorted(disc_numbers))} "
                    f"of {disc_count}"
                )
            name = title_lookup(title_id) if title_lookup else None
            items.append(
                BackupItem(
                    path=title_dir,
                    title_id=title_id,
                    name=name or (package_names[0] if package_names else title_id),
                    format=", ".join(game_types + support_types) or "Content",
                    content_type=", ".join(
                        CONTENT_TYPES[int(value, 16)][0]
                        for value in game_types + support_types
                        if int(value, 16) in CONTENT_TYPES
                    ),
                    media_id=", ".join(sorted(media_ids)),
                    size=directory_size(title_dir),
                    status=status,
                    notes=notes,
                    disc_number=min(disc_numbers) if len(disc_numbers) == 1 else 0,
                    disc_count=disc_count,
                )
            )

    games_root = target / "Games"
    if games_root.is_dir():
        for game_dir in sorted(child for child in games_root.iterdir() if child.is_dir()):
            title_id = ""
            title_name = game_dir.name
            media_id = ""
            format_name = "Extracted Xbox 360"
            extracted_notes: list[str] = []
            disc_number = 0
            disc_count = 0
            xbe = game_dir / "default.xbe"
            xex = game_dir / "default.xex"
            if xbe.is_file():
                try:
                    xbe_info = inspect_xbe(xbe)
                    title_id = xbe_info.title_id
                    title_name = xbe_info.title_name or title_name
                    format_name = "Extracted Original Xbox"
                except BackupError as exc:
                    extracted_notes.append(str(exc))
            else:
                if xex.is_file():
                    try:
                        xex_info = inspect_xex(xex)
                        title_id = xex_info.title_id
                        media_id = xex_info.media_id if xex_info.media_id != "00000000" else ""
                        disc_number = xex_info.disc_number
                        disc_count = xex_info.disc_count
                        extracted_notes.append(f"XEX version {xex_info.version}")
                        if xex_info.disc_count:
                            extracted_notes.append(
                                f"Disc {xex_info.disc_number} of {xex_info.disc_count}"
                            )
                    except BackupError as exc:
                        extracted_notes.append(str(exc))
                folder_match = FOLDER_TITLE_ID_RE.search(game_dir.name)
                if not title_id and folder_match:
                    title_id = folder_match.group(1).upper()
                if not xex.is_file():
                    extracted_notes.append("default.xex or default.xbe is missing")
            if title_id and title_lookup:
                title_name = title_lookup(title_id) or title_name
            items.append(
                BackupItem(
                    path=game_dir,
                    title_id=title_id,
                    name=title_name,
                    format=format_name,
                    media_id=media_id,
                    size=directory_size(game_dir),
                    status="ready" if not extracted_notes else "incomplete",
                    notes=extracted_notes,
                    disc_number=disc_number,
                    disc_count=disc_count,
                )
            )

    if not items:
        warnings.append("No Xbox 360 content or extracted games were found")
    return ScanResult(
        root=target,
        items=items,
        warnings=warnings,
        scanned_at=datetime.now(timezone.utc).isoformat(),
    )


def _package_filename(package: StfsPackage) -> str:
    if package.content_directory == "000B0000":
        return sha1_file(package.path).upper()
    filename = package.path.name
    if len(filename) > 42 or FATX_INVALID_RE.search(filename):
        return sha1_file(package.path).upper()
    return filename


def package_destination(package: StfsPackage, target_root: str | Path) -> Path:
    root = Path(target_root).expanduser().resolve()
    content_root = target_content_root(root)
    return (
        content_root
        / package.title_id
        / package.content_directory
        / _package_filename(package)
    )


def target_content_root(root: str | Path) -> Path:
    """Resolve a drive root, Content folder, or direct common-content folder."""
    target = Path(root).expanduser().resolve()
    if target.name == "0000000000000000":
        return target
    if target.name.lower() == "content":
        return target / "0000000000000000"
    try:
        if any(child.is_dir() and HEX8_RE.fullmatch(child.name) for child in target.iterdir()):
            return target
    except OSError:
        pass
    return target / "Content" / "0000000000000000"


def atomic_copy(
    source: str | Path,
    destination: str | Path,
    conflict: str = "skip",
    progress: Optional[Callable[[int, int], None]] = None,
) -> TransferResult:
    """Copy a file through a partial path, verify it, then atomically publish it."""
    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    if conflict not in {"skip", "replace", "error"}:
        raise ValueError("conflict must be skip, replace, or error")
    if destination_path.exists():
        if conflict == "skip":
            source_hash = sha256_file(source_path)
            destination_hash = sha256_file(destination_path)
            return TransferResult(
                str(source_path),
                str(destination_path),
                0,
                destination_hash,
                "skipped" if source_hash == destination_hash else "conflict",
            )
        if conflict == "error":
            raise ConflictError(f"Destination already exists: {destination_path}")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    partial = destination_path.with_name(destination_path.name + ".partial")
    source_size = source_path.stat().st_size
    copied = 0
    try:
        with source_path.open("rb") as source_handle, partial.open("wb") as dest_handle:
            while True:
                chunk = source_handle.read(COPY_CHUNK)
                if not chunk:
                    break
                dest_handle.write(chunk)
                copied += len(chunk)
                if progress:
                    progress(copied, source_size)
            dest_handle.flush()
            os.fsync(dest_handle.fileno())
        source_hash = sha256_file(source_path)
        destination_hash = sha256_file(partial)
        if source_hash != destination_hash:
            raise BackupError("Copied file failed SHA-256 verification")
        os.replace(partial, destination_path)
        return TransferResult(
            str(source_path), str(destination_path), copied, source_hash, "completed"
        )
    finally:
        if partial.exists():
            partial.unlink()


def install_stfs_package(
    source: str | Path,
    target_root: str | Path,
    conflict: str = "skip",
    progress: Optional[Callable[[int, int], None]] = None,
) -> TransferResult:
    package = inspect_stfs(source)
    return atomic_copy(
        package.path,
        package_destination(package, target_root),
        conflict=conflict,
        progress=progress,
    )


def _safe_zip_members(archive: zipfile.ZipFile, destination: Path) -> Iterator[zipfile.ZipInfo]:
    base = destination.resolve()
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_FILES:
        raise UnsafeArchiveError(
            f"Archive contains more than {MAX_ARCHIVE_FILES:,} entries"
        )
    expanded_size = sum(member.file_size for member in members)
    if expanded_size > MAX_ARCHIVE_EXPANDED_SIZE:
        raise UnsafeArchiveError("Archive expanded size exceeds the safety limit")
    for member in members:
        member_path = Path(member.filename.replace("\\", "/"))
        if member_path.is_absolute() or ".." in member_path.parts:
            raise UnsafeArchiveError(f"Unsafe archive path: {member.filename}")
        mode = member.external_attr >> 16
        if mode and (mode & 0o170000) == 0o120000:
            raise UnsafeArchiveError(f"Archive symlinks are not supported: {member.filename}")
        resolved = (base / member_path).resolve()
        try:
            resolved.relative_to(base)
        except ValueError as exc:
            raise UnsafeArchiveError(f"Unsafe archive path: {member.filename}") from exc
        yield member


def import_stfs_zip(
    archive_path: str | Path,
    target_root: str | Path,
    conflict: str = "skip",
) -> list[TransferResult]:
    """Safely extract and install supported STFS packages from a ZIP archive."""
    results: list[TransferResult] = []
    with tempfile.TemporaryDirectory(prefix="unityscraper-import-") as temporary:
        destination = Path(temporary)
        with zipfile.ZipFile(archive_path) as archive:
            members = list(_safe_zip_members(archive, destination))
            archive.extractall(destination, members=members)
        copied_sources: set[Path] = set()
        target_content = target_content_root(target_root)
        for common_root in _find_common_content_roots(destination):
            for title_dir in common_root.iterdir():
                if not title_dir.is_dir() or not HEX8_RE.fullmatch(title_dir.name):
                    continue
                for content_dir in title_dir.iterdir():
                    type_name = content_dir.name.upper()
                    if (
                        not content_dir.is_dir()
                        or not HEX8_RE.fullmatch(type_name)
                        or int(type_name, 16) not in CONTENT_TYPES
                    ):
                        continue
                    for source in sorted(
                        path for path in content_dir.rglob("*") if path.is_file()
                    ):
                        relative = source.relative_to(common_root)
                        results.append(
                            atomic_copy(
                                source,
                                target_content / relative,
                                conflict=conflict,
                            )
                        )
                        copied_sources.add(source.resolve())
        candidates = []
        for path in destination.rglob("*"):
            if not path.is_file() or path.resolve() in copied_sources:
                continue
            try:
                candidates.append(inspect_stfs(path))
            except (InvalidPackageError, OSError):
                continue
        if not candidates and not results:
            raise InvalidPackageError("Archive contains no supported STFS packages")
        for package in candidates:
            results.append(
                install_stfs_package(package.path, target_root, conflict=conflict)
            )
    return results


def _find_common_content_roots(extracted: Path) -> list[Path]:
    roots = []
    for candidate in extracted.rglob("0000000000000000"):
        if candidate.is_dir() and (
            candidate.parent.name.lower() == "content" or candidate.parent == extracted
        ):
            roots.append(candidate)
    if extracted.name == "0000000000000000":
        roots.append(extracted)
    unique = {path.resolve(): path for path in roots}
    return list(unique.values())


def export_backup_item(
    item: BackupItem,
    destination_root: str | Path,
    conflict: str = "skip",
) -> Path:
    """Export an inventory item with a preservation manifest and file hashes."""
    output_root = Path(destination_root).expanduser().resolve()
    safe_name = re.sub(r'[<>:"/\\|?*]', "_", item.name).strip(" .") or item.title_id or "XboxGame"
    destination = output_root / safe_name
    try:
        destination.resolve().relative_to(output_root)
    except ValueError as exc:
        raise BackupError("Export destination escapes the selected root") from exc
    if destination.exists():
        if conflict == "skip":
            return destination
        if conflict == "error":
            raise ConflictError(f"Export destination already exists: {destination}")
        if destination.is_symlink():
            destination.unlink()
        elif destination.is_dir():
            shutil.rmtree(destination)
        else:
            raise ConflictError(f"Export destination is not a directory: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    files = []
    source_root = item.path
    for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
        relative = source.relative_to(source_root)
        result = atomic_copy(source, destination / relative, conflict="replace")
        files.append(
            {
                "path": relative.as_posix(),
                "size": source.stat().st_size,
                "sha256": result.sha256,
            }
        )
    manifest = {
        "schema": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "item": item.to_dict(),
        "files": files,
    }
    (destination / "unityscraper-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return destination


def verify_backup_item(item: BackupItem) -> list[str]:
    issues = list(item.notes)
    if not item.path.exists():
        issues.append("Item path is missing")
        return issues
    for partial in item.path.rglob("*.partial"):
        issues.append(f"Abandoned partial file: {partial}")
    for data_dir in item.path.rglob("*.data"):
        if data_dir.is_dir() and not any(data_dir.iterdir()):
            issues.append(f"Empty GOD data directory: {data_dir}")
    return issues


class FtpBackupClient:
    """Single-connection FTP client for user-configured console targets."""

    def __init__(self, target: FtpTarget):
        self.target = target

    def _connect(self) -> ftplib.FTP:
        ftp = ftplib.FTP()
        ftp.connect(self.target.host, self.target.port, timeout=self.target.timeout)
        ftp.login(self.target.username, self.target.password)
        return ftp

    def test_connection(self) -> str:
        with self._connect() as ftp:
            return ftp.getwelcome()

    @staticmethod
    def _mkdirs(ftp: ftplib.FTP, remote_directory: str) -> None:
        current = PurePosixPath("/")
        for part in PurePosixPath(remote_directory).parts:
            if part == "/":
                continue
            current /= part
            try:
                ftp.mkd(str(current))
            except ftplib.error_perm as exc:
                if not str(exc).startswith("550"):
                    raise

    def upload_stfs(
        self,
        source: str | Path,
        conflict: str = "skip",
        progress: Optional[Callable[[int, int], None]] = None,
    ) -> TransferResult:
        if conflict not in {"skip", "replace", "error"}:
            raise ValueError("conflict must be skip, replace, or error")
        package = inspect_stfs(source)
        remote = (
            PurePosixPath(self.target.content_root)
            / package.title_id
            / package.content_directory
            / _package_filename(package)
        )
        partial = PurePosixPath(str(remote) + ".partial")
        source_path = Path(source)
        total = source_path.stat().st_size
        copied = 0

        def callback(chunk: bytes) -> None:
            nonlocal copied
            copied += len(chunk)
            if progress:
                progress(copied, total)

        with self._connect() as ftp:
            self._mkdirs(ftp, str(remote.parent))
            remote_exists = False
            try:
                ftp.voidcmd("TYPE I")
                ftp.size(str(remote))
                remote_exists = True
            except ftplib.error_perm:
                remote_exists = False
            if remote_exists and conflict == "skip":
                return TransferResult(
                    str(source_path),
                    str(remote),
                    0,
                    sha256_file(source_path),
                    "skipped",
                )
            if remote_exists and conflict == "error":
                raise ConflictError(f"Remote destination already exists: {remote}")
            try:
                with source_path.open("rb") as handle:
                    ftp.storbinary(
                        f"STOR {partial}",
                        handle,
                        blocksize=64 * 1024,
                        callback=callback,
                    )
                if remote_exists:
                    ftp.delete(str(remote))
                ftp.rename(str(partial), str(remote))
            except Exception:
                try:
                    ftp.delete(str(partial))
                except ftplib.all_errors:
                    pass
                raise
        return TransferResult(
            str(source_path),
            str(remote),
            copied,
            sha256_file(source_path),
            "completed",
        )


class ExternalConverter:
    """Runs an explicitly configured external converter for user-owned images."""

    def __init__(self, executable: str | Path, argument_template: Iterable[str]):
        self.executable = Path(executable).expanduser().resolve()
        self.argument_template = tuple(argument_template)
        if not self.executable.is_file():
            raise BackupError(f"Converter executable was not found: {self.executable}")

    def convert(
        self,
        source_iso: str | Path,
        output_directory: str | Path,
        timeout: float = 3600,
    ) -> subprocess.CompletedProcess[str]:
        source = Path(source_iso).expanduser().resolve()
        output = Path(output_directory).expanduser().resolve()
        if source.suffix.lower() != ".iso" or not source.is_file():
            raise BackupError("Converter input must be an existing ISO file")
        output.mkdir(parents=True, exist_ok=True)
        arguments = [
            value.replace("{input}", str(source)).replace("{output}", str(output))
            for value in self.argument_template
        ]
        return subprocess.run(
            [str(self.executable), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
