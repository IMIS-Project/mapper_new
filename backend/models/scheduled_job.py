"""SQLite-backed scheduler configuration and execution history."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.core.clock import local_now


class SchedulerBase(DeclarativeBase):
    """Declarative base reserved for the standalone scheduler SQLite database."""


def _localnow() -> datetime:
    return local_now()


class ScheduledJob(SchedulerBase):
    """Configuration for one recurring HTTP request."""

    __tablename__ = "scheduled_jobs"
    __table_args__ = (Index("idx_scheduled_jobs_enabled", "enabled"),)

    job_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False, default="GET")

    headers: Mapped[str | None] = mapped_column(Text, nullable=True)

    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    cron: Mapped[str | None] = mapped_column(String(255), nullable=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_localnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_localnow, onupdate=_localnow
    )


class ScheduledJobRun(SchedulerBase):
    """One result from a scheduled HTTP request."""

    __tablename__ = "scheduled_job_runs"
    __table_args__ = (Index("idx_scheduled_job_runs_recent", "job_id", "ran_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)

    request_headers: Mapped[str | None] = mapped_column(Text, nullable=True)

    response_headers: Mapped[str | None] = mapped_column(Text, nullable=True)

    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)

    response_body_truncated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    response_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_localnow
    )


__all__ = ["ScheduledJob", "ScheduledJobRun", "SchedulerBase"]
