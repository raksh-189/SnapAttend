"""Unit tests for security primitives — no DB, no FastAPI."""

import uuid

import jwt as pyjwt
import pytest

from app.core import security


def test_password_hash_roundtrip():
    hashed = security.hash_password("s3cret-pass")
    assert hashed != "s3cret-pass"
    assert security.verify_password("s3cret-pass", hashed)
    assert not security.verify_password("wrong", hashed)


def test_verify_password_malformed_hash_returns_false():
    assert not security.verify_password("anything", "not-a-bcrypt-hash")


def test_access_token_roundtrip():
    user_id = uuid.uuid4()
    token = security.create_access_token(user_id, "teacher")
    payload = security.decode_access_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["role"] == "teacher"
    assert payload["type"] == "access"


def test_access_token_bad_signature_rejected():
    token = security.create_access_token(uuid.uuid4(), "teacher")
    with pytest.raises(pyjwt.InvalidTokenError):
        pyjwt.decode(token, "wrong-key-" + "x" * 32, algorithms=[security.ALGORITHM])


def test_tampered_token_rejected():
    token = security.create_access_token(uuid.uuid4(), "teacher")
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    with pytest.raises(pyjwt.InvalidTokenError):
        security.decode_access_token(tampered)


def test_refresh_token_hash_is_deterministic_and_opaque():
    raw = security.generate_refresh_token()
    assert len(raw) >= 48
    assert security.hash_refresh_token(raw) == security.hash_refresh_token(raw)
    assert raw not in security.hash_refresh_token(raw)
