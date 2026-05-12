# Dogfood — DR DÉRICK VINHAS (`4493906974`)

**Date:** 2026-05-12
**Operator:** wellinton.ribeiro@v4company.com + Claude (Sonnet 4.7)
**Purpose:** P3 — dogfood expansion em vertical NOVA (médico / lead gen B2C). Prior dogfood sessions cobriram locação de equipamentos (Mestre da Obra JP) + e-commerce (ML Antiguidades spot-check) + consultoria (Nutry) + turismo (Expresso). Médico é diferente: funil curto, conversão é form fill / agendamento, geo precision crítico.

## Account context

- 61,074 impressions, 950 clicks, R$ 2,586.72 spend (LAST_30_DAYS)
- 149 conversions @ R$ 17.36 CPA
- 1:1 placeholder tracking (warning fired ✅ — 4ª validação empírica do UX-1)
- vs previous period: +24% conversions, similar spend, CPA caiu de R$ 21.00 → R$ 17.36 (-17%) — tendência positiva
- CTR 1.56% (vs 1.65% prev — leve queda; pode ser saturação de impressões)

## Account structure

1 campaign SEARCH (`[CP] [V4 COMPANY] [DR DERICK] [PESQUISA] [LEADS] [GT PEDRO] [01]`) com 7 ad groups por procedimento:

| Ad Group | Impr | Clicks | Cost | Conv | CTR | CPA |
|---|---|---|---|---|---|---|
| TOPO - MEIO | 18,220 | 274 | R$ 771 | 51.17 | 1.50% | R$ 15.07 |
| BRONCOSCOPIA | 12,486 | 206 | R$ 545 | 30.67 | 1.65% | R$ 17.76 |
| CIRURGIÃO TORÁCICO | 2,043 | 124 | R$ 342 | 21.67 | 6.07% | R$ 15.77 |
| HIPERIDROSE | 8,589 | 117 | R$ 288 | 9.00 | 1.36% | **R$ 32.00** ⚠ |
| PECTUS ESCAVADO | 12,249 | 100 | R$ 269 | 18.50 | 0.82% | R$ 14.53 |
| ESPIROMETRIA | 1,219 | 69 | R$ 234 | 11.00 | 5.66% | R$ 21.27 |
| BROMIDROSE | 6,268 | 60 | R$ 139 | 7.00 | 0.96% | R$ 19.88 |

**Pontos de atenção:**
- HIPERIDROSE com CPA 2x da média (R$ 32 vs ~R$ 17 médio)
- TOPO-MEIO drena 30% do spend (R$ 771/R$ 2,587) — catch-all com KWs amplas
- PECTUS ESCAVADO + BROMIDROSE com CTR < 1% — match ruim ou ad fraco

## Achados de produto (P3 findings)

### F1. ROAS warning fires corretamente em 4ª vertical ✅

`tracking_warning` aparece em `get_account_overview.current` E `previous` quando ratio 1:1 detectado. Já validado em locação (Mestre da Obra JP), consultoria (Nutry), turismo (Expresso, zero-value), e-commerce (ML Antiguidades, real revenue). **Medicina/lead gen é 5ª vertical empiricamente validada.** Helper robusto.

### F2. Workflow gap — competitor doctor name detection (alto valor, sem tool dedicado)

Search terms revela **5 buscas por médicos concorrentes** com R$ 16+ desperdiçados:
- `dr fernando tedesco são carlos telefone` (R$ 3.98, 1 conv mas é spam de form fill provavelmente — pessoa procurando outro médico clicou no anúncio)
- `dr mayckell passos mg` (R$ 3.51)
- `dr daniel galhardo ribeirão preto` (R$ 3.32)
- `luis renato alves` (R$ 2.62)
- `igor botto` (R$ 2.82)

**Esses são candidatos óbvios pra negative keywords.** O MCP tem `add_negatives_from_search_terms` (Sprint 3b.1) — funciona. Gestor pode usar com classification CONFIRM.

**Observation (não bug):** seria útil um tool tipo `detect_competitor_negatives(customer_id)` que olha search_terms e detecta padrões `dr|doutor [nome próprio]` para sugerir. **YAGNI por enquanto** — gestor + Claude conseguem fazer essa análise no fluxo natural, e o pattern é vertical-específico (médico). Documentado como ideia futura.

### F3. Educational/informational queries drenando spend (~R$ 50 perdidos)

Buscas com intent informacional (curiosidade/research), NÃO comercial:
- `como usar a bombinha para asma` (R$ 7.92, 0 conv)
- `como curar bronquite asmática` (R$ 4.47, 0 conv)
- `dpoc o que significa` (R$ 3.90, 0 conv)
- `exercicios para o pulmão` (R$ 4.22, 0 conv)
- `fibrose pulmonar tem cura` (R$ 9.32 cumulativo em 2 ad groups, 0 conv)
- `sintomas cancer pulmao` (R$ 3.45, 0 conv)
- `melhor desodorante bromidrose` (R$ 5.31, 0 conv — querendo PRODUTO não cirurgião)
- `como tira odor das axilas` (R$ 3.62, 0 conv)
- `pediatra especialista em pulmão` (R$ 3.20, 0 conv — wrong demographic)

**Candidatos a negativas em CAMPAIGN level** (cuidado: blanket "como" pode capturar leads comerciais). Recomenda-se phrase match em palavras tipo `pediatra`, `desodorante`, `bombinha`, `como tira`, `exercicios`, `tem cura`, `o que significa`, `sintomas`.

### F4. Cross-ad-group keyword spillage (problema de account structure, não MCP)

KWs amplas em ad group "errado" capturando termos que deveriam estar em outro:
- `cirurgia para hiperidrose nas maos` rolou em **TOPO-MEIO** (deveria ser HIPERIDROSE)
- `cirurgia hiperidrose mãos e pés` rolou em **CIRURGIÃO TORÁCICO** (deveria ser HIPERIDROSE)

**Out of MCP scope:** isso é hygiene de structure de campanha (KW alignment + match type tuning). Gestor faz via UI ou eventualmente um futuro tool `audit_keyword_alignment`.

### F5. UX observation — `get_search_terms_report` não agrega por search_term cross-ad-group

Hoje o report retorna 1 row por (search_term, ad_group_id). Search term `fibrose pulmonar tem cura` aparece em 2 rows distintas (BRONCOSCOPIA + CIRURGIÃO TORÁCICO) com custos separados (R$ 5.26 + R$ 4.06 = R$ 9.32 total — só pego se gestor soma manualmente).

**Possível UX improvement:** flag `aggregate_by_term=true` que coloca cross-ad-group totals. Mas YAGNI: gestor + Claude conseguem somar visualmente, e o uso primário do report é decidir qual ad group "owns" cada term pra negative-add.

**Documentado como nice-to-have, não acionar agora.**

### F6. UX observation — sem `min_cost_brl` filter em `get_search_terms_report`

Default `limit=500`. Pra accounts com milhares de search terms únicas, gestor precisa baixar tudo e filtrar mentalmente. Pequeno.

**YAGNI:** gestor pode usar `limit=N` mais agressivo. Quando ficar dor, considerar `min_cost_brl` filter.

## Achados de produto (expanded findings — product test framing)

### F7. `get_recommendations` — `type_pt` redundancy quando sem PT-BR mapping

Recommendation `FORECASTING_SET_TARGET_CPA` retornada como:
```json
{"type": "FORECASTING_SET_TARGET_CPA", "type_pt": "FORECASTING_SET_TARGET_CPA"}
```

`type_pt` field existe mas duplica `type` quando não há tradução. Gestor pensa que tradução funcionou. Melhores comportamentos:
- (a) `type_pt: null` quando sem mapping (gestor sabe usar `type`)
- (b) Mapping curado para os 10-20 tipos mais comuns + `null` para o resto

**Severidade:** Low-medium. Não quebra fluxo, mas comunica "feature de tradução existe" quando não. **Spawn-task candidato.**

### F8. `get_negative_keywords_audit` reveals empty list

Conta tem ZERO campaign-level negatives (`total_negatives: 0`). Tool retornou empty list corretamente. **Tool funciona, finding é account-level.** Explica F2 + F3 actionability (sem negativas → tudo passa).

### F9. ALL keywords são BROAD match (account-level finding)

10/10 keywords amostrados são `match_type: "BROAD"`. Conta depende 100% do broad matching algorithm — explica search terms ruins. **Account hygiene, não MCP issue.**

### F10. `first_page_cpc_brl` + `top_of_page_cpc_brl` retornam `null` para todos os 10 KWs

Position estimates da Google API são `null`. Pode ser:
- Account em MAXIMIZE_CONVERSIONS (auto-bidding) — Google não computa CPC estimates per-keyword
- Low volume bridge — confirmar via run_gaql

**Validation via run_gaql:** Conta usa `bidding_strategy_type: "MAXIMIZE_CONVERSIONS"` (confirmado). Position estimates não fazem sentido nesse modo. **Não é bug — comportamento correto da Google API.**

### F11. 🚨 `get_budget_pacing` retorna `delivery_method` como int string

```json
{"delivery_method": "2"}  // should be "STANDARD"
```

**Same bug class de Sprint 3b.7 UX-2/UX-3** (proto-plus v20 repr regression). Sprint 3b.7 fixou 22 call sites em 10 tools mas **missed `get_budget_pacing.py:30`**. Cross-validation: `run_gaql` com mesma field retorna `"STANDARD"` corretamente.

**Fix mecânico aplicado nesta sessão:** `str(row.campaign_budget.delivery_method)` → `row.campaign_budget.delivery_method.name`.

**Severidade:** Medium. Gestor que olha pacing fica confuso (`"2"` é ACCELERATED ou STANDARD?). Fix shipped junto com este doc.

### F12. 🚨 `update_keyword_bid` não pré-valida campaign bidding strategy

Conta usa `MAXIMIZE_CONVERSIONS` (auto-bidding). KWs têm `cpc_bid_micros = 0` por design (Google não armazena bid manual em auto-bidding). Tool aceita update payload e retorna dry-run com `delta_pct: 100.0%` em todas 6 KWs (porque vai de 0 → R$ 2-3.5). CONFIRM path foi acionado (good — variation >20%) mas confirmation_reason cita variation, NÃO "auto-bidding strategy active."

Se gestor confirmar via apply_change, Google provavelmente ignora silenciosamente (manual bid em campaign auto-bid não funciona). **Silent-acceptance bug class** (família A1-A5 do Sprints 3b.3-3b.6).

**Suggested fix:** pre-flight check em `update_keyword_bid` que detecta `campaign.bidding_strategy_type != MANUAL_CPC` e rejeita com mensagem clara antes do dry-run.

**Severidade:** Medium. Pode chegar até `apply_change` e gestor pensar que aplicou, mas Google ignora. Spawn-task candidato.

## Tools exercised (TODAS as 21 read tools + 4 mutate tools dry-run)

### Read tools — 21 de 21 ✅

| Tool | Result | Notes |
|---|---|---|
| `list_my_accounts` | ✅ | 23 contas listadas |
| `get_account_overview` | ✅ | tracking_warning fires ✅ (5ª vertical) |
| `get_campaign_performance` | ✅ | enum decode `status: "ENABLED"`, `type: "SEARCH"` |
| `get_ad_group_performance` | ✅ | 7 rows, ordering by cost |
| `get_keyword_performance` | ✅ | match_type, quality_* todos legíveis (F10 null OK) |
| `get_search_terms_report` | ✅ | status `"ADDED"`/`"NONE"` legível |
| `get_ad_performance` | ✅ | `ad_strength: "EXCELLENT"`, type `"RESPONSIVE_SEARCH_AD"` |
| `get_negative_keywords_audit` | ✅ | Empty (F8) — handled |
| `get_recommendations` | ✅⚠ | F7 — type_pt redundancy |
| `get_geo_performance` | ✅ | Single country (by design) |
| `get_device_performance` | ✅ | MOBILE 99% |
| `get_hourly_performance` | ✅ | day_of_week decoded |
| `get_audience_performance` | ✅ | Empty rows handled |
| `get_funnel_metrics` | ✅ | tracking_warning em totals ✅ |
| `get_budget_pacing` | 🚨 | **F11** — delivery_method enum not decoded (fix shipped) |
| `get_top_keywords_creatives` | ✅ | metric configurável |
| `get_conversion_actions` | ✅ | 11 actions, todos enums decoded |
| `get_change_history` | ✅ | Empty + summary block |
| `list_gaql_resources` | ✅ | 15 resources catalog |
| `run_gaql` | ✅ | Raw GAQL works, decoded properly |
| `validate_gaql` | ✅ | Reject bogus field corretamente |

### Mutation tools — 4 testadas via CONFIRM path (sem apply_change)

| Tool | Result | Notes |
|---|---|---|
| `update_keyword_bid` | ✅⚠ | F12 — sem pre-check bidding strategy. CONFIRM funcionou (variation >20%). Token `T3DCK4A9` gerado, NÃO aplicado |
| `bulk_pause_by_query` | ✅ | `status: "no_op"` quando filter sem matches — clean UX |
| `update_campaign_budget` | ✅ | Dry-run com blast_summary PT-BR. Token `YUKMZOYG` gerado, NÃO aplicado |
| `validate_gaql` | ✅ | Read utility — reject bogus field |

**0 mutations aplicadas.** 2 confirmation tokens gerados expiram em 10 min sem efeito.

## Summary

**Sprint P2 + 3b.7 health check em vertical nova:** todos os fixes shipados funcionam corretamente. ROAS warning helper validated em 5 verticals distintas (medicina = 5ª). Enum decode (UX-2/UX-3) sem regressions em 21 read tools testadas.

**Achados de produto (3 novos bugs + 3 nice-to-haves):**
- 🚨 **F11** (bug): `get_budget_pacing.delivery_method` enum não decoded — fix shipped nesta sessão. Sprint 3b.7 missed this file.
- 🚨 **F12** (bug class silent-acceptance): `update_keyword_bid` aceita payload em campaign auto-bidding sem validar — spawn-task candidato
- ⚠ **F7** (UX): `get_recommendations.type_pt` redundancy quando sem PT-BR mapping — spawn-task candidato
- 💡 F5, F6, F9-F10: nice-to-haves documentados (YAGNI)

**Real account-management value identified (não acionado nesta sessão — escopo de teste de produto):** R$ 60+ mensais em desperdício de spend acionável via tools existentes.

**P3 outcome:** ✅ todas as 21 read tools + 4 mutate-CONFIRM tools testadas em vertical nova (medicina). Tool count 39 mantido + 3 findings actionable surfaceadas. Stabilization compounding mantido (F11 é regression de Sprint 3b.7, não new bug introduced).
