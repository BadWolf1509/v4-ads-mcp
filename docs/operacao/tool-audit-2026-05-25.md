# Auditoria completa de tools — V4 Ads MCP — 2026-05-25

> **Contexto:** Análise data-driven dos 58 tools registrados pra avaliar tool count ideal, identificar zombies, oportunidades de consolidação e tools com bugs latentes. Disparada pós-Sprint M.2b ship + Meta App Review submit, antes de iniciar roadmap M.3-M.25 (~45 tools projetadas).
>
> **Decisão:** documentar findings + adiar ações de cleanup/consolidação. Material suficiente pra decidir sem ação imediata.

---

## TL;DR Executive

```
Estado:    58 tools (57 Google + 1 Meta novo + ferramentas Meta system)
Uso:       8 core tools fazem 60% do trabalho (Pareto evidente)
Zombies:   22 tools (38%) sem uso em 30d
Errors:    5/8 core tools com >20% error rate (mas são errors REAIS, não cancellations)
Roadmap:   M.3-M.25 projeta +45 Meta tools = 102 total (4x industry average)
Sweet spot recomendado: 30-45 tools curadas (vs 102 paridade total)
```

**3 decisões pendentes (post-decision):**
1. Consolidar 13 performance reports → 1-2 tools genéricas (-22% tool count)
2. Investigar bugs latentes (AttributeError + TypeError em create_campaign)
3. Avaliar Meta roadmap real (Top 10-15 vs paridade 45)

---

## 1. Dados quantitativos coletados

### 1.1 Distribuição por uso (últimos 30 dias)

| Bucket | Count | % | Definição |
|---|---|---|---|
| 🟢 Core | 8 | 14% | ≥10 uses 30d |
| 🟡 Warm | 10 | 17% | 5-9 uses 30d |
| 🟠 Cold | 18 | 31% | 1-4 uses 30d |
| 🔴 Zombie | 22 | 38% | 0 uses 30d |
| **Total** | **58** | 100% | |

### 1.2 Volume e concentração

- Total calls 30d: **287**
- Top 10 tools = **60.6%** do volume
- Users distintos: **1** (Wellington apenas — 3 colaboradores não-onboarded)
- Média: **~10 calls/dia**

### 1.3 Top 10 tools (60% do volume)

| Rank | Tool | Uses | Error% | Avg ms | Categoria |
|---|---|---|---|---|---|
| 1 | `create_and_link_assets` | 33 | 33.3% ⚠️ | 1679 | Google mutate |
| 2 | `get_change_history` | 29 | 10.3% | 2041 | Google read |
| 3 | `create_campaign` | 22 | **77.3% 🔴** | 1002 | Google mutate |
| 4 | `add_negative_keywords` | 17 | 29.4% | 1910 | Google mutate |
| 5 | `audit_competitor_keywords` | 16 | 0% | 2603 | Google audit |
| 6 | `create_conversion_action` | 16 | 50% ⚠️ | 1446 | Google mutate |
| 7 | `list_my_accounts` | 14 | 0% | 14 | Google read |
| 8 | `update_keyword_status` | 10 | 20% | 993 | Google mutate |
| 9 | `get_conversion_actions` | 9 | 0% | 3476 | Google read |
| 10 | `create_conversion_value_rule_set` | 8 | 62.5% ⚠️ | 1044 | Google mutate |

---

## 2. Zombie analysis (22 tools)

### Bucket A — Recém-shipped (2 tools, esperar 30d adicionais)

| Tool | Sprint | Análise |
|---|---|---|
| `detect_drift` | 3b.33 | Recém — dogfood pendente |
| `meta_list_my_ad_accounts` | M.2a | Cache tool, uso esporádico esperado |

### Bucket B — Performance reports redundantes (13 tools, candidatos consolidação)

| Tool | Veredicto |
|---|---|
| `get_account_overview` | Pode virar template `run_gaql` |
| `get_campaign_performance` | Idem |
| `get_ad_group_performance` | Idem |
| `get_ad_performance` | Idem |
| `get_keyword_performance` | Idem |
| `get_audience_performance` | Idem |
| `get_device_performance` | Dimension param de tool genérica |
| `get_geo_performance` | Idem |
| `get_hourly_performance` | Idem |
| `get_funnel_metrics` | Cobertura específica |
| `get_budget_pacing` | Cobertura específica |
| `get_search_terms_report` | Pode virar `run_gaql` |
| `get_top_keywords_creatives` | Pode virar `run_gaql` |
| `get_negative_keywords_audit` | Pode virar audit |

🎯 **Oportunidade:** 13 tools → 2-3 tools genéricas via `get_performance_breakdown(level, dimension, date_range)` + `run_gaql`. Reduz **22% do tool count** sem perder funcionalidade.

### Bucket C — Meta-tools developer (3 tools, manter)

| Tool | Análise |
|---|---|
| `list_gaql_resources` | Developer/debugging |
| `validate_gaql` | Validação power-user |
| `run_gaql` | Power-user — ABSORVE tools do Bucket B |

### Bucket D — Setup pontual crítico (1 tool, manter)

| Tool | Análise |
|---|---|
| `upload_customer_match_list` | Setup 1x/cliente, baixa frequência ok |

### Bucket E — Micro UX (3 tools, archive candidato)

| Tool | Análise |
|---|---|
| `apply_recommendation` | UI Google Ads cobre — archive |
| `dismiss_recommendation` | UI Google Ads cobre — archive |
| `update_campaign_bidding` | Mergeable com bid family |

---

## 3. Análise de errors (5 tools com >20%)

**Investigação:** errors são REAIS (não dry_run nem user cancellations).

### 3.1 Sample errors de `create_campaign` (77.3% error rate)

| Error message | Count | Categoria | Ação |
|---|---|---|---|
| "The operation is not allowed for the given context" | 10+ | Google policy/permission rejection | UX: enrich tool description com common causes |
| "The required field was not present" | ~2 | Schema gap nosso | Schema fix |
| "AttributeError (Python)" | 1 | 🐛 **Bug nosso latente** | Investigate + fix |
| "TypeError (Python)" | 1 | 🐛 **Bug nosso latente** | Investigate + fix |

**Contexto:** Todos 17 errors num único burst de 37 min (2026-05-18 02:55→03:32). Wellington tentando sandbox creation, batendo em problems específicos do contexto + 2 bugs Python.

### 3.2 Conclusão errors

NÃO é problema de audit_log normalization (que seria fix se errors fossem cancellations). É 3 problemas reais:

1. **2 bugs Python latentes** (AttributeError + TypeError) em create_campaign — devem ser investigados via reproduction subagent
2. **Tool descriptions fracas** — não orientam pre-conditions Google API
3. **Pre-flight validations ausentes** em tools de creation

---

## 4. Comparativo industry (tool count)

| Sistema | Tool count típico |
|---|---|
| GitHub Copilot Agents | 10-20 tools/agent |
| Salesforce Einstein Copilot | ~30 actions/topic |
| Claude Code (Anthropic) | ~25 core tools |
| Cursor agents | 15-25 tools |
| Supabase MCP | ~30 tools |
| Slack AI | ~20 actions |
| **V4 Ads MCP (atual)** | **58 tools** ⚠️ 2x industry |
| **V4 Ads MCP (projetado M.25)** | **~102 tools** 🚨 4x industry |

Wellington usa simultaneamente 4+ MCP servers (v4-ads + supabase + empsis + n8n) = **>150 tools expostas simultaneamente** em uma session Claude.

---

## 5. Roadmap M.3-M.25 reality check

**Premise original:** paridade quase total Google ↔ Meta (~45 tools cada).

**Problemas:**

1. **Workload solo dev:** ~45 tools × 1-2 dias/tool = **3-6 meses dedicado** (sem Google paralelo)
2. **Tool count explode:** 102 tools = território não-explorado, performance Claude degrada
3. **Dogfood evidence fraca:** apenas 5 usos `meta_get_account_overview` em 1 dia
4. **80/20 já provado em Google:** se Google tem 60% volume em 10 tools, Meta vai espelhar. Top 10-15 cobrem 80% provavelmente

---

## 6. Recomendações estruturadas

### 6.1 Sweet spot: 30-45 tools total (vs 102 projetado)

| Bucket | Count alvo | Status |
|---|---|---|
| Core Google daily ops | 12-15 | Já temos (top 10 + 5) |
| Core Google audits | 5-8 | Já temos (5 audits 3b.33-3b.37) |
| Long-tail Google occasional | 8-12 | Manter mas priorizar baixo |
| Core Meta read | 5-7 | A criar — overview, campaign perf, ad perf |
| Core Meta mutate | 5-8 | A criar — pause, budget, audience |
| **Total alvo** | **35-50** | vs 102 |

### 6.2 Fases sugeridas

**Fase 1 — Investigar bugs latentes (1-2h)**
- Reproduzir AttributeError + TypeError em create_campaign
- Catalogar como F50+ se confirmados
- Adicionar regression tests

**Fase 2 — Curar antes de adicionar (1 dia)**
- Auditar 22 zombies
- Decision por tool: keep / archive / merge
- Archive ≠ delete: mantém código mas descadastra do MCP server

**Fase 3 — Consolidation sprint (3-5 dias)**
- Criar `get_performance_breakdown(level, dimension, date_range)` 
- Archive 13 tools redundantes do Bucket B
- Tool count: 58 → ~44

**Fase 4 — Pós-decision gate Meta (variável)**
- Se APPROVED + dogfood positivo: ship Top 5-10 Meta tools (não 45)
- Se REJECTED ou dogfood baixo: pause Meta + foca Google maintenance

### 6.3 Princípios pra adicionar tools novas (post-V0)

1. **Demand pull, não supply push:** ship tool quando dogfood mostrar 3+ uses/semana esperadas
2. **Consolidação first:** verificar se tool genérica existente cobre (ex: `run_gaql` cobre 90% dos reads custom)
3. **Métricas de saúde:** revisar dashboard mensal — tools com 0 uses 60d viram archive candidate automático
4. **Subagent pattern em ~50 tools:** quando atingir, migrar pra arquitetura com agente-orquestrador + subagents especializados (cada com 10-15 tools no domain)

---

## 7. Não-ações esta sessão (deliberate)

- **NÃO implementar audit_log normalization** — investigação mostrou que errors são reais, não cancellations
- **NÃO consolidar agora** — sprint dedicada precisa foco sustentado, não janela atual
- **NÃO archive zombies agora** — algumas podem ter valor sazonal (ex: `upload_customer_match_list` setup 1x/cliente)
- **NÃO mudar Meta roadmap M.3-M.25 unilateralmente** — esperar decision gate (Meta App Review response + 2 semanas dogfood)

---

## 8. Métricas de acompanhamento (post-decision)

Reavaliar essa auditoria em **30 dias (2026-06-25)**:

| Métrica | Hoje (2026-05-25) | Target 2026-06-25 |
|---|---|---|
| Tool count | 58 | ≤55 (post-archive zombies óbvios) |
| Tools com 0 uses 30d | 22 (38%) | ≤10 (17%) |
| Core tools (≥10 uses) | 8 | ≥12 (com 3 colaboradores onboarded) |
| Error rate em core | 5/8 com >20% | ≤3/8 com >20% (post-bug fixes) |
| Users distintos | 1 | ≥3 (Wellington + colaboradores) |

Se métricas não melhorarem em 30d = decisão estrutural necessária (consolidation sprint OR pivot).

---

**Última atualização:** 2026-05-25 (Sprint M.2b shipped + Meta App Review submitted + smoke 8/8 PASS).
**Próxima revisão:** 2026-06-25 ou pós-decision gate Meta (o que vier primeiro).
