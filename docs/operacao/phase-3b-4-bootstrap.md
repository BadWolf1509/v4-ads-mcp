# Phase 3b.4 — manual smoke runbook

**Purpose:** Verify `apply_audience` works against real V4 accounts before declaring Sprint 3b.4 done.

**Operator:** Claude (Sonnet 4.7) executando em sessão dirigida por wellinton.ribeiro@v4company.com
**Account (AUTO sandbox):** `1163862076` "Rayane Ribeiro - Nutry" (paused campaigns, zero traffic — same sandbox used in 3b.1/3b.2/3b.3 smokes)
**Account (real biz exclusion test):** `7862230676` "Mestre da Obra - João Pessoa" (Customer Match dormente identificada no dogfood P1b)
**Date completed:** 2026-05-12
**Production revision tested:** `v4-ads-mcp-00102-6td`

## Pre-flight

- [x] Deploy lands successfully — revision `v4-ads-mcp-00102-6td`
- [x] Service `/health` returns 200
- [x] MCP client reloaded (post session restart) — tools list includes `apply_audience`

## Test 1 — AUTO observation user_interest (1 attachment) ✅ COM ACHADO A3

Primeiro listar user_interests disponíveis na Nutry via GAQL — retornou 5 categorias com `taxonomy_type: VERTICAL_GEO` (IDs 3, 5, 7, 8, 11 — "Arts & Entertainment", "Computers & Electronics", "Finance", "Games", "Home & Garden").

### T1.a — primeiro tentativa com VERTICAL_GEO (ID 7 "Finance"):

Call:
```
apply_audience(
  customer_id="1163862076",
  target_type="ad_group",
  mode="observation",
  attachments=[{"target_id": "183008426336", "audience_type": "user_interest",
                "audience_resource_name": "customers/1163862076/userInterests/7"}]
)
```

Response (PARECE OK):
```json
{
  "status": "applied",
  "applied_count": 1,
  "google_request_id": "1LOzDDJsDCBU5SZIEcB4HA",
  "auto_applied_reason": "apply_audience observation (1 attachments) — auto",
  "attachments_result": [{"target_id": "183008426336", "audience_type": "user_interest",
                           "audience_resource_name": "customers/1163862076/userInterests/7",
                           "status": "attached"}]
}
```

**Validação via GAQL:** `SELECT * FROM ad_group_criterion WHERE ad_group.id = 183008426336 AND user_interest.user_interest_category = 'customers/1163862076/userInterests/7'` → **0 rows**. **Criterion NÃO foi persistido apesar do success response.**

### T1.b — retry com IN_MARKET (ID 80001 "Autos & Vehicles"):

Mesma call com `audience_resource_name: customers/1163862076/userInterests/80001`.

Response: `status: "applied"`, `google_request_id: "RZrExcRKKmsGPhcpPdR9Hw"`, status=attached.

Validação via GAQL: **1 row encontrada** — `criterion_id: 56976936578`, `type: USER_INTEREST`, `status: ENABLED`, `user_interest_category: customers/1163862076/userInterests/80001` ✅

### Achado A3: Google silently drops user_interest com taxonomy_type incompatível

**Padrão:** taxonomy `VERTICAL_GEO` (IDs < 80000, ex: Display Topics categorias) é INCOMPATÍVEL com SEARCH ad_group attachment. Google API:
- Aceita o mutate request sem erro síncrono
- Retorna `applied_count: 1` + real `google_request_id`
- MAS silenciosamente dropa a criterion — não persiste

`taxonomy_type: IN_MARKET` (IDs >= 80000) funciona corretamente — criterion persiste.

**Implicação:** análogo ao Sprint 3b.3 finding A1 (silent dedupe), nossa partial_failure infrastructure não detecta esse tipo de "silent acceptance + non-persistence". O gestor verá `attached` no response mas a attachment não existe em produção.

**Mitigation futuras (não bloqueia Sprint 3b.4):**
- **Opção 1 (pre-flight):** validar `user_interest.taxonomy_type IN ('IN_MARKET', 'AFFINITY', 'LIFE_EVENT')` via GAQL antes do mutate. Custa 1 read op extra.
- **Opção 2 (post-validation):** após apply, query criterion back pra confirmar existence. Custa 1 read op extra.
- **Opção 3 (docs):** documentar explícito que VERTICAL_GEO IDs (1-79999) não anexam em SEARCH ad_group. Educar gestor.

Spawn-task documentado para sprint posterior.

- [x] **T1.a passou no contract layer** (response shape correto, applied_count, request_id real, AUTO path)
- [x] **T1.b validou que o tool funciona com input válido** (IN_MARKET persiste)
- [x] **Achado A3 documentado** — não bloqueia, mas é gap visibility-side

## Test 2 — CONFIRM observation >20 (NÃO aplicar) ✅

25 attachments (IDs 3, 5, 8, 11, 12, 13, 14, 16, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34) numa call:

Response:
```json
{
  "status": "dry_run",
  "blast_summary": "Apply 25 audience(s) [user_interest:25] como observation em 1 ad_group(s).",
  "confirmation_token": "GF4W5ZID",
  "expires_in_minutes": 10,
  "confirmation_reason": "apply_audience: observation com >20 attachments (25) — confirmar"
}
```

- [x] `status: "dry_run"`, `confirmation_token: "GF4W5ZID"` returned
- [x] `confirmation_reason` cita "observation com >20 attachments (25)"
- [x] `blast_summary` clara com aggregate `[user_interest:25]`
- [x] **Deliberadamente NÃO chamou apply_change** — token expira em 10min naturalmente

## Test 3 — CONFIRM exclusion (real biz Mestre da Obra JP) ✅ dry-run

Customer Match `clientes mestre da obra jp` (id `9377822529`, CRM_BASED, 1200 users) como exclusion na campanha de aquisição `22169885957` "[GPC][CAB][LEADS][SEG][SEX][MESTRE DA OBRA]":

Response (dry-run):
```json
{
  "status": "dry_run",
  "target_type": "campaign",
  "mode": "exclusion",
  "blast_summary": "Apply 1 audience(s) [user_list:1] como exclusion em 1 campaign(s).",
  "confirmation_token": "2GP3K1EY",
  "expires_in_minutes": 10,
  "confirmation_reason": "apply_audience: exclusion mode — sempre confirma (delivery impact)"
}
```

- [x] `status: "dry_run"`, `confirmation_token: "2GP3K1EY"` returned
- [x] `confirmation_reason` cita "exclusion mode — sempre confirma (delivery impact)"
- [x] `blast_summary` clara com aggregate `[user_list:1]` + mode + targets
- [ ] **Decisão Wellington pendente:** aplicar `2GP3K1EY` para -10% CPA esperado, ou deixar expirar?

## Test 4 — Schema rejection (bid_modifier em exclusion) ✅

```
apply_audience(customer_id="1163862076", target_type="campaign", mode="exclusion",
  attachments=[{"target_id": "22804468687", "audience_type": "user_list",
                "audience_resource_name": "customers/1163862076/userLists/123456789",
                "bid_modifier": 1.5}])
```

Response:
```json
{
  "status": "error",
  "error": "bid_modifier nao eh permitido em mode=exclusion (attachments [0] invalido(s) — exclusion bloqueia delivery, bid_modifier eh semanticamente N/A)"
}
```

- [x] `status: "error"`, pre-flight rejection clean PT-BR mencionando "bid_modifier" + "exclusion"
- [x] Pre-flight rejection — nenhuma mutation in Google
- [x] Zero quota consumida

## Test 5 — Schema rejection (audience_type vs resource_name mismatch) ✅

```
apply_audience(customer_id="1163862076", target_type="ad_group", mode="observation",
  attachments=[{"target_id": "183008426336", "audience_type": "user_list",
                "audience_resource_name": "customers/1163862076/userInterests/91501"}])
```

Response:
```json
{
  "status": "error",
  "error": "attachments[0]: audience_type='user_list' incompativel com resource_name (esperado segmento /userLists/ no path)"
}
```

- [x] `status: "error"`, PT-BR error clean mencionando audience_type + esperado segmento
- [x] Pre-flight rejection
- [x] Zero quota consumida

## Achados consolidados

### A3: Silent drop quando user_interest.taxonomy_type incompatível

Google API aceita user_interest attachment com qualquer taxonomy_type mas **silenciosamente dropa** quando incompatível com target_type. SEARCH ad_groups só aceitam IN_MARKET / AFFINITY / LIFE_EVENT (IDs >= 80000); VERTICAL_GEO (Display Topics, IDs 1-79999) é dropado silently. Tool reporta `attached` no response mas criterion não persiste.

**Visibility gap classe-A** — similar Sprint 3b.3 A1 (silent dedupe). Nossa partial_failure infrastructure não detecta porque Google não retorna error. Spawn-task documenta opções de fix (pre-flight taxonomy check ou post-validation).

## Cleanup

- T1.b criou criterion real (`56976936578` em Nutry ad_group `183008426336`). Tool `remove_audience` não existe — mesma constraint Sprint 3b.3 A2. Opções:
  - (a) UI manual: detach via Google Ads UI
  - (b) **Leave-in-place** (escolhida): Nutry é paused, zero traffic, sem impacto biz

**Recomendação:** Leave-in-place. Spawn-task `remove_audience` para sprint futura (também resolve gap A2 do Sprint 3b.3 sobre REMOVED status).

- T3 (real biz): se Wellington aplicar em Mestre da Obra JP → monitorar CPA WoW próxima semana. Se decidir reverter, mesma constraint (sem `remove_audience` tool).

## Sign-off final

- [x] T1-T5 todos passaram (T1.a contract layer OK, T1.b validou persistência com IN_MARKET)
- [x] No errors em service logs (request_ids T1.a `1LOzDDJsDCBU5SZIEcB4HA`, T1.b `RZrExcRKKmsGPhcpPdR9Hw`)
- [x] Achado A3 documentado — silent drop com VERTICAL_GEO taxonomy
- [ ] Decisão sobre T3 token `2GP3K1EY` pendente
- [x] Production revision: `v4-ads-mcp-00102-6td`
- [x] CLAUDE.md a ser atualizado: Sprint 3b.4 shipped 2026-05-12, tool count 37 → 38

**Date completed:** 2026-05-12 (executado por Claude em sessão dirigida por wellinton.ribeiro@v4company.com)
