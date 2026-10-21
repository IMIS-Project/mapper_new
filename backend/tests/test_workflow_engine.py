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
async def test_sspa_intake_workflow_execution(async_db: AsyncSession):
    # 1. Seed defaults (env variables & SSPA workflows)
    await seed_default_workflows(async_db)

    # 2. Query seeded workflow
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    stmt = select(Workflow).options(selectinload(Workflow.steps)).where(Workflow.slug == "sspa-complaint-intake")
    wf = (await async_db.execute(stmt)).scalar_one()

    # 3. Create mock HTTP client
    mock_http_client = MagicMock(spec=httpx.AsyncClient)

    captured_requests = []

    async def mock_request(**kwargs):
        captured_requests.append(kwargs)
        url = kwargs.get("url", "")
        if "auth/login" in url:
            # Login response matching SSPA MIS format
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
            # Complaint intake response
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
        "source_ticket_id": "IMIS-TICKET-2026-00123",
        "benef_cnic": "42201-1234567-1",
        "category": "Payments",
        "subcategory": "Delayed Transfer",
        "complaint_type": "benef",
        "complainant_name": "Fatima Bibi",
        "complainant_phone": "03001234567",
        "description": "Payment was not deposited into designated branch account.",
        "notes": "Received via IMIS Call Center",
        "program_id": 1,
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
    assert len(result["step_results"]) == 6

    # Verify the two HTTP calls happened
    assert len(captured_requests) == 2

    # Verify Call 1 (Login)
    login_req = captured_requests[0]
    assert login_req["method"] == "POST"
    assert login_req["url"] == "https://devmis.sspa.gos.pk/api/v1/imis/auth/login"
    assert login_req["headers"]["x-api-key"] == "MIS_KEY"
    assert login_req["json"]["email"] == "mis.b9v4c7w1y8@yopmail.com"

    # Verify Call 2 (Complaint intake)
    intake_req = captured_requests[1]
    assert intake_req["method"] == "POST"
    assert intake_req["url"] == "https://devmis.sspa.gos.pk/api/v1/imis/complaint/create"
    assert intake_req["headers"]["Authorization"] == "Bearer test-bearer-token-abc-123"
    assert intake_req["headers"]["x-api-key"] == "MIS_KEY"

    # Verify Call 2 body was AES-256-GCM encrypted and decryptable
    encrypted_body = intake_req["json"]
    assert "encrypted_data" in encrypted_body
    decrypted_body = decrypt_sspa_payload(encrypted_body, "0123456789abcdef0123456789abcdef")
    assert decrypted_body["source_ticket_id"] == "IMIS-TICKET-2026-00123"
    assert decrypted_body["benef_cnic"] == "42201-1234567-1"
    assert decrypted_body["category"] == "Payments"

    # Verify final response passed through
    assert result["final_output"]["complaint_number"] == "SSPA_2026_Oct_1042"
    assert result["final_output"]["imis_ticket_id"] == "IMIS-TICKET-2026-00123"


@pytest.mark.asyncio
async def test_sspa_resolve_workflow_execution(async_db: AsyncSession):
    await seed_default_workflows(async_db)

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    stmt = select(Workflow).options(selectinload(Workflow.steps)).where(Workflow.slug == "sspa-complaint-resolve")
    wf = (await async_db.execute(stmt)).scalar_one()

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
                "data": {"access_token": "token-resolve-456"},
            }
            return resp
        elif "complaint/update-status" in url:
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.headers = {"Content-Type": "application/json"}
            resp.json.return_value = {
                "status": "success",
                "message": "Complaint status updated successfully",
                "data": {
                    "source_ticket_id": "IMIS-TICKET-2026-00123",
                    "imis_ticket_id": "IMIS-TICKET-2026-00123",
                    "status": "resolved",
                    "complaint_id": "a9b8c7d6-e5f4-4321-abcd-1234567890ab",
                },
            }
            return resp
        raise RuntimeError(f"Unexpected url {url}")

    mock_http_client.request = AsyncMock(side_effect=mock_request)

    resolve_payload = {
        "source_ticket_id": "IMIS-TICKET-2026-00123",
        "description": "Payment disbursed successfully at local branch counter.",
        "resolved_at": "2026-10-19 16:30:00",
    }

    result = await run_workflow(
        workflow=wf,
        trigger_payload=resolve_payload,
        db=async_db,
        http_client=mock_http_client,
    )

    assert result["status"] == "SUCCESS"
    assert result["error"] is None
    assert len(captured_requests) == 2

    resolve_req = captured_requests[1]
    assert resolve_req["url"] == "https://devmis.sspa.gos.pk/api/v1/imis/complaint/update-status"
    assert resolve_req["headers"]["Authorization"] == "Bearer token-resolve-456"

    # Verify encrypted body
    decrypted_body = decrypt_sspa_payload(resolve_req["json"], "0123456789abcdef0123456789abcdef")
    assert decrypted_body["status"] == "resolved"
    assert decrypted_body["source_ticket_id"] == "IMIS-TICKET-2026-00123"
    assert decrypted_body["resolved_by_system"] == "IMIS"


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


