# Sprint 3b.21 — `get_negative_keywords_audit` com `created_date` enrichment design

**Status:** Draft → user review pending
**Owner:** Wellington (`wellinton.ribeiro@v4company.com`)
**Date:** 2026-05-17
**Predecessor:** Sprint 3b.20 (`date_range` clarification + search_terms default) — closes relatorio 2026-05-17 finding #3 (último finding aberto do relatório que dirigiu 3b.20).

## Goal

Enriquecer o response de `get_negative_keywords_audit` com `created_date` + `added_by_email` por critério, e adicionar bloco `additions_summary` no root, para que gestor V4 consiga dizer "X negativas adicionadas esta semana" em report semanal sem cruzar manualmente com `get_change_history`.

Resolve dogfood pain explícito do Wellington em relatório 15/05/2026 §1.3: "Pra falar 'X negativas adicionadas no período do relatório' precisei cruzar manualmente com `get_change_history`. Inviável pra relatório semanal." e "no Word entregue acabei falando do volume total (467) sem distinguir adições recentes."

## Context / why now

- **Único finding aberto** do relatório 2026-05-17. #1 + #2 fechados em Sprint 3b.20 (smoke MO-JP 7/7 PASS em 17/05). Finalizar o relatório dá fechamento limpo + libera próximos sprints pra create patterns.
- **Sem dependência de Standard Access** — análise empírica 2026-05-17 mostrou que quota Basic comporta 30x worst-case (ver CLAUDE.md subsection Standard Access).
- **Low quota:** +1 op por chamada (1→2 GAQL queries em paralelo). Hoje uso é 11/15k; mesmo doubling não move agulha.
- **Pattern reuse:** `_parse_resource_path` em `get_change_history.py` já faz exatamente o parsing necessário para extrair criterion_id de resource paths compound `{campaign_id}~{criterion_id}` (Sprint 3b.6 A5 finding documenta esse pattern).
- **Cross-cutting helper opportunity:** extrair `_parse_resource_path` para `src/google_ads/queries/_common.py` torna disponível para future tools que precisem de change_event JOINs (provavelmente surgirá em outras enrichment use cases).

## Non-goals (v0)

- **`include_history` opt-out toggle** — descartado em brainstorming (param que sempre será `true` é YAGNI; +1 op/call é negligível).
- **`added_since` filter param** — descartado (summary block resolve o weekly use case; gestor filtra client-side se quiser ver detalhe).
- **Enrichment para criteria não-keyword** — tool atual já filtra `type='KEYWORD'`; manter escopo.
- **Enrichment para mudanças UPDATE/REMOVE** (e.g., "negativa pausada esta semana") — out of scope. `created_date` semantics é só sobre CREATE event.
- **Timestamp precision além de date** — `created_date` retorna `YYYY-MM-DD`, sem hora/minuto. Para precisão maior gestor usa `get_change_history` direto.
- **Retorno de criterion_id-level audit_log** (quem REMOVED via MCP) — utility `get_my_audit_log` (Sprint 3b.13) já cobre isso.
- **Tracking de negative_placement / negative_user_list / etc** — escopo atual da tool é só `type=KEYWORD`. Future tool `get_audience_audit` ou similar fica fora.

## Tool surface

### Name
`get_negative_keywords_audit` (mantém — não é novo tool, é enrichment do existente).

### Description (PT-BR, atualizada)

```
Lista palavras-chave negativas aplicadas em nivel de campanha, com data
de criacao e usuario que adicionou (quando rastreavel via change_event,
retention ~30 dias). Util pra auditoria de cobertura de negativas,
identificar duplicacoes ou gaps, e narrar "X negativas adicionadas no
periodo" em report semanal. Bloco additions_summary no root agrega
counts por janela (7d / 30d / pre-30d-ou-desconhecido).
```

### Input schema

**Sem mudança.** Mantém apenas `customer_id` (string, pattern `^[0-9]{10}$`) obrigatório, `additionalProperties: false`.

### Response shape

```json
{
  "customer_id": "7862230676",
  "total_negatives": 467,
  "additions_summary": {
    "last_7_days": 12,
    "last_30_days": 38,
    "pre_30_days_or_unknown": 429
  },
  "by_campaign": [
    {
      "campaign_id": "21359547724",
      "campaign_name": "[GPC][JPA][LEADS][SEG][MESTRE DA OBRA]",
      "negatives": [
        {
          "criterion_id": "1234567890",
          "keyword_text": "concorrente xyz",
          "match_type": "EXACT",
          "created_date": "2026-05-10",
          "added_by_email": "wellinton.ribeiro@v4company.com"
        },
        {
          "criterion_id": "9876543210",
          "keyword_text": "grátis",
          "match_type": "BROAD",
          "created_date": null,
          "added_by_email": null
        }
      ]
    }
  ]
}
```

### Field semantics

| Field | Type | Semantics |
|---|---|---|
| `total_negatives` | int | Mantém. Total de negativas keyword campaign-level. |
| `additions_summary.last_7_days` | int | Negativas com `created_date >= today - 7d`. |
| `additions_summary.last_30_days` | int | Negativas com `created_date >= today - 30d`. Inclui contagem de last_7_days. |
| `additions_summary.pre_30_days_or_unknown` | int | Negativas com `created_date == null`. Cobre: (a) adicionadas >30d atrás, (b) auto-apply Google (não loga em change_event), (c) gaps de retention. |
| `negatives[*].created_date` | string `YYYY-MM-DD` ou `null` | Data do evento CREATE em `change_event`. `null` se >30d ou não rastreado. |
| `negatives[*].added_by_email` | string ou `null` | `change_event.user_email`. `null` mesmas condições que `created_date`. |

**Invariante:** `last_30_days + pre_30_days_or_unknown == total_negatives`. `last_7_days <= last_30_days`.

## Implementation overview

### Architectural changes

1. **Extract `_parse_resource_path` helper** de `src/mcp/tools/get_change_history.py` para `src/google_ads/queries/_common.py` (ou novo `src/google_ads/resources.py` se preferir isolation). Razão: cross-tool reuse + 3b.21 precisa do mesmo parser. Imports atualizados em `get_change_history.py`.

2. **New GAQL builder** `negative_criterion_creations_query(start, end)` em `src/google_ads/queries/change_history.py`:
   ```sql
   SELECT
     change_event.change_resource_name,
     change_event.change_date_time,
     change_event.user_email
   FROM change_event
   WHERE change_event.change_date_time BETWEEN '{start}' AND '{end}'
     AND change_event.change_resource_type = 'CAMPAIGN_CRITERION'
     AND change_event.resource_change_operation = 'CREATE'
   ORDER BY change_event.change_date_time DESC
   LIMIT 10000
   ```
   - Mesma 30-day cap que `change_history_query` (via `_MAX_DAYS=30` shared check ou inline).
   - LIMIT 10000 — match com `change_history` schema max. Realistic V4 30d burst é <500 criterion creates por account.

3. **Tool body refactor** em `src/mcp/tools/get_negative_keywords_audit.py`:
   - Substituir single `run_report` por `asyncio.gather` de:
     - Query A: existente (`negative_keywords_audit_query`) — full state of current negatives
     - Query B: novo (`negative_criterion_creations_query` para `LAST_30_DAYS` window)
   - Build dict `creations_by_criterion: dict[str, dict]` keyed por criterion_id, value = `{created_date, added_by_email}`.
     - Quando múltiplos CREATE events para mesmo criterion_id (raro — re-add após remove), tomar o MAIS RECENTE.
   - Para cada negativa em Query A result, enrich com lookup em `creations_by_criterion`. Default `null` se ausente.
   - Compute `additions_summary` iterando enriched negatives.

### Quota cost

Atual: 1 op/call. Novo: 2 ops/call (1 paralelo group). Net: +100% por chamada, mas absoluto trivial (hoje 11 ops/dia total).

### Latency

Parallel via `asyncio.gather` → wall-clock idêntico ao atual (limited by slower of 2 queries; ambas leves).

### Edge cases handled

1. **Negativa adicionada via auto-apply Google** — `change_event` pode não logar (Google client_type filter). Result: `created_date=null`. Acceptable.

2. **Negativa removida e re-adicionada em 30d** — `change_event` tem 2 CREATEs com criterion_ids DIFERENTES (Google cria novo criterion no re-add). Tool retorna info do criterion_id ATUAL (que é o mais recente). Sem ambiguidade.

3. **Negativa adicionada >30d atrás + UPDATE recente** (e.g., match_type changed) — `change_event` tem UPDATE event mas não CREATE. Result: `created_date=null` (correto — "data adicionada" semantics, não "última modificação"). Se gestor quer ver mudanças, usa `get_change_history` direto.

4. **Conta sem negativas** — Query A retorna `[]`, Query B retorna `[]` ou eventos órfãos. `by_campaign=[]`, `additions_summary` zeros, `total_negatives=0`. Sem crash.

5. **Mais de 10k CREATEs em 30d** — improbabilidade prática (V4 = 23 contas, típico account adiciona <50 negativas/30d). Se ocorrer, ordering DESC garante que pegamos os mais recentes; antigas perdem enrichment (fall back para `null`). Surfacing warning é YAGNI v0.

6. **Race condition: negativa removida entre Query A e Query B** — Query A vai ter o criterion já fora do current state, então não aparece no enriched output. Não problema.

## Testing strategy

### Unit tests (`tests/unit/`)

- **`test_query_negative_criterion_creations.py`** (new file):
  - `test_query_format_with_valid_range()` — GAQL produced é syntaticamente correto.
  - `test_query_raises_RangeTooWideError_over_30d()` — reuse `_MAX_DAYS` check pattern.
  - `test_query_includes_resource_type_filter()` — string contains check.
  - `test_query_includes_create_operation_filter()` — string contains check.

- **`test_get_negative_keywords_audit.py`** (extend existing or create):
  - `test_audit_includes_created_date_per_criterion()` — mock both queries, assert enriched negatives have `created_date` populated where match exists, `null` otherwise.
  - `test_audit_summary_block_counts_correctly()` — fixture com 5 negatives (2 last_7_days, 1 between 7-30d, 2 pre_30d), assert summary counts match.
  - `test_audit_handles_multiple_creates_for_same_criterion()` — fixture com 2 CREATE events for same criterion_id, assert tool picks MOST RECENT.
  - `test_audit_handles_empty_change_event_result()` — Query B returns `[]`, all `created_date=null`, summary `last_7_days=0, last_30_days=0, pre_30_days_or_unknown=total_negatives`.
  - `test_audit_handles_empty_negatives_result()` — Query A returns `[]`, response is empty + zeros.

- **`test_parse_resource_path_relocated.py`** (or extend existing `test_get_change_history.py`):
  - Verify import path still works for `get_change_history.py` after relocation.
  - Verify new import path works for `get_negative_keywords_audit.py`.

### Integration tests (`tests/integration/`)

- **`test_get_negative_keywords_audit.py`** (extend if exists, else create):
  - One end-to-end test with mocked Google Ads SDK responses for both queries, verifying full enrichment + summary computation path.
  - Marker `@pytest.mark.integration`.

### Schema test

- N/A. No schema changes (input stays same).

## Smoke runbook outline (Sprint 3b.21 bootstrap)

**Account:** Mestre da Obra JP `7862230676` (467 negativas conforme relatório).

- **T1:** Basic call, assert response includes new `additions_summary` block + per-criterion enrichment for at least some criteria.
  - `get_negative_keywords_audit(customer_id="7862230676")`
  - Expected: `additions_summary.last_30_days >= 1` (Wellington added some negatives in recent sprint smokes).
  - Expected: At least 1 negative has `created_date != null` + `added_by_email == "wellinton.ribeiro@v4company.com"`.

- **T2:** Validate retention boundary — pick a recent negative we know was added in last 7d via `get_change_history` cross-reference, assert it shows up in `last_7_days` count.

- **T3:** Validate retention boundary OUTSIDE — most of 467 should be `created_date=null` since they're old. Assert `pre_30_days_or_unknown` is bulk (>400 expected for MO-JP).

- **T4:** Invariant check: `last_30_days + pre_30_days_or_unknown == total_negatives` AND `last_7_days <= last_30_days`.

- **T5 (cross-tool sanity):** Run for a 2nd account with different volume (Nutry or Expresso). Confirm tool works across different shapes (low-volume vs high-volume accounts).

## Quality gates

- `python scripts/check_pre_push.py` PASS 5/5 antes do push.
- Smoke T1-T5 PASS first try em conta real antes de signing off.
- 11ª sprint consecutiva sem novos bugs no smoke se T1-T5 PASS clean (stabilization-class sprint).

## Out-of-scope follow-ups (spawn-task candidates)

- **`get_audience_audit`** — análoga para audiences (user_list / user_interest). Se cliente operacionalizar audience exclusion (post A4 fix), enrich também. Sprint futura.
- **`get_my_audit_log` filter by criterion_id** — utility já existe (3b.13) mas não filtra por target_id. Se gestor pede "quem REMOVED esta negativa via MCP", ampliar `get_my_audit_log` schema. YAGNI v0.

## Open questions / decisions log

- **Decisão:** `created_date` retorna `YYYY-MM-DD` (date), não datetime. Brainstorming question 1 cobriu — gestor não precisa precisão hour para weekly report.
- **Decisão:** Sem filter param (`added_since` etc) — brainstorming question 2 confirmou, summary block resolve.
- **Decisão:** `additions_summary` no root como bloco nested (consistente com `get_account_overview.current/previous` pattern), não inline fields.
- **Decisão:** Extract `_parse_resource_path` para `_common.py` — cross-tool reuse + foundation pra futuros change_event JOINs.
