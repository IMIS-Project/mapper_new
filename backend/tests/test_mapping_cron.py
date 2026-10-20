"""Mapping-backed cron jobs: external first, then the internal API.

The contract asserted here is the one the feature was built for:

* the mapping is picked up from the scheduler job's ``url`` + ``method`` —
  nothing about it is stored in the scheduler database;
* the **external** API (``source_api_url``) is called first, on every tick;
* its response is then forwarded **verbatim** to the **internal** API
  (``target_api_url``);
* the application database is only ever SELECTed.

Each test runs in its own subprocess, exactly like the scheduler suite, so the
in-memory SQLite databases and the APScheduler singletons stay isolated.
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
INTERNAL_URL = "https://internal.test/orders"

PRELUDE = (
    '''
import asyncio
import json

import httpx
from sqlalchemy import event, select

from backend.db.base import Base
from backend.db.scheduler_session import (
    SchedulerSessionLocal,
    create_scheduler_tables,
    dispose_scheduler_engine,
)
from backend.db.session import AsyncSessionLocal, engine
from backend.models import ApiCallLog, ApiEndpoint, ParameterMapping
from backend.models.scheduled_job import ScheduledJob
from backend.services import mapping_job_service, scheduler_service

EXTERNAL_URL = "'''
    + EXTERNAL_URL
    + '''"
INTERNAL_URL = "'''
    + INTERNAL_URL
    + '''"

# Every statement issued against the application database is recorded so a
# test can assert that the mapping tables are only ever read.
STATEMENTS = []
STATEMENT_SQL = []

_READ_ONLY = {"SELECT", "PRAGMA", "BEGIN", "COMMIT", "ROLLBACK", "ROLLBACK TO SAVEPOINT", "SAVEPOINT", "RELEASE SAVEPOINT"}


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _record(conn, cursor, statement, parameters, context, executemany):
    STATEMENTS.append(statement.strip().split()[0].upper())
    STATEMENT_SQL.append(statement)


def reset_statements():
    STATEMENTS.clear()
    STATEMENT_SQL.clear()


def writes():
    """Writes to the mapping tables.

    ``api_call_log`` is deliberately excluded: every scheduled run mirrors its
    audit row there, and that insert must not be mistaken for the mapping
    configuration being modified.
    """
    return [
        verb
        for verb, sql in zip(STATEMENTS, STATEMENT_SQL)
        if verb not in _READ_ONLY and "api_call_log" not in sql.lower()
    ]


async def seed_mapping(*, active=True):
    """One active mapping: the internal /orders -> the external /v2/orders."""
    async with AsyncSessionLocal() as db:
        endpoint = ApiEndpoint(
            endpoint_code="EP-TEST0001",
            source_api_url=EXTERNAL_URL,
            target_api_url=INTERNAL_URL,
            method="POST",
            is_active=active,
        )
        db.add(endpoint)
        await db.flush()
        db.add_all(
            [
                # source_parameter is the external field and target_parameter
                # the internal one, which is the direction the gateway reads.
                ParameterMapping(
                    api_endpoint_id=endpoint.id,
                    source_parameter="ref_no",
                    target_parameter="reference",
                    data_type="STRING",
                    parameter_type="BODY",
                    is_active=True,
                ),
                ParameterMapping(
                    api_endpoint_id=endpoint.id,
                    source_parameter="status",
                    target_parameter="state",
                    data_type="STRING",
                    parameter_type="BODY",
                    is_active=True,
                ),
            ]
        )
        await db.commit()
        return endpoint.id


async def drop_mappings():
    async with AsyncSessionLocal() as db:
        for row in list((await db.execute(select(ParameterMapping))).scalars().all()):
            await db.delete(row)
        for row in list((await db.execute(select(ApiEndpoint))).scalars().all()):
            await db.delete(row)
        await db.commit()


async def create_job(
    url=INTERNAL_URL,
    method="POST",
    body='{"reference": "REF-1", "state": "OPEN"}',
):
    async with SchedulerSessionLocal() as db:
        row = ScheduledJob(
            job_id="mapped-job",
            name="Mapped",
            url=url,
            method=method,
            headers=scheduler_service.dump_headers({"X-Api-Key": "secret"}),
            body=body,
            cron=None,
            interval_seconds=3600,
            enabled=True,
            created_by=None,
        )
        db.add(row)
        await db.commit()
    return row


async def teardown():
    await dispose_scheduler_engine()
    scheduler_service._http_client = None
'''
)


SCRIPT_HEAD = """
async def main():
    await create_scheduler_tables()
    # Only the two mapping tables are needed here; the full metadata carries a
    # pre-existing `webhooks.created_by` -> `users` foreign key that no model
    # declares, so it cannot be created wholesale on SQLite.
    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=[
                ApiEndpoint.__table__,
                ParameterMapping.__table__,
                ApiCallLog.__table__,
            ],
        )
    try:
"""

SCRIPT_TAIL = """
    finally:
        await teardown()

asyncio.run(main())
"""


def run_isolated(body: str) -> None:
    """Run ``body`` in a subprocess seeded with the mapping helpers."""
    with tempfile.TemporaryDirectory(prefix="mapper-mapping-cron-") as directory:
        env = os.environ.copy()
        env.update(
            {
                "JWT_SECRET": "mapping-cron-test",
                "ENCRYPTION_KEY": "mapping-cron-test",
                "AUTH_BASE_URL": "https://auth.test",
                "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
                "SCHEDULER_DATABASE_PATH": str(Path(directory) / "scheduler.db"),
                # Allow-listing the hosts short-circuits the DNS check, so the
                # `.test` names never have to resolve.
                "SCHEDULER_ALLOWED_HOSTS": "internal.test,external.test,manual.test",
                "SCHEDULER_ALLOW_PRIVATE_NETWORKS": "false",
                # Neutralise the production .env: a leftover upstream auth
                # handshake would be dialled through the mock transport.
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
            timeout=30,
            check=False,
        )
        if result.returncode:
            raise AssertionError(result.stderr or result.stdout)


class MappingCronTests(unittest.TestCase):
    def test_external_is_called_first_and_forwarded_verbatim_to_internal(self):
        run_isolated(
            """
            async def check():
                await seed_mapping()
                calls = []

                async def handler(request):
                    calls.append(
                        (
                            str(request.url),
                            json.loads(request.content or b"{}"),
                            {name.lower(): value for name, value in request.headers.items()},
                        )
                    )
                    if str(request.url).startswith(EXTERNAL_URL):
                        return httpx.Response(200, content=b'{"ref_no": "EXT-9", "status": "PAID"}', request=request)
                    return httpx.Response(200, content=b'{"received": true}', request=request)

                await create_job()
                reset_statements()
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    scheduler_service._http_client = client
                    run = await scheduler_service.execute_scheduled_job(
                        "mapped-job", INTERNAL_URL, "POST"
                    )

                # The external API is dialled first and receives the cron
                # values renamed to the external field names.
                assert len(calls) == 2, calls
                assert calls[0][0] == EXTERNAL_URL, calls
                assert calls[0][1] == {"ref_no": "REF-1", "status": "OPEN"}, calls
                # The cron job's own API key belongs to the internal target and
                # must not be forwarded to the external API.
                assert "x-api-key" not in calls[0][2], calls[0][2]

                # The internal API receives the external payload unchanged,
                # together with the cron job's configured credential.
                assert calls[1][0] == INTERNAL_URL, calls
                assert calls[1][1] == {"ref_no": "EXT-9", "status": "PAID"}, calls
                assert calls[1][2].get("x-api-key") == "secret", calls[1][2]

                assert run.success and run.status_code == 200, (run.status_code, run.error)
                assert run.error is None

                envelope = json.loads(run.response_body)
                assert envelope["kind"] == mapping_job_service.MAPPING_RUN_KIND
                assert envelope["mapping"]["endpoint_code"] == "EP-TEST0001"
                assert envelope["external"]["status_code"] == 200
                assert envelope["external"]["body"] == {"ref_no": "EXT-9", "status": "PAID"}
                assert envelope["internal"]["status_code"] == 200
                assert envelope["internal"]["body"] == '{"received": true}'

                # The run row describes the delivery that was scheduled.
                sent = scheduler_service.load_headers(run.request_headers)
                assert sent is not None
                assert {name.lower() for name in sent} >= {"x-api-key"}, sent

            await check()
            """
        )

    def test_relative_internal_url_is_expanded_against_the_mapper_base(self):
        run_isolated(
            """
            async def check():
                from backend.core.config import settings

                settings.MAPPER_BASE_URL = "https://internal.test"
                async with AsyncSessionLocal() as db:
                    endpoint = ApiEndpoint(
                        endpoint_code="EP-REL00001",
                        source_api_url=EXTERNAL_URL,
                        target_api_url="/ref_crp_beneficiary",
                        method="POST",
                        is_active=True,
                    )
                    db.add(endpoint)
                    await db.commit()

                calls = []

                async def handler(request):
                    calls.append(str(request.url))
                    return httpx.Response(200, content=b'{"ok": true}', request=request)

                await create_job(url="/ref_crp_beneficiary")
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    scheduler_service._http_client = client
                    run = await scheduler_service.execute_scheduled_job(
                        "mapped-job", "/ref_crp_beneficiary", "POST"
                    )

                assert run.success, run.error
                assert calls[0] == EXTERNAL_URL, calls
                assert calls[1] == "https://internal.test/ref_crp_beneficiary", calls

                envelope = json.loads(run.response_body)
                assert (
                    envelope["internal"]["url"]
                    == "https://internal.test/ref_crp_beneficiary"
                ), envelope["internal"]

            await check()
            """
        )

    def test_mapping_tables_are_only_ever_selected(self):
        run_isolated(
            """
            async def check():
                await seed_mapping()

                async def handler(request):
                    return httpx.Response(200, content=b"{}", request=request)

                await create_job()
                reset_statements()
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    scheduler_service._http_client = client
                    run = await scheduler_service.execute_scheduled_job(
                        "mapped-job", INTERNAL_URL, "POST"
                    )
                assert run.success

                offending = writes()
                assert not offending, offending
                assert "SELECT" in STATEMENTS

            await check()
            """
        )

    def test_failing_external_api_skips_the_internal_delivery(self):
        run_isolated(
            """
            async def check():
                await seed_mapping()
                calls = []

                async def handler(request):
                    calls.append(str(request.url))
                    return httpx.Response(503, content=b'{"error": "down"}', request=request)

                await create_job()
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    scheduler_service._http_client = client
                    run = await scheduler_service.execute_scheduled_job(
                        "mapped-job", INTERNAL_URL, "POST"
                    )

                # Only the external API was touched.
                assert calls == [EXTERNAL_URL], calls
                assert not run.success
                assert run.status_code == 503
                assert "External API call failed" in run.error, run.error

                envelope = json.loads(run.response_body)
                assert envelope["internal"] is None
                assert envelope["external"]["status_code"] == 503

            await check()
            """
        )

    def test_rejected_internal_delivery_fails_the_run(self):
        run_isolated(
            """
            async def check():
                await seed_mapping()

                async def handler(request):
                    if str(request.url).startswith(EXTERNAL_URL):
                        return httpx.Response(200, content=b'{"ref_no": "EXT-9"}', request=request)
                    return httpx.Response(500, content=b"boom", request=request)

                await create_job()
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    scheduler_service._http_client = client
                    run = await scheduler_service.execute_scheduled_job(
                        "mapped-job", INTERNAL_URL, "POST"
                    )

                assert not run.success
                assert run.status_code == 500
                assert run.error == "HTTP 500", run.error

            await check()
            """
        )

    def test_internal_401_is_retried_once_with_a_fresh_token(self):
        run_isolated(
            """
            async def check():
                await seed_mapping()
                internal_calls = []

                async def handler(request):
                    if str(request.url).startswith(EXTERNAL_URL):
                        return httpx.Response(200, content=b'{"ref_no": "EXT-9"}', request=request)
                    internal_calls.append(request.headers.get("authorization"))
                    if len(internal_calls) == 1:
                        return httpx.Response(
                            401,
                            content=b'{"detail": "Unauthorized: Invalid or missing token"}',
                            request=request,
                        )
                    return httpx.Response(200, content=b'{"ok": true}', request=request)

                async def fake_auth(headers, client, url=None):
                    headers["Authorization"] = "Bearer retry-me"
                    return True

                mapping_job_service.apply_upstream_auth = fake_auth
                scheduler_service.apply_upstream_auth = fake_auth

                await create_job()
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    scheduler_service._http_client = client
                    run = await scheduler_service.execute_scheduled_job(
                        "mapped-job", INTERNAL_URL, "POST"
                    )

                assert internal_calls == ["Bearer retry-me", "Bearer retry-me"], internal_calls
                assert run.success and run.status_code == 200, (run.status_code, run.error)
                assert run.error is None

            await check()
            """
        )

    def test_scheduled_run_is_mirrored_into_api_call_log(self):
        run_isolated(
            """
            async def check():
                endpoint_id = await seed_mapping()

                async def handler(request):
                    if str(request.url).startswith(EXTERNAL_URL):
                        return httpx.Response(200, content=b'{"ref_no": "EXT-9"}', request=request)
                    return httpx.Response(
                        401,
                        content=b'{"detail": "Unauthorized: Invalid or missing token"}',
                        request=request,
                    )

                await create_job()
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    scheduler_service._http_client = client
                    run = await scheduler_service.execute_scheduled_job(
                        "mapped-job", INTERNAL_URL, "POST"
                    )
                assert not run.success and run.status_code == 401, (run.status_code, run.error)

                async with AsyncSessionLocal() as db:
                    rows = list((await db.execute(select(ApiCallLog))).scalars().all())

                assert len(rows) == 1, rows
                row = rows[0]
                assert row.endpoint_id == endpoint_id, (row.endpoint_id, endpoint_id)
                assert row.client_status_code == 401
                assert row.upstream_status_code == 200
                assert row.status == "FAILED"
                assert row.error_message == "HTTP 401"
                assert row.source_request_payload == {"ref_no": "EXT-9"}
                assert row.target_request_payload == {
                    "ref_no": "REF-1",
                    "status": "OPEN",
                }
                assert row.source_response["detail"] == "Unauthorized: Invalid or missing token"
                assert row.target_response == {"ref_no": "EXT-9"}
                assert row.source_response_headers, row.source_response_headers
                assert row.target_response_headers, row.target_response_headers

            await check()
            """
        )

    def test_unmapped_url_keeps_the_plain_single_request_behaviour(self):
        run_isolated(
            """
            async def check():
                await seed_mapping()
                calls = []

                async def handler(request):
                    calls.append(str(request.url))
                    return httpx.Response(204, request=request)

                await create_job(url="https://manual.test/health", method="GET", body=None)
                reset_statements()
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    scheduler_service._http_client = client
                    run = await scheduler_service.execute_scheduled_job(
                        "mapped-job", "https://manual.test/health", "GET"
                    )

                # No mapping matched, so the URL was called directly and the
                # stored body is returned verbatim rather than enveloped.
                assert calls == ["https://manual.test/health"], calls
                assert run.success and run.status_code == 204
                assert run.response_body is None
                assert not writes(), writes()

            await check()
            """
        )

    def test_inactive_mapping_is_not_picked_up(self):
        run_isolated(
            """
            async def check():
                await seed_mapping(active=False)
                endpoint = await mapping_job_service.resolve_endpoint(
                    INTERNAL_URL, "POST"
                )
                assert endpoint is None
                assert not await scheduler_service.is_mapping_backed(
                    INTERNAL_URL, "POST"
                )
                assert await mapping_job_service.list_routes() == []

                await drop_mappings()
                await seed_mapping()
                route = (await mapping_job_service.list_routes())[0]
                assert route.endpoint_code == "EP-TEST0001"
                assert route.internal_url == INTERNAL_URL
                assert route.external_url == EXTERNAL_URL
                assert route.parameter_count == 2
                assert await scheduler_service.is_mapping_backed(INTERNAL_URL, "POST")

            await check()
            """
        )

    def test_internal_delivery_is_authenticated_and_token_is_redacted(self):
        run_isolated(
            """
            async def check():
                from backend.core.config import settings

                settings.UPSTREAM_AUTH_URL = "https://auth.test/login"
                settings.UPSTREAM_AUTH_EMAIL = "svc@example.test"
                settings.UPSTREAM_AUTH_PASSWORD = "hunter2"
                await seed_mapping()
                delivered_headers = []

                async def handler(request):
                    if str(request.url) == "https://auth.test/login":
                        return httpx.Response(
                            200,
                            content=b'{"access_token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghijklmnop"}',
                            request=request,
                        )
                    delivered_headers.append(dict(request.headers))
                    return httpx.Response(200, content=b"{}", request=request)

                await create_job()
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    scheduler_service._http_client = client
                    run = await scheduler_service.execute_scheduled_job(
                        "mapped-job", INTERNAL_URL, "POST"
                    )
                assert run.success, run.error

                # Every outbound call is authenticated: the internal (target)
                # API receives the same service-account bearer the gateway
                # uses for its upstream calls.
                internal_headers = {
                    name.lower(): value
                    for name, value in delivered_headers[-1].items()
                }
                assert internal_headers.get("authorization", "").startswith(
                    "Bearer "
                ), internal_headers
                assert "hunter2" not in str(internal_headers), internal_headers

                # And the credential is redacted out of the stored run.
                assert "hunter2" not in (run.response_body or "")
                assert "eyJhbGciOiJIUzI1NiJ9" not in (run.response_body or "")
                stored = scheduler_service.load_headers(run.request_headers)
                assert stored is not None

            await check()
            """
        )

    def test_run_body_never_leaks_the_mapping_database_credentials(self):
        run_isolated(
            """
            async def check():
                async with AsyncSessionLocal() as db:
                    endpoint = ApiEndpoint(
                        endpoint_code="EP-SECRET1",
                        source_api_url=EXTERNAL_URL,
                        target_api_url=INTERNAL_URL,
                        method="POST",
                        api_id="svc-account",
                        api_password="super-secret-value",
                        is_active=True,
                    )
                    db.add(endpoint)
                    await db.commit()

                async def handler(request):
                    return httpx.Response(200, content=b"{}", request=request)

                await create_job()
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    scheduler_service._http_client = client
                    run = await scheduler_service.execute_scheduled_job(
                        "mapped-job", INTERNAL_URL, "POST"
                    )

                assert run.success
                assert "super-secret-value" not in (run.response_body or "")
                assert "svc-account" not in (run.response_body or "")

            await check()
            """
        )
