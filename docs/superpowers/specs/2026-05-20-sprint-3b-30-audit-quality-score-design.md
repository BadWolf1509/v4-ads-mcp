# Sprint 3b.30 — `audit_quality_score` (52nd MCP tool)

**Data:** 2026-05-20
**Sprint candidate:** 3b.30 (#1 fila ICE 504 do dogfood MO-JP 2026-05-19)
**Origem:** Dogfood MO-JP cleanup (sub-demanda #4 priorizada ICE 504)
**Status:** Spec aprovado, pre-plan

## 1. Problema

Wellington gasta ~30min/sessão em queries manuais via `run_gaql` em `keyword_view` pra identificar keywords problemáticas. Caso real dogfood:

```
SELECT ad_group.id, ad_group_criterion.keyword.text,
       ad_group_criterion.quality_info.quality_score, ...
FROM keyword_view
WHERE ad_group.id IN (175472286913, 183622658769)
ORDER BY ad_group_criterion.quality_info.quality_score ASC
```

Depois agrega manual pra detectar 3 padrões:
- **Waste**: keywords QS 1-2 com impressions > 0 e clicks 0 (queima budget sem retorno)
- **Promote**: keywords QS 7-10 BROAD com conversions ≥ 1 (deveriam ser EXACT pra reduzir CPC)
- **Duplicate intent**: mesma keyword text em ad_groups diferentes (poluição estrutural)

Sessões de cirurgia são **recorrentes** (D+14, D+30, mensais). Tool curada economiza ~30min/sessão.

**ICE 504** (Impact 8 × Confidence 9 × Effort 7) = #1 da fila pós-MO-JP cleanup.

## 2. Decisões de design

| Item | Decisão | Justificativa |
|---|---|---|
| **Scope flags V0** | 3 flags: candidate_pause + candidate_promote_exact + duplicate_intent | Wellington aprovou full V0 (não YAGNI parcial). Dogfood demanda 3 padrões simultâneos. |
| **Output shape** | Flat list ordered QS ASC + impressions DESC tie-break | Match workflow real V4 (lista priorizada de fix). Compact: 1 entry per keyword com flags[] array. Aggregable via `run_gaql.aggregate_by` (3b.29) se gestor quiser counts. |
| **Duplicate detection** | Exact text match | Cobre caso real dogfood 100% (Wellington detectou keyword exata em 2 ad_groups). Zero deps novas, trivial implementation, bug-resistant. YAGNI on Jaccard/Levenshtein. |
| **`duplicate_intent` semantics** | **Amplificação only** (não trigger isolado) | Só flagada quando keyword JÁ é candidate_pause OU candidate_promote_exact + aparece em multi ad_groups. Reduz false positives. Kw QS=5 normal em 2 ad_groups NÃO flagada (noise reduction). |
| **Date window** | `resolve_date_window` helper existing (preset OR start+end) | Convention V4 (15+ tools usam). Default LAST_30_DAYS cobre 90%. Custom range pra "pós-evento" / "conta nova". |
| **Filtros V0** | `customer_id` (required) + `ad_group_ids[]` (filter) + `min_impressions` (default 10) + `limit` (default 200, max 1000) | `min_impressions` é o único threshold que varia per conta (gigante vs Nutry-like). QS thresholds (1-2 / 7-10) são Google research convention — hardcoded = guard rail saudável. `limit` previne token overflow (3b.29 lesson). |
| **Status filter** | `ad_group_criterion.status = 'ENABLED'` only (hardcoded) | Tool é pra current state actionable. PAUSED já tratada. REMOVED out-of-scope. |
| **`quality_score IS NOT NULL`** | hardcoded filter | QS pode ser unset em kw recém-criadas (Google ainda calculando) — excluir, sem signal. |
| **Audit** | `audit_this_call=True` em `run_report` | Sensitive read (per-keyword detail). Match com `get_search_terms_report` pattern. |
| **Blast radius** | N/A (read-only, não-mutating) | apply_change não consome. |
| **Tool count** | 51 → **52** | Adiciona tool nova ao registry (test_no_unexpected_tools precisa update). |

## 3. Contrato (schema + I/O)

### 3.1 Input schema

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
        "min_impressions": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10000,
            "default": 10,
            "description": (
                "Threshold mínimo de impressions pra candidate_pause flag. "
                "Default 10 (contas médias). Reduza pra ~3 em contas low-volume."
            ),
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 200,
            "description": "Máximo de keywords retornadas. Truncated:true se exceder.",
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
```

### 3.2 Output shape

```json
{
  "customer_id": "1163862076",
  "date_range_resolved": {"start": "2026-04-20", "end": "2026-05-20", "days": 30},
  "filters_applied": {
    "ad_group_ids": null,
    "min_impressions": 10,
    "limit": 200
  },
  "total_flagged": 47,
  "truncated": false,
  "flagged_keywords": [
    {
      "ad_group_id": "175472286913",
      "ad_group_name": "[GPA][06][GERADORES]",
      "campaign_name": "[CP][...][PESQUISA]",
      "keyword_id": "92266285",
      "keyword_text": "gerador energia",
      "match_type": "BROAD",
      "quality_score": 2,
      "impressions": 482,
      "clicks": 0,
      "conversions": 0,
      "cost_brl": 0.0,
      "flags": ["candidate_pause"]
    },
    {
      "ad_group_id": "183622658769",
      "ad_group_name": "[GPA][06][GERADORES] B",
      "campaign_name": "[CP][...][PESQUISA]",
      "keyword_id": "379376135",
      "keyword_text": "gerador honda 5500",
      "match_type": "BROAD",
      "quality_score": 8,
      "impressions": 1240,
      "clicks": 87,
      "conversions": 3,
      "cost_brl": 142.50,
      "flags": ["candidate_promote_exact", "duplicate_intent"]
    }
  ]
}
```

Notar:
- `flags` é array (kw pode ter múltiplas)
- Ordered: `quality_score ASC, impressions DESC` (pior+volume primeiro)
- `total_flagged` = pre-truncation count; `truncated: true` se > limit
- `cost_brl` em decimal (não micros)

## 4. Comportamento (algoritmo)

```
1. Validate schema (Layer 1) — additionalProperties:false rejeita typos
2. Resolve date_window via resolve_date_window helper
3. Build GAQL:
   SELECT ad_group.id, ad_group.name, campaign.name,
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.keyword.match_type,
          ad_group_criterion.quality_info.quality_score,
          metrics.impressions, metrics.clicks,
          metrics.conversions, metrics.cost_micros
   FROM keyword_view
   WHERE ad_group_criterion.status = 'ENABLED'
     AND segments.date BETWEEN '<start>' AND '<end>'
     AND ad_group_criterion.quality_info.quality_score IS NOT NULL
     [AND ad_group.id IN (...)]
4. Execute via run_report (audit_this_call=True)
5. Parse rows → list[KeywordRow] (dataclass frozen slots=True)
6. flag_keywords(rows, min_impressions) → list[FlaggedKeyword]:
   a. Para cada row:
      - candidate_pause if QS<=2 AND impressions>=min_impressions AND clicks==0
      - candidate_promote_exact if QS>=7 AND match_type=='BROAD' AND conversions>=1
   b. Build text→adgroups map: {keyword_text: set(ad_group_id)} (apenas kw com >=1 flag)
   c. Segunda passada: pra kw já flagged, se keyword_text aparece em >1 ad_group_id,
      adicionar 'duplicate_intent' ao flags[]
   d. Filter: apenas kw com flags non-empty
   e. Sort: (quality_score ASC, impressions DESC)
   f. Truncate a limit, set truncated:true se pre-truncate > limit
7. Return shape com flagged_keywords + metadata
```

### 4.1 Edge cases

| Cenário | Comportamento |
|---|---|
| Conta sem keywords ENABLED | `flagged_keywords: []`, `total_flagged: 0` |
| Todas keywords QS=NULL (conta nova) | `flagged_keywords: []` (GAQL filter exclui) |
| 0 flagged em conta com muitos kw | empty list (todos kw são "saudáveis") |
| `ad_group_ids` filter com IDs inexistentes | Returns empty (no error — GAQL aceita IN clause empty match) |
| Kw aparece em 3+ ad_groups | duplicate_intent flagada se qualquer outra flag presente |

### 4.2 Não-objetivos V0

- Sem `match_types` filter (filter client-side se necessário)
- Sem Jaccard/Levenshtein detection
- Sem QS threshold configurable (1-2 / 7-10 hardcoded — Google convention)
- Sem PAUSED/REMOVED status (apenas ENABLED)
- Sem grouping per ad_group (flat list por design)
- Sem SUM/AVG aggregations no output (gestor agrega via run_gaql.aggregate_by se quiser)

## 5. Arquitetura

### 5.1 Estrutura de arquivos

```
src/mcp/tools/audit_quality_score.py             # NOVO: tool entry (schema + handler)
src/google_ads/queries/audit_quality_score.py    # NOVO: GAQL builder + row parser
src/google_ads/flag_keywords.py                  # NOVO: pure module — flag computation
tests/unit/test_flag_keywords.py                 # NOVO: 14 unit tests (pure)
tests/unit/test_audit_quality_score_query.py    # NOVO: 5 unit tests do GAQL builder
tests/integration/test_audit_quality_score.py    # NOVO: 3 wire-up tests
tests/unit/test_tools_schemas.py                 # MODIFY: add audit_quality_score em test_all_phase_2_tools_registered + test_no_unexpected_tools
```

### 5.2 Interface `src/google_ads/flag_keywords.py`

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class KeywordRow:
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
    """Compute flags, sort, truncate. Returns (flagged_list, total_pre_truncate).

    Pure function — não importa Google SDK; testable standalone.

    Algorithm:
    1. Per-row primary flags (candidate_pause, candidate_promote_exact)
    2. text→adgroups map em flagged subset only
    3. Second pass: amplify with duplicate_intent if text em multi ad_groups
    4. Filter empty flags out
    5. Sort: quality_score ASC, impressions DESC tie-break
    6. Truncate at limit
    """
```

### 5.3 Boundaries

- **`flag_keywords.py`**: pure function. Sem Google SDK imports. Testable standalone (14 unit tests).
- **`queries/audit_quality_score.py`**: GAQL builder + row parser. Match pattern `bulk_pause.py`.
- **`tools/audit_quality_score.py`**: orquestra Layer 1 schema validation → resolve_date_window → run_report → parse → flag_keywords pure → return shape.
- **Audit**: `audit_this_call=True` em `run_report`. Match com `get_search_terms_report` pattern (sensitive read).

## 6. Testes

### 6.1 Unit tests `tests/unit/test_flag_keywords.py` (14 testes)

| # | Teste | Coverage |
|---|---|---|
| 1 | `test_empty_rows_returns_empty` | `[]` → `[]`, total=0 |
| 2 | `test_candidate_pause_flagged_when_qs_low_imp_above_threshold_zero_clicks` | QS=2, imp=15, clicks=0, min=10 → flagged |
| 3 | `test_candidate_pause_NOT_flagged_when_impressions_below_threshold` | QS=2, imp=5, clicks=0, min=10 → not flagged |
| 4 | `test_candidate_pause_NOT_flagged_when_qs_3` | QS=3 não trigger (threshold 1-2) |
| 5 | `test_candidate_pause_NOT_flagged_when_clicks_above_zero` | QS=1, imp=100, clicks=2 → not flagged |
| 6 | `test_candidate_promote_exact_flagged_when_qs_high_broad_with_conversions` | QS=8, BROAD, conv=2 → flagged |
| 7 | `test_candidate_promote_exact_NOT_flagged_when_already_exact` | QS=9, EXACT, conv=5 → not flagged |
| 8 | `test_candidate_promote_exact_NOT_flagged_zero_conversions` | QS=9, BROAD, conv=0 → not flagged |
| 9 | `test_duplicate_intent_amplifies_existing_pause` | 2 kw "X" em ad_groups diff, ambas candidate_pause → flags=[pause, dup_intent] |
| 10 | `test_duplicate_intent_amplifies_promote` | Mesmo pra candidate_promote_exact |
| 11 | `test_duplicate_intent_NOT_added_without_other_flag` | 2 kw "Y" em ad_groups diff, ambas normal → not flagged |
| 12 | `test_duplicate_intent_NOT_added_same_ad_group` | Mesma kw 2× em mesmo ad_group → não conta como duplicate |
| 13 | `test_sort_qs_asc_then_impressions_desc` | 3 kw QS=2 com imp variando → ordered impressions desc tie-break |
| 14 | `test_truncate_at_limit_returns_total_pre_truncate` | 250 flagged + limit=200 → 200 returned, total=250 |

### 6.2 Unit tests `tests/unit/test_audit_quality_score_query.py` (5 testes)

| # | Teste | Coverage |
|---|---|---|
| 15 | `test_query_without_ad_group_filter` | base GAQL string sem cláusula AND ad_group.id IN |
| 16 | `test_query_with_ad_group_filter_three_ids` | adiciona AND ad_group.id IN ('1','2','3') |
| 17 | `test_query_includes_status_enabled_and_qs_not_null` | ambos filtros hardcoded presentes |
| 18 | `test_query_with_custom_date_range_yyyy_mm_dd` | BETWEEN com YYYY-MM-DD |
| 19 | `test_query_with_preset_date_range_LAST_30_DAYS` | preset resolve via resolve_date_window |

### 6.3 Integration tests `tests/integration/test_audit_quality_score.py` (3 testes)

| # | Teste | Coverage |
|---|---|---|
| 20 | `test_returns_flagged_keywords_shape` | mock fake rows → wire-up correto, output shape match spec 3.2 |
| 21 | `test_audit_this_call_true_logs_to_audit` | verify audit_log.record called com operation_name="audit_quality_score" |
| 22 | `test_respects_min_impressions_threshold` | min_impressions=50 → only flags high-volume |

### 6.4 Schema tests (already covered globally)

- `test_every_tool_has_valid_schema`
- `test_no_composition_keywords_in_any_schema` (3b.19B.1 — schema é simple types, sem oneOf/allOf/anyOf)
- `test_customer_id_pattern_is_consistent`
- `test_every_tool_input_schema_disallows_extra_properties`
- `test_date_range_schemas_are_explicit` (Sprint 3b.20 — date_range tem type:"string" + enum)
- `test_no_unexpected_tools` (MODIFY: adicionar `audit_quality_score`)
- `test_all_phase_2_tools_registered` (MODIFY: adicionar `audit_quality_score`)

### 6.5 Não testar (YAGNI)

- Performance em 10k kw (trivial Python dict ops)
- Concurrent calls (state-less)
- Schema regression standalone — coberto global

## 7. Smoke runbook (Sprint 3b.30 bootstrap)

| # | Test | Esperado |
|---|---|---|
| T1 | `audit_quality_score(customer_id=Nutry)` sem filters | Lista flagged keywords ou empty se Nutry sandbox não tem QS suficiente |
| T2 | T1 com `min_impressions=1` | Lower threshold pra Nutry low-volume; deve flagar algo se houver kw com QS 1-2 |
| T3 | T1 com `ad_group_ids=[193008426336]` | Filtra ao ad_group; outros ad_groups excluded |
| T4 | T1 com `start_date=2026-05-01, end_date=2026-05-14` | Custom range respected |
| T5 | T1 com `limit=10` | Returns max 10, truncated:true se mais existem |
| T6 | T1 com `date_range="LAST_7_DAYS"` | Preset resolve corretamente |
| T7 | Empirical validação flag candidate_pause | Identificar kw QS≤2 + imp≥10 + clicks=0 manualmente via GAQL, comparar com tool output |
| T8 | Empirical validação duplicate_intent | Criar 2 kw text idêntico em ad_groups diff (smoke residual), verificar amplificação |

**Conta sandbox:** Nutry `1163862076` (low-volume; pode requerer min_impressions=1).

## 8. Riscos e mitigações

| Risco | Probabilidade | Mitigação |
|---|---|---|
| QS field path GAQL errado (`ad_group_criterion.quality_info.quality_score`) | LOW (documented Google API) | T1 do smoke valida — se schema inválido, GAQL retorna 400 explícito |
| QS pode lagar entre queries (igual `campaign.status` B4) | LOW | Doc em description: "QS pode lagar — re-query se decisão crítica" |
| Performance em conta gigante (>10k kw) | MED | Truncate via `limit` (default 200), max 1000 |
| `duplicate_intent` false positives | LOW | Amplificação only — só quando outra flag presente |
| Nutry sandbox sem QS data útil pra smoke | MED | T7-T8 podem ser DEFERRED se Nutry zero stats (igual F45 pattern) |

## 9. Sprint sizing estimate

- **A1**: `flag_keywords.py` pure module + 14 unit tests (2h, sonnet)
- **A2**: `queries/audit_quality_score.py` GAQL builder + 5 unit tests (1h, haiku)
- **A3**: `tools/audit_quality_score.py` wrapper + schema (45min, haiku)
- **A4**: 3 integration tests + schema regression tests (45min, sonnet)
- **A5**: Smoke runbook + push + Wellington smoke execution (~1h, sonnet + Wellington manual)
- **A6**: Signoff + commit + push (15min)

**Total estimate:** ~5-6h impl + smoke + signoff = **~1 day sprint**.

Comparado com 3b.27 (combo) ~1.5d, 3b.28 (Customer Match) ~2d, 3b.29 (aggregate_by) ~half-day. Esse é entre os médios — feature nova ground-up.

## 10. Aprovação

- [x] Section 1 (problema + ICE motivation) — aprovado
- [x] Section 2 (decisões de design) — aprovado
- [x] Section 3 (contrato I/O) — aprovado
- [x] Section 4 (algoritmo) — aprovado
- [x] Section 5 (arquitetura) — aprovado
- [x] Section 6 (testes) — aprovado
- [x] Section 7-9 (smoke + riscos + sizing) — aprovado

**Next:** Wellington revisar spec → invokar `writing-plans` skill → implementação via subagent-driven-development.
