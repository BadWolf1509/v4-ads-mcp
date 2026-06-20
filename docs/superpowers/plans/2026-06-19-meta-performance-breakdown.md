# M.4 — meta_get_performance_breakdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar 1 tool MCP `meta_get_performance_breakdown` que retorna Insights Meta quebrados por uma dimensão (platform/device/geo/hourly) × level (campaign/adset/ad).

**Architecture:** Estende o módulo puro `src/meta_ads/insights.py` (param `breakdowns` em `build_insights_call`; surfacing de dimensão em `parse_insights_row`) e cria 1 tool que espelha as M.3 (`meta_get_campaign_performance`), reusando `run_meta_graph_get` (gate+audit+BUC herdados). 1 breakdown por chamada (Meta restringe combos). Os valores Meta dos breakdowns entram **provisórios** e são confirmados no smoke real (gate antes do ship — lição F53/F54/F55).

**Tech Stack:** Python 3.13, `facebook-business` via `run_meta_graph_get` (Graph `/insights`), pytest + testcontainers, MCP Streamable HTTP.

## Global Constraints

- **Schema:** sem `oneOf`/`allOf`/`anyOf` em nenhum nível (3b.19B.1; guard `test_no_composition_keywords_in_any_schema`). Cross-field via helper privado se necessário — **v0 não tem combo inválido conhecido** (schema enums bastam; rejeição Meta vira erro friendly via `run_meta_graph_get`).
- **Tool file:** linha 1 `# bucket: defer`; description com prefixo `[DEFER]`; `bucket="defer"` no `@register_tool`. Auto-discovery via `pkgutil` (não há lista manual de import).
- **Governança Meta:** sempre `run_meta_graph_get(..., audit_this_call=True, params_summary={"ad_account_id": ...})`. O hard-gate (`can_manager_access`) + BUC + denial-audit (endurecido na Onda 0) são herdados — zero trabalho novo.
- **insights.py é módulo puro zero-SDK** → unit-first (TDD), ~50ms.
- **Teste de integração mocka `run_meta_graph_get` no namespace do TOOL** (`src.mcp.tools.meta_get_performance_breakdown.run_meta_graph_get`), nunca no de `_common`.
- **Date window:** `resolve_meta_date_window(preset_or_default, start, end, today)` (preset OU custom; custom sobrescreve).
- **Backward-compat obrigatória:** os novos params de `build_insights_call`/`parse_insights_row` são `None` por default → as 3 tools M.3 NÃO podem mudar de comportamento.
- **F53/F54/F55:** `ads_get_field_context` NÃO valida breakdowns (testado — `unknown_fields`). Os valores Meta em `BREAKDOWN_META_PARAM` são provisórios; o smoke per-valor + per-combo (Task 5) é o gate. **Nada vai pra prod antes do smoke.**
- **Verificação:** `python scripts/check_pre_push.py` (ruff+format+mypy+unit+integration não-DB) antes de cada commit. Integration com DB (testcontainers) só roda no CI ou full sweep com Docker.

---

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `src/meta_ads/insights.py` (modify) | + `Breakdown` Literal, `BREAKDOWN_META_PARAM` mapa; `breakdowns` em `build_insights_call`; `breakdown_keys` em `parse_insights_row` |
| `src/mcp/tools/meta_get_performance_breakdown.py` (create) | A tool: schema (level+breakdown), core fn, handler |
| `tests/unit/test_meta_insights.py` (modify) | Unit tests TDD dos 3 deltas de `insights.py` |
| `tests/integration/test_meta_get_performance_breakdown.py` (create) | Integração: happy-path com breakdown surfaced, params injetados, erros |
| `tests/unit/test_tools_schemas.py` (modify) | Adicionar `meta_get_performance_breakdown` ao set de `test_no_unexpected_tools` |
| `docs/operacao/phase-M-4-bootstrap.md` (create) | Smoke runbook (gate) — per-breakdown E per-combo |

---

### Task 1: Breakdown enum + Meta param mapping (insights.py)

**Files:**
- Modify: `src/meta_ads/insights.py` (após a linha `Level = Literal[...]`, ~linha 21)
- Test: `tests/unit/test_meta_insights.py`

**Interfaces:**
- Produces: `Breakdown = Literal["platform","device","geo","hourly"]`; `BREAKDOWN_META_PARAM: dict[str, list[str]]` (tool enum → Meta `breakdowns` param values).

- [ ] **Step 1: Write the failing test** (append em `tests/unit/test_meta_insights.py`)

```python
def test_breakdown_meta_param_covers_all_enum_values() -> None:
    from src.meta_ads.insights import BREAKDOWN_META_PARAM

    assert set(BREAKDOWN_META_PARAM) == {"platform", "device", "geo", "hourly"}
    assert BREAKDOWN_META_PARAM["platform"] == ["publisher_platform"]
    assert BREAKDOWN_META_PARAM["device"] == ["impression_device"]
    assert BREAKDOWN_META_PARAM["geo"] == ["country"]
    assert BREAKDOWN_META_PARAM["hourly"] == ["hourly_stats_aggregated_by_advertiser_time_zone"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_meta_insights.py::test_breakdown_meta_param_covers_all_enum_values -v`
Expected: FAIL — `ImportError: cannot import name 'BREAKDOWN_META_PARAM'`

- [ ] **Step 3: Write minimal implementation** (em `src/meta_ads/insights.py`, logo após `Level = Literal["campaign", "adset", "ad"]`)

```python
Breakdown = Literal["platform", "device", "geo", "hourly"]

# Tool breakdown enum → Meta Insights `breakdowns` param value(s).
# PROVISIONAL v0 (F53/F54/F55): `device`/`geo` variants são confirmados no smoke
# (docs/operacao/phase-M-4-bootstrap.md). ads_get_field_context NÃO valida
# breakdowns — o smoke per-valor é o gate antes do ship.
BREAKDOWN_META_PARAM: dict[str, list[str]] = {
    "platform": ["publisher_platform"],
    "device": ["impression_device"],
    "geo": ["country"],
    "hourly": ["hourly_stats_aggregated_by_advertiser_time_zone"],
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_meta_insights.py::test_breakdown_meta_param_covers_all_enum_values -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/meta_ads/insights.py tests/unit/test_meta_insights.py
git commit -m "feat(meta_ads): add Breakdown type + BREAKDOWN_META_PARAM mapping"
```

---

### Task 2: build_insights_call aceita `breakdowns` (insights.py)

**Files:**
- Modify: `src/meta_ads/insights.py:66-95` (`build_insights_call`)
- Test: `tests/unit/test_meta_insights.py`

**Interfaces:**
- Consumes: nada de Task 1.
- Produces: `build_insights_call(*, level, ad_account_id, start, end, limit, breakdowns: list[str] | None = None)` → quando `breakdowns` truthy, `params["breakdowns"] = ",".join(breakdowns)`; senão a chave é omitida.

- [ ] **Step 1: Write the failing tests** (append em `tests/unit/test_meta_insights.py`)

```python
def test_build_insights_call_with_breakdowns() -> None:
    _, params = build_insights_call(
        level="campaign", ad_account_id="act_1",
        start=date(2026, 5, 1), end=date(2026, 5, 7), limit=100,
        breakdowns=["publisher_platform"],
    )
    assert params["breakdowns"] == "publisher_platform"


def test_build_insights_call_without_breakdowns_omits_key() -> None:
    # Backward-compat: as tools M.3 chamam sem breakdowns → chave ausente.
    _, params = build_insights_call(
        level="campaign", ad_account_id="act_1",
        start=date(2026, 5, 1), end=date(2026, 5, 7), limit=100,
    )
    assert "breakdowns" not in params


def test_build_insights_call_joins_multiple_breakdowns() -> None:
    _, params = build_insights_call(
        level="ad", ad_account_id="act_1",
        start=date(2026, 5, 1), end=date(2026, 5, 7), limit=10,
        breakdowns=["country", "region"],
    )
    assert params["breakdowns"] == "country,region"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_meta_insights.py -k breakdowns -v`
Expected: FAIL — `TypeError: build_insights_call() got an unexpected keyword argument 'breakdowns'`

- [ ] **Step 3: Write minimal implementation** (substituir a assinatura + corpo de `build_insights_call`)

```python
def build_insights_call(
    *,
    level: Level,
    ad_account_id: str,
    start: date,
    end: date,
    limit: int,
    breakdowns: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build Graph API edge path + params dict for a /insights call.

    Returns: (edge, params) — caller passes both to run_meta_graph_get.

    M.4: `breakdowns` opcional → adiciona o param `breakdowns` (CSV). None/[]
    omite a chave (backward-compat: tools M.3 inalteradas).
    M.3.1 hotfix (F53): effective_status param removido; filtering omitido.
    """
    fields_by_level = {
        "campaign": INSIGHTS_FIELDS_CAMPAIGN,
        "adset": INSIGHTS_FIELDS_ADSET,
        "ad": INSIGHTS_FIELDS_AD,
    }
    edge = f"/{ad_account_id}/insights"
    params: dict[str, Any] = {
        "level": level,
        "fields": ",".join(fields_by_level[level]),
        "time_range": f'{{"since":"{start.isoformat()}","until":"{end.isoformat()}"}}',
        "limit": limit,
        "ad_account_id": ad_account_id,  # passed thru for BUC counter key
    }
    if breakdowns:
        params["breakdowns"] = ",".join(breakdowns)
    return edge, params
```

- [ ] **Step 4: Run tests to verify they pass** (inclui regressão M.3)

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_meta_insights.py -v`
Expected: PASS (todos, incluindo os `test_build_insights_call_*level*` de M.3 — backward-compat)

- [ ] **Step 5: Commit**

```bash
git add src/meta_ads/insights.py tests/unit/test_meta_insights.py
git commit -m "feat(meta_ads): build_insights_call accepts optional breakdowns param"
```

---

### Task 3: parse_insights_row expõe a dimensão via `breakdown_keys` (insights.py)

**Files:**
- Modify: `src/meta_ads/insights.py:121-181` (`parse_insights_row` — reestrutura pra 1 return)
- Test: `tests/unit/test_meta_insights.py`

**Interfaces:**
- Produces: `parse_insights_row(row, level, breakdown_keys: list[str] | None = None)` → quando `breakdown_keys` truthy, `out["breakdown"] = {k: row.get(k) for k in breakdown_keys}`; senão a chave `breakdown` é omitida.

- [ ] **Step 1: Write the failing tests** (append em `tests/unit/test_meta_insights.py`)

```python
def test_parse_insights_row_surfaces_breakdown() -> None:
    row = {
        "campaign_id": "1", "campaign_name": "T", "effective_status": "ACTIVE",
        "spend": "10", "publisher_platform": "instagram",
    }
    out = parse_insights_row(row, "campaign", breakdown_keys=["publisher_platform"])
    assert out["breakdown"] == {"publisher_platform": "instagram"}
    assert out["campaign_id"] == "1"  # campos do level preservados
    assert out["spend_brl"] == 10.0


def test_parse_insights_row_no_breakdown_keys_omits_key() -> None:
    # Backward-compat: as tools M.3 chamam sem breakdown_keys → chave ausente.
    row = {"campaign_id": "1", "campaign_name": "T", "effective_status": "ACTIVE", "spend": "10"}
    out = parse_insights_row(row, "campaign")
    assert "breakdown" not in out


def test_parse_insights_row_breakdown_missing_value_is_none() -> None:
    row = {"campaign_id": "1", "campaign_name": "T", "effective_status": "ACTIVE", "spend": "10"}
    out = parse_insights_row(row, "campaign", breakdown_keys=["publisher_platform"])
    assert out["breakdown"] == {"publisher_platform": None}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_meta_insights.py -k "breakdown and parse" -v`
Expected: FAIL — `TypeError: parse_insights_row() got an unexpected keyword argument 'breakdown_keys'`

- [ ] **Step 3: Write minimal implementation** (substituir `parse_insights_row` inteira — reestrutura os 3 `return` em `result` + 1 return)

```python
def parse_insights_row(
    row: dict[str, Any], level: Level, breakdown_keys: list[str] | None = None
) -> dict[str, Any]:
    """Parse single Meta Insights row → flat dict for MCP response.

    Level-specific fields prepended; common metrics + extracted actions follow.
    M.4: se `breakdown_keys` for dado, os valores da dimensão do row são
    expostos em result["breakdown"] (ex: {"publisher_platform": "instagram"}).
    """
    spend = float(row.get("spend") or 0)
    clicks = int(row.get("clicks") or 0)
    actions = row.get("actions")
    action_values = row.get("action_values")

    effective_status_raw = row.get("effective_status", "UNKNOWN")
    common: dict[str, Any] = {
        "effective_status": effective_status_raw,
        "effective_status_label": META_EFFECTIVE_STATUS_LABELS.get(
            effective_status_raw, "DESCONHECIDO"
        ),
        "spend_brl": round(spend, 2),
        "impressions": int(row.get("impressions") or 0),
        "clicks": clicks,
        "ctr": round(float(row.get("ctr") or 0) / 100, 4),  # Meta % → decimal
        "cpc_brl": round(float(row.get("cpc") or 0), 4),
        "reach": int(row.get("reach") or 0),
        "frequency": round(float(row.get("frequency") or 0), 2),
        "purchases": int(_extract_action_value(actions, "purchase")),
        "purchases_value_brl": round(_extract_action_value(action_values, "purchase"), 2),
        "purchase_roas": _extract_purchase_roas(row.get("purchase_roas")),
        "leads": int(_extract_action_value(actions, "lead")),
    }

    if level == "campaign":
        result: dict[str, Any] = {
            "campaign_id": row.get("campaign_id"),
            "campaign_name": row.get("campaign_name"),
            "objective": row.get("objective"),
            **common,
        }
    elif level == "adset":
        daily_budget_raw = row.get("daily_budget")
        daily_budget_brl = round(float(daily_budget_raw) / 100, 2) if daily_budget_raw else None
        result = {
            "ad_set_id": row.get("adset_id"),
            "ad_set_name": row.get("adset_name"),
            "campaign_id": row.get("campaign_id"),
            "campaign_name": row.get("campaign_name"),
            "optimization_goal": row.get("optimization_goal"),
            "billing_event": row.get("billing_event"),
            "daily_budget_brl": daily_budget_brl,
            **common,
        }
    else:  # ad
        result = {
            "ad_id": row.get("ad_id"),
            "ad_name": row.get("ad_name"),
            "ad_set_id": row.get("adset_id"),
            "ad_set_name": row.get("adset_name"),
            "campaign_id": row.get("campaign_id"),
            "campaign_name": row.get("campaign_name"),
            "creative_id": row.get("creative_id"),
            **common,
        }

    if breakdown_keys:
        result["breakdown"] = {key: row.get(key) for key in breakdown_keys}

    return result
```

- [ ] **Step 4: Run tests to verify they pass** (inclui toda a regressão M.3 de `parse_insights_row`)

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_meta_insights.py -v`
Expected: PASS (todos)

- [ ] **Step 5: Commit**

```bash
git add src/meta_ads/insights.py tests/unit/test_meta_insights.py
git commit -m "feat(meta_ads): parse_insights_row surfaces breakdown dimension"
```

---

### Task 4: A tool meta_get_performance_breakdown + integração + schema guard

**Files:**
- Create: `src/mcp/tools/meta_get_performance_breakdown.py`
- Create: `tests/integration/test_meta_get_performance_breakdown.py`
- Modify: `tests/unit/test_tools_schemas.py` (set de `test_no_unexpected_tools`)

**Interfaces:**
- Consumes: `BREAKDOWN_META_PARAM`, `Level`, `build_insights_call`, `parse_insights_row` (Tasks 1-3); `run_meta_graph_get`, `resolve_meta_date_window`, `meta_ad_accounts.get_by_id`.
- Produces: tool registrada `meta_get_performance_breakdown`; core fn `meta_get_performance_breakdown(manager_id, session_id, *, ad_account_id, breakdown, level="campaign", date_range=None, start_date=None, end_date=None, limit=100)`.

- [ ] **Step 1: Write the failing integration test** (criar `tests/integration/test_meta_get_performance_breakdown.py`)

```python
"""Integration tests Sprint M.4: meta_get_performance_breakdown."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import (
    manager_meta_account_access,
    managers,
    meta_ad_accounts,
    meta_oauth_connections,
)

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


async def _seed(db):
    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(conn, manager_id=mid, email="t@v4company.com", full_name="T")
        await meta_oauth_connections.upsert(
            conn, manager_id=mid, fb_user_id="fb_test", fb_email="t@v4company.com",
            access_token_enc=b"fake", token_expires_at=datetime.now(UTC) + timedelta(days=60),
            scopes=["ads_read"],
        )
        await meta_ad_accounts.upsert_many(
            conn,
            [{
                "ad_account_id": "act_123456", "business_id": "bm", "business_name": "BM",
                "account_name": "Test Account", "currency": "BRL",
                "timezone_name": "America/Sao_Paulo", "account_status": 1,
            }],
        )
        await manager_meta_account_access.grant(conn, manager_id=mid, ad_account_id="act_123456")
    return mid


@pytest.mark.integration
async def test_happy_path_platform_breakdown_sorted_and_surfaced(db):
    from src.mcp.tools.meta_get_performance_breakdown import meta_get_performance_breakdown

    mid = await _seed(db)
    body = {"data": [
        {"campaign_id": "c1", "campaign_name": "C1", "effective_status": "ACTIVE",
         "spend": "100", "publisher_platform": "facebook"},
        {"campaign_id": "c1", "campaign_name": "C1", "effective_status": "ACTIVE",
         "spend": "300", "publisher_platform": "instagram"},
    ]}
    with patch(
        "src.mcp.tools.meta_get_performance_breakdown.run_meta_graph_get",
        new=AsyncMock(return_value=body),
    ):
        result = await meta_get_performance_breakdown(
            manager_id=mid, session_id=uuid4(),
            ad_account_id="act_123456", breakdown="platform", date_range="LAST_7_DAYS",
        )
    assert result["status"] == "success"
    assert result["level"] == "campaign"
    assert result["breakdown"] == "platform"
    assert result["total_rows"] == 2
    assert result["rows"][0]["breakdown"] == {"publisher_platform": "instagram"}  # 300 first
    assert result["rows"][1]["breakdown"] == {"publisher_platform": "facebook"}


@pytest.mark.integration
async def test_injects_breakdowns_param_for_level(db):
    from src.mcp.tools.meta_get_performance_breakdown import meta_get_performance_breakdown

    mid = await _seed(db)
    captured: dict = {}

    async def capture(**kwargs):
        captured.update(kwargs["params"])
        return {"data": []}

    with patch(
        "src.mcp.tools.meta_get_performance_breakdown.run_meta_graph_get",
        new=AsyncMock(side_effect=capture),
    ):
        await meta_get_performance_breakdown(
            manager_id=mid, session_id=uuid4(),
            ad_account_id="act_123456", breakdown="hourly", level="adset",
        )
    assert captured["level"] == "adset"
    assert captured["breakdowns"] == "hourly_stats_aggregated_by_advertiser_time_zone"


@pytest.mark.integration
async def test_account_not_found_returns_error(db):
    from src.mcp.tools.meta_get_performance_breakdown import meta_get_performance_breakdown

    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(conn, manager_id=mid, email="t@v4company.com", full_name="T")

    result = await meta_get_performance_breakdown(
        manager_id=mid, session_id=uuid4(), ad_account_id="act_999999", breakdown="platform",
    )
    assert result["status"] == "error"
    assert "act_999999" in result["error_message"]
    assert "não encontrada" in result["error_message"]


@pytest.mark.integration
async def test_meta_api_error_returns_friendly_pt_br(db):
    from src.mcp.tools.meta_get_performance_breakdown import meta_get_performance_breakdown
    from src.meta_ads.errors import MetaAdsFriendlyError

    mid = await _seed(db)
    with patch(
        "src.mcp.tools.meta_get_performance_breakdown.run_meta_graph_get",
        new=AsyncMock(side_effect=MetaAdsFriendlyError("Limite Meta atingido.", retryable=True)),
    ):
        result = await meta_get_performance_breakdown(
            manager_id=mid, session_id=uuid4(),
            ad_account_id="act_123456", breakdown="geo",
        )
    assert result["status"] == "error"
    assert "Limite Meta" in result["error_message"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/integration/test_meta_get_performance_breakdown.py -v` (precisa Docker; senão valida no CI)
Expected: FAIL — `ModuleNotFoundError: No module named 'src.mcp.tools.meta_get_performance_breakdown'`

- [ ] **Step 3: Write the tool** (criar `src/mcp/tools/meta_get_performance_breakdown.py`)

```python
# bucket: defer
"""meta_get_performance_breakdown — Performance Meta quebrada por 1 dimensão (Sprint M.4).

Consolida o conceito de breakdown numa tool: level (campaign|adset|ad) × breakdown
(platform|device|geo|hourly). Reusa run_meta_graph_get (gate+audit+BUC) +
build_insights_call/parse_insights_row estendidos. 1 breakdown por chamada (Meta
restringe combos). bucket=defer (deep-dive, não a 1ª pergunta do gestor).
"""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from src.db import connection
from src.db.repositories import meta_ad_accounts
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool
from src.meta_ads.account_overview import resolve_meta_date_window
from src.meta_ads.insights import (
    BREAKDOWN_META_PARAM,
    Level,
    build_insights_call,
    parse_insights_row,
)
from src.meta_ads.reports import run_meta_graph_get

_DESCRIPTION = (
    "[DEFER] Performance Meta Ads quebrada por UMA dimensão: platform "
    "(Facebook/Instagram/Audience Network), device (iOS/Android/desktop), geo (país) "
    "ou hourly (hora do dia). level = campaign|adset|ad (default campaign). Métricas: "
    "spend, impressões, clicks, CTR, CPC, reach, frequency, purchases, purchase_roas, "
    "leads. Cada row traz o valor da dimensão em `breakdown`. Ordenado por spend desc. "
    "1 breakdown por chamada. Use meta_list_my_ad_accounts pros IDs."
)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ad_account_id": {
            "type": "string",
            "pattern": r"^act_\d+$",
            "description": "Meta ad account ID (act_<numeric>). Use meta_list_my_ad_accounts.",
        },
        "breakdown": {
            "type": "string",
            "enum": ["platform", "device", "geo", "hourly"],
            "description": (
                "Dimensão do corte: platform (publisher_platform), device, geo (país), "
                "hourly (hora no fuso do anunciante). 1 por chamada."
            ),
        },
        "level": {
            "type": "string",
            "enum": ["campaign", "adset", "ad"],
            "description": "Nível de agregação. Default campaign.",
        },
        "date_range": {
            "type": "string",
            "enum": ["TODAY", "YESTERDAY", "LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS", "LAST_90_DAYS"],
            "description": "Preset. Default LAST_30_DAYS se start_date+end_date não fornecidos.",
        },
        "start_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Custom range start. Sobrescreve preset. Requires end_date.",
        },
        "end_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Custom range end. Sobrescreve preset. Requires start_date.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
            "default": 100,
            "description": "Max rows. Meta API cap = 500/page.",
        },
    },
    "required": ["ad_account_id", "breakdown"],
    "additionalProperties": False,
}


async def meta_get_performance_breakdown(
    manager_id: UUID,
    session_id: UUID,
    *,
    ad_account_id: str,
    breakdown: str,
    level: str = "campaign",
    date_range: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Core logic — testable by integration tests."""
    pool = connection.get_pool()
    today = datetime.now(UTC).date()

    breakdown_params = BREAKDOWN_META_PARAM.get(breakdown)
    if breakdown_params is None:
        return {
            "status": "error",
            "error_message": (
                f"breakdown '{breakdown}' inválido. Aceitos: {sorted(BREAKDOWN_META_PARAM)}."
            ),
        }

    try:
        start, end = resolve_meta_date_window(
            date_range or "LAST_30_DAYS", start_date, end_date, today
        )
    except ValueError as e:
        return {"status": "error", "error_message": f"Datas inválidas: {e}"}

    async with pool.acquire() as conn:
        account = await meta_ad_accounts.get_by_id(conn, ad_account_id)
        if account is None:
            return {
                "status": "error",
                "error_message": (
                    f"Ad account {ad_account_id} não encontrada. "
                    f"Use meta_refresh_accounts ou reconnect via /oauth/meta/start."
                ),
            }

    level_typed = cast(Level, level)
    edge, params = build_insights_call(
        level=level_typed,
        ad_account_id=ad_account_id,
        start=start,
        end=end,
        limit=limit,
        breakdowns=breakdown_params,
    )

    try:
        resp = await run_meta_graph_get(
            manager_id=manager_id,
            session_id=session_id,
            edge=edge,
            params=params,
            operation_name="meta_get_performance_breakdown",
            estimated_calls=1,
            audit_this_call=True,
            params_summary={
                "ad_account_id": ad_account_id,
                "level": level,
                "breakdown": breakdown,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )
    except Exception as e:  # noqa: BLE001
        if hasattr(e, "message"):
            return {"status": "error", "error_message": e.message}
        return {"status": "error", "error_message": str(e)}

    rows = [
        parse_insights_row(r, level_typed, breakdown_keys=breakdown_params)
        for r in resp.get("data", [])
    ]
    rows.sort(key=lambda r: r["spend_brl"], reverse=True)

    return {
        "status": "success",
        "ad_account_id": ad_account_id,
        "ad_account_name": account.account_name,
        "currency": account.currency,
        "level": level,
        "breakdown": breakdown,
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "rows": rows,
        "total_rows": len(rows),
    }


@register_tool(
    name="meta_get_performance_breakdown",
    description=_DESCRIPTION,
    input_schema=_INPUT_SCHEMA,
    bucket="defer",
)
async def handler(args: dict[str, Any]) -> dict[str, Any]:
    """MCP tool handler — pulls context from contextvars, delegates to core."""
    ctx = get_current()
    return await meta_get_performance_breakdown(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        ad_account_id=args["ad_account_id"],
        breakdown=args["breakdown"],
        level=args.get("level", "campaign"),
        date_range=args.get("date_range"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        limit=args.get("limit", 100),
    )
```

- [ ] **Step 4: Add the tool to the schema guard set** (em `tests/unit/test_tools_schemas.py`, função `test_no_unexpected_tools`, dentro do `expected = {...}`, junto dos outros `meta_*`)

```python
        "meta_get_performance_breakdown",  # Sprint M.4
```

- [ ] **Step 5: Run the fast gate**

Run: `.venv/Scripts/python.exe scripts/check_pre_push.py`
Expected: PASS — ruff+format+mypy+unit+integration-não-DB verdes. (`test_no_unexpected_tools` passa com a tool nova no set; os integration DB rodam no CI.)

- [ ] **Step 6: Commit**

```bash
git add src/mcp/tools/meta_get_performance_breakdown.py tests/integration/test_meta_get_performance_breakdown.py tests/unit/test_tools_schemas.py
git commit -m "feat(mcp): meta_get_performance_breakdown tool (level x breakdown)"
```

---

### Task 5: Smoke runbook + execução real (GATE antes do ship)

**Files:**
- Create: `docs/operacao/phase-M-4-bootstrap.md`

> **Este é o gate F53/F54/F55.** Os valores em `BREAKDOWN_META_PARAM` são provisórios até aqui. NÃO prossiga pro ship (Task 6) sem este passo verde.

- [ ] **Step 1: Gerar o esqueleto do runbook** via subagent `smoke-runbook-generator` (ele puxa estrutura dos 3 runbooks mais recentes). Prompt: "Gerar phase-M-4-bootstrap.md pro sprint M.4 (meta_get_performance_breakdown). Cenários: per-breakdown (platform/device/geo/hourly) × per-level (campaign/adset/ad) contra conta Meta real."

- [ ] **Step 2: Executar o smoke** (Wellington, contas reais ML Antiguidades / MO-JP via MCP `v4-ads`). Para cada `breakdown` × `level` (até 12 combos), registrar:
  - Retornou rows? O `breakdown` de cada row tem o valor esperado?
  - Meta rejeitou? (erro friendly — anota o combo como não suportado).
  - **Decisões a confirmar:** `device` = `impression_device` (granular) vs `device_platform` (mobile/desktop/web)? `geo` = `country` basta ou inclui `region`? `hourly` funciona em todos os 3 levels?

- [ ] **Step 3: Ajustar `BREAKDOWN_META_PARAM` se o smoke indicar** (ex: trocar `device` pra `device_platform`, ou `geo` pra `["country","region"]`). Re-rodar os unit tests de Task 1 (atualizar asserts) + commit `fix(meta_ads): confirma breakdown params via smoke M.4`.

- [ ] **Step 4: Documentar resultados** no runbook (tabela combos × resultado) + qualquer F-finding via `/findings-add`. Combos rejeitados → documentar como out-of-scope na description da tool (ou adicionar `_validate_combo` privado se o gestor precisar de erro pró-ativo).

- [ ] **Step 5: Commit**

```bash
git add docs/operacao/phase-M-4-bootstrap.md src/meta_ads/insights.py tests/unit/test_meta_insights.py
git commit -m "docs(meta_ads): smoke runbook M.4 + breakdown params confirmados"
```

---

### Task 6: Ship + monitor

- [ ] **Step 1: Verificação final**

Run: `.venv/Scripts/python.exe scripts/check_pre_push.py`
Expected: PASS. (Opcional, se Docker disponível: `python scripts/check_pre_push_full.py`.)

- [ ] **Step 2: Push** (dispara CI + Deploy)

```bash
git push origin main
```

- [ ] **Step 3: Confirmar conclusão** (NUNCA pelo exit code do `gh run watch`)

Run: `gh run list --branch main --limit 2 --json databaseId,name`; depois `gh run view <id> --json conclusion`
Expected: CI `success` + Deploy `success`.

- [ ] **Step 4: Pós-deploy** — `detect_drift` na conta + confirmar `audit_log` registrando `meta_get_performance_breakdown`. Atualizar memória `improvement-roadmap-2026-06` (M.4 shipped) e checar contribuição pro gate Meta Full Access (25/06).

---

## Self-Review

**1. Spec coverage:**
- 1 tool consolidada, 1 breakdown/chamada → Task 4 (schema enum único `breakdown`). ✅
- level campaign/adset/ad → Task 4 (param `level` + `cast(Level, ...)`). ✅
- 4 breakdowns platform/device/geo/hourly → Task 1 (`BREAKDOWN_META_PARAM`). ✅
- Reusa run_meta_graph_get (gate+audit+BUC) → Task 4 (mesma chamada das M.3, `audit_this_call=True`). ✅
- Estende build_insights_call + parse_insights_row → Tasks 2-3. ✅
- Breakdowns provisórios + smoke como gate → Task 5 (gate explícito antes do ship). ✅
- Sem oneOf/allOf/anyOf → schema usa só enums; `test_no_composition_keywords_in_any_schema` cobre. ✅
- insights.py puro unit-first → Tasks 1-3 todas TDD unit. ✅
- Integration mocka run_meta_graph_get no namespace do tool → Task 4 Step 1. ✅

**2. Placeholder scan:** todos os steps de código têm código completo; nenhum "TBD/handle edge cases". Task 5 (smoke) é manual por natureza mas tem steps concretos. ✅

**3. Type consistency:** `build_insights_call(..., breakdowns=...)` (Task 2) e `parse_insights_row(..., breakdown_keys=...)` (Task 3) batem com as chamadas em Task 4. `BREAKDOWN_META_PARAM` (Task 1) consumido com o mesmo nome em Task 4. `Level`/`cast` consistente. ✅

**Cross-field validation (v0):** decisão consciente de NÃO adicionar `_validate_combo` agora (YAGNI) — não há combo inválido conhecido; rejeição Meta já vira erro friendly. Task 5 Step 4 adiciona validação SÓ se o smoke revelar combos rejeitados que mereçam erro pró-ativo.
