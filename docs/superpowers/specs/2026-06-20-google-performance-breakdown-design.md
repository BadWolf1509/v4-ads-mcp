# Fase 2A — `get_performance_breakdown` (consolidação aditiva dos reports Google)

> **Status:** design aprovado (brainstorming 2026-06-20). Próximo: `superpowers:writing-plans`.
> **Escopo:** Fase 2A apenas (tool nova, aditiva). O tombstone dos reports antigos é a **Fase 2B** (sprint separado, pós-soak) — fora deste design.
> **Anchor:** espelha `meta_get_performance_breakdown` (M.4, shipado + smoke green 2026-06-20). Refina a §6 de [`2026-05-25-architecture-refactor-design.md`](2026-05-25-architecture-refactor-design.md).

## 1. Objetivo

Consolidar os **8 reports Google de performance** numa tool única `get_performance_breakdown(level, breakdown)`, matando a duplicação (cada report repete `_DATE_PRESETS`, `_SCHEMA`, `_row_formatter`). **Aditivo:** a tool nova entra junto dos 8 antigos; nada é removido nesta fase.

Ganho permanente (−8 tools) só se materializa na Fase 2B, mas a duplicação morre já aqui (1 builder + 1 parser no lugar de 8).

## 2. Decisões do brainstorming (e desvios da spec §6)

| Decisão | Escolha | Motivo |
|---|---|---|
| **Sequenciamento** | Aditivo primeiro, tombstone na Fase 2B | 1º tombstone do projeto + 3 skills V4 dependentes → não remover sem dado de soak. Nada quebra durante a migração. |
| **account-level** | `get_account_overview` fica **separado pra sempre** (não consolida, não tombstona) | Retorna comparativo current/previous — shape distinto que não cabe no molde "rows" (como `get_funnel_metrics`/`get_budget_pacing`). |
| **device/geo/hourly** | `account` + breakdown (são account-level hoje: `FROM customer`/`geographic_view`) | Mapeia 1:1 o comportamento atual sem capability nova. |
| **breakdown nos entity levels** | **Fora do v0** (campaign+device etc. = Fase 2B/v1) | YAGNI + encolhe a matriz de smoke de ~15-20 pra 8 combos. |
| **filtros `campaign_ids[]`/`ad_group_ids[]`** | **Drop** (spec §6 propunha) | YAGNI — os reports atuais não filtram por isso. |
| **nome do param** | `breakdown` (não `dimension`); valores `device`/`geo`/`hourly` | Simetria com o M.4 — os dois tools viram irmãos idênticos no contrato. |
| **bucket** | `always` | É a tool de performance primária; substitui o `get_campaign_performance` (já always). |

## 3. Matriz válida (`_validate_combo`) — exatamente os 8 reports atuais

| level | breakdown | válido? | = report atual |
|---|---|---|---|
| campaign / ad_group / ad / keyword / audience | ausente | ✅ | os 5 entity reports |
| account | device / geo / hourly | ✅ | `get_device/geo/hourly_performance` |
| account | ausente | ❌ → aponta `get_account_overview` | (comparativo, tool própria) |
| {entity} | qualquer breakdown | ❌ → "breakdown só em level=account no v0" | (scoped breakdown = v1) |

`_validate_combo(level, breakdown) -> str | None` retorna mensagem PT-BR acionável ou `None`. **Sem `oneOf/allOf/anyOf`** no schema (convenção 3b.19B.1) — constraint cross-field só no helper.

## 4. A tool — `src/mcp/tools/get_performance_breakdown.py`

```
get_performance_breakdown(
  customer_id: str (^[0-9]{10}$, required),
  level: enum[campaign, ad_group, ad, keyword, audience, account] (required),
  breakdown: enum[device, geo, hourly] (optional),
  date_range: enum[TODAY..LAST_90_DAYS] (preset) OU start_date+end_date (custom, ^\d{4}-\d{2}-\d{2}$),
  status: enum[ENABLED, PAUSED, all] (optional, default ENABLED — só entity levels),
  limit: int 1..1000 (default 100),
)
```

- `bucket="always"`, `_meta` com `anthropic/alwaysLoad: true` (D3).
- Governança herdada de `run_report`: hard-gate `ensure_account_access` + rate-limit. **`audit_this_call=True`** desde o dia 1 (semeia o watch da Fase 2B).
- Resolve date window via `resolve_date_window` (`_common.py`).
- Padrão de erro: retorna `{"status":"error","error_message":...}` (igual aos reports atuais).

## 5. Módulo puro — `src/google_ads/performance_breakdown.py`

Zero-SDK, fully unit-testable (mesmo padrão de `insights.py` do M.4).

- `build_performance_breakdown_query(level, breakdown, status, start, end, limit) -> str`
  - Dispatch por `level`. Reusa os `*_query` de `performance.py`/`tactical.py` onde possível.
  - `breakdown` adiciona `segments.device` (device) / usa `geographic_view` + `geographic_view.country_criterion_id` (geo) / `segments.hour` + `segments.day_of_week` (hourly).
- `parse_performance_row(row, level, breakdown) -> dict`
  - Shape unificado: ids/names do level + `breakdown: {campo: valor}` (quando houver) + métricas comuns.
  - Métricas: `cost_brl` (micros→BRL via `micros_to_currency`), `impressions`, `clicks`, `conversions`, `conversions_value_brl`, `ctr`, `cpc_brl` (calculados; divisão-por-zero → 0).
  - **geo preserva o enrichment de nome de país** (`lookup_country_names`, hoje em `get_geo_performance`) — `breakdown: {country: "Brasil", country_criterion_id: "2076"}`.
- `_validate_combo(level, breakdown) -> str | None` (matriz §3).

## 6. Testes & smoke

**Unit (TDD, `tests/unit/test_performance_breakdown.py`):**
- `_validate_combo`: os 8 válidos retornam `None`; `account`+ausente e entity+breakdown retornam msg PT-BR.
- `parse_performance_row`: por level (ids/names corretos) + por breakdown (chave correta) + edge zero-divisão (impressions=0 → ctr/cpc=0).
- `build_performance_breakdown_query`: snapshot/asserção do SELECT+FROM por combo (sem rodar API).

**Integração (`tests/integration/test_get_performance_breakdown.py`):** mock `run_report` no namespace do tool; happy path por combo; guard de schema (sem composition keywords).

**Smoke (o GATE — runbook em `docs/operacao/`, nome do sprint atribuído no plano):** os **8 combos válidos** reais em conta Wellington (ML Antiguidades / MO-JP). Per-combo (lição 3b.19A.1 / F-findings). Confirma: geo→country_criterion_id mapeado + nome, device→enum Google (MOBILE/DESKTOP/TABLET), hourly→0-23. Aditivo → smoke pós-deploy com fix-forward (blast radius baixo, read-only).

## 7. Fora de escopo (Fase 2B — sprint futuro)

- **Tombstone** dos 8 reports antigos (§4.1 da spec de refactor) — só quando o watch via `audit_log` confirmar zero uso por 7d.
- **Atualizar as 3 skills V4** (`auditoria-google-ads`, `analise-performance-google-ads`, `relatorio-cliente-google-ads`) pra usar a tool nova — feito durante o soak (sem pressa; os antigos vivem).
- **Scoped breakdown** (entity + breakdown, ex: campaign+device).

## 8. Riscos

- **Combo GAQL rejeitado em runtime** (3b.19A.1): mitigado pelo smoke per-combo antes de declarar pronto. Matriz pequena (8) reduz a superfície.
- **geo enrichment**: `lookup_country_names` precisa ser portado fielmente (não regredir o nome do país).
- **Paridade de métricas**: o parser unificado deve bater bit-a-bit com os row_formatters atuais (cross-check no smoke).
