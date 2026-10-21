from __future__ import annotations

import base64
from datetime import datetime, date, timezone
import hashlib
import json
import math
import re
import time
from types import SimpleNamespace
from typing import Any

from backend.services.sspa_cipher import decrypt_sspa_payload, encrypt_sspa_payload


def _create_crypto_helpers() -> Any:
    return SimpleNamespace(
        encrypt_sspa_payload=encrypt_sspa_payload,
        decrypt_sspa_payload=decrypt_sspa_payload,
        sha256=lambda s: hashlib.sha256(str(s).encode("utf-8")).hexdigest(),
        md5=lambda s: hashlib.md5(str(s).encode("utf-8")).hexdigest(),
        b64encode=lambda s: base64.b64encode(s if isinstance(s, bytes) else str(s).encode("utf-8")).decode("ascii"),
        b64decode=lambda s: base64.b64decode(s).decode("utf-8", errors="ignore"),
    )


def execute_code_node(
    code_snippet: str,
    trigger: dict[str, Any],
    nodes: dict[str, Any],
    env: dict[str, str],
) -> Any:
    code_snippet = (code_snippet or "").strip()
    if not code_snippet:
        return {}

    crypto = _create_crypto_helpers()

    safe_globals: dict[str, Any] = {
        "__builtins__": {
            "abs": abs,
            "all": all,
            "any": any,
            "bin": bin,
            "bool": bool,
            "bytes": bytes,
            "chr": chr,
            "dict": dict,
            "divmod": divmod,
            "enumerate": enumerate,
            "filter": filter,
            "float": float,
            "format": format,
            "frozenset": frozenset,
            "hex": hex,
            "int": int,
            "isinstance": isinstance,
            "issubclass": issubclass,
            "iter": iter,
            "len": len,
            "list": list,
            "map": map,
            "max": max,
            "min": min,
            "next": next,
            "oct": oct,
            "ord": ord,
            "pow": pow,
            "range": range,
            "reversed": reversed,
            "round": round,
            "set": set,
            "slice": slice,
            "sorted": sorted,
            "str": str,
            "sum": sum,
            "tuple": tuple,
            "zip": zip,
            "Exception": Exception,
            "ValueError": ValueError,
            "KeyError": KeyError,
            "TypeError": TypeError,
        },
        "json": json,
        "base64": base64,
        "re": re,
        "math": math,
        "time": time,
        "datetime": datetime,
        "date": date,
        "timezone": timezone,
        "crypto": crypto,
        "encrypt_sspa_payload": encrypt_sspa_payload,
        "decrypt_sspa_payload": decrypt_sspa_payload,
    }

    local_vars: dict[str, Any] = {
        "trigger": trigger,
        "nodes": nodes,
        "env": env,
        "result": None,
        "output": None,
    }

    # If the user defines 'def main(...)', we will invoke main(trigger, nodes, env)
    if "def main(" in code_snippet:
        exec(code_snippet, safe_globals, local_vars)
        main_fn = local_vars.get("main")
        if callable(main_fn):
            return main_fn(trigger=trigger, nodes=nodes, env=env)

    # If code uses top-level 'return', wrap in a closure
    if "return " in code_snippet:
        lines = code_snippet.splitlines()
        indented = "\n".join("    " + line for line in lines)
        wrapper = f"def __entrypoint(trigger, nodes, env, crypto):\n{indented}\n__res = __entrypoint(trigger, nodes, env, crypto)"
        exec(wrapper, safe_globals, local_vars)
        return local_vars.get("__res")

    # Otherwise execute directly and inspect result / output
    exec(code_snippet, safe_globals, local_vars)

    if local_vars.get("result") is not None:
        return local_vars["result"]
    if local_vars.get("output") is not None:
        return local_vars["output"]

    # Return local variables created by user (excluding inputs)
    return {
        k: v
        for k, v in local_vars.items()
        if k not in ("trigger", "nodes", "env", "result", "output") and not k.startswith("_")
    }
