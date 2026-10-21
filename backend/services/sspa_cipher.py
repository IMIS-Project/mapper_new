from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_SIZE = 12
_TAG_SIZE = 16


def derive_aes_key(key: str | bytes) -> bytes:
    if isinstance(key, bytes):
        raw = key
    else:
        text = str(key).strip()
        if not text:
            raise ValueError("AES key must not be empty")

        if len(text) == 64:
            try:
                raw = bytes.fromhex(text)
            except ValueError:
                raw = b""
        elif len(text) == 44 and text.endswith("="):
            try:
                raw = base64.b64decode(text)
            except Exception:
                raw = b""
        elif len(text.encode("utf-8")) == 32:
            raw = text.encode("utf-8")
        else:
            raw = b""

        if len(raw) != 32:
            raw = hashlib.sha256(text.encode("utf-8")).digest()

    return raw


def encrypt_sspa_payload(data: Any, key: str | bytes) -> dict[str, str]:
    if isinstance(data, (dict, list)):
        payload_str = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    else:
        payload_str = str(data)

    key_bytes = derive_aes_key(key)
    aesgcm = AESGCM(key_bytes)
    nonce = os.urandom(_NONCE_SIZE)

    encrypted = aesgcm.encrypt(nonce, payload_str.encode("utf-8"), None)
    raw_ciphertext = encrypted[:-_TAG_SIZE]
    tag = encrypted[-_TAG_SIZE:]

    binary_stream = nonce + tag + raw_ciphertext
    encoded = base64.b64encode(binary_stream).decode("ascii")
    return {"encrypted_data": encoded}


def decrypt_sspa_payload(encrypted_envelope: dict[str, Any] | str, key: str | bytes) -> Any:
    if isinstance(encrypted_envelope, dict):
        encoded = encrypted_envelope.get("encrypted_data") or encrypted_envelope.get("data")
        if not encoded:
            return encrypted_envelope
    else:
        encoded = str(encrypted_envelope).strip()

    key_bytes = derive_aes_key(key)
    aesgcm = AESGCM(key_bytes)

    try:
        raw_stream = base64.b64decode(encoded)
    except Exception as exc:
        raise ValueError(f"Invalid base64 payload: {exc}") from exc

    if len(raw_stream) < (_NONCE_SIZE + _TAG_SIZE):
        raise ValueError(
            f"Payload too short for Nonce({_NONCE_SIZE}) + Tag({_TAG_SIZE})"
        )

    nonce = raw_stream[:_NONCE_SIZE]
    tag = raw_stream[_NONCE_SIZE : _NONCE_SIZE + _TAG_SIZE]
    raw_ciphertext = raw_stream[_NONCE_SIZE + _TAG_SIZE :]

    reconstructed_ciphertext_and_tag = raw_ciphertext + tag

    try:
        decrypted_bytes = aesgcm.decrypt(nonce, reconstructed_ciphertext_and_tag, None)
    except Exception as exc:
        raise ValueError(f"Decryption authentication failed (tampered data or wrong key): {exc}") from exc

    text = decrypted_bytes.decode("utf-8")
    try:
        return json.loads(text)
    except Exception:
        return text
