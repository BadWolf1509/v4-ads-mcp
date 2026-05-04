"""Domain check tests."""

import pytest

from src.auth.domain_check import is_allowed_email


@pytest.mark.parametrize(
    "email,expected",
    [
        ("wellinton.ribeiro@v4company.com", True),
        ("admin@v4company.com", True),
        ("WELLINTON@V4COMPANY.COM", True),  # case-insensitive
        ("attacker@gmail.com", False),
        ("attacker@v4company.com.malicious.com", False),
        ("malicious.v4company.com@gmail.com", False),
        ("", False),
        (None, False),
        ("nodomain", False),
        ("two@signs@v4company.com", False),
    ],
)
def test_is_allowed_email(email, expected):
    assert is_allowed_email(email) is expected
