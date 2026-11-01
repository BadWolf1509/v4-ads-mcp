# bucket: defer
"""Tool: meta_get_budget_pacing - gasto do mes contra o orcamento e projecao, por campanha Meta."""

from datetime import date, timedelta
from typing import Any

from src.janelas import calendario_do_mes
from src.mcp.context import get_current
from src.mcp.tools._meta_common import meta_error_message
from src.mcp.tools._registry import register_tool
from src.meta_ads.account_clock import resolve_meta_account_today
from src.meta_ads.entidades import listar_entidades
from src.meta_ads.insights import build_insights_call
from src.meta_ads.metricas import CONTRATO_NA_DESCRIPTION, metricas_da_linha
from src.meta_ads.pacing import orcamento_total, ritmo_de
from src.meta_ads.reports import run_meta_graph_get

_OPERACAO = "meta_get_budget_pacing"
_LIMITE_ENTIDADES = 500
_PAGINA_INSIGHTS = 100
_PAGINAS_INSIGHTS = 5

_ESCOPO = (
    "Só entidades ATIVAS (effective_status ACTIVE) entram no orçamento; campanhas e "
    "conjuntos pausados ficam de fora. O gasto é o das campanhas ativas nos dias "
    "fechados do mês, sem o dia corrente."
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ad_account_id": {
            "type": "string",
            "pattern": r"^act_\d+$",
            "description": (
                "Meta ad account ID (formato act_<numeric>). "
                "Use meta_list_my_ad_accounts pra descobrir IDs disponíveis."
            ),
        },
    },
    "required": ["ad_account_id"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[DEFER] Ritmo de gasto do mês contra o orçamento, por campanha ATIVA de UMA conta Meta "
    "(uma conta por chamada). `gasto_fechado_brl` é o gasto do mês até ONTEM "
    "(`date_range`): o dia corrente, parcial, fica fora. `media_diaria_brl` = gasto ÷ dias "
    "fechados; `projecao_mensal_brl` = média × dias do mês; no dia 1 não há dia fechado e "
    "gasto, média e projeção vêm null. Orçamento: a campanha com orçamento próprio vale uma "
    "vez só (`orcamento_em: 'campanha'`) e os conjuntos dela não são somados; sem orçamento "
    "na campanha, soma os conjuntos ativos (`orcamento_em: 'conjuntos'`) e, se algum "
    "conjunto não tem orçamento legível, o orçamento da campanha vem null. Orçamento "
    "VITALÍCIO (`tipo_orcamento: 'vitalicio'`) não tem projeção mensal (null) e a linha "
    "avisa. Só entidades ativas contam (`escopo`); pausadas ficam fora. Campanha ativa sem "
    "linha de gasto no período gastou zero; gasto que a Meta não reportou vem null. "
    "`truncated: true` = lista de campanhas, conjuntos ou gasto incompleta: o `total` vem "
    "null, porque soma parcial não é total. Só contas em BRL. Somente leitura. "
    "Do contrato de métricas da Meta, só `spend_brl` é usado aqui: " + CONTRATO_NA_DESCRIPTION
)


def _orcamento_da_campanha(
    camp: dict[str, Any], conjuntos: list[dict[str, Any]], *, conjuntos_truncados: bool
) -> dict[str, Any]:
    """Orcamento diario efetivo e de onde veio. Vitalicio nao vira diario."""
    daily, lifetime = camp.get("daily_budget_brl"), camp.get("lifetime_budget_brl")
    if daily is not None:
        return {"diario": daily, "vitalicio": None, "em": "campanha"}
    if lifetime is not None:
        return {"diario": None, "vitalicio": lifetime, "em": "campanha"}
    if conjuntos_truncados or not conjuntos:
        return {"diario": None, "vitalicio": None, "em": "conjuntos"}
    ilegivel = any(
        c.get("daily_budget_brl") is None and c.get("lifetime_budget_brl") is None
        for c in conjuntos
    )
    if ilegivel:
        return {"diario": None, "vitalicio": None, "em": "conjuntos"}
    if any(c.get("lifetime_budget_brl") is not None for c in conjuntos):
        return {"diario": None, "vitalicio": True, "em": "conjuntos"}
    return {
        "diario": orcamento_total(
            campanha=None, conjuntos=[c.get("daily_budget_brl") for c in conjuntos]
        ),
        "vitalicio": None,
        "em": "conjuntos",
    }


def _linha(
    camp: dict[str, Any],
    conjuntos: list[dict[str, Any]],
    gasto: float | None,
    *,
    conjuntos_truncados: bool,
    dias_fechados: int,
    dias_no_mes: int,
) -> dict[str, Any]:
    orc = _orcamento_da_campanha(camp, conjuntos, conjuntos_truncados=conjuntos_truncados)
    ritmo = ritmo_de(
        daily_budget=orc["diario"],
        lifetime_budget=orc["vitalicio"] if isinstance(orc["vitalicio"], float) else None,
        gasto_fechado=gasto,
        dias_fechados=dias_fechados,
        dias_no_mes=dias_no_mes,
    )
    tipo = ritmo["tipo_orcamento"]
    observacao = ritmo["observacao"]
    if orc["vitalicio"] is True:  # vitalicio nos conjuntos: nao ha valor unico para mostrar
        tipo = "vitalicio"
        observacao = "conjunto com orçamento vitalício: sem projeção mensal"
        ritmo = {**ritmo, "projecao": None, "projecao_vs_orcamento_pct": None}
    elif orc["diario"] is None and orc["vitalicio"] is None:
        observacao = (
            "conjuntos ativos incompletos na leitura: orçamento não calculado"
            if conjuntos_truncados
            else "orçamento não legível (conjunto sem orçamento ou sem conjunto ativo)"
        )
    return {
        "campaign_id": camp["id"],
        "campaign_name": camp.get("name"),
        "tipo_orcamento": tipo,
        "orcamento_em": orc["em"],
        "orcamento_diario_brl": orc["diario"],
        "orcamento_vitalicio_brl": orc["vitalicio"]
        if isinstance(orc["vitalicio"], float)
        else None,
        "orcamento_mensal_brl": ritmo["orcamento_mensal_brl"],
        "gasto_fechado_brl": gasto,
        "media_diaria_brl": ritmo["media_diaria"],
        "projecao_mensal_brl": ritmo["projecao"],
        "gasto_pct_do_orcamento_mensal": ritmo["gasto_pct_do_orcamento_mensal"],
        "projecao_vs_orcamento_pct": ritmo["projecao_vs_orcamento_pct"],
        "observacao": observacao,
    }


def _total(
    linhas: list[dict[str, Any]], *, truncated: bool, dias_fechados: int, dias_no_mes: int
) -> dict[str, Any]:
    """Soma so quando a lista esta completa e cada parcela e legivel."""
    vazio: dict[str, Any] = {
        "gasto_fechado_brl": None,
        "orcamento_diario_brl": None,
        "orcamento_mensal_brl": None,
        "media_diaria_brl": None,
        "projecao_mensal_brl": None,
        "projecao_vs_orcamento_pct": None,
    }
    if truncated or not linhas:
        return vazio
    gastos = [ln["gasto_fechado_brl"] for ln in linhas]
    orcs = [ln["orcamento_diario_brl"] for ln in linhas]
    gasto = None if any(g is None for g in gastos) else round(sum(gastos), 2)
    orcamento = None if any(o is None for o in orcs) else round(sum(orcs), 2)
    projetavel = all(ln["projecao_mensal_brl"] is not None for ln in linhas)
    ritmo = ritmo_de(
        daily_budget=orcamento,
        lifetime_budget=None,
        gasto_fechado=gasto if projetavel else None,
        dias_fechados=dias_fechados,
        dias_no_mes=dias_no_mes,
    )
    return {
        "gasto_fechado_brl": gasto,
        "orcamento_diario_brl": orcamento,
        "orcamento_mensal_brl": ritmo["orcamento_mensal_brl"],
        "media_diaria_brl": ritmo["media_diaria"],
        "projecao_mensal_brl": ritmo["projecao"],
        "projecao_vs_orcamento_pct": ritmo["projecao_vs_orcamento_pct"],
    }


@register_tool(
    name=_OPERACAO,
    description=_DESCRIPTION,
    input_schema=_SCHEMA,
    bucket="defer",
)
async def meta_get_budget_pacing(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    ad_account_id = args["ad_account_id"]
    hoje: date = await resolve_meta_account_today(ad_account_id)
    dias_no_mes, dias_fechados, dias_restantes = calendario_do_mes(hoje)
    inicio = hoje.replace(day=1)
    ontem = hoje - timedelta(days=1)
    janela = {"from": inicio.isoformat(), "to": ontem.isoformat()} if dias_fechados else None
    try:
        conta = await run_meta_graph_get(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            ad_account_id=ad_account_id,
            edge=f"/{ad_account_id}",
            params={"fields": "currency"},
            operation_name=_OPERACAO,
            estimated_calls=1,
            audit_this_call=True,
            params_summary={"ad_account_id": ad_account_id, "call": "moeda"},
        )
        moeda = conta.get("currency")
        if moeda != "BRL":
            return {
                "status": "error",
                "error_message": (
                    f"conta Meta em moeda {moeda!r}: o pacing só é calculado para contas em BRL"
                ),
            }
        campanhas, camp_trunc = await listar_entidades(
            ctx, ad_account_id, "campaign", "ACTIVE", _LIMITE_ENTIDADES
        )
        conjuntos, adset_trunc = await listar_entidades(
            ctx, ad_account_id, "adset", "ACTIVE", _LIMITE_ENTIDADES
        )
        gastos: dict[str, float | None] = {}
        insights_trunc = False
        if dias_fechados:
            edge, params = build_insights_call(
                level="campaign",
                ad_account_id=ad_account_id,
                start=inicio,
                end=ontem,
                limit=_PAGINA_INSIGHTS,
            )
            resp = await run_meta_graph_get(
                manager_id=ctx.manager_id,
                session_id=ctx.session_id,
                ad_account_id=ad_account_id,
                edge=edge,
                params=params,
                operation_name=_OPERACAO,
                estimated_calls=_PAGINAS_INSIGHTS,
                max_pages=_PAGINAS_INSIGHTS,
                audit_this_call=True,
                params_summary={
                    "ad_account_id": ad_account_id,
                    "call": "gasto_mes",
                    "start": inicio.isoformat(),
                    "end": ontem.isoformat(),
                },
            )
            insights_trunc = bool((resp.get("paging") or {}).get("next"))
            for linha in resp.get("data") or []:
                gastos[str(linha.get("campaign_id"))] = metricas_da_linha(linha)["spend_brl"]
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error_message": meta_error_message(e)}

    por_campanha: dict[str, list[dict[str, Any]]] = {}
    for c in conjuntos:
        por_campanha.setdefault(str(c.get("campaign_id")), []).append(c)

    linhas: list[dict[str, Any]] = []
    for camp in campanhas:
        gasto: float | None
        if not dias_fechados:
            gasto = None
        elif camp["id"] in gastos:
            gasto = gastos[camp["id"]]
        elif insights_trunc:
            gasto = None  # ausente numa lista cortada nao prova gasto zero
        else:
            gasto = 0.0  # a Meta nao manda linha sem entrega
        linhas.append(
            _linha(
                camp,
                por_campanha.get(camp["id"], []),
                gasto,
                conjuntos_truncados=adset_trunc,
                dias_fechados=dias_fechados,
                dias_no_mes=dias_no_mes,
            )
        )
    linhas.sort(key=lambda ln: -(ln["gasto_fechado_brl"] or 0.0))
    truncated = camp_trunc or adset_trunc or insights_trunc
    resposta: dict[str, Any] = {
        "status": "success",
        "ad_account_id": ad_account_id,
        "as_of": hoje.isoformat(),
        "date_range": janela,
        "inclui_dia_corrente": False,
        "dias_no_mes": dias_no_mes,
        "dias_fechados": dias_fechados,
        "dias_restantes": dias_restantes,
        "escopo": _ESCOPO,
        "truncated": truncated,
        "campaigns": linhas,
        "total": _total(
            linhas, truncated=truncated, dias_fechados=dias_fechados, dias_no_mes=dias_no_mes
        ),
    }
    if truncated:
        resposta["truncated_hint"] = (
            "Leitura incompleta (campanhas, conjuntos ou gasto passaram do limite): "
            "o total não é calculado e os valores afetados vêm null."
        )
    return resposta
