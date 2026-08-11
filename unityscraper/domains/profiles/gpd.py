"""GPD/XDBF inspection exports and transactional record editing."""

from __future__ import annotations

import os
import shutil
import struct
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gpd_parser import (
    GpdAchievement,
    GpdError,
    GpdImage,
    GpdReport,
    GpdSetting,
    GpdTitleHistory,
    XDBF_ENTRY,
    XDBF_FREE_ENTRY_SIZE,
    XDBF_HEADER,
    export_gpd_image,
    parse_gpd,
    parse_gpd_bytes,
)

SETTING_TYPE_IDS = {
    "context": 0,
    "uint32": 1,
    "int64": 2,
    "double": 3,
    "unicode": 4,
    "float": 5,
    "binary": 6,
    "datetime": 7,
    "null": 0xFF,
}


def update_gpd_setting(
    source: str | Path,
    setting_id: int,
    value: Any,
    *,
    output: str | Path,
) -> GpdReport:
    """Update one existing setting without resizing its XDBF allocation."""
    path = Path(source).expanduser().resolve()

    def mutate(data: bytearray) -> None:
        offset, size = _find_entry(data, 3, setting_id)
        if size < 0x18:
            raise GpdError("Setting record is too small")
        type_id = data[offset + 8]
        area = offset + 16
        if type_id in {0, 1}:
            data[area : area + 4] = int(value).to_bytes(4, "big", signed=False)
        elif type_id == 2:
            data[area : area + 8] = int(value).to_bytes(8, "big", signed=True)
        elif type_id == 3:
            data[area : area + 8] = struct.pack(">d", float(value))
        elif type_id == 5:
            data[area : area + 4] = struct.pack(">f", float(value))
        elif type_id == 7:
            filetime = _to_filetime(value)
            data[area : area + 8] = filetime.to_bytes(8, "big", signed=True)
        elif type_id in {4, 6}:
            encoded = (
                str(value).encode("utf-16-be") + b"\0\0"
                if type_id == 4
                else bytes.fromhex(str(value))
            )
            capacity = size - 0x18
            if len(encoded) > capacity:
                raise GpdError("Replacement setting exceeds its existing allocation")
            data[area : area + 4] = len(encoded).to_bytes(4, "big", signed=True)
            data[offset + 0x18 : offset + size] = encoded.ljust(capacity, b"\0")
        elif type_id == 0xFF:
            raise GpdError("Null settings do not contain editable storage")
        else:
            raise GpdError(f"Unsupported setting type: {type_id}")

    target = _mutate_file(path, output, mutate)
    return parse_gpd(target)


def set_gpd_achievement_state(
    source: str | Path,
    achievement_id: int,
    state: str,
    *,
    output: str | Path,
    unlocked_at: datetime | None = None,
) -> GpdReport:
    """Set an existing achievement state in a separate GPD output."""
    states = {"locked": 0, "unlocked-offline": 0x12, "unlocked-online": 0x13}
    if state not in states:
        raise GpdError(f"Unsupported achievement state: {state}")
    path = Path(source).expanduser().resolve()

    def mutate(data: bytearray) -> None:
        offset, size = _find_achievement(data, achievement_id)
        if size < 0x1C:
            raise GpdError("Achievement record is too small")
        data[offset + 17] = states[state]
        timestamp = unlocked_at if state == "unlocked-online" else None
        filetime = _to_filetime(timestamp or datetime.now(timezone.utc)) if timestamp else 0
        data[offset + 20 : offset + 28] = filetime.to_bytes(8, "big", signed=True)

    target = _mutate_file(path, output, mutate)
    return parse_gpd(target)


def _find_achievement(data: bytearray, achievement_id: int) -> tuple[int, int]:
    for offset, size in _entries(data, 1):
        if (
            size >= 8
            and int.from_bytes(data[offset + 4 : offset + 8], "big", signed=True) == achievement_id
        ):
            return offset, size
    raise KeyError(f"Achievement {achievement_id} was not found")


def _find_entry(data: bytearray, namespace: int, entry_id: int) -> tuple[int, int]:
    for table_id, offset, size in _entries_with_ids(data, namespace):
        if table_id == entry_id:
            return offset, size
        if size >= 4 and int.from_bytes(data[offset : offset + 4], "big", signed=True) == entry_id:
            return offset, size
    raise KeyError(f"XDBF entry {entry_id} was not found")


def _entries(data: bytearray, namespace: int):
    for _entry_id, offset, size in _entries_with_ids(data, namespace):
        yield offset, size


def _entries_with_ids(data: bytearray, namespace: int):
    if len(data) < XDBF_HEADER.size:
        raise GpdError("GPD is smaller than the XDBF header")
    magic, _version, entry_max, entry_count, free_max, _free_count = XDBF_HEADER.unpack_from(data)
    if magic != b"XDBF" or entry_count > entry_max:
        raise GpdError("GPD has an invalid XDBF header")
    header_size = XDBF_HEADER.size + entry_max * XDBF_ENTRY.size + free_max * XDBF_FREE_ENTRY_SIZE
    if header_size > len(data):
        raise GpdError("XDBF table extends beyond the file")
    for index in range(entry_count):
        entry_namespace, entry_id, relative, size = XDBF_ENTRY.unpack_from(
            data, XDBF_HEADER.size + index * XDBF_ENTRY.size
        )
        absolute = header_size + relative
        if relative < 0 or size < 0 or absolute + size > len(data):
            raise GpdError("XDBF entry extends beyond the file")
        if entry_namespace == namespace:
            yield entry_id, absolute, size


def _mutate_file(source: Path, output: str | Path, mutation) -> Path:
    target = Path(output).expanduser().resolve()
    if target == source:
        raise GpdError("GPD edits require a separate output file")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".partial", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        data = bytearray(temporary.read_bytes())
        mutation(data)
        temporary.write_bytes(data)
        parse_gpd(temporary)
        if target.exists():
            raise FileExistsError(target)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _to_filetime(value: Any) -> int:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise GpdError("Datetime settings require an ISO timestamp or datetime")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
    return int((value.astimezone(timezone.utc) - epoch).total_seconds() * 10_000_000)


__all__ = [
    "GpdAchievement",
    "GpdError",
    "GpdImage",
    "GpdReport",
    "GpdSetting",
    "GpdTitleHistory",
    "export_gpd_image",
    "parse_gpd",
    "parse_gpd_bytes",
    "set_gpd_achievement_state",
    "update_gpd_setting",
]
