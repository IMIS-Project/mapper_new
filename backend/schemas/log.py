from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.schemas.common import LocalDateTimeOptional, PaginatedResponse


def _coerce_status(value: Any) -> str | None:

    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


class CallLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, validate_assignment=True)

    id: int
    endpoint_id: int | None = None

    source_request_payload: dict[str, Any] | None = None
    source_response: dict[str, Any] | None = None
    target_request_payload: dict[str, Any] | None = None
    target_response: dict[str, Any] | None = None

    status: str | None = None
    response_time_ms: int | None = None
    error_message: str | None = None
    created_at: LocalDateTimeOptional = None

    request_id: str | None = None
    method: str | None = None

    path: str | None = None

    overall_status: bool | None = None
    tenant_id: str | None = None

    external_status_code: int | None = None
    total_time_ms: int | None = None

    internal_request_headers: dict[str, Any] | None = None
    internal_request_body: dict[str, Any] | None = None
    internal_api_client_response: dict[str, Any] | None = None

    internal_api_client_status: str | None = None

    external_request_url: str | None = None
    external_request_method: str | None = None
    external_request_headers: dict[str, Any] | None = None
    external_request_body: dict[str, Any] | None = None
    external_query_params: dict[str, Any] | None = None
    external_response: Any | None = None
    external_response_time_ms: int | None = None

    full_log: str | None = None
    timeout_configured: int | None = None

    _status_to_text = field_validator("internal_api_client_status", mode="before")(
        _coerce_status
    )


class CallLogSummary(BaseModel):
    """Trimmed log row for list views."""

    model_config = ConfigDict(from_attributes=True, validate_assignment=True)

    id: int
    endpoint_id: int | None = None

    request_id: str
    method: str | None = None
    path: str | None = None

    status: str | None = None
    overall_status: bool | None = None

    external_status_code: int | None = None
    total_time_ms: int | None = None
    created_at: LocalDateTimeOptional = None

    internal_request_headers: dict[str, Any] | None = None
    internal_request_body: dict[str, Any] | None = None
    internal_api_client_response: dict[str, Any] | None = None
    internal_api_client_status: str | None = None

    external_request_url: str | None = None
    external_request_method: str | None = None
    external_request_headers: dict[str, Any] | None = None
    external_request_body: dict[str, Any] | None = None
    external_query_params: dict[str, Any] | None = None
    external_response: Any | None = None
    external_response_time_ms: int | None = None

    _status_to_text = field_validator("internal_api_client_status", mode="before")(
        _coerce_status
    )


class CallLogListResponse(PaginatedResponse):
    """Paginated envelope of CallLogSummary rows."""

    items: list[CallLogSummary] = Field(default_factory=list)


class CallLogIngestRequest(BaseModel):
    """One log entry pushed by an external caller (e.g. the CRM gateway helper).

    Only the routing/diagnostic fields are typed; every other key (headers,
    request/response bodies, timings, ``full_log``, ...) is carried through
    untouched so alias names can be normalised by the ingest service.
    """

    model_config = ConfigDict(extra="allow")

    request_id: str | int | None = None
    endpoint_id: int | str | None = None
    method: str | None = None
    path: str | None = None
    success: bool | None = None
    status: str | None = None
    status_code: int | str | None = None


class CallLogIngestResponse(BaseModel):
    """Acknowledgement returned after a log entry has been stored."""

    success: bool
    message: str
    log_id: int | None = None
    endpoint_id: int | None = None
