"""F148 — o dry-run tem que deixar rastro proprio na trilha.

Antes deste fix, as 24 tools que chamam `create_pending` nao gravavam linha
nenhuma no caminho de dry-run, e o `create_pending` tambem nao. A unica linha
que aparecia era a da consulta GAQL do preview, emitida por `reports.py` com
`action_type="read"`. Pior: o `ensure_account_access` que o `create_pending`
chama com `level="write"` audita SO QUANDO NEGA — entao a trilha guardava os
previews recusados e perdia todos os que funcionavam.
"""

import pathlib
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.governance import dry_run


def _conn() -> AsyncMock:
    """asyncpg fake com `transaction()` usavel como async context manager."""
    conn = AsyncMock()
    conn.transaction = MagicMock(return_value=AsyncMock())
    return conn


@pytest.mark.asyncio
async def test_dry_run_grava_linha_propria_de_mutate_com_target_count_planejado():
    """A linha do preview e `mutate` + `dry_run`, e conta as operacoes PLANEJADAS.

    O `target_count` NAO pode ser o numero de linhas lidas pelo GAQL do preview
    (era o que aparecia antes: 0). Tem que ser o que a tool pretende escrever.
    """
    conn = _conn()
    gravadas = []

    async def _record(_conn_arg, **kwargs):
        gravadas.append(kwargs)
        return 1

    with (
        patch("src.governance.dry_run.ensure_account_access", AsyncMock()),
        patch("src.governance.dry_run.audit_log.record", AsyncMock(side_effect=_record)),
    ):
        await dry_run.create_pending(
            conn,
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="update_ad_schedule",
            payload={"__target_count__": 10, "campaign_ids": ["1"]},
            blast_summary="10 operacoes",
        )

    assert len(gravadas) == 1, "o dry-run tem que deixar exatamente uma linha propria"
    linha = gravadas[0]
    assert linha["action_type"] == "mutate", "preview e tentativa de escrita, nao leitura"
    assert linha["dry_run"] is True
    assert linha["operation"] == "update_ad_schedule"
    assert linha["target_count"] == 10, "tem que ser o planejado, nao o lido"
    assert linha["status"] == "success"


@pytest.mark.asyncio
async def test_target_count_ausente_grava_nulo_e_nunca_um():
    """Sem `__target_count__`, grava NULL — jamais o default `1` do apply_change.

    Hoje as 24 tools preenchem. O default silencioso e o que deixaria a 25a
    registrar "1 operacao" que ninguem planejou, e ninguem notaria.
    """
    conn = _conn()
    gravadas = []

    async def _record(_conn_arg, **kwargs):
        gravadas.append(kwargs)
        return 1

    with (
        patch("src.governance.dry_run.ensure_account_access", AsyncMock()),
        patch("src.governance.dry_run.audit_log.record", AsyncMock(side_effect=_record)),
    ):
        await dry_run.create_pending(
            conn,
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="tool_sem_target_count",
            payload={"campaign_ids": ["1"]},
            blast_summary="...",
        )

    assert gravadas[0]["target_count"] is None


@pytest.mark.asyncio
async def test_sem_acesso_nao_grava_linha_de_dry_run():
    """Negacao ja e auditada pelo `ensure_account_access`; nao duplicar."""
    from src.google_ads.access import AccountAccessDeniedError

    conn = _conn()
    record = AsyncMock()
    with (
        patch(
            "src.governance.dry_run.ensure_account_access",
            AsyncMock(side_effect=AccountAccessDeniedError("x")),
        ),
        patch("src.governance.dry_run.audit_log.record", record),
        pytest.raises(AccountAccessDeniedError),
    ):
        await dry_run.create_pending(
            conn,
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="999",
            operation_type="update_campaign_status",
            payload={"__target_count__": 5},
            blast_summary="...",
        )
    record.assert_not_called()


def test_toda_tool_que_cria_pendencia_declara_o_target_count_planejado():
    """Guard do 25o call-site: quem chama `create_pending` tem que passar o numero.

    Sem ele a linha de auditoria do F148 nasce com `target_count` NULL e a
    trilha volta a nao saber quantas operacoes o preview pretendia.

    Limite conhecido e deliberado: a checagem e por CONTEUDO DE ARQUIVO, nao por
    AST do call-site. Varias tools montam o payload numa variavel antes de
    passar, e um guard que so enxerga dict literal reprovaria codigo correto —
    ja aconteceu neste repo. Em troca, este guard nao pega o caso de a chave ser
    escrita num payload que nao e o passado ao `create_pending`.
    """
    tools = pathlib.Path("src/mcp/tools")
    faltando = [
        p.name
        for p in sorted(tools.glob("*.py"))
        if "create_pending" in (texto := p.read_text(encoding="utf-8"))
        and "__target_count__" not in texto
    ]
    assert not faltando, (
        "tools que criam pendencia sem declarar __target_count__ no payload: " + ", ".join(faltando)
    )
