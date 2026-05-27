# Sprint 3b.30 — `audit_quality_score` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 52nd MCP tool `audit_quality_score` that flags keywords with 3 actionable flags (candidate_pause, candidate_promote_exact, duplicate_intent) ordered by QS ASC. Resolves #1 ICE 504 dogfood MO-JP — economiza ~30min/sessão em queries manuais.

**Architecture:** Pure flag computation module (`src/google_ads/flag_keywords.py`) consumed by tool wrapper. GAQL builder em `src/google_ads/queries/audit_quality_score.py`. Read-only sensitive (audit_this_call=True). Flat list output ordered QS ASC.

**Tech Stack:** Python 3.12 stdlib only, pytest, ruff, mypy strict, google-ads SDK v24, asyncpg.

**Spec:** [`docs/superpowers/specs/2026-05-20-sprint-3b-30-audit-quality-score-design.md`](../specs/2026-05-20-sprint-3b-30-audit-quality-score-design.md)

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/google_ads/flag_keywords.py` | **CREATE** | Pure module: KeywordRow + FlaggedKeyword dataclasses + `flag_keywords()` pure function. Zero Google SDK imports. |
| `src/google_ads/queries/audit_quality_score.py` | **CREATE** | GAQL builder `build_audit_quality_score_query()` + row parser `parse_keyword_view_row()`. |
| `src/mcp/tools/audit_quality_score.py` | **CREATE** | Tool wrapper: schema, register_tool, orchestration. |
| `tests/unit/test_flag_keywords.py` | **CREATE** | 14 unit tests cobrindo flag logic + duplicate amplification + sort + truncate. |
| `tests/unit/test_audit_quality_score_query.py` | **CREATE** | 5 unit tests do GAQL builder (filtros, date range, hardcoded clauses). |
| `tests/integration/test_audit_quality_score.py` | **CREATE** | 3 wire-up tests: shape, audit_log call, min_impressions filter. |
| `tests/unit/test_tools_schemas.py` | **MODIFY** | Adicionar `audit_quality_score` em `test_all_phase_2_tools_registered` + `test_no_unexpected_tools` (2 lugares). |
| `docs/operacao/phase-3b-30-bootstrap.md` | **CREATE** | Smoke runbook 8 cases (T1-T8). |

---

## Task A1: Pure flag_keywords module + 14 unit tests

**Files:**
- Create: `src/google_ads/flag_keywords.py`
- Create: `tests/unit/test_flag_keywords.py`

**Recommended model:** sonnet (dataclasses + 14 testes coordenados + duplicate amplification logic).

### A1 — Step 1: Write 4 initial failing tests (RED)

Create `tests/unit/test_flag_keywords.py`:

```python
"""Unit tests for src.google_ads.flag_keywords.flag_keywords (Sprint 3b.30).

Pure function tests — sem Google SDK fixture. Cobertura: 3 flags + duplicate
amplification + sort + truncate.
"""

from src.google_ads.flag_keywords import FlaggedKeyword, KeywordRow, flag_keywords


def _make_row(
    *,
    ad_group_id: str = "1001",
    ad_group_name: str = "AG1",
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


def test_empty_rows_returns_empty():
    flagged, total = flag_keywords([], min_impressions=10, limit=200)
    assert flagged == []
    assert total == 0


def test_candidate_pause_flagged_when_qs_low_imp_above_threshold_zero_clicks():
    row = _make_row(quality_score=2, impressions=15, clicks=0)
    flagged, total = flag_keywords([row], min_impressions=10, limit=200)
    assert len(flagged) == 1
    assert flagged[0].flags == ("candidate_pause",)
    assert total == 1


def test_candidate_pause_NOT_flagged_when_impressions_below_threshold():
    row = _make_row(quality_score=2, impressions=5, clicks=0)
    flagged, total = flag_keywords([row], min_impressions=10, limit=200)
    assert flagged == []
    assert total == 0


def test_candidate_pause_NOT_flagged_when_qs_3():
    row = _make_row(quality_score=3, impressions=100, clicks=0)
    flagged, total = flag_keywords([row], min_impressions=10, limit=200)
    assert flagged == []
```

### A1 — Step 2: Run tests to verify they fail (RED)

Run: `python -m pytest tests/unit/test_flag_keywords.py -v`

Expected: `ImportError: cannot import name 'flag_keywords' from 'src.google_ads.flag_keywords'`

### A1 — Step 3: Create flag_keywords module (GREEN)

Create `src/google_ads/flag_keywords.py`:

```python
"""Pure client-side keyword flag computation (Sprint 3b.30 audit_quality_score).

3 flags:
- candidate_pause: QS<=2 + impressions>=min_impressions + clicks==0 (waste)
- candidate_promote_exact: QS>=7 + match_type=='BROAD' + conversions>=1 (promote pra EXACT)
- duplicate_intent: keyword_text exato em multi ad_groups (amplification only —
  só adicionado quando outra flag já presente; reduz false positives)

Pure function, zero Google SDK imports — testable standalone.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KeywordRow:
    """Input row from keyword_view GAQL query (Google-agnostic representation)."""

    ad_group_id: str
    ad_group_name: str
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


def flag_keywords(
    rows: list[KeywordRow],
    *,
    min_impressions: int,
    limit: int,
) -> tuple[list[FlaggedKeyword], int]:
    """Compute flags, amplify duplicates, sort, truncate.

    Args:
        rows: list[KeywordRow] from GAQL keyword_view.
        min_impressions: threshold pra candidate_pause flag (Google low-volume guard).
        limit: max output entries (truncate sort post-amplification).

    Returns:
        (flagged_list, total_pre_truncate). Sorted by quality_score ASC,
        impressions DESC tie-break.
    """
    # 1. Per-row primary flags
    candidates: list[tuple[KeywordRow, list[str]]] = []
    for row in rows:
        flags: list[str] = []
        if (
            row.quality_score <= 2
            and row.impressions >= min_impressions
            and row.clicks == 0
        ):
            flags.append("candidate_pause")
        if (
            row.quality_score >= 7
            and row.match_type == "BROAD"
            and row.conversions >= 1
        ):
            flags.append("candidate_promote_exact")
        if flags:
            candidates.append((row, flags))

    # 2. text -> ad_groups map (apenas em flagged subset; noise reduction)
    text_to_adgroups: dict[str, set[str]] = {}
    for row, _ in candidates:
        text_to_adgroups.setdefault(row.keyword_text, set()).add(row.ad_group_id)

    # 3. Amplify with duplicate_intent (only if text em >1 ad_group)
    flagged: list[FlaggedKeyword] = []
    for row, flags in candidates:
        if len(text_to_adgroups[row.keyword_text]) > 1:
            flags.append("duplicate_intent")
        flagged.append(
            FlaggedKeyword(
                ad_group_id=row.ad_group_id,
                ad_group_name=row.ad_group_name,
                campaign_name=row.campaign_name,
                keyword_id=row.keyword_id,
                keyword_text=row.keyword_text,
                match_type=row.match_type,
                quality_score=row.quality_score,
                impressions=row.impressions,
                clicks=row.clicks,
                conversions=row.conversions,
                cost_brl=row.cost_brl,
                flags=tuple(flags),
            )
        )

    # 4. Sort: QS ASC, impressions DESC tie-break
    flagged.sort(key=lambda f: (f.quality_score, -f.impressions))

    # 5. Truncate, return total pre-truncate
    total = len(flagged)
    return flagged[:limit], total
```

### A1 — Step 4: Run 4 tests to verify GREEN

Run: `python -m pytest tests/unit/test_flag_keywords.py -v`

Expected: 4 passed.

### A1 — Step 5: Add remaining 10 tests

Append to `tests/unit/test_flag_keywords.py`:

```python
def test_candidate_pause_NOT_flagged_when_clicks_above_zero():
    row = _make_row(quality_score=1, impressions=100, clicks=2)
    flagged, total = flag_keywords([row], min_impressions=10, limit=200)
    assert flagged == []


def test_candidate_promote_exact_flagged_when_qs_high_broad_with_conversions():
    row = _make_row(quality_score=8, match_type="BROAD", conversions=2)
    flagged, total = flag_keywords([row], min_impressions=10, limit=200)
    assert len(flagged) == 1
    assert flagged[0].flags == ("candidate_promote_exact",)


def test_candidate_promote_exact_NOT_flagged_when_already_exact():
    row = _make_row(quality_score=9, match_type="EXACT", conversions=5)
    flagged, total = flag_keywords([row], min_impressions=10, limit=200)
    assert flagged == []


def test_candidate_promote_exact_NOT_flagged_zero_conversions():
    row = _make_row(quality_score=9, match_type="BROAD", conversions=0)
    flagged, total = flag_keywords([row], min_impressions=10, limit=200)
    assert flagged == []


def test_duplicate_intent_amplifies_existing_pause():
    rows = [
        _make_row(
            ad_group_id="1001", keyword_id="A",
            keyword_text="gerador energia",
            quality_score=2, impressions=50, clicks=0,
        ),
        _make_row(
            ad_group_id="1002", keyword_id="B",
            keyword_text="gerador energia",
            quality_score=1, impressions=30, clicks=0,
        ),
    ]
    flagged, _ = flag_keywords(rows, min_impressions=10, limit=200)
    assert len(flagged) == 2
    for f in flagged:
        assert "candidate_pause" in f.flags
        assert "duplicate_intent" in f.flags


def test_duplicate_intent_amplifies_promote():
    rows = [
        _make_row(
            ad_group_id="1001", keyword_id="A",
            keyword_text="gerador honda",
            quality_score=8, match_type="BROAD", conversions=2,
        ),
        _make_row(
            ad_group_id="1002", keyword_id="B",
            keyword_text="gerador honda",
            quality_score=9, match_type="BROAD", conversions=3,
        ),
    ]
    flagged, _ = flag_keywords(rows, min_impressions=10, limit=200)
    assert len(flagged) == 2
    for f in flagged:
        assert "candidate_promote_exact" in f.flags
        assert "duplicate_intent" in f.flags


def test_duplicate_intent_NOT_added_without_other_flag():
    """2 kw 'Y' em ad_groups diff, ambas QS=5 normal → NOT flagged (amplificação only)."""
    rows = [
        _make_row(ad_group_id="1001", keyword_text="kw normal", quality_score=5),
        _make_row(ad_group_id="1002", keyword_text="kw normal", quality_score=5),
    ]
    flagged, total = flag_keywords(rows, min_impressions=10, limit=200)
    assert flagged == []
    assert total == 0


def test_duplicate_intent_NOT_added_same_ad_group():
    """Mesma kw 2× em mesmo ad_group → NÃO conta como duplicate."""
    rows = [
        _make_row(
            ad_group_id="1001", keyword_id="A",
            keyword_text="kw same",
            quality_score=2, impressions=15, clicks=0,
        ),
        _make_row(
            ad_group_id="1001", keyword_id="B",
            keyword_text="kw same",
            quality_score=1, impressions=20, clicks=0,
        ),
    ]
    flagged, _ = flag_keywords(rows, min_impressions=10, limit=200)
    assert len(flagged) == 2
    for f in flagged:
        assert f.flags == ("candidate_pause",)  # no duplicate_intent


def test_sort_qs_asc_then_impressions_desc():
    """3 kw QS=2 com imp variando → impressions DESC tie-break."""
    rows = [
        _make_row(keyword_id="A", quality_score=2, impressions=10, clicks=0),
        _make_row(keyword_id="B", quality_score=2, impressions=50, clicks=0),
        _make_row(keyword_id="C", quality_score=2, impressions=30, clicks=0),
    ]
    flagged, _ = flag_keywords(rows, min_impressions=5, limit=200)
    assert [f.keyword_id for f in flagged] == ["B", "C", "A"]


def test_truncate_at_limit_returns_total_pre_truncate():
    """250 flagged + limit=200 → 200 returned, total=250."""
    rows = [
        _make_row(
            keyword_id=str(i),
            keyword_text=f"kw_{i}",  # unique text — no duplicate_intent
            quality_score=2,
            impressions=20,
            clicks=0,
        )
        for i in range(250)
    ]
    flagged, total = flag_keywords(rows, min_impressions=10, limit=200)
    assert len(flagged) == 200
    assert total == 250
```

### A1 — Step 6: Run all 14 tests

Run: `python -m pytest tests/unit/test_flag_keywords.py -v`

Expected: 14 passed.

### A1 — Step 7: Pre-commit gate

Run: `python scripts/check_pre_push.py`

Expected: 5/5 PASS.

### A1 — Step 8: Commit

```bash
git add src/google_ads/flag_keywords.py tests/unit/test_flag_keywords.py
git commit -m "$(cat <<'EOF'
feat(flag_keywords): pure flag computation module (Sprint 3b.30 A1)

Pure function flag_keywords(rows, min_impressions, limit) que computa 3
flags em keywords + amplifica com duplicate_intent + ordena + trunca.

3 flags:
- candidate_pause: QS<=2 + imp>=threshold + clicks=0 (waste)
- candidate_promote_exact: QS>=7 + BROAD + conv>=1 (promote pra EXACT)
- duplicate_intent: keyword text exato em multi ad_groups (amplification
  only — só adicionado se outra flag presente; noise reduction)

Sort: QS ASC, impressions DESC tie-break. Truncate at limit, returns
total pre-truncate.

Dataclasses: KeywordRow (input) + FlaggedKeyword (output) — frozen,
slots=True. Zero Google SDK imports — testable standalone.

14 unit tests cobrem: empty, 4 candidate_pause variants (positive/negative
threshold/QS/clicks), 3 candidate_promote_exact variants, 4 duplicate_intent
variants (amplifies pause, amplifies promote, NOT-added-without-flag, NOT-
added-same-ad-group), sort tie-break, truncate.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A2: GAQL builder + row parser + 5 unit tests

**Files:**
- Create: `src/google_ads/queries/audit_quality_score.py`
- Create: `tests/unit/test_audit_quality_score_query.py`

**Recommended model:** haiku (mecânico, code completo abaixo).

### A2 — Step 1: Write 3 initial failing tests (RED)

Create `tests/unit/test_audit_quality_score_query.py`:

```python
"""Unit tests for src.google_ads.queries.audit_quality_score (Sprint 3b.30)."""

from src.google_ads.queries.audit_quality_score import build_audit_quality_score_query


def test_query_without_ad_group_filter():
    query = build_audit_quality_score_query(
        start_date="2026-04-20",
        end_date="2026-05-20",
        ad_group_ids=None,
    )
    assert "FROM keyword_view" in query
    assert "ad_group_criterion.status = 'ENABLED'" in query
    assert "ad_group_criterion.quality_info.quality_score IS NOT NULL" in query
    assert "segments.date BETWEEN '2026-04-20' AND '2026-05-20'" in query
    assert "ad_group.id IN" not in query  # no filter when None


def test_query_with_ad_group_filter_three_ids():
    query = build_audit_quality_score_query(
        start_date="2026-04-20",
        end_date="2026-05-20",
        ad_group_ids=["1001", "1002", "1003"],
    )
    assert "ad_group.id IN ('1001', '1002', '1003')" in query


def test_query_includes_status_enabled_and_qs_not_null():
    """Hardcoded filters MUST always be present (no opt-out)."""
    query = build_audit_quality_score_query(
        start_date="2026-04-20",
        end_date="2026-05-20",
        ad_group_ids=None,
    )
    assert "status = 'ENABLED'" in query
    assert "quality_score IS NOT NULL" in query
```

### A2 — Step 2: Run tests to verify they fail (RED)

Run: `python -m pytest tests/unit/test_audit_quality_score_query.py -v`

Expected: `ImportError: cannot import name 'build_audit_quality_score_query'`.

### A2 — Step 3: Create GAQL builder module (GREEN)

Create `src/google_ads/queries/audit_quality_score.py`:

```python
"""GAQL builder + row parser for audit_quality_score tool (Sprint 3b.30)."""

from typing import Any

from src.google_ads.flag_keywords import KeywordRow


def build_audit_quality_score_query(
    *,
    start_date: str,
    end_date: str,
    ad_group_ids: list[str] | None = None,
) -> str:
    """Build GAQL query for keyword_view filtered by status/date/qs/optional ad_groups.

    Hardcoded filters (per spec section 2):
    - ad_group_criterion.status = 'ENABLED' (only current-actionable)
    - ad_group_criterion.quality_info.quality_score IS NOT NULL (exclude unset/new kw)

    Args:
        start_date, end_date: YYYY-MM-DD (resolved via resolve_date_window upstream).
        ad_group_ids: optional filter — None means scan account-wide.

    Returns:
        GAQL string ready for run_report.
    """
    query = (
        "SELECT "
        "ad_group.id, ad_group.name, campaign.name, "
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
    if ad_group_ids:
        ids_clause = ", ".join(f"'{id_}'" for id_ in ad_group_ids)
        query += f" AND ad_group.id IN ({ids_clause})"
    return query


def parse_keyword_view_row(row: Any) -> dict[str, Any]:
    """Parse GoogleAds SDK row into dict matching KeywordRow fields.

    Returns dict (run_report's row_formatter contract). Tool wrapper
    converts to KeywordRow dataclass before passing to flag_keywords.
    """
    # match_type enum em v24: 2=EXACT, 3=PHRASE, 4=BROAD
    # SDK exposes .name attribute on proto enum
    match_type_str = row.ad_group_criterion.keyword.match_type.name

    return {
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": row.ad_group.name,
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


def dict_to_keyword_row(d: dict[str, Any]) -> KeywordRow:
    """Convert parsed dict back to KeywordRow dataclass at tool wrapper boundary."""
    return KeywordRow(
        ad_group_id=d["ad_group_id"],
        ad_group_name=d["ad_group_name"],
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

### A2 — Step 4: Run 3 tests to verify GREEN

Run: `python -m pytest tests/unit/test_audit_quality_score_query.py -v`

Expected: 3 passed.

### A2 — Step 5: Add 2 remaining tests

Append to `tests/unit/test_audit_quality_score_query.py`:

```python
def test_query_with_custom_date_range_yyyy_mm_dd():
    query = build_audit_quality_score_query(
        start_date="2026-05-01",
        end_date="2026-05-14",
        ad_group_ids=None,
    )
    assert "segments.date BETWEEN '2026-05-01' AND '2026-05-14'" in query


def test_query_selects_all_required_fields():
    """Output must include all 11 fields needed by KeywordRow dataclass."""
    query = build_audit_quality_score_query(
        start_date="2026-04-20",
        end_date="2026-05-20",
        ad_group_ids=None,
    )
    expected_fields = [
        "ad_group.id",
        "ad_group.name",
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

### A2 — Step 6: Run all 5 tests

Run: `python -m pytest tests/unit/test_audit_quality_score_query.py -v`

Expected: 5 passed.

### A2 — Step 7: Pre-commit gate

Run: `python scripts/check_pre_push.py`

Expected: 5/5 PASS.

### A2 — Step 8: Commit

```bash
git add src/google_ads/queries/audit_quality_score.py tests/unit/test_audit_quality_score_query.py
git commit -m "$(cat <<'EOF'
feat(queries): GAQL builder audit_quality_score (Sprint 3b.30 A2)

Builder build_audit_quality_score_query() + parsers
parse_keyword_view_row()/dict_to_keyword_row() em
src/google_ads/queries/audit_quality_score.py.

Hardcoded filters per spec:
- ad_group_criterion.status = 'ENABLED' (current-actionable only)
- ad_group_criterion.quality_info.quality_score IS NOT NULL (exclude
  unset/recém-criadas)

Optional ad_group_ids[] filter via IN clause. 5 unit tests cobrem
filtros, date range YYYY-MM-DD, hardcoded clauses, fields completos.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A3: Tool wrapper + schema + register_tool

**Files:**
- Create: `src/mcp/tools/audit_quality_score.py`
- Modify: `tests/unit/test_tools_schemas.py` (add em 2 lists)

**Recommended model:** haiku (mecânico).

### A3 — Step 1: Create tool wrapper

Create `src/mcp/tools/audit_quality_score.py`:

```python
"""Tool: audit_quality_score — flag keywords for pause/promote/duplicate intent.

Sprint 3b.30 — #1 fila ICE 504 do dogfood MO-JP 2026-05-19.
Economiza ~30min/sessão em queries manuais de keyword_view.
"""

from datetime import datetime
from typing import Any

from src.google_ads.flag_keywords import flag_keywords
from src.google_ads.queries.audit_quality_score import (
    build_audit_quality_score_query,
    dict_to_keyword_row,
    parse_keyword_view_row,
)
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._common import resolve_date_window
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "ad_group_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "minItems": 1,
            "maxItems": 50,
            "description": (
                "Opcional. Filtra audit a estes ad_group_ids. "
                "Default: conta inteira."
            ),
        },
        "min_impressions": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10000,
            "default": 10,
            "description": (
                "Threshold mínimo de impressions pra candidate_pause flag. "
                "Default 10. Reduza pra ~3 em contas low-volume."
            ),
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 200,
            "description": "Máximo keywords retornadas. truncated:true se exceder.",
        },
        "date_range": {
            "type": "string",
            "enum": ["LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS", "LAST_90_DAYS"],
            "description": "Preset. Override por start_date+end_date se ambos passados.",
        },
        "start_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "end_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


@register_tool(
    name="audit_quality_score",
    description=(
        "Identifica keywords problemáticas com 3 flags acionáveis: "
        "candidate_pause (QS<=2 + impressions>=threshold + clicks=0 = waste), "
        "candidate_promote_exact (QS>=7 + BROAD + conv>=1 = promote pra EXACT "
        "reduz CPC), duplicate_intent (mesma keyword text em multi ad_groups, "
        "amplification only — só com outra flag ativa). Output flat list "
        "ordenada QS ASC + impressions DESC tie-break. Filtros: ad_group_ids[], "
        "min_impressions (default 10), limit (default 200, max 1000), date_range "
        "preset OR start_date+end_date custom (default LAST_30_DAYS). Sempre "
        "auditado. Nota: QS pode lagar entre queries (cache Google) — re-query "
        "se decisão crítica baseada em QS."
    ),
    input_schema=_SCHEMA,
)
async def audit_quality_score(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    ad_group_ids = args.get("ad_group_ids")
    min_impressions = args.get("min_impressions", 10)
    limit = args.get("limit", 200)

    start_date, end_date = resolve_date_window(args)

    query = build_audit_quality_score_query(
        start_date=start_date,
        end_date=end_date,
        ad_group_ids=ad_group_ids,
    )

    raw_rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=parse_keyword_view_row,
        operation_name="audit_quality_score",
        audit_this_call=True,
        params_summary={
            "ad_group_ids": ad_group_ids,
            "min_impressions": min_impressions,
            "limit": limit,
            "date_window": f"{start_date} to {end_date}",
        },
    )

    keyword_rows = [dict_to_keyword_row(d) for d in raw_rows]
    flagged, total = flag_keywords(
        keyword_rows,
        min_impressions=min_impressions,
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
        "filters_applied": {
            "ad_group_ids": ad_group_ids,
            "min_impressions": min_impressions,
            "limit": limit,
        },
        "total_flagged": total,
        "truncated": total > limit,
        "flagged_keywords": [
            {
                "ad_group_id": f.ad_group_id,
                "ad_group_name": f.ad_group_name,
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
    }
```

### A3 — Step 2: Update schema regression tests

Open `tests/unit/test_tools_schemas.py` and find function `test_all_phase_2_tools_registered`. Add `"audit_quality_score"` to the `expected` set (sort alphabetically near top — after `add_negatives_from_search_terms` or similar).

Specifically, find the line `"add_keywords",` near the top of the expected set in `test_all_phase_2_tools_registered`, and add `"audit_quality_score",` after `"apply_recommendation",` (or wherever alphabetical fits — convention is to add em order).

Repeat the same addition in `test_no_unexpected_tools` (second expected set ~50 lines below).

For both sets, the line to add is exactly:
```python
        "audit_quality_score",
```

### A3 — Step 3: Run schema regression tests

Run: `python -m pytest tests/unit/test_tools_schemas.py -v`

Expected: all PASS (especialmente `test_every_tool_has_valid_schema`, `test_no_composition_keywords_in_any_schema`, `test_date_range_schemas_are_explicit`, `test_no_unexpected_tools`, `test_all_phase_2_tools_registered`).

If `test_registered_tool_count_matches_files_on_disk` fails, that's expected (will pass after tool count auto-incrementa).

### A3 — Step 4: Pre-commit gate

Run: `python scripts/check_pre_push.py`

Expected: 5/5 PASS. Tool registry auto-discovers `audit_quality_score.py` via `pkgutil`.

### A3 — Step 5: Commit

```bash
git add src/mcp/tools/audit_quality_score.py tests/unit/test_tools_schemas.py
git commit -m "$(cat <<'EOF'
feat(audit_quality_score): tool wrapper + schema (Sprint 3b.30 A3)

Tool MCP audit_quality_score (52nd tool) orquestra:
- resolve_date_window (Sprint 3b.20 helper)
- build_audit_quality_score_query (A2)
- run_report com row_formatter=parse_keyword_view_row + audit_this_call=True
- dict_to_keyword_row conversion at boundary
- flag_keywords pure (A1) com min_impressions + limit
- shape build com date_range_resolved + filters_applied + total_flagged
  + truncated + flagged_keywords[]

Schema: customer_id (req) + ad_group_ids[] (max 50) + min_impressions
(default 10) + limit (default 200, max 1000) + date_range preset OR
start_date+end_date custom.

Description menciona 3 flags + lag warning campaign.status (analog B4).

Tool count: 51 → 52. test_all_phase_2_tools_registered + test_no_
unexpected_tools atualizados.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A4: Integration tests + smoke runbook

**Files:**
- Create: `tests/integration/test_audit_quality_score.py`
- Create: `docs/operacao/phase-3b-30-bootstrap.md`

**Recommended model:** sonnet (mock patterns + runbook generation; ou dispatch smoke-runbook-generator subagent pra runbook).

### A4 — Step 1: Write 3 integration tests

Create `tests/integration/test_audit_quality_score.py`:

```python
"""Integration tests for audit_quality_score (Sprint 3b.30)."""

from unittest.mock import AsyncMock, MagicMock, patch
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
async def test_returns_flagged_keywords_shape(bound_context):
    """Wire-up: fake rows → output matches spec section 3.2."""
    from src.mcp.tools.audit_quality_score import audit_quality_score

    fake_rows = [
        {
            "ad_group_id": "1001",
            "ad_group_name": "AG1",
            "campaign_name": "C1",
            "keyword_id": "K1",
            "keyword_text": "gerador energia",
            "match_type": "BROAD",
            "quality_score": 2,
            "impressions": 50,
            "clicks": 0,
            "conversions": 0,
            "cost_brl": 0.0,
        },
        {
            "ad_group_id": "1002",
            "ad_group_name": "AG2",
            "campaign_name": "C1",
            "keyword_id": "K2",
            "keyword_text": "gerador honda",
            "match_type": "BROAD",
            "quality_score": 8,
            "impressions": 100,
            "clicks": 10,
            "conversions": 2,
            "cost_brl": 15.50,
        },
    ]

    with patch(
        "src.mcp.tools.audit_quality_score.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await audit_quality_score(
            {
                "customer_id": "1234567890",
                "date_range": "LAST_30_DAYS",
            }
        )

    assert result["customer_id"] == "1234567890"
    assert "date_range_resolved" in result
    assert result["date_range_resolved"]["days"] >= 28  # LAST_30_DAYS ~30
    assert result["total_flagged"] == 2
    assert result["truncated"] is False
    assert len(result["flagged_keywords"]) == 2
    # Order: QS 2 first (candidate_pause), QS 8 second (candidate_promote_exact)
    assert result["flagged_keywords"][0]["quality_score"] == 2
    assert "candidate_pause" in result["flagged_keywords"][0]["flags"]
    assert result["flagged_keywords"][1]["quality_score"] == 8
    assert "candidate_promote_exact" in result["flagged_keywords"][1]["flags"]


@pytest.mark.asyncio
async def test_audit_this_call_true_logs_to_audit(bound_context):
    """Verify run_report called with audit_this_call=True (sensitive read)."""
    from src.mcp.tools.audit_quality_score import audit_quality_score

    mock_run = AsyncMock(return_value=[])
    with patch("src.mcp.tools.audit_quality_score.run_report", mock_run):
        await audit_quality_score(
            {"customer_id": "1234567890", "date_range": "LAST_7_DAYS"}
        )

    # Inspect run_report call kwargs
    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs["audit_this_call"] is True
    assert call_kwargs["operation_name"] == "audit_quality_score"
    assert "min_impressions" in call_kwargs["params_summary"]


@pytest.mark.asyncio
async def test_respects_min_impressions_threshold(bound_context):
    """min_impressions=50 → only flag candidate_pause em kw com imp >= 50."""
    from src.mcp.tools.audit_quality_score import audit_quality_score

    fake_rows = [
        # imp 20 < threshold 50 → NOT flagged
        {
            "ad_group_id": "1001", "ad_group_name": "AG1", "campaign_name": "C1",
            "keyword_id": "K1", "keyword_text": "kw_low",
            "match_type": "BROAD", "quality_score": 1,
            "impressions": 20, "clicks": 0, "conversions": 0, "cost_brl": 0.0,
        },
        # imp 100 > threshold 50 → flagged
        {
            "ad_group_id": "1001", "ad_group_name": "AG1", "campaign_name": "C1",
            "keyword_id": "K2", "keyword_text": "kw_high",
            "match_type": "BROAD", "quality_score": 1,
            "impressions": 100, "clicks": 0, "conversions": 0, "cost_brl": 0.0,
        },
    ]

    with patch(
        "src.mcp.tools.audit_quality_score.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await audit_quality_score(
            {
                "customer_id": "1234567890",
                "min_impressions": 50,
                "date_range": "LAST_30_DAYS",
            }
        )

    assert result["total_flagged"] == 1
    assert result["flagged_keywords"][0]["keyword_text"] == "kw_high"
```

### A4 — Step 2: Run integration tests

Run: `python -m pytest tests/integration/test_audit_quality_score.py -v`

Expected: 3 passed.

### A4 — Step 3: Generate smoke runbook

**Option A (recommended):** Dispatch `smoke-runbook-generator` subagent with prompt:

```
Generate smoke runbook for Sprint 3b.30 audit_quality_score (52nd MCP tool).
Spec: docs/superpowers/specs/2026-05-20-sprint-3b-30-audit-quality-score-design.md
Plan: docs/superpowers/plans/2026-05-20-sprint-3b-30-audit-quality-score.md

8 smoke cases per spec section 7 (T1-T8). Conta sandbox: Nutry 1163862076
(low-volume; pode requerer min_impressions=1). Inclui validation que tool
count == 52 pós-deploy. Per-value probe N/A (sem enum whitelist).

Path: docs/operacao/phase-3b-30-bootstrap.md
```

**Option B (fallback manual):** Copy `docs/operacao/phase-3b-29-bootstrap.md` template and adapt to 3b.30 with the 8 smoke cases.

### A4 — Step 4: Pre-push gate (full)

Run: `python scripts/check_pre_push.py`

Expected: 5/5 PASS.

### A4 — Step 5: Commit + push

```bash
git add tests/integration/test_audit_quality_score.py docs/operacao/phase-3b-30-bootstrap.md
git commit -m "$(cat <<'EOF'
test(audit_quality_score): integration tests + smoke runbook (Sprint 3b.30 A4)

3 integration tests:
- test_returns_flagged_keywords_shape: wire-up shape match spec 3.2
- test_audit_this_call_true_logs_to_audit: verify audit_log integration
- test_respects_min_impressions_threshold: filtro funcionando end-to-end

Smoke runbook docs/operacao/phase-3b-30-bootstrap.md com 8 cases T1-T8
em Nutry sandbox (low-volume; min_impressions=1 fallback documentado).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

git push origin main
```

### A4 — Step 6: Watch CI

```bash
gh run list --limit 3
```

Pick latest workflow id, then:
```bash
gh run watch <run_id>
```

Expected: CI + Deploy parallel both green ~5-7min.

### A4 — Step 7: Verify production health + tool count

```bash
curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```

Expected: `{"status":"ok","version":"0.1.0"}` HTTP 200.

---

## Task A5: Smoke execution + signoff

**Files (modify):**
- `docs/operacao/phase-3b-30-bootstrap.md` (fill smoke results)
- `docs/operacao/sprint-history.md` (append Sprint 3b.30 entry)
- `CLAUDE.md` (bump 51→52 tool count + sprint counter 3b.29→3b.30)

**Recommended model:** sonnet (manual MCP execution + doc updates).

### A5 — Step 1: Execute smoke T1-T8 via MCP client

Wellington (or controller agent acting as proxy) executes 8 cases from runbook:

- T1: `audit_quality_score(customer_id="1163862076")` sem filters
- T2: T1 com `min_impressions=1` (Nutry low-volume fallback)
- T3: T1 com `ad_group_ids=["193008426336"]`
- T4: T1 com `start_date="2026-05-01", end_date="2026-05-14"`
- T5: T1 com `limit=10`
- T6: T1 com `date_range="LAST_7_DAYS"`
- T7: Empirical validate candidate_pause via run_gaql comparativo
- T8: Empirical validate duplicate_intent (criar 2 kw text idêntico em ad_groups diff)

Fill `docs/operacao/phase-3b-30-bootstrap.md` smoke results table.

**Esperado:** 6/8 ou 7/8 PASS. T7/T8 podem ser DEFERRED se Nutry zero stats (igual F45/F41 pattern).

### A5 — Step 2: Update sprint-history.md

Append after Sprint 3b.29 entry:

```markdown
| Sprint 3b.30 — `audit_quality_score` (52nd tool, #1 ICE 504 dogfood MO-JP) | ✅ 2026-05-20 | Production revisão post-`<commit>`. **Tool count 51 → 52.** N/8 PASS + M DEFERRED (T7/T8 se Nutry zero stats). 22 testes (14 unit pure flags + 5 GAQL builder + 3 integration wire-up). 3 flags V0: candidate_pause (QS<=2 + imp>=threshold + clicks=0), candidate_promote_exact (QS>=7 + BROAD + conv>=1), duplicate_intent (amplification only — kw text em multi ad_groups + outra flag ativa). Architecture pure: `src/google_ads/flag_keywords.py` (testable standalone, dataclasses frozen+slots) + `src/google_ads/queries/audit_quality_score.py` (GAQL builder + parser) + `src/mcp/tools/audit_quality_score.py` (wrapper). Audit_this_call=True. Default min_impressions=10, limit=200 (max 1000). Date range preset OR custom via resolve_date_window (Sprint 3b.20 helper). Hardcoded filters: status=ENABLED + quality_score IS NOT NULL (Google convention guard rails). Caso real economiza ~30min/sessão V4 cleanup recurring. Runbook: [`phase-3b-30-bootstrap.md`](phase-3b-30-bootstrap.md). |
```

### A5 — Step 3: Update CLAUDE.md

Replace sprint counter row + tool count.

Find:
```markdown
| Sprint 3b.1 → 3b.29 (29 sprints) | ✅ 2026-05-04→20 |
```
Replace with:
```markdown
| Sprint 3b.1 → 3b.30 (30 sprints) | ✅ 2026-05-04→20 |
```

Find:
```markdown
### Shipped (51 tools em produção)
```
Replace with:
```markdown
### Shipped (52 tools em produção)
```

Find `**51 MCP tools** registered:` line and change to `**52 MCP tools** registered: 24 read + 27 mutations + `apply_change`.`

Pending/future section: remove Sprint 3b.30 candidate row (now shipped); update next-in-queue to remove_* bundle OR audit_competitor_keywords (#6 ICE 432).

### A5 — Step 4: Commit signoff

```bash
git add docs/operacao/phase-3b-30-bootstrap.md docs/operacao/sprint-history.md CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(signoff): Sprint 3b.30 shipped — audit_quality_score (52nd tool)

Sprint 3b.30 (#1 ICE 504 dogfood MO-JP) shipped + smoke N/8 PASS em
Nutry sandbox. Tool count 51 → 52.

3 flags V0 validated:
- candidate_pause (QS<=2 + imp>=threshold + clicks=0)
- candidate_promote_exact (QS>=7 + BROAD + conv>=1)
- duplicate_intent (amplification only)

Economiza ~30min/sessão V4 cleanup recurring (caso real dogfood).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

git push origin main
```

---

## Verification checklist (final)

Após todas as tasks:

- [ ] `src/google_ads/flag_keywords.py` existe, 14 unit tests passing
- [ ] `src/google_ads/queries/audit_quality_score.py` existe, 5 unit tests passing
- [ ] `src/mcp/tools/audit_quality_score.py` existe + registered no MCP
- [ ] 3 integration tests passing
- [ ] `test_all_phase_2_tools_registered` + `test_no_unexpected_tools` updated
- [ ] `test_registered_tool_count_matches_files_on_disk` passa (52 == 52)
- [ ] `docs/operacao/phase-3b-30-bootstrap.md` existe + filled
- [ ] Smoke T1-T8 executed em Nutry (esperado 6/8 ou 7/8 PASS)
- [ ] `python scripts/check_pre_push.py` 5/5 PASS local
- [ ] CI green em GitHub Actions
- [ ] Cloud Run deployment green
- [ ] `/health` retorna 200
- [ ] `docs/operacao/sprint-history.md` updated com entry Sprint 3b.30
- [ ] `CLAUDE.md` Sprint counter + tool count atualizados
