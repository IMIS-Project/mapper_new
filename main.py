"""FastAPI application factory for the API Mapper & Gateway backend.

Run from the project root so the ``backend`` package and the root ``.env``
are picked up:

    uvicorn backend.main:app --reload
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.core.config import settings
from backend.core.redaction import mask_sensitive
from backend.db import schema_probe as audit_schema
from backend.services.http_client import create_http_client
from backend.services.scheduler_service import start_scheduler, stop_scheduler


from backend.api.auth import router as auth_router
from backend.api.bank_router import router as bank_router
from backend.api.endpoints_router import router as endpoints_router
from backend.api.export_import_router import router as export_import_router
from backend.api.gateway_router import router as gateway_router
from backend.api.gateway_proxy_router import router as gateway_proxy_router
from backend.api.health_router import router as health_router
from backend.api.logs_router import router as logs_router
from backend.api.mock_router import router as mock_router
from backend.api.parameters_router import router as parameters_router
from backend.api.sftp_router import router as sftp_router
from backend.api.scheduled_jobs_router import router as scheduled_jobs_router
from backend.api.webhook_router import router as webhook_router
from backend.api.env_vars_router import router as env_vars_router
from backend.api.workflows_router import router as workflows_router

from backend.middleware.rate_limit import RateLimitMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage process-wide resources."""
    app.state.http_client = create_http_client()
    try:
        try:
            from backend.db.session import engine
            from backend.db.base import Base
            from backend.models.workflow import Workflow, WorkflowStep, WorkflowRun
            from backend.models.env_var import ApiEnvVariable
            from backend.models.endpoint import ApiEndpoint
            from backend.models.parameter import ParameterMapping
            from backend.models.log import ApiCallLog
            from backend.models.user import User, Role, UserRole
            core_tables = [
                Workflow.__table__,
                WorkflowStep.__table__,
                WorkflowRun.__table__,
                ApiEnvVariable.__table__,
                ApiEndpoint.__table__,
                ParameterMapping.__table__,
                ApiCallLog.__table__,
                User.__table__,
                Role.__table__,
                UserRole.__table__,
            ]
            async with engine.begin() as conn:
                await conn.run_sync(
                    lambda sync_conn: Base.metadata.create_all(sync_conn, tables=core_tables)
                )
        except Exception:
            pass

        try:
            from backend.db.session import AsyncSessionLocal
            from backend.services.workflow_seed import seed_default_workflows
            async with AsyncSessionLocal() as session:
                await seed_default_workflows(session)
        except Exception:
            pass

        await audit_schema.warm()
        await start_scheduler(app.state.http_client)
        yield
    finally:
        await stop_scheduler()
        await app.state.http_client.aclose()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        title="API Mapper & Gateway",
        version="1.0.0",
        lifespan=lifespan,
        root_path=settings.APP_ROOT_PATH,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(RateLimitMiddleware)

    @app.exception_handler(RequestValidationError)
    async def redact_validation_errors(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Strip secrets from Pydantic validation errors.

        FastAPI quotes the offending input verbatim in ``detail[].input``,
        which is how a bearer token ended up in a 422 body. Redact before it
        reaches the caller or any log that records the response.
        """
        return JSONResponse(
            status_code=422,
            content={"detail": mask_sensitive(jsonable_encoder(exc.errors()))},
        )

    app.include_router(auth_router, prefix="/api")
    app.include_router(endpoints_router, prefix="/api")
    app.include_router(parameters_router, prefix="/api")
    app.include_router(gateway_router, prefix="/api")
    app.include_router(health_router, prefix="/api")
    app.include_router(logs_router, prefix="/api")
    app.include_router(sftp_router, prefix="/api")
    app.include_router(scheduled_jobs_router, prefix="/api")
    app.include_router(bank_router, prefix="/api")
    app.include_router(export_import_router, prefix="/api")
    app.include_router(mock_router, prefix="/api")
    app.include_router(webhook_router, prefix="/api")
    app.include_router(env_vars_router, prefix="/api")
    app.include_router(workflows_router, prefix="/api")
    app.include_router(workflows_router)

    @app.get("/", tags=["meta"])
    async def root() -> dict[str, str]:
        """Basic service metadata."""
        return {
            "name": "API Mapper & Gateway",
            "version": "1.0.0",
            "status": "ok",
        }

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "healthy"}

    # Legacy dynamic gateway ("/{path:path}") — registered last on purpose so
    # every concrete route above wins the match and only otherwise-unhandled
    # business requests fall through to endpoint resolution + proxy + logging.
    app.include_router(gateway_proxy_router)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.SERVER_HOST,
        port=int(settings.SERVER_PORT),
        reload=bool(settings.SERVER_RELOAD),
    )
