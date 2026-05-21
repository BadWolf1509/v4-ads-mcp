# Sprint 3b.35 — `audit_goal_attribution` Design Doc

**Date:** 2026-05-21
**Sprint:** 3b.35 (55ª MCP tool)
**ICE:** 360 (W3 dogfood [`dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md`](../../operacao/dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md))
**Author:** Wellington Ribeiro + Claude (brainstorming-driven)

---

## Context

Dogfood 2026-05-21 lição 47 revelou falsa premissa: gestor V4 assumiu que promover Secondary→Primary em ConversionAction era "cosmético KPI" — mexer só no dashboard sem afetar performance. Investigation revelou que `customer_conversion_goal.biddable=true` significa que ações primárias daquela (category, origin) AFETAM Smart Bidding em todas campaigns que usam o goal — NÃO é cosmético.

Frente 3 do MO-JP foi reavaliada após esse achado. Workflow manual atual pré-pre-flight:
1. `get_conversion_actions` — lista 22 actions de CONTACT category
2. GAQL custom `customer_conversion_goal` — extrair biddable per (category, origin)
3. Cross-reference manual em planilha
4. Decisão se safe promover

`audit_goal_attribution` consolida workflow em **1 tool call** com warning explícito por origin.

## Use case primário V0 (cravado em brainstorming)

**Pre-flight check antes de `update_conversion_action(primary_for_goal=...)`**. Gestor chama tool antes de qualquer mudança em `primary_for_goal` pra entender impact em Smart Bidding. Output expoe biddable per (category, origin) + lista de primary/secondary actions + warning textual se biddable=true.

## Design decisions cravadas (brainstorming 3 perguntas)

| Decisão | Escolha |
|---|---|
| **Escopo V0** | Origin_summary apenas (skip campaign_attribution V1) |
| **Category filter** | Optional, default = all (panorâmico) |
| **Warning shape** | Per-origin warning string PT-BR (null se biddable=false) |

Decisões assumidas (sem question explícita):
- Architecture: pure aggregator + wrapper sobre 2 `run_report` paralelas (padrão Sprint 3b.21/3b.31)
- Actions list inclusa (não só counts) — útil pra identificar qual action promover
- `status=ENABLED` filter hardcoded (PAUSED/REMOVED não afetam Smart Bidding)
- `audit_this_call=True` (sensitive read, exposes goal config)
- No truncation V0 (contas V4 típicas <50 actions)

---

## Section 1 — Architecture overview

**Pattern:** Pure aggregator + wrapper (padrão Sprint 3b.30 `audit_quality_score`, 3b.31 `audit_competitor_keywords`, 3b.33 `detect_drift`).

**Layer stack:**

1. **`src/google_ads/goal_attribution.py` — pure module** (testable standalone, zero Google SDK imports). 5 dataclasses frozen+slots: `ConversionActionRow`, `CustomerConversionGoalRow`, `ActionSummary`, `OriginSummary`, `GoalAttributionResult`. Função `audit_goal_attribution(actions, goals, *, category_filter, customer_id) → GoalAttributionResult`.
2. **`src/google_ads/queries/audit_goal_attribution.py`** — 2 GAQL builders (`build_conversion_action_query`, `build_customer_conversion_goal_query`) + 2 row parsers + 2 dict→dataclass converters.
3. **`src/mcp/tools/audit_goal_attribution.py` — tool wrapper** com `asyncio.gather` paralelo em 2 `run_report` calls. `audit_this_call=True` em ambas.

**Data flow:**

```
audit_goal_attribution({customer_id, category?})
  └─> asyncio.gather:
       ├─> run_report(conversion_action GAQL)
       │     └─> conversion_action.id/name/category/origin/primary_for_goal/
       │         include_in_conversions_metric/status WHERE status=ENABLED
       └─> run_report(customer_conversion_goal GAQL)
             └─> customer_conversion_goal.category/origin/biddable
  └─> dict_to_*_row[] (boundary conversion)
  └─> goal_attribution.audit_goal_attribution(actions, goals, category_filter, customer_id)
       └─> filter actions by category (if filter)
       └─> build goals_lookup: {(category, origin): biddable}
       └─> group_by (category, origin) → primary[] + secondary[]
       └─> lookup biddable from goals_lookup
       └─> generate warning_pt only if biddable=true
       └─> build origin_summary dict (key strategy depends on filter)
       └─> sort actions by name ASC within buckets
  └─> return result.to_dict()
```

**Reuse benefits:**

- 2 queries paralelas via `asyncio.gather` — padrão validado Sprint 3b.21 + 3b.31
- Boundary parser idêntico ao Sprint 3b.30/3b.31 (dict → frozen dataclass)
- Pure module testável standalone (zero Google SDK imports)
- F46 fix imune (não usa `change_event`)
- Sem dependência cross-tool (não invoca `get_conversion_actions` internally)

---

## Section 2 — Schema (input)

```python
# Sprint 3b.19A whitelist — 13 V4-focused categorias (após F17/F18/F19 fixes)
_V4_CATEGORIES = [
    "DEFAULT",
    "PAGE_VIEW",
    "PURCHASE",
    "SIGNUP",
    "SUBMIT_LEAD_FORM",
    "BOOK_APPOINTMENT",
    "REQUEST_QUOTE",
    "GET_DIRECTIONS",
    "OUTBOUND_CLICK",
    "CONTACT",
    "ENGAGEMENT",
    "STORE_VISIT",
    "STORE_SALE",
]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "category": {
            "type": "string",
            "enum": _V4_CATEGORIES,
            "description": (
                "Opcional. Filtra audit a uma única ConversionAction.category. "
                "Default sem filtro = retorna todas categories da conta agrupadas "
                "por (category, origin). Whitelist V4 13 valores (mesma de "
                "create_conversion_action 3b.19A — F17/F18/F19-safe)."
            ),
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}
```

**Notas:**

- `category` é **optional** (default = todas categories)
- Enum whitelist 13 V4 categorias (idêntica à `create_conversion_action` Sprint 3b.19A pós-F17/F18/F19 fixes)
- Sem `origin` filter V0 — gestor filtra client-side reading response
- Sem `include_paused_actions` flag V0 — incluir só `status=ENABLED` por default (PAUSED/REMOVED não afetam Smart Bidding ativo)
- **No composition keywords** (3b.19B.1 convention preservada)

---

## Section 3 — Output shape (response)

```python
{
    "customer_id": "7862230676",
    "category_filter": "CONTACT",   # null se sem filtro
    "origin_summary": {
        "WEBSITE": {
            "category": "CONTACT",
            "origin": "WEBSITE",
            "biddable": true,
            "warning": (
                "biddable=true: promover Secondary→Primary AFETA Smart Bidding "
                "(action vira biddable em todas campaigns que usam esta "
                "category+origin). NÃO é cosmético KPI."
            ),
            "primary_count": 7,
            "secondary_count": 13,
            "primary_actions": [
                {
                    "id": "123456",
                    "name": "Whatsapp - JPA",
                    "include_in_conversions_metric": true,
                    "status": "ENABLED",
                },
                # ... 7 total ordered by name ASC
            ],
            "secondary_actions": [
                {
                    "id": "234567",
                    "name": "Alisadora - JPA",
                    "include_in_conversions_metric": false,
                    "status": "ENABLED",
                },
                # ... 13 total ordered by name ASC
            ],
        },
        "CALL": {
            "category": "CONTACT",
            "origin": "CALL",
            "biddable": false,
            "warning": null,    # biddable=false = cosmético, sem warning
            "primary_count": 2,
            "secondary_count": 0,
            "primary_actions": [...],
            "secondary_actions": [],
        },
        # ... outras (category, origin) tuples
    },
    "total_actions_audited": 22,
    "origins_audited": ["WEBSITE", "CALL", "APP"],
    "categories_audited": ["CONTACT"],
}
```

**Decisões cravadas:**

- Top-level `origin_summary` é **dict keyed por origin** quando `category` filter ativo, ou keyed por `"{category}__{origin}"` (composite) quando sem filter (panorâmico)
- Cada bucket tem `category` + `origin` echoed explicit (não inferir só pela key)
- `warning` = `string` PT-BR se `biddable=true`, `null` caso contrário
- `primary_count` + `secondary_count` redundantes com `len(primary_actions)` mas explicit ajuda LLM scannar
- Actions list inclui `status` (filtramos `ENABLED` por default — mas tool retorna o que veio)
- `total_actions_audited` + `origins_audited` + `categories_audited` no top level — sanity metadata

**No truncation V0:** count de actions por origin tende a ser pequeno (<50 típico Nutry/MO-JP). Se conta grande, V1+ adiciona `limit` per origin.

---

## Section 4 — Algorithm (pure module logic)

```python
# src/google_ads/goal_attribution.py

from dataclasses import dataclass

# Status filter: tool retorna apenas ENABLED actions (PAUSED/REMOVED não afetam Smart Bidding)
_INCLUDED_STATUSES = frozenset({"ENABLED"})


@dataclass(frozen=True, slots=True)
class ConversionActionRow:
    """Boundary input — dict de conversion_action GAQL converte pra cá."""
    id: str
    name: str
    category: str
    origin: str
    primary_for_goal: bool
    include_in_conversions_metric: bool
    status: str


@dataclass(frozen=True, slots=True)
class CustomerConversionGoalRow:
    """Boundary input — dict de customer_conversion_goal GAQL converte pra cá."""
    category: str
    origin: str
    biddable: bool


@dataclass(frozen=True, slots=True)
class ActionSummary:
    """Output action representation (subset de ConversionActionRow)."""
    id: str
    name: str
    include_in_conversions_metric: bool
    status: str


@dataclass(frozen=True, slots=True)
class OriginSummary:
    category: str
    origin: str
    biddable: bool
    warning: str | None
    primary_count: int
    secondary_count: int
    primary_actions: tuple[ActionSummary, ...]
    secondary_actions: tuple[ActionSummary, ...]


@dataclass(frozen=True, slots=True)
class GoalAttributionResult:
    customer_id: str
    category_filter: str | None
    origin_summary: dict[str, OriginSummary]
    total_actions_audited: int
    origins_audited: tuple[str, ...]
    categories_audited: tuple[str, ...]


_WARNING_BIDDABLE_TRUE = (
    "biddable=true: promover Secondary→Primary AFETA Smart Bidding "
    "(action vira biddable em todas campaigns que usam esta "
    "category+origin). NÃO é cosmético KPI."
)


def audit_goal_attribution(
    actions: list[ConversionActionRow],
    goals: list[CustomerConversionGoalRow],
    *,
    category_filter: str | None,
    customer_id: str,
) -> GoalAttributionResult:
    """Aggregate conversion_actions by (category, origin), cross-ref biddable.

    Algorithm:
    1. Filter actions: status ∈ _INCLUDED_STATUSES (ENABLED-only) — defensive,
       complementa o `WHERE status='ENABLED'` server-side; protege contra
       Google retornar inadvertidamente PAUSED/REMOVED em edge cases (versão
       SDK / change_event lag scenarios).
       If category_filter, also filter by category.
    2. Build goals_lookup: {(category, origin): biddable} from goals list.
    3. Group filtered actions by (category, origin) tuple.
    4. Per group: split into primary_actions (primary_for_goal=true)
       + secondary_actions (primary_for_goal=false).
    5. Lookup biddable from goals_lookup; default False if absent (defensive).
    6. Generate warning_pt only if biddable=true (else None).
    7. Build origin_summary dict — key strategy:
       - if category_filter set: key = origin (e.g., "WEBSITE")
       - else: key = "{category}__{origin}" composite (e.g., "CONTACT__WEBSITE")
    8. Sort actions within primary/secondary lists by name ASC (stable display).
    9. Build metadata: total_actions_audited, origins_audited (sorted unique),
       categories_audited (sorted unique).

    Pure function — zero IO, zero Google SDK, fully testable.
    """
```

**Edge cases tratados:**

- Empty `actions` list → `origin_summary={}`, `total_actions_audited=0`
- Action sem `customer_conversion_goal` correspondente (raro, Google staleness) → `biddable=False` default + `warning=None` (não bloquear audit)
- `category_filter` que não bate com nenhuma action → `origin_summary={}` + `categories_audited=()` (zero results clean)
- Action com `status=REMOVED` ou `PAUSED` → filtered out
- Action com `primary_for_goal=False` → vai pra `secondary_actions`
- Multiple actions com mesmo (category, origin) → todas listed em primary/secondary buckets
- Goals list empty (rara) → todos `biddable=False` default

**GAQL builders** (`src/google_ads/queries/audit_goal_attribution.py`):

```python
def build_conversion_action_query() -> str:
    """GAQL pra conversion_action com fields necessários (audit_goal_attribution)."""
    return """
        SELECT
          conversion_action.id,
          conversion_action.name,
          conversion_action.category,
          conversion_action.origin,
          conversion_action.primary_for_goal,
          conversion_action.include_in_conversions_metric,
          conversion_action.status
        FROM conversion_action
        WHERE conversion_action.status = 'ENABLED'
    """.strip()


def build_customer_conversion_goal_query() -> str:
    """GAQL pra customer_conversion_goal (category, origin, biddable)."""
    return """
        SELECT
          customer_conversion_goal.category,
          customer_conversion_goal.origin,
          customer_conversion_goal.biddable
        FROM customer_conversion_goal
    """.strip()
```

**Boundary parsers** (também em `goal_attribution.py`):

```python
def dict_to_conversion_action_row(d: dict) -> ConversionActionRow:
    """Convert conversion_action row dict to ConversionActionRow dataclass.
    Defensive: missing fields default to "" or False."""
    return ConversionActionRow(
        id=str(d.get("id", "")),
        name=str(d.get("name", "")),
        category=str(d.get("category", "")),
        origin=str(d.get("origin", "")),
        primary_for_goal=bool(d.get("primary_for_goal", False)),
        include_in_conversions_metric=bool(d.get("include_in_conversions_metric", False)),
        status=str(d.get("status", "")),
    )


def dict_to_customer_conversion_goal_row(d: dict) -> CustomerConversionGoalRow:
    """Convert customer_conversion_goal row dict to CustomerConversionGoalRow.
    Defensive: missing fields default to "" or False."""
    return CustomerConversionGoalRow(
        category=str(d.get("category", "")),
        origin=str(d.get("origin", "")),
        biddable=bool(d.get("biddable", False)),
    )
```

---

## Section 5 — V0 cuts (out of scope)

| Item | Por que cortar V0 | V1+ candidato |
|---|---|---|
| **`campaign_attribution`** | Cross-check da lição 41 ("X de Y campaigns"). Requer `campaign_conversion_goal` GAQL adicional + agregação custom + custom_goal_config lookup. Complexity 3x da V0. | V1 dedicated `audit_campaign_goal_attribution` tool ou expand V1 |
| **`origin` filter** | Gestor pode pós-filter client-side (output já é dict keyed por origin). Schema simples. | V1 se demanda real surge |
| **`include_paused_actions` flag** | PAUSED não afeta Smart Bidding ativo. ENABLED é o que importa pre-flight. | YAGNI até demanda |
| **`limit` per origin** | Contas V4 típicas têm <50 actions por origin (Nutry tinha 14 total). | V1 se conta cresce |
| **Recommendation engine ("which secondary to promote?")** | Audit ≠ recommendation. Tool é passive. Active recommender = separate tool com modeling. | V2+ `recommend_goal_promotion` |
| **`custom_goal_config` lookup** | Custom goals são raras em V4 accounts (standard categories cobrem 95%). | V1+ se gestor pedir |
| **`account_default_conversion_action_settings`** | Cross-check account-level defaults vs per-action overrides. Niche. | V2+ |
| **Diff entre conta MCC default vs sub-account override** | Cross-account complexity. V0 single-account scope. | V3+ |
| **History tracking (biddable mudou desde quando?)** | Requer change_event integration (F46-aware) + storage. | V2+ se necessário |
| **`conversion_action_categories` filter no customer_conversion_goal** | F27 lição (Sprint 3b.22) — filter restricto a STORE values pelo Google. Nosso `category` filter é em ConversionAction, NÃO em customer_conversion_goal. | Não-aplicável |

---

## Section 6 — Testing strategy + V0 surface metrics

### Test pyramid

| Tipo | Count | Foco |
|---|---|---|
| Unit (pure module) | ~18 | Algorithm: filter status/category, biddable cross-ref, primary/secondary split, warning generation, composite key, sorting, metadata invariants |
| Unit (boundary) | ~4 | `dict_to_conversion_action_row` + `dict_to_customer_conversion_goal_row` parsers (missing fields, type coercion, defaults) |
| Unit (GAQL builders) | ~4 | `build_conversion_action_query` + `build_customer_conversion_goal_query` shape + status filter |
| Integration (tool wrapper) | ~3 | Wire-up: 2 `run_report` mocks via `asyncio.gather` → assemble → response shape. Schema validation. `category` filter passthrough. |
| Smoke (production) | T1-T6 | Real account Mestre da Obra JP (use case primário lição 47) |

### Unit tests detail (pure module, ~18)

- `test_empty_actions_returns_empty_summary` — `origin_summary={}`, `total_audited=0`
- `test_paused_action_excluded` — status filter ENABLED-only
- `test_removed_action_excluded` — status filter
- `test_category_filter_match_keeps_action` — category filter positive
- `test_category_filter_no_match_excludes_action` — category filter negative
- `test_no_filter_groups_all_categories` — composite key `"{cat}__{origin}"`
- `test_filter_set_uses_origin_only_key` — single category mode
- `test_primary_for_goal_true_in_primary_bucket` — split logic
- `test_primary_for_goal_false_in_secondary_bucket` — split logic
- `test_biddable_true_emits_warning_pt` — warning text exato
- `test_biddable_false_warning_is_null` — warning ausente
- `test_goal_absent_for_origin_defaults_biddable_false` — defensive default
- `test_multiple_actions_same_origin_all_listed` — no dedup
- `test_actions_sorted_by_name_asc_in_primary` — stable display
- `test_actions_sorted_by_name_asc_in_secondary` — stable display
- `test_metadata_total_audited_counts_post_filter` — invariant
- `test_metadata_origins_audited_unique_sorted` — invariant
- `test_metadata_categories_audited_unique_sorted` — invariant

### GAQL + boundary tests (~8)

- `test_build_conversion_action_query_includes_required_fields` — 7 fields no SELECT
- `test_build_conversion_action_query_filters_enabled_status` — WHERE clause `status = 'ENABLED'`
- `test_build_customer_conversion_goal_query_shape` — 3 fields no SELECT
- `test_build_customer_conversion_goal_query_no_filter` — sem WHERE
- `test_dict_to_conversion_action_row_handles_missing_status` — defaults
- `test_dict_to_conversion_action_row_bool_coercion_for_primary_for_goal` — bool
- `test_dict_to_customer_conversion_goal_row_handles_missing_biddable` — defaults
- `test_dict_to_customer_conversion_goal_row_full_dict` — happy path

### Smoke runbook V0 (6 tests)

| # | Cenário | Conta | Expected |
|---|---|---|---|
| T1 | Default (sem category filter) panorâmico | MO-JP `7862230676` | Multi-categories composite keys, todas origins, biddable cross-ref correto |
| T2 | Category filter = `CONTACT` | MO-JP | Apenas CONTACT actions, origin keyed simple (WEBSITE/CALL) |
| T3 | Category filter = `PURCHASE` | ML Antiguidades `7455088726` | ML é e-commerce, deveria ter PURCHASE actions com biddable=true expected |
| T4 | Biddable=true → warning emitido | MO-JP (qualquer origin biddable) | Warning text match `"AFETA Smart Bidding"` |
| T5 | Biddable=false → warning null | MO-JP (origin não-biddable) | warning=null em origins cosméticos |
| T6 | Caso real lição 47 MO-JP — Frente 3 reavaliação | MO-JP CONTACT WEBSITE | Confirma biddable=true + lista 7 primary + 13 secondary actions (dogfood numbers) |

**Defer conditions:**

- T3 DEFERRED se ML sem PURCHASE actions com biddable=true (env limitation pattern F41/F45)
- T6 DEFERRED se counts não baterem exatamente com dogfood numbers (re-verify before flag bug)

### V0 surface metrics

```
- 1 new MCP tool: audit_goal_attribution (tool count 54 → 55)
- 1 new pure module: src/google_ads/goal_attribution.py (~120 LOC)
- 1 new queries file: src/google_ads/queries/audit_goal_attribution.py (~50 LOC)
- 1 new tool wrapper: src/mcp/tools/audit_goal_attribution.py (~100 LOC)
- ~25 testes (18 unit pure + 4 boundary parser + 4 GAQL builder + 3 integration)
- 1 smoke runbook (phase-3b-35-bootstrap.md, 6 tests)
```

### Estimated effort

- A1 (haiku — pure module + 18 unit tests): ~25 min
- A2 (haiku — boundary parsers + GAQL builders + 8 tests): ~15 min
- A3 (sonnet — tool wrapper + 3 integration + schema + asyncio.gather): ~25 min
- A4 (smoke-runbook-generator): ~5 min
- A5 (controller smoke real + signoff): ~30 min

**TOTAL:** ~100 min (~1.7h) via subagent-driven (paralelo onde possível).

**Workflow:** A1 + A2 paralelo (arquivos diferentes), A3 depende de A1+A2 (importa dataclasses + builders). A4 paralelo a A3. A5 serial.

---

## Riscos + mitigações

| Risco | Mitigação |
|---|---|
| **`customer_conversion_goal.biddable` semantics confusa** | Documentar em tool description: "biddable=true significa que actions primárias daquela (category, origin) afetam Smart Bidding em campaigns usando esse goal". |
| **F17/F18/F19 (categorias removidas)** | Schema enum whitelist 13 V4-focused (idêntica à `create_conversion_action` 3b.19A pós-fixes). |
| **GAQL `WHERE status='ENABLED'` hardcoded poderia ser surpresa** | Documentar explicit em description + tool nome ("audit_goal_attribution" implica audit do estado ativo). V1 expõe flag se demanda. |
| **Goals list vazia em conta nova (sem conversion setup)** | Defensive `biddable=False` default + warning=null. Tool retorna `origin_summary={}` + counts zero — gestor entende conta sem setup. |
| **Action com category fora de `_V4_CATEGORIES`** (custom goal, rare) | Tool aceita qualquer category vinda do Google (input filter usa whitelist, mas grouping no algorithm não restringe). Audit não bloqueia. |
| **Token cap em conta grande** (>200 actions) | V0 sem `limit` per origin — risk em contas grandes. V1 adiciona limit se F22-style finding. |
| **B1 lag (3b.32)** | N/A — tool não usa change_event, sem lag. |

---

## References

- Dogfood source: [`docs/operacao/dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md`](../../operacao/dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md) seção "Tools curadas sugeridas — W3"
- Architecture precedent: Sprint 3b.30 ([`audit_quality_score`](../../operacao/phase-3b-30-bootstrap.md)) + 3b.31 ([`audit_competitor_keywords`](../../operacao/phase-3b-31-bootstrap.md)) + 3b.33 ([`detect_drift`](../../operacao/phase-3b-33-bootstrap.md))
- `customer_conversion_goal` API: Google Ads v24 resource ([context7 reference]) — fields `category`, `origin`, `biddable`
- F17/F18/F19 category whitelist origin: Sprint 3b.19A ([`phase-3b-19A-bootstrap.md`](../../operacao/phase-3b-19A-bootstrap.md))
- `customer_conversion_goal_categories` semantics (NÃO confundir): F27 Sprint 3b.22 — filter no ConversionValueRuleSet restrito a STORE values
- `primary_for_goal` mutation: Sprint 3b.27 ([`update_conversion_action`](../../operacao/phase-3b-27-bootstrap.md)) — V0 mutable fields = `name`, `primary_for_goal`
- No-composition-keywords convention: Sprint 3b.19B.1 ([CLAUDE.md](../../../CLAUDE.md) "No JSON Schema composition keywords")
