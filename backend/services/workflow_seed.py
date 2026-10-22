from __future__ import annotations

import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.workflow import Workflow, WorkflowStep
from backend.services.env_var_service import upsert_variable

logger = logging.getLogger(__name__)

DEFAULT_ENV_VARS = [
    {
        "key_name": "MIS_BASE_URL",
        "value": "https://devmis.sspa.gos.pk",
        "is_secret": False,
        "category": "MIS_GRM",
        "description": "Base URL for Sindh Social Protection Authority (SSPA) MIS Portal",
    },
    {
        "key_name": "MIS_KEY",
        "value": "MIS_KEY",
        "is_secret": False,
        "category": "MIS_GRM",
        "description": "System Identifier Header (x-api-key) required by SSPA MIS",
    },
    {
        "key_name": "MIS_API_KEY",
        "value": "kg8ICrhQGQRDnan8PoxHMRO825HrpCeM5sYcLbT9",
        "is_secret": True,
        "category": "MIS_GRM",
        "description": "x-api-key header required by SSPA MIS endpoints",
    },
    {
        "key_name": "MIS_EMAIL",
        "value": "mis.b9v4c7w1y8@yopmail.com",
        "is_secret": False,
        "category": "MIS_GRM",
        "description": "Partner service account login email",
    },
    {
        "key_name": "MIS_PASSWORD",
        "value": "905g87BWb2szwaX!fCqG279JXlT4%06eBE4aj1cKSRFn5#AIkk",
        "is_secret": True,
        "category": "MIS_GRM",
        "description": "Partner service account login password",
    },
    {
        "key_name": "MIS_PROGRAM_ID",
        "value": "4000001",
        "is_secret": False,
        "category": "MIS_GRM",
        "description": "Target program identifier for partner authentication",
    },
    {
        "key_name": "MIS_AES_KEY",
        "value": "0123456789abcdef0123456789abcdef",
        "is_secret": True,
        "category": "MIS_GRM",
        "description": "32-byte pre-shared symmetric key for AES-256-GCM encryption",
    },
]


WORKING_STEPS_CONFIG: list[dict[str, Any]] = [
    {
        "step_key": "step_1",
        "step_type": "start_webhook",
        "step_order": 1,
        "config": {
            "default_payload": {
                "source_ticket_id": "IMIS-TICKET-2026-00123",
                "benef_cnic": "42201-1234567-1",
                "category": "Payments",
                "subcategory": "Delayed Transfer",
                "complaint_type": "benef",
                "complainant_name": "Fatima Bibi",
                "complainant_phone": "03001234567",
                "description": "Sample grievance description",
                "notes": "Received via IMIS Call Center",
                "program_id": 4000001,
            }
        },
    },
    {
        "step_key": "step_3",
        "step_type": "http_request",
        "step_order": 2,
        "config": {
            "method": "POST",
            "url": "{{env.MIS_BASE_URL}}/api/v1/imis/auth/login",
            "headers": {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-api-key": "{{env.MIS_API_KEY}}",
            },
            "body": {
                "email": "{{env.MIS_EMAIL}}",
                "password": "{{env.MIS_PASSWORD}}",
                "program_id": "{{env.MIS_PROGRAM_ID}}",
            },
        },
    },
    {
        "step_key": "step_4",
        "step_type": "http_request",
        "step_order": 3,
        "config": {
            "method": "POST",
            "url": "{{env.MIS_BASE_URL}}/api/v1/imis/complaint/create",
            "headers": {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-api-key": "{{env.MIS_API_KEY}}",
                "Authorization": "Bearer {{nodes.step_3.data.access_token}}",
            },
            "body": {
                "notes": "{{trigger.default_payload.notes}}",
                "category": "{{trigger.default_payload.category}}",
                "benef_cnic": "{{trigger.default_payload.benef_cnic}}",
                "program_id": "{{trigger.default_payload.program_id}}",
                "description": "{{trigger.default_payload.description}}",
                "subcategory": "{{trigger.default_payload.subcategory}}",
                "complaint_type": "{{trigger.default_payload.complaint_type}}",
                "complainant_name": "{{trigger.default_payload.complainant_name}}",
                "source_ticket_id": "{{trigger.default_payload.source_ticket_id}}",
                "complainant_phone": "{{trigger.default_payload.complainant_phone}}",
            },
        },
    },
]


UPDATE_STEPS_CONFIG: list[dict[str, Any]] = [
    {
        "step_key": "step_1",
        "step_type": "start_webhook",
        "step_order": 1,
        "config": {
            "default_payload": {
                "source_ticket_id": "IMIS-TICKET-2026-0090",
                "status": "resolved",
                "description": "Payment disbursed successfully at local branch counter.",
                "resolved_by_system": "IMIS",
                "resolved_at": "2026-10-21 16:30:00",
            }
        },
    },
    {
        "step_key": "step_3",
        "step_type": "http_request",
        "step_order": 2,
        "config": {
            "method": "POST",
            "url": "{{env.MIS_BASE_URL}}/api/v1/imis/auth/login",
            "headers": {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-api-key": "{{env.MIS_API_KEY}}",
            },
            "body": {
                "email": "{{env.MIS_EMAIL}}",
                "password": "{{env.MIS_PASSWORD}}",
                "program_id": "{{env.MIS_PROGRAM_ID}}",
            },
        },
    },
    {
        "step_key": "step_4",
        "step_type": "http_request",
        "step_order": 3,
        "config": {
            "method": "POST",
            "url": "{{env.MIS_BASE_URL}}/api/v1/imis/complaint/update-status",
            "headers": {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-api-key": "{{env.MIS_API_KEY}}",
                "Authorization": "Bearer {{nodes.step_3.data.access_token}}",
            },
            "body": {
                "source_ticket_id": "{{trigger.default_payload.source_ticket_id}}",
                "status": "resolved",
                "description": "{{trigger.default_payload.description}}",
                "resolved_by_system": "IMIS",
                "resolved_at": "{{trigger.default_payload.resolved_at}}",
            },
        },
    },
]


async def _upsert_working_workflow(
    db: AsyncSession,
    slug: str,
    name: str,
    description: str,
    steps_config: list[dict[str, Any]] | None = None,
) -> None:
    if steps_config is None:
        steps_config = WORKING_STEPS_CONFIG
    stmt = select(Workflow).where(Workflow.slug == slug)
    res = await db.execute(stmt)
    wf = res.scalar_one_or_none()

    if not wf:
        wf = Workflow(
            name=name,
            slug=slug,
            description=description,
            trigger_type="webhook",
            is_active=True,
        )
        db.add(wf)
        await db.flush()

        for s_def in steps_config:
            step = WorkflowStep(
                workflow_id=wf.id,
                step_key=s_def["step_key"],
                step_type=s_def["step_type"],
                step_order=s_def["step_order"],
                config=s_def["config"],
                is_active=True,
            )
            db.add(step)
    else:
        wf.is_active = True
        step_stmt = select(WorkflowStep).where(WorkflowStep.workflow_id == wf.id)
        existing_steps = (await db.execute(step_stmt)).scalars().all()
        if not existing_steps:
            for s_def in steps_config:
                step = WorkflowStep(
                    workflow_id=wf.id,
                    step_key=s_def["step_key"],
                    step_type=s_def["step_type"],
                    step_order=s_def["step_order"],
                    config=s_def["config"],
                    is_active=True,
                )
                db.add(step)
        else:
            step_map = {s.step_key: s for s in existing_steps}
            for s_def in steps_config:
                k = s_def["step_key"]
                if k in step_map:
                    step_map[k].step_type = s_def["step_type"]
                    step_map[k].config = s_def["config"]
                    step_map[k].is_active = True
                else:
                    new_s = WorkflowStep(
                        workflow_id=wf.id,
                        step_key=k,
                        step_type=s_def["step_type"],
                        step_order=s_def["step_order"],
                        config=s_def["config"],
                        is_active=True,
                    )
                    db.add(new_s)


async def seed_default_workflows(db: AsyncSession) -> None:
    for item in DEFAULT_ENV_VARS:
        await upsert_variable(
            db=db,
            key_name=item["key_name"],
            value=item["value"],
            is_secret=item["is_secret"],
            category=item["category"],
            description=item["description"],
        )

    # Automatically delete deprecated legacy workflows
    deprecated_slugs = ["sspa-complaint-intake", "sspa-complaint-resolve"]
    del_stmt = select(Workflow).where(Workflow.slug.in_(deprecated_slugs))
    deprecated_wfs = (await db.execute(del_stmt)).scalars().all()
    for dwf in deprecated_wfs:
        await db.delete(dwf)

    await _upsert_working_workflow(
        db,
        slug="w",
        name="w1",
        description="workflow",
        steps_config=WORKING_STEPS_CONFIG,
    )
    await _upsert_working_workflow(
        db,
        slug="create-ticket",
        name="Create Ticket",
        description="Create Ticket on MIS",
        steps_config=WORKING_STEPS_CONFIG,
    )
    await _upsert_working_workflow(
        db,
        slug="update-ticket",
        name="Update Ticket",
        description="Update Complaint Status on MIS",
        steps_config=UPDATE_STEPS_CONFIG,
    )
    await _upsert_working_workflow(
        db,
        slug="w-update",
        name="w-update",
        description="workflow - update ticket status",
        steps_config=UPDATE_STEPS_CONFIG,
    )

    await _ensure_workflow_endpoint(db, "w", "w1", "https://devmis.sspa.gos.pk/api/v1/imis/complaint/create")
    await _ensure_workflow_endpoint(db, "create-ticket", "Create Ticket", "https://devmis.sspa.gos.pk/api/v1/imis/complaint/create")
    await _ensure_workflow_endpoint(db, "update-ticket", "Update Ticket", "https://devmis.sspa.gos.pk/api/v1/imis/complaint/update-status")
    await _ensure_workflow_endpoint(db, "w-update", "w-update", "https://devmis.sspa.gos.pk/api/v1/imis/complaint/update-status")

    await db.commit()

    try:
        await _backfill_existing_workflow_runs_to_logs(db)
        await db.commit()
    except Exception as exc:
        logger.warning("Could not backfill workflow runs to logs: %s", exc)
        try:
            await db.rollback()
        except Exception:
            pass


async def _ensure_workflow_endpoint(
    db: AsyncSession,
    slug: str,
    name: str,
    target_url: str = "https://devmis.sspa.gos.pk/api/v1/imis/complaint/create",
) -> None:
    try:
        from backend.models.endpoint import ApiEndpoint
        from backend.models.enums import ContentTypeEnum
        endpoint_code = f"WF_{slug.upper().replace('-', '_')}"
        stmt = select(ApiEndpoint).where(ApiEndpoint.endpoint_code == endpoint_code)
        ep = (await db.execute(stmt)).scalar_one_or_none()
        if not ep:
            url = f"/api/workflows/webhook/{slug}"
            stmt_url = select(ApiEndpoint).where(ApiEndpoint.source_api_url == url)
            ep = (await db.execute(stmt_url)).scalar_one_or_none()

        if ep:
            ep.target_api_url = target_url
            ep.request_content_type = ContentTypeEnum.JSON.value
            await db.flush()
        else:
            ep = ApiEndpoint(
                endpoint_code=endpoint_code,
                source_api_url=f"/api/workflows/webhook/{slug}",
                target_api_url=target_url,
                method="POST",
                request_content_type=ContentTypeEnum.JSON.value,
                is_active=True,
                description=f"Workflow Webhook: {name} ({slug})",
            )
            db.add(ep)
            await db.flush()

        from sqlalchemy import update
        stmt_fix = (
            update(ApiEndpoint)
            .where(ApiEndpoint.endpoint_code == endpoint_code)
            .where(ApiEndpoint.target_api_url.like("Workflow:%"))
            .values(target_api_url=target_url)
        )
        await db.execute(stmt_fix)
        await db.flush()
    except Exception as exc:
        logger.warning("Could not ensure endpoint for workflow %s: %s", slug, exc)
        try:
            await db.rollback()
        except Exception:
            pass


async def _backfill_existing_workflow_runs_to_logs(db: AsyncSession) -> None:
    from sqlalchemy import func
    from backend.models.log import ApiCallLog
    from backend.models.workflow import WorkflowRun
    from backend.services.workflow_engine import _record_workflow_to_api_call_log

    count_stmt = select(func.count(ApiCallLog.id))
    log_count = (await db.execute(count_stmt)).scalar() or 0
    if log_count > 0:
        return

    runs_stmt = (
        select(WorkflowRun, Workflow)
        .join(Workflow, WorkflowRun.workflow_id == Workflow.id)
        .order_by(WorkflowRun.ran_at.asc())
    )
    runs = (await db.execute(runs_stmt)).all()
    for run, wf in runs:
        await _record_workflow_to_api_call_log(
            db=db,
            workflow=wf,
            trigger_payload=run.trigger_payload or {},
            step_results=run.step_results or [],
            final_output=run.final_output,
            overall_status=run.status,
            total_time_ms=run.total_time_ms or 0,
            error_message=run.error_message,
        )

