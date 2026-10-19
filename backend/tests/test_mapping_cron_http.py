"""HTTP-level coverage for mapping-backed cron jobs.

The service tests drive :func:`execute_scheduled_job` directly, which skips the
router entirely. These tests go through the real routes so the wiring is
exercised too: the response models, the status codes, and — most importantly —
the fact that registering a job for an internal (RFC1918-style) API is allowed,
whereas a hand-typed private URL is still refused by the scheduler's SSRF
allowlist.
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

EXTERNAL_URL = "https://external.test/v2/orders"
# A private address: the scheduler allowlist rejects private destinations by
# default, so this only passes because the mapping path skips that check.
INTERNAL_URL = "http://10.20.30.40/internal/orders"
MANUAL_PRIVATE_URL = "http://10.20.30.40/manual-health"

PRELUDE = (
    '''
import asyncio
import json

import httpx
from fastapi.testclient import TestClient

import main
from backend.api.deps import get_current_active_user
from backend.db.base import Base
from backend.db.scheduler_session import (
    SchedulerSessionLocal,
    create_scheduler_tables,
)
from backend.db.session import AsyncSessionLocal, engine
from backend.models import ApiEndpoint, ParameterMapping
from backend.services import scheduler_service
from backend.services.central_auth import CentralUser

INTERNAL_URL = "'''
    + INTERNAL_URL
    + '''"
MANUAL_PRIVATE_URL = "'''
    + MANUAL_PRIVATE_URL
    + '''"
EXTERNAL_URL = "'''
    + EXTERNAL_URL
    + '''"

USER = CentralUser(id=1, user_name="tester", is_active=True)

def client():
    """The real app with auth and both databases pointed at the sandbox."""
    from backend.api.scheduled_jobs_router import get_scheduler_db
    from backend.db.session import get_db

    app = main.create_app()
    app.dependency_overrides[get_current_active_user] = lambda: USER
    app.dependency_overrides[get_db] = get_db_sandbox
    app.dependency_overrides[get_scheduler_db] = get_scheduler_db_sandbox
    # Not entered as a context manager, so the lifespan (and the real
    # scheduler) never starts.
    return TestClient(app)


async def get_db_sandbox():
    async with AsyncSessionLocal() as session:
        yield session


async def get_scheduler_db_sandbox():
    async with SchedulerSessionLocal() as session:
        yield session


async def seed():
    async with AsyncSessionLocal() as db:
        endpoint = ApiEndpoint(
            endpoint_code="EP-HTTP0001",
            source_api_url=EXTERNAL_URL,
            target_api_url=INTERNAL_URL,
            method="POST",
            is_active=True,
        )
        db.add(endpoint)
        await db.flush()
        db.add(
            ParameterMapping(
                api_endpoint_id=endpoint.id,
                source_parameter="ref_no",
                target_parameter="reference",
                data_type="STRING",
                parameter_type="BODY",
                is_active=True,
            )
        )
        await db.commit()
        return endpoint.id


def transport():
    calls = []

    async def handler(request):
        calls.append(str(request.url))
        if str(request.url) == EXTERNAL_URL:
            return httpx.Response(
                200, content=b'{"ref_no": "EXT-7"}', request=request
            )
        return httpx.Response(200, content=b'{"stored": true}', request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls
'''
)


SCRIPT_HEAD = """
async def _entry():
    await create_scheduler_tables()
    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=[ApiEndpoint.__table__, ParameterMapping.__table__],
        )
    # The lifespan is not run by TestClient, but create_job registers the job
    # with APScheduler, so the scheduler has to be up.
    await scheduler_service.start_scheduler(httpx.AsyncClient())
    try:
"""

SCRIPT_TAIL = """
    finally:
        await scheduler_service.stop_scheduler()

asyncio.run(_entry())
"""


def run_isolated(body: str) -> None:
    with tempfile.TemporaryDirectory(prefix="mapper-cron-http-") as directory:
        env = os.environ.copy()
        env.update(
            {
                "JWT_SECRET": "cron-http-test",
                "ENCRYPTION_KEY": "cron-http-test",
                "AUTH_BASE_URL": "https://auth.test",
                "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
                "SCHEDULER_DATABASE_PATH": str(Path(directory) / "scheduler.db"),
                # Empty allowlist and no private networks, so only the mapping
                # path can make a private internal API reachable.
                "SCHEDULER_ALLOWED_HOSTS": "",
                "SCHEDULER_ALLOW_PRIVATE_NETWORKS": "false",
                "UPSTREAM_AUTH_URL": "",
                "UPSTREAM_AUTH_EMAIL": "",
                "UPSTREAM_AUTH_PASSWORD": "",
                "UPSTREAM_API_TOKENS": "",
            }
        )
        script = (
            SCRIPT_HEAD + textwrap.indent(textwrap.dedent(body), " " * 8) + SCRIPT_TAIL
        )
        result = subprocess.run(
            [sys.executable, "-c", PRELUDE + script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode:
            raise AssertionError(result.stderr or result.stdout)


class MappingCronHttpTests(unittest.TestCase):
    def test_endpoints_expose_their_parameter_mappings(self):
        run_isolated(
            """
            await seed()
            response = client().get("/api/api-endpoints")
            assert response.status_code == 200, response.text
            rows = response.json()
            assert len(rows) == 1, rows
            parameters = rows[0]["parameters"]
            assert len(parameters) == 1, parameters
            assert parameters[0]["source_parameter"] == "ref_no"
            assert parameters[0]["target_parameter"] == "reference"
            """
        )

    def test_mapping_backed_job_registers_against_a_private_internal_api(self):
        run_isolated(
            """
            await seed()
            http = client()

            created = http.post(
                "/api/scheduled-jobs",
                json={
                    "job_id": "mapped",
                    "name": "Mapped orders",
                    "url": INTERNAL_URL,
                    "method": "POST",
                    "interval_seconds": 3600,
                    "body": '{"reference": "REF-3"}',
                },
            )
            # The same URL typed by hand is refused, because the scheduler
            # allowlist blocks private destinations.
            assert created.status_code == 201, created.text
            job = created.json()
            assert job["mapping"] is not None, job
            assert job["mapping"]["endpoint_code"] == "EP-HTTP0001"
            assert job["mapping"]["external_url"] == EXTERNAL_URL
            assert job["mapping"]["internal_url"] == INTERNAL_URL
            assert job["mapping"]["parameter_count"] == 1

            listed = http.get("/api/scheduled-jobs")
            assert listed.status_code == 200, listed.text
            entries = listed.json()
            assert len(entries) == 1, entries
            assert entries[0]["mapping"]["endpoint_id"] == job["mapping"]["endpoint_id"]

            manual = http.post(
                "/api/scheduled-jobs",
                json={
                    "job_id": "manual",
                    "url": MANUAL_PRIVATE_URL,
                    "method": "GET",
                    "interval_seconds": 3600,
                },
            )
            assert manual.status_code == 422, manual.text
            assert "disallowed" in manual.text, manual.text
            """
        )

    def test_run_now_returns_the_two_leg_envelope(self):
        run_isolated(
            """
            await seed()
            http = client()
            http.post(
                "/api/scheduled-jobs",
                json={
                    "job_id": "mapped",
                    "url": INTERNAL_URL,
                    "method": "POST",
                    "interval_seconds": 3600,
                    "body": '{"reference": "REF-3"}',
                },
            )

            transport_client, calls = transport()
            scheduler_service._http_client = transport_client
            try:
                ran = http.post("/api/scheduled-jobs/mapped/run")
            finally:
                await transport_client.aclose()

            assert ran.status_code == 200, ran.text
            run = ran.json()
            assert run["success"] is True, run
            assert run["status_code"] == 200

            envelope = json.loads(run["response_body"])
            assert envelope["kind"] == "api-mapping-cron-run"
            assert envelope["mapping"]["endpoint_code"] == "EP-HTTP0001"
            assert envelope["external"]["status_code"] == 200
            assert envelope["external"]["body"] == {"ref_no": "EXT-7"}
            assert envelope["internal"]["status_code"] == 200
            assert envelope["internal"]["body"] == '{"stored": true}'

            # External first, then the internal API.
            assert calls == [EXTERNAL_URL, INTERNAL_URL], calls

            detail = http.get(f"/api/scheduled-runs/{run['id']}")
            assert detail.status_code == 200, detail.text
            assert json.loads(detail.json()["response_body"])["kind"] == (
                "api-mapping-cron-run"
            )

            runs = http.get("/api/scheduled-jobs/mapped/runs")
            assert runs.status_code == 200, runs.text
            assert runs.json()[0]["has_response_body"] is True
            """
        )

    def test_toggle_and_delete_keep_working_for_a_mapped_job(self):
        run_isolated(
            """
            await seed()
            http = client()
            http.post(
                "/api/scheduled-jobs",
                json={
                    "job_id": "mapped",
                    "url": INTERNAL_URL,
                    "method": "POST",
                    "interval_seconds": 3600,
                    "body": '{"reference": "REF-3"}',
                },
            )

            paused = http.patch("/api/scheduled-jobs/mapped", json={"enabled": False})
            assert paused.status_code == 200, paused.text
            assert paused.json()["enabled"] is False
            assert paused.json()["mapping"] is not None

            resumed = http.patch("/api/scheduled-jobs/mapped", json={"enabled": True})
            assert resumed.status_code == 200, resumed.text
            assert resumed.json()["enabled"] is True

            removed = http.delete("/api/scheduled-jobs/mapped")
            assert removed.status_code == 200, removed.text
            assert http.get("/api/scheduled-jobs").json() == []
            """
        )
