"""Shared helpers for GAQL query construction."""

from __future__ import annotations

import contextlib
import json
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import structlog

from src.janelas import PRESETS, janela_do_preset
from src.razoes import arredondado as arredondado  # reexport: o ponto de import de ~18 modulos
from src.razoes import percentual as percentual
from src.razoes import razao as razao


class EntradaInvalidaError(ValueError):
    """Erro de ENTRADA de quem chamou, com mensagem escrita para o gestor/LLM.

    O `_error_envelope` do servidor repassa o texto ao cliente MCP; um `ValueError`
    cru segue scrubado como "Erro interno". Levante esta classe so quando a mensagem
    ja e PT-BR, sem SQL/driver/internals, e diz o que mandar no lugar.
    """


class InvalidDateRangeError(EntradaInvalidaError):
    """Periodo pedido que nao da para resolver — erro de ENTRADA de quem chamou.

    O `_error_envelope` do servidor devolve a mensagem ao cliente MCP, entao ela e
    escrita para o LLM se corrigir: em PT-BR, dizendo o que mandar no lugar. Janela
    invertida vinda de preset nao e isto — e bug nosso, `ValueError` de `janelas.py`.
    """


# Os presets e a janela de cada um moram em `src.janelas` (F195): uma regra so para
# o Google e a Meta.
log = structlog.get_logger(__name__)

# `account_today` MUDOU DE CASA em 2026-09-06: vive em `src/clock.py`.
# Ele nunca foi Google-specific — e o gemeo Meta do F141 precisa dele sem
# importar `src.google_ads.*`. Reexportar daqui deixaria dois caminhos de
# import pro mesmo corpo; quem precisa, importa de `src.clock`.


def parse_date_range(arg: str | dict[str, str], *, today: date) -> tuple[date, date]:
    """Resolve a date_range param into (start_date, end_date) inclusive.

    Accepts either a preset string (e.g., 'LAST_7_DAYS') or an explicit
    dict {from: ISO_DATE, to: ISO_DATE}.

    Sprint 3b.20 safety net: if `arg` is a string that looks like a JSON object,
    parse it before applying preset matching. This recovers from cases where
    Claude serialized a dict as a JSON string (relatorio 2026-05-17 finding #1).
    """
    if isinstance(arg, str) and arg.strip().startswith("{"):
        with contextlib.suppress(ValueError):
            arg = json.loads(arg)
        # if parse failed, fall through to preset matching with original string

    if isinstance(arg, dict):
        try:
            start = date.fromisoformat(arg["from"])
            end = date.fromisoformat(arg["to"])
        except (KeyError, ValueError) as e:
            raise InvalidDateRangeError(
                f"Data invalida em start_date/end_date ({e}): use o formato AAAA-MM-DD, "
                "por exemplo 2026-09-01."
            ) from e
        if start > end:
            raise InvalidDateRangeError(
                f"start_date ({start}) e depois de end_date ({end}): o inicio do periodo "
                "tem de ser anterior ou igual ao fim."
            )
        return start, end

    if not isinstance(arg, str):
        raise InvalidDateRangeError(
            f"date_range invalido ({type(arg).__name__}): use um preset "
            f"({', '.join(sorted(PRESETS))}) ou start_date + end_date."
        )

    preset = arg.upper()
    if preset not in PRESETS:
        raise InvalidDateRangeError(
            f"date_range '{preset}' desconhecido. Presets validos: {', '.join(sorted(PRESETS))}; "
            "ou use start_date + end_date (AAAA-MM-DD)."
        )

    # F141: `today` vem do chamador, ja no fuso da conta (`account_today`).
    # Sem default de proposito — esquecer de passar quebra alto, nao cai em UTC.
    return janela_do_preset(preset, today=today)


def resolve_date_window(
    date_range: str | dict[str, str] | None,
    start_date: str | None,
    end_date: str | None,
    *,
    today: date,
) -> tuple[date, date]:
    """Resolve date_range preset OR explicit start_date+end_date pair into (start, end).

    Precedence: if both start_date and end_date are provided, those win over date_range.
    Mismatched pair (only one of start_date/end_date) is rejected.

    Sprint 3b.20: replaces direct parse_date_range calls in tool bodies so that custom
    periods can be expressed via two top-level params (each with explicit `type: "string"`)
    instead of a single composite param without `type`, which caused Claude to serialize
    the dict as a JSON string and break the parser (relatorio 2026-05-17, finding #1).
    """
    if start_date is not None and end_date is None:
        raise InvalidDateRangeError("end_date e obrigatorio quando start_date e informado.")
    if end_date is not None and start_date is None:
        raise InvalidDateRangeError("start_date e obrigatorio quando end_date e informado.")
    if start_date is not None and end_date is not None:
        return parse_date_range({"from": start_date, "to": end_date}, today=today)
    return parse_date_range(date_range if date_range is not None else "LAST_30_DAYS", today=today)


def get_comparison_range(start: date, end: date) -> tuple[date, date]:
    """Given a date range, return the immediately-previous period of equal length.

    Example: for [2026-04-08, 2026-04-14] (7 days), returns [2026-04-01, 2026-04-07].
    """
    period_days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)
    return prev_start, prev_end


def nome_do_enum(valor: Any) -> str:
    """proto-plus IntEnum -> nome; str/int continuam str (mocks de teste).

    `hasattr` e deliberado: o SDK devolve enum com `.name`, os mocks de teste
    passam str/int puros. Unico lugar de `src/` com esse idioma (guard em
    `tests/unit/test_nome_do_enum.py`).
    """
    return str(valor.name) if hasattr(valor, "name") else str(valor)


def gaql_date_clause(start: date, end: date) -> str:
    """Format a GAQL `segments.date BETWEEN '...' AND '...'` clause."""
    return f"segments.date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'"


def janela_aplicada(start: date, end: date) -> dict[str, str]:
    """O `date_range` que `filters_applied` ecoa para a janela de `gaql_date_clause`.

    Mesma forma do F191 (`{"start", "end"}`). Mora ao lado da clausula para que
    quem monta uma monte a outra: o eco derivado da mesma fonte (spec 2026-09-25).
    """
    return {"start": start.isoformat(), "end": end.isoformat()}


# Plural-form keys in sync with resource types Google Ads emits via change_event.
# Compound IDs (e.g., {campaign_id}~{criterion_id}) returned as-is — caller splits if needed.
# Sprint 3b.21: extracted from get_change_history.py for cross-tool reuse.
_RESOURCE_PLURAL_TO_TYPE: dict[str, str] = {
    "campaigns": "campaign",
    "adGroups": "ad_group",
    "adGroupAds": "ad_group_ad",
    "adGroupCriteria": "ad_group_criterion",
    "campaignCriteria": "campaign_criterion",
    "campaignBudgets": "campaign_budget",
    "biddingStrategies": "bidding_strategy",
    "conversionActions": "conversion_action",
    "customerNegativeCriteria": "customer_negative_criterion",
    "assets": "asset",
    "campaignAssets": "campaign_asset",
    "adGroupAssets": "ad_group_asset",
    # F134: faltava a camada de conta. Hoje os 3 call sites descartam o tipo
    # devolvido, entao nao havia defeito vivo — mas a omissao arma o bug para
    # o dia em que alguem consumir o retorno.
    "customerAssets": "customer_asset",
}


def parse_resource_path(path: str) -> tuple[str | None, str | None]:
    """Parse 'customers/{cid}/{resource_plural}/{id}[...]' into (resource_type, id).

    Returns:
      (resource_type, id) when path matches known pattern.
      (None, id) when plural is unknown but id is parseable.
      (None, None) when path is malformed.

    Adding a new resource type? Update `_RESOURCE_PLURAL_TO_TYPE` above.
    """
    parts = path.split("/")
    if len(parts) < 4 or parts[0] != "customers":
        return None, None
    resource_plural = parts[2]
    resource_id = parts[3] if len(parts) > 3 else None
    return _RESOURCE_PLURAL_TO_TYPE.get(resource_plural), resource_id


def micros_to_currency(micros: int | float) -> float:
    """Google Ads stores money in micros (millionths). 1_500_000 micros = R$ 1.50."""
    return round(micros / 1_000_000.0, 2)


def brl_para_micros(valor: float) -> int:
    """BRL -> micros, ARREDONDADO. truncar o produto float de 2.01 da 2_009_999."""
    return round(Decimal(str(valor)) * 1_000_000)


def metrica_opcional(m: Any, campo: str) -> float | None:
    """Metrica `optional` do proto: o valor quando o Google a mandou, `None` quando nao.

    Os `search_*impression_share` sao `optional` (v24): campanha que nao e de pesquisa, ou
    de pesquisa sem impressao, vem SEM o campo — e ler o atributo direto devolve `0.0`, o
    zero falso (medido em 02/10, spec 2026-10-02 §3.2). Presenca no proto-plus e `campo in
    m` (e tambem no protobuf cru, sondado). O fallback por atributo e SO do `SimpleNamespace`
    dos testes: qualquer outro objeto sem `in` levanta, porque `hasattr` seria sempre
    verdadeiro e o zero falso voltaria em silencio (revisao 02/10, M6).
    """
    presente = hasattr(m, campo) if isinstance(m, SimpleNamespace) else campo in m
    return float(getattr(m, campo)) if presente else None


def em_moeda(valor_micros: float | None) -> float | None:
    """`micros_to_currency` que deixa `None` passar."""
    return None if valor_micros is None else micros_to_currency(valor_micros)


def _clausula_e_eco_de_metrica(
    min_cost_brl: float | None,
    min_clicks: int | None,
    min_conversions: float | None,
) -> tuple[str, dict[str, float | int]]:
    """Fonte unica da clausula de metrica e do seu eco: o mesmo ramo escreve a
    clausula e a chave, entao as duas nao descolam por construcao."""
    clauses: list[str] = []
    ecos: dict[str, float | int] = {}
    if min_cost_brl is not None:
        clauses.append(f"AND metrics.cost_micros >= {brl_para_micros(min_cost_brl)}")
        ecos["min_cost_brl"] = min_cost_brl
    if min_clicks is not None:
        clauses.append(f"AND metrics.clicks >= {int(min_clicks)}")
        ecos["min_clicks"] = min_clicks
    if min_conversions is not None:
        clauses.append(f"AND metrics.conversions > {float(min_conversions)}")
        ecos["min_conversions"] = min_conversions
    return " ".join(clauses), ecos


def build_metric_filter_clause(
    min_cost_brl: float | None = None,
    min_clicks: int | None = None,
    min_conversions: float | None = None,
) -> str:
    """Build the optional GAQL WHERE fragment for server-side metric filters.

    Server-side filtering on keyword_view / search_term_view (the metric fields
    are already in both SELECTs). cost_micros and clicks are integers and accept
    `>=`; conversions is a double and GAQL REJECTS `>=` on it — use `>` (strictly
    greater). Validated via validate_gaql on both resources (Onda 3).

    Returns a fragment starting with "AND " (safe to append after an existing
    WHERE clause), or "" when no filter is requested.
    """
    return _clausula_e_eco_de_metrica(min_cost_brl, min_clicks, min_conversions)[0]


def filtros_de_metrica(
    min_cost_brl: float | None = None,
    min_clicks: int | None = None,
    min_conversions: float | None = None,
) -> dict[str, float | int]:
    """O eco de `build_metric_filter_clause`: so os minimos que viraram clausula.

    Chama `_clausula_e_eco_de_metrica`, a MESMA funcao que monta a clausula: o
    mesmo ramo escreve a clausula e a chave do eco, entao as duas nao descolam
    por construcao — nao por um guard que confira depois.
    """
    return _clausula_e_eco_de_metrica(min_cost_brl, min_clicks, min_conversions)[1]


def value_proxy_warning(conversions: float, conversions_value: float) -> str | None:
    """Returns warning string PT-BR if conversions_value == conversions (1:1 placeholder
    tracking), else None.

    Real revenue tracking would have value != count (unless every conversion is
    coincidentally R$ 1.00 — extremely unlikely). 1:1 ratio strong signals that
    conversion action uses default value=1.0 BRL placeholder, making ROAS misleading.

    Sprint 3b.7 (P1b dogfood UX-1 finding).
    """
    if conversions > 0 and conversions == conversions_value:
        return (
            "conversions_value == conversions (1:1 ratio). Tracking provavelmente "
            "sem revenue real — ROAS pode ser misleading."
        )
    return None
