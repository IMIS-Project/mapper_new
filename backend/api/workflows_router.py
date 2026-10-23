from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any
import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from backend.api.deps import get_current_active_user, get_db
from backend.models.workflow import Workflow, WorkflowRun, WorkflowStep
from backend.services.central_auth import CentralUser
from backend.services.env_var_service import get_env_dict
from backend.services.http_client import get_http_client
from backend.services.workflow_engine import execute_step, run_workflow
from backend.services.workflow_seed import seed_default_workflows

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["Workflows"])


class WorkflowCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    trigger_type: str = "manual"
    is_active: bool = True


class WorkflowUpdateRequest(BaseModel):
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    trigger_type: str | None = None
    is_active: bool | None = None


class WorkflowStepCreateRequest(BaseModel):
    step_key: str = Field(..., min_length=1, max_length=100)
    step_type: str = Field(..., min_length=1, max_length=50)
    step_order: int = 1
    config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class WorkflowStepUpdateRequest(BaseModel):
    step_key: str | None = None
    step_type: str | None = None
    step_order: int | None = None
    config: dict[str, Any] | str | None = None
    is_active: bool | None = None


class StepOrderUpdate(BaseModel):
    step_id: str
    step_order: int


class ReorderStepsRequest(BaseModel):
    steps: list[StepOrderUpdate]


class WorkflowRunRequest(BaseModel):
    trigger_payload: dict[str, Any] | None = None


class StepTestRequest(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] | None = None
    step_type: str | None = None


@router.get("", response_model=dict[str, Any])
async def list_workflows(
    db: AsyncSession = Depends(get_db),
    user: CentralUser = Depends(get_current_active_user),
):
    # Ensure default workflows and variables are seeded
    has_update_stmt = select(func.count(Workflow.id)).where(Workflow.slug == "update-ticket")
    has_update = (await db.execute(has_update_stmt)).scalar() or 0
    if has_update == 0:
        await seed_default_workflows(db)

    stmt = (
        select(Workflow)
        .options(selectinload(Workflow.steps), selectinload(Workflow.runs))
        .order_by(Workflow.name)
    )
    result = await db.execute(stmt)
    workflows = result.scalars().all()

    items = []
    for wf in workflows:
        last_run = wf.runs[0] if wf.runs else None
        items.append({
            "id": wf.id,
            "name": wf.name,
            "slug": wf.slug,
            "description": wf.description,
            "trigger_type": wf.trigger_type,
            "is_active": wf.is_active,
            "step_count": len(wf.steps),
            "created_at": wf.created_at,
            "updated_at": wf.updated_at,
            "last_run": (
                {
                    "status": last_run.status,
                    "ran_at": last_run.ran_at,
                    "total_time_ms": last_run.total_time_ms,
                }
                if last_run
                else None
            ),
        })

    return {"success": True, "data": items}


@router.post("", response_model=dict[str, Any])
async def create_workflow(
    payload: WorkflowCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: CentralUser = Depends(get_current_active_user),
):
    existing = await db.execute(select(Workflow).where(Workflow.slug == payload.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Workflow slug already exists")

    wf = Workflow(
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        trigger_type=payload.trigger_type,
        is_active=payload.is_active,
    )
    db.add(wf)
    await db.commit()
    await db.refresh(wf)
    return {"success": True, "data": {"id": wf.id, "slug": wf.slug, "name": wf.name}}


@router.get("/{wf_id}", response_model=dict[str, Any])
async def get_workflow(
    wf_id: str,
    db: AsyncSession = Depends(get_db),
    user: CentralUser = Depends(get_current_active_user),
):
    stmt = (
        select(Workflow)
        .options(selectinload(Workflow.steps))
        .where(Workflow.id == wf_id)
    )
    result = await db.execute(stmt)
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    sorted_steps = sorted(wf.steps, key=lambda s: s.step_order)
    steps_data = []
    for s in sorted_steps:
        cfg = s.config
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception:
                cfg = {}
        steps_data.append({
            "id": s.id,
            "workflow_id": s.workflow_id,
            "step_key": s.step_key,
            "step_type": s.step_type,
            "step_order": s.step_order,
            "config": cfg if cfg is not None else {},
            "is_active": s.is_active,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
        })

    return {
        "success": True,
        "data": {
            "id": wf.id,
            "name": wf.name,
            "slug": wf.slug,
            "description": wf.description,
            "trigger_type": wf.trigger_type,
            "is_active": wf.is_active,
            "created_at": wf.created_at,
            "updated_at": wf.updated_at,
            "steps": steps_data,
        },
    }


@router.put("/{wf_id}", response_model=dict[str, Any])
async def update_workflow(
    wf_id: str,
    payload: WorkflowUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: CentralUser = Depends(get_current_active_user),
):
    stmt = select(Workflow).where(Workflow.id == wf_id)
    result = await db.execute(stmt)
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if payload.name is not None:
        wf.name = payload.name
    if payload.slug is not None:
        wf.slug = payload.slug
    if payload.description is not None:
        wf.description = payload.description
    if payload.trigger_type is not None:
        wf.trigger_type = payload.trigger_type
    if payload.is_active is not None:
        wf.is_active = payload.is_active

    await db.commit()
    await db.refresh(wf)
    return {"success": True, "message": "Workflow updated", "data": {"id": wf.id, "slug": wf.slug, "is_active": wf.is_active}}


@router.delete("/{wf_id}", response_model=dict[str, Any])
async def delete_workflow(
    wf_id: str,
    db: AsyncSession = Depends(get_db),
    user: CentralUser = Depends(get_current_active_user),
):
    stmt = select(Workflow).where(Workflow.id == wf_id)
    result = await db.execute(stmt)
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    await db.delete(wf)
    await db.commit()
    return {"success": True, "message": "Workflow deleted"}


@router.post("/{wf_id}/steps", response_model=dict[str, Any])
async def add_workflow_step(
    wf_id: str,
    payload: WorkflowStepCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: CentralUser = Depends(get_current_active_user),
):
    stmt = select(Workflow).where(Workflow.id == wf_id)
    wf = (await db.execute(stmt)).scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    step = WorkflowStep(
        workflow_id=wf.id,
        step_key=payload.step_key,
        step_type=payload.step_type,
        step_order=payload.step_order,
        config=payload.config,
        is_active=payload.is_active,
    )
    db.add(step)
    await db.commit()
    await db.refresh(step)
    return {
        "success": True,
        "message": "Step created",
        "data": {
            "id": step.id,
            "workflow_id": step.workflow_id,
            "step_key": step.step_key,
            "step_type": step.step_type,
            "step_order": step.step_order,
            "config": step.config or {},
            "is_active": step.is_active,
            "created_at": step.created_at,
            "updated_at": step.updated_at,
        },
    }


@router.get("/{wf_id}/steps/{step_id}", response_model=dict[str, Any])
async def get_workflow_step(
    wf_id: str,
    step_id: str,
    db: AsyncSession = Depends(get_db),
    user: CentralUser = Depends(get_current_active_user),
):
    stmt = select(WorkflowStep).where(
        WorkflowStep.workflow_id == wf_id, WorkflowStep.id == step_id
    )
    step = (await db.execute(stmt)).scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")

    cfg = step.config
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except Exception:
            cfg = {}

    return {
        "success": True,
        "data": {
            "id": step.id,
            "workflow_id": step.workflow_id,
            "step_key": step.step_key,
            "step_type": step.step_type,
            "step_order": step.step_order,
            "config": cfg if cfg is not None else {},
            "is_active": step.is_active,
            "created_at": step.created_at,
            "updated_at": step.updated_at,
        },
    }


@router.put("/{wf_id}/steps/reorder", response_model=dict[str, Any])
async def reorder_workflow_steps(
    wf_id: str,
    payload: ReorderStepsRequest,
    db: AsyncSession = Depends(get_db),
    user: CentralUser = Depends(get_current_active_user),
):
    stmt = select(WorkflowStep).where(WorkflowStep.workflow_id == wf_id)
    steps = (await db.execute(stmt)).scalars().all()
    step_map = {s.id: s for s in steps}

    for item in payload.steps:
        if item.step_id in step_map:
            step_map[item.step_id].step_order = item.step_order

    await db.commit()
    return {"success": True, "message": "Steps reordered"}


@router.put("/{wf_id}/steps/{step_id}", response_model=dict[str, Any])
async def update_workflow_step(
    wf_id: str,
    step_id: str,
    payload: WorkflowStepUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: CentralUser = Depends(get_current_active_user),
):
    stmt = select(WorkflowStep).where(
        WorkflowStep.workflow_id == wf_id, WorkflowStep.id == step_id
    )
    step = (await db.execute(stmt)).scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")

    if payload.step_key is not None and payload.step_key.strip():
        new_key = payload.step_key.strip()
        if new_key != step.step_key:
            conflict_stmt = select(func.count(WorkflowStep.id)).where(
                WorkflowStep.workflow_id == wf_id,
                WorkflowStep.step_key == new_key,
                WorkflowStep.id != step_id,
            )
            conflict_count = (await db.execute(conflict_stmt)).scalar() or 0
            if conflict_count > 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"A step with key '{new_key}' already exists in this workflow.",
                )
            step.step_key = new_key

    if payload.step_type is not None:
        step.step_type = payload.step_type
    if payload.step_order is not None:
        step.step_order = payload.step_order

    if payload.config is not None:
        cfg = payload.config
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid JSON in config: {e}")
        step.config = dict(cfg) if isinstance(cfg, dict) else cfg
        flag_modified(step, "config")

    if payload.is_active is not None:
        step.is_active = payload.is_active

    step.updated_at = datetime.now()

    await db.commit()
    await db.refresh(step)

    cfg = step.config
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except Exception:
            cfg = {}

    return {
        "success": True,
        "message": "Step updated successfully",
        "data": {
            "id": step.id,
            "workflow_id": step.workflow_id,
            "step_key": step.step_key,
            "step_type": step.step_type,
            "step_order": step.step_order,
            "config": cfg if cfg is not None else {},
            "is_active": step.is_active,
            "created_at": step.created_at,
            "updated_at": step.updated_at,
        },
    }


@router.delete("/{wf_id}/steps/{step_id}", response_model=dict[str, Any])
async def delete_workflow_step(
    wf_id: str,
    step_id: str,
    db: AsyncSession = Depends(get_db),
    user: CentralUser = Depends(get_current_active_user),
):
    stmt = select(WorkflowStep).where(
        WorkflowStep.workflow_id == wf_id, WorkflowStep.id == step_id
    )
    step = (await db.execute(stmt)).scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")

    await db.delete(step)
    await db.commit()
    return {"success": True, "message": "Step deleted"}


@router.post("/{wf_id}/run", response_model=dict[str, Any])
async def execute_workflow(
    wf_id: str,
    payload: WorkflowRunRequest,
    db: AsyncSession = Depends(get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
    user: CentralUser = Depends(get_current_active_user),
):
    stmt = (
        select(Workflow)
        .options(selectinload(Workflow.steps))
        .where(Workflow.id == wf_id)
    )
    wf = (await db.execute(stmt)).scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    trigger_data = payload.trigger_payload or {}
    if not trigger_data:
        # Check if first step is trigger and has default_payload
        for s in wf.steps:
            if s.step_type in ("trigger", "webhook", "start_webhook") and isinstance(s.config, dict):
                trigger_data = s.config.get("default_payload", {})
                break

    result = await run_workflow(
        workflow=wf,
        trigger_payload=trigger_data,
        db=db,
        http_client=http_client,
    )
    return {"success": True, "data": result}


@router.post("/{wf_id}/steps/{step_id}/test", response_model=dict[str, Any])
async def test_workflow_step(
    wf_id: str,
    step_id: str,
    payload: StepTestRequest,
    db: AsyncSession = Depends(get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
    user: CentralUser = Depends(get_current_active_user),
):
    stmt = select(WorkflowStep).where(
        WorkflowStep.workflow_id == wf_id, WorkflowStep.id == step_id
    )
    step = (await db.execute(stmt)).scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")

    env_vars = await get_env_dict(db)
    test_context = {
        "env": env_vars,
        "trigger": payload.context.get("trigger", {}),
        "nodes": payload.context.get("nodes", {}),
    }

    # Use unsaved live config if provided by the editor
    target_step = step
    if payload.config is not None or payload.step_type is not None:
        target_step = WorkflowStep(
            id=step.id,
            workflow_id=step.workflow_id,
            step_key=step.step_key,
            step_type=payload.step_type or step.step_type,
            step_order=step.step_order,
            config=payload.config if payload.config is not None else step.config,
            is_active=step.is_active,
        )

    start = time.perf_counter()
    try:
        output = await execute_step(target_step, test_context, http_client)
        duration_ms = int((time.perf_counter() - start) * 1000)
        http_log = None
        if isinstance(output, dict) and "_http_log" in output:
            http_log = output.pop("_http_log")

        return {
            "success": True,
            "data": {
                "step_key": target_step.step_key,
                "step_type": target_step.step_type,
                "status": "SUCCESS",
                "duration_ms": duration_ms,
                "output": output,
                "http_log": http_log,
                "error": None,
            },
        }
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        http_log = getattr(exc, "http_log", None)
        failed_output = getattr(exc, "output", None)
        if isinstance(failed_output, dict) and "_http_log" in failed_output:
            failed_output.pop("_http_log", None)

        return {
            "success": False,
            "data": {
                "step_key": target_step.step_key,
                "step_type": target_step.step_type,
                "status": "FAILED",
                "duration_ms": duration_ms,
                "output": failed_output,
                "http_log": http_log,
                "error": str(exc),
            },
        }


@router.get("/runs/{run_id}", response_model=dict[str, Any])
async def get_workflow_run_by_id(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(WorkflowRun).where(WorkflowRun.id == run_id)
    run = (await db.execute(stmt)).scalar_one_or_none()
    if not run:
        raise HTTPException(
            status_code=404,
            detail={"code": "RUN_NOT_FOUND", "message": f"Workflow run '{run_id}' not found"},
        )
    return {
        "success": True,
        "data": {
            "id": run.id,
            "workflow_id": run.workflow_id,
            "status": run.status,
            "total_time_ms": run.total_time_ms,
            "ran_at": run.ran_at,
            "error_message": run.error_message,
            "trigger_payload": run.trigger_payload,
            "step_results": run.step_results,
            "final_output": run.final_output,
        },
    }


@router.get("/{wf_id}/runs", response_model=dict[str, Any])
async def get_workflow_runs(
    wf_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: CentralUser = Depends(get_current_active_user),
):
    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.workflow_id == wf_id)
        .order_by(desc(WorkflowRun.ran_at))
        .limit(limit)
    )
    runs = (await db.execute(stmt)).scalars().all()
    runs_data = [
        {
            "id": r.id,
            "status": r.status,
            "total_time_ms": r.total_time_ms,
            "ran_at": r.ran_at,
            "error_message": r.error_message,
            "step_results": r.step_results,
            "final_output": r.final_output,
        }
        for r in runs
    ]
    return {"success": True, "data": runs_data}


@router.post("/execute-by-slug/{slug}", response_model=dict[str, Any])
async def execute_workflow_by_slug(
    slug: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
    request_headers: dict[str, Any] | None = None,
):
    """External / Webhook execution endpoint callable by IMIS or other systems."""
    stmt = (
        select(Workflow)
        .options(selectinload(Workflow.steps))
        .where(Workflow.slug == slug)
    )
    wf = (await db.execute(stmt)).scalar_one_or_none()
    if not wf:
        raise HTTPException(
            status_code=404,
            detail={"code": "WORKFLOW_NOT_FOUND", "message": f"Workflow with slug '{slug}' not found"},
        )

    if not wf.is_active:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "WORKFLOW_INACTIVE",
                "message": f"Workflow '{wf.name}' is currently INACTIVE (Unlive). Please toggle it to LIVE in the workflow builder to activate the webhook listener.",
                "slug": slug,
                "workflow_id": wf.id,
                "is_active": False,
            },
        )

    trigger_data = payload or {}
    if not trigger_data:
        for s in wf.steps:
            if s.step_type in ("trigger", "webhook", "start_webhook") and isinstance(s.config, dict):
                trigger_data = s.config.get("default_payload", {})
                break

    result = await run_workflow(
        workflow=wf,
        trigger_payload=trigger_data,
        db=db,
        http_client=http_client,
        request_headers=request_headers,
    )
    if result["status"] == "FAILED":
        raise HTTPException(
            status_code=502,
            detail={
                "code": "WORKFLOW_EXECUTION_FAILED",
                "message": result.get("error"),
                "run_id": result.get("run_id"),
                "step_results": result.get("step_results"),
            },
        )

    final_output = result.get("final_output")
    if (
        isinstance(final_output, dict)
        and "body" in final_output
        and "status_code" in final_output
        and "headers" in final_output
    ):
        final_output = final_output.get("body")

    if isinstance(final_output, dict):
        response_payload = dict(final_output)
        if "status" not in response_payload:
            response_payload["status"] = "success"
        response_payload["run_id"] = result.get("run_id")
        return response_payload

    return {
        "status": "success",
        "data": final_output,
        "run_id": result.get("run_id"),
    }


class ParseCurlRequest(BaseModel):
    curl_command: str


@router.post("/parse-curl", response_model=dict[str, Any])
async def parse_curl_endpoint(payload: ParseCurlRequest):
    """Parse raw cURL command into structured {method, url, headers, body}."""
    from backend.services.curl_parser import parse_curl_command
    parsed = parse_curl_command(payload.curl_command)
    return {"success": True, "data": parsed}


@router.api_route("/webhook/{slug}", methods=["GET", "POST", "PUT", "PATCH"], response_model=dict[str, Any])
async def webhook_trigger_endpoint(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
):
    """Start Webhook node trigger: accepts incoming webhooks and launches workflow."""
    try:
        body = await request.json()
    except Exception:
        body = dict(request.query_params)

    headers = dict(request.headers)

    print("=" * 60, flush=True)
    print(f"[WORKFLOW WEBHOOK HIT] /api/workflows/webhook/{slug}", flush=True)
    print(f"Method: {request.method}", flush=True)
    try:
        print("Incoming Data (Payload):\n" + json.dumps(body, indent=2, default=str), flush=True)
    except Exception:
        print(f"Incoming Data (Payload): {body}", flush=True)
    print("=" * 60, flush=True)

    return await execute_workflow_by_slug(slug, body, db, http_client, request_headers=headers)

