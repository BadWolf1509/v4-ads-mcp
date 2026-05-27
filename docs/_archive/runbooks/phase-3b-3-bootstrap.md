# Phase 3b.3 — manual smoke runbook

**Purpose:** Verify `add_keywords` works against real V4 account before declaring Sprint 3b.3 done.

**Operator:** Claude (Sonnet 4.7) executando em sessão dirigida por wellinton.ribeiro@v4company.com
**Account (mutation sandbox):** `1163862076` "Rayane Ribeiro - Nutry" (paused campaigns, zero traffic — same sandbox used in 3b.1 + 3b.2 smokes)
**Date completed:** 2026-05-12
**Production revision tested:** `v4-ads-mcp-00096-mzm` (commit `657f8f6`)

## Pre-flight

- [x] Deploy lands successfully — revision `v4-ads-mcp-00096-mzm` on commit `657f8f6`
- [x] Service `/health` returns 200
- [x] MCP client reloaded (post session restart) — tools list includes `add_keywords`

## Test 1 — `add_keywords` 1 KW EXACT (AUTO path) ✅

Ad group: `183008426336` (campaign `22804468687` "[CP][RAYANE][GT LUCAS][PESQUISA]" — paused, zero traffic).

Call:
```
add_keywords(
  customer_id="1163862076",
  ad_group_id="183008426336",
  keywords=[{"text": "claude smoke kw 001", "match_type": "EXACT"}]
)
```

Response:
```json
{
  "status": "applied",
  "applied_count": 1,
  "google_request_id": "qbbZPP0JzY_MeV6hNyxDKg",
  "auto_applied_reason": "add_keywords (1 KWs em 1 ad_group) — auto",
  "added": [{"text": "claude smoke kw 001", "match_type": "EXACT", "status": "added"}]
}
```

- [x] `status: "applied"`, `applied_count: 1`, real `google_request_id`
- [x] `added[0].status: "added"`
- [x] AUTO path triggered (1 ≤ 20) com PT-BR reason
- [x] Criterion criada com `criterion_id: 2484775198275` (confirmado via GAQL `SELECT … FROM ad_group_criterion WHERE keyword.text = 'claude smoke kw 001'`)

## Test 2 — `add_keywords` SAME KW (idempotency) ✅ COM ACHADO

Re-run T1 com text + match_type idênticos:

Response:
```json
{
  "status": "applied",
  "applied_count": 1,
  "google_request_id": "wXoIgpxTP2Kp5SqfvM5HAA",
  "added": [{"text": "claude smoke kw 001", "match_type": "EXACT", "status": "added"}]
}
```

**Achado real:** Google Ads API faz **silent dedupe server-side** em vez de retornar `CRITERION_EXISTS`. Confirmado:
- `google_request_id` diferente do T1 (`wXoIgpxTP2Kp5SqfvM5HAA` ≠ `qbbZPP0JzY_MeV6hNyxDKg`) → chamada real à API
- GAQL após T2 retorna **exatamente 1 row** com `criterion_id: 2484775198275` → nenhuma duplicata criada
- `partial_failures` está vazio (Google reportou sucesso) → nossa lógica `_classify_partial` mapeia pra `"added"` em vez de `"already_exists"`

**Implicação:** Sistema continua idempotente (state-wise) mas o sinal explícito `"already_exists"` no response **não funciona via Google partial_failure mode** — Google não envia o erro, simplesmente deduplica. O mapping `CRITERION_EXISTS`/`DUPLICATE_KEYWORD` no `_classify_partial` ainda é correto como defensive guard (caso o behavior mude no futuro), mas na prática nunca dispara.

- [x] `status: "applied"`, `applied_count: 1` (Google reportou success)
- [x] Sem criterion duplicada (GAQL confirma 1 row apenas)
- [x] Tool e sistema idempotentes na prática
- [ ] ~~`added[0].status: "already_exists"`~~ — **Google não retorna o erro; dedupe silencioso**

Update na spec/docstring é warranted: idempotência via Google dedupe (não via CRITERION_EXISTS mapping). Não bloqueia.

## Test 3 — `add_keywords` 25 KWs (CONFIRM path) ✅

Bulk batch acima do threshold (25 > 20):

Call: 25 keywords `claude smoke kw 002` até `claude smoke kw 026`, todas EXACT.

Response:
```json
{
  "status": "dry_run",
  "confirmation_token": "5M4TTKLH",
  "expires_in_minutes": 10,
  "confirmation_reason": "add_keywords: more than 20 KWs (25) — confirmar",
  "blast_summary": "Adicionar 25 KW(s) ao ad_group 183008426336. Match types: EXACT(25)."
}
```

- [x] `status: "dry_run"`, `confirmation_token: "5M4TTKLH"` retornado
- [x] PT-BR reason cita threshold 20 explicitamente
- [x] **Deliberadamente NÃO chamou `apply_change`** (token expirou após 10min naturalmente — sem clutter de 25 test KWs)

## Test 4 — Schema rejection (match_type inválido) ✅

```
add_keywords(
  customer_id="1163862076",
  ad_group_id="183008426336",
  keywords=[{"text": "x", "match_type": "REGEX"}]
)
```

Response:
```
Input validation error: 'REGEX' is not one of ['EXACT', 'PHRASE', 'BROAD']
```

- [x] Schema rejection no transporte MCP (validação antes da tool rodar)
- [x] Erro nomeia o valor inválido + lista os válidos
- [x] Nenhuma mutação no Google Ads (zero quota consumida)

## Cleanup ⚠️ COM ACHADO

Tentativa: `update_keyword_status(criterion_id="2484775198275", new_status="REMOVED")`:

Step 1 (dry_run) — OK:
```json
{
  "status": "dry_run",
  "confirmation_token": "S0B8CDNS",
  "confirmation_reason": "update_keyword_status: new_status=REMOVED — remove qualquer coisa sempre confirma (spec §7.1)"
}
```

Step 2 (apply_change) — **REJEITADO PELO GOOGLE:**
```
Google Ads retornou: Enum value 'REMOVED' cannot be used.
```

**Achado:** `AdGroupCriterion.status` field **só aceita ENABLED|PAUSED**. Pra deletar uma keyword é necessário emitir uma `ad_group_criterion_operation.remove` (com resource_name), NÃO um `update` com status=REMOVED. **Bug pré-existente do Sprint 3a** que afeta `update_keyword_status` (e provavelmente os 3 sibling tools — `update_campaign_status`, `update_ad_group_status`, `update_ad_status`, todos os quais o Sprint 3b.2 retrofit deliberadamente NÃO testaram via `apply_change`). Sprint 3b.3 smoke é a primeira tentativa real de aplicar REMOVED via os 4 tools.

Cleanup alternativo: PAUSED em vez de REMOVED (campanha já paused, zero impacto):

```json
{
  "status": "applied",
  "applied_count": 1,
  "google_request_id": "-4hPIyZ7tfOjjBgJPkf9ag",
  "auto_applied_reason": "update_keyword_status: single entity — auto"
}
```

- [x] KW `2484775198275` pausada com sucesso
- [x] Bug REMOVED-on-keyword flagged como follow-up task separado (não bloqueia Sprint 3b.3)
- [x] Conta `1163862076` em estado idempotente: 1 test KW pausada, campanha paused, zero impacto

## Achados consolidados

### A1: Idempotência via silent dedupe (NÃO via CRITERION_EXISTS error)

Google Ads API em partial_failure mode **silenciosamente deduplica** keyword adds com text+match_type duplicados. Não retorna `CRITERION_EXISTS`. Nossa lógica `_classify_partial` está correta defensively (mapeia o erro SE chegar), mas na prática nunca dispara.

**Action:** atualizar docstring do tool + spec §3.7 pra refletir realidade. O comportamento end-user é idempotente, só não retorna o sinal explícito esperado.

### A2: REMOVED status rejected on AdGroupCriterion.update (bug pré-Sprint 3b.3)

`update_keyword_status(new_status="REMOVED")` passa pelo dry-run gate (Sprint 3b.2 retrofit), mas `apply_change` falha porque `AdGroupCriterion.status` só aceita ENABLED|PAUSED. Mesmo problema provavelmente afeta os outros 3 status ops — Sprint 3b.2 nunca testou apply de REMOVED em produção.

**Action:** spawn_task criado (chip mostrado ao gestor). Fix via brainstorming: Option A (schema-restrict to ENABLED/PAUSED + separate remove_* tools) ou Option B (builder branches to remove operation when REMOVED). V4 practice favors PAUSE over REMOVE (preserva Quality Score history), então Option A pode ser preferível.

## Sign-off final

- [x] 4 de 4 tests core passaram (T1 ✅, T2 ✅ com achado, T3 ✅, T4 ✅)
- [x] Cleanup completo (via PAUSE em vez de REMOVE — bug pré-existente flagged)
- [x] 2 achados reais documentados (A1 silent dedupe, A2 REMOVED bug)
- [x] Production revision: `v4-ads-mcp-00096-mzm` (commit `657f8f6`)
- [x] CLAUDE.md a atualizar: Sprint 3b.3 shipped 2026-05-12

**Date completed:** 2026-05-12 (executado por Claude em sessão dirigida por wellinton.ribeiro@v4company.com)
