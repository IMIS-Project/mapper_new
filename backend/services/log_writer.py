"""Background persistence for gateway calls."""

import logging
import re
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.clock import local_now
from backend.db.schema_probe import probe as schema_probe
from backend.models import ApiCallLog, CallStatusEnum

logger = logging.getLogger(__name__)

__all__ = ["write_call_log", "redact", "MASK"]


MASK = "********"


_SENSITIVE_KEYS = frozenset(
    {
        "user",
        "username",
        "pass",
        "password",
        "pwd",
        "authorization",
        "auth",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "x-api-key",
        "x-api-token",
        "x-auth-token",
        "secret",
        "client_secret",
        "cookie",
        "set-cookie",
        "session",
    }
)


_BEARER = re.compile(r"^\s*(bearer|basic|token)\s+\S", re.IGNORECASE)
_JWT = re.compile(r"^\s*ey[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def _is_sensitive(key: str) -> bool:
    normalised = str(key).strip().lower().replace(" ", "_")
    if normalised in _SENSITIVE_KEYS:
        return True

    return any(
        part in normalised for part in ("password", "secret", "api_key", "apikey")
    )


def _scrub_value(value: str) -> str:
    """Mask a value that is credential-shaped even if the key was unusual."""
    if _BEARER.match(value) or _JWT.match(value):
        return MASK
    return value


def redact(payload: Any) -> Any:
    """Return a copy of ``payload`` with every credential value masked."""
    if isinstance(payload, dict):
        masked: dict[Any, Any] = {}
        for key, value in payload.items():
            if _is_sensitive(key):
                masked[key] = MASK
            else:
                masked[key] = redact(value)
        return masked

    if isinstance(payload, list):
        return [redact(item) for item in payload]

    if isinstance(payload, tuple):
        return tuple(redact(item) for item in payload)

    if isinstance(payload, str):
        return _scrub_value(payload)

    return payload


def _headers(source: Any) -> dict[str, Any] | None:
    """Normalise a captured header mapping to a plain, redacted dict."""
    if not isinstance(source, dict) or not source:
        return None
    return {str(key): str(value) for key, value in redact(dict(source)).items()}


def _query_params(source: Any) -> dict[str, Any] | None:
    """Normalise a captured query mapping to a plain, redacted dict."""
    if not isinstance(source, dict) or not source:
        return None

    flattened: dict[str, Any] = {}
    for key, value in redact(dict(source)).items():
        if isinstance(value, (list, tuple)):
            flattened[str(key)] = ", ".join(str(item) for item in value)
        else:
            flattened[str(key)] = str(value)

    return flattened


def _client_response(log_data: dict[str, Any]) -> dict[str, Any]:
    """Build the gateway's own response envelope for the client."""
    data = log_data.get("data")
    status_code = log_data.get("status_code")

    if log_data.get("success"):
        message = (
            data.get("message", "Success") if isinstance(data, dict) else "Success"
        )

        payload = data.get("data", data) if isinstance(data, dict) else data
        return {
            "success": True,
            "message": message,
            "resCode": status_code,
            "data": {} if payload is None else payload,
            "status_code": status_code,
        }

    return {
        "success": False,
        "error": log_data.get("error"),
        "message": log_data.get("error"),
        "resCode": status_code,
        "data": None,
        "status_code": status_code,
    }


def _inserted_id(result: Any) -> int | None:
    """Primary key of the row just written, for stamping the MongoDB mirror."""
    try:
        return result.inserted_primary_key[0]
    except Exception:
        logger.debug("Insert did not report a primary key", exc_info=True)
        return None


async def write_call_log(
    db: AsyncSession,
    log_data: dict[str, Any],
) -> int | None:
    """Persist one api_call_log row from a gateway result dict.

    Returns the inserted primary key, or ``None`` when the row could not be
    written (failures are logged, never raised).
    """

    try:
        succeeded = bool(log_data.get("success"))

        status = (
            CallStatusEnum.SUCCESS.value if succeeded else CallStatusEnum.FAILED.value
        )

        # A two-leg producer (a scheduled mapping run) can supply both sides
        # explicitly; the gateway keeps the derived envelope.
        source_response = log_data.get("source_response")
        if source_response is None:
            source_response = _client_response(log_data)
        else:
            source_response = redact(source_response)

        target_response = log_data.get("target_response")
        if target_response is None:
            target_response = redact(log_data.get("data") or {})
        else:
            target_response = redact(target_response)

        values = schema_probe.writable(
            {
                # Record the call's wall-clock time explicitly.  Relying on the
                # database default made the audit rows depend on the MySQL
                # server's timezone and could drift from scheduler history.
                "created_at": (
                    log_data.get("created_at")
                    or log_data.get("called_at")
                    or local_now()
                ),
                "endpoint_id": log_data.get("endpoint_id"),
                "source_request_headers": _headers(
                    log_data.get("request_headers")
                    or log_data.get("internal_request_headers")
                ),
                "source_response_headers": _headers(
                    log_data.get("response_headers")
                    or log_data.get("internal_response_headers")
                ),
                "target_request_headers": _headers(
                    log_data.get("external_request_headers")
                ),
                "target_response_headers": _headers(
                    log_data.get("external_response_headers")
                ),
                "target_query_params": _query_params(
                    log_data.get("external_query_params")
                ),
                "client_status_code": log_data.get("status_code"),
                "upstream_status_code": log_data.get("external_status_code"),
                "source_request_payload": redact(
                    log_data.get("internal_request_body")
                    or log_data.get("request_body")
                    or {}
                ),
                "source_response": source_response,
                "target_request_payload": redact(
                    log_data.get("external_request_body") or {}
                ),
                "target_response": target_response,
                "status": status,
                "response_time_ms": (
                    log_data.get("external_response_time_ms")
                    or log_data.get("total_time_ms")
                    or 0
                ),
                "error_message": log_data.get("error"),
            }
        )

        result = await db.execute(insert(ApiCallLog.__table__).values(**values))
        await db.commit()

        logger.info(
            "api_call_log row written: endpoint=%s status=%s HTTP=%s (%sms)",
            values.get("endpoint_id"),
            status,
            log_data.get("external_status_code"),
            values.get("response_time_ms"),
        )

        from backend.services import audit_enrichment

        inserted_id = _inserted_id(result)

        await audit_enrichment.mirror_call(inserted_id, log_data)

        return inserted_id

    except Exception:
        logger.exception("Failed to persist the gateway call log")

        try:
            await db.rollback()
        except Exception:
            logger.exception("Rollback after a failed log write also failed")
