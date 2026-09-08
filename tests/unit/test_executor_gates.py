"""Unit tests proving each Google executor propagates AccountAccessDeniedError.

T2 run_report, T3 run_mutation, T4a run_conversion_upload, T4b run_offline_user_data_job.

Pattern: patch ensure_account_access to raise + patch connection.get_pool so
the async-context-manager inside the gate doesn't blow up, then assert the error
propagates unchanged out of the executor.
"""

from __future__ import annotations

import ast
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.google_ads.access import AccountAccessDeniedError
from tests.unit import _guard_harness as h

# ---------------------------------------------------------------------------
# T2 — run_report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_report_denies_without_access():
    from src.google_ads import reports

    mock_pool = MagicMock()
    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_conn_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_conn_cm

    with (
        patch("src.google_ads.reports.connection.get_pool", return_value=mock_pool),
        patch(
            "src.google_ads.reports.ensure_account_access",
            AsyncMock(side_effect=AccountAccessDeniedError("sem acesso")),
        ),
        pytest.raises(AccountAccessDeniedError),
    ):
        await reports.run_report(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="999",
            query="SELECT 1",
            row_formatter=lambda r: {},
            operation_name="test_op",
        )


# ---------------------------------------------------------------------------
# T3 — run_mutation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_mutation_denies_without_access():
    from src.google_ads import mutations

    mock_pool = MagicMock()
    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_conn_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_conn_cm

    with (
        patch("src.google_ads.mutations.connection.get_pool", return_value=mock_pool),
        patch(
            "src.google_ads.mutations.ensure_account_access",
            AsyncMock(side_effect=AccountAccessDeniedError("sem acesso")),
        ),
        pytest.raises(AccountAccessDeniedError),
    ):
        await mutations.run_mutation(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="999",
            operation_type="update_campaign_status",
            payload={},
            target_count=1,
        )


# ---------------------------------------------------------------------------
# T4a — run_conversion_upload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_conversion_upload_denies_without_access():
    from src.google_ads import conversions

    mock_pool = MagicMock()
    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_conn_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_conn_cm

    with (
        patch("src.google_ads.conversions.connection.get_pool", return_value=mock_pool),
        patch(
            "src.google_ads.conversions.ensure_account_access",
            AsyncMock(side_effect=AccountAccessDeniedError("sem acesso")),
        ),
        pytest.raises(AccountAccessDeniedError),
    ):
        await conversions.run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="999",
            operation_type="import_offline_conversions",
            payload={},
            target_count=1,
        )


# ---------------------------------------------------------------------------
# T4b — run_offline_user_data_job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_offline_user_data_job_denies_without_access():
    from src.google_ads import customer_match

    mock_pool = MagicMock()
    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_conn_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_conn_cm

    with (
        patch("src.google_ads.customer_match.connection.get_pool", return_value=mock_pool),
        patch(
            "src.google_ads.customer_match.ensure_account_access",
            AsyncMock(side_effect=AccountAccessDeniedError("sem acesso")),
        ),
        pytest.raises(AccountAccessDeniedError),
    ):
        await customer_match.run_offline_user_data_job(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="999",
            user_list_id="1",
            operation_type="add",
            hashed_members=[],
        )


# ---------------------------------------------------------------------------
# R7-I3 — o EIXO read/write do gate
# ---------------------------------------------------------------------------
#
# Os quatro testes acima provam que a negacao PROPAGA. Nenhum deles olha o
# `level`: ate 2026-09-07, trocar `level="write"` por `"read"` nos executores
# deixava a suite inteira verde — e o eixo do hard-gate ficava inerte, porque
# um gestor com grant so de leitura passaria a poder MUTAR.
#
# Duas camadas, porque nenhuma sozinha basta:
#
# 1. **Comportamental** (`test_executor_gateia_no_nivel_certo`): o kwarg tem
#    que CHEGAR em `ensure_account_access` em tempo de execucao. Um literal
#    escrito no fonte mas perdido no caminho (lambda que nao repassa, wrapper
#    que reescreve) passaria por um guard so de sintaxe.
# 2. **Inventario** (`test_todo_call_site_do_gate_declara_o_nivel`): a lista de
#    call-sites e conferida INTEIRA contra uma tabela escrita. Nao e enumeracao
#    que perde o proximo executor — e o contrario: call-site novo, nivel
#    trocado ou funcao renomeada deixam o teste VERMELHO e obrigam alguem a
#    decidir por escrito. Cobre tambem `dry_run.create_pending` e
#    `validate_gaql`, que nao sao executores e nao tem teste comportamental.

# (arquivo sob src/, funcao que envolve a chamada, level literal)
CALL_SITES_DO_GATE = {
    ("google_ads/conversions.py", "run_conversion_upload", "write"),
    ("google_ads/customer_match.py", "run_offline_user_data_job", "write"),
    ("google_ads/mutations.py", "run_mutation", "write"),
    ("google_ads/mutations.py", "run_recommendation_action", "write"),
    ("google_ads/reports.py", "run_report", "read"),
    ("governance/dry_run.py", "create_pending", "write"),
    ("mcp/tools/validate_gaql.py", "validate_gaql", "read"),
}


def _funcao_dona(arv: ast.Module) -> dict[ast.AST, str]:
    """Nome da funcao que ENVOLVE cada no do modulo ("<modulo>" quando nenhuma).

    O `ast` nao guarda ponteiro pro pai, e a chamada ao gate mora dentro de um
    `lambda` passado a `run_with_reconnect` — quem responde por ela e a funcao
    de fora, nao o lambda. Funcao no nivel de modulo (nao aninhada dentro do
    laco de arquivos) porque a closure capturaria a variavel do laco.
    """
    dono: dict[ast.AST, str] = {}

    def visita(no: ast.AST, atual: str) -> None:
        for filho in ast.iter_child_nodes(no):
            envolve = (
                filho.name if isinstance(filho, ast.FunctionDef | ast.AsyncFunctionDef) else atual
            )
            dono[filho] = envolve
            visita(filho, envolve)

    visita(arv, "<modulo>")
    return dono


def _call_sites_do_gate() -> set[tuple[str, str, str | None]]:
    """(arquivo, funcao, level) de cada chamada a `ensure_account_access` em src/.

    `level` vem `None` quando a chamada NAO passa o kwarg (herdaria o default
    `"read"` da assinatura — o formato do rebaixamento silencioso) e
    `"<nao-literal>"` quando passa algo que nao da pra ler estaticamente.
    """
    achados: set[tuple[str, str, str | None]] = set()
    for p in h.fontes_py():
        arv = h.arvore(p)
        dono = _funcao_dona(arv)
        for no in ast.walk(arv):
            if not isinstance(no, ast.Call):
                continue
            f = no.func
            nome = (
                f.id
                if isinstance(f, ast.Name)
                else (f.attr if isinstance(f, ast.Attribute) else "")
            )
            if nome not in h.nomes_locais(arv, "ensure_account_access"):
                continue
            nivel: str | None = None
            for kw in no.keywords:
                if kw.arg != "level":
                    continue
                bruto = kw.value
                nivel = (
                    bruto.value
                    if isinstance(bruto, ast.Constant) and isinstance(bruto.value, str)
                    else "<nao-literal>"
                )
            achados.add((h.rel(p).removeprefix("src/"), dono.get(no, "<modulo>"), nivel))
    return achados


def test_todo_call_site_do_gate_declara_o_nivel() -> None:
    """O inventario de call-sites do hard-gate, conferido inteiro.

    Falhar aqui NAO e teste chato: e a pergunta "este call-site novo le ou
    escreve?" chegando a quem escreveu o codigo, em vez de ser respondida pelo
    default `"read"` da assinatura.
    """
    achados = _call_sites_do_gate()
    assert achados, (
        "nenhuma chamada a ensure_account_access encontrada em src/ — guard que "
        "varre zero call-sites passa por vacuidade (a funcao foi renomeada?)"
    )
    sem_nivel = {a for a in achados if a[2] is None or a[2] == "<nao-literal>"}
    assert not sem_nivel, (
        f"call-site do gate sem `level=` literal: {sorted(sem_nivel)}. Sem o kwarg "
        "a chamada herda o default 'read' da assinatura — que e exatamente a forma "
        "do rebaixamento silencioso: um caminho de ESCRITA gateado como leitura "
        "passa para quem so tem grant de leitura."
    )
    assert achados == CALL_SITES_DO_GATE, (
        "o inventario de call-sites do hard-gate mudou.\n"
        f"  so no codigo: {sorted(achados - CALL_SITES_DO_GATE)}\n"
        f"  so na tabela: {sorted(CALL_SITES_DO_GATE - achados)}\n"
        "Atualize CALL_SITES_DO_GATE **decidindo** o nivel de cada linha nova: "
        "escrita e 'write', leitura e 'read'. Trocar um 'write' por 'read' aqui "
        "sem motivo escrito e liberar mutacao para grant de leitura."
    )


_ARGUMENTOS_POR_EXECUTOR: dict[str, tuple[str, dict[str, Any]]] = {
    "run_mutation": (
        "src.google_ads.mutations",
        {"operation_type": "op", "payload": {}, "target_count": 1},
    ),
    "run_recommendation_action": (
        "src.google_ads.mutations",
        {"operation_type": "dismiss_recommendation", "payload": {}},
    ),
    "run_conversion_upload": (
        "src.google_ads.conversions",
        {"operation_type": "op", "payload": {}, "target_count": 1},
    ),
    "run_offline_user_data_job": (
        "src.google_ads.customer_match",
        {"user_list_id": "1", "operation_type": "add", "hashed_members": []},
    ),
    "run_report": (
        "src.google_ads.reports",
        {"query": "SELECT 1", "row_formatter": lambda r: {}, "operation_name": "test_op"},
    ),
}


async def _kwargs_do_gate(executor: str) -> dict[str, Any]:
    """Roda o executor ate o gate e devolve os kwargs que ele passou.

    O gate levanta (nada depois dele roda), mas o AsyncMock registra a chamada.
    """
    import importlib

    modulo, extras = _ARGUMENTOS_POR_EXECUTOR[executor]
    mod = importlib.import_module(modulo)
    gate = AsyncMock(side_effect=AccountAccessDeniedError("sem acesso"))

    mock_pool = MagicMock()
    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_conn_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_conn_cm

    argumentos: dict[str, Any] = {
        "manager_id": uuid4(),
        "session_id": uuid4(),
        "customer_id": "999",
        **extras,
    }
    with (
        patch(f"{modulo}.connection.get_pool", return_value=mock_pool),
        patch(f"{modulo}.ensure_account_access", gate),
        pytest.raises(AccountAccessDeniedError),
    ):
        await getattr(mod, executor)(**argumentos)
    assert gate.await_args is not None, (
        f"{executor} nao chegou a chamar ensure_account_access — o teste do nivel "
        "estaria medindo o nada"
    )
    return dict(gate.await_args.kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("executor", "nivel"),
    [
        ("run_mutation", "write"),
        ("run_recommendation_action", "write"),
        ("run_conversion_upload", "write"),
        ("run_offline_user_data_job", "write"),
        ("run_report", "read"),
    ],
)
async def test_executor_gateia_no_nivel_certo(executor: str, nivel: str) -> None:
    """R7-I3: o `level` que o executor DECLARA tem que ser o que CHEGA no gate."""
    kwargs = await _kwargs_do_gate(executor)
    assert kwargs["level"] == nivel, (
        f"{executor} gateou com level={kwargs.get('level')!r}, esperado {nivel!r}. "
        "Executor de escrita gateado como leitura libera mutacao para quem so tem "
        "grant de leitura."
    )
