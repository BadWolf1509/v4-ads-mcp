"""`scripts/medir_uso_tools.py`: a montagem do relatório de uso (A-01, P0).

O SQL roda em `tests/integration/test_medir_uso_tools.py`; aqui só a parte pura,
com `LinhaDeUso` montadas à mão.
"""

from __future__ import annotations

import ast
import inspect
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import asyncpg
import pytest

from scripts.medir_uso_tools import (
    OPERACAO_QUE_CONTA,
    OPERACOES_AUXILIARES,
    PASSARAM_A_AUDITAR_NO_P0,
    TOOLS_DE_MUTACAO,
    VARIAS_LINHAS_POR_CHAMADA,
    ContagemApplyChange,
    LinhaDeUso,
    montar_relatorio,
)
from src.mcp.tools._registry import all_tools, import_all_tools
from tests.unit import _guard_harness as h
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
        "linhas_mutacao": 0,
        "sucesso_mutacao": 0,
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
        set(TOOLS_DE_MUTACAO),
    ):
        assert not mapa - registry, f"tool fora do registry: {sorted(mapa - registry)}"


def test_preview_e_aplicacao_separados() -> None:
    rel = _relatorio(
        [
            _linha(
                "update_ad_status",
                linhas=2,
                linhas_preview=5,
                sucesso=2,
                linhas_mutacao=2,
                sucesso_mutacao=2,
            )
        ]
    )
    entrada = rel["tools"]["update_ad_status"]
    assert entrada["linhas"] == 2
    assert entrada["linhas_preview"] == 5


def test_leitura_da_tool_de_mutacao_nao_conta_como_chamada() -> None:
    """I1 da revisão: o preview de `update_ad_schedule` lê a grade com
    `audit_this_call=True` sob o nome da tool (`action_type='read'`, `dry_run`
    nulo). Essa leitura é pré-voo: nem aplicação, nem preview."""
    rel = _relatorio(
        [
            _linha(
                "update_ad_schedule",
                linhas=5,  # 3 leituras de grade + 2 aplicações
                linhas_preview=3,
                sucesso=5,
                linhas_mutacao=2,
                sucesso_mutacao=2,
            )
        ]
    )
    entrada = rel["tools"]["update_ad_schedule"]
    assert entrada["linhas"] == 2
    assert entrada["sucesso"] == 2
    assert entrada["linhas_preview"] == 3
    assert entrada["leituras_de_preflight"] == 3
    # Em tool de leitura a linha `read` é a chamada, e não há campo de pré-voo.
    leitura = _relatorio([_linha("get_assets", linhas=4, sucesso=4)])["tools"]["get_assets"]
    assert leitura["linhas"] == 4
    assert "leituras_de_preflight" not in leitura


def test_tools_de_mutacao_descreve_o_inventario() -> None:
    do_inventario = {t for t, cat in COMO_CADA_TOOL_AUDITA.items() if cat == "mutacao"}
    assert set(TOOLS_DE_MUTACAO) == do_inventario, (
        f"só no script: {sorted(TOOLS_DE_MUTACAO - do_inventario)}; "
        f"só no inventário: {sorted(do_inventario - TOOLS_DE_MUTACAO)}"
    )


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
    assert "detect_drift" in rel["tools"]["get_change_history"]["nota"]

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


# --- I2 da revisão: VARIAS_LINHAS_POR_CHAMADA amarrada ao código -------------
#
# Conta, por AST, os pontos que gravam audit e que o handler alcança: chamada
# com `audit_this_call` verdadeiro, `run_meta_level_performance`,
# `audit_log.record`, e os executores que auditam sempre
# (`run_keyword_planning`, `execute_gaql_raw`). Segue função local e função de
# `src.*` (um salto por vez, recursivo), multiplicando pelo número de pontos de
# chamada; um `audit_this_call=<parâmetro>` se resolve pelo que o chamador passa.
# O gate (`ensure_account_access`, `can_manager_access`) não entra: grava só na
# negação.
#
# É limite SUPERIOR de pontos, não contagem em runtime: ramos exclusivos somam
# (por isso `_UM_PONTO_POR_CHAMADA_APESAR_DA_CONTAGEM`), e laço não multiplica.
# Despacho dinâmico (função passada como argumento) só é visto quando a chamada
# carrega `audit_this_call` (o caso de `ler_colecao(leitor=...)`).

_EXECUTORES = frozenset(
    {
        "run_report",
        "run_meta_graph_get",
        "_gravar_audit_leitura",
        "run_mutation",
        "run_conversion_upload",
        "run_offline_user_data_job",
        "run_recommendation_action",
        "ensure_account_access",
        "can_manager_access",
    }
)
_AUDITAM_SEMPRE = frozenset(
    {"run_meta_level_performance", "run_keyword_planning", "execute_gaql_raw"}
)

# Mais de um ponto no código, uma linha (da operation que conta) por chamada.
_UM_PONTO_POR_CHAMADA_APESAR_DA_CONTAGEM: dict[str, str] = {
    "audit_goal_attribution": "o segundo ponto grava audit_goal_attribution_goals (auxiliar)",
    "detect_drift": "não medível: grava como get_change_history",
    "get_performance_breakdown": "os dois pontos estão em ramos exclusivos (hourly × demais)",
}

_Modulo = tuple[ast.Module, dict[str, ast.FunctionDef | ast.AsyncFunctionDef], dict[str, Any]]
_CACHE: dict[Path, _Modulo] = {}


def _modulo(caminho: Path) -> _Modulo:
    if caminho not in _CACHE:
        arv = h.arvore(caminho)
        fns = {f.name: f for f in h.funcoes(arv)}
        _CACHE[caminho] = (arv, fns, h._vinculos_de_src(arv, h.RAIZ))
    return _CACHE[caminho]


def _nome_chamado(f: ast.expr) -> str | None:
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _valor_do_parametro(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, nome: str, do_chamador: dict[str, ast.expr]
) -> ast.expr | None:
    if nome in do_chamador:
        return do_chamador[nome]
    a = fn.args
    for arg, default in zip(a.kwonlyargs, a.kw_defaults, strict=True):
        if arg.arg == nome:
            return default
    posicionais = a.posonlyargs + a.args
    for arg, default in zip(
        posicionais[len(posicionais) - len(a.defaults) :], a.defaults, strict=True
    ):
        if arg.arg == nome:
            return default
    return None


def _audita(
    chamada: ast.Call,
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    do_chamador: dict[str, ast.expr],
) -> bool:
    nome = _nome_chamado(chamada.func)
    if nome in _AUDITAM_SEMPRE:
        return True
    if (
        isinstance(chamada.func, ast.Attribute)
        and chamada.func.attr == "record"
        and isinstance(chamada.func.value, ast.Name)
        and chamada.func.value.id == "audit_log"
    ):
        return True
    for kw in chamada.keywords:
        if kw.arg != "audit_this_call":
            continue
        valor: ast.expr | None = kw.value
        if isinstance(valor, ast.Name):
            valor = _valor_do_parametro(fn, valor.id, do_chamador) or valor
        # Literal decide; qualquer outra expressão conta como auditada (lado seguro).
        return not (isinstance(valor, ast.Constant) and valor.value is not True)
    return False


def _alvo(chamada: ast.Call, caminho: Path) -> tuple[Path, str] | None:
    _, fns, vinculos = _modulo(caminho)
    f = chamada.func
    if isinstance(f, ast.Name):
        if f.id in _EXECUTORES:
            return None
        if f.id in fns:
            return (caminho, f.id)
        v = vinculos.get(f.id)
        if v is not None and v[1] is not None:
            return (Path(v[0]).resolve(), v[1])
    elif isinstance(f, ast.Attribute):
        if f.attr in _EXECUTORES:
            return None
        base = h._caminho_pontilhado(f.value)
        v = vinculos.get(base) if base else None
        if v is not None and v[1] is None:
            return (Path(v[0]).resolve(), f.attr)
    return None


def _pontos_auditados(
    caminho: Path,
    funcao: str,
    do_chamador: dict[str, ast.expr] | None = None,
    pilha: tuple[tuple[Path, str], ...] = (),
) -> list[str]:
    if (caminho, funcao) in pilha:
        return []
    _, fns, _ = _modulo(caminho)
    fn = fns.get(funcao)
    if fn is None:
        return []
    pontos: list[str] = []
    for no in h.nos_do_corpo_proprio(fn):
        if not isinstance(no, ast.Call):
            continue
        if _audita(no, fn, do_chamador or {}):
            pontos.append(f"{h.rel(caminho)}:{no.lineno}")
            continue
        alvo = _alvo(no, caminho)
        if alvo is not None:
            kwargs = {kw.arg: kw.value for kw in no.keywords if kw.arg}
            pontos += _pontos_auditados(alvo[0], alvo[1], kwargs, (*pilha, (caminho, funcao)))
    return pontos


def _pontos_por_tool_de_leitura() -> dict[str, list[str]]:
    import_all_tools()
    pontos: dict[str, list[str]] = {}
    for t in all_tools():
        if t.name in TOOLS_DE_MUTACAO or t.name == "apply_change":
            continue  # mutação conta preview/aplicação, não leitura
        arquivo = Path(inspect.getsourcefile(t.handler) or "").resolve()
        pontos[t.name] = _pontos_auditados(arquivo, t.handler.__name__)
    assert len(pontos) > 40, f"só {len(pontos)} tools de leitura: registry incompleto"
    return pontos


def test_varias_linhas_descreve_o_codigo() -> None:
    pontos = _pontos_por_tool_de_leitura()
    varios = {t for t, p in pontos.items() if len(p) > 1}
    fora_da_lista = (
        varios - VARIAS_LINHAS_POR_CHAMADA - set(_UM_PONTO_POR_CHAMADA_APESAR_DA_CONTAGEM)
    )
    assert not fora_da_lista, {
        t: pontos[t] for t in sorted(fora_da_lista)
    }  # grava mais de uma linha por chamada e não está em VARIAS_LINHAS_POR_CHAMADA
    sem_motivo = VARIAS_LINHAS_POR_CHAMADA - varios
    assert not sem_motivo, f"na lista sem mais de um ponto auditado: {sorted(sem_motivo)}"
    excecao_velha = set(_UM_PONTO_POR_CHAMADA_APESAR_DA_CONTAGEM) - varios
    assert not excecao_velha, f"exceção sem mais de um ponto: {sorted(excecao_velha)}"
    assert not VARIAS_LINHAS_POR_CHAMADA & set(_UM_PONTO_POR_CHAMADA_APESAR_DA_CONTAGEM)


def test_contador_ve_os_casos_conhecidos() -> None:
    """Controle do contador: os números que a revisão mediu à mão."""
    pontos = _pontos_por_tool_de_leitura()
    assert len(pontos["meta_get_budget_pacing"]) == 3
    assert len(pontos["get_campaign_performance"]) == 1
    # `audit_this_call=audited` resolvido pelo chamador: 3 consultas, 1 auditada.
    assert len(pontos["get_ad_schedule"]) == 1
    # O gate não conta.
    assert len(pontos["validate_gaql"]) == 1
    # `audit_log.record` direto conta (a linha do P0).
    assert len(pontos["meta_list_my_ad_accounts"]) == 1
    # Ramos exclusivos somam: é limite superior, e por isso há a exceção.
    assert len(pontos["get_performance_breakdown"]) == 2
