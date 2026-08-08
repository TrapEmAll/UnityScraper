"""Shared job result types for long-running desktop, CLI, and API workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class JobProgress:
    """A UI-neutral progress update from a long-running operation."""

    status: JobStatus
    message: str
    current: int = 0
    total: int = 0
    details: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=utc_now)

    @property
    def percent(self) -> float | None:
        if self.total <= 0:
            return None
        return min(100.0, max(0.0, (self.current / self.total) * 100.0))


@dataclass(frozen=True)
class JobResult:
    """A UI-neutral operation result."""

    status: JobStatus
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None

    @classmethod
    def completed(cls, message: str, **payload: Any) -> "JobResult":
        now = utc_now()
        return cls(
            status="completed",
            message=message,
            payload=payload,
            started_at=now,
            finished_at=now,
        )

    @classmethod
    def failed(cls, message: str, **payload: Any) -> "JobResult":
        now = utc_now()
        return cls(
            status="failed",
            message=message,
            payload=payload,
            started_at=now,
            finished_at=now,
        )

