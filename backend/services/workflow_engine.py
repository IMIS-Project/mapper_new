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
    request_headers: dict[str, Any] | None = None,
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

    await _record_workflow_to_api_call_log(
        db=db,
        workflow=workflow,
        trigger_payload=trigger_payload,
        step_results=step_results,
        final_output=final_output,
        overall_status=overall_status,
        total_time_ms=total_time_ms,
        error_message=error_message,
        request_headers=request_headers,
    )

    return {
        "run_id": run_record.id,
        "workflow_id": workflow.id,
        "status": overall_status,
        "total_time_ms": total_time_ms,
        "final_output": final_output,
        "step_results": step_results,
        "error": error_message,
    }


async def _get_or_create_step_endpoint(
    db: AsyncSession,
    workflow_slug: str,
    workflow_name: str,
    step_key: str,
    target_url: str,
    method: str = "POST",
) -> int | None:
    try:
        from sqlalchemy import select
        from backend.models.endpoint import ApiEndpoint
        from backend.models.enums import ContentTypeEnum

        clean_url = target_url.strip()
        code_suffix = step_key.upper().replace("-", "_")
        endpoint_code = f"WF_{workflow_slug.upper().replace('-', '_')}_{code_suffix}"

        stmt = select(ApiEndpoint).where(ApiEndpoint.endpoint_code == endpoint_code)
        ep = (await db.execute(stmt)).scalar_one_or_none()

        if not ep:
            source_url = f"/api/workflows/webhook/{workflow_slug}"
            stmt2 = select(ApiEndpoint).where(
                ApiEndpoint.source_api_url == source_url,
                ApiEndpoint.target_api_url == clean_url,
            )
            ep = (await db.execute(stmt2)).scalar_one_or_none()

        if ep:
            if ep.target_api_url != clean_url:
                ep.target_api_url = clean_url
                await db.flush()
            return ep.id

        new_ep = ApiEndpoint(
            endpoint_code=endpoint_code,
            source_api_url=f"/api/workflows/webhook/{workflow_slug}",
            target_api_url=clean_url,
            method=method.upper(),
            request_content_type=ContentTypeEnum.JSON.value,
            is_active=True,
            description=f"Workflow '{workflow_name}' Step: {step_key}",
        )
        db.add(new_ep)
        await db.flush()
        return new_ep.id
    except Exception as exc:
        logger.warning("Could not ensure endpoint for step %s (%s): %s", step_key, target_url, exc)
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def _record_workflow_to_api_call_log(
    db: AsyncSession,
    workflow: Workflow,
    trigger_payload: dict[str, Any],
    step_results: list[dict[str, Any]],
    final_output: Any,
    overall_status: str,
    total_time_ms: int,
    error_message: str | None,
    request_headers: dict[str, Any] | None = None,
) -> None:
    try:
        from backend.services.log_writer import write_call_log

        http_steps = [s for s in step_results if s.get("http_log")]

        if http_steps:
            for s in http_steps:
                http_log = s.get("http_log") or {}
                http_req = http_log.get("request") or {}
                http_resp = http_log.get("response") or {}

                target_url = (http_req.get("url") or "").strip()
                if not target_url:
                    continue

                method = (http_req.get("method") or "POST").upper()
                step_key = s.get("step_key") or "http"
                step_status = s.get("status") or "SUCCESS"
                step_duration = s.get("duration_ms", 0)

                ep_id = await _get_or_create_step_endpoint(
                    db=db,
                    workflow_slug=workflow.slug,
                    workflow_name=workflow.name,
                    step_key=step_key,
                    target_url=target_url,
                    method=method,
                )

                resp_code = http_resp.get("status_code") or (200 if step_status == "SUCCESS" else 502)
                req_body = http_req.get("body") if http_req.get("body") is not None else http_req.get("payload")
                resp_body = http_resp.get("body") if http_resp.get("body") is not None else s.get("output")

                source_resp = resp_body
                if not isinstance(source_resp, (dict, list)):
                    source_resp = {"result": source_resp}

                step_log_data = {
                    "success": step_status == "SUCCESS",
                    "endpoint_id": ep_id,
                    "request_body": req_body or trigger_payload,
                    "request_headers": http_req.get("headers") or request_headers or {},
                    "status_code": resp_code,
                    "external_status_code": resp_code,
                    "source_response": source_resp,
                    "external_request_url": target_url,
                    "external_request_headers": http_req.get("headers") or {},
                    "external_request_body": req_body or {},
                    "external_response_headers": http_resp.get("headers") or {},
                    "data": resp_body,
                    "target_response": resp_body,
                    "total_time_ms": step_duration,
                    "external_response_time_ms": step_duration,
                    "error": s.get("error"),
                }
                await write_call_log(db, step_log_data)
        else:
            from backend.models.endpoint import ApiEndpoint
            from backend.models.enums import ContentTypeEnum
            from sqlalchemy import select

            endpoint_code = f"WF_{workflow.slug.upper().replace('-', '_')}"
            stmt_ep = select(ApiEndpoint).where(ApiEndpoint.endpoint_code == endpoint_code)
            ep = (await db.execute(stmt_ep)).scalar_one_or_none()
            if not ep:
                ep = ApiEndpoint(
                    endpoint_code=endpoint_code,
                    source_api_url=f"/api/workflows/webhook/{workflow.slug}",
                    target_api_url="https://devmis.sspa.gos.pk/api/v1/imis/complaint/create",
                    method="POST",
                    request_content_type=ContentTypeEnum.JSON.value,
                    is_active=True,
                    description=f"Workflow Webhook: {workflow.name} ({workflow.slug})",
                )
                db.add(ep)
                await db.flush()

            client_status = 200 if overall_status == "SUCCESS" else 502
            log_data = {
                "success": overall_status == "SUCCESS",
                "endpoint_id": ep.id if ep else None,
                "request_body": trigger_payload,
                "request_headers": request_headers or {},
                "status_code": client_status,
                "external_status_code": client_status,
                "source_response": final_output if isinstance(final_output, (dict, list)) else {"result": final_output},
                "external_request_url": ep.target_api_url if ep else "",
                "external_request_headers": {},
                "external_request_body": trigger_payload,
                "external_response_headers": {},
                "data": final_output,
                "target_response": final_output,
                "total_time_ms": total_time_ms,
                "external_response_time_ms": total_time_ms,
                "error": error_message,
            }
            await write_call_log(db, log_data)
    except Exception as exc:
        logger.warning("Could not record workflow call to api_call_log: %s", exc)
        try:
            await db.rollback()
        except Exception:
            pass

