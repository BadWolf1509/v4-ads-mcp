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
from src.meta_ads.pacing import orcamento_total, projetar, ritmo_de
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
    "`total.gasto_fechado_ativas_brl` soma SÓ as campanhas ativas; o gasto do mês de campanhas "
    "fora da lista (pausadas, encerradas) vem em `total.gasto_fora_do_escopo_brl` (null se a "
    "leitura foi truncada ou no dia 1), então some os dois para o gasto da conta. Conjunto ou "
    "campanha ACTIVE com data final (`end_time`/`stop_time`) já vencida é excluído e contado "
    "em `excluidos_por_data_final`. Orçamento ilegível não esconde o gasto: `gasto_fechado_brl` "
    "e a projeção seguem na linha. "
    "`truncated: true` = lista de campanhas, conjuntos ou gasto incompleta: o `total` vem "
    "null, porque soma parcial não é total. Com orçamento vitalício na mistura, "
    "`total.media_diaria_brl` sai do gasto, mas orçamento e projeção do total vêm null: uma "
    "projeção mensal somada só valeria para parte das campanhas. Quando algum campo do total "
    "vem null, `total_motivo` diz por quê. Só contas em BRL. Somente leitura. "
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
        return {
            "diario": None,
            "vitalicio": None,
            "vitalicio_em_conjuntos": True,
            "em": "conjuntos",
        }
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
        lifetime_budget=orc["vitalicio"],
        gasto_fechado=gasto,
        dias_fechados=dias_fechados,
        dias_no_mes=dias_no_mes,
    )
    tipo = ritmo["tipo_orcamento"]
    observacao = ritmo["observacao"]
    if orc.get(
        "vitalicio_em_conjuntos"
    ):  # vitalicio nos conjuntos: nao ha valor unico para mostrar
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
        "orcamento_vitalicio_brl": orc["vitalicio"],
        "orcamento_mensal_brl": ritmo["orcamento_mensal_brl"],
        "gasto_fechado_brl": gasto,
        "media_diaria_brl": ritmo["media_diaria"],
        "projecao_mensal_brl": ritmo["projecao"],
        "gasto_pct_do_orcamento_mensal": ritmo["gasto_pct_do_orcamento_mensal"],
        "projecao_vs_orcamento_pct": ritmo["projecao_vs_orcamento_pct"],
        "observacao": observacao,
    }


def _total(
    linhas: list[dict[str, Any]],
    *,
    truncated: bool,
    gasto_fora: float | None,
    dias_fechados: int,
    dias_no_mes: int,
) -> dict[str, Any]:
    """Total das campanhas ATIVAS; soma so quando a lista esta completa e cada parcela legivel.

    `gasto_fora_do_escopo_brl` e o gasto do mes de campanhas que nao estao na lista (pausadas,
    encerradas): sem ele o total das ativas se leria como o gasto da conta.
    """
    total: dict[str, Any] = {
        "gasto_fechado_ativas_brl": None,
        "gasto_fora_do_escopo_brl": gasto_fora,
        "orcamento_diario_brl": None,
        "orcamento_mensal_brl": None,
        "media_diaria_brl": None,
        "projecao_mensal_brl": None,
        "projecao_vs_orcamento_pct": None,
    }
    if truncated or dias_fechados == 0:
        return total
    if not linhas:
        total["gasto_fechado_ativas_brl"] = 0.0  # nenhuma ativa, lista completa
        return total
    gastos = [ln["gasto_fechado_brl"] for ln in linhas]
    orcs = [ln["orcamento_diario_brl"] for ln in linhas]
    gasto = None if any(g is None for g in gastos) else round(sum(gastos), 2)
    orcamento = None if any(o is None for o in orcs) else round(sum(orcs), 2)
    projetavel = all(ln["projecao_mensal_brl"] is not None for ln in linhas)
    media = projetar(gasto_fechado=gasto, dias_fechados=dias_fechados, dias_no_mes=dias_no_mes)
    ritmo = ritmo_de(
        daily_budget=orcamento,
        lifetime_budget=None,
        gasto_fechado=gasto if projetavel else None,
        dias_fechados=dias_fechados,
        dias_no_mes=dias_no_mes,
    )
    total.update(
        {
            "gasto_fechado_ativas_brl": gasto,
            "orcamento_diario_brl": orcamento,
            "orcamento_mensal_brl": ritmo["orcamento_mensal_brl"],
            "media_diaria_brl": media["media_diaria"],
            "projecao_mensal_brl": ritmo["projecao"],
            "projecao_vs_orcamento_pct": ritmo["projecao_vs_orcamento_pct"],
        }
    )
    return total


def _motivo_do_total(
    linhas: list[dict[str, Any]], *, truncated: bool, dias_fechados: int
) -> str | None:
    """Por que algum campo do total vem null, ou `None` quando nada precisa de explicacao."""
    if truncated:
        return "Leitura incompleta: soma parcial não é total, então o total vem null."
    if dias_fechados == 0:
        return (
            "Ainda não há dia fechado no mês: gasto, orçamento, média e projeção do total vêm null."
        )
    if not linhas:
        return "Nenhuma campanha ativa: não há orçamento, média nem projeção a somar."
    n = len(linhas)
    vitalicias = sum(ln["tipo_orcamento"] == "vitalicio" for ln in linhas)
    sem_gasto = sum(ln["gasto_fechado_brl"] is None for ln in linhas)
    ilegiveis = sum(ln["tipo_orcamento"] is None for ln in linhas)
    partes: list[str] = []
    if vitalicias:
        partes.append(
            f"{vitalicias} de {n} campanha(s) com orçamento vitalício: ele não tem valor "
            "diário nem projeção mensal, então orçamento e projeção do total vêm null."
        )
    if sem_gasto:
        partes.append(
            f"{sem_gasto} de {n} campanha(s) sem gasto reportado: gasto, média e projeção do "
            "total vêm null."
        )
    if ilegiveis:
        partes.append(
            f"{ilegiveis} de {n} campanha(s) com orçamento não legível: o orçamento do total "
            "vem null."
        )
    return " ".join(partes) or None


def _encerrada(linha: dict[str, Any], campo: str, hoje: date) -> bool:
    """Data final ja vencida: a entidade pode seguir ACTIVE sem entregar nem orcar."""
    valor = linha.get(campo)
    if not isinstance(valor, str) or len(valor) < 10:
        return False
    try:
        return date.fromisoformat(valor[:10]) < hoje
    except ValueError:
        return False


@register_tool(
    name=_OPERACAO,
    description=_DESCRIPTION,
    input_schema=_SCHEMA,
    bucket="defer",
)
async def meta_get_budget_pacing(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    ad_account_id = args["ad_account_id"]
    try:
        hoje: date = await resolve_meta_account_today(ad_account_id)
        dias_no_mes, dias_fechados, dias_restantes = calendario_do_mes(hoje)
        inicio = hoje.replace(day=1)
        ontem = hoje - timedelta(days=1)
        janela = {"from": inicio.isoformat(), "to": ontem.isoformat()} if dias_fechados else None
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
            ctx, ad_account_id, "campaign", "ACTIVE", _LIMITE_ENTIDADES, operacao=_OPERACAO
        )
        conjuntos, adset_trunc = await listar_entidades(
            ctx, ad_account_id, "adset", "ACTIVE", _LIMITE_ENTIDADES, operacao=_OPERACAO
        )
        # A Graph ignora filtro invalido em silencio: confere o status aqui tambem.
        campanhas = [c for c in campanhas if c.get("effective_status") == "ACTIVE"]
        conjuntos = [c for c in conjuntos if c.get("effective_status") == "ACTIVE"]
        n_camp_total, n_adset_total = len(campanhas), len(conjuntos)
        campanhas = [c for c in campanhas if not _encerrada(c, "stop_time", hoje)]
        conjuntos = [c for c in conjuntos if not _encerrada(c, "end_time", hoje)]
        n_camp_enc = n_camp_total - len(campanhas)
        n_adset_enc = n_adset_total - len(conjuntos)
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
    ativas = {c["id"] for c in campanhas}
    fora = [v for k, v in gastos.items() if k not in ativas]
    gasto_fora: float | None = None
    if dias_fechados and not insights_trunc and not camp_trunc:
        valores = [v for v in fora if v is not None]
        gasto_fora = round(sum(valores), 2) if len(valores) == len(fora) else None
    motivo_total = _motivo_do_total(linhas, truncated=truncated, dias_fechados=dias_fechados)
    resposta: dict[str, Any] = {
        "status": "success",
        "ad_account_id": ad_account_id,
        "as_of": hoje.isoformat(),
        "date_range": janela,
        "inclui_dia_corrente": False,
        "dias_no_mes": dias_no_mes,
        "dias_fechados": dias_fechados,
        "dias_restantes": dias_restantes,
        "escopo": (
            f"{_ESCOPO} Excluídos por data final já vencida, apesar de ACTIVE: {n_camp_enc} "
            f"campanha(s) (stop_time) e {n_adset_enc} conjunto(s) (end_time)."
        ),
        "excluidos_por_data_final": {"campanhas": n_camp_enc, "conjuntos": n_adset_enc},
        "truncated": truncated,
        "campaigns": linhas,
        "total": _total(
            linhas,
            truncated=truncated,
            gasto_fora=gasto_fora,
            dias_fechados=dias_fechados,
            dias_no_mes=dias_no_mes,
        ),
    }
    if motivo_total:
        resposta["total_motivo"] = motivo_total
    if truncated:
        resposta["truncated_hint"] = (
            "Leitura incompleta (campanhas, conjuntos ou gasto passaram do limite): "
            "o total não é calculado e os valores afetados vêm null."
        )
    return resposta
