from auth_utils import (
    create_access_token,
    decode_token,
    get_password_hash,
    verify_password,
)


def test_decode_invalid_token():
    assert decode_token("not-a-jwt") is None


def test_roundtrip_token_sub():
    token = create_access_token({"sub": "42"})
    payload = decode_token(token)
    assert payload is not None
    assert payload.get("sub") == "42"


def test_password_hash_roundtrip():
    h = get_password_hash("secret")
    assert verify_password("secret", h)
    assert not verify_password("wrong", h)
