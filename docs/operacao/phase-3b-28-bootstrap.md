# Phase 3b.28 — manual smoke runbook (`upload_customer_match_list`)

**Purpose:** Validar Sprint 3b.28 (candidate) — 51º MCP tool e segundo dispatcher fora do `GoogleAdsService.mutate` (paralelo ao `ConversionUploadService` do Sprint 3b.26). Foundation pra V4 audience exclusion playbook (-10% CPA via remarketing exclusion) e prepara investigação aberta do finding A4 — mecanismo real de exclusion pra `(campaign + user_list)` que Google silently overrides hoje. LGPD-heavy: SHA-256 hashing client-side de PII (email + phone) antes de enviar pra Google.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Nutry (sandbox)

**Spec:** `docs/superpowers/specs/<TBD>-sprint-3b-28-upload-customer-match-list-design.md` _(não existe ainda — Wellington vai redigir antes de começar Sprint 3b.28)_
**Plan:** `docs/superpowers/plans/<TBD>-sprint-3b-28-upload-customer-match-list.md` _(não existe ainda — redigir após brainstorming)_

> **Status do runbook:** DRAFT/esqueleto pré-spec. Test scenarios T1..T10 são derivados de heurísticas (família OfflineUserDataJobService + LGPD invariants V4 + padrão 3b.26). Quando o plan formal for redigido, revisar test count + per-value probe + V4 invariants enforcement antes de executar smoke.
>
> **Histórico:** Esqueleto originalmente gerado em 2026-05-19 (subagent `smoke-runbook-generator`) pra Sprint 3b.27 — renomeado pra 3b.28 quando dogfood MO-JP 2026-05-19 reordenou o roadmap (Sprint 3b.27 virou combo `update_customer_conversion_goal` + B1 pre-flight fix; ver `dogfood-2026-05-19-mestre-da-obra-jp-cleanup-massivo.md` §priorização ICE).

## Pre-flight

- [ ] Deploy lands successfully
- [ ] Service `/health` returns 200
- [ ] Tool `upload_customer_match_list` visível em MCP tool list (count 50 → 51)
- [ ] Pre-push gate `python scripts/check_pre_push.py` 5/5 PASS
- [ ] _(opt-in)_ Full gate `python scripts/check_pre_push_full.py` 6/6 PASS (Sprint 3b.5/3b.8 lesson: novos pre-flight async em `_common.py` precisam Docker integration sweep)

Production revisions: `v4-ads-mcp-<TBD>` (initial) → _(add fix iterations as they happen)_

## Smoke results

Preencher conforme execução. Marcar resultado final no fim do arquivo.

| # | Test | Result | Notes |
|---|---|---|---|
| T1 | dry_run happy path (5 emails plaintext) | ⬜ pending | |
| T2 | Pre-flight: customer_list_id não existe | ⬜ pending | |
| T3 | Pre-flight Layer 2: input já-hashed accidentally rejected | ⬜ pending | |
| T4 | Happy path apply real (5 emails) — depende customer_list ENABLED em Nutry | ⬜ pending | possível deferred (F41-equivalent) se Nutry não tem CRM_BASED user_list |
| T5 | Batch 100 emails reais | ⬜ pending | |
| T6 | Partial failure: mix valid + invalid (emails malformed) | ⬜ pending | |
| T7 | Normalização: emails com casing/whitespace inconsistente | ⬜ pending | verificar SHA-256 bate com Google esperado |
| T8 | Normalização: telefones sem country code → +55 default | ⬜ pending | |
| T9 | Layer 2: consent.ad_user_data_consent_signal_time future / out of bounds | ⬜ pending | _(se a API expor esse campo no v24 SDK)_ |
| T10 | Schema regression: 101 items rejected pre-Google | ⬜ pending | |

**Effective result:** N/10 PASS

### F-findings emerged

_Empty placeholder — fill during smoke. Template: `**F## (SEV)** — <symptom>. Fix: <plan>. Family: <bug class>.`_

### Sign-off

- [ ] Pre-push gate 5/5 PASS
- [ ] Production /health 200 (revision `<final_revision>`)
- [ ] **N/10 PASS** após [N] fix iterations
- [ ] CLAUDE.md sprint row added
- [ ] findings-catalog.md updated com [findings] + **A4 status update** (Sprint 3b.28 investigation outcome)
- [ ] Tool count 50 → 51 confirmed in production
- [ ] **A4 investigation outcome documentado** — concluir se Customer Match exclusion mechanism pra V4 "-10% CPA playbook" é viável via (a) ad_group_criterion + user_list, (b) campaign_criterion via novo path, (c) requires outro mechanism (e.g. negative remarketing list)

---

## Pre-smoke setup

### Step 1: Identify or create CRM_BASED UserList em Nutry

`OfflineUserDataJobService.UploadUserData` exige um `user_list` resource alvo pre-existente, do tipo `CRM_BASED` (Customer Match). Verificar primeiro se Nutry sandbox já tem:

```
SELECT
  user_list.id,
  user_list.name,
  user_list.type,
  user_list.crm_based_user_list.upload_key_type,
  user_list.size_for_display,
  user_list.membership_status
FROM user_list
WHERE user_list.type = 'CRM_BASED'
```

**Se nenhum CRM_BASED com `membership_status=OPEN`:** criar manualmente via Google Ads UI (Ferramentas e configurações → Compartilhada → Gerenciador de público-alvo → Novo público-alvo → Lista de clientes). API de criação de user_list NÃO está em escopo desta sprint — escopo é só **upload de membros pra lista existente**.

Anotar o `user_list.id` resultante (ex: `987654321`) pra usar em T1, T4-T8.

**Caveat (similar a F41 do 3b.26):** se Nutry sandbox não tem CRM consent infra real (lista CRM_BASED + Customer Match terms acceptance + min 1000 members threshold antes do matching ativar), T4-T8 podem cair em DEFERRED state — não bug do Sprint 3b.28, só limitation do ambiente.

### Step 2: Preparar dataset de emails + telefones reais (sintéticos pra Nutry)

Gerar arquivo local com:
- 100 emails sintéticos `smoke3b27_NNN@nutry.test`
- 100 telefones BR sintéticos `+55119876NNNNN` (E.164)
- 20 emails malformed pra T6 (sem `@`, com espaço no meio, etc)
- 5 emails já-hashed (SHA-256 hex 64 chars) pra T3 detection
- 10 emails com casing/whitespace pra T7 (` SMOKE3b27_001@NUTRY.TEST `, etc)

**LGPD note:** dados sintéticos. Não usar PII real de clientes V4 em smoke runbook que fica versionado no repo.

### Step 3: Reference numbers pre-smoke

Anotar antes do smoke pra comparar pós-smoke:

```
GAQL pre-smoke:
SELECT user_list.id, user_list.size_for_display, user_list.size_for_search, user_list.size_for_display_range
FROM user_list
WHERE user_list.id = <user_list_id>
```

Capturar `size_for_display` baseline — pós-T4/T5 Google leva 24-48h pra ressincronizar matching, mas job result deve mostrar `operations_received` consistente com batch enviado.

---

## Test T1 — Dry_run happy path: 5 emails plaintext

```
upload_customer_match_list(
  customer_id="1163862076",
  user_list_id="<user_list_id from setup>",
  members=[
    {"email": "smoke3b27_001@nutry.test"},
    {"email": "smoke3b27_002@nutry.test"},
    {"email": "smoke3b27_003@nutry.test"},
    {"email": "smoke3b27_004@nutry.test"},
    {"email": "smoke3b27_005@nutry.test"}
  ]
)
```

Expected:
- [ ] dry_run com `confirmation_token` retornado
- [ ] `summary.member_count=5`, `summary.by_identifier={email:5, phone:0}`, `summary.normalized_count=5`
- [ ] sem PII em response (só counts + hash prefixes p/ debug se aplicável)
- [ ] sem chamada real ao Google (verify via Cloud Run logs: zero requests pra `OfflineUserDataJobService`)

**Result:** ⬜ pending

## Test T2 — Pre-flight: user_list_id não existe

```
upload_customer_match_list(
  customer_id="1163862076",
  user_list_id="999999999",
  members=[{"email": "test@nutry.test"}]
)
```

Expected:
- [ ] status=error, sem confirmation_token
- [ ] PT-BR error contém `"user_list_id=999999999 não existe em customer_id=1163862076"` (ou variant similar; depende de spec final)
- [ ] zero ops em `OfflineUserDataJobService`

**Result:** ⬜ pending

## Test T3 — Pre-flight Layer 2: input já-hashed accidentally rejected

```
upload_customer_match_list(
  customer_id="1163862076",
  user_list_id="<user_list_id>",
  members=[
    {"email": "ab7f4c5e1a2b3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e"}
  ]
)
```

Expected:
- [ ] status=error pre-Google: `"email parece já estar SHA-256 hashed (64 hex chars). Passe plaintext — o tool faz hash client-side."`
- [ ] Heurística: regex `^[a-f0-9]{64}$` + sem `@`
- [ ] zero ops em `OfflineUserDataJobService`

**Result:** ⬜ pending

## Test T4 — Happy path apply real: 5 emails

```
upload_customer_match_list(
  customer_id="1163862076",
  user_list_id="<user_list_id>",
  members=[{...5 emails...}],
  confirmation_token="<from T1>"
)
```

Expected:
- [ ] `status=applied`, `applied_count=5`, `failed_count=0`
- [ ] Response inclui `offline_user_data_job.resource_name` (path tipo `customers/1163862076/offlineUserDataJobs/<job_id>`)
- [ ] GAQL post-upload (job status):
  ```
  SELECT offline_user_data_job.id, offline_user_data_job.status, offline_user_data_job.failure_reason,
         offline_user_data_job.customer_match_user_list_metadata.user_list
  FROM offline_user_data_job
  WHERE offline_user_data_job.id = <job_id>
  ```
  Esperar `status=SUCCESS` ou `RUNNING` (assíncrono — Google processa em background; pode levar minutos)
- [ ] Após 24-48h: `user_list.size_for_display` deve incrementar (ou ficar < 1000 threshold; nesse caso `size_for_display_range = LESS_THAN_ONE_THOUSAND`)

**Result:** ⬜ pending _(possível DEFERRED se Nutry sandbox sem CRM consent infra — documentar como F41-equivalent)_

## Test T5 — Batch 100 reais

```
upload_customer_match_list(
  customer_id="1163862076",
  user_list_id="<user_list_id>",
  members=[...100 emails sintéticos...]
)
```

Expected:
- [ ] dry_run `summary.member_count=100`, `by_identifier={email:100}`
- [ ] apply `applied_count=100`, `failed_count=0`
- [ ] Response size < MCP cap (~100k chars)
- [ ] Job único agrupando 100 ops, ou múltiplos jobs se spec definir chunking (decidir no plan)

**Result:** ⬜ pending

## Test T6 — Partial failure: mix valid + invalid emails

```
upload_customer_match_list(
  customer_id="1163862076",
  user_list_id="<user_list_id>",
  members=[
    {"email": "valid1@nutry.test"},
    {"email": "valid2@nutry.test"},
    {"email": "no-at-sign-here"},
    {"email": "double@@at.test"},
    {"email": "  valid3@nutry.test  "}
  ]
)
```

Expected:
- [ ] Schema Layer 1 OR Layer 2 catch invalid antes do Google call (pattern regex `^[^@\s]+@[^@\s]+\.[^@\s]+$`)
- [ ] OU se passar pra Google: `applied_count=3, failed_count=2`, `failures[]` com `row_index=2` e `row_index=3` + error_code Google
- [ ] `failures` echo back plaintext input? **decidir no spec** — LGPD-sensitive; recomendação é só `row_index` + sanitized_hint (primeiros 3 chars + ***)

**Result:** ⬜ pending

## Test T7 — Normalização pre-hash: emails com casing/whitespace

```
upload_customer_match_list(
  customer_id="1163862076",
  user_list_id="<user_list_id>",
  members=[
    {"email": " SMOKE3b27_001@NUTRY.TEST "},
    {"email": "Smoke3b27_001@Nutry.Test"},
    {"email": "smoke3b27_001@nutry.test"}
  ]
)
```

Expected:
- [ ] Tool detecta e **dedupe pós-normalização** (lowercase + trim) → `summary.member_count=3` raw mas `normalized_count=1` (ou similar field name)
- [ ] Se spec não exigir dedupe, ao menos verificar 3 envios produzem mesmo hash (verify via debug log / hash prefix em response)
- [ ] **R6-equivalent critical assertion**: SHA-256 hash de `"smoke3b27_001@nutry.test"` é determinístico — 3 inputs com casing diferentes devem gerar 3 hashes idênticos

**Result:** ⬜ pending

## Test T8 — Normalização: phone sem country code → +55 default

```
upload_customer_match_list(
  customer_id="1163862076",
  user_list_id="<user_list_id>",
  members=[
    {"phone_number": "11987654321"},
    {"phone_number": "(11) 98765-4321"},
    {"phone_number": "+5511987654321"}
  ]
)
```

Expected:
- [ ] Todos 3 normalizados pra `+5511987654321` (E.164 BR)
- [ ] Hash determinístico — 3 inputs → mesmo SHA-256
- [ ] Se input já tem country code não-BR (ex `+1234567890`), spec decide: (a) aceitar como-é (b) rejeitar (V4 = BR-only)
- [ ] **Recomendação:** rejeitar `+[^5][^5]...` com PT-BR `"V4 hardcoded BR; telefone deve ser +55. Use formato (XX) XXXXX-XXXX ou +55XXXXXXXXXXX."`

**Result:** ⬜ pending

## Test T9 — Layer 2: consent timestamp future / out of bounds

_(Aplicável SE schema expor `consent.ad_user_data_consent_signal_time` ou similar — verificar v24 SDK `OfflineUserDataJobService.CustomerMatchUserListMetadata` no plan)_

```
upload_customer_match_list(
  customer_id="1163862076",
  user_list_id="<user_list_id>",
  members=[{"email": "test@nutry.test"}],
  consent_signal_time="2099-12-31T23:59:59-03:00"
)
```

Expected:
- [ ] Layer 2 pre-Google reject: `"consent_signal_time está no futuro"` (paralelo a T8 do Sprint 3b.26)

**Result:** ⬜ pending _(skip se SDK v24 não tem o campo)_

## Test T10 — Schema regression: 101 members rejected

```
upload_customer_match_list(
  customer_id="1163862076",
  user_list_id="<user_list_id>",
  members=[...101 emails...]  # maxItems=100 (a definir no spec)
)
```

Expected:
- [ ] JSONSchema Layer 1 reject pre-Google: `"members: is too long. Maximum 100 items per call."` (PT-BR)
- [ ] Zero ops Google

**Result:** ⬜ pending

---

## Per-value empirical probe (Sprint 3b.19A.1 convention)

Sprint 3b.28 likely expõe pelo menos 2 enum whitelists candidatas a probe:

### Probe A — `identifier_type` (UserIdentifier sub-types)

| Identifier type | Plaintext input example | Expected | Result |
|---|---|---|---|
| `email` | `test@nutry.test` | ✅ ACCEPT — V4 primary identifier | ⬜ pending |
| `phone_number` | `+5511987654321` | ✅ ACCEPT — V4 secondary identifier | ⬜ pending |
| `mobile_id` (IDFA/AAID) | `EA7583CD-A667-48BC-B806-42ECB2B48606` | ⚠️ Spec decision: out of scope V4 (web-only)? | ⬜ pending |
| `third_party_user_id` | `crm-user-abc123` | ⚠️ Spec decision: out of scope V4 inicial? | ⬜ pending |
| `address_info` (first_name + last_name + country + zip) | object com 4 fields | ⚠️ Spec decision: phase 2? | ⬜ pending |

**Recomendação spec:** v0 só `email` + `phone_number` (V4 lead-gen primary identifiers). Schema enum `["email", "phone_number"]`. Address + mobile_id + third_party_user_id como Sprint 3b.28.x candidates futuras.

### Probe B — `operation_type` (UserData add vs remove)

| Operation | Use case V4 | Expected | Result |
|---|---|---|---|
| `add` (UserDataOperation.create) | Adicionar lead novo ao remarketing/exclusion list | ✅ ACCEPT (default V0) | ⬜ pending |
| `remove` (UserDataOperation.remove) | Remover lead que pediu opt-out / LGPD direito ao esquecimento | ✅ ACCEPT (LGPD compliance — necessário) | ⬜ pending |

**Recomendação spec:** suportar `add` + `remove` desde v0 (LGPD compliance — opt-out flow precisa do remove).

**Convention:** every value in a tool's schema whitelist MUST be empirically validated by creating real entity. SDK descriptors contain values runtime rejects (legacy, system-managed, type-restricted). Bug history: 14 of 38 findings caught here (F17/F18/F19/F25/F27/F31/F32/F34/F36/F38/F39/F40/F42 + A4 family).

---

## V4 invariants validation

| Invariant | Enforcement | How smoke verifies |
|---|---|---|
| `country_code = BR` em `address_info` (se suportado v0) | Builder constant em `_normalize_address_info` | T7-equivalent: input address sem country → builder injeta BR; address com country=US rejected pre-flight |
| Phone `+55` default | Builder normalize em `_normalize_phone_e164` | T8: 3 inputs com/sem country code → todos hash idênticos pós-normalização |
| Email lowercase + trim antes do hash | Builder normalize em `_normalize_email` | T7: 3 casings → 1 hash |
| SHA-256 hash client-side (LGPD) | Builder `hashlib.sha256(plaintext.encode()).hexdigest()` em todos identifiers antes do envio | T3: detecção de input já-hashed bloqueia (evita double-hash); Cloud Run logs confirmam zero plaintext em outbound Google calls |
| `consent.ad_user_data = GRANTED` | Builder hardcoded constant | GAQL post-upload no `OfflineUserDataJob.customer_match_user_list_metadata.consent.ad_user_data` |
| `consent.ad_personalization = GRANTED` | Builder hardcoded constant | GAQL post-upload, mesmo path |
| `consent.ad_user_data_consent_signal_time` em -03:00 timezone | Builder hardcoded `tz=America/Sao_Paulo` (paralelo Sprint 3b.26 padrão) | T9 (se aplicável) |
| LGPD: nenhuma PII em audit_log / response | Audit only hashes prefix (8 chars) + counts | Inspecionar audit_log row pós-T4 — não deve ter email/phone plaintext |
| Always-CONFIRM dry_run gate | `dry_run=True` default + `confirmation_token` validation | T1 retorna token sem aplicar; T4 reusa token |

---

## A4 investigation companion (Sprint 3b.28 secondary deliverable)

**Background:** finding A4 desde Sprint 3b.4/3b.5 — Google silently overrides `negative=true` → `false` em `CampaignCriterion.create` quando criterion é `user_list`. Sprint 3b.5 mitigou via pre-flight rejeição do combo `(campaign + exclusion + user_list)`, direcionando gestor pra ad_group_criterion level. **Mas o mecanismo real pra V4 "-10% CPA via exclusion playbook" continua aberto** — gestor precisa excluir audiences de campaigns inteiras (não só ad_groups), e API atual não permite.

**Sprint 3b.28 não resolve A4 diretamente** (escopo é só upload de membros pra user_list existente), MAS desbloqueia investigação porque:

1. Com `upload_customer_match_list` shipped, gestor pode criar + popular uma user_list de "leads convertidos" pra testar exclusion no nível de remarketing.
2. Smoke runbook T4 vai gerar um user_list real com membros — usar pós-smoke como input pra investigação manual via Google Ads UI:
   - Pode-se adicionar a user_list como "Exclusão" no nível de campaign via UI? (UI permite o que API rejeita?)
   - Se UI permite, qual é o resource path / API field não-óbvio que Google usa? (inspecionar via GAQL pós-criação manual)
   - Se UI também rejeita, mecanismo real é `negative remarketing list` separado, ou requer Display/YouTube channels onde exclusion semantics são diferentes?

**Investigation outcome documentar em:** `docs/operacao/findings-catalog.md` §A4 update + Sprint 3b.28 completion summary. Possíveis outcomes:
- **(a)** A4 closeable — descoberto path correto; spawn Sprint 3b.28.x pra implementar `update_campaign_negative_audiences` ou similar
- **(b)** A4 confirmed limitation — UI e API ambos rejeitam; V4 playbook precisa ser revisado (talvez exclusion via ad_group em vez de campaign é a única forma supportada)
- **(c)** A4 needs more research — escalar pra Google Ads support / documentação oficial

---

## Cleanup post-smoke

- User_list criada em pre-smoke setup fica em Nutry sandbox. Não deletar (Sprint 3b.28 future bundle vai incluir `remove_user_list` candidate)
- Membros uploadados (~110 emails sintéticos) ficam na lista. Não afetam ROAS (sandbox sem traffic real → matching = 0 anyway)
- Job records de `offline_user_data_job` são read-only históricos (Google não permite delete)
- Audit_log rows ficam permanentes (LGPD compliance — audit trail de PII processing)

---

## Notas pra Wellington revisar antes de tratar como spec

1. **Plan formal precisa decidir:**
   - Async job model: 1 job por call ou múltiplos chunks de 1000? Spec final define `maxItems` schema.
   - `failures[]` echo back: incluir plaintext input (UX) vs só `row_index + sanitized_hint` (LGPD-safe)? Sugestão: o último.
   - Suportar `address_info` (first_name + last_name + country + zip) em v0 ou phase 2?
   - Schema include `consent_signal_time` parameter ou hardcoded "now()"?
   - Synchronous vs asynchronous response: aguardar `OfflineUserDataJob.status=SUCCESS` antes de retornar (pode levar minutos) vs retornar `job_id` immediately e gestor faz polling?
2. **Per-value probe scope:** decidir se Sprint 3b.28 v0 inclui só `email` + `phone_number` (recomendação) ou os 5 identifier types.
3. **A4 investigation timing:** smoke T4 sucesso é pré-requisito da investigação manual. Se T4 cair em DEFERRED por Nutry sandbox limitations, A4 investigation move pra Sprint 3b.28.x usando real V4 production account.
4. **F41-equivalent risk:** Nutry sandbox provavelmente não tem Customer Match terms acceptance + CRM consent infra. T4-T8 podem cair em DEFERRED. Plan precisa de fallback strategy (ex: usar conta MO-JP ou outra com Customer Match já habilitado).
