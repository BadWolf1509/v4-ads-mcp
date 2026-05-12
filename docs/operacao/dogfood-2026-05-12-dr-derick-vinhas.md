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

## Tools exercised (todas working)

- ✅ `list_my_accounts` — listou 23 contas, MCC bem populado
- ✅ `get_account_overview` — tracking_warning ✅, comparative ✅, enum decode ✅ (`type: "SEARCH"`)
- ✅ `get_campaign_performance` — 1 row, all enum fields legíveis
- ✅ `get_ad_group_performance` — 7 rows, ordering by cost desc ✅
- ✅ `get_search_terms_report` — 50 rows com status legível (`"ADDED"`, `"NONE"`), ad_group_name + campaign_name presentes ✅

**0 bugs encontrados nesta sessão.** Account exercitada em 5 read tools, todos os Sprint 3b.7 enum decode fixes confirmados na vertical médica.

## Recommended actions (gestor decision)

Curtas, prontas pra executar via MCP:

1. **Add negativas de concorrentes** (5 nomes) — usar `add_negatives_from_search_terms` ou `add_negative_keywords`. Esperado: ~R$ 16/mês economizados, redução de form fills lixo (spam de pessoas procurando outro médico).

2. **Add negativas informacionais (CAMPAIGN level, phrase match):**
   - `pediatra` (1 palavra)
   - `desodorante` (1 palavra)
   - `bombinha` (1 palavra)
   - `como tira` (phrase)
   - `exercicios` (1 palavra)
   - `tem cura` (phrase)
   - `o que significa` (phrase)
   - `sintomas cancer` (phrase — pode ser SUS-seeker)
   - Esperado: ~R$ 40-50/mês economizados, ad spend redirecionado pra intent comercial

3. **Restructure HIPERIDROSE ad group** (out of MCP scope, gestor faz na UI):
   - Investigar por que CPA é 2x média — pode ser landing page errada, ad copy fraco, ou KWs broad puxando tráfego ruim

4. **Restructure PECTUS + BROMIDROSE ad groups** (CTR <1%):
   - Provavelmente ad copy ou KWs precisam revisão

## Summary

**Sprint P2 + 3b.7 health check em vertical nova:** todos os fixes shipados funcionam corretamente. ROAS warning helper validated em 5 verticals distintas. Enum decode (UX-2/UX-3) sem regressions. Zero novos bugs encontrados.

**Real account-management value identified:** R$ 60+ mensais em desperdício de spend acionável via tools existentes (`add_negative_keywords` ou `add_negatives_from_search_terms`). Wellington pode executar a otimização nesta sessão se quiser.

**P3 outcome:** ✅ vertical nova exercitada sem surpresas técnicas, signal forte de produto (tools úteis pra gestor real fazer otimização de tráfego em conta médica).
