# Phase 3b.40 — manual smoke runbook (Quick Wins Mutate Safety A1+B9+A2)

**Purpose:** Validar Sprint 3b.40 — 3 quick wins do dogfood MO-JP 2026-05-27 (ICE somado 2030):
- **A2** (`audit_quality_score`): novo campo `ad_group_status` em `flagged_keywords[]` (replica pattern F52 cravado em `audit_zombie_keywords` 25/05) — permite consumer-side filter pra distinguir keywords flagged em ad_groups ENABLED (impactáveis) vs REMOVED (órfãs cosméticas — não competem em leilão).
- **B9** (`get_keyword_performance`): novo campo `negative: bool` em cada row (F56 mitigation Opção A+C) — permite consumer-side filter pra workflows positive-only, sem breaking change.
- **A1** (`update_keyword_status`): novo campo `sample_keywords` (top 5) + `sample_truncated` flag no DRY_RUN path — preview pra sanity check humano em batch mutation (TTL 10min sem reverter). Prevenção de bug humano em apply batch sem inspeção.

**Operator:** wellinton.ribeiro@v4company.com
**Account principal:** `7862230676` Mestre da Obra JP+CAB (production V4 — caso real cleanup massivo recurring)

**Spec:** `docs/superpowers/specs/2026-05-27-sprint-3b-40-quick-wins-mutate-safety-design.md`
**Plan:** `docs/superpowers/plans/2026-05-27-sprint-3b-40-quick-wins-mutate-safety.md`
**Dogfood source:** `docs/operacao/dogfood-2026-05-27-mestre-da-obra-jp-investigacao-senior.md` (§B9 ICE 630 + §A1 ICE 800 + §A2 ICE 600)

> **Escopo V0 confirmado:**
> - Tool count: 62 → **62** (zero novas tools — apenas enhancements em 3 tools existentes)
> - 4 commits sequenciais: F56 catalog + A2 + B9 + A1
> - Bucket distribution mantida (22 always + 40 defer)
> - ZERO breaking changes (todos os campos novos são adições puras)
> - F56 catalogado (55 → 56 findings)
> - Sample size A1 fixo top 5 V0 (configurable só se demanda real)

## Production URL

`https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`

## Pre-flight

- [ ] Deploy lands successfully (CI + Deploy green em commit final A1)
- [ ] Service `/health` returns 200 (`{"status":"ok","version":"0.1.0"}`)
- [ ] Pre-push gate `python scripts/check_pre_push.py` 5/5 PASS
- [ ] Unit tests `tests/unit/test_flag_keywords.py` PASS (KeywordRow.ad_group_status field)
- [ ] Unit tests `tests/unit/test_audit_quality_score_query.py` PASS (SELECT ad_group.status)
- [ ] Unit tests `tests/unit/test_keyword_lookup.py` PASS (4 tests novo módulo)
- [ ] Integration tests `tests/integration/test_audit_quality_score.py` PASS (ENABLED+REMOVED samples)
- [ ] Integration tests `tests/integration/test_get_keyword_performance.py` PASS (negative true+false samples)
- [ ] Integration tests `tests/integration/test_update_keyword_status.py` PASS (dry_run sample_keywords + auto_apply omit)
- [ ] F56 catalogado em `findings-catalog.md` (56 unique findings)
- [ ] MCP client (Claude Code) conectado à URL produção e enxerga descriptions atualizadas (warning F52 em audit_quality_score, warning F56 em get_keyword_performance)

Production revisions: `v4-ads-mcp-XXXXX-xxx` (preencher após deploy final).

## Smoke results

Preencher conforme execução. Marcar resultado final no fim do arquivo.

| # | Test | Result | Notes |
|---|---|---|---|
| T1 | A2 — `audit_quality_score` em MO-JP retorna `ad_group_status` em cada flagged_keyword | ⬜ pending | |
| T2 | B9 — `get_keyword_performance` em MO-JP retorna `negative: bool` em cada row + count consistente com audit_zombie_keywords | ⬜ pending | |
| T3 | A1 — `update_keyword_status` dry_run com 6+ keywords retorna `sample_keywords` top 5 + `sample_truncated=true` + apply via `apply_change` | ⬜ pending | |

**Effective result:** N/3 PASS

### F-findings emerged

_Preencher durante smoke. Template: `**F## (SEV)** — <symptom>. Fix: <plan>. Family: <bug class>.`_

Se zero F-findings: documentar explicitly "Zero F-findings novos. Sprint clean."

### Sign-off

- [ ] Pre-push gate 5/5 PASS
- [ ] Spec compliance + code quality reviewers APPROVED (4 commits sequenciais)
- [ ] Production `/health` 200 (revisão final)
- [ ] T1 PASS — A2 ad_group_status field presente em 100% das flagged_keywords + consumer-side filter funciona
- [ ] T2 PASS — B9 negative field presente em 100% das rows + count cross-check com `audit_zombie_keywords` consistent
- [ ] T3 PASS — A1 sample_keywords top 5 no dry_run + apply via `apply_change` aplica corretamente sem interferência
- [ ] CLAUDE.md "Pending section" refresh (remove A1/B9/A2 do dogfood 27/05) + bump finding count 55 → 56
- [ ] sprint-history.md entry Sprint 3b.40 added
- [ ] findings-catalog.md F56 row cravada (catalog Step 1 do plan)
- [ ] Tool count permanece 62 confirmed em produção (zero novas tools)

---

## Pre-smoke setup

### Step 1: Sanity check no MCP client + verificar descriptions atualizadas

Após deploy final 3b.40, reiniciar Claude Code pra refresh tool description cache:

1. Sair completamente do Claude Code (Cmd+Q / Alt+F4)
2. Reabrir
3. Verificar que MCP server v4-ads conecta sem erro
4. Especificamente verificar descriptions:
   - `audit_quality_score` description contém warning "ATENÇÃO (F52)" + menção `ad_group_status`
   - `get_keyword_performance` description contém warning "ATENÇÃO (F56)" + menção `negative: bool`
   - `update_keyword_status` description mantida igual (mudança é apenas em response shape, não description)

Se descriptions não mostram warnings F52/F56, deploy não landed completamente ou tool cache stale — restart Claude Code novamente OR investigar Cloud Run logs.

### Step 2: Capturar Wellington UUID (cross-validation audit_log)

```sql
-- Via mcp__supabase__execute_sql
SELECT id, email FROM managers WHERE email = 'wellinton.ribeiro@v4company.com';
-- Anotar id retornado (UUID) — usar em queries SQL se quiser cross-check audit_log
```

Anotar `<wellington_uuid>` opcional pra deep validation.

### Step 3: Baseline pré-smoke MO-JP — quality score flagged keywords

Capturar baseline via `audit_quality_score` PRÉ-fix (referência pra T1 — fazer ANTES de re-run pra observar shape change):

```
audit_quality_score(
  customer_id="7862230676"
)
```

Anotar:
- `total_flagged` (N keywords flagged)
- Verificar se shape PRÉ-fix tem campo `ad_group_status` (esperado: NÃO — só após deploy 3b.40 deve aparecer)

**Pós-deploy** (T1 real): re-run mesma call deve retornar `ad_group_status` em cada entry.

### Step 4: Baseline pré-smoke MO-JP — keyword performance + zombie counts

Capturar count cruzados pra T2 cross-validation:

```
# A: get_keyword_performance status=enabled
get_keyword_performance(
  customer_id="7862230676",
  status="enabled",
  limit=200
)
# Anotar: count total rows retornadas + count com negative=true (depois do deploy)
```

```
# B: audit_zombie_keywords (filtra negative=FALSE server-side)
audit_zombie_keywords(
  customer_id="7862230676"
)
# Anotar: total_zombies + breakdown ad_group_status (ENABLED vs REMOVED)
```

Workflow esperado em T2:
- Filter consumer-side `get_keyword_performance` rows com `negative=false` → comparar count com baseline subset positive
- Os 39 falsos positivos (`negative=true` ENABLED) documentados pelo Wellington em 27/05 em CAB GERAL devem aparecer na lista de `get_keyword_performance` mas NÃO em `audit_zombie_keywords` (filtrados server-side)

### Step 5: Identificar 6+ keywords safe-to-pause pra T3

Capturar lista de zumbis com filtro defensivo `ad_group_status='ENABLED'`:

```
audit_zombie_keywords(
  customer_id="7862230676"
)
```

Filter manualmente as primeiras 6-10 entries que tem:
- `ad_group_status == "ENABLED"` (impactáveis)
- `status == "ENABLED"` (não-pausada ainda)
- `keyword_text` reconhecível como zumbi safe (não-protegida, baixo risco)

Anotar lista de pairs `(ad_group_id, criterion_id)` + `keyword_text` esperado pra cada (pra cross-validation contra `sample_keywords` retornado em T3).

**Exemplo lista anotada (placeholder):**

```
1. (ad_group_id=174842025340, criterion_id=12345, keyword_text="rolo compactador")
2. (ad_group_id=174842025341, criterion_id=12346, keyword_text="dell aluguel")
3. (ad_group_id=174842025342, criterion_id=12347, keyword_text="caminhao munck pequeno")
4. (ad_group_id=174842025343, criterion_id=12348, keyword_text="placa solar valor")
5. (ad_group_id=174842025344, criterion_id=12349, keyword_text="forma metalica laje")
6. (ad_group_id=174842025345, criterion_id=12350, keyword_text="andaime tubular")
```

(Substituir pelos valores reais capturados em runtime — Wellington escolhe quais 6 são safe-to-pause)

### Step 6: Cloud Run logs streaming opcional

Em terminal separado, manter logs streaming pra captar errors durante calls:

```bash
gcloud run services logs read v4-ads-mcp \
  --region=southamerica-east1 \
  --project=v4-ads-mcp-prod \
  --limit=50
```

---

## Test T1 — A2 `audit_quality_score` retorna `ad_group_status` em cada flagged_keyword

**Setup:** Validar A2 — campo novo `ad_group_status` em cada entry de `flagged_keywords[]`. Replica pattern F52 cravado 25/05 em `audit_zombie_keywords`. Permite consumer-side filter pra distinguir órfãs cosméticas (REMOVED ad_groups) vs impactáveis (ENABLED).

**Pré-requisito:** Step 3 baseline anotado. MO-JP tem keywords flagged em mix ENABLED + REMOVED ad_groups (pattern F52 cravado 25/05 cobre os mesmos ad_groups).

**Tool call:**

```
audit_quality_score(
  customer_id="7862230676"
)
```

**Expected response shape (foco campo novo):**

```json
{
  "customer_id": "7862230676",
  "date_range_resolved": {"start": "2026-04-27", "end": "2026-05-27", "days": 30},
  "filters_applied": {"ad_group_ids": null, "min_impressions": 10, "limit": 200},
  "total_flagged": N,
  "truncated": false,
  "flagged_keywords": [
    {
      "ad_group_id": "...",
      "ad_group_name": "...",
      "ad_group_status": "ENABLED",  // NOVO A2 — PT-BR-mapped enum
      "campaign_name": "...",
      "keyword_id": "...",
      "keyword_text": "...",
      "match_type": "BROAD" | "PHRASE" | "EXACT",
      "quality_score": 2,
      "impressions": 50,
      "clicks": 0,
      "conversions": 0.0,
      "cost_brl": 0.0,
      "flags": ["candidate_pause"]
    }
    // ... sorted QS ASC + impressions DESC tie-break
  ]
}
```

**Validação:**

- [ ] `status` da call não-error (tool retorna dict válido sem `"error"` key)
- [ ] `total_flagged >= 1` (MO-JP tem keywords problemáticas — esperado dado cleanup history)
- [ ] **Crítico A2:** TODAS as entries em `flagged_keywords[]` contêm key `ad_group_status` (zero missing)
- [ ] Cada `ad_group_status` é string no whitelist V4: `"ENABLED" | "PAUSED" | "REMOVED" | "UNSPECIFIED" | "UNKNOWN"` (proto-plus `.name` access — Sprint 3b.7 lesson)
- [ ] Description atualizada visível no inspector contém warning F52 + menção `ad_group_status='ENABLED'` (pre-flight Step 1 verifica)
- [ ] Mantém os 12 campos legacy (ad_group_id, ad_group_name, campaign_name, keyword_id, keyword_text, match_type, quality_score, impressions, clicks, conversions, cost_brl, flags)
- [ ] Sort mantido: QS ASC + impressions DESC tie-break (validar primeiras 3 entries)
- [ ] Audit_log entry criada (operation `audit_quality_score`, status `success`)

**Bonus — Consumer-side filter cross-validation (cravamento da utilidade A2):**

Capturar count breakdown (filter Python externo OU mental count nos primeiros 50 entries):

```
flagged = result["flagged_keywords"]
impactable = [k for k in flagged if k["ad_group_status"] == "ENABLED"]
orphan = [k for k in flagged if k["ad_group_status"] == "REMOVED"]
other = [k for k in flagged if k["ad_group_status"] not in ("ENABLED", "REMOVED")]

print(f"Total flagged: {len(flagged)}")
print(f"Impactable (ENABLED ad_group): {len(impactable)}")
print(f"Orphan (REMOVED ad_group): {len(orphan)}")
print(f"Other (PAUSED/UNKNOWN/etc): {len(other)}")
```

**Validação bonus:**

- [ ] `len(impactable) + len(orphan) + len(other) == total_flagged` (sanity)
- [ ] **Expectativa baseado em F52 pattern:** `len(orphan) > 0` (MO-JP tem históricode ad_groups REMOVED que ainda têm keywords flagged em quality score — cleanup cosmético oportunidade) — Wellington documentou cravamento F52 em `audit_zombie_keywords` 25/05, mesmo pattern esperado aqui
- [ ] Insight operacional: Wellington pode usar `impactable` como input direto pra `update_keyword_status` workflow (keywords que realmente impactam QS/Smart Bidding) vs `orphan` que são inventário cosmético

**Failure modes investigation:**

- `ad_group_status` ausente em alguma entry → bug propagation KeywordRow → FlaggedKeyword falhou (verificar `src/google_ads/flag_keywords.py:flag_keywords` construction)
- `ad_group_status` retorna integer raw (e.g. `3`) em vez de `"REMOVED"` → bug parser `parse_keyword_view_row` não está aplicando `.name` access em proto enum
- Description PRÉ-fix sem warning F52 → deploy não landed completamente, restart Claude Code

**Result:** ⬜ pending

---

## Test T2 — B9 `get_keyword_performance` retorna `negative: bool` em cada row + cross-validation com audit_zombie_keywords

**Setup:** Validar B9 — campo novo `negative: bool` em cada row de `get_keyword_performance`. Mitigação F56 Opção A+C: backward-compat field + warning F56 na description. Caller filtra client-side; tools `audit_zombie_keywords` + `audit_quality_score` continuam filtrando `negative=FALSE` server-side.

**Pré-requisito:** Step 4 baseline anotado (count get_keyword_performance + audit_zombie_keywords).

**Tool call:**

```
get_keyword_performance(
  customer_id="7862230676",
  status="enabled",
  limit=200
)
```

**Expected response shape (foco campo novo):**

```json
{
  "customer_id": "7862230676",
  "period": {"from": "2026-04-27", "to": "2026-05-27"},
  "rows": [
    {
      "criterion_id": "...",
      "keyword_text": "gerador honda",
      "match_type": "BROAD" | "PHRASE" | "EXACT",
      "status": "ENABLED",
      "negative": false,  // NOVO B9 — bool
      "quality_score": 7,
      "quality_creative": "ABOVE_AVERAGE" | null,
      "quality_post_click": "AVERAGE" | null,
      "quality_search_predicted_ctr": "ABOVE_AVERAGE" | null,
      "first_page_cpc_brl": 0.50,
      "top_of_page_cpc_brl": 1.20,
      "ad_group_id": "1001",
      "ad_group_name": "AG1",
      "campaign_id": "10",
      "campaign_name": "C1",
      "impressions": 100,
      "clicks": 10,
      "cost_brl": 5.00,
      "conversions": 1.0,
      "conversions_value_brl": 50.0,
      "ctr": 0.1,
      "cpc_brl": 0.50
    }
    // ... mix de negative=true + negative=false esperado em MO-JP CAB GERAL
  ]
}
```

**Validação:**

- [ ] Response retorna sem error (tool retorna dict válido sem `"error"` key)
- [ ] `len(rows) >= 1` (MO-JP tem keywords ENABLED em LAST_30_DAYS)
- [ ] **Crítico B9:** TODAS as rows contêm key `negative` (zero missing)
- [ ] Cada `negative` é tipo Python `bool` (não None, não string `"false"`)
- [ ] Description atualizada visível no inspector contém warning F56 + menção `negative=false` filter pattern (pre-flight Step 1 verifica)
- [ ] Mantém os 23 campos legacy (criterion_id, keyword_text, match_type, status, quality_*, first_page_cpc_brl, top_of_page_cpc_brl, ad_group_*, campaign_*, metrics)
- [ ] `period.from` + `period.to` formato YYYY-MM-DD
- [ ] Audit_log entry criada (operation `get_keyword_performance`, status `success`)

**Bonus — Cross-validation com audit_zombie_keywords (cravamento F56 mitigation real):**

Capturar count comparativo via filter Python externo:

```
# get_keyword_performance rows
all_rows = result["rows"]
positive_only = [r for r in all_rows if not r["negative"]]
negative_typed = [r for r in all_rows if r["negative"]]

print(f"Total rows (get_keyword_performance): {len(all_rows)}")
print(f"Positive (negative=false): {len(positive_only)}")
print(f"Negative typed (negative=true ENABLED): {len(negative_typed)}")
```

Compare com baseline Step 4 audit_zombie_keywords:

- [ ] `len(negative_typed) > 0` esperado em MO-JP CAB GERAL — Wellington documentou 39 negative ENABLED em 27/05 (Cat C produtos únicos protegidos)
- [ ] `len(positive_only)` aproximadamente igual ao subset positive zumbis de `audit_zombie_keywords` (que filtra `negative=FALSE` server-side) — diferença pode existir porque audit_zombie filtra apenas zumbis (impressions=0+clicks=0), e get_keyword_performance retorna todas keywords ENABLED. Validation real é direcional: `len(positive_only) >= len(audit_zombie_keywords["zombies"])` filtered ENABLED.
- [ ] Insight operacional: workflow "fresh fetch keywords → extract criterion_ids pra PAUSE batch" agora consegue filtrar client-side `negative=false` ANTES de passar pro `update_keyword_status` (evita 39 falsos positivos rejeitados pelo pre-flight F43)

**Failure modes investigation:**

- `negative` ausente em alguma row → bug `_row_formatter` não está atribuindo (verificar `src/mcp/tools/get_keyword_performance.py:_row_formatter`)
- `negative` retorna `None` em vez de `False` → bug proto-plus default não está sendo casted como bool (cast `bool(...)` defensive deve garantir)
- `negative=true` rows TODAS aparecem com `quality_score=None` + cost_brl=0.0 — esperado, pois negative criterion não tem QS nem cost (sanity check operacional)
- 0 rows com `negative=true` em MO-JP → improvável dado history 27/05, mas se acontecer documentar como observação (MO-JP pode ter sido limpo entre sessões) — re-run em CAB GERAL específico OU outra account com keywords negativas conhecidas

**Result:** ⬜ pending

---

## Test T3 — A1 `update_keyword_status` dry_run retorna `sample_keywords` top 5 + apply via `apply_change`

**Setup:** Validar A1 — campo novo `sample_keywords` (top 5 primeiros da lista caller) + `sample_truncated: bool` flag no DRY_RUN path de `update_keyword_status`. Server-side fetch obrigatório via novo módulo `src/google_ads/queries/keyword_lookup.py`. Apply via `apply_change(confirmation_token=<token>)` deve aplicar normalmente (sample não interfere com mutation real).

**Pré-requisito:** Step 5 anotado — 6+ keywords safe-to-pause selecionadas via `audit_zombie_keywords` filtered `ad_group_status='ENABLED'`. Wellington tem lista de `(ad_group_id, criterion_id)` pairs reais com expected `keyword_text` pra cross-validation.

**Tool call (dry_run path — >5 keywords força CONFIRM):**

```
update_keyword_status(
  customer_id="7862230676",
  keywords=[
    {"ad_group_id": "<ag_id_1>", "criterion_id": "<cr_id_1>"},
    {"ad_group_id": "<ag_id_2>", "criterion_id": "<cr_id_2>"},
    {"ad_group_id": "<ag_id_3>", "criterion_id": "<cr_id_3>"},
    {"ad_group_id": "<ag_id_4>", "criterion_id": "<cr_id_4>"},
    {"ad_group_id": "<ag_id_5>", "criterion_id": "<cr_id_5>"},
    {"ad_group_id": "<ag_id_6>", "criterion_id": "<cr_id_6>"}
  ],
  new_status="PAUSED"
)
```

*(Substituir `<ag_id_N>`/`<cr_id_N>` pelos pairs reais capturados no Step 5)*

**Expected response shape (DRY_RUN path):**

```json
{
  "status": "dry_run",
  "operation": "update_keyword_status",
  "customer_id": "7862230676",
  "blast_summary": "Mudar status de 6 palavra(s)-chave para PAUSED.",
  "sample_keywords": [
    {
      "ad_group_id": "<ag_id_1>",
      "criterion_id": "<cr_id_1>",
      "keyword_text": "rolo compactador",
      "match_type": "PHRASE"
    },
    {
      "ad_group_id": "<ag_id_2>",
      "criterion_id": "<cr_id_2>",
      "keyword_text": "dell aluguel",
      "match_type": "BROAD"
    },
    {
      "ad_group_id": "<ag_id_3>",
      "criterion_id": "<cr_id_3>",
      "keyword_text": "caminhao munck pequeno",
      "match_type": "EXACT"
    },
    {
      "ad_group_id": "<ag_id_4>",
      "criterion_id": "<cr_id_4>",
      "keyword_text": "placa solar valor",
      "match_type": "PHRASE"
    },
    {
      "ad_group_id": "<ag_id_5>",
      "criterion_id": "<cr_id_5>",
      "keyword_text": "forma metalica laje",
      "match_type": "BROAD"
    }
  ],
  "sample_truncated": true,
  "confirmation_token": "abc123def456...",
  "expires_in_minutes": 10,
  "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
  "confirmation_reason": "..."
}
```

**Validação (dry_run path):**

- [ ] `status == "dry_run"` (CONFIRM path acionado pois >5 keywords)
- [ ] **Crítico A1:** `"sample_keywords"` key presente na response
- [ ] `len(sample_keywords) == 5` (top 5 fixed V0)
- [ ] **Crítico A1:** `sample_truncated == true` (6 > 5 → truncado)
- [ ] **Crítico A1:** `sample_keywords[0]` corresponde ao PRIMEIRO da lista caller (preserva intent caller-defined)
- [ ] `sample_keywords[4]` corresponde ao QUINTO da lista caller
- [ ] Cada sample contém TODAS as 4 keys: `ad_group_id`, `criterion_id`, `keyword_text`, `match_type`
- [ ] **Crítico cross-validation:** `sample_keywords[N].keyword_text` matches expected_text anotado no Step 5 (server-side fetch funcionou)
- [ ] **Crítico cross-validation:** `sample_keywords[N].match_type` está em whitelist `["BROAD", "PHRASE", "EXACT"]` (não None, não raw integer)
- [ ] `confirmation_token` populated (string não-vazia)
- [ ] `expires_in_minutes == 10`
- [ ] `blast_summary` em PT-BR ("Mudar status de 6 palavra(s)-chave para PAUSED.")
- [ ] Audit_log entry criada (operation `update_keyword_status`, status `dry_run`)

**Apply step (verifica que sample não interfere com mutation):**

```
apply_change(
  confirmation_token="<token>"
)
```

**Expected apply response:**

```json
{
  "status": "applied",
  "operation": "update_keyword_status",
  "applied_count": 6,
  "provider_request_id": "..."
}
```

**Validação (apply):**

- [ ] `status == "applied"` (apply executado sem erro)
- [ ] `applied_count == 6` (todas as 6 keywords pausadas)
- [ ] `provider_request_id` populated (Google Ads trace_id)
- [ ] Mutation real aconteceu — verificar via `get_keyword_performance(status="paused", limit=200)` ou Google Ads UI: as 6 keywords agora em status PAUSED
- [ ] Audit_log entry adicional criada (operation `update_keyword_status`, status `success`, action_type `mutate`)

**Bonus — Cross-validation keyword_text vs get_keyword_performance:**

Pra 1 sample do `sample_keywords` (e.g. `sample_keywords[0]`), verificar que mesmo `criterion_id` retorna mesmo `keyword_text` em `get_keyword_performance`:

```
# Captura criterion_id de sample_keywords[0]
target_criterion_id = result["sample_keywords"][0]["criterion_id"]
target_keyword_text = result["sample_keywords"][0]["keyword_text"]

# Roda get_keyword_performance e filtra
perf_result = get_keyword_performance(customer_id="7862230676", status="paused", limit=500)
matching = [r for r in perf_result["rows"] if r["criterion_id"] == target_criterion_id]

assert len(matching) == 1
assert matching[0]["keyword_text"] == target_keyword_text
# Match → server-side fetch keyword_lookup.py funciona consistente com tactical.py
```

**Validação bonus:**

- [ ] Cross-validation match — `keyword_lookup.py` fetch retorna mesmo `keyword_text` que `tactical.py` `keyword_performance_query` (resource `ad_group_criterion` é absolute state — consistente com time-series `keyword_view`)

**Edge case — Partial fetch graceful (se algum criterion_id não resolver):**

- [ ] Se algum sample retornar `keyword_text=None` + `match_type=None` mas `ad_group_id`/`criterion_id` preservados → fetch graceful funcionou (ID exists mas Google API não retornou row). Documentar como nota observacional.

**Failure modes investigation:**

- `sample_keywords` ausente da response dry_run → bug Task 4 Step 7 wiring (verificar `src/mcp/tools/update_keyword_status.py` import + DRY_RUN branch)
- `sample_truncated == false` apesar de 6 > 5 → bug condição `target_count > _SAMPLE_SIZE` na response
- `sample_keywords[N].keyword_text == None` em TODAS as 5 entries → fetch helper não retornou nenhuma row (`run_report` mock OR Google API rejeitou) — investigar Cloud Run logs
- `apply_change` falha com error "confirmation_token expired" → 10min TTL passou, re-run T3 dry_run pra novo token
- Apply funciona mas keywords não viraram PAUSED → bug `run_mutation` em downstream OR Google API silent reject (verificar via Google Ads UI)
- **Reversibilidade:** se Wellington quiser desfazer T3 pós-smoke, run `update_keyword_status(customer_id="7862230676", keywords=[...mesmos pairs...], new_status="ENABLED")` pra reverter. Documentar reversal no smoke notes.

**Auto-apply path validation (≤5 keywords — sanity check separado, opcional):**

Pra confirmar que AUTO_APPLY path NÃO inclui `sample_keywords` (preserva backward-compat):

```
update_keyword_status(
  customer_id="7862230676",
  keywords=[
    {"ad_group_id": "<ag_id_1>", "criterion_id": "<cr_id_1>"},
    {"ad_group_id": "<ag_id_2>", "criterion_id": "<cr_id_2>"},
    {"ad_group_id": "<ag_id_3>", "criterion_id": "<cr_id_3>"}
  ],
  new_status="ENABLED"
)
```

**Validação opcional:**

- [ ] `status == "applied"` (auto path, ≤5 keywords)
- [ ] `"sample_keywords"` key NÃO presente (sem preview no auto path — YAGNI documentado spec §3.6)
- [ ] `applied_count == 3`

**Result:** ⬜ pending

---

## V4 invariants validation

| Invariant | Aplicável | Enforcement | How smoke verifies |
|---|---|---|---|
| country_code = BR | N/A | N/A — sprint 3b.40 não toca geo data | — |
| language_code = pt-BR | ✅ Description | Tool descriptions PT-BR com warnings F52/F56 (`audit_quality_score`, `get_keyword_performance`); A1 mantém PT-BR existente | Pre-flight Step 1: inspector mostra descriptions PT-BR atualizadas |
| currency_code = BRL | ✅ Output | `cost_brl` em A2 + B9 retornados em BRL (não micros) | T1+T2 validam shape `cost_brl` float |
| timezone = -03:00 | N/A | N/A — sprint não toca timestamps em response shape | — |
| LGPD consent | N/A | Read-only A2+B9; A1 é mutate mas keywords não são PII | Audit_log captura quem aplicou (Wellington) — herdado de `run_report(audit_this_call=True)` |
| Schema whitelist V4 (3b.19A) | ✅ Input | Enum `match_type` proto-plus access `.name` em A2+B9+A1 (BROAD/PHRASE/EXACT); Enum `new_status` em A1 (ENABLED/PAUSED) | T1 valida sample.match_type em whitelist; T3 valida new_status accepted |
| No composition keywords (3b.19B.1) | ✅ Schema | Schema sem `oneOf/allOf/anyOf` em qualquer nesting level (regression `test_no_composition_keywords_in_any_schema`) | Pre-flight test passa |
| F52 pattern replicated (A2) | ✅ Output | `ad_group_status` field em flagged_keywords expostas via proto `ad_group.status.name` (Sprint 3b.7 lesson) | T1 valida campo presente + PT-BR-mapped enum + bonus filter ENABLED |
| F56 mitigation (B9) | ✅ Output | `negative: bool` cast defensivo em row_formatter; warning F56 description | T2 valida campo presente + bool type + cross-validation com audit_zombie |
| A1 sample top 5 (dogfood 27/05) | ✅ Output | `sample_keywords` top 5 + `sample_truncated` flag no DRY_RUN; server-side fetch via novo módulo `keyword_lookup.py` | T3 valida top 5 = primeiros 5 caller + truncated flag + keyword_text resolved |
| A1 fetch graceful (partial fetch tolerance) | ✅ Algorithm | `text_index.get(...)` retorna `{}` se ID não resolveu → sample tem keyword_text=None + match_type=None mas ids preservados | T3 edge case opcional valida graceful path |
| Sample ordering (primeiros 5 caller) | ✅ Algorithm | `for ad_group_id, criterion_id in keyword_pairs[:_SAMPLE_SIZE]` preserva intent caller-defined | T3 valida `sample_keywords[0]` matches lista[0] caller |
| keyword_lookup query absolute state | ✅ Query design | GAQL sobre `ad_group_criterion` resource (sem `segments.date` filter) — mais barato que `keyword_view` time-series | Pre-flight unit `test_keyword_lookup.py::test_build_query_dedups_and_sorts_ids` valida "segments.date" not in query |
| Backward-compat A2+B9 (additive only) | ✅ API surface | Campos novos `ad_group_status`/`negative` adicionados sem remover campos legacy (zero breaking change) | T1+T2 validam shape mantém todos os legacy fields |
| F56 catalogado pré-implementation | ✅ Process | F56 row cravada em `findings-catalog.md` ANTES dos commits A2/B9/A1 (atomic commit per F-finding) | Pre-flight verifica `findings-catalog.md` contém row F56 |

---

## Per-value empirical probe summary (Sprint 3b.19A.1 convention)

**Aplicabilidade:** Sprint 3b.40 NÃO introduz novos enums ou whitelists. Todos os enums tocados são pre-existing:

- `audit_quality_score.match_type` (3 valores BROAD/PHRASE/EXACT) — coverage herdada de smoke 3b.30
- `audit_quality_score.ad_group_status` (5 valores ENABLED/PAUSED/REMOVED/UNSPECIFIED/UNKNOWN) — **novo OUTPUT enum** — coverage validada via T1 (esperado encontrar ENABLED + REMOVED em MO-JP)
- `get_keyword_performance.match_type` (3 valores) — coverage herdada de smoke 3b.30
- `get_keyword_performance.negative` (2 valores bool true/false) — **novo OUTPUT field** — coverage validada via T2 (esperado encontrar ambos)
- `get_keyword_performance.status` enum (4 valores enabled/paused/removed/all) — coverage herdada
- `update_keyword_status.new_status` (2 valores ENABLED/PAUSED) — coverage herdada de smoke 3b.27

Per-value probe **dispensado pra novos OUTPUT enums** porque:
1. Não há schema whitelist input pra reject (campos são OUTPUT only)
2. Validação é "campo presente + valor em whitelist runtime" — coberta nos próprios T1+T2 com observação direta
3. Convention 3b.19A.1 endereça especificamente INPUT enum reject in schema validation layer (Anthropic Messages API)

**Critério PASS:** T1 retorna pelo menos 1 entry com `ad_group_status="ENABLED"` E pelo menos 1 entry com `ad_group_status="REMOVED"` (cravamento F52 pattern); T2 retorna pelo menos 1 row com `negative=true` E pelo menos 1 row com `negative=false`.

---

## Cleanup post-smoke

**T1 (A2 read-only):** zero cleanup. Pure read.

**T2 (B9 read-only):** zero cleanup. Pure read.

**T3 (A1 mutate REAL):** 6 keywords pausadas via apply em MO-JP. Opções:

1. **Manter pausadas** (default): se Wellington selecionou keywords legitimamente zumbis safe-to-pause, manter o estado new (PAUSED) — alinhado ao workflow real de cleanup. Documentar nos smoke notes quais foram pausadas.
2. **Reverter pra ENABLED** (rollback): se Wellington quiser testar idempotência ou se as 6 keywords selecionadas não eram safe pós-revisão, run:

```
update_keyword_status(
  customer_id="7862230676",
  keywords=[
    {"ad_group_id": "<ag_id_1>", "criterion_id": "<cr_id_1>"},
    {"ad_group_id": "<ag_id_2>", "criterion_id": "<cr_id_2>"},
    {"ad_group_id": "<ag_id_3>", "criterion_id": "<cr_id_3>"},
    {"ad_group_id": "<ag_id_4>", "criterion_id": "<cr_id_4>"},
    {"ad_group_id": "<ag_id_5>", "criterion_id": "<cr_id_5>"},
    {"ad_group_id": "<ag_id_6>", "criterion_id": "<cr_id_6>"}
  ],
  new_status="ENABLED"
)
```

Recomendação default: **manter pausadas** (workflow legitimate). Audit_log entries ficam permanentes (rastreio histórico).

---

## Notas pra Wellington pós-smoke

1. **Uso real após smoke:** workflow cleanup massivo MO-JP recurring agora consolidado:
   - **Pre-cleanup:** `audit_quality_score(customer_id=<conta>)` → consumer-side filter `ad_group_status=='ENABLED'` → impactable subset
   - **Pre-cleanup fresh fetch (alternativa):** `get_keyword_performance(customer_id=<conta>, status="enabled", limit=200)` → consumer-side filter `not negative` → positive subset
   - **Cross-validate:** comparar count com `audit_zombie_keywords` (server-side filter)
   - **PAUSE batch:** `update_keyword_status(customer_id=<conta>, keywords=[...], new_status="PAUSED")` → sanity check `sample_keywords` top 5 → `apply_change(token)`

2. **Workflow combinado A2 + A1:** `audit_quality_score` retorna candidates pra `update_keyword_status`. Workflow:
   - Capturar `(ad_group_id, keyword_id)` de cada `flagged_keyword` com `ad_group_status=='ENABLED'` E `flags` contains "candidate_pause"
   - Passar como `keywords` param pra `update_keyword_status` com `new_status="PAUSED"`
   - Sample top 5 valida intent ANTES de apply (proteção contra bug humano em batch TTL 10min)

3. **B9 mitigation cravada:** descrição F56 direciona caller pra usar `audit_zombie_keywords`/`audit_quality_score` em vez de `get_keyword_performance` quando workflow é positive-only (90% dos casos cleanup). `get_keyword_performance` mantém-se útil pra inventário completo (ambos positive + negative) com QS detalhado.

4. **Se T1 não retornar entries em REMOVED ad_groups:** Provavelmente MO-JP foi limpa recentemente. Re-run com `date_range="LAST_90_DAYS"` pra recapturar volume histórico OU aceitar como sinal positivo de hygiene da conta. Validation A2 ainda PASS desde que `ad_group_status` esteja presente em todas entries (mesmo que todas sejam ENABLED).

5. **Se T2 não retornar rows com `negative=true`:** Provavelmente MO-JP CAB GERAL teve cleanup de negative criterion entre sessões. Re-run em outra account com keywords negativas conhecidas OR aceitar como observação. Validation B9 ainda PASS desde que `negative` field esteja presente em todas as rows com tipo bool.

6. **Se T3 apply falhar com "all keywords already PAUSED":** Cleanup recente já pausou as keywords selecionadas. Selecionar outras 6 pairs do `audit_zombie_keywords` output ou ajustar `new_status="ENABLED"` pra revert testing.

7. **V1+ candidates Sprint Quick Wins #2 (Q3):**
   - A3 (`summary_only` mode em audit tools) — reduzir token usage em accounts grandes
   - A4 (`already_exists` graceful skip em `update_keyword_status`) — idempotência
   - A5 (`limit_per_ad_group`) — fairness em batch pause multi-ad_group
   - A6 (`last_conv_date` em audit outputs) — recency signal pra decision
   - B1 (batch tokens em `apply_change` — reverter 9 mudanças com 1 call em vez de 9)
   - B2/B3 (server-side filters em `search_terms`/`keyword_performance`)
   - D1-D3 (cravar lições V4 em descriptions de tools adjacentes)

8. **F52+F56 family lesson reinforced:** Tools de listagem que feed mutate workflows MUST expor type discriminators (status, negative, etc) explícitos no output, mesmo que GAQL native exponha. Tool layer não pode confiar que caller saiba inspecionar SDK proto fields. Family: design-gap-via-missing-discriminator-field (variant da silent-acceptance family). Aplicar pattern em sprints futuras quando expor novos resources via tools listing.

9. **Sample size A1 fixo top 5 V0:** YAGNI documentado. Expandir só se demanda real (e.g. Wellington pedir "preview 20 keywords pra batch maior"). Configurable `sample_size` param em V1+ se necessário.

10. **Sprint counter:** atualizar CLAUDE.md (Last shipped: 3b.39 → 3b.40) + sprint-history.md após signoff. Tool count permanece **62** (zero novas tools — sprint enhance-only).
