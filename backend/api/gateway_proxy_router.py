"""Legacy dynamic gateway route: ``/{path:path}``.

The old mapper engine exposed a catch-all ``api_route`` that received the
business requests the CRM forwards through ``gatewayhelper`` (e.g.
``GET /getCallByDate2.php?date=...&user=...``), resolved them against
``api_endpoint`` and proxied them upstream. This router reproduces that
contract on top of this app's own :class:`GatewayEngine`, so the exact same
requests are mapped, executed, audited and stored as call logs here.

Registration order matters: ``main.create_app`` includes this router
**last**, so every concrete route (``/``, ``/health``, ``/api/*``) wins the
match and only otherwise-unhandled paths fall through to the gateway.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_db
from backend.core.clock import local_now
from backend.core.config import settings
from backend.services.gateway_engine import GatewayEngine
from backend.services.http_client import get_http_client
from backend.services.log_writer import write_call_log

logger = logging.getLogger(__name__)

__all__ = ["router"]

router = APIRouter(tags=["Gateway"])

_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH")

# Hop-by-hop headers must not be forwarded; a stale Content-Length would
# otherwise contradict the body the engine serialises.
_DROP_HEADERS = frozenset(
    {
        "host",
        "content-length",
        "connection",
        "keep-alive",
        "transfer-encoding",
        "upgrade",
        "expect",
        "te",
        "trailer",
        "proxy-connection",
        "proxy-authorization",
    }
)


async def _request_payload(request: Request) -> dict[str, Any]:
    """Merge URL query params with the JSON body (body wins on conflict)."""
    query = dict(request.query_params)

    if request.method == "GET":
        return query

    try:
        payload = await request.json()
    except Exception:
        return query

    body = payload if isinstance(payload, dict) else {}
    return {**query, **body}


@router.api_route("/{path:path}", methods=list(_METHODS))
async def gateway_proxy(
    request: Request,
    path: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    http_client: Any = Depends(get_http_client),
) -> Response:
    """Resolve, proxy and log one dynamically routed business request."""
    target_url = f"/{path}"
    root = settings.APP_ROOT_PATH
    if root and target_url.startswith(f"{root}/"):
        target_url = target_url[len(root) :]

    method = request.method.upper()
    request_data = await _request_payload(request)
    headers = {
        name: value
        for name, value in request.headers.items()
        if name.lower() not in _DROP_HEADERS
    }

    engine = GatewayEngine(db, http_client, timeout=settings.API_TIMEOUT_SECONDS)
    result = await engine.process_request(None, request_data, headers, target_url, method)

    # SFTP "play" returns raw audio; the base64 envelope is only a transport
    # detail and must never be written to the audit log verbatim.
    data = result.get("data")
    audio: bytes | None = None
    if (
        isinstance(data, dict)
        and data.get("operation") == "play"
        and data.get("content_base64")
    ):
        try:
            audio = base64.b64decode(data["content_base64"])
        except Exception:
            audio = None

    # Only matched endpoints produce an audit row — unresolved probes stay out
    # of api_call_log, exactly like the legacy engine's "log only if endpoint".
    if result.get("endpoint_id") is not None:
        log_data = dict(result)
        if audio is not None and isinstance(data, dict):
            log_data["data"] = {
                key: value
                for key, value in data.items()
                if key != "content_base64"
            }
        log_data["internal_request_body"] = request_data
        log_data["created_at"] = local_now()
        background_tasks.add_task(write_call_log, db, log_data)

    status_code = result.get("status_code")
    if status_code is None:
        status_code = 200 if result.get("success") else 500

    logger.info(
        "gateway proxy %s %s -> HTTP %s (endpoint=%s)",
        method,
        target_url,
        status_code,
        result.get("endpoint_id"),
    )

    if audio is not None:
        media_type = str(data.get("content_type") or "application/octet-stream")
        filename = (
            str(data.get("filename") or "audio")
            .replace('"', "_")
            .replace("\r", "")
            .replace("\n", "")
        )
        headers = {"Content-Disposition": f'inline; filename="{filename}"'}
        if data.get("truncated"):
            headers["X-Audio-Truncated"] = "true"
        return Response(content=audio, media_type=media_type, headers=headers)

    if status_code == 204:
        return Response(status_code=204)

    _INTERNAL_KEYS = frozenset(
        {
            "status_code",
            "request_id",
            "endpoint_id",
            "tenant_id",
            "method",
            "path",
            "request_headers",
            "external_request_headers",
            "internal_request_body",
            "response_time_ms",
            "total_time_ms",
            "response_headers",
            "error",
            "external_request_url",
            "external_request_method",
            "external_request_body",
            "external_query_params",
            "external_response_headers",
            "external_status_code",
            "external_response_time_ms",
            "status",
            "timeout_configured",
        }
    )
    filtered = {key: value for key, value in result.items() if key not in _INTERNAL_KEYS}
    content = {"success": filtered.get("success")}
    content["message"] = filtered.pop("message", "Success" if filtered.get("success") else "Error")
    content["resCode"] = filtered.pop("resCode", status_code)
    content.update({k: v for k, v in filtered.items() if k != "success"})
    return JSONResponse(status_code=status_code, content=content)
