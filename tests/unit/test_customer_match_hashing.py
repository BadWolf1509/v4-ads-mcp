"""Unit tests for SHA-256 hashing utilities (Sprint 3b.28).

Google Ads Customer Match exige:
- Email: lowercase + remove ALL whitespace + SHA-256 hex digest
- Phone: E.164 normalize (+55 default BR) + lowercase + SHA-256 hex
"""

import hashlib


def test_normalize_and_hash_email_basic():
    from src.google_ads.customer_match import _normalize_and_hash_email

    result = _normalize_and_hash_email("user@example.com")
    expected = hashlib.sha256(b"user@example.com").hexdigest()
    assert result == expected
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_normalize_and_hash_email_lowercase():
    from src.google_ads.customer_match import _normalize_and_hash_email

    result_upper = _normalize_and_hash_email("USER@EXAMPLE.COM")
    result_lower = _normalize_and_hash_email("user@example.com")
    assert result_upper == result_lower


def test_normalize_and_hash_email_strips_whitespace():
    from src.google_ads.customer_match import _normalize_and_hash_email

    result_with_ws = _normalize_and_hash_email(" us er @example.com ")
    result_clean = _normalize_and_hash_email("user@example.com")
    assert result_with_ws == result_clean


def test_normalize_and_hash_phone_e164_already_formatted():
    from src.google_ads.customer_match import _normalize_and_hash_phone

    result = _normalize_and_hash_phone("+5511987654321")
    expected = hashlib.sha256(b"+5511987654321").hexdigest()
    assert result == expected


def test_normalize_and_hash_phone_default_to_br_plus55():
    """V4 invariant: phone sem country code → assume +55 BR."""
    from src.google_ads.customer_match import _normalize_and_hash_phone

    result_no_prefix = _normalize_and_hash_phone("11987654321")
    result_with_prefix = _normalize_and_hash_phone("+5511987654321")
    assert result_no_prefix == result_with_prefix


def test_normalize_and_hash_phone_strips_formatting():
    """Phone com parênteses, traços, espaços normaliza."""
    from src.google_ads.customer_match import _normalize_and_hash_phone

    result_formatted = _normalize_and_hash_phone("(11) 9 8765-4321")
    result_clean = _normalize_and_hash_phone("+5511987654321")
    assert result_formatted == result_clean


def test_normalize_and_hash_phone_strips_leading_zero_br():
    """Numero BR começa com 0 (DDD) → strip antes de adicionar +55."""
    from src.google_ads.customer_match import _normalize_and_hash_phone

    result_with_zero = _normalize_and_hash_phone("011987654321")
    result_clean = _normalize_and_hash_phone("+5511987654321")
    assert result_with_zero == result_clean


def test_normalize_and_hash_email_returns_lowercase_hex():
    from src.google_ads.customer_match import _normalize_and_hash_email

    result = _normalize_and_hash_email("user@example.com")
    assert result == result.lower()


def test_normalize_and_hash_phone_handles_international_prefix():
    """Phone com prefix internacional (+1, +44, etc) preserva o prefix."""
    from src.google_ads.customer_match import _normalize_and_hash_phone

    result_us = _normalize_and_hash_phone("+14155552671")
    expected = hashlib.sha256(b"+14155552671").hexdigest()
    assert result_us == expected
