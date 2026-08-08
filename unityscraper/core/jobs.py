"""Shared job result types for long-running desktop, CLI, and API workflows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
ProgressCallback = Callable[["JobProgress"], None]
JobOperation = Callable[["JobContext"], "JobResult"]


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


class JobCancelled(RuntimeError):
    """Raised when a job notices a cancellation request."""


@dataclass
class CancellationToken:
    """Small cooperative cancellation token shared with long operations."""

    requested: bool = False

    def cancel(self) -> None:
        self.requested = True

    def throw_if_cancelled(self) -> None:
        if self.requested:
            raise JobCancelled("Job was cancelled")


@dataclass
class JobContext:
    """Context passed to a UI-neutral job operation."""

    name: str
    token: CancellationToken = field(default_factory=CancellationToken)
    progress_callback: ProgressCallback | None = None

    def emit(
        self,
        message: str,
        *,
        status: JobStatus = "running",
        current: int = 0,
        total: int = 0,
        **details: Any,
    ) -> JobProgress:
        progress = JobProgress(
            status=status,
            message=message,
            current=current,
            total=total,
            details=details,
        )
        if self.progress_callback is not None:
            self.progress_callback(progress)
        return progress

    def throw_if_cancelled(self) -> None:
        self.token.throw_if_cancelled()


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

    @classmethod
    def cancelled(cls, message: str = "Job was cancelled", **payload: Any) -> "JobResult":
        now = utc_now()
        return cls(
            status="cancelled",
            message=message,
            payload=payload,
            started_at=now,
            finished_at=now,
        )


@dataclass(frozen=True)
class JobRunner:
    """Run a UI-neutral operation and normalize its terminal result."""

    progress_callback: ProgressCallback | None = None

    def run(
        self,
        name: str,
        operation: JobOperation,
        *,
        token: CancellationToken | None = None,
    ) -> JobResult:
        context = JobContext(
            name=name,
            token=token or CancellationToken(),
            progress_callback=self.progress_callback,
        )
        context.emit(f"{name} started", status="running")
        try:
            context.throw_if_cancelled()
            result = operation(context)
            context.emit(result.message, status=result.status)
            return result
        except JobCancelled as exc:
            result = JobResult.cancelled(str(exc), job=name)
            context.emit(result.message, status="cancelled")
            return result
        except Exception as exc:
            result = JobResult.failed(str(exc), job=name)
            context.emit(result.message, status="failed")
            return result


__all__ = [
    "CancellationToken",
    "JobCancelled",
    "JobContext",
    "JobOperation",
    "JobProgress",
    "JobResult",
    "JobRunner",
    "JobStatus",
    "ProgressCallback",
    "utc_now",
]
