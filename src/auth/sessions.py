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
