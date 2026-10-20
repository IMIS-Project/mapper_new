from __future__ import annotations

import asyncio
import base64
import html
import logging
import re
from datetime import datetime
from urllib.parse import quote, unquote

import asyncssh
import httpx

from backend.core.config import settings
from backend.services import endpoint_service

logger = logging.getLogger(__name__)

__all__ = [
    "endpoint_creds",
    "list_file_preview",
    "list_files_via_http",
    "list_files_with_creds",
    "list_remote_files",
    "password_looks_opaque",
    "read_file_via_http",
    "read_file_with_creds",
    "test_connection",
]

_semaphore = asyncio.Semaphore(int(settings.SFTP_MAX_CONCURRENT))

_CREDENTIAL_FIELDS = ("host", "port", "username", "password", "private_key_path")


def _connect_kwargs(creds: dict) -> dict:
    """Build asyncssh.connect kwargs (omit known_hosts rather than pass None)."""
    kwargs = {
        "host": creds["host"],
        "port": int(creds.get("port") or 22),
        "username": creds.get("username"),
        "connect_timeout": float(settings.SFTP_CONNECT_TIMEOUT_SECONDS),
        "login_timeout": float(settings.SFTP_LOGIN_TIMEOUT_SECONDS),
    }
    if creds.get("password"):
        kwargs["password"] = creds["password"]
    if creds.get("private_key_path"):
        kwargs["client_keys"] = [creds["private_key_path"]]
    if settings.SFTP_KNOWN_HOSTS_FILE:
        kwargs["known_hosts"] = settings.SFTP_KNOWN_HOSTS_FILE
    return kwargs


async def _resolved_creds(db, config: dict) -> dict:
    """Start from stored endpoint creds (if any), then overlay overrides."""
    creds: dict = {}
    endpoint_id = config.get("endpoint_id")
    if endpoint_id:
        endpoint = await endpoint_service.get_endpoint(db, endpoint_id)
        if endpoint is None:
            raise FileNotFoundError("Endpoint not found for SFTP operation")
        creds = {
            "host": endpoint.sftp_host,
            "port": endpoint.sftp_port,
            "username": endpoint.sftp_username,
            "password": endpoint.sftp_password,
            "private_key_path": endpoint.sftp_private_key_path,
        }
    for field in _CREDENTIAL_FIELDS:
        value = config.get(field)
        if value not in (None, ""):
            creds[field] = value
    if not creds.get("host"):
        raise ValueError("An SFTP host is required")
    return creds


async def _connect(creds: dict) -> asyncssh.SSHClientConnection:
    async with _semaphore:
        return await asyncssh.connect(**_connect_kwargs(creds))


async def _close(connection) -> None:
    try:
        connection.close()
        await connection.wait_closed()
    except Exception:
        logger.debug("Error closing SFTP connection", exc_info=True)


def _join(path: str, name: str) -> str:
    base = (path or "/").rstrip("/") or "/"
    return f"{base}/{name}" if base != "/" else f"/{name}"


def _entry(name: str, stat) -> dict:
    modified = None
    mtime = getattr(stat, "mtime", 0) or 0
    if mtime:
        modified = datetime.fromtimestamp(mtime).isoformat(timespec="seconds")
    return {
        "name": name,
        "is_dir": bool(getattr(stat, "is_dir", lambda: False)()),
        "size": int(getattr(stat, "size", 0) or 0),
        "modified": modified,
    }


async def test_connection(db, config: dict) -> dict:
    """Attempt a connection and return ``{success, message}``."""
    creds = await _resolved_creds(db, config)
    connection = await _connect(creds)
    await _close(connection)
    return {
        "success": True,
        "message": f"Connected to {creds['host']} (port {creds.get('port') or 22})",
    }


async def list_remote_files(db, config: dict) -> dict:
    """Return ``{path, files: [{name, is_dir, size, modified}]}``."""
    creds = await _resolved_creds(db, config)
    return await list_files_with_creds(creds, config.get("remote_path") or "/")


def endpoint_creds(endpoint) -> dict:
    """Build connection credentials from an endpoint snapshot/row."""
    return {
        "host": getattr(endpoint, "sftp_host", None),
        "port": getattr(endpoint, "sftp_port", None),
        "username": getattr(endpoint, "sftp_username", None),
        "password": getattr(endpoint, "sftp_password", None),
        "private_key_path": getattr(endpoint, "sftp_private_key_path", None),
    }


async def list_files_with_creds(creds: dict, remote_path: str) -> dict:
    """List one remote directory using already-resolved credentials."""
    if not creds.get("host"):
        raise ValueError("An SFTP host is required")
    connection = await _connect(creds)
    try:
        sftp = await connection.start_sftp_client()
        try:
            names = await sftp.listdir(remote_path)
            files = []
            for name in names[: int(settings.SFTP_MAX_ENTRIES)]:
                full = _join(remote_path, name)
                try:
                    stat = await sftp.stat(full)
                except Exception:
                    stat = None
                files.append(_entry(name, stat))
            return {"path": remote_path, "files": files}
        finally:
            try:
                sftp.close()
            except Exception:
                pass
    finally:
        await _close(connection)


def _safe_filename(filename: str) -> str:
    """Reject traversal/absolute paths so reads stay inside ``remote_path``.

    Sub-directories such as ``2026-10/call.mp3`` are allowed, because the
    recorder may organise recordings by date.
    """
    name = str(filename or "").strip().replace("\\", "/")
    if not name:
        raise ValueError("A 'file' or 'filename' parameter is required")
    parts = name.split("/")
    if name.startswith("/") or any(part in ("", ".", "..") for part in parts):
        raise ValueError("The filename must be a relative path inside the remote path")
    return name


def _content_type(filename: str) -> str:
    import mimetypes

    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


# ---------------------------------------------------------------------------
# HTTP directory-index fallback
#
# Recorder hosts often serve the same SFTP directory with Apache's auto-index.
# That gives us a password-free, read-only path for list/play when the stored
# SFTP credential is missing, stale, or cannot be decrypted.
# ---------------------------------------------------------------------------

_APACHE_ROW_RE = re.compile(
    r'<td[^>]*>\s*<img\s+src="/icons/(?P<icon>[^"]+)"[^>]*>\s*</td>\s*'
    r'<td[^>]*>\s*<a\s+href="(?P<href>[^"]*)">(?P<label>.*?)</a>\s*</td>\s*'
    r'<td[^>]*>(?P<date>.*?)</td>\s*'
    r'<td[^>]*>(?P<size>.*?)</td>',
    re.IGNORECASE | re.DOTALL,
)

_SIZE_RE = re.compile(r"^([\d.]+)\s*([KMGTPE]?)i?B?$", re.IGNORECASE)


def password_looks_opaque(password: str | None) -> bool:
    """True when a stored secret is clearly not a usable plaintext password.

    A few legacy rows contain a base64 blob (for example a 32-byte hash)
    instead of an encrypted password. Trying an SFTP login with that value only
    burns the login timeout, so callers can prefer the HTTP index first.
    """
    value = str(password or "").strip()
    if not value or ":" in value:
        return False
    try:
        decoded = base64.b64decode(value, validate=True)
    except Exception:
        return False
    if len(decoded) < 16:
        return False
    printable = sum(1 for byte in decoded if 32 <= byte < 127)
    return printable < len(decoded) * 0.9


def _safe_rel_path(value: str, field_name: str = "path") -> str:
    """Normalise a relative path/label and reject absolute or traversing values."""
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    if text.startswith("/"):
        raise ValueError(f"The {field_name} must be a relative path")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ValueError(f"The {field_name} must not contain '..'")
    return "/".join(parts)


def _http_base(creds: dict, remote_path: str, subpath: str | None = None) -> str:
    """Build the read-only HTTP URL that mirrors the SFTP directory."""
    host = str(creds.get("host") or "").strip()
    if not host:
        raise ValueError("An SFTP host is required")
    port = int(settings.SFTP_HTTP_PORT)
    path = "/" + str(remote_path or "/").strip().lstrip("/")
    path = path.rstrip("/") or "/"
    if subpath:
        relative = _safe_rel_path(subpath)
        if relative:
            path = f"{path.rstrip('/')}/{relative}"
    path = path.rstrip("/") + "/"
    return f"http://{host}:{port}{quote(path, safe='/')}"


def _child_url(base: str, name: str) -> str:
    return f"{base.rstrip('/')}/{quote(name, safe='')}/"


def _parse_size(text: str) -> int:
    value = html.unescape(str(text or "")).strip().replace(",", "")
    if not value or value == "-":
        return 0
    match = _SIZE_RE.match(value)
    if not match:
        return 0
    try:
        number = float(match.group(1))
    except ValueError:
        return 0
    unit = match.group(2).upper()
    factor = {
        "": 1,
        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
        "T": 1024**4,
        "P": 1024**5,
        "E": 1024**6,
    }[unit]
    return int(number * factor)


def _parse_modified(text: str) -> str | None:
    value = html.unescape(str(text or "")).strip()
    if not value or value in ("-", "&nbsp;"):
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%d-%b-%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).isoformat(timespec="seconds")
        except ValueError:
            continue
    return value


def _parse_apache_entry(line: str) -> dict | None:
    """Parse one ``mod_autoindex`` table row, or return ``None`` to skip it."""
    match = _APACHE_ROW_RE.search(line or "")
    if not match:
        return None
    icon = match.group("icon").lower()
    if "back" in icon or "blank" in icon:
        return None
    href = html.unescape(match.group("href")).strip()
    if not href or href.startswith(("?", "/", "http://", "https://", "mailto:")):
        return None
    is_dir = "folder" in icon or href.endswith("/")
    name = unquote(href.rstrip("/"))
    if not name or name in (".", ".."):
        return None
    return {
        "name": name,
        "is_dir": is_dir,
        "size": 0 if is_dir else _parse_size(match.group("size")),
        "modified": _parse_modified(match.group("date")),
    }


async def _fetch_index(
    client: httpx.AsyncClient, url: str, limit: int
) -> list[dict]:
    """Stream an Apache index and stop as soon as ``limit`` rows are read."""
    separator = "&" if "?" in url else "?"
    sorted_url = f"{url}{separator}C=M;O=D"
    entries: list[dict] = []
    timeout = float(settings.SFTP_HTTP_TIMEOUT_SECONDS)
    async with client.stream(
        "GET", sorted_url, timeout=timeout, follow_redirects=True
    ) as response:
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code} from {sorted_url}")
        async for line in response.aiter_lines():
            entry = _parse_apache_entry(line)
            if entry is None:
                continue
            entries.append(entry)
            if len(entries) >= limit:
                break
    return entries


async def list_files_via_http(
    creds: dict,
    remote_path: str,
    *,
    subpath: str | None = None,
    max_entries: int | None = None,
    depth: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """List recordings via the host's read-only Apache directory index."""
    base = _http_base(creds, remote_path, subpath)
    limit = int(max_entries or settings.SFTP_MAX_ENTRIES)
    max_depth = int(
        depth if depth is not None else settings.SFTP_HTTP_LIST_DEPTH
    )
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    files: list[dict] = []
    truncated = False
    queue: list[tuple[str, str, int]] = [(base, "", 0)]
    seen: set[str] = set()
    try:
        while queue and len(files) < limit:
            url, prefix, level = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            try:
                entries = await _fetch_index(client, url, limit - len(files))
            except Exception:
                if not files and not queue:
                    raise
                logger.warning(
                    "HTTP SFTP fallback: cannot list %s", url, exc_info=True
                )
                continue
            for entry in entries:
                name = str(entry["name"])
                relative = f"{prefix}{name}"
                if entry["is_dir"]:
                    if level < max_depth:
                        queue.append(
                            (_child_url(url, name), f"{relative}/", level + 1)
                        )
                    continue
                files.append(
                    {
                        "name": name,
                        "path": relative,
                        "is_dir": False,
                        "size": entry["size"],
                        "modified": entry["modified"],
                    }
                )
                if len(files) >= limit:
                    truncated = True
                    break
            if len(files) >= limit:
                truncated = True
                break
        return {
            "path": remote_path,
            "base_url": base,
            "files": files,
            "truncated": truncated,
            "transport": "http",
        }
    finally:
        if own_client:
            await client.aclose()


def _content_range_total(response: httpx.Response) -> int | None:
    value = response.headers.get("content-range") or ""
    match = re.search(r"/\s*(\d+)\s*$", value)
    if match:
        return int(match.group(1))
    length = response.headers.get("content-length")
    if length and str(length).strip().isdigit():
        return int(length)
    return None


async def _stream_file(
    client: httpx.AsyncClient, url: str, name: str, max_bytes: int
) -> dict:
    limit = max(0, int(max_bytes))
    headers = {"Range": f"bytes=0-{max(0, limit - 1)}"}
    timeout = float(settings.SFTP_HTTP_TIMEOUT_SECONDS)
    async with client.stream(
        "GET",
        url,
        headers=headers,
        timeout=timeout,
        follow_redirects=True,
    ) as response:
        if response.status_code == 404:
            raise FileNotFoundError(url)
        if response.status_code not in (200, 206):
            raise RuntimeError(f"HTTP {response.status_code} from {url}")
        total = _content_range_total(response)
        content_type = response.headers.get("content-type") or _content_type(name)
        data = bytearray()
        async for chunk in response.aiter_bytes():
            if not chunk:
                continue
            remaining = limit - len(data)
            if remaining <= 0:
                break
            data.extend(chunk[:remaining])
            if len(data) >= limit:
                break
        return {
            "filename": name,
            "content": bytes(data),
            "size": total if total is not None else len(data),
            "truncated": bool(
                (total is not None and total > len(data))
                or (limit > 0 and len(data) >= limit)
            ),
            "content_type": content_type,
        }


async def read_file_via_http(
    creds: dict,
    remote_path: str,
    filename: str,
    max_bytes: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Read one recording via HTTP, falling back to sub-directory lookup."""
    name = _safe_filename(filename)
    base = _http_base(creds, remote_path)
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    candidates = [f"{base}{quote(name, safe='/')}"]
    if "/" not in name:
        try:
            for entry in await _fetch_index(client, base, 200):
                if entry["is_dir"]:
                    candidates.append(
                        f"{base}{quote(entry['name'], safe='')}/"
                        f"{quote(name, safe='')}"
                    )
        except Exception:
            logger.debug(
                "HTTP SFTP fallback: cannot inspect %s for %r", base, name
            )
    seen: set[str] = set()
    last_error: Exception | None = None
    try:
        for url in candidates:
            if url in seen:
                continue
            seen.add(url)
            try:
                result = await _stream_file(client, url, name, max_bytes)
            except FileNotFoundError as exc:
                last_error = exc
                continue
            result["url"] = url
            result["transport"] = "http"
            return result
        raise FileNotFoundError(
            f"{name!r} was not found under {remote_path} on "
            f"{creds.get('host')}"
            + (f" (last error: {last_error})" if last_error else "")
        )
    finally:
        if own_client:
            await client.aclose()


async def read_file_with_creds(
    creds: dict, remote_path: str, filename: str, max_bytes: int
) -> dict:
    """Read a remote file (bounded) using already-resolved credentials."""
    if not creds.get("host"):
        raise ValueError("An SFTP host is required")
    name = _safe_filename(filename)
    full = _join((remote_path or "/").rstrip("/") or "/", name)
    connection = await _connect(creds)
    try:
        sftp = await connection.start_sftp_client()
        try:
            total = None
            try:
                total = int((await sftp.stat(full)).size or 0)
            except Exception:
                pass
            async with sftp.open(full, "rb") as handle:
                data = await handle.read(int(max_bytes))
            return {
                "filename": name,
                "content": data,
                "size": total if total is not None else len(data),
                "truncated": bool(total is not None and total > len(data)),
                "content_type": _content_type(name),
            }
        finally:
            try:
                sftp.close()
            except Exception:
                pass
    finally:
        await _close(connection)


async def list_file_preview(db, config: dict) -> dict:
    """Read up to the configured byte cap of a remote file for previewing."""
    creds = await _resolved_creds(db, config)
    remote_path = config.get("remote_path") or "/"
    filename = config.get("filename") or ""
    full = _join(remote_path, filename)
    connection = await _connect(creds)
    try:
        sftp = await connection.start_sftp_client()
        try:
            total_size = None
            try:
                total_size = int((await sftp.stat(full)).size or 0)
            except Exception:
                pass
            async with sftp.open(full, "rb") as handle:
                data = await handle.read(int(settings.SFTP_PREVIEW_MAX_BYTES))
            content = data.decode("utf-8", errors="replace")
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            file_type = "csv" if ext == "csv" else "json"
            return {
                "filename": filename,
                "file_type": file_type,
                "content": content,
                "size": total_size if total_size is not None else len(data),
            }
        finally:
            try:
                sftp.close()
            except Exception:
                pass
    finally:
        await _close(connection)
