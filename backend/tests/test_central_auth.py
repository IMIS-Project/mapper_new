import json
import unittest
from unittest.mock import patch

import httpx

from backend.services import central_auth

_KEY = "k" * 32


class CentralAuthProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        central_auth._TOKEN_CACHE.clear()
        self.settings_patch = patch.multiple(
            central_auth.settings,
            AUTH_BASE_URL="https://central.test/auth",
            AUTH_SERVICE_ENCRYPTION_KEY=_KEY,
            AUTH_RETRY_ATTEMPTS=3,
            AUTH_RETRY_BACKOFF_SECONDS=0.0,
            AUTH_TOKEN_CACHE_SECONDS=30.0,
        )
        self.settings_patch.start()

    def tearDown(self):
        self.settings_patch.stop()
        central_auth._TOKEN_CACHE.clear()

    def test_encrypt_decrypt_round_trip_uses_nonce_tag_ciphertext_layout(self):
        encrypted = central_auth.encrypt_auth_json({"email": "u", "password": "p"})
        self.assertEqual(
            central_auth.decrypt_auth_json(encrypted),
            {"email": "u", "password": "p"},
        )

    async def test_login_gets_pre_auth_token_and_decrypts_central_response(self):
        calls = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url.path == "/auth/get_token":
                return httpx.Response(
                    200,
                    json={
                        "status": "success",
                        "code": 200,
                        "message": "ok",
                        "data": {"token": "pre-auth"},
                    },
                )
            if request.url.path == "/auth/auth1/login":
                self.assertEqual(request.headers["authorization"], "Bearer pre-auth")
                body = json.loads(request.content)
                self.assertEqual(
                    central_auth.decrypt_auth_json(body["encrypted_data"]),
                    {
                        "email": "user@example.com",
                        "password": "secret",
                        "interface_type": "W",
                    },
                )
                return httpx.Response(
                    200,
                    json={
                        "encrypted_data": central_auth.encrypt_auth_json(
                            {
                                "status": "success",
                                "code": 200,
                                "message": "ok",
                                "data": {
                                    "user": {
                                        "id": 7,
                                        "name": "Test User",
                                        "email": "user@example.com",
                                        "roles": ["Admin"],
                                    },
                                    "access_token": "access",
                                    "refresh_token": "refresh",
                                    "access_token_expires_in": 900,
                                },
                            }
                        )
                    },
                )
            return httpx.Response(404, json={"detail": "not found"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://central.test",
        ) as client:
            session = await central_auth.central_login(
                client, "user@example.com", "secret"
            )

        self.assertEqual(
            [request.url.path for request in calls],
            [
                "/auth/get_token",
                "/auth/auth1/login",
            ],
        )
        self.assertEqual(session.access_token, "access")
        self.assertEqual(session.refresh_token, "refresh")
        self.assertEqual(session.user.id, 7)
        self.assertEqual(session.user.roles, ["Admin"])

    async def test_permissions_validates_access_token_and_normalizes_user(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/auth/auth1/permissions")
            self.assertEqual(request.headers["authorization"], "Bearer access")
            return httpx.Response(
                200,
                json={
                    "encrypted_data": central_auth.encrypt_auth_json(
                        {
                            "status": "success",
                            "code": 200,
                            "message": "ok",
                            "data": {
                                "user": {
                                    "id": 7,
                                    "name": "Test User",
                                    "email": "user@example.com",
                                    "roles": ["Admin"],
                                    "is_super_admin": True,
                                },
                                "permissions_by_program": {"1": {"read": True}},
                            },
                        }
                    )
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://central.test",
        ) as client:
            user = await central_auth.validate_access_token(client, "access")

        self.assertEqual(user.id, 7)
        self.assertEqual(user.roles, ["Admin"])
        self.assertTrue(user.is_super_admin)
        self.assertEqual(user.permissions, {"1": {"read": True}})

    async def test_encrypted_central_error_is_mapped_to_rejection(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/auth/get_token":
                return httpx.Response(200, json={"data": {"token": "pre-auth"}})
            return httpx.Response(
                401,
                json={
                    "encrypted_data": central_auth.encrypt_auth_json(
                        {
                            "status": "error",
                            "code": 401,
                            "message": "Invalid username or password",
                            "data": None,
                        }
                    )
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://central.test",
        ) as client:
            with self.assertRaises(central_auth.CentralAuthRejected) as raised:
                await central_auth.central_login(client, "bad@example.com", "bad")

        self.assertEqual(raised.exception.status_code, 401)
        self.assertIn("Invalid username", raised.exception.message)


class CentralAuthResilienceTests(unittest.IsolatedAsyncioTestCase):
    """The central service is external: blips must not become hard failures."""

    def setUp(self):
        central_auth._TOKEN_CACHE.clear()
        self.settings_patch = patch.multiple(
            central_auth.settings,
            AUTH_BASE_URL="https://central.test/auth",
            AUTH_SERVICE_ENCRYPTION_KEY=_KEY,
            AUTH_RETRY_ATTEMPTS=3,
            AUTH_RETRY_BACKOFF_SECONDS=0.0,
            AUTH_TOKEN_CACHE_SECONDS=30.0,
        )
        self.settings_patch.start()

    def tearDown(self):
        self.settings_patch.stop()
        central_auth._TOKEN_CACHE.clear()

    @staticmethod
    def _login_success(user_id: int = 7) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "encrypted_data": central_auth.encrypt_auth_json(
                    {
                        "status": "success",
                        "code": 200,
                        "message": "ok",
                        "data": {
                            "user": {"id": user_id, "name": "Test", "roles": ["Admin"]},
                            "access_token": "access",
                            "refresh_token": "refresh",
                            "access_token_expires_in": 900,
                        },
                    }
                )
            },
        )

    async def test_get_token_5xx_is_retried_before_succeeding(self):
        get_token_calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal get_token_calls
            if request.url.path == "/auth/get_token":
                get_token_calls += 1
                if get_token_calls < 3:
                    return httpx.Response(503, json={"detail": "overloaded"})
                return httpx.Response(200, json={"data": {"token": "pre-auth"}})
            return self._login_success()

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://central.test",
        ) as client:
            session = await central_auth.central_login(client, "u", "p")

        self.assertEqual(session.access_token, "access")
        self.assertEqual(get_token_calls, 3)

    async def test_transport_error_is_retried(self):
        attempts = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.ConnectError("connection reset", request=request)
            if request.url.path == "/auth/get_token":
                return httpx.Response(200, json={"data": {"token": "pre-auth"}})
            return self._login_success()

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://central.test",
        ) as client:
            session = await central_auth.central_login(client, "u", "p")

        self.assertEqual(session.access_token, "access")
        self.assertGreaterEqual(attempts, 2)

    async def test_persistent_5xx_becomes_unavailable(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"detail": "down"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://central.test",
        ) as client:
            with self.assertRaises(central_auth.CentralAuthUnavailable) as raised:
                await central_auth.central_login(client, "u", "p")

        self.assertEqual(raised.exception.status_code, 503)

    async def test_rate_limit_is_not_retried_and_maps_to_429(self):
        login_calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal login_calls
            if request.url.path == "/auth/get_token":
                return httpx.Response(200, json={"data": {"token": "pre-auth"}})
            login_calls += 1
            return httpx.Response(
                429,
                headers={"Retry-After": "300"},
                json={
                    "encrypted_data": central_auth.encrypt_auth_json(
                        {
                            "status": "error",
                            "code": 429,
                            "message": "Too many requests",
                            "data": None,
                        }
                    )
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://central.test",
        ) as client:
            with self.assertRaises(central_auth.CentralAuthRateLimited) as raised:
                await central_auth.central_login(client, "u", "p")

        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.retry_after, 300)
        self.assertEqual(login_calls, 1)

    async def test_identity_is_cached_across_requests(self):
        permissions_calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal permissions_calls
            permissions_calls += 1
            return httpx.Response(
                200,
                json={
                    "encrypted_data": central_auth.encrypt_auth_json(
                        {
                            "status": "success",
                            "code": 200,
                            "data": {"user": {"id": 7, "name": "Test"}},
                        }
                    )
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://central.test",
        ) as client:
            first = await central_auth.validate_access_token(client, "access")
            second = await central_auth.validate_access_token(client, "access")

        self.assertEqual(first.id, second.id)
        self.assertEqual(permissions_calls, 1)

    async def test_identity_cache_can_be_disabled(self):
        permissions_calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal permissions_calls
            permissions_calls += 1
            return httpx.Response(
                200,
                json={
                    "encrypted_data": central_auth.encrypt_auth_json(
                        {
                            "status": "success",
                            "code": 200,
                            "data": {"user": {"id": 7, "name": "Test"}},
                        }
                    )
                },
            )

        with patch.object(central_auth.settings, "AUTH_TOKEN_CACHE_SECONDS", 0.0):
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="https://central.test",
            ) as client:
                await central_auth.validate_access_token(client, "access")
                await central_auth.validate_access_token(client, "access")

        self.assertEqual(permissions_calls, 2)

    async def test_logout_invalidates_the_cached_identity(self):
        permissions_calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal permissions_calls
            if request.url.path == "/auth/auth1/logout":
                return httpx.Response(200, json={"status": "success", "code": 200})
            permissions_calls += 1
            return httpx.Response(
                200,
                json={
                    "encrypted_data": central_auth.encrypt_auth_json(
                        {
                            "status": "success",
                            "code": 200,
                            "data": {"user": {"id": 7, "name": "Test"}},
                        }
                    )
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://central.test",
        ) as client:
            await central_auth.validate_access_token(client, "access")
            await central_auth.central_logout(client, "access")
            await central_auth.validate_access_token(client, "access")

        self.assertEqual(permissions_calls, 2)

    def test_aes_key_accepts_base64_hex_and_raw(self):
        import base64 as b64

        raw = b"0123456789abcdef0123456789abcdef"
        self.assertEqual(central_auth._process_aes_key(b64.b64encode(raw).decode()), raw)
        self.assertEqual(central_auth._process_aes_key(raw.hex()), raw)
        self.assertEqual(central_auth._process_aes_key(raw.decode()), raw)

    def test_missing_or_wrong_length_key_is_unavailable(self):
        with self.assertRaises(central_auth.CentralAuthUnavailable):
            central_auth._process_aes_key("")
        with self.assertRaises(central_auth.CentralAuthUnavailable):
            central_auth._process_aes_key("too-short")


if __name__ == "__main__":
    unittest.main()
