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
