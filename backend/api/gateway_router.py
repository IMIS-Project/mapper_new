import logging
from uuid import uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_active_user, get_db
from backend.core.clock import local_now
from backend.core.config import settings
from backend.models import CallStatusEnum
from backend.services.central_auth import CentralUser

User = CentralUser
from backend.schemas.gateway import MapAndCallRequest, MapAndCallResponse
from backend.services.circuit_breaker import circuit_breaker
from backend.services.dedup import dedup_cache
from backend.services.gateway_engine import GatewayEngine
from backend.services.http_client import get_http_client
from backend.services.log_writer import write_call_log
from backend.services.rate_limiter import rate_limiter


logger = logging.getLogger(__name__)

__all__ = ["router"]

router = APIRouter(tags=["Gateway"])

_TRIPABLE = frozenset(
    {
        "upstream_http",
        "upstream_timeout",
        "transport",
        "local_pool_timeout",
    }
)


def _rejected(
    headers,
    url,
    method,
    endpoint_id,
    status_code: int,
    error: str,
) -> dict:

    return {
        "request_id": str(uuid4()),
        "endpoint_id": endpoint_id,
        "tenant_id": None,
        "method": method,
        "path": url,
        "request_headers": dict(headers or {}),
        "success": False,
        "data": None,
        "status_code": status_code,
        "response_time_ms": None,
        "total_time_ms": None,
        "response_headers": None,
        "error": error,
        "external_request_url": None,
        "external_request_method": None,
        "external_request_headers": None,
        "external_request_body": None,
        "external_query_params": None,
        "external_response_headers": None,
        "external_status_code": None,
        "external_response_time_ms": None,
        "status": CallStatusEnum.FAILED.value,
        "timeout_configured": settings.API_TIMEOUT_SECONDS,
    }


def _tripable(result: dict) -> bool:
    return result.get("failure_kind") in _TRIPABLE


@router.post(
    "/map-and-call",
    response_model=MapAndCallResponse,
)
async def map_and_call(
    payload: MapAndCallRequest,
    background_tasks: BackgroundTasks,
    http_client: httpx.AsyncClient = Depends(get_http_client),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_active_user),
) -> MapAndCallResponse:

    called_at = local_now()
    engine = GatewayEngine(
        db,
        http_client,
        timeout=settings.API_TIMEOUT_SECONDS,
    )

    method = str(payload.targetMethod or "").strip().upper()
    url = str(payload.targetUrl or "").strip()
    request_headers = payload.headers or {}

    endpoint = await engine.resolve_endpoint(
        payload.endpointId,
        url,
        method,
    )

    if endpoint is None:
        result = await engine.process_request(
            payload.endpointId,
            payload.requestData,
            request_headers,
            url,
            method,
        )

    else:
        cached = await dedup_cache.get(
            payload.endpointId,
            payload.requestData,
        )

        if cached is not None:
            result = dict(cached)

        else:
            rate_limit_rpm = settings.RATE_LIMIT_DEFAULT_RPM

            decision = await rate_limiter.check(
                endpoint.id,
                rate_limit_rpm,
            )

            if not decision.allowed:
                result = _rejected(
                    request_headers,
                    url,
                    method,
                    payload.endpointId,
                    429,
                    (
                        f"Rate limit exceeded "
                        f"({rate_limit_rpm} req/min on this endpoint). "
                        f"Retry after {decision.retry_after}s."
                    ),
                )

            elif not await circuit_breaker.allow(endpoint.id):
                result = _rejected(
                    request_headers,
                    url,
                    method,
                    payload.endpointId,
                    503,
                    "Downstream is temporarily unavailable (circuit open).",
                )

            else:
                outcome = await engine.execute_resolved(
                    endpoint,
                    payload.requestData,
                    request_headers,
                    url,
                    method,
                )

                result = outcome.to_result()

                if result.get("success"):
                    await circuit_breaker.record_success(endpoint.id)

                    await dedup_cache.set(
                        payload.endpointId,
                        payload.requestData,
                        result,
                    )

                elif _tripable(result):
                    await circuit_breaker.record_failure(endpoint.id)

    result["called_at"] = called_at
    log_data = dict(result)
    log_data["internal_request_body"] = payload.requestData

    background_tasks.add_task(
        write_call_log,
        db,
        log_data,
    )

    logger.info(
        "map-and-call %s %s -> HTTP %s in %sms",
        result.get("method"),
        result.get("path"),
        result.get("status_code"),
        result.get("total_time_ms"),
    )

    return MapAndCallResponse.model_validate(result)
