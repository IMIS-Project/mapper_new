from typing import Any

from pydantic import BaseModel, Field


class BankCallRequest(BaseModel):
    """A single call against one allow-listed bank operation."""

    operationId: str
    payload: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, Any] | None = None
    correlationId: str | None = None
    # Chained token captured from a previous step (bank-auth AccessToken or the
    # tokenGeneration access_token). Ignored by operations that manage their own
    # token internally.
    bankToken: str | None = None


class ErrorLayer(BaseModel):
    """One hop in a failed call.

    A single request can fail at several layers at once - the console, the
    integration service, and the bank behind it - and the useful message is
    often the innermost one.
    """

    origin: str  # "mapper" | "integration-service" | "bank"
    label: str
    status_code: int | None = None
    message: str


class BankCallResponse(BaseModel):
    success: bool
    operationId: str
    targetUrl: str | None = None
    targetMethod: str | None = None
    status_code: int | None = None
    response_time_ms: int | None = None
    data: Any | None = None
    error: str | None = None
    # Where the failure came from: this service ("mapper") or the integration
    # service upstream. Lets the console label a 500 correctly instead of
    # guessing from the status code alone.
    error_source: str | None = None
    # Every layer that contributed to the failure, outermost first.
    error_layers: list[ErrorLayer] | None = None

    correlation_id: str | None = None
    token_flow: str | None = None
    token_source: str | None = None

    request_headers: dict[str, Any] | None = None
    request_body: Any | None = None
    response_headers: dict[str, Any] | None = None


class BankConfigResponse(BaseModel):
    base_url: str
    timeout_seconds: float
    # The console forwards the caller's own session bearer, so there is no
    # server-side token to report here.
    auth_mode: str = "session"