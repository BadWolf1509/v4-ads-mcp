# Phase 3b.39 — manual smoke runbook (Tool Bucket Classification + Wellington Claude Code config)

**Purpose:** Validar Sprint 3b.39 — Fase 1 do refactor arquitetural V4 Ads MCP. Server-side metadata-only: 59 tools recebem tag `# bucket: always|defer` + description prefix `[CORE]`/`[DEFER]` + `_meta.com.v4company/bucket` em `tools/list` response. Wellington atualiza manualmente `~/.claude/settings.json` (client-side) com `defer_loading` per-tool baseado nos prefixes. Sem mudança de comportamento server-side em `list_tools()` (todas 59 tools continuam listed; defer-loading é decisão Anthropic Messages API client-side parameter — descoberta D2 finding via OQ1 research).

**Operator:** wellinton.ribeiro@v4company.com
**Conta primária smoke (T4):** `6436352492` MCC V4 Maceió (entry point — `list_my_accounts` retorna 25 child accounts)
**Conta secundária (T5):** `7862230676` Mestre da Obra JP (`audit_zombie_keywords` — defer tool by-name invocation)

**Spec:** `docs/superpowers/specs/2026-05-25-architecture-refactor-design.md` §5 (Fase 1)
**Plan:** `docs/superpowers/plans/2026-05-25-sprint-3b-39-tool-bucket-classification.md`
**Bucket classification source:** `docs/operacao/tool-buckets-2026-05-25.md` (commit f55954c)
**Discovery D2 (OQ1):** MCP `defer_loading` é CLIENT-SIDE Anthropic Messages API parameter (`anthropic-beta: advanced-tool-use-2025-11-20`), NÃO server metadata. F1 reformulada pra server-metadata-only + Wellington manual client config.

> **Escopo F1 confirmado:**
> - **Server-side mecânicas:** `@register_tool` extended com `bucket: Literal["always", "defer"]` kwarg (default "defer", conservative). Mass-edit 59 tool files com (1) `# bucket: ...` comment line 1 grepability, (2) `bucket="..."` kwarg, (3) description prefix `[CORE]` ou `[DEFER]`. `list_tools()` retorna `_meta={"com.v4company/bucket": t.bucket}` per tool (reverse-DNS namespacing).
> - **Sem mudança comportamental server:** todas 59 tools continuam listed via `tools/list`; nenhuma é excluída do response. Defer = decisão CLIENT-SIDE em config.
> - **Wellington manual side:** edit `~/.claude/settings.json` adicionando `defer_loading: true` per defer tool (38 entries) + `anthropic-beta` beta header no MCP server connection.
> - Bucket counts canonical: **21 always-loaded** ([CORE] prefix) + **38 defer-loading** ([DEFER] prefix) = 59 total. Source of truth: description prefix (commit ac0941a estabeleceu consistência pós-Task C followup).
> - Tool count: 59 → **59** (sem mudança — F1 metadata-only, archive vem F3 Sprint 3b.41).
> - Conhecida inconsistência: 21 [CORE] description prefixes vs 20 `bucket="always"` kwargs em registry (`meta_list_my_ad_accounts` tem [CORE] description via _DESCRIPTION constante mas falta `bucket="always"` explicit kwarg). NÃO bloqueia F1: prefix é primary signal pra Wellington Claude Code config; kwarg secondary pra introspection futura. Fix candidate cleanup post-smoke.

## Production URL

`https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`

## Pre-flight

- [ ] Deploy lands successfully (CI + Deploy green em commit final Task F)
- [ ] Service `/health` returns 200 (`{"status":"ok","version":"0.1.0"}`)
- [ ] Pre-push gate `python scripts/check_pre_push.py` 5/5 PASS
- [ ] Unit tests `tests/unit/test_registry_bucket.py` 3/3 PASS (Task B coverage)
- [ ] Tool count baseline: 59 files em `src/mcp/tools/` (excluindo _registry/_meta_common/_common/__init__)
- [ ] Bucket distribution baseline: 21 `# bucket: always` + 38 `# bucket: defer` comments
- [ ] Description prefix distribution: 21 [CORE] + 38 [DEFER] (source of truth)
- [ ] Wellington tem Claude Code instalado + `~/.claude/settings.json` writable
- [ ] Baseline `audit_log` query rodada (Task A output em `tool-buckets-2026-05-25.md`)

Production revisions: `v4-ads-mcp-XXXXX-xxx` (preencher após deploy final).

## Smoke results

Preencher conforme execução. Marcar resultado final no fim do arquivo.

| # | Test | Result | Notes |
|---|---|---|---|
| T1 | Baseline measurement server-side (file grep + counts) | ⬜ pending | |
| T2 | Server registry introspection (Python script) | ⬜ pending | |
| T3 | Wellington manual Claude Code config procedure | ⬜ pending | |
| T4 | Regression always-loaded tool funciona idêntico (list_my_accounts) | ⬜ pending | |
| T5 | Defer tool invocação by-name funciona (audit_zombie_keywords) | ⬜ pending | |
| T6 | Wellington 7d feedback collection template | ⬜ pending | |

**Effective result:** N/6 PASS + Y DEFERRED

### F-findings emerged

_Preencher durante smoke. Template: `**F## (SEV)** — <symptom>. Fix: <plan>. Family: <bug class>.`_

Se zero F-findings: documentar explicitly "Zero F-findings novos. Sprint clean."

### Sign-off

- [ ] Pre-push gate 5/5 PASS
- [ ] Code quality reviewers APPROVED (Tasks A-F)
- [ ] Production `/health` 200 (revisão final)
- [ ] T1, T2 PASS (auto, server-side mecânicos)
- [ ] T3 PASS (Wellington manual config completa sem erro)
- [ ] T4, T5 PASS (always-loaded + defer tools funcionais)
- [ ] T6 template criado + GitHub issue aberto (response 7d post-deploy)
- [ ] CLAUDE.md §Pending atualizado (F1 shipped, F2 next)
- [ ] sprint-history.md updated com entry Sprint 3b.39
- [ ] findings-catalog.md atualizado com D2 (MCP defer_loading client-side discovery)
- [ ] Tool count 59 confirmado em produção (sem mudança — F1 metadata-only)

---

## Pre-smoke setup

### Step 1: Sanity check Claude Code reconhece servidor pós-deploy

Conectar Claude/Inspector à URL de produção (`https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/mcp`). Confirmar que:

```
# Tool list count = 59 (sem mudança vs pre-3b.39)
# Tool descriptions agora prefixadas:
#   - 21 tools com prefix "[CORE]" (always)
#   - 38 tools com prefix "[DEFER]" (defer)
# _meta field presente em cada tool response:
#   - "com.v4company/bucket": "always" OR "defer"
```

Se tool count mudou (não-59) OR algum tool sem prefix, deploy não landed ou Task C mass-edit gaps — abortar smoke + investigar.

### Step 2: Capture bucket distribution baseline pra runbook

Roda local pra capturar lista exata pra T1/T2 + Wellington config generation:

```bash
# Tool count total (sanity, deve ser 59)
ls src/mcp/tools/*.py | grep -v _registry | grep -v _meta_common | grep -v _common | grep -v __init__ | wc -l

# Tools always (file comment baseline — 21)
grep -l "^# bucket: always" src/mcp/tools/*.py | sort > /tmp/always_tools.txt
wc -l /tmp/always_tools.txt

# Tools defer (file comment baseline — 38)
grep -l "^# bucket: defer" src/mcp/tools/*.py | sort > /tmp/defer_tools.txt
wc -l /tmp/defer_tools.txt

# Description prefix [CORE] (canonical — 21)
grep -l '"\[CORE\]' src/mcp/tools/*.py | wc -l

# Description prefix [DEFER] (canonical — 38)
grep -l '"\[DEFER\]' src/mcp/tools/*.py | wc -l
```

Esperado:
- `/tmp/always_tools.txt`: 21 paths
- `/tmp/defer_tools.txt`: 38 paths
- 21 + 38 = 59 total ✓

---

## Test T1 — Baseline measurement (server-side)

**Setup:** Auto-verificável via shell. Confirma bucket tagging consistency cross-mechanism (file comment + description prefix). Pré-requisito pra Task F commit.

**Commands:**

```bash
# Bucket comment counts
echo "Always comments: $(grep -l '^# bucket: always' src/mcp/tools/*.py | wc -l)"
echo "Defer comments: $(grep -l '^# bucket: defer' src/mcp/tools/*.py | wc -l)"

# Description prefix counts
echo "[CORE] prefix: $(grep -l '\"\[CORE\]' src/mcp/tools/*.py | wc -l)"
echo "[DEFER] prefix: $(grep -l '\"\[DEFER\]' src/mcp/tools/*.py | wc -l)"

# Tool file count
echo "Total tool files: $(ls src/mcp/tools/*.py | grep -v _registry | grep -v _meta_common | grep -v _common | grep -v __init__ | wc -l)"
```

**Expected output:**

```
Always comments: 21
Defer comments: 38
[CORE] prefix: 21
[DEFER] prefix: 38
Total tool files: 59
```

**Validação:**

- [ ] Always comments == 21
- [ ] Defer comments == 38
- [ ] [CORE] prefix == 21
- [ ] [DEFER] prefix == 38
- [ ] Total tool files == 59
- [ ] Always + Defer == Total (21 + 38 == 59)
- [ ] Comments count == Prefix count (file comment matches description prefix — sem drift)

**Known inconsistency note:** Description prefix [CORE] = 21 (canonical) MAS registry `bucket="always"` kwarg count = 20 (`meta_list_my_ad_accounts` tem [CORE] description via constante `_DESCRIPTION` mas falta `bucket="always"` explicit kwarg). NÃO bloqueia smoke: prefix é primary signal pra Wellington Claude Code config; kwarg secondary pra introspection futura. Documentado como cleanup candidate pós-smoke.

**Result:** ⬜ pending

---

## Test T2 — Server registry introspection (Python script)

**Setup:** Validar `_TOOLS` registry state pós-`import_all_tools()`. Cross-check counts via runtime (não só grep). Também valida que `_meta.com.v4company/bucket` field é exposed em `tools/list` response.

**Script (rodar local em ambiente venv):**

```python
import src.mcp.server  # triggers import_all_tools() side effect
from src.mcp.tools._registry import _TOOLS, all_tools

# Source of truth pra Wellington Claude Code config = description prefix
core_tools = sorted([t.name for t in _TOOLS.values() if t.description.startswith("[CORE]")])
defer_tools = sorted([t.name for t in _TOOLS.values() if t.description.startswith("[DEFER]")])
no_prefix = [t.name for t in _TOOLS.values() if not (t.description.startswith("[CORE]") or t.description.startswith("[DEFER]"))]

print(f"[CORE] (always): {len(core_tools)} tools")
print(f"[DEFER] (defer): {len(defer_tools)} tools")
print(f"No prefix (BUG if >0): {len(no_prefix)} -> {no_prefix}")
print(f"Total registered: {len(_TOOLS)}")
print()
print("=== ALWAYS tools (Wellington keep loaded) ===")
for n in core_tools:
    print(f"  {n}")
print()
print("=== DEFER tools (Wellington defer_loading=true) ===")
for n in defer_tools:
    print(f"  {n}")
```

**Expected output:**

```
[CORE] (always): 21 tools
[DEFER] (defer): 38 tools
No prefix (BUG if >0): 0 -> []
Total registered: 59

=== ALWAYS tools (Wellington keep loaded) ===
  add_negative_keywords
  apply_audience
  audit_competitor_keywords
  audit_goal_attribution
  audit_quality_score
  audit_zombie_keywords
  bulk_pause_by_query
  create_and_link_assets
  create_campaign
  create_conversion_action
  detect_drift
  get_change_history
  get_conversion_actions
  get_recommendations
  list_my_accounts
  meta_get_account_overview
  meta_list_my_ad_accounts
  remove_audience
  update_ad_group_status
  update_keyword_bid
  update_keyword_status

=== DEFER tools (Wellington defer_loading=true) ===
  add_keywords
  add_negatives_from_search_terms
  apply_change
  apply_recommendation
  audit_orphan_smart_actions
  create_ad_group
  create_conversion_value_rule_set
  create_rsa
  dismiss_recommendation
  get_account_overview
  get_ad_group_performance
  get_ad_performance
  get_audience_performance
  get_budget_pacing
  get_campaign_performance
  get_device_performance
  get_funnel_metrics
  get_geo_performance
  get_hourly_performance
  get_keyword_performance
  get_my_audit_log
  get_my_rate_limit_status
  get_negative_keywords_audit
  get_search_terms_report
  get_top_keywords_creatives
  import_offline_conversions
  list_gaql_resources
  remove_negative_keywords
  run_gaql
  update_ad_group_bid
  update_ad_status
  update_campaign_bidding
  update_campaign_budget
  update_campaign_status
  update_conversion_action
  update_rsa
  upload_customer_match_list
  validate_gaql
```

**Validação:**

- [ ] [CORE] count == 21
- [ ] [DEFER] count == 38
- [ ] No prefix count == 0 (BUG se >0 — Task C mass-edit gap)
- [ ] Total registered == 59
- [ ] Always list contém entries esperadas (cross-ref `tool-buckets-2026-05-25.md` §Always-loaded bucket)
- [ ] Defer list contém entries esperadas (cross-ref `tool-buckets-2026-05-25.md` §Defer-loading bucket)
- [ ] Lista ordenada alfabeticamente (sort consistency)

**Validação adicional — `_meta` field em `tools/list` response (opcional, requer MCP Inspector OR curl):**

Se MCP Inspector disponível, validar que tool entries em `tools/list` response têm:

```json
{
  "name": "audit_zombie_keywords",
  "description": "[CORE] ...",
  "inputSchema": {...},
  "_meta": {
    "com.v4company/bucket": "always"
  }
}
```

- [ ] `_meta.com.v4company/bucket` presente em cada tool entry
- [ ] Valor `"always"` pra [CORE]-prefixed tools
- [ ] Valor `"defer"` pra [DEFER]-prefixed tools (NB: este reflete kwarg state — pode mostrar "defer" pra `meta_list_my_ad_accounts` mesmo com [CORE] prefix, conforme known inconsistency T1)

**Result:** ⬜ pending

---

## Test T3 — Wellington Claude Code config procedure

**Setup:** Core deliverable de F1. Wellington edita manualmente `~/.claude/settings.json` adicionando defer_loading per-tool. Procedure step-by-step abaixo. Decision gate D2 confirma: defer_loading é CLIENT-SIDE Anthropic Messages API parameter, NÃO server config — Claude Code repassa pro API call.

### Step 3.1 — Locate Claude Code user settings file

**Windows (Wellington dev env):**

```powershell
# User settings (per-user defaults)
$userSettings = Join-Path $env:USERPROFILE ".claude\settings.json"
Test-Path $userSettings    # esperado: True
Get-Item $userSettings | Select FullName, Length
```

Esperado: `C:\Users\welli\.claude\settings.json` exists (verificado pré-runbook).

**Mac/Linux (futuros colaboradores V4 LS&Co):**

```bash
ls -la ~/.claude/settings.json
```

**Confirmação Claude Code config layout (verify com `claude --help` OR Anthropic docs):**

- [`~/.claude/settings.json`](https://docs.anthropic.com/en/docs/claude-code/settings) — user-level config (permissions, defaults, env vars, MCP servers)
- Project-level: `.mcp.json` (root projeto) — MCP server definitions
- `tools` / `defer_loading` schema exato em Claude Code ainda **TBD pendendo release notes** (esta é a única open question). Procedure abaixo segue best-guess baseado em D2 research; ajustar se Claude Code schema diferir.

### Step 3.2 — Backup settings.json antes de editar

```powershell
Copy-Item $userSettings "$userSettings.bak-pre-3b39"
```

Rollback path: `Copy-Item "$userSettings.bak-pre-3b39" $userSettings` restaura estado pré-3b.39.

### Step 3.3 — Gerar lista defer tools embarcada pra config

Lista canonical embedded abaixo (extraída de T2 output — 38 tools).

**Defer tools (Wellington adiciona estes 38 em config):**

```
add_keywords
add_negatives_from_search_terms
apply_change
apply_recommendation
audit_orphan_smart_actions
create_ad_group
create_conversion_value_rule_set
create_rsa
dismiss_recommendation
get_account_overview
get_ad_group_performance
get_ad_performance
get_audience_performance
get_budget_pacing
get_campaign_performance
get_device_performance
get_funnel_metrics
get_geo_performance
get_hourly_performance
get_keyword_performance
get_my_audit_log
get_my_rate_limit_status
get_negative_keywords_audit
get_search_terms_report
get_top_keywords_creatives
import_offline_conversions
list_gaql_resources
remove_negative_keywords
run_gaql
update_ad_group_bid
update_ad_status
update_campaign_bidding
update_campaign_budget
update_campaign_status
update_conversion_action
update_rsa
upload_customer_match_list
validate_gaql
```

OR regenerar dinamicamente via shell:

```bash
grep -l "^# bucket: defer" src/mcp/tools/*.py | \
  xargs -I {} basename {} .py | sort
```

### Step 3.4 — Adicionar beta header ao MCP server connection

Edit `~/.claude/settings.json` pra incluir `anthropic-beta` header na conexão MCP V4 (necessário pra Tool Search Tool / advanced-tool-use feature). NB: V4 Ads MCP usa Streamable HTTP em produção via `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/mcp`. Se servidor está configurado em `.mcp.json` (project-level) ao invés de user `settings.json`, edit `.mcp.json` em vez disso.

**Snippet pra adicionar (exact schema TBD — best-guess baseado em D2 research):**

```json
{
  "mcp": {
    "servers": {
      "v4-ads": {
        "type": "streamable-http",
        "url": "https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/mcp",
        "headers": {
          "Authorization": "Bearer <existing_token>",
          "anthropic-beta": "advanced-tool-use-2025-11-20"
        }
      }
    }
  }
}
```

**NB importante:** `anthropic-beta` header pode precisar ser passado em outro layer (Claude Code → Anthropic API call, não MCP server → Claude Code). Verificar com `claude config` OR docs Anthropic em https://docs.anthropic.com/en/docs/build-with-claude/tool-use/advanced-tool-use após release notes Claude Code Tool Search support. Se Claude Code abstrai isso transparente (passa beta automaticamente quando vê tools com `defer_loading` config), pular este step.

### Step 3.5 — Adicionar bloco `defer_loading` per-tool

Edit `~/.claude/settings.json` — adicionar bloco `tools` listando os 38 defer tools com `defer_loading: true`:

```json
{
  "mcp": {
    "servers": { "v4-ads": { ... } }
  },
  "tools": [
    {"name": "mcp__v4-ads__add_keywords", "defer_loading": true},
    {"name": "mcp__v4-ads__add_negatives_from_search_terms", "defer_loading": true},
    {"name": "mcp__v4-ads__apply_change", "defer_loading": true},
    {"name": "mcp__v4-ads__apply_recommendation", "defer_loading": true},
    {"name": "mcp__v4-ads__audit_orphan_smart_actions", "defer_loading": true},
    {"name": "mcp__v4-ads__create_ad_group", "defer_loading": true},
    {"name": "mcp__v4-ads__create_conversion_value_rule_set", "defer_loading": true},
    {"name": "mcp__v4-ads__create_rsa", "defer_loading": true},
    {"name": "mcp__v4-ads__dismiss_recommendation", "defer_loading": true},
    {"name": "mcp__v4-ads__get_account_overview", "defer_loading": true},
    {"name": "mcp__v4-ads__get_ad_group_performance", "defer_loading": true},
    {"name": "mcp__v4-ads__get_ad_performance", "defer_loading": true},
    {"name": "mcp__v4-ads__get_audience_performance", "defer_loading": true},
    {"name": "mcp__v4-ads__get_budget_pacing", "defer_loading": true},
    {"name": "mcp__v4-ads__get_campaign_performance", "defer_loading": true},
    {"name": "mcp__v4-ads__get_device_performance", "defer_loading": true},
    {"name": "mcp__v4-ads__get_funnel_metrics", "defer_loading": true},
    {"name": "mcp__v4-ads__get_geo_performance", "defer_loading": true},
    {"name": "mcp__v4-ads__get_hourly_performance", "defer_loading": true},
    {"name": "mcp__v4-ads__get_keyword_performance", "defer_loading": true},
    {"name": "mcp__v4-ads__get_my_audit_log", "defer_loading": true},
    {"name": "mcp__v4-ads__get_my_rate_limit_status", "defer_loading": true},
    {"name": "mcp__v4-ads__get_negative_keywords_audit", "defer_loading": true},
    {"name": "mcp__v4-ads__get_search_terms_report", "defer_loading": true},
    {"name": "mcp__v4-ads__get_top_keywords_creatives", "defer_loading": true},
    {"name": "mcp__v4-ads__import_offline_conversions", "defer_loading": true},
    {"name": "mcp__v4-ads__list_gaql_resources", "defer_loading": true},
    {"name": "mcp__v4-ads__remove_negative_keywords", "defer_loading": true},
    {"name": "mcp__v4-ads__run_gaql", "defer_loading": true},
    {"name": "mcp__v4-ads__update_ad_group_bid", "defer_loading": true},
    {"name": "mcp__v4-ads__update_ad_status", "defer_loading": true},
    {"name": "mcp__v4-ads__update_campaign_bidding", "defer_loading": true},
    {"name": "mcp__v4-ads__update_campaign_budget", "defer_loading": true},
    {"name": "mcp__v4-ads__update_campaign_status", "defer_loading": true},
    {"name": "mcp__v4-ads__update_conversion_action", "defer_loading": true},
    {"name": "mcp__v4-ads__update_rsa", "defer_loading": true},
    {"name": "mcp__v4-ads__upload_customer_match_list", "defer_loading": true},
    {"name": "mcp__v4-ads__validate_gaql", "defer_loading": true}
  ]
}
```

**Open question:** Schema exato `tools[].name` (`mcp__v4-ads__<tool>` MCP namespacing prefix vs `v4-ads.<tool>` shorthand) TBD pendendo Claude Code release notes oficial sobre Tool Search Tool client support. Best-guess acima usa `mcp__<server>__<tool>` namespacing (mesma convention que Claude Code já usa pra invocar MCP tools internamente). **Verificar com Anthropic docs pós-Claude Code Tool Search release:**
- https://docs.anthropic.com/en/docs/claude-code/mcp
- https://docs.anthropic.com/en/docs/build-with-claude/tool-use/advanced-tool-use

Se Claude Code release notes especificar schema diferente, atualizar este runbook + Wellington reedit settings.json.

### Step 3.6 — Validar JSON sintaxe pós-edit

```powershell
# Verifica JSON valid antes de restart Claude Code
Get-Content $userSettings | ConvertFrom-Json | Out-Null
if ($?) { Write-Host "settings.json JSON OK" -ForegroundColor Green }
else { Write-Host "settings.json JSON BROKEN — restore .bak" -ForegroundColor Red }
```

Se JSON broken: `Copy-Item "$userSettings.bak-pre-3b39" $userSettings` + re-edit.

### Step 3.7 — Restart Claude Code

Quit Claude Code completamente (close all sessions). Reabrir.

```powershell
# Verifica processo terminou
Get-Process | Where-Object {$_.ProcessName -like "*claude*"}
```

### Step 3.8 — Verificar config aplicada via Claude Code MCP inspector

Em sessão fresh Claude Code:
- Slash command `/mcp` lista MCP servers conectados → confirmar `v4-ads` listed
- Tool list inspection: confirmar 21 tools immediately loaded em context (CORE) + 38 tools available via Tool Search (DEFER)
- Token usage tools descriptions reduzido ~66% (proxy: contexto Claude reporta menos tokens em tool defs)

### Validação T3:

- [ ] `~/.claude/settings.json` localizado em `C:\Users\welli\.claude\settings.json`
- [ ] Backup `.bak-pre-3b39` criado
- [ ] Bloco `tools` adicionado com 38 entries defer_loading=true
- [ ] JSON sintaxe valid pós-edit (ConvertFrom-Json passa)
- [ ] Claude Code restart completo (sem processos residuais)
- [ ] `/mcp` slash command mostra `v4-ads` connected
- [ ] Tool list inspection confirma always-loaded count razoável (~21)
- [ ] Wellington completou steps 3.1-3.8 sem erro

**Fallback se Claude Code config schema diferir do best-guess:**
- Documentar schema real descoberto em comentário no settings.json
- Atualizar este runbook + commit fix em Sprint 3b.39.1 followup
- Wellington reedit settings.json com schema correto
- T3 ainda PASS se config aplicada (independente do schema exato)

**Result:** ⬜ pending

---

## Test T4 — Regression always-loaded tool funciona idêntico

**Setup:** Validar que tools always-loaded (bucket="always" / [CORE] prefix) continuam funcionais idêntico pré-refactor. `list_my_accounts` é entry point natural (top Pareto, sem args, retorna 25 contas V4 MCC).

**Tool call (em sessão Claude Code pós-T3 restart):**

> "Lista as minhas contas Google Ads"

**Expected behavior:**

- Claude reconhece intent → invoca `mcp__v4-ads__list_my_accounts` (sem args)
- Tool retorna lista de 25 child accounts MCC `6436352492` V4 Maceió:
  - `customer_id` (10 digits sem traços)
  - `name`, `currency_code`, `time_zone`, `is_test_account`
- Audit_log +1 entry com `operation: list_my_accounts`
- Rate_counter +1
- Response time comparable pré-refactor (≤2s)

**Validação:**

- [ ] Tool `list_my_accounts` é invocada sem precisar nomeá-la explicitamente (always-loaded = Claude descobre)
- [ ] Response shape idêntico pré-refactor (mesmos campos, mesmos types)
- [ ] Count contas == 25 (V4 MCC baseline)
- [ ] Sem erros descrição parse OR schema validation
- [ ] Audit_log +1 entry
- [ ] Rate_counter +1

**Crítico — NÃO regression behavior:**
- Description `[CORE]` prefix presente mas NÃO confunde Claude (prefix é tag pra Wellington config, transparent pra Claude inference)
- `_meta.com.v4company/bucket: "always"` presente mas NÃO altera handler logic
- Tool handler 100% unchanged pré-3b.39

**Result:** ⬜ pending

---

## Test T5 — Defer tool invocação by-name funciona

**Setup:** Validar que defer-loading tools (38 com `[DEFER]` prefix) continuam **invocáveis quando explicitly named pelo gestor**. Defer != disabled — apenas removida do context default pra economia de tokens. Claude Code Tool Search Tool deve resolver by-name OR via semantic search.

**Tool call (em sessão Claude Code pós-T3 restart):**

> "Roda audit_zombie_keywords na conta 7862230676 com LAST_30_DAYS"

OR (forma mais explicit):

> "Use o tool mcp__v4-ads__audit_zombie_keywords com customer_id 7862230676 e date_range LAST_30_DAYS"

**Expected behavior:**

- Claude Code Tool Search resolve `audit_zombie_keywords` (via name OR semantic) mesmo sendo defer
- Tool é carregada on-demand pro context Claude
- Invocação ocorre normalmente
- Response shape idêntico pré-refactor:
  - `customer_id`, `date_range_resolved`, `filters_applied`
  - `total_zombies`, `truncated`, `returned_count`, `zombies[]`
- MO-JP `7862230676` esperado retornar ~280 zombies em LAST_30_DAYS (dogfood 2026-05-25 baseline)
- Audit_log +1 entry com `operation: audit_zombie_keywords`

**Validação:**

- [ ] Tool `audit_zombie_keywords` é encontrada via name search (defer ≠ desaparecido)
- [ ] Tool é loaded on-demand pro context (Claude Code Tool Search behavior)
- [ ] Response shape válido (matches pré-refactor T1 baseline 3b.36)
- [ ] `total_zombies` ~280 (MO-JP cleanup massivo dogfood baseline — pode ter variado pós-cleanup)
- [ ] Audit_log +1 entry
- [ ] Rate_counter +1

**Fallback se Claude Code não resolve defer tool by-name:**
- Verificar `defer_loading` config aplicada corretamente (T3 Step 3.8)
- Tentar variantes naming: `audit_zombie_keywords`, `mcp__v4-ads__audit_zombie_keywords`, `v4-ads.audit_zombie_keywords`
- Se nenhum funciona: Claude Code release notes specifying invocation pattern needed — T5 DEFERRED + escalation
- Workaround temporário: Wellington remove tool específico do defer list pra trazer pra always-loaded

**Result:** ⬜ pending

---

## Test T6 — Wellington 7d feedback collection template

**Setup:** F1 gate é outcome-based timeout 14d (spec §5.5). 7 dias post-deploy = primeiro touchpoint Wellington structured feedback. Template GitHub issue dedicado pra audit trail + decision context (continue F2 OR abort/revert).

**GitHub issue template (criar 7d post-deploy):**

**Title:** `Sprint 3b.39 — Wellington 7-day feedback (F1 → F2 decision)`

**Body:**

```markdown
## Wellington 7-day feedback Sprint 3b.39

**Data ship:** 2026-MM-DD
**Data feedback:** 2026-MM-DD (+7d)
**Sessions Claude Code rodadas neste período:** ~N (estimar)

### 1. Responsiveness Claude

Escala 1-5 (1=muito pior, 3=igual, 5=muito melhor):

- **Nota:** [1/2/3/4/5]
- **Notas:** Comparação subjetiva tempo response Claude vs pré-3b.39. Foco em first-token latency + tool inference accuracy. Esperado: melhora marginal pq tool descriptions menor → menos tokens → Claude foca mais.

### 2. Tool discovery — sentiu falta de tool nos 7 dias?

- **Yes/No**
- **Se Yes — listar tools "não encontrei":**
  - [ ] tool_name_1 — contexto da query
  - [ ] tool_name_2 — contexto da query

> **CRÍTICO:** se >2 tools "não encontrei" → trigger abort F1 (revert path: mass-set `bucket="always"`).

### 3. Defer tools encontradas — invocou alguma via name explicit?

- **Yes/No**
- **Quais defer tools invocadas:**
  - [ ] tool_name_1 — workflow context
  - [ ] tool_name_2 — workflow context
- **Foi fácil OR teve fricção?** [livre]

### 4. Funcionalidade perdida totalmente?

Algo que sentiu falta sem alternativa via outra tool? (livre)

### 5. Decision F1 → F2

- [ ] **CONTINUE F2** (avançar pra Sprint 3b.40 Caminho C consolidação)
- [ ] **PAUSE** (manter F1 ativa mais N dias, re-evaluate)
- [ ] **REVERT** (rollback F1 — mass-set `bucket="always"` em todos tools)

**Justificativa decision:** [livre, 1-2 frases]
```

**Validação T6:**

- [ ] GitHub issue criada com template acima (issue # registrado em sprint-history.md)
- [ ] Wellington committed a respond em 7d post-deploy
- [ ] Decision documentada (CONTINUE / PAUSE / REVERT)

**Result:** ⬜ pending (data collection ongoing, response esperada 7d post-deploy)

---

## Decision gate F1 → F2

Aplicar **14 dias post-deploy** (timeout default conforme spec §5.5).

### Auto (smoke + monitoring)

- [ ] Smoke 6/6 PASS este runbook (T1-T6 todas PASS)
- [ ] `/health` 200 sustained last 7d (uptime cron OR manual check)
- [ ] CI green last 7d (zero red builds consecutivos)
- [ ] Tool count 59 confirmado em produção (sem mudança — F1 metadata-only)

### Wellington feedback (T6 GitHub issue)

- [ ] Responsiveness ≥4/5
- [ ] Zero "tool desaparecida" reports OR ≤2 tools "não encontrei"
- [ ] Decision "CONTINUE F2"

### Outcome paths

**Se ALL ✅ (auto + Wellington positivo):**
→ proceed to **Fase 2 Sprint 3b.40** (Caminho C consolidação — `get_performance_breakdown(level, dimension)` substitui 9 reports performance redundantes = -9 tools permanente)

**Se ANY 🚨 abort trigger:**
- 🚨 >2 tools "não encontrei" em 7d (Wellington feedback)
- 🚨 Smoke regression em tool always-loaded (T4 FAIL)
- 🚨 CI vermelho 2× consecutivos em 7d
- 🚨 `/health` ≠ 200 sustained
- 🚨 Wellington decision "REVERT"

→ Execute **revert path** abaixo + Wellington re-evaluate spec §5

### Revert path (1-line PR)

Mass-set `bucket="always"` em todos 59 tools. Voltar Wellington `~/.claude/settings.json` restaurando backup `.bak-pre-3b39`.

```bash
# Server-side revert (1 commit)
# Edit src/mcp/tools/_registry.py: change default kwarg pra always
# OR find/replace em src/mcp/tools/*.py: bucket="defer" → bucket="always"

git add src/mcp/tools/*.py
git commit -m "revert(buckets): F1 abort — mass-set bucket='always' em todos tools

Sprint 3b.39 F1 → F2 gate aborted. Wellington feedback negativo:
- [reason 1]
- [reason 2]

Reverting pra pre-3b.39 behavior: todas tools always-loaded.
Description prefix tags + _meta field preservados (informational only).

Next: re-evaluate spec arch refactor §5 — Wellington + Anthropic
docs sync, possivelmente waiting Claude Code Tool Search GA release."

git push origin main
```

**Wellington side:**

```powershell
# Restore pre-3b.39 settings.json
$userSettings = Join-Path $env:USERPROFILE ".claude\settings.json"
Copy-Item "$userSettings.bak-pre-3b39" $userSettings

# Restart Claude Code
```

---

## V4 invariants validation

| Invariant | Aplicável | Enforcement | How smoke verifies |
|---|---|---|---|
| country_code = BR | N/A | N/A — tool metadata refactor não toca geo data | — |
| language_code = pt-BR | ✅ Description prefixes | `[CORE]`/`[DEFER]` prepend mantém description PT-BR original (Sprint 3b.* convention) | T2 valida descriptions começam com prefix mas mantêm conteúdo PT-BR |
| currency_code = BRL | N/A | N/A — tool refactor não toca cost reporting | — |
| timezone = -03:00 | N/A | N/A — tool refactor não toca timestamps | — |
| LGPD consent | N/A | Server-side metadata only — sem PII | — |
| Schema whitelist (3b.19A) | N/A | Sem mudança de input_schema em nenhuma das 59 tools — F1 metadata-only | Regression T4/T5 validam handler invocação idêntica |
| No composition keywords (3b.19B.1) | ✅ Regression | Schemas unchanged — `test_no_composition_keywords_in_any_schema` continua passando | Pre-push gate |
| F46 imune | N/A | F1 sem mudança em GAQL queries | — |
| Bucket consistency cross-mechanism | ✅ NEW Sprint 3b.39 | (1) `# bucket:` comment, (2) `bucket="..."` kwarg, (3) `[CORE]/[DEFER]` description prefix, (4) `_meta.com.v4company/bucket` field deveriam alinhar | T1 + T2 cross-validate; known gap em 1 tool (`meta_list_my_ad_accounts`) documented |
| Tool count estável | ✅ F1 contract | 59 tools registered (sem add/remove em F1) — archive vem F3 | T1 valida tool file count == 59 |
| Server `list_tools()` retorna todas 59 | ✅ F1 contract | F1 NÃO modifica list_tools comportamento — Claude Code client-side filtra via defer_loading config | T2 valida `len(_TOOLS) == 59` |

---

## Cleanup post-smoke

Não há cleanup destrutivo necessário:
- F1 é metadata-only — sem mudança DB, sem mudança schema, sem mudança runtime behavior
- Audit_log entries de T4/T5 ficam permanentes (rastreio histórico)
- Rate_counter incrementa normalmente: ~2-3 calls em T4/T5 + zero em T1/T2/T3/T6

Wellington settings.json modification é reversible via `.bak-pre-3b39` backup (T3 Step 3.2).

---

## Notas pra Wellington pós-smoke

1. **F1 success metric primário:** Wellington responsiveness perception em 7d. Auto-tests (T1/T2) validam apenas mecânica server-side; valor real está em UX Claude Code (T4/T5/T6).
2. **Tool Search Tool client schema TBD:** Claude Code release notes oficial sobre Tool Search Tool support determinam schema exato `tools[].defer_loading` em `~/.claude/settings.json`. Best-guess deste runbook (`mcp__v4-ads__<tool>` namespacing) baseado em convenção existente Claude Code pra MCP tool naming. Pós-release: atualizar este runbook + commit fix Sprint 3b.39.1 followup.
3. **Known inconsistency (cleanup candidate):** `meta_list_my_ad_accounts` tem [CORE] description prefix MAS `bucket="defer"` default no registry (falta kwarg explicit). Cross-check T1 detecta. Fix simples: add `bucket="always"` ao `@register_tool` call. Não bloqueia F1: description prefix é primary signal pra Wellington config.
4. **Re-classification mensal:** spec §9.3 SQL query roda mensalmente pra promover tools movendo entre buckets (cold 1-4 → core ≥10 → always). Próxima execução: 2026-06-25. Resultados em novo `docs/operacao/tool-buckets-YYYY-MM-DD.md` doc.
5. **Decision gate F1 → F2 timeout 14d:** se Wellington feedback T6 não vier em 7d, default = pause (manter F1 ativa). Se 14d sem decisão, default = CONTINUE F2 (assume silence = no issues). Spec §5.5.
6. **Revert path testado mentalmente:** mass-set `bucket="always"` em 59 tools + restore Wellington settings.json backup. ~5 min execution. Sem risco data loss (F1 metadata-only).
7. **F2 next preview (Sprint 3b.40):** Caminho C consolidação 9 reports → 1 `get_performance_breakdown(level, dimension)`. -9 tools permanente. Spec §6. Pre-requisito: F1 gate PASS.
8. **D2 finding documentado:** OQ1 research descobriu MCP defer_loading é client-side Anthropic API parameter — F1 pivoted pra server-metadata-only design. Lição reinforced: research API features cross-layer (client vs server) ANTES de implementation. findings-catalog.md entry D2.
9. **Skills V4 V4 Ads Google em `.claude/skills/`** referenciam tools por nome — se uma tool fica defer + Skill invoca by-name, deve funcionar (defer ≠ disabled, T5 cobre). Se Skills tem problemas: tracked em out-of-MCP-scope Wellington manual paralelo (spec §10 R6).
10. **Sprint 3b.39 tool count:** 59 → **59** (sem mudança — F1 metadata-only). Próximo F2 reduz pra ~50 (consolidação 9 reports). Próximo F3 reduz pra ~35-40 (archive zombies). Estado final esperado spec §14.
