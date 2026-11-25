"""Formato de e-mail — a allowlist de acesso e a tabela `managers`, nao o dominio."""

import pytest

from src.auth.domain_check import is_valid_email_shape


@pytest.mark.parametrize(
    "email,expected",
    [
        ("wellington.ribeiro.eng@gmail.com", True),
        ("a@v4company.com", True),
        ("A@GMAIL.COM", True),
        ("two@signs@x.com", False),
        ("", False),
        (None, False),
        ("nodomain", False),
        ("@x.com", False),
        ("a@", False),
    ],
)
def test_is_valid_email_shape(email, expected):
    assert is_valid_email_shape(email) is expected
