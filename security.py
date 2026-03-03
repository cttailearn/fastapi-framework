from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any


_PBKDF2_NAME = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 310_000
_PBKDF2_SALT_BYTES = 16


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_PBKDF2_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{_PBKDF2_NAME}${_PBKDF2_ITERATIONS}${_b64url_encode(salt)}${_b64url_encode(dk)}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        name, iterations_s, salt_b64, dk_b64 = stored_hash.split("$", 3)
        if name != _PBKDF2_NAME:
            return False
        iterations = int(iterations_s)
        salt = _b64url_decode(salt_b64)
        expected = _b64url_decode(dk_b64)
    except Exception:
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def generate_api_key() -> str:
    return f"ak_{_b64url_encode(secrets.token_bytes(32))}"


def api_key_prefix(api_key: str) -> str:
    return api_key[:10]


def hash_api_key(api_key: str, pepper: str) -> str:
    mac = hmac.new(pepper.encode("utf-8"), api_key.encode("utf-8"), hashlib.sha256).digest()
    return mac.hex()


@dataclass(frozen=True)
class JwtToken:
    token: str
    expires_at: int


def jwt_encode(payload: dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url_encode(sig)}"


def jwt_decode(token: str, secret: str) -> dict[str, Any]:
    try:
        header_b64, payload_b64, sig_b64 = token.split(".", 2)
    except ValueError as e:
        raise ValueError("invalid_token") from e

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    actual_sig = _b64url_decode(sig_b64)
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("invalid_signature")

    payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")
    exp = payload.get("exp")
    if isinstance(exp, int) and exp < int(time.time()):
        raise ValueError("token_expired")
    return payload


def issue_access_token(user_id: int, is_admin: bool, secret: str, ttl_seconds: int) -> JwtToken:
    now = int(time.time())
    exp = now + ttl_seconds
    token = jwt_encode({"sub": user_id, "adm": 1 if is_admin else 0, "iat": now, "exp": exp}, secret=secret)
    return JwtToken(token=token, expires_at=exp)

