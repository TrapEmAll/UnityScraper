"""Read-only XBE and XEX metadata inspection."""

from __future__ import annotations

from pathlib import Path

from .errors import InvalidPackageError
from .models import XbePackage, XexPackage


def inspect_xbe(path: str | Path) -> XbePackage:
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
        package_path,
        title_id,
        title_name,
        package_path.stat().st_size,
        int.from_bytes(certificate[0x9C:0xA0], "little"),
        int.from_bytes(certificate[0xA0:0xA4], "little"),
        int.from_bytes(certificate[0xA8:0xAC], "little"),
        int.from_bytes(certificate[0xAC:0xB0], "little"),
    )


def inspect_xex(path: str | Path) -> XexPackage:
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
        return f"{(value >> 28) & 0xF}.{(value >> 24) & 0xF}.{(value >> 8) & 0xFFFF}.{value & 0xFF}"

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


__all__ = ["inspect_xbe", "inspect_xex"]
