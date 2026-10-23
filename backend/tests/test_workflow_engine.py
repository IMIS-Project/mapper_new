import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
import httpx

from backend.db.base import Base
from backend.models.workflow import Workflow, WorkflowStep, WorkflowRun
from backend.services.workflow_engine import run_workflow
from backend.services.workflow_seed import seed_default_workflows
from backend.services.sspa_cipher import decrypt_sspa_payload


@pytest_asyncio.fixture
async def async_db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    from backend.models.env_var import ApiEnvVariable
    from backend.models.endpoint import ApiEndpoint
    from backend.models.log import ApiCallLog
    tables = [
        Workflow.__table__,
        WorkflowStep.__table__,
        WorkflowRun.__table__,
        ApiEnvVariable.__table__,
        ApiEndpoint.__table__,
        ApiCallLog.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables))

    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_sspa_create_ticket_workflow_execution(async_db: AsyncSession):
    # 1. Seed defaults (env variables & SSPA workflows)
    await seed_default_workflows(async_db)

    # 2. Query seeded workflow
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    stmt = select(Workflow).options(selectinload(Workflow.steps)).where(Workflow.slug == "w")
    wf = (await async_db.execute(stmt)).scalar_one()

    # 3. Create mock HTTP client
    mock_http_client = MagicMock(spec=httpx.AsyncClient)
    captured_requests = []

    async def mock_request(**kwargs):
        captured_requests.append(kwargs)
        url = kwargs.get("url", "")
        if "auth/login" in url:
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.headers = {"Content-Type": "application/json"}
            resp.json.return_value = {
                "status": "success",
                "message": "Login successful",
                "data": {
                    "access_token": "test-bearer-token-abc-123",
                    "token_type": "bearer",
                    "expires_in": 86400,
                },
            }
            return resp
        elif "complaint/create" in url:
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 201
            resp.headers = {"Content-Type": "application/json"}
            resp.json.return_value = {
                "status": "success",
                "message": "Complaint registered successfully",
                "data": {
                    "complaint_id": "a9b8c7d6-e5f4-4321-abcd-1234567890ab",
                    "complaint_number": "SSPA_2026_Oct_1042",
                    "source_ticket_id": "IMIS-TICKET-2026-00123",
                    "imis_ticket_id": "IMIS-TICKET-2026-00123",
                },
            }
            return resp
        raise RuntimeError(f"Unexpected url {url}")

    mock_http_client.request = AsyncMock(side_effect=mock_request)

    # 4. Run workflow
    trigger_payload = {
        "default_payload": {
            "source_ticket_id": "IMIS-TICKET-2026-00123",
            "benef_cnic": "42201-1234567-1",
            "category": "Payments",
            "description": "Sample grievance description",
        }
    }

    result = await run_workflow(
        workflow=wf,
        trigger_payload=trigger_payload,
        db=async_db,
        http_client=mock_http_client,
    )

    # 5. Assert workflow outcome
    assert result["status"] == "SUCCESS"
    assert result["error"] is None
    assert len(result["step_results"]) == 3

    # Verify the two HTTP calls happened
    assert len(captured_requests) == 2

    # Verify Call 1 (Login)
    login_req = captured_requests[0]
    assert login_req["method"] == "POST"
    assert login_req["url"] == "https://devmis.sspa.gos.pk/api/v1/imis/auth/login"
    assert login_req["json"]["email"] == "mis.b9v4c7w1y8@yopmail.com"

    # Verify Call 2 (Complaint intake)
    intake_req = captured_requests[1]
    assert intake_req["method"] == "POST"
    assert intake_req["url"] == "https://devmis.sspa.gos.pk/api/v1/imis/complaint/create"
    assert intake_req["headers"]["Authorization"] == "Bearer test-bearer-token-abc-123"
    assert intake_req["json"]["source_ticket_id"] == "IMIS-TICKET-2026-00123"
    assert intake_req["json"]["benef_cnic"] == "42201-1234567-1"

    # Verify final response passed through
    assert result["final_output"]["data"]["complaint_number"] == "SSPA_2026_Oct_1042"
    assert result["final_output"]["data"]["imis_ticket_id"] == "IMIS-TICKET-2026-00123"


@pytest.mark.asyncio
async def test_cleanup_deprecated_workflows(async_db: AsyncSession):
    # Pre-populate deprecated workflows to verify seed_default_workflows deletes them
    dwf1 = Workflow(name="Old Intake", slug="sspa-complaint-intake", trigger_type="webhook", is_active=False)
    dwf2 = Workflow(name="Old Resolve", slug="sspa-complaint-resolve", trigger_type="webhook", is_active=False)
    async_db.add(dwf1)
    async_db.add(dwf2)
    await async_db.commit()

    await seed_default_workflows(async_db)

    from sqlalchemy import select
    res = (await async_db.execute(select(Workflow).where(Workflow.slug.in_(["sspa-complaint-intake", "sspa-complaint-resolve"])))).scalars().all()
    assert len(res) == 0


@pytest.mark.asyncio
async def test_update_ticket_workflow_execution(async_db: AsyncSession):
    await seed_default_workflows(async_db)

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    stmt = select(Workflow).options(selectinload(Workflow.steps)).where(Workflow.slug == "update-ticket")
    wf = (await async_db.execute(stmt)).scalar_one()

    assert wf.is_active is True
    assert len(wf.steps) == 3

    mock_http_client = MagicMock(spec=httpx.AsyncClient)
    captured = []

    async def mock_request(**kwargs):
        captured.append(kwargs)
        url = kwargs.get("url", "")
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {"Content-Type": "application/json"}
        if "auth/login" in url:
            resp.json.return_value = {
                "status": "success",
                "data": {"access_token": "token-test-xyz"},
            }
        elif "complaint/update-status" in url:
            resp.json.return_value = {
                "status": "success",
                "message": "Complaint status updated successfully",
                "data": {
                    "source_ticket_id": "IMIS-TICKET-2026-0090",
                    "status": "resolved",
                },
            }
        return resp

    mock_http_client.request = AsyncMock(side_effect=mock_request)

    payload = {
        "default_payload": {
            "source_ticket_id": "IMIS-TICKET-2026-0090",
            "description": "Resolved by branch counter",
        }
    }

    result = await run_workflow(
        workflow=wf,
        trigger_payload=payload,
        db=async_db,
        http_client=mock_http_client,
    )

    assert result["status"] == "SUCCESS"
    assert len(captured) == 2
    assert captured[0]["url"] == "https://devmis.sspa.gos.pk/api/v1/imis/auth/login"
    assert captured[1]["url"] == "https://devmis.sspa.gos.pk/api/v1/imis/complaint/update-status"
    assert captured[1]["headers"]["Authorization"] == "Bearer token-test-xyz"
    assert captured[1]["json"]["source_ticket_id"] == "IMIS-TICKET-2026-0090"
    assert captured[1]["json"]["status"] == "resolved"


@pytest.mark.asyncio
async def test_step_update_and_get_complete_data(async_db: AsyncSession):
    await seed_default_workflows(async_db)

    from backend.api.workflows_router import get_workflow, get_workflow_step, update_workflow_step, WorkflowStepUpdateRequest
    from sqlalchemy import select

    # 1. Test get_workflow returns complete step details
    wf = (await async_db.execute(select(Workflow).where(Workflow.slug == "w"))).scalar_one()
    res = await get_workflow(wf_id=wf.id, db=async_db, user=None)
    assert res["success"] is True
    steps = res["data"]["steps"]
    assert len(steps) == 3

    step_4 = next(s for s in steps if s["step_key"] == "step_4")
    assert step_4["workflow_id"] == wf.id
    assert "method" in step_4["config"]
    assert "headers" in step_4["config"]
    assert "body" in step_4["config"]
    assert step_4["config"]["body"]["notes"] == "{{trigger.default_payload.notes}}"

    # 2. Test get_workflow_step returns single step complete details
    single_res = await get_workflow_step(wf_id=wf.id, step_id=step_4["id"], db=async_db, user=None)
    assert single_res["success"] is True
    assert single_res["data"]["id"] == step_4["id"]
    assert single_res["data"]["config"]["body"]["notes"] == "{{trigger.default_payload.notes}}"

    # 3. Test update_workflow_step modifies config in DB and returns updated data
    new_config = {
        "method": "POST",
        "url": "https://example.com/custom-endpoint",
        "headers": {"x-custom": "true"},
        "body": {"custom_field": "custom_value"},
    }
    update_payload = WorkflowStepUpdateRequest(config=new_config)
    update_res = await update_workflow_step(
        wf_id=wf.id, step_id=step_4["id"], payload=update_payload, db=async_db, user=None
    )
    assert update_res["success"] is True
    assert update_res["data"]["config"]["url"] == "https://example.com/custom-endpoint"
    assert update_res["data"]["config"]["body"]["custom_field"] == "custom_value"

    # Verify directly via fresh query
    step_check = (await async_db.execute(select(WorkflowStep).where(WorkflowStep.id == step_4["id"]))).scalar_one()
    assert step_check.config["url"] == "https://example.com/custom-endpoint"

    # 4. Verify re-seeding DOES NOT overwrite user-customized config!
    await seed_default_workflows(async_db)
    step_after_seed = (await async_db.execute(select(WorkflowStep).where(WorkflowStep.id == step_4["id"]))).scalar_one()
    assert step_after_seed.config["url"] == "https://example.com/custom-endpoint"
    assert step_after_seed.config["body"]["custom_field"] == "custom_value"



