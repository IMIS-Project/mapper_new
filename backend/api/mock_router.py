from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_active_user, get_db
from backend.services.central_auth import CentralUser

User = CentralUser
from backend.services import endpoint_service

__all__ = ["router"]

router = APIRouter(tags=["Mock"])


class MockConfigRequest(BaseModel):
    mock_enabled: bool | None = None
    mock_response: Any = None


async def _get_or_404(db, endpoint_id: UUID):
    endpoint = await endpoint_service.get_endpoint(db, endpoint_id)
    if endpoint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found"
        )
    return endpoint


@router.get("/api-endpoints/{endpoint_id}/mock")
async def get_mock_config(
    endpoint_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_active_user),
) -> dict:
    endpoint = await _get_or_404(db, endpoint_id)
    return {
        "endpoint_id": endpoint.id,
        "mock_enabled": getattr(endpoint, "mock_enabled", None),
        "mock_response": getattr(endpoint, "mock_response", None),
    }


@router.put("/api-endpoints/{endpoint_id}/mock")
async def set_mock_config(
    endpoint_id: UUID,
    payload: MockConfigRequest,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_active_user),
) -> dict:
    await _get_or_404(db, endpoint_id)
    data = payload.model_dump(exclude_unset=True)
    endpoint = await endpoint_service.update_endpoint(db, endpoint_id, data)
    return {
        "endpoint_id": endpoint.id,
        "mock_enabled": getattr(endpoint, "mock_enabled", None),
        "mock_response": getattr(endpoint, "mock_response", None),
    }
