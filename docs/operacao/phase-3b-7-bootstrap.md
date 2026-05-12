# Phase 3b.7 — manual smoke runbook (UX fixes bundle)

**Purpose:** Verify Sprint 3b.7 fixes em conta real — re-execute P1b dogfood
scenarios + spot-check enum decode em outras read tools.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `7862230676` "Mestre da Obra - João Pessoa" (active acquisition
campaigns — same conta exercida em P1b dogfood)

## Pre-flight

- [ ] Deploy lands successfully (`gh run watch <id>` shows green Deploy)
- [ ] Service `/health` returns 200
- [ ] Reload MCP client (restart Claude Code session)

## Test T1 — UX-1 tracking_warning em get_account_overview

```
get_account_overview(customer_id="7862230676", date_range="LAST_7_DAYS")
```

Expected:
- [ ] `current` contém `tracking_warning` field com mensagem PT-BR mencionando "1:1 ratio" + "misleading"
- [ ] `previous` também tem `tracking_warning` (se ratio 1:1 em ambos períodos)
- [ ] Demais fields preserved (impressions, clicks, cost_brl, conversions, conversions_value_brl, roas)

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
- [ ] Response NÃO inclui `tracking_warning` field (real revenue tracking)
- [ ] `roas` é número significativo (não 0.05 placeholder)

Expected outcome B — TODAS V4 accounts têm placeholder tracking:
- [ ] **Document as finding** — todas mostram warning → V4 setup pattern
      probavelmente não configura value-per-conversion. Spawn-task para
      V4 setup audit (out-of-MCP-scope).

## Test T3 — UX-1 funnel metrics validation

```
get_funnel_metrics(customer_id="7862230676", date_range="LAST_7_DAYS")
```

Expected:
- [ ] `funnel.totals` contém `tracking_warning` quando 1:1 detectado
- [ ] String PT-BR same content como T1

## Test T4 — UX-2 enum decode in get_campaign_performance

```
get_campaign_performance(customer_id="7862230676", date_range="LAST_7_DAYS", status="enabled")
```

Expected:
- [ ] `status: "ENABLED"` (não mais `"2"`)
- [ ] `type: "SEARCH"` (não mais `"2"`)
- [ ] Other fields preserved (campaign_id, campaign_name, impressions, etc)

## Test T5 — UX-3 enum decode in get_search_terms_report

```
get_search_terms_report(customer_id="7862230676", date_range="LAST_7_DAYS", limit=10)
```

Expected:
- [ ] `status: "NONE"`, `"ADDED"`, ou `"EXCLUDED"` (não mais `"2"`/`"5"`)
- [ ] Decode alinha com tool description ("ADDED/EXCLUDED/NONE")
- [ ] Other fields preserved (search_term, ad_group_name, campaign_name, etc)

## Test T6 — UX-2 spot-check em get_keyword_performance

```
get_keyword_performance(customer_id="7862230676", limit=5)
```

Expected:
- [ ] `status: "ENABLED"` etc + `match_type: "EXACT"`/`"PHRASE"`/`"BROAD"` (não int)
- [ ] Other fields preserved

## Test T7 — UX-2 spot-check em get_ad_performance

```
get_ad_performance(customer_id="7862230676", limit=3)
```

Expected:
- [ ] `status: "ENABLED"`, `type: "RESPONSIVE_SEARCH_AD"` etc, `ad_strength: "GOOD"`/etc
- [ ] Todos enum fields legíveis (não int)

## Cleanup

Zero — todas operations são read-only, nenhuma mutação.

## Sign-off final

- [ ] T1-T3 UX-1 warning detection (both 1:1 and negative case)
- [ ] T4-T7 UX-2/UX-3 enum decode em 4 tools (campaign + search_terms + keyword + ad)
- [ ] No regressions (existing fields preserved)
- [ ] T2 outcome documented (real-tracking found OR V4 setup gap noted)
- [ ] Production revision verified
- [ ] CLAUDE.md atualizado: Sprint 3b.7 shipped

**Date completed:** ____
