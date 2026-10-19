from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
import httpx

from backend.api.deps import bearer_scheme
from backend.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RefreshResponse,
)
from backend.services.central_auth import (
    CentralAuthError,
    central_login,
    central_logout,
    central_refresh,
)
from backend.services.http_client import get_http_client

__all__ = ["router"]

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _user_payload(user) -> dict:
    return {
        "id": user.id,
        "user_name": user.user_name,
        "email": user.email,
        "roles": user.roles,
        "is_super_admin": user.is_super_admin,
        "permissions": user.permissions,
        "programs": user.programs,
    }


def _retry_after_header(exc: CentralAuthError) -> dict[str, str] | None:
    retry_after = getattr(exc, "retry_after", None)
    return {"Retry-After": str(retry_after)} if retry_after else None


def _login_error(exc: CentralAuthError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=LoginResponse(success=False, message=exc.message).model_dump(),
        headers=_retry_after_header(exc),
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    http_request: Request,
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> LoginResponse | JSONResponse:
    """Exchange plain credentials for centralized access/refresh tokens."""
    try:
        session = await central_login(
            http_client,
            request.email,
            request.password,
            ip_address=http_request.client.host if http_request.client else None,
        )
    except CentralAuthError as exc:
        return _login_error(exc)

    return LoginResponse(
        success=True,
        message="Login successful",
        token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=session.expires_in,
        email=session.user.email,
        user=_user_payload(session.user),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    request: RefreshRequest,
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> RefreshResponse | JSONResponse:
    """Refresh a central access token using the stored refresh token."""
    try:
        tokens = await central_refresh(http_client, request.refresh_token)
    except CentralAuthError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content=RefreshResponse(success=False, message=exc.message).model_dump(),
            headers=_retry_after_header(exc),
        )
    return RefreshResponse(
        success=True,
        message="Access token refreshed successfully",
        token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> dict[str, str | bool]:
    """Revoke the central token when possible; local logout is always safe."""
    if credentials is not None and credentials.credentials:
        await central_logout(http_client, credentials.credentials)
    return {"success": True, "message": "Logged out successfully"}
