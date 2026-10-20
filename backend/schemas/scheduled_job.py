"""Pydantic contracts for recurring HTTP requests."""

from __future__ import annotations

import re
from typing import Annotated
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
    field_validator,
    model_validator,
)

from backend.core.config import settings
from backend.schemas.common import LocalDateTime

_HTTP_URL = TypeAdapter(HttpUrl)
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

#: Methods the scheduler accepts a request body for.
METHODS_WITH_BODY = {"POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")

_FORBIDDEN_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "expect",
        "host",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)


def _validate_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Scheduled job URL must not be empty")
    if text.startswith("//"):
        raise ValueError("Scheduled job URL must not be protocol-relative")
    parsed = urlsplit(text)
    if parsed.scheme:
        validated = _HTTP_URL.validate_python(text)
        if validated.username is not None or validated.password is not None:
            raise ValueError("Scheduled job URL must not contain credentials")
        if validated.fragment:
            raise ValueError("Scheduled job URL must not contain a fragment")
        return str(validated)
    # Scheme-less paths are allowed: they identify a mapping-backed endpoint
    # (for example ``/v1/audio/list``) or are expanded against MAPPER_BASE_URL
    # when the job actually runs.
    if not parsed.path:
        raise ValueError("Scheduled job URL must include a path")
    if parsed.fragment:
        raise ValueError("Scheduled job URL must not contain a fragment")
    path = parsed.path if parsed.path.startswith("/") else f"/{parsed.path}"
    return urlunsplit(("", "", path, parsed.query, ""))


def _validate_headers(value: object) -> dict[str, str] | None:
    """Normalise request headers, rejecting malformed or scheduler-owned pairs."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("headers must be an object of header names to values")
    if len(value) > settings.SCHEDULER_MAX_HEADERS:
        raise ValueError(
            f"at most {settings.SCHEDULER_MAX_HEADERS} headers are allowed"
        )
    normalized: dict[str, str] = {}
    for raw_name, raw_value in value.items():
        name = str(raw_name).strip()
        if not name:
            raise ValueError("header names must not be empty")
        if not _HEADER_NAME.match(name):
            raise ValueError(f"'{name}' is not a valid header name")
        if name.lower() in _FORBIDDEN_HEADERS:
            raise ValueError(f"the '{name}' header is managed by the scheduler")
        if isinstance(raw_value, bool) or not isinstance(raw_value, (str, int, float)):
            raise ValueError(f"header '{name}' must have a text value")
        text = str(raw_value).strip()
        if any(char in text for char in ("\n", "\r", "\x00")):
            raise ValueError(f"header '{name}' contains illegal control characters")
        normalized[name] = text
    return normalized or None


def _validate_body(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("body must be a string")
    if len(value.encode("utf-8")) > settings.SCHEDULER_MAX_REQUEST_BODY_BYTES:
        raise ValueError(
            "body exceeds the "
            f"{settings.SCHEDULER_MAX_REQUEST_BODY_BYTES} byte scheduler limit"
        )
    return value or None


ScheduledJobUrl = Annotated[str, Field(max_length=2083), AfterValidator(_validate_url)]
ScheduledJobHeaders = Annotated[
    dict[str, str] | None, AfterValidator(_validate_headers)
]
ScheduledJobBody = Annotated[str | None, AfterValidator(_validate_body)]


class ScheduledJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(
        default_factory=lambda: uuid4().hex,
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )
    name: str | None = Field(default=None, max_length=255)
    url: ScheduledJobUrl
    method: str = Field(default="GET", min_length=1, max_length=16)
    headers: ScheduledJobHeaders = None
    body: ScheduledJobBody = None
    cron: str | None = Field(default=None, max_length=255)
    interval_seconds: int | None = Field(default=None, gt=0)

    @field_validator("method", mode="before")
    @classmethod
    def normalize_method(cls, value: object) -> str:
        method = str(value or "GET").strip().upper()
        if method not in _METHODS:
            raise ValueError("Unsupported HTTP method")
        return method

    @field_validator("cron", mode="before")
    @classmethod
    def normalize_cron(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value).strip() or None

    @model_validator(mode="after")
    def validate_schedule(self) -> "ScheduledJobCreate":
        if (self.cron is None) == (self.interval_seconds is None):
            raise ValueError("provide exactly one of cron or interval_seconds")
        if self.body and self.method not in METHODS_WITH_BODY:
            raise ValueError(f"{self.method} requests cannot carry a body")
        return self


class ScheduledJobUpdate(BaseModel):
    """Partial update payload for an existing cron job.

    Every field is optional; only the ones actually sent are changed. The
    schedule is switched by sending the new kind: ``cron`` replaces any
    interval and ``interval_seconds`` replaces any cron expression, so the two
    are never set at the same time. ``headers`` and ``body`` accept ``null``
    to clear them.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    url: ScheduledJobUrl | None = None
    method: str | None = Field(default=None, min_length=1, max_length=16)
    headers: ScheduledJobHeaders = None
    body: ScheduledJobBody = None
    cron: str | None = Field(default=None, max_length=255)
    interval_seconds: int | None = Field(default=None, gt=0)

    @field_validator("method", mode="before")
    @classmethod
    def normalize_method(cls, value: object) -> str | None:
        if value is None:
            return None
        method = str(value).strip().upper()
        if method not in _METHODS:
            raise ValueError("Unsupported HTTP method")
        return method

    @field_validator("cron", mode="before")
    @classmethod
    def normalize_cron(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value).strip() or None

    @model_validator(mode="after")
    def validate_update(self) -> "ScheduledJobUpdate":
        provided = self.model_fields_set
        if "cron" in provided and "interval_seconds" in provided:
            raise ValueError("provide exactly one of cron or interval_seconds")
        if (
            "body" in provided
            and self.body
            and self.method
            and self.method not in METHODS_WITH_BODY
        ):
            raise ValueError(f"{self.method} requests cannot carry a body")
        return self


class ScheduledJobToggle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class ScheduledJobMapping(BaseModel):
    """The API mapping a job is bound to, when it was created from one."""

    endpoint_id: int
    endpoint_code: str | None = None
    internal_url: str
    external_url: str
    method: str
    parameter_count: int = 0


class ScheduledJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    name: str | None
    url: str
    method: str
    headers: dict[str, str] | None = None
    body: str | None = None
    cron: str | None
    interval_seconds: int | None
    enabled: bool
    created_by: int | None
    created_at: LocalDateTime
    updated_at: LocalDateTime
    next_run_time: LocalDateTime | None = None
    last_run_at: LocalDateTime | None = None
    last_success: bool | None = None
    mapping: ScheduledJobMapping | None = None


class ScheduledJobRunSummary(BaseModel):
    """History row without the captured payload, used by the list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: str
    url: str
    method: str
    status_code: int | None
    success: bool
    duration_ms: int
    error: str | None
    ran_at: LocalDateTime
    response_size: int | None = None
    has_response_body: bool = False


class ScheduledJobRunResponse(ScheduledJobRunSummary):
    """Full run detail: both header sets plus the captured response body."""

    request_headers: dict[str, str] | None = None
    response_headers: dict[str, str] | None = None
    response_body: str | None = None
    response_body_truncated: bool = False


__all__ = [
    "METHODS_WITH_BODY",
    "ScheduledJobBody",
    "ScheduledJobCreate",
    "ScheduledJobHeaders",
    "ScheduledJobMapping",
    "ScheduledJobResponse",
    "ScheduledJobRunResponse",
    "ScheduledJobRunSummary",
    "ScheduledJobToggle",
    "ScheduledJobUpdate",
]
