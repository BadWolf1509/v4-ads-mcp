> **Relatório bruto** de um dos 5 agentes da varredura de 21/09 — recorte: resumo que diverge do detalhe na mesma resposta.
> Recuperado do transcript da sessão em 25/09 e reproduzido **sem edição**. Os status
> ("CONFIRMADO", "PLAUSÍVEL") são do agente, não verificação nossa; o destino de cada
> achado está no [índice](README.md).

---

Analysis complete. Here are the results.

---

# Resumo que pode divergir do detalhe — varredura das 68 tools

## 1. População medida (antes de procurar)

Enumerei pelo registry (`import_all_tools()` + `all_tools()`), nunca por grep — **68 tools**, batendo com o `CLAUDE.md`.

Regra de inclusão que apliquei: *o payload de sucesso carrega, ao mesmo tempo, (a) um agregado/veredito sobre um conjunto e (b) a lista dos itens desse conjunto.*

**41 das 68 tools estão na população.** As 27 fora são: tools de performance que devolvem só `rows`+`truncated` sem agregado (`get_campaign_performance`, `get_keyword_performance`, `get_search_terms_report`, `get_ad_performance`, `get_ad_group_performance`, `get_audience_performance`, `get_device_performance`, `get_geo_performance`, `get_hourly_performance`), tools só-agregado sem lista (`get_account_overview`, `meta_get_account_overview`, `import_offline_conversions`, `create_and_link_assets`, `upload_customer_match_list`, `remove_negative_keywords`), previews de entidade única (`create_campaign`, `remove_audience`, `apply_recommendation`, `dismiss_recommendation`, `update_campaign_*`, `update_ad_group_status`), duas listas sem agregado (`get_top_keywords_creatives`) e catálogos estáticos (`list_gaql_resources`, `list_my_accounts`, `validate_gaql`).

O script de contagem levanta erro se algum nome classificado não existir no registry (piso anti-vacuidade). Rodou limpo.

**Contexto:** `tests/unit/test_resumo_bate_com_o_detalhe.py` — o guard do F187 — varre **só `docs/operacao/*.md`**. A lente nunca foi aplicada a `src/mcp/tools/`.

---

## 2. Achados, ranqueados por impacto

### #1 — `get_ad_schedule`: o resumo e a lista vêm de queries com filtros de status DIFERENTES · **CONFIRMADO**

É o **F161 por uma porta que o fix não cobriu.**

| | arquivo:linha |
|---|---|
| Lista (`windows[]`) | `D:\v4-ads-mcp\src\mcp\tools\get_ad_schedule.py:205` (query) → `:211` → `:291` |
| Agregado (`schedule_summary{}`) | `D:\v4-ads-mcp\src\mcp\tools\get_ad_schedule.py:209` (query) → `:213-224` → `:292` |
| Onde os caminhos se separam | `D:\v4-ads-mcp\src\google_ads\queries\ad_schedule.py:39-40` vs `:75-88` |
| O veredito fabricado | `D:\v4-ads-mcp\src\google_ads\ad_schedule.py:331-332` |

`windows[]` sai de `ad_schedule_query(..., status=status, ...)`, que acrescenta `campaign_criterion.status = '&lt;STATUS&gt;'` ao WHERE. `schedule_summary{}` é **chaveado por `orcamentos`**, de `campaign_budget_query`, que não tem filtro de status de critério nenhum — e o corpo do resumo é `summarize_current(atual.get(cid, []))`, onde `atual` veio da grade **filtrada**.

`summarize_current([])` devolve:
```python
return {"has_schedule": False, "windows": 0, "hours_per_week": 168.0}
```

**Cenário concreto** (probe local, sem produção — patch em `run_report` no namespace do tool): conta com campanha `111` ENABLED cuja grade ENABLED é seg–sex 08–18h (50h/semana).

```
status=enabled   len(windows)=5   has_schedule=True    hours_per_week=50.0    truncated=False
status=all       len(windows)=5   has_schedule=True    hours_per_week=50.0    truncated=False
status=paused    len(windows)=0   has_schedule=False   hours_per_week=168.0   truncated=False
status=removed   len(windows)=0   has_schedule=False   hours_per_week=168.0   truncated=False
```

Com `status="paused"` a tool afirma que uma campanha restrita a 50h serve **24x7** — e a própria descrição (`get_ad_schedule.py:77-79`) ensina o gestor a ler exatamente `has_schedule: false` + `hours_per_week: 168` como "serve o tempo todo". A válvula de escape (`campanhas_com_grade_incerta`, `:241`) **só arma sob truncamento** (`get_ad_schedule.py:168-169`: `if not truncated: return set()`), então aqui não dispara: `truncated: false`, sem `schedule_desconhecida_por_truncamento`.

Que o codebase já sabe a regra certa está em `D:\v4-ads-mcp\src\mcp\tools\apply_change.py:361` — a reconsulta pós-apply lê `status="all"` e **depois** filtra o que serve (`:383`), justamente para não alimentar `summarize_current` com um recorte.

---

### #2 — `add_negatives_from_search_terms`: dois números para a mesma pergunta, no mesmo envelope · **CONFIRMADO (reproduzido)**

| | arquivo:linha |
|---|---|
| Agregado A (prosa, superfície de decisão) | `D:\v4-ads-mcp\src\mcp\tools\add_negatives_from_search_terms.py:135` + `:139-140` |
| Agregado B | `:141` → `D:\v4-ads-mcp\src\google_ads\mutations.py:326-330` |
| Lista (`added[]`) | `:111-130`, devolvida em `:144` |
| Onde separam | `D:\v4-ads-mcp\src\google_ads\mutations.py:90-105` vs `D:\v4-ads-mcp\src\mcp\tools\_common.py:36-41` |

Os dois contam "não-falhou", mas sobre **vocabulários de status diferentes**. `_parse_partial_failures` rotula qualquer op sem `WhichOneof("response")` como `"failed"` — inclusive a que o Google recusou por `CRITERION_EXISTS`. O tool então **re-rotula a mesma op** via `classify_partial`, que mapeia o erro de já-existe para `"already_exists"`, que não é `"failed"`.

Reproduzido com o fixture que já está no repo (`tests/unit/test_add_negatives_from_search_terms.py:100`) — 3 negativas, 1 já existente:

```json
{
  "blast_summary": "Adicionar 3 negativa(s) ... (3 aceita(s) pelo Google).",
  "applied_count": 2,
  "added": [ {"status":"added"}, {"status":"already_exists"}, {"status":"added"} ]
}
```

`applied_count: 2` e "**3** aceita(s) pelo Google" no mesmo objeto. E a trilha de auditoria recebe o **2** (`mutations.py:355-360`, `resultado_para_audit(applied_count=…)`), enquanto o gestor lê o **3**. É o F187 na forma pura: dois dados verdadeiros, e o que decide é qual se lê primeiro.

O teste existente assere `applied_count == 2` **e** `added[1]["status"] == "already_exists"` — as duas metades da divergência — mas nunca assere `blast_summary`. O guard é cego para ela por construção.

---

### #3 — `get_assets`: o `summary` fala do conjunto inteiro, `links[]` vem cortado, e o órfão apontado pode não estar na lista · **CONFIRMADO**

| | arquivo:linha |
|---|---|
| Agregado | `D:\v4-ads-mcp\src\google_ads\asset_inventory.py:42-64` (sobre `ordenados`, conjunto completo) |
| Lista | `D:\v4-ads-mcp\src\google_ads\asset_inventory.py:65` — `return ordenados[:limit], summary` |
| Retorno | `D:\v4-ads-mcp\src\mcp\tools\get_assets.py:161-173` |

Probe local (`build_inventory` é função pura), 4 vínculos, `limit=2`, órfão com `asset_id` alto:

```
links devolvidos     : ['100', '200']
summary.total_links  : 4          summary.truncated : True
summary.by_level     : {'CUSTOMER':1,'CAMPAIGN':2,'AD_GROUP':1}   (soma 4, links tem 2)
summary.orfaos       : ['999']
summary.orphan_scope : conta_completa
CONTROLE: orfaos SEM linha correspondente em links[] = ['999']
```

O gestor precisa do `resource_name` — que só existe em `links[]` — para chamar `remove_asset_link`. Para um órfão além do corte, ele não está na resposta. E `orphan_scope` só tem dois valores (`conta_completa` / `nao_calculado_com_filtro`): **nenhum expressa "calculado sobre tudo, detalhe cortado"**, então `conta_completa` sai ao lado de `truncated: true` sem contradição visível.

Não é hipotético: a própria descrição (`get_assets.py:82-85`) mede **735 vínculos na conta 786-223-0676** contra um `limit` default de **200**. Toda chamada default àquela conta cai neste estado.

Divergência na direção segura (o agregado é *mais* completo), mas silenciosa — a descrição explica o `truncated` como "a lista foi cortada" e nunca diz que o bloco `summary` tem outro escopo.

---

### #4 — `bulk_pause_by_query`: o resumo do preview diz "no periodo" para um custo que pode ser vitalício · **PLAUSÍVEL**

| | arquivo:linha |
|---|---|
| Agregado | `D:\v4-ads-mcp\src\mcp\tools\bulk_pause_by_query.py:286`, rótulo em `:298-301`, eco em `:323` |
| Lista | `:287` (`sample = rows[:10]`) |
| Onde separa | `D:\v4-ads-mcp\src\google_ads\queries\bulk_pause.py:119-120` |

`metrics.cost_micros` está **sempre** no SELECT (`bulk_pause.py:24-68`), mas a cláusula `segments.date` só é injetada quando o filtro do gestor menciona `metrics.`. O resumo, porém, afirma o recorte incondicionalmente:

```python
f"Pausar {count} {target_type}(s). Custo total R$ {total_cost:.2f} no periodo. "
```

E o filtro que a **própria descrição recomenda** (`:197-198`, `ad_group_criterion.status = 'ENABLED'`) é exatamente o caso entity-only que não injeta data. A janela resolvida não é ecoada em lugar nenhum do preview — o gestor confirma um `blast_summary` persistido em `pending_operations` sem poder conferir o escopo.

É "resumo contra o próprio rótulo", não agregado-vs-lista. **Probe que resolve:** `validate_gaql` (ou um `run_gaql` de leitura numa conta de teste) com `SELECT ad_group_criterion.criterion_id, metrics.cost_micros FROM keyword_view WHERE ad_group_criterion.status = 'ENABLED' LIMIT 5`, comparado contra a mesma query com `AND segments.date DURING LAST_7_DAYS`. Se os `cost_micros` diferirem, está confirmado. Não rodei — decidiria por chamada ao vivo.

Nota adjacente no mesmo arquivo: `bulk_pause.py:129-134` emite `LIMIT 101` **sem `ORDER BY`**, e `sample` é `rows[:10]` — as 10 entidades que o gestor vê antes de pausar 100 são arbitrárias. Família F88/F98, não F187.

---

### #5 — `get_performance_breakdown` (`campaign`+`hourly`): `truncated` significa coisas diferentes nos dois ramos · **CONFIRMADO, baixo impacto**

`D:\v4-ads-mcp\src\mcp\tools\get_performance_breakdown.py:182` calcula `truncado = len(celulas) &gt; teto` uma vez. O ramo `raw_grid=true` (`:183-191`) devolve `celulas[:teto]` — cortado, flag correta. O ramo agregado (`:192-208`) particiona sobre `celulas` **inteiro, sem corte**, e devolve o mesmo `truncated: truncado`. Com os mesmos argumentos variando só a flag, os totais dos blocos não batem com a soma das linhas cruas, e o modo agregado anuncia truncamento que não sofreu. Erra acusando (direção segura).

---

### #6 — `run_gaql`: `row_count` é o universo, `rows` é o cortado · **CONFIRMADO, baixo impacto**

`D:\v4-ads-mcp\src\mcp\tools\run_gaql.py:109-116` — `row_count: len(rows)` (pré-corte) imediatamente acima de `rows: rows[:limit]`. Declarado pela chave vizinha `returned`, então há saída. Mas o ramo `aggregate_by` (`:99-107`) **não tem o gêmeo `returned`**: `group_count` é a contagem cheia, `groups` sai cortado em `_MAX_ROWS`, e a soma dos counts dos grupos devolvidos não fecha com `total_rows_scanned` sob truncamento.

---

### #7 — `audit_competitor_keywords`: o custo do veredito é do conjunto cheio, a lista é cortada · **CONFIRMADO, baixo impacto**

`D:\v4-ads-mcp\src\google_ads\competitor_analysis.py:174-175` acumula `total_cost` e `total_conversions` sobre **todos** os matches; `:251-256` devolve `matched_st[:limit]`. `summary.total_cost_wasted_brl` (`audit_competitor_keywords.py:175`) fica ao lado de `search_terms[]` (`:195-208`). Mitigado por `search_terms_truncated` adjacente (`:174`) — mas os números de custo/conversão em si não carregam marcador de escopo, e `total_cost_wasted_brl` é o que vira narrativa pro cliente.

---

## 3. Verificado e LIMPO (derivação correta ou divergência declarada)

Abri o caminho inteiro, incluindo helpers a um salto:

- **`detect_drift`** — `summary` sobre o conjunto cheio, `changes[]` cortado, e os **dois** truncados nomeados e distinguidos na description (`detect_drift.py:446-470`; `drift_detection.py:300-330`). Exemplar.
- **`get_change_history`** — corte **antes** da agregação, de propósito, com o motivo escrito em `get_change_history.py:500-505`: *"Se o corte viesse depois da agregacao, `summary.total_changes` nao bateria com `rows` — dois numeros para a mesma pergunta."* É a formulação do F187 aplicada um ano antes de o finding existir.
- **`get_negative_keywords_audit`** — divergência real e **declarada no schema** (`:28-32`) e na description (`:115-120`).
- `audit_quality_score`, `audit_zombie_keywords`, `audit_orphan_smart_actions` — `total_*` + `truncated` + `returned_count` + lista. Coerentes.
- `audit_goal_attribution` — `primary_count = len(primary_summaries)`, derivado da mesma tupla emitida (`goal_attribution.py:198-201`). Sem truncamento.
- `get_conversion_actions`, `get_recommendations`, `get_my_audit_log` — `count = len(&lt;lista emitida&gt;)`, pós-corte.
- `get_my_rate_limit_status` — `blocking_scope` é veredito derivado dos dois blocos que ele também emite (`:105-114`).
- `get_funnel_metrics`, `get_account_overview` — `stages`/`totals` e `current`/`previous` da mesma leitura.
- Meta: `_meta_performance.py:135-152`, `meta_get_performance_breakdown.py:169-190`, `meta_list_my_ad_accounts` — `total_rows = len(rows)` pós-corte; `truncated` do `paging.next`. Honestos.
- `apply_change` — `failed_count` e `applied_count` da mesma `per_op_results` (`:453-456`, `:500-501`).
- `update_keyword_bid` / `update_ad_group_bid` — `max_delta_pct` da mesma lista `changes[]` emitida.
- `update_keyword_status` / `update_ad_status` — `sample_keywords` + `sample_truncated` explícito.
- `create_ad_group`, `create_rsa`, `create_conversion_action`, `create_and_link_assets`, `import_offline_conversions`, `upload_customer_match_list` — resumo derivado do mesmo `args` que vira payload; `_hash_members` é 1:1.
- **`get_budget_pacing`** — **investiguei e descartei.** O loop `cost_micros_total +=` (`:73`) sob um `LIMIT` de nível de linha (`overview.py:47`) tem exatamente a cara de "agregado sobre dias cortados". Não é: `FROM campaign` com `segments.date` só no WHERE não segmenta, e a prova é o `campaign_performance_query` (`performance.py:8-20`), de forma idêntica, cujo tool emite linhas direto sem agregar e serve "top 5 campanhas" em produção. `limit` corta campanhas, `truncated` é honesto.

---

## 4. O que eu NÃO examinei

- **Nenhuma chamada MCP contra produção.** Todos os três achados CONFIRMADOS foram reproduzidos com patch local em `run_report` / função pura. O #4 continua PLAUSÍVEL porque decidi-lo exigiria probe ao vivo — descrita acima, não executada.
- **`src/web/`** — resumos renderizados em template (cards, contadores de painel) contra as tabelas que eles encimam. Mesma classe, outro suporte; fora do recorte que você pediu.
- **`src/db/repositories/`** — se algum `COUNT(*)` de repositório roda com `WHERE` diferente do `SELECT` da lista que o mesmo endpoint devolve. Li os consumidores, não as queries.
- **`src/meta_ads/insights.py`** — `parse_insights_row` internals. Não verifiquei se `purchase_roas` / `purchases` saem de uma fatia de `actions[]` diferente da que é emitida na linha. É a lacuna mais provável de esconder um oitavo achado.
- **`src/google_ads/partial_failure.py`** (`erros_por_indice`) — li o consumidor em `mutations.py`, não o desempacotamento do proto. Se ele perder um índice, o #2 fica pior, não melhor.
- **Cobertura de guard dos achados #5, #6, #7** — não conferi se algum teste já os pinta como comportamento intencional.
- **Docs e runbooks** — já cobertos por `test_resumo_bate_com_o_detalhe.py`.

Nada foi editado; nenhum comando git foi executado. Os probes vivem em `C:\Users\welli\AppData\Local\Temp\claude\D--v4-ads-mcp\a0b3a9f5-c8f6-4547-8b27-1b28860043ef\scratchpad\` (`probe_sched.py`, `probe_negs.py`, `probe_assets.py`, `tally.py`) e são re-executáveis.
