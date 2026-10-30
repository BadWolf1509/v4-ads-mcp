# bucket: defer
"""Tool: meta_get_account_balance - saldo restante de uma conta Meta Ads."""

from datetime import date, timedelta
from typing import Any

from src.mcp.context import get_current
from src.mcp.tools._meta_common import meta_error_message
from src.mcp.tools._registry import register_tool
from src.meta_ads.account_clock import resolve_meta_account_today
from src.meta_ads.insights import build_insights_call
from src.meta_ads.metricas import CONTRATO_NA_DESCRIPTION, metricas_da_linha
from src.meta_ads.reports import run_meta_graph_get
from src.meta_ads.saldo import montar_saldo_meta

_OPERACAO = "meta_get_account_balance"

_CAMPOS_CONTA = (
    "name,account_status,disable_reason,is_prepay_account,spend_cap,amount_spent,"
    "balance,currency,funding_source_details"
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
    "[DEFER] Saldo restante de UMA conta Meta Ads (uma conta por chamada). A conta tem dois "
    "freios: o saldo pré-pago (`freio_saldo_brl`, só em conta pré-paga) e o limite de gastos "
    "(`freio_limite_brl`, quando há teto); `restante_brl` é o menor dos dois e "
    "`trava_primeiro` diz qual limita ('saldo_prepago' ou 'limite_de_gastos'). O saldo "
    "pré-pago é lido do texto de `funding_source_details` da Meta; se o formato mudar, ele "
    "vem `null` com o texto original em `saldo_prepago_texto` e situação indeterminada. "
    "Em conta pós-paga, `a_faturar_brl` é o que ainda será cobrado, não é saldo. Cupons "
    "ficam fora do restante e aparecem em `cupons`. Conta com status diferente de ativa "
    "traz um aviso em `avisos`: os anúncios podem estar parados independente do saldo. "
    "`status_conta_label` e `disable_reason_label` dão o status e o motivo de bloqueio em texto. "
    "`dias_restantes` = restante ÷ média diária dos 7 dias fechados; dia sem entrega conta "
    "como zero. `situacao` tem 6 valores: "
    "com_saldo = dias restantes acima de 7; "
    "acabando = dias restantes até 7; "
    "sem_gasto = há saldo mas não houve gasto nos últimos 7 dias; "
    "esgotada = sem saldo ou menos de um dia de gasto; "
    "sem_teto = pós-paga sem limite de gastos: não para por falta de saldo, mas pode parar "
    "por status de pagamento; "
    "indeterminada = não foi possível calcular (veja `motivo`), inclusive saldo pré-pago "
    "ilegível. O valor é aproximado (`aproximado: true`). Só contas em BRL. "
    "Do contrato de métricas da Meta, só `spend_brl` é usado aqui: " + CONTRATO_NA_DESCRIPTION
)


@register_tool(
    name=_OPERACAO,
    description=_DESCRIPTION,
    input_schema=_SCHEMA,
    bucket="defer",
)
async def meta_get_account_balance(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    ad_account_id = args["ad_account_id"]
    hoje: date = await resolve_meta_account_today(ad_account_id)
    ontem = hoje - timedelta(days=1)
    inicio = ontem - timedelta(days=29)
    edge_insights, params_insights = build_insights_call(
        level="account",
        ad_account_id=ad_account_id,
        start=inicio,
        end=ontem,
        limit=40,
        time_increment=1,
    )
    resumo = {
        "ad_account_id": ad_account_id,
        "start": inicio.isoformat(),
        "end": ontem.isoformat(),
    }
    try:
        conta = await run_meta_graph_get(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            ad_account_id=ad_account_id,
            edge=f"/{ad_account_id}",
            params={"fields": _CAMPOS_CONTA},
            operation_name=_OPERACAO,
            estimated_calls=1,
            audit_this_call=True,
            params_summary={**resumo, "call": "conta"},
        )
        insights = await run_meta_graph_get(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            ad_account_id=ad_account_id,
            edge=edge_insights,
            params=params_insights,
            operation_name=_OPERACAO,
            estimated_calls=1,
            audit_this_call=True,
            params_summary={**resumo, "call": "gasto_diario"},
        )
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error_message": meta_error_message(e)}

    gastos: dict[date, float] = {}
    try:
        for linha in insights.get("data") or []:
            gasto = metricas_da_linha(linha)["spend_brl"]
            # spend_brl None = a Meta nao reportou gasto: conta como sem entrega no dia, igual
            # ao dia ausente (que o calculo trata como zero).
            if gasto is not None:
                gastos[date.fromisoformat(linha["date_start"])] = float(gasto)
        saldo = montar_saldo_meta(conta, gastos, hoje=hoje)
    except KeyError as e:
        return {
            "status": "error",
            "error_message": f"resposta da Meta sem o campo {e.args[0]!r}: saldo não calculado",
        }
    except ValueError as e:
        return {"status": "error", "error_message": str(e)}
    return {
        "status": "success",
        **saldo,
        "ad_account_id": ad_account_id,
        "period": {"from": inicio.isoformat(), "to": ontem.isoformat()},
    }
