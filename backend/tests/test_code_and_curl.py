import pytest
from backend.services.code_executor import execute_code_node
from backend.services.curl_parser import parse_curl_command
from backend.services.sspa_cipher import decrypt_sspa_payload


def test_code_node_simple_return():
    code = """
token = nodes.get("login", {}).get("token")
return {
    "computed": trigger.get("val", 0) * 2,
    "auth": f"Bearer {token}"
}
"""
    trigger = {"val": 21}
    nodes = {"login": {"token": "secret123"}}
    env = {"KEY": "VAL"}

    res = execute_code_node(code, trigger, nodes, env)
    assert res["computed"] == 42
    assert res["auth"] == "Bearer secret123"


def test_code_node_sspa_aes_encryption():
    code = """
payload = {
    "source_ticket_id": trigger.get("ticket_id"),
    "benef_cnic": trigger.get("cnic"),
    "status": "active"
}
encrypted = crypto.encrypt_sspa_payload(payload, env["MIS_AES_KEY"])
return encrypted
"""
    trigger = {"ticket_id": "IMIS-001", "cnic": "42201-1234567-1"}
    nodes = {}
    env = {"MIS_AES_KEY": "0123456789abcdef0123456789abcdef"}

    res = execute_code_node(code, trigger, nodes, env)
    assert "encrypted_data" in res

    decrypted = decrypt_sspa_payload(res, env["MIS_AES_KEY"])
    assert decrypted["source_ticket_id"] == "IMIS-001"
    assert decrypted["benef_cnic"] == "42201-1234567-1"


def test_curl_parser():
    cmd = """
curl -X POST https://devmis.sspa.gos.pk/api/v1/imis/auth/login \
  -H "Content-Type: application/json" \
  -H "x-api-key: MIS_KEY" \
  -d '{"email": "test@example.com", "password": "pass", "program_id": 1}'
"""
    parsed = parse_curl_command(cmd)
    assert parsed["method"] == "POST"
    assert parsed["url"] == "https://devmis.sspa.gos.pk/api/v1/imis/auth/login"
    assert parsed["headers"]["x-api-key"] == "MIS_KEY"
    assert parsed["headers"]["Content-Type"] == "application/json"
    assert parsed["body"]["email"] == "test@example.com"
    assert parsed["body"]["program_id"] == 1
