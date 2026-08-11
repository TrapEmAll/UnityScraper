"""Transactional STFS mutation and user-supplied signing interfaces."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Mapping

from .errors import InvalidPackageError
from .models import StfsMutationResult
from .stfs import (
    BLOCK_SIZE,
    LEVEL0_BLOCKS,
    LEVEL1_BLOCKS,
    StfsLayout,
    list_stfs_entries,
    read_stfs_layout,
)

StfsSigner = Callable[[str, bytes], bytes]

METADATA_FIELDS: Mapping[str, tuple[int, int, str]] = {
    "display_name": (0x411, 0x100, "utf-16-be"),
    "title_name": (0x1691, 0x100, "utf-16-be"),
    "publisher": (0x1611, 0x80, "utf-16-be"),
}


def replace_stfs_file(
    package: str | Path,
    internal_path: str,
    replacement: str | Path,
    *,
    output: str | Path | None = None,
    signer: StfsSigner | None = None,
) -> StfsMutationResult:
    """Replace one file without reallocating its existing STFS block chain."""
    source = Path(package).expanduser().resolve()
    incoming = Path(replacement).expanduser().resolve()
    if not incoming.is_file():
        raise FileNotFoundError(incoming)
    normalized = internal_path.replace("\\", "/").strip("/")
    entry = next(
        (item for item in list_stfs_entries(source) if item.path == normalized),
        None,
    )
    if entry is None or entry.is_directory:
        raise InvalidPackageError(f"STFS file was not found: {normalized}")
    replacement_size = incoming.stat().st_size
    if replacement_size > entry.allocated_blocks * BLOCK_SIZE:
        raise InvalidPackageError(
            "Replacement exceeds the file's current allocation; package growth is not yet safe"
        )

    def mutate(working: Path) -> int:
        layout = read_stfs_layout(working)
        with incoming.open("rb") as source_handle, working.open("r+b") as handle:
            remaining = replacement_size
            for block in entry.blocks:
                chunk = source_handle.read(min(remaining, BLOCK_SIZE)) if remaining else b""
                handle.seek(layout.data_offset(block))
                handle.write(chunk.ljust(BLOCK_SIZE, b"\0"))
                remaining -= len(chunk)
            if remaining:
                raise InvalidPackageError("Replacement data did not fit its declared allocation")
            handle.seek(entry.table_offset + 0x34)
            handle.write(replacement_size.to_bytes(4, "big"))
        return _rehash_in_place(working, signer)

    target, rehashed, signed = _transaction(source, output, mutate, signer is not None)
    return StfsMutationResult(
        source, target, "replace", (normalized,), rehashed, signed, _sha256(target)
    )


def edit_stfs_metadata(
    package: str | Path,
    updates: Mapping[str, str],
    *,
    output: str | Path | None = None,
    signer: StfsSigner | None = None,
) -> StfsMutationResult:
    """Edit bounded public text fields and rebuild package integrity data."""
    source = Path(package).expanduser().resolve()
    unknown = set(updates) - set(METADATA_FIELDS)
    if unknown:
        raise InvalidPackageError(f"Unsupported STFS metadata fields: {', '.join(sorted(unknown))}")

    def mutate(working: Path) -> int:
        read_stfs_layout(working)
        with working.open("r+b") as handle:
            for field, value in updates.items():
                offset, width, encoding = METADATA_FIELDS[field]
                encoded = value.encode(encoding)
                if len(encoded) > width - 2:
                    raise InvalidPackageError(f"{field} exceeds {width // 2 - 1} characters")
                handle.seek(offset)
                handle.write(encoded.ljust(width, b"\0"))
        return _rehash_in_place(working, signer)

    target, rehashed, signed = _transaction(source, output, mutate, signer is not None)
    return StfsMutationResult(
        source,
        target,
        "metadata",
        tuple(sorted(updates)),
        rehashed,
        signed,
        _sha256(target),
    )


def rehash_stfs(
    package: str | Path,
    *,
    output: str | Path | None = None,
    signer: StfsSigner | None = None,
) -> StfsMutationResult:
    """Rebuild the STFS hash tree and optionally invoke a caller-owned signer."""
    source = Path(package).expanduser().resolve()

    def mutate(working: Path) -> int:
        return _rehash_in_place(working, signer)

    target, rehashed, signed = _transaction(source, output, mutate, signer is not None)
    return StfsMutationResult(source, target, "rehash", (), rehashed, signed, _sha256(target))


def _transaction(
    source: Path,
    output: str | Path | None,
    mutation: Callable[[Path], int],
    signed: bool,
) -> tuple[Path, int, bool]:
    if not source.is_file():
        raise FileNotFoundError(source)
    target = Path(output).expanduser().resolve() if output else source
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".partial", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        rehashed = mutation(temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target, rehashed, signed


def _rehash_in_place(path: Path, signer: StfsSigner | None) -> int:
    layout = read_stfs_layout(path)
    with path.open("r+b") as handle:
        for block in range(layout.block_count):
            handle.seek(layout.data_offset(block))
            digest = hashlib.sha1(handle.read(BLOCK_SIZE)).digest()
            record_offset = _record_offset(layout, handle, block, 0)
            handle.seek(record_offset)
            handle.write(digest)

        if layout.block_count > LEVEL0_BLOCKS:
            groups = (layout.block_count + LEVEL0_BLOCKS - 1) // LEVEL0_BLOCKS
            for group in range(groups):
                block = group * LEVEL0_BLOCKS
                table_offset = _active_table_offset(layout, handle, block, 0)
                handle.seek(table_offset)
                digest = hashlib.sha1(handle.read(BLOCK_SIZE)).digest()
                handle.seek(_record_offset(layout, handle, block, 1))
                handle.write(digest)

        if layout.block_count > LEVEL1_BLOCKS:
            groups = (layout.block_count + LEVEL1_BLOCKS - 1) // LEVEL1_BLOCKS
            for group in range(groups):
                block = group * LEVEL1_BLOCKS
                table_offset = _active_table_offset(layout, handle, block, 1)
                handle.seek(table_offset)
                digest = hashlib.sha1(handle.read(BLOCK_SIZE)).digest()
                handle.seek(_record_offset(layout, handle, block, 2))
                handle.write(digest)

        top_level = 0 if layout.block_count <= LEVEL0_BLOCKS else 1
        if layout.block_count > LEVEL1_BLOCKS:
            top_level = 2
        top_offset = _active_table_offset(layout, handle, 0, top_level)
        master_digest = hashlib.sha1(_read_block(handle, top_offset)).digest()
        handle.seek(0x381)
        handle.write(master_digest)

        header_hash_size = 0x9CBC if layout.base_offset == 0xA000 else 0xACBC
        header_digest = hashlib.sha1(_read_range(handle, 0x344, header_hash_size)).digest()
        handle.seek(0x32C)
        handle.write(header_digest)
        if signer is not None:
            signing_digest = hashlib.sha1(_read_range(handle, 0x22C, 0x118)).digest()
            signature = signer(layout.magic.decode("ascii").strip(), signing_digest)
            expected = 0x80 if layout.magic == b"CON " else 0x100
            if len(signature) != expected:
                raise InvalidPackageError(
                    f"Signer returned {len(signature)} bytes; {expected} are required"
                )
            handle.seek(0x1AC if layout.magic == b"CON " else 4)
            handle.write(signature)
    return layout.block_count


def _record_offset(layout: StfsLayout, handle, block: int, level: int) -> int:
    return layout.hash_record(handle, block, level).offset


def _active_table_offset(layout: StfsLayout, handle, block: int, level: int) -> int:
    return layout.active_hash_table_offset(handle, block, level)


def _read_block(handle, offset: int) -> bytes:
    return _read_range(handle, offset, BLOCK_SIZE)


def _read_range(handle, offset: int, size: int) -> bytes:
    handle.seek(offset)
    value = handle.read(size)
    if len(value) != size:
        raise InvalidPackageError("STFS package is truncated during rehashing")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "METADATA_FIELDS",
    "StfsSigner",
    "edit_stfs_metadata",
    "rehash_stfs",
    "replace_stfs_file",
]
