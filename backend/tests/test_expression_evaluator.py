import pytest
from backend.services.expression_evaluator import evaluate_expression, get_nested_value


def test_get_nested_value():
    data = {"user": {"profile": {"roles": ["admin", "viewer"]}}}
    assert get_nested_value(data, "user.profile.roles.0") == "admin"
    assert get_nested_value(data, "user.profile.roles.1") == "viewer"
    assert get_nested_value(data, "user.profile.missing") is None


def test_evaluate_expression():
    context = {
        "env": {"MIS_KEY": "KEY123", "BASE_URL": "https://api.example.com"},
        "trigger": {"benef_cnic": "42201-1234567-1"},
        "nodes": {
            "login": {
                "data": {"access_token": "token_xyz", "expires_in": 3600}
            },
            "encrypt": {
                "output": {"encrypted_data": "abc1234=="}
            }
        }
    }

    assert evaluate_expression("{{env.MIS_KEY}}", context) == "KEY123"
    assert evaluate_expression("Bearer {{nodes.login.data.access_token}}", context) == "Bearer token_xyz"
    assert evaluate_expression("{{nodes.encrypt.output}}", context) == {"encrypted_data": "abc1234=="}

    config = {
        "url": "{{env.BASE_URL}}/complaints",
        "headers": {
            "x-api-key": "{{env.MIS_KEY}}",
            "Authorization": "Bearer {{nodes.login.data.access_token}}"
        },
        "body": {
            "cnic": "{{trigger.benef_cnic}}",
            "token": "{{nodes.login.data.access_token}}"
        }
    }

    resolved = evaluate_expression(config, context)
    assert resolved["url"] == "https://api.example.com/complaints"
    assert resolved["headers"]["x-api-key"] == "KEY123"
    assert resolved["headers"]["Authorization"] == "Bearer token_xyz"
    assert resolved["body"]["cnic"] == "42201-1234567-1"
    assert resolved["body"]["token"] == "token_xyz"
