from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_active_user, get_db
from backend.services import env_var_service
from backend.services.central_auth import CentralUser

router = APIRouter(prefix="/variables", tags=["Environment Variables"])


class EnvVarUpsertRequest(BaseModel):
    key_name: str | None = Field(default=None, max_length=100)
    key: str | None = Field(default=None, max_length=100)
    value: str
    is_secret: bool = True
    category: str = "MIS_GRM"
    description: str | None = None

    @property
    def resolved_key(self) -> str:
        k = (self.key_name or self.key or "").strip()
        if not k:
            raise ValueError("key_name or key is required")
        return k


@router.get("", response_model=dict[str, Any])
async def list_variables(
    unmask: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    user: CentralUser = Depends(get_current_active_user),
):
    items = await env_var_service.get_all_variables(db, mask_secrets=not unmask)
    return {"success": True, "data": items}


@router.post("", response_model=dict[str, Any])
async def upsert_variable(
    payload: EnvVarUpsertRequest,
    db: AsyncSession = Depends(get_db),
    user: CentralUser = Depends(get_current_active_user),
):
    var = await env_var_service.upsert_variable(
        db=db,
        key_name=payload.resolved_key,
        value=payload.value,
        is_secret=payload.is_secret,
        category=payload.category,
        description=payload.description,
    )
    return {
        "success": True,
        "message": f"Variable {var.key_name} saved",
        "data": {
            "id": var.id,
            "key_name": var.key_name,
            "is_secret": var.is_secret,
            "category": var.category,
        },
    }


@router.delete("/{var_id}", response_model=dict[str, Any])
async def delete_variable(
    var_id: int,
    db: AsyncSession = Depends(get_db),
    user: CentralUser = Depends(get_current_active_user),
):
    deleted = await env_var_service.delete_variable(db, var_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Variable not found")
    return {"success": True, "message": "Variable deleted"}
