from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from backend.models.enums import ContentTypeEnum, MethodEnum, ProtocolEnum
from backend.schemas.parameter import ParameterResponse


class EndpointCreate(BaseModel):
    endpoint_code: str | None = None
    source_api_url: str
    target_api_url: str
    method: MethodEnum = MethodEnum.POST
    protocol: ProtocolEnum = ProtocolEnum.HTTP
    request_content_type: ContentTypeEnum = ContentTypeEnum.JSON
    require_authentication: bool = False
    require_correlation_id: bool = True
    description: str | None = None
    is_active: bool = True
    is_hidden: bool = False
    mock_response: JsonValue = None
    mock_enabled: bool = False
    tenant_id: str | None = None
    rate_limit_rpm: int | None = Field(default=60, ge=0)

    sftp_host: str | None = None
    sftp_port: int = 22
    sftp_username: str | None = None
    sftp_password: str | None = None
    sftp_private_key_path: str | None = None
    sftp_remote_path: str | None = None
    dynamic_filename_pattern: str | None = None

    api_id: str | None = None
    api_password: str | None = None
    api_auth_url: str | None = None

    created_by: int | None = None


class EndpointUpdate(BaseModel):
    """Partial update payload — every field is optional."""

    endpoint_code: str | None = None
    source_api_url: str | None = None
    target_api_url: str | None = None
    method: MethodEnum | None = None
    protocol: ProtocolEnum | None = None
    request_content_type: ContentTypeEnum | None = None
    require_authentication: bool | None = None
    require_correlation_id: bool | None = None
    description: str | None = None
    is_active: bool | None = None
    is_hidden: bool | None = None
    mock_response: JsonValue = None
    mock_enabled: bool | None = None
    tenant_id: str | None = None
    rate_limit_rpm: int | None = Field(default=None, ge=0)

    sftp_host: str | None = None
    sftp_port: int | None = None
    sftp_username: str | None = None
    sftp_password: str | None = None
    sftp_private_key_path: str | None = None
    sftp_remote_path: str | None = None
    dynamic_filename_pattern: str | None = None

    api_id: str | None = None
    api_password: str | None = None
    api_auth_url: str | None = None

    updated_by: int | None = None


class EndpointResponse(BaseModel):
    """Stored endpoint (read model)."""

    model_config = ConfigDict(from_attributes=True)

    id: int

    endpoint_code: str | None = None
    source_api_url: str
    target_api_url: str
    method: str | None = None
    protocol: str | None = None
    request_content_type: str | None = None
    require_authentication: bool | None = None
    require_correlation_id: bool | None = None
    description: str | None = None
    is_active: bool | None = None
    is_hidden: bool | None = None
    mock_response: JsonValue = None
    mock_enabled: bool | None = None
    tenant_id: str | None = None
    rate_limit_rpm: int | None = None

    sftp_host: str | None = None
    sftp_port: int | None = None
    sftp_username: str | None = None
    sftp_password: str | None = None
    sftp_private_key_path: str | None = None
    sftp_remote_path: str | None = None
    dynamic_filename_pattern: str | None = None

    api_id: str | None = None
    api_password: str | None = None
    api_auth_url: str | None = None

    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Eager-loaded by ``endpoint_service``; read-only consumers (the cron job
    # picker) need the field names without a second round trip.
    parameters: list[ParameterResponse] = []


class MappingItem(BaseModel):
    """One field-level mapping as sent by the mapper frontend."""

    sourceField: str
    targetField: str
    enabled: bool = True
    parameterType: str = "BODY"
    parameterTypeValue: str = "BODY"


class CompleteMappingRequest(BaseModel):
    """Payload for ``POST /api/mappings/complete`` (frontend contract)."""

    source: dict[str, Any] | None = None
    target: dict[str, Any] | None = None
    sourceUrl: str
    targetUrl: str
    sourceMethod: str
    targetMethod: str
    mappings: list[MappingItem]
    score: float | None = None
    protocol: ProtocolEnum = ProtocolEnum.HTTP
    api_id: str | None = None
    api_password: str | None = None
    api_auth_url: str | None = None

    # SFTP-backed mappings read their data straight from a remote server
    # (the same shape the audio APIs use) instead of calling an HTTP upstream.
    sftp_host: str | None = None
    sftp_port: int | None = 22
    sftp_username: str | None = None
    sftp_password: str | None = None
    sftp_private_key_path: str | None = None
    sftp_remote_path: str | None = None
    dynamic_filename_pattern: str | None = None

    @model_validator(mode="after")
    def _validate_sftp(self) -> "CompleteMappingRequest":
        """SFTP mappings need credentials and a scheme-less gateway route."""
        if self.protocol is ProtocolEnum.SFTP:
            if not (self.sftp_host or "").strip():
                raise ValueError("sftp_host is required for SFTP mappings")
            if str(self.targetUrl).strip().lower().startswith(
                ("http://", "https://")
            ):
                raise ValueError(
                    "targetUrl must be a gateway path (no http/https) for "
                    "SFTP mappings"
                )
        return self


class CompleteMappingResponse(BaseModel):
    """Result of persisting a complete mapping."""

    success: bool
    apiEndpointId: int
    endpointCode: str
    message: str
    parameterCount: int
    isDuplicate: bool | None = None
    warning: bool | None = None
