"""Mede o uso de cada tool do registry a partir do `audit_log` (A-01, P0).

Uso, da raiz do repo::

    python scripts/medir_uso_tools.py --dias 90 [--ate YYYY-MM-DD]

Lê `DATABASE_URL` do ambiente (como `src/scripts/admin.py`), abre UMA conexão e
roda tudo numa transação `READ ONLY`: o script só lê, e o banco recusa qualquer
escrita que escapasse. Imprime JSON no stdout.

Existe porque a lista de "tools sem uso" que ia pautar o 02/12 contava como zero
o que não tinha sido medido (A-01 da varredura de 15/11): leitura que não grava
no sucesso, tool que grava sob o nome de outra, preview misturado com aplicação.
Cada tool sai com o que foi medido E com o que não foi — `linhas: null` quer
dizer "não medido", nunca zero.

Gestores só são CONTADOS: o relatório não traz e-mail nem id de ninguém.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg

_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:  # `python scripts/medir_uso_tools.py` da raiz
    sys.path.insert(0, str(_RAIZ))

from src.governance.dry_run import DEFAULT_TTL_MINUTES  # noqa: E402

# Janela em dias do calendário de Brasília: é o fuso da unidade e o das contas.
FUSO = ZoneInfo("America/Sao_Paulo")

# Tool -> a operation que representa UMA chamada dela. Padrão: o próprio nome.
# Só entra aqui quem difere (Anexo 1 da varredura de 15/11).
OPERACAO_QUE_CONTA: dict[str, str] = {
    "audit_goal_attribution": "audit_goal_attribution_actions",
    # Compartilhada com `get_change_history`: não separável (ver `_NAO_MEDIVEIS`).
    "detect_drift": "get_change_history",
}

# Operations gravadas junto com a chamada e que NÃO contam como chamada.
OPERACOES_AUXILIARES: dict[str, tuple[str, ...]] = {
    "get_negative_keywords_audit": ("get_negative_keywords_audit_creations",),
    "audit_goal_attribution": ("audit_goal_attribution_goals",),
    "bulk_pause_by_query": ("bulk_pause_by_query_dry_run",),
    "apply_recommendation": ("apply_recommendation_lookup",),
    "update_campaign_budget": ("update_campaign_budget_lookup",),
    "remove_ad": ("remove_ad_lookup", "remove_ad_enabled_por_grupo"),
    "update_recommendation_subscription": ("update_recommendation_subscription_lookup",),
}

# Tools que gravam mais de uma linha sob o mesmo nome numa chamada: para elas,
# `linhas` não é número de chamadas. Amarrada ao código por
# `test_varias_linhas_descreve_o_codigo` (contagem dos pontos auditados que o
# handler alcança, delegadas incluídas).
VARIAS_LINHAS_POR_CHAMADA: frozenset[str] = frozenset(
    {
        "audit_competitor_keywords",  # 2 leituras em gather
        "get_account_balance",  # 2 leituras
        "meta_get_account_balance",  # conta + insights
        "meta_get_ad_preview",  # prova de posse + prévia
        "meta_get_budget_pacing",  # 2 listagens de entidades + insights (2 no dia 1)
        "meta_get_creatives",  # com ad_id: anúncios + criativos
    }
)

# Tools de mutação: numa delas, a chamada é o preview (`dry_run=true`) ou a
# aplicação (`action_type='mutate'`). Uma leitura auditada sob o nome dela (a
# grade lida no preview de `update_ad_schedule`) é pré-voo, não chamada, e sai
# em `leituras_de_preflight`. Amarrada a `COMO_CADA_TOOL_AUDITA` (categoria
# `mutacao`) pelo teste.
TOOLS_DE_MUTACAO: frozenset[str] = frozenset(
    {
        "add_keywords",
        "add_negative_keywords",
        "add_negatives_from_search_terms",
        "apply_audience",
        "apply_recommendation",
        "bulk_pause_by_query",
        "create_ad_group",
        "create_and_link_assets",
        "create_campaign",
        "create_conversion_action",
        "create_conversion_value_rule_set",
        "create_rsa",
        "dismiss_recommendation",
        "import_offline_conversions",
        "remove_ad",
        "remove_asset_link",
        "remove_audience",
        "remove_negative_keywords",
        "update_ad_group_bid",
        "update_ad_group_status",
        "update_ad_schedule",
        "update_ad_status",
        "update_campaign_bidding",
        "update_campaign_budget",
        "update_campaign_status",
        "update_conversion_action",
        "update_keyword_bid",
        "update_keyword_status",
        "update_recommendation_subscription",
        "update_rsa",
        "upload_customer_match_list",
    }
)

# As 7 leituras que só passaram a gravar no sucesso com o P0. Antes do deploy
# dele, as 6 Google só têm linha `denied` (sem opt-in, `run_report` não grava
# nem o erro) e `meta_list_my_ad_accounts` não tem linha nenhuma: a medição útil
# começa na primeira linha de sucesso (`janela_efetiva_desde`).
PASSARAM_A_AUDITAR_NO_P0: frozenset[str] = frozenset(
    {
        "get_account_overview",
        "get_budget_pacing",
        "get_funnel_metrics",
        "get_negative_keywords_audit",
        "get_search_terms_report",
        "get_top_keywords_creatives",
        "meta_list_my_ad_accounts",
    }
)

_NAO_MEDIVEIS: dict[str, str] = {
    "detect_drift": "grava como get_change_history; não separável no audit",
}

_NOTA_PENDENCIAS = (
    "tokens consumidos na janela; o purge apaga pendência 7 dias depois de expirar "
    "(src/jobs/purge.py:23): cobre só o fim da janela"
)
_NOTA_VIA_AUDIT = (
    "estimado: linhas de mutação aplicadas precedidas, na mesma sessão, operation e "
    f"conta, por um preview até {DEFAULT_TTL_MINUTES} min antes; conta linhas, não "
    "aplicações (uma aplicação que grava N linhas sob o mesmo nome conta N)"
)

# Nota por tool que conta, além das próprias, chamadas de outra tool.
_NOTAS_POR_TOOL: dict[str, str] = {
    "get_change_history": "inclui as chamadas de detect_drift, que gravam sob o mesmo nome",
}

NAO_MEDIDO: tuple[str, ...] = (
    "detect_drift: grava como get_change_history, sem como separar as duas no audit_log.",
    "apply_change: não grava linha própria (aplica sob o nome da tool de origem); "
    "via_pendencias cobre só o fim da janela (purge), via_audit é estimativa.",
    "As 7 leituras do P0 só gravam no sucesso desde o deploy dele: antes, as 6 Google "
    "só têm linha denied e meta_list_my_ad_accounts nenhuma (janela_efetiva_desde "
    "marca o início útil).",
    "A linha success é gravada pela leitura principal; uma falha numa leitura "
    "secundária posterior não grava linha de erro (get_account_overview, "
    "get_top_keywords_creatives, get_budget_pacing, get_negative_keywords_audit, "
    "como já era no meta_get_account_overview).",
    "Tools em VARIAS_LINHAS_POR_CHAMADA: linhas não é número de chamadas.",
    "linhas conta tentativas em todas as situações (success, error, denied); sucesso "
    "separa só as que deram certo.",
    "Em tool de mutação, linhas conta só action_type=mutate (aplicação ou negação do "
    "gate de escrita); leitura auditada sob o nome dela sai em leituras_de_preflight.",
    "Antes do F148 (migration 007, 04/09/2026) o preview não gravava dry_run=true: "
    "numa janela que comece antes disso, preview e aplicação se misturam.",
    "Linhas action_type auth/system ficam de fora: não são chamada de tool.",
    "Chamada que falha antes do executor (validação de argumento, ou a leitura das "
    "contas em list_my_accounts/meta_list_my_ad_accounts) não grava linha.",
)


@dataclass(frozen=True)
class LinhaDeUso:
    """Agregado de uma operation na janela."""

    operation: str
    linhas: int  # dry_run IS NOT TRUE
    linhas_preview: int  # dry_run = true
    sucesso: int  # dry_run IS NOT TRUE e status = 'success'
    linhas_mutacao: int  # dry_run IS NOT TRUE e action_type = 'mutate'
    sucesso_mutacao: int  # idem, com status = 'success'
    gestores: int
    ultima: datetime | None
    primeira_sucesso: datetime | None


@dataclass(frozen=True)
class ContagemApplyChange:
    via_pendencias: int
    gestores_pendencias: int
    ultima_pendencia: datetime | None
    via_audit: int


def _limites(inicio: date, fim: date) -> tuple[datetime, datetime]:
    """[inicio 00:00, fim+1 00:00) no fuso de Brasília."""
    return (
        datetime.combine(inicio, time(), tzinfo=FUSO),
        datetime.combine(fim + timedelta(days=1), time(), tzinfo=FUSO),
    )


_SQL_USO = """
SELECT operation,
       count(*) FILTER (WHERE dry_run IS NOT TRUE) AS linhas,
       count(*) FILTER (WHERE dry_run IS TRUE) AS linhas_preview,
       count(*) FILTER (WHERE dry_run IS NOT TRUE AND status = 'success') AS sucesso,
       count(*) FILTER (WHERE dry_run IS NOT TRUE AND action_type = 'mutate')
           AS linhas_mutacao,
       count(*) FILTER (
           WHERE dry_run IS NOT TRUE AND action_type = 'mutate' AND status = 'success'
       ) AS sucesso_mutacao,
       count(DISTINCT manager_id) AS gestores,
       max(occurred_at) AS ultima,
       min(occurred_at) FILTER (WHERE dry_run IS NOT TRUE AND status = 'success')
           AS primeira_sucesso
  FROM audit_log
 WHERE occurred_at >= $1 AND occurred_at < $2
   AND action_type IN ('read', 'mutate')
 GROUP BY operation
"""

_SQL_PENDENCIAS = """
SELECT count(*) AS n, count(DISTINCT s.manager_id) AS gestores, max(p.consumed_at) AS ultima
  FROM pending_confirmations p
  JOIN mcp_sessions s ON s.id = p.session_id
 WHERE p.consumed_at >= $1 AND p.consumed_at < $2
"""

_SQL_APLICACOES_VIA_AUDIT = """
SELECT count(*)
  FROM audit_log a
 WHERE a.action_type = 'mutate'
   AND a.dry_run IS NOT TRUE
   AND a.occurred_at >= $1 AND a.occurred_at < $2
   AND EXISTS (
       SELECT 1
         FROM audit_log p
        WHERE p.dry_run = true
          AND p.session_id = a.session_id
          AND p.operation = a.operation
          AND p.customer_id IS NOT DISTINCT FROM a.customer_id
          AND p.occurred_at <= a.occurred_at
          AND p.occurred_at >= a.occurred_at - make_interval(mins => $3)
   )
"""


async def coletar(conn: asyncpg.Connection, *, inicio: date, fim: date) -> list[LinhaDeUso]:
    de, ate = _limites(inicio, fim)
    rows = await conn.fetch(_SQL_USO, de, ate)
    return [
        LinhaDeUso(
            operation=r["operation"],
            linhas=r["linhas"],
            linhas_preview=r["linhas_preview"],
            sucesso=r["sucesso"],
            linhas_mutacao=r["linhas_mutacao"],
            sucesso_mutacao=r["sucesso_mutacao"],
            gestores=r["gestores"],
            ultima=r["ultima"],
            primeira_sucesso=r["primeira_sucesso"],
        )
        for r in rows
    ]


async def coletar_aplicacoes(
    conn: asyncpg.Connection, *, inicio: date, fim: date
) -> ContagemApplyChange:
    de, ate = _limites(inicio, fim)
    pend = await conn.fetchrow(_SQL_PENDENCIAS, de, ate)
    via_audit = await conn.fetchval(_SQL_APLICACOES_VIA_AUDIT, de, ate, DEFAULT_TTL_MINUTES)
    assert pend is not None  # agregado sem GROUP BY sempre devolve uma linha
    return ContagemApplyChange(
        via_pendencias=pend["n"],
        gestores_pendencias=pend["gestores"],
        ultima_pendencia=pend["ultima"],
        via_audit=int(via_audit or 0),
    )


def _dia(momento: datetime | None) -> str | None:
    return momento.astimezone(FUSO).date().isoformat() if momento is not None else None


def _entrada_da_tool(tool: str, por_operation: dict[str, LinhaDeUso]) -> dict[str, Any]:
    operation = OPERACAO_QUE_CONTA.get(tool, tool)
    if tool in _NAO_MEDIVEIS:
        return {
            "linhas": None,
            "linhas_preview": None,
            "gestores": None,
            "ultima": None,
            "operation": operation,
            "medivel": False,
            "nota": _NAO_MEDIVEIS[tool],
        }
    uso = por_operation.get(operation)
    notas: list[str] = []
    if tool in TOOLS_DE_MUTACAO:
        linhas = uso.linhas_mutacao if uso else 0
        sucesso = uso.sucesso_mutacao if uso else 0
    else:
        linhas = uso.linhas if uso else 0
        sucesso = uso.sucesso if uso else 0
    entrada: dict[str, Any] = {
        "linhas": linhas,
        "linhas_preview": uso.linhas_preview if uso else 0,
        "sucesso": sucesso,
        "gestores": uso.gestores if uso else 0,
        "ultima": _dia(uso.ultima) if uso else None,
        "operation": operation,
        "medivel": True,
        "linhas_sao_chamadas": tool not in VARIAS_LINHAS_POR_CHAMADA,
    }
    if tool in TOOLS_DE_MUTACAO:
        entrada["leituras_de_preflight"] = (uso.linhas - uso.linhas_mutacao) if uso else 0
    if tool in VARIAS_LINHAS_POR_CHAMADA:
        notas.append("grava mais de uma linha por chamada: linhas != chamadas")
    if tool in _NOTAS_POR_TOOL:
        notas.append(_NOTAS_POR_TOOL[tool])
    if tool in PASSARAM_A_AUDITAR_NO_P0:
        desde = _dia(uso.primeira_sucesso) if uso else None
        entrada["janela_efetiva_desde"] = desde
        notas.append(
            "grava no sucesso só desde o P0; antes, só recusa ou erro"
            if desde is not None
            else "sem linha de sucesso na janela"
        )
    entrada["nota"] = "; ".join(notas) or None
    return entrada


def _entrada_apply_change(aplicacoes: ContagemApplyChange) -> dict[str, Any]:
    return {
        "linhas": None,
        "linhas_preview": None,
        "gestores": None,
        "ultima": None,
        "operation": None,
        "medivel": True,
        "nota": "não grava linha própria; dois números independentes abaixo",
        "via_pendencias": {
            "aplicacoes": aplicacoes.via_pendencias,
            "gestores": aplicacoes.gestores_pendencias,
            "ultima": _dia(aplicacoes.ultima_pendencia),
            "nota": _NOTA_PENDENCIAS,
        },
        "via_audit": {"aplicacoes": aplicacoes.via_audit, "nota": _NOTA_VIA_AUDIT},
    }


def montar_relatorio(
    linhas: list[LinhaDeUso],
    aplicacoes: ContagemApplyChange,
    *,
    tools: list[str],
    inicio: date,
    fim: date,
) -> dict[str, Any]:
    por_operation = {u.operation: u for u in linhas}
    conhecidas = {OPERACAO_QUE_CONTA.get(t, t) for t in tools}
    for t in tools:
        conhecidas.update(OPERACOES_AUXILIARES.get(t, ()))

    saida_tools: dict[str, dict[str, Any]] = {}
    for tool in sorted(tools):
        if tool == "apply_change":
            saida_tools[tool] = _entrada_apply_change(aplicacoes)
        else:
            saida_tools[tool] = _entrada_da_tool(tool, por_operation)

    fora = [
        {"operation": u.operation, "linhas": u.linhas, "linhas_preview": u.linhas_preview}
        for u in sorted(linhas, key=lambda u: u.operation)
        if u.operation not in conhecidas
    ]
    return {
        "janela": {"inicio": inicio.isoformat(), "fim": fim.isoformat(), "fuso": FUSO.key},
        "nao_medido": list(NAO_MEDIDO),
        "tools": saida_tools,
        "operations_fora_do_registry": fora,
    }


def _nomes_do_registry() -> list[str]:
    from src.mcp.tools._registry import all_tools, import_all_tools

    import_all_tools()
    return sorted(t.name for t in all_tools())


async def _medir(dsn: str, *, inicio: date, fim: date) -> dict[str, Any]:
    tools = _nomes_do_registry()
    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction(readonly=True):
            linhas = await coletar(conn, inicio=inicio, fim=fim)
            aplicacoes = await coletar_aplicacoes(conn, inicio=inicio, fim=fim)
    finally:
        await conn.close()
    return montar_relatorio(linhas, aplicacoes, tools=tools, inicio=inicio, fim=fim)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Uso por tool, lido do audit_log.")
    parser.add_argument("--dias", type=int, default=90, help="tamanho da janela (default 90)")
    parser.add_argument(
        "--ate",
        type=date.fromisoformat,
        default=None,
        help="último dia da janela, inclusive (default: hoje em Brasília)",
    )
    args = parser.parse_args(argv)
    if args.dias < 1:
        parser.error("--dias precisa ser >= 1")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL não definida no ambiente", file=sys.stderr)
        return 2
    fim: date = args.ate or datetime.now(FUSO).date()
    inicio = fim - timedelta(days=args.dias - 1)
    relatorio = asyncio.run(_medir(dsn, inicio=inicio, fim=fim))
    print(json.dumps(relatorio, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
