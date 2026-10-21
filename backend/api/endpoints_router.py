from datetime import datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from backend.api.deps import get_current_active_user, get_db
from backend.models import (
    ParamTypeEnum,
    ParameterMapping,
    ProtocolEnum,
    WebhookEvent,
)
from backend.services.central_auth import CentralUser

User = CentralUser
from backend.schemas.common import SuccessResponse
from backend.schemas.endpoint import (
    CompleteMappingRequest,
    CompleteMappingResponse,
    EndpointCreate,
    EndpointResponse,
    EndpointUpdate,
    MappingItem,
)
from backend.schemas.parameter import ParameterCreate
from backend.services import endpoint_service, parameter_service
from backend.services.http_client import get_http_client
from backend.services.webhook_service import fire_event

__all__ = ["router"]

router = APIRouter(tags=["API Endpoints"])

_PARAM_TYPE_VALUES = {member.value for member in ParamTypeEnum}

# The mapper frontend edits ``QUERY``; older payloads (and the legacy DB
# column) spell the same location ``QUERYSTRING``. Accept every spelling.
_LEGACY_PARAM_TYPES = {
    "QUERYSTRING": ParamTypeEnum.QUERY.value,
    "QUERY_STRING": ParamTypeEnum.QUERY.value,
}


def _resolve_param_type(item: MappingItem) -> str:

    sent = item.model_fields_set
    candidates = [
        item.parameterTypeValue if "parameterTypeValue" in sent else None,
        item.parameterType if "parameterType" in sent else None,
        item.parameterType,
        item.parameterTypeValue,
    ]

    for candidate in candidates:
        normalized = (candidate or "").strip().upper()
        normalized = _LEGACY_PARAM_TYPES.get(normalized, normalized)
        if normalized in _PARAM_TYPE_VALUES:
            return normalized

    return ParamTypeEnum.BODY.value


def _enabled_rows(mappings: list[MappingItem]) -> list[MappingItem]:
    """Rows carrying an enabled, complete source -> target pair."""
    return [m for m in mappings if m.enabled and m.sourceField and m.targetField]


def _request_signature(mappings: list[MappingItem]) -> str:
    """Order-insensitive signature of the enabled mapping rows."""
    return "|".join(
        f"{m.sourceField}->{m.targetField}:{_resolve_param_type(m)}"
        for m in sorted(
            _enabled_rows(mappings),
            key=lambda m: m.sourceField,
        )
    )


def _stored_signature(parameters: list[ParameterMapping]) -> str:
    """Signature of persisted rows (mirrors :func:`_request_signature`)."""
    return "|".join(
        f"{p.source_parameter}->{p.target_parameter}:"
        f"{p.parameter_type or ParamTypeEnum.BODY.value}"
        for p in sorted(
            parameters,
            key=lambda p: p.source_parameter,
        )
    )


def _build_parameters(
    mappings: list[MappingItem],
) -> list[ParameterCreate]:
    """Convert the enabled mapping rows into ``ParameterCreate`` payloads."""
    return [
        ParameterCreate(
            source_parameter=item.sourceField,
            target_parameter=item.targetField,
            parameter_type=ParamTypeEnum(_resolve_param_type(item)),
        )
        for item in _enabled_rows(mappings)
    ]


def _generate_description(
    source: dict | None,
    target: dict | None,
    mappings: list[MappingItem],
) -> str:
    """Compose the auto-description stored alongside the endpoint."""
    parts: list[str] = []

    if source and source.get("name"):
        parts.append(f"Source: {source['name']}")

    if target and target.get("name"):
        parts.append(f"Target: {target['name']}")

    parts.append(f"Mapped: {len(_enabled_rows(mappings))} fields")
    parts.append(f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return " | ".join(parts)


def _normalize_method(value: str) -> str:
    """Upper-case the HTTP verb sent by the editor (blank => ``POST``)."""
    normalized = (value or "").strip().upper()
    return normalized or "POST"


_SFTP_CLEAR_FIELDS = {
    "sftp_host": None,
    "sftp_port": None,
    "sftp_username": None,
    "sftp_password": None,
    "sftp_private_key_path": None,
    "sftp_remote_path": None,
    "dynamic_filename_pattern": None,
}


def _text(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _transport_fields(
    payload: CompleteMappingRequest,
    *,
    for_update: bool = False,
) -> dict:
    """Map the request's transport settings onto ``api_endpoint`` columns.

    SFTP-backed mappings carry the same credential set the audio APIs use.
    When switching back to HTTP the stale SFTP columns are cleared. On an
    update an empty password means "keep the stored secret", matching the
    behaviour of the endpoint SFTP settings dialog.
    """
    protocol = payload.protocol or ProtocolEnum.HTTP
    if protocol is not ProtocolEnum.SFTP:
        return {"protocol": protocol.value, **_SFTP_CLEAR_FIELDS}

    fields = {
        "protocol": protocol.value,
        "sftp_host": _text(payload.sftp_host),
        "sftp_port": payload.sftp_port or 22,
        "sftp_username": _text(payload.sftp_username),
        "sftp_password": payload.sftp_password or None,
        "sftp_private_key_path": _text(payload.sftp_private_key_path),
        "sftp_remote_path": _text(payload.sftp_remote_path) or "/",
        "dynamic_filename_pattern": _text(payload.dynamic_filename_pattern),
    }
    if for_update and not fields["sftp_password"]:
        fields.pop("sftp_password")
    return fields


def _not_found(
    detail: str = "Endpoint not found",
) -> HTTPException:
    """Uniform 404 for missing endpoints/mappings."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=detail,
    )


@router.get(
    "/api-endpoints",
    response_model=list[EndpointResponse],
)
async def list_api_endpoints(
    search: str | None = Query(
        default=None,
        description="Substring match on code / source / target URL.",
    ),
    is_active: bool | None = Query(
        default=None,
        description="Filter on the enablement flag.",
    ),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_active_user),
) -> list[EndpointResponse]:
    """List registered endpoints, newest first (parameters included)."""
    return await endpoint_service.list_endpoints(
        db,
        skip=skip,
        limit=limit,
        search=search,
        is_active=is_active,
    )


@router.get(
    "/api-endpoints/{endpoint_id}",
    response_model=EndpointResponse,
)
async def get_api_endpoint(
    endpoint_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_active_user),
) -> EndpointResponse:
    """Fetch a single endpoint with its parameter mappings."""
    endpoint = await endpoint_service.get_endpoint(db, endpoint_id)

    if endpoint is None:
        raise _not_found()

    return endpoint


@router.post(
    "/api-endpoints",
    response_model=EndpointResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_endpoint(
    payload: EndpointCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EndpointResponse:

    data = payload.model_dump()

    if data.get("created_by") is None:
        data["created_by"] = current_user.id

    try:
        endpoint = await endpoint_service.create_endpoint(db, data)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An endpoint with this endpoint_code already exists",
        ) from exc

    return endpoint


@router.put(
    "/api-endpoints/{endpoint_id}",
    response_model=EndpointResponse,
)
@router.patch(
    "/api-endpoints/{endpoint_id}",
    response_model=EndpointResponse,
)
async def update_api_endpoint(
    endpoint_id: int,
    payload: EndpointUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EndpointResponse:

    data = payload.model_dump(exclude_unset=True)
    data["updated_by"] = current_user.id

    try:
        endpoint = await endpoint_service.update_endpoint(
            db,
            endpoint_id,
            data,
        )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An endpoint with this endpoint_code already exists",
        ) from exc

    if endpoint is None:
        raise _not_found()

    return endpoint


@router.delete(
    "/api-endpoints/{endpoint_id}",
    response_model=SuccessResponse,
)
async def delete_api_endpoint(
    endpoint_id: int,
    hard: bool = Query(
        default=False,
        description="Permanently remove the row instead of deactivating it.",
    ),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_active_user),
) -> SuccessResponse:
    """Soft-delete an endpoint (hard=true removes it permanently)."""
    removed = await endpoint_service.delete_endpoint(
        db,
        endpoint_id,
        hard=hard,
    )

    if not removed:
        raise _not_found()

    return SuccessResponse(
        success=True,
        message=(
            "Mapping permanently deleted"
            if hard
            else "Mapping soft deleted successfully"
        ),
    )


@router.put(
    "/api-endpoints/{endpoint_id}/toggle",
    response_model=EndpointResponse,
)
async def toggle_api_endpoint(
    endpoint_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_active_user),
) -> EndpointResponse:
    """Flip the endpoint's active flag and return the updated row."""
    endpoint = await endpoint_service.toggle_endpoint(db, endpoint_id)

    if endpoint is None:
        raise _not_found()

    return endpoint


@router.post(
    "/mappings/complete",
    response_model=CompleteMappingResponse,
)
async def save_complete_mapping(
    payload: CompleteMappingRequest,
    background_tasks: BackgroundTasks,
    http_client: httpx.AsyncClient = Depends(get_http_client),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> CompleteMappingResponse:

    method = _normalize_method(payload.targetMethod)

    existing = await endpoint_service.check_duplicate(
        db,
        payload.sourceUrl,
        payload.targetUrl,
        method,
    )

    if existing is not None:
        stored = await parameter_service.list_parameters(
            db,
            existing.id,
        )

        if _request_signature(payload.mappings) == _stored_signature(stored):
            return CompleteMappingResponse(
                success=True,
                warning=True,
                isDuplicate=True,
                apiEndpointId=existing.id,
                endpointCode=existing.endpoint_code or "",
                message=(
                    "A mapping with the same source URL, target URL, and "
                    "parameters already exists!"
                ),
                parameterCount=len(stored),
            )

        endpoint = await endpoint_service.update_endpoint(
            db,
            existing.id,
            {
                "source_api_url": payload.sourceUrl,
                "target_api_url": payload.targetUrl,
                "method": method,
                "description": _generate_description(
                    payload.source,
                    payload.target,
                    payload.mappings,
                ),
                "api_id": payload.api_id,
                "api_password": payload.api_password,
                "api_auth_url": payload.api_auth_url,
                **_transport_fields(payload, for_update=True),
                "updated_by": current_user.id,
            },
        )

        if endpoint is None:
            raise _not_found()

        await parameter_service.delete_all_parameters(
            db,
            existing.id,
        )

        message = "API mapping updated (parameters changed)"

    else:
        endpoint = await endpoint_service.create_endpoint(
            db,
            {
                "source_api_url": payload.sourceUrl,
                "target_api_url": payload.targetUrl,
                "method": method,
                "description": _generate_description(
                    payload.source,
                    payload.target,
                    payload.mappings,
                ),
                "api_id": payload.api_id,
                "api_password": payload.api_password,
                "api_auth_url": payload.api_auth_url,
                **_transport_fields(payload),
                "created_by": current_user.id,
            },
        )

        message = "New API mapping created"

        background_tasks.add_task(
            fire_event,
            db,
            http_client,
            WebhookEvent.ENDPOINT_CREATED.value,
            {
                "endpoint_id": str(endpoint.id),
                "endpoint_code": endpoint.endpoint_code,
                "source_api_url": payload.sourceUrl,
                "target_api_url": payload.targetUrl,
            },
            endpoint.id,
        )

    created = await parameter_service.bulk_create_parameters(
        db,
        endpoint.id,
        _build_parameters(payload.mappings),
    )

    return CompleteMappingResponse(
        success=True,
        apiEndpointId=endpoint.id,
        endpointCode=endpoint.endpoint_code or "",
        message=message,
        parameterCount=len(created),
    )


@router.put(
    "/mappings/complete/{endpoint_id}",
    response_model=CompleteMappingResponse,
)
async def update_complete_mapping(
    endpoint_id: int,
    payload: CompleteMappingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> CompleteMappingResponse:

    existing = await endpoint_service.get_endpoint(
        db,
        endpoint_id,
    )

    if existing is None:
        raise _not_found("Mapping not found")

    method = _normalize_method(payload.targetMethod)

    duplicate = await endpoint_service.check_duplicate(
        db,
        payload.sourceUrl,
        payload.targetUrl,
        method,
        exclude_id=endpoint_id,
    )

    if duplicate is not None:
        duplicate_params = await parameter_service.list_parameters(
            db,
            duplicate.id,
        )

        if _request_signature(payload.mappings) == _stored_signature(duplicate_params):
            return CompleteMappingResponse(
                success=True,
                warning=True,
                isDuplicate=True,
                apiEndpointId=duplicate.id,
                endpointCode=duplicate.endpoint_code or "",
                message=(
                    "Cannot update: A mapping with the same source URL, target "
                    "URL, and parameters already exists!"
                ),
                parameterCount=len(duplicate_params),
            )

    updated = await endpoint_service.update_endpoint(
        db,
        endpoint_id,
        {
            "source_api_url": payload.sourceUrl,
            "target_api_url": payload.targetUrl,
            "method": method,
            "description": _generate_description(
                payload.source,
                payload.target,
                payload.mappings,
            ),
            "api_id": payload.api_id,
            "api_password": payload.api_password,
            "api_auth_url": payload.api_auth_url,
            **_transport_fields(payload, for_update=True),
            "updated_by": current_user.id,
        },
    )

    if updated is None:
        raise _not_found("Mapping not found")

    await parameter_service.delete_all_parameters(
        db,
        endpoint_id,
    )

    created = await parameter_service.bulk_create_parameters(
        db,
        endpoint_id,
        _build_parameters(payload.mappings),
    )

    return CompleteMappingResponse(
        success=True,
        apiEndpointId=endpoint_id,
        endpointCode=updated.endpoint_code or "",
        message=f"API mapping updated with {len(created)} parameters",
        parameterCount=len(created),
    )
