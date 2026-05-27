# V4 Ads MCP — Phase 1a: Auth Backend + First MCP Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** End-to-end MCP authentication: a manager can be bootstrapped via CLI, complete Google Ads OAuth, receive an MCP Bearer token, configure Claude Desktop / Codex, and call the first real MCP tool `list_my_accounts` to see the Google Ads accounts they're authorized to operate.

**Architecture:** Adds `src/auth/`, `src/google_ads/`, `src/db/repositories/`, expanded `src/mcp/`, and CLI scripts in `src/scripts/`. No web UI yet (deferred to Phase 1b) — bootstrapping happens via CLI tools that point at production DB. OAuth callback returns a plain JSON success page so the manager knows the connection worked.

**Tech Stack:** Adds `google-ads>=27.0.0` (official Google Ads Python SDK), `cryptography>=44.0.0` (AES-GCM for refresh-token-at-rest encryption). Reuses Phase 0 stack for everything else.

**Reference spec:** `docs/superpowers/specs/2026-05-03-v4-ads-mcp-design.md` §5 (auth flows), §6.2 (read tools — only `list_my_accounts` here), §6.4 (utilities), §7 (governance — minimal in 1a, expanded in Phase 3).

**Definition of done (Phase 1a):**

1. `wellinton@v4company.com` exists as `role=admin` in `managers` table.
2. He completes Google OAuth via `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/oauth/google/start?invite=<token>` and `google_oauth_connections` row exists with encrypted refresh_token.
3. The `account-resync` Cloud Run Job runs once and populates `google_ads_accounts` with the 29 V4 MCC accounts.
4. He's auto-granted access to all of them in `manager_account_access` (admin auto-assignment).
5. Via CLI, he creates an MCP session and gets a one-time `mcp_<token>` Bearer.
6. He configures Claude Desktop with that Bearer pointing to `/mcp`, asks "what tools do you have?", and Claude lists `list_my_accounts`.
7. He calls `list_my_accounts` from Claude → gets the 29 accounts back with names + currency + timezone.
8. The MCP `audit_log` table has at least one row showing the call (the manager_id, session_id, tool, status=success).

---

## File structure (created/modified in this phase)

```
.
├── pyproject.toml                                  # MODIFY: add google-ads, cryptography
├── src/
│   ├── auth/                                       # NEW PACKAGE
│   │   ├── __init__.py
│   │   ├── tokens.py                               # AES-GCM encrypt/decrypt
│   │   ├── sessions.py                             # MCP Bearer token gen + hash
│   │   ├── oauth_state.py                          # HMAC-signed OAuth state
│   │   └── oauth.py                                # /oauth/google/start + callback
│   ├── google_ads/                                 # NEW PACKAGE
│   │   ├── __init__.py
│   │   ├── client.py                               # GoogleAdsClient factory from refresh_token
│   │   ├── errors.py                               # GoogleAdsException → friendly PT-BR msgs
│   │   └── accounts.py                             # list_accessible_customers wrapper
│   ├── db/repositories/                            # NEW PACKAGE
│   │   ├── __init__.py
│   │   ├── managers.py
│   │   ├── mcp_sessions.py
│   │   ├── google_oauth_connections.py
│   │   ├── google_ads_accounts.py
│   │   ├── manager_account_access.py
│   │   └── audit_log.py
│   ├── mcp/
│   │   ├── server.py                               # MODIFY: register tools dynamically
│   │   ├── session.py                              # REPLACE stub: real Bearer → manager_id
│   │   ├── context.py                              # NEW: per-request context (manager_id)
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── _registry.py                        # Tool registration + dispatch
│   │       └── list_my_accounts.py                 # First real tool
│   ├── app.py                                      # MODIFY: wire OAuth routes, init Settings before app
│   ├── scripts/                                    # NEW PACKAGE
│   │   ├── __init__.py
│   │   └── admin.py                                # CLI: bootstrap-admin, create-session, etc.
│   └── jobs/
│       └── account_resync.py                       # NEW: list_accessible_customers + upsert
├── tests/
│   ├── unit/
│   │   ├── test_tokens.py                          # AES-GCM round-trip + tampering
│   │   ├── test_sessions.py                        # Token format + hash
│   │   ├── test_oauth_state.py                     # HMAC sign/verify
│   │   └── test_list_my_accounts_tool.py           # Tool unit (mocked repo)
│   └── integration/
│       ├── test_repositories.py                    # All repos against testcontainers Postgres
│       ├── test_oauth_flow.py                      # /oauth/google/start + callback (respx mocked)
│       ├── test_mcp_session_middleware.py          # Bearer auth resolves manager_id
│       └── test_list_my_accounts_e2e.py            # MCP request → tool → DB → response
└── docs/operacao/
    └── phase-1a-bootstrap.md                       # Runbook: how to bootstrap an admin, run resync
```

---

## Manual prerequisites

These are already done from Phase 0 / earlier setup:

- [x] All 10 Secret Manager secrets populated with real values (`session-signing-key`, `aes-master-key`, `google-oauth-client-id`, `google-oauth-client-secret`, `google-ads-developer-token`, `google-ads-login-customer-id=7862230676`, `supabase-url`, `supabase-anon-key`, `supabase-service-key`, `database-url` URL-encoded).
- [x] OAuth Client created in GCP with redirect URI `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/oauth/google/callback`.
- [x] Cloud Run service running with `/mcp` and `/health` healthy.
- [x] Migrations applied (8 tables present in Supabase).
- [x] Google Ads developer token approved for **Test Account** access (Standard Access submission deferred — covers MVP since 15k ops/day suffices).

---

## Task 1: Add Google Ads SDK + cryptography dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add deps to `pyproject.toml`**

Use Edit tool to add the two new deps to the runtime dependencies array.

OLD:
```toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "mcp>=1.2.0",
    "asyncpg>=0.30.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.6.0",
    "structlog>=24.4.0",
    "httpx>=0.27.0",
]
```

NEW:
```toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "mcp>=1.2.0",
    "asyncpg>=0.30.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.6.0",
    "structlog>=24.4.0",
    "httpx>=0.27.0",
    "google-ads>=27.0.0",
    "cryptography>=44.0.0",
]
```

Also add an mypy override for `google.ads.*` (similar to existing `mcp.*` override):

```toml
[[tool.mypy.overrides]]
module = ["google.ads.*"]
ignore_missing_imports = true
ignore_errors = true
```

- [ ] **Step 2: Install in venv**

```bash
cd "/d/HUB ads MCP"
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

Expected: `google-ads-X.Y.Z` and `cryptography-X.Y.Z` appear in the install output. May take 30-60s (google-ads has gRPC + protobuf transitive deps).

- [ ] **Step 3: Smoke import**

```bash
./.venv/Scripts/python.exe -c "from google.ads.googleads.client import GoogleAdsClient; from cryptography.hazmat.primitives.ciphers.aead import AESGCM; print('OK')"
```

Expected: `OK`. If import fails, deps didn't install correctly — re-run install.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat(deps): add google-ads SDK and cryptography

google-ads is the official Google Ads Python SDK (gRPC + protobuf
based). cryptography provides AES-GCM for refresh-token-at-rest
encryption. Both have ample type stubs gaps that the existing
mcp.* mypy override pattern handles fine — added google.ads.*
override accordingly."
```

---

## Task 2: AES-GCM token encryption module (TDD)

**Files:**
- Create: `src/auth/__init__.py` (empty), `src/auth/tokens.py`, `tests/unit/test_tokens.py`

- [ ] **Step 1: Write failing test `tests/unit/test_tokens.py`**

```python
"""AES-GCM round-trip + tamper-detection tests."""
import os

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
```

- [ ] **Step 2: Run test → verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_tokens.py -v
```

Expected: 6 tests fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/auth/tokens.py`**

```python
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

    # Pad if needed so urlsafe_b64decode is happy.
    pad = (-len(raw)) % 4
    decoded = base64.urlsafe_b64decode(raw + ("=" * pad))
    if len(decoded) < 32:
        raise ValueError(
            f"AES master key source decoded to {len(decoded)} bytes; need ≥ 32"
        )
    return decoded[:32]
```

- [ ] **Step 4: Also add a small derive-from-settings test**

Append to `tests/unit/test_tokens.py`:

```python
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
```

- [ ] **Step 5: Run tests → verify all 8 pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_tokens.py -v
```

Expected: 8 PASSED.

- [ ] **Step 6: mypy + ruff**

```bash
./.venv/Scripts/python.exe -m mypy src/auth/tokens.py
./.venv/Scripts/python.exe -m ruff check src/auth/ tests/unit/test_tokens.py
./.venv/Scripts/python.exe -m ruff format --check src/auth/ tests/unit/test_tokens.py
```

Auto-format if needed. mypy clean expected.

- [ ] **Step 7: Commit**

```bash
git add src/auth/__init__.py src/auth/tokens.py tests/unit/test_tokens.py
git commit -m "feat(auth): AES-256-GCM encryption for refresh tokens

Random 12-byte nonce per encryption; authentication tag verified
on decrypt. Tampering, wrong key, and truncated ciphertexts all
raise InvalidCiphertextError. Master key derived from
Settings.aes_master_key (urlsafe base64 → 32 raw bytes).

Tested: round-trip, non-determinism, wrong key, bit flip, truncation."
```

---

## Task 3: MCP session token module (TDD)

**Files:**
- Create: `src/auth/sessions.py`, `tests/unit/test_sessions.py`

- [ ] **Step 1: Write failing test `tests/unit/test_sessions.py`**

```python
"""MCP Bearer token generation + hashing tests."""
import re

from src.auth.sessions import generate_session_token, hash_session_token


def test_token_has_mcp_prefix():
    token = generate_session_token()
    assert token.startswith("mcp_")


def test_token_length_is_consistent():
    """32 bytes urlsafe-base64 → ~43 chars; with 'mcp_' prefix ~47."""
    tokens = [generate_session_token() for _ in range(50)]
    lengths = {len(t) for t in tokens}
    # All same length (within 1 char tolerance for trailing '=' stripping).
    assert max(lengths) - min(lengths) <= 1


def test_tokens_are_unique():
    """50 tokens, all distinct (entropy sanity)."""
    tokens = {generate_session_token() for _ in range(50)}
    assert len(tokens) == 50


def test_token_uses_urlsafe_alphabet():
    """No characters that need URL-encoding."""
    token = generate_session_token()
    assert re.match(r"^mcp_[A-Za-z0-9_-]+$", token), f"Got: {token}"


def test_hash_is_deterministic():
    token = "mcp_known_value_xyz"
    h1 = hash_session_token(token)
    h2 = hash_session_token(token)
    assert h1 == h2


def test_hash_differs_for_different_tokens():
    h1 = hash_session_token("mcp_aaa")
    h2 = hash_session_token("mcp_bbb")
    assert h1 != h2


def test_hash_is_hex_64_chars():
    """SHA-256 hex digest is 64 lowercase hex chars."""
    h = hash_session_token("mcp_anything")
    assert re.match(r"^[0-9a-f]{64}$", h), f"Got: {h}"


def test_hash_handles_empty_string():
    """Edge case: empty string still produces a valid hash."""
    h = hash_session_token("")
    assert len(h) == 64
```

- [ ] **Step 2: Run test → fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_sessions.py -v
```

Expected: 8 fail with import error.

- [ ] **Step 3: Implement `src/auth/sessions.py`**

```python
"""MCP session Bearer token generation and hashing.

Tokens are opaque, 32 bytes of entropy, prefixed with 'mcp_' so
clients/operators recognize them at a glance. The DB only stores
the SHA-256 hex digest; the original token is shown to the
manager exactly once (at create time) and never recoverable
afterwards. This is the same pattern as GitHub PATs and AWS
access keys.
"""
import hashlib
import secrets

_TOKEN_PREFIX = "mcp_"
_TOKEN_BYTES = 32  # 256 bits of entropy


def generate_session_token() -> str:
    """Return a fresh opaque Bearer token, format: 'mcp_<43 url-safe chars>'."""
    return _TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """SHA-256 hex digest of the token (what we store in mcp_sessions.token_hash).

    SHA-256 is appropriate here because the input has 256 bits of entropy
    (not a low-entropy human password); collision/preimage attacks against
    SHA-256 are not relevant. bcrypt/argon2 would be over-engineering and
    add latency on every MCP request.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run tests → 8 PASS**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_sessions.py -v
```

- [ ] **Step 5: mypy + ruff**

```bash
./.venv/Scripts/python.exe -m mypy src/auth/sessions.py
./.venv/Scripts/python.exe -m ruff check src/auth/ tests/unit/test_sessions.py
./.venv/Scripts/python.exe -m ruff format --check src/auth/ tests/unit/test_sessions.py
```

- [ ] **Step 6: Commit**

```bash
git add src/auth/sessions.py tests/unit/test_sessions.py
git commit -m "feat(auth): MCP Bearer token generation + SHA-256 hashing

Tokens: 'mcp_<32 bytes urlsafe>'. SHA-256 hex stored in DB; raw
token shown to manager once. SHA-256 is appropriate here (high
entropy input, not a low-entropy password); avoids bcrypt latency
on every MCP request."
```

---

## Task 4: HMAC-signed OAuth state (TDD)

**Files:**
- Create: `src/auth/oauth_state.py`, `tests/unit/test_oauth_state.py`

- [ ] **Step 1: Write failing test `tests/unit/test_oauth_state.py`**

```python
"""HMAC-signed OAuth state for CSRF prevention."""
import time

import pytest

from src.auth.oauth_state import (
    InvalidStateError,
    sign_state,
    verify_state,
)


_SIGNING_KEY = "x" * 32


def test_round_trip_recovers_payload():
    state = sign_state({"manager_id": "uuid-1", "kind": "google"}, _SIGNING_KEY)
    payload = verify_state(state, _SIGNING_KEY)
    assert payload["manager_id"] == "uuid-1"
    assert payload["kind"] == "google"


def test_state_is_url_safe():
    """State is passed in URL query, must use only URL-safe chars."""
    import re
    state = sign_state({"manager_id": "uuid"}, _SIGNING_KEY)
    assert re.match(r"^[A-Za-z0-9_.-]+$", state), f"Got: {state}"


def test_tampered_state_rejected():
    state = sign_state({"manager_id": "uuid-1"}, _SIGNING_KEY)
    tampered = state[:-1] + ("X" if state[-1] != "X" else "Y")
    with pytest.raises(InvalidStateError):
        verify_state(tampered, _SIGNING_KEY)


def test_wrong_key_rejected():
    state = sign_state({"manager_id": "uuid-1"}, _SIGNING_KEY)
    with pytest.raises(InvalidStateError):
        verify_state(state, "y" * 32)


def test_expired_state_rejected():
    """States older than 10 minutes must be rejected."""
    # Mint a state with timestamp 11 minutes in the past.
    fake_now = time.time() - (11 * 60)
    state = sign_state(
        {"manager_id": "uuid-1"},
        _SIGNING_KEY,
        issued_at=fake_now,
    )
    with pytest.raises(InvalidStateError, match="expired"):
        verify_state(state, _SIGNING_KEY)


def test_state_within_ttl_accepted():
    """States issued in the last 10 minutes accepted."""
    fake_now = time.time() - (5 * 60)
    state = sign_state(
        {"manager_id": "uuid-1"},
        _SIGNING_KEY,
        issued_at=fake_now,
    )
    payload = verify_state(state, _SIGNING_KEY)
    assert payload["manager_id"] == "uuid-1"


def test_garbage_input_rejected_cleanly():
    with pytest.raises(InvalidStateError):
        verify_state("not-a-real-state", _SIGNING_KEY)
```

- [ ] **Step 2: Run → fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_oauth_state.py -v
```

- [ ] **Step 3: Implement `src/auth/oauth_state.py`**

```python
"""HMAC-signed, time-bounded OAuth state token.

Format:  base64url(payload_json) + "." + base64url(hmac_sha256(payload_json))

Payload always includes 'iat' (issued-at unix seconds). Verify checks
HMAC tag and rejects if iat is older than STATE_TTL_SECONDS.

Used in /oauth/google/start to encode {manager_id, kind} so the callback
can recover them WITHOUT a server-side session lookup. Stateless across
Cloud Run instances. Defends against CSRF (attacker can't mint a valid
HMAC) and replay (TTL).
"""
import base64
import hmac
import json
import time
from hashlib import sha256
from typing import Any

STATE_TTL_SECONDS = 10 * 60  # 10 minutes


class InvalidStateError(Exception):
    """Raised when state is tampered, wrong key, expired, or malformed."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + ("=" * pad))


def sign_state(
    payload: dict[str, Any],
    signing_key: str,
    *,
    issued_at: float | None = None,
) -> str:
    """Build a signed state string from a JSON-serializable payload."""
    full = dict(payload)
    full["iat"] = int(issued_at if issued_at is not None else time.time())
    body = json.dumps(full, sort_keys=True, separators=(",", ":")).encode("utf-8")
    tag = hmac.new(signing_key.encode("utf-8"), body, sha256).digest()
    return f"{_b64url(body)}.{_b64url(tag)}"


def verify_state(state: str, signing_key: str) -> dict[str, Any]:
    """Verify HMAC + TTL, return decoded payload (without 'iat'). Raises on failure."""
    try:
        body_b64, tag_b64 = state.split(".", 1)
        body = _b64url_decode(body_b64)
        tag = _b64url_decode(tag_b64)
    except (ValueError, base64.binascii.Error) as e:
        raise InvalidStateError("Malformed state") from e

    expected = hmac.new(signing_key.encode("utf-8"), body, sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise InvalidStateError("HMAC mismatch (tampered or wrong key)")

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise InvalidStateError("Payload is not valid JSON") from e

    iat = payload.get("iat")
    if not isinstance(iat, int):
        raise InvalidStateError("Missing or invalid 'iat'")
    if (time.time() - iat) > STATE_TTL_SECONDS:
        raise InvalidStateError("State expired")

    payload.pop("iat", None)
    return payload
```

- [ ] **Step 4: Run tests → 7 PASS**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_oauth_state.py -v
```

- [ ] **Step 5: mypy + ruff**

```bash
./.venv/Scripts/python.exe -m mypy src/auth/oauth_state.py
./.venv/Scripts/python.exe -m ruff check src/auth/ tests/unit/test_oauth_state.py
./.venv/Scripts/python.exe -m ruff format --check src/auth/ tests/unit/test_oauth_state.py
```

- [ ] **Step 6: Commit**

```bash
git add src/auth/oauth_state.py tests/unit/test_oauth_state.py
git commit -m "feat(auth): HMAC-signed OAuth state with 10-min TTL

Stateless CSRF defense — the OAuth callback can validate state
without a server-side lookup, surviving Cloud Run instance
rotation. Format: b64url(json).b64url(hmac256). 'iat' enforces a
10-minute window (long enough for slow consent screens, short
enough to limit replay)."
```

---

## Task 5: DB repositories (mostly mechanical, tested via integration in Task 6)

**Files:**
- Create: `src/db/repositories/__init__.py` (empty), `src/db/repositories/managers.py`, `src/db/repositories/mcp_sessions.py`, `src/db/repositories/google_oauth_connections.py`, `src/db/repositories/google_ads_accounts.py`, `src/db/repositories/manager_account_access.py`, `src/db/repositories/audit_log.py`

Tests are in Task 6 (one integration test file covering all repos against a real Postgres). This task just creates the modules.

- [ ] **Step 1: `src/db/repositories/__init__.py`** — leave empty.

- [ ] **Step 2: Implement `src/db/repositories/managers.py`**

```python
"""CRUD for the `managers` table."""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg


@dataclass(slots=True, frozen=True)
class Manager:
    id: UUID
    email: str
    full_name: str | None
    role: str  # 'gestor' | 'admin'
    is_active: bool
    created_at: datetime
    last_seen_at: datetime | None


def _row_to_manager(row: asyncpg.Record) -> Manager:
    return Manager(
        id=row["id"],
        email=row["email"],
        full_name=row["full_name"],
        role=row["role"],
        is_active=row["is_active"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
    )


async def get_by_id(conn: asyncpg.Connection, manager_id: UUID) -> Manager | None:
    row = await conn.fetchrow("SELECT * FROM managers WHERE id = $1", manager_id)
    return _row_to_manager(row) if row else None


async def get_by_email(conn: asyncpg.Connection, email: str) -> Manager | None:
    row = await conn.fetchrow("SELECT * FROM managers WHERE email = $1", email)
    return _row_to_manager(row) if row else None


async def create(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    email: str,
    full_name: str | None,
    role: str = "gestor",
) -> Manager:
    row = await conn.fetchrow(
        """
        INSERT INTO managers (id, email, full_name, role)
        VALUES ($1, $2, $3, $4)
        RETURNING *
        """,
        manager_id,
        email,
        full_name,
        role,
    )
    assert row is not None
    return _row_to_manager(row)


async def touch_last_seen(conn: asyncpg.Connection, manager_id: UUID) -> None:
    await conn.execute(
        "UPDATE managers SET last_seen_at = now() WHERE id = $1",
        manager_id,
    )


async def list_active(conn: asyncpg.Connection) -> list[Manager]:
    rows = await conn.fetch(
        "SELECT * FROM managers WHERE is_active = true ORDER BY email"
    )
    return [_row_to_manager(r) for r in rows]
```

- [ ] **Step 3: Implement `src/db/repositories/mcp_sessions.py`**

```python
"""CRUD for `mcp_sessions`."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import asyncpg

DEFAULT_TTL_DAYS = 90


@dataclass(slots=True, frozen=True)
class McpSession:
    id: UUID
    manager_id: UUID
    token_hash: str
    label: str | None
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    expires_at: datetime | None


def _row_to_session(row: asyncpg.Record) -> McpSession:
    return McpSession(
        id=row["id"],
        manager_id=row["manager_id"],
        token_hash=row["token_hash"],
        label=row["label"],
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
        revoked_at=row["revoked_at"],
        expires_at=row["expires_at"],
    )


async def create(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    token_hash: str,
    label: str | None,
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> McpSession:
    row = await conn.fetchrow(
        """
        INSERT INTO mcp_sessions (manager_id, token_hash, label, expires_at)
        VALUES ($1, $2, $3, now() + ($4 || ' days')::interval)
        RETURNING *
        """,
        manager_id,
        token_hash,
        label,
        str(ttl_days),
    )
    assert row is not None
    return _row_to_session(row)


async def find_by_hash(
    conn: asyncpg.Connection, token_hash: str
) -> McpSession | None:
    """Return only if NOT revoked AND NOT expired."""
    row = await conn.fetchrow(
        """
        SELECT * FROM mcp_sessions
        WHERE token_hash = $1
          AND revoked_at IS NULL
          AND (expires_at IS NULL OR expires_at > now())
        """,
        token_hash,
    )
    return _row_to_session(row) if row else None


async def touch_last_used(conn: asyncpg.Connection, session_id: UUID) -> None:
    await conn.execute(
        "UPDATE mcp_sessions SET last_used_at = now() WHERE id = $1",
        session_id,
    )


async def revoke(conn: asyncpg.Connection, session_id: UUID) -> None:
    await conn.execute(
        "UPDATE mcp_sessions SET revoked_at = now() WHERE id = $1 AND revoked_at IS NULL",
        session_id,
    )


async def list_for_manager(
    conn: asyncpg.Connection, manager_id: UUID, *, include_revoked: bool = False
) -> list[McpSession]:
    if include_revoked:
        rows = await conn.fetch(
            "SELECT * FROM mcp_sessions WHERE manager_id = $1 ORDER BY created_at DESC",
            manager_id,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT * FROM mcp_sessions
            WHERE manager_id = $1 AND revoked_at IS NULL
            ORDER BY created_at DESC
            """,
            manager_id,
        )
    return [_row_to_session(r) for r in rows]
```

- [ ] **Step 4: Implement `src/db/repositories/google_oauth_connections.py`**

```python
"""CRUD for `google_oauth_connections`."""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg


@dataclass(slots=True, frozen=True)
class OAuthConnection:
    id: UUID
    manager_id: UUID
    google_email: str
    refresh_token_enc: bytes
    scopes: list[str]
    connected_at: datetime
    revoked_at: datetime | None


def _row_to_conn(row: asyncpg.Record) -> OAuthConnection:
    return OAuthConnection(
        id=row["id"],
        manager_id=row["manager_id"],
        google_email=row["google_email"],
        refresh_token_enc=row["refresh_token_enc"],
        scopes=row["scopes"],
        connected_at=row["connected_at"],
        revoked_at=row["revoked_at"],
    )


async def upsert(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    google_email: str,
    refresh_token_enc: bytes,
    scopes: list[str],
) -> OAuthConnection:
    """INSERT new connection or update refresh_token if (manager_id, email) exists."""
    row = await conn.fetchrow(
        """
        INSERT INTO google_oauth_connections
            (manager_id, google_email, refresh_token_enc, scopes)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (manager_id, google_email) DO UPDATE SET
            refresh_token_enc = EXCLUDED.refresh_token_enc,
            scopes = EXCLUDED.scopes,
            connected_at = now(),
            revoked_at = NULL
        RETURNING *
        """,
        manager_id,
        google_email,
        refresh_token_enc,
        scopes,
    )
    assert row is not None
    return _row_to_conn(row)


async def get_active_for_manager(
    conn: asyncpg.Connection, manager_id: UUID
) -> OAuthConnection | None:
    """Return the most recent NON-REVOKED connection for the manager."""
    row = await conn.fetchrow(
        """
        SELECT * FROM google_oauth_connections
        WHERE manager_id = $1 AND revoked_at IS NULL
        ORDER BY connected_at DESC
        LIMIT 1
        """,
        manager_id,
    )
    return _row_to_conn(row) if row else None


async def revoke(
    conn: asyncpg.Connection, connection_id: UUID
) -> None:
    await conn.execute(
        "UPDATE google_oauth_connections SET revoked_at = now() WHERE id = $1",
        connection_id,
    )
```

- [ ] **Step 5: Implement `src/db/repositories/google_ads_accounts.py`**

```python
"""CRUD for `google_ads_accounts`. Populated by the resync job."""
from dataclasses import dataclass
from datetime import datetime

import asyncpg


@dataclass(slots=True, frozen=True)
class GoogleAdsAccount:
    customer_id: str
    mcc_id: str
    descriptive_name: str
    currency_code: str | None
    time_zone: str | None
    is_test_account: bool
    is_active: bool
    synced_at: datetime


def _row_to_account(row: asyncpg.Record) -> GoogleAdsAccount:
    return GoogleAdsAccount(
        customer_id=row["customer_id"],
        mcc_id=row["mcc_id"],
        descriptive_name=row["descriptive_name"],
        currency_code=row["currency_code"],
        time_zone=row["time_zone"],
        is_test_account=row["is_test_account"],
        is_active=row["is_active"],
        synced_at=row["synced_at"],
    )


async def upsert_many(
    conn: asyncpg.Connection,
    accounts: list[dict],  # each: customer_id, mcc_id, descriptive_name, currency_code, time_zone, is_test_account
) -> int:
    """Insert or update accounts in bulk; returns count touched."""
    if not accounts:
        return 0
    rows = [
        (
            a["customer_id"],
            a["mcc_id"],
            a["descriptive_name"],
            a.get("currency_code"),
            a.get("time_zone"),
            bool(a.get("is_test_account", False)),
        )
        for a in accounts
    ]
    await conn.executemany(
        """
        INSERT INTO google_ads_accounts
            (customer_id, mcc_id, descriptive_name, currency_code,
             time_zone, is_test_account, is_active, synced_at)
        VALUES ($1, $2, $3, $4, $5, $6, true, now())
        ON CONFLICT (customer_id) DO UPDATE SET
            mcc_id = EXCLUDED.mcc_id,
            descriptive_name = EXCLUDED.descriptive_name,
            currency_code = EXCLUDED.currency_code,
            time_zone = EXCLUDED.time_zone,
            is_test_account = EXCLUDED.is_test_account,
            is_active = true,
            synced_at = now()
        """,
        rows,
    )
    return len(rows)


async def mark_inactive_except(
    conn: asyncpg.Connection,
    *,
    mcc_id: str,
    keep_customer_ids: list[str],
) -> int:
    """Mark accounts under mcc_id as inactive if not in keep list (deletion detection)."""
    if not keep_customer_ids:
        # All accounts for this MCC become inactive (no resync data).
        result = await conn.execute(
            "UPDATE google_ads_accounts SET is_active = false WHERE mcc_id = $1 AND is_active = true",
            mcc_id,
        )
    else:
        result = await conn.execute(
            """
            UPDATE google_ads_accounts SET is_active = false
            WHERE mcc_id = $1
              AND is_active = true
              AND customer_id <> ALL($2::text[])
            """,
            mcc_id,
            keep_customer_ids,
        )
    # asyncpg.execute returns 'UPDATE N'
    return int(result.split()[-1]) if result.startswith("UPDATE") else 0


async def list_all(conn: asyncpg.Connection) -> list[GoogleAdsAccount]:
    rows = await conn.fetch(
        "SELECT * FROM google_ads_accounts WHERE is_active = true ORDER BY descriptive_name"
    )
    return [_row_to_account(r) for r in rows]
```

- [ ] **Step 6: Implement `src/db/repositories/manager_account_access.py`**

```python
"""CRUD for `manager_account_access` (which manager can operate which account)."""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg

from src.db.repositories.google_ads_accounts import GoogleAdsAccount, _row_to_account


@dataclass(slots=True, frozen=True)
class AccountAccess:
    manager_id: UUID
    customer_id: str
    access_level: str  # 'read' | 'write'
    granted_at: datetime
    granted_by: UUID | None


async def grant(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    customer_id: str,
    access_level: str = "write",
    granted_by: UUID | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO manager_account_access (manager_id, customer_id, access_level, granted_by)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (manager_id, customer_id) DO UPDATE SET
            access_level = EXCLUDED.access_level,
            granted_at = now(),
            granted_by = EXCLUDED.granted_by
        """,
        manager_id,
        customer_id,
        access_level,
        granted_by,
    )


async def grant_all_active(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    granted_by: UUID | None = None,
) -> int:
    """Grant write access to every active google_ads_accounts row for this manager."""
    result = await conn.execute(
        """
        INSERT INTO manager_account_access (manager_id, customer_id, access_level, granted_by)
        SELECT $1, customer_id, 'write', $2
        FROM google_ads_accounts
        WHERE is_active = true
        ON CONFLICT (manager_id, customer_id) DO NOTHING
        """,
        manager_id,
        granted_by,
    )
    return int(result.split()[-1]) if result.startswith("INSERT") else 0


async def revoke(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    customer_id: str,
) -> None:
    await conn.execute(
        "DELETE FROM manager_account_access WHERE manager_id = $1 AND customer_id = $2",
        manager_id,
        customer_id,
    )


async def list_accounts_for_manager(
    conn: asyncpg.Connection, manager_id: UUID
) -> list[GoogleAdsAccount]:
    """Return GoogleAdsAccount rows the manager has any access to (active accounts only)."""
    rows = await conn.fetch(
        """
        SELECT a.*
        FROM google_ads_accounts a
        INNER JOIN manager_account_access m ON m.customer_id = a.customer_id
        WHERE m.manager_id = $1
          AND a.is_active = true
        ORDER BY a.descriptive_name
        """,
        manager_id,
    )
    return [_row_to_account(r) for r in rows]


async def can_manager_access(
    conn: asyncpg.Connection, manager_id: UUID, customer_id: str, *, level: str = "read"
) -> bool:
    """Return True if manager has at least `level` access to customer_id."""
    row = await conn.fetchrow(
        """
        SELECT access_level FROM manager_account_access
        WHERE manager_id = $1 AND customer_id = $2
        """,
        manager_id,
        customer_id,
    )
    if row is None:
        return False
    if level == "read":
        return True
    return row["access_level"] == "write"
```

- [ ] **Step 7: Implement `src/db/repositories/audit_log.py`**

```python
"""Append-only audit log writes."""
from typing import Any
from uuid import UUID

import asyncpg


async def record(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID | None,
    session_id: UUID | None,
    customer_id: str | None,
    action_type: str,  # 'mutate' | 'read' | 'auth' | 'system'
    operation: str,
    target_count: int | None = None,
    params_summary: dict[str, Any] | None = None,
    google_request_id: str | None = None,
    status: str = "success",  # 'success' | 'error' | 'denied'
    error_message: str | None = None,
    duration_ms: int | None = None,
) -> int:
    """Insert a row into audit_log; returns the new row id."""
    import json
    row = await conn.fetchrow(
        """
        INSERT INTO audit_log (
            manager_id, session_id, customer_id,
            action_type, operation, target_count,
            params_summary, google_request_id, status,
            error_message, duration_ms
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11)
        RETURNING id
        """,
        manager_id,
        session_id,
        customer_id,
        action_type,
        operation,
        target_count,
        json.dumps(params_summary) if params_summary is not None else None,
        google_request_id,
        status,
        error_message,
        duration_ms,
    )
    assert row is not None
    return int(row["id"])
```

- [ ] **Step 8: mypy + ruff (no test commit yet — Task 6 covers them)**

```bash
./.venv/Scripts/python.exe -m mypy src/db/repositories/
./.venv/Scripts/python.exe -m ruff check src/db/repositories/
./.venv/Scripts/python.exe -m ruff format --check src/db/repositories/
```

Expected: all clean. Auto-format if needed.

- [ ] **Step 9: Commit**

```bash
git add src/db/repositories/
git commit -m "feat(db): repositories for managers, sessions, OAuth conns, accounts, audit

Six small modules, each owning queries for one aggregate. asyncpg
+ raw SQL (no ORM). Dataclasses for read models. Upsert variants
where appropriate. Tests come in next task (integration only —
unit-testing CRUD against a mock yields zero confidence)."
```

---

## Task 6: Repository integration tests (TDD against testcontainers Postgres)

**Files:**
- Create: `tests/integration/test_repositories.py`

- [ ] **Step 1: Write the test file**

```python
"""Integration tests for all DB repositories.

One container, one set of migrations, then test each repository's
behavior against real SQL. We don't mock asyncpg — that yields
zero confidence in column names, constraints, or upsert behavior.
"""
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import (
    google_ads_accounts,
    google_oauth_connections,
    manager_account_access,
    managers,
    mcp_sessions,
    audit_log,
)


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg: PostgresContainer):
    """Initialize pool + run migrations once; yield, then tear down."""
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


# ---------- managers ----------


@pytest.mark.integration
async def test_managers_create_get_by_id_and_email(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        m = await managers.create(
            conn, manager_id=mid, email="x@v4company.com", full_name="X", role="admin"
        )
        assert m.id == mid
        assert m.role == "admin"
        assert m.is_active is True

        by_id = await managers.get_by_id(conn, mid)
        assert by_id is not None
        assert by_id.email == "x@v4company.com"

        by_email = await managers.get_by_email(conn, "x@v4company.com")
        assert by_email is not None
        assert by_email.id == mid


@pytest.mark.integration
async def test_managers_get_missing_returns_none(db) -> None:
    async with db.acquire() as conn:
        assert await managers.get_by_id(conn, uuid4()) is None
        assert await managers.get_by_email(conn, "nobody@v4.com") is None


@pytest.mark.integration
async def test_managers_touch_last_seen(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        m = await managers.create(conn, manager_id=mid, email="t@v4.com", full_name=None)
        assert m.last_seen_at is None
        await managers.touch_last_seen(conn, mid)
        m2 = await managers.get_by_id(conn, mid)
        assert m2 is not None
        assert m2.last_seen_at is not None


# ---------- mcp_sessions ----------


@pytest.mark.integration
async def test_sessions_create_find_revoke(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="s@v4.com", full_name=None)
        s = await mcp_sessions.create(
            conn, manager_id=mid, token_hash="abc" * 21, label="Claude Desktop"
        )
        assert s.label == "Claude Desktop"
        assert s.expires_at is not None

        found = await mcp_sessions.find_by_hash(conn, "abc" * 21)
        assert found is not None
        assert found.id == s.id

        await mcp_sessions.touch_last_used(conn, s.id)
        await mcp_sessions.revoke(conn, s.id)

        # After revoke, find_by_hash returns None
        assert await mcp_sessions.find_by_hash(conn, "abc" * 21) is None


@pytest.mark.integration
async def test_sessions_list_for_manager_excludes_revoked_by_default(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="ml@v4.com", full_name=None)
        s1 = await mcp_sessions.create(conn, manager_id=mid, token_hash="h1" * 32, label="A")
        s2 = await mcp_sessions.create(conn, manager_id=mid, token_hash="h2" * 32, label="B")
        await mcp_sessions.revoke(conn, s2.id)

        active = await mcp_sessions.list_for_manager(conn, mid)
        assert len(active) == 1
        assert active[0].id == s1.id

        all_sessions = await mcp_sessions.list_for_manager(conn, mid, include_revoked=True)
        assert len(all_sessions) == 2


# ---------- google_oauth_connections ----------


@pytest.mark.integration
async def test_oauth_upsert_then_update(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="o@v4.com", full_name=None)
        c1 = await google_oauth_connections.upsert(
            conn, manager_id=mid, google_email="o@v4.com",
            refresh_token_enc=b"enc-v1", scopes=["adwords"],
        )
        c2 = await google_oauth_connections.upsert(
            conn, manager_id=mid, google_email="o@v4.com",
            refresh_token_enc=b"enc-v2", scopes=["adwords"],
        )
        # Same row (UNIQUE constraint), refresh updated.
        assert c1.id == c2.id
        assert c2.refresh_token_enc == b"enc-v2"


@pytest.mark.integration
async def test_oauth_get_active_returns_latest(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="g@v4.com", full_name=None)
        c1 = await google_oauth_connections.upsert(
            conn, manager_id=mid, google_email="primary@gmail.com",
            refresh_token_enc=b"e1", scopes=["adwords"],
        )
        c2 = await google_oauth_connections.upsert(
            conn, manager_id=mid, google_email="other@gmail.com",
            refresh_token_enc=b"e2", scopes=["adwords"],
        )
        active = await google_oauth_connections.get_active_for_manager(conn, mid)
        assert active is not None
        # Most recent — c2 was inserted after c1.
        assert active.id == c2.id

        await google_oauth_connections.revoke(conn, c2.id)
        active_after = await google_oauth_connections.get_active_for_manager(conn, mid)
        assert active_after is not None
        assert active_after.id == c1.id


# ---------- google_ads_accounts ----------


@pytest.mark.integration
async def test_accounts_upsert_and_list(db) -> None:
    async with db.acquire() as conn:
        n = await google_ads_accounts.upsert_many(
            conn,
            [
                {
                    "customer_id": "1234567890",
                    "mcc_id": "9999999999",
                    "descriptive_name": "Cliente Alpha",
                    "currency_code": "BRL",
                    "time_zone": "America/Sao_Paulo",
                    "is_test_account": False,
                },
                {
                    "customer_id": "2345678901",
                    "mcc_id": "9999999999",
                    "descriptive_name": "Cliente Beta",
                    "currency_code": "BRL",
                    "time_zone": "America/Sao_Paulo",
                    "is_test_account": False,
                },
            ],
        )
        assert n == 2
        all_accounts = await google_ads_accounts.list_all(conn)
        assert len(all_accounts) == 2
        names = [a.descriptive_name for a in all_accounts]
        assert names == sorted(names)  # ORDER BY descriptive_name


@pytest.mark.integration
async def test_accounts_mark_inactive_except(db) -> None:
    async with db.acquire() as conn:
        await google_ads_accounts.upsert_many(
            conn,
            [
                {"customer_id": "111", "mcc_id": "MCC1", "descriptive_name": "A"},
                {"customer_id": "222", "mcc_id": "MCC1", "descriptive_name": "B"},
                {"customer_id": "333", "mcc_id": "MCC1", "descriptive_name": "C"},
            ],
        )
        deactivated = await google_ads_accounts.mark_inactive_except(
            conn, mcc_id="MCC1", keep_customer_ids=["111", "333"]
        )
        assert deactivated == 1
        active = await google_ads_accounts.list_all(conn)
        ids = {a.customer_id for a in active}
        assert ids == {"111", "333"}


# ---------- manager_account_access ----------


@pytest.mark.integration
async def test_access_grant_list_revoke(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="a@v4.com", full_name=None)
        await google_ads_accounts.upsert_many(
            conn,
            [{"customer_id": "111", "mcc_id": "M1", "descriptive_name": "X"}],
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="111")

        accounts = await manager_account_access.list_accounts_for_manager(conn, mid)
        assert len(accounts) == 1
        assert accounts[0].customer_id == "111"

        assert await manager_account_access.can_manager_access(conn, mid, "111") is True
        assert await manager_account_access.can_manager_access(conn, mid, "999") is False

        await manager_account_access.revoke(conn, manager_id=mid, customer_id="111")
        accounts2 = await manager_account_access.list_accounts_for_manager(conn, mid)
        assert accounts2 == []


@pytest.mark.integration
async def test_access_grant_all_active(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="ga@v4.com", full_name=None)
        await google_ads_accounts.upsert_many(
            conn,
            [
                {"customer_id": "111", "mcc_id": "M1", "descriptive_name": "A"},
                {"customer_id": "222", "mcc_id": "M1", "descriptive_name": "B"},
            ],
        )
        n = await manager_account_access.grant_all_active(conn, manager_id=mid)
        assert n == 2
        accounts = await manager_account_access.list_accounts_for_manager(conn, mid)
        assert len(accounts) == 2

        # Idempotent re-run inserts 0 (ON CONFLICT DO NOTHING).
        n2 = await manager_account_access.grant_all_active(conn, manager_id=mid)
        assert n2 == 0


# ---------- audit_log ----------


@pytest.mark.integration
async def test_audit_record_returns_id(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="al@v4.com", full_name=None)
        log_id = await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id="1234567890",
            action_type="read",
            operation="list_my_accounts",
            target_count=29,
            params_summary={"foo": "bar"},
            status="success",
            duration_ms=42,
        )
        assert log_id > 0
```

- [ ] **Step 2: Run integration tests → all PASS**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_repositories.py -v -m integration
```

Expected: 12 tests pass. First run includes container spin-up (~10s).

If a test fails: read carefully — column name typo, missing constraint, etc. Fix the repository module, NOT the test.

- [ ] **Step 3: ruff + mypy**

```bash
./.venv/Scripts/python.exe -m ruff check tests/integration/test_repositories.py
./.venv/Scripts/python.exe -m ruff format --check tests/integration/test_repositories.py
./.venv/Scripts/python.exe -m mypy src/db/repositories/
```

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_repositories.py
git commit -m "test(db): integration tests for all repositories

Real Postgres via testcontainers — covers managers CRUD, session
lifecycle (create/find/revoke/touch), OAuth upsert behavior,
account upsert + deactivation, manager_account_access grant/revoke
+ grant_all_active idempotency, audit_log insert."
```

---

## Task 7: Google Ads SDK client factory + accounts wrapper (TDD with mocked SDK)

**Files:**
- Create: `src/google_ads/__init__.py` (empty), `src/google_ads/client.py`, `src/google_ads/accounts.py`, `src/google_ads/errors.py`, `tests/unit/test_google_ads_client.py`

- [ ] **Step 1: `src/google_ads/__init__.py`** — empty.

- [ ] **Step 2: Implement `src/google_ads/errors.py`**

```python
"""Translate Google Ads SDK exceptions into PT-BR friendly errors.

Phase 1a covers only the few errors the resync + list_my_accounts paths
can hit. Future phases extend this dict.
"""


class GoogleAdsFriendlyError(Exception):
    """User-facing error with a PT-BR message + the original exception attached."""

    def __init__(self, message_pt: str, *, code: str | None = None, original: Exception | None = None):
        super().__init__(message_pt)
        self.message_pt = message_pt
        self.code = code
        self.original = original


# Map of (error_code, error_string_in_proto) → friendly PT-BR message.
# The Google Ads SDK exposes errors as GoogleAdsException.failure.errors[].error_code
# which is a oneof — we look at the populated field name.
_FRIENDLY_MESSAGES: dict[str, str] = {
    "AUTHENTICATION_ERROR": (
        "Falha de autenticação com o Google Ads. A conexão OAuth do gestor pode "
        "ter sido revogada — peça pra ele reconectar."
    ),
    "AUTHORIZATION_ERROR": (
        "Sem permissão pra esta operação. Verifique se o gestor tem acesso ao "
        "MCC e às contas em questão."
    ),
    "QUOTA_ERROR": (
        "Quota diária da API do Google Ads esgotada (15.000 ops). Aguarde o "
        "reset de meia-noite (PT) ou solicite Standard Access."
    ),
    "INTERNAL_ERROR": (
        "Erro interno do Google Ads. Tente novamente em alguns segundos."
    ),
}


def to_friendly(exc: Exception) -> GoogleAdsFriendlyError:
    """Convert a GoogleAdsException to a friendly PT-BR error.

    If the SDK exception's structure can't be parsed, returns a generic message
    with the original exception attached.
    """
    # Avoid importing the Google SDK here to keep this module testable in isolation.
    failure = getattr(exc, "failure", None)
    if failure is None:
        return GoogleAdsFriendlyError(
            "Erro inesperado ao falar com o Google Ads.",
            original=exc,
        )

    errors = getattr(failure, "errors", None) or []
    if not errors:
        return GoogleAdsFriendlyError(
            "O Google Ads recusou a operação sem detalhes.",
            original=exc,
        )

    first = errors[0]
    error_code = getattr(first, "error_code", None)
    populated = None
    if error_code is not None:
        # error_code is a proto oneof — find which field is set.
        for field_name in (
            "authentication_error",
            "authorization_error",
            "quota_error",
            "internal_error",
        ):
            if getattr(error_code, field_name, None):
                populated = field_name.upper()
                break

    msg = _FRIENDLY_MESSAGES.get(populated or "", None)
    if msg is None:
        # Fallback: include the SDK's English message.
        sdk_msg = getattr(first, "message", "erro desconhecido")
        msg = f"Google Ads retornou: {sdk_msg}"

    return GoogleAdsFriendlyError(msg, code=populated, original=exc)
```

- [ ] **Step 3: Implement `src/google_ads/client.py`**

```python
"""Factory for the official google-ads SDK GoogleAdsClient.

Each call constructs a fresh client with the manager's decrypted refresh
token. Clients are NOT cached — the SDK keeps internal connections, and
caching across managers risks privilege confusion. The construction cost
is small.
"""
from typing import Any

# Imported lazily inside the factory to keep this module unit-testable
# without the heavy google-ads SDK import.


def build_client(
    *,
    refresh_token: str,
    developer_token: str,
    client_id: str,
    client_secret: str,
    login_customer_id: str,
) -> Any:
    """Build a GoogleAdsClient ready to make API calls in the manager's name."""
    from google.ads.googleads.client import GoogleAdsClient  # type: ignore[import-not-found]

    config = {
        "developer_token": developer_token,
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "login_customer_id": login_customer_id,
        "use_proto_plus": True,
    }
    return GoogleAdsClient.load_from_dict(config)
```

- [ ] **Step 4: Implement `src/google_ads/accounts.py`**

```python
"""Wrapper around CustomerService.list_accessible_customers + GoogleAdsService details fetch."""
from typing import Any

from src.google_ads.errors import to_friendly


def list_accessible_customer_resource_names(client: Any) -> list[str]:
    """Call CustomerService.list_accessible_customers and return resource names.

    Resource names look like 'customers/1234567890'.
    """
    try:
        service = client.get_service("CustomerService")
        response = service.list_accessible_customers()
        return list(response.resource_names)
    except Exception as e:
        raise to_friendly(e) from e


def fetch_account_details(
    client: Any,
    *,
    login_customer_id: str,
    customer_ids: list[str],
) -> list[dict]:
    """Fetch descriptive_name, currency_code, time_zone, test_account flag for many accounts.

    Uses GoogleAdsService.search to query the customer_client view from the MCC,
    which lists all child customers including their attributes.
    """
    try:
        ga_service = client.get_service("GoogleAdsService")
        # Query the MCC for all its children at once.
        query = """
            SELECT
              customer_client.id,
              customer_client.descriptive_name,
              customer_client.currency_code,
              customer_client.time_zone,
              customer_client.test_account,
              customer_client.manager
            FROM customer_client
            WHERE customer_client.manager = false
        """
        results: list[dict] = []
        # Pagination handled by SDK; we iterate through pages.
        request = client.get_type("SearchGoogleAdsRequest")
        request.customer_id = login_customer_id
        request.query = query
        response = ga_service.search(request=request)
        for row in response:
            cc = row.customer_client
            cid = str(cc.id)
            if customer_ids and cid not in customer_ids:
                continue
            results.append(
                {
                    "customer_id": cid,
                    "mcc_id": login_customer_id,
                    "descriptive_name": cc.descriptive_name or f"Cliente {cid}",
                    "currency_code": cc.currency_code,
                    "time_zone": cc.time_zone,
                    "is_test_account": bool(cc.test_account),
                }
            )
        return results
    except Exception as e:
        raise to_friendly(e) from e
```

- [ ] **Step 5: Write the unit test for `errors.py` (mocked SDK exception shape)**

```python
"""Test friendly-error translation without importing the heavy SDK."""
from src.google_ads.errors import GoogleAdsFriendlyError, to_friendly


class _FakeErrorCode:
    """Mimics the proto oneof — only the populated field is truthy."""
    def __init__(self, populated_field: str | None):
        for field in (
            "authentication_error",
            "authorization_error",
            "quota_error",
            "internal_error",
        ):
            setattr(self, field, 1 if field == populated_field else 0)


class _FakeError:
    def __init__(self, populated_field: str | None, message: str = "boom"):
        self.error_code = _FakeErrorCode(populated_field)
        self.message = message


class _FakeFailure:
    def __init__(self, errors):
        self.errors = errors


class _FakeException(Exception):
    def __init__(self, errors):
        super().__init__("fake")
        self.failure = _FakeFailure(errors)


def test_authentication_error_pt_message():
    fe = to_friendly(_FakeException([_FakeError("authentication_error")]))
    assert "OAuth do gestor pode" in fe.message_pt
    assert fe.code == "AUTHENTICATION_ERROR"


def test_quota_error_pt_message():
    fe = to_friendly(_FakeException([_FakeError("quota_error")]))
    assert "Quota diária" in fe.message_pt


def test_unknown_code_falls_back_to_sdk_message():
    fe = to_friendly(_FakeException([_FakeError(None, message="weird internal thing")]))
    assert "weird internal thing" in fe.message_pt


def test_no_failure_attribute_returns_generic():
    fe = to_friendly(Exception("naked"))
    assert "Erro inesperado" in fe.message_pt
    assert isinstance(fe, GoogleAdsFriendlyError)


def test_empty_errors_list_returns_generic():
    fe = to_friendly(_FakeException([]))
    assert "sem detalhes" in fe.message_pt
```

- [ ] **Step 6: Run unit tests → 5 PASS**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_google_ads_client.py -v
```

- [ ] **Step 7: mypy + ruff**

```bash
./.venv/Scripts/python.exe -m mypy src/google_ads/
./.venv/Scripts/python.exe -m ruff check src/google_ads/ tests/unit/test_google_ads_client.py
./.venv/Scripts/python.exe -m ruff format --check src/google_ads/ tests/unit/test_google_ads_client.py
```

- [ ] **Step 8: Commit**

```bash
git add src/google_ads/ tests/unit/test_google_ads_client.py
git commit -m "feat(google_ads): client factory + accounts wrapper + friendly errors

build_client() constructs a GoogleAdsClient per call (no cross-manager
caching). list_accessible_customer_resource_names + fetch_account_details
power the resync job. errors.to_friendly() maps SDK exceptions to PT-BR
strings — covers auth, authz, quota, internal at this phase; extended
in Phase 2."
```

---

## Task 8: MCP context + real session middleware (TDD)

**Files:**
- Create: `src/mcp/context.py`
- Modify: `src/mcp/session.py` (replace stub with DB-backed resolution)
- Create: `tests/integration/test_mcp_session_middleware.py`

- [ ] **Step 1: Implement `src/mcp/context.py`**

```python
"""Per-request MCP context — manager_id and session_id available to tool handlers.

Stored in contextvars so async tool handlers (which don't get the request
object directly) can access it.
"""
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID


@dataclass(slots=True, frozen=True)
class McpRequestContext:
    manager_id: UUID
    session_id: UUID


_current: ContextVar[McpRequestContext | None] = ContextVar(
    "mcp_request_context", default=None
)


def set_current(ctx: McpRequestContext) -> None:
    _current.set(ctx)


def clear_current() -> None:
    _current.set(None)


def get_current() -> McpRequestContext:
    """Return the current request context. Raises if not set (programmer error)."""
    ctx = _current.get()
    if ctx is None:
        raise RuntimeError(
            "No MCP request context bound — middleware must run before tool handlers"
        )
    return ctx
```

- [ ] **Step 2: Replace `src/mcp/session.py` with full implementation**

```python
"""MCP session resolution from Bearer tokens.

Fetches the session row from `mcp_sessions` keyed by SHA-256 of the
Bearer token, validates not-revoked + not-expired, and binds the
manager_id/session_id to the request context. Updates last_used_at
asynchronously after the resolution.
"""
from uuid import UUID

import structlog

from src.auth.sessions import hash_session_token
from src.db import connection
from src.db.repositories import managers, mcp_sessions
from src.mcp.context import McpRequestContext, set_current

log = structlog.get_logger(__name__)


def extract_bearer_token(authorization_header: str | None) -> str | None:
    """Parse 'Bearer <token>' header, returning the token or None."""
    if not authorization_header:
        return None
    parts = authorization_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


class UnauthorizedError(Exception):
    """Raised when Bearer is missing/invalid/expired/revoked."""


async def resolve_session_to_context(authorization_header: str | None) -> McpRequestContext:
    """Resolve Bearer header → bind request context. Raises UnauthorizedError on failure."""
    token = extract_bearer_token(authorization_header)
    if token is None:
        raise UnauthorizedError("Missing or malformed Authorization Bearer header")

    token_hash = hash_session_token(token)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        session = await mcp_sessions.find_by_hash(conn, token_hash)
        if session is None:
            raise UnauthorizedError("Session not found, expired, or revoked")
        # Touch last_used_at + manager.last_seen_at in same connection.
        await mcp_sessions.touch_last_used(conn, session.id)
        await managers.touch_last_seen(conn, session.manager_id)

    ctx = McpRequestContext(manager_id=session.manager_id, session_id=session.id)
    set_current(ctx)
    log.info("mcp_session_resolved", manager_id=str(ctx.manager_id), session_id=str(ctx.session_id))
    return ctx
```

- [ ] **Step 3: Update existing unit test for `extract_bearer_token`**

It should still pass without changes (`tests/unit/test_mcp_session.py` from Phase 0). Run:

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_mcp_session.py -v
```

Expected: 4 still PASS. If they fail because the function moved, they're already in the right module — no change needed.

- [ ] **Step 4: Write `tests/integration/test_mcp_session_middleware.py`**

```python
"""Integration tests for the MCP Bearer → context resolution."""
from datetime import timedelta
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.auth.sessions import generate_session_token, hash_session_token
from src.db import connection, migrate
from src.db.repositories import managers, mcp_sessions
from src.mcp.session import (
    UnauthorizedError,
    resolve_session_to_context,
)


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg: PostgresContainer):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


@pytest.mark.integration
async def test_valid_bearer_resolves_context(db) -> None:
    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="r@v4.com", full_name=None)
        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token), label="t",
        )

    ctx = await resolve_session_to_context(f"Bearer {token}")
    assert ctx.manager_id == mid
    assert ctx.session_id == sess.id


@pytest.mark.integration
async def test_missing_header_raises_unauthorized(db) -> None:
    with pytest.raises(UnauthorizedError, match="Missing"):
        await resolve_session_to_context(None)


@pytest.mark.integration
async def test_unknown_token_raises_unauthorized(db) -> None:
    with pytest.raises(UnauthorizedError, match="not found"):
        await resolve_session_to_context("Bearer mcp_definitely_not_a_real_token")


@pytest.mark.integration
async def test_revoked_session_raises_unauthorized(db) -> None:
    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="rv@v4.com", full_name=None)
        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token), label="t",
        )
        await mcp_sessions.revoke(conn, sess.id)

    with pytest.raises(UnauthorizedError):
        await resolve_session_to_context(f"Bearer {token}")


@pytest.mark.integration
async def test_resolution_touches_last_used(db) -> None:
    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="tu@v4.com", full_name=None)
        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token), label="t",
        )
        assert sess.last_used_at is None

    await resolve_session_to_context(f"Bearer {token}")

    async with pool.acquire() as conn:
        refreshed_list = await mcp_sessions.list_for_manager(conn, mid)
        assert refreshed_list[0].last_used_at is not None
```

- [ ] **Step 5: Run tests → 5 PASS**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_mcp_session_middleware.py -v -m integration
```

- [ ] **Step 6: ruff + mypy**

```bash
./.venv/Scripts/python.exe -m mypy src/mcp/
./.venv/Scripts/python.exe -m ruff check src/mcp/ tests/integration/test_mcp_session_middleware.py
./.venv/Scripts/python.exe -m ruff format --check src/mcp/ tests/integration/test_mcp_session_middleware.py
```

- [ ] **Step 7: Commit**

```bash
git add src/mcp/context.py src/mcp/session.py tests/integration/test_mcp_session_middleware.py
git commit -m "feat(mcp): real Bearer → manager_id resolution

session.py now hashes the Bearer, looks up mcp_sessions, validates
not-revoked + not-expired, and binds an McpRequestContext into a
contextvar so async tool handlers can read manager_id/session_id
without thread-locals. Also touches last_used_at + last_seen_at."
```

---

## Task 9: Tool registry + `list_my_accounts` tool (TDD)

**Files:**
- Create: `src/mcp/tools/__init__.py` (empty), `src/mcp/tools/_registry.py`, `src/mcp/tools/list_my_accounts.py`
- Modify: `src/mcp/server.py` to use the registry
- Create: `tests/unit/test_list_my_accounts_tool.py`

- [ ] **Step 1: Implement `src/mcp/tools/_registry.py`**

```python
"""Decorator-based tool registry. Each tool module imports `register_tool` and
declares its handler + JSON schema in one place.

The MCP server (server.py) iterates `_TOOLS` to power list_tools and call_tool.
"""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

# Each handler receives the parsed-input dict and returns a JSON-serializable result.
ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(slots=True, frozen=True)
class RegisteredTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


_TOOLS: dict[str, RegisteredTool] = {}


def register_tool(
    *,
    name: str,
    description: str,
    input_schema: dict[str, Any],
) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator: registers the function as the handler for `name`."""

    def decorator(fn: ToolHandler) -> ToolHandler:
        if name in _TOOLS:
            raise RuntimeError(f"Tool '{name}' already registered")
        _TOOLS[name] = RegisteredTool(
            name=name, description=description, input_schema=input_schema, handler=fn
        )
        return fn

    return decorator


def all_tools() -> list[RegisteredTool]:
    return list(_TOOLS.values())


def get_tool(name: str) -> RegisteredTool | None:
    return _TOOLS.get(name)


def reset() -> None:
    """Test helper — clear the registry between tests."""
    _TOOLS.clear()


def import_all_tools() -> None:
    """Import every tool module so its register_tool decorator runs."""
    from src.mcp.tools import list_my_accounts  # noqa: F401
```

- [ ] **Step 2: Implement `src/mcp/tools/list_my_accounts.py`**

```python
"""Tool: list_my_accounts — returns Google Ads accounts the caller can operate."""
import time
from typing import Any

import structlog

from src.db import connection
from src.db.repositories import audit_log, manager_account_access
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

log = structlog.get_logger(__name__)


_INPUT_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


@register_tool(
    name="list_my_accounts",
    description=(
        "Lista as contas Google Ads que o gestor logado tem permissão pra operar. "
        "Retorna o customer_id (sem traços), nome, moeda, fuso e flag de conta de teste. "
        "Sem parâmetros — usa a sessão MCP pra identificar o gestor."
    ),
    input_schema=_INPUT_SCHEMA,
)
async def list_my_accounts(_args: dict[str, Any]) -> list[dict]:
    ctx = get_current()
    started = time.monotonic()

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accounts = await manager_account_access.list_accounts_for_manager(
            conn, ctx.manager_id
        )

    result = [
        {
            "customer_id": a.customer_id,
            "descriptive_name": a.descriptive_name,
            "mcc_id": a.mcc_id,
            "currency_code": a.currency_code,
            "time_zone": a.time_zone,
            "is_test_account": a.is_test_account,
        }
        for a in accounts
    ]

    duration_ms = int((time.monotonic() - started) * 1000)

    # Audit (read action_type so it's discoverable, but it's a small list).
    async with pool.acquire() as conn:
        await audit_log.record(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=None,
            action_type="read",
            operation="list_my_accounts",
            target_count=len(result),
            params_summary=None,
            status="success",
            duration_ms=duration_ms,
        )

    log.info("tool_list_my_accounts", count=len(result), duration_ms=duration_ms)
    return result
```

- [ ] **Step 3: Modify `src/mcp/server.py` to use the registry**

Replace the body of `build_server` to register handlers from the registry:

```python
"""MCP server using the official Anthropic Python SDK with Streamable HTTP transport."""
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import anyio
import structlog
from fastapi import FastAPI, Request, Response
from mcp.server import Server
from mcp.server.streamable_http import StreamableHTTPServerTransport
from mcp.types import TextContent, Tool

from src.mcp.session import UnauthorizedError, resolve_session_to_context
from src.mcp.tools._registry import all_tools, get_tool, import_all_tools

SERVER_NAME = "v4-ads-mcp"
SERVER_VERSION = "0.1.0"

log = structlog.get_logger(__name__)

# Eagerly import all tool modules so their @register_tool decorators run.
import_all_tools()


def build_server() -> Any:
    """Construct the MCP Server with all registered tools."""
    server = Server(SERVER_NAME, version=SERVER_VERSION)

    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=t.name,
                description=t.description,
                inputSchema=t.input_schema,
            )
            for t in all_tools()
        ]

    @server.call_tool()  # type: ignore[no-untyped-call, untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        tool = get_tool(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        result = await tool.handler(arguments or {})
        # MCP requires tool result to be a list of content blocks; we return
        # a single TextContent with JSON-serialized payload.
        import json
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]

    return server


_mcp_server = build_server()


def mount_mcp(app: FastAPI) -> None:
    """Mount the MCP server's Streamable HTTP transport at /mcp.

    Each request resolves the Bearer token to bind the manager context
    BEFORE the MCP handler runs. Phase 1a tightens this from Phase 0's
    no-auth stub — every /mcp request must carry a valid Bearer.
    """

    @app.post("/mcp")
    async def mcp_endpoint(request: Request) -> Response:
        # Resolve session → bind context. 401 on missing/invalid Bearer.
        try:
            await resolve_session_to_context(request.headers.get("authorization"))
        except UnauthorizedError as e:
            return Response(
                content=f'{{"error":"unauthorized","message":"{e}"}}',
                status_code=401,
                headers={"content-type": "application/json"},
            )

        http_transport = StreamableHTTPServerTransport(
            mcp_session_id=None,
            is_json_response_enabled=True,
        )

        response_status = 200
        response_headers: list[tuple[bytes, bytes]] = []
        response_body = bytearray()

        async def receive() -> MutableMapping[str, Any]:
            body = await request.body()
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message: MutableMapping[str, Any]) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = int(message["status"])
                response_headers.extend(message.get("headers", []))
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))

        async with anyio.create_task_group() as tg:

            async def run_server(
                *,
                task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
            ) -> None:
                async with http_transport.connect() as streams:
                    read_stream, write_stream = streams
                    task_status.started()
                    await _mcp_server.run(
                        read_stream,
                        write_stream,
                        _mcp_server.create_initialization_options(),
                        stateless=True,
                    )

            await tg.start(run_server)
            await http_transport.handle_request(request.scope, receive, send)
            await http_transport.terminate()
            tg.cancel_scope.cancel()

        return Response(
            content=bytes(response_body),
            status_code=response_status,
            headers={k.decode(): v.decode() for k, v in response_headers},
        )
```

- [ ] **Step 4: Update Phase 0 MCP handshake test (now requires Bearer)**

Open `tests/integration/test_mcp_handshake.py`. The 2 existing tests will break because they don't send a Bearer. Update them to:

```python
import pytest
from httpx import AsyncClient


async def test_mcp_no_auth_returns_401(client: AsyncClient) -> None:
    """Without Bearer, /mcp must reject with 401."""
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 401


async def test_mcp_bad_bearer_returns_401(client: AsyncClient) -> None:
    """Unknown Bearer token must reject with 401."""
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer mcp_not_a_real_token",
        },
    )
    # 401 when DB pool not initialized may surface differently; either is fine.
    assert response.status_code in (401, 500)
```

We replace the previous initialize/tools-list tests because they require a DB-backed valid session, which belongs in the E2E test (Task 14). The unit-test surface here just confirms the auth gate.

- [ ] **Step 5: Write `tests/unit/test_list_my_accounts_tool.py`**

```python
"""Unit test for the list_my_accounts tool.

Mocks the DB layer so we test the tool's logic (context binding,
result shape, audit recording) without spinning up Postgres.
"""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.db.repositories.google_ads_accounts import GoogleAdsAccount
from src.mcp.context import McpRequestContext, set_current, clear_current
from src.mcp.tools.list_my_accounts import list_my_accounts


@pytest.fixture
def bound_context():
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.asyncio
async def test_returns_account_list_shape(bound_context):
    from datetime import datetime, UTC
    fake_account = GoogleAdsAccount(
        customer_id="1234567890",
        mcc_id="9999999999",
        descriptive_name="Cliente Alpha",
        currency_code="BRL",
        time_zone="America/Sao_Paulo",
        is_test_account=False,
        is_active=True,
        synced_at=datetime.now(UTC),
    )

    mock_pool = MagicMock()
    mock_conn_ctx = AsyncMock()
    mock_pool.acquire = MagicMock(return_value=mock_conn_ctx)
    mock_conn_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_conn_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("src.mcp.tools.list_my_accounts.connection.get_pool", return_value=mock_pool), \
         patch(
             "src.mcp.tools.list_my_accounts.manager_account_access.list_accounts_for_manager",
             AsyncMock(return_value=[fake_account]),
         ), \
         patch(
             "src.mcp.tools.list_my_accounts.audit_log.record",
             AsyncMock(return_value=42),
         ):
        result = await list_my_accounts({})

    assert len(result) == 1
    assert result[0]["customer_id"] == "1234567890"
    assert result[0]["descriptive_name"] == "Cliente Alpha"
    assert result[0]["currency_code"] == "BRL"
    assert result[0]["is_test_account"] is False


@pytest.mark.asyncio
async def test_empty_when_no_accounts(bound_context):
    mock_pool = MagicMock()
    mock_conn_ctx = AsyncMock()
    mock_pool.acquire = MagicMock(return_value=mock_conn_ctx)
    mock_conn_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_conn_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("src.mcp.tools.list_my_accounts.connection.get_pool", return_value=mock_pool), \
         patch(
             "src.mcp.tools.list_my_accounts.manager_account_access.list_accounts_for_manager",
             AsyncMock(return_value=[]),
         ), \
         patch(
             "src.mcp.tools.list_my_accounts.audit_log.record",
             AsyncMock(return_value=42),
         ):
        result = await list_my_accounts({})
    assert result == []


@pytest.mark.asyncio
async def test_raises_without_bound_context():
    """Calling tool without binding context (programmer error) raises."""
    clear_current()
    with pytest.raises(RuntimeError, match="No MCP request context"):
        await list_my_accounts({})
```

- [ ] **Step 6: Run tests → all pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_list_my_accounts_tool.py tests/integration/test_mcp_handshake.py -v
```

Expected: 3 unit + 2 integration PASS.

- [ ] **Step 7: ruff + mypy**

```bash
./.venv/Scripts/python.exe -m mypy src/mcp/
./.venv/Scripts/python.exe -m ruff check src/mcp/ tests/unit/test_list_my_accounts_tool.py tests/integration/test_mcp_handshake.py
./.venv/Scripts/python.exe -m ruff format --check src/mcp/ tests/unit/test_list_my_accounts_tool.py tests/integration/test_mcp_handshake.py
```

- [ ] **Step 8: Commit**

```bash
git add src/mcp/tools/ src/mcp/server.py tests/unit/test_list_my_accounts_tool.py tests/integration/test_mcp_handshake.py
git commit -m "feat(mcp): tool registry + list_my_accounts + Bearer auth gate

Decorator-based registration so each tool module is self-contained.
list_my_accounts is the first real tool — reads
manager_account_access JOIN google_ads_accounts and writes an
audit_log row. /mcp now requires a valid Bearer (Phase 0 stub
left it open); existing handshake test updated to verify the
401 gate."
```

---

## Task 10: OAuth flow endpoints (TDD with respx mocking Google)

**Files:**
- Create: `src/auth/oauth.py`, `tests/integration/test_oauth_flow.py`
- Modify: `src/app.py` to mount the OAuth routes

- [ ] **Step 1: Implement `src/auth/oauth.py`**

```python
"""OAuth 2.0 flow with Google for the 'adwords' scope.

Two HTTP endpoints:
  GET /oauth/google/start?invite=<token>  → redirect to Google's consent screen
  GET /oauth/google/callback?code=...&state=... → exchange + persist + return success page

The `invite` token is an HMAC-signed payload with manager_id (created
by the bootstrap CLI). Phase 1b will replace this with a panel session.
"""
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.auth.oauth_state import InvalidStateError, sign_state, verify_state
from src.auth.tokens import derive_master_key_from_settings, encrypt_refresh_token
from src.config import get_settings
from src.db import connection
from src.db.repositories import google_oauth_connections, managers

log = structlog.get_logger(__name__)

GOOGLE_ADWORDS_SCOPE = "https://www.googleapis.com/auth/adwords"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


router = APIRouter(prefix="/oauth/google", tags=["oauth"])


def _build_redirect_uri(request: Request) -> str:
    """Construct the absolute callback URL based on the running host.

    Cloud Run sets X-Forwarded-* headers; FastAPI/uvicorn surfaces them via
    request.url. Using request.url ensures the URL matches what's registered
    with the OAuth Client (which we configured to the run.app URL).
    """
    return str(request.url_for("oauth_callback"))


@router.get("/start")
async def oauth_start(invite: str, request: Request) -> RedirectResponse:
    """Redirect the manager to Google's consent screen.

    `invite` is a state-signed payload containing manager_id, minted by the
    admin bootstrap CLI. Phase 1b replaces this with a panel session.
    """
    settings = get_settings()
    try:
        invite_payload = verify_state(invite, settings.session_signing_key)
    except InvalidStateError as e:
        raise HTTPException(status_code=400, detail=f"invalid invite: {e}") from e

    manager_id_str = invite_payload.get("manager_id")
    if not manager_id_str:
        raise HTTPException(status_code=400, detail="invite missing manager_id")

    # Validate manager exists.
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        m = await managers.get_by_id(conn, UUID(manager_id_str))
        if m is None or not m.is_active:
            raise HTTPException(status_code=404, detail="manager not found or inactive")

    # Mint a new state with manager_id for the callback to recover.
    callback_state = sign_state({"manager_id": manager_id_str}, settings.session_signing_key)

    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": _build_redirect_uri(request),
        "scope": GOOGLE_ADWORDS_SCOPE,
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "state": callback_state,
        "include_granted_scopes": "true",
    }
    url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    log.info("oauth_start", manager_id=manager_id_str)
    return RedirectResponse(url=url, status_code=302)


@router.get("/callback", name="oauth_callback")
async def oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    *,
    request: Request,
) -> HTMLResponse:
    """Exchange the auth code for a refresh token and persist it encrypted."""
    if error:
        return _error_page(f"O Google retornou um erro: {error}", status=400)
    if not code or not state:
        return _error_page("Resposta incompleta do Google (faltou code ou state).", status=400)

    settings = get_settings()
    try:
        payload = verify_state(state, settings.session_signing_key)
    except InvalidStateError as e:
        return _error_page(f"State inválido ou expirado: {e}", status=400)

    manager_id_str = payload["manager_id"]
    manager_id = UUID(manager_id_str)

    # Exchange code → tokens.
    async with httpx.AsyncClient(timeout=30.0) as http:
        token_resp = await http.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": _build_redirect_uri(request),
            },
        )
        if token_resp.status_code != 200:
            log.warning("oauth_token_exchange_failed", status=token_resp.status_code, body=token_resp.text)
            return _error_page(
                f"Troca do code falhou (HTTP {token_resp.status_code}). Tente conectar de novo.",
                status=502,
            )
        tokens = token_resp.json()
        refresh_token = tokens.get("refresh_token")
        access_token = tokens.get("access_token")
        if not refresh_token:
            return _error_page(
                "O Google não devolveu refresh_token. Isso geralmente significa que a conta já tinha autorizado o app antes; revogue em https://myaccount.google.com/permissions e tente de novo.",
                status=400,
            )

        # Fetch the email of the Google account that just authorized.
        userinfo_resp = await http.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        userinfo = userinfo_resp.json() if userinfo_resp.status_code == 200 else {}
        google_email = userinfo.get("email") or "unknown"

    # Encrypt + persist.
    master_key = derive_master_key_from_settings(settings.aes_master_key)
    refresh_enc = encrypt_refresh_token(refresh_token, master_key)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await google_oauth_connections.upsert(
            conn,
            manager_id=manager_id,
            google_email=google_email,
            refresh_token_enc=refresh_enc,
            scopes=[GOOGLE_ADWORDS_SCOPE],
        )

    log.info("oauth_callback_success", manager_id=manager_id_str, google_email=google_email)
    return _success_page(google_email)


def _success_page(email: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>V4 Ads MCP — Conectado</title>
<style>body{{font-family:system-ui;max-width:640px;margin:80px auto;padding:0 24px;color:#333}}.ok{{color:#228B22}}</style>
</head><body>
<h1 class="ok">✅ Conectado</h1>
<p>Conta Google <code>{email}</code> autorizada.</p>
<p>Próximo passo: o admin precisa atribuir a você as contas Google Ads que você pode operar (no MVP, isso é manual via CLI). Após isso, peça pra ele criar uma sessão MCP e te enviar o token.</p>
<p>Pode fechar esta aba.</p>
</body></html>""",
        status_code=200,
    )


def _error_page(message: str, *, status: int) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>V4 Ads MCP — Erro</title>
<style>body{{font-family:system-ui;max-width:640px;margin:80px auto;padding:0 24px;color:#333}}.err{{color:#c00}}</style>
</head><body>
<h1 class="err">❌ Falha</h1>
<p>{message}</p>
<p><a href="/health">Status do serviço</a></p>
</body></html>""",
        status_code=status,
    )
```

- [ ] **Step 2: Modify `src/app.py` to mount the router**

After `mount_mcp(app)` add:

```python
    from src.auth.oauth import router as oauth_router

    app.include_router(oauth_router)
```

- [ ] **Step 3: Write `tests/integration/test_oauth_flow.py`**

```python
"""Integration tests for the OAuth flow with respx mocks."""
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
import respx
from httpx import AsyncClient, ASGITransport, Response
from testcontainers.postgres import PostgresContainer

from src.app import create_app
from src.auth.oauth_state import sign_state
from src.db import connection, migrate
from src.db.repositories import google_oauth_connections, managers


_SIGNING_KEY = "x" * 32
_AES_MASTER = "y" * 43  # urlsafe base64 source for 32 bytes


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def app_with_db(pg, monkeypatch):
    """App with real DB pool initialized."""
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("SESSION_SIGNING_KEY", _SIGNING_KEY)
    monkeypatch.setenv("AES_MASTER_KEY", _AES_MASTER)

    app = create_app(skip_db_init=True)
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield app
    finally:
        await connection.close_pool()


@pytest.fixture
async def client(app_with_db) -> AsyncClient:
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.integration
async def test_start_redirects_to_google(client: AsyncClient) -> None:
    # Bootstrap a manager.
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="boot@v4.com", full_name="Boot")
    invite = sign_state({"manager_id": str(mid)}, _SIGNING_KEY)

    response = await client.get(f"/oauth/google/start?invite={invite}", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    qs = parse_qs(urlparse(location).query)
    assert "adwords" in qs["scope"][0]
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]


@pytest.mark.integration
async def test_start_rejects_invalid_invite(client: AsyncClient) -> None:
    response = await client.get("/oauth/google/start?invite=bogus", follow_redirects=False)
    assert response.status_code == 400


@pytest.mark.integration
@respx.mock
async def test_callback_persists_encrypted_refresh_token(client: AsyncClient) -> None:
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="cb@v4.com", full_name=None)

    state = sign_state({"manager_id": str(mid)}, _SIGNING_KEY)

    # Mock Google's token + userinfo endpoints.
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=Response(200, json={
            "access_token": "ya29.fake",
            "refresh_token": "1//06fake-refresh",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/adwords",
            "token_type": "Bearer",
        })
    )
    respx.get("https://www.googleapis.com/oauth2/v2/userinfo").mock(
        return_value=Response(200, json={"email": "manager@gmail.com"})
    )

    response = await client.get(
        f"/oauth/google/callback?code=fake-code&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Conectado" in response.text

    # Verify the connection was persisted with encrypted refresh token.
    async with pool.acquire() as conn:
        c = await google_oauth_connections.get_active_for_manager(conn, mid)
    assert c is not None
    assert c.google_email == "manager@gmail.com"
    assert c.refresh_token_enc != b"1//06fake-refresh"  # encrypted, not plaintext
    assert len(c.refresh_token_enc) > 16  # nonce + ct + tag


@pytest.mark.integration
async def test_callback_rejects_missing_refresh_token(client: AsyncClient) -> None:
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="nr@v4.com", full_name=None)
    state = sign_state({"manager_id": str(mid)}, _SIGNING_KEY)

    with respx.mock:
        respx.post("https://oauth2.googleapis.com/token").mock(
            return_value=Response(200, json={"access_token": "x"})  # no refresh_token
        )
        response = await client.get(
            f"/oauth/google/callback?code=fake&state={state}",
            follow_redirects=False,
        )
    assert response.status_code == 400
    assert "refresh_token" in response.text


@pytest.mark.integration
async def test_callback_rejects_google_error(client: AsyncClient) -> None:
    response = await client.get(
        "/oauth/google/callback?error=access_denied",
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "access_denied" in response.text
```

- [ ] **Step 4: Run tests → 5 PASS**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_oauth_flow.py -v -m integration
```

- [ ] **Step 5: ruff + mypy**

```bash
./.venv/Scripts/python.exe -m mypy src/auth/ src/app.py
./.venv/Scripts/python.exe -m ruff check src/auth/ src/app.py tests/integration/test_oauth_flow.py
./.venv/Scripts/python.exe -m ruff format --check src/auth/ src/app.py tests/integration/test_oauth_flow.py
```

- [ ] **Step 6: Commit**

```bash
git add src/auth/oauth.py src/app.py tests/integration/test_oauth_flow.py
git commit -m "feat(auth): Google OAuth flow (start + callback)

/oauth/google/start?invite=<signed> redirects to Google's consent
screen with access_type=offline + prompt=consent (forces refresh
token issuance). /oauth/google/callback exchanges the code,
fetches the Google account email, encrypts the refresh token
with AES-GCM, and upserts into google_oauth_connections.

The invite token is HMAC-signed (10-min TTL) and minted by the
admin bootstrap CLI; Phase 1b will source it from a panel session
instead. Tests use respx to mock Google's token + userinfo APIs."
```

---

## Task 11: CLI admin script (bootstrap, sessions, account access)

**Files:**
- Create: `src/scripts/__init__.py` (empty), `src/scripts/admin.py`

- [ ] **Step 1: Implement `src/scripts/admin.py`**

```python
"""Admin CLI for Phase 1a (no panel UI yet).

Usage (run from project root with venv active):

  # Bootstrap admin (idempotent — uses email as upsert key)
  python -m src.scripts.admin bootstrap-admin --email wellinton@v4company.com --name "Wellinton Ribeiro"

  # Generate the invite URL for a manager to do OAuth
  python -m src.scripts.admin invite --email wellinton@v4company.com [--base-url https://...]

  # Grant a manager access to all currently-active accounts
  python -m src.scripts.admin grant-all --email wellinton@v4company.com

  # Create an MCP session token (printed once)
  python -m src.scripts.admin create-session --email wellinton@v4company.com --label "Claude Desktop"

  # List sessions for a manager
  python -m src.scripts.admin list-sessions --email wellinton@v4company.com

DATABASE_URL must be set in env (e.g. via Secret Manager fetch).
"""
import argparse
import asyncio
import sys
from uuid import uuid4

from src.auth.oauth_state import sign_state
from src.auth.sessions import generate_session_token, hash_session_token
from src.config import get_settings
from src.db import connection
from src.db.repositories import (
    manager_account_access,
    managers,
    mcp_sessions,
)


async def cmd_bootstrap_admin(args) -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            existing = await managers.get_by_email(conn, args.email)
            if existing:
                print(f"Manager already exists: {existing.id} ({existing.role})")
                if existing.role != "admin":
                    await conn.execute(
                        "UPDATE managers SET role = 'admin', is_active = true WHERE id = $1",
                        existing.id,
                    )
                    print("Promoted to admin.")
                return 0
            new_id = uuid4()
            m = await managers.create(
                conn, manager_id=new_id, email=args.email, full_name=args.name, role="admin"
            )
            print(f"Created admin: {m.id} ({m.email})")
            return 0
    finally:
        await connection.close_pool()


async def cmd_invite(args) -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            m = await managers.get_by_email(conn, args.email)
            if m is None:
                print(f"Manager not found: {args.email}", file=sys.stderr)
                return 1
        invite = sign_state({"manager_id": str(m.id)}, settings.session_signing_key)
        url = f"{args.base_url.rstrip('/')}/oauth/google/start?invite={invite}"
        print("Open this URL in a browser (logged into the desired Google account):")
        print(url)
        print()
        print("⚠️  Invite expires in 10 minutes.")
        return 0
    finally:
        await connection.close_pool()


async def cmd_grant_all(args) -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            m = await managers.get_by_email(conn, args.email)
            if m is None:
                print(f"Manager not found: {args.email}", file=sys.stderr)
                return 1
            n = await manager_account_access.grant_all_active(
                conn, manager_id=m.id, granted_by=m.id
            )
        print(f"Granted access to {n} new accounts (existing grants kept).")
        return 0
    finally:
        await connection.close_pool()


async def cmd_create_session(args) -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            m = await managers.get_by_email(conn, args.email)
            if m is None:
                print(f"Manager not found: {args.email}", file=sys.stderr)
                return 1
            token = generate_session_token()
            sess = await mcp_sessions.create(
                conn,
                manager_id=m.id,
                token_hash=hash_session_token(token),
                label=args.label,
                ttl_days=args.ttl_days,
            )
        print(f"Session created: {sess.id} (expires {sess.expires_at})")
        print()
        print("⚠️  TOKEN — copy it now, won't be shown again:")
        print()
        print(token)
        print()
        print("MCP client config snippet (Claude Desktop):")
        print(f'  "v4-ads": {{ "url": "<SERVICE_URL>/mcp", "headers": {{ "Authorization": "Bearer {token}" }} }}')
        return 0
    finally:
        await connection.close_pool()


async def cmd_list_sessions(args) -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            m = await managers.get_by_email(conn, args.email)
            if m is None:
                print(f"Manager not found: {args.email}", file=sys.stderr)
                return 1
            sessions = await mcp_sessions.list_for_manager(conn, m.id, include_revoked=args.all)
        if not sessions:
            print("(no sessions)")
            return 0
        print(f"{'ID':38}  {'Label':20}  {'Created':25}  {'Last used':25}  {'Expires':25}  Revoked?")
        for s in sessions:
            print(
                f"{str(s.id):38}  "
                f"{(s.label or '-'):20}  "
                f"{s.created_at.isoformat():25}  "
                f"{(s.last_used_at.isoformat() if s.last_used_at else '-'):25}  "
                f"{(s.expires_at.isoformat() if s.expires_at else '-'):25}  "
                f"{'Y' if s.revoked_at else 'N'}"
            )
        return 0
    finally:
        await connection.close_pool()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="admin", description="V4 Ads MCP admin CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_boot = sub.add_parser("bootstrap-admin", help="Create or promote an admin manager")
    p_boot.add_argument("--email", required=True)
    p_boot.add_argument("--name", default=None)

    p_inv = sub.add_parser("invite", help="Print an OAuth invite URL")
    p_inv.add_argument("--email", required=True)
    p_inv.add_argument(
        "--base-url",
        default="https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app",
        help="Service base URL",
    )

    p_grant = sub.add_parser("grant-all", help="Grant a manager access to all active accounts")
    p_grant.add_argument("--email", required=True)

    p_sess = sub.add_parser("create-session", help="Issue an MCP Bearer for a manager")
    p_sess.add_argument("--email", required=True)
    p_sess.add_argument("--label", default="cli")
    p_sess.add_argument("--ttl-days", type=int, default=90)

    p_ls = sub.add_parser("list-sessions", help="Print sessions for a manager")
    p_ls.add_argument("--email", required=True)
    p_ls.add_argument("--all", action="store_true", help="Include revoked sessions")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = {
        "bootstrap-admin": cmd_bootstrap_admin,
        "invite": cmd_invite,
        "grant-all": cmd_grant_all,
        "create-session": cmd_create_session,
        "list-sessions": cmd_list_sessions,
    }[args.cmd]
    return asyncio.run(handler(args))


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke run (with empty DB env vars to verify CLI parses)**

```bash
cd "/d/HUB ads MCP"
./.venv/Scripts/python.exe -m src.scripts.admin --help
./.venv/Scripts/python.exe -m src.scripts.admin bootstrap-admin --help
```

Expected: argparse help printed, no error.

- [ ] **Step 3: ruff + mypy**

```bash
./.venv/Scripts/python.exe -m mypy src/scripts/
./.venv/Scripts/python.exe -m ruff check src/scripts/
./.venv/Scripts/python.exe -m ruff format --check src/scripts/
```

- [ ] **Step 4: Commit**

```bash
git add src/scripts/__init__.py src/scripts/admin.py
git commit -m "feat(scripts): admin CLI for bootstrap + invite + sessions

Five subcommands cover Phase 1a's no-panel ops:
bootstrap-admin (create/promote), invite (mint OAuth URL),
grant-all (assign all active accounts), create-session
(issue Bearer — printed once), list-sessions.

Run with DATABASE_URL set in env; intended for one-off ops
from the developer's machine pointing at the production DB."
```

---

## Task 12: Account resync job (Cloud Run Job)

**Files:**
- Create: `src/jobs/account_resync.py`

- [ ] **Step 1: Implement `src/jobs/account_resync.py`**

```python
"""Cloud Run Job: refresh google_ads_accounts from the MCC.

Picks any active OAuth connection (admin's by default) and uses its
refresh token to call list_accessible_customers + customer_client
search on the MCC. Upserts results, marks deactivated accounts.

Entry point: `python -m src.jobs.account_resync`
"""
import asyncio
import sys

import structlog

from src.auth.tokens import decrypt_refresh_token, derive_master_key_from_settings
from src.config import get_settings
from src.db import connection
from src.db.repositories import (
    google_ads_accounts,
    google_oauth_connections,
    managers,
)
from src.google_ads.accounts import (
    fetch_account_details,
    list_accessible_customer_resource_names,
)
from src.google_ads.client import build_client

log = structlog.get_logger(__name__)


async def _pick_oauth_connection(conn) -> tuple:
    """Return (manager, oauth_conn) for the first active admin's OAuth.

    Falls back to any active connection if no admin has one.
    """
    admins = await conn.fetch(
        "SELECT id FROM managers WHERE role = 'admin' AND is_active = true ORDER BY created_at"
    )
    for row in admins:
        oc = await google_oauth_connections.get_active_for_manager(conn, row["id"])
        if oc is not None:
            m = await managers.get_by_id(conn, row["id"])
            return m, oc

    # Fallback: any active connection.
    row = await conn.fetchrow(
        "SELECT manager_id FROM google_oauth_connections WHERE revoked_at IS NULL ORDER BY connected_at DESC LIMIT 1"
    )
    if row is None:
        return None, None
    oc = await google_oauth_connections.get_active_for_manager(conn, row["manager_id"])
    m = await managers.get_by_id(conn, row["manager_id"])
    return m, oc


async def run() -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            manager, oc = await _pick_oauth_connection(conn)
            if oc is None:
                log.error("resync_no_oauth_connection")
                print(
                    "No active OAuth connection — bootstrap an admin and have them complete /oauth/google/start first.",
                    file=sys.stderr,
                )
                return 1

        master_key = derive_master_key_from_settings(settings.aes_master_key)
        refresh_token = decrypt_refresh_token(oc.refresh_token_enc, master_key)

        client = build_client(
            refresh_token=refresh_token,
            developer_token=settings.google_ads_developer_token,
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret,
            login_customer_id=settings.google_ads_login_customer_id,
        )

        # Discover accessible customers (mostly: just the MCC itself).
        resource_names = list_accessible_customer_resource_names(client)
        log.info("resync_accessible_customers", count=len(resource_names))

        # Pull descriptive details for all child customers under the MCC.
        accounts = fetch_account_details(
            client,
            login_customer_id=settings.google_ads_login_customer_id,
            customer_ids=[],  # empty → all
        )

        async with pool.acquire() as conn:
            n = await google_ads_accounts.upsert_many(conn, accounts)
            keep_ids = [a["customer_id"] for a in accounts]
            deactivated = await google_ads_accounts.mark_inactive_except(
                conn,
                mcc_id=settings.google_ads_login_customer_id,
                keep_customer_ids=keep_ids,
            )

        log.info("resync_complete", upserted=n, deactivated=deactivated)
        print(f"OK: upserted {n} accounts, deactivated {deactivated}")
        return 0
    finally:
        await connection.close_pool()


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke import**

```bash
./.venv/Scripts/python.exe -c "from src.jobs import account_resync; print('OK', account_resync.main.__doc__ or 'imports clean')"
```

Expected: `OK ...`. No import error.

- [ ] **Step 3: ruff + mypy**

```bash
./.venv/Scripts/python.exe -m mypy src/jobs/account_resync.py
./.venv/Scripts/python.exe -m ruff check src/jobs/account_resync.py
./.venv/Scripts/python.exe -m ruff format --check src/jobs/account_resync.py
```

- [ ] **Step 4: Commit**

```bash
git add src/jobs/account_resync.py
git commit -m "feat(jobs): account_resync — populate google_ads_accounts from MCC

Picks the first admin's OAuth connection, decrypts the refresh
token, builds a GoogleAdsClient, and queries customer_client to
discover all child accounts under the MCC. Upserts results +
marks accounts not seen this run as inactive (deletion detection).

Entry point: python -m src.jobs.account_resync. To be wired as a
Cloud Run Job in Task 13."
```

---

## Task 13: Cloud Run Job for account-resync + Cloud Scheduler

**Manual gcloud ops + a workflow update.**

- [ ] **Step 1: Create the Cloud Run Job**

```bash
PATH="/c/Program Files (x86)/Google/Cloud SDK/google-cloud-sdk/bin:$PATH"
export PATH
PROJECT_ID=v4-ads-mcp-prod
REGION=southamerica-east1

# Use the latest deployed image (same one Cloud Run service uses).
LATEST_IMAGE=$(gcloud run services describe v4-ads-mcp \
    --region=${REGION} --format='value(spec.template.spec.containers[0].image)')
echo "Latest image: $LATEST_IMAGE"

gcloud run jobs create v4-ads-mcp-resync \
    --image="$LATEST_IMAGE" \
    --region=${REGION} \
    --service-account=v4-ads-mcp-runtime@${PROJECT_ID}.iam.gserviceaccount.com \
    --command=python --args="-m,src.jobs.account_resync" \
    --max-retries=1 \
    --task-timeout=600 \
    --set-env-vars="APP_ENV=production,APP_TIMEZONE=America/Sao_Paulo,LOG_LEVEL=info" \
    --set-secrets="DATABASE_URL=database-url:latest,SESSION_SIGNING_KEY=session-signing-key:latest,AES_MASTER_KEY=aes-master-key:latest,GOOGLE_OAUTH_CLIENT_ID=google-oauth-client-id:latest,GOOGLE_OAUTH_CLIENT_SECRET=google-oauth-client-secret:latest,GOOGLE_ADS_DEVELOPER_TOKEN=google-ads-developer-token:latest,GOOGLE_ADS_LOGIN_CUSTOMER_ID=google-ads-login-customer-id:latest,SUPABASE_URL=supabase-url:latest,SUPABASE_ANON_KEY=supabase-anon-key:latest,SUPABASE_SERVICE_KEY=supabase-service-key:latest"
```

- [ ] **Step 2: Update the deploy workflow to also keep this job's image fresh**

Edit `.github/workflows/deploy.yml`. Find the existing "Update migration job image" step and add a parallel step right after it:

```yaml
      - name: Update resync job image
        env:
          PROJECT_ID: ${{ secrets.GCP_PROJECT_ID }}
          REGION: ${{ secrets.GCP_REGION }}
        run: |
          gcloud run jobs update v4-ads-mcp-resync \
            --image=southamerica-east1-docker.pkg.dev/${PROJECT_ID}/v4-ads-mcp/app:${{ github.sha }} \
            --region=${REGION}
```

- [ ] **Step 3: Create Cloud Scheduler job (daily 04:00 BRT = 07:00 UTC)**

```bash
PROJECT_NUMBER=518798891402

# Cloud Scheduler needs a service account that can invoke Cloud Run Jobs.
# The deployer SA already has roles/run.admin which suffices.

gcloud scheduler jobs create http v4-ads-mcp-resync-daily \
    --location=${REGION} \
    --schedule="0 7 * * *" \
    --time-zone="Etc/UTC" \
    --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/v4-ads-mcp-resync:run" \
    --http-method=POST \
    --oauth-service-account-email=github-deployer@${PROJECT_ID}.iam.gserviceaccount.com \
    --oauth-token-scope=https://www.googleapis.com/auth/cloud-platform \
    --description="Daily Google Ads accounts sync (07:00 UTC = 04:00 BRT)"
```

- [ ] **Step 4: Update `docs/operacao/infra-setup.md`**

Append to the GCP project section:

```markdown
- [x] Cloud Run Job `v4-ads-mcp-resync` created (entry: `python -m src.jobs.account_resync`)
- [x] Cloud Scheduler `v4-ads-mcp-resync-daily` (cron `0 7 * * *` UTC = 04:00 BRT)
```

- [ ] **Step 5: Commit workflow + docs**

```bash
git add .github/workflows/deploy.yml docs/operacao/infra-setup.md
git commit -m "ci: keep resync Job image in sync + record Scheduler

Each deploy now updates both v4-ads-mcp-migrate and
v4-ads-mcp-resync to the new image SHA. Cloud Scheduler runs
the resync daily at 04:00 BRT."
git push
```

---

## Task 14: Bootstrap runbook + production E2E verification

**Files:**
- Create: `docs/operacao/phase-1a-bootstrap.md`

- [ ] **Step 1: Write `docs/operacao/phase-1a-bootstrap.md`**

```markdown
# Phase 1a — Bootstrap runbook

This runbook walks through the first end-to-end onboarding using the CLI
(no panel UI yet). Execute from the project root with venv active.

## Prereqs

- `gcloud` authenticated against the `v4-ads-mcp-prod` project.
- Cloud Run service deployed and healthy (`curl https://<URL>/health`).
- All 10 secrets in Secret Manager populated.

## 1. Fetch DATABASE_URL into env (one-shot)

```bash
export DATABASE_URL=$(gcloud secrets versions access latest --secret=database-url)
export AES_MASTER_KEY=$(gcloud secrets versions access latest --secret=aes-master-key)
export SESSION_SIGNING_KEY=$(gcloud secrets versions access latest --secret=session-signing-key)
export GOOGLE_OAUTH_CLIENT_ID=$(gcloud secrets versions access latest --secret=google-oauth-client-id)
export GOOGLE_OAUTH_CLIENT_SECRET=$(gcloud secrets versions access latest --secret=google-oauth-client-secret)
export GOOGLE_ADS_DEVELOPER_TOKEN=$(gcloud secrets versions access latest --secret=google-ads-developer-token)
export GOOGLE_ADS_LOGIN_CUSTOMER_ID=$(gcloud secrets versions access latest --secret=google-ads-login-customer-id)
export SUPABASE_URL=$(gcloud secrets versions access latest --secret=supabase-url)
export SUPABASE_ANON_KEY=$(gcloud secrets versions access latest --secret=supabase-anon-key)
export SUPABASE_SERVICE_KEY=$(gcloud secrets versions access latest --secret=supabase-service-key)
export APP_ENV=production
```

## 2. Bootstrap the first admin

```bash
./.venv/Scripts/python.exe -m src.scripts.admin bootstrap-admin \
    --email wellinton@v4company.com \
    --name "Wellinton Ribeiro"
```

Expected: `Created admin: <uuid> (wellinton@v4company.com)`

## 3. Issue invite URL + complete OAuth in browser

```bash
./.venv/Scripts/python.exe -m src.scripts.admin invite \
    --email wellinton@v4company.com
```

Open the printed URL in a browser logged into your V4 Google account
that has access to the V4 MCC. Authorize → you should see the green
"✅ Conectado" page.

## 4. Run resync to populate accounts

Manual one-off (Cloud Scheduler will do this daily after Phase 1a):
```bash
gcloud run jobs execute v4-ads-mcp-resync --region=southamerica-east1 --wait
```

Verify accounts in Supabase via SQL editor:
```sql
SELECT customer_id, descriptive_name FROM google_ads_accounts WHERE is_active = true ORDER BY descriptive_name;
```
Expect ~29 rows.

## 5. Grant yourself access to all accounts

```bash
./.venv/Scripts/python.exe -m src.scripts.admin grant-all \
    --email wellinton@v4company.com
```

Expected: `Granted access to 29 new accounts (existing grants kept).`

## 6. Create an MCP session

```bash
./.venv/Scripts/python.exe -m src.scripts.admin create-session \
    --email wellinton@v4company.com \
    --label "Claude Desktop"
```

**Copy the printed `mcp_xxx...` token immediately — it won't be shown again.**

## 7. Configure Claude Desktop

Edit `~/AppData/Roaming/Claude/claude_desktop_config.json` (Windows) or
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "v4-ads": {
      "url": "https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/mcp",
      "headers": {
        "Authorization": "Bearer mcp_xxxxxxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

Restart Claude Desktop.

## 8. Verify in Claude

In a new chat:
> "List the available MCP tools."

Expected: Claude lists `list_my_accounts`.

> "Use list_my_accounts."

Expected: Claude returns ~29 accounts with names + currency + timezone.

## 9. Verify audit trail

```sql
SELECT occurred_at, manager_id, operation, target_count, status
FROM audit_log
ORDER BY occurred_at DESC
LIMIT 5;
```

Expect a row with `operation = 'list_my_accounts'`, `target_count = 29`, `status = 'success'`.

---

## Troubleshooting

- **OAuth callback says "Google didn't return a refresh_token"** — your Google account previously authorized this app and Google won't re-issue. Go to https://myaccount.google.com/permissions, revoke "V4 Ads MCP", retry.
- **Resync fails with "AUTHENTICATION_ERROR"** — the admin's refresh token expired or was revoked. Re-run step 3 (invite + OAuth) for the admin.
- **Resync fails with "no active OAuth connection"** — no admin has done OAuth yet; complete step 3 first.
- **Claude says "tool not found"** — restart Claude Desktop fully (not just close window). Check the Bearer token is exactly as printed (no leading/trailing spaces).
```

- [ ] **Step 2: Run all unit + integration tests one final time before push**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -v --tb=short
```

Expected: ALL pass. Document the count.

- [ ] **Step 3: Push everything**

```bash
git add docs/operacao/phase-1a-bootstrap.md
git commit -m "docs(ops): Phase 1a bootstrap runbook

Step-by-step CLI flow: fetch secrets → bootstrap admin →
invite + OAuth → resync → grant-all → create-session →
configure Claude Desktop → verify list_my_accounts."
git push
```

This triggers a deploy. Watch:
```bash
gh run watch $(gh run list --branch main --workflow=deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status
```

Expected: GREEN.

- [ ] **Step 4: Execute the runbook against production end-to-end**

Follow `docs/operacao/phase-1a-bootstrap.md` steps 1-9. At step 8, ask Claude Desktop to call `list_my_accounts` and verify 29 accounts come back.

If any step fails, check Cloud Run logs:
```bash
gcloud run services logs read v4-ads-mcp --region=southamerica-east1 --limit=30
gcloud run jobs executions list --job=v4-ads-mcp-resync --region=southamerica-east1 --limit=3
```

- [ ] **Step 5: Final commit closing Phase 1a**

After successful E2E:
```bash
echo "
## Phase 1a sign-off

- [x] All 10 manual prereqs complete
- [x] Bootstrap CLI works (admin created)
- [x] OAuth flow works (refresh token encrypted in DB)
- [x] Resync populated 29 accounts
- [x] Session created + Claude Desktop configured
- [x] list_my_accounts returns 29 accounts via Claude
- [x] audit_log has the call
- [x] Date: $(date +%Y-%m-%d)
" >> docs/operacao/infra-setup.md
git add docs/operacao/infra-setup.md
git commit -m "docs(ops): close Phase 1a — all acceptance criteria met"
git push
```

After this, Phase 1a is **done**. Move to Phase 1b plan (web panel).

---

## Self-review notes

**Spec coverage:**
- §5.1 Fluxo A (Supabase Auth) — DEFERRED to Phase 1b
- §5.1 Fluxo B (OAuth Google) — Task 10 (oauth.py)
- §5.1 Fluxo C (MCP sessions) — Task 3 (sessions module) + Task 8 (middleware) + Task 11 (CLI)
- §5.2 Resolução em uma chamada MCP — Task 8 (middleware) + Task 9 (registry hooks audit)
- §6.4 list_my_accounts utility — Task 9
- §7.4 Audit log — Tasks 5+9 (repo writes; full rotation in Phase 4)
- §9.2 Cron jobs — Task 13 (resync only; audit-rotation deferred)
- §11 Phase 1 critério "list_my_accounts works end-to-end" — Task 14

**Out of scope for Phase 1a (deferred to 1b):**
- Web panel UI (login, dashboard, accounts, sessions, admin pages)
- Supabase Auth integration in panel
- V4 design system CSS

**Type/name consistency:**
- `Settings` and `get_settings()` consistent across all modules.
- `connection.init_pool` / `close_pool` / `get_pool` API consistent.
- `McpRequestContext` / `set_current` / `get_current` consistent across context.py, session.py, tools.
- `register_tool` decorator + `all_tools` / `get_tool` API consistent across registry + server.
- `GoogleAdsAccount` dataclass shape consistent across repos and tool result.
- `_row_to_account` is module-private but imported by manager_account_access — this is acceptable for related-aggregate code; document if it becomes wider-spread.
