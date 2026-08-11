"""Data contracts for Xbox package inspection and integrity workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
    header_size: int = 0
    block_count: int = 0
    structure_type: int = 0


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
    blocks: tuple[int, ...] = ()
    table_offset: int = 0


@dataclass(frozen=True)
class StfsMutationResult:
    source: Path
    output: Path
    operation: str
    changed_paths: tuple[str, ...]
    rehashed_blocks: int
    signed: bool
    sha256: str


@dataclass(frozen=True)
class StfsHashRecord:
    block: int
    level: int
    stored_sha1: str
    status: int
    next_block: int
    table_index: int
    offset: int


@dataclass(frozen=True)
class StfsBlockVerification:
    block: int
    status: str
    stored_sha1: str = ""
    calculated_sha1: str = ""
    message: str = ""


@dataclass(frozen=True)
class StfsIntegrityReport:
    source: Path
    block_count: int
    checked: int
    valid_blocks: int
    mismatched_blocks: int
    unverifiable_blocks: int
    issues: tuple[StfsBlockVerification, ...]

    @property
    def valid(self) -> bool:
        return self.mismatched_blocks == 0


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


__all__ = [
    "StfsBlockVerification",
    "StfsEntry",
    "StfsHashRecord",
    "StfsIntegrityReport",
    "StfsMutationResult",
    "StfsPackage",
    "XbePackage",
    "XexPackage",
]
