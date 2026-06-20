# Onda 3 — Filtros server-side (dogfood) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar filtros server-side `min_cost_brl` / `min_clicks` / `min_conversions` a `get_keyword_performance` e `get_search_terms_report`, cortando o payload na origem (a dor #1 do dogfood: output estoura o cap do MCP, gestor cai pra Bash+Python).

**Architecture:** Um helper GAQL compartilhado `build_metric_filter_clause` (em `queries/_common.py`) gera o fragmento `WHERE` opcional; os 2 query builders (`keyword_performance_query`, `search_terms_query` em `tactical.py`) o injetam; os 2 tools ganham os 3 params no schema + handler. **Filtro server-side** (não client-side) porque o `WHERE` atua ANTES do `LIMIT` — o top-N sai do conjunto já filtrado.

**Tech Stack:** Python 3.13 · GAQL (Google Ads Query Language) · pytest (`asyncio_mode=auto`).

## Global Constraints

- **Operadores GAQL (validados via `validate_gaql` em keyword_view + search_term_view):** `metrics.cost_micros >= <micros>` e `metrics.clicks >= <int>` (inteiros aceitam `>=`); **`metrics.conversions > <float>`** (double — GAQL REJEITA `>=` em conversions; só `=, !=, <, >, IN, NOT IN, IS NULL/NOT NULL`). Os 3 campos já estão no SELECT dos 2 builders.
- **Conversão:** `min_cost_brl` (BRL) → micros = `int(min_cost_brl * 1_000_000)`.
- **Semântica de `min_conversions`:** "ESTRITAMENTE acima" (operador `>`). Documentar no schema: use `0` pra "tem ao menos uma conversão". `min_cost_brl`/`min_clicks` são "pelo menos" (`>=`).
- **Filtros são opcionais** — ausentes → clause vazia → query idêntica à de hoje (backward-compat). Defaults de `limit` inalterados (200 keyword / 50 search_terms).
- **Date-range conventions inalteradas** (preset OU start+end via `resolve_date_window`).
- **Fora de escopo (desvio consciente da spec §5):** o "payload budget helper" da spec é YAGNI — os filtros server-side já resolvem o estouro de payload; o `limit` + `ORDER BY cost DESC` já existem. Não adicionar cap genérico.
- **Verificação antes de cada commit:** `.venv/Scripts/python.exe scripts/check_pre_push.py` verde. Commit `feat(mcp): ...` + trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: Helper `build_metric_filter_clause`

**Files:**
- Modify: `src/google_ads/queries/_common.py` (adicionar a função; é onde vivem `gaql_date_clause` + `micros_to_currency`)
- Test: `tests/unit/test_metric_filter_clause.py` (criar)

**Interfaces:**
- Produces: `build_metric_filter_clause(min_cost_brl: float | None = None, min_clicks: int | None = None, min_conversions: float | None = None) -> str` — retorna o fragmento GAQL (começando com `AND `) ou `""` se nenhum filtro.

- [ ] **Step 1: Escrever o teste (falhando)**

Criar `tests/unit/test_metric_filter_clause.py`:

```python
"""Helper GAQL pros filtros server-side da Onda 3 (dogfood)."""

from src.google_ads.queries._common import build_metric_filter_clause


def test_no_filters_returns_empty() -> None:
    assert build_metric_filter_clause() == ""


def test_cost_filter_uses_gte_and_micros() -> None:
    assert build_metric_filter_clause(min_cost_brl=3.0) == "AND metrics.cost_micros >= 3000000"


def test_clicks_filter_uses_gte_int() -> None:
    assert build_metric_filter_clause(min_clicks=5) == "AND metrics.clicks >= 5"


def test_conversions_filter_uses_strict_gt_float() -> None:
    # GAQL rejeita >= em metrics.conversions (double) — usa > ; 0 → "tem alguma conversão"
    assert build_metric_filter_clause(min_conversions=0) == "AND metrics.conversions > 0.0"


def test_all_three_combined_in_order() -> None:
    assert build_metric_filter_clause(min_cost_brl=3.0, min_clicks=5, min_conversions=1) == (
        "AND metrics.cost_micros >= 3000000 AND metrics.clicks >= 5 AND metrics.conversions > 1.0"
    )
```

- [ ] **Step 2: Rodar pra verificar que falha**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_metric_filter_clause.py -v`
Expected: FAIL (`ImportError: cannot import name 'build_metric_filter_clause'`)

- [ ] **Step 3: Implementar o helper em `src/google_ads/queries/_common.py`**

Adicionar (perto de `gaql_date_clause` / `micros_to_currency`):

```python
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
    clauses: list[str] = []
    if min_cost_brl is not None:
        clauses.append(f"AND metrics.cost_micros >= {int(min_cost_brl * 1_000_000)}")
    if min_clicks is not None:
        clauses.append(f"AND metrics.clicks >= {int(min_clicks)}")
    if min_conversions is not None:
        clauses.append(f"AND metrics.conversions > {float(min_conversions)}")
    return " ".join(clauses)
```

- [ ] **Step 4: Rodar o teste**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_metric_filter_clause.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Verificação + commit**

```bash
.venv/Scripts/python.exe scripts/check_pre_push.py
git add src/google_ads/queries/_common.py tests/unit/test_metric_filter_clause.py
git commit -m "feat(mcp): helper build_metric_filter_clause pros filtros server-side (dogfood)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Filtros em `get_keyword_performance`

**Files:**
- Modify: `src/google_ads/queries/tactical.py` (`keyword_performance_query:8` — adicionar kwargs)
- Modify: `src/mcp/tools/get_keyword_performance.py` (schema `:25-57` + handler `:115-133`)
- Test: `tests/unit/test_keyword_performance_filters.py` (criar)

**Interfaces:**
- Consumes: `build_metric_filter_clause(...)` (Task 1).
- Produces: `keyword_performance_query(start, end, status, limit, *, min_cost_brl=None, min_clicks=None, min_conversions=None) -> str`.

- [ ] **Step 1: Escrever os testes (falhando)**

Criar `tests/unit/test_keyword_performance_filters.py`:

```python
"""Filtros server-side no get_keyword_performance + query builder (Onda 3)."""

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.google_ads.queries.tactical import keyword_performance_query
from src.mcp.tools._registry import get_tool


def test_query_without_filters_omits_metric_clauses() -> None:
    q = keyword_performance_query(date(2026, 6, 1), date(2026, 6, 19), "enabled", 200)
    assert "metrics.cost_micros >=" not in q
    assert "metrics.clicks >=" not in q
    assert "metrics.conversions >" not in q
    # backward-compat: ORDER BY + LIMIT preservados
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 200" in q


def test_query_with_filters_injects_clauses() -> None:
    q = keyword_performance_query(
        date(2026, 6, 1), date(2026, 6, 19), "enabled", 200,
        min_cost_brl=3.0, min_clicks=5, min_conversions=0,
    )
    assert "metrics.cost_micros >= 3000000" in q
    assert "metrics.clicks >= 5" in q
    assert "metrics.conversions > 0.0" in q
    # status clause ainda presente
    assert "ad_group_criterion.status = 'ENABLED'" in q


@pytest.mark.asyncio
async def test_handler_passes_filters_into_query(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.mcp.tools.get_keyword_performance as mod

    ctx = MagicMock()
    ctx.manager_id = uuid4()
    ctx.session_id = uuid4()
    monkeypatch.setattr(mod, "get_current", lambda: ctx)

    captured: dict[str, str] = {}

    async def _fake_run_report(**kwargs: object) -> list[object]:
        captured["query"] = str(kwargs["query"])
        return []

    monkeypatch.setattr(mod, "run_report", _fake_run_report)

    tool = get_tool("get_keyword_performance")
    assert tool is not None
    await tool.handler(
        {"customer_id": "1234567890", "date_range": "LAST_7_DAYS", "min_cost_brl": 3.0, "min_clicks": 5}
    )
    assert "metrics.cost_micros >= 3000000" in captured["query"]
    assert "metrics.clicks >= 5" in captured["query"]
```

- [ ] **Step 2: Rodar pra verificar que falha**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_keyword_performance_filters.py -v`
Expected: FAIL (`keyword_performance_query()` não aceita `min_cost_brl`; o schema rejeita os params → handler test falha).

- [ ] **Step 3: Adicionar kwargs ao `keyword_performance_query`**

Em `src/google_ads/queries/tactical.py`, substituir `keyword_performance_query` (linhas 8-31) por:

```python
def keyword_performance_query(
    start: date,
    end: date,
    status: str,
    limit: int,
    *,
    min_cost_brl: float | None = None,
    min_clicks: int | None = None,
    min_conversions: float | None = None,
) -> str:
    status_clause = "" if status == "all" else f"AND ad_group_criterion.status = '{status.upper()}'"
    metric_clause = build_metric_filter_clause(min_cost_brl, min_clicks, min_conversions)
    return f"""
        SELECT
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.keyword.match_type,
          ad_group_criterion.status,
          ad_group_criterion.negative,
          ad_group_criterion.quality_info.quality_score,
          ad_group_criterion.quality_info.creative_quality_score,
          ad_group_criterion.quality_info.post_click_quality_score,
          ad_group_criterion.quality_info.search_predicted_ctr,
          ad_group_criterion.position_estimates.first_page_cpc_micros,
          ad_group_criterion.position_estimates.top_of_page_cpc_micros,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM keyword_view
        WHERE {gaql_date_clause(start, end)} {status_clause} {metric_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit}
    """.strip()
```

And add the import at the top of `tactical.py` (line 5 already imports from `_common`):

```python
from src.google_ads.queries._common import build_metric_filter_clause, gaql_date_clause
```

- [ ] **Step 4: Adicionar os 3 params ao schema + passá-los no handler de `get_keyword_performance.py`**

In `_SCHEMA["properties"]` (after `"limit"`, line ~53):

```python
        "min_cost_brl": {
            "type": "number",
            "minimum": 0,
            "description": "Filtro server-side: só linhas com custo (BRL) >= este valor. Corta a cauda de baixo gasto (reduz payload).",
        },
        "min_clicks": {
            "type": "integer",
            "minimum": 0,
            "description": "Filtro server-side: só linhas com clicks >= este valor.",
        },
        "min_conversions": {
            "type": "number",
            "minimum": 0,
            "description": "Filtro server-side: só linhas com conversions ESTRITAMENTE acima deste valor (GAQL não aceita >= em conversions). Use 0 pra 'tem ao menos uma conversão'.",
        },
```

In the handler, replace the `run_report` call's `query=` argument (line 129):

```python
        query=keyword_performance_query(
            start,
            end,
            status,
            limit,
            min_cost_brl=args.get("min_cost_brl"),
            min_clicks=args.get("min_clicks"),
            min_conversions=args.get("min_conversions"),
        ),
```

- [ ] **Step 5: Rodar os testes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_keyword_performance_filters.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Verificação + commit**

```bash
.venv/Scripts/python.exe scripts/check_pre_push.py
git add src/google_ads/queries/tactical.py src/mcp/tools/get_keyword_performance.py tests/unit/test_keyword_performance_filters.py
git commit -m "feat(mcp): filtros server-side min_cost/min_clicks/min_conversions em get_keyword_performance" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Filtros em `get_search_terms_report`

**Files:**
- Modify: `src/google_ads/queries/tactical.py` (`search_terms_query:34` — adicionar kwargs)
- Modify: `src/mcp/tools/get_search_terms_report.py` (schema `:25-52` + handler `:88-104`)
- Test: `tests/unit/test_search_terms_filters.py` (criar)

**Interfaces:**
- Consumes: `build_metric_filter_clause(...)` (Task 1).
- Produces: `search_terms_query(start, end, limit, *, min_cost_brl=None, min_clicks=None, min_conversions=None) -> str`.

- [ ] **Step 1: Escrever os testes (falhando)**

Criar `tests/unit/test_search_terms_filters.py`:

```python
"""Filtros server-side no get_search_terms_report + query builder (Onda 3)."""

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.google_ads.queries.tactical import search_terms_query
from src.mcp.tools._registry import get_tool


def test_query_without_filters_omits_metric_clauses() -> None:
    q = search_terms_query(date(2026, 6, 1), date(2026, 6, 19), 50)
    assert "metrics.cost_micros >=" not in q
    assert "metrics.clicks >=" not in q
    assert "metrics.conversions >" not in q
    assert "LIMIT 50" in q


def test_query_with_filters_injects_clauses() -> None:
    q = search_terms_query(
        date(2026, 6, 1), date(2026, 6, 19), 50,
        min_cost_brl=3.0, min_clicks=5, min_conversions=0,
    )
    assert "metrics.cost_micros >= 3000000" in q
    assert "metrics.clicks >= 5" in q
    assert "metrics.conversions > 0.0" in q


@pytest.mark.asyncio
async def test_handler_passes_filters_into_query(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.mcp.tools.get_search_terms_report as mod

    ctx = MagicMock()
    ctx.manager_id = uuid4()
    ctx.session_id = uuid4()
    monkeypatch.setattr(mod, "get_current", lambda: ctx)

    captured: dict[str, str] = {}

    async def _fake_run_report(**kwargs: object) -> list[object]:
        captured["query"] = str(kwargs["query"])
        return []

    monkeypatch.setattr(mod, "run_report", _fake_run_report)

    tool = get_tool("get_search_terms_report")
    assert tool is not None
    await tool.handler(
        {"customer_id": "1234567890", "date_range": "LAST_7_DAYS", "min_cost_brl": 3.0}
    )
    assert "metrics.cost_micros >= 3000000" in captured["query"]
```

- [ ] **Step 2: Rodar pra verificar que falha**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_search_terms_filters.py -v`
Expected: FAIL (`search_terms_query()` não aceita `min_cost_brl`).

- [ ] **Step 3: Adicionar kwargs ao `search_terms_query`**

Em `src/google_ads/queries/tactical.py`, substituir `search_terms_query` (linhas 34-47) por:

```python
def search_terms_query(
    start: date,
    end: date,
    limit: int,
    *,
    min_cost_brl: float | None = None,
    min_clicks: int | None = None,
    min_conversions: float | None = None,
) -> str:
    metric_clause = build_metric_filter_clause(min_cost_brl, min_clicks, min_conversions)
    return f"""
        SELECT
          search_term_view.search_term,
          search_term_view.status,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM search_term_view
        WHERE {gaql_date_clause(start, end)} {metric_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit}
    """.strip()
```

(The `build_metric_filter_clause` import was already added to `tactical.py` in Task 2 Step 3.)

- [ ] **Step 4: Adicionar os 3 params ao schema + passá-los no handler de `get_search_terms_report.py`**

In `_SCHEMA["properties"]` (after `"limit"`, line ~48) — same 3 properties as Task 2 Step 4 (`min_cost_brl`, `min_clicks`, `min_conversions`, with the identical descriptions).

In the handler, replace the `query=` argument (line 101):

```python
        query=search_terms_query(
            start,
            end,
            limit,
            min_cost_brl=args.get("min_cost_brl"),
            min_clicks=args.get("min_clicks"),
            min_conversions=args.get("min_conversions"),
        ),
```

- [ ] **Step 5: Rodar os testes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_search_terms_filters.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Verificação + commit**

```bash
.venv/Scripts/python.exe scripts/check_pre_push.py
git add src/google_ads/queries/tactical.py src/mcp/tools/get_search_terms_report.py tests/unit/test_search_terms_filters.py
git commit -m "feat(mcp): filtros server-side min_cost/min_clicks/min_conversions em get_search_terms_report" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Smoke (pós-deploy, human-gate — não é task TDD)

A viabilidade GAQL já foi validada via `validate_gaql` (keyword_view + search_term_view, os 3 operadores). Pós-deploy, confirmar o corte real numa conta com volume:
- `get_keyword_performance(customer, LAST_30_DAYS)` sem filtro → conta as rows/tamanho.
- `get_keyword_performance(customer, LAST_30_DAYS, min_cost_brl=3, min_clicks=1)` → confirma payload bem menor (a cauda longa some) e que os filtros batem com os valores no resultado.

## Self-Review (do autor do plano)

**Cobertura da spec §5 (Onda 3):**
- Filtros `min_cost_brl`/`min_clicks`/`min_conversions` em `get_keyword_performance` + `get_search_terms_report` → Tasks 2+3 ✅
- "GAQL HAVING" da spec → corrigido pra **GAQL WHERE server-side** (HAVING não existe em GAQL); operadores validados empiricamente ✅
- Helper compartilhado → Task 1 (`build_metric_filter_clause`) ✅
- "Payload budget helper" da spec → **DROP (YAGNI)**, documentado em Global Constraints (os filtros resolvem o estouro) ✅

**Type/naming consistency:** `build_metric_filter_clause(min_cost_brl, min_clicks, min_conversions)` é a mesma assinatura nos 2 builders e nos 2 handlers (todos via `args.get(...)`). Os 3 params de schema são idênticos nos 2 tools.

**Risco residual:** o operador `>` em conversions (vs `>=` esperado) é uma sutileza de semântica — mitigado pela description explícita do schema. Sem mudança de produção fora dos 2 tools + 1 helper; backward-compat garantida (filtros ausentes → query idêntica).
