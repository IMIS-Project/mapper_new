import json
from typing import Any

from pydantic import Field, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

_RAW_STRING_FIELDS = frozenset(
    {
        "CORS_ORIGINS",
        "SCHEDULER_ALLOWED_HOSTS",
        "SCHEDULER_ALLOWED_CIDRS",
        "UPSTREAM_API_TOKENS",
    }
)


class _RawStringDecodeMixin:
    """Skip JSON decoding for fields handled by our own validators."""

    def decode_complex_value(
        self, field_name: str, field: FieldInfo, value: Any
    ) -> Any:
        if field_name in _RAW_STRING_FIELDS and isinstance(value, str):
            return value
        return super().decode_complex_value(field_name, field, value)


class _EnvSettingsSource(_RawStringDecodeMixin, EnvSettingsSource):
    pass


class _DotEnvSettingsSource(_RawStringDecodeMixin, DotEnvSettingsSource):
    pass


class Settings(BaseSettings):
    """Central configuration for the API Mapper & Gateway backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/api_mapper"
    )

    ENCRYPTION_KEY: str

    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = Field(default=2528, ge=1, le=65535)
    SERVER_RELOAD: bool = False

    CORS_ORIGINS: list[str] = ["*"]
    API_TIMEOUT_SECONDS: int = 60

    HTTP_MAX_CONNECTIONS: int = Field(default=100, gt=0)
    HTTP_MAX_KEEPALIVE_CONNECTIONS: int = Field(default=20, ge=0)
    HTTP_CONNECT_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0)

    SCHEDULER_DATABASE_PATH: str = "scheduler.db"
    SCHEDULER_TIMEZONE: str = "UTC"
    SCHEDULER_REQUEST_TIMEOUT_SECONDS: float = 30.0
    SCHEDULER_DNS_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0)
    SCHEDULER_ALLOWED_HOSTS: list[str] = Field(default_factory=list)
    SCHEDULER_ALLOWED_CIDRS: list[str] = Field(default_factory=list)
    SCHEDULER_ALLOW_PRIVATE_NETWORKS: bool = False
    SCHEDULER_MAX_CONCURRENT_JOBS: int = Field(default=10, gt=0)
    SCHEDULER_MAX_JOBS: int = Field(default=100, gt=0)
    SCHEDULER_RUN_RETENTION_DAYS: int = Field(default=90, gt=0)

    SCHEDULER_MAX_REQUEST_BODY_BYTES: int = Field(default=65536, gt=0)
    SCHEDULER_MAX_RESPONSE_BODY_BYTES: int = Field(default=65536, gt=0)
    SCHEDULER_MAX_HEADERS: int = Field(default=32, gt=0)

    AUDIT_MONGO_ENABLED: bool = True

    AUDIT_MONGO_URI: str
    AUDIT_MONGO_DATABASE: str
    AUDIT_MONGO_COLLECTION: str

    AUDIT_MATCH_WINDOW_SECONDS: float = Field(default=5.0, gt=0)

    AUDIT_MONGO_TIMEOUT_MS: int = Field(default=1500, gt=0)

    AUDIT_MONGO_MIRROR: bool | None = None

    APP_ROOT_PATH: str = ""

    # Public base URL of this mapper deployment (scheme + host, optionally a
    # path prefix). A mapping may store its internal API as a bare path such as
    # ``/ref_crp_beneficiary``; that path is expanded against this base before
    # the mapped payload is delivered. Leave empty to keep requiring absolute
    # internal URLs.
    MAPPER_BASE_URL: str = ""

    @field_validator("APP_ROOT_PATH", mode="before")
    @classmethod
    def _normalize_root_path(cls, value: Any) -> str:

        if value is None:
            return ""
        text = str(value).strip()
        if not text or text == "/":
            return ""
        return "/" + text.strip("/")

    AUTH_BASE_URL: str

    AUTH_SERVICE_ENCRYPTION_KEY: str | None = None

    # Central auth is an external service: a single dropped connection or a
    # brief 5xx used to turn into a hard 503 for the caller. Retry the two
    # login hops a couple of times before giving up. 4xx responses are never
    # retried - a rejected credential or a rate limit will not change.
    AUTH_RETRY_ATTEMPTS: int = Field(default=3, ge=1, le=5)
    AUTH_RETRY_BACKOFF_SECONDS: float = Field(default=0.25, ge=0)

    # How long a validated token's identity is reused before asking the central
    # service again. Keeps the 15s console polling from turning every page
    # refresh into an upstream permissions round trip. 0 disables the cache.
    AUTH_TOKEN_CACHE_SECONDS: float = Field(default=30.0, ge=0)

    UPSTREAM_AUTH_URL: str | None = None
    UPSTREAM_AUTH_EMAIL: str | None = None
    UPSTREAM_AUTH_PASSWORD: str | None = None
    UPSTREAM_AUTH_DECRYPTION_KEY: str | None = None
    UPSTREAM_AUTH_ENCRYPTED_FIELD: str = "encrypted_data"

    UPSTREAM_AUTH_USERNAME_FIELD: str = "email"
    UPSTREAM_AUTH_PASSWORD_FIELD: str = "password"
    UPSTREAM_AUTH_LOGIN_CONTENT_TYPE: str = "json"
    UPSTREAM_AUTH_HEADER_NAME: str = "Authorization"
    UPSTREAM_AUTH_TOKEN_PREFIX: str = "Bearer"

    UPSTREAM_AUTH_TOKEN_KEYS: list[str] = [
        "access_token",
        "token",
        "api_token",
        "id_token",
        "jwt",
        "auth_token",
        "data.access_token",
        "data.token",
        "result.access_token",
        "result.token",
    ]
    UPSTREAM_AUTH_EXPIRY_KEYS: list[str] = [
        "expires_in",
        "expires_in_seconds",
        "token_expires_in",
        "expiry_seconds",
        "access_token_expires_in",
        "access_token_expiry",
        "data.expires_in",
        "result.expires_in",
    ]
    UPSTREAM_AUTH_MIN_TTL_SECONDS: int = 60

    UPSTREAM_API_TOKENS: dict[str, str] = Field(default_factory=dict)

    SFTP_KNOWN_HOSTS_FILE: str | None = None
    SFTP_CONNECT_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0)
    SFTP_LOGIN_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0)
    SFTP_MAX_ENTRIES: int = Field(default=5000, gt=0)
    SFTP_PREVIEW_MAX_BYTES: int = Field(default=1048576, gt=0)
    SFTP_MAX_CONCURRENT: int = Field(default=10, gt=0)

    WEBHOOK_DELIVERY_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0)

    WEBHOOK_RETRY_DELAY_SECONDS: float = Field(default=0.25, ge=0)

    # Bank Alfalah integration console. ``INTEGRATION_API_BASE_URL`` is the IMIS
    # integration service root that /bank/operations paths resolve against.
    #
    # There is deliberately no static token here: the integration service
    # validates the same central auth bearer the console already holds, so
    # bank_call forwards the caller's own session token.
    INTEGRATION_API_BASE_URL: str = ""
    BANK_API_TIMEOUT_SECONDS: float = Field(default=60.0, gt=0)

    POLICY_MAX_ENDPOINTS: int = Field(default=10000, gt=0)
    DEDUP_TTL_SECONDS: float = Field(default=5.0, gt=0)
    DEDUP_MAX_ENTRIES: int = Field(default=1000, gt=0)

    RATE_LIMIT_DEFAULT_RPM: int = Field(default=60, ge=0)
    GLOBAL_RATE_LIMIT_RPM: int = Field(default=600, gt=0)
    CIRCUIT_FAILURE_THRESHOLD: int = Field(default=5, gt=0)
    CIRCUIT_WINDOW_SECONDS: float = Field(default=60.0, gt=0)
    CIRCUIT_RECOVERY_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Use env/dotenv sources that pass raw strings to our validators."""
        return (
            init_settings,
            _EnvSettingsSource(settings_cls),
            _DotEnvSettingsSource(
                settings_cls,
                env_file=dotenv_settings.env_file,
                env_file_encoding=dotenv_settings.env_file_encoding,
            ),
            file_secret_settings,
        )

    @field_validator(
        "CORS_ORIGINS",
        "SCHEDULER_ALLOWED_HOSTS",
        "SCHEDULER_ALLOWED_CIDRS",
        mode="before",
    )
    @classmethod
    def _parse_cors_origins(cls, value: Any) -> Any:
        """Accept both JSON lists and comma-separated strings from the env."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return value

    @field_validator("UPSTREAM_API_TOKENS", mode="before")
    @classmethod
    def _parse_upstream_api_tokens(cls, value: Any) -> Any:
        """Accept a JSON object or ``host=token[,host=token]`` from the env."""
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return {}
            if stripped.startswith("{"):
                return json.loads(stripped)
            tokens: dict[str, str] = {}
            for pair in stripped.split(","):
                if "=" not in pair:
                    continue
                host, token = pair.split("=", 1)
                host = host.strip().lower()
                if host:
                    tokens[host] = token.strip()
            return tokens
        return value


# The module-level Settings singleton is built lazily. Tests must clear the
# environment (and let pydantic_settings parse only the sandbox .env) before
# the first access, otherwise the real .env's production values leak into the
# `settings_customise_sources` merge. The public `settings` object is never
# replaced - only the backed singleton is constructed on first use.
_settings: Settings | None = None


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


settings = _get_settings()
