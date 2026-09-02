"""GAQL builder for the change_event resource (used by get_change_history tool).

F46 (Sprint 3b.34 fix): Google GAQL interpreta `BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'`
em campo TIMESTAMP (change_event.change_date_time) como `>= 'YYYY-MM-DD 00:00:00'
AND <= 'YYYY-MM-DD 00:00:00'` — midnight start-of-day exclusive em ambos extremos.
Resultado pré-fix: single-day window retornava 0 rows silenciosamente; multi-day
window excluía changes do end_date depois do meio-dia. Fix: append `timedelta(days=1)`
ao end_date antes do isoformat — Google passa a interpretar como `<= midnight do
dia seguinte`, capturando o dia inteiro inclusive. Empirically validated em Sprint
3b.33 T3 (Pedro Vytor cluster 20/05 10:12-10:13 retorna em window 19→20+1=21).
Bug família: design-gap-via-Google-API-semantics. Affects: get_change_history,
get_negative_keywords_audit (via negative_criterion_creations_query), detect_drift.
"""

from datetime import date, timedelta

from src.google_ads.queries._gaql import gaql_escape, gaql_in_list


class RangeTooWideError(ValueError):
    """Raised when the requested date_range exceeds the 30-day API limit."""


# Google Ads change_event has a documented ~30-day retention.
# Empirically (smoke 2026-05-11) the `DURING LAST_30_DAYS` GAQL preset
# can hit "too old" depending on edge timing; our path uses explicit
# BETWEEN dates which has worked at exactly 30 days. If the API tightens
# further, drop this to 29 and resolve LAST_30_DAYS in parse_date_range
# accordingly, OR translate Google's "too old" error to a friendly
# PT-BR retry hint.
_MAX_DAYS = 30


# Espelha _RETENTION_SAFETY_DAYS do get_change_history: a retencao do
# change_event e ~30 dias e o Google recusa start alem disso, entao a sonda
# varre 28 pra ter margem contra drift de UTC.
_RETENTION_SAFETY_DAYS_SONDA = 28


def _format_change_date_between(start: date, end: date) -> str:
    """Format change_event.change_date_time BETWEEN clause with F46-fix end+1 day.

    Google interprets date-string in BETWEEN as midnight 00:00:00. Without the +1 day,
    single-day windows return empty and multi-day windows exclude changes from end_date
    after midnight. This helper centralizes the workaround across both builders so the
    fix is applied consistently.
    """
    end_inclusive = end + timedelta(days=1)
    return (
        f"change_event.change_date_time BETWEEN "
        f"'{start.isoformat()}' AND '{end_inclusive.isoformat()}'"
    )


def _quote_literal(s: str) -> str:
    """Escape do conteúdo de um string literal GAQL (F87 — barra invertida, não doubling)."""
    return gaql_escape(s)


def _format_in_clause(values: list[str]) -> str:
    """Format ('val1', 'val2', ...) for a GAQL IN clause.

    F87: `user_emails` chega aqui como texto livre — o `format: "email"` do schema
    NÃO é enforced, porque `jsonschema.validate` roda sem `format_checker`.
    """
    return gaql_in_list(values)


def change_event_frontier_query(*, today: date) -> str:
    """F131: GAQL da fronteira de indexacao — o evento mais NOVO da conta.

    Deliberadamente SEM os filtros do usuario. Uma sonda que herdasse
    `resource_types` responderia vazio pelo mesmo silencio que ela existe para
    medir: conta sem historico daquele tipo pareceria "nao indexado". A sonda
    responde "ate quando esta indexado nesta CONTA", nao "no seu recorte" — o
    recorte sai de graca do `max` das linhas que a query principal ja devolveu.

    **A sonda NAO aceita a janela do chamador.** Ela deriva a propria, sobre a
    retencao inteira. A primeira versao recebia `start`/`end` e o call site
    passava a janela do usuario — entao `account_frontier` mudava conforme o
    que se perguntava, e uma janela terminando em dia sem write saia como
    `atrasado` com a conta indexada em dia. Warning que dispara em condicao
    normal treina a ignorar o warning, que e o oposto do que o F131 constroi.
    Tirar o parametro fecha a classe: nao ha por onde herdar.

    Janela propria = `today-28 .. today+1`. O 28 espelha o
    `_RETENTION_SAFETY_DAYS` do get_change_history (retencao de 30 dias com
    margem contra drift de UTC); o +1 e o F46, que exige end+1 porque o
    `BETWEEN` do Google trata data como midnight start-of-day.

    Predicado de data e OBRIGATORIO aqui: sem ele a API recusa com "missing
    filters on change_event.change_date_time or is filtering with an infinite
    range" (probado 2026-09-02). Por isso a sonda nao pode simplesmente omitir
    a clausula — ela tem que ter uma janela propria, larga.

    `LIMIT` tambem e obrigatorio: "Change event requests must specify a LIMIT
    in query and LIMIT should be less than or equal to 10k".
    """
    inicio = today - timedelta(days=_RETENTION_SAFETY_DAYS_SONDA)
    return (
        "SELECT change_event.change_date_time "
        "FROM change_event "
        f"WHERE {_format_change_date_between(inicio, today)} "
        "ORDER BY change_event.change_date_time DESC "
        "LIMIT 1"
    )


def change_history_query(
    *,
    start: date,
    end: date,
    resource_types: list[str] | None,
    operation_types: list[str] | None,
    user_emails: list[str] | None,
    client_types: list[str] | None,
    limit: int,
) -> str:
    """Build the GAQL for fetching change_event rows with optional filters.

    Raises RangeTooWideError if (end - start) > 30 days.

    All filter args, when provided, must be non-empty lists; pass None to omit.
    """
    range_days = (end - start).days + 1
    if range_days > _MAX_DAYS:
        raise RangeTooWideError(
            f"Janela maxima de {_MAX_DAYS} dias para historico de mudancas — "
            f"recebido {range_days} dias. Limite da API do Google Ads."
        )

    where: list[str] = [_format_change_date_between(start, end)]

    if resource_types:
        where.append(f"change_event.change_resource_type IN {_format_in_clause(resource_types)}")
    if operation_types:
        where.append(
            f"change_event.resource_change_operation IN {_format_in_clause(operation_types)}"
        )
    if user_emails:
        where.append(f"change_event.user_email IN {_format_in_clause(user_emails)}")
    if client_types:
        where.append(f"change_event.client_type IN {_format_in_clause(client_types)}")

    where_clause = " AND ".join(where)

    return f"""
        SELECT
          change_event.change_date_time,
          change_event.user_email,
          change_event.client_type,
          change_event.change_resource_type,
          change_event.change_resource_name,
          change_event.resource_change_operation,
          change_event.changed_fields,
          change_event.campaign,
          change_event.ad_group
        FROM change_event
        WHERE {where_clause}
        ORDER BY change_event.change_date_time DESC
        LIMIT {limit}
    """.strip()


def negative_criterion_creations_query(*, start: date, end: date) -> str:
    """Build GAQL for fetching campaign_criterion CREATE events.

    Used by get_negative_keywords_audit to enrich each negative keyword with
    its created_date + added_by_email. Filters to CAMPAIGN_CRITERION resource
    type + CREATE operation. Sprint 3b.21.

    Raises RangeTooWideError if range exceeds ~30 days (change_event API limit).
    """
    range_days = (end - start).days + 1
    if range_days > _MAX_DAYS:
        raise RangeTooWideError(
            f"Janela maxima de {_MAX_DAYS} dias para historico de mudancas — "
            f"recebido {range_days} dias. Limite da API do Google Ads."
        )

    return f"""
        SELECT
          change_event.change_resource_name,
          change_event.change_date_time,
          change_event.user_email
        FROM change_event
        WHERE {_format_change_date_between(start, end)}
          AND change_event.change_resource_type = 'CAMPAIGN_CRITERION'
          AND change_event.resource_change_operation = 'CREATE'
        ORDER BY change_event.change_date_time DESC
        LIMIT 10000
    """.strip()
