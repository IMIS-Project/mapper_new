"""Scheduler lifecycle, execution, and run-history queries."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.base import SchedulerNotRunningError
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.redaction import mask_sensitive
from backend.db.scheduler_session import (
    SCHEDULER_SYNC_DATABASE_URL,
    SchedulerSessionLocal,
    create_scheduler_tables,
    dispose_scheduler_engine,
)
from backend.db.session import AsyncSessionLocal
from backend.models.scheduled_job import ScheduledJob, ScheduledJobRun
from backend.schemas.scheduled_job import ScheduledJobCreate
from backend.services import mapping_job_service
from backend.services.log_writer import write_call_log
from backend.services.scheduler_security import (
    UnsafeDestinationError,
    build_pinned_request,
    validate_destination_async,
)
from backend.services.upstream_auth import (
    apply_upstream_auth,
    drop_token_header,
    invalidate_token,
)

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(
    jobstores={"default": SQLAlchemyJobStore(url=SCHEDULER_SYNC_DATABASE_URL)},
    timezone=settings.SCHEDULER_TIMEZONE,
)
_http_client: httpx.AsyncClient | None = None
_execution_semaphore: asyncio.Semaphore | None = None


class SchedulerConflictError(Exception):
    """A scheduler ID is already in use."""


class SchedulerNotFoundError(Exception):
    """A scheduler configuration no longer exists."""


class SchedulerJobDisabledError(Exception):
    """A scheduler job exists but is currently disabled."""


class SchedulerLimitError(Exception):
    """The scheduler job limit has been reached."""


def build_trigger(*, cron: str | None = None, interval_seconds: int | None = None):
    if (cron is None) == (interval_seconds is None):
        raise ValueError("provide exactly one of cron or interval_seconds")
    if cron is not None:
        return CronTrigger.from_crontab(cron, timezone=settings.SCHEDULER_TIMEZONE)
    return IntervalTrigger(
        seconds=int(interval_seconds), timezone=settings.SCHEDULER_TIMEZONE
    )


def dump_headers(headers: dict[str, str] | None) -> str | None:
    """Serialise a header mapping to JSON for the scheduler SQLite columns."""
    if not headers:
        return None
    return json.dumps(headers, ensure_ascii=False, sort_keys=True)


def load_headers(value: str | None) -> dict[str, str] | None:
    """Read back a header mapping, tolerating rows written before this column."""
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return {str(key): str(item) for key, item in parsed.items()}


def _decode_body(payload: bytes) -> str:
    """Decode a captured body, replacing undecodable bytes instead of failing."""
    return payload.decode("utf-8", errors="replace")


def _capture_body(text: str) -> tuple[str | None, bool]:
    """Trim an already-serialised payload to the stored response limit."""
    limit = int(settings.SCHEDULER_MAX_RESPONSE_BODY_BYTES)
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", errors="replace"), True


def guess_content_type(body: str) -> str:
    """Pick a default Content-Type for a body the user did not label."""
    if body.lstrip()[:1] in "{[":
        return "application/json"
    if body.lstrip()[:1] == "<":
        return "application/xml"
    return "text/plain; charset=utf-8"


def _skipped_run(
    job_id: str,
    url: str,
    method: str,
    reason: str,
    started: float,
) -> ScheduledJobRun:
    """Transient run describing a job that was not allowed to execute.

    It is deliberately not added to the session: a stale APScheduler entry for
    a deleted/disabled row must not create a new history row on every tick.
    """
    return ScheduledJobRun(
        job_id=job_id,
        url=url,
        method=method,
        request_headers=None,
        response_headers=None,
        response_body=None,
        response_body_truncated=False,
        response_size=None,
        status_code=None,
        success=False,
        duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
        error=reason,
        ran_at=datetime.now(timezone.utc),
    )


async def is_mapping_backed(url: str, method: str) -> bool:
    """True when ``url``/``method`` resolve to an active API mapping.

    Such a job dials destinations an administrator registered in
    ``api_endpoint`` — the same rows the gateway already calls on every inbound
    request — so the allowlist that guards user-typed scheduler URLs does not
    apply to them. The lookup itself is a plain SELECT.
    """
    try:
        endpoint = await mapping_job_service.resolve_endpoint(url, method)
    except Exception:
        logger.warning(
            "Could not check whether %s %s is mapping-backed",
            method,
            url,
            exc_info=True,
        )
        return False
    return endpoint is not None


async def start_scheduler(http_client: httpx.AsyncClient) -> None:
    global _execution_semaphore, _http_client
    await create_scheduler_tables()
    _http_client = http_client
    _execution_semaphore = asyncio.Semaphore(settings.SCHEDULER_MAX_CONCURRENT_JOBS)
    if not scheduler.running:
        scheduler.start()
    await reconcile_jobs()


async def stop_scheduler() -> None:
    global _execution_semaphore, _http_client
    if scheduler.running:
        scheduler.shutdown(wait=True)
    await dispose_scheduler_engine()
    _execution_semaphore = None
    _http_client = None


def get_job(job_id: str):
    if not scheduler.running:
        return None
    return scheduler.get_job(job_id)


def _add_live_job(row: ScheduledJob) -> None:
    if not scheduler.running:
        raise SchedulerNotRunningError("Scheduler is not running")
    scheduler.add_job(
        execute_scheduled_job,
        trigger=build_trigger(cron=row.cron, interval_seconds=row.interval_seconds),
        args=[row.job_id, row.url, row.method],
        id=row.job_id,
        name=row.name or row.job_id,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )


async def _fetch_job(db: AsyncSession, job_id: str) -> ScheduledJob | None:
    return await db.get(ScheduledJob, job_id)


def _restore_live_job(
    job_id: str,
    url: str,
    method: str,
    name: str | None,
    cron: str | None,
    interval_seconds: int | None,
) -> None:
    scheduler.add_job(
        execute_scheduled_job,
        trigger=build_trigger(cron=cron, interval_seconds=interval_seconds),
        args=[job_id, url, method],
        id=job_id,
        name=name or job_id,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )


def _restore_scheduler_jobs(jobs) -> None:
    for live_job in scheduler.get_jobs():
        try:
            scheduler.remove_job(live_job.id)
        except JobLookupError:
            pass
    for job in jobs:
        scheduler.add_job(
            job.func,
            trigger=job.trigger,
            args=job.args,
            kwargs=job.kwargs,
            id=job.id,
            name=job.name,
            replace_existing=True,
            max_instances=job.max_instances,
            coalesce=job.coalesce,
            misfire_grace_time=job.misfire_grace_time,
        )


async def reconcile_jobs() -> None:
    previous_jobs = list(scheduler.get_jobs())
    async with SchedulerSessionLocal() as db:
        try:
            result = await db.execute(
                select(ScheduledJob).where(ScheduledJob.enabled.is_(True))
            )
            rows = list(result.scalars().all())
            configured = set()
            for row in rows:
                try:
                    if not await is_mapping_backed(row.url, row.method):
                        await validate_destination_async(
                            mapping_job_service.resolve_internal_url(row.url)
                        )
                    build_trigger(cron=row.cron, interval_seconds=row.interval_seconds)
                except (UnsafeDestinationError, ValueError):
                    row.enabled = False
                    continue
                configured.add(row.job_id)
                _add_live_job(row)
            for live_job in scheduler.get_jobs():
                if live_job.id not in configured:
                    try:
                        scheduler.remove_job(live_job.id)
                    except JobLookupError:
                        pass
            await db.commit()
        except Exception:
            await db.rollback()
            try:
                _restore_scheduler_jobs(previous_jobs)
            except Exception:
                logger.exception(
                    "Could not restore scheduler state after reconciliation failure"
                )
            raise


async def create_job(
    db: AsyncSession, payload: ScheduledJobCreate, created_by: int | None = None
) -> ScheduledJob:
    if await _fetch_job(db, payload.job_id) is not None or get_job(payload.job_id):
        raise SchedulerConflictError("Scheduled job ID already exists")
    count_result = await db.execute(select(func.count(ScheduledJob.job_id)))
    if int(count_result.scalar_one() or 0) >= settings.SCHEDULER_MAX_JOBS:
        raise SchedulerLimitError("Scheduled job limit reached")
    if not await is_mapping_backed(payload.url, payload.method):
        await validate_destination_async(
            mapping_job_service.resolve_internal_url(payload.url)
        )
    build_trigger(cron=payload.cron, interval_seconds=payload.interval_seconds)
    row = ScheduledJob(
        job_id=payload.job_id,
        name=payload.name,
        url=payload.url,
        method=payload.method,
        headers=dump_headers(payload.headers),
        body=payload.body,
        cron=payload.cron,
        interval_seconds=payload.interval_seconds,
        enabled=True,
        created_by=created_by,
    )
    _add_live_job(row)
    db.add(row)
    try:
        await db.commit()
        await db.refresh(row)
    except Exception:
        await db.rollback()
        try:
            scheduler.remove_job(row.job_id)
        except JobLookupError:
            pass
        raise
    return row


async def list_jobs(db: AsyncSession) -> list[ScheduledJob]:
    result = await db.execute(
        select(ScheduledJob).order_by(ScheduledJob.created_at.desc())
    )
    return list(result.scalars().all())


async def get_latest_run(db: AsyncSession, job_id: str) -> ScheduledJobRun | None:
    result = await db.execute(
        select(ScheduledJobRun)
        .where(ScheduledJobRun.job_id == job_id)
        .order_by(ScheduledJobRun.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_runs(
    db: AsyncSession, job_id: str, limit: int = 50
) -> list[ScheduledJobRun]:
    result = await db.execute(
        select(ScheduledJobRun)
        .where(ScheduledJobRun.job_id == job_id)
        .order_by(ScheduledJobRun.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_all_runs(db: AsyncSession, limit: int = 100) -> list[ScheduledJobRun]:
    result = await db.execute(
        select(ScheduledJobRun).order_by(ScheduledJobRun.id.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def get_run(db: AsyncSession, run_id: int) -> ScheduledJobRun | None:
    return await db.get(ScheduledJobRun, run_id)


async def delete_job(db: AsyncSession, job_id: str) -> bool:
    row = await _fetch_job(db, job_id)
    if row is None:
        return False
    was_enabled = row.enabled
    job_values = (
        row.job_id,
        row.url,
        row.method,
        row.name,
        row.cron,
        row.interval_seconds,
    )
    try:
        scheduler.remove_job(job_id)
    except (JobLookupError, SchedulerNotRunningError):
        pass
    try:
        await db.delete(row)
        await db.commit()
    except Exception:
        await db.rollback()
        if was_enabled:
            _restore_live_job(*job_values)
        raise
    return True


async def set_job_enabled(db: AsyncSession, job_id: str, enabled: bool) -> ScheduledJob:
    row = await _fetch_job(db, job_id)
    if row is None:
        raise SchedulerNotFoundError("Scheduled job not found")
    previous = row.enabled
    job_values = (
        row.job_id,
        row.url,
        row.method,
        row.name,
        row.cron,
        row.interval_seconds,
    )
    if enabled:
        if not await is_mapping_backed(row.url, row.method):
            await validate_destination_async(
                mapping_job_service.resolve_internal_url(row.url)
            )
        _add_live_job(row)
    else:
        try:
            scheduler.remove_job(job_id)
        except (JobLookupError, SchedulerNotRunningError):
            pass
    row.enabled = enabled
    row.updated_at = datetime.now(timezone.utc)
    try:
        await db.commit()
        await db.refresh(row)
    except Exception:
        await db.rollback()
        if enabled:
            try:
                scheduler.remove_job(job_id)
            except JobLookupError:
                pass
        elif previous:
            _restore_live_job(*job_values)
        raise
    return row


async def _persist_run(run: ScheduledJobRun) -> None:
    async with SchedulerSessionLocal() as db:
        try:
            db.add(run)
            await db.flush()
            cutoff = datetime.now(timezone.utc) - timedelta(
                days=settings.SCHEDULER_RUN_RETENTION_DAYS
            )
            await db.execute(
                delete(ScheduledJobRun).where(ScheduledJobRun.ran_at < cutoff)
            )
            await db.commit()
            await db.refresh(run)
        except Exception:
            await db.rollback()
            logger.exception("Could not persist scheduled job run %s", run.job_id)
            raise


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, UnsafeDestinationError):
        return str(exc)
    if isinstance(exc, httpx.TimeoutException):
        return "Request timed out"
    if isinstance(exc, httpx.RequestError):
        return "Request failed"
    return type(exc).__name__


def _parsed_body(body: Any) -> Any:
    """Parse a captured body as JSON when possible, otherwise keep it as-is."""
    if body is None:
        return None
    if not isinstance(body, str):
        return body
    stripped = body.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except (TypeError, ValueError):
        return body


def _api_call_log_data(
    job: ScheduledJob | None,
    run: ScheduledJobRun,
    mapping: mapping_job_service.MappingJobOutcome | None,
) -> dict[str, Any]:
    """Translate a scheduler run into the ``log_data`` shape write_call_log reads."""
    if mapping is not None:
        external = mapping.external
        internal = mapping.internal
        return {
            "endpoint_id": mapping.endpoint_id,
            "method": run.method,
            "path": run.url,
            # Internal leg: the API the cron job delivers the payload to.
            "request_headers": dict(internal.request_headers) if internal else {},
            "response_headers": dict(internal.response_headers) if internal else {},
            "internal_request_body": external.body,
            "status_code": mapping.status_code,
            "data": _parsed_body(internal.body) if internal else None,
            "source_response": _parsed_body(internal.body) if internal else None,
            # External leg: the API the mapper calls first.
            "external_request_url": external.url,
            "external_request_method": external.method,
            "external_request_headers": dict(external.request_headers),
            "external_request_body": mapping.external_request_body or {},
            "external_query_params": mapping.external_query_params,
            "external_response_headers": dict(external.response_headers),
            "external_status_code": external.status_code,
            "external_response_time_ms": external.duration_ms,
            "target_response": external.body,
            "success": mapping.success,
            "error": mapping.error,
            "total_time_ms": run.duration_ms,
            "status": "SUCCESS" if mapping.success else "FAILED",
        }

    job_body = _parsed_body(job.body) if job is not None else None
    return {
        "endpoint_id": None,
        "method": run.method,
        "path": run.url,
        "request_headers": load_headers(run.request_headers) or {},
        "response_headers": load_headers(run.response_headers) or {},
        "request_body": job_body if isinstance(job_body, (dict, list)) else None,
        "status_code": run.status_code,
        "data": _parsed_body(run.response_body),
        "success": run.success,
        "error": run.error,
        "total_time_ms": run.duration_ms,
        "status": "SUCCESS" if run.success else "FAILED",
    }


async def _mirror_to_api_call_log(
    job: ScheduledJob | None,
    run: ScheduledJobRun,
    mapping: mapping_job_service.MappingJobOutcome | None,
) -> None:
    """Best-effort copy of one scheduled run into the main ``api_call_log``.

    The scheduler's SQLite history remains the source of truth for the cron
    UI. This mirror makes scheduled traffic visible in the log dashboard next
    to every other mapped call. A logging failure must never fail the job.
    """
    try:
        async with AsyncSessionLocal() as db:
            await write_call_log(db, _api_call_log_data(job, run, mapping))
    except Exception:
        logger.warning(
            "Could not mirror scheduled job %s into api_call_log",
            run.job_id,
            exc_info=True,
        )


async def _send_stream_request(
    client: httpx.AsyncClient,
    method: str,
    request_url: str,
    send_headers: dict[str, str],
    extensions: dict | None,
    request_kwargs: dict,
) -> tuple[int | None, dict[str, str], str | None, bool, int]:
    """Perform one streamed request and capture a bounded response."""
    async with client.stream(
        method,
        request_url,
        headers=send_headers,
        extensions=extensions,
        follow_redirects=False,
        timeout=float(settings.SCHEDULER_REQUEST_TIMEOUT_SECONDS),
        **request_kwargs,
    ) as response:
        status_code = response.status_code
        response_headers = dict(response.headers)
        limit = int(settings.SCHEDULER_MAX_RESPONSE_BODY_BYTES)
        buffer = bytearray()
        truncated = False
        async for chunk in response.aiter_bytes():
            remaining = limit - len(buffer)
            if remaining <= 0:
                truncated = True
                break
            buffer.extend(chunk[:remaining])
            if len(chunk) > remaining:
                truncated = True
                break
        body = _decode_body(bytes(buffer)) if buffer else None
        return status_code, response_headers, body, truncated, len(buffer)


async def execute_scheduled_job(job_id: str, url: str, method: str) -> ScheduledJobRun:
    global _http_client
    started = time.perf_counter()
    status_code = None
    error = None
    request_headers: dict[str, str] = {}
    response_headers: dict[str, str] = {}
    response_body: str | None = None
    response_body_truncated = False
    response_size: int | None = None
    client = _http_client
    temporary_client = None
    semaphore = _execution_semaphore
    row: ScheduledJob | None = None
    mapping: mapping_job_service.MappingJobOutcome | None = None
    if semaphore is None:
        semaphore = asyncio.Semaphore(settings.SCHEDULER_MAX_CONCURRENT_JOBS)
    try:
        async with semaphore:
            async with SchedulerSessionLocal() as db:
                row = await _fetch_job(db, job_id)

            # The live APScheduler entry can outlive a disable/delete (for
            # example when the database is changed outside this process).
            # Re-read the row on every tick and stop before any outbound call.
            if row is None or not row.enabled:
                reason = (
                    "Scheduled job not found"
                    if row is None
                    else "Scheduled job is disabled"
                )
                logger.info("Skipping scheduled job %s: %s", job_id, reason)
                return _skipped_run(job_id, url, method, reason, started)

            headers = load_headers(row.headers)
            body = row.body

            if client is None or client.is_closed:
                temporary_client = httpx.AsyncClient(
                    timeout=float(settings.SCHEDULER_REQUEST_TIMEOUT_SECONDS),
                    follow_redirects=False,
                )
                client = temporary_client

            # A job whose URL + method match an active mapping runs the mapped
            # flow instead: the external API is called first and its response
            # is forwarded verbatim to the internal API. Both tables are only
            # ever SELECTed.
            mapping = await mapping_job_service.execute_mapping_job(
                internal_url=url,
                method=method,
                headers=headers,
                body=body,
                http_client=client,
            )

            if mapping is not None:
                status_code = mapping.status_code
                error = mapping.error
                request_headers = mapping.request_headers
                response_headers = mapping.response_headers
                response_body, response_body_truncated = _capture_body(
                    json.dumps(mapping.payload, ensure_ascii=False, default=str)
                )
                response_size = (
                    len(response_body.encode("utf-8")) if response_body else 0
                )
            else:
                effective_url = mapping_job_service.resolve_internal_url(url)
                addresses = await validate_destination_async(effective_url)
                request_url, pinned_headers, extensions = build_pinned_request(
                    effective_url, addresses[0] if addresses else None
                )
                send_headers = dict(pinned_headers)
                send_headers.update(headers or {})
                request_kwargs = {}
                if body is not None:
                    request_kwargs["content"] = body.encode("utf-8")
                    send_headers.setdefault("content-type", guess_content_type(body))
                # Authenticate every outbound call: a static token when the
                # host has one configured, otherwise a service-account bearer
                # issued by the destination host's auth service.
                injected = await apply_upstream_auth(
                    send_headers, client, effective_url
                )
                request_headers = dict(send_headers)
                (
                    status_code,
                    response_headers,
                    response_body,
                    response_body_truncated,
                    response_size,
                ) = await _send_stream_request(
                    client,
                    method,
                    request_url,
                    send_headers,
                    extensions,
                    request_kwargs,
                )

                # A target that rejects the bearer we just sent may be running
                # an auth service whose advertised lifetime is longer than it
                # actually accepts. Drop the cached token and retry once.
                if status_code == 401 and injected:
                    invalidate_token(effective_url)
                    drop_token_header(send_headers)
                    await apply_upstream_auth(send_headers, client, effective_url)
                    request_headers = dict(send_headers)
                    (
                        status_code,
                        response_headers,
                        response_body,
                        response_body_truncated,
                        response_size,
                    ) = await _send_stream_request(
                        client,
                        method,
                        request_url,
                        send_headers,
                        extensions,
                        request_kwargs,
                    )

                if 300 <= status_code < 400:
                    error = "Redirect responses are not followed"
                elif status_code >= 400:
                    error = f"HTTP {status_code}"
    except Exception as exc:
        error = _safe_error(exc)
        logger.warning("Scheduled job %s failed: %s", job_id, error)
    finally:
        if temporary_client is not None:
            await temporary_client.aclose()

    run = ScheduledJobRun(
        job_id=job_id,
        url=url,
        method=method,
        request_headers=dump_headers(mask_sensitive(request_headers)),
        response_headers=dump_headers(response_headers),
        response_body=response_body,
        response_body_truncated=response_body_truncated,
        response_size=response_size,
        status_code=status_code,
        success=status_code is not None and 200 <= status_code < 300 and error is None,
        duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
        error=error,
        ran_at=datetime.now(timezone.utc),
    )
    await _persist_run(run)
    await _mirror_to_api_call_log(row, run, mapping)
    return run


async def run_job_now(db: AsyncSession, job_id: str) -> ScheduledJobRun:
    row = await _fetch_job(db, job_id)
    if row is None:
        raise SchedulerNotFoundError("Scheduled job not found")
    if not row.enabled:
        raise SchedulerJobDisabledError("Scheduled job is disabled")
    return await execute_scheduled_job(row.job_id, row.url, row.method)
