# Sprint M.3 — Meta Performance Tools (campaign + ad_set + ad) — Design Doc

**Sprint:** M.3 (Meta Ads family)
**Author:** Wellington Ribeiro + Claude (brainstorming session 2026-05-26)
**Status:** Approved — pronto pra writing-plans phase
**Estimativa:** ~1 dia útil (subagent-driven, paralelizável A3+A4+A5)

---

## 0. Contexto e motivador

Sprint family Meta Ads (M.1 – M.25) shipped até M.2b: foundation + OAuth + 2 tools (`meta_list_my_ad_accounts` + `meta_get_account_overview`). Meta App Review rejeitou Full Access em 2026-05-25 (Limited Access ativo + decisão Caminho B+ janela observação 30-45d pra acumular 500 calls/15d threshold).

**Motivador M.3:** ship as 3 tools de performance core (campaign/ad_set/ad) — equivalentes diretos de `get_campaign_performance` / `get_ad_group_performance` / `get_ad_performance` Google. São os top 3 reports Pareto Meta (gestor V4 pede primeiro). Caminho B+ exige acelerar Meta volume natural via dogfood — M.3+M.4+M.6 nos próximos 14 dias contribuem ~10-15 calls/dia sustained.

**Estado atual:** 59 tools (57 Google + 2 Meta). Pós-M.3: 62 (21+1 always = 22, 38+2 defer = 40).

---

## 1. Architecture Overview

**3 tools paralelas Meta** (paridade direta Google `get_*_performance`):

```
src/mcp/tools/
├── meta_get_campaign_performance.py     ← bucket=always (Pareto Meta top usage)
├── meta_get_ad_set_performance.py       ← bucket=defer (granular, gestor pede após campaign)
└── meta_get_ad_performance.py           ← bucket=defer (idem)

src/meta_ads/
├── insights.py                          ← NOVO shared module
│   ├── build_insights_call(level, ad_account_id, fields, date_window, effective_status) -> (edge, params)
│   ├── parse_insights_row(row, level) -> dict (flat para MCP response)
│   ├── _extract_action_value(actions, action_type) -> float
│   ├── _extract_purchase_roas(roas_list) -> float
│   ├── INSIGHTS_FIELDS_CAMPAIGN: list[str]
│   ├── INSIGHTS_FIELDS_ADSET: list[str]
│   └── INSIGHTS_FIELDS_AD: list[str]
└── (reusa) account_overview.py::resolve_meta_date_window  ← já shipped M.2b

src/mcp/tools/_meta_common.py            ← adiciona META_EFFECTIVE_STATUS_LABELS
```

**Reuso vertical (zero código novo nesses):**
- `run_meta_graph_get` (shipped M.2b) — executor com BUC tracking + audit_log + PT-BR errors
- `resolve_meta_date_window` (shipped M.2b) — date window resolver paralelo a Google `resolve_date_window`
- `meta_ad_accounts.get_by_id` (shipped M.2a) — account metadata lookup
- `build_meta_api_for_manager` (shipped M.2a) — SDK factory com token expiry validation
- `@register_tool` decorator com `bucket` kwarg (shipped 3b.39)

**Endpoint Meta Graph API:**
```
GET /act_<id>/insights?level=<campaign|adset|ad>&fields=...&time_range=...&filtering=...&limit=...
```

Single endpoint Meta, mesmo padrão pra 3 levels (apenas `level` query param muda). Pattern: build call → execute via `run_meta_graph_get` → parse rows → sort by spend DESC → return.

**Custo arquitetural:** 1 módulo novo (`insights.py` ~150 LOC) + 3 tools MCP (~30 LOC handlers cada) + ~15 LOC em `_meta_common.py`. Zero touch em código existente Meta/Google. Total ~255 LOC novo.

---

## 2. Schema Input (3 tools idênticos)

Padrão schema comum, diferem apenas em `bucket` kwarg:

```python
{
    "type": "object",
    "properties": {
        "ad_account_id": {
            "type": "string",
            "pattern": r"^act_\d+$",
            "description": "Meta ad account ID. Use meta_list_my_ad_accounts pra IDs."
        },
        "date_range": {
            "type": "string",
            "enum": ["TODAY", "YESTERDAY", "LAST_7_DAYS", "LAST_14_DAYS",
                     "LAST_30_DAYS", "LAST_90_DAYS"],
            "description": "Preset. Default LAST_30_DAYS se start_date+end_date não fornecidos."
        },
        "start_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "end_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "effective_status": {
            "type": "string",
            "enum": ["ACTIVE", "PAUSED", "ARCHIVED", "ALL"],
            "default": "ACTIVE",
            "description": "Filter por effective_status. ALL inclui tudo."
        },
        "limit": {
            "type": "integer", "minimum": 1, "maximum": 500, "default": 100,
            "description": "Max rows. Meta API cap = 500/page."
        }
    },
    "required": ["ad_account_id"],
    "additionalProperties": False
}
```

**Decisões deliberadas schema V0:**

| Decisão | Por que |
|---|---|
| `effective_status` enum **simplificado a 4 valores** (ACTIVE/PAUSED/ARCHIVED/ALL) | Mapeia mental model Google (enabled/paused/removed/all). Meta full enum tem 9 valores; DISAPPROVED/PENDING_REVIEW/PREAPPROVED/PENDING_BILLING_INFO/CAMPAIGN_PAUSED/ADSET_PAUSED ficam V1. Per-value probe T6 valida 4 empíricamente. |
| `date_range` enum **sem THIS_MONTH/LAST_MONTH/THIS_WEEK/LAST_WEEK** | Meta API usa `date_preset` enum diferente (`this_month`); mistura com `time_range` JSON é confuso. V0 padroniza LAST_N_DAYS — janelas relativas via `time_range` direto. |
| `limit` cap = **500** | Meta API hard cap por página. Google cap 10000. Paginação multi-page (cursor) escopo V1. Contas V4 com >500 campaigns raras. |
| **Sem `oneOf/allOf/anyOf`** | 3b.19B.1 convention. `start_date`+`end_date` vs `date_range` mutex validado em `resolve_meta_date_window` helper privado. |

---

## 3. Response Shape (row formatter)

**`meta_get_campaign_performance` retorna:**

```python
{
    "status": "success",
    "ad_account_id": "act_123456789",
    "ad_account_name": "Cliente XYZ - V4",
    "currency": "BRL",
    "date_range": {"start": "2026-04-26", "end": "2026-05-25"},
    "rows": [
        {
            "campaign_id": "23842456789",
            "campaign_name": "Brand BR - Search",
            "effective_status": "ACTIVE",
            "effective_status_label": "Ativa",
            "objective": "OUTCOME_SALES",
            "spend_brl": 1234.56,
            "impressions": 50000,
            "clicks": 800,
            "ctr": 0.016,
            "cpc_brl": 1.54,
            "reach": 12345,
            "frequency": 4.05,
            "purchases": 12,
            "purchases_value_brl": 5500.00,
            "purchase_roas": 4.45,
            "leads": 3
        },
        # ... ordenado por spend_brl DESC
    ],
    "total_rows": 23
}
```

**Diferenças per-level (level-specific fields prepended):**

| Tool | Extra fields per row |
|---|---|
| `meta_get_campaign_performance` | `campaign_id`, `campaign_name`, `objective` |
| `meta_get_ad_set_performance` | `ad_set_id`, `ad_set_name`, `campaign_id`, `campaign_name`, `optimization_goal`, `billing_event`, `daily_budget_brl` |
| `meta_get_ad_performance` | `ad_id`, `ad_name`, `ad_set_id`, `ad_set_name`, `campaign_id`, `campaign_name`, `creative_id` |

**Common fields todas 3 tools:** `effective_status`, `effective_status_label`, `spend_brl`, `impressions`, `clicks`, `ctr`, `cpc_brl`, `reach`, `frequency`, `purchases`, `purchases_value_brl`, `purchase_roas`, `leads`.

**Parser lógica chave:**
- `spend` Meta retorna string ("1234.56") → convert pra float `spend_brl`
- `purchases` = `next((a["value"] for a in row.get("actions",[]) if a["action_type"] == "purchase"), 0)`
- `purchases_value_brl` = idem em `action_values[]`
- `leads` = `action_type == "lead"` extraction
- `cpc_brl` Meta retorna pré-calculado; fallback `spend/clicks` se None
- `purchase_roas` Meta retorna lista `[{"action_type":"omni_purchase","value":"4.45"}]` — extrair `[0].value`
- `ctr` Meta retorna percentual (1.6 = 1.6%) — normaliza pra decimal (0.016)
- `daily_budget` Meta retorna em centavos — divide por 100 pra BRL

**Ordenação default:** `spend_brl DESC` (paridade Google `cost_micros DESC`).

---

## 4. Insights Module Implementation

`src/meta_ads/insights.py` (~150 LOC):

```python
"""Shared insights helpers for meta_get_*_performance tools (Sprint M.3).

Pure module — zero SDK imports, fully unit-testable.
"""
from datetime import date
from typing import Any, Literal

from src.mcp.tools._meta_common import META_EFFECTIVE_STATUS_LABELS

Level = Literal["campaign", "adset", "ad"]

# Per-level field lists (Meta Insights API field names)
_COMMON_INSIGHTS_FIELDS = [
    "spend", "impressions", "clicks", "ctr", "cpc",
    "reach", "frequency", "actions", "action_values", "purchase_roas",
]
INSIGHTS_FIELDS_CAMPAIGN = [
    "campaign_id", "campaign_name", "objective", "effective_status",
    *_COMMON_INSIGHTS_FIELDS,
]
INSIGHTS_FIELDS_ADSET = [
    "adset_id", "adset_name", "campaign_id", "campaign_name",
    "optimization_goal", "billing_event", "daily_budget", "effective_status",
    *_COMMON_INSIGHTS_FIELDS,
]
INSIGHTS_FIELDS_AD = [
    "ad_id", "ad_name", "adset_id", "adset_name",
    "campaign_id", "campaign_name", "creative_id", "effective_status",
    *_COMMON_INSIGHTS_FIELDS,
]


def build_insights_call(
    *,
    level: Level,
    ad_account_id: str,
    start: date,
    end: date,
    effective_status: str,
    limit: int,
) -> tuple[str, dict[str, Any]]:
    """Build Graph API edge path + params dict for a /insights call."""
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
    if effective_status != "ALL":
        params["filtering"] = (
            f'[{{"field":"effective_status","operator":"IN",'
            f'"value":["{effective_status}"]}}]'
        )
    return edge, params


def _extract_action_value(actions: list[dict[str, Any]] | None,
                          action_type: str) -> float:
    """Extract value of first action matching action_type. 0 if absent."""
    if not actions:
        return 0.0
    for a in actions:
        if a.get("action_type") == action_type:
            try:
                return float(a.get("value", 0))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _extract_purchase_roas(roas_list: list[dict[str, Any]] | None) -> float:
    """purchase_roas é lista: [{'action_type':'omni_purchase','value':'4.45'}]."""
    if not roas_list:
        return 0.0
    try:
        return float(roas_list[0].get("value", 0))
    except (TypeError, ValueError, IndexError):
        return 0.0


def parse_insights_row(row: dict[str, Any], level: Level) -> dict[str, Any]:
    """Parse single Meta Insights row → flat dict for MCP response."""
    spend = float(row.get("spend", 0) or 0)
    clicks = int(row.get("clicks", 0) or 0)
    actions = row.get("actions")
    action_values = row.get("action_values")

    common = {
        "effective_status": row.get("effective_status", "UNKNOWN"),
        "effective_status_label": META_EFFECTIVE_STATUS_LABELS.get(
            row.get("effective_status", ""), "Desconhecido"
        ),
        "spend_brl": round(spend, 2),
        "impressions": int(row.get("impressions", 0) or 0),
        "clicks": clicks,
        "ctr": round(float(row.get("ctr", 0) or 0) / 100, 4),
        "cpc_brl": round(float(row.get("cpc", 0) or 0), 4),
        "reach": int(row.get("reach", 0) or 0),
        "frequency": round(float(row.get("frequency", 0) or 0), 2),
        "purchases": int(_extract_action_value(actions, "purchase")),
        "purchases_value_brl": round(
            _extract_action_value(action_values, "purchase"), 2
        ),
        "purchase_roas": _extract_purchase_roas(row.get("purchase_roas")),
        "leads": int(_extract_action_value(actions, "lead")),
    }

    if level == "campaign":
        return {
            "campaign_id": row.get("campaign_id"),
            "campaign_name": row.get("campaign_name"),
            "objective": row.get("objective"),
            **common,
        }
    if level == "adset":
        return {
            "ad_set_id": row.get("adset_id"),
            "ad_set_name": row.get("adset_name"),
            "campaign_id": row.get("campaign_id"),
            "campaign_name": row.get("campaign_name"),
            "optimization_goal": row.get("optimization_goal"),
            "billing_event": row.get("billing_event"),
            "daily_budget_brl": (
                round(float(row.get("daily_budget", 0) or 0) / 100, 2)
                if row.get("daily_budget") else None
            ),
            **common,
        }
    # ad
    return {
        "ad_id": row.get("ad_id"),
        "ad_name": row.get("ad_name"),
        "ad_set_id": row.get("adset_id"),
        "ad_set_name": row.get("adset_name"),
        "campaign_id": row.get("campaign_id"),
        "campaign_name": row.get("campaign_name"),
        "creative_id": row.get("creative_id"),
        **common,
    }
```

**Helper a adicionar em `src/mcp/tools/_meta_common.py`:**

```python
META_EFFECTIVE_STATUS_LABELS: dict[str, str] = {
    "ACTIVE": "Ativa",
    "PAUSED": "Pausada",
    "ARCHIVED": "Arquivada",
    "DELETED": "Removida",
    "PENDING_REVIEW": "Em revisão",
    "DISAPPROVED": "Reprovada",
    "PREAPPROVED": "Pré-aprovada",
    "PENDING_BILLING_INFO": "Cobrança pendente",
    "CAMPAIGN_PAUSED": "Campanha pausada",
    "ADSET_PAUSED": "Ad set pausado",
}
```

**Tool handler pattern (~30 LOC cada):**

```python
async def handler(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    pool = connection.get_pool()
    today = datetime.now(UTC).date()

    try:
        start, end = resolve_meta_date_window(
            args.get("date_range", "LAST_30_DAYS"),
            args.get("start_date"), args.get("end_date"), today,
        )
    except ValueError as e:
        return {"status": "error", "error_message": f"Datas inválidas: {e}"}

    async with pool.acquire() as conn:
        account = await meta_ad_accounts.get_by_id(conn, args["ad_account_id"])
        if account is None:
            return {"status": "error", "error_message": "Ad account não encontrada."}

    edge, params = build_insights_call(
        level="campaign",  # ← unique per tool
        ad_account_id=args["ad_account_id"],
        start=start, end=end,
        effective_status=args.get("effective_status", "ACTIVE"),
        limit=args.get("limit", 100),
    )

    try:
        resp = await run_meta_graph_get(
            manager_id=ctx.manager_id, session_id=ctx.session_id,
            edge=edge, params=params,
            operation_name="meta_get_campaign_performance",  # ← unique per tool
            estimated_calls=1, audit_this_call=True,
            params_summary={
                "ad_account_id": args["ad_account_id"], "level": "campaign",
                "start": start.isoformat(), "end": end.isoformat(),
                "effective_status": args.get("effective_status", "ACTIVE"),
            },
        )
    except Exception as e:
        if hasattr(e, "message"):
            return {"status": "error", "error_message": e.message}
        return {"status": "error", "error_message": str(e)}

    rows = [parse_insights_row(r, "campaign") for r in resp.get("data", [])]
    rows.sort(key=lambda r: r["spend_brl"], reverse=True)

    return {
        "status": "success",
        "ad_account_id": args["ad_account_id"],
        "ad_account_name": account.account_name,
        "currency": account.currency,
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "rows": rows,
        "total_rows": len(rows),
    }
```

Adset + ad handlers idênticos, mudam apenas `level=` + `operation_name=`.

---

## 5. Testing Strategy

**Unit tests (`tests/unit/meta_ads/test_insights.py`) — ~15 tests:**

```
test_build_insights_call_campaign_level
test_build_insights_call_adset_level
test_build_insights_call_ad_level
test_build_insights_call_status_filter_all          # NÃO injeta filtering
test_build_insights_call_status_filter_active       # filtering injetado
test_parse_insights_row_campaign_full
test_parse_insights_row_adset_with_daily_budget    # cents→BRL conversion
test_parse_insights_row_ad_missing_optional
test_parse_insights_row_actions_extraction          # purchase + lead extracted
test_parse_insights_row_no_actions                  # purchases=0, leads=0
test_parse_insights_row_purchase_roas_first_only
test_parse_insights_row_ctr_normalization           # Meta % → decimal
test_extract_action_value_missing_action_type
test_extract_action_value_malformed_value           # string não-numérica → 0
test_extract_purchase_roas_empty_list
```

~50ms total, todos isolated.

**Integration tests (~14 tests):**

```
tests/integration/test_meta_get_campaign_performance.py   (~6 tests)
├── test_happy_path_returns_sorted_rows
├── test_effective_status_filter_active_default
├── test_effective_status_filter_all_omits_filtering
├── test_meta_api_error_returns_friendly_pt_br
├── test_account_not_found_returns_error
└── test_date_range_custom_overrides_preset

tests/integration/test_meta_get_ad_set_performance.py     (~4 tests)
tests/integration/test_meta_get_ad_performance.py         (~4 tests)
```

Mock Graph API via `respx`. Valida schema input → builder → parser → response shape + audit_log row gravado com `platform="meta"`.

**Smoke runbook (`docs/operacao/phase-M-3-bootstrap.md`) — 10 tests:**

```
T1: meta_get_campaign_performance happy path (conta V4 com Wellington admin)
T2: meta_get_ad_set_performance happy path
T3: meta_get_ad_performance happy path
T4: effective_status="ALL" inclui ARCHIVED rows
T5: custom date range start_date/end_date override
T6: per-value probe — cada effective_status enum (ACTIVE/PAUSED/ARCHIVED/ALL)
T7: error path — ad_account_id inexistente retorna friendly error
T8: error path — token expirado retorna PT-BR reconnect message
T9: BUC tracking — após 5 calls, meta_rate_counters.calls_used incrementa
T10: audit_log.platform="meta" + provider_request_id populated
```

**Regression guards (já existentes pegam Meta auto):**
- `test_no_composition_keywords_in_any_schema`
- `test_date_range_schemas_are_explicit`
- `test_tools_schemas`
- `test_list_tools_anthropic_alwaysload_count_matches_always_bucket` (22 always = 22 alwaysLoad pós-M.3)

**Pre-push gate:** `python scripts/check_pre_push.py` 5/5 PASS.

---

## 6. Risks & Out-of-Scope V0

### Risks com mitigation

| Risk | Prob. | Impacto | Mitigation V0 |
|---|---|---|---|
| `effective_status` enum incompleto (4 valores arbitrários) | Média | Médio | Per-value probe T6 smoke valida 4. Se DISAPPROVED/PENDING_REVIEW comum V4, add em V0.1 (1-line schema enum) |
| `actions` sem "purchase" → purchases=0 false negative | Baixa | Médio | Documentado em description: "purchases conta apenas eventos Pixel 'purchase'. Custom Conversions custom_event_X ficam ausentes V0" |
| BUC throttle Limited Access (Caminho B+) | Alta | Alto | Dogfood +3-6 calls/dia naturais. Monitor `meta_rate_counters.last_throttle_pct` >75%. Throttle real → priorize Full Access re-submit |
| Paginação multi-page (>500 rows V4 large account) | Baixa | Baixo | V0 hard cap `limit ≤ 500`. Conta MCC com 500+ campaigns raro V4. V1 cursor-based |
| Long-lived token expirou meio-sprint | Baixa | Alto | `run_meta_graph_get` já valida via `build_meta_api_for_manager` (M.2a) |
| Smoke real fails em ad_set_id format | Média | Baixo | Meta retorna `adset_id`. Parser normaliza pra `ad_set_id` snake_case |
| 3 tools = 3 audit_log rows + 3 BUC tickets/sessão | Média | Baixo | Audit overhead aceitável. BUC volume é Caminho B+ DESEJÁVEL |

### Deliberadamente OUT-OF-SCOPE V0

| Feature | Por que não V0 | Quando reconsider |
|---|---|---|
| Comparativo período anterior built-in | Wellington pediu paridade Google flat. Compose via 2 calls naturais | Se gestor pede em ≥3 dogfood sessões |
| Breakdowns (age/gender/country/device) | Sprint M.4 já cobre geo + device + hourly | M.4 scope |
| Status filter granular (DISAPPROVED/PENDING_REVIEW) | Per-value probe valida. Add se Wellington pede | Dogfood feedback D+7 |
| Custom action types (signup/add_to_cart/view_content) | 95% V4 dogfood usa purchase + lead. YAGNI | Se ≥1 cliente V4 usa Custom Conversion custom_event_X |
| Paginação cursor multi-page (>500 rows) | Hard cap 500 V0 | Conta real >500 captured em dogfood |
| `sort_by="purchases"` override | Default spend DESC mapeia 90% uso | Se Wellington pede top X por purchases |
| Async Insights jobs (range >90d) | Hard cap LAST_90_DAYS schema | V1 quando range >90d demanda real |
| `action_attribution_windows` custom | Default Meta 7d-click-1d-view aceitável | Se gestor pede attribution custom |

### Decisões codificadas

1. Sem `meta_apply_change` router branch (read-only sprint). M.16+ mutates terá.
2. Sem pre-flight call (read-only, sem entity-exists validation needed).
3. Sem dispatcher (single Graph API call por tool, sem chained mutations).
4. `audit_this_call=True` em todas 3 tools — reads sensíveis + Caminho B+ volume tracking essencial.
5. `estimated_calls=1` constant — single insights call per tool invocation.

---

## 7. Sprint Timeline & Roadmap

### Phases (subagent-driven recomendação)

| Phase | Entrega | Estimativa | Subagent |
|---|---|---|---|
| **A1** | `src/meta_ads/insights.py` (~150 LOC) + 15 unit tests | 1-2h | haiku (pure module) |
| **A2** | `_meta_common.py` adiciona `META_EFFECTIVE_STATUS_LABELS` | 15min | inline |
| **A3** | `meta_get_campaign_performance.py` + schema + bucket=always | 1h | sonnet |
| **A4** | `meta_get_ad_set_performance.py` + schema + bucket=defer (paralelo A5) | 30min | sonnet |
| **A5** | `meta_get_ad_performance.py` + schema + bucket=defer (paralelo A4) | 30min | sonnet |
| **A6** | 14 integration tests (3 tools × ~4-5 cada) | 1-2h | sonnet |
| **A7** | Pre-push gate + push deploy | 30min | inline |
| **B1** | Smoke runbook `phase-M-3-bootstrap.md` | 30min | smoke-runbook-generator |
| **B2** | Smoke execution Wellington manual em conta V4 + per-value probe | 30min | Wellington |
| **B3** | Signoff: reviewer + CLAUDE.md + sprint-history.md + findings | 30min | inline |

**Total estimado:** ~6-8h dev + 30min smoke = **~1 dia útil completo**.

**Paralelismo:** A1+A2 sequencial (insights.py é dep). A3+A4+A5 paralelo (arquivos isolated, padrão Sprint 3b.28 validado). A6 sequencial.

### Tool count após M.3

59 → **62** (21+1 always = 22, 38+2 defer = 40).

### Caminho B+ contribution

- M.3 ship → Wellington dogfood +3-6 calls/dia naturais
- Meta volume baseline atual: ~0 calls/dia
- 500 calls/15d threshold: ~33 calls/dia sustained
- M.3 + M.4 + M.5 shipped + dogfood real → ~10-15 calls/dia realistic
- **Janela 30-45d viável** se M.3+M.4+M.5 shipped até 2026-06-08 (D+14)

### Sequência ótima Caminho B+ próximos sprints

| Sprint | Tools | Prioridade |
|---|---|---|
| **M.4** | geo + device + hourly performance | Alta — multiplica volume per session |
| **M.5** | audience + top_creatives | Média |
| **M.6** | budget_pacing + funnel_metrics | Alta — gestores pedem semanal |

Skip não-Pareto pra acelerar volume.

### Decision gate F1→F2 interaction (Sprint 3b.39 outcome)

- D+7 = 2026-06-01 Wellington 5 perguntas estruturadas
- F1 fail → pause Meta sprints, re-prioritize Google
- Mitigação: M.3 ship antes D+7 = volume Meta começa acumular paralelo a F1 evaluation

### Dependências externas

- ✅ Meta App em Limited Access ativo (não bloqueia development)
- ✅ Wellington Meta OAuth conectado (validated M.2b)
- ✅ Pelo menos 1 conta V4 Lima Soares & Co com spend ativo
- ⚠️ Conta com ≥1 purchase event configurado (T1 valida `purchases` extraction)

---

## 8. Critérios de signoff sprint

- [ ] 15 unit tests PASS
- [ ] 14 integration tests PASS
- [ ] `python scripts/check_pre_push.py` 5/5 PASS
- [ ] CI green deploy production
- [ ] Smoke T1-T10 PASS Wellington manual em conta V4 (mínimo 1 conta real)
- [ ] `meta_rate_counters` incrementa após smoke T9
- [ ] `audit_log.platform="meta"` populated após smoke T10
- [ ] Per-value probe T6 valida 4 effective_status (remove se reject)
- [ ] CLAUDE.md atualizado (Current state + tool count 59→62)
- [ ] sprint-history.md row M.3 adicionada
- [ ] findings-catalog.md updated se F-finding novo

---

## 9. Pre-V0 checklist (antes de invocar writing-plans)

- [x] Brainstorming completo (todas 7 seções aprovadas)
- [ ] Spec doc commitado (este arquivo)
- [ ] Wellington review do spec
- [ ] writing-plans skill invocado pra Sprint M.3 isolado

### Escopo do writing-plans

writing-plans gera plan **APENAS para Sprint M.3** (3 tools paralelas + insights.py shared module). M.4+M.5+M.6 ganham seu próprio plan via `/sprint-bootstrap` quando chegar a vez.

---

**Sprint ready to start:** M.3 — 3 tools Meta performance (campaign always + adset/ad defer). Estimativa: ~1 dia útil.
