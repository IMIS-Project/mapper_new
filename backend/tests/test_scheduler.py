import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_isolated(body: str, prepare: str = "") -> None:
    with tempfile.TemporaryDirectory(prefix="mapper-scheduler-test-") as directory:
        env = os.environ.copy()
        env.update(
            {
                "JWT_SECRET": "scheduler-test",
                "ENCRYPTION_KEY": "scheduler-test",
                "AUTH_BASE_URL": "https://auth.test",
                "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
                "SCHEDULER_DATABASE_PATH": str(Path(directory) / "scheduler.db"),
                "SCHEDULER_ALLOWED_HOSTS": "example.test",
                # Keep these tests offline: the host has no auth service.
                "UPSTREAM_AUTH_URL": "",
                "UPSTREAM_AUTH_EMAIL": "",
                "UPSTREAM_AUTH_PASSWORD": "",
                "UPSTREAM_API_TOKENS": "",
            }
        )
        script = textwrap.dedent(
            """
            import asyncio
            import httpx
            from sqlalchemy import select
            from backend.db.scheduler_session import SchedulerSessionLocal, create_scheduler_tables, dispose_scheduler_engine
            from backend.models.scheduled_job import ScheduledJob, ScheduledJobRun
            from backend.schemas.scheduled_job import ScheduledJobCreate
            from backend.services import scheduler_service

            async def seed_job(job_id):
                async with SchedulerSessionLocal() as db:
                    db.add(
                        ScheduledJob(
                            job_id=job_id,
                            url="https://example.test/health",
                            method="GET",
                            enabled=True,
                        )
                    )
                    await db.commit()

            async def main():
                await create_scheduler_tables()
                try:
                    for job_id in ("test-job", "failed-job", "redirect-job"):
                        await seed_job(job_id)
                    interval = scheduler_service.build_trigger(interval_seconds=15)
                    cron = scheduler_service.build_trigger(cron="*/5 * * * *")
                    assert interval.interval.total_seconds() == 15
                    assert cron.fields[6].name == "minute"

                    async def success_handler(request):
                        assert request.url.host == "example.test"
                        assert request.headers["host"] == "example.test"
                        return httpx.Response(204, request=request)

                    async with httpx.AsyncClient(transport=httpx.MockTransport(success_handler)) as client:
                        scheduler_service._http_client = client
                        run = await scheduler_service.execute_scheduled_job(
                            "test-job", "https://example.test/health", "GET"
                        )
                    assert run.status_code == 204 and run.success
                    assert run.response_body is None and run.response_size == 0

                    async def failure_handler(request):
                        raise httpx.ConnectError("connection refused", request=request)

                    async with httpx.AsyncClient(transport=httpx.MockTransport(failure_handler)) as client:
                        scheduler_service._http_client = client
                        failed = await scheduler_service.execute_scheduled_job(
                            "failed-job", "https://example.test/health", "GET"
                        )
                    assert failed.status_code is None and not failed.success

                    async def redirect_handler(request):
                        return httpx.Response(302, headers={"location": "http://127.0.0.1"}, request=request)

                    async with httpx.AsyncClient(transport=httpx.MockTransport(redirect_handler)) as client:
                        scheduler_service._http_client = client
                        redirected = await scheduler_service.execute_scheduled_job(
                            "redirect-job", "https://example.test/health", "GET"
                        )
                    assert redirected.status_code == 302 and not redirected.success
                    assert redirected.error == "Redirect responses are not followed"

                    async with SchedulerSessionLocal() as db:
                        rows = list((await db.execute(select(ScheduledJobRun))).scalars().all())
                    assert {row.job_id for row in rows} == {"test-job", "failed-job", "redirect-job"}
                    assert next(row for row in rows if row.job_id == "failed-job").error == "Request failed"
                finally:
                    await dispose_scheduler_engine()
                    scheduler_service._http_client = None

            asyncio.run(main())
            """
        )
        script = prepare + "\n" + script + "\n" + textwrap.dedent(body)
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if result.returncode:
            raise AssertionError(result.stderr or result.stdout)


class SchedulerIntegrationTests(unittest.TestCase):
    def test_scheduler_uses_temporary_sqlite_and_persists_runs(self):
        run_isolated("")

    def test_disabled_and_missing_jobs_never_hit_the_network(self):
        run_isolated(
            """
            import asyncio

            async def check():
                async with SchedulerSessionLocal() as db:
                    db.add(
                        ScheduledJob(
                            job_id="disabled-job",
                            url="https://example.test/health",
                            method="GET",
                            enabled=False,
                        )
                    )
                    db.add(
                        ScheduledJob(
                            job_id="toggle-job",
                            url="https://example.test/health",
                            method="GET",
                            enabled=True,
                        )
                    )
                    await db.commit()

                calls = []

                async def handler(request):
                    calls.append(str(request.url))
                    return httpx.Response(200, request=request)

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as client:
                    scheduler_service._http_client = client
                    enabled = await scheduler_service.execute_scheduled_job(
                        "toggle-job", "https://example.test/health", "GET"
                    )
                    assert enabled.success, enabled.error
                    assert calls == ["https://example.test/health"], calls

                    # The next tick must re-read the row, not trust the
                    # APScheduler entry that was live when the job started.
                    async with SchedulerSessionLocal() as db:
                        row = await db.get(ScheduledJob, "toggle-job")
                        row.enabled = False
                        await db.commit()

                    toggled = await scheduler_service.execute_scheduled_job(
                        "toggle-job", "https://example.test/health", "GET"
                    )
                    disabled = await scheduler_service.execute_scheduled_job(
                        "disabled-job", "https://example.test/health", "GET"
                    )
                    missing = await scheduler_service.execute_scheduled_job(
                        "missing-job", "https://example.test/health", "GET"
                    )

                assert calls == ["https://example.test/health"], calls
                assert toggled.error == "Scheduled job is disabled", toggled.error
                assert toggled.success is False and toggled.id is None
                assert disabled.error == "Scheduled job is disabled", disabled.error
                assert disabled.success is False and disabled.id is None
                assert missing.error == "Scheduled job not found", missing.error
                assert missing.success is False and missing.id is None

                async with SchedulerSessionLocal() as db:
                    rows = list(
                        (
                            await db.execute(
                                select(ScheduledJobRun).where(
                                    ScheduledJobRun.job_id.in_(
                                        ("disabled-job", "missing-job")
                                    )
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                assert rows == [], rows

            asyncio.run(check())
            """
        )

    def test_existing_cron_job_can_be_edited(self):
        run_isolated(
            """
            import asyncio
            from backend.schemas.scheduled_job import ScheduledJobUpdate

            async def check():
                async with SchedulerSessionLocal() as db:
                    db.add(
                        ScheduledJob(
                            job_id="edit-job",
                            name="Original",
                            url="https://example.test/health",
                            method="GET",
                            interval_seconds=60,
                            enabled=True,
                        )
                    )
                    await db.commit()

                async with SchedulerSessionLocal() as db:
                    updated = await scheduler_service.update_job(
                        db,
                        "edit-job",
                        ScheduledJobUpdate(
                            name="Renamed",
                            url="https://example.test/other",
                            method="POST",
                            cron="*/2 * * * *",
                            headers={"X-Api-Key": "secret"},
                            body='{"a": 1}',
                        ),
                    )
                    assert updated.name == "Renamed"
                    assert updated.url == "https://example.test/other"
                    assert updated.method == "POST"
                    assert updated.cron == "*/2 * * * *"
                    # A cron expression replaces the stored interval.
                    assert updated.interval_seconds is None
                    assert scheduler_service.load_headers(updated.headers) == {
                        "X-Api-Key": "secret"
                    }
                    assert updated.body == '{"a": 1}'

                async with SchedulerSessionLocal() as db:
                    stored = await scheduler_service._fetch_job(db, "edit-job")
                assert stored.cron == "*/2 * * * *"
                assert stored.interval_seconds is None
                assert stored.url == "https://example.test/other"

                # Switching back to an interval drops the cron expression.
                async with SchedulerSessionLocal() as db:
                    switched = await scheduler_service.update_job(
                        db, "edit-job", ScheduledJobUpdate(interval_seconds=30)
                    )
                assert switched.interval_seconds == 30
                assert switched.cron is None
                assert switched.url == "https://example.test/other"

                # The headers and the body can be cleared.
                async with SchedulerSessionLocal() as db:
                    cleared = await scheduler_service.update_job(
                        db,
                        "edit-job",
                        ScheduledJobUpdate(headers=None, body=None, name=None),
                    )
                assert cleared.headers is None and cleared.body is None
                assert cleared.name is None

                # A body on a method that cannot carry one is rejected and
                # leaves the stored job untouched.
                async with SchedulerSessionLocal() as db:
                    try:
                        await scheduler_service.update_job(
                            db,
                            "edit-job",
                            ScheduledJobUpdate(method="GET", body='{"a": 1}'),
                        )
                    except ValueError:
                        pass
                    else:
                        raise AssertionError("a body on GET was accepted")
                async with SchedulerSessionLocal() as db:
                    stored = await scheduler_service._fetch_job(db, "edit-job")
                assert stored.method == "POST"
                assert stored.body is None

                # A missing job is reported, never created.
                async with SchedulerSessionLocal() as db:
                    try:
                        await scheduler_service.update_job(
                            db, "missing-job", ScheduledJobUpdate(name="x")
                        )
                    except scheduler_service.SchedulerNotFoundError:
                        pass
                    else:
                        raise AssertionError("a missing job was updated")

            asyncio.run(check())
            """
        )

    def test_scheduler_payload_validation_rejects_invalid_inputs(self):
        run_isolated(
            """
            from pydantic import ValidationError
            from backend.services.scheduler_security import (
                UnsafeDestinationError,
                validate_destination,
            )
            try:
                ScheduledJobCreate(url="https://example.test")
            except ValidationError:
                pass
            else:
                raise AssertionError("missing schedule was accepted")
            try:
                ScheduledJobCreate(
                    url="https://user:password@example.test", interval_seconds=5
                )
            except ValidationError:
                pass
            else:
                raise AssertionError("credential URL was accepted")
            try:
                validate_destination("http://127.0.0.1/health")
            except UnsafeDestinationError:
                pass
            else:
                raise AssertionError("loopback destination was accepted")
            """
        )

    def test_scheduler_payload_validation_normalisation(self):
        run_isolated(
            """
            from pydantic import ValidationError

            def rejected(**kwargs):
                try:
                    ScheduledJobCreate(**kwargs)
                except ValidationError:
                    return
                raise AssertionError(f"invalid payload accepted: {kwargs}")

            base = {"url": "https://example.test", "interval_seconds": 60}

            # A body is meaningless for GET, and headers must stay safe.
            rejected(**base, method="GET", body='{"a":1}')
            rejected(**base, method="HEAD", body="x")
            rejected(**base, headers={"Host": "evil.test"})
            rejected(**base, headers={"Content-Length": "10"})
            rejected(**base, headers={"X-Bad": "a\\r\\nInjected: yes"})
            rejected(**base, headers={"Bad Name": "x"})
            rejected(**base, headers={"X-Api-Key": {"nested": 1}})

            # A valid POST with headers and a body is accepted as given.
            created = ScheduledJobCreate(
                url="https://example.test",
                method="post",
                interval_seconds=60,
                headers={"X-Api-Key": "secret", "Accept": "application/json"},
                body='{"a":1}',
            )
            assert created.method == "POST"
            assert created.headers == {
                "X-Api-Key": "secret",
                "Accept": "application/json",
            }
            assert created.body == '{"a":1}'

            # Empty header maps and bodies normalise away instead of storing "".
            empty = ScheduledJobCreate(
                url="https://example.test", interval_seconds=60, headers={}, body=""
            )
            assert empty.headers is None and empty.body is None

            assert scheduler_service.guess_content_type('{"a":1}') == "application/json"
            assert scheduler_service.guess_content_type("<a/>") == "application/xml"
            assert scheduler_service.guess_content_type("hi") == "text/plain; charset=utf-8"
            assert scheduler_service.load_headers(None) is None
            assert scheduler_service.load_headers("not json") is None
            assert scheduler_service.load_headers(
                scheduler_service.dump_headers({"A": "b"})
            ) == {"A": "b"}
            assert scheduler_service.dump_headers(None) is None
            """
        )

    def test_scheduler_payload_validation_accepts_relative_paths(self):
        run_isolated(
            """
            from pydantic import ValidationError

            created = ScheduledJobCreate(url="v1/audio/list", interval_seconds=60)
            assert created.url == "/v1/audio/list", created.url

            queried = ScheduledJobCreate(
                url="/v1/audio/play?file=call-1.mp3", interval_seconds=60
            )
            assert queried.url == "/v1/audio/play?file=call-1.mp3", queried.url

            for bad in ("", "?x=1", "/v1/audio/list#frag", "//host/path"):
                try:
                    ScheduledJobCreate(url=bad, interval_seconds=60)
                except ValidationError:
                    pass
                else:
                    raise AssertionError(f"invalid relative URL accepted: {bad!r}")
            """
        )

    def test_mapping_job_payload_includes_query_string(self):
        run_isolated(
            """
            from backend.services.mapping_job_service import _request_payload

            assert _request_payload(None, "/v1/audio/play?file=a.mp3") == {
                "file": "a.mp3"
            }
            # An explicit body value wins over the URL default.
            assert _request_payload(
                '{"file": "b.mp3"}', "/v1/audio/play?file=a.mp3"
            ) == {"file": "b.mp3"}
            assert _request_payload(None, None) == {}
            """
        )

    def test_run_timestamps_are_serialised_as_system_local(self):
        run_isolated(
            """
            import json
            from datetime import datetime, timedelta, timezone
            from backend.core.clock import local_zone
            from backend.schemas.scheduled_job import ScheduledJobRunSummary

            def summary(ran_at):
                return ScheduledJobRunSummary(
                    id=1, job_id="j", url="https://example.test", method="GET",
                    status_code=200, success=True, duration_ms=1, error=None,
                    ran_at=ran_at,
                )

            # SQLite hands back the naive system-local wall clock. The API adds
            # the system offset so clients can both sort correctly and display
            # the mapper host's local time.
            naive = datetime(2026, 9, 28, 7, 53, 19, 911501)
            emitted = json.loads(summary(naive).model_dump_json())["ran_at"]
            assert emitted.startswith("2026-09-28T07:53:19.911501"), emitted
            assert summary(naive).ran_at == naive.replace(tzinfo=local_zone())

            # An already-aware value is converted to the system timezone, not
            # reinterpreted as local.
            offset = datetime(2026, 9, 28, 12, 53, 19, tzinfo=timezone(timedelta(hours=5)))
            converted = summary(offset).ran_at
            assert converted == offset.astimezone(local_zone())

            # Seconds survive the round trip, so the UI can show them.
            assert ".911501" in emitted
            """
        )

    def test_scheduler_sends_body_and_captures_response(self):
        run_isolated(
            """
            import asyncio

            async def check():
                captured = {}

                async def handler(request):
                    captured["content"] = request.content
                    captured["headers"] = dict(request.headers)
                    return httpx.Response(
                        201,
                        content=b'{"ok": true}',
                        headers={"x-custom": "abc"},
                        request=request,
                    )

                payload = ScheduledJobCreate(
                    url="https://example.test/jobs",
                    method="POST",
                    interval_seconds=60,
                    headers={"X-Api-Key": "secret"},
                    body='{"hello": "world"}',
                )
                async with SchedulerSessionLocal() as db:
                    row = ScheduledJob(
                        job_id=payload.job_id,
                        name=payload.name,
                        url=payload.url,
                        method=payload.method,
                        headers=scheduler_service.dump_headers(payload.headers),
                        body=payload.body,
                        cron=payload.cron,
                        interval_seconds=payload.interval_seconds,
                        enabled=True,
                        created_by=None,
                    )
                    db.add(row)
                    await db.commit()

                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    scheduler_service._http_client = client
                    run = await scheduler_service.execute_scheduled_job(
                        row.job_id, row.url, row.method
                    )

                # The body and custom headers reached the server, and a
                # content type was inferred for them.
                assert captured["content"] == b'{"hello": "world"}'
                assert captured["headers"]["x-api-key"] == "secret"
                assert captured["headers"]["content-type"] == "application/json"

                assert run.status_code == 201 and run.success
                assert run.response_body == '{"ok": true}'
                assert run.response_size == 12 and not run.response_body_truncated
                assert (
                    scheduler_service.load_headers(run.response_headers)["x-custom"]
                    == "abc"
                )
                sent = scheduler_service.load_headers(run.request_headers)
                assert sent["X-Api-Key"] == "secret"
                assert sent["content-type"] == "application/json"

                # The detail route reads the same row back through the service.
                async with SchedulerSessionLocal() as db:
                    fetched = await scheduler_service.get_run(db, run.id)
                assert fetched is not None and fetched.response_body == run.response_body

                # Oversized responses are cut at the limit and flagged as such.
                async def big_handler(request):
                    return httpx.Response(200, content=b"x" * 200000, request=request)

                async with httpx.AsyncClient(transport=httpx.MockTransport(big_handler)) as client:
                    scheduler_service._http_client = client
                    large = await scheduler_service.execute_scheduled_job(
                        row.job_id, row.url, "GET"
                    )
                assert large.response_body_truncated
                assert len(large.response_body) == 65536
                assert large.response_size == 65536

            asyncio.run(check())
            """
        )

    def test_scheduler_migrates_pre_existing_database(self):
        legacy = textwrap.dedent(
            """
            import sqlite3
            from backend.core.config import settings

            connection = sqlite3.connect(settings.SCHEDULER_DATABASE_PATH)
            connection.executescript(
                "CREATE TABLE scheduled_jobs ("
                " job_id VARCHAR(255) NOT NULL, name VARCHAR(255), url TEXT NOT NULL,"
                " method VARCHAR(16) NOT NULL, cron VARCHAR(255), interval_seconds INTEGER,"
                " enabled BOOLEAN NOT NULL, created_by INTEGER, created_at DATETIME NOT NULL,"
                " updated_at DATETIME NOT NULL, PRIMARY KEY (job_id));"
                "CREATE TABLE scheduled_job_runs ("
                " id INTEGER NOT NULL, job_id VARCHAR(255) NOT NULL, url TEXT NOT NULL,"
                " method VARCHAR(16) NOT NULL, status_code INTEGER, success BOOLEAN NOT NULL,"
                " duration_ms INTEGER NOT NULL, error TEXT, ran_at DATETIME NOT NULL,"
                " PRIMARY KEY (id));"
                "INSERT INTO scheduled_jobs VALUES"
                " ('legacy', 'Legacy', 'https://example.test/health', 'GET', NULL, 60, 1,"
                "  NULL, '2024-01-01 00:00:00', '2024-01-01 00:00:00');"
            )
            connection.commit()
            connection.close()
            """
        )
        run_isolated(
            """
            import asyncio
            import sqlite3
            from backend.core.config import settings

            async def check():
                connection = sqlite3.connect(settings.SCHEDULER_DATABASE_PATH)
                job_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(scheduled_jobs)")
                }
                run_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(scheduled_job_runs)")
                }
                connection.close()

                assert {"headers", "body"} <= job_columns, job_columns
                assert {
                    "request_headers",
                    "response_headers",
                    "response_body",
                    "response_body_truncated",
                    "response_size",
                } <= run_columns, run_columns

                # The pre-existing row survives and stays readable by the service.
                async with SchedulerSessionLocal() as db:
                    row = await scheduler_service._fetch_job(db, "legacy")
                assert row is not None and row.method == "GET"
                assert row.headers is None and row.body is None

            asyncio.run(check())
            """,
            prepare=legacy,
        )
