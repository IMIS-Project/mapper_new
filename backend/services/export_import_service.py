from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from backend.core.config import settings
from backend.models import DataTypeEnum, ParamTypeEnum
from backend.schemas.parameter import ParameterCreate
from backend.services import endpoint_service, parameter_service

__all__ = [
    "export_csv",
    "export_json",
    "export_postman",
    "import_data",
]

_CSV_COLUMNS = [
    "endpoint_code",
    "source_api_url",
    "target_api_url",
    "method",
    "protocol",
    "description",
    "mock_enabled",
    "tenant_id",
    "rate_limit_rpm",
    "source_parameter",
    "target_parameter",
    "data_type",
    "parameter_type",
    "parameter_is_active",
]

_NON_EXPORT_KEYS = (
    "id",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
    "parameters",
)


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, (bytes,)):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _serialize_endpoint(endpoint) -> dict[str, Any]:
    data = {
        col: getattr(endpoint, col)
        for col in (
            "endpoint_code",
            "source_api_url",
            "target_api_url",
            "method",
            "protocol",
            "request_content_type",
            "require_authentication",
            "require_correlation_id",
            "description",
            "mock_response",
            "mock_enabled",
            "tenant_id",
            "rate_limit_rpm",
            "is_hidden",
            "sftp_host",
            "sftp_port",
            "sftp_username",
            "sftp_password",
            "sftp_private_key_path",
            "sftp_remote_path",
            "dynamic_filename_pattern",
            "api_id",
            "api_password",
            "api_auth_url",
        )
        if hasattr(endpoint, col)
    }
    data["source_api_url"] = data.get("source_api_url") or ""
    data["target_api_url"] = data.get("target_api_url") or ""
    data["source"] = data["source_api_url"]
    data["target"] = data["target_api_url"]
    data["parameters"] = [
        {
            "source_parameter": p.source_parameter,
            "target_parameter": p.target_parameter,
            "data_type": p.data_type,
            "parameter_type": p.parameter_type,
            "is_active": p.is_active,
        }
        for p in (endpoint.parameters or [])
    ]
    return data


async def _all_endpoints(db):
    return await endpoint_service.list_endpoints(
        db, skip=0, limit=int(settings.POLICY_MAX_ENDPOINTS)
    )


async def export_json(db) -> bytes:
    endpoints = await _all_endpoints(db)
    document = {
        "format": "api-mapper",
        "version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "endpoints": [_serialize_endpoint(ep) for ep in endpoints],
    }
    return json.dumps(document, indent=2, default=_json_default).encode("utf-8")


async def export_csv(db) -> bytes:
    endpoints = await _all_endpoints(db)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for ep in endpoints:
        params = ep.parameters or []
        if not params:
            params = [None]
        for param in params:
            row = {
                "endpoint_code": ep.endpoint_code,
                "source_api_url": ep.source_api_url or "",
                "target_api_url": ep.target_api_url or "",
                "method": ep.method,
                "protocol": ep.protocol,
                "description": ep.description,
                "mock_enabled": getattr(ep, "mock_enabled", False),
                "tenant_id": getattr(ep, "tenant_id", None),
                "rate_limit_rpm": getattr(ep, "rate_limit_rpm", None),
            }
            if param is not None:
                row.update(
                    {
                        "source_parameter": param.source_parameter,
                        "target_parameter": param.target_parameter,
                        "data_type": param.data_type,
                        "parameter_type": param.parameter_type,
                        "parameter_is_active": param.is_active,
                    }
                )
            writer.writerow(row)
    return buffer.getvalue().encode("utf-8-sig")


async def export_postman(db) -> bytes:
    endpoints = await _all_endpoints(db)
    items = []
    for ep in endpoints:
        url = ep.source_api_url or ep.target_api_url or ""
        body_params = [
            p
            for p in (ep.parameters or [])
            if str(p.parameter_type or "BODY").upper() == "BODY"
        ]
        body = "{}"
        if body_params:
            body = json.dumps({p.source_parameter: "" for p in body_params}, indent=2)
        request = {"method": str(ep.method or "POST").upper(), "url": url}
        if body_params:
            request["body"] = {"mode": "raw", "raw": body}
        items.append(
            {
                "name": ep.endpoint_code or str(ep.id),
                "request": request,
            }
        )
    collection = {
        "info": {
            "name": "API Mapper & Gateway — Exports",
            "description": "Exported API mappings",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "version": "1.0.0",
        },
        "item": items,
    }
    return json.dumps(collection, indent=2, default=_json_default).encode("utf-8")


def _parse_json_import(raw: bytes):
    try:
        document = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return [], [{"error": f"Invalid JSON: {exc}"}]
    entries = []
    for ep in document.get("endpoints", []) or []:
        entries.append(
            {
                "endpoint": _strip_metadata(dict(ep)),
                "parameters": list(ep.get("parameters", []) or []),
            }
        )
    return entries, []


def _strip_metadata(endpoint: dict) -> dict:
    """Drop ORM-derived keys the build layer regenerates itself."""
    for key in _NON_EXPORT_KEYS:
        endpoint.pop(key, None)
    endpoint.pop("source", None)
    endpoint.pop("target", None)
    return endpoint


def _parse_csv_import(raw: bytes):
    try:
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    except Exception as exc:
        return [], [{"error": f"Invalid CSV: {exc}"}]

    groups: dict[tuple, dict] = {}
    order: list[tuple] = []
    for row in rows:
        code = (row.get("endpoint_code") or "").strip()
        source_url = (row.get("source_api_url") or "").strip()
        target_url = (row.get("target_api_url") or "").strip()
        method = (row.get("method") or "").strip()
        protocol = (row.get("protocol") or "").strip()
        description = (row.get("description") or "").strip()
        mock_enabled = (row.get("mock_enabled") or "").strip()
        tenant_id = (row.get("tenant_id") or "").strip()
        rate_limit_rpm = (row.get("rate_limit_rpm") or "").strip()
        # endpoint_code is NOT unique in the store, so grouping by code alone
        # collapses distinct endpoints. Key on the full endpoint-level row so a
        # round-trip is lossless.
        key = (code, source_url, target_url, method, protocol, description,
               mock_enabled, tenant_id, rate_limit_rpm) if (code or source_url or target_url) else None
        if not key:
            continue
        if key not in groups:
            order.append(key)
            groups[key] = {
                "endpoint": {
                    "endpoint_code": code or None,
                    "source_api_url": row.get("source_api_url") or "",
                    "target_api_url": row.get("target_api_url") or "",
                    "method": row.get("method") or "POST",
                    "protocol": row.get("protocol") or None,
                    "description": row.get("description"),
                    "mock_enabled": _as_bool(row.get("mock_enabled")),
                    "tenant_id": row.get("tenant_id"),
                    "rate_limit_rpm": _as_int(row.get("rate_limit_rpm")),
                },
                "parameters": [],
            }
        groups[key]["parameters"].append(
            {
                "source_parameter": row.get("source_parameter"),
                "target_parameter": row.get("target_parameter"),
                "data_type": row.get("data_type"),
                "parameter_type": row.get("parameter_type"),
                "is_active": _as_bool(row.get("parameter_is_active")),
            }
        )
    return [groups[k] for k in order], []


def _as_bool(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def _postman_variables(document: dict) -> dict[str, str]:

    variables: dict[str, str] = {}
    for item in document.get("variable", []) or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if key:
            variables[f"{{{{{key}}}}}"] = _stringify(item.get("value"))
    info = document.get("info", {}) or {}
    if isinstance(info, dict):
        for key in ("baseUrl", "base_url"):
            placeholder = f"{{{{{key}}}}}"
            if placeholder not in variables and info.get(key):
                variables[placeholder] = _stringify(info.get(key))
    return variables


def _resolve_postman_values(value: Any, variables: dict[str, str]) -> Any:
    """Substitute ``{{...}}`` placeholders through a value tree."""
    if isinstance(value, str):
        resolved: str = value
        for placeholder, replacement in variables.items():
            resolved = resolved.replace(placeholder, replacement)
        return resolved
    if isinstance(value, dict):
        return {k: _resolve_postman_values(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_postman_values(v, variables) for v in value]
    return value


def _postman_url(url: Any, variables: dict[str, str] | None = None) -> str:
    if isinstance(url, dict):
        raw = url.get("raw") or ""
    else:
        raw = str(url or "")
    if variables:
        raw = _resolve_postman_values(raw, variables)
    return str(raw or "")


def _walk_postman_requests(items: Any):
    """Depth-first yield of every item carrying a ``request`` (folders too)."""
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if "request" in item:
            yield item
        elif "item" in item:
            yield from _walk_postman_requests(item.get("item"))


def _postman_response_body(request: dict) -> Any:

    for response in request.get("response", []) or []:
        if not isinstance(response, dict):
            continue
        body = response.get("body")
        if isinstance(body, str) and body.strip():
            body = {"raw": body}
        if not isinstance(body, dict):
            continue
        raw = body.get("raw")
        if raw is None and body:
            return body
        if isinstance(raw, str) and raw.strip():
            try:
                return json.loads(raw)
            except Exception:
                return raw
    return None


def _parse_postman_import(raw: bytes):
    try:
        document = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return [], [{"error": f"Invalid Postman collection: {exc}"}]

    variables = _postman_variables(document)
    entries = []
    for item in _walk_postman_requests(document.get("item")):
        request = item.get("request", {}) or {}
        url = _postman_url(request.get("url", ""), variables)
        method = str(request.get("method") or "POST").upper()

        parameters = []
        body = request.get("body", {}) or {}
        raw_body = body.get("raw")
        if isinstance(raw_body, str) and raw_body.strip():
            try:
                parsed = json.loads(raw_body)
            except Exception:
                parsed = {}
            if isinstance(parsed, dict):
                parameters = [
                    {
                        "source_parameter": k,
                        "target_parameter": k,
                        "parameter_type": "BODY",
                    }
                    for k in parsed
                ]

        endpoint = {
            "source_api_url": url or "",
            "target_api_url": url or "",
            "method": method,
            "description": item.get("name"),
        }
        response_body = _postman_response_body(request)
        if response_body is not None:
            endpoint["mock_response"] = response_body
            endpoint["mock_enabled"] = True
        entries.append({"endpoint": endpoint, "parameters": parameters})

    return entries, []


async def _persist_entry(db, entry: dict) -> tuple[int, int]:
    """Persist one endpoint + parameters in a single transaction."""
    endpoint_data = dict(entry["endpoint"])
    endpoint_data.setdefault("source_api_url", "")
    endpoint_data.setdefault("target_api_url", "")
    endpoint_data.setdefault("method", "POST")
    if not (endpoint_data.get("source_api_url") or endpoint_data.get("target_api_url")):
        raise ValueError("Endpoint requires a source or target URL")

    endpoint = await endpoint_service.create_endpoint_flush(db, endpoint_data)
    parameters: list[ParameterCreate] = []
    for p in entry.get("parameters", []) or []:
        if not isinstance(p, dict):
            continue
        source = p.get("source_parameter")
        target = p.get("target_parameter")
        if not source or not target:
            continue
        is_active = _as_bool(p.get("is_active"))
        parameters.append(
            ParameterCreate(
                source_parameter=str(source),
                target_parameter=str(target),
                data_type=p.get("data_type") or DataTypeEnum.STRING,
                parameter_type=p.get("parameter_type") or ParamTypeEnum.BODY,
                is_active=is_active,
            )
        )
    created = await parameter_service.bulk_create_parameters_flush(
        db, endpoint.id, parameters
    )
    await db.commit()
    return 1, len(created)


async def import_data(db, kind: str, raw: bytes) -> dict[str, Any]:
    """Import a JSON/CSV/Postman bundle; one transaction per endpoint."""
    if kind == "json":
        entries, errors = _parse_json_import(raw)
    elif kind == "csv":
        entries, errors = _parse_csv_import(raw)
    elif kind == "postman":
        entries, errors = _parse_postman_import(raw)
    else:
        return {
            "success": False,
            "imported_endpoints": 0,
            "imported_mappings": 0,
            "errors": [{"error": f"Unsupported import format: {kind}"}],
        }

    imported_endpoints = 0
    imported_mappings = 0
    for entry in entries:
        try:
            eps, params = await _persist_entry(db, entry)
            imported_endpoints += eps
            imported_mappings += params
        except Exception as exc:
            await db.rollback()
            errors.append({"error": str(exc)})

    return {
        "success": not errors,
        "imported_endpoints": imported_endpoints,
        "imported_mappings": imported_mappings,
        "errors": errors,
    }
