import pytest
import pytest_asyncio
import httpx
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import select

from backend.db.base import Base
from backend.models.endpoint import ApiEndpoint
from backend.models.scheduled_job import ScheduledJob, SchedulerBase
from backend.services import mapping_job_service, scheduler_service


@pytest_asyncio.fixture
async def test_dbs():
    app_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    sched_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    async with app_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=[ApiEndpoint.__table__]))

    async with sched_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: SchedulerBase.metadata.create_all(sync_conn))

    app_maker = async_sessionmaker(bind=app_engine, class_=AsyncSession, expire_on_commit=False)
    sched_maker = async_sessionmaker(bind=sched_engine, class_=AsyncSession, expire_on_commit=False)

    async with app_maker() as app_session, sched_maker() as sched_session:
        yield app_session, sched_session

    await app_engine.dispose()
    await sched_engine.dispose()


@pytest.mark.asyncio
async def test_inactive_mapping_detection_and_skip(test_dbs):
    app_db, sched_db = test_dbs

    # 1. Seed inactive endpoint in app DB
    endpoint = ApiEndpoint(
        endpoint_code="EP_TEST_INACTIVE",
        source_api_url="https://upstream.example.com/api/v1/resource",
        target_api_url="/api/v1/internal/inactive-endpoint",
        method="POST",
        is_active=False,
    )
    app_db.add(endpoint)
    await app_db.commit()

    # 2. Test check_mapping_active with session passed
    status = await mapping_job_service.check_mapping_active(
        "/api/v1/internal/inactive-endpoint", "POST", db=app_db
    )
    assert status.is_mapping is True
    assert status.is_active is False
    assert status.endpoint_code == "EP_TEST_INACTIVE"

    # Also test matching with full URL
    status_full = await mapping_job_service.check_mapping_active(
        "http://localhost:8000/api/v1/internal/inactive-endpoint?debug=1", "POST", db=app_db
    )
    assert status_full.is_mapping is True
    assert status_full.is_active is False

    # 3. Create scheduled job bound to this inactive endpoint
    job = ScheduledJob(
        job_id="test-inactive-job",
        name="Test Inactive Job",
        url="/api/v1/internal/inactive-endpoint",
        method="POST",
        interval_seconds=60,
        enabled=True,
    )
    sched_db.add(job)
    await sched_db.commit()

    # 4. run_job_now must raise SchedulerMappingInactiveError when mapping is inactive
    orig_check = mapping_job_service.check_mapping_active
    orig_fetch = scheduler_service._fetch_job

    async def patched_check(url, method, db=None):
        return await orig_check(url, method, db=db or app_db)

    async def patched_fetch(db, job_id):
        if job_id == "test-inactive-job":
            return job
        return await orig_fetch(db, job_id)

    mapping_job_service.check_mapping_active = patched_check
    scheduler_service._fetch_job = patched_fetch
    try:
        with pytest.raises(scheduler_service.SchedulerMappingInactiveError) as exc_info:
            await scheduler_service.run_job_now(sched_db, "test-inactive-job")
        assert "EP_TEST_INACTIVE" in str(exc_info.value)
        assert "inactive" in str(exc_info.value).lower()

        # 5. execute_scheduled_job (background APScheduler execution) must skip and NOT make HTTP calls
        calls = []

        async def handler(request):
            calls.append(str(request.url))
            return httpx.Response(200, content=b'{"ok": true}', request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scheduler_service._http_client = client
            run = await scheduler_service.execute_scheduled_job(
                "test-inactive-job", "/api/v1/internal/inactive-endpoint", "POST"
            )

        # Asserts: No HTTP calls were made at all!
        assert len(calls) == 0
        assert run.success is False
        assert "inactive" in str(run.error).lower()
        assert "EP_TEST_INACTIVE" in str(run.error)
    finally:
        mapping_job_service.check_mapping_active = orig_check
        scheduler_service._fetch_job = orig_fetch
