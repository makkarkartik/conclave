import pytest

from conclave.domain.crypto import decrypt_secret, encrypt_secret


def test_roundtrip():
    token = encrypt_secret("sk-super-secret")
    assert token != "sk-super-secret"
    assert decrypt_secret(token) == "sk-super-secret"


def test_empty_passthrough():
    assert encrypt_secret("") == ""
    assert decrypt_secret("") == ""


def test_tampered_token_raises():
    token = encrypt_secret("sk-super-secret")
    with pytest.raises(ValueError):
        decrypt_secret(token[:-4] + "AAAA")
