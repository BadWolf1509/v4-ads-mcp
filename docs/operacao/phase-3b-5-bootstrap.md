# Phase 3b.5 — manual smoke runbook (stabilization)

**Purpose:** Verify Sprint 3b.5 stabilization fixes (A2 + A3 + A4) em conta real antes de declarar shipping done.

**Operator:** wellinton.ribeiro@v4company.com
**Account (sandbox):** `1163862076` "Rayane Ribeiro - Nutry" (paused campaigns, zero traffic — same sandbox used in 3b.1/3b.2/3b.3/3b.4 smokes)

## Pre-flight

- [ ] Deploy lands successfully (`gh run watch <id>` shows green Deploy)
- [ ] Service `/health` returns 200
- [ ] Reload MCP client (restart Claude Code session) — tools list inclui apply_audience + 4 status tools com schema atualizado

## Test A2-T1 — update_keyword_status rejeita REMOVED no schema

```
update_keyword_status(
  customer_id="1163862076",
  keywords=[{"ad_group_id": "183008426336", "criterion_id": "2484775198275"}],
  new_status="REMOVED"
)
```

Expected:
- [ ] MCP transport rejeita com schema validation error ("'REMOVED' is not one of ['ENABLED', 'PAUSED']")
- [ ] Tool NÃO foi executada (rejeição pre-tool)
- [ ] Zero quota consumida

## Test A2-T2 — update_campaign_status rejeita REMOVED no schema

```
update_campaign_status(
  customer_id="1163862076",
  campaign_ids=["22804468687"],
  new_status="REMOVED"
)
```

Expected:
- [ ] MCP transport rejection com schema error
- [ ] Zero quota consumida

## Test A2-T3 — update_ad_group_status aceita PAUSED + ENABLED (sanity non-regression)

```
update_ad_group_status(
  customer_id="1163862076",
  ad_group_ids=["183008426336"],
  new_status="PAUSED"
)
```

Expected:
- [ ] `status: "applied"`, `applied_count: 1`, real `google_request_id`
- [ ] AUTO path triggered (single entity)
- [ ] Sanity confirma schema-restrict não quebrou flows existentes

Re-enable depois:
```
update_ad_group_status(
  customer_id="1163862076",
  ad_group_ids=["183008426336"],
  new_status="ENABLED"
)
```

Expected:
- [ ] `status: "applied"`, retorna ad_group pro estado original

## Test A4-T1 — apply_audience rejeita campaign + exclusion + user_list

```
apply_audience(
  customer_id="1163862076",
  target_type="campaign",
  mode="exclusion",
  attachments=[{
    "target_id": "22804468687",
    "audience_type": "user_list",
    "audience_resource_name": "customers/1163862076/userLists/9158136688"
  }]
)
```

Expected:
- [ ] `status: "error"`, PT-BR error mencionando "user_list" + "ad_group" + "Customer Match"
- [ ] Pre-flight rejection — zero quota consumida
- [ ] Sugere usar `target_type='ad_group'` no error message

## Test A4-T2 — apply_audience permite ad_group + exclusion + user_list (sanity)

```
apply_audience(
  customer_id="1163862076",
  target_type="ad_group",
  mode="exclusion",
  attachments=[{
    "target_id": "183008426336",
    "audience_type": "user_list",
    "audience_resource_name": "customers/1163862076/userLists/9159326037"
  }]
)
```

(Usar "All Converters" user_list `9159326037` que ainda não está anexada.)

Expected:
- [ ] `status: "dry_run"`, `confirmation_token` (exclusion sempre confirma)
- [ ] Reason cita "exclusion mode — sempre confirma"
- [ ] **Deliberadamente NÃO chamar apply_change** (ad_group level testing isolated; criterion criado vira tooling debt sem `remove_audience`)

## Test A4-T3 — apply_audience permite campaign + exclusion + user_interest (sanity)

```
apply_audience(
  customer_id="1163862076",
  target_type="campaign",
  mode="exclusion",
  attachments=[{
    "target_id": "22804468687",
    "audience_type": "user_interest",
    "audience_resource_name": "customers/1163862076/userInterests/80012"
  }]
)
```

Expected:
- [ ] `status: "dry_run"`, `confirmation_token` (não foi rejeitado pelo A4 fix)
- [ ] Confirma que A4 fix é cirúrgico — só user_list rejected, user_interest exclusion em campaign continua
- [ ] **Deliberadamente NÃO chamar apply_change**

## Test A3-T1 — apply_audience rejeita VERTICAL_GEO taxonomy (Display Topics)

```
apply_audience(
  customer_id="1163862076",
  target_type="ad_group",
  mode="observation",
  attachments=[{
    "target_id": "183008426336",
    "audience_type": "user_interest",
    "audience_resource_name": "customers/1163862076/userInterests/7"
  }]
)
```

Expected:
- [ ] `status: "error"`, error PT-BR mencionando "VERTICAL_GEO" ou "taxonomy"
- [ ] Erro lista as taxonomies aceitas (IN_MARKET, AFFINITY)
- [ ] Pre-flight async GAQL detectou o issue — 1 read op consumida (pre-flight lookup)
- [ ] **Nenhuma mutation no Google Ads** (criterion não foi criado — diferente do Sprint 3b.4 silent drop)

## Test A3-T2 — apply_audience aceita IN_MARKET (sanity)

```
apply_audience(
  customer_id="1163862076",
  target_type="ad_group",
  mode="observation",
  attachments=[{
    "target_id": "183008426336",
    "audience_type": "user_interest",
    "audience_resource_name": "customers/1163862076/userInterests/80012"
  }]
)
```

Expected:
- [ ] `status: "applied"`, `applied_count: 1`, AUTO path
- [ ] Criterion criado (verify via GAQL):
  ```
  SELECT ad_group_criterion.criterion_id, ad_group_criterion.user_interest.user_interest_category, ad_group_criterion.status
  FROM ad_group_criterion
  WHERE ad_group.id = 183008426336
    AND ad_group_criterion.user_interest.user_interest_category = 'customers/1163862076/userInterests/80012'
  ```
  Expected: 1 row, status=ENABLED

## Test A3-T3 — apply_audience aceita AFFINITY (sanity)

```
apply_audience(
  customer_id="1163862076",
  target_type="ad_group",
  mode="observation",
  attachments=[{
    "target_id": "183008426336",
    "audience_type": "user_interest",
    "audience_resource_name": "customers/1163862076/userInterests/90100"
  }]
)
```

Expected:
- [ ] `status: "applied"`, AUTO path
- [ ] AFFINITY taxonomy aceita

## Test A3-T4 — Mixed batch: 2 IN_MARKET + 1 VERTICAL_GEO → rejeição cita índice 2

```
apply_audience(
  customer_id="1163862076",
  target_type="ad_group",
  mode="observation",
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

Expected:
- [ ] `status: "error"`, error cita `attachments[2]=8 (VERTICAL_GEO)`
- [ ] Batch lookup eficiente: **1 GAQL call** (não 3) — verificável via service logs
- [ ] Nenhuma das 3 attachments foi applied (atomic rejection)

## Cleanup

Test A3-T2 + A3-T3 criaram 2 criteria reais em Nutry ad_group `183008426336`:
- 1 user_interest IN_MARKET 80012 ("Hybrid & Alternative Vehicles")
- 1 user_interest AFFINITY 90100 ("Outdoor Enthusiasts")

**Tool `remove_audience` não existe ainda** — gap conhecido do Sprint 3b.4 (também afeta Sprint 3b.3 A2 sobre REMOVED). Opções:
- (a) UI Google Ads: detach manual via interface
- (b) **Leave-in-place** (recomendado): Nutry é paused, zero traffic — sem impacto

Spawn-task `remove_audience` continua pendente.

## Sign-off final

- [ ] A2-T1, A2-T2, A2-T3 todos passaram (schema rejeita REMOVED + accepts PAUSED/ENABLED)
- [ ] A4-T1, A4-T2, A4-T3 todos passaram (campaign+user_list rejected; ad_group+user_list ok; campaign+user_interest ok)
- [ ] A3-T1, A3-T2, A3-T3, A3-T4 todos passaram (VERTICAL_GEO rejected; IN_MARKET ok; AFFINITY ok; batch index detection)
- [ ] No errors em service logs durante os tests
- [ ] `/admin/audit` mostra audit rows corretos para os fixes
- [ ] Production revision verificada
- [ ] CLAUDE.md atualizado: Sprint 3b.5 shipped

**Date completed:** ____
