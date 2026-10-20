from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.core.config import settings

logger = logging.getLogger(__name__)

__all__ = [
    "apply_upstream_auth",
    "auth_url_for",
    "drop_token_header",
    "invalidate_token",
    "strip_auth_headers",
]

_MAX_DEPTH = 6
_GCM_NONCE_SIZE = 12
_GCM_TAG_SIZE = 16


@dataclass(frozen=True, slots=True)
class _CachedToken:
    token: str
    expires_at: float | None = None

    def is_valid(self, min_ttl_seconds: float) -> bool:
        if self.expires_at is None:
            return True
        return (self.expires_at - time.time()) > min_ttl_seconds


_CACHE: dict[str, _CachedToken] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def _configured() -> bool:
    """True when a shared login is fully populated in ``.env``."""
    return bool(
        settings.UPSTREAM_AUTH_URL
        and settings.UPSTREAM_AUTH_EMAIL
        and settings.UPSTREAM_AUTH_PASSWORD
    )


def _login_payload() -> dict[str, str]:
    return {
        settings.UPSTREAM_AUTH_USERNAME_FIELD or "email": settings.UPSTREAM_AUTH_EMAIL,
        settings.UPSTREAM_AUTH_PASSWORD_FIELD
        or "password": settings.UPSTREAM_AUTH_PASSWORD,
    }


def _lookup_path(data: Any, path: str) -> Any:
    """Traverse a dotted ``a.b.c`` path returning the value or ``None``."""
    current = data
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        if part not in current:
            return None
        current = current[part]
    return current


def _find_value(data: Any, keys: list[str], _depth: int = 0) -> Any:
    """Recursively find the first value whose key (or dotted path) is named."""
    if _depth > _MAX_DEPTH:
        return None
    if isinstance(data, Mapping):
        for key in keys:
            value = _lookup_path(data, key)
            if value is not None:
                return value
        for key in keys:
            if "." in key:
                leaf = key.rsplit(".", 1)[1]
                child = _find_value(data, [leaf], _depth + 1)
                if child is not None:
                    return child
        for value in data.values():
            found = _find_value(value, keys, _depth + 1)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_value(item, keys, _depth + 1)
            if found is not None:
                return found
    return None


def _parse_expiry(data: Any, keys: list[str]) -> float | None:

    raw = _find_value(data, keys)
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return time.time() + float(raw)
    if isinstance(raw, str):
        text = raw.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.timestamp()
        except ValueError:
            return None
    return None


def _process_aes_key(key_str: str) -> bytes:

    if "=" in key_str or "+" in key_str or "/" in key_str:
        try:
            key_bytes = base64.b64decode(key_str)
            if len(key_bytes) == 32:
                return key_bytes
        except Exception:
            pass

    if all(c in "0123456789abcdefABCDEF" for c in key_str):
        try:
            key_bytes = bytes.fromhex(key_str)
            if len(key_bytes) == 32:
                return key_bytes
        except ValueError:
            pass

    key_bytes = key_str.encode("utf-8")
    if len(key_bytes) != 32:
        raise ValueError(
            f"Invalid AES key length: expected 32 bytes, got {len(key_bytes)}"
        )
    return key_bytes


def _cipher_key() -> bytes | None:
    """Return the 32-byte AES-GCM key, or ``None`` when not configured."""
    key = settings.UPSTREAM_AUTH_DECRYPTION_KEY
    if not key:
        return None
    return _process_aes_key(key)


def _decrypt_login_payload(data: Any, url: str) -> str | None:

    field = settings.UPSTREAM_AUTH_ENCRYPTED_FIELD or "encrypted_data"
    blob = _find_value(data, [field]) if isinstance(data, Mapping) else None
    if not blob or not isinstance(blob, str):
        return None

    try:
        key = _cipher_key()
    except ValueError as exc:
        logger.warning("Upstream auth login: %s at %s", exc, url)
        return None
    if key is None:
        return None

    try:
        raw = base64.b64decode(blob, validate=True)
    except (ValueError, binascii.Error):
        logger.warning(
            "Upstream auth login: encrypted_data is not valid base64 at %s", url
        )
        return None
    if len(raw) < _GCM_NONCE_SIZE + _GCM_TAG_SIZE:
        logger.warning("Upstream auth login: encrypted_data too short at %s", url)
        return None

    nonce = raw[:_GCM_NONCE_SIZE]
    tag = raw[_GCM_NONCE_SIZE : _GCM_NONCE_SIZE + _GCM_TAG_SIZE]
    ciphertext = raw[_GCM_NONCE_SIZE + _GCM_TAG_SIZE :]
    try:
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext + tag, None)
    except Exception as exc:
        logger.warning(
            "Upstream auth login: failed to decrypt encrypted_data at %s: %s", url, exc
        )
        return None
    return plaintext.decode("utf-8", errors="replace")


def _encrypt_login_payload(payload: dict[str, str], url: str) -> dict[str, str] | None:

    field = settings.UPSTREAM_AUTH_ENCRYPTED_FIELD or "encrypted_data"
    try:
        key = _cipher_key()
    except ValueError as exc:
        logger.warning("Upstream auth login: %s at %s", exc, url)
        return None
    if key is None:
        return None

    nonce = os.urandom(_GCM_NONCE_SIZE)
    try:
        aesgcm = AESGCM(key)

        ct = aesgcm.encrypt(nonce, json.dumps(payload).encode("utf-8"), None)
    except Exception as exc:
        logger.warning(
            "Upstream auth login: failed to encrypt login payload at %s: %s", url, exc
        )
        return None
    ciphertext, tag = ct[:-_GCM_TAG_SIZE], ct[-_GCM_TAG_SIZE:]
    combined = nonce + tag + ciphertext
    return {field: base64.b64encode(combined).decode("ascii")}


async def _login(
    client: httpx.AsyncClient, auth_url: str | None = None
) -> _CachedToken | None:

    url = auth_url or settings.UPSTREAM_AUTH_URL
    payload = _login_payload()
    content_type = (settings.UPSTREAM_AUTH_LOGIN_CONTENT_TYPE or "json").strip().lower()

    try:
        encrypted = _encrypt_login_payload(payload, url)
        if encrypted is not None:
            response = await client.post(url, json=encrypted)
        elif content_type == "form":
            response = await client.post(url, data=payload)
        else:
            response = await client.post(url, json=payload)
    except (httpx.RequestError, httpx.TimeoutException) as exc:
        logger.warning("Upstream auth login failed (transport) at %s: %s", url, exc)
        return None

    try:
        data = response.json()
    except ValueError:
        logger.warning(
            "Upstream auth login response was not JSON at %s: HTTP %s",
            url,
            response.status_code,
        )
        return None

    decrypted = _decrypt_login_payload(data, url)
    if decrypted is not None:
        try:
            parsed = json.loads(decrypted)
        except ValueError:
            parsed = decrypted
        if isinstance(parsed, Mapping):
            data = parsed
        elif isinstance(parsed, str) and parsed.strip():
            return _CachedToken(token=parsed.strip(), expires_at=None)

    token = _find_value(data, settings.UPSTREAM_AUTH_TOKEN_KEYS)
    if isinstance(token, str) and token.strip():
        return _CachedToken(
            token=token.strip(),
            expires_at=_parse_expiry(data, settings.UPSTREAM_AUTH_EXPIRY_KEYS),
        )

    if response.status_code >= 400:
        logger.warning(
            "Upstream auth login failed at %s: HTTP %s — %s",
            url,
            response.status_code,
            response.text[:500],
        )
    else:
        logger.warning(
            "Upstream auth login succeeded but no token found (looked for %s) at %s",
            settings.UPSTREAM_AUTH_TOKEN_KEYS,
            url,
        )
    return None


async def _cached_token(
    client: httpx.AsyncClient, auth_url: str | None = None
) -> str | None:
    """Return a valid cached token, refreshing it in place when necessary."""
    if not _configured():
        return None

    url = auth_url or settings.UPSTREAM_AUTH_URL
    lock = _LOCKS.setdefault(url, asyncio.Lock())

    async with lock:
        cached = _CACHE.get(url)
        if cached is not None and cached.is_valid(
            settings.UPSTREAM_AUTH_MIN_TTL_SECONDS
        ):
            return cached.token
        fresh = await _login(client, url)
        if fresh is None:
            return cached.token if cached is not None else None
        _CACHE[url] = fresh
        return fresh.token


def _header_name() -> str:
    return (settings.UPSTREAM_AUTH_HEADER_NAME or "Authorization").strip()


def _token_value(token: str) -> str:
    prefix = (settings.UPSTREAM_AUTH_TOKEN_PREFIX or "").strip()
    return f"{prefix} {token}".strip() if prefix else token


def _static_token_for(url: str) -> str | None:

    tokens = settings.UPSTREAM_API_TOKENS or {}
    if not tokens or not url:
        return None
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return None
    if host in tokens:
        return tokens[host]
    for candidate, token in tokens.items():
        if host.endswith("." + candidate):
            return token
    return None


def auth_url_for(url: str | None) -> str | None:
    """Pick the login endpoint that issues tokens for ``url``'s host.

    ``UPSTREAM_AUTH_HOSTS`` maps a host to its own login endpoint (for
    environments that run a separate auth service). Failing that, the shared
    ``UPSTREAM_AUTH_URL`` is used when it belongs to the same host.
    """
    if not url:
        return None
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return None
    for candidate, login_url in (settings.UPSTREAM_AUTH_HOSTS or {}).items():
        name = str(candidate).lower().lstrip(".")
        if name and (host == name or host.endswith("." + name)):
            return login_url
    configured = settings.UPSTREAM_AUTH_URL
    if configured:
        configured_host = (urlparse(configured).hostname or "").lower()
        if configured_host and (
            host == configured_host or host.endswith("." + configured_host)
        ):
            return configured
    return None


def invalidate_token(upstream_url: str | None = None) -> None:
    """Forget the cached token for a host so the next lookup logs in again.

    Called when a target rejects a freshly injected token with 401. Some auth
    services report a lifetime that is longer than the token they actually
    accept, so expiry checks alone cannot catch a token that has gone stale.
    """
    url = auth_url_for(upstream_url) if upstream_url else settings.UPSTREAM_AUTH_URL
    if url:
        _CACHE.pop(url, None)


async def apply_upstream_auth(
    header_params: dict[str, str],
    http_client: httpx.AsyncClient,
    upstream_url: str | None = None,
    *,
    allow_shared: bool = True,
) -> bool:
    """Attach credentials to ``header_params``.

    Returns ``True`` when a token issued by the auth service was injected (as
    opposed to a static token or a caller-supplied header). Callers use this to
    decide whether a 401 is worth retrying after dropping the cached token.

    ``allow_shared`` controls whether the generic ``UPSTREAM_AUTH_URL`` token
    may be used for a host that has no explicit auth URL of its own. Internal
    delivery (the cron job's target) keeps the historical fallback; gateway
    calls to arbitrary external APIs pass ``False`` so the IMIS bearer is not
    leaked to a third party that never asked for it.
    """
    header_name = _header_name()
    for existing in header_params:
        if existing.lower() in {"authorization", "x-api-token", header_name.lower()}:
            return False

    token = _static_token_for(upstream_url) if upstream_url else None
    if token:
        logger.debug(
            "Injecting static API token header %r for %s", header_name, upstream_url
        )
        header_params[header_name] = _token_value(token)
        return False

    if not _configured():
        return False

    auth_url = auth_url_for(upstream_url)
    if not auth_url and not allow_shared:
        logger.debug(
            "No auth endpoint configured for %s; not injecting shared token",
            upstream_url,
        )
        return False
    try:
        token = await _cached_token(http_client, auth_url)
    except Exception as exc:  # defensive: never break the gateway on auth config
        logger.exception("Upstream auth lookup failed: %s", exc)
        return False

    if not token:
        return False

    logger.debug("Injecting upstream auth header %r for upstream call", header_name)
    header_params[header_name] = _token_value(token)
    return True


_AUTH_HEADER_NAMES = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "x-api-token",
        "api-key",
        "apikey",
        "x-auth-token",
    }
)


def strip_auth_headers(header_params: dict[str, str]) -> None:
    """Remove caller-supplied or injected credentials from a header mapping.

    Used when an endpoint is marked ``require_authentication=N`` (or when a
    cron job's own token must stay on the internal leg) so a bearer/API key
    is never leaked to an API that did not ask for it.
    """
    configured = _header_name().lower()
    for name in list(header_params):
        lowered = str(name).lower()
        if lowered in _AUTH_HEADER_NAMES or lowered == configured:
            header_params.pop(name, None)


def drop_token_header(header_params: dict[str, str]) -> None:
    """Remove an auth header previously injected by :func:`apply_upstream_auth`."""
    header_name = _header_name()
    for name in list(header_params):
        if name.lower() in {"authorization", "x-api-token", header_name.lower()}:
            header_params.pop(name, None)
