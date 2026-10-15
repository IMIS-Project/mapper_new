"""Tests for the Bank Alfalah integration console proxy.

The console never forwards a caller-supplied URL, so the important behaviours
covered here are: the operation allow-list, the header construction for each
token flow, and the masking of secrets in the echoed request headers.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import HTTPException

from backend.api import bank_router
from backend.core.config import settings
from backend.schemas.bank import BankCallRequest
from fastapi.security import HTTPAuthorizationCredentials


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
                self.assertEqual(op["paramStyle"], "path" if "{" in op["path"] else "query")
                self.assertEqual(op["paramName"], "cnic")
                self.assertEqual([f["name"] for f in op["fields"]], ["cnic"])

    def test_catalog_carries_no_internal_implementation_notes(self):
        """
        The catalog is rendered in the console, so every string value is
        user-facing copy. Implementation detail (source files, function names,
        which caller invokes what) belongs in a code comment, not here.
        """
        offenders = ("imis-frontend", ".py", ".ts", "get_oauth_token", "get_bank_auth_token")
        for op in bank_router.BANK_OPERATIONS:
            for key, value in op.items():
                if not isinstance(value, str):
                    continue
                lowered = value.lower()
                for marker in offenders:
                    if marker.lower() in lowered:
                        self.fail(f"{op['id']}.{key} leaks internals: {value!r}")

    def test_operation_ids_are_unique(self):
        ids = [op["id"] for op in bank_router.BANK_OPERATIONS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_account_opening_surface_is_complete(self):
        """Account opening is SSPA Registration plus the two lookup helpers."""
        account_opening = {
            op["id"]
            for op in bank_router.BANK_OPERATIONS
            if op["group"] == "account-opening"
        }
        self.assertEqual(
            account_opening,
            {
                "sspa-registration",
                "beneficiary-lookup-path",
                "beneficiary-lookup-query",
            },
        )

    def test_removed_account_opening_endpoints_are_gone(self):
        """The auto-auth account-opening pair was deliberately dropped."""
        ids = {op["id"] for op in bank_router.BANK_OPERATIONS}
        self.assertNotIn("account-opening", ids)
        self.assertNotIn("account-opening-update", ids)
        for op in bank_router.BANK_OPERATIONS:
            self.assertNotIn("account-opening", op.get("aliasPaths", ()))

    def test_sspa_registration_auto_chains_bank_auth(self):
        """
        sspa_registration() does not authenticate itself - it only reads the
        x-bank-authorization header (sspa_registration.py:122/140) - so the
        console must run /bank-auth first.
        """
        by_id = {op["id"]: op for op in bank_router.BANK_OPERATIONS}
        registration = by_id["sspa-registration"]

        self.assertTrue(registration["autoChain"])
        self.assertEqual(registration["autoChainOperation"], "bank-auth")
        self.assertEqual(
            list(registration["autoChainCredentials"]), ["Username", "Password"]
        )
        # Both credentials are already part of the registration payload.
        field_names = {field["name"] for field in registration["fields"]}
        for credential in registration["autoChainCredentials"]:
            self.assertIn(credential, field_names)

    def test_auto_chain_operation_exists_in_the_catalog(self):
        """A dangling auto-chain target would silently send no token."""
        ids = {op["id"] for op in bank_router.BANK_OPERATIONS}
        for op in bank_router.BANK_OPERATIONS:
            if op.get("autoChain"):
                with self.subTest(operation=op["id"]):
                    self.assertIn(op["autoChainOperation"], ids)

    def test_c2c_endpoints_never_chain_a_token(self):
        """c2c_disbursement.py calls get_oauth_token() internally."""
        for op in bank_router.BANK_OPERATIONS:
            if op["group"] == "c2c":
                with self.subTest(operation=op["id"]):
                    self.assertEqual(
                        op["tokenFlow"], "token-generation-internal"
                    )
                    self.assertIsNone(op["tokenHeader"])

    def test_c2c_payment_aliases_cover_all_three_routes(self):
        """c2c_payment.py registers the same handler under three paths."""
        by_id = {op["id"]: op for op in bank_router.BANK_OPERATIONS}
        self.assertEqual(
            set(by_id["c2c-payment"]["aliasPaths"]),
            {
                "/integration/imis/api/compliance/baf-c2c-disbursement",
                "/integration/imis/api/compliance/c2c-disbursement-auto",
            },
        )

    def test_bank_auth_flow_is_separate_from_token_generation(self):
        """Account opening must use Bank Auth; C2C must use Token Generation."""
        by_id = {op["id"]: op for op in bank_router.BANK_OPERATIONS}

        self.assertEqual(by_id["token-generation"]["tokenFlow"], "token-generation")
        self.assertEqual(by_id["bank-auth"]["tokenFlow"], "bank-auth")

        # Only SSPA registration takes a chained token, and it is the bank-auth one.
        chained = [
            op for op in bank_router.BANK_OPERATIONS if op.get("tokenHeader")
        ]
        self.assertEqual([op["id"] for op in chained], ["sspa-registration"])
        self.assertEqual(chained[0]["tokenFlow"], "bank-auth")
        self.assertEqual(chained[0]["tokenHeader"], "x-bank-authorization")

        for c2c in ("c2c-disbursement", "c2c-payment"):
            self.assertEqual(
                by_id[c2c]["tokenFlow"],
                "token-generation-internal",
                c2c,
            )

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
        """It is not a secret and is the first thing you check when debugging."""
        masked = bank_router._mask_headers({"x-correlation-id": "11111"})
        self.assertEqual(masked["x-correlation-id"], "11111")


class JwtLeakTests(unittest.TestCase):
    """A token parked under a neutral key must still be redacted.

    Pydantic quotes the offending input in detail[].input, so a JWT under
    "value" rendered in full before this was handled.
    """

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
        self.assertEqual(
            masked["detail"][0]["input"]["value"], bank_router.MASK
        )

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


class BankSuccessCodeTests(unittest.TestCase):
    """The banks answer HTTP 200 for business failures, with code != 200."""

    def test_non_success_code_on_200_is_a_failure(self):
        self.assertFalse(bank_router._is_success(200, {"code": "99"}))

    def test_success_code_on_200_passes(self):
        self.assertTrue(bank_router._is_success(200, {"code": "200"}))
        self.assertTrue(bank_router._is_success(200, {"code": 0}))

    def test_response_code_field_is_honoured(self):
        self.assertTrue(
            bank_router._is_success(200, {"ResponseCode": "200"})
        )
        self.assertFalse(
            bank_router._is_success(200, {"ResponseCode": "401"})
        )

    def test_bodies_without_a_code_are_unaffected(self):
        """tokenGeneration and the beneficiary lookups have no code field."""
        self.assertTrue(
            bank_router._is_success(200, {"access_token": "abc", "scope": "x"})
        )
        self.assertTrue(bank_router._is_success(200, {"data": {"CustomerName": "Ali"}}))

    def test_non_numeric_code_is_not_treated_as_a_failure(self):
        self.assertTrue(bank_router._is_success(200, {"code": "SUCCESS"}))

    def test_http_error_is_always_a_failure(self):
        self.assertFalse(bank_router._is_success(400, {"code": "200"}))


class PayloadFormatTests(unittest.IsolatedAsyncioTestCase):
    """
    Upstream validates CNIC/mobile with pydantic validators that raise
    ValueError; the service's 422 handler then fails to serialise its own
    error and answers 500. These values must never get that far.
    """

    def setUp(self):
        self._base = settings.INTEGRATION_API_BASE_URL
        settings.INTEGRATION_API_BASE_URL = "https://imis.test:9001"

    def tearDown(self):
        settings.INTEGRATION_API_BASE_URL = self._base

    async def _call(self, operation_id, payload):
        client = _client(_response(200, {"code": "200"}))
        with self.assertRaises(HTTPException) as ctx:
            await bank_router.bank_call(
                BankCallRequest(operationId=operation_id, payload=payload),
                http_client=client,
                credentials=_credentials(),
                _current_user=MagicMock(),
            )
        # Nothing must reach the integration service.
        client.request.assert_not_awaited()
        return ctx.exception

    async def test_short_cnic_is_rejected_before_sending(self):
        exc = await self._call(
            "c2c-payment", {"Amount": "1", "CNIC_No": "12345", "Mobile_No": "03001234567"}
        )
        self.assertEqual(exc.status_code, 400)
        self.assertIn("13 digits", exc.detail)

    async def test_non_numeric_cnic_is_rejected(self):
        exc = await self._call(
            "c2c-payment", {"Amount": "1", "CNIC_No": "not-a-cnic", "Mobile_No": "03001234567"}
        )
        self.assertIn("must contain digits", exc.detail)

    async def test_wrong_length_mobile_is_rejected(self):
        exc = await self._call(
            "c2c-payment", {"Amount": "1", "CNIC_No": "3520212345671", "Mobile_No": "0300"}
        )
        self.assertIn("11 digits", exc.detail)

    async def test_hyphenated_valid_cnic_is_accepted(self):
        client = _client(_response(200, {"code": "200"}))
        result = await bank_router.bank_call(
            BankCallRequest(
                operationId="c2c-payment",
                payload={"Amount": "1", "CNIC_No": "35202-1234567-1", "Mobile_No": "0300-1234567"},
            ),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )
        self.assertTrue(result.success)
        client.request.assert_awaited()

    async def test_missing_value_is_left_to_the_service(self):
        """Absent fields are not our validation problem."""
        client = _client(_response(200, {"code": "200"}))
        result = await bank_router.bank_call(
            BankCallRequest(operationId="c2c-payment", payload={"Amount": "1"}),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )
        self.assertTrue(result.success)

    def test_every_digit_constrained_field_is_declared(self):
        """CNIC 13 / mobile 11 across the catalog."""
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


class IntegrationServiceValidationCrashTests(unittest.IsolatedAsyncioTestCase):
    """
    The integration service's own 422 handler puts exc.errors() straight into
    JSONResponse without encoding, so a pydantic validator that raises
    ValueError makes the response unserialisable and the service returns 500
    instead of 422.
    """

    def setUp(self):
        self._base = settings.INTEGRATION_API_BASE_URL
        settings.INTEGRATION_API_BASE_URL = "https://imis.test:9001"

    def tearDown(self):
        settings.INTEGRATION_API_BASE_URL = self._base

    async def test_crash_is_reported_verbatim_not_swallowed(self):
        """
        If the service does 500 for any other reason, the console must show
        that 500 rather than pretend the call succeeded.
        """
        result = await bank_router.bank_call(
            BankCallRequest(
                operationId="c2c-payment",
                payload={"Amount": "1", "CNIC_No": "3520212345671"},
            ),
            http_client=_client(_response(500, {"detail": "Internal Server Error"})),
            credentials=_credentials(),
            _current_user=MagicMock(),
        )
        self.assertFalse(result.success)
        self.assertEqual(result.status_code, 500)
        self.assertEqual(result.error_source, "integration-service")


class ErrorLayerTests(unittest.IsolatedAsyncioTestCase):
    """A failure can originate at more than one hop; surface every one."""

    def setUp(self):
        self._base = settings.INTEGRATION_API_BASE_URL
        settings.INTEGRATION_API_BASE_URL = "https://imis.test:9001"

    def tearDown(self):
        settings.INTEGRATION_API_BASE_URL = self._base

    async def _call(self, response):
        return await bank_router.bank_call(
            BankCallRequest(operationId="c2c-payment", payload={"Amount": "1"}),
            http_client=_client(response),
            credentials=_credentials(),
            _current_user=MagicMock(),
        )

    async def test_wrapped_response_yields_service_and_bank_layers(self):
        """The c2c-payment shape: service envelope around the bank's body."""
        result = await self._call(
            _response(
                400,
                {
                    "status": "error",
                    "code": 500,
                    "message": (
                        "Bank Alfalah disbursement failed: Internal Server Error"
                    ),
                    "data": {
                        "code": "500",
                        "description": "Internal Server Error",
                    },
                },
            )
        )

        origins = [layer.origin for layer in result.error_layers]
        self.assertEqual(origins, ["integration-service", "bank"])

        bank = result.error_layers[1]
        self.assertEqual(bank.status_code, 500)
        self.assertEqual(bank.message, "Internal Server Error")
        self.assertEqual(bank.label, "Bank Alfalah")

        service = result.error_layers[0]
        self.assertEqual(service.status_code, 400)
        self.assertEqual(service.label, "Integration service")

    async def test_passthrough_response_is_attributed_to_the_bank(self):
        """c2c-disbursement returns the bank body untouched."""
        result = await self._call(
            _response(200, {"code": "99", "description": "Invalid account"})
        )
        origins = [layer.origin for layer in result.error_layers]
        self.assertIn("bank", origins)

    async def test_bank_auth_envelope_is_recognised(self):
        result = await bank_router.bank_call(
            BankCallRequest(operationId="bank-auth", payload={}),
            http_client=_client(
                _response(
                    401,
                    {
                        "ResponseCode": "401",
                        "ResponseDescription": {"Message": "Bad credentials"},
                    },
                )
            ),
            credentials=_credentials(),
            _current_user=MagicMock(),
        )
        bank = [x for x in result.error_layers if x.origin == "bank"]
        self.assertEqual(len(bank), 1)
        self.assertEqual(bank[0].message, "Bad credentials")

    async def test_mapper_failure_has_only_one_layer(self):
        """Transport failed, so neither the service nor the bank is involved."""
        client = MagicMock()
        client.request = AsyncMock(side_effect=httpx.ConnectError("refused"))
        result = await bank_router.bank_call(
            BankCallRequest(operationId="c2c-payment", payload={}),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )
        self.assertEqual(len(result.error_layers), 1)
        self.assertEqual(result.error_layers[0].origin, "mapper")
        self.assertEqual(result.error_layers[0].label, "This console")

    async def test_success_carries_no_layers(self):
        result = await self._call(_response(200, {"access_token": "abc"}))
        self.assertIsNone(result.error_layers)

    async def test_passthrough_attributes_the_error_to_the_bank(self):
        """
        The service returned the bank body verbatim, so listing both hops
        would be misleading - the bank is the origin.
        """
        result = await self._call(
            _response(200, {"code": "99", "description": "Invalid account"})
        )
        self.assertFalse(result.success)
        self.assertEqual(len(result.error_layers), 1)
        self.assertEqual(result.error_layers[0].origin, "bank")

    async def test_duplicate_message_is_not_repeated(self):
        """Don't stack two layers saying the same thing."""
        layers = bank_router._error_layers(
            400,
            {"code": "400", "description": "Invalid account"},
            "integration-service",
            "Invalid account",
        )
        self.assertEqual(len(layers), 1)


class UpstreamErrorTests(unittest.IsolatedAsyncioTestCase):
    """A 500 from the integration service must surface verbatim, not generically."""

    def setUp(self):
        self._base = settings.INTEGRATION_API_BASE_URL
        settings.INTEGRATION_API_BASE_URL = "https://imis.test:9001"

    def tearDown(self):
        settings.INTEGRATION_API_BASE_URL = self._base

    async def _call(self, response):
        return await bank_router.bank_call(
            BankCallRequest(
                operationId="c2c-disbursement", payload={"Amount": "1"}
            ),
            http_client=_client(response),
            credentials=_credentials(),
            _current_user=MagicMock(),
        )

    async def test_integration_service_message_is_passed_through(self):
        """The real c2c-disbursement 500 shape."""
        result = await self._call(
            _response(500, {"error": "Failed to generate OAuth token"})
        )
        self.assertEqual(result.status_code, 500)
        self.assertEqual(result.error, "Failed to generate OAuth token")
        self.assertEqual(result.error_source, "integration-service")

    async def test_traceback_text_is_preserved(self):
        """The service's generic 500 handler returns str(e) as the body."""
        result = await self._call(
            _response(500, {"error": "HTTPSConnectionPool(...): Read timed out"})
        )
        self.assertEqual(
            result.error, "HTTPSConnectionPool(...): Read timed out"
        )
        self.assertEqual(result.error_source, "integration-service")

    async def test_fastapi_validation_detail_list_is_flattened(self):
        result = await self._call(
            _response(
                422,
                {
                    "detail": [
                        {"loc": ["body", "Amount"], "msg": "field required"},
                        {"loc": ["body", "Stan"], "msg": "field required"},
                    ]
                },
            )
        )
        self.assertIn("field required", result.error)
        self.assertEqual(result.error, "field required; field required")

    async def test_non_json_upstream_body_is_kept(self):
        """A gateway HTML page or bare text must not be discarded."""
        result = await self._call(
            _response(
                500,
                {"raw_response": "<html>Request Rejected</html>"},
            )
        )
        self.assertEqual(result.error, "<html>Request Rejected</html>")
        self.assertEqual(result.error_source, "integration-service")

    async def test_empty_body_still_says_something_useful(self):
        result = await self._call(_response(500, {}))
        self.assertTrue(result.error)
        self.assertNotEqual(result.error, "")

    async def test_transport_failure_is_attributed_to_the_mapper(self):
        client = MagicMock()
        client.request = AsyncMock(side_effect=httpx.ConnectError("refused"))
        result = await bank_router.bank_call(
            BankCallRequest(operationId="c2c-disbursement", payload={}),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )
        self.assertEqual(result.error_source, "mapper")

    async def test_timeout_is_attributed_to_the_mapper(self):
        client = MagicMock()
        client.request = AsyncMock(side_effect=httpx.ReadTimeout("slow"))
        result = await bank_router.bank_call(
            BankCallRequest(operationId="c2c-disbursement", payload={}),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )
        self.assertEqual(result.error_source, "mapper")
        self.assertEqual(result.status_code, 504)

    async def test_success_has_no_error_source(self):
        result = await self._call(_response(200, {"code": "200"}))
        self.assertIsNone(result.error)
        self.assertIsNone(result.error_source)


class RequestBodyMaskingTests(unittest.TestCase):
    def test_credentials_are_redacted(self):
        masked = bank_router._mask_body(
            {"Username": "bank.user", "Password": "S3cret!"}
        )
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
        self.assertEqual(masked["Scope"], "GetToken")

    def test_business_fields_survive(self):
        """C2C fields carry no credential markers and must stay readable."""
        masked = bank_router._mask_body(
            {
                "Transaction_Ref": "SSPA123",
                "Amount": "500",
                "To_Account": "0123456789",
                "Stan": "",
                "CNIC_No": "3520212345671",
                "Mobile_No": "03001234567",
            }
        )
        self.assertEqual(masked["Amount"], "500")
        self.assertEqual(masked["CNIC_No"], "3520212345671")
        self.assertEqual(masked["To_Account"], "0123456789")

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


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._base = settings.INTEGRATION_API_BASE_URL
        settings.INTEGRATION_API_BASE_URL = "https://imis.test:9001"

    def tearDown(self):
        settings.INTEGRATION_API_BASE_URL = self._base

    async def test_token_generation_call_sets_auth_and_correlation(self):
        client = _client(_response(200, {"access_token": "abc123"}))

        result = await bank_router.bank_call(
            BankCallRequest(
                operationId="token-generation",
                payload={"ClientId": "x", "GrantType": "client_credentials"},
            ),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )

        url, kwargs = client.request.await_args[0][1], client.request.await_args[1]
        self.assertEqual(url, "https://imis.test:9001/integration/imis/api/compliance/tokenGeneration")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer session-token-abc")
        self.assertIn("x-correlation-id", kwargs["headers"])
        self.assertTrue(result.success)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["access_token"], "abc123")

    async def test_supplied_correlation_id_is_forwarded(self):
        client = _client(_response(200, {"access_token": "abc"}))

        result = await bank_router.bank_call(
            BankCallRequest(
                operationId="token-generation",
                payload={},
                correlationId="11111",
            ),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )

        headers = client.request.await_args[1]["headers"]
        self.assertEqual(headers["x-correlation-id"], "11111")
        self.assertEqual(result.correlation_id, "11111")

    async def test_sspa_registration_requires_a_chained_bank_token(self):
        with self.assertRaises(HTTPException) as ctx:
            await bank_router.bank_call(
                BankCallRequest(
                    operationId="sspa-registration",
                    payload={"Username": "u"},
                ),
                http_client=_client(_response(200, {})),
                credentials=_credentials(),
                _current_user=MagicMock(),
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("x-bank-authorization", ctx.exception.detail)

    async def test_chained_bank_token_is_sent_as_bearer(self):
        client = _client(_response(200, {"ResponseDescription": {"Message": "ok"}}))

        result = await bank_router.bank_call(
            BankCallRequest(
                operationId="sspa-registration",
                payload={"Username": "u", "Password": "p"},
                bankToken="bank-token-value",
            ),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )

        headers = client.request.await_args[1]["headers"]
        self.assertEqual(headers["x-bank-authorization"], "Bearer bank-token-value")
        self.assertEqual(result.token_source, "chained bank-auth token")

    async def test_c2c_does_not_send_a_chained_bank_token(self):
        client = _client(_response(200, {"code": "200"}))

        result = await bank_router.bank_call(
            BankCallRequest(
                operationId="c2c-disbursement",
                payload={"Amount": "1", "To_Account": "0123"},
            ),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )

        headers = client.request.await_args[1]["headers"]
        self.assertNotIn("x-bank-authorization", headers)
        self.assertEqual(result.token_flow, "token-generation-internal")

    async def test_upstream_error_is_surfaced(self):
        client = _client(
            _response(404, {"error": "Person not found"}),
        )

        result = await bank_router.bank_call(
            BankCallRequest(
                operationId="beneficiary-lookup-query",
                payload={"cnic": "35202-1234567-1"},
            ),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status_code, 404)
        self.assertEqual(result.error, "Person not found")

    async def test_secrets_are_masked_in_echoed_headers(self):
        client = _client(_response(200, {"access_token": "abc"}))

        result = await bank_router.bank_call(
            BankCallRequest(operationId="bank-auth", payload={"Username": "u"}),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )

        self.assertNotIn("session-token-abc", result.request_headers["Authorization"])
        self.assertTrue(result.request_headers["Authorization"].startswith("Bearer"))

    async def test_transport_failure_becomes_502(self):
        client = MagicMock()
        client.request = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )

        result = await bank_router.bank_call(
            BankCallRequest(operationId="bank-auth", payload={"Username": "u"}),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status_code, 502)
        self.assertIn("Could not reach the integration service", result.error)

    async def test_timeout_becomes_504(self):
        client = MagicMock()
        client.request = AsyncMock(side_effect=httpx.ReadTimeout("too slow"))

        result = await bank_router.bank_call(
            BankCallRequest(operationId="bank-auth", payload={"Username": "u"}),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status_code, 504)

    async def test_beneficiary_lookup_substitutes_the_path_parameter(self):
        client = _client(_response(200, {"data": {"CustomerName": "Ali"}}))

        result = await bank_router.bank_call(
            BankCallRequest(
                operationId="beneficiary-lookup-path",
                payload={"cnic": "35202-1234567-1"},
            ),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )

        args, kwargs = client.request.await_args
        self.assertEqual(args[0], "GET")
        self.assertEqual(
            args[1],
            "https://imis.test:9001/integration/imis/api/compliance/beneficiary/35202-1234567-1",
        )
        self.assertNotIn("json", kwargs)
        self.assertIsNone(result.request_body)
        self.assertEqual(result.targetMethod, "GET")
        self.assertTrue(result.success)

    async def test_beneficiary_lookup_query_variant_sends_a_query_param(self):
        client = _client(_response(200, {"data": {}}))

        await bank_router.bank_call(
            BankCallRequest(
                operationId="beneficiary-lookup-query",
                payload={"cnic": "3520212345671"},
            ),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )

        args, kwargs = client.request.await_args
        self.assertEqual(args[0], "GET")
        self.assertEqual(
            args[1],
            "https://imis.test:9001/integration/imis/api/compliance/beneficiary-details"
            "?cnic=3520212345671",
        )
        self.assertNotIn("params", kwargs)

    async def test_get_does_not_send_a_content_type(self):
        client = _client(_response(200, {"data": {}}))

        await bank_router.bank_call(
            BankCallRequest(
                operationId="beneficiary-lookup-query",
                payload={"cnic": "3520212345671"},
            ),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )

        headers = client.request.await_args[1]["headers"]
        self.assertNotIn("Content-Type", headers)
        self.assertEqual(headers["Accept"], "application/json")

    async def test_missing_cnic_is_rejected_before_calling_out(self):
        client = _client(_response(200, {}))

        with self.assertRaises(HTTPException) as ctx:
            await bank_router.bank_call(
                BankCallRequest(operationId="beneficiary-lookup-path", payload={}),
                http_client=client,
                credentials=_credentials(),
                _current_user=MagicMock(),
            )

        self.assertEqual(ctx.exception.status_code, 400)
        client.request.assert_not_awaited()

    async def test_the_callers_session_bearer_is_forwarded(self):
        """No static service token - the console reuses its own auth bearer."""
        client = _client(_response(200, {"access_token": "abc"}))

        await bank_router.bank_call(
            BankCallRequest(operationId="token-generation", payload={}),
            http_client=client,
            credentials=_credentials("console-session-jwt"),
            _current_user=MagicMock(),
        )

        headers = client.request.await_args[1]["headers"]
        self.assertEqual(headers["Authorization"], "Bearer console-session-jwt")

    async def test_a_missing_session_bearer_is_rejected(self):
        client = _client(_response(200, {}))

        with self.assertRaises(HTTPException) as ctx:
            await bank_router.bank_call(
                BankCallRequest(operationId="bank-auth", payload={}),
                http_client=client,
                credentials=None,
                _current_user=MagicMock(),
            )

        self.assertEqual(ctx.exception.status_code, 401)
        client.request.assert_not_awaited()

    async def test_credentials_are_masked_in_the_echoed_body_only(self):
        """The wire payload keeps the real values; the echo does not."""
        client = _client(_response(200, {}))

        result = await bank_router.bank_call(
            BankCallRequest(
                operationId="bank-auth",
                payload={"Username": "bank.user", "Password": "S3cret!"},
            ),
            http_client=client,
            credentials=_credentials(),
            _current_user=MagicMock(),
        )

        sent = client.request.await_args[1]["json"]
        self.assertEqual(sent["Username"], "bank.user")
        self.assertEqual(sent["Password"], "S3cret!")

        self.assertEqual(result.request_body["Username"], bank_router.MASK)
        self.assertEqual(result.request_body["Password"], bank_router.MASK)
        self.assertNotIn("S3cret!", json.dumps(result.request_body))

    async def test_session_bearer_is_sent_alongside_the_chained_bank_token(self):
        """SSPA registration carries two distinct tokens on the wire."""
        client = _client(_response(200, {}))

        await bank_router.bank_call(
            BankCallRequest(
                operationId="sspa-registration",
                payload={},
                bankToken="bank-token",
            ),
            http_client=client,
            credentials=_credentials("console-session-jwt"),
            _current_user=MagicMock(),
        )

        headers = client.request.await_args[1]["headers"]
        self.assertEqual(headers["Authorization"], "Bearer console-session-jwt")
        self.assertEqual(headers["x-bank-authorization"], "Bearer bank-token")


if __name__ == "__main__":
    unittest.main()