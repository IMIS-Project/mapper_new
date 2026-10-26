"""Cron execution driven by an already-registered API mapping.

A mapping-backed cron job is stored in the scheduler database exactly like a
manual one: the ``url`` column holds the mapping's **internal** API URL and the
``method`` column the mapping's method. Nothing about the mapping is copied into
the scheduler database, so every tick re-reads ``api_endpoint`` and
``api_endpoint_parameter_mapping`` and always reflects the current mapping.

Both tables are read with SELECT statements only. Resolution and the external
call run through :class:`GatewayEngine`, which additionally refuses to operate
on a session that carries pending writes, so the read-only guarantee holds even
if the flow is extended later.

URL direction follows the gateway runtime — the same convention the endpoints
page shows with its outbound/inbound icons:

* ``source_api_url`` — the **external** API, the upstream that is actually
  dialled. It is always called first, on every tick.
* ``target_api_url`` — the **internal** API, the route that receives the
  external payload.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.redaction import mask_sensitive
from backend.db.session import AsyncSessionLocal
from backend.models import ApiEndpoint, ParameterMapping
from backend.services.gateway_engine import EndpointSnapshot, GatewayEngine
from backend.services.upstream_auth import (
    apply_upstream_auth,
    drop_token_header,
    invalidate_token,
    strip_auth_headers,
)

logger = logging.getLogger(__name__)

__all__ = [
    "MAPPING_RUN_KIND",
    "MappingInactiveError",
    "MappingJobOutcome",
    "MappingLeg",
    "MappingRoute",
    "MappingStatus",
    "check_mapping_active",
    "execute_mapping_job",
    "is_absolute_http_url",
    "list_routes",
    "resolve_endpoint",
    "resolve_internal_url",
]

#: Marks a stored run body as the two-leg envelope written by this module, so
#: the UI can tell a mapping run apart from a plain single-URL run.
MAPPING_RUN_KIND = "api-mapping-cron-run"

# Hop-by-hop headers must not be forwarded; a stale Content-Length would
# contradict the body the delivery serialises.
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


class MappingInactiveError(Exception):
    """The API mapping associated with this cron job is inactive in Endpoints."""

    def __init__(self, endpoint_code: str | None = None, endpoint_id: int | None = None):
        name = endpoint_code or (f"#{endpoint_id}" if endpoint_id else "associated with this job")
        super().__init__(f"API mapping '{name}' is currently inactive in Endpoints. Execution skipped.")
        self.endpoint_code = endpoint_code
        self.endpoint_id = endpoint_id


@dataclass(frozen=True, slots=True)
class MappingStatus:
    is_mapping: bool
    is_active: bool
    endpoint_id: int | None = None
    endpoint_code: str | None = None


@dataclass(frozen=True, slots=True)
class MappingRoute:
    """One active or registered mapping, as offered to the cron job form or list."""

    endpoint_id: int
    endpoint_code: str | None
    internal_url: str
    external_url: str
    method: str
    parameter_count: int
    is_active: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "endpoint_id": self.endpoint_id,
            "endpoint_code": self.endpoint_code,
            "internal_url": self.internal_url,
            "external_url": self.external_url,
            "method": self.method,
            "parameter_count": self.parameter_count,
            "is_active": self.is_active,
        }


@dataclass(frozen=True, slots=True)
class MappingLeg:
    """Outcome of one leg of a mapping-backed run."""

    url: str
    method: str
    status_code: int | None = None
    duration_ms: int = 0
    request_headers: dict[str, str] = field(default_factory=dict)
    response_headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return (
            self.error is None
            and self.status_code is not None
            and 200 <= self.status_code < 300
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "method": self.method,
            "status_code": self.status_code,
            "duration_ms": self.duration_ms,
            # Never persist the bearer this leg actually sent (the service
            # account token or a static API token).
            "request_headers": mask_sensitive(self.request_headers),
            "response_headers": self.response_headers,
            "body": self.body,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class MappingJobOutcome:
    """Terminal result of one mapping-backed tick."""

    endpoint_id: int
    endpoint_code: str | None
    external: MappingLeg
    internal: MappingLeg | None
    payload: dict[str, Any]
    status_code: int | None
    success: bool
    error: str | None
    request_headers: dict[str, str]
    response_headers: dict[str, str]
    #: The transformed payload actually sent to the external API, kept for the
    #: ``api_call_log`` mirror. Not part of the two-leg response envelope.
    external_request_body: Any = None
    external_query_params: Any = None


def _stringify(headers: Any) -> dict[str, str]:
    return {str(name): str(value) for name, value in (headers or {}).items()}


def _request_payload(body: str | None, url: str | None = None) -> dict[str, Any]:
    """Cron body -> the internal field values sent on to the external API.

    Keys are the mapping's *internal* field names, which is what
    :meth:`GatewayEngine._transform_parameters` reads; it renames them to the
    external field names on the way out. A query string on the job URL is
    folded in too, so ``GET /v1/audio/play?file=x.mp3`` reaches an SFTP-backed
    endpoint with its ``file`` parameter intact.
    """
    payload: dict[str, Any] = {}
    if url:
        payload.update(
            dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
        )
    if body and body.strip():
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            payload.update(parsed)
    return payload


async def _fetch_routes(db: AsyncSession, only_active: bool = True) -> list[MappingRoute]:
    query = select(
        ApiEndpoint.id,
        ApiEndpoint.endpoint_code,
        ApiEndpoint.source_api_url,
        ApiEndpoint.target_api_url,
        ApiEndpoint.method,
        ApiEndpoint.is_active,
    )
    if only_active:
        query = query.where(ApiEndpoint.is_active == True)
    rows = await db.execute(query)
    counts = await db.execute(
        select(ParameterMapping.api_endpoint_id, func.count(ParameterMapping.id))
        .where(ParameterMapping.is_active == True)
        .group_by(ParameterMapping.api_endpoint_id)
    )
    count_by_endpoint = {int(key): int(value) for key, value in counts.all()}
    return [
        MappingRoute(
            endpoint_id=int(row.id),
            endpoint_code=row.endpoint_code,
            internal_url=(row.target_api_url or "").strip(),
            external_url=(row.source_api_url or "").strip(),
            method=(row.method or "POST").strip().upper(),
            parameter_count=count_by_endpoint.get(int(row.id), 0),
            is_active=bool(row.is_active),
        )
        for row in rows.all()
    ]


async def list_routes(
    db: AsyncSession | None = None, only_active: bool = True
) -> list[MappingRoute]:
    """Mappings the cron form or list can bind to (SELECT only)."""
    if db is not None:
        return await _fetch_routes(db, only_active=only_active)
    async with AsyncSessionLocal() as own_db:
        return await _fetch_routes(own_db, only_active=only_active)


async def check_mapping_active(
    url: str,
    method: str,
    db: AsyncSession | None = None,
) -> MappingStatus:
    clean_url = str(url or "").strip()
    clean_method = str(method or "").strip().upper()
    if not clean_url:
        return MappingStatus(is_mapping=False, is_active=False)

    own_db = db is None
    session = db or AsyncSessionLocal()
    try:
        query = select(
            ApiEndpoint.id,
            ApiEndpoint.endpoint_code,
            ApiEndpoint.target_api_url,
            ApiEndpoint.source_api_url,
            ApiEndpoint.method,
            ApiEndpoint.is_active,
        )
        if clean_method:
            query = query.where(
                (ApiEndpoint.method.is_(None)) | (func.upper(ApiEndpoint.method) == clean_method)
            )
        query = query.order_by(ApiEndpoint.is_active.desc(), ApiEndpoint.id.desc())
        result = await session.execute(query)
        rows = result.all()

        route = clean_url.split("?", 1)[0].rstrip("/")
        path = urlsplit(clean_url).path.rstrip("/")
        if path and not path.startswith("/"):
            path = f"/{path}"

        matched_row = None
        for r in rows:
            target = str(r.target_api_url or "").strip().rstrip("/")
            target_route = target.split("?", 1)[0].rstrip("/")
            target_path = urlsplit(target).path.rstrip("/")
            if target_path and not target_path.startswith("/"):
                target_path = f"/{target_path}"

            source = str(r.source_api_url or "").strip().rstrip("/")
            source_route = source.split("?", 1)[0].rstrip("/")
            source_path = urlsplit(source).path.rstrip("/")
            if source_path and not source_path.startswith("/"):
                source_path = f"/{source_path}"

            is_target_match = (
                (clean_url.lower() == target.lower())
                or (route and target_route and route.lower() == target_route.lower())
                or (
                    bool(path)
                    and bool(target_path)
                    and (
                        path.lower() == target_path.lower()
                        or target_route.lower().endswith(path.lower())
                        or route.lower().endswith(target_path.lower())
                    )
                )
            )
            is_source_match = (
                (clean_url.lower() == source.lower())
                or (route and source_route and route.lower() == source_route.lower())
                or (
                    bool(path)
                    and bool(source_path)
                    and (
                        path.lower() == source_path.lower()
                        or source_route.lower().endswith(path.lower())
                        or route.lower().endswith(source_path.lower())
                    )
                )
            )

            if is_target_match or is_source_match:
                matched_row = r
                if bool(r.is_active):
                    break

        if matched_row is None:
            return MappingStatus(is_mapping=False, is_active=False)

        return MappingStatus(
            is_mapping=True,
            is_active=bool(matched_row.is_active),
            endpoint_id=int(matched_row.id),
            endpoint_code=matched_row.endpoint_code,
        )
    finally:
        if own_db:
            await session.close()


async def resolve_endpoint(
    internal_url: str,
    method: str,
    *,
    http_client: httpx.AsyncClient | None = None,
    db: AsyncSession | None = None,
) -> EndpointSnapshot | None:
    """Resolve ``internal_url``/``method`` to an active mapping, or ``None``.

    The lookup is delegated to the gateway so a cron job always binds to the
    very same mapping an inbound request would. ``http_client`` is unused by
    resolution and may be left out by callers that only need the config check.
    """
    if db is not None:
        engine = GatewayEngine(db, http_client, timeout=_timeout())
        return await engine.resolve_endpoint(None, internal_url, method)

    async with AsyncSessionLocal() as own_db:
        engine = GatewayEngine(own_db, http_client, timeout=_timeout())
        return await engine.resolve_endpoint(None, internal_url, method)


def _timeout() -> int:
    return max(1, int(float(settings.SCHEDULER_REQUEST_TIMEOUT_SECONDS)))


async def _deliver_to_internal(
    *,
    url: str,
    method: str,
    payload: Any,
    headers: dict[str, str],
    http_client: httpx.AsyncClient,
) -> MappingLeg:
    """POST the external payload, verbatim, to the internal API."""
    started = time.perf_counter()
    send_headers = {
        name: value
        for name, value in (headers or {}).items()
        if name.lower() not in _DROP_HEADERS
    }
    content: bytes | None = None
    if payload is not None:
        encoded = json.dumps(payload, ensure_ascii=False, default=str)
        limit = int(settings.SCHEDULER_MAX_RESPONSE_BODY_BYTES)
        if len(encoded.encode("utf-8")) > limit:
            return MappingLeg(
                url=url,
                method=method,
                duration_ms=_elapsed_ms(started),
                request_headers=mask_sensitive(send_headers),
                error=(
                    "The external payload exceeds the scheduler forwarding limit "
                    f"of {limit} bytes"
                ),
            )
        content = encoded.encode("utf-8")
        send_headers.setdefault("Content-Type", "application/json")

    # The internal (target) API is part of the same IMIS estate and usually
    # rejects anonymous calls with 401. Authenticate the delivery the same way
    # the gateway authenticates its upstream calls: a static token when the
    # host has one configured, otherwise a service-account bearer from the
    # central auth login. A header already supplied by the cron job wins.
    injected = await apply_upstream_auth(send_headers, http_client, url)
    leg = await _attempt_internal(
        url=url,
        method=method,
        content=content,
        headers=send_headers,
        http_client=http_client,
        started=started,
    )

    # A 401 means the target rejected the bearer we just sent. Auth services
    # can issue a token whose advertised lifetime is longer than the target
    # accepts, so drop the cached token and retry once with a fresh login
    # rather than waiting for the next schedule tick to fail the same way.
    if leg.status_code == 401 and injected:
        invalidate_token(url)
        drop_token_header(send_headers)
        await apply_upstream_auth(send_headers, http_client, url)
        leg = await _attempt_internal(
            url=url,
            method=method,
            content=content,
            headers=send_headers,
            http_client=http_client,
            started=started,
        )

    return leg


async def _attempt_internal(
    *,
    url: str,
    method: str,
    content: bytes | None,
    headers: dict[str, str],
    http_client: httpx.AsyncClient,
    started: float,
) -> MappingLeg:
    try:
        async with http_client.stream(
            method,
            url,
            content=content,
            headers=headers or None,
            follow_redirects=False,
            timeout=float(settings.SCHEDULER_REQUEST_TIMEOUT_SECONDS),
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
            body_text = buffer.decode("utf-8", errors="replace") if buffer else None
    except httpx.TimeoutException:
        return MappingLeg(
            url=url,
            method=method,
            duration_ms=_elapsed_ms(started),
            request_headers=mask_sensitive(headers),
            error="Internal delivery timed out",
        )
    except httpx.RequestError as exc:
        return MappingLeg(
            url=url,
            method=method,
            duration_ms=_elapsed_ms(started),
            request_headers=mask_sensitive(headers),
            error=f"Internal delivery failed: {exc}",
        )

    if 300 <= status_code < 400:
        error: str | None = "Redirect responses are not followed"
    elif status_code >= 400:
        error = f"HTTP {status_code}"
    else:
        error = None

    body: Any = body_text
    if truncated and body_text:
        body = f"{body_text}\n[truncated at {limit} bytes]"

    return MappingLeg(
        url=url,
        method=method,
        status_code=status_code,
        duration_ms=_elapsed_ms(started),
        request_headers=mask_sensitive(headers),
        response_headers=response_headers,
        body=body,
        error=error,
    )


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def is_absolute_http_url(url: str) -> bool:
    """True when ``url`` already carries an explicit ``http(s)`` scheme."""
    return str(url or "").strip().lower().startswith(("http://", "https://"))


def resolve_internal_url(url: str) -> str:
    """Expand a scheme-less internal URL against ``settings.MAPPER_BASE_URL``.

    A mapping may register its internal API as a bare path (for example
    ``/ref_crp_beneficiary``) so the route is not repeated on every endpoint.
    Absolute URLs are returned untouched; anything else is joined onto the
    mapper's configured base URL. When no base is configured the value is
    returned unchanged and the caller reports the configuration error.
    """
    text = str(url or "").strip()
    if not text or "://" in text:
        return text

    base = str(settings.MAPPER_BASE_URL or "").strip().rstrip("/")
    if not base:
        return text

    path = text if text.startswith("/") else f"/{text}"
    return f"{base}{path}"


async def execute_mapping_job(
    *,
    internal_url: str,
    method: str,
    headers: dict[str, str] | None,
    body: str | None,
    http_client: httpx.AsyncClient,
    db: AsyncSession | None = None,
) -> MappingJobOutcome | None:
    """Run one mapping-backed tick: external first, then the internal API.

    Returns ``None`` when ``internal_url``/``method`` match no active mapping,
    which tells the caller to fall back to the plain single-URL behaviour.
    """
    own_db = db is None
    session = db or AsyncSessionLocal()
    try:
        mapping_status = await check_mapping_active(internal_url, method, db=session)
        if mapping_status.is_mapping and not mapping_status.is_active:
            raise MappingInactiveError(
                endpoint_code=mapping_status.endpoint_code,
                endpoint_id=mapping_status.endpoint_id,
            )
        engine = GatewayEngine(session, http_client, timeout=_timeout())
        try:
            endpoint = await engine.resolve_endpoint(None, internal_url, method)
        except Exception:
            # A manual job must not break because the mappings database is
            # unreachable; fall back to the plain single-URL behaviour.
            logger.warning(
                "Could not resolve mapping %s %s", method, internal_url, exc_info=True
            )
            return None
        if endpoint is None:
            return None

        mappings = await engine.load_mappings(endpoint)
        # The cron job's own credentials belong to its internal target. Do not
        # forward them to the mapping's external API: that leg only receives a
        # token when the endpoint says it requires authentication.
        external_headers = dict(headers or {})
        strip_auth_headers(external_headers)
        outcome = await engine.execute_resolved(
            endpoint,
            _request_payload(body, internal_url),
            external_headers,
            internal_url,
            method,
            mappings=mappings,
        )
    finally:
        if own_db:
            await session.close()

    result = outcome.to_result()
    external_ok = bool(result.get("success"))
    external_body = result.get("data")
    if isinstance(external_body, dict) and "content_base64" in external_body:
        # A played recording is delivered to the caller, never stored in the
        # run history; keep the metadata so the run detail stays readable.
        external_body = {
            key: value
            for key, value in external_body.items()
            if key != "content_base64"
        }
        external_body["audio_omitted"] = True
    external = MappingLeg(
        url=str(result.get("external_request_url") or endpoint.source_api_url or ""),
        method=str(
            result.get("external_request_method") or endpoint.method or "POST"
        ).upper(),
        status_code=result.get("external_status_code"),
        duration_ms=int(result.get("external_response_time_ms") or 0),
        # Redacted: the gateway may have injected an upstream bearer token
        # into the request it actually sent, and that must not be stored.
        request_headers=mask_sensitive(
            _stringify(result.get("external_request_headers"))
        ),
        response_headers=_stringify(result.get("external_response_headers")),
        body=external_body,
        error=result.get("error"),
    )

    target_url = str(endpoint.target_api_url or "").strip()
    delivery_url = resolve_internal_url(target_url)
    internal: MappingLeg | None = None
    self_contained = bool(endpoint.is_sftp)
    if not external_ok:
        error = f"External API call failed: {external.error or 'unknown error'}"
        status_code = external.status_code
    elif self_contained:
        # SFTP endpoints are the API: the remote read is the response, so
        # there is no second (internal) HTTP leg to call.
        status_code = external.status_code
        error = None
    elif not is_absolute_http_url(delivery_url):
        error = (
            "The internal API URL of this mapping is not an absolute HTTP(S) "
            "URL; set MAPPER_BASE_URL so a relative path can be expanded"
        )
        status_code = external.status_code
    else:
        internal = await _deliver_to_internal(
            url=delivery_url,
            method=method,
            payload=external.body,
            # The cron job's own headers, never the external request's: that
            # one carries the upstream bearer token the gateway obtained.
            headers=headers or {},
            http_client=http_client,
        )
        status_code = internal.status_code
        error = None if internal.ok else internal.error or "Internal delivery failed"

    envelope = {
        "kind": MAPPING_RUN_KIND,
        "mapping": {
            "endpoint_id": endpoint.id,
            "endpoint_code": endpoint.endpoint_code,
            "internal_url": target_url,
            "external_url": external.url,
        },
        "self_contained": self_contained,
        "external": external.as_dict(),
        "internal": internal.as_dict() if internal is not None else None,
    }

    return MappingJobOutcome(
        endpoint_id=endpoint.id,
        endpoint_code=endpoint.endpoint_code,
        external=external,
        internal=internal,
        payload=envelope,
        status_code=status_code,
        success=external_ok
        and (self_contained or (internal is not None and internal.ok)),
        error=error,
        request_headers=dict(
            internal.request_headers if internal else external.request_headers
        ),
        response_headers=dict(
            internal.response_headers if internal else external.response_headers
        ),
        external_request_body=result.get("external_request_body"),
        external_query_params=result.get("external_query_params"),
    )
