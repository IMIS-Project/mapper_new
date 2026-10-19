"""Database value types shared by mapper models."""

from __future__ import annotations

from typing import Any

from sqlalchemy import String, TypeDecorator
from sqlalchemy.engine import Dialect

__all__ = ["ParameterTypeValue", "YesNoBoolean"]


class YesNoBoolean(TypeDecorator[bool]):
    """Map boolean API values to legacy MySQL ``ENUM('Y', 'N')`` values."""

    impl = String(1)
    cache_ok = True

    def process_bind_param(
        self,
        value: bool | str | int | None,
        dialect: Dialect,
    ) -> str | None:
        """Convert booleans and compatible strings to values accepted by MySQL."""
        if value is None:
            return None

        normalized = str(value).strip().lower()
        if value is True or normalized in {"1", "y", "yes", "true"}:
            return "Y"
        if value is False or normalized in {"0", "n", "no", "false"}:
            return "N"

        raise ValueError(f"Unsupported Y/N value: {value!r}")

    def process_result_value(
        self,
        value: Any,
        dialect: Dialect,
    ) -> bool | None:
        """Convert stored ``Y``/``N`` values back to booleans."""
        if value is None:
            return None

        normalized = str(value).strip().upper()
        if normalized == "Y":
            return True
        if normalized == "N":
            return False

        raise ValueError(f"Unsupported Y/N value: {value!r}")


class ParameterTypeValue(TypeDecorator[str]):
    """Map the API's ``QUERY`` location onto the legacy MySQL enum value.

    The ``api_endpoint_parameter_mapping.parameter_type`` column is a legacy
    ``ENUM('HEADER', 'BODY', 'QUERYSTRING')`` -- it spells the query location
    ``QUERYSTRING`` while the application (and the mapper frontend) speaks
    ``QUERY``. Writing ``QUERY`` straight to that column makes MySQL truncate
    it (error 1265), which surfaced as a 500 on save. Translating at the column
    boundary fixes reads and writes everywhere without touching the schema.
    """

    impl = String(20)
    cache_ok = True

    _TO_DB = {
        "QUERY": "QUERYSTRING",
        "QUERYSTRING": "QUERYSTRING",
        "QUERY_STRING": "QUERYSTRING",
    }
    _FROM_DB = {
        "QUERYSTRING": "QUERY",
        "QUERY_STRING": "QUERY",
    }

    def process_bind_param(
        self,
        value: Any,
        dialect: Dialect,
    ) -> str | None:
        """Translate the app value to the spelling the column accepts."""
        if value is None:
            return None

        normalized = str(getattr(value, "value", value)).strip().upper()
        return self._TO_DB.get(normalized, normalized)

    def process_result_value(
        self,
        value: Any,
        dialect: Dialect,
    ) -> str | None:
        """Normalise legacy ``QUERYSTRING`` rows back to ``QUERY``."""
        if value is None:
            return None

        normalized = str(value).strip().upper()
        return self._FROM_DB.get(normalized, normalized)
