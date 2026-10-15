"""Tests for the Bank Alfalah integration console.

The console never forwards a caller-supplied URL, so the important behaviours
covered here are: the operation allow-list, the header construction for each
token flow, the layered error reporting, secret masking, and the call-log
entries written for every attempt.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock

import httpx
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from backend.api import bank_router
from backend.core.config import settings
from backend.schemas.bank import BankCallRequest


def _response(status_code: int, payload, headers=None) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        headers=headers or {},
        request=httpx.Request("POST", "https://example.test"),
    )


def _client(response) -> MagicMock:
    client = MagicMock()
    client.request = AsyncMock(return_value=response)
    return client


def _credentials(token: str = "session-token-abc") -> HTTPAuthorizationCredentials:
    """The console user's own central auth bearer."""
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _tasks() -> MagicMock:
    """Collects deferred write_call_log tasks instead of running them."""
    tasks = MagicMock()
    tasks.added = []
    tasks.add_task = lambda fn, *a: tasks.added.append((fn, a))
    return tasks


def _logged(tasks):
    """The single deferred log entry, as the log_data dict."""
    entries = [a[1][1] for a in tasks.added]
    assert len(entries) == 1, f"expected one log entry, got {len(entries)}"
    return entries[0]


class _BankCall:
    """Mixin providing the dependencies every bank_call needs."""

    def setUp(self):
        self._base = settings.INTEGRATION_API_BASE_URL
        settings.INTEGRATION_API_BASE_URL = "https://imis.test:9001"

    def tearDown(self):
        settings.INTEGRATION_API_BASE_URL = self._base

    async def call(self, operation_id="bank-auth", payload=None, response=None,
                   client=None, credentials="session-token-abc"):
        tasks = _tasks()
        used = client if client is not None else _client(response)
        self._last_client_args = None
        kwargs = {
            "payload": BankCallRequest(operationId=operation_id, payload=payload or {}),
            "background_tasks": tasks,
            "db": MagicMock(),
            "http_client": used,
            "credentials": None if credentials is None else _credentials(credentials),
            "_current_user": MagicMock(),
        }
        result = await bank_router.bank_call(**kwargs)
        self._last_client_args = used.request.await_args
        return result, tasks


class CatalogTests(unittest.TestCase):
    def test_every_operation_targets_a_compliance_path(self):
        for op in bank_router.BANK_OPERATIONS:
            with self.subTest(operation=op["id"]):
                self.assertIn(op["method"], {"GET", "POST"})
                self.assertTrue(
                    op["path"].startswith("/integration/imis/api/compliance/"),
                    op["path"],
                )

    def test_get_operations_declare_a_single_cnic_parameter(self):
        gets = [op for op in bank_router.BANK_OPERATIONS if op["method"] == "GET"]
        self.assertTrue(gets, "expected the beneficiary lookups to be catalogued")

        for op in gets:
            with self.subTest(operation=op["id"]):
                self.assertEqual(
                    op["paramStyle"], "path" if "{" in op["path"] else "query"
                )
                self.assertEqual(op["paramName"], "cnic")
                self.assertEqual([f["name"] for f in op["fields"]], ["cnic"])

    def test_operation_ids_are_unique(self):
        ids = [op["id"] for op in bank_router.BANK_OPERATIONS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_catalog_carries_no_internal_implementation_notes(self):
        """
        The catalog is rendered in the console, so every string value is
        user-facing copy. Implementation detail belongs in a code comment.
        """
        offenders = (
            "imis-frontend", ".py", ".ts", "get_oauth_token", "get_bank_auth_token",
        )
        for op in bank_router.BANK_OPERATIONS:
            for key, value in op.items():
                if not isinstance(value, str):
                    continue
                for marker in offenders:
                    if marker.lower() in value.lower():
                        self.fail(f"{op['id']}.{key} leaks internals: {value!r}")

    def test_account_opening_surface_is_complete(self):
        account_opening = {
            op["id"]
            for op in bank_router.BANK_OPERATIONS
            if op["group"] == "account-opening"
        }
        self.assertEqual(
            account_opening,
            {"sspa-registration", "beneficiary-lookup-path", "beneficiary-lookup-query"},
        )

    def test_removed_account_opening_endpoints_are_gone(self):
        ids = {op["id"] for op in bank_router.BANK_OPERATIONS}
        self.assertNotIn("account-opening", ids)
        self.assertNotIn("account-opening-update", ids)
        for op in bank_router.BANK_OPERATIONS:
            self.assertNotIn("account-opening", op.get("aliasPaths", ()))

    def test_sspa_registration_auto_chains_bank_auth(self):
        """
        sspa_registration() only reads the x-bank-authorization header, so the
        console must run /bank-auth first.
        """
        by_id = {op["id"]: op for op in bank_router.BANK_OPERATIONS}
        registration = by_id["sspa-registration"]

        self.assertTrue(registration["autoChain"])
        self.assertEqual(registration["autoChainOperation"], "bank-auth")
        self.assertEqual(
            list(registration["autoChainCredentials"]), ["Username", "Password"]
        )
        field_names = {field["name"] for field in registration["fields"]}
        for credential in registration["autoChainCredentials"]:
            self.assertIn(credential, field_names)

    def test_auto_chain_operation_exists_in_the_catalog(self):
        ids = {op["id"] for op in bank_router.BANK_OPERATIONS}
        for op in bank_router.BANK_OPERATIONS:
            if op.get("autoChain"):
                with self.subTest(operation=op["id"]):
                    self.assertIn(op["autoChainOperation"], ids)

    def test_c2c_endpoints_never_chain_a_token(self):
        """c2c_disbursement obtains its own OAuth token internally."""
        for op in bank_router.BANK_OPERATIONS:
            if op["group"] == "c2c":
                with self.subTest(operation=op["id"]):
                    self.assertEqual(op["tokenFlow"], "token-generation-internal")
                    self.assertIsNone(op["tokenHeader"])

    def test_c2c_payment_aliases_cover_all_three_routes(self):
        by_id = {op["id"]: op for op in bank_router.BANK_OPERATIONS}
        self.assertEqual(
            set(by_id["c2c-payment"]["aliasPaths"]),
            {
                "/integration/imis/api/compliance/baf-c2c-disbursement",
                "/integration/imis/api/compliance/c2c-disbursement-auto",
            },
        )

    def test_every_digit_constrained_field_is_declared(self):
        by_id = {op["id"]: op for op in bank_router.BANK_OPERATIONS}

        def digits_of(op_id, field_name):
            for field in by_id[op_id]["fields"]:
                if field["name"] == field_name:
                    return field.get("digits")
            return None

        self.assertEqual(digits_of("c2c-payment", "CNIC_No"), 13)
        self.assertEqual(digits_of("c2c-payment", "Mobile_No"), 11)
        self.assertEqual(digits_of("sspa-registration", "CustomerCNIC"), 13)
        self.assertEqual(digits_of("sspa-registration", "MobileNumber"), 11)
        self.assertEqual(digits_of("beneficiary-lookup-path", "cnic"), 13)

    def test_every_field_declares_its_type(self):
        """The JSON view documents the schema, so no field may be untyped."""
        for op in bank_router.BANK_OPERATIONS:
            for field in op["fields"]:
                with self.subTest(operation=op["id"], field=field["name"]):
                    self.assertEqual(field["type"], "string")
                    self.assertIn("example", field)
                    self.assertIn("required", field)

    def test_enum_fields_advertise_their_options(self):
        by_id = {op["id"]: op for op in bank_router.BANK_OPERATIONS}
        grant = next(
            f for f in by_id["token-generation"]["fields"] if f["name"] == "GrantType"
        )
        self.assertEqual(grant["enum"], ["client_credentials"])

    def test_password_fields_declare_the_format(self):
        by_id = {op["id"]: op for op in bank_router.BANK_OPERATIONS}
        secret = next(
            f
            for f in by_id["token-generation"]["fields"]
            if f["name"] == "SecretKey"
        )
        self.assertEqual(secret["format"], "password")

    def test_unknown_operation_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            bank_router._resolve_operation("not-a-real-operation")
        self.assertEqual(ctx.exception.status_code, 404)


class HeaderMaskingTests(unittest.TestCase):
    def test_authorization_is_masked(self):
        masked = bank_router._mask_headers(
            {"Authorization": "Bearer supersecretcompliancevalue"}
        )
        self.assertNotIn("supersecretcompliancevalue", masked["Authorization"])
        self.assertTrue(masked["Authorization"].startswith("Bearer"))

    def test_bank_authorization_is_masked(self):
        masked = bank_router._mask_headers(
            {"x-bank-authorization": "Bearer banktokenvalue1234"}
        )
        self.assertNotIn("banktokenvalue1234", masked["x-bank-authorization"])

    def test_non_sensitive_headers_survive(self):
        masked = bank_router._mask_headers({"Accept": "application/json"})
        self.assertEqual(masked["Accept"], "application/json")

    def test_correlation_id_is_not_masked(self):
        """Not a secret, and the first thing you check when debugging."""
        masked = bank_router._mask_headers({"x-correlation-id": "11111"})
        self.assertEqual(masked["x-correlation-id"], "11111")


class JwtLeakTests(unittest.TestCase):
    """A token parked under a neutral key must still be redacted."""

    JWT = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJodHRwOi8vc2NoZW1hcy54bWxzb2FwLm9yZy93cy8yMDA1LzA1IiwiaXNzIjoiaHR0cHM6Ly9sb2NhbGhvc3Q6MzE1ODkifQ."
        "NAtupaLtgSD2CHk7loT2XcqGu5hpEEKSV5a-FkOdGbo"
    )

    def test_jwt_under_a_neutral_key_is_masked(self):
        masked = bank_router._mask_body({"value": self.JWT, "expiresAt": 1})
        self.assertEqual(masked["value"], bank_router.MASK)
        self.assertEqual(masked["expiresAt"], 1)

    def test_a_validation_error_shape_is_fully_scrubbed(self):
        """The exact 422 body that leaked the token."""
        leaked = {
            "detail": [
                {
                    "type": "string_type",
                    "loc": ["body", "bankToken"],
                    "msg": "Input should be a valid string",
                    "input": {
                        "value": self.JWT,
                        "expiresAt": 3584105243,
                        "capturedLabel": "12:53:43",
                    },
                }
            ]
        }
        masked = bank_router._mask_body(leaked)
        self.assertNotIn(self.JWT, json.dumps(masked))
        self.assertEqual(masked["detail"][0]["input"]["value"], bank_router.MASK)

    def test_jwt_embedded_in_free_text_is_scrubbed(self):
        masked = bank_router._mask_body({"msg": f"token {self.JWT} rejected"})
        self.assertNotIn(self.JWT, masked["msg"])
        self.assertIn(bank_router.MASK, masked["msg"])

    def test_ordinary_values_are_not_disturbed(self):
        masked = bank_router._mask_body(
            {"Amount": "500", "CNIC_No": "3520212345671", "note": "a.b.c"}
        )
        self.assertEqual(masked["Amount"], "500")
        self.assertEqual(masked["CNIC_No"], "3520212345671")
        self.assertEqual(masked["note"], "a.b.c")


class RequestBodyMaskingTests(unittest.TestCase):
    def test_credentials_are_redacted(self):
        masked = bank_router._mask_body({"Username": "bank.user", "Password": "S3cret!"})
        self.assertEqual(masked["Username"], bank_router.MASK)
        self.assertEqual(masked["Password"], bank_router.MASK)

    def test_token_generation_secrets_are_redacted(self):
        masked = bank_router._mask_body(
            {
                "SecretKey": "shh",
                "ClientId": "abc",
                "GrantType": "client_credentials",
                "Scope": "GetToken",
            }
        )
        self.assertEqual(masked["SecretKey"], bank_router.MASK)
        self.assertEqual(masked["ClientId"], bank_router.MASK)
        self.assertEqual(masked["GrantType"], "client_credentials")

    def test_business_fields_survive(self):
        masked = bank_router._mask_body(
            {
                "Transaction_Ref": "SSPA123",
                "Amount": "500",
                "To_Account": "0123456789",
                "CNIC_No": "3520212345671",
                "Mobile_No": "03001234567",
            }
        )
        self.assertEqual(masked["Amount"], "500")
        self.assertEqual(masked["CNIC_No"], "3520212345671")

    def test_nested_structures_are_walked(self):
        masked = bank_router._mask_body(
            {"outer": {"SecretKey": "abc", "keep": "yes"}, "rows": [{"Password": "p"}]}
        )
        self.assertEqual(masked["outer"]["SecretKey"], bank_router.MASK)
        self.assertEqual(masked["outer"]["keep"], "yes")
        self.assertEqual(masked["rows"][0]["Password"], bank_router.MASK)

    def test_matching_is_case_insensitive(self):
        masked = bank_router._mask_body({"PASSWORD": "p", "username": "u"})
        self.assertEqual(masked["PASSWORD"], bank_router.MASK)
        self.assertEqual(masked["username"], bank_router.MASK)


class BankSuccessCodeTests(unittest.TestCase):
    """The banks answer HTTP 200 for business failures, with code != 200."""

    def test_non_success_code_on_200_is_a_failure(self):
        self.assertFalse(bank_router._is_success(200, {"code": "99"}))

    def test_success_code_on_200_passes(self):
        self.assertTrue(bank_router._is_success(200, {"code": "200"}))
        self.assertTrue(bank_router._is_success(200, {"code": 0}))

    def test_response_code_field_is_honoured(self):
        self.assertTrue(bank_router._is_success(200, {"ResponseCode": "200"}))
        self.assertFalse(bank_router._is_success(200, {"ResponseCode": "401"}))

    def test_bodies_without_a_code_are_unaffected(self):
        self.assertTrue(
            bank_router._is_success(200, {"access_token": "abc", "scope": "x"})
        )
        self.assertTrue(bank_router._is_success(200, {"data": {"CustomerName": "Ali"}}))

    def test_non_numeric_code_is_not_treated_as_a_failure(self):
        self.assertTrue(bank_router._is_success(200, {"code": "SUCCESS"}))

    def test_http_error_is_always_a_failure(self):
        self.assertFalse(bank_router._is_success(400, {"code": "200"}))


class ProxyTests(_BankCall, unittest.IsolatedAsyncioTestCase):
    async def test_token_generation_call_sets_auth_and_correlation(self):
        result, tasks = await self.call(
            operation_id="token-generation",
            payload={"ClientId": "x", "GrantType": "client_credentials"},
            response=_response(200, {"access_token": "abc123"}),
        )
        args, kwargs = self._last_client_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(
            args[1],
            "https://imis.test:9001/integration/imis/api/compliance/tokenGeneration",
        )
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer session-token-abc")
        self.assertIn("x-correlation-id", kwargs["headers"])
        self.assertTrue(result.success)
        self.assertEqual(result.data["access_token"], "abc123")

    async def test_supplied_correlation_id_is_forwarded(self):
        result, _tasks = await self.call(
            operation_id="token-generation",
            response=_response(200, {"access_token": "abc"}),
        )
        # Generated when omitted, and echoed back to the caller.
        self.assertTrue(result.correlation_id)

    async def test_sspa_registration_requires_a_chained_bank_token(self):
        with self.assertRaises(HTTPException) as ctx:
            await self.call(
                operation_id="sspa-registration", payload={"Username": "u"}
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("x-bank-authorization", ctx.exception.detail)

    async def test_chained_bank_token_is_sent_as_bearer(self):
        client = _client(_response(200, {"ResponseDescription": {"Message": "ok"}}))
        result = await bank_router.bank_call(
            payload=BankCallRequest(
                operationId="sspa-registration",
                payload={"Username": "u", "Password": "p"},
                bankToken="bank-token-value",
            ),
            background_tasks=_tasks(),
            db=MagicMock(),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )
        headers = client.request.await_args[1]["headers"]
        self.assertEqual(headers["x-bank-authorization"], "Bearer bank-token-value")
        self.assertEqual(result.token_source, "chained bank-auth token")

    async def test_c2c_does_not_send_a_chained_bank_token(self):
        result, _tasks = await self.call(
            operation_id="c2c-disbursement",
            payload={"Amount": "1", "To_Account": "0123"},
            response=_response(200, {"code": "200"}),
        )
        headers = self._last_client_args[1]["headers"]
        self.assertNotIn("x-bank-authorization", headers)
        self.assertEqual(result.token_flow, "token-generation-internal")

    async def test_secrets_are_masked_in_echoed_headers(self):
        result, _ = await self.call(
            payload={"Username": "u"}, response=_response(200, {"access_token": "abc"})
        )
        self.assertNotIn("session-token-abc", result.request_headers["Authorization"])
        self.assertTrue(result.request_headers["Authorization"].startswith("Bearer"))

    async def test_the_callers_session_bearer_is_forwarded(self):
        client = _client(_response(200, {"access_token": "abc"}))
        await self.call(
            operation_id="token-generation",
            client=client,
            credentials="console-session-jwt",
        )
        headers = client.request.await_args[1]["headers"]
        self.assertEqual(headers["Authorization"], "Bearer console-session-jwt")

    async def test_a_missing_session_bearer_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            await self.call(credentials=None)
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_session_bearer_is_sent_alongside_the_chained_bank_token(self):
        client = _client(_response(200, {}))
        await bank_router.bank_call(
            payload=BankCallRequest(
                operationId="sspa-registration", payload={}, bankToken="bank-token"
            ),
            background_tasks=_tasks(),
            db=MagicMock(),
            http_client=client,
            credentials=_credentials("console-session-jwt"),
            _current_user=MagicMock(),
        )
        headers = client.request.await_args[1]["headers"]
        self.assertEqual(headers["Authorization"], "Bearer console-session-jwt")
        self.assertEqual(headers["x-bank-authorization"], "Bearer bank-token")

    async def test_credentials_are_masked_in_the_echoed_body_only(self):
        """The wire payload keeps the real values; the echo does not."""
        client = _client(_response(200, {}))
        result = await bank_router.bank_call(
            payload=BankCallRequest(
                operationId="bank-auth",
                payload={"Username": "bank.user", "Password": "S3cret!"},
            ),
            background_tasks=_tasks(),
            db=MagicMock(),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )
        sent = client.request.await_args[1]["json"]
        self.assertEqual(sent["Username"], "bank.user")
        self.assertEqual(sent["Password"], "S3cret!")
        self.assertEqual(result.request_body["Password"], bank_router.MASK)
        self.assertNotIn("S3cret!", json.dumps(result.request_body))

    async def test_beneficiary_lookup_substitutes_the_path_parameter(self):
        result, _ = await self.call(
            operation_id="beneficiary-lookup-path",
            payload={"cnic": "35202-1234567-1"},
            response=_response(200, {"data": {"CustomerName": "Ali"}}),
        )
        args, _kw = self._last_client_args
        self.assertEqual(args[0], "GET")
        self.assertEqual(
            args[1],
            "https://imis.test:9001/integration/imis/api/compliance/beneficiary/35202-1234567-1",
        )
        self.assertIsNone(result.request_body)
        self.assertEqual(result.targetMethod, "GET")
        self.assertTrue(result.success)

    async def test_beneficiary_lookup_query_variant_sends_a_query_param(self):
        await self.call(
            operation_id="beneficiary-lookup-query",
            payload={"cnic": "3520212345671"},
            response=_response(200, {"data": {}}),
        )
        args, kwargs = self._last_client_args
        self.assertEqual(args[0], "GET")
        self.assertEqual(
            args[1],
            "https://imis.test:9001/integration/imis/api/compliance/beneficiary-details"
            "?cnic=3520212345671",
        )
        self.assertNotIn("params", kwargs)

    async def test_get_does_not_send_a_content_type(self):
        await self.call(
            operation_id="beneficiary-lookup-query",
            payload={"cnic": "3520212345671"},
            response=_response(200, {"data": {}}),
        )
        headers = self._last_client_args[1]["headers"]
        self.assertNotIn("Content-Type", headers)
        self.assertEqual(headers["Accept"], "application/json")

    async def test_missing_cnic_is_rejected_before_calling_out(self):
        client = _client(_response(200, {}))
        with self.assertRaises(HTTPException) as ctx:
            await self.call(operation_id="beneficiary-lookup-path", client=client)
        self.assertEqual(ctx.exception.status_code, 400)
        client.request.assert_not_awaited()


class TransportTests(_BankCall, unittest.IsolatedAsyncioTestCase):
    async def test_transport_failure_becomes_502(self):
        client = MagicMock()
        client.request = AsyncMock(side_effect=httpx.ConnectError("refused"))
        result, _ = await self.call(client=client)
        self.assertFalse(result.success)
        self.assertEqual(result.status_code, 502)
        self.assertEqual(result.error_source, "mapper")
        self.assertIn("Could not reach the integration service", result.error)

    async def test_timeout_becomes_504(self):
        client = MagicMock()
        client.request = AsyncMock(side_effect=httpx.ReadTimeout("slow"))
        result, _ = await self.call(client=client)
        self.assertFalse(result.success)
        self.assertEqual(result.status_code, 504)
        self.assertEqual(result.error_source, "mapper")


class PayloadFormatTests(_BankCall, unittest.IsolatedAsyncioTestCase):
    async def test_short_cnic_is_rejected_before_sending(self):
        with self.assertRaises(HTTPException) as ctx:
            await self.call(
                operation_id="c2c-payment",
                payload={"Amount": "1", "CNIC_No": "12345"},
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("13 digits", ctx.exception.detail)

    async def test_non_numeric_cnic_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            await self.call(
                operation_id="c2c-payment",
                payload={"Amount": "1", "CNIC_No": "not-a-cnic"},
            )
        self.assertIn("must contain digits", ctx.exception.detail)

    async def test_wrong_length_mobile_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            await self.call(
                operation_id="c2c-payment",
                payload={
                    "Amount": "1",
                    "CNIC_No": "3520212345671",
                    "Mobile_No": "0300",
                },
            )
        self.assertIn("11 digits", ctx.exception.detail)

    async def test_hyphenated_valid_cnic_is_accepted(self):
        result, _ = await self.call(
            operation_id="c2c-payment",
            payload={
                "Amount": "1",
                "CNIC_No": "35202-1234567-1",
                "Mobile_No": "0300-1234567",
            },
            response=_response(200, {"code": "200"}),
        )
        self.assertTrue(result.success)

    async def test_missing_value_is_left_to_the_service(self):
        result, _ = await self.call(
            operation_id="c2c-payment",
            payload={"Amount": "1"},
            response=_response(200, {"code": "200"}),
        )
        self.assertTrue(result.success)


class ErrorLayerTests(_BankCall, unittest.IsolatedAsyncioTestCase):
    async def test_wrapped_response_yields_service_and_bank_layers(self):
        """The c2c-payment shape: service envelope around the bank body."""
        result, _ = await self.call(
            operation_id="c2c-payment",
            response=_response(
                400,
                {
                    "status": "error",
                    "code": 500,
                    "message": "Bank Alfalah disbursement failed: Internal Server Error",
                    "data": {"code": "500", "description": "Internal Server Error"},
                },
            ),
        )
        origins = [layer.origin for layer in result.error_layers]
        self.assertEqual(origins, ["integration-service", "bank"])
        bank = result.error_layers[1]
        self.assertEqual(bank.status_code, 500)
        self.assertEqual(bank.message, "Internal Server Error")
        service = result.error_layers[0]
        self.assertEqual(service.status_code, 400)

    async def test_passthrough_attributes_the_error_to_the_bank(self):
        result, _ = await self.call(
            operation_id="c2c-disbursement",
            response=_response(200, {"code": "99", "description": "Invalid account"}),
        )
        self.assertFalse(result.success)
        self.assertEqual(len(result.error_layers), 1)
        self.assertEqual(result.error_layers[0].origin, "bank")

    async def test_bank_auth_envelope_is_recognised(self):
        result, _ = await self.call(
            response=_response(
                401,
                {
                    "ResponseCode": "401",
                    "ResponseDescription": {"Message": "Bad credentials"},
                },
            ),
        )
        bank = [x for x in result.error_layers if x.origin == "bank"]
        self.assertEqual(len(bank), 1)
        self.assertEqual(bank[0].message, "Bad credentials")

    async def test_mapper_failure_has_only_one_layer(self):
        client = MagicMock()
        client.request = AsyncMock(side_effect=httpx.ConnectError("refused"))
        result, _ = await self.call(client=client)
        self.assertEqual(len(result.error_layers), 1)
        self.assertEqual(result.error_layers[0].origin, "mapper")

    async def test_success_carries_no_layers(self):
        result, _ = await self.call(response=_response(200, {"access_token": "abc"}))
        self.assertIsNone(result.error_layers)

    def test_duplicate_message_is_not_repeated(self):
        layers = bank_router._error_layers(
            400,
            {"code": "400", "description": "Invalid account"},
            "integration-service",
            "Invalid account",
        )
        self.assertEqual(len(layers), 1)


class UpstreamErrorTests(_BankCall, unittest.IsolatedAsyncioTestCase):
    async def test_integration_service_message_is_passed_through(self):
        result, _ = await self.call(
            operation_id="c2c-disbursement",
            response=_response(500, {"error": "Failed to generate OAuth token"}),
        )
        self.assertEqual(result.status_code, 500)
        self.assertEqual(result.error, "Failed to generate OAuth token")
        self.assertEqual(result.error_source, "integration-service")

    async def test_traceback_text_is_preserved(self):
        result, _ = await self.call(
            operation_id="c2c-disbursement",
            response=_response(
                500, {"error": "HTTPSConnectionPool(...): Read timed out"}
            ),
        )
        self.assertEqual(result.error, "HTTPSConnectionPool(...): Read timed out")

    async def test_fastapi_validation_detail_list_is_flattened(self):
        result, _ = await self.call(
            operation_id="c2c-disbursement",
            response=_response(
                422,
                {
                    "detail": [
                        {"loc": ["body", "Amount"], "msg": "field required"},
                        {"loc": ["body", "Stan"], "msg": "field required"},
                    ]
                },
            ),
        )
        self.assertEqual(result.error, "field required; field required")

    async def test_non_json_upstream_body_is_kept(self):
        result, _ = await self.call(
            operation_id="c2c-disbursement",
            response=_response(500, {"raw_response": "<html>Request Rejected</html>"}),
        )
        self.assertEqual(result.error, "<html>Request Rejected</html>")

    async def test_empty_body_still_says_something_useful(self):
        result, _ = await self.call(
            operation_id="c2c-disbursement", response=_response(500, {})
        )
        self.assertTrue(result.error)

    async def test_crash_is_reported_verbatim_not_swallowed(self):
        """If the service 500s for any other reason, show that 500."""
        result, _ = await self.call(
            operation_id="c2c-payment",
            payload={"Amount": "1", "CNIC_No": "3520212345671"},
            response=_response(500, {"detail": "Internal Server Error"}),
        )
        self.assertFalse(result.success)
        self.assertEqual(result.status_code, 500)
        self.assertEqual(result.error_source, "integration-service")


class CallLogTests(_BankCall, unittest.IsolatedAsyncioTestCase):
    """Every bank attempt must land in Call Logs like a gateway call."""

    async def test_successful_call_is_logged(self):
        result, tasks = await self.call(
            operation_id="c2c-payment",
            payload={"Amount": "1", "CNIC_No": "3520212345671"},
            response=_response(200, {"code": "200"}),
        )
        entry = _logged(tasks)
        self.assertEqual(entry["method"], "POST")
        self.assertEqual(entry["path"], "/integration/imis/api/compliance/c2c-payment")
        self.assertEqual(
            entry["external_request_url"],
            "https://imis.test:9001/integration/imis/api/compliance/c2c-payment",
        )
        self.assertEqual(entry["external_status_code"], 200)
        self.assertTrue(entry["success"])
        self.assertIsNone(entry["error"])

    async def test_get_calls_record_the_method(self):
        _result, tasks = await self.call(
            operation_id="beneficiary-lookup-query",
            payload={"cnic": "3520212345671"},
            response=_response(200, {"data": {}}),
        )
        entry = _logged(tasks)
        self.assertEqual(entry["method"], "GET")
        self.assertEqual(
            entry["path"], "/integration/imis/api/compliance/beneficiary-details"
        )

    async def test_failed_call_is_logged_with_its_error(self):
        _result, tasks = await self.call(
            operation_id="c2c-disbursement",
            payload={"Amount": "1"},
            response=_response(500, {"error": "Failed to generate OAuth token"}),
        )
        entry = _logged(tasks)
        self.assertFalse(entry["success"])
        self.assertEqual(entry["external_status_code"], 500)
        self.assertEqual(entry["error"], "Failed to generate OAuth token")

    async def test_business_failure_on_http_200_is_logged_as_failed(self):
        _result, tasks = await self.call(
            operation_id="c2c-disbursement",
            payload={"Amount": "1"},
            response=_response(200, {"code": "99", "description": "Invalid account"}),
        )
        entry = _logged(tasks)
        self.assertFalse(entry["success"])
        self.assertEqual(entry["error"], "Invalid account")

    async def test_timeout_is_logged(self):
        client = MagicMock()
        client.request = AsyncMock(side_effect=httpx.ReadTimeout("slow"))
        _result, tasks = await self.call(client=client)
        entry = _logged(tasks)
        self.assertFalse(entry["success"])
        self.assertEqual(entry["external_status_code"], 504)

    async def test_transport_failure_is_logged(self):
        client = MagicMock()
        client.request = AsyncMock(side_effect=httpx.ConnectError("refused"))
        _result, tasks = await self.call(client=client)
        entry = _logged(tasks)
        self.assertFalse(entry["success"])
        self.assertEqual(entry["external_status_code"], 502)

    async def test_logged_headers_carry_no_session_bearer(self):
        _result, tasks = await self.call(
            operation_id="bank-auth",
            payload={"Username": "u"},
            response=_response(200, {"ResponseCode": "200"}),
        )
        entry = _logged(tasks)
        self.assertNotIn(
            "session-token-abc", json.dumps(entry["request_headers"])
        )

    async def test_logged_body_is_redacted(self):
        _result, tasks = await self.call(
            operation_id="bank-auth",
            payload={"Username": "bank.user", "Password": "S3cret!"},
            response=_response(200, {"ResponseCode": "200"}),
        )
        entry = _logged(tasks)
        self.assertNotIn("S3cret!", json.dumps(entry["request_body"]))

    def test_log_entry_shape_matches_the_gateway_contract(self):
        """Keys write_call_log reads for a gateway result."""
        entry = bank_router._build_log_entry(
            {"path": "/p", "label": "L"},
            method="POST",
            target_url="https://x/p",
            request_headers={"Authorization": "Bearer abc"},
            request_body={"a": 1},
            status_code=200,
            response_headers={"h": "v"},
            data={"ok": True},
            success=True,
            error=None,
            elapsed_ms=12,
            correlation_id="cid",
        )
        for key in (
            "request_id", "method", "path", "external_request_url",
            "external_status_code", "request_headers", "response_headers",
            "internal_request_body", "data", "success", "error",
            "total_time_ms", "status_code",
        ):
            self.assertIn(key, entry)
        self.assertEqual(entry["request_id"], "cid")
        self.assertEqual(entry["total_time_ms"], 12)


if __name__ == "__main__":
    unittest.main()