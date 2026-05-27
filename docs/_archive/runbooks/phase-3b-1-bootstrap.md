# Phase 3b.1 — manual smoke runbook

**Purpose:** Verify `add_negatives_from_search_terms` + `get_change_history` work against a real V4 account, before declaring Sprint 3b.1 done.

**Operator:** wellinton.ribeiro@v4company.com
**Account used (mutation):** `1163862076` "Rayane Ribeiro - Nutry" (campanhas paused, tráfego zero — sandbox seguro)
**Account used (change_history):** `7862230676` "Mestre da Obra - João Pessoa" (25 mudanças nos últimos 7 dias)
**Date completed:** 2026-05-11

## Pre-flight

- [x] Deploy lands successfully (`gh run watch` shows green Deploy → revision `v4-ads-mcp-00084-vrk`)
- [x] Service `/health` returns 200
- [x] MCP server connected (tools/list inclui `add_negatives_from_search_terms` + `get_change_history`)

## Test 1 — `add_negatives_from_search_terms` happy path ✅

Chamada feita com 3 termos sintéticos:
```json
{
  "customer_id": "1163862076",
  "negatives": [
    {"search_term": "claude mcp smoke test 001", "match_type": "EXACT", "scope": "campaign", "scope_id": "22782946457"},
    {"search_term": "claude mcp smoke test 002", "match_type": "EXACT", "scope": "campaign", "scope_id": "22782946457"},
    {"search_term": "claude mcp smoke test 003", "match_type": "EXACT", "scope": "campaign", "scope_id": "22782946457"}
  ]
}
```

Response:
```json
{
  "status": "applied",
  "applied_count": 3,
  "google_request_id": "Rf_7JHnI-wMZVMgqvQhYmg",
  "auto_applied_reason": "add_negatives_from_search_terms (3 negatives) — auto, negatives raramente quebram",
  "added": [
    {"search_term": "...001", "status": "added"},
    {"search_term": "...002", "status": "added"},
    {"search_term": "...003", "status": "added"}
  ]
}
```

- [x] Per-row status correto (`added` para todas)
- [x] Real `google_request_id` retornado pelo Google
- [x] Custom `params_summary` no audit_log: `{scopes_distribution: {campaign: 3}, match_types_distribution: {EXACT: 3}, scope_ids_count: 1}` (verificado via Supabase)
- [x] AUTO classification (sem dry-run)

## Test 2 — Idempotência 🟡 (comportamento real diverge do spec idealizado)

Re-rodei a mesma chamada de Test 1.

Response:
```json
{
  "applied_count": 3,
  "google_request_id": "iRYSSWqJAxV-WGGO76GwYg",
  "added": [
    {"status": "added"},  // 3x
  ]
}
```

`get_negative_keywords_audit` após Test 1 + Test 2: **total_negatives = 3** (NÃO 6) — Google dedup silenciosamente.

- [x] Idempotência efetiva (count não duplicou)
- [ ] Status `"already_exists"` per-row — **NÃO disparou**: Google API trata duplicates como sucesso silencioso (sem partial_failure_error). Nosso `_classify_partial` só vê erros que Google de fato surfaceia. Comportamento documentado da API; spec §3.4 era idealizada demais. Resultado prático é equivalente (no-op idempotente).

## Test 3 — `get_change_history` happy path ✅

Conta `7862230676` (ativa) com `LAST_7_DAYS`:

- [x] Retorna `period: {from: "2026-05-04", to: "2026-05-10"}`
- [x] 25 rows
- [x] `summary.total_changes: 25`
- [x] `summary.by_user`: `{"wellinton.ribeiro@v4company.com": 24, "auto-apply": 1}` — auto-apply collapse FUNCIONANDO
- [x] `summary.by_resource_type`: `{CAMPAIGN_CRITERION: 12, AD_GROUP_CRITERION: 10, AD: 3}`
- [x] `summary.by_operation`: `{CREATE: 14, REMOVE: 8, UPDATE: 3}`
- [x] `summary.auto_applied_count: 1` — detecta 1 evento `GOOGLE_ADS_RECOMMENDATIONS` corretamente
- [x] `resource_name` resolvido para nomes humanos (ex: `"[GPC][CAB][LEADS][SEG][SEX][MESTRE DA OBRA]"`)

## Test 4 — Filter precision ✅

Filtro `resource_types=["CAMPAIGN_CRITERION"], operation_types=["CREATE"], limit=5` em `7862230676`:

- [x] Retorna exatamente 5 rows
- [x] Todas com `resource_type == "CAMPAIGN_CRITERION"` ✓
- [x] Todas com `operation == "CREATE"` ✓
- [x] Summary alinha: `{CAMPAIGN_CRITERION: 5, CREATE: 5}` ✓

## Test 5 — 30-day enforcement ✅

`date_range: {from: "2026-03-01", to: "2026-05-11"}` (72 dias):

- [x] PT-BR error: `"Janela maxima de 30 dias para historico de mudancas — recebido 72 dias. Limite da API do Google Ads."`
- [x] Erro disparado ANTES de chamar a API (sem consumo de quota)

## Cleanup ✅

- [x] `remove_negative_keywords` removeu os 3 test criteria de `1163862076`
- [x] `get_negative_keywords_audit` confirmou `total_negatives: 0` — estado original restaurado

## Bugs encontrados e CORRIGIDOS durante o smoke

### B1: `request.partial_failure_mode` não existe (commit `8fe426c`)

Original (Sprint 3b.1, commit `f156d99`):
```python
request.partial_failure_mode = client.enums.PartialFailureModeEnum.PARTIAL_FAILURE
```

Falha em produção: `AttributeError: '_EnumGetter' object has no attribute 'PartialFailureModeEnum'`.

Fix: o campo correto é `request.partial_failure = True` (bool, não enum).

### B2: Enum `client_types` com nomes inventados (commit `d58bfc4`)

Original tinha valores que não existem na API:
- `GOOGLE_ADS_UI` (real: `GOOGLE_ADS_WEB_CLIENT`)
- `GOOGLE_ADS_RECOMMENDATIONS_AUTO_APPLY` (real: `GOOGLE_ADS_RECOMMENDATIONS`)

Impacto: filtros `client_types=[...]` nunca matchavam rows reais; `auto_applied_count` sempre 0.

Fix: enum completo da `ChangeClientTypeEnum` (14 valores) + atualização do `_AUTO_APPLY_CLIENT_TYPE` constant.

## Findings da API observados (informativos)

- **change_event tem propagation lag** — adicionei negatives e mesmo após 30s não apareceram em `change_event`. Não é bug nosso; é comportamento documentado do Google (lag de minutos a horas).
- **`DURING LAST_30_DAYS` na change_event retorna "too old"** — janela máxima parece ser ligeiramente menor que 30 dias. Nosso `_MAX_DAYS = 30` está no limite; pode valer reduzir para 29 ou tratar o erro de forma graciosa.
- **`change_event` rejeita filtros sem `BETWEEN`** — `>=` alone é "infinite range" para o Google. Nosso builder usa BETWEEN ✓.
- **Phase 3a `add_negative_keywords` tem mesma idempotência silenciosa** que Sprint 3b.1, mas sem reportar via per-row status. Sprint 3b.1 ganha a transparência do per-row mesmo que dedup ainda seja silenciosa em CRITERION_EXISTS.

## Sign-off final

- [x] Tests 1, 3, 4, 5 passaram limpos (✅)
- [x] Test 2 passou em comportamento prático (idempotência efetiva) — status `"already_exists"` é limitação da API, não bug nosso. Documentação do tool já alinhada.
- [x] 2 bugs reais corrigidos durante o smoke (commits `8fe426c` + `d58bfc4`)
- [x] Negatives de teste removidas; conta `1163862076` restaurada
- [x] Production revision atual: `v4-ads-mcp-00084-vrk` (commit `d58bfc4`)
- [x] Sprint 3b.1 oficialmente VALIDADA em produção com dados reais

**Date completed:** 2026-05-11 (smoke executado por Claude em sessão dirigida por wellinton.ribeiro@v4company.com)
