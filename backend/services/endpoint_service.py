from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from backend.core.config import settings
from backend.core.crypto import (
    decrypt_value_with_fallback,
    encrypt_value,
)
from backend.models import ApiEndpoint, ParameterMapping

__all__ = [
    "check_duplicate",
    "create_endpoint",
    "create_endpoint_flush",
    "delete_endpoint",
    "generate_endpoint_code",
    "get_endpoint",
    "list_endpoints",
    "toggle_endpoint",
    "update_endpoint",
]

_SENSITIVE_FIELDS = ("sftp_password", "api_password")


def generate_endpoint_code() -> str:
    """Return a fresh ``EP-XXXXXXXX`` code (upper-case, 8 random hex chars)."""
    return f"EP-{uuid4().hex[:8].upper()}"


def _as_int(value: object) -> int | None:

    if isinstance(value, int):
        return value
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (AttributeError, TypeError, ValueError):
        return None


def _encrypt_sensitive(data: dict[str, Any]) -> dict[str, Any]:

    prepared = dict(data)
    for field in _SENSITIVE_FIELDS:
        if field not in prepared:
            continue
        value = prepared[field]
        if not value:
            prepared[field] = None
        else:
            prepared[field] = encrypt_value(str(value), settings.ENCRYPTION_KEY)
    return prepared


def _decrypt_sensitive(endpoint: ApiEndpoint) -> ApiEndpoint:
    """Decrypt credential columns in place without dirtying the instance."""
    for field in _SENSITIVE_FIELDS:
        value = getattr(endpoint, field)
        if value:
            set_committed_value(
                endpoint,
                field,
                decrypt_value_with_fallback(
                    value,
                    settings.ENCRYPTION_KEY,
                    settings.LEGACY_ENCRYPTION_KEY,
                ),
            )
    return endpoint


async def _fetch_by_id(db: AsyncSession, endpoint_id: int | str) -> ApiEndpoint | None:
    """Plain single-row fetch (no eager loading, credentials left encrypted)."""
    identifier = _as_int(endpoint_id)
    if identifier is None:
        return None
    result = await db.execute(select(ApiEndpoint).where(ApiEndpoint.id == identifier))
    return result.scalar_one_or_none()


async def list_endpoints(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    search: str | None = None,
    is_active: bool | None = None,
) -> list[ApiEndpoint]:

    statement = (
        select(ApiEndpoint)
        .options(selectinload(ApiEndpoint.parameters))
        .order_by(ApiEndpoint.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                ApiEndpoint.endpoint_code.ilike(pattern),
                ApiEndpoint.source_api_url.ilike(pattern),
                ApiEndpoint.target_api_url.ilike(pattern),
            )
        )
    if is_active is not None:
        statement = statement.where(ApiEndpoint.is_active == is_active)

    result = await db.execute(statement)
    return [_decrypt_sensitive(endpoint) for endpoint in result.scalars().all()]


async def get_endpoint(db: AsyncSession, endpoint_id: int | str) -> ApiEndpoint | None:

    identifier = _as_int(endpoint_id)
    if identifier is None:
        return None
    result = await db.execute(
        select(ApiEndpoint)
        .options(selectinload(ApiEndpoint.parameters))
        .where(ApiEndpoint.id == identifier)
    )
    endpoint = result.scalar_one_or_none()
    return _decrypt_sensitive(endpoint) if endpoint is not None else None


async def create_endpoint_flush(db: AsyncSession, data: dict[str, Any]) -> ApiEndpoint:

    payload = _encrypt_sensitive(data)
    if not payload.get("endpoint_code"):
        payload["endpoint_code"] = generate_endpoint_code()
    endpoint = ApiEndpoint(**payload)
    db.add(endpoint)
    await db.flush()
    return endpoint


async def create_endpoint(db: AsyncSession, data: dict[str, Any]) -> ApiEndpoint:

    endpoint = await create_endpoint_flush(db, data)
    await db.commit()
    await db.refresh(endpoint)
    return _decrypt_sensitive(endpoint)


async def update_endpoint(
    db: AsyncSession, endpoint_id: int | str, data: dict[str, Any]
) -> ApiEndpoint | None:

    endpoint = await _fetch_by_id(db, endpoint_id)
    if endpoint is None:
        return None

    for field, value in _encrypt_sensitive(data).items():
        setattr(endpoint, field, value)

    await db.commit()
    await db.refresh(endpoint)
    return _decrypt_sensitive(endpoint)


async def delete_endpoint(
    db: AsyncSession, endpoint_id: int | str, hard: bool = False
) -> bool:

    endpoint = await _fetch_by_id(db, endpoint_id)
    if endpoint is None:
        return False

    if hard:
        await db.execute(
            delete(ParameterMapping).where(
                ParameterMapping.api_endpoint_id == endpoint.id
            )
        )
        await db.delete(endpoint)
    else:
        endpoint.is_active = False

    await db.commit()
    return True


async def check_duplicate(
    db: AsyncSession,
    source_url: str,
    target_url: str,
    method: str,
    exclude_id: int | str | None = None,
) -> ApiEndpoint | None:

    statement = select(ApiEndpoint).where(
        ApiEndpoint.source_api_url == source_url,
        ApiEndpoint.target_api_url == target_url,
        ApiEndpoint.is_active == True,
    )
    if method:
        statement = statement.where(
            func.upper(ApiEndpoint.method) == method.strip().upper()
        )
    identifier = _as_int(exclude_id)
    if identifier is not None:
        statement = statement.where(ApiEndpoint.id != identifier)

    result = await db.execute(
        statement.order_by(ApiEndpoint.created_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def toggle_endpoint(
    db: AsyncSession, endpoint_id: int | str
) -> ApiEndpoint | None:
    """Flip ``is_active`` and return the endpoint (``None`` when missing)."""
    endpoint = await _fetch_by_id(db, endpoint_id)
    if endpoint is None:
        return None

    endpoint.is_active = not endpoint.is_active
    await db.commit()
    await db.refresh(endpoint)
    return _decrypt_sensitive(endpoint)
