"""Test friendly-error translation without importing the heavy SDK."""

import contextlib
import secrets
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.auth.tokens import (
    InvalidCiphertextError,
    derive_master_key_from_settings,
    encrypt_refresh_token,
)
from src.google_ads.errors import GoogleAdsFriendlyError, to_friendly


class _FakeErrorCode:
    """Mimics the proto oneof — only the populated field is truthy."""

    def __init__(self, populated_field: str | None):
        for field in (
            "authentication_error",
            "authorization_error",
            "quota_error",
            "internal_error",
            "query_error",
            "policy_finding_error",
        ):
            setattr(self, field, 1 if field == populated_field else 0)


class _FakeError:
    def __init__(self, populated_field: str | None, message: str = "boom"):
        self.error_code = _FakeErrorCode(populated_field)
        self.message = message


class _FakeFailure:
    def __init__(self, errors):
        self.errors = errors


class _FakeException(Exception):  # noqa: N818
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


def test_ciphertext_error_gives_actionable_reconnect_message():
    """Decrypt-failure (chave AES rotacionada na migração) vira erro amigável
    apontando pra reconexão — senão o dispatcher scruba pra 'Erro interno' (F70)."""
    fe = to_friendly(InvalidCiphertextError("Ciphertext authentication failed"))
    assert fe.code == "TOKEN_DECRYPT_FAILED"
    assert "reconecte" in fe.message_pt.lower()
    # a URL do painel é interpolada pra a mensagem ser acionável de fato
    assert "run.app" in fe.message_pt


async def test_build_client_for_manager_decrypt_failure_is_friendly():
    """build_client_for_manager converte InvalidCiphertextError na ORIGEM (é chamado
    fora do wrap de to_friendly dos executores) — cobre todos os tools de uma vez."""
    from src.google_ads.client import build_client_for_manager

    old_key = secrets.token_urlsafe(32)
    new_key = secrets.token_urlsafe(32)
    # Token cifrado com a chave ANTIGA (pré-migração); serviço agora tem a NOVA.
    enc = encrypt_refresh_token("1//realtoken", derive_master_key_from_settings(old_key))

    fake_oc = MagicMock()
    fake_oc.refresh_token_enc = enc

    @contextlib.asynccontextmanager
    async def fake_acquire():
        yield MagicMock()

    fake_pool = MagicMock()
    fake_pool.acquire = fake_acquire

    fake_settings = MagicMock()
    fake_settings.aes_master_key = new_key

    with (
        patch("src.config.get_settings", return_value=fake_settings),
        patch("src.db.connection.get_pool", return_value=fake_pool),
        patch(
            "src.db.repositories.google_oauth_connections.get_active_for_manager",
            AsyncMock(return_value=fake_oc),
        ),
        pytest.raises(GoogleAdsFriendlyError) as ei,
    ):
        await build_client_for_manager(manager_id=uuid4())

    assert ei.value.code == "TOKEN_DECRYPT_FAILED"
    assert "reconecte" in ei.value.message_pt.lower()


def test_policy_finding_error_names_the_violated_topics():
    """C4: reprovação de política nomeia os tópicos específicos (o gestor tentava
    às cegas — 9x no dogfood 07-02) em vez do genérico 'policy topics of type PROHIBITED'."""

    class _Topic:
        def __init__(self, topic: str) -> None:
            self.topic = topic

    class _PolicyFindingDetails:
        def __init__(self, topics: list) -> None:
            self.policy_topic_entries = topics

    class _Details:
        def __init__(self, pfd: object) -> None:
            self.policy_finding_details = pfd

    class _PolicyError:
        def __init__(self) -> None:
            self.error_code = _FakeErrorCode("policy_finding_error")
            self.message = "The resource has been disapproved..."
            self.details = _Details(
                _PolicyFindingDetails([_Topic("DESTINATION_NOT_WORKING"), _Topic("TRADEMARKS")])
            )

    fe = to_friendly(_FakeException([_PolicyError()]))
    assert fe.code == "POLICY_FINDING_ERROR"
    assert "DESTINATION_NOT_WORKING" in fe.message_pt
    assert "TRADEMARKS" in fe.message_pt


def test_policy_finding_error_without_details_degrades_gracefully():
    """Sem details parseáveis (proto diferente entre versões SDK), cai no sdk_msg."""
    fe = to_friendly(
        _FakeException([_FakeError("policy_finding_error", message="disapproved xyz")])
    )
    assert fe.code == "POLICY_FINDING_ERROR"
    assert "disapproved xyz" in fe.message_pt


def test_query_error_enriched_with_hint():
    """QUERY_ERROR (campo/métrica/recurso inválido) mantém o erro cru E anexa dica
    acionável (list_gaql_resources / validate_gaql) pro cliente LLM se autocorrigir."""
    fe = to_friendly(
        _FakeException(
            [
                _FakeError(
                    "query_error",
                    message="Unrecognized field in the query: 'metrics.search_overlap_rate'.",
                )
            ]
        )
    )
    assert fe.code == "QUERY_ERROR"
    # mantém o campo cru — o LLM precisa saber QUAL campo falhou
    assert "search_overlap_rate" in fe.message_pt
    # anexa a dica acionável apontando pras tools de validação
    assert "list_gaql_resources" in fe.message_pt
    assert "validate_gaql" in fe.message_pt
