from __future__ import annotations

import json
import re
import shlex
from typing import Any


def parse_curl_command(curl_command: str) -> dict[str, Any]:
    text = curl_command.strip()
    if not text:
        return {"method": "GET", "url": "", "headers": {}, "body": None}

    # Clean multi-line backslashes and powershell backticks
    text = re.sub(r"\\\s*\n", " ", text)
    text = re.sub(r"`\s*\n", " ", text)

    try:
        tokens = shlex.split(text)
    except Exception:
        tokens = text.split()

    if tokens and tokens[0].lower() == "curl":
        tokens = tokens[1:]

    method = "GET"
    url = ""
    headers: dict[str, str] = {}
    data_parts: list[str] = []

    i = 0
    while i < len(tokens):
        token = tokens[i]

        if token in ("-X", "--request") and i + 1 < len(tokens):
            method = tokens[i + 1].upper()
            i += 2
        elif token in ("-H", "--header") and i + 1 < len(tokens):
            header_str = tokens[i + 1]
            if ":" in header_str:
                k, v = header_str.split(":", 1)
                headers[k.strip()] = v.strip()
            i += 2
        elif token in ("-d", "--data", "--data-raw", "--data-binary", "--data-ascii") and i + 1 < len(tokens):
            data_parts.append(tokens[i + 1])
            if method == "GET":
                method = "POST"
            i += 2
        elif token == "--url" and i + 1 < len(tokens):
            url = tokens[i + 1]
            i += 2
        elif token.startswith("http://") or token.startswith("https://") or token.startswith("{{"):
            url = token
            i += 1
        elif token.startswith("-"):
            # Skip unknown flags or flags with values
            if token in ("-u", "--user", "-A", "--user-agent", "-m", "--max-time") and i + 1 < len(tokens):
                i += 2
            else:
                i += 1
        else:
            if not url:
                url = token
            i += 1

    body: Any = None
    if data_parts:
        raw_body = " ".join(data_parts)
        try:
            body = json.loads(raw_body)
        except Exception:
            body = raw_body

    return {
        "method": method,
        "url": url,
        "headers": headers,
        "body": body,
    }
