# bucket: defer
"""Tool: get_account_balance - saldo restante do orcamento de conta Google Ads."""

from datetime import date, datetime, timedelta
from typing import Any

from src.google_ads.account_clock import resolve_account_today
from src.google_ads.errors import GoogleAdsFriendlyError
from src.google_ads.queries._common import micros_to_currency
from src.google_ads.queries.overview import gasto_diario_conta_query, saldo_orcamento_conta_query
from src.google_ads.reports import run_report
from src.google_ads.saldo import montar_saldo_google
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_OPERACAO = "get_account_balance"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {
            "type": "string",
            "pattern": "^[0-9]{10}$",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _row_formatter_orcamento(row: Any) -> dict[str, Any]:
    b = row.account_budget
    tipo = b.approved_spending_limit_type.name
    return {
        "tipo_limite": tipo,
        "limite_ajustado_micros": (
            None if tipo == "INFINITE" else int(b.adjusted_spending_limit_micros)
        ),
        "gasto_micros": int(b.amount_served_micros),
        "ajustes_micros": int(b.total_adjustments_micros),
        "inicio": str(b.approved_start_date_time),
        "fim": str(b.approved_end_date_time) or None,
        "tipo_fim": b.approved_end_time_type.name,
        "pendente": bool(b.pending_proposal.account_budget_proposal),
    }


def _row_formatter_gasto(row: Any) -> dict[str, Any]:
    return {
        "data": datetime.strptime(str(row.segments.date), "%Y-%m-%d").date(),
        "custo": micros_to_currency(int(row.metrics.cost_micros)),
    }


@register_tool(
    name="get_account_balance",
    description=(
        "[DEFER] Saldo restante do orçamento de conta de UMA conta Google Ads (uma conta por "
        "chamada). `restante_brl` é o 'Fundos disponíveis' do Faturamento: limite ajustado "
        "menos gasto acumulado. `situacao` tem 6 valores: "
        "com_saldo = dias restantes acima de 7; "
        "acabando = dias restantes até 7; "
        "sem_gasto = há saldo mas não houve gasto nos últimos 7 dias; "
        "esgotada = sem saldo, menos de um dia de gasto ou orçamento encerrado; "
        "sem_teto = orçamento de conta sem limite; "
        "indeterminada = não foi possível calcular (veja `motivo`). "
        "`sem_teto` não tem número e não diz a forma de pagamento (cartão, boleto ou "
        "faturamento mensal). `dias_restantes` = restante ÷ média diária dos 7 dias fechados; "
        "a data de fim do orçamento conta como freio: `trava_primeiro` diz se o que limita é "
        "o 'saldo' ou a 'data_fim'. O valor é aproximado: o gasto atrasa algumas horas "
        "(`aproximado: true`). Se o Google recusar a leitura por autorização (sem permissão de "
        "faturamento ou sem acesso à conta) a resposta vem indeterminada, sem números. "
        "Os campos _brl assumem que a moeda da conta é BRL."
        " filters_applied diz o recorte que a query aplicou."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def get_account_balance(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    hoje: date = await resolve_account_today(customer_id)
    ontem = hoje - timedelta(days=1)
    inicio = ontem - timedelta(days=29)
    gaql_orc, filtros_orc = saldo_orcamento_conta_query()
    gaql_gasto, filtros_gasto = gasto_diario_conta_query(inicio, ontem)
    filters_applied = {"orcamento": filtros_orc, "gasto": filtros_gasto}
    period = {"from": inicio.isoformat(), "to": ontem.isoformat()}
    try:
        orcamentos = await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=gaql_orc,
            row_formatter=_row_formatter_orcamento,
            operation_name=_OPERACAO,
            audit_this_call=True,
        )
    except GoogleAdsFriendlyError as exc:
        if exc.code != "AUTHORIZATION_ERROR":
            raise
        saldo = montar_saldo_google([], {}, hoje=hoje)
        # nada foi medido: nenhum numero pode ir como zero (nao medido nao e zero)
        saldo["motivo"] = (
            "erro de autorização do Google ao ler o orçamento da conta "
            "(sem permissão de faturamento ou sem acesso à conta)"
        )
        saldo["media_diaria_7d_brl"] = None
        return {
            **saldo,
            "customer_id": customer_id,
            "period": period,
            "filters_applied": filters_applied,
        }
    linhas = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=gaql_gasto,
        row_formatter=_row_formatter_gasto,
        operation_name=_OPERACAO,
        audit_this_call=True,
    )
    gastos = {r["data"]: r["custo"] for r in linhas}
    saldo = montar_saldo_google(orcamentos, gastos, hoje=hoje)
    return {
        **saldo,
        "customer_id": customer_id,
        "period": period,
        "filters_applied": filters_applied,
    }
