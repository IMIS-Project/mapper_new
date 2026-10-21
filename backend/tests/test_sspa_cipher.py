import pytest
from backend.services.sspa_cipher import (
    derive_aes_key,
    encrypt_sspa_payload,
    decrypt_sspa_payload,
)


def test_derive_aes_key():
    key32 = b"12345678901234567890123456789012"
    assert derive_aes_key(key32) == key32

    hex_key = key32.hex()
    assert derive_aes_key(hex_key) == key32

    short_key = "my-secret-key"
    derived = derive_aes_key(short_key)
    assert len(derived) == 32


def test_encrypt_and_decrypt_roundtrip():
    key = "0123456789abcdef0123456789abcdef"
    payload = {
        "source_ticket_id": "IMIS-TICKET-2026-00123",
        "benef_cnic": "42201-1234567-1",
        "category": "Payments",
        "subcategory": "Delayed Transfer",
        "complaint_type": "benef",
        "complainant_name": "Fatima Bibi",
        "complainant_phone": "03001234567",
        "description": "Payment was not deposited into designated branch account.",
        "program_id": 1,
    }

    encrypted = encrypt_sspa_payload(payload, key)
    assert "encrypted_data" in encrypted
    assert isinstance(encrypted["encrypted_data"], str)

    decrypted = decrypt_sspa_payload(encrypted, key)
    assert decrypted == payload


def test_tamper_detection():
    key = "0123456789abcdef0123456789abcdef"
    payload = {"status": "resolved", "ticket": 123}

    encrypted = encrypt_sspa_payload(payload, key)
    import base64

    raw = bytearray(base64.b64decode(encrypted["encrypted_data"]))
    raw[-1] ^= 0xFF
    tampered_b64 = base64.b64encode(raw).decode("ascii")

    with pytest.raises(ValueError, match="Decryption authentication failed"):
        decrypt_sspa_payload({"encrypted_data": tampered_b64}, key)


def test_wrong_key_fails():
    key1 = "0123456789abcdef0123456789abcdef"
    key2 = "fedcba9876543210fedcba9876543210"
    payload = {"hello": "world"}

    encrypted = encrypt_sspa_payload(payload, key1)
    with pytest.raises(ValueError, match="Decryption authentication failed"):
        decrypt_sspa_payload(encrypted, key2)
