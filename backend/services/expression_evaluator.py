from __future__ import annotations

import re
from typing import Any

_EXPR_PATTERN = re.compile(r"\{\{\s*([\w\.\-]+)\s*\}\}")


def get_nested_value(data: Any, path: str) -> Any:
    if not path:
        return data

    parts = path.split(".")
    current = data
    for part in parts:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, (list, tuple)):
            try:
                idx = int(part)
                current = current[idx] if 0 <= idx < len(current) else None
            except ValueError:
                return None
        elif hasattr(current, part):
            current = getattr(current, part)
        else:
            return None
    return current


def resolve_single_reference(ref: str, context: dict[str, Any]) -> Any:
    ref = ref.strip()
    if ref.startswith("env."):
        key = ref[4:]
        env_vars = context.get("env", {})
        val = env_vars.get(key)
        if isinstance(val, str) and val.isdigit() and (len(val) == 1 or not val.startswith("0")):
            try:
                return int(val)
            except ValueError:
                return val
        return val
    elif ref.startswith("trigger."):
        path = ref[8:]
        trigger_payload = context.get("trigger", {})
        val = get_nested_value(trigger_payload, path)
        if val is None and path.startswith("default_payload."):
            val = get_nested_value(trigger_payload, path[16:])
        elif val is None and isinstance(trigger_payload, dict) and isinstance(trigger_payload.get("default_payload"), dict):
            val = get_nested_value(trigger_payload.get("default_payload"), path)
        return val
    elif ref.startswith("nodes."):
        path = ref[6:]
        nodes_data = context.get("nodes", {})
        val = get_nested_value(nodes_data, path)
        if val is None and path.endswith(".output"):
            base_path = path[:-7]
            val = get_nested_value(nodes_data, base_path)
        return val

    else:
        return get_nested_value(context, ref)


def evaluate_expression(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        match = _EXPR_PATTERN.fullmatch(value.strip())
        if match:
            return resolve_single_reference(match.group(1), context)

        def _replacer(m: re.Match) -> str:
            val = resolve_single_reference(m.group(1), context)
            return "" if val is None else str(val)

        return _EXPR_PATTERN.sub(_replacer, value)

    elif isinstance(value, dict):
        return {k: evaluate_expression(v, context) for k, v in value.items()}

    elif isinstance(value, list):
        return [evaluate_expression(item, context) for item in value]

    return value
