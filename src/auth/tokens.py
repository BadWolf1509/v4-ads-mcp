"""AES-256-GCM encryption for refresh tokens at rest.

Stored format:  [12-byte nonce][ciphertext+16-byte tag]

The nonce is generated fresh per encryption (never reused with the
same key). AES-GCM's authentication tag is checked on decryption;
any tampering or wrong key raises InvalidCiphertextError.

Master key lives in Google Secret Manager and is loaded once at
app startup via Settings.aes_master_key. The key string is
expected to be 32 raw bytes encoded by `secrets.token_urlsafe(32)`
(which yields ~43 url-safe characters; the first 32 raw bytes of
the underlying entropy are used).
"""

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LEN = 12  # GCM-recommended


class InvalidCiphertextError(Exception):
    """Raised when ciphertext fails authentication or is malformed."""


def _validate_key(key: bytes) -> None:
    if len(key) != 32:
        raise ValueError(f"Master key must be 32 bytes (got {len(key)})")


def encrypt_refresh_token(plaintext: str, master_key: bytes) -> bytes:
    """Encrypt a refresh token with AES-256-GCM.

    Returns nonce || ciphertext+tag as raw bytes.
    """
    _validate_key(master_key)
    nonce = os.urandom(_NONCE_LEN)
    cipher = AESGCM(master_key)
    ct = cipher.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return nonce + ct


def decrypt_refresh_token(blob: bytes, master_key: bytes) -> str:
    """Decrypt a blob produced by encrypt_refresh_token. Raises on tamper/wrong key."""
    _validate_key(master_key)
    if len(blob) < _NONCE_LEN + 16:  # nonce + tag minimum
        raise InvalidCiphertextError("Ciphertext too short to be valid")
    nonce, ct = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    cipher = AESGCM(master_key)
    try:
        pt = cipher.decrypt(nonce, ct, associated_data=None)
    except InvalidTag as e:
        raise InvalidCiphertextError("Ciphertext authentication failed") from e
    return pt.decode("utf-8")


def derive_master_key_from_settings(raw: str) -> bytes:
    """Convert the AES_MASTER_KEY env value (urlsafe-base64 string) to 32 raw bytes.

    Settings stores the key as a urlsafe string for env-var hygiene; this helper
    decodes it to the 32-byte AESGCM key. Raises ValueError if the source can't
    yield 32 bytes.
    """
    # token_urlsafe(32) produces ~43 url-safe chars decoding to 32 bytes.
    import base64
    import binascii

    # Pad if needed so urlsafe_b64decode is happy.
    pad = (-len(raw)) % 4
    try:
        decoded = base64.urlsafe_b64decode(raw + ("=" * pad))
    except binascii.Error:
        # Invalid base64 is treated as insufficient entropy
        decoded = b""
    if len(decoded) < 32:
        raise ValueError(f"AES master key source decoded to {len(decoded)} bytes; need ≥ 32")
    return decoded[:32]
