# Varredura de faxina (15/11): achados

> **Desenho:** [`2026-11-15-varredura-faxina-design.md`](../superpowers/specs/2026-11-15-varredura-faxina-design.md).
> **Só leitura:** nada foi alterado no código.
> **Detectores**, em venv descartável fora do projeto:
> - `vulture`, com confiança ≥ 60;
> - cobertura da suíte unit + integração não-DB: **90%**;
> - `pytest --durations`;
> - `pylint duplicate-code`, com ≥ 10 linhas;
> - links de docs;
> - uso das tools no `audit_log` (17/08–15/11, só SELECT).
>
> Quatro agentes de leitura (A: Google/MCP/governança · B: Meta/painel/db/jobs · C: testes · D: docs/scripts/CI) confirmaram cada candidato com a prova do uso. O detalhe de cada achado (onde, evidência, custo, risco, sugestão) está nos relatórios por área, mais abaixo.

## Resumo por parte proposta

As partes estão em ordem de ganho por risco. Cada uma vira um PR, se você escolher.

| parte | achados | ganho | risco | tamanho |
|---|---|---|---|---|
| **P1: Docs** | D-01 a D-06, D-09, D-11 | ~370 KB a menos na doc viva; fatos velhos corrigidos no `CLAUDE.md`, no README e no `nucleo.md`; subagente de smoke apontando para runbooks que existem | baixo | M |
| **P2: Gate mais rápido** | C-01, C-09 | os 3 guards AST somam **~2 min** sem coverage (55 s + 34 s + 33 s). 95% do tempo é `nomes_locais` refazendo `ast.walk` a cada chamada: memoizar não enfraquece a asserção | baixo | P |
| **P3: Código morto pontual** | A-06, A-07, B-02, B-03, B-05, B-06, B-07, D-12 | tira constante, dataclass, macro, alias, asset e helper sem nenhum uso; fecha 4 minors conferidos no código | baixo | P |
| **P4: Testes duplicados** | C-02 a C-05, C-07, C-08 | fixture de contexto MCP copiada em **~100 arquivos**; fakes de pool repetidos apesar de `fixtures/fake_pool.py`; 4 testes subsumidos pelo guard global; lista de tools escrita à mão 3× | médio | G |
| **P5: Duplicação em `src`** | A-03, A-05, A-08, B-08, B-09 | AUTO/CONFIRM repetido em 9 tools (~200 linhas); par de datas em 4 tools; loader gêmeo Google/Meta; bloco gêmeo nos dois `reconcile.py` | médio (snapshot de schema, rota) | M |
| **P6: Esqueleto dos executores** | A-02 | reserva de cota → chamada → reconcilia → audit copiado em 6 executores | **alto** (gate, cota, audit: F57/F73/F83/F91) | G |

**Fora da faxina, mas importante para o 02/12 (A-01):** a lista de "24 tools sem uso" estava errada.
- **15** são zero real.
- **8 não são medíveis:**
  - 5 leituras não gravam audit no sucesso (`get_budget_pacing`, `get_funnel_metrics`, `get_search_terms_report`, `get_top_keywords_creatives`, `get_negative_keywords_audit`);
  - `apply_change` grava sob o nome da tool aplicada;
  - `detect_drift` grava como `get_change_history`;
  - `meta_list_my_ad_accounts` não audita.
- **1 está em uso:** `audit_goal_attribution`.

Para decidir sobre uso no 02/12, essas 8 precisam passar a ser medidas, por audit no sucesso ou por log. Isso muda o comportamento do audit e é decisão sua. O inventário das 15 está em A-04, só como lista.

**Descartados por decisão registrada ou por prova:**
- **B-04:** `mark_inactive_except` fica, por decisão sua de 03/11 (uso de emergência).
- **D-07:** os runbooks `phase-3b-41..44` ficam, por causa do guard do F187.
- **D-10:** o `smoke-liveness.yml` fica dormente (F186).
- **D-08:** as sondas `scripts/probe_*` ficam, porque são citadas como proveniência no código.
- **B-01:** a cobertura baixa de `admin.py` e das rotas admin é artefato do recorte não-DB. O código está vivo e testado.
- Também saíram os falsos positivos do `vulture`: rotas, handlers e fixtures.

**Não medido:**
- cobertura com a integração de DB (testcontainers);
- uso real das 8 tools não medíveis;
- o efeito do P2 no tempo do CI, que só foi medido local.

---


## Relatório A


Base: 30.802 linhas nessas três áreas. Nenhum arquivo do repo foi editado. Ficaram de fora, por decisão registrada: os 8 reports antigos da Fase 2B (get_campaign/ad_group/ad/keyword/audience/device/geo/hourly_performance), a divisão do `recommendations.py` e `accounts*.html`.

### Achados

#### A-01 — ⭐ O `zero_90d` do JSON é enganoso: 9 dos 24 não são zero medido
- Onde: `src/google_ads/reports.py:49,138` (`audit_this_call: bool = False`: sucesso só grava com opt-in); `src/governance/dry_run.py:106` (preview grava `action_type=mutate, dry_run=true`); `src/mcp/tools/apply_change.py:106` (aplica com o `operation_type` da pendência).
- Evidência: leitura de cada tool. Zero real (preview ou leitura sempre grava): 15 tools. Não medível: `apply_change` (grava sob o nome da tool aplicada), `detect_drift` (grava `get_change_history`, `change_scan.py:284`), `get_budget_pacing`, `get_funnel_metrics`, `get_search_terms_report`, `get_top_keywords_creatives`, `get_negative_keywords_audit` (os 5 chamam `run_report` sem `audit_this_call`), `meta_list_my_ad_accounts` (não chama audit_log). `audit_goal_attribution` está usada: as ops `audit_goal_attribution_actions/_goals` constam em `operations_fora_do_registry`.
- Custo de manter hoje: decidir no 02/12 sobre a lista crua pode apontar como ociosa tool em uso.
- Risco de mexer: nenhum (só documento).
- Sugestão: documentar a tabela do Anexo 2 no handoff. Medir as 5 leituras exige ligar o opt-in de audit (muda comportamento do audit; decisão do Wellington) ou olhar logs do Cloud Run.
- Tamanho: P

#### A-02 — ⭐ Esqueleto reserva-de-cota → chamada → reconcilia → audit copiado em 6 executores
- Onde: `google_ads/reports.py:85,127`, `keyword_planning.py:79,131`, `customer_match.py:278,388`, `conversions.py:106,189`, `mutations.py:264,393` e `:487,529`.
- Evidência: `grep "reservar_cota("` = 6 chamadas; `grep "reconciliar_cota("` = 6; pylint aponta bloco duplicado `customer_match:[375:392]` × `keyword_planning:[122:135]`. O catálogo registra F73/F83/F91 como bugs desse esqueleto; é o padrão "conserto pegou só um gêmeo".
- Custo de manter hoje: cada correção de cota/audit precisa ser feita 6 vezes; é o ponto mais caro do núcleo.
- Risco de mexer: alto (cota, audit best-effort, ordem do `finally`; exige full sweep e caracterização de cada executor antes).
- Sugestão: simplificar com um gerenciador de contexto único (reserve/commit) em `governance/reserva.py`, em PR próprio e só com testes de caracterização por executor. Não misturar com faxina de baixo risco.
- Tamanho: G

#### A-03 — ⭐ Bifurcação AUTO/CONFIRM repetida em 9 tools de mutação
- Onde: `update_campaign_status.py:56-95`, `update_ad_group_status.py`, `update_ad_status.py`, `update_keyword_status.py`, `update_keyword_bid.py`, `update_ad_group_bid.py`, `update_conversion_action.py`, `add_keywords.py`, `apply_audience.py`.
- Evidência: `grep -c RiskLevel.AUTO` = 1 nos 9. `diff` de `update_ad_group_status.py` × `update_campaign_status.py` mostra só nome do campo, texto e operation; o corpo `classify → payload/summary → run_mutation+applied_envelope | emitir_preview` é idêntico. O pylint não pegou por causa das linhas variáveis.
- Custo de manter hoje: ~18-25 linhas × 9 ≈ 200 linhas; qualquer ajuste de envelope (como `efeito` do F180) exige 9 edições. `_mutate_common.py` já tem `emitir_preview` e `applied_envelope`, falta o passo que junta os dois.
- Risco de mexer: médio. O schema é guardado por `test_schemas_snapshot.py` e o corpo não o altera. Full sweep obrigatório (pré-flight de mutate). Atenção: 4 das 9 tools têm zero uso, então a prova em produção é fraca; a prova vem do teste.
- Sugestão: fundir num helper `aplicar_ou_pedir_confirmacao(...)` em `_mutate_common.py`.
- Tamanho: M

#### A-04 — ⭐ Peso de manutenção das 15 tools com zero uso real (só inventário; não sugiro remover)
- Onde (`wc -l`): `upload_customer_match_list` 221 + `customer_match.py` 509; `import_offline_conversions` 307 + `conversions.py` 334; `apply_audience` 319 + `remove_audience` 120 + `mutates/audiences.py` 105; `create_campaign` 214 + `mutates/campaigns.py` 278 (builders compartilhados com `update_campaign_budget`, usada); `create_conversion_value_rule_set` 250 + `mutates/conversion_value_rules.py` 141; `add_negatives_from_search_terms` 230; `apply_recommendation` 426 (+ `queries/recommendations.py` 988, compartilhado com `get_recommendations`, usada); `audit_orphan_smart_actions` 160 + `flag_orphan_smart_actions.py` 76; `update_campaign_status` 95, `update_campaign_bidding` 95, `update_keyword_bid` 153, `update_ad_group_bid` 145; `get_device_performance` e `get_hourly_performance` são Fase 2B.
- Evidência: Anexo 2.
- Custo de manter hoje: cerca de 2.900 linhas de tool e módulo exclusivos, mais testes e os `CONFIRMADORES` de `import_offline_conversions`, `upload_customer_match_list` e `apply_recommendation`.
- Risco de mexer: alto (removeria capacidade; fora de escopo por decisão registrada).
- Sugestão: só registrar; decidir depois do 02/12 e depois de A-01.
- Tamanho: G

#### A-05 — ⭐ Par start/end de data copiado em 3 tools de auditoria e em `detect_drift`
- Onde: `audit_quality_score.py:47-98`, `audit_zombie_keywords.py:38-86`, `audit_orphan_smart_actions.py:48-93` (pylint: blocos de 46-51 linhas idênticos entre os três) e `detect_drift.py`.
- Evidência: `grep -l "Data inicial YYYY-MM-DD"` lista esses arquivos além de `_common.py`, que já tem `_START_E_END` e `propriedades_de_data`. O `date_range` das 3 de auditoria tem descrição e enum próprios, então `propriedades_de_data` não encaixa direto.
- Custo de manter hoje: ~16 linhas × 4; baixo.
- Risco de mexer: baixo-médio (schema é contrato do handshake, `schemas_das_tools.json`).
- Sugestão: simplificar expondo `_START_E_END` e usando-o nos 4; não unificar o `date_range` (mudaria texto do contrato).
- Tamanho: P

#### A-06 — Código só usado por teste dentro de `src/`
- Onde: `google_ads/ad_schedule.py:140-145` (`ScheduleDiff.is_empty`, `.op_count`); `google_ads/campos_gaql.py:34` (`limpar_cache`); `mcp/context.py:25` (`clear_current`).
- Evidência: `grep "\.is_empty\b\|\.op_count\b"` em `src` = só a definição; os usos são `tests/unit/test_ad_schedule_domain.py:129-157`. `limpar_cache` só em `tests/unit/test_list_gaql_resources_compat.py:21,27`; `clear_current` em ~250 usos de teste (helper legítimo).
- Custo de manter hoje: ~6 linhas de src.
- Risco de mexer: baixo para `is_empty`/`op_count` (apagar e ajustar 4 linhas de teste); `clear_current` e `limpar_cache` ficam (infra de teste).
- Sugestão: remover só `is_empty`/`op_count` (ganho mínimo).
- Tamanho: P

#### A-07 — Restos mortos pontuais
- Onde: `governance/rate_limit.py:25` (`DAILY_QUOTA_STANDARD`); `mcp/server.py:52-54` (aliases `_Scope`, `_ASGIReceive`, `_ASGISend`).
- Evidência: os 3 aliases têm 1 ocorrência em `src`, `tests` e `scripts` (script de nomes); `Callable/Awaitable/MutableMapping` continuam usados em `server.py:184-188`. `DAILY_QUOTA_STANDARD` só aparece na definição e no comentário de `get_my_rate_limit_status.py:57`, que o descreve como valor-alvo quando o Standard Access for aprovado: pode ser intencional.
- Custo de manter hoje: 4 linhas.
- Risco de mexer: baixo.
- Sugestão: remover os 3 aliases; manter `DAILY_QUOTA_STANDARD`, que está documentado.
- Tamanho: P

#### A-08 — Boilerplate de schema entre tools de leitura e entre `create_rsa` e `update_rsa`
- Onde (pylint): `_meta_performance:[64:83]` × `meta_get_performance_breakdown:[76:95]`, `get_budget_pacing:[19:31]` × `get_recommendations:[16:28]`, `create_rsa:[43:62]` × `update_rsa:[84:104]` (arrays de headlines/descriptions), `get_search_terms_report:[61:95]` × `get_ad_performance:[85:116]` (este lado é Fase 2B).
- Evidência: leitura dos blocos em `duplicacao-src.txt`.
- Custo de manter hoje: baixo; parte da repetição é intencional (schema = contrato do handshake).
- Risco de mexer: médio (snapshot de schema).
- Sugestão: deixar. Só o par `_meta_performance` × `meta_get_performance_breakdown` merece fragmento comum se alguém mexer ali.
- Tamanho: P

### Descartados (falso positivo ou decisão registrada)
- vulture: ~84 "unused function" em `mcp/tools/*.py` — handlers com `@register_tool`; o registry os chama (`_registry._TOOLS`, `server.import_all_tools`).
- vulture: 27 `build_*` em `google_ads/mutates/*.py` — todos com `@register_builder` (27 de 27), resolvidos por `get_builder` (`mutates/_common.py:38`).
- vulture: atributos `remove`, `target_cpa_micros`, `hashed_email`, `gclid` etc. em `mutates/*`, `conversions.py`, `customer_match.py` — escrita em mensagens protobuf do SDK do Google Ads.
- vulture: `volume_mensal`, `concorrencia`... (`planejador.py:19-23`) e `provider_request_id_*`, `members_failed` (`resultados.py:60-65`) — campos de dataclass lidos por chave/atributo (`confirmadores.py:310-317`, `get_keyword_metrics`, testes).
- vulture: `intercept_unary_unary` (`request_id.py:47`) — método do protocolo do interceptor gRPC; testado em `test_request_id.py`.
- vulture: `mcp_endpoint` (`server.py:155`) — rota registrada; `validate_only`, `keyword_plan_network`, `page_size`, `locale` — campos de SDK/schema.
- Módulos órfãos: varredura de import nas três áreas — nenhum módulo sem importador em `src/`.
- coverage: baixa cobertura de `update_campaign_bidding` (30%), `update_keyword_status` (34%), `update_ad_group_status`/`update_campaign_status` (43%), `remove_negative_keywords` (47%), `update_conversion_action` (57%), `get_top_keywords_creatives` (61%), `account_clock` (35%), `dry_run` (65%), `google_ads_accounts` (68%) — há testes em `tests/integration/` (test_campaign_mutations, test_keyword_mutations, test_negative_keywords, test_update_conversion_action, test_client_report_tools, test_account_clock_db), que a medição "unit + integração não-DB" exclui. Não é lacuna medida.
- coverage: `mcp/server.py` 66% — endpoint ASGI; não medi onde é coberto.
- duplicacao: os 8 reports da Fase 2B (blocos de 19-73 linhas entre `get_{campaign,ad_group,ad,keyword,audience,device,geo,hourly}_performance`) e `performance_breakdown:[212:278]` × esses reports — Fase 2B travada.
- duplicacao `google_ads.reconcile` × `meta_ads.reconcile` — fora da minha área; já delegam a `reconciliacao.py`.
- `detect_drift` "sem uso": grava como `get_change_history` (A-01).

### Não medido
- Chamadas de `audit_goal_attribution` e `bulk_pause_by_query_dry_run`: o JSON só lista o nome em `operations_fora_do_registry`.
- Uso de `apply_change`, `detect_drift`, `get_budget_pacing`, `get_funnel_metrics`, `get_search_terms_report`, `get_top_keywords_creatives`, `get_negative_keywords_audit`, `meta_list_my_ad_accounts`: o audit_log não os registra. Fonte alternativa (logs do Cloud Run) não consultada: sem chamada externa.
- O JSON mistura preview (dry_run) e aplicação nas tools de mutação; não distingue só pré-visualizado de aplicado.
- `get_account_overview` (6 linhas): sem `audit_this_call`, só podem ser recusas ou erros; não verifiquei quais.
- `preflight.py` (1.194 linhas) e `confirmadores.py` (1.091 linhas): li só trechos; nada afirmado sobre simplificação interna.
- Linhas de teste das tools de A-04 não foram somadas.

### Anexo 1 — Mapeamento tool → operation(s) no audit_log (onde difere do nome da tool)
| Tool | Operations gravadas |
|---|---|
| `apply_change` | nenhuma própria; grava com o `operation_type` da pendência (ex. `update_campaign_budget`) |
| `detect_drift` | `get_change_history` (`change_scan.py:284`); `_frontier` e `_resolve_*` não auditam |
| `get_negative_keywords_audit` | `get_negative_keywords_audit`, `_creations` (sem opt-in: sucesso não grava) |
| `audit_goal_attribution` | `audit_goal_attribution_actions`, `audit_goal_attribution_goals` |
| `bulk_pause_by_query` | `bulk_pause_by_query_dry_run` (leitura), `bulk_pause_by_query` (preview/aplicação) |
| `apply_recommendation`, `update_campaign_budget`, `remove_ad`, `update_recommendation_subscription` | a própria + `<nome>_lookup` (`remove_ad` também `_enabled_por_grupo`) |
| `update_ad_schedule`, `get_ad_schedule`, `get_assets`, `get_experiments` | a própria, só nas consultas marcadas `audited=True` |
| `get_performance_breakdown`, `meta_get_ad_performance`, `meta_get_ad_set_performance`, `meta_get_campaign_performance` | o próprio nome (`audit_this_call=True`; Meta em `_meta_performance.py:210`) |
| `meta_list_my_ad_accounts` | nenhuma |
| Mutações em geral (`emitir_preview`) | preview grava `action_type=mutate, dry_run=true` com o nome da operação; a aplicação grava de novo |
| Leituras Google (`run_report`) | gravam sucesso só com `audit_this_call=True`; a negação de acesso grava sempre |

### Anexo 2 — Uso em 90 dias (17/08 a 15/11)
Zero real (15): `add_negatives_from_search_terms`, `apply_audience`, `apply_recommendation`, `create_campaign`, `create_conversion_value_rule_set`, `get_device_performance` (2B), `get_hourly_performance` (2B), `import_offline_conversions`, `remove_audience`, `update_ad_group_bid`, `update_campaign_bidding`, `update_campaign_status`, `update_keyword_bid`, `upload_customer_match_list`, `audit_orphan_smart_actions`.

Poucas chamadas e 1 gestor (observar, não remover): `bulk_pause_by_query` 1, `create_conversion_action` 1 (19/08), `update_conversion_action` 1 (19/08), `dismiss_recommendation` 1, `get_audience_performance` 1 (09/10), `list_gaql_resources` 1, `get_geo_performance` 2 (18/08), `get_experiments` 2, `meta_get_pages` 2.

Mais usadas: `run_gaql` 2153, `meta_get_account_overview` 877, `meta_get_account_balance` 828, `get_account_balance` 762, `get_campaign_performance` 583, `meta_get_campaign_performance` 392, `get_performance_breakdown` 363, `get_conversion_actions` 347, `validate_gaql` 319.

Tabela completa (83 tools do JSON; "chamadas / gestores / última data"):

| Tool | chamadas / gestores / última | situação |
|---|---|---|
| `add_keywords` | 27 / 3 / 2026-11-11 | usada |
| `add_negative_keywords` | 33 / 2 / 2026-11-14 | usada |
| `add_negatives_from_search_terms` | 0 / 0 / - | ZERO REAL |
| `apply_audience` | 0 / 0 / - | ZERO REAL |
| `apply_change` | 0 / 0 / - | NÃO MEDIDO (grava sob a tool aplicada) |
| `apply_recommendation` | 0 / 0 / - | ZERO REAL |
| `audit_competitor_keywords` | 10 / 3 / 2026-11-06 | usada |
| `audit_goal_attribution` | 0 / 0 / - | USADA (ops _actions/_goals; contagem fora do JSON) |
| `audit_orphan_smart_actions` | 0 / 0 / - | ZERO REAL |
| `audit_quality_score` | 7 / 2 / 2026-11-12 | usada |
| `audit_zombie_keywords` | 3 / 1 / 2026-11-14 | usada |
| `bulk_pause_by_query` | 1 / 1 / 2026-11-04 | usada |
| `create_ad_group` | 26 / 3 / 2026-11-11 | usada |
| `create_and_link_assets` | 6 / 2 / 2026-11-11 | usada |
| `create_campaign` | 0 / 0 / - | ZERO REAL |
| `create_conversion_action` | 1 / 1 / 2026-08-19 | usada |
| `create_conversion_value_rule_set` | 0 / 0 / - | ZERO REAL |
| `create_rsa` | 36 / 3 / 2026-11-15 | usada |
| `detect_drift` | 0 / 0 / - | NÃO MEDIDO (grava como get_change_history) |
| `dismiss_recommendation` | 1 / 1 / 2026-11-14 | usada |
| `get_account_balance` | 762 / 2 / 2026-11-14 | usada |
| `get_account_overview` | 6 / 1 / 2026-10-27 | usada? (6 linhas, sem opt-in: só recusas/erros) |
| `get_ad_group_performance` | 10 / 2 / 2026-10-29 | usada |
| `get_ad_performance` | 3 / 1 / 2026-10-15 | usada |
| `get_ad_schedule` | 19 / 1 / 2026-09-21 | usada |
| `get_assets` | 17 / 2 / 2026-11-14 | usada |
| `get_audience_performance` | 1 / 1 / 2026-10-09 | usada |
| `get_budget_pacing` | 0 / 0 / - | NÃO MEDIDO (leitura sem opt-in de audit) |
| `get_campaign_performance` | 583 / 6 / 2026-11-12 | usada |
| `get_change_history` | 164 / 2 / 2026-11-14 | usada |
| `get_conversion_actions` | 347 / 3 / 2026-11-14 | usada |
| `get_device_performance` | 0 / 0 / - | ZERO REAL |
| `get_experiments` | 2 / 1 / 2026-11-15 | usada |
| `get_funnel_metrics` | 0 / 0 / - | NÃO MEDIDO (leitura sem opt-in de audit) |
| `get_geo_performance` | 2 / 1 / 2026-08-18 | usada |
| `get_hourly_performance` | 0 / 0 / - | ZERO REAL |
| `get_keyword_metrics` | 14 / 2 / 2026-11-13 | usada |
| `get_keyword_performance` | 189 / 3 / 2026-10-29 | usada |
| `get_my_audit_log` | 26 / 1 / 2026-11-04 | usada |
| `get_my_rate_limit_status` | 5 / 2 / 2026-11-04 | usada |
| `get_negative_keywords_audit` | 0 / 0 / - | NÃO MEDIDO (leitura sem opt-in de audit) |
| `get_performance_breakdown` | 363 / 5 / 2026-11-14 | usada |
| `get_recommendations` | 5 / 1 / 2026-11-14 | usada |
| `get_search_terms_report` | 0 / 0 / - | NÃO MEDIDO (leitura sem opt-in de audit) |
| `get_top_keywords_creatives` | 0 / 0 / - | NÃO MEDIDO (leitura sem opt-in de audit) |
| `import_offline_conversions` | 0 / 0 / - | ZERO REAL |
| `list_gaql_resources` | 1 / 1 / 2026-11-14 | usada |
| `list_my_accounts` | 116 / 6 / 2026-11-14 | usada |
| `meta_get_account_balance` | 828 / 2 / 2026-11-14 | usada |
| `meta_get_account_overview` | 877 / 5 / 2026-11-11 | usada |
| `meta_get_ad_performance` | 50 / 5 / 2026-11-12 | usada |
| `meta_get_ad_preview` | 7 / 1 / 2026-11-02 | usada |
| `meta_get_ad_set_performance` | 213 / 3 / 2026-11-12 | usada |
| `meta_get_budget_pacing` | 23 / 1 / 2026-11-10 | usada |
| `meta_get_campaign_performance` | 392 / 5 / 2026-11-12 | usada |
| `meta_get_change_history` | 21 / 2 / 2026-11-11 | usada |
| `meta_get_creatives` | 21 / 2 / 2026-11-12 | usada |
| `meta_get_delivery_estimate` | 5 / 1 / 2026-11-02 | usada |
| `meta_get_entities` | 71 / 3 / 2026-11-13 | usada |
| `meta_get_pages` | 2 / 1 / 2026-11-02 | usada |
| `meta_get_performance_breakdown` | 11 / 3 / 2026-11-12 | usada |
| `meta_list_my_ad_accounts` | 0 / 0 / - | NÃO MEDIDO (tool não audita) |
| `meta_search_targeting` | 10 / 1 / 2026-11-02 | usada |
| `plan_keyword_ideas` | 17 / 2 / 2026-11-13 | usada |
| `remove_ad` | 2 / 1 / 2026-11-15 | usada |
| `remove_asset_link` | 4 / 1 / 2026-10-15 | usada |
| `remove_audience` | 0 / 0 / - | ZERO REAL |
| `remove_negative_keywords` | 14 / 1 / 2026-11-04 | usada |
| `run_gaql` | 2153 / 4 / 2026-11-15 | usada |
| `update_ad_group_bid` | 0 / 0 / - | ZERO REAL |
| `update_ad_group_status` | 10 / 2 / 2026-11-11 | usada |
| `update_ad_schedule` | 44 / 1 / 2026-09-21 | usada |
| `update_ad_status` | 5 / 1 / 2026-11-11 | usada |
| `update_campaign_bidding` | 0 / 0 / - | ZERO REAL |
| `update_campaign_budget` | 3 / 1 / 2026-11-04 | usada |
| `update_campaign_status` | 0 / 0 / - | ZERO REAL |
| `update_conversion_action` | 1 / 1 / 2026-08-19 | usada |
| `update_keyword_bid` | 0 / 0 / - | ZERO REAL |
| `update_keyword_status` | 10 / 3 / 2026-11-13 | usada |
| `update_recommendation_subscription` | 2 / 1 / 2026-11-14 | usada |
| `update_rsa` | 37 / 3 / 2026-11-14 | usada |
| `upload_customer_match_list` | 0 / 0 / - | ZERO REAL |
| `validate_gaql` | 319 / 2 / 2026-11-15 | usada |

## Relatório B


Método: vulture-60 e coverage.txt filtrados para a área; varredura própria de todo `def`/`class`/constante de topo da área contra `src/`, `tests/` e templates (contagem de ocorrências por palavra); conferência de rotas, jobs (`Procfile`, `deploy.yml`), templates, macros e estáticos.
Resumo: a área está enxuta. Código morto real é pequeno (4 itens); a cobertura baixa de `admin.py` e das rotas admin é artefato do recorte da medição, não risco.

### Achados

#### B-01 ⭐ — Cobertura baixa de `scripts/admin.py` e rotas admin é artefato da medição (não é código morto nem sem teste)
- Onde: `src/scripts/admin.py` (17%), `web/routes/admin_*.py`, `sessions.py`, `audit.py`, `jobs/restore.py`, `jobs/purge.py`, `db/migrate.py`, repos `managers`/`manager_account_access` (31–55%).
- Evidência: `coverage.txt` mede só unit + integração NÃO-DB (cabeçalho do brief). Existem testes DB que cobrem exatamente esses arquivos: `tests/integration/test_admin_script.py` (17 testes), `test_web_panel_admin.py`, `test_web_panel_sessions.py`, `test_web_panel_audit.py`, `test_web_panel_accounts.py`, `test_admin_meta_access.py`, `test_admin_access_idempotente.py`, `test_backup_restore.py`, `test_purge.py`, `test_managers_invite.py`; `migrate.run_all()` roda em todo `tests/integration/conftest.py:58` e em todo deploy (`Procfile:2`, `deploy.yml:119-121`). `admin.py` é CLI de operação documentada (docstring de uso + `findings-catalog.md:2044,6164`), código vivo.
- Custo de manter hoje: nenhum de código; o custo é o relatório de cobertura enganar a próxima varredura.
- Risco de mexer: n/a (não mexer).
- Sugestão: documentar — gerar o relatório de cobertura com o full sweep (Docker) antes de usá-lo como sinal de "sem teste". Nenhuma remoção.
- Tamanho: P (só nota na spec/handoff)

#### B-02 ⭐ — `MetaRateCounter` (dataclass) sem nenhum uso
- Onde: `src/db/repositories/meta_rate_counters.py:15-21`
- Evidência: varredura própria `src=0 tests=0`; grep `MetaRateCounter` só acha a definição. O módulo é vivo por `increment_calls`/`update_throttle` (`src/governance/rate_limit.py:263-282`) e o purge; só a classe é morta (os repos devolvem int, não a dataclass).
- Custo de manter hoje: baixo (7 linhas + imports `dataclass`/`date` só dela, e campos que o vulture marca).
- Risco de mexer: baixo — nenhum teste nem template referencia.
- Sugestão: remover a classe e os imports que sobrarem.
- Tamanho: P

#### B-03 ⭐ — `META_EFFECTIVE_STATUS_LABELS` sem nenhum uso
- Onde: `src/meta_ads/labels.py:45-56`
- Evidência: varredura `src=0 tests=0`; só aparece em docs (`findings-catalog.md`, `sprint-history.md`, plano 2026-11-10). A irmã (dict de `account_status`, linhas ~20-43) é usada.
- Custo de manter hoje: baixo, mas é tradução PT-BR que ninguém renderiza e tende a divergir do enum real da Meta.
- Risco de mexer: baixo.
- Sugestão: remover (ou, se a tool de entidades vier a traduzir status, reintroduzir com consumidor + teste).
- Tamanho: P

#### B-04 ⭐ — `mark_inactive_except` só tem chamador em teste (caminho "de emergência" sem chamador por design)
- Onde: `src/db/repositories/google_ads_accounts.py:206-~250` e `tests/integration/test_repositories.py:204`
- Evidência: grep em `src/`: nenhuma chamada fora da própria docstring/comentários (`account_resync.py:298` cita em comentário; `meta_ad_accounts.py:176` comenta que a forma antiga foi removida). A docstring (linhas 161-166, 208-217) admite "SEM chamador por design (decisão registrada, F85)". Substituída por `build_plan()` + `deactivate()` (`account_resync.py:169`).
- Custo de manter hoje: ~50 linhas + teste + docstring longa + citações cruzadas; o lado Meta já a removeu, então Google e Meta estão assimétricos.
- Risco de mexer: médio — é decisão registrada (F85), com guard de lista vazia. Remover exige tirar também o teste e atualizar os comentários que a citam (`google_ads_accounts.py:161-166`, `account_resync.py:298`, `meta_ad_accounts.py:176`, migration 008 só comentário, não editar). Alternativa mais barata: mover para script de operação ou deixar como está.
- Sugestão: decisão do Wellington (remover, alinhando ao Meta, ou manter). Não remover sem aval nominal.
- Tamanho: P

#### B-05 — Macro `radio` em `_components.html` sem uso
- Onde: `src/web/templates/_components.html:55-61`
- Evidência: `grep -rn radio src/web/templates | grep -v _components.html` → vazio; nenhum `{% from … import radio %}` nem chamada. Demais macros têm uso (`tooltip` 1 uso em `audit.html:85`, `form_group` 2, `cursor_pagination` 2).
- Custo: ~7 linhas; trivial.
- Risco de mexer: baixo (teste de templates não referencia; confirmar com `tests/unit` que lista macros, se houver, e rodar `tests/browser`).
- Sugestão: remover.
- Tamanho: P

#### B-06 — Estático `logo_v4_puro_round_transparente.svg` sem referência
- Onde: `src/web/static/logo/logo_v4_puro_round_transparente.svg` (585 bytes)
- Evidência: nenhuma referência em `src/` (templates/py/css); só `docs/operacao/infra-setup.md:247` ("reserva… para dark-mode/footer futuro"). O irmão `logo_v4_puro_round.svg` tem 4 referências.
- Custo: desprezível.
- Risco: baixo; é reserva intencional.
- Sugestão: remover ou deixar; ganho mínimo.
- Tamanho: P

#### B-07 — Alias de tipo `Breakdown` sem uso
- Onde: `src/meta_ads/insights.py:29`
- Evidência: único hit é a própria definição (grep `\bBreakdown\b` em `src`, `tests`); `tests/unit/test_meta_insights.py:297` é só comentário. `BREAKDOWN_META_PARAM` (mesmo arquivo, linha 35) é usado e não é o alvo.
- Custo/risco: 1 linha, baixo; a `Literal` documenta os valores, mas nada a tipa.
- Sugestão: remover, ou usar para tipar o parâmetro de `build_insights_call` (preferível: dá o guard de tipo que o alias parecia prometer).
- Tamanho: P

#### B-08 — Loader duplicado nas rotas gêmeas de acesso Google/Meta
- Onde: `src/web/routes/admin_access.py` — pares `admin_access`/`admin_access_meta` (~linhas 40-100), `by_manager`/`meta_by_manager`, `manager_detail`/`meta_manager_detail` (arquivo de 392 linhas, 11 handlers vulture-60, todos falso positivo por serem rotas).
- Evidência: `_load(conn)` e o `TemplateResponse` repetem a mesma forma 3 vezes por plataforma; a lógica de mutação já está unificada via `PLATAFORMAS[...]` (`_acesso.py`) + `aplicar_toggle`/`conceder_em_massa`/`copiar_acessos`; as listas de leitura diferem por repositório (`manager_account_access` vs `manager_meta_account_access`). Templates já são compartilhados (`access.html` etc.).
- Custo de manter hoje: médio-baixo; nova plataforma ou novo filtro exige editar 6 handlers.
- Risco de mexer: médio — rotas do painel em produção, `tests/browser` e integração DB precisam rodar (full sweep).
- Sugestão: simplificar, empurrando as 3 leituras para métodos de `Plataforma` (como já foi feito com a escrita). Ganho moderado; só vale se uma 3ª plataforma estiver no horizonte.
- Tamanho: M

#### B-09 — Bloco duplicado `google_ads/reconcile.py:89-104` × `meta_ads/reconcile.py:102-120`
- Onde: os dois `reconcile.py` (montagem de `Plan` a partir do plano do núcleo).
- Evidência: `duplicacao-src.txt:1010-1030`; os dois já delegam ao núcleo `src/reconciliacao.py`, restando só a cópia de campos do `Plan`.
- Custo: ~15 linhas, com comentário explicativo que só aplica a um dos lados.
- Risco de mexer: médio (reconciliação revoga acesso; F85/F93/F157). Ganho pequeno.
- Sugestão: documentar/aceitar. Só fundir se o núcleo passar a devolver `Plan` direto.
- Tamanho: P

### Descartados (falso positivo ou decisão registrada)
- Rotas FastAPI (~50 itens vulture em `web/routes/*`, `app.py:67,143`, `auth/oauth.py:146,240`, `auth/meta_data_deletion.py:71`) — registradas por decorator `@router.*`/`@app.*`; os testes de integração as chamam por URL (`tests/integration/test_web_panel_*`). A varredura própria listou 24 handlers "src=0" e todos são rotas de decorator.
- `web/middleware.py:100,128 dispatch` — método de `BaseHTTPMiddleware`, chamado pelo Starlette.
- `config.py:12 model_config`, `config.py:93 validate_customer_id_format`, `config.py:95 cls` — pydantic (`field_validator` em `google_ads_login_customer_id`, linha 93-98).
- `meta_ads/criativos.py:179 handle_starttag` — override de `HTMLParser`.
- `_acesso.py:50,52,54 campo_nome_conta/sufixo_id/e_meta` — usados em `admin/access.html`, `access_by_manager.html`, `access_manager_detail.html`.
- `synced_at`, `invited_at`, `su_reachable`, `last_throttle_pct`, `calls_used` (campos de dataclass/colunas de repositório) — usados em SQL, templates, `reconciliacao.py`, `alcance.py`, `rate_limit.py`, testes.
- `src/jobs/restore.py` (43%), `purge.py` (40%), `account_resync.py`, `meta_resync.py`, `backup.py` — vivos: `Procfile:3-4` (resync, backup), purge chamado no resync diário (`infra-setup.md:17,20`), `meta_resync` é piggyback do resync, `restore` é job de DR do `backup-restore-runbook.md` com `tests/integration/test_backup_restore.py`.
- `src/scripts/admin.py` — CLI documentada e testada (ver B-01).
- `error.html`, `oauth_conectado.html` (contagem zero na minha heurística por nome de arquivo) — usados em `src/app.py:180` e `src/auth/oauth.py:525,534`.
- `admin/accounts.html` × `admin/accounts_meta.html` — decisão registrada, fora do escopo.
- CSS do Tailwind gerado (`v4-tailwind.css`) — gerado e commitado, não conta como duplicação.
- Fase 2B, `recommendations.py`, remoção de tools — fora do escopo.
- `meta_ads/saldo.py` × `src/saldo.py` — funções distintas (`montar_saldo_meta`/parser de texto vs. classificação por série diária); sem sobreposição medida.

### Não medido
- Código morto "um nível acima": varredura própria só vê nome sem referência; função usada apenas por outra função morta não é detectada (ex.: helpers privados que só `mark_inactive_except` chame — não verificado).
- `src/db/repositories/*` e `src/auth/*` foram cobertos pela varredura de nomes; não li o corpo de cada função em busca de ramos mortos.
- Tamanho de custo de manutenção dos templates (`admin/access.html` 149 linhas, etc.): não medi duplicação de HTML entre templates (o pylint só olha Python).
- Cobertura real das rotas admin: não reexecutei o full sweep com cobertura (exigiria Docker); a afirmação de B-01 se apoia na existência e no alvo dos testes DB, não em percentual medido.
- Estáticos: confirmado uso de `htmx`, `v4-*.css` e `v4-panel.js` por referência de nome em templates/py (contagem ≥2); não verifiquei se há regras CSS mortas dentro deles.

## Relatório C


Escopo medido: 487 arquivos versionados em `tests/` (474 `.py`; unit 379, integration 86, browser 2), ~96 mil linhas. Nenhum `.pyc`, `__pycache__`, `.coverage` ou `.prof` versionado (`git ls-files tests | grep pyc` = 0; `__pycache__` está no `.gitignore`).

### Achados

#### C-01 ⭐ — Guards AST lentos: `nomes_locais` refaz um `ast.walk` do módulo inteiro a cada chamada (não é reparse)
- Onde: `tests/unit/_guard_harness.py:342` (`nomes_locais`), chamada por `chama()` (:436), `chama_no_corpo_proprio()` (:775) e direto em `test_executor_gates.py:233`, `test_filters_applied_e_derivado.py:423`.
- Evidência (medido, sem coverage, `-p no:cacheprovider`):
  - `test_chamada_de_funcao_de_query_em_teste_desempacota_a_tupla` = 55,2 s; `test_every_mutate_builder_has_a_builder_test` = 33,9 s; `test_todo_call_site_do_gate_declara_o_nivel` = 32,6 s. Soma 122 s (sob coverage eram 95+67+61 = 223 s).
  - cProfile do guard de call-sites do gate: 113 s sob profiler, 6.960 chamadas a `nomes_locais` = 108 s cumulativos (95%), 7,8 milhões de visitas de `ast.walk`. O parse em si é barato: `h.arvore` sobre os 474 testes = 2,7 s e sobre os 268 de src = 1,6 s (medido).
  - Causa em cada um: (a) `test_executor_gates.py:233` chama `h.nomes_locais(arv, "ensure_account_access")` DENTRO do laço de cada `ast.Call` (O(chamadas × nós) por arquivo; o resultado é o mesmo para o arquivo todo); (b) `test_every_mutate_builder...` chama `h.chama(arv, fn.__name__, arv=arv)` para cada builder (~60) × cada árvore (~400), e cada `chama` refaz `nomes_locais` (walk) mais outro walk; (c) `test_filters_applied...:423` faz `{alias for n in nomes for alias in h.nomes_locais(arv, n)}` — um walk por nome × arquivo, e ainda monta o mapa de pais por walk.
  - `test_structural_guards` (30 s, 18 s, 16 s) usa as mesmas primitivas via `chama_no_corpo_proprio`/`escopos_pais` (mesmo padrão; o perfil de 30 s/18 s/16 s não foi medido sem coverage nem perfilado).
- Custo de manter hoje: ~120 s de gate (sem coverage) em 3 testes; ~223 s sob coverage no CI. Dá para ganhar mais de 200 s sem tirar nenhuma asserção.
- Risco de mexer: baixo. Compartilhar não enfraquece o guard se for só memoização com a mesma semântica: (1) mapa `alvo -> aliases` calculado uma vez por árvore dentro do harness (cache por `id(arv)` mantendo a árvore viva, ou `functools.cache` sobre um helper que receba o path); (2) içar `nomes_locais` para fora do laço em `_call_sites_do_gate`; (3) em `test_every_mutate_builder...`, um conjunto único de nomes chamados por árvore (um walk por árvore, não por builder). Cache de `arvore()` por (path, mtime) também é seguro: grep por mutação de árvore em tests (`NodeTransformer`, atribuição a `.body`, `.parent =`) = 0 ocorrências fora de `test_guard_harness`. O ganho do cache de parse sozinho seria só ~4 s por guard que varre tudo (36 arquivos varrem `fontes_py`/`testes_py`, 56 chamadas a `arvore`), então a memoização de `nomes_locais` é a parte que vale. Exige sabotagem de controle (o guard continua vermelho contra o código pré-fix) por ser mudança no harness.
- Sugestão: simplificar (memoizar no harness) + corrigir os 3 call-sites. Manter as asserções.
- Tamanho: P/M

#### C-02 ⭐ — A mesma fixture de contexto MCP copiada em ~100 arquivos de teste
- Onde: fixture `_ctx` (autouse ou não) em 70 arquivos (`grep -rl "^def _ctx" tests`); `bound_context` em 23; `session_ctx` em 19+ (hashing AST de funções top-level idênticas em ≥2 arquivos, ver script abaixo). Ex.: `test_update_keyword_bid.py:11`, `test_remove_ad.py:85`, `test_audit_quality_score.py`, `test_add_keywords.py`.
- Evidência (AST, ignorando nome e docstring): 24 cópias `autouse` literalmente iguais com o import local (`set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4())); yield; clear_current()`), 22 iguais sem o import, 11 variantes que `yield ctx`, 3+ não autouse; `bound_context` 23 cópias idênticas; `session_ctx` 19. Mais ~15 variantes com stub de `_hoje` (`date(2026, 5, 15)`), que já duplicam o que `tests/conftest.py:114` (`_relogio_da_conta_stubado`) faz globalmente.
- Custo de manter hoje: ~100 definições de 5 a 11 linhas (~600 linhas); mudar o contrato do contexto (campo novo em `McpRequestContext`) pede editar ~100 arquivos.
- Risco de mexer: médio. A fixture autouse em `tests/conftest.py` mudaria o estado de testes que NÃO querem contexto (alguns testam justamente a ausência dele, por ex. `get_current()` levantando); caminho seguro é fixture NÃO-autouse compartilhada (`tests/unit/conftest.py` ou `fixtures/`) com nomes `ctx_mcp`, e migrar por grupo, comparando o conjunto de testes passando antes/depois. Não medi quais arquivos dependem da ausência do contexto.
- Sugestão: fundir (uma fixture compartilhada + helper `com_contexto(...)` para a variante que devolve `ctx`).
- Tamanho: M

#### C-03 ⭐ — Fixtures de pool/conexão duplicadas apesar de `fixtures/fake_pool.py`
- Onde: `_pool_with_transactable_conn` ×9 (`test_executor_bookkeeping_never_masks.py`, `test_mutations_partial_failure.py`, `test_reports_params_summary.py`, `test_run_conversion_upload_quota_reserve.py`, `test_run_keyword_planning.py`, `test_run_mutation_quota_reserve.py`, …); `_pool_with_conn` ×2; `_pool` ×2+3; `_FakeAcquire`/`_FakePool` ×3 (`test_db_connection.py:29`, `test_health_resilience.py:22`, `test_hot_reads_reconnect.py:45`); `_fake_client` ×3; `_client_with_responses` (51 linhas) ×3 (`test_add_keywords.py`, `test_apply_audience.py`, `test_remove_audience.py`); `_fake_success_client` ×2.
- Evidência: hash AST de função top-level igual em ≥2 arquivos (script no scratchpad). `tests/unit/fixtures/fake_pool.py` já existe e é usado por 32 arquivos, mas só modela "um conn"; as 3 `_FakePool` entregam conexões em sequência (semântica diferente, `acquires` contado) e as `_pool_with_transactable_conn` precisam de `conn.transaction()`.
- Custo de manter hoje: ~40 helpers repetidos; um deles (`_client_with_responses`, 51 linhas) triplicado.
- Risco de mexer: baixo. Mover para `fixtures/fake_pool.py` (`SequentialPool`, `pool_com_transacao`) e importar.
- Sugestão: fundir
- Tamanho: M

#### C-04 ⭐ — Quatro testes por-tool de "sem oneOf/allOf/anyOf" subsumidos pelo guard global
- Onde: `test_create_and_link_assets.py:196`, `test_import_offline_conversions.py:173`, `test_update_conversion_action.py:10`, `test_upload_customer_match_list.py:14` — todos `json.dumps(_SCHEMA)` + `'"oneOf"' not in ...`.
- Evidência: `test_tools_schemas.py:23::test_no_composition_keywords_in_any_schema` varre o registry inteiro, recursivo (path por chave/índice), com mensagem de ofensor; é o guard citado em `docs/convencoes/testes.md`. O teste por-tool por substring de JSON é mais fraco e cobre só uma tool. Os testes por-tool `test_schema_explicit_types` (`test_update_conversion_action.py:20`, `test_upload_customer_match_list.py:23`) NÃO têm equivalente global — não os remover: ou promover a um guard registry-wide (`test_every_tool_has_explicit_property_types`, ainda inexistente) ou mantê-los.
- Custo de manter hoje: 4 testes + ~35 linhas; baixo, mas é duplicata exata do mecanismo mais crítico (a classe que derrubou sessão inteira 2×).
- Risco de mexer: baixo (a duplicata que cobre está citada acima).
- Sugestão: remover os 4 de composição; promover `explicit_types` a guard global.
- Tamanho: P

#### C-05 — Lista de nomes de tool escrita à mão 3× e já defasada
- Onde: `tests/unit/test_tools_schemas.py:185` (`test_all_phase_2_tools_registered`, docstring ainda diz "31 tools"), `:277` (`test_no_unexpected_tools`), mais o nome de cada tool em `fixtures/schemas_das_tools.json` (snapshot de 201 KB, `test_schemas_snapshot.py`).
- Evidência: o `expected` de `test_all_phase_2_tools_registered` é subconjunto do de `test_no_unexpected_tools` (a primeira lista termina em `get_performance_breakdown`, a segunda continua; mesma ordem e comentários de sprint). `test_no_unexpected_tools` (igualdade? ver :277-368, só li o início) cobre a primeira por construção se for `==`; não confirmei se é `==` ou `<=`.
- Custo de manter hoje: tool nova pede editar 2 listas + regerar o snapshot.
- Risco de mexer: baixo; confirmar antes se `test_no_unexpected_tools` é igualdade exata. O snapshot já falha em qualquer tool nova/removida.
- Sugestão: fundir (manter uma lista) ou derivar de `uso-tools`/snapshot.
- Tamanho: P

#### C-06 — Arquivos de teste muito fragmentados por assunto (fundir)
- Onde: `test_export_csv_days_tem_teto.py` (91 l), `_escopo_explicito`, `_prova_completude`, `_tem_teto_de_linhas` (102 l) — 4 arquivos para a mesma rota `/audit/export.csv`; `test_meta_erro.py` (77) + `test_meta_erro_de_entrada.py` (16 l, 1 teste) + `test_meta_errors.py` (260); `test_meta_sort_server_side.py` (89) + `test_meta_ordenacao_sem_gasto.py` (79); `test_meta_sem_estimated_calls.py` (17 l, 1 teste); `test_arrays_de_tool_tem_teto.py`; `test_apply_change*.py` (7 arquivos: base, `_ad_schedule`, `_assinatura`, `_caracterizacao` 640 l, `_recomendacao`, `_remove_ad`, `_rsa_estado`).
- Evidência: docstrings/lista de testes lidos; assuntos coincidem (não comparei asserção a asserção, então NÃO há prova de redundância de asserção, só de fragmentação).
- Custo de manter hoje: navegação e imports/helper repetidos; não é peso de execução.
- Risco de mexer: baixo (mover testes) a médio (renomear nodeids que o `docs/` cita).
- Sugestão: fundir os do export CSV e os dois de `meta_erro*` no mesmo arquivo.
- Tamanho: M

#### C-07 — Guard de "SDK facebook_business não volta" sem mais sujeito
- Onde: `tests/unit/test_meta_errors.py:215` e `:236` (`test_errors_py_nao_depende_mais_do_sdk_facebook_business`, `test_meta_graph_http_error_retryable_mesmo_sem_o_sdk_instalado`).
- Evidência: `facebook` não aparece em `pyproject.toml`/lockfiles; o segundo teste diz na própria docstring "o acoplamento que este teste perseguia é hoje impossível POR CONSTRUÇÃO" e o `patch.dict(sys.modules, {...: None})` não faz nada sem import. A asserção de fundo (5xx retryable) está também em `:190` (502) — não confirmei que ele afirma `retryable`.
- Custo de manter hoje: ~50 linhas de docstring/teste para um cenário que não existe. Também `test_meta_secret_leak.py:150`, `test_meta_token_nao_vaza_em_erro.py:3` e `test_meta_client.py:4` têm cabeçalhos de história do SDK removido (documentação, não código).
- Risco de mexer: baixo para o segundo teste (o primeiro é guard de dependência; mantê-lo se quiser trava anti-regressão).
- Sugestão: simplificar (remover o 2º, ou fundi-lo com o de 502 como assert de retryable).
- Tamanho: P

#### C-08 — Helpers duplicados entre guards "gate exige conta ativa"
- Onde: `_e_conjuncao_pura` ×3, `_tem_join_puro_para` ×3, `_achar_funcao` ×4, `_sql_sem_docstring` ×2, `_tem_predicado_bem_formado` ×2 em `test_gate_google_exige_conta_ativa.py`, `test_gate_meta_exige_conta_ativa.py`, `test_list_queues_google_predicado_is_active.py`, `test_fila_saiu_da_parceria_alcanca_a_volta.py`.
- Evidência: hash AST; o harness (`_guard_harness.py`) é o "dono da varredura" por `convencoes/testes.md`, mas estes helpers de SQL/AST ficaram locais. Mesma observação em `_negacao_real`/`_inventario`/`_ConnComMoeda` (`test_meta_get_entities_tool.py` e `test_meta_pacing.py`), `_make_signed_request` (2), `_FakeError*` (`test_google_ads_client.py` e `test_google_errors.py`), `_admin_cookie` (2).
- Custo de manter hoje: 4 cópias do detector de uma mesma propriedade; corrigir um buraco numa cópia não corrige as outras (o exato modo que o F155 descreve).
- Risco de mexer: médio (guard — mover helper para o harness exige controle positivo de cada detector).
- Sugestão: fundir em `_guard_harness`.
- Tamanho: M

#### C-09 — Mapa de pais da AST reconstruído em 6+ lugares
- Onde: `test_filters_applied_e_derivado.py:373`, `test_executor_gates.py:191`, `test_declaracao_de_truncamento.py:175`, `test_ratchet_camadas.py:104/145`, `test_structural_guards.py:830/1255`; o harness já tem `escopos_pais`.
- Evidência: `grep -rn "ast.iter_child_nodes(no)" tests`. Cada um com construção própria do mesmo "filho -> pai" (versão com `ast.walk` O(n²) em `test_filters_applied` :373).
- Custo de manter hoje: leve duplicação; vira lentidão onde a construção é feita por chamada (ver C-01).
- Risco de mexer: médio (guards).
- Sugestão: fundir (harness expõe `pais(arv)` memoizado).
- Tamanho: P

### Descartados (falso positivo ou decisão registrada)
- Fixtures de `tests/conftest.py` e `tests/integration/conftest.py` (`_test_env`, `client`, `pg`, `pg_dsn`, `db`, `app_with_db`, `_relogio_da_conta_stubado`) — todas usadas (`pg_dsn` em 3 testes; `client` por nome de parâmetro em 36 arquivos unit; autouse). Nada sem leitor.
- `tests/unit/fixtures/{fake_pool,proto_capture}.py` — 32 e 29 arquivos usam; `fixtures/schemas_das_tools.json` (201 KB) lido por `test_schemas_snapshot.py`; `tabela_de_rotas.json` por 2 testes; `grade_de_horario_caracterizacao.json` por 3; `acesso_snapshot/*.html` (10 arquivos) por `test_acesso_templates_snapshot.py`; `fixtures_guards/` por `test_guard_harness.py`; `_meta_formas_medidas.py` por 3 testes. Nenhum fixture grande órfão (os 369 KB de fixtures têm leitor).
- `tests/integration/_seed.py`, `_audiencia.py` — helpers com 2 a 26 usos cada (`state_da_url` e `patch_pool` têm só 2 usos, mas vivos).
- Artefatos versionados: nenhum (0 `.pyc`, 0 `__pycache__` rastreados).
- Testes de tool/recurso removido do src: não achei (guards de "SDK facebook_business" estão em C-07, não é tool). `test_oauth_meta_pessoal_removido.py` é guard anti-regressão de rota removida, mantém sujeito (usa `tabela_de_rotas.json`).
- `test_proto_capture_fixture.py` (7 testes do próprio `make_capture_client`) — testa a ferramenta de teste citada em `convencoes/testes.md`; manter.
- `test_declaracao_de_truncamento.py` × `test_tools_declaram_truncamento.py` × `test_builders_pedem_a_linha_sentinela.py` × `test_unbounded_reads_have_limit.py` — parecem sobrepostos, mas lidos os docstrings: um é propriedade AST do registry (declara `truncated`), outro é comportamento por tool (corta e avisa, par `nao_cortou`), outro exige `limit + 1` no builder. Distintos; NÃO propor remover sem comparar asserção por asserção (não feito).
- `test_drift_detection.py` (módulo puro, 21 testes) × `test_detect_drift.py` (teto/varredura da tool, 13 testes) — camadas diferentes.
- `test_meta_secret_leak.py` × `test_meta_token_nao_vaza_em_erro.py` — sinks diferentes (URL do httpx no log × mensagem/audit/log estruturado), docstrings distintas.
- `test_tooling_parity.py` × `test_ci_local_parity.py` × `test_ferramentas_fixadas.py` × `test_actions_pinadas.py` — propriedades diferentes (Claude×Codex; gate×CI; pins; SHA de actions).
- Guards lentos: não propus apagar nenhum (nenhum tem duplicata mostrada); a lentidão é do harness (C-01).
- Fase 2B, divisão do `recommendations.py`, `accounts*.html`, remoção de tool — decisão registrada, fora de escopo.

### Não medido
- Tempo sem coverage dos guards de `test_structural_guards.py` (30,8 s / 18,9 s / 16,3 s sob coverage) e dos ~12 outros guards de 3 a 7 s; presumo a mesma causa (`nomes_locais` por escopo) mas só perfilei `test_todo_call_site_do_gate_declara_o_nivel`.
- Ganho real do patch de C-01: estimado (~95% do tempo dos 3 testes está em `nomes_locais`), não implementado.
- `test_no_unexpected_tools` ser igualdade exata ou `<=` (C-05) — li só o começo.
- Redundância asserção-a-asserção entre testes de propriedades parecidas (truncamento, `apply_change*`, `test_run_*_quota_reserve`×4, `test_validate_*`×12): só comparei docstrings/nomes. Sem prova, não entram como achado.
- Quais testes unit dependem da AUSÊNCIA de contexto MCP (risco de C-02).
- `tests/browser` (1 teste, Playwright) e a suíte de integração (testcontainers) não foram executados.
- Overlap do snapshot (`schemas_das_tools.json`) com `test_tools_schemas.py` (descrição, `additionalProperties`, contagem): parcial, não medi quais asserções ficariam realmente cobertas só pelo snapshot.
- Scripts de apoio em `C:/Users/welli/AppData/Local/Temp/claude/94e63053a6560f8f/d2f57c97-1a88-48dd-92de-51a0cde56568/scratchpad/` (`c.py`, `d.py`, `p.py`, `prof.py`): hash AST de helpers duplicados e perfil.

## Relatório D


Medição feita sobre `D:/v4-ads-mcp` na branch `docs/fecho-15-11`. Nada foi editado. Todo grep de uso excluiu `_archive/`, `.git`, `.venv`, `.superpowers` e os caches.

### Achados

#### D-01 ⭐ — `docs/operacao/sprint-history.md` (114 KB) é um arquivo morto morando na doc viva
- Onde: `docs/operacao/sprint-history.md:1-5` (título "Sprint history **archive**"; "Last updated: 2026-08-19. Estado corrente: 64 MCP tools … F117").
- Evidência:
  - `git log -3 -- docs/operacao/sprint-history.md` → o último commit é de 19/08 (depois só a reorganização de 04/11).
  - Hoje são 83 tools e o catálogo vai até F211, então o cabeçalho afirma estado falso.
  - Não está na tabela de roteamento do `CLAUDE.md` (grep `sprint-history` em `CLAUDE.md`, `docs/convencoes`, `.claude` → 0 hits).
  - `grep -rn sprint-history tests` → 0 hits: nenhum guard lê o arquivo.
  - Quem o cita: `README.md`, `findings-catalog.md`, os 4 `phase-3b-4x-*-smoke.md` e as specs de 05/24 e 05/25 (links de doc, nada de código nem processo).
- Custo de manter hoje: 114 KB que entram no grep de qualquer varredura de docs; o `_archive/README.md` manda para ele em "Quando usar", o que dá status de doc diária a um arquivo parado há 3 meses.
- Risco de mexer: baixo. É preciso reescrever os links dos 7 citantes; o `tests/unit/test_docs_links.py` prova que não sobrou link quebrado.
- Sugestão: mover para `docs/_archive/` (ou `_archive/handoffs/`) e reescrever os links por script, como na limpeza de 04/11.
- Tamanho: P

#### D-02 ⭐ — planos e specs já executados que ainda estão em `docs/superpowers/`
- Onde:
  - `plans/2026-10-30-varredura-correcoes.md` (26 KB)
  - `plans/2026-10-31-meta-onda-1-leitura.md` (16 KB)
  - `plans/2026-11-03-varredura-refatoracao.md` (34 KB)
  - `plans/2026-11-10-varredura-refatoracao.md` (59 KB)
  - `specs/2026-05-24-meta-ads-incorporation-design.md` (45 KB)
  - `specs/2026-05-25-architecture-refactor-design.md` (29 KB)
- Evidência:
  - A regra do próprio `_archive/README.md` é "planos e specs entregues há mais de 7 dias saem da doc viva".
  - Os 4 planos foram executados: ledgers `.superpowers/sdd/2026-11-03-*` e `2026-11-10-*` fechados, e o 10/30 e o 10/31 estão em produção (`estado-atual.md`: "Onda 1 Meta em produção").
  - As 2 specs de maio são de Meta M.1 e do refactor F1–F4, entregues em maio/junho.
  - Quem cita cada um (grep fora de `_archive`):
    - 10-30 e 10-31 plano: ninguém, exceto outros planos e a spec de 10-31;
    - 11-03: só `findings-catalog.md`;
    - 11-10: o handoff de 10/11, o `levantamento-recomendacoes-v25` e o catálogo;
    - spec 05-24: `sprint-history.md`, a spec de 05-25 e um comentário de `src/db/migrations/003_meta_schema.sql`;
    - spec 05-25: `sprint-history.md` e a spec de 06-20.
- Custo de manter hoje: ~210 KB que a varredura de docs e a busca por "Onda" ou "refatoração" retornam como se fossem vivos.
- Risco de mexer: baixo-médio.
  - Os links do catálogo e dos handoffs precisam de reescrita.
  - O comentário da migration 003 vai apontar para caminho que mudou, e o hook `guard-migrations` proíbe editar migration commitada; aceitar o comentário como histórico.
- Sugestão: mover para `_archive/plans` e `_archive/specs` com reescrita de link por script.
- **Ficam vivos de propósito** (não mover):
  - `plans/2026-11-02-meta-onda-2-auditorias.md`: Onda 2 está pausada e o `estado-atual` linka;
  - `specs/2026-10-31-meta-leitura-auditoria-escrita-design.md`: o plano da Onda 2 depende dela;
  - `specs/2026-06-20-google-performance-breakdown-design.md`: a Fase 2B (tombstone) ainda é a continuação;
  - as specs de 10-28 e 10-29: o código `src/saldo.py` e `scripts/probe_keyword_planner.py` as citam;
  - tudo de 14–15/11: menos de 7 dias.
- Tamanho: M

#### D-03 ⭐ — cauda histórica de `docs/operacao/infra-setup.md` (12 KB, linhas 182–274)
- Onde: `docs/operacao/infra-setup.md:182-274` (seções "GitHub", "GCP project (HISTÓRICO…)", "Supabase", "Google Ads", "Phase sign-offs", "Phase FE Redesign v2").
- Evidência:
  - Linha 186: "HISTÓRICO — projeto antigo `v4-ads-mcp-prod`, a decomissionar; use a seção ESTADO ATUAL".
  - Linha 204: redirect URI do host antigo `v4-ads-mcp-jf26mmrgqa-rj.a.run.app`.
  - Linha 262: "Tailwind CDN", aposentado (CLAUDE.md: CSS offline).
  - Linhas 261 e 273 citam por texto 3 caminhos inexistentes:
    - `docs/superpowers/specs/2026-05-05-frontend-redesign-v2-design.md`;
    - o plan correspondente;
    - `docs/operacao/screenshots/after/`.
  - Só o link de markdown é conferido pelo guard, então esses 3 passam.
  - Nenhuma âncora aponta para as seções antigas (grep `infra-setup.md#` fora do próprio arquivo → 0).
  - O `CLAUDE.md` e o `nucleo.md` mandam ler esse arquivo para DR, e quem lê encontra dois projetos GCP e dois hosts.
- Custo de manter hoje: leitor de DR tem de descobrir qual metade vale; as linhas 1–181 (estado atual + runbook de alerta) são a parte viva.
- Risco de mexer: baixo (nenhum teste lê esse trecho; conferir `test_docs_links`).
- Sugestão: mover as linhas 182–274 para `docs/_archive/setup/infra-setup-historico.md` e deixar uma linha de ponteiro.
- Tamanho: P

#### D-04 ⭐ — README e CLAUDE.md/nucleo.md com fato desatualizado (medido contra o código)
- Onde e evidência:
  - `CLAUDE.md:17` diz `google-ads>=27.0.0`; `pyproject.toml` diz `google-ads>=33.0.0` (e o `estado-atual` diz 33.0.0).
  - `README.md:34` diz o gate `~50s`; `CLAUDE.md:75` diz `~2-3 min`. O ledger de 14/11 registra full sweep de 647 s, contra o "~60-90s" do `README.md:35`.
  - `README.md` (seção Documentação): "findings-catalog — 116 IDs"; o catálogo vai até F211.
  - `README.md:53`: `auth/ # OAuth Google + Meta`; `ls src/auth` não tem `meta_oauth.py` (removido em 11/2026, como o próprio `nucleo.md:25` diz).
  - `README.md` seção Deploy descreve o deploy sem o gate F138 (push só de `docs/` não deploya).
  - `README.md:19-21` repete o parágrafo "Stack" do `CLAUDE.md` (a única duplicação de bloco ≥80 caracteres entre as docs; ver Descartados).
  - `docs/convencoes/nucleo.md:76`: "Hoje 18 das 28 tools computam e ignoram [`classify()`]"; hoje `grep -l "classify(" src/mcp/tools/*.py` dá 30 arquivos. A contagem exata do "ignoram" **não foi medida**; o "Hoje" é de F112 e está velho.
- Custo de manter hoje: o README é a entrada para quem não é agente; os números dele não têm guard (`test_resumo_bate_com_o_detalhe` só varre `findings-catalog`, `CLAUDE.md` e `estado-atual`).
- Risco de mexer: baixo.
- Sugestão: reduzir o README a ponteiro (stack e verificação ficam só no `CLAUDE.md`), ou ampliar `_FONTES_DE_METRICA` do guard F187 para incluir o README; corrigir `CLAUDE.md:17`; trocar o "Hoje 18 das 28" do `nucleo.md` por "derivado pelo guard".
- Tamanho: P

#### D-05 ⭐ — subagente `smoke-runbook-generator` aponta para 3 runbooks que não existem onde diz
- Onde: `.claude/agents/smoke-runbook-generator.md:34-36` e o gêmeo `.codex/agents/smoke-runbook-generator.toml` (mesmo texto; `test_tooling_parity.py` exige os dois iguais).
- Evidência:
  - Aponta para `docs/operacao/phase-3b-24-bootstrap.md`, `-25-` e `-26-`.
  - `ls docs/operacao` não os tem; estão em `docs/_archive/runbooks/phase-3b-2{4,5,6}-bootstrap.md`.
  - Por ser o `CLAUDE.md` ("Smoke runbook? `smoke-runbook-generator` subagent") quem manda usar o agente, a 1ª instrução dele falha ao ler o template.
  - O `description` ainda diz "latest 3 existing runbooks (3b.24/3b.25/3b.26)", embora os 3 mais recentes hoje sejam 3b.42/43/44 (em `docs/operacao`).
- Custo de manter hoje: agente quebrado em silêncio; o caminho morto também faz a leitura de template cair em qualquer coisa que o modelo ache.
- Risco de mexer: baixo, desde que os dois lados mudem juntos (o guard de paridade acusa se divergirem).
- Sugestão: apontar para `docs/_archive/runbooks/…` ou, melhor, para os 3 `phase-3b-4{2,3,4}-*-smoke.md` vivos; alterar `.md` e `.toml` no mesmo PR.
- Tamanho: P

#### D-06 — smokes executados sem nenhum citante e um guia vivo sem link
- Onde: `docs/operacao/smoke-saldo-da-conta.md` (2 KB), `docs/operacao/smoke-planejador-de-palavras.md` (3,6 KB), `docs/operacao/guia-alerta-de-saldo.md` (2,7 KB).
- Evidência:
  - Os dois `smoke-*` são tabelas "Medido" de 29–30/10, de tools entregues. O grep do nome não acha citante nenhum (só estão listados como órfãos em `docs-links.txt`).
  - O glob do guard F187 é `phase-*-smoke.md`; eles não casam, então não são lidos por guard.
  - `guia-alerta-de-saldo.md` é **vivo**: é o manual do gestor (decisão de 30/10 de que cada gestor monta o próprio alerta, com pedido pronto para colar) e fala das tools `get_account_balance` e `meta_get_account_balance`, que existem. Mas nenhum doc o cita, então ninguém o acha.
- Custo de manter hoje: baixo em bytes, mas 3 órfãos poluem a lista "docs que ninguém cita" e escondem os órfãos de verdade.
- Risco de mexer: baixo.
- Sugestão: mover os 2 `smoke-*` para `_archive/runbooks`; linkar o guia no `estado-atual.md` ("Pendências do Wellington" ou nova linha) ou no `README`.
- Tamanho: P

#### D-07 — os 4 runbooks `phase-3b-41..44-*-smoke.md` (249 KB) vivem na doc viva só por causa de um guard
- Onde: `docs/operacao/phase-3b-41-assets-smoke.md` (45 KB), `-42-ad-schedule-` (90 KB), `-43-particao-horaria-` (53 KB), `-44-bid-modifier-` (61 KB).
- Evidência:
  - `_archive/README.md` diz que ficam em `operacao/` porque "o `test_resumo_bate_com_o_detalhe` os varre".
  - O guard confirma: `tests/unit/test_resumo_bate_com_o_detalhe.py:81` faz `_OPERACAO.glob("phase-*-smoke.md")` e `_PISO_DE_RUNBOOKS = 3`.
  - Esse guard nasceu do F187 (em 20/09: "o smoke 3b.42 parou em 5 de 10" repetido em 3 leituras). O F187 segue **aberto** no `estado-atual`.
  - Só o `findings-catalog` e outros runbooks os citam.
- Custo de manter hoje: 249 KB lidos só para sustentar um guard; o tamanho aparece em qualquer grep de "smoke".
- Risco de mexer: **médio**. Tirá-los exige mover o guard para varrer `_archive/runbooks` (ou baixar o piso) e decidir se o F187 continua sendo guardado; mexe em guard aberto, então a decisão é do Wellington.
- Sugestão: decisão do Wellington; se arquivar, apontar o glob do guard para o novo caminho (autoteste de escopo vazio já existe: `EscopoVazioError`).
- Tamanho: M

#### D-08 — `scripts/probe_*.py`: 7 sondas únicas (~1.350 linhas) fora de todo gate
- Onde: `scripts/probe_keyword_planner.py` (198), `probe_meta_auth_header.py` (144), `probe_meta_combinacoes.py` (117), `probe_meta_metricas.py` (212), `probe_meta_onda1.py` (270), `probe_meta_sort.py` (159), `probe_meta_time_increment.py` (66).
- Evidência:
  - Nada os executa: não estão em `Procfile`, nem em `.github/workflows/*.yml`, nem em `scripts/_runner.py`, nem em `pyproject.toml`.
  - Ninguém os importa, exceto `probe_meta_time_increment` → `probe_meta_combinacoes` (só os dois entre si).
  - São **proveniência**: `src/meta_ads/insights.py:129,139,143,153`, `src/governance/rate_limit.py:222`, `tests/unit/test_buc_header_parsing.py:104`, `tests/unit/_meta_formas_medidas.py:1`, `tests/unit/test_meta_sort_server_side.py:15` e o doc `sonda-meta-onda1-2026-10-31.md` citam o arquivo pelo nome como a medição que sustenta um comportamento.
  - Fora do gate: `scripts/_runner.py:30-32` roda ruff/mypy só em `src tests`. Medido: `ruff check scripts` → 1 erro (SIM108 em `test_meta_deletion_callback.py:33`); `mypy scripts` → 28 erros, todos em `probe_meta_sort.py` (sem anotação).
  - Todos importam hoje sem erro (`python -c "import scripts.<mod>"` limpo nos 7), mas dependem de símbolos de `src/` (`BREAKDOWN_META_PARAM`, `build_insights_call`, `META_GRAPH_API_VERSION`), então um rename em `src/` os quebra sem aviso.
- Custo de manter hoje: baixo-médio; ruído de leitura e risco de quebrar em silêncio.
- Risco de mexer: médio se remover (quebra a proveniência citada em 6 lugares do código).
- Sugestão: **não remover.** Opções:
  - (a) mover para `scripts/sondas/` atualizando os 6 citantes;
  - (b) deixar e só adicionar no topo de cada um um aviso "sonda histórica, não rodada pelo CI";
  - (c) incluir `scripts/` no `ruff check`.
  A (b) é a barata.
- Tamanho: P

#### D-09 — `scripts/test_meta_deletion_callback.py` tem URL de produção velha e nome que parece teste
- Onde: `scripts/test_meta_deletion_callback.py:7-16` (docstring) e `:33-36`.
- Evidência:
  - A docstring manda fazer POST para `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/...`, o host do projeto GCP antigo. O de hoje é `v4-ads-mcp-299432068772.southamerica-east1.run.app`.
  - A rota existe e está montada: `src/app.py:127-129` → `src/auth/meta_data_deletion.py:71`.
  - Só `docs/operacao/sprint-history.md` o cita (grep do nome).
  - O nome `test_*` está fora de `testpaths = ["tests"]`, então o pytest não o coleta (medido em `pyproject.toml:93`), mas confunde quem procura testes.
  - `ruff check scripts` acusa o SIM108 nele (linha 33).
- Custo de manter hoje: ensina o URL errado a quem o usar; é a única ferramenta para testar o callback de exclusão da Meta (exigência de App Review).
- Risco de mexer: baixo.
- Sugestão: corrigir a URL (ou ler `PUBLIC_BASE_URL`), renomear para `scripts/gerar_signed_request_meta.py` e atualizar a linha de `sprint-history`.
- Tamanho: P

#### D-10 — `.github/workflows/smoke-liveness.yml` (123 linhas) está dormente e repete a lógica do smoke do deploy
- Onde: `.github/workflows/smoke-liveness.yml` inteiro (só `workflow_dispatch`, sem `schedule`).
- Evidência:
  - O próprio cabeçalho diz "SEM `schedule`, de propósito (20/09)".
  - `SMOKE_MCP_BEARER` está expirado (`estado-atual`: 401 desde 10/11).
  - As 3 etapas (health, secret existe, token vale) repetem o trecho equivalente de `deploy.yml` (curl ao `/mcp` com o Bearer, o mesmo grep de `list_my_accounts`, os mesmos `::error::`).
  - Só o catálogo (F186) o cita. Nenhum teste o lê (grep `smoke-liveness` em `tests` → 0).
- Custo de manter hoje: 123 linhas e duas cópias da lógica de "token vale?" para divergirem.
- Risco de mexer: baixo no pipeline (não roda sozinho), mas **é decisão do F186**: ele é o instrumento de "re-armar" quando houver identidade de TI.
- Sugestão: decisão do Wellington. Se mantiver, fundir a lógica numa action local compartilhada (ou documentar que a cópia é consciente); se não, remover e registrar no F186 como "re-armar = recriar o workflow".
- Tamanho: P

#### D-11 — comentários velhos nos workflows
- Onde e evidência:
  - `.github/workflows/deploy.yml:44`: "que e a pendencia 1b do estado-atual". `grep -n 1b docs/operacao/estado-atual.md` → 0; a pendência foi resolvida (a reconciliação já revoga).
  - `.github/workflows/ci.yml:33-36`: comentário de 4 linhas sobre o `services: postgres` "foi removido", ou seja, relato de algo que não existe mais.
  - `.github/workflows/deploy.yml` (passo "Update backup job image"): "O comentário anterior dizia o contrário" — histórico de edição dentro do código.
  - `JOB_SECRETS_RETIRADOS: "GOOGLE_ADS_DEVELOPER_TOKEN"` (`deploy.yml:~56`) roda `--remove-secrets` em todo deploy, nos 3 jobs. Só pode sair quando alguém medir que o secret saiu dos jobs; **não medido**. Há teste (`tests/unit/test_deploy_jobs_retiram_secrets.py`) que prende o comportamento, então não mexer sem ele.
- Custo de manter hoje: o leitor acha que existe uma pendência 1b; comentários narram versões anteriores.
- Risco de mexer: baixo, só comentário. Cuidado: vários testes leem os `.yml` (`test_ci_deploy_gate`, `test_deploy_job_image_order`, `test_deploy_jobs_retiram_secrets`); trocar texto de comentário pode quebrar assert por substring, então rodar o gate.
- Sugestão: apagar os três comentários; deixar o `JOB_SECRETS_RETIRADOS` como está.
- Tamanho: P

#### D-12 — minors de manutenção ainda abertos, conferidos no código atual
Cada item foi conferido contra o código de hoje.
- **a) Parâmetro morto `experiment_id` em `experimentos_query`.**
  - Onde: `src/google_ads/queries/experiments.py:24-31`.
  - Evidência: a única chamada de produção é `src/mcp/tools/get_experiments.py:145` com `None`; o ramo com id só roda em `tests/unit/test_get_experiments.py:307-311`.
  - Origem: ledger do backlog, Task 4 ("experimentos_query(experiment_id) com filtro sem uso na tool").
  - Risco: baixo. Remover o parâmetro e o teste de F87 do ramo (a validação `_id` continua coberta por `anuncios`/`metricas`).
- **b) `final_urls` selecionado e descartado.**
  - Onde: `src/google_ads/queries/experiments.py:38` (SELECT) × `parse_anuncio_row`, `:87-96` (não lê `final_urls`).
  - Origem: ledger, Task 4 (também registrado como "decisão do Wellington" se expõe URL por lado).
  - Risco: baixo; tirar do SELECT reduz payload, mas mexe numa GAQL medida em 14/11, então reconfirmar com `validate_gaql`. Ou decidir expor (contrato novo).
- **c) Parâmetro `session_id` morto em `exigir_brl`.**
  - Onde: `src/meta_ads/moeda.py:26` e docstring `:37` ("fica na assinatura do contrato"). Callers: `src/mcp/tools/meta_get_budget_pacing.py:263` e `meta_get_entities.py:91`. O corpo (`:40-47`) não usa `session_id`.
  - Origem: handoff 10/11 ("`operacao` e `session_id` mortos em exigir_brl"). O `operacao` já saiu; o `session_id` ficou.
  - Risco: baixo-médio. Um guard de contrato pode exigir a assinatura; checar antes.
- **d) Parâmetro `manager` morto no helper de teste do resync.**
  - Onde: `tests/unit/test_account_resync.py:60` (`_base_patches(..., manager: object = None)`); o comentário `:85-86` admite "não é mais lido"; `grep -n "manager=" tests/unit/test_account_resync.py` → 0 chamadores passam o argumento.
  - Origem: ledger da rodada de 11/11 (Parte J, minor 3 deferido).
  - Risco: nenhum (só teste).
- **e) (produto leve, não é faxina pura)** `src/mcp/tools/list_gaql_resources.py:96-100`: `str(e)` cru em `error_message` e `motivo`, em vez de `to_friendly` (`src/google_ads/errors.py:70`).
  - Origem: ledger do backlog, Task 7. Ainda vale.
  - Risco: baixo, mas muda o texto que o gestor vê; só entra se o Wellington aprovar.
- Custo de manter hoje: cada item é leitura a mais; a e) é inconsistência de mensagem.
- Tamanho: P (todos juntos)

### Descartados (falso positivo, decisão registrada ou já resolvido)
- **Os 13 "órfãos" de `docs-links.txt`** (veredito um a um):
  - `phase-3b-41/42/43/44-*-smoke.md` → vivos (lidos pelo guard F187, ver D-07), com decisão pendente.
  - `guia-alerta-de-saldo.md` → vivo (manual de gestor, ver D-06), só falta o link.
  - `sonda-meta-onda1-2026-10-31.md` → vivo: citado por `src/meta_ads/entidades.py`, pelo plano e pela spec de 10-31 (a lista de órfãos considera só doc→doc).
  - `smoke-saldo-da-conta.md`, `smoke-planejador-de-palavras.md` → candidatos (D-06).
  - `plans/2026-10-30-…`, `plans/2026-10-31-…` → candidatos (D-02).
  - `specs/2026-10-31-meta-leitura-…` → vivo (a Onda 2, pausada, depende dela).
  - `specs/2026-06-20-google-performance-breakdown-design.md` → vivo (base da Fase 2B).
  - `specs/2026-11-15-varredura-faxina-design.md` → esta varredura.
- **Fase 2B** (tombstone dos 8 reports), **`recommendations.py`** e **`accounts.html × accounts_meta.html`** → decisão registrada, fora do escopo.
- **`.codex/` e `.agents/skills/findings-add`** como duplicata de `.claude/`: não é duplicação a limpar. `diff -q` dá os dois `SKILL.md` idênticos, e `tests/unit/test_tooling_parity.py` + `AGENTS.md` documentam a cópia como inevitável (o Codex lê desse caminho) e guardada.
- **Duplicação entre `CLAUDE.md`, `convencoes/*.md` e `estado-atual.md`:** medi janelas de 80 caracteres iguais entre todos os pares. O único bloco real repetido é o "Stack" entre `CLAUDE.md` e `README.md` (D-04); entre convenções só se repete a linha de ponteiro "Taxonomia completa dos bugs". Não há duplicação substancial.
- **`estado-atual.md`:** conferi "83 tools (68 Google + 15 Meta)" → `ls src/mcp/tools` dá 83 arquivos não-`_`, 15 `meta_*`. Confere. Tamanho 9,4 KB, dentro do teto.
- **`findings-catalog.md`** (639 KB) → enciclopédia, cresce por design; sem proposta.
- **Handoffs vivos (3)** → exatamente os 3 mais recentes, conforme a regra. O handoff de 14/11 ainda lista S1–S3 como "Abertos", mas o de 15/11 os fecha; é histórico, não precisa de edição.
- **Dependabot (`.github/dependabot.yml`):** os 3 `ignore` têm motivo comentado e medido; sem passo morto.
- **`ci.yml` e `deploy.yml`:** sem passo duplicado ou morto além dos comentários de D-11. A duplicação `JOB_ENV_VARS` × `--set-env-vars` no `deploy.yml` é deliberada e documentada (o comentário pede para não "corrigir").
- **Minors que o ledger lista mas o código já resolveu** (conferidos):
  - `estimated_calls` morto: `grep estimated_calls src` → só `.pyc`; os testes afirmam a ausência.
  - Import morto com `noqa: F401` em `test_meta_reconcile_job.py`: 0 `noqa` hoje.
  - `_tools_com_razao` não casava `src.razoes`: `test_razao_indefinida.py:252` já casa.
  - `docstring de razao` ("tools Google"): `src/razoes.py:11` já diz "Google e Meta".
  - `lidas += 1` depois do `yield`: em `graph.py:116` e `reports.py:136` o incremento ficou antes.
  - Docstring de `moeda.py` com premissa falsa: reescrita (linhas 1–10).
  - `test_compacto_nao_e_aplicado_ate_5` com monkeypatch sem uso: o teste atual (`test_rsa_lote.py:76-91`) não tem monkeypatch e compara com o compacto.
- **Minors de teste fraco/sem teste** (`test_blast_radius_paused_confirma`, TOCTOU, `remover_pinos` sem verificação pós-write, pior caso de 50 itens): são de produto ou de cobertura, não de manutenção barata; ficam nos ledgers.
- **`.superpowers/`** (15 MB, ~60 `review-*.diff`): é git-ignored, então não pesa no repo nem no CI; só fica de nota ("limpeza local").

### Não medido
- Se `scripts/probe_*` ainda rodam contra a API real (não chamei API; só conferi que importam sem erro).
- Se o `GOOGLE_ADS_DEVELOPER_TOKEN` ainda está montado em algum dos 3 Cloud Run Jobs (precisa de `gcloud`; condiciona retirar `JOB_SECRETS_RETIRADOS`).
- A contagem exata de tools que "computam `classify()` e ignoram `.level`" hoje (D-04): só medi que 30 arquivos chamam `classify(`.
- Se algum **skill ou plugin fora do repo** (ex.: `v4-trafego-google-ads`) cita `sprint-history.md` ou os planos que D-01/D-02 movem; só varri o repo.
- Quantos links o script de reescrita de D-01/D-02/D-03 vai tocar (estimativa: os ~10 arquivos citantes listados; não rodei o script).
- Se `docs/operacao/levantamento-recomendacoes-v25-2026-11-11.md` (10 KB, só o catálogo o cita) e `tool-buckets-2026-10-05.md` (só o `estado-atual` o cita) ainda servem a alguém; mantidos por falta de prova de que não.
