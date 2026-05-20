# Sprint 3b.29 — `run_gaql.aggregate_by` (B5 fix)

**Data:** 2026-05-20
**Sprint candidate:** 3b.29 (ou 3b.29.x, dependendo de prioriza vs `audit_quality_score`/`remove_*`)
**Origem:** Dogfood MO-JP 2026-05-19 (sub-demanda B5)
**Status:** Spec aprovado, pre-plan

## 1. Problema (B5 dogfood)

`run_gaql` retorna rows densas em queries de alta cardinalidade:

- `get_search_terms_report` 14d → >60k chars (truncamento + save-to-file)
- `campaign_asset` GAQL com 3 fields enxutos → **89k chars (272 rows × ~330 chars/row JSON)**

Workaround atual de Wellington: Bash + Python + `Counter()` pra ler arquivo + agregar manualmente. Funciona mas overhead de contexto + comandos extras por sessão.

**Sugestão original (dogfood):**
> *"`run_gaql` aceitar parâmetro `aggregate_by: [field_a, field_b]` que faz GROUP BY + COUNT internamente, retornando agregado."*

GAQL nativo **não suporta** GROUP BY (verified em `src/google_ads/queries/bulk_pause.py:20` — está na blacklist `_FORBIDDEN_KEYWORDS`). Aggregation precisa ser **client-side post-fetch**.

## 2. Decisões de design

| Item | Decisão | Justificativa |
|---|---|---|
| **Escopo** | Apenas `run_gaql` (escape hatch) | YAGNI: B5 cataloga caso de query custom. Tools curadas (`get_search_terms_report` etc.) mantêm contrato estável. Propagar pra tools curadas em Sprint 3b.30+ **se** uso real revelar recorrência. |
| **Operações V0** | COUNT apenas | (1) B5 literal usou `Counter()`. (2) GAQL nativo já agrega `metrics.*`. (3) AVG client-side é perigoso (Simpson's paradox). (4) SUM/AVG/MIN/MAX = especulação sem caso documentado. |
| **Output shape** | Replace `rows` por `groups[]` ordenado por count DESC | Idiomático (`pandas.groupby().size().sort_values(ascending=False)`); match com `Counter().most_common()`. Adiciona `total_rows_scanned` + `group_count` + `truncated` como metadata. |
| **Truncation** | Aggregate ANTES de truncar + safety net hard 10k raw rows | Correctness first (counts exatos). Hard limit 10k previne OOM em queries patológicas. Contas V4 típicas geram <5k rows; 10k tem margem confortável. |
| **Audit** | `aggregate_by` em `params_summary` do audit_log | Transparency — gestor consegue auditar quais agregações foram executadas. |
| **Backward compat** | `aggregate_by` é OPCIONAL. Ausente → shape atual mantido (`rows[]`). | Zero regression risk em callers existentes. |

## 3. Contrato (schema + I/O)

### 3.1 Schema (addition em `run_gaql._SCHEMA`)

```python
"aggregate_by": {
    "type": "array",
    "items": {"type": "string"},
    "minItems": 1,
    "maxItems": 5,
    "description": (
        "Opcional. Lista de field paths (dotted) pra agrupar rows e contar. "
        "Ex: ['field_type','asset.type']. Retorna groups[] ordenado por count "
        "DESC ao invés de rows[]. Limite hard: 10k raw rows antes de agregar."
    ),
},
```

### 3.2 Output sem `aggregate_by` (unchanged — backward compat)

```json
{
  "customer_id": "1163862076",
  "row_count": 272,
  "truncated": false,
  "rows": [...]
}
```

### 3.3 Output com `aggregate_by` (novo)

```json
{
  "customer_id": "1163862076",
  "total_rows_scanned": 272,
  "group_count": 8,
  "truncated": false,
  "groups": [
    {"key": {"field_type": "STRUCTURED_SNIPPET", "asset.type": "STRUCTURED_SNIPPET"}, "count": 96},
    {"key": {"field_type": "SITELINK", "asset.type": "SITELINK"}, "count": 72}
  ]
}
```

Notar:
- `rows` **omitido** (não vazio).
- `row_count` substituído por `total_rows_scanned` (mais explícito).
- `group_count` = `len(groups)` pós-truncate.
- `truncated: true` se group_count > 1000 (raro).

## 4. Comportamento (algoritmo passo a passo)

```
1. Stream rows do Google API via execute_gaql_raw (sem limite client-side prévio)
2. Se len(raw_rows) > 10_000:
     raise ValueError("query retornou >10k rows; refine WHERE clause antes de agregar")
3. Aggregate client-side: dict {tuple_of_key_values: count}
4. Ordenar grupos por count DESC (stable sort — empates preservam ordem de inserção)
5. Truncate groups[] a 1000 grupos (mesmo limite atual de rows[])
6. Set truncated:true se group_count_pre_truncate > 1000
7. Retornar shape com groups[] + metadata
```

### 4.1 Edge cases

| Cenário | Comportamento |
|---|---|
| Field path aponta pra field não presente em row | Row contribui pra grupo com `None` no key (não ignora). Preserves visibility. |
| Empty result (0 rows) | `{group_count: 0, groups: [], total_rows_scanned: 0}` |
| Nested field path (ex: `asset.type`) | Extrai via dotted lookup no flat dict retornado por `MessageToDict` |
| Empate em count | first-seen wins (stable sort) |

### 4.2 Não-objetivos V0

- Sem SUM/AVG/MIN/MAX (apenas COUNT)
- Sem `having` filter (ex: "só grupos com count >= 10")
- Sem `order_by: "key"` (sempre count DESC)
- Sem aggregate em tools curadas (escopo limitado a `run_gaql`)

## 5. Arquitetura

### 5.1 Estrutura de arquivos

```
src/mcp/tools/run_gaql.py                # UPDATE: aceita aggregate_by no schema, branch shape
src/google_ads/aggregation.py            # NOVO módulo puro: aggregate_rows(rows, group_by)
tests/unit/test_aggregation.py           # NOVO: 9 unit tests puros
tests/integration/test_utility_tools.py  # UPDATE: 4 wire-up tests pra run_gaql + aggregate_by
```

### 5.2 Interface `src/google_ads/aggregation.py`

```python
def aggregate_rows(
    rows: list[dict[str, Any]],
    group_by: list[str],
) -> list[dict[str, Any]]:
    """Agrupa rows por field paths (dotted) e retorna [{key:{...}, count:N}] desc.

    Pure function — não importa Google SDK; testável sem fixture pesado.

    Args:
        rows: flat dicts vindos de MessageToDict (preserving_proto_field_name=True).
        group_by: 1-5 field paths dotted. Ex: ['field_type', 'asset.type'].

    Returns:
        Lista de grupos sorted by count desc. Key é dict mapeando cada field path
        ao valor encontrado (None se field missing). Empates preservam insertion order.
    """
```

### 5.3 Boundaries

- `aggregation.py` é **pure function** — não importa nada do Google SDK. Testável standalone sem mock pesado.
- `run_gaql.py` orquestra: chama `execute_gaql_raw` → checa `aggregate_by` → roda `aggregate_rows` se presente → monta output shape correto.
- Safety limit (10k raw rows) vive em `run_gaql.py` (boundary com Google API), **não** em `aggregation.py` (pure).
- Audit log: `aggregate_by` vai pra `params_summary`. Tool já é audited.

## 6. Testes

### 6.1 Unit tests (`tests/unit/test_aggregation.py`, 9 testes)

| # | Teste | Coverage |
|---|---|---|
| 1 | `test_empty_rows_returns_empty_groups` | `[]` → `[]` |
| 2 | `test_single_field_group_by` | 5 rows × `field_type` → 2 grupos sorted DESC |
| 3 | `test_multi_field_group_by` | grupos por `['field_type', 'asset.type']` |
| 4 | `test_nested_field_path_dotted_lookup` | `'campaign.id'` extrai value de nested dict |
| 5 | `test_missing_field_yields_none_key` | row sem field → grupo com `None` |
| 6 | `test_sort_is_count_desc` | confirma ordenação descendente |
| 7 | `test_ties_in_count_preserves_insertion_order` | stable sort |
| 8 | `test_single_row_returns_one_group_count_1` | minimal positive case |
| 9 | `test_group_by_field_not_in_any_row` | todos `None` → 1 grupo `{key: {field: None}, count: N}` |

### 6.2 Integration tests (extend `test_utility_tools.py`, 4 testes)

| # | Teste | Coverage |
|---|---|---|
| 10 | `test_run_gaql_without_aggregate_by_returns_rows` | regressão: shape original mantido |
| 11 | `test_run_gaql_with_aggregate_by_returns_groups_shape` | aggregate_by ativo → groups[] + metadata |
| 12 | `test_run_gaql_aggregate_truncates_at_1000_groups` | mocked 1500 grupos → truncated:true |
| 13 | `test_run_gaql_rejects_more_than_10k_raw_rows` | safety net hard limit raises ValueError |

### 6.3 Schema tests (já cobertos)

`test_every_tool_has_valid_schema` + `test_no_composition_keywords_in_any_schema` (3b.19B.1 convention) — `aggregate_by` é simple `array of string`, sem `oneOf/allOf/anyOf`.

### 6.4 Não testar (YAGNI)

- Performance (10k rows × dict aggregate ≈ ~1ms; trivial em Python)
- Concurrent calls (state-less, sem race condition)

## 7. Smoke runbook (Sprint 3b.29.X bootstrap)

| # | Teste | Esperado |
|---|---|---|
| T1 | `run_gaql(query="SELECT campaign.id FROM campaign LIMIT 5")` sem aggregate_by | Shape original (`rows[]`) |
| T2 | T1 + `aggregate_by:["campaign.status"]` | `groups[]` com 1-3 grupos por status |
| T3 | `campaign_asset` query + `aggregate_by:["field_type","asset.type"]` | Reproduce o caso B5 — confirma agregação real |
| T4 | `aggregate_by:["nonexistent.field"]` | 1 grupo `{key:{nonexistent.field:None}, count:N}` |
| T5 | Query que retorna 0 rows + `aggregate_by` | `{group_count:0, groups:[], total_rows_scanned:0}` |
| T6 | Smoke query patológica (>10k rows hipotético) | Erro PT-BR claro sobre limite 10k |

## 8. Riscos e mitigações

| Risco | Probabilidade | Mitigação |
|---|---|---|
| OOM em query muito grande | LOW | Safety net 10k raw rows hard fail antes de aggregate |
| Field path errado silently retorna `None` em todos grupos | LOW | T4 do smoke valida; documentar no description |
| Wellington usa `aggregate_by` em tool curada (não suportado) | LOW | Schema rejeita campo desconhecido em outras tools (additionalProperties: false) |
| Future SUM/AVG demand | LOW | YAGNI — sprint pequeno depois adiciona; aggregator é refactor-friendly |

## 9. Sprint sizing estimate

- **A1**: `aggregation.py` + 9 unit tests (1-2h, sonnet)
- **A2**: `run_gaql.py` schema + branch + wire (30min, haiku)
- **A3**: 4 integration tests (30min, haiku)
- **A4**: smoke runbook + execução Nutry (Wellington manual, ~30min)
- **A5**: signoff + commit + push (5min)

**Total estimate:** ~3-4h de implementação + ~30min smoke + signoff = **~half-day sprint**.

Comparado com 3b.27 (combo, 1.5 dia) e 3b.28 (Customer Match, 2 dias), este é dos menores. Atrativo se Wellington escolher 3b.29 = `audit_quality_score` (maior) como next-in-queue, e este vira 3b.29.x.

## 10. Aprovação

- [x] Section 1 (contrato I/O) — aprovado
- [x] Section 2 (truncation + safety) — aprovado
- [x] Section 3 (arquitetura) — aprovado
- [x] Section 4 (testes) — aprovado
- [x] Section 5 (resumo executivo) — aprovado

**Next:** Wellington revisar spec → invokar `writing-plans` skill → implementação via subagent-driven-development.
