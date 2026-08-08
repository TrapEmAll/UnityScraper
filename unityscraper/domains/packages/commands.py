"""UI-neutral package inspection use cases."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from unityscraper.core.jobs import JobResult

from .inspectors import inspect_stfs, list_stfs_entries


class InspectStfsPackage:
    """Read public STFS metadata without modifying the package."""

    def run(self, source: str | Path) -> JobResult:
        path = Path(source)
        try:
            package = inspect_stfs(path)
        except Exception as exc:
            return JobResult.failed(
                "STFS inspection failed",
                source=str(path),
                error=str(exc),
            )
        return JobResult.completed(
            "STFS inspection completed",
            source=str(path),
            package=asdict(package),
        )


class InventoryStfsFileTable:
    """Read the supported consecutive STFS file table without extraction."""

    def run(self, source: str | Path, *, max_entries: int = 100_000) -> JobResult:
        path = Path(source)
        try:
            entries = list_stfs_entries(path, max_entries=max_entries)
        except Exception as exc:
            return JobResult.failed(
                "STFS file table inventory failed",
                source=str(path),
                error=str(exc),
            )
        return JobResult.completed(
            "STFS file table inventory completed",
            source=str(path),
            entry_count=len(entries),
            entries=[asdict(entry) for entry in entries],
        )


__all__ = ["InspectStfsPackage", "InventoryStfsFileTable"]
