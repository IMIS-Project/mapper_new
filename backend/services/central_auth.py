from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.core.config import settings

logger = logging.getLogger(__name__)

_NONCE_SIZE = 12
_TAG_SIZE = 16

# Short-lived identity cache keyed by a digest of the access token. Entries are
# dropped when they expire; the size cap is only a backstop for a process that
# sees an unusual number of distinct tokens.
_TOKEN_CACHE: dict[str, tuple[float, "CentralUser"]] = {}
_TOKEN_CACHE_MAX_ENTRIES = 512


def _prune_token_cache() -> None:
    """Drop expired entries, then the soonest-expiring ones if still oversized."""
    now = time.monotonic()
    for key in [key for key, (expiry, _) in _TOKEN_CACHE.items() if expiry <= now]:
        _TOKEN_CACHE.pop(key, None)
    overflow = len(_TOKEN_CACHE) - _TOKEN_CACHE_MAX_ENTRIES
    if overflow > 0:
        for key, _ in sorted(_TOKEN_CACHE.items(), key=lambda item: item[1][0])[
            :overflow
        ]:
            _TOKEN_CACHE.pop(key, None)


__all__ = [
    "CentralAuthError",
    "CentralAuthRateLimited",
    "CentralAuthRejected",
    "CentralAuthUnavailable",
    "CentralSession",
    "CentralTokenPair",
    "CentralUser",
    "central_login",
    "central_logout",
    "central_refresh",
    "decrypt_auth_json",
    "encrypt_auth_json",
    "invalidate_access_token",
    "validate_access_token",
]


class CentralAuthError(RuntimeError):
    """An error returned while talking to the centralized auth service."""

    def __init__(
        self,
        message: str,
        status_code: int = 502,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after


class CentralAuthUnavailable(CentralAuthError):
    """The central service could not be reached or is not configured."""

    def __init__(
        self,
        message: str = "Authentication service unavailable",
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message, status_code=503, retry_after=retry_after)


class CentralAuthRateLimited(CentralAuthError):
    """The central service is throttling us; retrying immediately makes it worse."""

    def __init__(
        self, message: str = "Too many requests", retry_after: int | None = None
    ) -> None:
        super().__init__(message, status_code=429, retry_after=retry_after)


class CentralAuthRejected(CentralAuthError):
    """The central service rejected supplied credentials or a token."""

    def __init__(
        self, message: str = "Invalid credentials", status_code: int = 401
    ) -> None:
        super().__init__(message, status_code=status_code)


@dataclass(slots=True)
class CentralUser:
    """Identity data returned by the central permissions endpoint."""

    id: int
    user_name: str
    email: str | None = None
    is_active: bool = True
    roles: list[str] = field(default_factory=list)
    is_super_admin: bool = False
    permissions: Any = field(default_factory=dict)
    programs: list[Any] = field(default_factory=list)


@dataclass(slots=True)
class CentralSession:
    """Normalized successful central login result."""

    access_token: str
    refresh_token: str | None
    expires_in: int | None
    user: CentralUser


@dataclass(slots=True)
class CentralTokenPair:
    """Normalized refresh result; the refresh token is reusable by design."""

    access_token: str
    refresh_token: str | None
    expires_in: int | None
    user: CentralUser | None = None


def _process_aes_key(value: str | None) -> bytes:
    """Resolve the central AES key exactly as the auth service does."""
    if not value:
        raise CentralAuthUnavailable(
            "Central authentication encryption key is not configured"
        )

    if "=" in value or "+" in value or "/" in value:
        try:
            decoded = base64.b64decode(value, validate=True)
            if len(decoded) == 32:
                return decoded
        except (ValueError, binascii.Error):
            pass

    if all(char in "0123456789abcdefABCDEF" for char in value):
        try:
            decoded = bytes.fromhex(value)
            if len(decoded) == 32:
                return decoded
        except ValueError:
            pass

    raw = value.encode("utf-8")
    if len(raw) != 32:
        raise CentralAuthUnavailable(
            "Central authentication encryption key must be 32 bytes"
        )
    return raw


def _auth_key() -> bytes:

    return _process_aes_key(
        settings.AUTH_SERVICE_ENCRYPTION_KEY or settings.UPSTREAM_AUTH_DECRYPTION_KEY
    )


def encrypt_auth_json(payload: Mapping[str, Any]) -> str:
    """Encrypt JSON as base64(nonce + GCM tag + ciphertext)."""
    key = _auth_key()
    nonce = os.urandom(_NONCE_SIZE)
    encrypted = AESGCM(key).encrypt(
        nonce, json.dumps(dict(payload), separators=(",", ":")).encode("utf-8"), None
    )
    ciphertext, tag = encrypted[:-_TAG_SIZE], encrypted[-_TAG_SIZE:]
    return base64.b64encode(nonce + tag + ciphertext).decode("ascii")


def decrypt_auth_json(blob: str) -> dict[str, Any]:
    """Decrypt the central service's AES-GCM JSON envelope."""
    try:
        raw = base64.b64decode(blob, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise CentralAuthError(
            "Authentication service returned invalid encrypted data"
        ) from exc
    if len(raw) < _NONCE_SIZE + _TAG_SIZE:
        raise CentralAuthError(
            "Authentication service returned truncated encrypted data"
        )

    nonce = raw[:_NONCE_SIZE]
    tag = raw[_NONCE_SIZE : _NONCE_SIZE + _TAG_SIZE]
    ciphertext = raw[_NONCE_SIZE + _TAG_SIZE :]
    try:
        plaintext = AESGCM(_auth_key()).decrypt(nonce, ciphertext + tag, None)
        value = json.loads(plaintext.decode("utf-8"))
    except Exception as exc:
        raise CentralAuthError(
            "Unable to decrypt authentication service response"
        ) from exc
    if not isinstance(value, dict):
        raise CentralAuthError("Authentication service response was not a JSON object")
    return value


def _base_url() -> str:
    """Return the central service base URL, including the ``/auth`` mount."""
    raw = settings.AUTH_BASE_URL
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    path = parsed.path.rstrip("/")
    for suffix in ("/openapi.json", "/auth1/login"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    if not path:
        path = "/auth"
    return f"{parsed.scheme or 'https'}://{parsed.netloc}{path}"


def _url(path: str) -> str:
    return f"{_base_url().rstrip('/')}/{path.lstrip('/')}"


# 5xx responses are worth another attempt; 4xx never are. A rejected password
# or an upstream rate limit will not change on a retry, and retrying a
# rate-limited endpoint only extends the block.
_TRANSIENT_STATUS = frozenset({500, 502, 503, 504})


async def _request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    what: str,
    attempts: int | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Send one central-auth request, retrying transient failures.

    A dropped connection or a brief 5xx from the central service used to
    surface to the caller as a hard 503 with nothing written to the log, which
    made the failure impossible to diagnose. Retry those, log every outcome,
    and let 4xx responses through so the caller sees the real reason.
    """
    total = max(
        1, int(attempts if attempts is not None else settings.AUTH_RETRY_ATTEMPTS)
    )
    delay = max(0.0, float(settings.AUTH_RETRY_BACKOFF_SECONDS))
    last_exc: Exception | None = None

    for attempt in range(1, total + 1):
        try:
            response = await client.request(method, url, **kwargs)
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            last_exc = exc
            logger.warning(
                "Central auth %s failed (attempt %d/%d) at %s: %s",
                what,
                attempt,
                total,
                url,
                exc,
            )
            if attempt < total:
                await asyncio.sleep(delay * attempt)
                continue
            raise CentralAuthUnavailable() from exc

        if response.status_code in _TRANSIENT_STATUS and attempt < total:
            logger.warning(
                "Central auth %s returned HTTP %s (attempt %d/%d) at %s; retrying",
                what,
                response.status_code,
                attempt,
                total,
                url,
            )
            await asyncio.sleep(delay * attempt)
            continue

        if response.status_code >= 400:
            logger.warning(
                "Central auth %s returned HTTP %s at %s: %s",
                what,
                response.status_code,
                url,
                response.text[:300],
            )
        return response

    raise CentralAuthUnavailable() from last_exc


def _json_response(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError as exc:
        raise CentralAuthError("Authentication service returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise CentralAuthError("Authentication service returned an invalid response")
    return value


def _envelope(response: httpx.Response) -> dict[str, Any]:
    """Read an encrypted or plain APIResponse envelope."""
    raw = _json_response(response)
    encrypted = raw.get("encrypted_data")
    if not isinstance(encrypted, str) and isinstance(raw.get("data"), Mapping):
        encrypted = raw["data"].get("encrypted_data")
    if isinstance(encrypted, str) and encrypted:
        return decrypt_auth_json(encrypted)
    return raw


def _retry_after_seconds(response: httpx.Response) -> int | None:
    """Seconds to wait before retrying, from an upstream ``Retry-After`` header."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0, int(float(raw)))
    except (TypeError, ValueError):
        return None


def _raise_for_error(response: httpx.Response, envelope: Mapping[str, Any]) -> None:
    code_value = envelope.get("code", response.status_code)
    try:
        code = int(code_value)
    except (TypeError, ValueError):
        code = response.status_code
    status = str(envelope.get("status", "")).lower()
    if response.status_code < 400 and code < 400 and status != "error":
        return

    message = str(
        envelope.get("message") or envelope.get("detail") or "Authentication failed"
    )
    retry_after = _retry_after_seconds(response)
    if code in {400, 401, 403} or response.status_code in {400, 401, 403}:
        raise CentralAuthRejected(
            message, status_code=code if 400 <= code < 600 else response.status_code
        )
    if code == 429 or response.status_code == 429:
        logger.warning("Central auth rate limited the request: %s", message)
        raise CentralAuthRateLimited(message, retry_after=retry_after)
    if response.status_code >= 500 or code >= 500:
        logger.error(
            "Central auth rejected the request with a server error: HTTP %s, "
            "code=%s, message=%s",
            response.status_code,
            code,
            message,
        )
        raise CentralAuthUnavailable(
            "Authentication service is temporarily unavailable",
            retry_after=retry_after,
        )
    raise CentralAuthError(
        message,
        status_code=code if 400 <= code < 600 else 502,
        retry_after=retry_after,
    )


def _request_json(response: httpx.Response) -> dict[str, Any]:
    try:
        envelope = _envelope(response)
    except CentralAuthError as exc:
        logger.warning(
            "Central auth returned an unusable body (HTTP %s): %s",
            response.status_code,
            exc,
        )
        if response.status_code >= 500:
            raise CentralAuthUnavailable(
                retry_after=_retry_after_seconds(response)
            ) from exc
        raise
    _raise_for_error(response, envelope)
    return envelope


async def _get_pre_auth_token(
    client: httpx.AsyncClient, ip_address: str | None = None
) -> str:
    """Get the short-lived token required by the central login route."""
    try:
        response = await _request(
            client,
            "POST",
            _url("get_token"),
            what="get_token",
            json={
                "interface_type_id": 0,
                "mac_address": "00:00:00:00:00:00",
                "ip_address": ip_address or "0.0.0.0",
            },
        )
    except (httpx.RequestError, httpx.TimeoutException) as exc:
        raise CentralAuthUnavailable() from exc

    envelope = _request_json(response)
    data = envelope.get("data")
    token = data.get("token") if isinstance(data, Mapping) else None
    if not token and isinstance(data, Mapping):
        token = data.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise CentralAuthError("Authentication service did not return a pre-auth token")
    return token.strip()


def _active_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().upper() not in {"N", "FALSE", "0", "INACTIVE", "DISABLED"}
    return bool(value) if value is not None else True


def _role_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for role in value:
        if isinstance(role, str):
            name = role
        elif isinstance(role, Mapping):
            name = role.get("role_name") or role.get("name") or role.get("role")
        else:
            name = None
        if name and str(name) not in result:
            result.append(str(name))
    return result


def _central_user(data: Mapping[str, Any]) -> CentralUser:
    user = data.get("user")
    user_data = user if isinstance(user, Mapping) else data
    user_id = user_data.get("id", user_data.get("user_id", data.get("user_id")))
    if user_id is None:
        raise CentralAuthError(
            "Authentication service response did not include a user id"
        )
    try:
        normalized_id = int(user_id)
    except (TypeError, ValueError) as exc:
        raise CentralAuthError(
            "Authentication service returned an invalid user id"
        ) from exc

    email = user_data.get("email")
    user_name = (
        user_data.get("name")
        or user_data.get("user_name")
        or user_data.get("username")
        or email
        or ""
    )
    programs = user_data.get("programs", [])
    return CentralUser(
        id=normalized_id,
        user_name=str(user_name),
        email=str(email) if email else None,
        is_active=_active_value(
            user_data.get("is_active", user_data.get("active", True))
        ),
        roles=_role_names(user_data.get("roles", data.get("roles", []))),
        is_super_admin=bool(
            user_data.get("is_super_admin", data.get("is_super_admin", False))
        ),
        permissions=data.get("permissions_by_program", data.get("permissions", {})),
        programs=list(programs) if isinstance(programs, list) else [],
    )


async def central_login(
    client: httpx.AsyncClient,
    email: str,
    password: str,
    ip_address: str | None = None,
) -> CentralSession:
    """Perform the two-step encrypted central login."""
    pre_auth_token = await _get_pre_auth_token(client, ip_address=ip_address)
    payload = {"email": email.strip(), "password": password, "interface_type": "W"}
    try:
        response = await _request(
            client,
            "POST",
            _url("auth1/login"),
            what="login",
            headers={"Authorization": f"Bearer {pre_auth_token}"},
            json={"encrypted_data": encrypt_auth_json(payload)},
        )
    except (httpx.RequestError, httpx.TimeoutException) as exc:
        raise CentralAuthUnavailable() from exc

    envelope = _request_json(response)
    data = envelope.get("data")
    if not isinstance(data, Mapping):
        raise CentralAuthError("Authentication service returned no login data")
    access_token = data.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise CentralAuthRejected(
            "Authentication service did not return an access token"
        )
    user = _central_user(data)
    expires = data.get("access_token_expires_in", data.get("expires_in"))
    try:
        expires_in = int(expires) if expires is not None else None
    except (TypeError, ValueError):
        expires_in = None
    refresh_token = data.get("refresh_token")
    return CentralSession(
        access_token=access_token.strip(),
        refresh_token=str(refresh_token) if refresh_token else None,
        expires_in=expires_in,
        user=user,
    )


async def validate_access_token(
    client: httpx.AsyncClient, access_token: str
) -> CentralUser:
    """Validate an access token and load the current central identity.

    Results are cached for a short window. Without it every console request -
    including the 15s scheduled-jobs polling - costs a round trip to the
    central service, so a single blip there fails unrelated reads with a 503.
    """
    cache_key = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
    cached = _TOKEN_CACHE.get(cache_key)
    if cached is not None and cached[0] > time.monotonic():
        return cached[1]

    try:
        response = await _request(
            client,
            "GET",
            _url("auth1/permissions"),
            what="permissions",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    except (httpx.RequestError, httpx.TimeoutException) as exc:
        raise CentralAuthUnavailable() from exc
    envelope = _request_json(response)
    data = envelope.get("data")
    if not isinstance(data, Mapping):
        raise CentralAuthRejected("Authentication service returned no permission data")
    user = _central_user(data)

    ttl = max(0.0, float(settings.AUTH_TOKEN_CACHE_SECONDS))
    if ttl:
        _TOKEN_CACHE[cache_key] = (time.monotonic() + ttl, user)
        if len(_TOKEN_CACHE) > _TOKEN_CACHE_MAX_ENTRIES:
            _prune_token_cache()
    return user


def invalidate_access_token(access_token: str) -> None:
    """Drop a cached identity so a revoked token is rejected immediately."""
    if access_token:
        _TOKEN_CACHE.pop(hashlib.sha256(access_token.encode("utf-8")).hexdigest(), None)


async def central_refresh(
    client: httpx.AsyncClient, refresh_token: str
) -> CentralTokenPair:
    """Exchange a central refresh token for a new access token."""
    try:
        response = await _request(
            client,
            "POST",
            _url("auth1/refresh_token"),
            what="refresh",
            headers={"Authorization": f"Bearer {refresh_token}"},
            json={"encrypted_data": encrypt_auth_json({})},
        )
    except (httpx.RequestError, httpx.TimeoutException) as exc:
        raise CentralAuthUnavailable() from exc
    envelope = _request_json(response)
    data = envelope.get("data")
    if not isinstance(data, Mapping):
        raise CentralAuthRejected("Authentication service returned no refresh data")
    access_token = data.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise CentralAuthRejected(
            "Authentication service did not return an access token"
        )
    expires = data.get("expires_in", data.get("access_token_expires_in"))
    try:
        expires_in = int(expires) if expires is not None else None
    except (TypeError, ValueError):
        expires_in = None
    return CentralTokenPair(
        access_token=access_token.strip(),
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


async def central_logout(client: httpx.AsyncClient, access_token: str) -> None:
    """Revoke a central access token; callers may treat this as best effort."""
    invalidate_access_token(access_token)
    try:
        response = await _request(
            client,
            "POST",
            _url("auth1/logout"),
            what="logout",
            attempts=1,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"encrypted_data": encrypt_auth_json({})},
        )
    except (httpx.RequestError, httpx.TimeoutException, CentralAuthError):
        return

    if response.status_code not in {401, 403}:
        try:
            _request_json(response)
        except CentralAuthError:
            return
