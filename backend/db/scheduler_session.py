import logging
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.clock import utc_naive_to_local
from backend.core.config import settings

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_scheduler_path = Path(settings.SCHEDULER_DATABASE_PATH).expanduser()
if not _scheduler_path.is_absolute():
    _scheduler_path = PROJECT_ROOT / _scheduler_path

SCHEDULER_DATABASE_PATH = str(_scheduler_path)
SCHEDULER_ASYNC_DATABASE_URL = f"sqlite+aiosqlite:///{SCHEDULER_DATABASE_PATH}"
SCHEDULER_SYNC_DATABASE_URL = f"sqlite:///{SCHEDULER_DATABASE_PATH}"

scheduler_engine = create_async_engine(
    SCHEDULER_ASYNC_DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)
SchedulerSessionLocal = async_sessionmaker(
    bind=scheduler_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


async def get_scheduler_db() -> AsyncGenerator[AsyncSession, None]:
    async with SchedulerSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("scheduled_jobs", "headers", "TEXT"),
    ("scheduled_jobs", "body", "TEXT"),
    ("scheduled_job_runs", "request_headers", "TEXT"),
    ("scheduled_job_runs", "response_headers", "TEXT"),
    ("scheduled_job_runs", "response_body", "TEXT"),
    (
        "scheduled_job_runs",
        "response_body_truncated",
        "BOOLEAN NOT NULL DEFAULT 0",
    ),
    ("scheduled_job_runs", "response_size", "INTEGER"),
)


def _add_missing_scheduler_columns(connection) -> None:
    """Add post-release scheduler columns to a pre-existing database."""
    inspector = sa_inspect(connection)
    for table, column, ddl_type in _ADDED_COLUMNS:
        if not inspector.has_table(table):
            continue
        if column in {item["name"] for item in inspector.get_columns(table)}:
            continue
        connection.exec_driver_sql(
            f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"
        )


def _parse_stored_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    return datetime.fromisoformat(text_value)


def _migrate_legacy_utc_timestamps(connection) -> None:
    """Convert pre-local scheduler rows from naive UTC to system-local time.

    Earlier releases stored ``ran_at``/``created_at``/``updated_at`` in UTC.
    The schema now stores system-local wall-clock values, so an existing
    history must be shifted once.  ``PRAGMA user_version`` makes the migration
    idempotent across restarts.
    """
    version = int(connection.exec_driver_sql("PRAGMA user_version").scalar() or 0)
    if version >= 1:
        return

    inspector = sa_inspect(connection)
    converted = 0

    if inspector.has_table("scheduled_jobs"):
        rows = connection.execute(
            text("SELECT job_id, created_at, updated_at FROM scheduled_jobs")
        ).mappings()
        updates = []
        for row in rows:
            created = _parse_stored_datetime(row["created_at"])
            updated = _parse_stored_datetime(row["updated_at"])
            if created is None and updated is None:
                continue
            updates.append(
                {
                    "job_id": row["job_id"],
                    "created_at": (
                        utc_naive_to_local(created) if created is not None else None
                    ),
                    "updated_at": (
                        utc_naive_to_local(updated) if updated is not None else None
                    ),
                }
            )
        if updates:
            connection.execute(
                text(
                    "UPDATE scheduled_jobs "
                    "SET created_at = :created_at, updated_at = :updated_at "
                    "WHERE job_id = :job_id"
                ),
                updates,
            )
            converted += len(updates)

    if inspector.has_table("scheduled_job_runs"):
        rows = connection.execute(
            text("SELECT id, ran_at FROM scheduled_job_runs")
        ).mappings()
        updates = []
        for row in rows:
            ran_at = _parse_stored_datetime(row["ran_at"])
            if ran_at is None:
                continue
            updates.append(
                {
                    "id": row["id"],
                    "ran_at": utc_naive_to_local(ran_at),
                }
            )
        if updates:
            connection.execute(
                text("UPDATE scheduled_job_runs SET ran_at = :ran_at WHERE id = :id"),
                updates,
            )
            converted += len(updates)

    connection.exec_driver_sql("PRAGMA user_version = 1")
    if converted:
        logger.info(
            "Converted %s legacy scheduler timestamp(s) from UTC to local time",
            converted,
        )


async def create_scheduler_tables() -> None:
    from backend.models.scheduled_job import (
        ScheduledJob,
        ScheduledJobRun,
        SchedulerBase,
    )

    _scheduler_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with scheduler_engine.begin() as connection:
            await connection.run_sync(
                SchedulerBase.metadata.create_all,
                tables=[ScheduledJob.__table__, ScheduledJobRun.__table__],
            )
            await connection.run_sync(_add_missing_scheduler_columns)
            await connection.run_sync(_migrate_legacy_utc_timestamps)
    except Exception:
        await scheduler_engine.dispose()
        raise


async def dispose_scheduler_engine() -> None:
    await scheduler_engine.dispose()
