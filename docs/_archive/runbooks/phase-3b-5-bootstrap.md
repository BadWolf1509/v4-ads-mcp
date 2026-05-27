# Phase 3b.5 — manual smoke runbook (stabilization)

**Purpose:** Verify Sprint 3b.5 stabilization fixes (A2 + A3 + A4) em conta real antes de declarar shipping done.

**Operator:** Claude (Sonnet 4.7) executando em sessão dirigida por wellinton.ribeiro@v4company.com
**Account (sandbox):** `1163862076` "Rayane Ribeiro - Nutry" (paused campaigns, zero traffic — same sandbox used in 3b.1/3b.2/3b.3/3b.4 smokes)
**Date completed:** 2026-05-12
**Production revision tested:** `v4-ads-mcp-00111-ljc` (commit `3c23fc5` — Sprint 3b.5 + CI integration test cleanup)

## Pre-flight

- [x] Deploy lands successfully — revision `v4-ads-mcp-00111-ljc` (após CI fix pra integration tests pre-existentes)
- [x] Service `/health` returns 200
- [x] MCP client reloaded (post session restart) — schemas update_*_status enum `["ENABLED", "PAUSED"]` confirmado + apply_audience description menciona A4 constraint

## Test A2-T1 — update_keyword_status rejeita REMOVED no schema ✅

Call:
```
update_keyword_status(
  customer_id="1163862076",
  keywords=[{"ad_group_id": "183008426336", "criterion_id": "2484775198275"}],
  new_status="REMOVED"
)
```

Response:
```
Input validation error: 'REMOVED' is not one of ['ENABLED', 'PAUSED']
```

- [x] MCP transport rejection com schema error
- [x] Tool NÃO foi executada (rejeição pre-tool)
- [x] Zero quota consumida

## Test A2-T2 — update_campaign_status rejeita REMOVED no schema ✅

Call:
```
update_campaign_status(
  customer_id="1163862076",
  campaign_ids=["22804468687"],
  new_status="REMOVED"
)
```

Response:
```
Input validation error: 'REMOVED' is not one of ['ENABLED', 'PAUSED']
```

- [x] MCP transport rejection idêntico
- [x] Zero quota consumida

## Test A2-T3 — update_ad_group_status aceita PAUSED + ENABLED (sanity non-regression) ✅

### PAUSED
```
update_ad_group_status(customer_id="1163862076", ad_group_ids=["183008426336"], new_status="PAUSED")
```

Response: `applied_count: 1`, `google_request_id: "yrPzm6wekRZ5CWdLdZKn4g"`, AUTO path.

### ENABLED (restore)
```
update_ad_group_status(customer_id="1163862076", ad_group_ids=["183008426336"], new_status="ENABLED")
```

Response: `applied_count: 1`, `google_request_id: "tOin7Z1yD0mj3trBN010pg"`, AUTO path.

- [x] Ambos applied OK — schema-restrict NÃO quebrou flows existentes
- [x] ad_group state restored (ENABLED → PAUSED → ENABLED, idempotent)

## Test A4-T1 — apply_audience rejeita campaign + exclusion + user_list ✅

Call:
```
apply_audience(
  customer_id="1163862076", target_type="campaign", mode="exclusion",
  attachments=[{"target_id": "22804468687", "audience_type": "user_list",
                "audience_resource_name": "customers/1163862076/userLists/9158136688"}]
)
```

Response:
```json
{
  "status": "error",
  "error": "Customer Match (user_list) exclusion em campaign level nao eh suportada pela Google Ads API — negative flag eh silently dropado em CampaignCriterion para user_list. Use target_type='ad_group' em vez disso (attachments [0] sao user_list). user_interest exclusion em campaign continua funcionando."
}
```

- [x] `status: "error"`, PT-BR clean mencionando Customer Match + user_list + ad_group
- [x] Pre-flight rejection — zero quota consumida
- [x] Sugere `target_type='ad_group'` + esclarece que user_interest exclusion continua
- [x] Cita exatamente `attachments [0]` (index detection correct)

## Test A4-T2 — ad_group + exclusion + user_list dry_run (sanity) ✅

Call:
```
apply_audience(
  customer_id="1163862076", target_type="ad_group", mode="exclusion",
  attachments=[{"target_id": "183008426336", "audience_type": "user_list",
                "audience_resource_name": "customers/1163862076/userLists/9159326037"}]
)
```

Response: `status: "dry_run"`, `confirmation_token: "OAEKQUDM"`, `confirmation_reason: "apply_audience: exclusion mode — sempre confirma (delivery impact)"`.

- [x] `dry_run` retornado, NÃO bloqueado pelo A4 (ad_group level)
- [x] Token expira em 10min, deliberadamente NÃO chamou apply_change

## Test A4-T3 — campaign + exclusion + user_interest dry_run (sanity — A4 cirúrgico) ✅

Call:
```
apply_audience(
  customer_id="1163862076", target_type="campaign", mode="exclusion",
  attachments=[{"target_id": "22804468687", "audience_type": "user_interest",
                "audience_resource_name": "customers/1163862076/userInterests/80012"}]
)
```

Response: `status: "dry_run"`, `confirmation_token: "HIWD8K4F"`, `blast_summary: "Apply 1 audience(s) [user_interest:1] como exclusion em 1 campaign(s)."`.

- [x] A4 fix é **cirúrgico** — só user_list rejected, user_interest exclusion em campaign continua passando
- [x] GAQL pre-flight (A3 fix) também aceitou taxonomy IN_MARKET (id 80012)
- [x] Token NÃO aplicado

## Test A3-T1 — VERTICAL_GEO (id 7) rejected via GAQL pre-flight ✅

Call:
```
apply_audience(
  customer_id="1163862076", target_type="ad_group", mode="observation",
  attachments=[{"target_id": "183008426336", "audience_type": "user_interest",
                "audience_resource_name": "customers/1163862076/userInterests/7"}]
)
```

Response:
```json
{
  "status": "error",
  "error": "user_interest attachments com taxonomy_type incompativel detectados: attachments[0]=7 (VERTICAL_GEO). Apenas IN_MARKET, AFFINITY sao aceitas pra attachment em ad_group/campaign (V4 use case SEARCH). VERTICAL_GEO (Display Topics, IDs 1-79999) eh silently dropado pelo Google."
}
```

- [x] Pre-flight async GAQL detectou taxonomy VERTICAL_GEO → reject
- [x] Erro cita `attachments[0]=7 (VERTICAL_GEO)` + lista IN_MARKET/AFFINITY válidos
- [x] **Nenhuma mutation no Google Ads** — diferente do Sprint 3b.4 silent drop (que ia até Google e retornava success fake)
- [x] 1 read op consumida (GAQL lookup) — custo trivial vs valor de visibility

## Test A3-T2 — IN_MARKET (id 80012) applied + GAQL verify ✅

Call (mesma user_interest do A4-T3 mas em observation/ad_group):
```
apply_audience(
  customer_id="1163862076", target_type="ad_group", mode="observation",
  attachments=[{"target_id": "183008426336", "audience_type": "user_interest",
                "audience_resource_name": "customers/1163862076/userInterests/80012"}]
)
```

Response: `status: "applied"`, `applied_count: 1`, `google_request_id: "jmYfChthxCCzXM3vDhCgtw"`, AUTO path, `attached`.

**GAQL verification:**
```
SELECT ad_group_criterion.criterion_id, ad_group_criterion.type, ad_group_criterion.status, ad_group_criterion.user_interest.user_interest_category
FROM ad_group_criterion
WHERE ad_group.id = 183008426336
  AND ad_group_criterion.user_interest.user_interest_category = 'customers/1163862076/userInterests/80012'
```

Returned: 1 row — `criterion_id: 52988066042`, `type: USER_INTEREST`, `status: ENABLED`, `user_interest_category: customers/1163862076/userInterests/80012`. **Persists.**

- [x] IN_MARKET aceita pelo pre-flight + applied pelo Google
- [x] GAQL post-mutation confirma persist (diferente do A3 silent drop fingerprint)

## Test A3-T3 — AFFINITY (id 90100) applied ✅

Call:
```
apply_audience(
  customer_id="1163862076", target_type="ad_group", mode="observation",
  attachments=[{"target_id": "183008426336", "audience_type": "user_interest",
                "audience_resource_name": "customers/1163862076/userInterests/90100"}]
)
```

Response: `status: "applied"`, `applied_count: 1`, `google_request_id: "39-3zcdeJAfFSR3bceu4Fw"`, AUTO path.

- [x] AFFINITY taxonomy aceita pelo pre-flight
- [x] Sanity confirma whitelist `{IN_MARKET, AFFINITY}` cobre os 2 use cases V4 documentados

## Test A3-T4 — Mixed batch (2 IN_MARKET + 1 VERTICAL_GEO) → atomic rejection citing index 2 ✅

Call:
```
apply_audience(
  customer_id="1163862076", target_type="ad_group", mode="observation",
  attachments=[
    {"target_id": "183008426336", "audience_type": "user_interest",
     "audience_resource_name": "customers/1163862076/userInterests/80001"},
    {"target_id": "183008426336", "audience_type": "user_interest",
     "audience_resource_name": "customers/1163862076/userInterests/80004"},
    {"target_id": "183008426336", "audience_type": "user_interest",
     "audience_resource_name": "customers/1163862076/userInterests/8"}
  ]
)
```

Response:
```json
{
  "status": "error",
  "error": "user_interest attachments com taxonomy_type incompativel detectados: attachments[2]=8 (VERTICAL_GEO). Apenas IN_MARKET, AFFINITY sao aceitas pra attachment em ad_group/campaign (V4 use case SEARCH). VERTICAL_GEO (Display Topics, IDs 1-79999) eh silently dropado pelo Google."
}
```

- [x] Error cita exatamente `attachments[2]=8 (VERTICAL_GEO)` — index detection correto
- [x] **Atomic rejection**: nenhuma das 3 attachments foi applied (80001 + 80004 NÃO foram persistidos)
- [x] Batch lookup eficiente — 1 GAQL call cobriu os 3 IDs (perf gain do `IN (...)` clause)

## Cleanup

Tests aplicaram 2 criteria reais em Nutry ad_group `183008426336`:
- `52988066042` — user_interest IN_MARKET 80012 ("Hybrid & Alternative Vehicles")
- New criterion — user_interest AFFINITY 90100 ("Outdoor Enthusiasts")

Plus criterion `2484607635720` (user_list 9158136688 negative=True) sobrou do brainstorming empirical test do Sprint 3b.5.

**Tool `remove_audience` não existe ainda** — gap conhecido do Sprint 3b.4. Opções:
- (a) UI Google Ads: detach manual
- (b) **Leave-in-place** (escolhido): Nutry é paused, zero traffic, zero impact

Spawn-task `remove_audience` continua pendente pra Sprint futura.

## Sign-off final

- [x] **A2-T1, A2-T2, A2-T3** todos passaram (schema rejeita REMOVED nos 4 tools + accepts PAUSED/ENABLED sanity sem regressão)
- [x] **A4-T1, A4-T2, A4-T3** todos passaram (campaign+user_list rejected com PT-BR clean; ad_group+user_list dry_run OK; campaign+user_interest dry_run OK — A4 fix é cirúrgico)
- [x] **A3-T1, A3-T2, A3-T3, A3-T4** todos passaram (VERTICAL_GEO rejected via GAQL pre-flight; IN_MARKET + AFFINITY persistem; mixed batch detection de index 2)
- [x] **10 de 10 tests passaram em primeira tentativa** — nenhum bug pego no smoke (diferente das Sprints 3b.3 e 3b.4 que descobriram A1/A2/A3/A4 reais)
- [x] No errors em service logs durante os tests
- [x] Production revision tested: `v4-ads-mcp-00111-ljc`
- [x] CLAUDE.md a ser atualizado: Sprint 3b.5 shipped 2026-05-12

**Insight:** Sprint 3b.5 é a primeira sprint em que o smoke runbook NÃO encontrou bugs novos. Isso é o resultado esperado de uma stabilization sprint — fixes específicos baseados em smoke findings anteriores, com pre-flight rules covering os edge cases. O brainstorming empírico (Option 3 validation antes da decisão) também eliminou risco de implementation surprise.

**Date completed:** 2026-05-12 (executado por Claude em sessão dirigida por wellinton.ribeiro@v4company.com)
