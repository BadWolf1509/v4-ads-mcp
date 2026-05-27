# Phase 3b.6 — manual smoke runbook (remove_audience + real cleanup)

**Purpose:** Verify Sprint 3b.6 `remove_audience` em conta real + faz cleanup das 5 orphan criteria de Sprints 3b.4 + 3b.5.

**Operator:** Claude (Sonnet 4.7) executando em sessão dirigida por wellinton.ribeiro@v4company.com
**Account (sandbox):** `1163862076` "Rayane Ribeiro - Nutry" (paused, zero traffic)
**Account (real cleanup secundário):** `7862230676` "Mestre da Obra - João Pessoa" — pendente decisão Wellington sobre criterion `2480650242694` (Sprint 3b.4 T3 Customer Match observation acidental, A4 silent override)
**Date completed:** 2026-05-12
**Production revision tested:** `v4-ads-mcp-00115-znm` (commit `193442a` — Sprint 3b.6 com cross-cutting fix do params_summary em apply_change)

## Pre-flight

- [x] Deploy lands successfully — revision `v4-ads-mcp-00115-znm`
- [x] Service `/health` returns 200
- [x] MCP client reloaded (post session restart) — schema `remove_audience` confirmado com `target_type` enum + `target_id` singular + `criterion_ids` array maxItems=100

## Pre-cleanup state (GAQL discovery)

Query inicial encontrou **4 orphan criteria** em Nutry ad_group `183008426336`:

| criterion_id | type | resource | status | negative | Origem |
|---|---|---|---|---|---|
| `51668099935` | USER_INTEREST | userInterests/90100 ("Outdoor Enthusiasts" AFFINITY) | ENABLED | false | Sprint 3b.5 T3 |
| `52988066042` | USER_INTEREST | userInterests/80012 ("Hybrid & Alt Vehicles" IN_MARKET) | ENABLED | false | Sprint 3b.5 T2 |
| `56976936578` | USER_INTEREST | userInterests/80001 ("Autos & Vehicles" IN_MARKET) | ENABLED | false | Sprint 3b.4 T1.b |
| `2484607635720` | USER_LIST | userLists/9158136688 ("All visitors AdWords") | ENABLED | **true** | Sprint 3b.5 brainstorming empirical (A4 ad_group exclusion test) |

Mix orphan: 3 observation + 1 exclusion, 3 user_interest + 1 user_list. Real cleanup workflow validation comprehensive.

## Test T1 — Schema rejection: missing criterion_ids ✅

Call (com `criterion_ids: []` em vez de omit — equivalente teste pra schema minItems=1):
```
remove_audience(
  customer_id="1163862076", target_type="ad_group",
  target_id="183008426336", criterion_ids=[]
)
```

Response:
```
Input validation error: [] should be non-empty
```

- [x] MCP transport rejection com schema minItems=1 error clean
- [x] Tool NÃO executada (rejeição pre-tool)
- [x] Zero quota consumida

## Test T2 — Schema rejection: invalid target_type ✅

Call:
```
remove_audience(
  customer_id="1163862076", target_type="removeall",
  target_id="183008426336", criterion_ids=["52988066042"]
)
```

Response:
```
Input validation error: 'removeall' is not one of ['ad_group', 'campaign']
```

- [x] MCP transport rejection com enum error clean
- [x] Zero quota consumida

## Test T3 — CONFIRM dry_run de criterion REAL `52988066042` ✅

```
remove_audience(
  customer_id="1163862076", target_type="ad_group",
  target_id="183008426336", criterion_ids=["52988066042"]
)
```

Response:
```json
{
  "status": "dry_run",
  "operation": "remove_audience",
  "target_type": "ad_group",
  "target_id": "183008426336",
  "blast_summary": "Remover 1 audience criteria do ad_group 183008426336.",
  "confirmation_token": "2NSW5D2W",
  "expires_in_minutes": 10,
  "confirmation_reason": "remove_audience (1 criteria) — sempre confirma (spec §7.1 remove)"
}
```

- [x] `status: "dry_run"`, `confirmation_token: "2NSW5D2W"`
- [x] Reason cita "sempre confirma (spec §7.1 remove)" exact match
- [x] blast_summary clara: target_type + target_id + count

## Test T4 — Apply T3 token + GAQL verify removed ✅

```
apply_change(confirmation_token="2NSW5D2W")
```

Response:
```json
{
  "status": "applied",
  "operation": "remove_audience",
  "blast_summary": "Remover 1 audience criteria do ad_group 183008426336.",
  "google_request_id": "JBCC8hqwvf7_k2XyPADj1g",
  "applied_count": 1
}
```

GAQL verification post-apply:
```
SELECT ad_group_criterion.criterion_id, ad_group_criterion.status
FROM ad_group_criterion
WHERE ad_group.id = 183008426336 AND ad_group_criterion.criterion_id = '52988066042'
```

Returned: **0 rows** ✓ criterion sumiu de fato.

- [x] `applied_count: 1`, real google_request_id
- [x] **Criterion `52988066042` realmente sumiu** (post-apply GAQL = 0 rows)
- [x] **Diferente do Sprint 3b.4 silent drop**: aqui applied_count corresponde a uma mutação real-and-persisted

## Test T5 — Re-remove same criterion (idempotency) ✅

Dry_run (mesma call):
```
remove_audience(...same payload as T3...)
→ confirmation_token: "TPFOF2AV"
```

Apply:
```
apply_change(confirmation_token="TPFOF2AV")
```

Response:
```json
{
  "status": "applied",
  "google_request_id": "WmcHJohxadxTfGuYioyCYA",
  "applied_count": 1
}
```

**Achado: Google silently succeeded a remove de criterion já removido** — applied_count=1 mesmo state já era removed (criterion não existia). Same class do Sprint 3b.3 A1 (silent dedupe for adds), aqui aplicado ao remove path. Não retornou NOT_FOUND error, então nosso defensive `_classify_partial` mapping (`already_removed` para NOT_FOUND family) **não disparou** mas continua sendo guard útil caso behavior mude.

- [x] dry_run + token returned (schema só checa formato)
- [x] apply_change `applied_count: 1` (Google silent success em vez de NOT_FOUND error)
- [x] **Idempotency state-wise validada** — re-running sem spurious failure
- [x] Defensive `_classify_partial` mapping continua útil mesmo se latente

## Test T6 — Batch cleanup das 3 remaining orphan criteria (REAL biz value!) ✅

Batch:
```
remove_audience(
  customer_id="1163862076",
  target_type="ad_group",
  target_id="183008426336",
  criterion_ids=["51668099935", "56976936578", "2484607635720"]
)
→ confirmation_token: "7AXP0XGB"
apply_change(confirmation_token="7AXP0XGB")
```

Apply response:
```json
{
  "status": "applied",
  "blast_summary": "Remover 3 audience criteria do ad_group 183008426336.",
  "google_request_id": "CnaXDPbUP2zFavbQCJ4cvw",
  "applied_count": 3
}
```

Post-apply GAQL verification (whole ad_group cleanup check):
```
SELECT ad_group_criterion.criterion_id, ad_group_criterion.type
FROM ad_group_criterion
WHERE ad_group.id = 183008426336
  AND ad_group_criterion.type IN ('USER_INTEREST', 'USER_LIST')
```

Returned: **0 rows** ✓ **ZERO audience criteria orfãs restantes**.

- [x] Batch dry_run + token gerado em 1 call (mixed types — 3 user_interest + 1 user_list + mixed negative flags)
- [x] Apply `applied_count: 3`
- [x] **Nutry sandbox completamente zerado** após 4 sprints de testing debt
- [x] **Real biz workflow validation:** mixed types + mixed negative flags handled atomicamente

## Mestre da Obra JP cleanup — EXECUTED com achado A5 ⚠️

Wellington aprovou remove do criterion `2480650242694` (Sprint 3b.4 T3 Customer Match observation acidental no campaign `22169885957`). **Primeira tentativa falhou silenciosamente** — descobriu Sprint 3b.6 smoke finding A5.

### Tentativa 1 (FALHA silenciosa)

```
remove_audience(customer_id="7862230676", target_type="campaign", target_id="22169885957", criterion_ids=["2480650242694"])
→ confirmation_token: "82KZ0R44"
apply_change(confirmation_token="82KZ0R44")
→ status: "applied", applied_count: 1, google_request_id: "1HmFrpDhyyBjr8EFPUs7_w"
```

GAQL post-apply:
```
SELECT campaign_criterion.resource_name, campaign_criterion.status
FROM campaign_criterion
WHERE campaign.id = 22169885957 AND campaign_criterion.criterion_id = '2480650242694'
```

Retornou: **1 row, status: ENABLED** — criterion **NÃO foi removido** apesar do success response!

### Diagnóstico A5

Resource_name real é `customers/7862230676/campaignCriteria/22169885957~2480650242694` — **compound key** `{campaign_id}~{criterion_id}`. Sprint 3b.6 builder construía path flat `customers/X/campaignCriteria/{criterion_id}` (sem `~`).

**SDK introspection confirmou:**
```python
CampaignCriterionServiceClient.campaign_criterion_path(cid, campaign_id, criterion_id)
→ "customers/{cid}/campaignCriteria/{campaign_id}~{criterion_id}"  # compound
```

Google aceitou o path malformado flat e retornou success **silenciosamente** — não fez nada. Sprint 3b.6 spec/builder assumiu (errado) que CampaignCriterion path era flat enquanto AdGroupCriterion era compound. Na verdade **ambos são compound**.

**Classe A5 — Silent acceptance of malformed resource_name.** 5ª classe da família: A1 (silent dedupe in adds), A3 (silent drop), A4 (silent override), A5 (silent ack of bad path). Smoke pegou o bug porque GAQL post-verify era step obrigatório do runbook.

### Fix shippado em commit `0c68bca`

- `src/google_ads/mutates/audiences.py`: builder agora usa SDK path helpers (`AdGroupCriterionService.ad_group_criterion_path` + `CampaignCriterionService.campaign_criterion_path`) — authoritative format, no inline construction drift
- `tests/unit/fixtures/proto_capture.py`: fixture adicionou 2 service mocks pros criterion path helpers (3-arg compound signature)
- `tests/unit/test_remove_audience_builder.py`: tests #2 + #5 corrigidos pra compound key. Test #5 (antes `..._path_omits_target_id`) renamed para `..._path_includes_target_id_via_tilde`

Production revision atualizada: `v4-ads-mcp-00117-frb`.

### Tentativa 2 (POST A5 FIX) — SUCCESS

```
remove_audience(...same payload...)
→ confirmation_token: "U5R2U7ZC"
apply_change(confirmation_token="U5R2U7ZC")
→ status: "applied", applied_count: 1, google_request_id: "RBXdbgBbsdWp76S7Ax52kg"
```

GAQL post-apply: **0 rows** ✅ criterion realmente removido.

- [x] Criterion `2480650242694` removido em produção (revision `v4-ads-mcp-00117-frb`)
- [x] A5 silent-acceptance pattern documented + fixed in production
- [x] `remove_audience` validado em campaign ATIVA (real traffic) — confidence beyond Nutry sandbox
- [x] Smart bidding re-learning começa: monitorar CPA WoW próximas 1-2 semanas pra estabilização

## Sign-off final

- [x] **T1 + T2** schema rejections OK (zero quota)
- [x] **T3 + T4** single-criterion remove ciclo completo (dry_run → apply → GAQL verify removed)
- [x] **T5** idempotency validada (Google silent-success em remove-já-removed; defensive guard mapping não disparou mas continua útil)
- [x] **T6** batch cleanup das 3 remaining orphan criteria (real biz value — Nutry ad_group `183008426336` ZEROed)
- [ ] Decisão Mestre da Obra JP `2480650242694` documentada (pendente Wellington)
- [x] No errors em service logs
- [x] Production revision: `v4-ads-mcp-00115-znm`
- [x] **6 de 6 smoke tests PASS** + 1 achado documentado (T5 Google silent-success behavior)
- [x] CLAUDE.md a atualizar: Sprint 3b.6 shipped, tool count 38 → 39

**Real biz value alcançado:** Nutry sandbox zerado após 4 sprints (3b.3 + 3b.4 + 3b.5) de testing debt. 4 orphan criteria removidas em uma sessão. `remove_audience` validado em production com mixed types + mixed negative flags atomicamente.

**Date completed:** 2026-05-12 (executado por Claude em sessão dirigida por wellinton.ribeiro@v4company.com)
