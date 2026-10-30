"""Unit tests do executor generico `run_keyword_planning` (planejador de palavras).

Estrutura paralela a `run_offline_user_data_job` (customer_match): gate ->
reserva global + `mgr:` na transacao externa -> client -> run_blocking ->
bookkeeping best-effort. O executor nao conhece o KeywordPlanIdeaService: quem
sabe o que chamar e o closure `chamadas`, escrito pela tool.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.config import get_settings
from src.google_ads.access import AccountAccessDeniedError
from src.google_ads.errors import GoogleAdsFriendlyError
from src.governance.rate_limit import QuotaExhausted

_MOD = "src.google_ads.keyword_planning"


def _pool_with_transactable_conn() -> MagicMock:
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


@pytest.fixture
def ctx() -> dict[str, Any]:
    return {
        "manager_id": uuid4(),
        "session_id": uuid4(),
        "customer_id": "1163862076",
        "operation_name": "generate_keyword_ideas",
        "estimated_ops": 7,
        "params_summary": {"seed_count": 2},
    }


@pytest.fixture
def gov():
    with (
        patch(f"{_MOD}.before_call", AsyncMock(return_value=1)) as before,
        patch(f"{_MOD}.record_actual", AsyncMock()) as rec_actual,
        patch(f"{_MOD}.audit_log.record", AsyncMock(return_value=1)) as audit,
        patch(f"{_MOD}.ensure_account_access", AsyncMock()) as gate,
        patch(f"{_MOD}.connection.get_pool", return_value=_pool_with_transactable_conn()),
        patch(f"{_MOD}.build_client_for_manager", AsyncMock(return_value=MagicMock())) as build,
    ):
        yield {
            "before_call": before,
            "record_actual": rec_actual,
            "audit": audit,
            "gate": gate,
            "build": build,
        }


@pytest.mark.asyncio
async def test_nega_sem_acesso(ctx, gov) -> None:
    from src.google_ads.keyword_planning import run_keyword_planning

    gov["gate"].side_effect = AccountAccessDeniedError("sem acesso")
    chamadas = MagicMock()

    with pytest.raises(AccountAccessDeniedError):
        await run_keyword_planning(**ctx, chamadas=chamadas)

    chamadas.assert_not_called()
    gov["before_call"].assert_not_awaited()
    assert gov["gate"].await_args.kwargs["level"] == "read"


@pytest.mark.asyncio
async def test_reserva_unica_com_estimated_ops(ctx, gov) -> None:
    from src.google_ads.keyword_planning import run_keyword_planning

    gov["before_call"].side_effect = [11, 22]
    resultado = await run_keyword_planning(**ctx, chamadas=lambda client: ["a", "b", "c"])

    assert resultado == ["a", "b", "c"]
    assert gov["before_call"].await_count == 2
    from src.governance.rate_limit import hash_developer_token

    token_id = hash_developer_token(get_settings().google_ads_developer_token)
    chaves = [c.args[1] for c in gov["before_call"].await_args_list]
    assert chaves == [token_id, f"mgr:{ctx['manager_id']}"]
    for c in gov["before_call"].await_args_list:
        assert c.kwargs["estimated_ops"] == 7
    # reconcilia as duas, com actual = estimated em sucesso
    assert gov["record_actual"].await_count == 2
    reconciliados = [(c.args[1], c.kwargs["dia"]) for c in gov["record_actual"].await_args_list]
    assert reconciliados == [(token_id, 11), (f"mgr:{ctx['manager_id']}", 22)]
    for c in gov["record_actual"].await_args_list:
        assert c.kwargs["actual_ops"] == 7
    audit = gov["audit"].await_args.kwargs
    assert audit["action_type"] == "read"
    assert audit["operation"] == "generate_keyword_ideas"
    assert audit["target_count"] == 3
    assert audit["status"] == "success"
    assert audit["params_summary"] == {"seed_count": 2}


@pytest.mark.asyncio
async def test_resultado_sem_tamanho_audita_target_count_none(ctx, gov) -> None:
    from src.google_ads.keyword_planning import run_keyword_planning

    resultado = await run_keyword_planning(**ctx, chamadas=lambda client: 42)

    assert resultado == 42
    assert gov["audit"].await_args.kwargs["target_count"] is None


@pytest.mark.asyncio
async def test_quota_esgotada_nao_reconcilia_e_audita(ctx, gov) -> None:
    """F73: sem reserva persistida nao ha o que reconciliar; o audit roda."""
    from src.google_ads.keyword_planning import run_keyword_planning

    gov["before_call"].side_effect = QuotaExhausted("quota diaria esgotada: 9/10")
    chamadas = MagicMock()

    with pytest.raises(QuotaExhausted, match="quota diaria esgotada: 9/10"):
        await run_keyword_planning(**ctx, chamadas=chamadas)

    chamadas.assert_not_called()
    gov["record_actual"].assert_not_awaited()
    audit = gov["audit"].await_args.kwargs
    assert audit["status"] == "error"


@pytest.mark.asyncio
async def test_chamadas_roda_no_run_blocking(ctx, gov) -> None:
    from src.google_ads.keyword_planning import run_keyword_planning

    client = MagicMock()
    gov["build"].return_value = client
    recebido: list[Any] = []

    async def _fake_run_blocking(fn):
        recebido.append("run_blocking")
        return fn()

    def _chamadas(c: Any) -> list[int]:
        recebido.append(c)
        return [1]

    with patch(f"{_MOD}.run_blocking", _fake_run_blocking):
        await run_keyword_planning(**ctx, chamadas=_chamadas)

    assert recebido == ["run_blocking", client]


@pytest.mark.asyncio
async def test_erro_vira_friendly_e_audit_error(ctx, gov) -> None:
    from src.google_ads.keyword_planning import run_keyword_planning

    def _explode(client: Any) -> None:
        raise RuntimeError("falha do SDK")

    friendly = GoogleAdsFriendlyError("mensagem amigavel")
    with (
        patch(f"{_MOD}.to_friendly", return_value=friendly) as conv,
        pytest.raises(GoogleAdsFriendlyError) as exc,
    ):
        await run_keyword_planning(**ctx, chamadas=_explode)

    assert exc.value is friendly
    conv.assert_called_once()
    audit = gov["audit"].await_args.kwargs
    assert audit["status"] == "error"
    assert audit["target_count"] is None
    for c in gov["record_actual"].await_args_list:
        assert c.kwargs["actual_ops"] == 0


@pytest.mark.asyncio
async def test_resumo_do_resultado_e_mesclado_no_audit(ctx, gov) -> None:
    from src.google_ads.keyword_planning import run_keyword_planning

    await run_keyword_planning(
        **ctx,
        chamadas=lambda client: ["a"],
        resumo_do_resultado=lambda r: {"falhas": 2},
    )
    assert gov["audit"].await_args.kwargs["params_summary"] == {"seed_count": 2, "falhas": 2}


@pytest.mark.asyncio
async def test_resumo_que_levanta_nao_derruba_a_leitura(ctx, gov) -> None:
    from src.google_ads.keyword_planning import run_keyword_planning

    def ruim(r: Any) -> dict[str, Any]:
        raise RuntimeError("boom")

    resultado = await run_keyword_planning(
        **ctx, chamadas=lambda client: ["a"], resumo_do_resultado=ruim
    )
    assert resultado == ["a"]
    audit = gov["audit"].await_args.kwargs
    assert audit["status"] == "success"
    assert audit["params_summary"] == {"seed_count": 2}


@pytest.mark.asyncio
async def test_resumo_nao_roda_em_erro(ctx, gov) -> None:
    from src.google_ads.keyword_planning import run_keyword_planning

    resumo = MagicMock(return_value={"x": 1})

    def quebra(client: Any) -> Any:
        raise RuntimeError("falhou")

    with pytest.raises(GoogleAdsFriendlyError):
        await run_keyword_planning(**ctx, chamadas=quebra, resumo_do_resultado=resumo)
    resumo.assert_not_called()
    assert gov["audit"].await_args.kwargs["params_summary"] == {"seed_count": 2}


@pytest.mark.asyncio
async def test_request_id_nao_capturado_audita_none_e_nao_vazio(ctx, gov) -> None:
    """Nao medido e `None`, nunca `""`: o executor trocava o id ausente por string vazia,
    e o audit afirmava um id vazio onde nao havia medicao."""
    from src.google_ads.keyword_planning import run_keyword_planning

    await run_keyword_planning(**ctx, chamadas=lambda client: [1])

    assert gov["audit"].await_args.kwargs["provider_request_id"] is None


@pytest.mark.asyncio
async def test_request_id_capturado_vai_para_o_audit(ctx, gov) -> None:
    from src.google_ads.keyword_planning import run_keyword_planning

    with patch(f"{_MOD}.get_request_id", return_value="JjxAVnjh1bUgtd4KrxWk5Q"):
        await run_keyword_planning(**ctx, chamadas=lambda client: [1])

    assert gov["audit"].await_args.kwargs["provider_request_id"] == "JjxAVnjh1bUgtd4KrxWk5Q"
