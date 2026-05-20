# Dogfood 2026-05-19 — Mestre da Obra JP (`7862230676`) — sessão D+7 cleanup massivo

**Operator:** Claude Code (Sonnet 4.7) em sessão dirigida por wellinton.ribeiro@v4company.com
**Account:** `7862230676` — Mestre da Obra JP+CAB
**Window:** Mix LAST_7_DAYS / LAST_14_DAYS / LAST_30_DAYS conforme query
**Goal:** Sessão real D+7 do launch Meta MO. Cobertura ampla: detecção de incidente Meta isolado, auditorias V4 (Google + BWSM + n8n + ERP + V4 BM), cleanup massivo Google legacy gestor anterior. 9+ tools v4-ads exercitadas em fluxo end-to-end com **6 writes aplicados** (3 PAUSE + 2× add_negatives + 1 add_keyword + 1 create_rsa + 1 update_ad_status + 1 update_keyword_status multi).

## Read tools exercitadas

1. `list_my_accounts` ✅ (1 call início)
2. `validate_gaql` ✅ (~12 calls — alta cadência)
3. `run_gaql` ✅ (~15 calls — múltiplos resources)
4. `get_campaign_performance` ✅ (LAST_14_DAYS + LAST_30_DAYS)
5. `get_ad_group_performance` (não usado nesta sessão diretamente — substituído por GAQL custom em vários momentos)
6. `get_search_terms_report` ✅ (LAST_7_DAYS, limit 40)
7. `get_conversion_actions` ✅ (43 actions retornadas)
8. `get_change_history` ✅ (filtrado `AD_GROUP_CRITERION` + `CREATE`, 30d janela explícita)

## Write tools exercitadas

9. `update_keyword_status` ✅ (3 calls: 3 PAUSED auto + 22 PAUSED dry-run + 17 PAUSED dry-run após filtro)
10. `add_negative_keywords` ✅ (6 calls: cleanup 5+5 + cirurgia 6+6 + Audit-Search-Terms 7+2 = total 31 negativas em 2 campaigns)
11. `add_keywords` ✅ (1 call: 1 PHRASE `"gerador energia"`)
12. `create_rsa` ✅ (1 call: novo RSA `809360964432` ENABLED — 15 headlines + 4 descriptions)
13. `update_ad_status` ✅ (1 call: PAUSED antigo RSA `757110239665`)
14. `apply_change` ✅ (2 calls: confirma 17-PAUSE + confirma create_rsa)

## Bugs / pegadinhas encontradas

### B1: `update_keyword_status` rejeita silently quando ID é negative ad_group_criterion (HIGH)

**Sintoma:** Sessão pausou 22 criterion_ids em 1 batch. `apply_change(token)` retornou:
```
Google Ads retornou: Negative ad group criteria are not updateable.
```

Erro genérico Google — não identifica QUAIS dos 22 IDs eram negative. Tive que rodar GAQL extra cross-checkando `ad_group_criterion.negative` flag pra descobrir que **5 dos 22 eram negative** (legacy gestor anterior). Re-tentei com 17 positive-only → applied OK.

**Custo na sessão:** 1 retry de `apply_change` + 1 query GAQL custom + raciocínio de cross-check + retentativa do dry-run (gerou novo token, queimou primeiro).

**Padrão:** Sprint 3b "Silent-acceptance design gap" (família A1-A5) — Google API tem distinção que SDK descriptor não expõe no contrato write tool. Lock-in entre `update_keyword_status` (write tool de operações de **status** em positive) e `negative=true` criterion (read-only via mesma API tool — Google considera state machine separada).

**Sugestão de fix:** **Pre-flight GAQL check** em `update_keyword_status`:

```python
# Pseudo-code antes do call do GoogleAdsService
preflight_q = f"""
SELECT ad_group_criterion.criterion_id, ad_group_criterion.negative
FROM ad_group_criterion
WHERE ad_group_criterion.criterion_id IN ({ids})
"""
result = run_gaql(preflight_q)
negative_ids = [r.criterion_id for r in result if r.negative]
positive_ids = [r.criterion_id for r in result if not r.negative]

if negative_ids:
    return {
        "status": "rejected_preflight",
        "negative_criterion_ids_blocked": negative_ids,
        "positive_criterion_ids_safe": positive_ids,
        "to_retry_with": f"Re-call com {len(positive_ids)} positive IDs apenas. Negativas são read-only via update_keyword_status (Google API design — pra des-negativar, UI Google obrigatório).",
        "summary": f"{len(negative_ids)}/{len(ids)} são negative ad_group_criterion."
    }
```

**Severity:** HIGH — pegou 1 sessão completa com retry. Em batches grandes (cirurgias) gestor pode achar que aplicou e perder rastreabilidade.

### B2: `validate_gaql` `LAST_30_DAYS` em `change_event` retorna erro genérico Google (LOW)

**Sintoma:**
```sql
SELECT change_event.change_date_time, ... FROM change_event
WHERE change_event.change_date_time DURING LAST_30_DAYS ...
```

Retorna: `Google Ads retornou: The requested start date is too old. It cannot be older than 30 days.`

LAST_30_DAYS pega 31 dias (hoje + 30 anteriores). `change_event` API só permite 30 dias inclusive. Tive que ajustar pra LAST_14_DAYS pra confirmar audit Auto-Apply, e separadamente usar `get_change_history` com date range explícito (`2026-04-20` → `2026-05-04`) pra investigar keywords legacy.

**Sugestão de fix:** `validate_gaql` poderia detectar `FROM change_event` no parse + reservar mensagem específica:
> *"change_event tem janela máxima 30d inclusiva. LAST_30_DAYS = 31 dias = rejeitado. Use LAST_14_DAYS ou date range explícito (start_date+end_date) ≤30d."*

**Severity:** LOW — 1 retry, recuperação rápida. Mas erro genérico Google é abrasivo pra gestor primeira vez.

### B3: `segments.conversion_action` incompatível com `metrics.cost_micros` em `FROM campaign` (LOW)

**Sintoma:**
```sql
SELECT segments.conversion_action, segments.conversion_action_name,
       metrics.conversions, metrics.cost_micros
FROM campaign WHERE campaign.id IN (...)
```

`validate_gaql` rejeita:
> *"Cannot select the following segments because at least one unsupported metric is found in SELECT or WHERE clause: 'segments.conversion_action'(unsupported metrics: 'cost_micros')..."*

Pra obter conv por action + custo aproximado tive que fazer 2 queries: uma com segments+conversions, outra com cost_micros agregado.

**Sugestão de fix:** `validate_gaql` poderia adicionar hint:
> *"`segments.conversion_action_*` não combina com `metrics.cost_micros`. Use 2 queries separadas: (1) conv por action com `segments.conversion_action`, (2) cost agregado por campaign sem segments."*

**Severity:** LOW.

### B4: Discrepância `campaign.status` entre queries diferentes (LOW — possivelmente cache Google)

**Sintoma:** Mesma campanha (PMax `21359437667`) reportada como:
- `PAUSED` em GAQL inicial filtrando `advertising_channel_type = 'PERFORMANCE_MAX'`
- `REMOVED` em `get_campaign_performance status=all` ~5min depois

Re-query confirmou `REMOVED` definitivo. Provável lag de cache server-side Google (não bug do MCP), mas confundiu análise de plano de ação.

**Sugestão de fix:** Documentar em CLAUDE.md MCP V4 ou em description de tools:
> *"`campaign.status` pode lagar até alguns minutos entre queries. Se status crítico pra decisão (ex: deletar campaign), re-query antes de agir."*

**Severity:** LOW.

### B5: Resultado `get_search_terms_report` + `consulta_livre_select` excede tokens MCP cliente quando rows densas ✅ **RESOLVED (Sprint 3b.29 — `run_gaql.aggregate_by`, 2026-05-20)**

**Sintoma:** ERP empsis `logon` 14d + `evento_usuario` 14d retornaram >60k chars cada, caindo em truncamento + save-to-file. `campaign_asset` GAQL mesmo com fields enxutos (campaign.id + field_type + asset.type) retornou 89k chars (272 rows × ~330 chars/row JSON).

Workaround: Bash + Python pra ler arquivo + agregar com `Counter()`. Funciona mas overhead de contexto + comandos.

**Sugestão de fix opcional:** `run_gaql` aceitar parâmetro `aggregate_by: ["field_a", "field_b"]` que faz GROUP BY + COUNT internamente, retornando agregado. Especialmente útil pra resources com cardinalidade alta (campaign_asset, ad_group_ad).

**Severity:** LOW — workaround Python existe.

**Resolução (Sprint 3b.29, 2026-05-20):** `run_gaql` agora aceita `aggregate_by: list[str]` opcional. Smoke T3 reproduziu o caso real: campaign_asset Nutry 119 rows → 7 groups ordered DESC (SITELINK:68, CALLOUT:40, etc). Output reduzido drasticamente vs raw rows. Workaround Bash+Counter() obsoleto pra queries densas via MCP. Spec: [`2026-05-20-sprint-3b-29-run-gaql-aggregate-by-design.md`](../superpowers/specs/2026-05-20-sprint-3b-29-run-gaql-aggregate-by-design.md).

## Gaps de cobertura (tools faltando)

| Tool ausente | Por quê precisei | Impacto sessão |
|---|---|---|
| `update_customer_conversion_goal` / `update_campaign_conversion_goal` | Setar `biddable=FALSE` em ENGAGEMENT/STORE_VISIT/UNKNOWN | Opção C 23/05 vai precisar UI Wellington |
| `update_conversion_action` | Mudar `primary_for_goal` / `include_in_conversions_metric` | Não consegui rebaixar Store visits action pra secondary (era P2 do playbook); workaround = via custom goal |
| `remove_campaign` / `remove_ad_group` / `remove_keyword` / `remove_ad` | Deletar Smart Camp `21362837957` PAUSED | UI Wellington manual |
| `update_keyword_match_type` (ou `update_keyword`) | Mudar `gerador energia` BROAD→PHRASE no `[GPA][06][GERADORES]` | Workaround = PAUSE BROAD + ADD PHRASE (cria 2 criterion_ids, perde histórico) |
| `update_ad_schedule` / `update_bid_modifier` | Bid schedule lunch shift -15% (pendência D+30) | Quando aplicar, vai UI Wellington |
| `move_keyword` | Mover keyword entre ad_groups preservando histórico | Pendência futura |

## Sugestões de tools de auditoria curadas (alto valor)

Inspirado nos audits que tive de implementar via GAQL custom hoje. Cada uma economizaria 10-30min/sessão:

### `audit_quality_score`

```
Input: customer_id, [ad_group_id_filter optional]
Output: ad_groups + keywords ordenadas QS ASC.
Flags:
  - "candidate_pause": QS 1-2 + impressions > 0 + clicks 0 (waste)
  - "candidate_promote_exact": QS 7-10 + match=BROAD + conv >= 1 (move para EXACT reduz CPC)
  - "duplicate_intent": keyword text similar em ad_groups diferentes
```

Hoje rodei manualmente via GAQL `keyword_view` filtrando `ad_group.id IN (175472286913, 183622658769)` + ordenando. Tool curada faria isso ao nível conta inteira.

### `audit_competitor_keywords`

```
Input: customer_id, competitor_brands: ["projecta", "casa do construtor", "promina", ...]
Output: keywords positivas ADDED com text matching qualquer brand + search terms últimos 7d capturados + total cost wasted projetado.
```

Hoje detectei manualmente examinando search terms report + cross-checkando ad_group_criterion. Tool curada faria sob input do gestor com lista de marcas locais.

### `audit_zombie_keywords`

```
Input: customer_id, period: LAST_30_DAYS, threshold_impressions: 0
Output: keywords ENABLED com impressões abaixo threshold.
Grouped by ad_group + total count + ad_group_total_zombie_percentage.
```

Hoje listei `[GPA][06][GERADORES]` JPA 15/24 zombies (62%) manualmente — tool listaria pra conta inteira.

### `audit_orphan_smart_actions`

```
Input: customer_id
Output: conversion actions tipo SMART_CAMPAIGN_* / GOOGLE_HOSTED status ENABLED mas Smart Campaign owner = REMOVED.
Inclui: explicação de read-only + sugestão "documentar cosmético".
```

Hoje descobri que as 4 Smart Campaign actions ficaram órfãs pós-REMOVE — Google não auto-remove. Tool curada explicaria isso preventivamente.

### `audit_negative_criterion_overlap`

```
Input: customer_id
Output: detecta negativas duplicadas entre níveis (ad_group / campaign / customer).
Exemplo encontrado hoje: `comprar` BROAD existia como negative ad_group_criterion no `[GPA][06][GERADORES]` + foi adicionada como campaign-level também na cirurgia.
```

Não é bug — overlap é OK funcionalmente — mas pode poluir manutenção. Tool curada ajudaria gestor a decidir consolidar nível.

### `audit_assets_parity_between_campaigns`

```
Input: customer_id, [campaign_ids optional]
Output: assets attached (Sitelinks, Callouts, Snippets, etc) por campaign — flag gap.
Caso real hoje: CAB tem 8 sitelinks vs JPA 20 → gap 12.
```

Hoje detectei agregando via Python o output de `campaign_asset`. Tool curada faria nativamente.

## UX issues menores

### UX-A: `apply_change` requer chamada separada com confirmation_token (10min TTL)

Workflow `update_keyword_status > 5 entities` → dry_run → apply_change. Funciona, mas se Claude/Wellington discutir 5min e re-rodar dry_run, token velho expira silentemente. Tive isso 1× na sessão (re-tentei após cross-check negative).

**Sugestão:** parâmetro opcional `auto_apply_token: <token>` na chamada original — se passado, ignora preview e aplica. Útil pra sessões dirigidas onde Claude/gestor já confirmaram fora-banda.

### UX-B: `get_conversion_actions` não retorna `include_in_conversions_metric` + `primary_for_goal`

Eu tive que fazer GAQL separada (`SELECT conversion_action.id, ..., conversion_action.primary_for_goal, conversion_action.include_in_conversions_metric ...`) pra obter os flags críticos. `get_conversion_actions` retorna name/category/type/status/attribution/default_value, mas NÃO esses 2 flags que definem se action alimenta Smart Bidding.

**Sugestão:** adicionar 2 campos no response — `include_in_conversions_metric: bool` + `primary_for_goal: bool`. São flags universalmente úteis em audit.

### UX-C: `add_keywords` aceita 1 ad_group por chamada

Pra aplicar os 9 PROMOTE candidates pendentes (pós-D+14) — 9 keywords spalhadas em ~5 ad_groups diferentes — vão precisar 5 calls. Não é bloqueador mas multiplica overhead.

**Sugestão:** aceitar array `[{ad_group_id, keywords[]}]` pra batch multi-grupo. Mantém spec `auto if ≤20 KWs / 1 ad_group` ou `confirm if >20 ou >1 ad_group`.

### UX-D: `get_change_history` janela 30d hard limit

Pra investigar **quem criou** keywords legacy de marcas concorrentes (`projecta` criterion_id `24019150`, formato early Google Ads), precisei descobrir indiretamente que foi gestor anterior (não vi CREATE event nos últimos 30d). Google API limita 30d server-side, então MCP não pode fazer milagre — mas a tool description poderia citar a limitação explicitamente.

**Sugestão:** doc da tool mencionar "janela 30d hard limit Google API — pra histórico mais antigo, usar Google Ads UI Change History (até 1y) ou cravar baseline na primeira sessão de assunção de conta".

## Padrões V4 que merecem entrar no MCP

### Padrão 1: Pre-flight detection de takeover

Quando `list_my_accounts` retorna lista vazia ou account previamente conhecido (cacheado por session ou parâmetro) sumiu da resposta:

```json
{
  "ad_accounts": [...],
  "warnings": {
    "possible_account_takeover": {
      "missing_vs_history": ["act_xxx"],
      "evidence": "Account previously accessible (last seen 2026-05-13) not in current list. Recommendation: verify with client before troubleshooting credentials."
    }
  }
}
```

Memory `feedback_mcp_denied_account_takeover` documenta isso a nível Claude. MCP-side seria mais robusto.

**Caso real desta sessão**: Meta MCP oficial retornou "Access denied" pra `act_1145068113357031` e `ads_get_ad_accounts` listou só `945292518409916` (não MO). Era takeover (descoberto via Wellington UI Meta). Sem aviso prévio, gastei tempo retentando credencial.

### Padrão 2: Hook PostToolUse auto-log writes

Já mencionado no `D:/Gestor de Tráfego de Ads/CLAUDE.md` raiz V4 como pendente. Hoje fiz log manual via `Edit 01-HISTORICO.md` após cada write (4 edits separados). Hook automático poupa esforço + garante consistência.

**Caso real desta sessão**: 6 writes em conta `7862230676`. Cada um exigiu update manual em `01-HISTORICO.md` + `PENDENCIAS.md`. ~5min/write = 30min de overhead documental.

### Padrão 3: ICE Score como input nas tools de write

Tools de write aceitar parâmetro opcional:
```python
mcp__v4-ads__add_negative_keywords(
    ...,
    ice_impact=8,
    ice_confidence=9,
    ice_effort=9,  # 10 = muito fácil
    hypothesis="Se adicionar negativas X/Y/Z, então CPC cai ~30%, porque ..."
)
```

Hook PostToolUse leria essas tags e logaria estruturado no `01-HISTORICO`. Aplicaria padrão V4 ICE Score sem onerar Claude/gestor com manutenção doc.

## Priorização ICE sugerida (perspectiva do operador de MCP)

| # | Item | Impact | Conf | Effort | **ICE** | Notas |
|---|---|---|---|---|---|---|
| 1 | **B1 — Pre-flight negative check em `update_keyword_status`** | 7 | 10 | 9 | **630** | Único bug HIGH desta sessão. Pegou batch grande, recuperação custosa |
| 2 | **Tool `update_customer_conversion_goal`** | 9 | 10 | 6 | **540** | Opção C SIMPLIFICADA 23/05 (pendência V4 D+11) depende disso ou vai UI |
| 3 | **UX-B — `get_conversion_actions` retornar 2 flags primary/include** | 6 | 10 | 9 | **540** | Auditoria conversion actions é high-frequency. 1 GAQL extra hoje por causa disso |
| 4 | **`audit_quality_score` curada** | 8 | 9 | 7 | **504** | Sessões de cirurgia recorrentes. Hoje gastei ~30min em queries manuais |
| 5 | **Padrão 1 — Pre-flight takeover detection** | 7 | 9 | 7 | **441** | Caso real Meta hoje. V4 Lima Soares & Co opera ~10 clientes — risco recorrente |
| 6 | **`audit_competitor_keywords` curada** | 9 | 8 | 6 | **432** | Cleanup MO hoje detectou ~R$2k/mês waste. Outros clientes V4 herdam mesma estrutura legacy |
| 7 | **Tools `remove_*` (campaign/ad_group/keyword/ad)** | 6 | 9 | 8 | **432** | UI Wellington 1× nesta sessão (Smart Camp REMOVED). Recorrente |
| 8 | **B2/B3 — `validate_gaql` mensagens específicas (`change_event`/`segments`)** | 5 | 10 | 8 | **400** | UX improvement, baixa frequência |
| 9 | **Padrão 2 — Hook PostToolUse auto-log HISTORICO** | 8 | 8 | 5 | **320** | V4 já documenta como pendente. Esforço médio (script + testes) |
| 10 | **UX-A — `auto_apply_token` opcional** | 4 | 9 | 9 | **324** | Pequeno mas elegante |
| 11 | **`audit_zombie_keywords` curada** | 5 | 9 | 7 | **315** | Sessões pontuais — menor frequência |
| 12 | **`audit_orphan_smart_actions` curada** | 4 | 9 | 8 | **288** | Edge case — clientes herdados |
| 13 | **`audit_assets_parity_between_campaigns` curada** | 5 | 8 | 7 | **280** | Pendência D+30 MO+CAB. Vale pra outros clientes |
| 14 | **UX-C — `add_keywords` multi-ad-group** | 4 | 9 | 7 | **252** | 9 PROMOTE pós-D+14 MO precisa disso |
| 15 | **`update_keyword_match_type`** | 5 | 8 | 5 | **200** | Workaround PAUSE+ADD funciona |
| 16 | **`audit_negative_criterion_overlap` curada** | 3 | 8 | 7 | **168** | Cosmético |

## Recomendação prática

**Aplicar antes de 23/05 sex (Opção C SIMPLIFICADA MO):**
- #2 `update_customer_conversion_goal` (alto valor V4 cravado — pendência D+11)
- #1 B1 pre-flight negative (HIGH severity da sessão)

**Aplicar próximo sprint (curto prazo):**
- #3 UX-B `get_conversion_actions` flags (low effort, high value)
- #4 `audit_quality_score` curada (alto valor V4 recorrente)
- #5 Pre-flight takeover detection
- #6 `audit_competitor_keywords` curada

**Backlog (médio prazo):**
- #7 tools `remove_*` (com CONFIRM obrigatório)
- #9 Hook PostToolUse auto-log

---

## Anexo — outputs de write desta sessão (rastreabilidade)

Todos com `apply_change`+request_id real do Google. Cravados em `D:/Gestor de Tráfego de Ads/clientes/Mestre da Obra/João Pessoa/01-HISTORICO.md` entrada `### 19/05/2026`.

| Operação | Google Request ID |
|---|---|
| 3 keywords PAUSED (concorrentes legacy) | `QVfBkv1sy8psjHufjP5t6A` |
| 5 negativas JPA (cleanup competidores) | `EDcY31Ksugo2423ahukRVA` |
| 5 negativas CAB (cleanup competidores) | `PhclC40_I9V3RpK1E28MGA` |
| 6 negativas JPA (cirurgia GERADORES) | `K04Z5nFvsIoxR9RDFcTjkw` |
| 6 negativas CAB (cirurgia GERADORES) | `BBdt1kkgJlWFL3vXDLWBPw` |
| 17 keywords PAUSED (cirurgia GERADORES) | `zs3KQHXSgiBnJW9Fe8JpnA` |
| 1 keyword PHRASE `"gerador energia"` | `O-b04m96pG1pCFliiPNwOA` |
| 7 negativas CAB (Audit-Search-Terms) | `bWkcRgcfak_ki6A-LGvBlA` |
| 2 negativas JPA (Audit-Search-Terms) | `5AywlY9IUTc2FGOk0Lqe_w` |
| RSA novo `809360964432` ENABLED | `9J6UbQP5eh-OE2b2sz2VdA` |
| RSA antigo `757110239665` PAUSED | `Y5-09frEhob4rUfwLjOYdw` |

Total: 11 writes Google aplicados na sessão (5 add_negative + 3 update_keyword_status + 1 add_keyword + 1 create_rsa + 1 update_ad_status).

---

*Dogfood report gerado 2026-05-19 noite. Cross-reference: `01-HISTORICO.md` MO-JP entrada `19/05/2026` (todas entradas). Linkar em `findings-catalog.md` quando B1 virar bug catalogado (severity HIGH).*
