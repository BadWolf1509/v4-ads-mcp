"""AES-GCM round-trip + tamper-detection tests."""

import pytest

from src.auth.tokens import (
    InvalidCiphertextError,
    decrypt_refresh_token,
    encrypt_refresh_token,
)

# A fixed key for deterministic tests. Real master key comes from Secret Manager.
_TEST_KEY = b"x" * 32  # 32-byte AES-256 key


def test_round_trip_returns_original():
    plaintext = "1//06abc-DEFghijkLMNop_qrstuvWXYZ-1234567890"
    ct = encrypt_refresh_token(plaintext, _TEST_KEY)
    assert ct != plaintext.encode()  # actually encrypted
    pt = decrypt_refresh_token(ct, _TEST_KEY)
    assert pt == plaintext


def test_ciphertext_is_not_deterministic():
    """Same plaintext + key must produce different ciphertexts (random nonce)."""
    plaintext = "secret-token"
    ct1 = encrypt_refresh_token(plaintext, _TEST_KEY)
    ct2 = encrypt_refresh_token(plaintext, _TEST_KEY)
    assert ct1 != ct2


def test_decrypt_with_wrong_key_raises():
    plaintext = "secret-token"
    ct = encrypt_refresh_token(plaintext, _TEST_KEY)
    wrong_key = b"y" * 32
    with pytest.raises(InvalidCiphertextError):
        decrypt_refresh_token(ct, wrong_key)


def test_decrypt_corrupted_ciphertext_raises():
    plaintext = "secret-token"
    ct = bytearray(encrypt_refresh_token(plaintext, _TEST_KEY))
    # Flip one bit in the body (after nonce).
    ct[20] ^= 0x01
    with pytest.raises(InvalidCiphertextError):
        decrypt_refresh_token(bytes(ct), _TEST_KEY)


def test_decrypt_truncated_ciphertext_raises():
    """Truncated ciphertext (shorter than nonce) must error cleanly."""
    with pytest.raises(InvalidCiphertextError):
        decrypt_refresh_token(b"too-short", _TEST_KEY)


def test_key_length_validated():
    """AES-256 requires exactly 32 bytes of key material."""
    short_key = b"too-short"
    with pytest.raises(ValueError, match="32 bytes"):
        encrypt_refresh_token("anything", short_key)


def test_derive_master_key_from_settings_yields_32_bytes():
    import secrets

    from src.auth.tokens import derive_master_key_from_settings

    raw = secrets.token_urlsafe(32)
    key = derive_master_key_from_settings(raw)
    assert len(key) == 32
    assert isinstance(key, bytes)


def test_derive_master_key_rejects_short_source():
    from src.auth.tokens import derive_master_key_from_settings

    with pytest.raises(ValueError, match="≥ 32"):
        derive_master_key_from_settings("short")
