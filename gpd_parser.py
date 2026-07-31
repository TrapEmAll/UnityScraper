"""Bounded, read-only parser for Xbox 360 XDBF/GPD databases."""

from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


XDBF_MAGIC = b"XDBF"
XDBF_HEADER = struct.Struct(">4sIIIII")
XDBF_ENTRY = struct.Struct(">Hqii")
XDBF_FREE_ENTRY_SIZE = 8
MAX_TABLE_ENTRIES = 100_000
MAX_FILE_SIZE = 512 * 1024 * 1024
TITLE_ID_RE = re.compile(r"^[0-9A-Fa-f]{8}$")

NAMESPACE_NAMES = {
    0: "nothing",
    1: "achievement",
    2: "image",
    3: "setting",
    4: "title",
    5: "string",
}

SETTING_TYPES = {
    0: "context",
    1: "uint32",
    2: "int64",
    3: "double",
    4: "unicode",
    5: "float",
    6: "binary",
    7: "datetime",
    0xFF: "null",
}


class GpdError(ValueError):
    """Raised when a GPD file is malformed or exceeds a safety bound."""


@dataclass(frozen=True)
class XdbfEntry:
    namespace: int
    entry_id: int
    offset: int
    size: int

    @property
    def namespace_name(self) -> str:
        return NAMESPACE_NAMES.get(self.namespace, f"unknown-{self.namespace}")


@dataclass(frozen=True)
class GpdAchievement:
    entry_id: int
    achievement_id: int
    image_id: int
    gamerscore: int
    state: str
    unlocked_at: str
    title: str
    locked_description: str
    unlocked_description: str

    @property
    def unlocked(self) -> bool:
        return self.state in {"unlocked-offline", "unlocked-online"}


@dataclass(frozen=True)
class GpdSetting:
    entry_id: int
    setting_id: int
    value_type: str
    value: Any


@dataclass(frozen=True)
class GpdTitleHistory:
    entry_id: int
    title_id: str
    title: str
    achievements_earned: int
    achievements_possible: int
    gamerscore_earned: int
    gamerscore_possible: int
    last_played_at: str


@dataclass(frozen=True)
class GpdImage:
    entry_id: int
    image_format: str
    size: int
    sha256: str


@dataclass(frozen=True)
class GpdReport:
    path: Path
    title_id: str
    version: int
    sha256: str
    size: int
    entry_count: int
    achievements: tuple[GpdAchievement, ...]
    settings: tuple[GpdSetting, ...]
    titles: tuple[GpdTitleHistory, ...]
    images: tuple[GpdImage, ...]
    namespace_counts: dict[str, int]
    warnings: tuple[str, ...]

    @property
    def unlocked_count(self) -> int:
        return sum(item.unlocked for item in self.achievements)

    @property
    def gamerscore_earned(self) -> int:
        return sum(item.gamerscore for item in self.achievements if item.unlocked)

    @property
    def gamerscore_possible(self) -> int:
        return sum(item.gamerscore for item in self.achievements)


def parse_gpd(path: str | Path, title_id: str = "") -> GpdReport:
    """Parse one standalone GPD without changing it."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    size = source.stat().st_size
    if size > MAX_FILE_SIZE:
        raise GpdError(f"GPD exceeds the {MAX_FILE_SIZE}-byte safety limit")
    data = source.read_bytes()
    return parse_gpd_bytes(data, path=source, title_id=title_id)


def export_gpd_image(
    path: str | Path, entry_id: int, destination: str | Path
) -> Path:
    """Export one validated embedded image without changing its GPD."""
    source = Path(path).expanduser().resolve()
    data = source.read_bytes()
    if len(data) > MAX_FILE_SIZE:
        raise GpdError(f"GPD exceeds the {MAX_FILE_SIZE}-byte safety limit")
    if len(data) < XDBF_HEADER.size:
        raise GpdError("GPD is smaller than the XDBF header")
    magic, _version, entry_max, entry_count, free_max, _free_count = XDBF_HEADER.unpack_from(data)
    if magic != XDBF_MAGIC or entry_max > MAX_TABLE_ENTRIES or entry_count > entry_max:
        raise GpdError("GPD has an invalid XDBF header")
    header_size = XDBF_HEADER.size + entry_max * XDBF_ENTRY.size + free_max * XDBF_FREE_ENTRY_SIZE
    for index in range(entry_count):
        namespace, current_id, offset, size = XDBF_ENTRY.unpack_from(
            data, XDBF_HEADER.size + index * XDBF_ENTRY.size
        )
        if namespace != 2 or current_id != entry_id:
            continue
        absolute = header_size + offset
        if offset < 0 or size < 0 or absolute > len(data) or size > len(data) - absolute:
            raise GpdError("Image entry extends beyond the end of the GPD")
        payload = data[absolute:absolute + size]
        image_format = _image_format(payload)
        if not image_format or size > 16 * 1024 * 1024:
            raise GpdError("Embedded image is unsupported or exceeds the safety limit")
        target = Path(destination).expanduser().resolve()
        expected_suffix = ".jpg" if image_format == "jpeg" else f".{image_format}"
        if target.suffix.casefold() != expected_suffix:
            target = target.with_suffix(expected_suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".partial")
        temporary.write_bytes(payload)
        try:
            from PIL import Image
            with Image.open(temporary) as image:
                image.verify()
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise GpdError(f"Embedded image failed validation: {exc}") from exc
        if target.exists() and hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(payload).digest():
            temporary.unlink(missing_ok=True)
            raise FileExistsError(target)
        temporary.replace(target)
        return target
    raise KeyError(f"GPD image entry {entry_id} was not found")


def parse_gpd_bytes(
    data: bytes,
    *,
    path: str | Path = "memory.gpd",
    title_id: str = "",
) -> GpdReport:
    """Parse bytes using XDBF offsets documented by the X360/Le Fluffie lineage."""
    if len(data) < XDBF_HEADER.size:
        raise GpdError("GPD is smaller than the XDBF header")
    magic, version, entry_max, entry_count, free_max, free_count = XDBF_HEADER.unpack_from(
        data
    )
    if magic != XDBF_MAGIC:
        raise GpdError("File is not an XDBF/GPD database")
    for label, value in (
        ("entry capacity", entry_max),
        ("entry count", entry_count),
        ("free-entry capacity", free_max),
        ("free-entry count", free_count),
    ):
        if value > MAX_TABLE_ENTRIES:
            raise GpdError(f"XDBF {label} exceeds the safety limit")
    if entry_count > entry_max:
        raise GpdError("XDBF entry count exceeds its table capacity")
    if free_count > free_max:
        raise GpdError("XDBF free-entry count exceeds its table capacity")

    header_size = (
        XDBF_HEADER.size
        + (entry_max * XDBF_ENTRY.size)
        + (free_max * XDBF_FREE_ENTRY_SIZE)
    )
    if header_size > len(data):
        raise GpdError("XDBF table extends beyond the end of the file")

    entries: list[XdbfEntry] = []
    namespace_counts: dict[str, int] = {}
    for index in range(entry_count):
        table_offset = XDBF_HEADER.size + (index * XDBF_ENTRY.size)
        namespace, entry_id, offset, entry_size = XDBF_ENTRY.unpack_from(
            data, table_offset
        )
        if offset < 0 or entry_size < 0:
            raise GpdError(f"XDBF entry {index} has a negative offset or size")
        absolute = header_size + offset
        if absolute > len(data) or entry_size > len(data) - absolute:
            raise GpdError(f"XDBF entry {index} extends beyond the end of the file")
        entry = XdbfEntry(namespace, entry_id, offset, entry_size)
        entries.append(entry)
        name = entry.namespace_name
        namespace_counts[name] = namespace_counts.get(name, 0) + 1

    achievements: list[GpdAchievement] = []
    settings: list[GpdSetting] = []
    titles: list[GpdTitleHistory] = []
    images: list[GpdImage] = []
    warnings: list[str] = []
    for entry in entries:
        payload = data[
            header_size + entry.offset : header_size + entry.offset + entry.size
        ]
        if entry.namespace == 1 and entry.entry_id not in {-1, -2}:
            try:
                achievements.append(_parse_achievement(entry, payload))
            except GpdError as exc:
                warnings.append(f"Achievement {entry.entry_id}: {exc}")
        elif entry.namespace == 3 and entry.entry_id not in {-1, -2}:
            try:
                settings.append(_parse_setting(entry, payload))
            except GpdError as exc:
                warnings.append(f"Setting {entry.entry_id}: {exc}")
        elif entry.namespace == 4 and entry.entry_id not in {-1, -2}:
            try:
                titles.append(_parse_title_history(entry, payload))
            except GpdError as exc:
                warnings.append(f"Title {entry.entry_id}: {exc}")
        elif entry.namespace == 2 and entry.entry_id not in {-1, -2}:
            image_format = _image_format(payload)
            if image_format:
                images.append(
                    GpdImage(
                        entry.entry_id,
                        image_format,
                        len(payload),
                        hashlib.sha256(payload).hexdigest().upper(),
                    )
                )
            else:
                warnings.append(f"Image {entry.entry_id}: unsupported or malformed image")

    source = Path(path)
    inferred = source.stem.upper() if TITLE_ID_RE.fullmatch(source.stem) else ""
    normalized_title_id = title_id.strip().upper() or inferred
    if normalized_title_id and not TITLE_ID_RE.fullmatch(normalized_title_id):
        raise GpdError(f"Invalid TitleID: {normalized_title_id}")
    return GpdReport(
        source,
        normalized_title_id,
        version,
        hashlib.sha256(data).hexdigest().upper(),
        len(data),
        entry_count,
        tuple(sorted(achievements, key=lambda item: item.achievement_id)),
        tuple(sorted(settings, key=lambda item: item.setting_id)),
        tuple(sorted(titles, key=lambda item: item.last_played_at, reverse=True)),
        tuple(sorted(images, key=lambda item: item.entry_id)),
        namespace_counts,
        tuple(warnings),
    )


def _parse_achievement(entry: XdbfEntry, payload: bytes) -> GpdAchievement:
    if len(payload) < 0x1C:
        raise GpdError("record is smaller than the achievement header")
    achievement_id, image_id, gamerscore = struct.unpack_from(">iiI", payload, 4)
    flags = payload[16:20]
    filetime = struct.unpack_from(">q", payload, 20)[0]
    state = {
        0x12: "unlocked-offline",
        0x13: "unlocked-online",
    }.get(flags[1], "locked")
    strings = _split_utf16be_strings(payload[0x1C:], limit=3)
    while len(strings) < 3:
        strings.append("")
    return GpdAchievement(
        entry.entry_id,
        achievement_id,
        image_id,
        gamerscore,
        state,
        _filetime_iso(filetime) if state == "unlocked-online" else "",
        strings[0],
        strings[1],
        strings[2],
    )


def _parse_setting(entry: XdbfEntry, payload: bytes) -> GpdSetting:
    if len(payload) < 0x18:
        raise GpdError("record is smaller than the setting header")
    setting_id = struct.unpack_from(">i", payload, 0)[0]
    type_id = payload[8]
    type_name = SETTING_TYPES.get(type_id, f"unknown-{type_id}")
    value_area = payload[16:24]
    if type_id in {0, 1}:
        value: Any = struct.unpack_from(">I", value_area)[0]
    elif type_id in {2, 7}:
        raw = struct.unpack_from(">q", value_area)[0]
        value = _filetime_iso(raw) if type_id == 7 else raw
    elif type_id == 3:
        value = struct.unpack_from(">d", value_area)[0]
    elif type_id == 5:
        value = struct.unpack_from(">f", value_area)[0]
    elif type_id in {4, 6}:
        length = struct.unpack_from(">i", value_area)[0]
        if length < 0 or length > len(payload) - 0x18:
            raise GpdError("variable-length setting has an invalid length")
        raw = payload[0x18 : 0x18 + length]
        value = (
            raw.decode("utf-16-be", errors="replace").rstrip("\0")
            if type_id == 4
            else raw.hex().upper()
        )
    else:
        value = value_area.hex().upper()
    return GpdSetting(entry.entry_id, setting_id, type_name, value)


def _parse_title_history(entry: XdbfEntry, payload: bytes) -> GpdTitleHistory:
    if len(payload) < 0x28:
        raise GpdError("record is smaller than the title-history header")
    title_id, possible_count, earned_count, possible_score, earned_score = (
        struct.unpack_from(">IIIII", payload, 0)
    )
    filetime = struct.unpack_from(">q", payload, 0x20)[0]
    title_bytes = payload[0x28:]
    title = title_bytes.decode("utf-16-be", errors="replace").split("\0", 1)[0]
    return GpdTitleHistory(
        entry.entry_id,
        f"{title_id:08X}",
        title,
        earned_count,
        possible_count,
        earned_score,
        possible_score,
        _filetime_iso(filetime),
    )


def _image_format(payload: bytes) -> str:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if payload.startswith(b"BM"):
        return "bmp"
    return ""


def _split_utf16be_strings(data: bytes, limit: int) -> list[str]:
    result: list[str] = []
    current = bytearray()
    for index in range(0, len(data) - 1, 2):
        pair = data[index : index + 2]
        if pair == b"\0\0":
            result.append(current.decode("utf-16-be", errors="replace"))
            current.clear()
            if len(result) >= limit:
                break
        else:
            current.extend(pair)
    if current and len(result) < limit:
        result.append(current.decode("utf-16-be", errors="replace"))
    return result


def _filetime_iso(value: int) -> str:
    if value <= 0:
        return ""
    try:
        origin = datetime(1601, 1, 1, tzinfo=timezone.utc)
        return (origin + timedelta(microseconds=value / 10)).isoformat()
    except (OverflowError, ValueError):
        return ""
