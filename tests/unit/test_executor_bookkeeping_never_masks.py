"""F83: bookkeeping do `finally` nao pode derrubar o resultado da operacao.

Excecao levantada dentro de um `finally` DESCARTA o `return` pendente do `try`
(semantica do Python). Nos executores, o `finally` faz `pool.acquire()` cru pra
reconciliar quota e gravar audit — e conexao asyncpg stale (modo de falha F76,
6 ocorrencias reais em producao) faria uma mutacao JA APLICADA no Google voltar
como erro pro gestor. Consequencia tripla: (1) erro numa operacao que funcionou,
(2) cliente LLM re-tenta operacao NAO-idempotente (add_keywords, create_campaign,
update_campaign_budget), (3) nenhuma linha de audit — o invariante "audit SEMPRE
em mutates" quebra justamente onde mais importa.

Contrato coberto aqui:
- falha do bookkeeping NUNCA mascara o resultado da operacao;
- falha na reconciliacao de quota NAO impede a gravacao do audit (sao
  independentes — hoje sao sequenciais no mesmo `finally`, entao a primeira
  derruba a segunda);
- a falha vira log ERROR (alertavel via add_cloud_logging_severity) em vez de
  sumir em silencio.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _pool_with_transactable_conn() -> MagicMock:
    """conn.transaction() precisa ser um async CM real (nao coroutine bare)."""
    fake_conn = AsyncMock()
    fake_txn_cm = MagicMock()
    fake_txn_cm.__aenter__ = AsyncMock(return_value=None)
    fake_txn_cm.__aexit__ = AsyncMock(return_value=None)
    fake_conn.transaction = MagicMock(return_value=fake_txn_cm)

    mock_pool = MagicMock()
    mock_acquire_cm = MagicMock()
    mock_acquire_cm.__aenter__ = AsyncMock(return_value=fake_conn)
    mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_acquire_cm
    return mock_pool


def _fake_success_client() -> MagicMock:
    client = MagicMock()
    fake_response = MagicMock()
    fake_response.mutate_operation_responses = []
    fake_response.partial_failure_error = MagicMock(code=0, details=[])
    fake_service = MagicMock()
    fake_service.mutate = MagicMock(return_value=fake_response)
    client.get_service = MagicMock(return_value=fake_service)
    client.get_type = MagicMock(return_value=MagicMock(mutate_operations=[]))
    return client


class _StaleConnectionError(Exception):
    """Stand-in pro asyncpg.ConnectionDoesNotExistError do F76."""


def _pool_that_goes_stale_after(healthy_acquires: int) -> MagicMock:
    """Pool que serve N conexoes e depois falha JA NO acquire.

    E o modo de falha real do F76: o asyncpg so descobre o socket fechado no
    proximo statement/acquire, nao no corpo do `with`. Como o ruff colapsou o
    `async with best_effort(...), pool.acquire() as conn` num statement so, este
    teste prova que o best_effort ainda captura excecao vinda do `__aenter__` do
    context manager seguinte (semantica de `with A(), B()` == aninhado).
    """
    pool = _pool_with_transactable_conn()
    healthy_cm = pool.acquire.return_value
    calls = {"n": 0}

    def _acquire(*_args: object, **_kwargs: object) -> MagicMock:
        calls["n"] += 1
        if calls["n"] > healthy_acquires:
            failing_cm = MagicMock()
            failing_cm.__aenter__ = AsyncMock(side_effect=_StaleConnectionError("stale"))
            failing_cm.__aexit__ = AsyncMock(return_value=None)
            return failing_cm
        return healthy_cm

    pool.acquire = MagicMock(side_effect=_acquire)
    return pool


@pytest.mark.asyncio
async def test_conexao_stale_no_proprio_acquire_do_finally_nao_derruba_o_mutate():
    """F83: as 2 primeiras aquisicoes (gate + reserva) funcionam; as do `finally`
    falham no acquire — o mutate ja aplicado tem que voltar mesmo assim."""
    from src.google_ads import mutations
    from src.google_ads.mutations import run_mutation

    with (
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", AsyncMock()),
        patch.object(mutations, "record_actual", AsyncMock()),
        patch.object(mutations.audit_log, "record", AsyncMock(return_value=1)),
        patch.object(mutations.connection, "get_pool", return_value=_pool_that_goes_stale_after(2)),
        patch.object(
            mutations, "build_client_for_manager", AsyncMock(return_value=_fake_success_client())
        ),
        patch.object(mutations, "get_builder", lambda _op: lambda c, cid, p: [MagicMock()]),
        patch.object(mutations, "get_request_id", lambda: "fake-req-id"),
        patch.object(mutations, "reset_request_id", lambda: None),
    ):
        result = await run_mutation(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="update_keyword_status",
            payload={"keywords": [{}]},
            target_count=2,
        )

    assert result["applied_count"] == 2


@pytest.mark.asyncio
async def test_mutation_aplicada_sobrevive_a_falha_de_audit():
    """F83: audit que falha no `finally` NAO pode transformar mutate aplicado em erro."""
    from src.google_ads import mutations
    from src.google_ads.mutations import run_mutation

    with (
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", AsyncMock()),
        patch.object(mutations, "record_actual", AsyncMock()),
        patch.object(
            mutations.audit_log, "record", AsyncMock(side_effect=_StaleConnectionError("stale"))
        ),
        patch.object(mutations.connection, "get_pool", return_value=_pool_with_transactable_conn()),
        patch.object(
            mutations, "build_client_for_manager", AsyncMock(return_value=_fake_success_client())
        ),
        patch.object(mutations, "get_builder", lambda _op: lambda c, cid, p: [MagicMock()]),
        patch.object(mutations, "get_request_id", lambda: "fake-req-id"),
        patch.object(mutations, "reset_request_id", lambda: None),
    ):
        result = await run_mutation(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="update_keyword_status",
            payload={"keywords": [{}]},
            target_count=3,
        )

    # A mutacao FOI aplicada no Google — o gestor tem que receber isso, nao um erro.
    assert result["applied_count"] == 3
    assert result["provider_request_id"] == "fake-req-id"


@pytest.mark.asyncio
async def test_falha_na_reconciliacao_de_quota_nao_impede_o_audit():
    """F83: quota e audit sao independentes — a 1a falhando nao pode pular a 2a."""
    from src.google_ads import mutations
    from src.google_ads.mutations import run_mutation

    audit_mock = AsyncMock(return_value=1)

    with (
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", AsyncMock()),
        patch.object(
            mutations, "record_actual", AsyncMock(side_effect=_StaleConnectionError("stale"))
        ),
        patch.object(mutations.audit_log, "record", audit_mock),
        patch.object(mutations.connection, "get_pool", return_value=_pool_with_transactable_conn()),
        patch.object(
            mutations, "build_client_for_manager", AsyncMock(return_value=_fake_success_client())
        ),
        patch.object(mutations, "get_builder", lambda _op: lambda c, cid, p: [MagicMock()]),
        patch.object(mutations, "get_request_id", lambda: "fake-req-id"),
        patch.object(mutations, "reset_request_id", lambda: None),
    ):
        result = await run_mutation(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="update_keyword_status",
            payload={"keywords": [{}]},
            target_count=3,
        )

    assert result["applied_count"] == 3
    audit_mock.assert_awaited_once()
    assert audit_mock.call_args.kwargs["status"] == "success"


@pytest.mark.asyncio
async def test_falha_de_bookkeeping_e_logada_como_erro():
    """F83: engolir a excecao nao pode ser silencioso — precisa virar log ERROR."""
    from src.google_ads import mutations
    from src.google_ads.mutations import run_mutation
    from src.governance import bookkeeping

    with (
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", AsyncMock()),
        patch.object(mutations, "record_actual", AsyncMock()),
        patch.object(
            mutations.audit_log, "record", AsyncMock(side_effect=_StaleConnectionError("stale"))
        ),
        patch.object(mutations.connection, "get_pool", return_value=_pool_with_transactable_conn()),
        patch.object(
            mutations, "build_client_for_manager", AsyncMock(return_value=_fake_success_client())
        ),
        patch.object(mutations, "get_builder", lambda _op: lambda c, cid, p: [MagicMock()]),
        patch.object(mutations, "get_request_id", lambda: "fake-req-id"),
        patch.object(mutations, "reset_request_id", lambda: None),
        patch.object(bookkeeping.log, "exception") as log_mock,
    ):
        await run_mutation(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="update_keyword_status",
            payload={"keywords": [{}]},
            target_count=1,
        )

    assert log_mock.called, "falha de bookkeeping tem que deixar rastro alertavel"
