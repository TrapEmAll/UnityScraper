"""App-start knowledge refresh scheduling with persistent, opt-in state."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app_paths import DATABASE_PATH
from unityscraper.core.scheduling import ScheduledTask


TASK_NAME = "knowledge-refresh"
MIN_INTERVAL_HOURS = 6


class KnowledgeScheduler(ScheduledTask):
    """Run cached/rate-limited imports when an enabled schedule becomes due."""

    def __init__(self, database_path: str | Path = DATABASE_PATH) -> None:
        super().__init__(
            database_path,
            TASK_NAME,
            default_interval_hours=168,
            min_interval_hours=MIN_INTERVAL_HOURS,
        )

    def run_if_due(self, sync: Callable[[], Any] | None = None) -> dict[str, Any] | None:
        return super().run_if_due(sync or _sync_all)


def _sync_all() -> dict[str, Any]:
    from knowledge_sync import sync_consolemods_knowledge, sync_reference_wikis

    return {
        "consolemods": sync_consolemods_knowledge(),
        "wikis": sync_reference_wikis(),
    }
