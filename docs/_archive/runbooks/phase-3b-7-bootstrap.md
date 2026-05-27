# Phase 3b.7 — manual smoke runbook (UX fixes bundle)

**Purpose:** Verify Sprint 3b.7 fixes em conta real — re-execute P1b dogfood
scenarios + spot-check enum decode em outras read tools.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `7862230676` "Mestre da Obra - João Pessoa" (active acquisition
campaigns — same conta exercida em P1b dogfood)

## Pre-flight

- [x] Deploy lands successfully (`gh run watch <id>` shows green Deploy)
- [x] Service `/health` returns 200
- [x] Reload MCP client (restart Claude Code session)

Production revision: `v4-ads-mcp-00121-kw7`.

## Test T1 — UX-1 tracking_warning em get_account_overview

```
get_account_overview(customer_id="7862230676", date_range="LAST_7_DAYS")
```

Expected:
- [x] `current` contém `tracking_warning` field com mensagem PT-BR mencionando "1:1 ratio" + "misleading"
- [x] `previous` também tem `tracking_warning` (se ratio 1:1 em ambos períodos)
- [x] Demais fields preserved (impressions, clicks, cost_brl, conversions, conversions_value_brl, roas)

**Result:** ✅ PASS. `current.tracking_warning` = `"conversions_value == conversions
(1:1 ratio). Tracking provavelmente sem revenue real — ROAS pode ser misleading."`.
`previous.tracking_warning` idem (ambos períodos 1:1). All baseline fields preserved.

## Test T2 — UX-1 negative case: real-tracking account

Tentar encontrar conta V4 que tenha real revenue tracking (value > count exato):

```
list_my_accounts()
```

Spot-check 2-3 accounts via:
```
get_account_overview(customer_id="<other_account>", date_range="LAST_7_DAYS")
```

Expected outcome A — conta encontrada com real tracking:
- [x] Response NÃO inclui `tracking_warning` field (real revenue tracking)
- [x] `roas` é número significativo (não 0.05 placeholder)

Expected outcome B — TODAS V4 accounts têm placeholder tracking:
- [ ] **Document as finding** — todas mostram warning → V4 setup pattern
      probavelmente não configura value-per-conversion. Spawn-task para
      V4 setup audit (out-of-MCP-scope).

**Result:** ✅ PASS (outcome A). **ML Antiguidades (`7455088726`)** retorna
`conversions: 293.0`, `conversions_value_brl: 150902.45`, `roas: 100.79`,
**SEM `tracking_warning` field** — confirma helper só dispara em 1:1 exato.
AOV calculado: R$ 515.03 (real e-commerce tracking). **Finding adicional:**
Expresso Turismo (`5295988089`) retorna `conversions: 95.0`,
`conversions_value_brl: 0.0` — tracking gap diferente (value=0, não 1:1),
helper corretamente não dispara mesmo com placeholder semelhante. Cobertura
empírica do helper validada em 3 shapes distintos (1:1 placeholder, real
revenue, zero-value).

## Test T3 — UX-1 funnel metrics validation

```
get_funnel_metrics(customer_id="7862230676", date_range="LAST_7_DAYS")
```

Expected:
- [x] `funnel.totals` contém `tracking_warning` quando 1:1 detectado
- [x] String PT-BR same content como T1

**Result:** ✅ PASS. `funnel.totals.tracking_warning` retorna mesma string PT-BR
de T1. `aov_brl: 1.0` confirma ratio 1:1 (cada conversão vale R$ 1.00 placeholder).
Demais funnel fields (impressions → clicks → conversions stages) preserved.

## Test T4 — UX-2 enum decode in get_campaign_performance

```
get_campaign_performance(customer_id="7862230676", date_range="LAST_7_DAYS", status="enabled")
```

Expected:
- [x] `status: "ENABLED"` (não mais `"2"`)
- [x] `type: "SEARCH"` (não mais `"2"`)
- [x] Other fields preserved (campaign_id, campaign_name, impressions, etc)

**Result:** ✅ PASS. Todas as campanhas retornaram `status: "ENABLED"` + `type:
"SEARCH"` legíveis. Antes do fix retornavam `"2"` em ambos campos. Demais
fields (campaign_id, campaign_name, impressions, clicks, cost_brl, conversions,
roas) preserved.

## Test T5 — UX-3 enum decode in get_search_terms_report

```
get_search_terms_report(customer_id="7862230676", date_range="LAST_7_DAYS", limit=10)
```

Expected:
- [x] `status: "NONE"`, `"ADDED"`, ou `"EXCLUDED"` (não mais `"2"`/`"5"`)
- [x] Decode alinha com tool description ("ADDED/EXCLUDED/NONE")
- [x] Other fields preserved (search_term, ad_group_name, campaign_name, etc)

**Result:** ✅ PASS. Search terms retornaram mix de `status: "ADDED"` (termos
já existentes como keyword) e `status: "NONE"` (termos não classificados).
Antes do fix retornavam `"2"`/`"5"`/`"6"`. Decoding alinhado com tool description.

## Test T6 — UX-2 spot-check em get_keyword_performance

```
get_keyword_performance(customer_id="7862230676", limit=5)
```

Expected:
- [x] `status: "ENABLED"` etc + `match_type: "EXACT"`/`"PHRASE"`/`"BROAD"` (não int)
- [x] Other fields preserved

**Result:** ✅ PASS. Keywords retornaram `match_type: "BROAD"`, `status: "ENABLED"`,
+ bonus enums `quality_score`, `creative_quality_score`, `post_click_quality_score`,
`search_predicted_ctr` legíveis (`"BELOW_AVERAGE"`/`"AVERAGE"`/etc). 6 enum
fields todos decoded corretamente — antes do fix retornavam ints.

## Test T7 — UX-2 spot-check em get_ad_performance

```
get_ad_performance(customer_id="7862230676", limit=3)
```

Expected:
- [x] `status: "ENABLED"`, `type: "RESPONSIVE_SEARCH_AD"` etc, `ad_strength: "GOOD"`/etc
- [x] Todos enum fields legíveis (não int)

**Result:** ✅ PASS. Ads retornaram `status: "ENABLED"`, `type:
"RESPONSIVE_SEARCH_AD"`, `ad_strength: "AVERAGE"`/`"GOOD"`. Todos os 3 enum
fields decoded corretamente — antes do fix retornavam ints.

## Cleanup

Zero — todas operations são read-only, nenhuma mutação.

## Sign-off final

- [x] T1-T3 UX-1 warning detection (both 1:1 and negative case)
- [x] T4-T7 UX-2/UX-3 enum decode em 4 tools (campaign + search_terms + keyword + ad)
- [x] No regressions (existing fields preserved)
- [x] T2 outcome documented (ML Antiguidades real tracking + Expresso zero-value
      tracking gap — V4 setup audit out of MCP scope)
- [x] Production revision verified (`v4-ads-mcp-00121-kw7`)
- [x] CLAUDE.md atualizado: Sprint 3b.7 shipped

**Date completed:** 2026-05-12

## Findings

1. **UX-1 helper coverage validated empiricamente em 3 shapes:**
   - Placeholder 1:1 (Mestre da Obra JP) → warning fires ✅
   - Real revenue (ML Antiguidades, R$ 515 AOV) → no warning ✅
   - Zero-value tracking gap (Expresso Turismo, value=0) → no warning ✅ (correct
     — different gap class, not 1:1)

2. **UX-2/UX-3 (mesmo bug) confirmado fix mecânico em 10 tools:** 22 call sites
   trocados de `str(enum).split(".")[-1]` para `.name`. proto-plus v20 repr
   regression resolvida sem side-effects (nenhum AttributeError nos genuine
   strings adjacentes).

3. **Bonus enum decodes encontrados em get_keyword_performance:** quality_*
   fields (4 enums adicionais) previamente também broken — fix capturou
   automaticamente ao varrer `.split(".")[-1]` no arquivo. Coverage maior que
   spec antecipou.

4. **Out-of-MCP-scope finding:** V4 accounts default à placeholder tracking
   (1:1 ou zero-value). ML Antiguidades é exceção com real revenue config —
   é o único caso "feliz" entre os 4 spot-checked. Sugestão para gestores:
   auditar config de conversion actions no Google Ads UI (separate concern).
