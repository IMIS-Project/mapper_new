"""Foundation contracts with mocks only; no database, network, or secret files."""

import asyncio
import os
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import UUID

import httpx
from pydantic import ValidationError
from pydantic_settings import DotEnvSettingsSource
from sqlalchemy.ext.asyncio import AsyncSession


AUDIT_TEST_SETTINGS: dict[str, str] = {
    "AUDIT_MONGO_URI": "mongodb://audit-store.invalid:27017/",
    "AUDIT_MONGO_DATABASE": "audit_test_db",
    "AUDIT_MONGO_COLLECTION": "audit_test_collection",
}

with (
    patch.dict(
        os.environ,
        {
            "JWT_SECRET": "foundation-test-only",
            "ENCRYPTION_KEY": "foundation-test-only",
            **AUDIT_TEST_SETTINGS,
        },
        clear=True,
    ),
    patch.object(DotEnvSettingsSource, "_read_env_files", return_value={}),
):
    from backend.core.config import Settings
    from backend.models import (
        ApiEndpoint,
        ParamTypeEnum,
        ParameterMapping,
        User,
        Webhook,
        WebhookEvent,
    )
    from backend.models.types import ParameterTypeValue, YesNoBoolean
    from backend.schemas.endpoint import EndpointCreate, EndpointUpdate
    from backend.schemas.gateway import MapAndCallResponse
    from backend.schemas.parameter import ParameterCreate
    from backend.schemas.webhook import WebhookCreate, WebhookResponse, WebhookUpdate
    from backend.services import endpoint_service, parameter_service
    from backend.services.gateway_engine import (
        EndpointSnapshot,
        ExecutionOutcome,
        GatewayEngine,
        MappingSnapshot,
    )

ENDPOINT_ID = 290

WEBHOOK_ID = UUID("22222222-2222-4222-8222-222222222222")
LEGACY_KEYS = set(
    """
    request_id endpoint_id tenant_id method path request_headers success data
    status_code response_time_ms total_time_ms response_headers error
    external_request_url external_request_method external_request_headers
    external_request_body external_query_params external_response_headers
    external_status_code external_response_time_ms status timeout_configured
""".split()
)


def endpoint_row(**updates):
    row = dict(
        id=ENDPOINT_ID,
        endpoint_code="EP-TEST",
        source_api_url="https://upstream.test/items",
        target_api_url="https://gateway.test/v1/items",
        method="POST",
        is_active=False,
        tenant_id="tenant",
        rate_limit_rpm=60,
        mock_enabled=False,
        mock_response={"items": [False, 0]},
        updated_at=datetime(2026, 1, 1),
    )
    row.update(updates)
    return row


def endpoint_snapshot(**updates):
    row = endpoint_row(**updates)
    row["_mock_response"] = row.pop("mock_response")
    return EndpointSnapshot(**row)


def endpoint_result(row):
    result = Mock()
    result.mappings.return_value.first.return_value = row
    return result


def parameter_result(*rows):
    result = Mock()
    result.scalars.return_value.all.return_value = list(rows)
    return result


def make_db(*results):
    db = MagicMock(spec=AsyncSession)
    db.new, db.dirty, db.deleted = set(), set(), set()
    db.in_transaction.return_value = False
    pending = iter(results)

    async def execute(statement):
        db.in_transaction.return_value = True
        return next(pending)

    async def rollback():
        db.in_transaction.return_value = False

    db.execute = AsyncMock(side_effect=execute)
    db.rollback = AsyncMock(side_effect=rollback)
    return db


def make_client(status=200, data=None, error=None):
    client = Mock(spec=httpx.AsyncClient)

    def build_request(**kwargs):
        kwargs.pop("timeout")
        return httpx.Request(**kwargs)

    client.build_request.side_effect = build_request
    response = httpx.Response(status, json=data, headers={"X-Upstream": "yes"})
    client.send = AsyncMock(side_effect=error, return_value=response)
    return client


class YesNoBooleanTests(unittest.TestCase):
    def test_legacy_mysql_flags_map_both_ways(self):
        column_type = YesNoBoolean()

        self.assertEqual(column_type.process_bind_param(True, None), "Y")
        self.assertEqual(column_type.process_bind_param(False, None), "N")
        self.assertEqual(column_type.process_bind_param("yes", None), "Y")
        self.assertEqual(column_type.process_bind_param("no", None), "N")
        self.assertIsNone(column_type.process_bind_param(None, None))
        self.assertIs(column_type.process_result_value("Y", None), True)
        self.assertIs(column_type.process_result_value("N", None), False)
        self.assertIsNone(column_type.process_result_value(None, None))

        with self.assertRaises(ValueError):
            column_type.process_bind_param("unknown", None)
        with self.assertRaises(ValueError):
            column_type.process_result_value("unknown", None)

    def test_legacy_flag_columns_use_boolean_mapping(self):
        for column in (
            ApiEndpoint.require_authentication,
            ApiEndpoint.require_correlation_id,
            ApiEndpoint.is_active,
            ApiEndpoint.is_hidden,
            ParameterMapping.is_active,
            User.is_active,
        ):
            with self.subTest(column=column.key):
                self.assertIsInstance(column.type, YesNoBoolean)


class ParameterTypeValueTests(unittest.TestCase):
    def test_app_query_value_maps_to_legacy_querystring_column(self):
        column_type = ParameterTypeValue()

        # The app speaks QUERY; the legacy column spells it QUERYSTRING.
        self.assertEqual(column_type.process_bind_param("QUERY", None), "QUERYSTRING")
        self.assertEqual(
            column_type.process_bind_param(ParamTypeEnum.QUERY, None), "QUERYSTRING"
        )
        self.assertEqual(column_type.process_bind_param("BODY", None), "BODY")
        self.assertEqual(column_type.process_bind_param("HEADER", None), "HEADER")
        self.assertEqual(
            column_type.process_bind_param("QUERYSTRING", None), "QUERYSTRING"
        )
        self.assertIsNone(column_type.process_bind_param(None, None))

        # Legacy rows read back as the app spelling.
        self.assertEqual(column_type.process_result_value("QUERYSTRING", None), "QUERY")
        self.assertEqual(column_type.process_result_value("BODY", None), "BODY")
        self.assertIsNone(column_type.process_result_value(None, None))

    def test_parameter_column_uses_the_translating_type(self):
        self.assertIsInstance(
            ParameterMapping.parameter_type.type, ParameterTypeValue
        )


class ResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_config_only_explicit_inactive_id_has_one_query(self):
        row = endpoint_row(mock_enabled=True)
        db = make_db(endpoint_result(row))
        client = make_client()
        with patch.object(
            parameter_service, "list_parameters", new_callable=AsyncMock
        ) as mappings:
            resolved = await GatewayEngine(db, client).resolve_endpoint(
                str(ENDPOINT_ID)
            )
        self.assertEqual(resolved.id, ENDPOINT_ID)
        self.assertFalse(resolved.is_active)

        self.assertFalse(resolved.mock_enabled)
        mappings.assert_not_awaited()
        client.send.assert_not_awaited()
        self.assertEqual(db.execute.await_count, 1)
        statement = db.execute.call_args.args[0]
        self.assertNotIn("is_active", str(statement.whereclause))
        self.assertNotIn("api_password", statement.selected_columns.keys())
        self.assertNotIn("parameter_mappings", str(statement))
        self.assertFalse(db.in_transaction())
        db.rollback.assert_awaited_once()

        self.assertIsNone(resolved.mock_response)
        with self.assertRaises(FrozenInstanceError):
            resolved.rate_limit_rpm = 0

    async def test_missing_id_falls_back_to_active_url_and_normalized_method(self):
        db = make_db(
            endpoint_result(None), endpoint_result(endpoint_row(is_active=True))
        )
        endpoint = await GatewayEngine(db, make_client()).resolve_endpoint(
            ENDPOINT_ID, " /v1/items ", " post "
        )
        self.assertEqual(endpoint.id, ENDPOINT_ID)
        self.assertEqual(db.execute.await_count, 2)
        statement = db.execute.call_args.args[0]
        self.assertIn("is_active = :is_active_1", str(statement))
        self.assertIn("created_at DESC", str(statement))
        self.assertIn("%/v1/items", statement.compile().params.values())
        self.assertIn("POST", statement.compile().params.values())
        db.rollback.assert_awaited_once()

    async def test_invalid_id_skips_id_query_but_preserves_url_fallback(self):
        db = make_db(endpoint_result(endpoint_row()))
        endpoint = await GatewayEngine(db, make_client()).resolve_endpoint(
            "invalid", "/v1/items"
        )
        self.assertEqual(endpoint.id, ENDPOINT_ID)
        self.assertEqual(db.execute.await_count, 1)

    async def test_missing_url_releases_existing_auth_read_without_query(self):
        db = make_db()
        db.in_transaction.return_value = True
        self.assertIsNone(
            await GatewayEngine(db, make_client()).resolve_endpoint("invalid")
        )
        db.execute.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_resolution_error_still_releases_read_transaction(self):
        db = make_db()
        db.in_transaction.return_value = True
        db.execute.side_effect = RuntimeError("read failed")
        with self.assertRaisesRegex(RuntimeError, "read failed"):
            await GatewayEngine(db, make_client()).resolve_endpoint(ENDPOINT_ID)
        db.rollback.assert_awaited_once()

    async def test_pending_writes_are_not_silently_rolled_back(self):
        db = make_db()
        db.new = {object()}
        with self.assertRaisesRegex(RuntimeError, "pending writes"):
            await GatewayEngine(db, make_client()).resolve_endpoint(ENDPOINT_ID)
        db.rollback.assert_not_awaited()
        db.execute.assert_not_awaited()

    async def test_mapping_snapshot_load_is_single_active_query_and_detached(self):
        row = SimpleNamespace(
            source_parameter="up",
            target_parameter="down",
            parameter_type="BODY",
            data_type="STRING",
        )
        db = make_db(parameter_result(row))
        mappings = await GatewayEngine(db, make_client()).load_mappings(
            endpoint_snapshot()
        )
        row.source_parameter = "changed"
        self.assertEqual(mappings, (MappingSnapshot("up", "down", "BODY", "STRING"),))
        self.assertEqual(db.execute.await_count, 1)
        self.assertIn("is_active = :is_active_1", str(db.execute.call_args.args[0]))
        self.assertFalse(db.in_transaction())


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_pipeline_queries_once_each_and_uses_source_destination(self):
        row = SimpleNamespace(
            source_parameter="up",
            target_parameter="down",
            parameter_type="BODY",
            data_type="NUMBER",
        )
        db = make_db(endpoint_result(endpoint_row()), parameter_result(row))
        client = make_client(data=[False, 0])

        async def send(request):
            self.assertFalse(db.in_transaction())
            self.assertEqual(str(request.url), "https://upstream.test/items")
            self.assertEqual(request.method, "POST")
            return httpx.Response(200, json=[False, 0])

        client.send.side_effect = send
        result = await GatewayEngine(db, client).process_request(
            ENDPOINT_ID, {"down": 0}, {"Host": "gateway.test"}, "/v1/items", "GET"
        )
        self.assertEqual(set(result), LEGACY_KEYS)
        self.assertTrue(result["success"])
        self.assertEqual(result["data"], [False, 0])
        self.assertEqual(result["method"], "GET")
        self.assertEqual(result["external_request_body"], {"up": 0})
        self.assertEqual(result["external_request_headers"]["host"], "upstream.test")
        self.assertEqual(result["endpoint_id"], ENDPOINT_ID)
        self.assertEqual(db.execute.await_count, 2)
        self.assertEqual(db.rollback.await_count, 2)
        self.assertIsInstance(result["total_time_ms"], int)
        public = MapAndCallResponse.model_validate(result).model_dump()
        self.assertNotIn("failure_kind", public)
        self.assertNotIn("upstream_attempted", public)
        self.assertNotIn("source", public)

    async def test_supplied_mappings_skip_all_queries_and_release_existing_read(self):
        db = make_db()
        db.in_transaction.return_value = True
        client = make_client(data=False)
        outcome = await GatewayEngine(db, client).execute_resolved(
            endpoint_snapshot(), {}, mappings=()
        )
        db.execute.assert_not_awaited()
        db.rollback.assert_awaited_once()
        self.assertEqual(outcome.source, "live")
        self.assertTrue(outcome.success)
        self.assertIs(outcome.to_result()["data"], False)
        self.assertTrue(outcome.upstream_attempted)

    async def test_http_statuses_are_not_confused_with_local_failures(self):
        for status, failure in [
            (200, None),
            (302, None),
            (400, "upstream_http"),
            (429, "upstream_http"),
            (408, "upstream_timeout"),
            (500, "upstream_http"),
            (502, "upstream_http"),
            (503, "upstream_http"),
            (504, "upstream_timeout"),
        ]:
            with self.subTest(status=status):
                outcome = await GatewayEngine(
                    make_db(), make_client(status)
                ).execute_resolved(endpoint_snapshot(), {}, mappings=())
                self.assertEqual(outcome.failure_kind, failure)
                self.assertEqual(outcome.upstream_status, status)
                self.assertTrue(outcome.upstream_attempted)
                self.assertEqual(outcome.to_result()["status_code"], status)

    async def test_transport_and_pool_timeouts_keep_legacy_status_but_distinct_metadata(
        self,
    ):
        cases = [
            (httpx.PoolTimeout("pool"), "local_pool_timeout", 408, False),
            (httpx.ConnectTimeout("connect"), "upstream_timeout", 408, True),
            (httpx.ReadTimeout("read"), "upstream_timeout", 408, True),
            (httpx.WriteTimeout("write"), "upstream_timeout", 408, True),
            (httpx.ConnectError("connect"), "transport", 503, True),
            (httpx.ReadError("read"), "transport", 502, True),
            (ValueError("unexpected"), "internal", 500, True),
        ]
        for error, kind, status, attempted in cases:
            with self.subTest(error=type(error).__name__):
                outcome = await GatewayEngine(
                    make_db(), make_client(error=error)
                ).execute_resolved(endpoint_snapshot(), {}, mappings=())
                self.assertEqual(outcome.failure_kind, kind)
                self.assertEqual(outcome.upstream_attempted, attempted)
                self.assertIsNone(outcome.upstream_status)
                self.assertEqual(outcome.to_result()["status_code"], status)
                self.assertFalse(outcome.success)

    async def test_local_request_build_failure_does_not_claim_upstream_attempt(self):
        client = make_client()
        client.build_request.side_effect = ValueError("invalid request")
        outcome = await GatewayEngine(make_db(), client).execute_resolved(
            endpoint_snapshot(), {}, mappings=()
        )
        self.assertEqual(outcome.failure_kind, "internal")
        self.assertFalse(outcome.upstream_attempted)
        client.send.assert_not_awaited()

    async def test_missing_source_is_configuration_failure_with_timing(self):
        client = make_client()
        outcome = await GatewayEngine(make_db(), client).execute_resolved(
            endpoint_snapshot(source_api_url=" "), {}, mappings=()
        )
        self.assertEqual(outcome.failure_kind, "configuration")
        self.assertFalse(outcome.upstream_attempted)
        self.assertEqual(outcome.to_result()["status_code"], 500)
        self.assertIsInstance(outcome.to_result()["total_time_ms"], int)
        client.send.assert_not_awaited()

    async def test_not_found_hints_release_read_and_keep_envelope(self):
        similar = Mock()
        similar.all.return_value = [
            SimpleNamespace(
                id=ENDPOINT_ID, endpoint_code="EP-HINT", target_api_url="/hint"
            )
        ]
        db = make_db(endpoint_result(None), similar)
        client = make_client()
        result = await GatewayEngine(db, client).process_request(
            None, {}, target_url="/missing", target_method="POST"
        )
        self.assertEqual(result["status_code"], 404)
        self.assertIn("EP-HINT (/hint)", result["error"])
        self.assertEqual(set(result), LEGACY_KEYS)
        self.assertFalse(db.in_transaction())
        client.send.assert_not_awaited()

    async def test_cancellation_propagates_without_open_read(self):
        db = make_db()
        db.in_transaction.return_value = True
        with self.assertRaises(asyncio.CancelledError):
            await GatewayEngine(
                db, make_client(error=asyncio.CancelledError())
            ).execute_resolved(endpoint_snapshot(), {}, mappings=())
        self.assertFalse(db.in_transaction())

    def test_mapping_semantics_preserve_static_headers_falsy_values_and_case(self):
        mappings = [
            MappingSnapshot("n", "number", "BODY", "NUMBER"),
            MappingSnapshot("flag", "enabled", "QUERY", "BOOLEAN"),
            MappingSnapshot("X-Token", "token", "HEADER", "STRING"),
            MappingSnapshot("X-Static", "static:literal", "HEADER", "STRING"),
            MappingSnapshot("X-Fallback", "fallback", "HEADER", "STRING"),
        ]
        body, headers, query = GatewayEngine._transform_parameters(
            {"number": 0, "enabled": False, "fallback": "body"},
            mappings,
            {"Host": "ignore.test", "TOKEN": "incoming"},
        )
        self.assertEqual(body, {"n": 0})
        self.assertEqual(query, {"flag": False})
        self.assertNotIn("Host", headers)
        self.assertEqual(headers["X-Token"], "incoming")
        self.assertEqual(headers["X-Static"], "literal")
        self.assertEqual(headers["X-Fallback"], "body")
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_no_mappings_passes_request_body_through_unchanged(self):
        body, headers, query = GatewayEngine._transform_parameters(
            {"page": 1, "page_size": 2},
            (),
            {"Host": "ignore.test", "X-Trace": "abc"},
        )
        self.assertEqual(body, {"page": 1, "page_size": 2})
        self.assertEqual(query, {})
        self.assertNotIn("Host", headers)
        self.assertEqual(headers["X-Trace"], "abc")

    def test_empty_request_with_no_mappings_yields_empty_body(self):
        body, _headers, query = GatewayEngine._transform_parameters({}, (), {})
        self.assertEqual(body, {})
        self.assertEqual(query, {})

    def test_outcome_owns_immutable_nested_audit_and_independent_envelopes(self):
        original = {
            "success": True,
            "data": [0, {"ok": False}],
            "external_status_code": 200,
            "external_request_headers": {"x": "a"},
        }
        outcome = ExecutionOutcome(original, upstream_attempted=True)
        original["data"].append("changed")
        copy = outcome.to_result()
        copy["data"][1]["ok"] = True
        self.assertEqual(outcome.to_result()["data"], [0, {"ok": False}])
        with self.assertRaises(TypeError):
            outcome.result["data"][1]["ok"] = True
        with self.assertRaises(TypeError):
            outcome.upstream_audit["external_request_headers"]["x"] = "changed"
        self.assertEqual(outcome.upstream_audit["external_response"][0], 0)
        self.assertEqual(outcome.upstream_status, 200)
        with self.assertRaises(FrozenInstanceError):
            outcome.source = "cache"


class ComposableWriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_flush_encrypts_without_commit_refresh_or_decrypt(self):
        db = make_db()
        data = {
            "source_api_url": "https://upstream.test",
            "target_api_url": "/items",
            "api_password": "test-value",
        }
        with (
            patch.object(endpoint_service, "encrypt_value", return_value="ciphertext"),
            patch.object(endpoint_service, "_decrypt_sensitive") as decrypt,
        ):
            endpoint = await endpoint_service.create_endpoint_flush(db, data)
        self.assertEqual(endpoint.api_password, "ciphertext")
        self.assertEqual(data["api_password"], "test-value")
        self.assertTrue(endpoint.endpoint_code.startswith("EP-"))
        db.flush.assert_awaited_once()
        db.commit.assert_not_awaited()
        db.refresh.assert_not_awaited()
        decrypt.assert_not_called()

    async def test_endpoint_public_wrapper_still_commits_refreshes_and_decrypts(self):
        db = make_db()
        endpoint = object()
        with (
            patch.object(
                endpoint_service,
                "create_endpoint_flush",
                new=AsyncMock(return_value=endpoint),
            ),
            patch.object(
                endpoint_service, "_decrypt_sensitive", return_value=endpoint
            ) as decrypt,
        ):
            actual = await endpoint_service.create_endpoint(db, {})
        self.assertIs(actual, endpoint)
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(endpoint)
        decrypt.assert_called_once_with(endpoint)

    async def test_parameter_flush_helpers_keep_enum_values_and_do_not_commit(self):
        data = ParameterCreate(source_parameter="up", target_parameter="down")
        for helper, argument in [
            (parameter_service.create_parameter_flush, data),
            (parameter_service.bulk_create_parameters_flush, [data]),
        ]:
            with self.subTest(helper=helper.__name__):
                db = make_db()
                value = await helper(db, ENDPOINT_ID, argument)
                row = value[0] if isinstance(value, list) else value
                self.assertEqual(row.api_endpoint_id, ENDPOINT_ID)
                self.assertEqual(row.parameter_type, "BODY")
                self.assertEqual(row.data_type, "STRING")
                db.flush.assert_awaited_once()
                db.commit.assert_not_awaited()
                db.refresh.assert_not_awaited()

    async def test_parameter_public_wrappers_still_commit_and_refresh(self):
        data = ParameterCreate(source_parameter="up", target_parameter="down")
        for helper, argument in [
            (parameter_service.create_parameter, data),
            (parameter_service.bulk_create_parameters, [data]),
        ]:
            with self.subTest(helper=helper.__name__):
                db = make_db()
                value = await helper(db, ENDPOINT_ID, argument)
                row = value[0] if isinstance(value, list) else value
                db.commit.assert_awaited_once()
                db.refresh.assert_awaited_once_with(row)

    async def test_flush_failure_leaves_rollback_to_atomic_group_owner(self):
        db = make_db()
        db.flush.side_effect = [None, RuntimeError("mapping failed")]
        data = ParameterCreate(source_parameter="up", target_parameter="down")
        with self.assertRaisesRegex(RuntimeError, "mapping failed"):
            await endpoint_service.create_endpoint_flush(
                db,
                {
                    "id": ENDPOINT_ID,
                    "source_api_url": "https://upstream.test",
                    "target_api_url": "/items",
                },
            )
            await parameter_service.bulk_create_parameters_flush(
                db, ENDPOINT_ID, [data]
            )
        db.commit.assert_not_awaited()
        db.rollback.assert_not_awaited()
        await db.rollback()
        db.rollback.assert_awaited_once()

    async def test_empty_and_invalid_bulk_inputs_preserve_no_write_behavior(self):
        db = make_db()
        data = ParameterCreate(source_parameter="up", target_parameter="down")
        self.assertEqual(
            await parameter_service.bulk_create_parameters(db, ENDPOINT_ID, []), []
        )
        self.assertEqual(
            await parameter_service.bulk_create_parameters_flush(db, "bad", [data]), []
        )
        db.flush.assert_not_awaited()
        db.commit.assert_not_awaited()


class SchemaAndConfigTests(unittest.TestCase):
    def test_endpoint_rate_and_json_validation(self):
        urls = {"source_api_url": "https://upstream.test", "target_api_url": "/items"}
        for value in [False, 0, "", [], {}, None, [1, {"nested": True}]]:
            with self.subTest(json=value):
                self.assertEqual(
                    EndpointCreate(**urls, mock_response=value).mock_response, value
                )
                update = EndpointUpdate(mock_response=value)
                self.assertEqual(
                    update.model_dump(exclude_unset=True), {"mock_response": value}
                )
        self.assertEqual(EndpointCreate(**urls).rate_limit_rpm, 60)
        for rpm in [None, 0, 60]:
            self.assertEqual(
                EndpointCreate(**urls, rate_limit_rpm=rpm).rate_limit_rpm, rpm
            )
            self.assertEqual(EndpointUpdate(rate_limit_rpm=rpm).rate_limit_rpm, rpm)
        for schema, kwargs in [(EndpointCreate, urls), (EndpointUpdate, {})]:
            with self.assertRaises(ValidationError):
                schema(**kwargs, rate_limit_rpm=-1)
            with self.assertRaises(ValidationError):
                schema(**kwargs, mock_response=object())
        self.assertEqual(EndpointUpdate().model_dump(exclude_unset=True), {})

    def test_webhook_global_create_partial_update_and_audit_fields(self):
        created = WebhookCreate(
            url="https://receiver.test/events", events=["call_success"]
        )
        self.assertIsNone(created.endpoint_id)
        self.assertTrue(created.enabled)
        self.assertEqual(created.events, [WebhookEvent.CALL_SUCCESS])
        self.assertEqual(WebhookUpdate().model_dump(exclude_unset=True), {})
        self.assertEqual(
            WebhookUpdate(endpoint_id=None, enabled=False).model_dump(
                exclude_unset=True
            ),
            {"endpoint_id": None, "enabled": False},
        )
        now = datetime.now(timezone.utc)
        response = WebhookResponse.model_validate(
            SimpleNamespace(
                id=WEBHOOK_ID,
                endpoint_id=None,
                url=created.url,
                events=created.events,
                enabled=True,
                created_by=7,
                created_at=now,
                updated_at=now,
            )
        )
        self.assertEqual(response.created_by, 7)
        self.assertEqual(response.created_at, now)

    def test_webhook_rejects_invalid_events_credentials_and_null_updates(self):
        base = {"url": "https://receiver.test/events", "events": ["call_success"]}
        cases = [
            dict(events=[]),
            dict(events=["unknown"]),
            dict(events=["call_success", "call_success"]),
            dict(created_by=99),
            dict(url="ftp://receiver.test/events"),
            dict(url="https://user:pass@receiver.test"),
            dict(url="https://receiver.test/events#fragment"),
        ]
        for invalid in cases:
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                WebhookCreate(**(base | invalid))
        for name in ["url", "events", "enabled"]:
            with self.assertRaises(ValidationError):
                WebhookUpdate(**{name: None})

    def test_webhook_model_registration_cascade_and_timezone(self):
        self.assertIs(Webhook.metadata.tables["webhooks"], Webhook.__table__)
        columns = Webhook.__table__.c
        self.assertTrue(columns.endpoint_id.nullable)
        self.assertEqual(
            next(iter(columns.endpoint_id.foreign_keys)).ondelete, "CASCADE"
        )
        self.assertEqual(
            next(iter(columns.created_by.foreign_keys)).ondelete, "SET NULL"
        )
        self.assertFalse(columns.events.nullable)
        self.assertTrue(columns.created_at.type.timezone)
        self.assertTrue(columns.updated_at.type.timezone)
        self.assertEqual(
            {event.value for event in WebhookEvent},
            {
                "call_success",
                "call_failure",
                "call_timeout",
                "endpoint_created",
            },
        )

    def make_settings(self, **kwargs):
        with patch.dict(os.environ, {}, clear=True):
            return Settings(
                _env_file=None,
                JWT_SECRET="test",
                ENCRYPTION_KEY="test",
                AUTH_BASE_URL="https://auth.test",
                **AUDIT_TEST_SETTINGS,
                **kwargs,
            )

    def test_settings_disable_dotenv_and_have_bounded_defaults(self):
        def no_file_reads(source):
            self.assertIsNone(source.env_file)
            return {}

        with patch.object(DotEnvSettingsSource, "_read_env_files", no_file_reads):
            settings = self.make_settings()
        self.assertIsNone(settings.SFTP_KNOWN_HOSTS_FILE)
        self.assertEqual(settings.SFTP_PRIVATE_KEY_PATHS, [])
        self.assertEqual(settings.SFTP_CONNECT_TIMEOUT_SECONDS, 10)
        self.assertEqual(settings.SFTP_LOGIN_TIMEOUT_SECONDS, 10)
        self.assertEqual(settings.SFTP_OPERATION_TIMEOUT_SECONDS, 20)
        self.assertEqual(settings.SFTP_MAX_ENTRIES, 5000)
        self.assertEqual(settings.SFTP_PREVIEW_MAX_BYTES, 1048576)
        self.assertEqual(settings.SFTP_MAX_CONCURRENT, 10)
        self.assertEqual(settings.WEBHOOK_ALLOWED_HOSTS, [])
        self.assertEqual(settings.WEBHOOK_ALLOWED_CIDRS, [])
        self.assertEqual(settings.WEBHOOK_MAX_JOBS, 100)
        self.assertEqual(settings.WEBHOOK_MAX_CONCURRENT, 10)
        self.assertEqual(settings.WEBHOOK_DELIVERY_TIMEOUT_SECONDS, 5)
        self.assertEqual(settings.DEDUP_TTL_SECONDS, 5)
        self.assertEqual(settings.DEDUP_MAX_BYTES, 16777216)

    def test_settings_list_values_accept_csv_and_json_without_new_dependencies(self):
        # CORS_ORIGINS is the only list-valued setting that decodes CSV.
        environment = {
            "CORS_ORIGINS": "receiver.test, other.test",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings(
                _env_file=None,
                JWT_SECRET="test",
                ENCRYPTION_KEY="test",
                AUTH_BASE_URL="https://auth.test",
                **AUDIT_TEST_SETTINGS,
            )
        self.assertEqual(
            settings.WEBHOOK_ALLOWED_HOSTS, ["receiver.test", "other.test"]
        )
        self.assertEqual(settings.WEBHOOK_ALLOWED_CIDRS, ["10.0.0.0/8"])
        self.assertEqual(settings.SFTP_PRIVATE_KEY_PATHS, ["C:/keys/operator"])
        self.assertEqual(settings.CORS_ORIGINS, ["*"])

    def test_capacity_and_timeout_settings_reject_zero(self):
        for name in [
            "SFTP_MAX_CONCURRENT",
            "SFTP_CONNECT_TIMEOUT_SECONDS",
            "SFTP_LOGIN_TIMEOUT_SECONDS",
            "SFTP_PREVIEW_MAX_BYTES",
            "WEBHOOK_DELIVERY_TIMEOUT_SECONDS",
            "SCHEDULER_MAX_JOBS",
            "SCHEDULER_MAX_REQUEST_BODY_BYTES",
            "SCHEDULER_MAX_RESPONSE_BODY_BYTES",
            "SCHEDULER_MAX_HEADERS",
            "DEDUP_TTL_SECONDS",
            "DEDUP_MAX_ENTRIES",
        ]:
            with self.subTest(setting=name), self.assertRaises(ValidationError):
                self.make_settings(**{name: 0})


if __name__ == "__main__":
    unittest.main()
