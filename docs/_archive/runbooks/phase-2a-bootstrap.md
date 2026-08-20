# Smoke Runbook — Fase 2A `get_performance_breakdown`

> **Gate humano (Wellington), pós-deploy.** A tool é **aditiva** (os 8 reports antigos seguem vivos) e **read-only**, então smoke-com-fix-forward é seguro: param/combo errado → erro friendly, sem blast radius. Plano: [`2026-06-20-google-performance-breakdown.md`](../superpowers/plans/2026-06-20-google-performance-breakdown.md).

## Pré-requisitos

1. **Deploy verde** (CI + Deploy `success`, `/health` 200).
2. **Reconectar a sessão MCP** pra ver a 63ª→64ª tool (F28: o cache de schema do cliente MCP não atualiza sozinho pós-deploy).
3. **Conta Google com atividade** — `customer_id` de 10 dígitos da MCC `6436352492` (ex: MO-JP / CAB, usadas nos smokes anteriores). Substituir `<CID>` abaixo.
4. Período com dados: `date_range=LAST_30_DAYS` (ou `LAST_90_DAYS` se a conta for low-volume).

## Parte A — 8 combos válidos (= os 8 reports atuais, 1:1)

Cada chamada deve retornar `status` ausente de erro (envelope `{customer_id, level, breakdown, period, rows}`) e o shape correto. Marcar ✅/❌.

| # | Chamada | Esperado | Resultado |
|---|---|---|---|
| 1 | `get_performance_breakdown(customer_id=<CID>, level=campaign)` | rows com `campaign_id/campaign_name/status/type` + métricas | ☐ |
| 2 | `…level=ad_group` | rows com `ad_group_id/ad_group_name/status/campaign_*` | ☐ |
| 3 | `…level=ad` | rows com `ad_id/status/type/ad_strength/headlines/descriptions/final_urls` | ☐ |
| 4 | `…level=keyword` | rows com `criterion_id/keyword_text/match_type/negative/quality_*/…cpc_brl` | ☐ |
| 5 | `…level=audience` | rows com `resource_name/criterion_id/user_list/user_interest_category` | ☐ |
| 6 | `…level=account, breakdown=device` | rows com `breakdown:{device}` (ex: MOBILE/DESKTOP/TABLET) | ☐ |
| 7 | `…level=account, breakdown=geo` | rows com `breakdown:{country_criterion_id, country_name, country_code}` — **`country_name` resolvido, não null** | ☐ |
| 8 | `…level=account, breakdown=hourly` | rows com `breakdown:{hour (0-23), day_of_week}` | ☐ |

## Parte B — 2 combos negativos (erro friendly)

| # | Chamada | Esperado | Resultado |
|---|---|---|---|
| 9 | `…level=account` (sem breakdown) | `{status:"error", error_message:…}` apontando `get_account_overview` | ☐ |
| 10 | `…level=campaign, breakdown=device` | `{status:"error", …}` "breakdown só em level=account no v0" | ☐ |

## Parte C — Parity cross-check (a validação-chave)

Rodar o report **antigo** e o **novo** no mesmo `<CID>` + período e conferir que as métricas batem (a consolidação não pode regredir). Mínimo: campaign + geo.

| Par | Antigo | Novo | Métricas batem? (cost_brl/impressions/clicks/conversions) |
|---|---|---|---|
| campaign | `get_campaign_performance(customer_id=<CID>)` | `get_performance_breakdown(customer_id=<CID>, level=campaign)` | ☐ |
| geo | `get_geo_performance(customer_id=<CID>)` | `get_performance_breakdown(customer_id=<CID>, level=account, breakdown=geo)` | ☐ |

> Nota de shape: no antigo `get_geo_performance` o país vem top-level (`country_name`); no novo vem aninhado em `breakdown.country_name`. As **métricas** é que devem bater bit-a-bit; o local da chave de dimensão mudou de propósito (simetria com o M.4).

## Resultado

- [ ] Parte A: __/8 combos válidos PASS
- [ ] Parte B: __/2 negativos PASS
- [ ] Parte C: parity campaign ✅/❌, geo ✅/❌
- [ ] Veredito: **GREEN** (libera Fase 2B — tombstone) / **fix-forward** (anotar o combo + ajuste)

Fix-forward (se preciso): combo errado é tipicamente 1 linha em `build_performance_breakdown_query` (dispatch) ou `parse_performance_row` (chave) → corrigir + redeploy (aditivo, read-only).
