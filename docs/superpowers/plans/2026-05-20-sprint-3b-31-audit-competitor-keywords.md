# Sprint 3b.31 — `audit_competitor_keywords` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 53rd MCP tool `audit_competitor_keywords` que detecta gasto em concorrência (positive keywords ENABLED matching competitor brands + search terms com cost) + sugere negative keywords EXACT+PHRASE per matched brand. Resolves #6 ICE 432 dogfood MO-JP — detectou ~R$2k/mês waste real.

**Architecture:** Pure module match logic (`src/google_ads/competitor_analysis.py`) + 2 GAQL builders (`src/google_ads/queries/audit_competitor_keywords.py`) + tool wrapper com `asyncio.gather` paralelo. Read-only sensitive (audit_this_call=True em ambas calls). Substring case-insensitive match algorithm. Sem mutations — sugestões só.

**Tech Stack:** Python 3.12 stdlib only, pytest, ruff, mypy strict, google-ads SDK v24, asyncio.gather.

**Spec:** [`docs/superpowers/specs/2026-05-20-sprint-3b-31-audit-competitor-keywords-design.md`](../specs/2026-05-20-sprint-3b-31-audit-competitor-keywords-design.md)

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/google_ads/competitor_analysis.py` | **CREATE** | Pure module: 5 dataclasses + `normalize_brand` + `match_competitor_brands` function. Zero Google SDK imports. |
| `src/google_ads/queries/audit_competitor_keywords.py` | **CREATE** | 2 GAQL builders + 2 row parsers + 2 dict→dataclass converters. |
| `src/mcp/tools/audit_competitor_keywords.py` | **CREATE** | Tool wrapper: schema, register_tool, `asyncio.gather` orchestration. |
| `tests/unit/test_competitor_analysis.py` | **CREATE** | 14 unit tests pure (match logic + duplicate handling + truncate + suggested negatives). |
| `tests/unit/test_audit_competitor_keywords_query.py` | **CREATE** | 6 unit tests (GAQL builders + parsers). |
| `tests/integration/test_audit_competitor_keywords.py` | **CREATE** | 3 wire-up tests. |
| `tests/unit/test_tools_schemas.py` | **MODIFY** | Add `audit_competitor_keywords` em 2 expected sets. |
| `docs/operacao/phase-3b-31-bootstrap.md` | **CREATE** | Smoke runbook 8 cases via smoke-runbook-generator subagent. |

---

## Task A1: Pure competitor_analysis module + 14 unit tests

**Files:**
- Create: `src/google_ads/competitor_analysis.py`
- Create: `tests/unit/test_competitor_analysis.py`

**Recommended model:** sonnet (dataclasses + 14 testes + match logic + suggested negatives generation).

### A1 — Step 1: Write 4 initial failing tests (RED)

Create `tests/unit/test_competitor_analysis.py`:

```python
"""Unit tests for src.google_ads.competitor_analysis (Sprint 3b.31)."""

from src.google_ads.competitor_analysis import (
    KeywordRow,
    SearchTermRow,
    match_competitor_brands,
    normalize_brand,
)


def _make_kw(
    *,
    ad_group_id: str = "1001",
    ad_group_name: str = "AG1",
    campaign_name: str = "C1",
    keyword_id: str = "1",
    keyword_text: str = "kw",
    match_type: str = "BROAD",
) -> KeywordRow:
    return KeywordRow(
        ad_group_id=ad_group_id,
        ad_group_name=ad_group_name,
        campaign_name=campaign_name,
        keyword_id=keyword_id,
        keyword_text=keyword_text,
        match_type=match_type,
    )


def _make_st(
    *,
    search_term: str = "st",
    ad_group_name: str = "AG1",
    campaign_name: str = "C1",
    impressions: int = 100,
    clicks: int = 5,
    cost_brl: float = 10.0,
) -> SearchTermRow:
    return SearchTermRow(
        search_term=search_term,
        ad_group_name=ad_group_name,
        campaign_name=campaign_name,
        impressions=impressions,
        clicks=clicks,
        cost_brl=cost_brl,
    )


def test_empty_inputs_returns_empty_everything():
    matched_kw, matched_st, suggested, totals, total_cost = match_competitor_brands(
        keyword_rows=[],
        search_term_rows=[],
        competitor_brands=[],
        limit=200,
    )
    assert matched_kw == []
    assert matched_st == []
    assert suggested == []
    assert totals == {
        "positive_count": 0,
        "positive_truncated": False,
        "search_count": 0,
        "search_truncated": False,
        "suggested_count": 0,
    }
    assert total_cost == 0.0


def test_normalize_brand_strips_and_lowercases():
    assert normalize_brand(" Projecta ") == "projecta"
    assert normalize_brand("CASA DO CONSTRUTOR") == "casa do construtor"
    assert normalize_brand("  promina") == "promina"


def test_positive_keyword_substring_match():
    rows = [_make_kw(keyword_text="comprar projecta gerador")]
    matched_kw, _, _, totals, _ = match_competitor_brands(
        keyword_rows=rows,
        search_term_rows=[],
        competitor_brands=["projecta"],
        limit=200,
    )
    assert len(matched_kw) == 1
    assert matched_kw[0].matched_brand == "projecta"
    assert matched_kw[0].status == "ENABLED"
    assert totals["positive_count"] == 1


def test_positive_keyword_case_insensitive():
    """Brand 'Projecta' matches kw 'PROJECTA 5500' (both normalized lowercase)."""
    rows = [_make_kw(keyword_text="PROJECTA 5500")]
    matched_kw, _, _, _, _ = match_competitor_brands(
        keyword_rows=rows,
        search_term_rows=[],
        competitor_brands=["Projecta"],
        limit=200,
    )
    assert len(matched_kw) == 1
    assert matched_kw[0].matched_brand == "projecta"  # normalized
```

### A1 — Step 2: Run tests to verify they fail (RED)

Run: `python -m pytest tests/unit/test_competitor_analysis.py -v`

Expected: `ImportError: cannot import name 'KeywordRow' from 'src.google_ads.competitor_analysis'`

### A1 — Step 3: Create competitor_analysis module (GREEN)

Create `src/google_ads/competitor_analysis.py`:

```python
"""Pure client-side competitor brand matching (Sprint 3b.31).

Match algorithm: substring case-insensitive contra positive keywords +
search terms. Aggregate cost wasted + sugere negative keywords (EXACT +
PHRASE per brand matched).

Pure function, zero Google SDK imports — testable standalone.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KeywordRow:
    """Positive keyword da query keyword_view (negative=FALSE, status=ENABLED)."""

    ad_group_id: str
    ad_group_name: str
    campaign_name: str
    keyword_id: str
    keyword_text: str
    match_type: str  # "EXACT" | "PHRASE" | "BROAD"


@dataclass(frozen=True, slots=True)
class SearchTermRow:
    """Search term real query do search_term_view com metrics."""

    search_term: str
    ad_group_name: str
    campaign_name: str
    impressions: int
    clicks: int
    cost_brl: float


@dataclass(frozen=True, slots=True)
class MatchedKeyword:
    """KeywordRow + matched_brand + status."""

    ad_group_id: str
    ad_group_name: str
    campaign_name: str
    keyword_id: str
    keyword_text: str
    match_type: str
    matched_brand: str
    status: str  # always "ENABLED" em V0


@dataclass(frozen=True, slots=True)
class MatchedSearchTerm:
    """SearchTermRow + matched_brand."""

    search_term: str
    matched_brand: str
    ad_group_name: str
    campaign_name: str
    impressions: int
    clicks: int
    cost_brl: float


@dataclass(frozen=True, slots=True)
class SuggestedNegative:
    """Suggestion pra add_negative_keywords (V4 manual apply)."""

    text: str
    match_type: str  # "EXACT" | "PHRASE"
    reason: str


def normalize_brand(brand: str) -> str:
    """Lowercase + strip pra comparison consistente."""
    return brand.strip().lower()


def _find_matching_brand(text: str, normalized_brands: list[str]) -> str | None:
    """Return first brand (insertion order) que é substring de text.lower(), else None."""
    text_lower = text.lower()
    for brand in normalized_brands:
        if brand in text_lower:
            return brand
    return None


def match_competitor_brands(
    *,
    keyword_rows: list[KeywordRow],
    search_term_rows: list[SearchTermRow],
    competitor_brands: list[str],
    limit: int,
) -> tuple[
    list[MatchedKeyword],
    list[MatchedSearchTerm],
    list[SuggestedNegative],
    dict[str, int | bool],
    float,
]:
    """Match keywords + search terms vs brands; aggregate cost; suggest negatives.

    Pure function — zero Google SDK imports; testable standalone.

    Args:
        keyword_rows: positive keywords da query keyword_view (ENABLED + negative=FALSE).
        search_term_rows: search terms da query search_term_view (date-filtered).
        competitor_brands: lista de brand names (gestor passa marcas locais).
        limit: max entries por lista (positive_keywords + search_terms separadamente).

    Returns:
        Tuple of (matched_keywords_truncated, matched_search_terms_truncated,
                  suggested_negatives, totals_dict, total_cost_wasted_brl).

        totals_dict keys: positive_count, positive_truncated, search_count,
                          search_truncated, suggested_count.
    """
    # 1. Normalize brands (preserve insertion order)
    normalized = [normalize_brand(b) for b in competitor_brands]

    # 2. Match positive keywords
    matched_kw: list[MatchedKeyword] = []
    for row in keyword_rows:
        brand = _find_matching_brand(row.keyword_text, normalized)
        if brand:
            matched_kw.append(
                MatchedKeyword(
                    ad_group_id=row.ad_group_id,
                    ad_group_name=row.ad_group_name,
                    campaign_name=row.campaign_name,
                    keyword_id=row.keyword_id,
                    keyword_text=row.keyword_text,
                    match_type=row.match_type,
                    matched_brand=brand,
                    status="ENABLED",
                )
            )

    # 3. Match search terms + aggregate cost
    matched_st: list[MatchedSearchTerm] = []
    total_cost = 0.0
    for row in search_term_rows:
        brand = _find_matching_brand(row.search_term, normalized)
        if brand:
            matched_st.append(
                MatchedSearchTerm(
                    search_term=row.search_term,
                    matched_brand=brand,
                    ad_group_name=row.ad_group_name,
                    campaign_name=row.campaign_name,
                    impressions=row.impressions,
                    clicks=row.clicks,
                    cost_brl=row.cost_brl,
                )
            )
            total_cost += row.cost_brl

    # 4. Sort
    matched_kw.sort(key=lambda k: (k.matched_brand, k.ad_group_name))
    matched_st.sort(key=lambda s: -s.cost_brl)

    # 5. Per-brand stats pra suggested_negatives reasons
    pos_count: dict[str, int] = {}
    st_count: dict[str, int] = {}
    st_cost: dict[str, float] = {}
    for k in matched_kw:
        pos_count[k.matched_brand] = pos_count.get(k.matched_brand, 0) + 1
    for s in matched_st:
        st_count[s.matched_brand] = st_count.get(s.matched_brand, 0) + 1
        st_cost[s.matched_brand] = st_cost.get(s.matched_brand, 0.0) + s.cost_brl

    # 6. Suggested negatives — apenas pra brands com hit (alphabetical)
    suggested: list[SuggestedNegative] = []
    matched_brands_with_hit = sorted(set(pos_count.keys()) | set(st_count.keys()))
    for brand in matched_brands_with_hit:
        p = pos_count.get(brand, 0)
        st = st_count.get(brand, 0)
        cost = st_cost.get(brand, 0.0)
        suggested.append(
            SuggestedNegative(
                text=brand,
                match_type="EXACT",
                reason=(
                    f"Brand competidora encontrada em {p} keyword(s) positive "
                    f"+ {st} search term(s) (R$ {cost:.2f} cost)"
                ),
            )
        )
        suggested.append(
            SuggestedNegative(
                text=brand,
                match_type="PHRASE",
                reason="Brand competidora — PHRASE bloqueia qualquer query contendo o termo",
            )
        )

    # 7. Truncate + build totals
    pos_total = len(matched_kw)
    st_total = len(matched_st)
    totals: dict[str, int | bool] = {
        "positive_count": pos_total,
        "positive_truncated": pos_total > limit,
        "search_count": st_total,
        "search_truncated": st_total > limit,
        "suggested_count": len(suggested),
    }

    return (
        matched_kw[:limit],
        matched_st[:limit],
        suggested,
        totals,
        total_cost,
    )
```

### A1 — Step 4: Run 4 tests to verify GREEN

Run: `python -m pytest tests/unit/test_competitor_analysis.py -v`

Expected: 4 passed.

### A1 — Step 5: Add remaining 10 tests

Append to `tests/unit/test_competitor_analysis.py`:

```python
def test_no_matches_returns_empty_with_brands():
    """Brands passed mas zero matches → empty everything + no suggested."""
    rows = [_make_kw(keyword_text="kw normal sem brand")]
    matched_kw, matched_st, suggested, totals, total_cost = match_competitor_brands(
        keyword_rows=rows,
        search_term_rows=[_make_st(search_term="normal query")],
        competitor_brands=["projecta", "promina"],
        limit=200,
    )
    assert matched_kw == []
    assert matched_st == []
    assert suggested == []
    assert totals["positive_count"] == 0
    assert total_cost == 0.0


def test_search_term_match_aggregates_cost():
    """3 search_terms matched, costs [10, 20, 30] → total 60.0."""
    rows = [
        _make_st(search_term="gerador projecta 1", cost_brl=10.0),
        _make_st(search_term="projecta 5500", cost_brl=20.0),
        _make_st(search_term="comprar projecta", cost_brl=30.0),
    ]
    _, matched_st, _, _, total_cost = match_competitor_brands(
        keyword_rows=[],
        search_term_rows=rows,
        competitor_brands=["projecta"],
        limit=200,
    )
    assert len(matched_st) == 3
    assert total_cost == 60.0


def test_suggested_negatives_2_per_matched_brand():
    """1 brand matched → 2 sugestões (EXACT + PHRASE)."""
    rows = [_make_kw(keyword_text="comprar projecta")]
    _, _, suggested, _, _ = match_competitor_brands(
        keyword_rows=rows,
        search_term_rows=[],
        competitor_brands=["projecta"],
        limit=200,
    )
    assert len(suggested) == 2
    assert suggested[0].text == "projecta"
    assert suggested[0].match_type == "EXACT"
    assert suggested[1].text == "projecta"
    assert suggested[1].match_type == "PHRASE"


def test_suggested_negatives_skip_brand_without_matches():
    """Brand 'promina' passada mas zero match → NÃO incluída em suggested."""
    rows = [_make_kw(keyword_text="comprar projecta")]
    _, _, suggested, _, _ = match_competitor_brands(
        keyword_rows=rows,
        search_term_rows=[],
        competitor_brands=["projecta", "promina"],
        limit=200,
    )
    assert len(suggested) == 2  # Only projecta (EXACT + PHRASE)
    assert all(s.text == "projecta" for s in suggested)


def test_keyword_matched_by_first_brand_when_multiple_overlap():
    """Brands ['projecta', 'comprar'], kw 'comprar projecta' → matched_brand='projecta' (insertion order)."""
    rows = [_make_kw(keyword_text="comprar projecta")]
    matched_kw, _, _, _, _ = match_competitor_brands(
        keyword_rows=rows,
        search_term_rows=[],
        competitor_brands=["projecta", "comprar"],
        limit=200,
    )
    assert len(matched_kw) == 1
    assert matched_kw[0].matched_brand == "projecta"  # first in normalized order


def test_search_terms_sorted_by_cost_desc():
    """3 search_terms costs [50, 10, 30] → output [50, 30, 10]."""
    rows = [
        _make_st(search_term="projecta a", cost_brl=10.0),
        _make_st(search_term="projecta b", cost_brl=50.0),
        _make_st(search_term="projecta c", cost_brl=30.0),
    ]
    _, matched_st, _, _, _ = match_competitor_brands(
        keyword_rows=[],
        search_term_rows=rows,
        competitor_brands=["projecta"],
        limit=200,
    )
    assert [s.cost_brl for s in matched_st] == [50.0, 30.0, 10.0]


def test_truncate_positive_keywords_at_limit():
    """250 matches + limit=200 → 200 returned, totals=250."""
    rows = [_make_kw(keyword_id=str(i), keyword_text=f"projecta {i}") for i in range(250)]
    matched_kw, _, _, totals, _ = match_competitor_brands(
        keyword_rows=rows,
        search_term_rows=[],
        competitor_brands=["projecta"],
        limit=200,
    )
    assert len(matched_kw) == 200
    assert totals["positive_count"] == 250
    assert totals["positive_truncated"] is True


def test_truncate_search_terms_at_limit():
    """250 matched search_terms + limit=200 → 200 returned, totals=250."""
    rows = [_make_st(search_term=f"projecta {i}", cost_brl=1.0) for i in range(250)]
    _, matched_st, _, totals, _ = match_competitor_brands(
        keyword_rows=[],
        search_term_rows=rows,
        competitor_brands=["projecta"],
        limit=200,
    )
    assert len(matched_st) == 200
    assert totals["search_count"] == 250
    assert totals["search_truncated"] is True


def test_reason_string_includes_counts_and_cost():
    """Brand com 2 pos + 3 st (R$95.50) → reason text contém '2', '3', '95.50'."""
    pos_rows = [
        _make_kw(keyword_id="A", keyword_text="projecta 1"),
        _make_kw(keyword_id="B", keyword_text="comprar projecta"),
    ]
    st_rows = [
        _make_st(search_term="projecta a", cost_brl=30.0),
        _make_st(search_term="projecta b", cost_brl=25.50),
        _make_st(search_term="projecta c", cost_brl=40.0),
    ]
    _, _, suggested, _, _ = match_competitor_brands(
        keyword_rows=pos_rows,
        search_term_rows=st_rows,
        competitor_brands=["projecta"],
        limit=200,
    )
    exact = suggested[0]  # EXACT primeiro
    assert exact.match_type == "EXACT"
    assert "2 keyword" in exact.reason
    assert "3 search term" in exact.reason
    assert "95.50" in exact.reason


def test_brand_minimum_length_documented_not_enforced_at_pure_layer():
    """Brand 'MO' 2 chars passa em pure layer (schema upstream enforces minLength 3).

    Documenta contrato: validação de brand length é responsabilidade do schema,
    não do pure module. Tool MCP rejeita brand < 3 chars via input_schema.
    """
    rows = [_make_kw(keyword_text="MO equipamentos")]
    matched_kw, _, _, _, _ = match_competitor_brands(
        keyword_rows=rows,
        search_term_rows=[],
        competitor_brands=["MO"],
        limit=200,
    )
    # Pure module ainda matches; caller é responsável por validar input.
    assert len(matched_kw) == 1
```

### A1 — Step 6: Run all 14 tests

Run: `python -m pytest tests/unit/test_competitor_analysis.py -v`

Expected: 14 passed.

### A1 — Step 7: Pre-commit gate

Run: `python scripts/check_pre_push.py`

Expected: 5/5 PASS.

### A1 — Step 8: Commit

```bash
git add src/google_ads/competitor_analysis.py tests/unit/test_competitor_analysis.py
git commit -m "$(cat <<'EOF'
feat(competitor_analysis): pure brand match module (Sprint 3b.31 A1)

Pure function match_competitor_brands que detecta gasto em concorrencia:
- Positive keywords ENABLED matching brand (substring case-insensitive)
- Search terms com cost matching brand
- Cost real aggregate
- Suggested negatives EXACT + PHRASE per matched brand (apenas brands com hit)

5 dataclasses frozen+slots: KeywordRow, SearchTermRow, MatchedKeyword,
MatchedSearchTerm, SuggestedNegative.

Sort:
- matched_keywords: matched_brand ASC, ad_group_name ASC
- matched_search_terms: cost_brl DESC

normalize_brand: lowercase + strip helper. Insertion order preserva
quando multiple brands match (first brand wins).

14 unit tests cobrem: empty, no matches, normalize, substring,
case-insensitive, aggregate cost, suggested 2-per-brand, skip zero-match
brands, multiple brands first-match, sort cost desc, truncate kw + st,
reason text format, short brand documentation.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A2: GAQL builders + parsers + 6 unit tests

**Files:**
- Create: `src/google_ads/queries/audit_competitor_keywords.py`
- Create: `tests/unit/test_audit_competitor_keywords_query.py`

**Recommended model:** sonnet (2 builders + 2 parsers + 6 tests).

### A2 — Step 1: Write 3 initial failing tests (RED)

Create `tests/unit/test_audit_competitor_keywords_query.py`:

```python
"""Unit tests for src.google_ads.queries.audit_competitor_keywords (Sprint 3b.31)."""

from src.google_ads.queries.audit_competitor_keywords import (
    build_positive_keywords_query,
    build_search_terms_query,
)


def test_positive_keywords_query_includes_status_enabled_and_negative_false():
    query = build_positive_keywords_query()
    assert "FROM keyword_view" in query
    assert "ad_group_criterion.status = 'ENABLED'" in query
    assert "ad_group_criterion.negative = FALSE" in query


def test_positive_keywords_query_no_date_filter():
    """State-based query — sem segments.date BETWEEN."""
    query = build_positive_keywords_query()
    assert "segments.date" not in query
    assert "BETWEEN" not in query


def test_search_terms_query_includes_date_between():
    query = build_search_terms_query(start_date="2026-05-13", end_date="2026-05-19")
    assert "FROM search_term_view" in query
    assert "segments.date BETWEEN '2026-05-13' AND '2026-05-19'" in query
```

### A2 — Step 2: Verify tests fail

Run: `python -m pytest tests/unit/test_audit_competitor_keywords_query.py -v`

Expected: ImportError on `build_positive_keywords_query`.

### A2 — Step 3: Create GAQL builders + parsers module

Create `src/google_ads/queries/audit_competitor_keywords.py`:

```python
"""GAQL builders + row parsers for audit_competitor_keywords (Sprint 3b.31)."""

from typing import Any

from src.google_ads.competitor_analysis import KeywordRow, SearchTermRow


def build_positive_keywords_query() -> str:
    """GAQL pra keyword_view: positive ENABLED keywords (state-based, sem date filter).

    Hardcoded filters per spec section 2:
    - ad_group_criterion.status = 'ENABLED' (current actionable only)
    - ad_group_criterion.negative = FALSE (apenas positive criteria — negative
      criteria não pagam, então não interessam pra audit de waste).
    """
    return (
        "SELECT "
        "ad_group.id, ad_group.name, campaign.name, "
        "ad_group_criterion.criterion_id, "
        "ad_group_criterion.keyword.text, "
        "ad_group_criterion.keyword.match_type "
        "FROM keyword_view "
        "WHERE ad_group_criterion.status = 'ENABLED' "
        "AND ad_group_criterion.negative = FALSE"
    )


def build_search_terms_query(*, start_date: str, end_date: str) -> str:
    """GAQL pra search_term_view: search terms entregues no date window.

    Args:
        start_date, end_date: YYYY-MM-DD (resolved via resolve_date_window upstream).
    """
    return (
        "SELECT "
        "search_term_view.search_term, "
        "ad_group.name, campaign.name, "
        "metrics.impressions, metrics.clicks, metrics.cost_micros "
        "FROM search_term_view "
        f"WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'"
    )


def parse_positive_keyword_row(row: Any) -> dict[str, Any]:
    """Parse SDK row → dict matching KeywordRow fields (run_report contract)."""
    # match_type enum em v24: SDK exposes .name attribute
    match_type_str = row.ad_group_criterion.keyword.match_type.name
    return {
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": row.ad_group.name,
        "campaign_name": row.campaign.name,
        "keyword_id": str(row.ad_group_criterion.criterion_id),
        "keyword_text": row.ad_group_criterion.keyword.text,
        "match_type": match_type_str,
    }


def parse_search_term_row(row: Any) -> dict[str, Any]:
    """Parse SDK row → dict matching SearchTermRow fields."""
    return {
        "search_term": row.search_term_view.search_term,
        "ad_group_name": row.ad_group.name,
        "campaign_name": row.campaign.name,
        "impressions": row.metrics.impressions,
        "clicks": row.metrics.clicks,
        "cost_brl": row.metrics.cost_micros / 1_000_000.0,
    }


def dict_to_keyword_row(d: dict[str, Any]) -> KeywordRow:
    """Convert parsed dict back to KeywordRow dataclass at tool wrapper boundary."""
    return KeywordRow(
        ad_group_id=d["ad_group_id"],
        ad_group_name=d["ad_group_name"],
        campaign_name=d["campaign_name"],
        keyword_id=d["keyword_id"],
        keyword_text=d["keyword_text"],
        match_type=d["match_type"],
    )


def dict_to_search_term_row(d: dict[str, Any]) -> SearchTermRow:
    """Convert parsed dict back to SearchTermRow dataclass at tool wrapper boundary."""
    return SearchTermRow(
        search_term=d["search_term"],
        ad_group_name=d["ad_group_name"],
        campaign_name=d["campaign_name"],
        impressions=d["impressions"],
        clicks=d["clicks"],
        cost_brl=d["cost_brl"],
    )
```

### A2 — Step 4: Verify 3 tests pass

Run: `python -m pytest tests/unit/test_audit_competitor_keywords_query.py -v`

Expected: 3 passed.

### A2 — Step 5: Add 3 remaining tests

Append to `tests/unit/test_audit_competitor_keywords_query.py`:

```python
def test_positive_keywords_query_selects_required_fields():
    """6 fields necessários pra KeywordRow."""
    query = build_positive_keywords_query()
    expected_fields = [
        "ad_group.id",
        "ad_group.name",
        "campaign.name",
        "ad_group_criterion.criterion_id",
        "ad_group_criterion.keyword.text",
        "ad_group_criterion.keyword.match_type",
    ]
    for f in expected_fields:
        assert f in query, f"Missing field: {f}"


def test_search_terms_query_selects_required_fields():
    """6 fields necessários pra SearchTermRow."""
    query = build_search_terms_query(start_date="2026-05-13", end_date="2026-05-19")
    expected_fields = [
        "search_term_view.search_term",
        "ad_group.name",
        "campaign.name",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
    ]
    for f in expected_fields:
        assert f in query, f"Missing field: {f}"


def test_parse_keyword_row_handles_match_type_enum():
    """match_type.name extrai string enum (BROAD/PHRASE/EXACT)."""
    from unittest.mock import MagicMock

    from src.google_ads.queries.audit_competitor_keywords import parse_positive_keyword_row

    fake_row = MagicMock()
    fake_row.ad_group.id = 1001
    fake_row.ad_group.name = "AG1"
    fake_row.campaign.name = "C1"
    fake_row.ad_group_criterion.criterion_id = 42
    fake_row.ad_group_criterion.keyword.text = "comprar projecta"
    fake_row.ad_group_criterion.keyword.match_type.name = "BROAD"

    parsed = parse_positive_keyword_row(fake_row)
    assert parsed["ad_group_id"] == "1001"
    assert parsed["keyword_id"] == "42"
    assert parsed["keyword_text"] == "comprar projecta"
    assert parsed["match_type"] == "BROAD"
```

### A2 — Step 6: Verify 6 tests pass

Run: `python -m pytest tests/unit/test_audit_competitor_keywords_query.py -v`

Expected: 6 passed.

### A2 — Step 7: Pre-commit gate

Run: `python scripts/check_pre_push.py`

Expected: 5/5 PASS.

### A2 — Step 8: Commit

```bash
git add src/google_ads/queries/audit_competitor_keywords.py tests/unit/test_audit_competitor_keywords_query.py
git commit -m "$(cat <<'EOF'
feat(queries): GAQL builders audit_competitor_keywords (Sprint 3b.31 A2)

2 GAQL builders + 2 row parsers + 2 dict-to-dataclass converters:
- build_positive_keywords_query() — state-based keyword_view (status=ENABLED
  + negative=FALSE; sem date filter)
- build_search_terms_query(start_date, end_date) — search_term_view com
  date BETWEEN
- parse_positive_keyword_row / parse_search_term_row — SDK row → dict
  (run_report contract)
- dict_to_keyword_row / dict_to_search_term_row — boundary conversion
  pra KeywordRow/SearchTermRow dataclasses (A1 module)

cost_micros / 1_000_000.0 conversion → cost_brl decimal.

6 unit tests: filtros hardcoded positive query, no date filter positive,
date filter search, fields completos ambas, parse keyword match_type enum.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A3: Tool wrapper + schema + asyncio.gather

**Files:**
- Create: `src/mcp/tools/audit_competitor_keywords.py`
- Modify: `tests/unit/test_tools_schemas.py` (add em 2 lists alfabéticas)

**Recommended model:** sonnet (paralelismo asyncio.gather + schema judgment).

### A3 — Step 1: Create tool wrapper

Create `src/mcp/tools/audit_competitor_keywords.py`:

```python
"""Tool: audit_competitor_keywords — detect competitor brand spending.

Sprint 3b.31 — #6 fila ICE 432 do dogfood MO-JP 2026-05-19.
Detecta gasto em concorrência: positive keywords matching brands + search
terms com cost + sugere negative keywords EXACT+PHRASE per matched brand.
"""

import asyncio
from datetime import datetime
from typing import Any

from src.google_ads.competitor_analysis import match_competitor_brands
from src.google_ads.queries.audit_competitor_keywords import (
    build_positive_keywords_query,
    build_search_terms_query,
    dict_to_keyword_row,
    dict_to_search_term_row,
    parse_positive_keyword_row,
    parse_search_term_row,
)
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._common import resolve_date_window
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "competitor_brands": {
            "type": "array",
            "items": {"type": "string", "minLength": 3, "maxLength": 50},
            "minItems": 1,
            "maxItems": 20,
            "description": (
                "Lista de brand names competidoras pra detectar match. "
                "Min 3 chars cada pra evitar false positives. Max 20 brands. "
                "Match: substring case-insensitive em keyword text + search term."
            ),
        },
        "date_range": {
            "type": "string",
            "enum": ["LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS", "LAST_90_DAYS"],
            "default": "LAST_7_DAYS",
            "description": "Preset. Override por start_date+end_date se ambos passados.",
        },
        "start_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "end_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 200,
            "description": (
                "Máximo entries por lista (positive_keywords e search_terms). "
                "truncated:true se exceder."
            ),
        },
    },
    "required": ["customer_id", "competitor_brands"],
    "additionalProperties": False,
}


@register_tool(
    name="audit_competitor_keywords",
    description=(
        "Detecta gasto em concorrência: keywords positivas ENABLED com text "
        "matching competitor brands + search terms entregues no date window que "
        "matched brand competidora. Output: 2 listas + summary (total cost wasted "
        "real) + suggested_negatives (EXACT + PHRASE per matched brand). Filtros: "
        "competitor_brands[] required (3-50 chars cada, 1-20 brands), date_range "
        "preset OR start_date+end_date custom (default LAST_7_DAYS), limit (default "
        "200, max 1000). Match: substring case-insensitive em keyword text + search "
        "term. Sempre auditado. Nota: cost data Google pode lagar entre queries — "
        "re-query se decisão crítica."
    ),
    input_schema=_SCHEMA,
)
async def audit_competitor_keywords(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    competitor_brands = args["competitor_brands"]
    limit = args.get("limit", 200)

    start_date, end_date = resolve_date_window(args)

    pos_query = build_positive_keywords_query()
    st_query = build_search_terms_query(start_date=start_date, end_date=end_date)

    # Parallel via asyncio.gather (latency reduction — 2 queries independent)
    pos_raw, st_raw = await asyncio.gather(
        run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=pos_query,
            row_formatter=parse_positive_keyword_row,
            operation_name="audit_competitor_keywords",
            audit_this_call=True,
            params_summary={
                "phase": "positive_keywords",
                "competitor_brands": competitor_brands,
                "limit": limit,
            },
        ),
        run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=st_query,
            row_formatter=parse_search_term_row,
            operation_name="audit_competitor_keywords",
            audit_this_call=True,
            params_summary={
                "phase": "search_terms",
                "competitor_brands": competitor_brands,
                "date_window": f"{start_date} to {end_date}",
                "limit": limit,
            },
        ),
    )

    keyword_rows = [dict_to_keyword_row(d) for d in pos_raw]
    search_term_rows = [dict_to_search_term_row(d) for d in st_raw]

    matched_kw, matched_st, suggested, totals, total_cost = match_competitor_brands(
        keyword_rows=keyword_rows,
        search_term_rows=search_term_rows,
        competitor_brands=competitor_brands,
        limit=limit,
    )

    days = (
        datetime.strptime(end_date, "%Y-%m-%d").date()
        - datetime.strptime(start_date, "%Y-%m-%d").date()
    ).days + 1

    return {
        "customer_id": customer_id,
        "date_range_resolved": {
            "start": start_date,
            "end": end_date,
            "days": days,
        },
        "competitor_brands": competitor_brands,
        "summary": {
            "positive_keywords_count": totals["positive_count"],
            "positive_keywords_truncated": totals["positive_truncated"],
            "search_terms_count": totals["search_count"],
            "search_terms_truncated": totals["search_truncated"],
            "total_cost_wasted_brl": total_cost,
            "suggested_negatives_count": totals["suggested_count"],
        },
        "positive_keywords": [
            {
                "ad_group_id": k.ad_group_id,
                "ad_group_name": k.ad_group_name,
                "campaign_name": k.campaign_name,
                "keyword_id": k.keyword_id,
                "keyword_text": k.keyword_text,
                "match_type": k.match_type,
                "matched_brand": k.matched_brand,
                "status": k.status,
            }
            for k in matched_kw
        ],
        "search_terms": [
            {
                "search_term": s.search_term,
                "matched_brand": s.matched_brand,
                "ad_group_name": s.ad_group_name,
                "campaign_name": s.campaign_name,
                "impressions": s.impressions,
                "clicks": s.clicks,
                "cost_brl": s.cost_brl,
            }
            for s in matched_st
        ],
        "suggested_negatives": [
            {
                "text": n.text,
                "match_type": n.match_type,
                "reason": n.reason,
            }
            for n in suggested
        ],
    }
```

### A3 — Step 2: Update test_tools_schemas.py — add audit_competitor_keywords em 2 lists

**File:** `tests/unit/test_tools_schemas.py`

In BOTH functions (`test_all_phase_2_tools_registered` ~linha 91 e `test_no_unexpected_tools` ~linha 163), add `"audit_competitor_keywords",` alphabetically. Place após `"audit_quality_score",` se já presente, ou antes de `"bulk_pause_by_query",`.

Exact line (8 spaces indent):
```python
        "audit_competitor_keywords",
```

Read the file first to confirm placement.

### A3 — Step 3: Run schema regression tests

Run: `python -m pytest tests/unit/test_tools_schemas.py -v`

Expected: all PASS. `test_registered_tool_count_matches_files_on_disk` deve verificar 53 == 53 (pkgutil auto-discovery).

### A3 — Step 4: Pre-commit gate

Run: `python scripts/check_pre_push.py`

Expected: 5/5 PASS.

### A3 — Step 5: Commit

```bash
git add src/mcp/tools/audit_competitor_keywords.py tests/unit/test_tools_schemas.py
git commit -m "$(cat <<'EOF'
feat(audit_competitor_keywords): tool wrapper + schema (Sprint 3b.31 A3)

Tool MCP audit_competitor_keywords (53rd tool) orquestra:
- resolve_date_window (Sprint 3b.20 helper)
- build_positive_keywords_query + build_search_terms_query (A2)
- asyncio.gather PARALELO em 2 chamadas run_report (latency reduction
  — 2 queries independent)
- audit_this_call=True em ambas calls (sensitive read)
- dict_to_keyword_row + dict_to_search_term_row boundary conversion
- match_competitor_brands pure (A1) com competitor_brands + limit
- shape build com date_range_resolved + summary + 3 listas + suggested

Schema: customer_id (req) + competitor_brands[] (1-20, minLength 3-50)
+ min_impressions removido (não aplica) + date_range preset OR custom
+ limit (default 200, max 1000).

Description menciona match algorithm + 3 outputs + lag warning cost.

Tool count: 52 → 53. test_all_phase_2_tools_registered + test_no_
unexpected_tools atualizados.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A4: Integration tests + smoke runbook

**Files:**
- Create: `tests/integration/test_audit_competitor_keywords.py`
- Create: `docs/operacao/phase-3b-31-bootstrap.md`

**Recommended model:** sonnet (mock patterns + asyncio.gather assertion + smoke-runbook-generator dispatch).

### A4 — Step 1: Write 3 integration tests

Create `tests/integration/test_audit_competitor_keywords.py`:

```python
"""Integration tests for audit_competitor_keywords (Sprint 3b.31)."""

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
async def test_returns_full_shape_with_matched_brands(bound_context):
    """Wire-up: fake rows → output shape match spec section 3.2."""
    from src.mcp.tools.audit_competitor_keywords import audit_competitor_keywords

    fake_pos_rows = [
        {
            "ad_group_id": "1001",
            "ad_group_name": "AG1",
            "campaign_name": "C1",
            "keyword_id": "K1",
            "keyword_text": "comprar projecta",
            "match_type": "BROAD",
        },
    ]
    fake_st_rows = [
        {
            "search_term": "gerador projecta 5500",
            "ad_group_name": "AG1",
            "campaign_name": "C1",
            "impressions": 142,
            "clicks": 5,
            "cost_brl": 42.30,
        },
        {
            "search_term": "projecta promoção",
            "ad_group_name": "AG1",
            "campaign_name": "C1",
            "impressions": 50,
            "clicks": 2,
            "cost_brl": 15.00,
        },
    ]

    # run_report mock retorna pos_rows na 1ª call, st_rows na 2ª
    mock_run = AsyncMock(side_effect=[fake_pos_rows, fake_st_rows])
    with patch("src.mcp.tools.audit_competitor_keywords.run_report", mock_run):
        result = await audit_competitor_keywords(
            {
                "customer_id": "1234567890",
                "competitor_brands": ["projecta"],
                "date_range": "LAST_7_DAYS",
            }
        )

    assert result["customer_id"] == "1234567890"
    assert result["competitor_brands"] == ["projecta"]
    assert result["summary"]["positive_keywords_count"] == 1
    assert result["summary"]["search_terms_count"] == 2
    assert result["summary"]["total_cost_wasted_brl"] == 57.30
    assert result["summary"]["suggested_negatives_count"] == 2  # EXACT + PHRASE
    assert len(result["positive_keywords"]) == 1
    assert result["positive_keywords"][0]["matched_brand"] == "projecta"
    assert len(result["search_terms"]) == 2
    # Search terms sorted cost desc
    assert result["search_terms"][0]["cost_brl"] == 42.30
    assert result["search_terms"][1]["cost_brl"] == 15.00
    # Suggested negatives EXACT + PHRASE
    assert result["suggested_negatives"][0]["match_type"] == "EXACT"
    assert result["suggested_negatives"][1]["match_type"] == "PHRASE"


@pytest.mark.asyncio
async def test_audit_this_call_true_in_both_calls(bound_context):
    """Verify ambas chamadas run_report têm audit_this_call=True."""
    from src.mcp.tools.audit_competitor_keywords import audit_competitor_keywords

    mock_run = AsyncMock(return_value=[])
    with patch("src.mcp.tools.audit_competitor_keywords.run_report", mock_run):
        await audit_competitor_keywords(
            {
                "customer_id": "1234567890",
                "competitor_brands": ["projecta"],
                "date_range": "LAST_7_DAYS",
            }
        )

    # 2 calls — verificar audit_this_call em ambas
    assert mock_run.call_count == 2
    for call in mock_run.call_args_list:
        kwargs = call.kwargs
        assert kwargs["audit_this_call"] is True
        assert kwargs["operation_name"] == "audit_competitor_keywords"


@pytest.mark.asyncio
async def test_2_queries_called_in_parallel_via_gather(bound_context):
    """Verify ambas queries chamadas (asyncio.gather usado em paralelo)."""
    from src.mcp.tools.audit_competitor_keywords import audit_competitor_keywords

    mock_run = AsyncMock(return_value=[])
    with patch("src.mcp.tools.audit_competitor_keywords.run_report", mock_run):
        await audit_competitor_keywords(
            {
                "customer_id": "1234567890",
                "competitor_brands": ["projecta"],
                "date_range": "LAST_7_DAYS",
            }
        )

    # Ambas queries devem ter sido chamadas (1 positive + 1 search_term)
    assert mock_run.call_count == 2
    # Verify queries são distintas (não a mesma chamada 2×)
    queries_called = [call.kwargs["query"] for call in mock_run.call_args_list]
    assert any("keyword_view" in q for q in queries_called)
    assert any("search_term_view" in q for q in queries_called)
```

### A4 — Step 2: Run integration tests

Run: `python -m pytest tests/integration/test_audit_competitor_keywords.py -v`

Expected: 3 passed.

### A4 — Step 3: Generate smoke runbook via subagent

Dispatch `smoke-runbook-generator` subagent with prompt:

```
Generate smoke runbook esqueleto pra Sprint 3b.31 (audit_competitor_keywords — 53rd MCP tool).

Path: docs/operacao/phase-3b-31-bootstrap.md

Sprint context:
- Spec: docs/superpowers/specs/2026-05-20-sprint-3b-31-audit-competitor-keywords-design.md
- Plan: docs/superpowers/plans/2026-05-20-sprint-3b-31-audit-competitor-keywords.md
- Tool count: 52 → 53 (NEW tool, audit_competitor_keywords)
- Backward compat: N/A (tool nova)

Funcionalidade:
- Input: customer_id (req) + competitor_brands[] (3-50 chars, 1-20 brands req)
  + date_range preset OR start_date+end_date custom (default LAST_7_DAYS)
  + limit (default 200, max 1000)
- Output: 2 listas (positive_keywords + search_terms) + summary
  (total_cost_wasted_brl real) + suggested_negatives (EXACT + PHRASE per matched brand)
- Match algorithm: substring case-insensitive (normalize lowercase + strip)
- asyncio.gather paralelo em 2 queries (keyword_view + search_term_view)
- audit_this_call=True em ambas

8 smoke cases (T1-T8) per spec section 7:
- T1: audit com brand "nutry" em Nutry sandbox — sanity match em positive_keywords
- T2: brand inexistente "kjadflk" — empty everything + zero suggested
- T3: 2 brands [matched_brand, "kjadflk"] — apenas matched brand aparece em suggested
- T4: date_range=LAST_30_DAYS — custom resolution
- T5: start_date+end_date custom range
- T6: limit=5 — truncate validation se Nutry tem >5 matches
- T7: Empirical match: criar/usar kw "projecta-test" em ad_group sandbox, verificar substring match
- T8: Schema validation: brand 2-char rejeitada (minLength 3)

Conta sandbox: Nutry 1163862076 (low-volume — T7 pode requerer manual setup).

Pre-flight checks:
- Deploy lands successfully
- /health 200
- Tool count == 53 (audit_competitor_keywords visível na lista)
- Pre-push gate 5/5 PASS
- 14 unit competitor_analysis + 6 unit GAQL + 3 integration PASS

V4 invariants: N/A (read-only tool, sem geo/lang/currency/timezone/LGPD touched).

Per-value probe N/A (sem enum whitelist em audit_competitor_keywords schema).

Estilo: PT-BR conciso, action-oriented, match com phase-3b-30-bootstrap.md template.
```

Wait subagent completion, verify file exists.

### A4 — Step 4: Pre-push gate

Run: `python scripts/check_pre_push.py`

Expected: 5/5 PASS.

### A4 — Step 5: Commit + push

```bash
git add tests/integration/test_audit_competitor_keywords.py docs/operacao/phase-3b-31-bootstrap.md
git commit -m "$(cat <<'EOF'
test(audit_competitor_keywords): integration tests + smoke runbook (Sprint 3b.31 A4)

3 integration tests:
- test_returns_full_shape_with_matched_brands: wire-up match spec 3.2,
  positive_keywords + search_terms sorted, suggested EXACT+PHRASE
- test_audit_this_call_true_in_both_calls: verify audit_log integration
  em ambas calls (positive + search_terms)
- test_2_queries_called_in_parallel_via_gather: asyncio.gather validation
  + queries distintas (keyword_view + search_term_view)

Smoke runbook docs/operacao/phase-3b-31-bootstrap.md com 8 cases T1-T8
em Nutry sandbox (low-volume — T7 empirical match pode requerer setup).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

git push origin main
```

### A4 — Step 6: Watch CI

```bash
gh run list --limit 3
```

Pick latest CI run id, then:
```bash
gh run watch <run_id>
```

Expected: CI + Deploy green ~5-7min.

### A4 — Step 7: Health check production

```bash
curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```

Expected: `{"status":"ok","version":"0.1.0"}` HTTP 200.

---

## Task A5: Smoke execution + signoff

**Files (modify):**
- `docs/operacao/phase-3b-31-bootstrap.md` (fill smoke results)
- `docs/operacao/sprint-history.md` (append Sprint 3b.31 entry)
- `CLAUDE.md` (bump 52→53 tool count + sprint counter 3b.30→3b.31)

**Recommended model:** sonnet (controller; reload tool então execute smoke).

### A5 — Step 1: Reload tool via ToolSearch

After A4 deploy is green, this session's MCP cache may not have `audit_competitor_keywords` yet. Re-load tool schema:

```python
# Use ToolSearch with query "select:mcp__v4-ads__audit_competitor_keywords"
# If not available, signoff requires Wellington reboot pattern 3b.30 A5
```

### A5 — Step 2: Execute smoke T1-T8 via MCP client

Run 8 cases from runbook em Nutry sandbox:

- T1: `audit_competitor_keywords(customer_id="1163862076", competitor_brands=["nutry"])` (sanity self-match em Nutry positive kws)
- T2: brand inexistente — esperar empty
- T3: 2 brands (1 matched, 1 não) — verificar suggested_negatives apenas matched brand
- T4: date_range=LAST_30_DAYS
- T5: start_date+end_date custom
- T6: limit=5 truncate
- T7-T8: Empirical match + schema validation

Fill `docs/operacao/phase-3b-31-bootstrap.md` smoke results table.

**Esperado:** 6/8 PASS + 2 DEFERRED se Nutry low-volume / sem search_terms suficientes pra T7.

### A5 — Step 3: Update sprint-history.md

Append after Sprint 3b.30 entry:

```markdown
| Sprint 3b.31 — `audit_competitor_keywords` (53rd tool, #6 ICE 432 dogfood MO-JP) | ✅ 2026-05-20 | Production revisão post-`<commit>`. **Tool count 52 → 53.** N/8 PASS + M DEFERRED. 23 testes (14 unit pure competitor_analysis + 6 GAQL builder + 3 integration wire-up). 2 dimensões V0: positive_keywords (state-based, ENABLED + negative=FALSE) + search_terms (date-windowed com cost). Match algorithm: substring case-insensitive. Suggested negatives: EXACT + PHRASE per matched brand (apenas brands com hit). Architecture pure: `src/google_ads/competitor_analysis.py` (testable standalone, 5 dataclasses frozen+slots) + `src/google_ads/queries/audit_competitor_keywords.py` (2 GAQL builders + parsers) + `src/mcp/tools/audit_competitor_keywords.py` (wrapper com asyncio.gather paralelo). `audit_this_call=True` em ambas calls. Default LAST_7_DAYS, limit 200 (max 1000), brands 1-20 (minLength 3). Hardcoded filters em positive_keywords: status=ENABLED + negative=FALSE. Caso real dogfood MO-JP: ~R$2k/mês waste detectado em concorrência. Subagent-Driven: A1 (sonnet) + A2 (sonnet) + A3 (sonnet) + A4 (sonnet+smoke-runbook-generator) + A5 (controller). Runbook: [`phase-3b-31-bootstrap.md`](phase-3b-31-bootstrap.md). |
```

### A5 — Step 4: Update CLAUDE.md

Replace sprint counter row + tool count.

Find:
```markdown
| Sprint 3b.1 → 3b.30 (30 sprints) | ✅ 2026-05-04→20 |
```
Replace with:
```markdown
| Sprint 3b.1 → 3b.31 (31 sprints) | ✅ 2026-05-04→20 |
```

Find:
```markdown
### Shipped (52 tools em produção)
```
Replace with:
```markdown
### Shipped (53 tools em produção)
```

Find `**52 MCP tools** registered:` line and change to `**53 MCP tools** registered: 25 read + 27 mutations + `apply_change`.`

Pending/future section: remove Sprint 3b.30 row (shipped); replace with Sprint 3b.31 shipped + new next-in-queue (audit_zombie_keywords #11 ICE 315 OR remove_* bundle OR audit_log gap).

### A5 — Step 5: Commit signoff

```bash
git add docs/operacao/phase-3b-31-bootstrap.md docs/operacao/sprint-history.md CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(signoff): Sprint 3b.31 shipped — audit_competitor_keywords (53rd tool)

Sprint 3b.31 (#6 ICE 432 dogfood MO-JP) shipped + smoke N/8 PASS em
Nutry sandbox. Tool count 52 → 53.

2 dimensões V0 implementadas:
- positive_keywords (state-based ENABLED + negative=FALSE)
- search_terms (date-windowed com cost real)

Match algorithm substring case-insensitive. Suggested negatives
EXACT + PHRASE per matched brand. asyncio.gather paralelo.

Caso real dogfood MO-JP: ~R$2k/mês waste detectado em concorrência.
Outros clientes V4 herdam estrutura legacy → multiplica leverage.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

git push origin main
```

---

## Verification checklist (final)

Após todas as tasks:

- [ ] `src/google_ads/competitor_analysis.py` existe, 14 unit tests passing
- [ ] `src/google_ads/queries/audit_competitor_keywords.py` existe, 6 unit tests passing
- [ ] `src/mcp/tools/audit_competitor_keywords.py` existe + registered no MCP
- [ ] 3 integration tests passing
- [ ] `test_all_phase_2_tools_registered` + `test_no_unexpected_tools` updated
- [ ] `test_registered_tool_count_matches_files_on_disk` passa (53 == 53)
- [ ] `docs/operacao/phase-3b-31-bootstrap.md` existe + filled
- [ ] Smoke T1-T8 executed em Nutry (esperado 6/8 ou 7/8 PASS)
- [ ] `python scripts/check_pre_push.py` 5/5 PASS local
- [ ] CI green em GitHub Actions
- [ ] Cloud Run deployment green
- [ ] `/health` retorna 200
- [ ] `docs/operacao/sprint-history.md` updated com entry Sprint 3b.31
- [ ] `CLAUDE.md` Sprint counter + tool count atualizados
