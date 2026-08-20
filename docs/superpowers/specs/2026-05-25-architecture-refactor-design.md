# V4 Ads MCP — Architecture Refactor Design

**Data:** 2026-05-25
**Sprint range:** 3b.39 → 3b.41 + M.3+ ongoing
**Duração estimada:** ~7 semanas concentrated + ongoing
**Owner:** Wellington Ribeiro (wellinton.ribeiro@v4company.com)
**Status:** Design (brainstorming approved, pending writing-plans)

---

## 1. Context & Motivation

V4 Ads MCP atingiu 59 tools (57 Google + 2 Meta) em Maio 2026. Tool audit completa em 2026-05-25 (tool-audit-2026-05-25.md) + research arquitetural ([Agent #2 report](#11-referências)) revelaram 3 problemas estruturais:

### P1 — Tool count 3× acima do "20-tool cliff" documentado

Research empírica converge: AWS Heroes Pet Store benchmark (10→perfect, 20→19/20, 107→fail completo), GitHub Copilot (40→13 = +2-5pp accuracy + -400ms latency), Block Engineering (Linear MCP rebuild 3× pra ir 30+→2 tools), LongFuncEval paper (7-85% accuracy drop com growth). Anthropic recomenda **3-5 tools always-loaded, defer rest** via Tool Search + threshold alert >10K tokens em tool defs ([advanced-tool-use](https://www.anthropic.com/engineering/advanced-tool-use)).

V4 atual: ~25-30K tokens em descriptions Google+Meta+governance, projetado pra ~50K em M.25 (102 tools). Wellington usa simultaneamente 4+ MCP servers (v4-ads + supabase + empsis + n8n) = >150 tools expostas em 1 session Claude.

### P2 — 22 zombies (38%) sem uso 30d + 13 reports redundantes

Tool audit 2026-05-25 identificou Pareto 80/20:
- 8 core tools = 60% volume
- 22 zombies = 0 uses 30d
- 13 reports performance consolidáveis em 1-2 generic tools via `get_performance_breakdown(level, dimension, date_range)`

Sweet spot recomendado: **30-45 tools** (vs 102 projetado M.25 — 4× industry average).

### P3 — Roadmap M.3-M.25 sem revisão pós-rejeição Meta Full Access

[D1 finding 2026-05-25](../../operacao/findings-catalog.md): Meta App Review rejeitou Full Access (critério literal Meta: ≥500 calls/15d + <15% error rate). Decisão Caminho B+ janela observação 30-45 dias — acelerar M.3+ pra ship mais tools Meta pra volume natural orgânico.

Mas spec M.3-M.25 original assume **paridade quase total** (~45 tools Meta espelhando Google). Tool audit já provou Pareto cumpre em Google — Meta provavelmente vai espelhar. **Top 10-15 Meta tools cobrem 80% dos use cases V4.** Não precisa 45.

---

## 2. Princípios arquiteturais (invariantes)

Estes invariantes são preservados em todas as fases do refactor:

1. **Layering atual mantido** — thin wrapper (`src/mcp/tools/*.py`) + pure modules (`src/google_ads/`, `src/meta_ads/`) + shared governance (`src/governance/`). Já bem feito, não mexer.
2. **Google + Meta separados** — sem unificar abstraction (industry pattern Supermetrics/Improvado). Schema explosion + loss of clarity OK pra refactor futuro se evidência empírica surge, não agora.
3. **Skills V4 em `.claude/skills/`** — não migrar pro MCP. LlamaIndex pattern: Skills wrap MCP primitives, não substituir.
4. **Governance per-call mantido** — audit_log, rate_limit, blast_radius continuam idênticos. Refactor é sobre TOOL EXPOSURE, não governance.
5. **Reversibilidade** — toda decisão tem rollback path:
   - Tombstone reversible (1-line uncomment)
   - `defer_loading=true` toggleable per-tool
   - Generic schema preserva tools antigas 14d como fallback

---

## 3. Arquitetura final — 3 buckets de tools

Tools são classificadas em 3 buckets data-driven (re-avaliados mensal via audit_log query):

### Bucket A — Always-loaded (sempre em context Claude)

**Critério:** ≥5 uses/30d (core + warm) OR exceções semânticas justificadas.

**Count estimado:** ~18 tools.

**Tools core (≥10 uses) atuais (8):**
- `create_and_link_assets` (33 uses)
- `get_change_history` (29)
- `create_campaign` (22)
- `add_negative_keywords` (17)
- `audit_competitor_keywords` (16)
- `create_conversion_action` (16)
- `list_my_accounts` (14)
- `update_keyword_status` (10)

**Tools warm (5-9 uses) atuais (~10):**
- `get_conversion_actions` (9)
- `create_conversion_value_rule_set` (8)
- Outras 8 a serem identificadas via query refresh

**Exceções semânticas always-loaded:**
- `detect_drift` — recém-shipped Sprint 3b.33, 60d grace period
- `meta_list_my_ad_accounts` — cache esporádico esperado, importante pra OAuth discovery
- `meta_get_account_overview` — entry point Meta, must be discoverable

### Bucket B — Defer-loading (carrega sob demanda via Tool Search)

**Critério:** 1-4 uses/30d (cold) OR zombies que NÃO entram em archive (valor sazonal).

**Count estimado:** ~18-22 tools.

**Padrões esperados:**
- Audits especializados (`audit_zombie_keywords`, `audit_goal_attribution`, `audit_orphan_smart_actions`, `audit_quality_score`)
- Reports detalhados (após Fase 2 consolidação, alguns viram tombstone; outros como `get_funnel_metrics`, `get_budget_pacing` ficam defer)
- Setup tools (`upload_customer_match_list` — 1×/cliente)
- Power-user (`run_gaql`, `validate_gaql`, `list_gaql_resources`)
- Mutations de baixa frequência (`update_conversion_action`, `update_rsa`, `update_campaign_budget`)

### Bucket C — Tombstone (handler retorna error PT-BR)

**Critério:** 0 uses 30d + sem valor sazonal claro + substituível por outra tool OR UI Google Ads.

**Count estimado:** 15-18 tools.

**Candidates óbvios:**
- `apply_recommendation`, `dismiss_recommendation` (UI Google Ads cobre)
- `update_campaign_bidding` (merge-able com bid family)
- 9 reports consolidados em `get_performance_breakdown` (Fase 2)
- Outras zombies confirmadas após análise pós-F2

**Exceções (NÃO tombstone, mantém defer-loading):**
- `upload_customer_match_list` (setup 1×/cliente, valor sazonal alto)
- `detect_drift` (60d grace, recém-shipped)

---

## 4. Tombstone policy detalhada

Quando uma tool é movida pra Bucket C (Tombstone):

### 4.1 Tombstone implementation pattern

```python
# Pattern: src/mcp/tools/<archived_tool>.py (post-archive)
@register_tool(
    name="<tool_name>",
    description="[ARCHIVED Sprint 3b.NN] Use '<alternative_tool>' em vez disso.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
)
async def <tool_name>(args: dict) -> dict:
    return {
        "error": "TOOL_ARCHIVED",
        "message_pt": (
            "Tool '<tool_name>' foi arquivada em Sprint 3b.NN (motivo curto). "
            "Use '<alternative_tool>(<params_hint>)' em vez disso."
        ),
        "archived_in_sprint": "3b.NN",
        "archived_date": "YYYY-MM-DD",
        "use_instead": "<alternative_tool>",
        "migration_hint": "<short PT-BR explanation>",
    }
```

### 4.2 Tombstone lifecycle

1. **T+0 (ship):** Tool tombstoned. Description + handler retornam error PT-BR.
2. **T+14d:** Watch period. Audit_log monitorado pra retry attempts (SQL: `SELECT operation, COUNT(*) FROM audit_log WHERE operation = '<tool_name>' AND created_at > NOW() - INTERVAL '14 days'`).
3. **T+90d:** Hard delete via `git rm <file>` (git history preservada). Cleanup commit em Sprint regular.
4. **Se retry detectado em 14d:** Investigar — pode ser caso edge não-coberto pela alternative. Considera un-archive OR extensão da alternative.

### 4.3 Atualização cross-cutting

Cada tombstone tool requer atualização em:
- `findings-catalog.md` — entry em nova "Bug class 8: Architectural deprecations"
- `sprint-history.md` — sprint row updated com lista de tools tombstoned
- Skills V4 em `.claude/skills/` que referenciam tool por nome (out-of-MCP scope, Wellington manual paralelo)

---

## 5. Fase 1 — Tool Search defer_loading (Sprint 3b.39)

### 5.1 Objetivo

Reduzir 85% token usage em tool descriptions sem cortar tools (Anthropic empirical benchmark: 191K vs 122K em test).

### 5.2 Duração estimada

~3-5 dias dev (Wellington single-handed via subagent-driven).

### 5.3 Scope

**Mudanças código:**
- Adicionar parametro `defer_loading: bool = False` no `@register_tool` decorator em `src/mcp/tools/_registry.py`
- Implementar Tool Search adapter em `src/mcp/_tool_search_adapter.py` — wraps Anthropic API contract (research OQ1: confirm se MCP server ou Claude Code client owns essa lógica)
- Modificar `src/mcp/server.py` `list_tools()` — retorna apenas tools com `defer_loading=False`
- Implementar `tools/list_archived` MCP endpoint (read-only discovery pra Wellington investigation)
- Adicionar tag classification em cada tool file (`# bucket: always | defer | tombstone`) pra grepability

**Classificação inicial (data-driven via audit_log query):**
```sql
SELECT operation, COUNT(*) as uses_30d
FROM audit_log
WHERE created_at > NOW() - INTERVAL '30 days'
  AND status NOT IN ('error', 'cancelled')
GROUP BY operation
ORDER BY uses_30d DESC;
```

Bucket assignment:
- `uses_30d >= 5` → `defer_loading=False` (always)
- `uses_30d 1-4` → `defer_loading=True` (cold)
- `uses_30d == 0` → `defer_loading=True` (preparação pra F3 tombstone decision)
- Overrides semânticos manuais (detect_drift, meta_list_my_ad_accounts, etc) hardcoded em lista.

### 5.4 Deliverables

1. Código + tests passing (5/5 PASS pre-push gate)
2. Smoke runbook `docs/operacao/phase-3b-39-bootstrap.md` cobrindo:
   - T1: list_tools retorna apenas always-loaded count
   - T2: defer tool invocável por nome explicit (`mcp__v4-ads__<defer_tool>`)
   - T3: Tool Search com query semantic retorna defer tools matching
   - T4: archived list endpoint retorna tombstone candidates
   - T5: regression — todas tools always-loaded funcionam idêntico pre-refactor
5. Sprint-history + findings-catalog updated
6. CLAUDE.md §Pending updated removendo Fase 1 da lista

### 5.5 Gate saída Fase 1 → Fase 2

**Outcome-based com timeout 14d.**

Avançar pra F2 se:
- ✅ Smoke 5/5 PASS (auto)
- ✅ /health 200 + CI verde (auto)
- ✅ Wellington feedback 7d positivo: responsiveness ≥4/5, tools encontradas yes, zero "funcionalidade faltando"
- ⏱️ Timeout 14d default

Abort/revert se:
- 🚨 Wellington reporta >2 tools "não encontrei" em 7d
- 🚨 Smoke regression em tool always-loaded
- 🚨 CI vermelho 2× consecutivos

**Revert path:** mass-set `defer_loading=False` em todas tools (1-line PR), volta estado pré-F1 sem perder funcionalidade.

---

## 6. Fase 2 — Caminho C consolidação reports (Sprint 3b.40)

### 6.1 Objetivo

-9 tools permanente sem perder funcionalidade. Substituir 9 reports performance redundantes por 1 generic `get_performance_breakdown` com parametrização orthogonal.

### 6.2 Duração estimada

~5-7 dias dev.

### 6.3 Scope

**Novo tool:**

```python
# src/mcp/tools/get_performance_breakdown.py
@register_tool(
    name="get_performance_breakdown",
    description=(
        "Generic performance breakdown — substitui 9 reports especializados. "
        "level (required): account|campaign|ad_group|ad|keyword|audience. "
        "dimension (optional): null|device|geo|hour pra breakdown adicional. "
        "Filters opcionais: campaign_ids[], ad_group_ids[]. Date window via "
        "preset OR custom dates. Sempre auditado."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
            "level": {
                "type": "string",
                "enum": ["account", "campaign", "ad_group", "ad", "keyword", "audience"],
                "description": "Granularidade primária (required).",
            },
            "dimension": {
                "type": "string",
                "enum": ["device", "geo", "hour"],
                "description": "Breakdown secundário (optional). Default null = no breakdown.",
            },
            "campaign_ids": {
                "type": "array",
                "items": {"type": "string", "pattern": "^[0-9]+$"},
                "maxItems": 50,
            },
            "ad_group_ids": {
                "type": "array",
                "items": {"type": "string", "pattern": "^[0-9]+$"},
                "maxItems": 100,
            },
            "date_range": {
                "type": "string",
                "enum": ["TODAY", "YESTERDAY", "LAST_7_DAYS", "LAST_14_DAYS",
                         "LAST_30_DAYS", "LAST_90_DAYS"],
                "default": "LAST_7_DAYS",
            },
            "start_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
            "end_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 100},
        },
        "required": ["customer_id", "level"],
        "additionalProperties": False,
    },
)
```

**Pure module:** `src/google_ads/performance_breakdown.py`
- `build_performance_breakdown_query(level, dimension, filters, date_range) -> str`
- `parse_performance_row(row, level, dimension) -> dict`
- `_validate_combo(level, dimension) -> str | None` — algumas combinações inválidas (ex: `level=ad + dimension=hour` pode não fazer sentido)
- Builder pattern: 1 método por level (`_build_for_campaign`, `_build_for_ad_group`, etc), dimension adiciona `segments.device` / `segments.geo_target_constant` / `segments.hour` ao SELECT

**Tools tombstoned (9 — todos tombstone após F2 ship, hard delete em F3 ou T+90d):**
- `get_account_overview`
- `get_campaign_performance`
- `get_ad_group_performance`
- `get_ad_performance`
- `get_keyword_performance`
- `get_audience_performance`
- `get_device_performance`
- `get_geo_performance`
- `get_hourly_performance`

**NÃO tombstoned em F2 (mantém defer-loading bucket):**
- `get_funnel_metrics` (cobertura específica — funnel-shape distinct vs flat breakdown)
- `get_budget_pacing` (cobertura específica — calendar-aware pacing distinct)
- `get_search_terms_report` (cobertura específica — search terms ≠ performance metric)

### 6.4 Deliverables

1. Código + tests:
   - `tests/unit/test_performance_breakdown.py` — `_validate_combo` + parser + builder per level/dimension
   - `tests/integration/test_get_performance_breakdown.py` — wire-up + happy paths
2. Smoke runbook `docs/operacao/phase-3b-40-bootstrap.md` cobrindo TODAS combinações level × dimension válidas (~15-20 combos) em conta real Wellington (MO-JP+CAB ou ML Antiguidades)
3. 9 tools tombstoned mas registered (compatibilidade 14d fallback)
4. findings-catalog + sprint-history updated
5. Update tool-audit-2026-05-25.md com new count

### 6.5 Gate saída Fase 2 → Fase 3

**Outcome-based com timeout 21d.**

Avançar pra F3 se:
- ✅ Smoke real 8/8 PASS em conta Wellington (todas combinações level × dimension válidas testadas)
- ✅ Wellington dogfood ≥3 uses/semana de `get_performance_breakdown` nas 2 primeiras semanas
- ✅ Zero retry tentativas em audit_log das 9 tools tombstoned por 7d consecutivos
- ⏱️ Timeout 21d

Abort/pause se:
- 🚨 Schema rejeitado pelo Claude (composition keywords issue, etc) — revert + redesign
- 🚨 Dogfood baixo (<3 uses/semana) — investiga UX

**Revert path:** un-tombstone 9 tools (revert decorator + handler), `get_performance_breakdown` fica como adicional, não substituto.

---

## 7. Fase 3 — Archive zombies óbvios (Sprint 3b.41)

### 7.1 Objetivo

-6 a -8 tools adicional. Limpeza final dos zombies confirmados sem valor.

### 7.2 Duração estimada

~2-3 dias dev (operacional, sem código novo).

### 7.3 Scope

**Re-análise pós-F1+F2:**
- Query audit_log refresh (30d janela) — algumas zombies podem ter ganho uso após Tool Search expose elas
- Confirma list final de tombstone candidates

**Tombstone candidates iniciais (re-confirmar):**
- `apply_recommendation`
- `dismiss_recommendation`
- `update_campaign_bidding` (merge-able com bid family)
- Outras zombies 0 uses 60d (mais conservador que 30d pra F3)

**Excepções (mantém defer-loading):**
- `upload_customer_match_list` (setup 1×/cliente)
- `detect_drift` (60d grace, recém-shipped)
- Tools com valor sazonal claro identificado em audit

**Para cada tombstone:**
- Handler PT-BR error + use_instead hint
- Update findings-catalog entry
- Update sprint-history

### 7.4 Deliverables

1. ~6-8 tools tombstoned (handlers PT-BR error)
2. Smoke runbook minimalista (10/10 PASS validation — todos handlers retornam tombstone error corretamente)
3. findings-catalog Bug class 8 com lista completa
4. sprint-history 3b.41 row

### 7.5 Gate finalização Fase 3 → Fase 4

**Outcome-based com timeout 14d.**

Fase 3 considered done se:
- ✅ Zero retry tentativas em audit_log 14d post-tombstone
- ✅ Wellington feedback "nada faltou"
- ⏱️ Timeout 14d

Un-archive specific tool se:
- 🚨 Retry detectado em 14d (caso edge não-coberto pela alternative)

---

## 8. Fase 4 — Roadmap M.3-M.25 reformulado (M.3+ ongoing)

### 8.1 Objetivo

Meta family curado por demand pull (10-15 tools, não 45 paridade). Volume Meta cresce → atinge 500 calls/15d threshold → re-submit Full Access (Caminho B+).

### 8.2 Duração estimada

~3 meses ongoing (paralelo ao refactor Fases 1-3).

### 8.3 Scope

**Re-spec [`2026-05-24-meta-ads-incorporation-design.md`](2026-05-24-meta-ads-incorporation-design.md):**
- Remover roadmap M.3-M.25 atual (45 tools paridade)
- Substituir por **decision tree per-sprint:**

```
Para cada Meta tool candidate:
1. Há request claro dogfood/Wellington em <2 semanas? → ship (demand pull)
2. Cobertura Pareto top 10-15 esperada? → ship (proactive)
3. Apenas spec original/paridade sem evidência? → defer indefinitely (YAGNI)
```

**Top 10-15 Meta candidates prioritários (espelhando Pareto Google):**

| # | Sprint | Tool | Paridade Google | Justificativa |
|---|---|---|---|---|
| 1 | M.3 | `meta_get_campaign_performance` | `get_campaign_performance` (29 uses) | Top 2 Pareto Google esperado replicar em Meta |
| 2 | M.4 | `meta_get_ad_performance` | `get_ad_performance` | Drill-down crítico pós-campaign overview |
| 3 | M.5 | `meta_pause_ad_set` | `update_ad_group_status` | Mutate paralelo essencial pra cleanup ops |
| 4 | M.6 | `meta_audit_account_overview` | `audit_competitor_keywords` (16 uses) | Audit hero Pareto |
| 5 | M.7 | `meta_get_creative_performance` | `get_ad_performance` (creative-aware) | Cobertura ad set + creative |
| 6 | M.8 | `meta_update_ad_set_budget` | `update_campaign_budget` | Budget management cross-platform |
| 7-15 | M.9+ | TBD | TBD | Ship por demand pull confirmed dogfood ≥3 uses/semana |

**Tools NÃO ship em V0 (defer indefinitely):**
- `meta_create_ad_set` (complex; gestor V4 prefere UI Meta pra creation)
- `meta_create_campaign` (idem)
- `meta_create_ad` (idem)
- `meta_get_audience_performance` (Meta audience model diferente Google, requer dogfood evidence)
- ~30 outras tools que apareciam no spec original (45 → 15 = -67%)

### 8.4 Deliverables

1. Re-spec [`2026-05-24-meta-ads-incorporation-design.md`](2026-05-24-meta-ads-incorporation-design.md) — substituir M.3-M.25 detalhado por decision tree + top 10-15 prioritários
2. Per-sprint Meta: brainstorming + plan + ship + smoke conforme convention atual
3. Monitorar `meta_rate_counters` table — quando atinge ~500 calls cumulativas 15d, re-submit Full Access (Wellington manual fora-MCP)

### 8.5 Gate finalização Fase 4

**Não há F5 — termo do refactor arquitetural.**

Fase 4 success critérios:
- ✅ Tool count estável ~35-40 (vs 102 plano original)
- ✅ Meta Full Access re-submitted após 500 calls atingidas (~30-45 dias)
- ✅ Dogfood ≥3 uses/semana cross-platform sustentado
- 🔄 Re-avaliar tool audit em 2026-08-25 (3 meses pós-ship Fase 1)

---

## 9. Métricas de validação

### 9.1 Auto-mensuráveis (background, sem ação Wellington)

| Métrica | Source | Threshold | Frequência |
|---|---|---|---|
| Smoke tests | `python scripts/check_pre_push.py` + smoke real | 5/5 PASS | Per-ship |
| /health | `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health` | 200 OK | Post-deploy + daily |
| CI green | GitHub Actions | All checks pass | Per-commit |
| Tool count | `import_all_tools()` registry count | Trending down (59 → ~35-40) | Post-cada-fase |
| Audit_log tombstone retry | SQL query (ver 9.3) | 0 retries per tool 14d | Daily watch |
| Audit_log tool usage | SQL query (ver 9.3) | Re-classify monthly | Mensal |
| Meta rate counters | `meta_rate_counters` table | Trending up pra ≥500/15d | Daily Fase 4 |

### 9.2 Wellington feedback (5 perguntas estruturadas 7d após cada fase)

```
[Sprint 3b.NN Fase X — 7d post-ship feedback]

1. Responsiveness Claude melhorou/igual/piorou? (1-5 scale)
2. Tool que precisava — encontrou rápido? (yes/no + which se no)
3. Tombstone error PT-BR ajudou ou frustrou? (n/a se nenhum)
4. Alguma funcionalidade que sentiu falta? (open text)
5. Continuar próxima fase OR pause/revert? (decision)
```

Wellington responde via comentário em GitHub issue dedicado por fase (mantém audit trail + decision context).

### 9.3 SQL queries auxiliares

**Tool usage re-classify (mensal):**
```sql
SELECT operation, COUNT(*) AS uses_30d
FROM audit_log
WHERE created_at > NOW() - INTERVAL '30 days'
  AND status NOT IN ('error', 'cancelled')
GROUP BY operation
ORDER BY uses_30d DESC;
```

**Tombstone retry watch (daily):**
```sql
SELECT operation, COUNT(*) AS retry_count, MAX(created_at) AS last_retry
FROM audit_log
WHERE result LIKE '%TOOL_ARCHIVED%'
  AND created_at > NOW() - INTERVAL '14 days'
GROUP BY operation
ORDER BY retry_count DESC;
```

**Meta rate progress (daily Fase 4):**
```sql
SELECT date, SUM(operations_used) AS daily_calls,
       SUM(SUM(operations_used)) OVER (ORDER BY date) AS cumulative_15d
FROM meta_rate_counters
WHERE date > NOW() - INTERVAL '15 days'
GROUP BY date
ORDER BY date;
```

---

## 10. Riscos + mitigations

| # | Risco | Probabilidade | Impacto | Mitigation |
|---|---|---|---|---|
| **R1** | Tool Search `defer_loading` API Anthropic muda | Baixa | Alto | Feature relativamente nova — wrap em adapter `src/mcp/_tool_search_adapter.py`. Se Anthropic muda contract, fix 1 arquivo |
| **R2** | Wellington não encontra tool após defer_loading | Média | Alto | Tool Search via search/by-name funciona. F1 gate exige feedback negativo abort + revert 1-line |
| **R3** | `get_performance_breakdown` schema mais complex que tools especializados | Média | Médio | Schema com `_validate_combo` helper + clear error PT-BR. Tools tombstoned ficam 14d como fallback |
| **R4** | Audit_log query pra re-classify mensal vira manual chore | Baixa | Baixo | Considerar cron job MCP server roda 1×/mês + emite report markdown em `docs/operacao/tool-audit-YYYY-MM-DD.md` automaticamente (V1 candidate) |
| **R5** | Sprint 3b.39-3b.41 atrasados | Média | Médio | Roadmap M.3+ não-blocked por refactor (continua paralelo). Refactor pode esticar pra 6-8 semanas sem afetar Meta progress |
| **R6** | Tombstone errors confundem Claude em workflows V4 Skills | Baixa | Alto | Skills V4 em `.claude/skills/` apontam pra tools por nome — vão receber tombstone error com migration hint. Update Skills V4 em paralelo (out-of-MCP-scope, Wellington manual) |
| **R7** | Meta Full Access re-submission rejeita novamente | Média | Baixo | Caminho B+ já espera 30-45 dias gerar volume. Se 500 calls + <15% error rate atingidos = data-driven case forte. Worst case: aceitar Limited Access permanente (Caminho A fallback) |
| **R8** | Tool count atinge >40 again pós-Fase 4 ship M.3+ tools | Média | Médio | Re-avaliar 2026-08-25 audit. Considera Caminho C++ (2nd consolidation round) OR subagent split |

---

## 11. Open questions (não-decisões esta sessão)

| # | Question | Quando decidir |
|---|---|---|
| **OQ1** | Tool Search Anthropic feature requer Claude Code/Codex client cooperate? OR funciona transparent em MCP server? | Fase 1 implementation kickoff (~2 dias research + POC) |
| **OQ2** | `get_performance_breakdown` schema final `level × dimension` combos válidos vs inválidos | Fase 2 planning (writing-plans skill output) |
| **OQ3** | Subagent split (Google specialist + Meta specialist + orchestrator) — quando re-avaliar? | Post-Fase 4 (~3 meses), trigger se atingir 50+ tools again OR cross-platform queries frequentes |
| **OQ4** | Skills V4 (`auditoria-google-ads`, `analise-performance-google-ads`) update pra usar `get_performance_breakdown` | Out-of-MCP-scope (Wellington manual `.claude/skills/` update) Sprint paralelo a F2 |
| **OQ5** | Code Execution with MCP (98.7% token reduction pra workflows GAQL-heavy) | Re-avaliar 2026-08-25 audit, se ainda volume issues |

---

## 12. Não-ações deliberadas (YAGNI)

- **NÃO unificar Google+Meta** em interface common — industry pattern Supermetrics/Improvado contra. Schema explosion. Loss of clarity. Re-evaluate se cross-platform queries frequent surge em 3+ meses dogfood.
- **NÃO split em MCPs separados** (`v4-ads-google` + `v4-ads-meta`) — perde cross-platform queries futuros + complica deploy/auth. Subagent pattern preferível se split eventually needed.
- **NÃO migrar Skills V4 pra dentro MCP** — LlamaIndex/Anthropic pattern: Skills wrap MCP primitives, não substituir. Manter `.claude/skills/` separado.
- **NÃO subagent agora** — Meta só 2 tools, overhead 3× tokens não compensa. Re-evaluate em M.10 OR Re-audit 2026-08-25.
- **NÃO Code Execution agora** — esperar volume issues empíricos antes. Re-evaluate 2026-08-25.
- **NÃO refactor big-bang** — alto risco solo dev. Evolução incremental fases mesmo destino menor risco.

---

## 13. Cronograma estimado

```
Semana 1 (Sprint 3b.39):  Fase 1 ship + smoke + Wellington feedback collection
Semana 2:                  Fase 1 gate validation (continue OR abort)
Semana 3-4 (Sprint 3b.40): Fase 2 ship get_performance_breakdown + smoke real
Semana 5-6:                Fase 2 gate validation (dogfood ≥3 uses/semana)
Semana 7 (Sprint 3b.41):   Fase 3 tombstone zombies + 14d watch
Semana 8+:                 Fase 3 gate + transition pra Fase 4 ongoing
Semana 8-24 (M.3+):        Fase 4 demand pull Meta ship
2026-08-25:                Re-audit tool count + métricas finais
```

**Total tempo concentrated:** ~50 dias / ~7 semanas (vs estimativa original 6-8 semanas — coerente).
**Tempo Wellington dev:** ~3-4 semanas (resto é gate observation passive).
**Tempo Wellington feedback:** ~5 min × 3 fases = 15 min total.

---

## 14. Estado final esperado

| Métrica | Hoje (2026-05-25) | Pós-refactor (2026-08-25) |
|---|---|---|
| Tool count alive (não-tombstone) | 59 | ~35-40 |
| Tool count registered (incl. tombstones T<90d) | 59 | ~50-58 (decrescendo via hard-delete T+90d) |
| Always-loaded em context Claude | 59 (100%) | ~18 (~45% dos alive) |
| Defer-loading (sob demanda) | 0 | ~18-22 (~50% dos alive) |
| Tombstone (handler retorna error) | 0 | ~15-18 (cleanup gradual hard-delete T+90d) |
| Token usage em descriptions | ~25-30K | ~8-10K (-66%) |
| Zombies 0 uses 30d | 22 (38%) | ≤5 (≤14%) |
| Meta tools shipped (alive) | 2 | 6-8 (top Pareto only, não 45 paridade) |
| Meta calls/15d cumulative | ~5 | ~500+ (re-submit Full Access threshold) |

---

## 15. Referências

### Research arquitetural (Agent #2 report 2026-05-25)

- [Anthropic — Advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use)
- [Anthropic — Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)
- [Anthropic — Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
- [Anthropic — Multiagent sessions](https://platform.claude.com/docs/en/managed-agents/multi-agent)
- [Block Engineering — Playbook for Designing MCP Servers](https://engineering.block.xyz/blog/blocks-playbook-for-designing-mcp-servers)
- [MCP Bundles — Six-Tool Pattern](https://www.mcpbundles.com/blog/mcp-tool-design-pattern)
- [LlamaIndex — Skills vs MCP tools for agents](https://www.llamaindex.ai/blog/skills-vs-mcp-tools-for-agents-when-to-use-what)
- [LongFuncEval paper (arXiv 2505.10570)](https://arxiv.org/pdf/2505.10570)
- [DEV/AWS Heroes — MCP Tool Design: Why Your AI Agent Is Failing](https://dev.to/aws-heroes/mcp-tool-design-why-your-ai-agent-is-failing-and-how-to-fix-it-40fc)

### Internal V4 Ads MCP context

- Tool audit 2026-05-25 — Pareto 80/20 evidence + sweet spot 30-45
- [Findings catalog](../../operacao/findings-catalog.md) — 50 findings F1-F52 + A1-A6 + D1
- [Sprint history](../../operacao/sprint-history.md) — Sprints 3b.1-3b.38 + M.1-M.2b
- [Meta App Review decision (D1)](../../operacao/findings-catalog.md) — Caminho B+ janela observação 30-45 dias
- [Dogfood 2026-05-25 zombies audit](../../operacao/dogfood-2026-05-25-mestre-da-obra-jp-zombies-audit.md) — F52 + lição V4 48 P4
- [Meta family overview](2026-05-24-meta-ads-incorporation-design.md) — spec original M.1-M.25 (será reformulado Fase 4)

---

**Status:** Design completo (brainstorming approved). Próximo: spec self-review + Wellington review + writing-plans skill.
