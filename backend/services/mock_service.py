from __future__ import annotations

from typing import Any

from backend.models import CallStatusEnum

__all__ = ["build_mock_result"]


def build_mock_result(
    endpoint: Any,
    *,
    request_id: str,
    method: str,
    url: str,
    headers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a gateway-compatible result dict sourced from the mock response."""
    return {
        "request_id": request_id,
        "endpoint_id": endpoint.id,
        "tenant_id": getattr(endpoint, "tenant_id", None),
        "method": method,
        "path": url,
        "request_headers": dict(headers or {}),
        "success": True,
        "data": getattr(endpoint, "mock_response", None),
        "status_code": 200,
        "response_time_ms": 0,
        "response_headers": {"Content-Type": "application/json"},
        "error": None,
        "failure_kind": None,
        "upstream_attempted": False,
        "source": "mock",
        "external_request_url": None,
        "external_request_method": None,
        "external_request_headers": None,
        "external_request_body": None,
        "external_query_params": None,
        "external_response_headers": None,
        "external_status_code": None,
        "external_response_time_ms": None,
        "total_time_ms": 0,
        "status": CallStatusEnum.SUCCESS.value,
        "timeout_configured": None,
    }
