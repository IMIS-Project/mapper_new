"""Shared response envelopes and value types used across the API."""

from datetime import datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, Field

from backend.core.clock import as_local


def _as_local(value: datetime) -> datetime:
    localized = as_local(value)
    return localized if localized is not None else value


def _as_optional_local(value: datetime | None) -> datetime | None:
    return as_local(value)


# Datetimes leave the API with the server's local offset attached.  The
# console can therefore sort them correctly while still showing the server's
# wall clock instead of the viewer's browser timezone.
LocalDateTime = Annotated[datetime, AfterValidator(_as_local)]
LocalDateTimeOptional = Annotated[datetime | None, AfterValidator(_as_optional_local)]


class SuccessResponse(BaseModel):
    """Generic single-operation result."""

    success: bool = True
    message: str = ""


class PaginatedResponse(BaseModel):
    """Generic pagination envelope for list endpoints."""

    items: list[Any] = Field(default_factory=list)
    total: int
    page: int
    per_page: int
    pages: int
