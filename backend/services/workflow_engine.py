from __future__ import annotations

import json
import logging
import time
from typing import Any
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.workflow import Workflow, WorkflowRun, WorkflowStep
from backend.services.code_executor import execute_code_node
from backend.services.curl_parser import parse_curl_command
from backend.services.env_var_service import get_env_dict
from backend.services.expression_evaluator import evaluate_expression
from backend.services.log_writer import redact
from backend.services.sspa_cipher import decrypt_sspa_payload, encrypt_sspa_payload

logger = logging.getLogger(__name__)


def generate_curl_command(method: str, url: str, headers: dict[str, str], body: Any) -> str:
    lines = [f"curl --location --request {method.upper()} '{url}'"]
    for hk, hv in headers.items():
        lines.append(f"  --header '{hk}: {hv}'")
    if body is not None:
        if isinstance(body, (dict, list)):
            body_str = json.dumps(body)
        else:
            body_str = str(body)
        lines.append(f"  --data '{body_str}'")
    return " \\\n".join(lines)


async def execute_step(
    step: WorkflowStep,
    context: dict[str, Any],
    http_client: httpx.AsyncClient,
) -> Any:
    raw_config = step.config or {}
    resolved_config = evaluate_expression(raw_config, context)
    step_type = step.step_type.lower()

    if step_type in ("trigger", "webhook", "start_webhook"):
        return context.get("trigger", {})

    elif step_type in ("http_request", "curl"):
        curl_cmd = resolved_config.get("curl_command") or raw_config.get("curl_command")
        if curl_cmd and not resolved_config.get("url"):
            parsed_curl = parse_curl_command(curl_cmd)
            method = parsed_curl.get("method", "GET").upper()
            url = parsed_curl.get("url", "").strip()
            headers = parsed_curl.get("headers", {})
            body = parsed_curl.get("body")
        else:
            method = str(resolved_config.get("method") or "GET").upper()
            url = str(resolved_config.get("url") or "").strip()
            headers = resolved_config.get("headers") or {}
            body = resolved_config.get("body")

        timeout_val = float(resolved_config.get("timeout", 30.0))

        if not url:
            raise ValueError(f"HTTP request node '{step.step_key}' missing URL")

        clean_headers: dict[str, str] = {}
        for hk, hv in (headers or {}).items():
            if hv is None:
                continue
            str_hv = str(hv).strip()
            if hk.lower() == "authorization" and str_hv.lower() in ("bearer", "bearer none", "bearer null", "bearer undefined"):
                continue
            clean_headers[hk] = str_hv

        req_kwargs: dict[str, Any] = {
            "method": method,
            "url": url,
            "headers": clean_headers,
            "timeout": timeout_val,
        }

        if body is not None:
            if isinstance(body, (dict, list)):
                req_kwargs["json"] = body
            else:
                req_kwargs["content"] = str(body)

        curl_cmd_generated = generate_curl_command(method, url, clean_headers, body)

        req_start = time.perf_counter()
        http_error = None
        resp_data = None
        status_code = None
        resp_headers = {}

        try:
            response = await http_client.request(**req_kwargs)
            http_duration_ms = int((time.perf_counter() - req_start) * 1000)
            status_code = response.status_code
            resp_headers = dict(response.headers)
            try:
                resp_data = response.json()
            except Exception:
                resp_data = response.text
        except Exception as exc:
            http_duration_ms = int((time.perf_counter() - req_start) * 1000)
            http_error = str(exc)

        http_log = {
            "request": {
                "method": method,
                "url": url,
                "headers": redact(clean_headers),
                "body": redact(body) if isinstance(body, (dict, list)) else body,
                "curl_command": curl_cmd_generated,
            },
            "response": {
                "status_code": status_code,
                "headers": resp_headers,
                "body": resp_data,
            } if status_code is not None else None,
            "duration_ms": http_duration_ms,
            "error": http_error,
        }

        if http_error:
            exc = RuntimeError(f"HTTP request to {method} {url} failed: {http_error}")
            exc.http_log = http_log
            raise exc

        result: dict[str, Any] = {
            "status_code": status_code,
            "headers": resp_headers,
            "body": resp_data,
            "response": resp_data,
            "_http_log": http_log,
        }

        if isinstance(resp_data, dict):
            result.update(resp_data)
            if "data" not in resp_data:
                result["data"] = resp_data
        else:
            result["data"] = resp_data

        if status_code and status_code >= 400:
            exc = RuntimeError(
                f"HTTP {status_code} from {method} {url}: {resp_data}"
            )
            exc.http_log = http_log
            exc.output = result
            raise exc

        return result

    elif step_type == "aes_encrypt":
        key = resolved_config.get("key")
        payload = resolved_config.get("payload")
        if not key:
            raise ValueError(f"AES encrypt node '{step.step_key}' missing key")
        if payload is None:
            raise ValueError(f"AES encrypt node '{step.step_key}' missing payload")

        return encrypt_sspa_payload(payload, key)

    elif step_type == "aes_decrypt":
        key = resolved_config.get("key")
        enc_data = resolved_config.get("encrypted_data") or resolved_config.get("payload")
        if not key:
            raise ValueError(f"AES decrypt node '{step.step_key}' missing key")
        if enc_data is None:
            raise ValueError(f"AES decrypt node '{step.step_key}' missing encrypted_data")

        return decrypt_sspa_payload(enc_data, key)

    elif step_type == "transform":
        template = resolved_config.get("template")
        if template is not None:
            return template
        return resolved_config

    elif step_type == "output":
        return resolved_config.get("response", resolved_config)

    elif step_type == "code":
        code_str = raw_config.get("code") or resolved_config.get("code") or ""
        return execute_code_node(
            code_snippet=code_str,
            trigger=context.get("trigger", {}),
            nodes=context.get("nodes", {}),
            env=context.get("env", {}),
        )

    else:
        return resolved_config



async def run_workflow(
    workflow: Workflow,
    trigger_payload: dict[str, Any],
    db: AsyncSession,
    http_client: httpx.AsyncClient,
) -> dict[str, Any]:
    start_time = time.perf_counter()
    env_vars = await get_env_dict(db)

    context: dict[str, Any] = {
        "env": env_vars,
        "trigger": trigger_payload,
        "nodes": {},
    }

    steps = sorted(
        [s for s in workflow.steps if s.is_active],
        key=lambda s: s.step_order,
    )

    step_results: list[dict[str, Any]] = []
    final_output: Any = None
    overall_status = "SUCCESS"
    error_message: str | None = None

    for step in steps:
        step_start = time.perf_counter()
        try:
            output = await execute_step(step, context, http_client)
            step_duration_ms = int((time.perf_counter() - step_start) * 1000)

            http_log = None
            if isinstance(output, dict) and "_http_log" in output:
                http_log = output.pop("_http_log")

            context["nodes"][step.step_key] = output
            final_output = output

            step_entry: dict[str, Any] = {
                "step_key": step.step_key,
                "step_type": step.step_type,
                "status": "SUCCESS",
                "duration_ms": step_duration_ms,
                "output": output,
                "error": None,
            }
            if http_log:
                step_entry["http_log"] = http_log

            step_results.append(step_entry)
        except Exception as exc:
            step_duration_ms = int((time.perf_counter() - step_start) * 1000)
            overall_status = "FAILED"
            error_message = f"Step '{step.step_key}' failed: {exc}"
            logger.error("Workflow '%s' failed at step '%s': %s", workflow.slug, step.step_key, exc)

            http_log = getattr(exc, "http_log", None)
            failed_output = getattr(exc, "output", None)
            if isinstance(failed_output, dict) and "_http_log" in failed_output:
                failed_output.pop("_http_log", None)

            step_entry: dict[str, Any] = {
                "step_key": step.step_key,
                "step_type": step.step_type,
                "status": "FAILED",
                "duration_ms": step_duration_ms,
                "output": failed_output,
                "error": str(exc),
            }
            if http_log:
                step_entry["http_log"] = http_log

            step_results.append(step_entry)
            break

    total_time_ms = int((time.perf_counter() - start_time) * 1000)

    run_record = WorkflowRun(
        workflow_id=workflow.id,
        status=overall_status,
        trigger_payload=trigger_payload,
        step_results=step_results,
        final_output=final_output if isinstance(final_output, dict) else {"result": final_output},
        error_message=error_message,
        total_time_ms=total_time_ms,
    )
    db.add(run_record)
    await db.commit()
    await db.refresh(run_record)

    return {
        "run_id": run_record.id,
        "workflow_id": workflow.id,
        "status": overall_status,
        "total_time_ms": total_time_ms,
        "final_output": final_output,
        "step_results": step_results,
        "error": error_message,
    }
