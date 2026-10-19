"""Secret redaction helpers shared by the API layer.

Used to keep credentials out of anything we echo back to a caller - response
bodies, log lines and especially FastAPI/Pydantic validation errors, which
otherwise quote the offending input verbatim.
"""

import re
from typing import Any

__all__ = ["MASK", "SENSITIVE_KEYS", "mask_sensitive", "mask_jwts", "looks_like_jwt"]

MASK = "********"

SENSITIVE_KEYS = (
    "secretkey",
    "clientid",
    "clientsecret",
    "secret",
    "password",
    "username",
    "accesstoken",
    "access_token",
    "token",
    "apikey",
    "api_key",
    # Bearer/basic credentials travel in these headers; the value must never
    # be echoed back or stored in a run's captured request headers.
    "authorization",
    "x-api-token",
)

# Three base64url segments is a JWT whatever key it happens to sit under, so
# key-based masking alone is not sufficient.
_JWT_PATTERN = re.compile(r"\b[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")


def looks_like_jwt(value: Any) -> bool:
    """True for a bare JWT string of plausible segment lengths."""
    if not isinstance(value, str) or len(value) <= 40:
        return False
    return _JWT_PATTERN.fullmatch(value.strip()) is not None


def mask_jwts(value: Any) -> Any:
    """Replace JWT-shaped substrings inside strings, recursing containers."""
    if isinstance(value, dict):
        return {key: mask_jwts(item) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_jwts(item) for item in value]
    if isinstance(value, tuple):
        return tuple(mask_jwts(item) for item in value)
    if isinstance(value, str) and _JWT_PATTERN.search(value):
        return _JWT_PATTERN.sub(MASK, value)
    return value


def mask_sensitive(value: Any) -> Any:
    """Redact by key name *and* by JWT shape, at any depth."""
    if isinstance(value, dict):
        return {
            key: (
                MASK
                if any(marker in str(key).lower() for marker in SENSITIVE_KEYS)
                else mask_sensitive(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(mask_sensitive(item) for item in value)
    if isinstance(value, str) and _JWT_PATTERN.search(value):
        return _JWT_PATTERN.sub(MASK, value)
    return value