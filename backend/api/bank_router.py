"""Bank Alfalah integration console.

Proxies the Bank Alfalah operations exposed by the IMIS integration service
(``/integration/imis/api/compliance/*``) so they can be exercised from the
console without leaving the browser.

Two independent token flows exist upstream and this module keeps them apart:

* **Token Generation** (``tokenGeneration``) - an OAuth ``client_credentials``
  call that returns an ``access_token``. The C2C endpoints use *this* token.
* **Bank Auth** (``bank-auth``) - a username/password call that returns
  ``ResponseDescription.AccessToken``. The account-opening endpoints use
  *this* token.

Operations are resolved from a fixed allow-list: the console never forwards a
caller-supplied URL, so the proxy cannot be pointed at an arbitrary host.
"""

import logging
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlencode
from uuid import uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import bearer_scheme, get_current_active_user, get_db
from backend.core.clock import local_now
from backend.core.config import settings
from backend.core.redaction import mask_sensitive
from backend.services.log_writer import write_call_log
from backend.schemas.bank import BankCallRequest, BankCallResponse, BankConfigResponse
from backend.services.central_auth import CentralUser
from backend.services.http_client import get_http_client

logger = logging.getLogger(__name__)

__all__ = ["router", "BANK_OPERATIONS"]

router = APIRouter(tags=["Bank"])

CORRELATION_HEADER = "x-correlation-id"
BANK_AUTH_HEADER = "x-bank-authorization"
BEARER_PREFIX = "bearer "

# The integration service extracts the bearer from this header and replays it to
# mvisa.bankalfalah.com, so a bare token and a "Bearer <token>" both work.
_TOKEN_IN_HEADER = re.compile(r"^\s*bearer\s+", re.IGNORECASE)


_EXAMPLES: dict[str, str] = {
    "GrantType": "client_credentials",
    "Scope": "GetToken",
    "Transaction_Ref": "SSPA1730000000A1B2",
    "Amount": "500",
    "To_Account": "0123456789",
    "CNIC_No": "35202-1234567-1",
    "Mobile_No": "0300-1234567",
    "CustomerCNIC": "35202-1234567-1",
    "MobileNumber": "0300-1234567",
    "Province": "Sindh",
    "CNICIssuanceDate": "2024-01-15",
    "AccountOpeningDate": "2024-01-15",
    "CNIC_Expiry_Date": "2029-01-15",
    "cnic": "35202-1234567-1",
}


def _field(
    name: str,
    label: str,
    *,
    required: bool = False,
    kind: str = "text",
    placeholder: str = "",
    help: str = "",
    default: Any = None,
    options: tuple[str, ...] = (),
    digits: int | None = None,
    value_type: str = "string",
) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "required": required,
        "kind": kind,
        "placeholder": placeholder,
        "help": help,
        "default": default,
        "options": list(options),
        # Expected digit count, ignoring separators. Enforced here so a bad
        # value never reaches an endpoint whose validator would otherwise
        # crash the integration service with a 500.
        "digits": digits,
        # Schema metadata, rendered beside the JSON editor the way an API
        # reference documents its request body.
        "type": value_type,
        "format": "password" if kind == "password" else None,
        "enum": list(options) or None,
        "example": _EXAMPLES.get(name, ""),
    }


_CNIC_HELP = "13 digits, hyphens allowed."
_MOBILE_HELP = "11 digits, hyphens allowed."


BANK_OPERATIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "token-generation",
        "label": "Token Generation",
        "group": "token",
        "method": "POST",
        "path": "/integration/imis/api/compliance/tokenGeneration",
        "summary": "OAuth client-credentials token. The C2C endpoints fetch this server-side.",
        "downstream": (
            "https://servicegateway.bankalfalah.com/bankalfalah/uat/"
            "oauthgeneratetokenupdated/v1"
        ),
        "tokenFlow": "token-generation",
        "tokenHeader": None,
        "requiresCorrelationId": True,
        "tokenOutcome": "access_token",
        "fields": (
            _field("SecretKey", "Secret key", required=True, kind="password"),
            _field("ClientId", "Client ID", required=True),
            _field(
                "GrantType",
                "Grant type",
                required=True,
                kind="select",
                options=("client_credentials",),
                default="client_credentials",
            ),
            _field("Scope", "Scope", required=True, default="GetToken"),
        ),
    },
    {
        "id": "bank-auth",
        "label": "Bank Auth",
        "group": "token",
        "method": "POST",
        "path": "/integration/imis/api/compliance/bank-auth",
        "summary": "Username/password login. SSPA Registration requires this token.",
        "downstream": (
            "https://mvisa.bankalfalah.com/SendNotificationCenter/sspa/authenticate"
        ),
        "tokenFlow": "bank-auth",
        "tokenHeader": None,
        "requiresCorrelationId": False,
        "tokenOutcome": "ResponseDescription.AccessToken",
        "fields": (
            _field("Username", "Username", required=True),
            _field("Password", "Password", required=True, kind="password"),
        ),
    },
    {
        "id": "sspa-registration",
        "label": "SSPA Registration",
        "group": "account-opening",
        "method": "POST",
        "path": "/integration/imis/api/compliance/sspa-registration",
        "summary": (
            "Account opening at the bank. Needs the bank-auth token in the "
            "x-bank-authorization header; this console obtains it for you."
        ),
        "downstream": (
            "https://mvisa.bankalfalah.com/SendNotificationCenter/sspa/SSPARegistration"
        ),
        "tokenFlow": "bank-auth",
        "tokenHeader": BANK_AUTH_HEADER,
        # This endpoint requires the bank-auth token but cannot obtain one
        # itself, so the console authenticates first and forwards the token.
        "autoChain": True,
        "autoChainOperation": "bank-auth",
        "autoChainCredentials": ("Username", "Password"),
        "requiresCorrelationId": False,
        "tokenOutcome": None,
        "fields": (
            _field("Username", "Username", required=True),
            _field("Password", "Password", required=True, kind="password"),
            _field("CustomerCNIC", "Customer CNIC", required=True, help=_CNIC_HELP, digits=13),
            _field("CustomerName", "Customer name", required=True),
            _field("District", "District", required=True),
            _field("MobileNumber", "Mobile number", required=True, help=_MOBILE_HELP, digits=11),
            _field("FatherName", "Father name"),
            _field("MotherName", "Mother name"),
            _field("Province", "Province"),
            _field("Address", "Address"),
            _field("CNICIssuanceDate", "CNIC issuance date", placeholder="YYYY-MM-DD"),
            _field("Taluka", "Taluka"),
        ),
    },
    {
        "id": "beneficiary-lookup-path",
        "label": "Beneficiary Lookup (path)",
        "group": "account-opening",
        "method": "GET",
        "path": "/integration/imis/api/compliance/beneficiary/{cnic}",
        "paramStyle": "path",
        "paramName": "cnic",
        "summary": (
            "Reads the beneficiary demographics the SSPA registration form needs, "
            "keyed by CNIC in the path. Read-only - it never reaches the bank."
        ),
        "downstream": "None - IMIS database lookup (ubr_person, ubr_household, ...).",
        "tokenFlow": "none",
        "tokenHeader": None,
        "requiresCorrelationId": False,
        "tokenOutcome": None,
        "fields": (
            _field("cnic", "CNIC", required=True, help=_CNIC_HELP, digits=13),
        ),
    },
    {
        "id": "beneficiary-lookup-query",
        "label": "Beneficiary Lookup (query)",
        "group": "account-opening",
        "method": "GET",
        "path": "/integration/imis/api/compliance/beneficiary-details",
        "paramStyle": "query",
        "paramName": "cnic",
        "summary": "Same lookup as the path variant, addressed as a query parameter.",
        "downstream": "None - IMIS database lookup (ubr_person, ubr_household, ...).",
        "tokenFlow": "none",
        "tokenHeader": None,
        "requiresCorrelationId": False,
        "tokenOutcome": None,
        "fields": (
            _field("cnic", "CNIC", required=True, help=_CNIC_HELP, digits=13),
        ),
    },
    {
        "id": "c2c-disbursement",
        "label": "C2C Disbursement",
        "group": "c2c",
        "method": "POST",
        "path": "/integration/imis/api/compliance/c2c-disbursement",
        "summary": "Fetches its own OAuth token, then calls the Bank Alfalah C2C API.",
        "downstream": (
            "https://servicegateway.bankalfalah.com/bankalfalah/uat/sspa-c2c/v1"
        ),
        "tokenFlow": "token-generation-internal",
        "tokenHeader": None,
        "requiresCorrelationId": False,
        "tokenOutcome": None,
        "fields": (
            _field("Transaction_Ref", "Transaction reference", required=True),
            _field("Amount", "Amount", required=True, placeholder="1"),
            _field("To_Account", "To account", required=True),
            _field("Stan", "Stan", required=True),
            _field("CNIC_No", "CNIC", required=True, help=_CNIC_HELP, digits=13),
            _field("Mobile_No", "Mobile number", required=True, help=_MOBILE_HELP, digits=11),
        ),
    },
    {
        "id": "c2c-payment",
        "label": "C2C Payment",
        "group": "c2c",
        "method": "POST",
        "path": "/integration/imis/api/compliance/c2c-payment",
        "aliasPaths": (
            "/integration/imis/api/compliance/baf-c2c-disbursement",
            "/integration/imis/api/compliance/c2c-disbursement-auto",
        ),
        "summary": "Same self-managed token flow; auto-generates the transaction ref.",
        "downstream": (
            "https://servicegateway.bankalfalah.com/bankalfalah/uat/sspa-c2c/v1"
        ),
        "tokenFlow": "token-generation-internal",
        "tokenHeader": None,
        "requiresCorrelationId": False,
        "tokenOutcome": None,
        "fields": (
            _field("Amount", "Amount", required=True, placeholder="1"),
            _field("To_Account", "To account", required=True),
            _field("CNIC_No", "CNIC", required=True, help=_CNIC_HELP, digits=13),
            _field("Mobile_No", "Mobile number", required=True, help=_MOBILE_HELP, digits=11),
            _field(
                "Transaction_Ref",
                "Transaction reference",
                help="Auto-generated by the service when omitted.",
            ),
            _field("Stan", "Stan"),
        ),
    },
)

_OPERATIONS_BY_ID: dict[str, dict[str, Any]] = {op["id"]: op for op in BANK_OPERATIONS}

_SENSITIVE_HEADERS = frozenset({"authorization", BANK_AUTH_HEADER, "cookie"})

# Mirrors the integration service's mask_sensitive_data() key list so the
# console redacts the same fields the service redacts in its own logs.
MASK = "********"


def _mask_body(value: Any) -> Any:
    """Redact credentials in a request payload before echoing it to the console.

    Applied to the copy stored on the response only - the values actually sent
    to the integration service are untouched.
    """
    return mask_sensitive(value)


def _mask_value(value: str) -> str:
    text = str(value)
    prefix = _TOKEN_IN_HEADER.match(text)
    if prefix:
        return f"{prefix.group(0).strip()} ••••••"
    if len(text) <= 8:
        return "••••••"
    return f"{text[:4]}…{text[-4:]}"


def _mask_headers(headers: dict[str, str]) -> dict[str, str]:
    """Mask the secrets we injected; everything else is safe to echo back."""
    return {
        key: _mask_value(value) if key.lower() in _SENSITIVE_HEADERS else value
        for key, value in headers.items()
    }


_NON_DIGITS = re.compile(r"\D")


def _validate_payload(
    operation: dict[str, Any], payload: dict[str, Any]
) -> list[str]:
    """Check the value shapes before anything is sent upstream.

    Several integration-service endpoints validate CNIC/mobile with pydantic
    validators that raise ValueError. Its 422 handler passes exc.errors()
    straight to JSONResponse without encoding, so the raw exception makes the
    response unserialisable and the endpoint answers 500 instead. Rejecting
    the bad value here keeps a typo from turning into a server error.
    """
    problems: list[str] = []

    for field in operation.get("fields", ()):
        expected = field.get("digits")
        if not expected:
            continue

        raw = payload.get(field["name"])
        if raw is None or not str(raw).strip():
            continue  # missing values are the service's business

        text = str(raw).strip()
        digits = _NON_DIGITS.sub("", text)

        if not digits:
            problems.append(f"{field['label']} must contain digits.")
        elif len(digits) != expected:
            problems.append(
                f"{field['label']} must be exactly {expected} digits."
            )

    return problems


def _resolve_operation(operation_id: str) -> dict[str, Any]:
    operation = _OPERATIONS_BY_ID.get(operation_id)
    if operation is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown bank operation '{operation_id}'.",
        )
    return operation


def _require_base_url() -> str:
    base = (settings.INTEGRATION_API_BASE_URL or "").strip().rstrip("/")
    if not base:
        raise HTTPException(
            status_code=503,
            detail=(
                "INTEGRATION_API_BASE_URL is not configured on this service; "
                "the bank console cannot reach the integration service."
            ),
        )
    return base


@router.get("/bank/config", response_model=BankConfigResponse)
async def bank_config(
    _current_user: CentralUser = Depends(get_current_active_user),
) -> BankConfigResponse:
    """Expose non-secret wiring so the UI can warn before the first call."""
    return BankConfigResponse(
        base_url=(settings.INTEGRATION_API_BASE_URL or "").strip(),
        timeout_seconds=settings.BANK_API_TIMEOUT_SECONDS,
    )


@router.get("/bank/operations")
async def bank_operations(
    _current_user: CentralUser = Depends(get_current_active_user),
) -> dict[str, Any]:
    """The allow-listed bank operations, with their token flow and form fields."""
    return {
        "basePath": "/integration/imis",
        "tokenFlows": {
            "token-generation": "Token Generation - used by the C2C endpoints.",
            "bank-auth": "Bank Auth - used by the account-opening endpoints.",
        },
        "operations": list(BANK_OPERATIONS),
    }


@router.post("/bank/call", response_model=BankCallResponse)
async def bank_call(
    payload: BankCallRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    http_client: httpx.AsyncClient = Depends(get_http_client),
    _current_user: CentralUser = Depends(get_current_active_user),
) -> BankCallResponse:
    """Forward one allow-listed operation to the integration service.

    The integration service authenticates with the same central auth bearer the
    console already holds, so the caller's own session token is replayed in the
    Authorization header. No static service token is involved.
    """
    operation = _resolve_operation(payload.operationId)
    base_url = _require_base_url()

    problems = _validate_payload(operation, payload.payload)
    if problems:
        raise HTTPException(status_code=400, detail="; ".join(problems))

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=401,
            detail=(
                "A central auth bearer is required to call the integration "
                "service. Sign in again to refresh the console session."
            ),
        )

    target_url = f"{base_url}{operation['path']}"
    correlation_id = (payload.correlationId or "").strip() or str(uuid4())

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {credentials.credentials}",
        CORRELATION_HEADER: correlation_id,
    }

    token_header = operation.get("tokenHeader")
    if token_header:
        bank_token = _TOKEN_IN_HEADER.sub("", (payload.bankToken or "").strip())
        if not bank_token:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"'{operation['label']}' needs the bank-auth token in the "
                    f"{token_header} header. Run Bank Auth first and chain the token."
                ),
            )
        headers[token_header] = f"Bearer {bank_token}"

    for key, value in (payload.headers or {}).items():
        lowered = key.lower()
        if lowered in {"host", "content-length"}:
            continue
        headers[key] = str(value)

    # GET operations carry a single CNIC either in the path or the query string
    # instead of a JSON body.
    method = operation["method"]
    request_kwargs: dict[str, Any] = {}
    if method == "GET":
        headers.pop("Content-Type", None)
        param_name = operation["paramName"]
        raw_value = str((payload.payload or {}).get(param_name, "")).strip()
        if not raw_value:
            raise HTTPException(
                status_code=400,
                detail=f"'{operation['label']}' requires the '{param_name}' parameter.",
            )
        if operation.get("paramStyle") == "path":
            target_url = target_url.replace(
                "{" + param_name + "}", quote(raw_value, safe="")
            )
        else:
            # Fold the query into the URL so the console shows the exact
            # address that was requested.
            target_url = f"{target_url}?{urlencode({param_name: raw_value})}"
    else:
        request_kwargs["json"] = payload.payload

    called_at = local_now()
    started = time.perf_counter()
    try:
        response = await http_client.request(
            method,
            target_url,
            headers=headers,
            timeout=settings.BANK_API_TIMEOUT_SECONDS,
            **request_kwargs,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        try:
            data: Any = response.json()
        except ValueError:
            data = {"raw_response": response.text}

        ok = _is_success(response.status_code, data)
        background_tasks.add_task(
            write_call_log,
            db,
            _build_log_entry(
                operation,
                method=method,
                target_url=target_url,
                request_headers=headers,
                request_body=payload.payload,
                status_code=response.status_code,
                response_headers=dict(response.headers),
                data=data,
                success=ok,
                error=None if ok else _describe(data),
                elapsed_ms=elapsed_ms,
                correlation_id=correlation_id,
                called_at=called_at,
            ),
        )

        return BankCallResponse(
            success=_is_success(response.status_code, data),
            operationId=operation["id"],
            targetUrl=target_url,
            targetMethod=method,
            status_code=response.status_code,
            response_time_ms=elapsed_ms,
            data=data,
            error=None if _is_success(response.status_code, data) else _describe(data),
            error_source=(
                None if _is_success(response.status_code, data) else "integration-service"
            ),
            error_layers=(
                None
                if _is_success(response.status_code, data)
                else _error_layers(
                    response.status_code,
                    data,
                    "integration-service",
                    _describe(data),
                )
            ),
            correlation_id=correlation_id,
            called_at=called_at,
            token_flow=operation.get("tokenFlow"),
            token_source=(
                "chained bank-auth token"
                if token_header
                else "handled by the integration service"
            ),
            request_headers=_mask_headers(headers),
            request_body=_mask_body(payload.payload) if method != "GET" else None,
            response_headers=dict(response.headers),
        )

    except httpx.TimeoutException as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.warning("Bank call %s timed out after %sms", operation["id"], elapsed_ms)
        background_tasks.add_task(
            write_call_log,
            db,
            _build_log_entry(
                operation,
                method=method,
                target_url=target_url,
                request_headers=headers,
                request_body=payload.payload,
                status_code=504,
                response_headers=None,
                data=None,
                success=False,
                error=f"Timed out after {settings.BANK_API_TIMEOUT_SECONDS}s: {exc}",
                elapsed_ms=elapsed_ms,
                correlation_id=correlation_id,
                called_at=called_at,
            ),
        )
        return BankCallResponse(
            success=False,
            operationId=operation["id"],
            targetUrl=target_url,
            targetMethod=method,
            status_code=504,
            response_time_ms=elapsed_ms,
            data=None,
            error=f"Timed out after {settings.BANK_API_TIMEOUT_SECONDS}s: {exc}",
            error_source="mapper",
            error_layers=_error_layers(
                504,
                None,
                "mapper",
                f"Timed out after {settings.BANK_API_TIMEOUT_SECONDS}s: {exc}",
            ),
            correlation_id=correlation_id,
            called_at=called_at,
            token_flow=operation.get("tokenFlow"),
            request_headers=_mask_headers(headers),
            request_body=_mask_body(payload.payload) if method != "GET" else None,
        )

    except httpx.HTTPError as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.warning("Bank call %s failed: %s", operation["id"], exc)
        background_tasks.add_task(
            write_call_log,
            db,
            _build_log_entry(
                operation,
                method=method,
                target_url=target_url,
                request_headers=headers,
                request_body=payload.payload,
                status_code=502,
                response_headers=None,
                data=None,
                success=False,
                error=f"Could not reach the integration service: {exc}",
                elapsed_ms=elapsed_ms,
                correlation_id=correlation_id,
                called_at=called_at,
            ),
        )
        return BankCallResponse(
            success=False,
            operationId=operation["id"],
            targetUrl=target_url,
            targetMethod=method,
            status_code=502,
            response_time_ms=elapsed_ms,
            data=None,
            error=f"Could not reach the integration service: {exc}",
            error_source="mapper",
            error_layers=_error_layers(
                502,
                None,
                "mapper",
                f"Could not reach the integration service: {exc}",
            ),
            correlation_id=correlation_id,
            called_at=called_at,
            token_flow=operation.get("tokenFlow"),
            request_headers=_mask_headers(headers),
            request_body=_mask_body(payload.payload) if method != "GET" else None,
        )


_ERROR_KEYS = ("error", "message", "description", "ResponseDescription", "detail")
_RAW_KEY = "raw_response"


_SUCCESS_CODES = frozenset({0, 200})


def _bank_reported_failure(data: Any) -> bool:
    """True when a 2xx response actually carries a failure code.

    The bank APIs answer HTTP 200 for business failures and put the real
    outcome in a ``code``/``ResponseCode`` field, where 200 (or 0) means
    success. Judging on HTTP status alone reports those as successes.
    """
    if not isinstance(data, dict):
        return False

    raw = data.get("code", data.get("ResponseCode"))
    if raw is None:
        return False

    code = _as_int(raw)
    if code is None:
        return False

    return code not in _SUCCESS_CODES


def _is_success(status_code: int, data: Any) -> bool:
    return 200 <= status_code < 300 and not _bank_reported_failure(data)


_BANK_MARKERS = ("ResponseCode", "ResponseDescription", "transactionReference", "rrn")


def _looks_like_bank(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if any(marker in payload for marker in _BANK_MARKERS):
        return True
    return "code" in payload and "description" in payload


def _is_service_envelope(payload: dict[str, Any]) -> bool:
    """The integration service wraps bank responses in this shape."""
    return (
        "status" in payload and "message" in payload and isinstance(payload.get("data"), dict)
    )


def _bank_message(payload: dict[str, Any]) -> str:
    for key in ("description", "ResponseDescription", "message", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, dict):
            nested = value.get("Message") or value.get("message")
            if isinstance(nested, str) and nested.strip():
                return nested
    return _describe(payload)


def _bank_layer(data: Any) -> dict[str, Any] | None:
    """Locate the bank's own response inside the body, if present.

    c2c_payment nests it under ``data``; the other bank-facing endpoints pass
    it through untouched, so the body itself is the bank's.
    """
    if not isinstance(data, dict):
        return None

    inner = data.get("data")
    if isinstance(inner, dict) and _looks_like_bank(inner):
        return {
            "origin": "bank",
            "label": "Bank Alfalah",
            "status_code": _as_int(inner.get("code") or inner.get("ResponseCode")),
            "message": _bank_message(inner),
        }

    if _looks_like_bank(data) and not _is_service_envelope(data):
        return {
            "origin": "bank",
            "label": "Bank Alfalah",
            "status_code": _as_int(data.get("code") or data.get("ResponseCode")),
            "message": _bank_message(data),
        }

    return None


def _build_log_entry(
    operation: dict[str, Any],
    *,
    method: str,
    target_url: str,
    request_headers: dict[str, str],
    request_body: Any,
    status_code: int | None,
    response_headers: dict[str, str] | None,
    data: Any,
    success: bool,
    error: str | None,
    elapsed_ms: int,
    correlation_id: str,
    called_at: datetime,
) -> dict[str, Any]:
    """Shape a bank call like a gateway result so it lands in Call Logs.

    "Source" is this console talking to the integration service; the bank sits
    behind that, so the target columns are left unset rather than guessed.
    """
    return {
        "request_id": correlation_id,
        "endpoint_id": None,
        "created_at": called_at,
        "method": method,
        "path": operation["path"],
        "external_request_url": target_url,
        "external_request_method": method,
        "external_status_code": status_code,
        "request_headers": _mask_headers(request_headers),
        "response_headers": _mask_headers(response_headers) if response_headers else None,
        "internal_request_body": _mask_body(request_body),
        "request_body": _mask_body(request_body),
        "data": data,
        "success": success,
        "error": error,
        "total_time_ms": elapsed_ms,
        "status_code": status_code,
    }


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _error_layers(
    status_code: int | None,
    data: Any,
    origin: str,
    message: str,
) -> list[dict[str, Any]]:
    layers: list[dict[str, Any]] = [
        {
            "origin": origin,
            "label": (
                "This console"
                if origin == "mapper"
                else "Integration service"
            ),
            "status_code": status_code,
            "message": message,
        }
    ]

    bank = _bank_layer(data)
    if bank is not None:
        if bank["message"] == message:
            # The integration service passed the bank body through unchanged,
            # so the bank is the real origin - don't attribute it to the hop
            # in the middle.
            layers = [bank]
        else:
            layers.append(bank)

    return layers


def _describe(data: Any) -> str:
    """Best-effort message from an upstream body, never discarding the detail.

    The console must show what the integration service actually said. A 500
    with an unparseable or empty body still has to produce something more
    useful than a generic sentence, so the raw text is the last resort
    rather than being thrown away.
    """
    if isinstance(data, dict):
        for key in _ERROR_KEYS:
            if key not in data:
                continue
            value = data[key]
            if isinstance(value, str) and value.strip():
                return value
            # FastAPI validation errors put a list of issues under "detail".
            if isinstance(value, list) and value:
                parts = [
                    str(item.get("msg", item)) if isinstance(item, dict) else str(item)
                    for item in value
                ]
                return "; ".join(parts)
        # Non-JSON upstream body (an HTML error page, a bare stack trace).
        raw = data.get(_RAW_KEY)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()[:500]

    if isinstance(data, str) and data.strip():
        return data.strip()[:500]

    return "The integration service returned an error with no message body."