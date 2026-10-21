from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.schema_probe import probe as schema_probe
from backend.models import ApiCallLog, ApiEndpoint, CallStatusEnum
from backend.schemas.log import CallLogSummary, CallLogResponse
from backend.services import audit_enrichment
from backend.services.log_writer import redact

logger = logging.getLogger(__name__)

__all__ = ["get_log", "list_logs"]

_MAX_PER_PAGE = 200

_MAX_LIMIT = 5000

_VALID_STATUS = {member.value for member in CallStatusEnum}

LOG_ONLY_PLACEHOLDER = "Log only endpoint"


def _resolve_external_url(endpoint: ApiEndpoint | None) -> str:
    if not endpoint or not endpoint.target_api_url:
        return "https://devmis.sspa.gos.pk/api/v1/imis/complaint/create"
    if endpoint.target_api_url.startswith("Workflow:"):
        return "https://devmis.sspa.gos.pk/api/v1/imis/complaint/create"
    return endpoint.target_api_url


def _external_response_or_placeholder(value: object) -> object:
    """Return the log-only placeholder when no upstream response was captured.

    Ingested (log-only) calls store an empty ``target_response`` and legacy
    rows may store ``NULL``; the frontend renders whatever value the API
    returns, so the placeholder string is displayed verbatim in the
    External Response section without any client-side change.
    """
    if value is None:
        return LOG_ONLY_PLACEHOLDER

    if isinstance(value, str):
        return LOG_ONLY_PLACEHOLDER if not value.strip() else value

    if isinstance(value, (dict, list)) and not value:
        return LOG_ONLY_PLACEHOLDER

    return value


def _as_int(value: object) -> int | None:
    if isinstance(value, int):
        return value

    if value in (None, ""):
        return None

    try:
        return int(str(value))
    except (AttributeError, TypeError, ValueError):
        return None


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value

    if value in (None, ""):
        return None

    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


async def list_logs(
    db: AsyncSession,
    *,
    endpoint_id: int | str | None = None,
    status: str | None = None,
    date_from=None,
    date_to=None,
    method: str | None = None,
    page: int = 1,
    per_page: int = 20,
    limit: int | None = None,
) -> tuple[int, list[CallLogSummary], int, int]:
    """Return ``(total, items, page, per_page)``; page is 1-based."""
    await schema_probe.ensure(db)

    conditions = []

    endpoint_int = _as_int(endpoint_id) if endpoint_id is not None else None

    if endpoint_int is not None:
        conditions.append(ApiCallLog.endpoint_id == endpoint_int)

    if status:
        value = str(status).strip().upper()

        if value in _VALID_STATUS:
            conditions.append(ApiCallLog.status == value)

    if method:
        conditions.append(func.upper(ApiEndpoint.method) == str(method).strip().upper())

    start = _as_datetime(date_from)

    if start is not None:
        conditions.append(ApiCallLog.created_at >= start)

    end = _as_datetime(date_to)

    if end is not None:
        conditions.append(ApiCallLog.created_at <= end)

    page = max(1, int(page))
    per_page = max(1, min(int(per_page), _MAX_PER_PAGE))

    offset = (page - 1) * per_page
    row_cap = per_page
    if limit is not None:
        limit = max(1, min(int(limit), _MAX_LIMIT))

        row_cap = max(0, min(per_page, limit - offset))

    count_stmt = (
        select(func.count())
        .select_from(ApiCallLog)
        .outerjoin(
            ApiEndpoint,
            ApiCallLog.endpoint_id == ApiEndpoint.id,
        )
        .where(*conditions)
    )

    count_result = await db.execute(count_stmt)
    total = int(count_result.scalar() or 0)

    if limit is not None:
        total = min(total, limit)

    stmt = (
        select(ApiCallLog, ApiEndpoint)
        .outerjoin(
            ApiEndpoint,
            ApiCallLog.endpoint_id == ApiEndpoint.id,
        )
        .where(*conditions)
        .order_by(ApiCallLog.id.desc())
        .offset(offset)
        .limit(row_cap)
        .options(*schema_probe.load_options())
    )

    result = await db.execute(stmt)

    rows = result.all()

    for log, _endpoint in rows:
        schema_probe.apply_defaults(log)

    items = [
        CallLogSummary(
            id=log.id,
            endpoint_id=log.endpoint_id,
            request_id=str(log.id),
            method=endpoint.method if endpoint else "POST",
            path=endpoint.source_api_url if endpoint else "/api/workflows/webhook",
            status=log.status,
            overall_status=(
                True
                if log.status == "SUCCESS"
                else False
                if log.status is not None
                else None
            ),
            internal_request_headers=redact(log.source_request_headers),
            internal_request_body=redact(log.source_request_payload),
            internal_api_client_response=redact(log.source_response),
            internal_api_client_status=log.client_status_code,
            external_request_url=_resolve_external_url(endpoint),
            external_request_method=endpoint.method if endpoint else "POST",
            external_request_headers=redact(log.target_request_headers),
            external_request_body=redact(log.target_request_payload),
            external_query_params=redact(log.target_query_params),
            external_response=redact(log.target_response),
            external_response_time_ms=log.response_time_ms,
            external_status_code=log.upstream_status_code,
            total_time_ms=log.response_time_ms,
            created_at=log.created_at,
        )
        for log, endpoint in rows
    ]

    supplements = audit_enrichment.enrich_rows(
        [(log.id, log.created_at) for log, _ in rows],
        CallLogSummary.model_fields,
    )

    if supplements:
        for item in items:
            supplement = supplements.get(item.id)
            if supplement:
                for field, value in audit_enrichment.apply(
                    item.model_dump(), supplement
                ).items():
                    if field in item.model_fields:
                        setattr(item, field, value)

    for item in items:
        item.external_response = _external_response_or_placeholder(
            item.external_response
        )

    return total, items, page, per_page


async def get_log(
    db: AsyncSession,
    log_id: int | str,
) -> CallLogResponse | None:
    """Return one call log with endpoint data for the frontend."""

    identifier = _as_int(log_id)

    if identifier is None:
        return None

    await schema_probe.ensure(db)

    result = await db.execute(
        select(ApiCallLog, ApiEndpoint)
        .outerjoin(
            ApiEndpoint,
            ApiCallLog.endpoint_id == ApiEndpoint.id,
        )
        .where(ApiCallLog.id == identifier)
        .options(*schema_probe.load_options())
    )

    row = result.first()

    if row is None:
        return None

    log, endpoint = row

    schema_probe.apply_defaults(log)

    detail = _enrich(
        CallLogResponse(
            id=log.id,
            endpoint_id=log.endpoint_id,
            request_id=str(log.id),
            method=endpoint.method if endpoint else "POST",
            path=endpoint.source_api_url if endpoint else "/api/workflows/webhook",
            status=log.status,
            error_message=log.error_message,
            overall_status=(
                True
                if log.status == "SUCCESS"
                else False
                if log.status is not None
                else None
            ),
            internal_request_headers=redact(log.source_request_headers),
            internal_request_body=redact(log.source_request_payload),
            internal_api_client_response=redact(log.source_response),
            internal_api_client_status=log.client_status_code,
            external_request_url=_resolve_external_url(endpoint),
            external_request_method=endpoint.method if endpoint else "POST",
            external_request_headers=redact(log.target_request_headers),
            external_request_body=redact(log.target_request_payload),
            external_query_params=redact(log.target_query_params),
            external_response=redact(log.target_response),
            external_response_time_ms=log.response_time_ms,
            total_time_ms=log.response_time_ms,
            external_status_code=log.upstream_status_code,
            full_log=None,
            timeout_configured=None,
            tenant_id=None,
            created_at=log.created_at,
        ),
        log.created_at,
    )

    detail.external_response = _external_response_or_placeholder(
        detail.external_response
    )

    return detail


def _enrich(record: CallLogResponse, created_at: datetime | None) -> CallLogResponse:
    """Fill a record's empty fields from its MongoDB audit document."""
    try:
        supplements = audit_enrichment.enrich_rows(
            [(record.id, created_at)], CallLogResponse.model_fields
        )
        supplement = supplements.get(record.id)
        if not supplement:
            return record

        for field, value in audit_enrichment.apply(
            record.model_dump(), supplement
        ).items():
            if field in type(record).model_fields:
                setattr(record, field, value)
    except Exception:
        logger.warning("Call log enrichment failed for %s", record.id, exc_info=True)

    return record
