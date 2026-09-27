"""Pure module pra meta_get_account_overview tool (Sprint M.2b).

Zero IO. Date math + Graph response parsing + deltas + warnings.
"""

from datetime import date, datetime, timedelta
from typing import Any

from src.janelas import janela_do_preset
from src.meta_ads.metricas import metricas_da_linha, metricas_sem_linha

# Os campos com variacao no comparativo (sufixo `_pct`). Os nomes sao os do
# contrato (`metricas.py`), os mesmos do trio.
DELTA_CAMPOS = (
    "spend_brl",
    "impressions",
    "clicks",
    "purchases",
    "purchases_value_brl",
    "leads",
    "messaging_conversations_started",
    "purchase_roas",
)


def resolve_meta_date_window(
    preset: str | None,
    start_date: str | None,
    end_date: str | None,
    today: date,
) -> tuple[date, date]:
    """Resolve preset OR (start, end) → (start, end) date tuple.

    Custom (start+end) overrides preset. Default LAST_7_DAYS se ambos None.
    Raises ValueError se inconsistent (apenas um de start/end fornecido) ou preset
    desconhecido.

    F195: o preset sai de `src.janelas`, a mesma regra do Google — `LAST_N_DAYS` sao
    os N dias completos ate ontem, como na propria Meta (`date_preset=last_7d`). A conta
    daqui terminava hoje, com o dia corrente pela metade dentro da janela.
    """
    if start_date and end_date:
        return (date.fromisoformat(start_date), date.fromisoformat(end_date))
    if start_date or end_date:
        raise ValueError("start_date e end_date devem ser fornecidos juntos")
    return janela_do_preset(preset or "LAST_7_DAYS", today=today)


def shift_to_previous_period(start: date, end: date) -> tuple[date, date]:
    """Calculate previous period of same length."""
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    return (prev_start, prev_end)


def parse_insights_response(data: dict[str, Any]) -> dict[str, Any]:
    """Resposta /insights de nivel `account` -> metricas do periodo, pelo contrato.

    Sem linha nenhuma (a Meta nao manda linha zerada: sem entrega, nao vem linha),
    as metricas saem de `metricas_sem_linha` e `sem_dados_no_periodo` e True — o
    que distingue "nao houve entrega" de uma linha medida com zero. E o contrato do
    overview Google (F193), com uma diferenca deliberada: la as conversoes sem linha
    sao 0; aqui os eventos sao None, porque a Meta nao diz se a conta os rastreia
    (spec 2026-09-26, §3.4).
    """
    linhas = data.get("data") or []
    if not linhas:
        return {**metricas_sem_linha(), "sem_dados_no_periodo": True}
    return {**metricas_da_linha(linhas[0]), "sem_dados_no_periodo": False}


def compute_deltas(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, float | None]:
    """Variacao percentual por campo de `DELTA_CAMPOS`, com sufixo `_pct`.

    None quando um dos lados e None (nao medido) ou o anterior e 0 (sem base).
    Campo ausente do dict conta como nao medido — antes contava como 0 e virava
    -100%.
    """
    out: dict[str, float | None] = {}
    for key in DELTA_CAMPOS:
        prev_val = previous.get(key)
        curr_val = current.get(key)
        if prev_val is None or curr_val is None or prev_val == 0:
            out[f"{key}_pct"] = None
        else:
            out[f"{key}_pct"] = round((curr_val - prev_val) / prev_val * 100, 2)
    return out


def build_warnings(
    account_status_label: str,
    token_expires_at: datetime | None,
    now: datetime,
) -> list[str]:
    """Returns lista PT-BR warnings ativos (account_status problema + token <7d)."""
    out: list[str] = []
    if account_status_label != "ATIVO":
        out.append(
            f"account_status={account_status_label} — "
            f"métricas podem estar desatualizadas ou ad serving suspenso. "
            f"Verificar billing/status no Meta Business Suite."
        )
    if token_expires_at is not None:
        days_left = (token_expires_at - now).days
        if days_left < 7:
            iso_date = token_expires_at.date().isoformat()
            out.append(
                f"Token OAuth Meta expira em {days_left} dias ({iso_date}). "
                f"Reconectar via /admin → 'Conectar Meta' pra evitar interrupção das tools."
            )
    return out
