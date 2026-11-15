"""`scripts/medir_uso_tools.py`: a montagem do relatório de uso (A-01, P0).

O SQL roda em `tests/integration/test_medir_uso_tools.py`; aqui só a parte pura,
com `LinhaDeUso` montadas à mão.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import asyncpg
import pytest

from scripts.medir_uso_tools import (
    OPERACAO_QUE_CONTA,
    OPERACOES_AUXILIARES,
    PASSARAM_A_AUDITAR_NO_P0,
    VARIAS_LINHAS_POR_CHAMADA,
    ContagemApplyChange,
    LinhaDeUso,
    montar_relatorio,
)
from src.mcp.tools._registry import all_tools, import_all_tools
from tests.unit.test_leitura_audita_no_sucesso import COMO_CADA_TOOL_AUDITA

_INICIO = date(2026, 8, 18)
_FIM = date(2026, 11, 15)
_SEM_APLICACAO = ContagemApplyChange(
    via_pendencias=0, gestores_pendencias=0, ultima_pendencia=None, via_audit=0
)


def _registry() -> set[str]:
    import_all_tools()
    nomes = {t.name for t in all_tools()}
    assert nomes, "registry vazio"
    return nomes


def _linha(operation: str, **campos: object) -> LinhaDeUso:
    base: dict[str, object] = {
        "linhas": 0,
        "linhas_preview": 0,
        "sucesso": 0,
        "gestores": 1,
        "ultima": datetime(2026, 11, 14, 15, tzinfo=UTC),
        "primeira_sucesso": None,
    }
    base.update(campos)
    return LinhaDeUso(operation=operation, **base)  # type: ignore[arg-type]


def _relatorio(
    linhas: list[LinhaDeUso], aplicacoes: ContagemApplyChange = _SEM_APLICACAO
) -> dict[str, Any]:
    return montar_relatorio(
        linhas, aplicacoes, tools=sorted(COMO_CADA_TOOL_AUDITA), inicio=_INICIO, fim=_FIM
    )


def test_toda_tool_do_registry_tem_linha() -> None:
    # A lista de tools vem do inventário do T0.1, que é amarrado ao registry.
    assert set(_relatorio([])["tools"]) == _registry()


def test_mapa_so_tem_tool_que_existe() -> None:
    registry = _registry()
    for mapa in (
        set(OPERACAO_QUE_CONTA),
        set(OPERACOES_AUXILIARES),
        set(VARIAS_LINHAS_POR_CHAMADA),
        set(PASSARAM_A_AUDITAR_NO_P0),
    ):
        assert not mapa - registry, f"tool fora do registry: {sorted(mapa - registry)}"


def test_preview_e_aplicacao_separados() -> None:
    rel = _relatorio([_linha("update_ad_status", linhas=2, linhas_preview=5, sucesso=2)])
    entrada = rel["tools"]["update_ad_status"]
    assert entrada["linhas"] == 2
    assert entrada["linhas_preview"] == 5


def test_auxiliar_nao_conta_chamada() -> None:
    rel = _relatorio(
        [
            _linha("get_negative_keywords_audit", linhas=3, sucesso=3),
            _linha("get_negative_keywords_audit_creations", linhas=3, sucesso=3),
        ]
    )
    assert rel["tools"]["get_negative_keywords_audit"]["linhas"] == 3
    assert rel["operations_fora_do_registry"] == []


def test_operation_sem_dono_sai_em_fora_do_registry() -> None:
    rel = _relatorio([_linha("operacao_que_nao_existe", linhas=4)])
    assert rel["operations_fora_do_registry"] == [
        {"operation": "operacao_que_nao_existe", "linhas": 4, "linhas_preview": 0}
    ]


def test_operation_diferente_do_nome_e_contada_pela_tool() -> None:
    rel = _relatorio(
        [
            _linha("audit_goal_attribution_actions", linhas=7),
            _linha("audit_goal_attribution_goals", linhas=7),
        ]
    )
    assert rel["tools"]["audit_goal_attribution"]["linhas"] == 7
    assert rel["operations_fora_do_registry"] == []


def test_tool_que_passou_a_auditar_traz_janela_efetiva() -> None:
    assert len(PASSARAM_A_AUDITAR_NO_P0) == 7
    com_sucesso = "get_funnel_metrics"
    rel = _relatorio(
        [
            _linha(
                com_sucesso,
                linhas=3,
                sucesso=2,
                # 01:30 UTC de 20/11 ainda é 19/11 em Brasília.
                primeira_sucesso=datetime(2026, 11, 20, 1, 30, tzinfo=UTC),
            ),
            # Só recusa: linha existe, sucesso não.
            _linha("get_budget_pacing", linhas=2, sucesso=0),
        ]
    )
    for tool in PASSARAM_A_AUDITAR_NO_P0:
        entrada = rel["tools"][tool]
        assert "janela_efetiva_desde" in entrada, tool
        if tool == com_sucesso:
            assert entrada["janela_efetiva_desde"] == "2026-11-19"
        else:
            assert entrada["janela_efetiva_desde"] is None, tool
            assert "sem linha de sucesso na janela" in entrada["nota"], tool
    # Tool fora do P0 não ganha o campo.
    assert "janela_efetiva_desde" not in rel["tools"]["get_campaign_performance"]


def test_nao_medido_nao_vira_zero() -> None:
    rel = _relatorio([_linha("get_change_history", linhas=9)])
    drift = rel["tools"]["detect_drift"]
    assert drift["medivel"] is False
    assert drift["linhas"] is None
    assert "get_change_history" in drift["nota"]
    assert rel["tools"]["get_change_history"]["linhas"] == 9

    aplicar = _relatorio(
        [],
        ContagemApplyChange(
            via_pendencias=4,
            gestores_pendencias=2,
            ultima_pendencia=datetime(2026, 11, 10, 12, tzinfo=UTC),
            via_audit=5,
        ),
    )["tools"]["apply_change"]
    assert aplicar["linhas"] is None
    assert aplicar["via_pendencias"]["aplicacoes"] == 4
    assert aplicar["via_pendencias"]["gestores"] == 2
    assert "purge" in aplicar["via_pendencias"]["nota"]
    assert aplicar["via_audit"]["aplicacoes"] == 5
    assert "estimado" in aplicar["via_audit"]["nota"]


def test_varias_linhas_por_chamada_e_marcada() -> None:
    rel = _relatorio([_linha("get_account_balance", linhas=10)])
    assert rel["tools"]["get_account_balance"]["linhas_sao_chamadas"] is False
    assert rel["tools"]["get_campaign_performance"]["linhas_sao_chamadas"] is True


def test_relatorio_nao_tem_email() -> None:
    rel = _relatorio(
        [_linha(nome, linhas=1, sucesso=1, gestores=2) for nome in sorted(_registry())],
        ContagemApplyChange(
            via_pendencias=1, gestores_pendencias=1, ultima_pendencia=None, via_audit=1
        ),
    )
    assert "@" not in json.dumps(rel, ensure_ascii=False)


async def test_medicao_abre_uma_conexao_em_transacao_so_de_leitura(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O CLI lê produção: uma conexão, tudo dentro de `transaction(readonly=True)`,
    e a conexão fecha no fim. O SQL de verdade roda no teste de integração."""
    import scripts.medir_uso_tools as script

    eventos: list[str] = []

    class _Transacao:
        async def __aenter__(self) -> None:
            eventos.append("begin")

        async def __aexit__(self, *_exc: object) -> None:
            eventos.append("end")

    class _Conexao:
        def transaction(self, **kwargs: Any) -> _Transacao:
            eventos.append(f"transaction:{kwargs}")
            return _Transacao()

        async def fetch(self, *_a: Any) -> list[Any]:
            eventos.append("fetch")
            return []

        async def fetchrow(self, *_a: Any) -> dict[str, Any]:
            eventos.append("fetchrow")
            return {"n": 0, "gestores": 0, "ultima": None}

        async def fetchval(self, *_a: Any) -> int:
            eventos.append("fetchval")
            return 0

        async def close(self) -> None:
            eventos.append("close")

    conexoes: list[str] = []

    async def _connect(dsn: str) -> _Conexao:
        conexoes.append(dsn)
        return _Conexao()

    monkeypatch.setattr(asyncpg, "connect", _connect)
    rel = await script._medir("postgres://falso", inicio=_INICIO, fim=_FIM)

    assert conexoes == ["postgres://falso"]
    assert eventos == [
        "transaction:{'readonly': True}",
        "begin",
        "fetch",
        "fetchrow",
        "fetchval",
        "end",
        "close",
    ]
    assert set(rel["tools"]) == _registry()
