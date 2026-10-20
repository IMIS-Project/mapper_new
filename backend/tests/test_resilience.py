import asyncio
import base64
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from pydantic_settings import DotEnvSettingsSource

with (
    patch.dict(
        os.environ,
        {
            "JWT_SECRET": "test",
            "ENCRYPTION_KEY": "test",
            "AUTH_BASE_URL": "https://auth.test",
            "AUDIT_MONGO_URI": "mongodb://audit-store.invalid:27017/",
            "AUDIT_MONGO_DATABASE": "audit_test_db",
            "AUDIT_MONGO_COLLECTION": "audit_test_collection",
        },
        clear=True,
    ),
    patch.object(DotEnvSettingsSource, "_read_env_files", return_value={}),
):
    from backend.api.health_router import health
    from backend.middleware.rate_limit import RateLimitMiddleware
    from backend.models import CallStatusEnum
    from backend.services import log_service
    from backend.services.circuit_breaker import CircuitBreaker, CircuitState
    from backend.services.dedup import DedupCache
    from backend.services.gateway_engine import GatewayEngine
    from backend.services.mock_service import build_mock_result
    from backend.services.rate_limiter import RateLimiter
    from backend.services.webhook_service import event_for_result
    from test_foundations import (
        endpoint_snapshot,
        make_client,
        make_db,
    )


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("10.0.0.5", 1234),
            "server": ("test.local", 80),
        }
    )


class RateLimiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_allows_up_to_budget_then_rejects(self):
        limiter = RateLimiter(window_seconds=10)
        for _ in range(3):
            self.assertTrue((await limiter.check("ep", 3)).allowed)
        decision = await limiter.check("ep", 3)
        self.assertFalse(decision.allowed)
        self.assertGreater(decision.retry_after, 0)

    async def test_zero_budget_blocks_everything(self):
        limiter = RateLimiter()
        self.assertFalse((await limiter.check("ep", 0)).allowed)

    async def test_none_budget_falls_back_to_default(self):
        limiter = RateLimiter()
        self.assertTrue((await limiter.check("ep", None)).allowed)

    async def test_window_expires_and_allows_again(self):
        limiter = RateLimiter(window_seconds=0.05)
        await limiter.check("ep", 1)
        self.assertFalse((await limiter.check("ep", 1)).allowed)
        await asyncio.sleep(0.1)
        self.assertTrue((await limiter.check("ep", 1)).allowed)


class CircuitBreakerTests(unittest.IsolatedAsyncioTestCase):
    async def test_opens_after_threshold_failures(self):
        breaker = CircuitBreaker(
            failure_threshold=3, window_seconds=60, recovery_timeout=0.1
        )
        for _ in range(3):
            self.assertTrue(await breaker.allow("ep"))
            await breaker.record_failure("ep")
        self.assertEqual(breaker.state("ep"), CircuitState.OPEN)
        self.assertFalse(await breaker.allow("ep"))

    async def test_recovers_to_half_open_then_closes_on_success(self):
        breaker = CircuitBreaker(
            failure_threshold=2, window_seconds=60, recovery_timeout=0.05
        )
        await breaker.record_failure("ep")
        await breaker.record_failure("ep")
        self.assertEqual(breaker.state("ep"), CircuitState.OPEN)
        self.assertFalse(await breaker.allow("ep"))
        await asyncio.sleep(0.1)
        self.assertTrue(await breaker.allow("ep"))
        self.assertEqual(breaker.state("ep"), CircuitState.HALF_OPEN)
        await breaker.record_success("ep")
        self.assertEqual(breaker.state("ep"), CircuitState.CLOSED)
        self.assertTrue(await breaker.allow("ep"))

    async def test_failure_during_half_open_retrips(self):
        breaker = CircuitBreaker(
            failure_threshold=1, window_seconds=60, recovery_timeout=0.01
        )
        await breaker.record_failure("ep")
        await asyncio.sleep(0.02)
        self.assertTrue(await breaker.allow("ep"))
        await breaker.record_failure("ep")
        self.assertEqual(breaker.state("ep"), CircuitState.OPEN)
        self.assertFalse(await breaker.allow("ep"))


class DedupCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_identical_request_replays_cached_result(self):
        cache = DedupCache(ttl_seconds=5, max_entries=100)
        self.assertIsNone(await cache.get("ep", {"a": 1}))
        await cache.set("ep", {"a": 1}, {"request_id": "x", "success": True})
        self.assertEqual((await cache.get("ep", {"a": 1}))["request_id"], "x")

    async def test_key_is_order_insensitive(self):
        cache = DedupCache(ttl_seconds=5)
        await cache.set("ep", {"a": 1, "b": 2}, {"request_id": "y"})
        self.assertEqual((await cache.get("ep", {"b": 2, "a": 1}))["request_id"], "y")

    async def test_expired_entries_are_dropped(self):
        cache = DedupCache(ttl_seconds=0.05, max_entries=10)
        await cache.set("ep", {"a": 1}, {"request_id": "z"})
        await asyncio.sleep(0.1)
        self.assertIsNone(await cache.get("ep", {"a": 1}))


class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_healthy_report(self):
        db = MagicMock()
        db.execute = AsyncMock(return_value=None)
        body = await health(db=db)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["database"], "connected")
        self.assertIn("uptime_seconds", body)
        self.assertIn("platform", body)

    async def test_degraded_when_db_down(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=RuntimeError("db down"))
        body = await health(db=db)
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["database"], "unavailable")


class MiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_limit_returns_429(self):
        middleware = RateLimitMiddleware(FastAPI(), rpm=1)
        request = _request("/api/map-and-call")

        async def downstream(_request):
            return PlainTextResponse("ok")

        self.assertEqual(
            (await middleware.dispatch(request, downstream)).status_code, 200
        )
        self.assertEqual(
            (await middleware.dispatch(request, downstream)).status_code, 429
        )

    async def test_health_path_is_exempt(self):
        middleware = RateLimitMiddleware(FastAPI(), rpm=1)
        request = _request("/api/health")

        async def downstream(_request):
            return PlainTextResponse("ok")

        for _ in range(3):
            self.assertEqual(
                (await middleware.dispatch(request, downstream)).status_code, 200
            )


class WebhookClassificationTests(unittest.TestCase):
    def test_call_outcome_classification(self):
        self.assertEqual(event_for_result({"success": True}), "call_success")
        self.assertEqual(
            event_for_result({"success": False, "failure_kind": "upstream_timeout"}),
            "call_timeout",
        )
        self.assertEqual(
            event_for_result({"success": False, "failure_kind": "upstream_http"}),
            "call_failure",
        )


class LogServiceTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _log_row(log_id: int) -> tuple[SimpleNamespace, SimpleNamespace]:

        log = SimpleNamespace(
            id=log_id,
            endpoint_id=1,
            status=CallStatusEnum.FAILED.value,
            source_request_headers=None,
            source_request_payload=None,
            source_response=None,
            client_status_code=200,
            target_request_headers=None,
            target_request_payload=None,
            target_query_params=None,
            target_response=None,
            response_time_ms=12,
            upstream_status_code=500,
            created_at=None,
        )
        endpoint = SimpleNamespace(
            method="POST",
            source_api_url="https://source.test",
            target_api_url="https://target.test",
        )
        return log, endpoint

    async def test_list_logs_paginates_with_total(self):
        db = MagicMock()
        count = Mock()
        count.scalar.return_value = 7
        page = Mock()
        page.all.return_value = [self._log_row(1), self._log_row(2)]
        results = iter([count, page])

        async def execute(_statement):
            return next(results)

        db.execute = AsyncMock(side_effect=execute)
        total, items, page_no, per = await log_service.list_logs(
            db, status="failed", page=2, per_page=2
        )
        self.assertEqual(total, 7)
        self.assertEqual(len(items), 2)
        self.assertEqual(page_no, 2)
        self.assertEqual(per, 2)

    async def test_get_log_invalid_id_returns_none_without_query(self):
        db = MagicMock()
        db.execute = AsyncMock()
        self.assertIsNone(await log_service.get_log(db, "not-a-uuid"))
        db.execute.assert_not_awaited()

    async def test_invalid_status_filter_is_ignored(self):
        db = MagicMock()
        count = Mock()
        count.scalar.return_value = 0
        page = Mock()
        page.all.return_value = []
        results = iter([count, page])

        async def execute(_statement):
            return next(results)

        db.execute = AsyncMock(side_effect=execute)
        total, items, *_ = await log_service.list_logs(db, status="bogus")
        self.assertEqual(total, 0)
        self.assertEqual(items, [])


class LogOnlyEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_relative_source_url_skips_the_upstream_call(self):
        endpoint = endpoint_snapshot(source_api_url="/v1/audio/play", method="GET")
        client = make_client()

        outcome = await GatewayEngine(make_db(), client).execute_resolved(
            endpoint,
            {"draw": 1},
            {},
            "/v1/audio/play",
            "GET",
            mappings=(),
        )

        result = outcome.to_result()
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.source, "policy")
        self.assertFalse(outcome.upstream_attempted)
        self.assertIsNone(outcome.failure_kind)
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["status"], CallStatusEnum.SUCCESS.value)
        self.assertIsNone(result["error"])
        self.assertEqual(
            result["data"], {"message": "Log-only endpoint, no external call made"}
        )
        self.assertIsNone(result["external_request_url"])
        client.send.assert_not_awaited()

    async def test_absolute_source_url_still_reaches_the_upstream(self):
        client = make_client(status=200)

        outcome = await GatewayEngine(make_db(), client).execute_resolved(
            endpoint_snapshot(), {}, mappings=()
        )

        self.assertEqual(outcome.source, "live")
        self.assertTrue(outcome.upstream_attempted)
        client.send.assert_awaited()


class SftpFilenameTests(unittest.TestCase):
    def test_relative_names_only(self):
        from backend.services.sftp_service import _safe_filename

        self.assertEqual(_safe_filename("call.mp3"), "call.mp3")
        self.assertEqual(_safe_filename("2026-10/call.mp3"), "2026-10/call.mp3")
        for bad in ("", "/etc/passwd", "../secret", "a/../../b", "a//b", "."):
            with self.assertRaises(ValueError):
                _safe_filename(bad)


class SftpEndpointTests(unittest.IsolatedAsyncioTestCase):
    """SFTP-backed endpoints read the remote server instead of an HTTP upstream."""

    @staticmethod
    def _sftp_endpoint(**updates):
        values = dict(
            source_api_url="/v1/audio/list",
            target_api_url="/v1/audio/list",
            method="GET",
            protocol="SFTP",
            sftp_host="sftp.test",
            sftp_port=22,
            sftp_username="reader",
            sftp_password="secret",
            sftp_remote_path="/recordings",
        )
        values.update(updates)
        return endpoint_snapshot(**values)

    async def test_sftp_list_returns_remote_files(self):
        endpoint = self._sftp_endpoint()
        listing = {
            "path": "/recordings",
            "files": [{"name": "a.mp3", "is_dir": False, "size": 10, "modified": None}],
        }
        service = AsyncMock(return_value=listing)
        with patch(
            "backend.services.gateway_engine.sftp_service.list_files_with_creds",
            new=service,
        ):
            outcome = await GatewayEngine(make_db(), make_client()).execute_resolved(
                endpoint, {}, {}, "/v1/audio/list", "GET", mappings=()
            )

        result = outcome.to_result()
        self.assertTrue(outcome.success)
        self.assertTrue(outcome.upstream_attempted)
        self.assertIsNone(outcome.failure_kind)
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["data"]["operation"], "list")
        self.assertEqual(result["data"]["files"], listing["files"])
        self.assertEqual(
            result["external_request_url"], "sftp://sftp.test:22/recordings"
        )
        service.assert_awaited_once()

    async def test_sftp_play_returns_base64_audio(self):
        endpoint = self._sftp_endpoint(
            source_api_url="/v1/audio/play", target_api_url="/v1/audio/play"
        )
        service = AsyncMock(
            return_value={
                "filename": "a.mp3",
                "content": b"ID3-audio",
                "size": 9,
                "truncated": False,
                "content_type": "audio/mpeg",
            }
        )
        with patch(
            "backend.services.gateway_engine.sftp_service.read_file_with_creds",
            new=service,
        ):
            outcome = await GatewayEngine(make_db(), make_client()).execute_resolved(
                endpoint,
                {"file": "a.mp3"},
                {},
                "/v1/audio/play",
                "GET",
                mappings=(),
            )

        data = outcome.to_result()["data"]
        self.assertTrue(outcome.success)
        self.assertEqual(data["operation"], "play")
        self.assertEqual(data["filename"], "a.mp3")
        self.assertEqual(data["content_type"], "audio/mpeg")
        self.assertEqual(base64.b64decode(data["content_base64"]), b"ID3-audio")

    async def test_legacy_file_mapping_keeps_http_behaviour(self):
        # Old file mappings also say protocol=SFTP, but their target is an
        # absolute URL for another service; the gateway must not read them.
        endpoint = self._sftp_endpoint(
            source_api_url="https://upstream.test/items",
            target_api_url="http://127.0.0.1:9003/psp/api/items",
        )
        client = make_client(status=200)
        outcome = await GatewayEngine(make_db(), client).execute_resolved(
            endpoint, {}, {}, "/psp/api/items", "POST", mappings=()
        )

        self.assertFalse(endpoint.is_sftp)
        self.assertTrue(outcome.upstream_attempted)
        client.send.assert_awaited()

    async def test_sftp_failure_is_a_transport_failure(self):
        endpoint = self._sftp_endpoint()
        service = AsyncMock(side_effect=PermissionError("denied"))
        with patch(
            "backend.services.gateway_engine.sftp_service.list_files_with_creds",
            new=service,
        ):
            outcome = await GatewayEngine(make_db(), make_client()).execute_resolved(
                endpoint, {}, {}, "/v1/audio/list", "GET", mappings=()
            )

        result = outcome.to_result()
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.failure_kind, "transport")
        self.assertEqual(result["status_code"], 502)
        self.assertIn("SFTP error", result["error"])


class SftpHttpFallbackTests(unittest.IsolatedAsyncioTestCase):
    """Recorder hosts often expose the same directory through Apache HTTP."""

    @staticmethod
    def _sftp_endpoint(**updates):
        values = dict(
            source_api_url="/v1/audio/list",
            target_api_url="/v1/audio/list",
            method="GET",
            protocol="SFTP",
            sftp_host="sftp.test",
            sftp_port=22,
            sftp_username="reader",
            sftp_password="secret",
            sftp_remote_path="/recordings",
        )
        values.update(updates)
        return endpoint_snapshot(**values)

    def test_opaque_password_detection(self):
        from backend.services.sftp_service import password_looks_opaque

        opaque = base64.b64encode(b"\x87" + b"\x00" * 31).decode("ascii")
        self.assertTrue(password_looks_opaque(opaque))
        self.assertFalse(password_looks_opaque("correct horse battery staple"))
        self.assertFalse(password_looks_opaque("nonce:deadbeef"))
        self.assertFalse(password_looks_opaque(""))

    def test_apache_index_rows_parse(self):
        from backend.services.sftp_service import _parse_apache_entry

        audio = (
            '<tr><td valign="top"><img src="/icons/sound2.gif" alt="[SND]"></td>'
            '<td><a href="20260218-090000-03710314033-s.wav">'
            "20260218-090000-03710314033-s.wav</a></td>"
            '<td align="right">2026-02-18 09:00  </td>'
            '<td align="right"> 44 </td><td>&nbsp;</td></tr>'
        )
        parsed = _parse_apache_entry(audio)
        self.assertEqual(parsed["name"], "20260218-090000-03710314033-s.wav")
        self.assertFalse(parsed["is_dir"])
        self.assertEqual(parsed["size"], 44)
        self.assertEqual(parsed["modified"], "2026-02-18T09:00:00")

        folder = (
            '<tr><td valign="top"><img src="/icons/folder.gif" alt="[DIR]"></td>'
            '<td><a href="monitor/">monitor/</a></td>'
            '<td align="right">2026-10-20 00:10  </td>'
            '<td align="right">  - </td><td>&nbsp;</td></tr>'
        )
        parsed = _parse_apache_entry(folder)
        self.assertEqual(parsed["name"], "monitor")
        self.assertTrue(parsed["is_dir"])

        parent = (
            '<tr><td valign="top"><img src="/icons/back.gif" alt="[PARENTDIR]"></td>'
            '<td><a href="/recordings/">Parent Directory</a></td>'
            '<td>&nbsp;</td><td align="right">  - </td><td>&nbsp;</td></tr>'
        )
        self.assertIsNone(_parse_apache_entry(parent))

    def test_size_and_relative_path_helpers(self):
        from backend.services.sftp_service import _parse_size, _safe_rel_path

        self.assertEqual(_parse_size("44"), 44)
        self.assertEqual(_parse_size("1.5M"), int(1.5 * 1024**2))
        self.assertEqual(_parse_size("562K"), 562 * 1024)
        self.assertEqual(_parse_size("-"), 0)
        self.assertEqual(_safe_rel_path("testNew"), "testNew")
        self.assertEqual(_safe_rel_path("a/b"), "a/b")
        self.assertEqual(_safe_rel_path(""), "")
        for bad in ("/abs", "../x", "a/../b"):
            with self.assertRaises(ValueError):
                _safe_rel_path(bad)

    async def test_sftp_list_falls_back_to_http(self):
        endpoint = self._sftp_endpoint()
        sftp = AsyncMock(side_effect=PermissionError("denied"))
        listing = {
            "path": "/recordings",
            "base_url": "http://sftp.test:80/recordings/",
            "files": [
                {
                    "name": "a.wav",
                    "path": "testNew/a.wav",
                    "is_dir": False,
                    "size": 12,
                    "modified": None,
                }
            ],
            "truncated": False,
            "transport": "http",
        }
        http = AsyncMock(return_value=listing)
        with (
            patch(
                "backend.services.gateway_engine.sftp_service.list_files_with_creds",
                new=sftp,
            ),
            patch(
                "backend.services.gateway_engine.sftp_service.list_files_via_http",
                new=http,
            ),
        ):
            outcome = await GatewayEngine(make_db(), make_client()).execute_resolved(
                endpoint, {}, {}, "/v1/audio/list", "GET", mappings=()
            )

        result = outcome.to_result()
        self.assertTrue(outcome.success)
        self.assertIsNone(outcome.failure_kind)
        self.assertEqual(result["data"]["transport"], "http")
        self.assertEqual(result["data"]["files"], listing["files"])
        self.assertEqual(
            result["external_request_url"], "http://sftp.test:80/recordings/"
        )
        self.assertEqual(result["external_request_method"], "HTTP")
        http.assert_awaited_once()
        sftp.assert_awaited_once()

    async def test_sftp_play_falls_back_to_http(self):
        endpoint = self._sftp_endpoint(
            source_api_url="/v1/audio/play", target_api_url="/v1/audio/play"
        )
        sftp = AsyncMock(side_effect=PermissionError("denied"))
        http = AsyncMock(
            return_value={
                "filename": "a.wav",
                "content": b"RIFF-audio",
                "size": 10,
                "truncated": False,
                "content_type": "audio/x-wav",
                "url": "http://sftp.test:80/recordings/testNew/a.wav",
                "transport": "http",
            }
        )
        with (
            patch(
                "backend.services.gateway_engine.sftp_service.read_file_with_creds",
                new=sftp,
            ),
            patch(
                "backend.services.gateway_engine.sftp_service.read_file_via_http",
                new=http,
            ),
        ):
            outcome = await GatewayEngine(make_db(), make_client()).execute_resolved(
                endpoint,
                {"file": "testNew/a.wav"},
                {},
                "/v1/audio/play",
                "GET",
                mappings=(),
            )

        result = outcome.to_result()
        data = result["data"]
        self.assertTrue(outcome.success)
        self.assertEqual(data["transport"], "http")
        self.assertEqual(data["content_type"], "audio/x-wav")
        self.assertEqual(base64.b64decode(data["content_base64"]), b"RIFF-audio")
        self.assertEqual(
            result["external_request_url"],
            "http://sftp.test:80/recordings/testNew/a.wav",
        )
        http.assert_awaited_once()

    async def test_opaque_password_prefers_http(self):
        opaque = base64.b64encode(b"\x87" + b"\x00" * 31).decode("ascii")
        endpoint = self._sftp_endpoint(sftp_password=opaque)
        sftp = AsyncMock()
        http = AsyncMock(
            return_value={
                "path": "/recordings",
                "base_url": "http://sftp.test:80/recordings/",
                "files": [],
                "truncated": False,
                "transport": "http",
            }
        )
        with (
            patch(
                "backend.services.gateway_engine.sftp_service.list_files_with_creds",
                new=sftp,
            ),
            patch(
                "backend.services.gateway_engine.sftp_service.list_files_via_http",
                new=http,
            ),
        ):
            outcome = await GatewayEngine(make_db(), make_client()).execute_resolved(
                endpoint, {}, {}, "/v1/audio/list", "GET", mappings=()
            )

        self.assertTrue(outcome.success)
        http.assert_awaited_once()
        sftp.assert_not_awaited()


class EndpointAuthTests(unittest.IsolatedAsyncioTestCase):
    """Only APIs marked as requiring auth receive the caller/job token."""

    @staticmethod
    def _endpoint(**updates):
        values = dict(
            source_api_url="https://upstream.test/items",
            target_api_url="https://gateway.test/v1/items",
            method="POST",
        )
        values.update(updates)
        return endpoint_snapshot(**values)

    async def test_require_authentication_false_drops_caller_token(self):
        client = make_client(status=200)
        outcome = await GatewayEngine(make_db(), client).execute_resolved(
            self._endpoint(require_authentication=False),
            {"a": 1},
            {
                "Authorization": "Bearer cron-token",
                "X-Api-Key": "secret",
                "X-Trace": "trace-1",
            },
            "/v1/items",
            "POST",
            mappings=(),
        )

        self.assertTrue(outcome.success)
        request = client.send.await_args.args[0]
        headers = {name.lower(): value for name, value in request.headers.items()}
        self.assertNotIn("authorization", headers)
        self.assertNotIn("x-api-key", headers)
        self.assertEqual(headers.get("x-trace"), "trace-1")

    async def test_require_authentication_false_skips_injection(self):
        auth = AsyncMock(return_value=True)
        with patch(
            "backend.services.gateway_engine.apply_upstream_auth", new=auth
        ):
            outcome = await GatewayEngine(make_db(), make_client()).execute_resolved(
                self._endpoint(require_authentication=False),
                {"a": 1},
                {},
                "/v1/items",
                "POST",
                mappings=(),
            )

        self.assertTrue(outcome.success)
        auth.assert_not_awaited()

    async def test_require_authentication_true_keeps_caller_token(self):
        client = make_client(status=200)
        outcome = await GatewayEngine(make_db(), client).execute_resolved(
            self._endpoint(require_authentication=True),
            {"a": 1},
            {"Authorization": "Bearer caller-token"},
            "/v1/items",
            "POST",
            mappings=(),
        )

        self.assertTrue(outcome.success)
        request = client.send.await_args.args[0]
        self.assertEqual(
            request.headers.get("authorization"), "Bearer caller-token"
        )

    async def test_missing_flag_keeps_previous_behaviour(self):
        client = make_client(status=200)
        outcome = await GatewayEngine(make_db(), client).execute_resolved(
            self._endpoint(require_authentication=None),
            {"a": 1},
            {"Authorization": "Bearer caller-token"},
            "/v1/items",
            "POST",
            mappings=(),
        )

        self.assertTrue(outcome.success)
        request = client.send.await_args.args[0]
        self.assertEqual(
            request.headers.get("authorization"), "Bearer caller-token"
        )

    def test_strip_auth_headers_keeps_non_auth_headers(self):
        from backend.services.upstream_auth import strip_auth_headers

        headers = {
            "Authorization": "Bearer token",
            "X-Api-Key": "key",
            "X-Auth-Token": "token",
            "X-Trace": "trace-1",
            "Content-Type": "application/json",
        }
        strip_auth_headers(headers)
        self.assertEqual(
            headers,
            {"X-Trace": "trace-1", "Content-Type": "application/json"},
        )

    async def test_shared_token_is_scoped_to_configured_hosts(self):
        from backend.core.config import settings
        from backend.services import upstream_auth

        client = Mock(spec=httpx.AsyncClient)
        with (
            patch.object(
                settings, "UPSTREAM_AUTH_URL", "https://auth.test/login"
            ),
            patch.object(settings, "UPSTREAM_API_TOKENS", {}),
            patch.object(upstream_auth, "_configured", return_value=True),
            patch.object(
                upstream_auth,
                "_cached_token",
                new=AsyncMock(return_value="shared-token"),
            ),
        ):
            headers: dict[str, str] = {}
            injected = await upstream_auth.apply_upstream_auth(
                headers,
                client,
                "https://unrelated.test/api",
                allow_shared=False,
            )
            self.assertFalse(injected)
            self.assertNotIn("Authorization", headers)

            headers = {}
            injected = await upstream_auth.apply_upstream_auth(
                headers,
                client,
                "https://unrelated.test/api",
                allow_shared=True,
            )
            self.assertTrue(injected)
            self.assertIn("Authorization", headers)

            headers = {}
            injected = await upstream_auth.apply_upstream_auth(
                headers,
                client,
                "https://auth.test/api",
                allow_shared=False,
            )
            self.assertTrue(injected)
            self.assertIn("Authorization", headers)


class MockShortCircuitTests(unittest.IsolatedAsyncioTestCase):
    async def test_mock_returns_configured_response_without_upstream(self):
        endpoint = endpoint_snapshot(
            mock_enabled=True, mock_response={"hello": [1, 2, 3]}
        )
        client = make_client()
        engine = GatewayEngine(make_db(), client)
        outcome = await engine.execute_resolved(
            endpoint, {"a": 1}, {}, "/v1/items", "POST"
        )
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.source, "mock")
        self.assertEqual(outcome.to_result()["status_code"], 200)
        self.assertEqual(outcome.to_result()["data"], {"hello": [1, 2, 3]})
        client.send.assert_not_awaited()

    def test_build_mock_result_sets_success_audit_envelope(self):
        endpoint = endpoint_snapshot(mock_enabled=True, mock_response={"ok": True})
        result = build_mock_result(
            endpoint,
            request_id="rid",
            method="POST",
            url="/v1/items",
            headers={"X": "1"},
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["data"], {"ok": True})
        self.assertIn("external_request_url", result)


if __name__ == "__main__":
    unittest.main()
