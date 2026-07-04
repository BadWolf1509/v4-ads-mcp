"""Unit tests — run_recommendation_action (src/google_ads/mutations.py, ~L316) happy path.

tests/unit/test_recommendation_gate.py já cobre o deny path (AccountAccessDeniedError
propaga antes de before_call/build_client). Este arquivo espelha
test_run_mutation_resource_names.py / test_run_mutation_quota_reserve.py mas para o
executor de recomendações: audit sempre-on (status=success), captura de
provider_request_id via get_request_id(), e reconcile no finally (record_actual
sempre chamado com actual_ops=1==estimated_ops=1).

Diferente de run_mutation, este executor NÃO usa conn.transaction() (só
`async with pool.acquire() as conn:` simples) — o mock do pool aqui não precisa
fornecer um transaction() CM.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _mock_pool() -> MagicMock:
    mock_pool = MagicMock()
    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
    mock_conn_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_conn_cm
    return mock_pool


@pytest.mark.asyncio
async def test_apply_recommendation_happy_path_audits_success_and_captures_request_id():
    from src.google_ads import mutations

    manager_id = uuid4()
    session_id = uuid4()
    fake_client = MagicMock()

    with (
        patch.object(mutations, "connection") as mock_connection,
        patch.object(mutations, "ensure_account_access", AsyncMock()) as ensure_access_mock,
        patch.object(mutations, "before_call", AsyncMock()) as before_call_mock,
        patch.object(mutations, "record_actual", AsyncMock()) as record_actual_mock,
        patch.object(mutations, "build_client_for_manager", AsyncMock(return_value=fake_client)),
        patch.object(mutations, "get_request_id", lambda: "fake-recommendation-req-id"),
        patch.object(mutations, "reset_request_id", lambda: None),
        patch(
            "src.google_ads.mutates.recommendations.execute_apply_recommendation",
            MagicMock(return_value=MagicMock()),
        ) as execute_mock,
        patch.object(mutations.audit_log, "record", AsyncMock(return_value=1)) as audit_mock,
    ):
        mock_connection.get_pool.return_value = _mock_pool()

        result = await mutations.run_recommendation_action(
            manager_id=manager_id,
            session_id=session_id,
            customer_id="1234567890",
            operation_type="apply_recommendation",
            payload={"recommendation_resource_name": "customers/1234567890/recommendations/1"},
        )

    # Return shape: provider_request_id capturado + applied_count fixo em 1.
    assert result == {
        "provider_request_id": "fake-recommendation-req-id",
        "applied_count": 1,
    }

    # Gate + quota reservation rodaram antes do builder.
    ensure_access_mock.assert_awaited_once()
    assert ensure_access_mock.call_args.kwargs["level"] == "write"
    assert ensure_access_mock.call_args.kwargs["operation_name"] == "apply_recommendation"
    before_call_mock.assert_awaited_once()
    assert before_call_mock.call_args.kwargs["estimated_ops"] == 1

    # O executor de recomendação dedicado (RecommendationService), não o
    # generic run_mutation builder path.
    execute_mock.assert_called_once()
    assert execute_mock.call_args.args[0] is fake_client
    assert execute_mock.call_args.args[1] == "1234567890"

    # Reconcile no finally: sempre chamado, actual_ops == estimated_ops == 1.
    record_actual_mock.assert_awaited_once()
    assert record_actual_mock.call_args.kwargs["actual_ops"] == 1
    assert record_actual_mock.call_args.kwargs["estimated_ops"] == 1

    # Audit SEMPRE-ON: status=success, action_type=mutate, request_id propagado.
    audit_mock.assert_awaited_once()
    audit_kwargs = audit_mock.call_args.kwargs
    assert audit_kwargs["status"] == "success"
    assert audit_kwargs["action_type"] == "mutate"
    assert audit_kwargs["operation"] == "apply_recommendation"
    assert audit_kwargs["manager_id"] == manager_id
    assert audit_kwargs["session_id"] == session_id
    assert audit_kwargs["customer_id"] == "1234567890"
    assert audit_kwargs["provider_request_id"] == "fake-recommendation-req-id"
    assert audit_kwargs["error_message"] is None


@pytest.mark.asyncio
async def test_dismiss_recommendation_happy_path_dispatches_to_dismiss_executor():
    """operation_type='dismiss_recommendation' dispatcha pro executor certo (não apply)."""
    from src.google_ads import mutations

    fake_client = MagicMock()

    with (
        patch.object(mutations, "connection") as mock_connection,
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", AsyncMock()),
        patch.object(mutations, "record_actual", AsyncMock()),
        patch.object(mutations, "build_client_for_manager", AsyncMock(return_value=fake_client)),
        patch.object(mutations, "get_request_id", lambda: "dismiss-req-id"),
        patch.object(mutations, "reset_request_id", lambda: None),
        patch(
            "src.google_ads.mutates.recommendations.execute_apply_recommendation",
            MagicMock(),
        ) as apply_mock,
        patch(
            "src.google_ads.mutates.recommendations.execute_dismiss_recommendation",
            MagicMock(return_value=MagicMock()),
        ) as dismiss_mock,
        patch.object(mutations.audit_log, "record", AsyncMock(return_value=1)),
    ):
        mock_connection.get_pool.return_value = _mock_pool()

        result = await mutations.run_recommendation_action(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="dismiss_recommendation",
            payload={"recommendation_resource_name": "customers/1234567890/recommendations/2"},
        )

    dismiss_mock.assert_called_once()
    apply_mock.assert_not_called()
    assert result["provider_request_id"] == "dismiss-req-id"
    assert result["applied_count"] == 1


@pytest.mark.asyncio
async def test_unknown_operation_type_raises_friendly_error_and_still_audits_error():
    """operation_type desconhecido -> ValueError interno é capturado pelo
    `except Exception: raise to_friendly(e) from e` do bloco de execução (mesmo
    wrap que erros reais do SDK levam) -> GoogleAdsFriendlyError propaga pro
    caller; audit registra status='error' (o finally roda incondicionalmente)."""
    from src.google_ads import mutations
    from src.google_ads.errors import GoogleAdsFriendlyError

    with (
        patch.object(mutations, "connection") as mock_connection,
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", AsyncMock()),
        patch.object(mutations, "record_actual", AsyncMock()) as record_actual_mock,
        patch.object(mutations, "build_client_for_manager", AsyncMock(return_value=MagicMock())),
        patch.object(mutations, "get_request_id", lambda: None),
        patch.object(mutations, "reset_request_id", lambda: None),
        patch.object(mutations.audit_log, "record", AsyncMock(return_value=1)) as audit_mock,
    ):
        mock_connection.get_pool.return_value = _mock_pool()

        with pytest.raises(GoogleAdsFriendlyError):
            await mutations.run_recommendation_action(
                manager_id=uuid4(),
                session_id=uuid4(),
                customer_id="1234567890",
                operation_type="totally_unknown_op",
                payload={},
            )

    # finally sempre reconcilia + audita, mesmo em erro pós-reserva. error_message
    # carrega a mensagem GENÉRICA do to_friendly (ValueError não tem .failure,
    # então cai no fallback "Erro inesperado... (ValueError)") -- não o texto
    # original "Unknown recommendation operation" (comportamento intencional:
    # to_friendly nunca vaza a exceção crua pro audit_log/usuário final).
    record_actual_mock.assert_awaited_once()
    audit_mock.assert_awaited_once()
    assert audit_mock.call_args.kwargs["status"] == "error"
    assert "ValueError" in audit_mock.call_args.kwargs["error_message"]
