# Sprint 3b.40 — Quick Wins Mutate Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar 3 quick wins do dogfood MO-JP 2026-05-27 (A1+B9+A2, ICE somado 2030) em 4 commits sequenciais.

**Architecture:** Catalog F56 primeiro (B9 finding) → 3 features em ordem inversa de complexidade (A2 trivial → B9 trivial → A1 com novo módulo). Bundle único single PR, sem subagent dispatch (esforço 4-6h não justifica overhead). Pattern F52 reusado pra A2 (replica 1:1 de audit_zombie_keywords cravado 25/05).

**Tech Stack:** Python 3.12, google-ads SDK v24, pytest, asyncpg, MCP via Streamable HTTP. Pre-push gate via `python scripts/check_pre_push.py`.

**Spec:** `docs/superpowers/specs/2026-05-27-sprint-3b-40-quick-wins-mutate-safety-design.md`

---

## File Structure

**Created:**
- `src/google_ads/queries/keyword_lookup.py` — fetch keyword_text + match_type per (ad_group_id, criterion_id), used by A1
- `tests/unit/test_keyword_lookup.py` — query builder + parser tests
- `tests/integration/test_get_keyword_performance.py` — wire-up tests (file não existia)
- `tests/integration/test_update_keyword_status.py` — wire-up tests (file não existia)
- `docs/operacao/phase-3b-40-bootstrap.md` — smoke runbook (gerado via subagent)

**Modified:**
- `docs/operacao/findings-catalog.md` — catalog F56 (Task 1)
- `src/google_ads/flag_keywords.py` — add `ad_group_status` field em KeywordRow + FlaggedKeyword (Task 2)
- `src/google_ads/queries/audit_quality_score.py` — query SELECT + parser + dict_to_keyword_row (Task 2)
- `src/mcp/tools/audit_quality_score.py` — response shape + description warning (Task 2)
- `src/google_ads/queries/tactical.py` — keyword_performance_query SELECT (Task 3)
- `src/mcp/tools/get_keyword_performance.py` — row_formatter + description (Task 3)
- `src/mcp/tools/update_keyword_status.py` — import keyword_lookup + dry_run branch (Task 4)
- `tests/unit/test_flag_keywords.py` — `_make_row` helper add ad_group_status param (Task 2)
- `tests/unit/test_audit_quality_score_query.py` — assertion ad_group.status (Task 2)
- `tests/integration/test_audit_quality_score.py` — fake_rows + assertions ad_group_status (Task 2)
- `docs/operacao/sprint-history.md` — nova row Sprint 3b.40 (Task 7)
- `CLAUDE.md` — Pending section refresh + count 55→56 findings (Task 7)

---

## Task 1: Catalog F56 em findings-catalog.md

**Files:**
- Modify: `docs/operacao/findings-catalog.md` (table "Bug class 1: Silent-acceptance design gap", append row)

- [ ] **Step 1: Read findings-catalog.md table structure (rows F50-F55 já existem)**

Run: `grep -n "^| \*\*F5" docs/operacao/findings-catalog.md`
Expected: 6 rows (F50-F55) localizando coluna positions.

- [ ] **Step 2: Add F56 row to Bug class 1 table**

Add after F52 row (end of "Silent-acceptance" table, before `---` separator):

```markdown
| **F56** | MED | dogfood 2026-05-27 MO-JP | 3b.40 | **`get_keyword_performance` retorna positive E negative `ad_group_criterion` indistintamente — workflow risk em mutate downstream.** Dogfood 2026-05-27 MO-JP+CAB cleanup massivo: fresh fetch `get_keyword_performance(status=enabled, limit=500)` retornou 500 keywords ENABLED. Cross-check com `audit_zombie_keywords` (filtra `negative=FALSE` server-side) revelou 280 zumbis totais → 108 em ENABLED ad_groups. **Diferença com fresh fetch: 39 keywords = negative ad_group_criterion com status ENABLED.** Workflow "extract criterion_ids zumbis pra PAUSE batch via fresh fetch" produz 147 candidatos (incorretos) vs 108 verdadeiros (positive ENABLED). Os 39 falsos positivos seriam rejeitados por `update_keyword_status` via pre-flight `validate_keyword_criterion_types` (F43 mitigation), mas inflam baseline de "zumbis" + forçam parse Python externo. **Root cause:** GAQL `keyword_view` resource expõe `ad_group_criterion.negative` mas tool atual omite no row_formatter. **Fix Sprint 3b.40 (Opção A+C — backward-compat):** adicionar field `negative: bool` na response (zero breaking change pra consumers existentes) + warning F56 explícito na tool description direcionando consumer pra `audit_zombie_keywords`/`audit_quality_score` (filtram `negative=FALSE` server-side). **Lição generalizável:** tools de listagem que feed mutate workflows MUST expor type discriminators (positive vs negative, criterion type) explícitos no output, mesmo que GAQL native exponha (tool layer não pode confiar que caller saiba inspecionar SDK proto fields). Family: design-gap-via-missing-discriminator-field (variant da silent-acceptance family, similar F52 missing parent filter pattern). [dogfood-2026-05-27-mestre-da-obra-jp-investigacao-senior.md §B9] |
```

- [ ] **Step 3: Update "Last updated" header**

Edit line 7 of findings-catalog.md:

```markdown
> **Last updated:** 2026-05-27 (Sprint 3b.40 ship: **+F56** [get_keyword_performance positive+negative gap, MEDIUM, Opção A+C fix com field + description warning]. 56 unique findings.)
```

- [ ] **Step 4: Verify add count**

Run: `grep -c "^| \*\*F" docs/operacao/findings-catalog.md`
Expected: previous count + 1.

- [ ] **Step 5: Commit**

```bash
git add docs/operacao/findings-catalog.md
git commit -m "$(cat <<'EOF'
docs(findings): catalog F56 get_keyword_performance negative criteria gap

B9 do dogfood MO-JP 2026-05-27 — tool retorna positive E negative
ad_group_criterion indistintamente. Workflow "fresh fetch zumbis →
PAUSE batch" produziu 147 candidatos (39 falsos positivos = negative
typed) vs 108 reais. Mitigation Sprint 3b.40 (Opção A+C).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: A2 — ad_group_status em audit_quality_score (replica F52)

**Files:**
- Modify: `src/google_ads/flag_keywords.py:20-52` (KeywordRow + FlaggedKeyword)
- Modify: `src/google_ads/queries/audit_quality_score.py:27-86` (query + parser + dict converter)
- Modify: `src/mcp/tools/audit_quality_score.py:75-170` (response + description)
- Modify: `tests/unit/test_flag_keywords.py:10-36` (_make_row helper)
- Modify: `tests/unit/test_audit_quality_score_query.py:48-69` (SELECT assertion)
- Modify: `tests/integration/test_audit_quality_score.py:20-143` (fake_rows + assertions)

### Test First (RED phase)

- [ ] **Step 1: Add new unit test for KeywordRow.ad_group_status field**

Edit `tests/unit/test_flag_keywords.py` — modify `_make_row` signature (linha 10) to accept new `ad_group_status` param, and add new test at end:

```python
def _make_row(
    *,
    ad_group_id: str = "1001",
    ad_group_name: str = "AG1",
    ad_group_status: str = "ENABLED",  # NEW
    campaign_name: str = "C1",
    keyword_id: str = "1",
    keyword_text: str = "kw",
    match_type: str = "BROAD",
    quality_score: int = 5,
    impressions: int = 100,
    clicks: int = 5,
    conversions: int = 0,
    cost_brl: float = 0.0,
) -> KeywordRow:
    return KeywordRow(
        ad_group_id=ad_group_id,
        ad_group_name=ad_group_name,
        ad_group_status=ad_group_status,  # NEW
        campaign_name=campaign_name,
        keyword_id=keyword_id,
        keyword_text=keyword_text,
        match_type=match_type,
        quality_score=quality_score,
        impressions=impressions,
        clicks=clicks,
        conversions=conversions,
        cost_brl=cost_brl,
    )
```

Add at end of file:

```python
def test_f52_pattern_ad_group_status_propagates_to_flagged_keyword():
    """A2 (espelha F52): ad_group_status field propaga de KeywordRow → FlaggedKeyword."""
    row = _make_row(
        ad_group_status="REMOVED",
        quality_score=2,
        impressions=15,
        clicks=0,
    )
    flagged, _ = flag_keywords([row], min_impressions=10, limit=200)
    assert len(flagged) == 1
    assert flagged[0].ad_group_status == "REMOVED"
```

- [ ] **Step 2: Run unit test to verify RED**

Run: `python -m pytest tests/unit/test_flag_keywords.py -v`
Expected: ALL tests FAIL with `TypeError: KeywordRow.__init__() got an unexpected keyword argument 'ad_group_status'` (dataclass field doesn't exist yet).

### Implementation (GREEN phase)

- [ ] **Step 3: Add ad_group_status field to KeywordRow + FlaggedKeyword**

Edit `src/google_ads/flag_keywords.py` linha 20-52:

```python
@dataclass(frozen=True, slots=True)
class KeywordRow:
    """Input row from keyword_view GAQL query (Google-agnostic representation)."""

    ad_group_id: str
    ad_group_name: str
    ad_group_status: str  # A2 (espelha F52): revela órfãs em ad_group REMOVED
    campaign_name: str
    keyword_id: str
    keyword_text: str
    match_type: str  # "EXACT" | "PHRASE" | "BROAD"
    quality_score: int  # 1-10
    impressions: int
    clicks: int
    conversions: int
    cost_brl: float


@dataclass(frozen=True, slots=True)
class FlaggedKeyword:
    """Output: KeywordRow + flags tuple."""

    ad_group_id: str
    ad_group_name: str
    ad_group_status: str  # A2 (espelha F52)
    campaign_name: str
    keyword_id: str
    keyword_text: str
    match_type: str
    quality_score: int
    impressions: int
    clicks: int
    conversions: int
    cost_brl: float
    flags: tuple[str, ...]
```

Edit `flag_keywords` function linha ~105 (within FlaggedKeyword construction):

```python
        flagged.append(
            FlaggedKeyword(
                ad_group_id=row.ad_group_id,
                ad_group_name=row.ad_group_name,
                ad_group_status=row.ad_group_status,  # NEW
                campaign_name=row.campaign_name,
                keyword_id=row.keyword_id,
                keyword_text=row.keyword_text,
                match_type=row.match_type,
                quality_score=row.quality_score,
                impressions=row.impressions,
                clicks=row.clicks,
                conversions=row.conversions,
                cost_brl=row.cost_brl,
                flags=tuple(all_flags),
            )
        )
```

- [ ] **Step 4: Run unit tests to verify GREEN**

Run: `python -m pytest tests/unit/test_flag_keywords.py -v`
Expected: ALL tests PASS (existing + new `test_f52_pattern_ad_group_status_propagates_to_flagged_keyword`).

### Query builder + parser tests (RED)

- [ ] **Step 5: Add query SELECT assertion test**

Edit `tests/unit/test_audit_quality_score_query.py` — update `test_query_selects_all_required_fields` linha 48-69 to include `ad_group.status`:

```python
def test_query_selects_all_required_fields():
    """Output must include all fields needed by KeywordRow dataclass."""
    query = build_audit_quality_score_query(
        start_date="2026-04-20",
        end_date="2026-05-20",
        ad_group_ids=None,
    )
    expected_fields = [
        "ad_group.id",
        "ad_group.name",
        "ad_group.status",  # A2 (espelha F52)
        "campaign.name",
        "ad_group_criterion.criterion_id",
        "ad_group_criterion.keyword.text",
        "ad_group_criterion.keyword.match_type",
        "ad_group_criterion.quality_info.quality_score",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.conversions",
        "metrics.cost_micros",
    ]
    for f in expected_fields:
        assert f in query, f"Missing field: {f}"
```

- [ ] **Step 6: Run query test to verify RED**

Run: `python -m pytest tests/unit/test_audit_quality_score_query.py::test_query_selects_all_required_fields -v`
Expected: FAIL with `AssertionError: Missing field: ad_group.status`.

### Query builder + parser (GREEN)

- [ ] **Step 7: Add ad_group.status to query + parser + dict_to_keyword_row**

Edit `src/google_ads/queries/audit_quality_score.py`:

Linha ~27-44 (`build_audit_quality_score_query`): adicionar `"ad_group.status, "` no SELECT:

```python
    query = (
        "SELECT "
        "ad_group.id, ad_group.name, ad_group.status, campaign.name, "  # A2 (espelha F52): + ad_group.status
        "ad_group_criterion.criterion_id, "
        "ad_group_criterion.keyword.text, "
        "ad_group_criterion.keyword.match_type, "
        "ad_group_criterion.quality_info.quality_score, "
        "metrics.impressions, metrics.clicks, "
        "metrics.conversions, metrics.cost_micros "
        "FROM keyword_view "
        "WHERE ad_group_criterion.status = 'ENABLED' "
        f"AND segments.date BETWEEN '{start_date}' AND '{end_date}' "
        "AND ad_group_criterion.quality_info.quality_score IS NOT NULL"
    )
```

Linha ~47-69 (`parse_keyword_view_row`): adicionar `ad_group_status`:

```python
    return {
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": row.ad_group.name,
        "ad_group_status": row.ad_group.status.name,  # A2 (espelha F52)
        "campaign_name": row.campaign.name,
        "keyword_id": str(row.ad_group_criterion.criterion_id),
        "keyword_text": row.ad_group_criterion.keyword.text,
        "match_type": match_type_str,
        "quality_score": row.ad_group_criterion.quality_info.quality_score,
        "impressions": row.metrics.impressions,
        "clicks": row.metrics.clicks,
        "conversions": row.metrics.conversions,
        "cost_brl": row.metrics.cost_micros / 1_000_000.0,
    }
```

Linha ~72-86 (`dict_to_keyword_row`): forward field:

```python
def dict_to_keyword_row(d: dict[str, Any]) -> KeywordRow:
    """Convert parsed dict back to KeywordRow dataclass at tool wrapper boundary."""
    return KeywordRow(
        ad_group_id=d["ad_group_id"],
        ad_group_name=d["ad_group_name"],
        ad_group_status=d["ad_group_status"],  # A2 (espelha F52)
        campaign_name=d["campaign_name"],
        keyword_id=d["keyword_id"],
        keyword_text=d["keyword_text"],
        match_type=d["match_type"],
        quality_score=d["quality_score"],
        impressions=d["impressions"],
        clicks=d["clicks"],
        conversions=d["conversions"],
        cost_brl=d["cost_brl"],
    )
```

- [ ] **Step 8: Run query test to verify GREEN**

Run: `python -m pytest tests/unit/test_audit_quality_score_query.py -v`
Expected: ALL tests PASS.

### Integration test (RED → GREEN)

- [ ] **Step 9: Update integration test fake_rows + add F52-regression test**

Edit `tests/integration/test_audit_quality_score.py` — add `"ad_group_status": "ENABLED"` em CADA fake_row dict (linha 24-50 + linha 98-125). Pattern: after `"ad_group_name"` line, add `"ad_group_status": "ENABLED",` line.

Then ADD at end of file:

```python
@pytest.mark.asyncio
async def test_a2_orphan_keywords_in_removed_ad_groups_exposed(bound_context):
    """A2 (espelha F52): keywords flagged em ad_groups REMOVED appear with
    ad_group_status='REMOVED' na response, permitting consumer-side filter.

    Pattern idêntico ao F52 regression em audit_zombie_keywords (dogfood
    2026-05-25). Consumer pode filtrar `ad_group_status == 'ENABLED'` pra
    cleanup de impacto técnico real, OU manter tudo pra inventário cosmético.
    """
    from src.mcp.tools.audit_quality_score import audit_quality_score

    fake_rows = [
        {
            "ad_group_id": "2001",
            "ad_group_name": "GPA01_GERAL",
            "ad_group_status": "ENABLED",  # impactável
            "campaign_name": "GPA",
            "keyword_id": "K1",
            "keyword_text": "alpha",
            "match_type": "BROAD",
            "quality_score": 2,
            "impressions": 50,
            "clicks": 0,
            "conversions": 0,
            "cost_brl": 0.0,
        },
        {
            "ad_group_id": "174842025340",
            "ad_group_name": "DELL",
            "ad_group_status": "REMOVED",  # órfã cosmética
            "campaign_name": "JPA",
            "keyword_id": "K2",
            "keyword_text": "beta",
            "match_type": "BROAD",
            "quality_score": 1,
            "impressions": 30,
            "clicks": 0,
            "conversions": 0,
            "cost_brl": 0.0,
        },
    ]
    with patch(
        "src.mcp.tools.audit_quality_score.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await audit_quality_score({"customer_id": "1234567890"})

    assert result["total_flagged"] == 2
    # Sorted by QS ASC (1 antes de 2), so K2/DELL first
    assert result["flagged_keywords"][0]["ad_group_name"] == "DELL"
    assert result["flagged_keywords"][0]["ad_group_status"] == "REMOVED"
    assert result["flagged_keywords"][1]["ad_group_name"] == "GPA01_GERAL"
    assert result["flagged_keywords"][1]["ad_group_status"] == "ENABLED"

    # Consumer-side filter pattern documented em description A2
    impactable = [k for k in result["flagged_keywords"] if k["ad_group_status"] == "ENABLED"]
    assert len(impactable) == 1
    assert impactable[0]["keyword_text"] == "alpha"
```

- [ ] **Step 10: Run integration test to verify RED**

Run: `python -m pytest tests/integration/test_audit_quality_score.py -v`
Expected: New test FAILS with `KeyError: 'ad_group_status'` on result dict access (tool response shape doesn't expose field yet).

### Tool wrapper update (GREEN)

- [ ] **Step 11: Add ad_group_status to tool response shape + description warning**

Edit `src/mcp/tools/audit_quality_score.py`:

Linha ~75 (description) — replace entire description string:

```python
@register_tool(
    name="audit_quality_score",
    description=(
        "[CORE] Identifica keywords problemáticas com 3 flags acionáveis: "
        "candidate_pause (QS<=2 + impressions>=threshold + clicks=0 = waste), "
        "candidate_promote_exact (QS>=7 + BROAD + conv>=1 = promote pra EXACT "
        "reduz CPC), duplicate_intent (mesma keyword text em multi ad_groups, "
        "amplification only — só com outra flag ativa). Output flat list "
        "ordenada QS ASC + impressions DESC tie-break. Filtros: ad_group_ids[], "
        "min_impressions (default 10), limit (default 200, max 1000), date_range "
        "preset OR start_date+end_date custom (default LAST_30_DAYS). Sempre "
        "auditado. Nota: QS pode lagar entre queries (cache Google) — re-query "
        "se decisão crítica baseada em QS. ATENÇÃO (F52): keywords flagged podem "
        "estar em ad_groups REMOVED (órfãs cosméticas — não competem em leilão, "
        "não impactam QS/Smart Bidding). Cada row tem field `ad_group_status` "
        "— filtre `ad_group_status='ENABLED'` no consumer pra cleanup de impacto "
        "técnico real, OU mantenha tudo pra inventário cosmético."
    ),
    input_schema=_SCHEMA,
    bucket="always",
)
```

Linha ~153 (response `flagged_keywords[]` dict comprehension) — add `ad_group_status`:

```python
        "flagged_keywords": [
            {
                "ad_group_id": f.ad_group_id,
                "ad_group_name": f.ad_group_name,
                "ad_group_status": f.ad_group_status,  # A2 (espelha F52)
                "campaign_name": f.campaign_name,
                "keyword_id": f.keyword_id,
                "keyword_text": f.keyword_text,
                "match_type": f.match_type,
                "quality_score": f.quality_score,
                "impressions": f.impressions,
                "clicks": f.clicks,
                "conversions": f.conversions,
                "cost_brl": f.cost_brl,
                "flags": list(f.flags),
            }
            for f in flagged
        ],
```

- [ ] **Step 12: Run integration tests to verify GREEN**

Run: `python -m pytest tests/integration/test_audit_quality_score.py -v`
Expected: ALL tests PASS (existing + new `test_a2_orphan_keywords_in_removed_ad_groups_exposed`).

- [ ] **Step 13: Run full test suite for regression check**

Run: `python -m pytest tests/unit/test_flag_keywords.py tests/unit/test_audit_quality_score_query.py tests/integration/test_audit_quality_score.py -v`
Expected: ALL tests PASS.

- [ ] **Step 14: Commit Task 2**

```bash
git add src/google_ads/flag_keywords.py src/google_ads/queries/audit_quality_score.py src/mcp/tools/audit_quality_score.py tests/unit/test_flag_keywords.py tests/unit/test_audit_quality_score_query.py tests/integration/test_audit_quality_score.py
git commit -m "$(cat <<'EOF'
feat(mcp): A2 ad_group_status em audit_quality_score (espelha F52)

Replica pattern F52 cravado em audit_zombie_keywords (3b.38) pra
audit_quality_score: KeywordRow + FlaggedKeyword + query SELECT +
parser + dict_to_keyword_row + tool response + description warning.

Caller agora pode filtrar `ad_group_status='ENABLED'` client-side
pra distinguir keywords flagged em ad_groups ENABLED (impactáveis)
vs REMOVED (órfãs cosméticas — não competem em leilão).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: B9 — negative field em get_keyword_performance + warning F56

**Files:**
- Modify: `src/google_ads/queries/tactical.py:8-30` (keyword_performance_query SELECT)
- Modify: `src/mcp/tools/get_keyword_performance.py:60-133` (_row_formatter + description)
- Create: `tests/integration/test_get_keyword_performance.py` (NEW file)

### Test First (RED)

- [ ] **Step 1: Create integration test file with negative-field assertion**

Create `tests/integration/test_get_keyword_performance.py`:

```python
"""Integration tests for get_keyword_performance (Sprint 3b.40 B9)."""

from datetime import date
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
def bound_context():
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.asyncio
async def test_b9_negative_field_present_in_response(bound_context):
    """B9 (F56): cada row contém `negative: bool` field (true + false samples)."""
    from src.mcp.tools.get_keyword_performance import get_keyword_performance

    fake_rows = [
        {
            "criterion_id": "K1",
            "keyword_text": "gerador honda",
            "match_type": "BROAD",
            "status": "ENABLED",
            "negative": False,  # positive criterion
            "quality_score": 7,
            "quality_creative": "ABOVE_AVERAGE",
            "quality_post_click": "AVERAGE",
            "quality_search_predicted_ctr": "ABOVE_AVERAGE",
            "first_page_cpc_brl": 0.50,
            "top_of_page_cpc_brl": 1.20,
            "ad_group_id": "1001",
            "ad_group_name": "AG1",
            "campaign_id": "10",
            "campaign_name": "C1",
            "impressions": 100,
            "clicks": 10,
            "cost_brl": 5.00,
            "conversions": 1.0,
            "conversions_value_brl": 50.0,
            "ctr": 0.1,
            "cpc_brl": 0.50,
        },
        {
            "criterion_id": "K2",
            "keyword_text": "bobcat",
            "match_type": "BROAD",
            "status": "ENABLED",
            "negative": True,  # negative ad_group_criterion ENABLED
            "quality_score": None,
            "quality_creative": None,
            "quality_post_click": None,
            "quality_search_predicted_ctr": None,
            "first_page_cpc_brl": None,
            "top_of_page_cpc_brl": None,
            "ad_group_id": "1001",
            "ad_group_name": "AG1",
            "campaign_id": "10",
            "campaign_name": "C1",
            "impressions": 0,
            "clicks": 0,
            "cost_brl": 0.0,
            "conversions": 0.0,
            "conversions_value_brl": 0.0,
            "ctr": 0.0,
            "cpc_brl": 0.0,
        },
    ]

    with patch(
        "src.mcp.tools.get_keyword_performance.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await get_keyword_performance(
            {
                "customer_id": "1234567890",
                "date_range": "LAST_30_DAYS",
            }
        )

    assert result["customer_id"] == "1234567890"
    assert len(result["rows"]) == 2

    # B9 (F56): assert negative field present + correct type
    assert result["rows"][0]["negative"] is False
    assert result["rows"][1]["negative"] is True

    # Consumer-side filter pattern (F56 mitigation)
    positive_only = [r for r in result["rows"] if not r["negative"]]
    assert len(positive_only) == 1
    assert positive_only[0]["keyword_text"] == "gerador honda"
```

- [ ] **Step 2: Run integration test to verify RED**

Run: `python -m pytest tests/integration/test_get_keyword_performance.py -v`
Expected: FAIL — depending on _row_formatter logic, either `KeyError: 'negative'` or `AttributeError` from row.ad_group_criterion.negative missing. Mock return passes through, so failure surfaces in assertion `result["rows"][0]["negative"] is False`.

### Query update (GREEN)

- [ ] **Step 3: Add ad_group_criterion.negative to SELECT clause**

Edit `src/google_ads/queries/tactical.py:8-30` — add line `ad_group_criterion.negative,` after `ad_group_criterion.status,`:

```python
def keyword_performance_query(start: date, end: date, status: str, limit: int) -> str:
    status_clause = "" if status == "all" else f"AND ad_group_criterion.status = '{status.upper()}'"
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
        WHERE {gaql_date_clause(start, end)} {status_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit}
    """.strip()
```

### Tool wrapper update (GREEN)

- [ ] **Step 4: Add negative field to _row_formatter + update description**

Edit `src/mcp/tools/get_keyword_performance.py:60-97` (_row_formatter) — add `"negative"` field after `"status"`:

```python
def _row_formatter(row: Any) -> dict[str, Any]:
    m = row.metrics
    qi = row.ad_group_criterion.quality_info
    pe = row.ad_group_criterion.position_estimates
    impr = int(m.impressions)
    clicks = int(m.clicks)
    cost_micros = int(m.cost_micros)
    return {
        "criterion_id": str(row.ad_group_criterion.criterion_id),
        "keyword_text": row.ad_group_criterion.keyword.text,
        "match_type": row.ad_group_criterion.keyword.match_type.name,
        "status": row.ad_group_criterion.status.name,
        "negative": bool(row.ad_group_criterion.negative),  # B9 (F56)
        "quality_score": int(qi.quality_score) if qi.quality_score else None,
        "quality_creative": qi.creative_quality_score.name if qi.creative_quality_score else None,
        "quality_post_click": qi.post_click_quality_score.name
        if qi.post_click_quality_score
        else None,
        "quality_search_predicted_ctr": qi.search_predicted_ctr.name
        if qi.search_predicted_ctr
        else None,
        "first_page_cpc_brl": micros_to_currency(pe.first_page_cpc_micros)
        if pe.first_page_cpc_micros
        else None,
        "top_of_page_cpc_brl": micros_to_currency(pe.top_of_page_cpc_micros)
        if pe.top_of_page_cpc_micros
        else None,
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": row.ad_group.name,
        "campaign_id": str(row.campaign.id),
        "campaign_name": row.campaign.name,
        "impressions": impr,
        "clicks": clicks,
        "cost_brl": micros_to_currency(cost_micros),
        "conversions": round(float(m.conversions), 2),
        "conversions_value_brl": round(float(m.conversions_value), 2),
        "ctr": round(clicks / impr, 4) if impr else 0.0,
        "cpc_brl": micros_to_currency(cost_micros / clicks) if clicks else 0.0,
    }
```

Linha 100-109 (description) — replace entire description string:

```python
@register_tool(
    name="get_keyword_performance",
    description=(
        "[DEFER] Performance por palavra-chave com Quality Score completo (3 componentes: "
        "creative, post_click, search_predicted_ctr) + estimativas de first_page_cpc "
        "e top_of_page_cpc. Filtros: status (enabled|paused|removed|all), limit. "
        "ATENÇÃO (F56): retorna positive E negative ad_group_criterion indistintamente. "
        "Cada row tem field `negative: bool` — filtre `negative=false` no consumer pra "
        "workflows de PAUSE/análise QS, OU use `audit_zombie_keywords`/`audit_quality_score` "
        "(filtram `negative=FALSE` server-side)."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
```

- [ ] **Step 5: Run integration test to verify GREEN**

Run: `python -m pytest tests/integration/test_get_keyword_performance.py -v`
Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/google_ads/queries/tactical.py src/mcp/tools/get_keyword_performance.py tests/integration/test_get_keyword_performance.py
git commit -m "$(cat <<'EOF'
feat(mcp): B9 negative field em get_keyword_performance + warning F56

Adiciona `negative: bool` na response de cada row + warning F56
na tool description. Caller pode filtrar client-side
`[r for r in rows if not r['negative']]` pra positive-only workflows.

Backward-compat total (Opção A+C). Tools audit_zombie_keywords e
audit_quality_score continuam filtrando server-side (negative=FALSE)
como recomendado pra workflows de PAUSE/QS.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: A1 — sample_keywords no dry-run update_keyword_status

**Files:**
- Create: `src/google_ads/queries/keyword_lookup.py` (NEW module)
- Create: `tests/unit/test_keyword_lookup.py` (NEW file)
- Create: `tests/integration/test_update_keyword_status.py` (NEW file)
- Modify: `src/mcp/tools/update_keyword_status.py:1-127` (top-level import + DRY_RUN branch)

### Unit tests first (RED)

- [ ] **Step 1: Create unit test file for keyword_lookup module**

Create `tests/unit/test_keyword_lookup.py`:

```python
"""Unit tests for src.google_ads.queries.keyword_lookup (Sprint 3b.40 A1)."""

import pytest

from src.google_ads.queries.keyword_lookup import (
    _lookup_row_formatter,
    build_keyword_text_lookup_query,
)


def test_build_query_dedups_and_sorts_ids():
    """Pairs com duplicates → IN clause dedupes, output ordered ASC."""
    pairs = [
        ("1001", "K2"),
        ("1002", "K1"),
        ("1001", "K3"),
        ("1001", "K2"),  # duplicate
    ]
    query = build_keyword_text_lookup_query(pairs)
    assert "FROM ad_group_criterion" in query
    # Dedup + sort
    assert "ad_group.id IN (1001, 1002)" in query
    assert "ad_group_criterion.criterion_id IN (K1, K2, K3)" in query
    # No date filter (resource is absolute state)
    assert "segments.date" not in query


def test_build_query_selects_required_fields():
    pairs = [("1001", "K1")]
    query = build_keyword_text_lookup_query(pairs)
    expected_fields = [
        "ad_group.id",
        "ad_group_criterion.criterion_id",
        "ad_group_criterion.keyword.text",
        "ad_group_criterion.keyword.match_type",
    ]
    for f in expected_fields:
        assert f in query, f"Missing field: {f}"


def test_build_query_empty_pairs_raises():
    with pytest.raises(ValueError, match="cannot be empty"):
        build_keyword_text_lookup_query([])


def test_lookup_row_formatter_extracts_fields():
    """Mock SDK row → dict with str types pra ids."""

    class FakeKeyword:
        text = "aluguel de airless"

        class match_type:  # noqa: N801
            name = "BROAD"

    class FakeCriterion:
        criterion_id = 12345
        keyword = FakeKeyword()

    class FakeAdGroup:
        id = 67890

    class FakeRow:
        ad_group = FakeAdGroup()
        ad_group_criterion = FakeCriterion()

    out = _lookup_row_formatter(FakeRow())
    assert out["ad_group_id"] == "67890"
    assert out["criterion_id"] == "12345"
    assert out["keyword_text"] == "aluguel de airless"
    assert out["match_type"] == "BROAD"
```

- [ ] **Step 2: Run unit test to verify RED**

Run: `python -m pytest tests/unit/test_keyword_lookup.py -v`
Expected: FAIL with `ImportError` or `ModuleNotFoundError: src.google_ads.queries.keyword_lookup`.

### Implementation helper module (GREEN)

- [ ] **Step 3: Create keyword_lookup.py module**

Create `src/google_ads/queries/keyword_lookup.py`:

```python
"""GAQL helper pra resolver criterion_id → keyword_text + match_type.

Usado por update_keyword_status dry-run preview (Sprint 3b.40 A1).
Returns partial dict if some pairs not found (no exception).
"""

from typing import Any
from uuid import UUID

from src.google_ads.reports import run_report


def build_keyword_text_lookup_query(
    keyword_pairs: list[tuple[str, str]],
) -> str:
    """Build GAQL pra fetch keyword_text + match_type per (ad_group_id, criterion_id).

    Args:
        keyword_pairs: list de (ad_group_id, criterion_id) — duplicates OK,
            query deduplicates implicit via IN clause + sort ASC for determinism.

    Returns:
        GAQL string sobre ad_group_criterion resource, sem date filter
        (resource é absolute state, não time-series).

    Raises:
        ValueError: if keyword_pairs is empty.

    Note: keyword_view é time-series (requires segments.date). ad_group_criterion
    é absolute state — não precisa date_range, mais barato.
    """
    if not keyword_pairs:
        raise ValueError("keyword_pairs cannot be empty")
    ad_group_ids = sorted({pair[0] for pair in keyword_pairs})
    criterion_ids = sorted({pair[1] for pair in keyword_pairs})
    ad_group_clause = ", ".join(ad_group_ids)
    criterion_clause = ", ".join(criterion_ids)
    return (
        "SELECT "
        "ad_group.id, "
        "ad_group_criterion.criterion_id, "
        "ad_group_criterion.keyword.text, "
        "ad_group_criterion.keyword.match_type "
        "FROM ad_group_criterion "
        f"WHERE ad_group.id IN ({ad_group_clause}) "
        f"AND ad_group_criterion.criterion_id IN ({criterion_clause})"
    )


def _lookup_row_formatter(row: Any) -> dict[str, Any]:
    """Parse SDK row → dict pra lookup index."""
    return {
        "ad_group_id": str(row.ad_group.id),
        "criterion_id": str(row.ad_group_criterion.criterion_id),
        "keyword_text": row.ad_group_criterion.keyword.text,
        "match_type": row.ad_group_criterion.keyword.match_type.name,
    }


async def fetch_keyword_texts(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    keyword_pairs: list[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, str]]:
    """Resolve (ad_group_id, criterion_id) → {keyword_text, match_type}.

    Used by update_keyword_status DRY_RUN path pra preview sample.
    Graceful: returns partial dict if some pairs not found (no exception).

    Returns:
        dict keyed by (ad_group_id, criterion_id) tuple. Missing pairs
        simply absent from dict — caller iterates pairs e checks presence
        via `.get()`.
    """
    if not keyword_pairs:
        return {}
    query = build_keyword_text_lookup_query(keyword_pairs)
    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_lookup_row_formatter,
        operation_name="keyword_text_lookup",
    )
    return {
        (r["ad_group_id"], r["criterion_id"]): {
            "keyword_text": r["keyword_text"],
            "match_type": r["match_type"],
        }
        for r in rows
    }
```

- [ ] **Step 4: Run unit tests to verify GREEN**

Run: `python -m pytest tests/unit/test_keyword_lookup.py -v`
Expected: ALL tests PASS (4 tests).

### Integration test for update_keyword_status (RED)

- [ ] **Step 5: Create integration test file for update_keyword_status DRY_RUN sample**

Create `tests/integration/test_update_keyword_status.py`:

```python
"""Integration tests for update_keyword_status (Sprint 3b.40 A1).

A1: DRY_RUN path (>5 keywords) inclui sample_keywords (top 5).
AUTO_APPLY path (<=5 keywords) NÃO inclui sample_keywords (sem preview).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.mcp.context import McpRequestContext, clear_current, set_current

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg: PostgresContainer):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


@pytest.fixture
def bound_context():
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.integration
async def test_a1_dry_run_with_more_than_5_keywords_includes_sample_top_5(
    db, bound_context
):
    """A1: 6 keywords → CONFIRM path → response inclui sample_keywords top 5 + sample_truncated=true."""
    from src.mcp.tools.update_keyword_status import update_keyword_status

    keywords = [{"ad_group_id": "1001", "criterion_id": str(i)} for i in range(1, 7)]

    fake_lookup = {
        ("1001", str(i)): {
            "keyword_text": f"keyword #{i}",
            "match_type": "BROAD",
        }
        for i in range(1, 7)
    }

    with (
        patch(
            "src.mcp.tools.update_keyword_status.validate_keyword_criterion_types",
            AsyncMock(return_value=None),  # pre-flight passa
        ),
        patch(
            "src.mcp.tools.update_keyword_status.fetch_keyword_texts",
            AsyncMock(return_value=fake_lookup),
        ),
    ):
        result = await update_keyword_status(
            {
                "customer_id": "1234567890",
                "keywords": keywords,
                "new_status": "PAUSED",
            }
        )

    assert result["status"] == "dry_run"
    assert "sample_keywords" in result
    assert len(result["sample_keywords"]) == 5  # top 5 fixo V0
    assert result["sample_truncated"] is True
    # Top 5 = primeiros 5 da lista caller (preserva intent caller-defined)
    assert result["sample_keywords"][0]["criterion_id"] == "1"
    assert result["sample_keywords"][0]["keyword_text"] == "keyword #1"
    assert result["sample_keywords"][0]["match_type"] == "BROAD"
    assert result["sample_keywords"][4]["criterion_id"] == "5"
    assert "confirmation_token" in result


@pytest.mark.integration
async def test_a1_auto_apply_with_5_or_fewer_keywords_omits_sample(db, bound_context):
    """A1: 3 keywords (≤5) → AUTO path → response NÃO contém sample_keywords."""
    from src.mcp.tools.update_keyword_status import update_keyword_status

    keywords = [{"ad_group_id": "1001", "criterion_id": str(i)} for i in range(1, 4)]

    fake_run_mutation = AsyncMock(
        return_value={"applied_count": 3, "provider_request_id": "fake-trace-id"}
    )

    with (
        patch(
            "src.mcp.tools.update_keyword_status.validate_keyword_criterion_types",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.update_keyword_status.run_mutation",
            fake_run_mutation,
        ),
    ):
        result = await update_keyword_status(
            {
                "customer_id": "1234567890",
                "keywords": keywords,
                "new_status": "PAUSED",
            }
        )

    assert result["status"] == "applied"
    assert "sample_keywords" not in result
    assert result["applied_count"] == 3


@pytest.mark.integration
async def test_a1_dry_run_with_partial_fetch_returns_none_for_missing(db, bound_context):
    """A1 edge: fetch retorna partial → sample_keywords contains None pra missing IDs."""
    from src.mcp.tools.update_keyword_status import update_keyword_status

    keywords = [{"ad_group_id": "1001", "criterion_id": str(i)} for i in range(1, 7)]

    # Fetch retorna apenas IDs 1, 2, 3 (4, 5, 6 missing)
    fake_lookup_partial = {
        ("1001", str(i)): {
            "keyword_text": f"keyword #{i}",
            "match_type": "BROAD",
        }
        for i in range(1, 4)
    }

    with (
        patch(
            "src.mcp.tools.update_keyword_status.validate_keyword_criterion_types",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.update_keyword_status.fetch_keyword_texts",
            AsyncMock(return_value=fake_lookup_partial),
        ),
    ):
        result = await update_keyword_status(
            {
                "customer_id": "1234567890",
                "keywords": keywords,
                "new_status": "PAUSED",
            }
        )

    assert result["status"] == "dry_run"
    assert len(result["sample_keywords"]) == 5
    # IDs 1, 2, 3 resolved
    assert result["sample_keywords"][0]["keyword_text"] == "keyword #1"
    assert result["sample_keywords"][2]["keyword_text"] == "keyword #3"
    # IDs 4, 5 missing → keyword_text/match_type = None, but ids preserved
    assert result["sample_keywords"][3]["keyword_text"] is None
    assert result["sample_keywords"][3]["match_type"] is None
    assert result["sample_keywords"][3]["criterion_id"] == "4"
    assert result["sample_keywords"][4]["keyword_text"] is None
    assert result["sample_keywords"][4]["criterion_id"] == "5"
```

- [ ] **Step 6: Run integration test to verify RED**

Run: `python -m pytest tests/integration/test_update_keyword_status.py -v`
Expected: ALL 3 tests FAIL. AUTO path may pass (no sample_keywords change), DRY_RUN tests fail with `KeyError: 'sample_keywords'` OR `ImportError: cannot import name 'fetch_keyword_texts' from 'src.mcp.tools.update_keyword_status'` (helper not wired yet).

### Tool wrapper update (GREEN)

- [ ] **Step 7: Wire fetch_keyword_texts + sample_keywords into update_keyword_status**

Edit `src/mcp/tools/update_keyword_status.py`:

Top imports (linha 1-12) — add `from src.google_ads.queries.keyword_lookup import fetch_keyword_texts`:

```python
# bucket: always
"""Tool: update_keyword_status - pause/enable/remove keywords."""

from typing import Any

from src.db import connection
from src.google_ads.mutations import run_mutation
from src.google_ads.queries._common import validate_keyword_criterion_types
from src.google_ads.queries.keyword_lookup import fetch_keyword_texts
from src.governance.blast_radius import RiskLevel, classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool
```

Add SAMPLE_SIZE constant after `_SCHEMA` (linha ~38):

```python
_SAMPLE_SIZE = 5  # A1: top 5 fixed V0 (configurable só se demanda real)
```

Modify the DRY_RUN branch (linhas 107-126) — após `create_pending` é OK, mas fetch deve ser antes do return. Substituir todo o bloco `pool = connection.get_pool()` até o `return {...}` final:

```python
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_keyword_status",
            payload=payload,
            blast_summary=summary,
        )

    # A1: fetch keyword_texts pra sample preview (top 5 da lista caller)
    text_index = await fetch_keyword_texts(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        keyword_pairs=keyword_pairs,
    )
    sample_keywords = []
    for ad_group_id, criterion_id in keyword_pairs[:_SAMPLE_SIZE]:
        text_info = text_index.get((ad_group_id, criterion_id), {})
        sample_keywords.append(
            {
                "ad_group_id": ad_group_id,
                "criterion_id": criterion_id,
                "keyword_text": text_info.get("keyword_text"),  # None se não resolvido
                "match_type": text_info.get("match_type"),
            }
        )

    return {
        "status": "dry_run",
        "operation": "update_keyword_status",
        "customer_id": customer_id,
        "blast_summary": summary,
        "sample_keywords": sample_keywords,
        "sample_truncated": target_count > _SAMPLE_SIZE,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
```

- [ ] **Step 8: Run integration tests to verify GREEN**

Run: `python -m pytest tests/integration/test_update_keyword_status.py -v`
Expected: ALL 3 tests PASS.

- [ ] **Step 9: Run all updated tests for regression**

Run: `python -m pytest tests/unit/test_keyword_lookup.py tests/integration/test_update_keyword_status.py tests/integration/test_get_keyword_performance.py tests/integration/test_audit_quality_score.py tests/unit/test_flag_keywords.py tests/unit/test_audit_quality_score_query.py -v`
Expected: ALL tests PASS.

- [ ] **Step 10: Commit Task 4**

```bash
git add src/google_ads/queries/keyword_lookup.py src/mcp/tools/update_keyword_status.py tests/unit/test_keyword_lookup.py tests/integration/test_update_keyword_status.py
git commit -m "$(cat <<'EOF'
feat(mcp): A1 sample_keywords no dry-run de update_keyword_status

Novo módulo src/google_ads/queries/keyword_lookup.py com helper
fetch_keyword_texts (resolve criterion_id → keyword_text+match_type
via single GAQL com IN clause sobre ad_group_criterion resource).

Tool update_keyword_status agora retorna sample_keywords (top 5
primeiros da lista caller) + sample_truncated flag no DRY_RUN path
(>5 keywords). AUTO_APPLY path (≤5) inalterado. Custo: ~100ms extra
fetch só em dry_run. Partial fetch fail graceful (keyword_text=None
preservando criterion_id+ad_group_id como fallback identifier).

Prevenção bug humano em batch mutation com TTL 10min sem reverter
(dogfood MO-JP 27/05 — Wellington aplicou 9 tokens PAUSE em batch
sem sanity check).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Pre-push gate + push deploy

- [ ] **Step 1: Run pre-push gate**

Run: `python scripts/check_pre_push.py`
Expected: `5/5 PASS` (ruff + format + mypy + unit + non-DB integration).

If any step FAILS, fix and re-run before push.

- [ ] **Step 2: Push to main**

Run: `git push origin main`
Expected: 4 commits pushed (catalog F56 + A2 + B9 + A1).

- [ ] **Step 3: Watch CI + Deploy**

Run: `gh run list --limit 5 && gh run watch <latest-run-id>`
Expected: CI + Deploy both GREEN within ~10-15 min.

- [ ] **Step 4: Verify production /health**

Run: `curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health`
Expected: `{"status":"ok",...}` 200.

---

## Task 6: Smoke runbook gen via subagent

- [ ] **Step 1: Dispatch smoke-runbook-generator subagent**

Use Agent tool with subagent_type=`smoke-runbook-generator` and prompt:

```
Generate docs/operacao/phase-3b-40-bootstrap.md smoke runbook for Sprint 3b.40
Quick Wins Mutate Safety (A1+B9+A2). 3 tests in MO-JP+CAB account (7862230676):

T1 (A2): audit_quality_score em MO-JP — verify cada flagged_keyword[] contém
field `ad_group_status` com valor PT-BR-mapped (ENABLED|PAUSED|REMOVED|UNKNOWN).
Bonus: filtrar consumer-side `ad_group_status=='ENABLED'` e contar.

T2 (B9): get_keyword_performance em MO-JP — verify cada row contém `negative: bool`
field. Mix esperado: maioria false + algumas true (Wellington documentou 39
negative ENABLED em CAB GERAL 27/05 — Cat C produtos únicos). Filter consumer-side
`[r for r in rows if not r['negative']]` e comparar count com `audit_zombie_keywords`.

T3 (A1): update_keyword_status em MO-JP com 6+ keywords (random sample de zumbis
safe-to-pause) — verify dry_run response contém `sample_keywords` top 5 +
`sample_truncated=true`. Cada sample contém ad_group_id+criterion_id+keyword_text+
match_type. Apply via apply_change(token=...) — verify aplica corretamente.

Source spec: docs/superpowers/specs/2026-05-27-sprint-3b-40-quick-wins-mutate-safety-design.md
```

- [ ] **Step 2: Review generated runbook**

Read `docs/operacao/phase-3b-40-bootstrap.md` and verify:
- 3 tests cover A1+B9+A2
- Each test has clear "verify" criteria
- MO-JP customer_id correto (`7862230676`)

- [ ] **Step 3: Commit smoke runbook**

```bash
git add docs/operacao/phase-3b-40-bootstrap.md
git commit -m "$(cat <<'EOF'
docs(runbook): phase-3b-40-bootstrap.md smoke runbook (A1+B9+A2)

3 testes T1-T3 em MO-JP+CAB (7862230676) cobrindo Sprint 3b.40:
- T1 (A2): ad_group_status em audit_quality_score
- T2 (B9): negative field em get_keyword_performance
- T3 (A1): sample_keywords + apply em update_keyword_status

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

- [ ] **Step 4: Wellington executes smoke manually**

User-driven step. Wellington runs T1-T3 in Claude Code session com MCP v4-ads connected, reports PASS/FAIL per test.

---

## Task 7: Signoff — sprint-history + CLAUDE.md updates

- [ ] **Step 1: Add Sprint 3b.40 row to sprint-history.md**

Read `docs/operacao/sprint-history.md` to find correct table + last row format.

Add new row at end of Google sprint table (or appropriate section):

```markdown
| 3b.40 | 2026-05-27 | Quick Wins Mutate Safety (A1+B9+A2) | 4 commits sequenciais: F56 catalog + A2 ad_group_status em audit_quality_score (replica F52 pattern) + B9 negative field em get_keyword_performance + A1 sample_keywords no dry-run de update_keyword_status via novo módulo keyword_lookup.py. ICE somado 2030 (dogfood MO-JP 27/05). Esforço ~4-6h. Smoke real 3/3 PASS em MO-JP. |
```

- [ ] **Step 2: Update CLAUDE.md — remove A1/B9/A2 from Pending + bump finding count**

Edit `CLAUDE.md`:

- Update header: "55 findings" → "56 findings (F1-F56 + A1-A6 + D1-D3)"
- In "Shipped" table, append row for Sprint 3b.40 ship
- In "Pending" section, remove any reference to dogfood 27/05 quick wins (B9+A1+A2) — they're now shipped
- Update "Quick-start próxima sessão" TL;DR — Sprint 3b.40 = last shipped, Sprint M.4 = next candidate

- [ ] **Step 3: Optionally commit dogfood doc**

If `docs/operacao/dogfood-2026-05-27-mestre-da-obra-jp-investigacao-senior.md` ainda untracked, decide whether to commit (gestor work doc):

```bash
git add docs/operacao/dogfood-2026-05-27-mestre-da-obra-jp-investigacao-senior.md
```

(Default: commit junto signoff. Skip se Wellington preferir keep untracked.)

- [ ] **Step 4: Pre-push gate + commit + push signoff**

Run: `python scripts/check_pre_push.py` → 5/5 PASS.

```bash
git add CLAUDE.md docs/operacao/sprint-history.md
git commit -m "$(cat <<'EOF'
docs: Sprint 3b.40 signoff — sprint-history + CLAUDE.md refresh

Sprint 3b.40 (Quick Wins Mutate Safety A1+B9+A2) shipped:
- F56 catalogado (56 unique findings agora)
- A2 ad_group_status em audit_quality_score (replica F52)
- B9 negative field em get_keyword_performance
- A1 sample_keywords no dry-run update_keyword_status

Próximo sprint candidato: M.4 (Meta breakdowns geo+device+hourly).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

- [ ] **Step 5: Watch final CI**

Run: `gh run watch <latest-run-id>`
Expected: CI GREEN. Production /health 200.

---

## Self-Review checklist

After completing all tasks:

- [ ] **Spec coverage:** Every section in spec has corresponding task? F56 catalog (Task 1), A2 (Task 2), B9 (Task 3), A1 (Task 4), smoke (Task 6), signoff (Task 7). ✅
- [ ] **Placeholder scan:** No TBD/TODO em code blocks. Every task has exact files + commands.
- [ ] **Type consistency:** `ad_group_status: str` em KeywordRow + FlaggedKeyword + parser + dict_to_keyword_row + tool response — consistent name. `negative: bool` em row_formatter + test assertions. `sample_keywords` + `sample_truncated` em response shape consistent.

---

## Estimated effort

| Task | Steps | Effort |
|---|---|---|
| Task 1 (F56 catalog) | 5 | 15 min |
| Task 2 (A2 ad_group_status) | 14 | 60-90 min |
| Task 3 (B9 negative field) | 6 | 30-45 min |
| Task 4 (A1 sample_keywords) | 10 | 90-120 min |
| Task 5 (pre-push + push) | 4 | 15-20 min (+ CI wait) |
| Task 6 (smoke runbook gen) | 4 | 15-30 min (+ Wellington smoke) |
| Task 7 (signoff docs) | 5 | 20-30 min |
| **Total** | **48 steps** | **~4-6h** |

---

*Plan produzido 2026-05-27 via skill `superpowers:writing-plans`. Cada task é commit atômico — bisect-friendly se regressão.*
