from __future__ import annotations

import logging
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.crypto import decrypt_value_with_fallback, encrypt_value
from backend.models.env_var import ApiEnvVariable

logger = logging.getLogger(__name__)

_MASK = "••••••••"


def _encrypt_if_secret(val: str, is_secret: bool) -> str:
    if not is_secret or not val:
        return val
    try:
        return encrypt_value(val, settings.ENCRYPTION_KEY)
    except Exception as exc:
        logger.warning("Could not encrypt secret variable: %s", exc)
        return val


def _decrypt_if_secret(val: str, is_secret: bool) -> str:
    if not is_secret or not val:
        return val
    try:
        return decrypt_value_with_fallback(val, settings.ENCRYPTION_KEY, settings.LEGACY_ENCRYPTION_KEY) or val
    except Exception:
        return val


async def get_all_variables(
    db: AsyncSession, mask_secrets: bool = True
) -> list[dict[str, Any]]:
    stmt = select(ApiEnvVariable).order_by(ApiEnvVariable.category, ApiEnvVariable.key_name)
    result = await db.execute(stmt)
    records = result.scalars().all()

    items = []
    for row in records:
        decrypted = _decrypt_if_secret(row.value, row.is_secret)
        items.append({
            "id": row.id,
            "key_name": row.key_name,
            "value": _MASK if (row.is_secret and mask_secrets) else decrypted,
            "is_secret": row.is_secret,
            "category": row.category or "GENERAL",
            "description": row.description,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        })
    return items


async def get_env_dict(db: AsyncSession) -> dict[str, str]:
    stmt = select(ApiEnvVariable)
    result = await db.execute(stmt)
    records = result.scalars().all()
    env_map: dict[str, str] = {}
    for row in records:
        decrypted = _decrypt_if_secret(row.value, row.is_secret)
        env_map[row.key_name] = decrypted
    return env_map


async def upsert_variable(
    db: AsyncSession,
    key_name: str,
    value: str,
    is_secret: bool = True,
    category: str = "MIS_GRM",
    description: str | None = None,
) -> ApiEnvVariable:
    key_name = key_name.strip().upper()
    stmt = select(ApiEnvVariable).where(ApiEnvVariable.key_name == key_name)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    encrypted_val = _encrypt_if_secret(value, is_secret)

    if existing:
        if value != _MASK:
            existing.value = encrypted_val
        existing.is_secret = is_secret
        existing.category = category
        if description is not None:
            existing.description = description
        await db.commit()
        await db.refresh(existing)
        return existing
    else:
        new_var = ApiEnvVariable(
            key_name=key_name,
            value=encrypted_val,
            is_secret=is_secret,
            category=category,
            description=description,
        )
        db.add(new_var)
        await db.commit()
        await db.refresh(new_var)
        return new_var


async def delete_variable(db: AsyncSession, var_id: int) -> bool:
    stmt = select(ApiEnvVariable).where(ApiEnvVariable.id == var_id)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if not existing:
        return False
    await db.delete(existing)
    await db.commit()
    return True
