# Sprint 3b.36 — `audit_zombie_keywords` Design Doc

**Date:** 2026-05-21
**Sprint:** 3b.36 (56ª MCP tool)
**ICE:** 315 (#11 backlog dogfood 2026-05-19 cleanup massivo MO-JP)
**Author:** Wellington Ribeiro + Claude (brainstorming-driven)

---

## Context

Workflow V4 recurring "cleanup massivo" descoberto em dogfood 2026-05-19 MO-JP: gestor periodicamente identifica keywords ENABLED mas sem activity (impressions=0 + clicks=0) em window de N dias, pausa/remove pra reduzir waste. Workflow manual atual:
1. `get_keyword_performance(date_range=LAST_30_DAYS)` retorna TODAS keywords com metrics
2. Mental filter por impressions=0 + clicks=0
3. Decisão de pause/remove

`audit_zombie_keywords` consolida workflow em **1 tool call** retornando lista filtrada + agrupada por ad_group.

## Use case primário V0 (cravado em brainstorming)

**Cleanup massivo recurring:** Detectar keywords ENABLED com zero activity (impressions=0 AND clicks=0) em window LAST_30_DAYS (default). Output flat list agrupada por ad_group_name ASC. Pre-cleanup decision tool — Wellington decide pause/remove com base no output.

## Design decisions cravadas (brainstorming 3 perguntas)

| Decisão | Escolha |
|---|---|
| **Definição zombie V0** | `impressions=0 AND clicks=0` (pure waste, máximo confidence) |
| **Window default** | `LAST_30_DAYS` (preset OR custom start/end_date) |
| **Output ordering** | `ad_group_name ASC, keyword_text ASC` (scannable, agrupa visualmente) |

Decisões assumidas (sem question explícita):
- Architecture: pure aggregator + wrapper (padrão Sprint 3b.30/3b.31/3b.33/3b.35)
- `status=ENABLED + negative=FALSE` hardcoded server-side via GAQL
- `audit_this_call=True` (sensitive read, lista config completa)
- No truncation V0 sem `limit` específico per ad_group (cap total `limit` 200 default, 1000 max)

---

## Section 1 — Architecture overview

**Pattern:** Pure aggregator + wrapper (Sprint 3b.30/3b.31/3b.33/3b.35 lineage).

**Layer stack:**

1. **`src/google_ads/flag_zombie_keywords.py` — pure module** (testable standalone, zero Google SDK imports). 2 dataclasses frozen+slots: `KeywordRow`, `ZombieKeyword`. Função `flag_zombie_keywords(rows, *, limit) → tuple[list[ZombieKeyword], int]`.
2. **`src/google_ads/queries/audit_zombie_keywords.py`** — GAQL builder + row parser + boundary dict→dataclass.
3. **`src/mcp/tools/audit_zombie_keywords.py` — tool wrapper** com `run_report` único. `audit_this_call=True`.

**Data flow:**

```
audit_zombie_keywords({customer_id, ad_group_ids?, limit?, date_range?, start?, end?})
  └─> resolve_date_window
  └─> build_audit_zombie_keywords_query(start, end, ad_group_ids)
        └─> GAQL keyword_view WHERE status=ENABLED + negative=FALSE + (ad_group_ids filter)
  └─> run_report(query) [audit_this_call=True]
  └─> dict_to_keyword_row[] (boundary)
  └─> flag_zombie_keywords.flag_zombie_keywords(rows, limit)
       └─> filter impressions==0 AND clicks==0
       └─> sort by (ad_group_name ASC, keyword_text ASC)
       └─> truncate to limit
  └─> return result.to_dict()
```

**Reuse benefits:**

- Padrão validado em 4 sprints anteriores
- Boundary parser idêntico
- F46 imune (não usa change_event)
- `resolve_date_window` reusa (Sprint 3b.20)
- Schema com `date_range` preset + start/end custom é convention V4

---

## Section 2 — Schema (input)

```python
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "ad_group_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "minItems": 1,
            "maxItems": 50,
            "description": "Opcional. Filtra audit a estes ad_group_ids. Default: conta inteira.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 200,
            "description": "Máximo zombies retornados. truncated:true se exceder.",
        },
        "date_range": {
            "type": "string",
            "enum": ["LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS", "LAST_90_DAYS"],
            "default": "LAST_30_DAYS",
            "description": "Preset. Override por start_date+end_date se ambos passados.",
        },
        "start_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": (
                "Data inicial YYYY-MM-DD inclusive. Quando informado junto com end_date, "
                "sobrepoe date_range preset. Obriga end_date."
            ),
        },
        "end_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Data final YYYY-MM-DD inclusive. Obrigatorio se start_date informado.",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}
```

**Notas:**

- `ad_group_ids` é **optional** (default = conta inteira)
- Schema idêntico ao `audit_quality_score` (3b.30) minus `min_impressions` (V0 strict zero)
- **No composition keywords** (3b.19B.1 convention)

---

## Section 3 — Output shape (response)

```python
{
    "customer_id": "7862230676",
    "date_range_resolved": {
        "start": "2026-04-21",
        "end": "2026-05-21",
        "days": 30,
    },
    "filters_applied": {
        "ad_group_ids": None,
        "limit": 200,
    },
    "total_zombies": 42,
    "truncated": False,
    "returned_count": 42,
    "zombies": [
        {
            "ad_group_id": "196329838059",
            "ad_group_name": "[GPC][JPA][LEADS][SEG][MESTRE DA OBRA]",
            "campaign_name": "CAMPANHA [PESQUISA]",
            "keyword_id": "60987266",
            "keyword_text": "andaime metálico",
            "match_type": "BROAD",
            "impressions": 0,
            "clicks": 0,
            "cost_brl": 0.0,
            "conversions": 0,
            "status": "ENABLED",
        },
        # sorted by ad_group_name ASC, keyword_text ASC
    ],
}
```

**Decisões cravadas:**

- `total_zombies` é POST-filter (post-WHERE GAQL + post-impressions/clicks=0 client-side filter)
- `returned_count` ≤ `total_zombies` (após truncation)
- `truncated: bool` echoes Sprint 3b.23 F22 pattern
- `zombies[]` flat list (não agrupada — gestor lê sequencial)

---

## Section 4 — Algorithm (pure module logic)

```python
# src/google_ads/flag_zombie_keywords.py

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KeywordRow:
    """Boundary input — dict de keyword_view GAQL converte pra cá."""

    ad_group_id: str
    ad_group_name: str
    campaign_name: str
    keyword_id: str
    keyword_text: str
    match_type: str
    impressions: int
    clicks: int
    cost_brl: float
    conversions: int
    status: str


@dataclass(frozen=True, slots=True)
class ZombieKeyword:
    """Output: KeywordRow flagged as zombie."""

    ad_group_id: str
    ad_group_name: str
    campaign_name: str
    keyword_id: str
    keyword_text: str
    match_type: str
    impressions: int
    clicks: int
    cost_brl: float
    conversions: int
    status: str


def flag_zombie_keywords(
    rows: list[KeywordRow],
    *,
    limit: int,
) -> tuple[list[ZombieKeyword], int]:
    """Filter zombies, sort, truncate.

    Args:
        rows: list[KeywordRow] from GAQL keyword_view (já filtered server-side
              por status=ENABLED + negative=FALSE).
        limit: max output entries.

    Returns:
        (zombies, total_pre_truncate). Sorted by ad_group_name ASC,
        keyword_text ASC.

    Algorithm:
    1. Filter: keep only rows com impressions == 0 AND clicks == 0 (pure waste).
    2. Sort: ad_group_name ASC, keyword_text ASC (stable visual grouping).
    3. Truncate to limit. Return (zombies, total_pre_truncate).

    Pure function — zero IO, zero Google SDK, fully testable.
    """
    zombies = [
        ZombieKeyword(
            ad_group_id=r.ad_group_id,
            ad_group_name=r.ad_group_name,
            campaign_name=r.campaign_name,
            keyword_id=r.keyword_id,
            keyword_text=r.keyword_text,
            match_type=r.match_type,
            impressions=r.impressions,
            clicks=r.clicks,
            cost_brl=r.cost_brl,
            conversions=r.conversions,
            status=r.status,
        )
        for r in rows
        if r.impressions == 0 and r.clicks == 0
    ]
    zombies.sort(key=lambda z: (z.ad_group_name, z.keyword_text))
    total = len(zombies)
    return zombies[:limit], total
```

**Edge cases tratados:**
- Empty `rows` input → `([], 0)`
- `limit=1` em conta com 50 zombies → returns 1, total=50, truncated=True
- Multiple keywords mesmo ad_group → todas listed
- Ordering tie-break: ad_group_name primary, keyword_text secondary, stable Python sorted

**GAQL builder** (`src/google_ads/queries/audit_zombie_keywords.py`):

```python
from datetime import date
from typing import Any

from src.google_ads.queries._common import gaql_date_clause
from src.google_ads.flag_zombie_keywords import KeywordRow


def build_audit_zombie_keywords_query(
    *,
    start_date: str,
    end_date: str,
    ad_group_ids: list[str] | None,
) -> str:
    """GAQL pra keyword_view com fields necessários (audit_zombie_keywords)."""
    from datetime import date as _d

    start = _d.fromisoformat(start_date)
    end = _d.fromisoformat(end_date)
    date_clause = gaql_date_clause(start, end)

    ad_group_clause = ""
    if ad_group_ids:
        ids = ",".join(ad_group_ids)
        ad_group_clause = f" AND ad_group.id IN ({ids})"

    return f"""
        SELECT
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.keyword.match_type,
          ad_group_criterion.status,
          ad_group.id,
          ad_group.name,
          campaign.name,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions
        FROM keyword_view
        WHERE {date_clause}
          AND ad_group_criterion.status = 'ENABLED'
          AND ad_group_criterion.negative = FALSE{ad_group_clause}
    """.strip()


def parse_keyword_view_row(row: Any) -> dict[str, Any]:
    """Parse keyword_view GAQL row → dict (boundary)."""
    return {
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": row.ad_group.name,
        "campaign_name": row.campaign.name,
        "keyword_id": str(row.ad_group_criterion.criterion_id),
        "keyword_text": row.ad_group_criterion.keyword.text,
        "match_type": row.ad_group_criterion.keyword.match_type.name,
        "impressions": int(row.metrics.impressions),
        "clicks": int(row.metrics.clicks),
        "cost_brl": float(row.metrics.cost_micros) / 1_000_000.0,
        "conversions": int(row.metrics.conversions),
        "status": row.ad_group_criterion.status.name,
    }


def dict_to_keyword_row(d: dict[str, Any]) -> KeywordRow:
    """Convert keyword_view row dict to KeywordRow dataclass (defensive)."""
    return KeywordRow(
        ad_group_id=str(d.get("ad_group_id", "")),
        ad_group_name=str(d.get("ad_group_name", "")),
        campaign_name=str(d.get("campaign_name", "")),
        keyword_id=str(d.get("keyword_id", "")),
        keyword_text=str(d.get("keyword_text", "")),
        match_type=str(d.get("match_type", "")),
        impressions=int(d.get("impressions", 0)),
        clicks=int(d.get("clicks", 0)),
        cost_brl=float(d.get("cost_brl", 0.0)),
        conversions=int(d.get("conversions", 0)),
        status=str(d.get("status", "")),
    )
```

---

## Section 5 — V0 cuts (out of scope)

| Item | Por que cortar V0 | V1+ candidato |
|---|---|---|
| **`min_impressions` threshold** | V0 strict zero (`impressions=0 AND clicks=0`). Adicionar threshold complica semantics (zombie?soft-zombie?). YAGNI até demanda. | V1 se gestor pede "soft zombie" (impressions>0 mas clicks=0) |
| **Cost-aware variant** (`cost_brl>0 AND conversions=0`) | Diferente semantics (waste com gasto vs pure inactive). Tool distinct V1: `audit_unproductive_keywords`. | V1+ |
| **Severity tiers** (totally invisible vs visible-not-clicked) | V0 single tier "zombie". Tiers complica scan da output. | V1 com threshold flag |
| **Auto-pause action** | Tool é passive detect. Mutate = `update_keyword_status` separate call. | V1+ workflow combinado |
| **Ad_group_name search/filter** | Gestor pós-filter client-side. Schema simples. | V1 se demanda |
| **Bid info** (`first_page_cpc`, `top_of_page_cpc`) | Output focused waste detection. Bid info useless se keyword zombie. | V1+ |
| **Quality score field** | Pertence a `audit_quality_score` (3b.30). Separation of concerns. | N/A |
| **Match type breakdown** | Output já inclui `match_type` per zombie. Sem agregação V0. | V1+ |
| **Cross-campaign deduplication** | Mesma keyword text em multiple campaigns listed separately. Esperado V0. | V1 com flag `dedup` |

---

## Section 6 — Testing strategy + V0 surface metrics

### Test pyramid

| Tipo | Count | Foco |
|---|---|---|
| Unit (pure module) | ~10 | Filter logic (impressions=0 + clicks=0), sort, truncate, edge cases |
| Unit (boundary + GAQL) | ~4 | `dict_to_keyword_row` + `parse_keyword_view_row` + GAQL builder shape + WHERE clauses |
| Integration (tool wrapper) | ~3 | Wire-up: run_report mock → flag_zombie_keywords → response shape |
| Smoke (production) | T1-T6 | Real account MO-JP + ML Antiguidades |

### Unit tests detail (pure module, ~10)

- `test_empty_rows_returns_empty`
- `test_filter_keeps_impressions_zero_clicks_zero`
- `test_filter_excludes_impressions_positive` (keyword com 1+ impression NÃO é zombie)
- `test_filter_excludes_clicks_positive` (keyword com clicks NÃO é zombie, mesmo com impressions=0 — edge case rare mas defensive)
- `test_sort_by_ad_group_name_asc`
- `test_sort_tie_break_by_keyword_text_asc`
- `test_truncation_limit_exceeded` (50 rows + limit=10 → returns 10, total=50)
- `test_truncation_limit_not_exceeded` (5 rows + limit=200 → returns 5, total=5)
- `test_multiple_keywords_same_ad_group_all_listed`
- `test_total_count_pre_truncate_preserved`

### Boundary + GAQL tests (~4)

- `test_build_query_includes_required_fields` (11 fields SELECT)
- `test_build_query_filters_enabled_and_not_negative` (WHERE clauses)
- `test_build_query_ad_group_ids_filter` (optional clause)
- `test_dict_to_keyword_row_handles_missing_fields` (defaults)

### Smoke runbook V0 (6 tests)

| # | Cenário | Conta | Expected |
|---|---|---|---|
| T1 | Default LAST_30_DAYS panorâmico | MO-JP `7862230676` | Lista zombies da conta inteira, sorted by ad_group_name |
| T2 | ad_group_ids filter | MO-JP (1 ad_group específico) | Apenas zombies daquele ad_group |
| T3 | Custom date range (start_date + end_date) | MO-JP | Window honored, zombies filtered |
| T4 | limit truncation | MO-JP `limit=10` em conta com 20+ zombies | `truncated=true`, `returned_count=10`, `total_zombies` reflects full |
| T5 | Conta clean (poucos zombies) | ML Antiguidades `7455088726` | Output pequeno ou empty (e-commerce ativo) |
| T6 | Caso real dogfood 19/05 — MO-JP cleanup recurring | MO-JP | Detecta keywords ENABLED zumbi candidates pra pause/remove |

**Defer conditions:**
- T5 DEFERRED se ML antiguidades inesperadamente tem muitos zombies (mudar pra conta clean diferente)
- Sem F-finding novo expected (pattern bem cravado)

### V0 surface metrics

```
- 1 new MCP tool: audit_zombie_keywords (tool count 55 → 56)
- 1 new pure module: src/google_ads/flag_zombie_keywords.py (~80 LOC)
- 1 new queries file: src/google_ads/queries/audit_zombie_keywords.py (~70 LOC)
- 1 new tool wrapper: src/mcp/tools/audit_zombie_keywords.py (~100 LOC)
- ~17 testes (10 unit pure + 4 boundary/GAQL + 3 integration)
- 1 smoke runbook (phase-3b-36-bootstrap.md, 6 tests)
```

### Estimated effort

- A1 (haiku — pure module + 10 unit tests): ~20 min
- A2 (haiku — GAQL builder + parsers + 4 tests): ~15 min
- A3 (sonnet — tool wrapper + 3 integration + schema): ~20 min
- A4 (smoke-runbook-generator): ~5 min
- A5 (controller smoke + signoff): ~30 min

**TOTAL:** ~90 min (~1.5h) via subagent-driven (paralelo A1+A2).

---

## Riscos + mitigações

| Risco | Mitigação |
|---|---|
| **Token cap em conta grande** (>500 zombies em conta com muitas keywords) | `limit` default 200 + max 1000. F22 pattern aplicado. |
| **False positives — keyword nova (criada esta semana, ainda aprendendo)** | Gestor escolhe window apropriado (LAST_30_DAYS catch só keywords old). V1+ flag pra excluir keywords recém-criadas. |
| **Keyword com impressions>0 mas clicks=0** | NÃO é zombie V0 (definição strict). Conceitualmente "low CTR" — diferente issue, fora scope. |
| **F46 lag concerns** | N/A — tool não usa change_event. `gaql_date_clause` from `_common.py` é orthogonal a F46 fix. |
| **B1 lag (campaign.status)** | N/A — tool não filtra por campaign status. |

---

## References

- Dogfood source: cleanup massivo MO-JP recurring (dogfood 2026-05-19 lição 41+)
- Architecture precedent: Sprint 3b.30 ([`audit_quality_score`](../../operacao/phase-3b-30-bootstrap.md)) — schema + algorithm pattern idêntico
- F22 limit + truncated pattern: Sprint 3b.23
- Date range conventions: Sprint 3b.20 + 3b.34 F46 fix em change_history (NÃO afeta keyword_view)
- No-composition-keywords: Sprint 3b.19B.1
