from typing import Any

from pydantic import BaseModel

from backend.schemas.common import LocalDateTimeOptional


class MapAndCallRequest(BaseModel):
    targetUrl: str
    targetMethod: str
    requestData: dict[str, Any]
    headers: dict[str, Any] | None = None
    endpointId: int | str


class MapAndCallResponse(BaseModel):
    success: bool
    data: Any | None = None
    status_code: int | None = None
    response_time_ms: int | None = None
    called_at: LocalDateTimeOptional = None
    request_headers: dict[str, Any] | None = None
    response_headers: dict[str, Any] | None = None
    external_request_headers: dict[str, Any] | None = None
    external_response_headers: dict[str, Any] | None = None
    error: str | None = None

    request_id: str | None = None
    external_request_url: str | None = None
    external_request_method: str | None = None
    external_request_body: dict[str, Any] | None = None
    external_query_params: dict[str, Any] | None = None
    external_status_code: int | None = None
    external_response_time_ms: int | None = None
    total_time_ms: int | None = None
