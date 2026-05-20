# Sprint 3b.31 — `audit_competitor_keywords` (53rd MCP tool)

**Data:** 2026-05-20
**Sprint candidate:** 3b.31 (#6 fila ICE 432 do dogfood MO-JP 2026-05-19)
**Origem:** Dogfood MO-JP cleanup massivo (detectou ~R$2k/mês waste em concorrência)
**Status:** Spec aprovado, pre-plan

## 1. Problema

Wellington detectou manualmente em sessão de cleanup MO ~R$2k/mês de gasto em concorrência (keywords positivas adicionadas com brand competitor + search terms onde Google entregou anúncio em queries de marca competidora). Processo manual envolveu:

1. Examinar `search_term_view` últimos 7d
2. Cross-check com `ad_group_criterion` ENABLED
3. Listar brands locais conhecidas (projecta, casa do construtor, promina, etc)
4. Detectar overlap manualmente

Outros clientes V4 herdam estrutura legacy similar → multiplica leverage.

**ICE 432** (Impact 9 × Confidence 8 × Effort 6) = #6 da fila pós-MO-JP cleanup.

## 2. Decisões de design

| Item | Decisão | Justificativa |
|---|---|---|
| **Scope V0** | Full: 2 dimensões (positive_keywords + search_terms) + cost projection + suggested_negatives | Cobre caso real dogfood literal. Cost projection é real (search_term_view tem cost_micros). Suggested negatives entrega valor imediato sem mutation auto-apply (gestor controla). |
| **Match algorithm** | Substring case-insensitive (normalize lowercase + strip) | Brand names tipicamente únicos (3+ chars). Funciona em PT-BR sem complicações de word boundary com acentos/hifens. Gestor controla input — pode passar full name pra evitar false positives. |
| **Date window** | Preset OR custom range (default LAST_7_DAYS) | Convention V4 (15+ tools usam). Default match dogfood literal (7d). Custom range cobre "pós-evento" / "primeira quinzena". |
| **Cost projection** | Real (sum `metrics.cost_micros / 1_000_000`) | Search_term_view tem cost por search term. Não inventa estimativa monthly (pode confundir). |
| **Suggested negatives match types** | EXACT + PHRASE per matched brand (2 suggestions) | EXACT bloqueia query exata; PHRASE bloqueia qualquer query contendo o termo. Wellington escolheu cobrir ambos. Gestor decide qual aplicar via `add_negative_keywords` separado. |
| **Suggested negatives — escope brands** | Apenas brands com hit (positive OR search_term) | Brands passadas mas zero match → sem evidência de problema → não sugerir negative (evita ruido). |
| **Positive keywords filter** | `status = 'ENABLED'` AND `negative = FALSE` (hardcoded) | Tool é pra detectar onde gestor está PAGANDO pra aparecer em brand competitor. Negative criteria não pagam. |
| **No date filter em positive_keywords** | State-based query | Keyword é current state, não histórico. Date filter aplica só a search_terms. |
| **Parallel queries** | `asyncio.gather` em 2 `run_report` calls | Eficiência (latency reduction); ambas independent. |
| **Audit** | `audit_this_call=True` em ambas calls | Sensitive (per-keyword + per-search-term detail). |
| **Blast radius** | N/A (read-only) | `apply_change` não consome. |
| **Tool count** | 52 → **53** | Adiciona tool nova ao registry. |

## 3. Contrato (schema + I/O)

### 3.1 Input schema

```python
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
            "description": "Máximo entries por lista (positive_keywords e search_terms). truncated:true se exceder.",
        },
    },
    "required": ["customer_id", "competitor_brands"],
    "additionalProperties": False,
}
```

### 3.2 Output shape

```json
{
  "customer_id": "1163862076",
  "date_range_resolved": {"start": "2026-05-13", "end": "2026-05-19", "days": 7},
  "competitor_brands": ["projecta", "casa do construtor"],
  "summary": {
    "positive_keywords_count": 3,
    "positive_keywords_truncated": false,
    "search_terms_count": 12,
    "search_terms_truncated": false,
    "total_cost_wasted_brl": 187.50,
    "suggested_negatives_count": 4
  },
  "positive_keywords": [
    {
      "ad_group_id": "175472286913",
      "ad_group_name": "[GPA][06][GERADORES]",
      "campaign_name": "[CP][...]",
      "keyword_id": "92266285",
      "keyword_text": "comprar projecta",
      "match_type": "BROAD",
      "matched_brand": "projecta",
      "status": "ENABLED"
    }
  ],
  "search_terms": [
    {
      "search_term": "gerador projecta 5500",
      "matched_brand": "projecta",
      "ad_group_name": "[GPA][06][GERADORES]",
      "campaign_name": "[CP][...]",
      "impressions": 142,
      "clicks": 5,
      "cost_brl": 42.30
    }
  ],
  "suggested_negatives": [
    {
      "text": "projecta",
      "match_type": "EXACT",
      "reason": "Brand competidora encontrada em 1 keyword positive + 8 search terms (R$ 95.50 cost)"
    },
    {
      "text": "projecta",
      "match_type": "PHRASE",
      "reason": "Brand competidora — PHRASE bloqueia qualquer query contendo o termo"
    }
  ]
}
```

Notar:
- `summary` agrega counts + cost + truncate flags
- `positive_keywords` ordered alphabetical por `matched_brand`, depois `ad_group_name`
- `search_terms` ordered por `cost_brl` DESC (waste maior primeiro)
- `suggested_negatives` ordered: matched brand alphabetical, então EXACT antes PHRASE
- Apenas brands com hit aparecem em `suggested_negatives` (brands zero-match são omitidas)

## 4. Comportamento (algoritmo)

```
1. Validate schema (Layer 1) — additionalProperties:false rejeita typos
2. Normalize brands: [b.strip().lower() for b in competitor_brands]
3. Resolve date_window via resolve_date_window helper
4. Parallel via asyncio.gather:
   a. Query positive_keywords (keyword_view, sem date filter):
      SELECT ad_group.id, ad_group.name, campaign.name,
             ad_group_criterion.criterion_id,
             ad_group_criterion.keyword.text,
             ad_group_criterion.keyword.match_type
      FROM keyword_view
      WHERE ad_group_criterion.status = 'ENABLED'
        AND ad_group_criterion.negative = FALSE
   b. Query search_terms (search_term_view, com date filter):
      SELECT search_term_view.search_term,
             ad_group.name, campaign.name,
             metrics.impressions, metrics.clicks, metrics.cost_micros
      FROM search_term_view
      WHERE segments.date BETWEEN '<start>' AND '<end>'
5. Parse rows → dataclasses (KeywordRow, SearchTermRow)
6. match_competitor_brands(keyword_rows, search_term_rows, brands, limit):
   a. Pra cada keyword_row: se any brand é substring de kw_text.lower() →
      append MatchedKeyword com matched_brand = primeira brand match
   b. Pra cada search_term_row: same logic → MatchedSearchTerm
   c. Sort matched_keywords por (matched_brand ASC, ad_group_name ASC)
   d. Sort matched_search_terms por cost_brl DESC
   e. total_cost_wasted_brl = sum(matched_search_terms[*].cost_brl)
   f. Build text→counts dict pra suggested_negatives reason
   g. Pra cada brand que tem hit em pos OR st: gerar 2 SuggestedNegative
      (EXACT + PHRASE) com reason text counts + cost
   h. Truncate cada lista (pos + st) a limit; set truncated flags
   i. Return (matched_keywords, matched_search_terms, suggested_negatives,
              totals_dict, total_cost_wasted_brl)
7. Build output shape com summary + arrays
```

### 4.1 Edge cases

| Cenário | Comportamento |
|---|---|
| Conta sem keywords ENABLED | `positive_keywords: []` |
| Date window sem search_terms | `search_terms: []`, `total_cost_wasted_brl: 0.0` |
| Brand zero matches | NÃO incluída em `suggested_negatives` (sem evidência) |
| Brand muito short ("MO" 2 chars) | Schema rejeita (`minLength: 3`); 3+ chars passa, gestor controla false positive risk |
| Keyword matched por 2 brands | `matched_brand` = primeira brand insertion order (mesma kw aparece 1× output) |
| Search term matched por 2 brands | Same: 1 entry com primeira match |
| Conta com >1000 matches | `truncated_*: true`, listas cortadas a `limit`, totals refletem pre-truncate |

### 4.2 Não-objetivos V0

- Sem fuzzy/Levenshtein matching
- Sem auto-apply negatives (gestor decide manual via `add_negative_keywords`)
- Sem monthly cost projection (real cost do período)
- Sem cross-account audit
- Sem match_type filter (audit todos os match types)
- Sem dedup quando mesma kw em 2 ad_groups (each row é um entry distinct)

## 5. Arquitetura

### 5.1 Estrutura de arquivos

```
src/mcp/tools/audit_competitor_keywords.py            # NOVO: tool entry
src/google_ads/queries/audit_competitor_keywords.py   # NOVO: 2 GAQL builders + parsers
src/google_ads/competitor_analysis.py                 # NOVO: pure module — match logic
tests/unit/test_competitor_analysis.py                # NOVO: 14 unit tests pure
tests/unit/test_audit_competitor_keywords_query.py    # NOVO: 6 unit tests GAQL
tests/integration/test_audit_competitor_keywords.py   # NOVO: 3 wire-up tests
tests/unit/test_tools_schemas.py                      # MODIFY: add em 2 lists
```

### 5.2 Interface `src/google_ads/competitor_analysis.py`

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


@dataclass(frozen=True, slots=True)
class SearchTermRow:
    search_term: str
    ad_group_name: str
    campaign_name: str
    impressions: int
    clicks: int
    cost_brl: float


@dataclass(frozen=True, slots=True)
class MatchedKeyword:
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
    search_term: str
    matched_brand: str
    ad_group_name: str
    campaign_name: str
    impressions: int
    clicks: int
    cost_brl: float


@dataclass(frozen=True, slots=True)
class SuggestedNegative:
    text: str
    match_type: str  # "EXACT" | "PHRASE"
    reason: str


def normalize_brand(brand: str) -> str:
    """Lowercase + strip. Pure helper."""
    return brand.strip().lower()


def match_competitor_brands(
    *,
    keyword_rows: list[KeywordRow],
    search_term_rows: list[SearchTermRow],
    competitor_brands: list[str],
    limit: int,
) -> tuple[
    list[MatchedKeyword],         # positive_keywords (truncated, sorted)
    list[MatchedSearchTerm],      # search_terms (truncated, sorted cost desc)
    list[SuggestedNegative],      # suggested_negatives (EXACT+PHRASE per matched brand)
    dict[str, int],               # totals: counts + truncated flags pre-truncate
    float,                        # total_cost_wasted_brl (pre-truncate sum)
]:
    """Match keywords + search terms against competitor brands, suggest negatives.

    Pure function — não importa Google SDK; testable standalone.

    Returns:
        Tuple of (truncated lists + totals + cost).
        totals dict has keys: positive_count, positive_truncated, search_count,
        search_truncated, suggested_count.
    """
```

### 5.3 Boundaries

- **`competitor_analysis.py`**: pure function. Sem Google SDK imports. Testable standalone.
- **`queries/audit_competitor_keywords.py`**: 2 GAQL builders + 2 row parsers. Match pattern `audit_quality_score.py` (3b.30).
- **`tools/audit_competitor_keywords.py`**: orquestra schema validation → resolve_date_window → 2 parallel `run_report` via `asyncio.gather` → dict→dataclass boundary → `match_competitor_brands` pure → return shape.
- **Audit**: `audit_this_call=True` em ambas calls. `operation_name="audit_competitor_keywords"`.
- **Parallelism**: `asyncio.gather` reduz latency (2 sequential ~2-3s → ~1-1.5s paralelo).

## 6. Testes

### 6.1 Unit tests `tests/unit/test_competitor_analysis.py` (14 testes)

| # | Teste | Coverage |
|---|---|---|
| 1 | `test_empty_inputs_returns_empty_everything` | `[]` rows + `[]` brands → empty everything |
| 2 | `test_no_matches_returns_empty_with_brands` | Brands populated, zero matches → empty + no suggested |
| 3 | `test_normalize_brand_strips_and_lowercases` | `" Projecta "` → `"projecta"` |
| 4 | `test_positive_keyword_substring_match` | Brand "projecta", kw "comprar projecta gerador" → matched |
| 5 | `test_positive_keyword_case_insensitive` | Brand "Projecta" matches "PROJECTA 5500" |
| 6 | `test_search_term_match_aggregates_cost` | 3 matched search_terms, costs [10, 20, 30] → total 60.0 |
| 7 | `test_suggested_negatives_2_per_matched_brand` | 1 matched brand → 2 sugestões (EXACT + PHRASE) |
| 8 | `test_suggested_negatives_skip_brand_without_matches` | Brand zero matches → não inclui em suggested |
| 9 | `test_keyword_matched_by_first_brand_when_multiple_overlap` | Brands ["projecta", "comprar"], kw "comprar projecta" → matched_brand="projecta" (insertion order) |
| 10 | `test_search_terms_sorted_by_cost_desc` | 3 search_terms costs [50, 10, 30] → output [50, 30, 10] |
| 11 | `test_truncate_positive_keywords_at_limit` | 250 matches + limit=200 → 200 returned, total=250 |
| 12 | `test_truncate_search_terms_at_limit` | Same pra search_terms |
| 13 | `test_reason_string_includes_counts_and_cost` | Brand com 2 pos + 3 st (R$95.50) → reason text contém "2", "3", "95.50" |
| 14 | `test_brand_minimum_length_documented_not_enforced_at_pure_layer` | Brand "MO" 2 chars passa em pure (gestor controla); schema upstream enforces minLength 3 |

### 6.2 Unit tests `tests/unit/test_audit_competitor_keywords_query.py` (6 testes)

| # | Teste | Coverage |
|---|---|---|
| 15 | `test_positive_keywords_query_includes_status_enabled_and_negative_false` | Hardcoded filters |
| 16 | `test_positive_keywords_query_no_date_filter` | State-based, sem segments.date BETWEEN |
| 17 | `test_search_terms_query_includes_date_between` | Date YYYY-MM-DD aplicado |
| 18 | `test_positive_keywords_query_selects_required_fields` | 6 fields presentes pra KeywordRow |
| 19 | `test_search_terms_query_selects_required_fields` | 6 fields presentes pra SearchTermRow |
| 20 | `test_parse_keyword_row_handles_match_type_enum` | match_type.name extrai BROAD/PHRASE/EXACT |

### 6.3 Integration tests `tests/integration/test_audit_competitor_keywords.py` (3 testes)

| # | Teste | Coverage |
|---|---|---|
| 21 | `test_returns_full_shape_with_matched_brands` | Mock 2 queries, fake matches → output shape match spec 3.2 |
| 22 | `test_audit_this_call_true_in_both_calls` | Ambas chamadas a run_report têm `audit_this_call=True` |
| 23 | `test_2_queries_called_in_parallel_via_gather` | Inspect mock — verify asyncio.gather usage (assertions sobre call timing OR pelo menos verificar que ambas foram chamadas) |

### 6.4 Schema regression (already covered globally)

- `test_every_tool_has_valid_schema`
- `test_no_composition_keywords_in_any_schema`
- `test_customer_id_pattern_is_consistent`
- `test_every_tool_input_schema_disallows_extra_properties`
- `test_date_range_schemas_are_explicit` (Sprint 3b.20)
- `test_no_unexpected_tools` (MODIFY: adicionar `audit_competitor_keywords`)
- `test_all_phase_2_tools_registered` (MODIFY: adicionar `audit_competitor_keywords`)

### 6.5 Não testar (YAGNI)

- Performance em 10k+ search_terms (trivial)
- Concurrent users (state-less)

## 7. Smoke runbook (Sprint 3b.31 bootstrap)

| # | Test | Esperado |
|---|---|---|
| T1 | `audit_competitor_keywords(customer_id=Nutry, competitor_brands=["nutry"])` | Match em positive_keywords se houver kw "nutry" — sanity check |
| T2 | T1 com brand inexistente em Nutry (ex: "kjadflk") | Empty positive_keywords + search_terms; zero suggested_negatives |
| T3 | T1 com 2 brands, uma matched, outra não | Apenas brand matched aparece em suggested_negatives |
| T4 | T1 com `date_range="LAST_30_DAYS"` | Custom date resolution |
| T5 | T1 com `start_date+end_date` custom | Custom range respected |
| T6 | T1 com `limit=5` | Truncate validation se Nutry tem >5 matches |
| T7 | Empirical match validation: criar kw "projecta-test" em ad_group sandbox, verificar match | Confirma substring case-insensitive em produção |
| T8 | Schema validation: brand 2-char | Rejeitada (minLength 3) |

**Conta sandbox:** Nutry `1163862076` (low-volume; pode requerer T7 manual mutation pra validar match real).

## 8. Riscos e mitigações

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Brand muito short ("MO" 2 chars) false positives | MED | Schema `minLength: 3` enforce |
| Search_term_view GAQL field path errado | LOW | T1 smoke valida; Context7 confirms v24 schema |
| Conta com >1000 matched entries → truncation perde context | LOW | `limit` default 200 + truncated flag explícito + summary preserva total |
| 2 queries paralelas rate limit | LOW | rate_limit.py gerencia per-call; 2 ops countados |
| Lag de cost data Google (search_term_view cost pode lagar) | LOW | Mesma nota B4 — documentar em description |
| Mesma kw em 2 ad_groups apareça 2× output | LOW | by design: each ad_group_criterion é distinct entry (gestor pode ver onde kw está espalhada) |

## 9. Sprint sizing estimate

- **A1**: `competitor_analysis.py` pure module + 14 unit tests (2h, sonnet)
- **A2**: `queries/audit_competitor_keywords.py` 2 GAQL builders + parsers + 6 unit tests (1.5h, haiku/sonnet)
- **A3**: `tools/audit_competitor_keywords.py` wrapper + `asyncio.gather` + schema (1h, sonnet — paralelismo é judgment)
- **A4**: 3 integration tests + smoke runbook (1h, sonnet+subagent)
- **A5**: Smoke execution Nutry + signoff (~30min, controller)

**Total estimate:** ~5-6h impl + smoke + signoff = **~half-day sprint**. Match com 3b.30 sizing.

## 10. Aprovação

- [x] Section 1 (problema + ICE motivation) — aprovado
- [x] Section 2 (decisões de design) — aprovado
- [x] Section 3 (contrato I/O) — aprovado
- [x] Section 4 (algoritmo) — aprovado
- [x] Section 5 (arquitetura) — aprovado
- [x] Section 6 (testes) — aprovado
- [x] Section 7-9 (smoke + riscos + sizing) — aprovado

**Next:** Wellington revisar spec → invokar `writing-plans` skill → implementação via subagent-driven-development.
