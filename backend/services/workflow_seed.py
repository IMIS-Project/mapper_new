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

    # 1. Seed Complaint Intake Workflow
    intake_slug = "sspa-complaint-intake"
    stmt = select(Workflow).where(Workflow.slug == intake_slug)
    res = await db.execute(stmt)
    if not res.scalar_one_or_none():
        wf_intake = Workflow(
            name="SSPA MIS - Complaint Intake (IMIS -> MIS)",
            slug=intake_slug,
            description="Two-way Grievance Redressal Mechanism (GRM) intake pipeline: Authenticates with SSPA MIS, transforms ticket payload, encrypts via AES-256-GCM, and registers complaint.",
            trigger_type="webhook",
            is_active=False,
        )
        db.add(wf_intake)
        await db.flush()

        steps = [
            WorkflowStep(
                workflow_id=wf_intake.id,
                step_key="trigger",
                step_type="trigger",
                step_order=1,
                config={
                    "default_payload": {
                        "source_ticket_id": "IMIS-TICKET-2026-00123",
                        "benef_cnic": "42201-1234567-1",
                        "category": "Payments",
                        "subcategory": "Delayed Transfer",
                        "complaint_type": "benef",
                        "complainant_name": "Fatima Bibi",
                        "complainant_phone": "03001234567",
                        "description": "Beneficiary did not receive the scheduled installment for Q2.",
                        "notes": "Received via IMIS Call Center",
                        "program_id": 1,
                    }
                },
            ),
            WorkflowStep(
                workflow_id=wf_intake.id,
                step_key="login",
                step_type="http_request",
                step_order=2,
                config={
                    "method": "POST",
                    "url": "{{env.MIS_BASE_URL}}/api/v1/imis/auth/login",
                    "headers": {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "x-api-key": "{{env.MIS_KEY}}",
                    },
                    "body": {
                        "email": "{{env.MIS_EMAIL}}",
                        "password": "{{env.MIS_PASSWORD}}",
                        "program_id": 4000001,
                    },
                },
            ),
            WorkflowStep(
                workflow_id=wf_intake.id,
                step_key="prepare_payload",
                step_type="transform",
                step_order=3,
                config={
                    "template": {
                        "source_ticket_id": "{{trigger.source_ticket_id}}",
                        "benef_cnic": "{{trigger.benef_cnic}}",
                        "category": "{{trigger.category}}",
                        "subcategory": "{{trigger.subcategory}}",
                        "complaint_type": "{{trigger.complaint_type}}",
                        "complainant_name": "{{trigger.complainant_name}}",
                        "complainant_phone": "{{trigger.complainant_phone}}",
                        "description": "{{trigger.description}}",
                        "notes": "{{trigger.notes}}",
                        "program_id": 1,
                    }
                },
            ),
            WorkflowStep(
                workflow_id=wf_intake.id,
                step_key="encrypt_payload",
                step_type="aes_encrypt",
                step_order=4,
                config={
                    "key": "{{env.MIS_AES_KEY}}",
                    "payload": "{{nodes.prepare_payload.output}}",
                },
            ),
            WorkflowStep(
                workflow_id=wf_intake.id,
                step_key="intake_api",
                step_type="http_request",
                step_order=5,
                config={
                    "method": "POST",
                    "url": "{{env.MIS_BASE_URL}}/api/v1/imis/complaint/create",
                    "headers": {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "x-api-key": "{{env.MIS_KEY}}",
                        "Authorization": "Bearer {{nodes.login.data.access_token}}",
                    },
                    "body": "{{nodes.encrypt_payload.output}}",
                },
            ),
            WorkflowStep(
                workflow_id=wf_intake.id,
                step_key="output",
                step_type="output",
                step_order=6,
                config={
                    "response": "{{nodes.intake_api.data}}",
                },
            ),
        ]
        for s in steps:
            db.add(s)

    # 2. Seed Complaint Resolution Workflow
    resolve_slug = "sspa-complaint-resolve"
    stmt2 = select(Workflow).where(Workflow.slug == resolve_slug)
    res2 = await db.execute(stmt2)
    if not res2.scalar_one_or_none():
        wf_resolve = Workflow(
            name="SSPA MIS - Complaint Resolution (IMIS -> MIS)",
            slug=resolve_slug,
            description="Two-way Grievance Redressal Mechanism (GRM) resolution pipeline: Authenticates, encrypts resolution notes, and updates ticket status to 'resolved'.",
            trigger_type="webhook",
            is_active=False,
        )
        db.add(wf_resolve)
        await db.flush()

        steps2 = [
            WorkflowStep(
                workflow_id=wf_resolve.id,
                step_key="trigger",
                step_type="trigger",
                step_order=1,
                config={
                    "default_payload": {
                        "source_ticket_id": "IMIS-TICKET-2026-00123",
                        "status": "resolved",
                        "description": "Payment disbursed successfully at local branch counter.",
                        "resolved_by_system": "IMIS",
                        "resolved_at": "2026-10-19 16:30:00",
                    }
                },
            ),
            WorkflowStep(
                workflow_id=wf_resolve.id,
                step_key="login",
                step_type="http_request",
                step_order=2,
                config={
                    "method": "POST",
                    "url": "{{env.MIS_BASE_URL}}/api/v1/imis/auth/login",
                    "headers": {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "x-api-key": "{{env.MIS_KEY}}",
                    },
                    "body": {
                        "email": "{{env.MIS_EMAIL}}",
                        "password": "{{env.MIS_PASSWORD}}",
                        "program_id": 4000001,
                    },
                },
            ),
            WorkflowStep(
                workflow_id=wf_resolve.id,
                step_key="prepare_resolution",
                step_type="transform",
                step_order=3,
                config={
                    "template": {
                        "source_ticket_id": "{{trigger.source_ticket_id}}",
                        "status": "resolved",
                        "description": "{{trigger.description}}",
                        "resolved_by_system": "IMIS",
                        "resolved_at": "{{trigger.resolved_at}}",
                    }
                },
            ),
            WorkflowStep(
                workflow_id=wf_resolve.id,
                step_key="encrypt_resolution",
                step_type="aes_encrypt",
                step_order=4,
                config={
                    "key": "{{env.MIS_AES_KEY}}",
                    "payload": "{{nodes.prepare_resolution.output}}",
                },
            ),
            WorkflowStep(
                workflow_id=wf_resolve.id,
                step_key="resolve_api",
                step_type="http_request",
                step_order=5,
                config={
                    "method": "POST",
                    "url": "{{env.MIS_BASE_URL}}/api/v1/imis/complaint/update-status",
                    "headers": {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "x-api-key": "{{env.MIS_KEY}}",
                        "Authorization": "Bearer {{nodes.login.data.access_token}}",
                    },
                    "body": "{{nodes.encrypt_resolution.output}}",
                },
            ),
            WorkflowStep(
                workflow_id=wf_resolve.id,
                step_key="output",
                step_type="output",
                step_order=6,
                config={
                    "response": "{{nodes.resolve_api.data}}",
                },
            ),
        ]
        for s in steps2:
            db.add(s)

    await db.commit()
