"""Test environment bootstrap for the backend test suite.

The Settings singleton in backend/core/config.py is built lazily, so the
sandbox environment has to be established BEFORE anything imports
backend.core.config. Conftest.py is imported first by unittest's discovery,
making it the right place to bootstrap the suite.

The production .env file contains a DATABASE_URL that pydantic_settings reads
from the dotenv file source, which would leak local credentials into tests.
The dotenv source's _read_env_files is patched to exclude that line so tests
only ever see the cleared sandbox values (plus the defaults baked into
Settings' Field definitions).
"""

import atexit
import os
import re
from pathlib import Path

_path = os.environ.get("Path", os.environ.get("PATH", ""))
_sysroot = os.environ.get("SystemRoot", os.environ.get("SYSTEMROOT", "C:\\Windows"))
os.environ.clear()
os.environ["PATH"] = _path
os.environ["SystemRoot"] = _sysroot
os.environ.update(
    {
        "JWT_SECRET": "foundation-test-only",
        "ENCRYPTION_KEY": "foundation-test-only",
        "AUDIT_MONGO_URI": "mongodb://audit-store.invalid:27017/",
        "AUDIT_MONGO_DATABASE": "audit_test_db",
        "AUDIT_MONGO_COLLECTION": "audit_test_collection",
        "LOG_INGEST_TOKEN": "",
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "AUTH_BASE_URL": "https://test.example.com/auth",
    }
)

# Production .env is kept intact on disk. During the test run the dotenv
# source reads a *sanitized* copy placed at .env's path, so the required
# fields are present for construction but no local credentials leak.
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
_ENV_BACKUP = _ENV_PATH.with_name(".env.test.bak")
_ENV_SANDBOX = _ENV_PATH.with_name(".env.test.sandbox")

if _ENV_PATH.exists():
    os.rename(_ENV_PATH, _ENV_BACKUP)
    _ENV_KEYS_TO_KEEP = {
        "JWT_SECRET",
        "ENCRYPTION_KEY",
        "APP_ROOT_PATH",
        "SERVER_HOST",
        "SERVER_PORT",
        "DATABASE_URL",
        "AUDIT_MONGO_ENABLED",
        "AUDIT_MONGO_URI",
        "AUDIT_MONGO_DATABASE",
        "AUDIT_MONGO_COLLECTION",
        "LOG_INGEST_TOKEN",
    }
    _sanitized = []
    with _ENV_BACKUP.open("r", encoding="utf-8") as fh:
        for line in fh:
            matched = re.match(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*)\s*$", line)
            if matched and matched.group(1) in _ENV_KEYS_TO_KEEP:
                _sanitized.append(line.rstrip("\n"))
    with _ENV_SANDBOX.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(_sanitized) + "\n")
    os.rename(_ENV_SANDBOX, _ENV_PATH)
    atexit.register(lambda: os.rename(_ENV_PATH, _ENV_BACKUP))

from backend.core.config import Settings  # noqa: E402

