# Backlog de tráfego (M1, N1+N2, N3, G1, G2, M2, M3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar os 7 itens aprovados do backlog da sessão de tráfego: estado de aprovação pós-write de RSA, avisos de GAQL, tool de assinatura de recomendação, leitura de experimentos, pinos em RSA, teto de lote 50 e compatibilidade de campos.

**Architecture:** Sete partes independentes, **um PR por parte**, na ordem M1 → N1+N2 → N3 → G1 → G2 → M2 → M3. G2 e M2 constroem sobre o confirmador `_RSA` do M1 (merge do M1 antes). Mutates seguem o molde existente: tool faz dry-run com `emitir_preview` → `apply_change` despacha por `confirmador_para(operation_type)` → `pre_check`/`executar`/`pos_check`; I/O pós-escrita nunca vira erro.

**Tech Stack:** Python 3.13, `google-ads` v25 (proto-plus), MCP via `register_tool`, asyncpg, pytest (`tests/unit/fixtures/fake_pool.FakePool`, executores substituídos no módulo `src.mcp.tools.apply_change`).

**Spec:** `docs/superpowers/specs/2026-11-14-backlog-trafego-design.md` — ler junto; as seções "Revisão do builder" e os adendos valem sobre o texto anterior.

## Global Constraints

- Um PR por parte; branch `feat/<item>-…` a partir de `main`; `git merge origin/main` antes de abrir (nunca force-push).
- Gate antes de cada commit: `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py`, rodado **mudo, lendo `$?`** — nunca com pipe antes do `&&`.
- Full sweep (`scripts/check_pre_push_full.py`, Docker) em toda parte que muda pré-flight de mutate (M1, G2, M2, N3).
- I/O depois da escrita aplicada nunca vira erro (F83/F91): `try/except Exception` → `confirmation_error` + `portas.log.warning`.
- Proto-plus omite default (F145): "não lido" é `None`; enum compara por `.name`, nunca por presença de atributo.
- Todo guard tem de **falhar contra o código pré-fix** — verificar por sabotagem ou cópia, **nunca `git checkout`**.
- Texto ao gestor em PT-BR; descrição de tool começa com `[DEFER]` (bucket default) — `test_prefixo_da_descricao_concorda_com_o_bucket`.
- Tool nova ou parâmetro novo só aparece em sessão nova (F140); smoke de mutate só com o gestor presente; merge e deploy pedem aval nominal do Wellington por PR.
- Audit de RSA nunca grava texto de anúncio (só contagens) — regra de `_build_params_summary`.

## Review Focus

1. **Releitura que volta com menos linhas que o pedido** (anúncio removido entre apply e releitura; assinatura sumida): o item ausente sai com estado `None` + motivo, nunca some da resposta nem vira "aprovado". → teste em Task 1 e Task 3.
2. **`resource_names` de `update_rsa` vêm como `customers/x/ads/{id}`, os de `create_rsa` como `customers/x/adGroupAds/{ag}~{ad}`**: a releitura tem de extrair o `ad_id` dos dois formatos. → teste em Task 1.
3. **Lote misto no M2** (50 itens, parte aceita, parte recusada pelo Google): `estado_revisao`/pinos só para as linhas com `efeito == "mudou"`; linha que falhou não é relida como se tivesse mudado. → teste em Task 6.
4. **Query com `segments.date` dentro de string literal ou comentário** (ex.: `WHERE campaign.name = 'segments.date'`): o lint do N1 olha só a lista do SELECT, não o texto inteiro. → teste em Task 2.
5. **Experimento ENABLED cujo grupo não tem base ENABLED** (todas as bases pausadas): grupo sai com `base: []` e métricas de base `None`, sem divisão por zero. → teste em Task 4.

---

## Parte 1 — M1: estado de aprovação pós-write de RSA

### Task 1: confirmador `_RSA` com releitura de política

**Files:**
- Create: `src/google_ads/queries/rsa_estado.py`
- Modify: `src/google_ads/confirmadores.py` (novo `_RSA`; registrar em `CONFIRMADORES` para `"create_rsa"` e `"update_rsa"`)
- Modify: `src/mcp/tools/update_rsa.py`, `src/mcp/tools/create_rsa.py` (só a descrição: "pos-apply devolve `estado_revisao` — foto do instante, não veredito")
- Test: `tests/unit/test_apply_change_rsa_estado.py`, `tests/unit/test_rsa_estado_query.py`

**Interfaces:**
- Produces (usado por G2 e M2):
  - `ad_id_de_resource_name(resource_name: str) -> str` — aceita `customers/{c}/ads/{id}` e `customers/{c}/adGroupAds/{ag}~{id}`; outro formato → `ValueError`.
  - `rsa_estado_query(ad_ids: list[str]) -> str` — `SELECT ad_group_ad.ad.id, ad_group_ad.policy_summary.approval_status, ad_group_ad.policy_summary.review_status, ad_group_ad.policy_summary.policy_topic_entries, ad_group_ad.ad.responsive_search_ad.headlines, ad_group_ad.ad.responsive_search_ad.descriptions FROM ad_group_ad WHERE ad_group_ad.ad.id IN (...)` — **sem `segments.date`**.
  - `parse_rsa_estado_row(row: Any) -> dict[str, Any]` → `{"ad_id", "approval_status", "review_status", "topicos": list[str], "assets_reprovados": list[{"campo": "headline"|"description", "texto", "approval_status"}], "pinos": dict[str, list[str]]}` (chave = `HEADLINE_1`…; `pinos` é consumido pelo G2).
  - `class _RSA(_SemPreCheck)`; `executar` idêntico ao `_Padrao`; `pos_check` devolve o envelope do `_Padrao` + `estado_revisao: list[dict] | None`, `lido_em: str (ISO UTC)`, `aviso_revisao: str`, `releitura: {"tool": "run_gaql", "query": str}`, `confirmation_error: str | None`.

- [ ] **Step 1: testes da query/parse** — `test_ad_id_dos_dois_formatos` (`"customers/1/ads/99"`→`"99"`, `"customers/1/adGroupAds/5~99"`→`"99"`, `"x"`→`ValueError`); `test_query_sem_segments_date` (`"segments.date" not in rsa_estado_query(["1"])`); `test_parse_default_omitido_vira_none` (row sem `approval_status` → `None`, não `"UNSPECIFIED"`); `test_parse_asset_reprovado` (headline com `policy_summary_info.approval_status.name == "DISAPPROVED"` entra em `assets_reprovados`).
- [ ] **Step 2: rodar** `.venv/Scripts/python.exe -m pytest tests/unit/test_rsa_estado_query.py -v` — FAIL (módulo inexistente).
- [ ] **Step 3: implementar `rsa_estado.py`** — enum por `.name`; `pinos` a partir de `pinned_field.name` quando `!= "UNSPECIFIED"`.
- [ ] **Step 4: testes do confirmador** (molde `test_apply_change_ad_schedule.py`, executores trocados em `mod`):
  - `test_update_rsa_devolve_estado_revisao` — `run_mutation` devolve `resource_names=["customers/1/ads/99"]`; `run_report` devolve linha `UNDER_REVIEW`; asserir `out["estado_revisao"][0]["review_status"] == "REVIEW_IN_PROGRESS"` (ou o valor do fake), `"lido_em" in out`, `"não é veredito" in out["aviso_revisao"]`, `out["releitura"]["tool"] == "run_gaql"`.
  - `test_create_rsa_extrai_ad_id_de_adgroupad`.
  - `test_releitura_que_quebra_preserva_sucesso` — `run_report` levanta `RuntimeError`; asserir `out["status"]` de sucesso, `out["estado_revisao"] is None`, `out["confirmation_error"]` contém `"run_gaql"` (o caminho de releitura que existe).
  - `test_ad_ausente_na_releitura` (Review Focus 1) — pedido 2 ads, releitura devolve 1; o ausente aparece com `approval_status: None` e `motivo: "nao_encontrado_na_releitura"`.
- [ ] **Step 5: rodar** — FAIL (`estado_revisao` não existe: prova contra o pré-fix).
- [ ] **Step 6: implementar `_RSA` e registrar.** `pos_check` relê só `resource_names` com `efeito == "mudou"` se o resultado trouxer `efeito` por linha; senão todos.
- [ ] **Step 7: rodar os dois arquivos** — PASS; depois `pytest tests/unit/test_apply_change.py tests/unit/test_apply_change_caracterizacao.py -q` — PASS (caminho padrão intacto).
- [ ] **Step 8: gate + full sweep, commit** `feat(mcp): apply_change de RSA devolve estado de revisao pos-write (M1)`.

---

## Parte 2 — N1 + N2: avisos de GAQL

### Task 2: lint `segments.date` no SELECT + hint "must be present in SELECT"

**Files:**
- Create: `src/google_ads/gaql_lint.py`
- Modify: `src/mcp/tools/validate_gaql.py` (sucesso e erro ganham `avisos`), `src/mcp/tools/run_gaql.py` (resposta ganha `avisos` quando não vazio)
- Modify: `src/google_ads/errors.py:158-165` (ramo `QUERY_ERROR`)
- Test: `tests/unit/test_gaql_lint.py`, `tests/unit/test_validate_gaql_hints.py` (estender)

**Interfaces:**
- Produces: `avisos_gaql(query: str) -> list[str]` — analisa **só a lista entre `SELECT` e `FROM`** (case-insensitive); M3 acrescenta uma regra aqui.
- Copy fixa do aviso N1: `"segments.date no SELECT: o Google so devolve linhas de (entidade, dia) com dado — entidade sem trafego no periodo NAO aparece. Para inventario, tire segments.date do SELECT; no WHERE ele nao esconde nada (medido em 14/11)."`
- Copy fixa do hint N2 (substitui o sufixo genérico quando `"must be present in select"` está na mensagem do SDK): `"→ Adicione ao SELECT o campo citado na mensagem: filtrar por um campo exige seleciona-lo neste recurso."`

- [ ] **Step 1: testes do lint** — `test_data_no_select_avisa`; `test_data_so_no_where_nao_avisa` (`"SELECT campaign.id FROM campaign WHERE segments.date DURING LAST_7_DAYS"` → `[]`); `test_data_em_literal_do_where_nao_avisa` (Review Focus 4); `test_case_insensitive` (`select SEGMENTS.DATE from campaign`).
- [ ] **Step 2: rodar** — FAIL.
- [ ] **Step 3: implementar `avisos_gaql`.**
- [ ] **Step 4: testes das tools** — `validate_gaql` válido com data no SELECT → `result["avisos"] == [AVISO_N1]`; sem data → `result["avisos"] == []` (a chave existe sempre); `run_gaql` idem no envelope; erro com mensagem `"The following field must be present in SELECT clause: 'campaign.id'"` → contém o hint N2 e **não** contém `"auction insights"`.
- [ ] **Step 5: rodar** — FAIL; **implementar** nas duas tools e em `errors.py`; rodar — PASS, inclusive `test_validate_gaql_hints.py` antigo (B2/B3 intactos).
- [ ] **Step 6: gate, commit** `feat(mcp): validate_gaql e run_gaql avisam segments.date no SELECT (N1) e erro de campo ausente (N2)`.

---

## Parte 3 — N3: `update_recommendation_subscription`

### Task 3: tool + builder + confirmador

**Files:**
- Create: `src/mcp/tools/update_recommendation_subscription.py`, `src/google_ads/mutates/recommendation_subscriptions.py`
- Modify: `src/google_ads/confirmadores.py` (`_AssinaturaRecomendacao`), `src/governance/blast_radius.py` (ramo novo)
- Test: `tests/unit/test_update_recommendation_subscription.py`, `tests/unit/test_apply_change_assinatura.py`

**Interfaces:**
- Tool `update_recommendation_subscription`, schema `{customer_id: ^[0-9]{10}$, type: enum, status: enum ["PAUSED","ENABLED"]}`, required os três.
- `TIPOS_ASSINAVEIS: tuple[str, ...]` = nomes de `RecommendationTypeEnum.RecommendationType` do SDK v25 **menos** `UNKNOWN`, `UNSPECIFIED` — derivado do enum em import, não digitado.
- Builder `@register_builder("update_recommendation_subscription")` → `MutateOperation.recommendation_subscription_operation.update` com `resource_name = f"customers/{cid}/recommendationSubscriptions/{type}"`, `status`, `update_mask = ["status"]`.
- `blast_radius.classify`: `ENABLED` → CONFIRM com motivo "liga aplicacao automatica do Google"; `PAUSED` → CONFIRM.
- Payload: `{"type", "status", "status_antes", "__target_count__": 1, "__params_summary__": {"type", "status"}}`.
- Confirmador `pos_check`: relê `SELECT recommendation_subscription.type, recommendation_subscription.status, recommendation_subscription.modify_date_time FROM recommendation_subscription WHERE recommendation_subscription.type = '{type}'` → `status_resultante`; `status_resultante != status` → sobrescreve `efeito` da linha para `"sem_efeito"`; falha → `confirmation_error`.

- [ ] **Step 1: testes do dry-run** — `test_tipos_derivados_do_enum` (`set(TIPOS_ASSINAVEIS) == {n for n in enum names} - {"UNKNOWN","UNSPECIFIED"}`); `test_unknown_recusado_no_schema`; `test_tipo_sem_assinatura_recusa` (GAQL vazia → erro "criar assinatura esta fora do escopo"); `test_ja_no_status_sem_token` (atual PAUSED, pedido PAUSED → resposta "ja esta PAUSED", `create_pending` não chamado); `test_mais_de_uma_linha_do_tipo_recusa` (2 linhas → erro citando F185); `test_enabled_aviso_e_risco` (preview contém `"aplicar recomendacoes deste tipo sozinho"`).
- [ ] **Step 2: rodar** — FAIL.
- [ ] **Step 3: implementar tool + builder + blast radius.**
- [ ] **Step 4: testes do confirmador** — `test_status_resultante`; `test_divergencia_vira_sem_efeito` (pedido PAUSED, releitura ENABLED); `test_releitura_falha_preserva_sucesso`; `test_assinatura_sumiu_na_releitura` (Review Focus 1 → `status_resultante: None` + motivo).
- [ ] **Step 5: rodar** — FAIL; implementar; PASS.
- [ ] **Step 6: subagente `mcp-tool-quality-reviewer`** sobre o arquivo novo; corrigir o que ele apontar.
- [ ] **Step 7: gate + full sweep, commit** `feat(mcp): update_recommendation_subscription pausa e reativa assinatura (N3)`.

---

## Parte 4 — G1: `get_experiments`

### Task 4: tool de leitura

**Files:**
- Create: `src/mcp/tools/get_experiments.py`, `src/google_ads/queries/experiments.py`
- Test: `tests/unit/test_get_experiments.py`

**Interfaces:**
- Schema `{customer_id, experiment_id?: ^[0-9]+$}`. Leituras via `run_report` (gate e audit vêm dele), três queries: `FROM experiment`; `FROM ad_group_ad` (RSA, status ENABLED, campos `ad_group.id, ad_group.name, campaign.name, ad_group_ad.ad.id, ad_group_ad.ad.system_managed_resource_source, ad_group_ad.ad.final_urls`); métricas `FROM ad_group_ad` com `segments.date BETWEEN '{ini}' AND '{fim}'` **só no WHERE**.
- Resposta: `{"experimentos": [{"experiment_id","nome","tipo","status","inicio","fim", "grupos": [...] | None}], "atribuicao": "inferida_por_eliminacao" | None, "atribuicao_motivo": str | None, "janela": {"inicio","fim"} | None, "como_aplicar": str, "aviso": str}`.
- `grupos[]` (só AD_VARIATION ENABLED atribuído): `{"ad_group_id","ad_group","campanha","base_ad_ids": list[str], "variacao_ad_ids": list[str], "base": metricas, "variacao": metricas}`; `metricas = {"impressions","clicks","cost_brl","conversions","cpa_brl"}`; `cpa_brl` `None` com 0 conversão.
- Janela: `inicio = start_date`, `fim = min(ontem no fuso da conta, end_date)` (usar o helper de fuso existente em `src/google_ads/account_clock.py`).
- `como_aplicar` (copy fixa): `"Para aplicar o resultado: update_rsa nos base_ad_ids do grupo — a variacao herda a mudanca em minutos (F181); ler cedo demais devolve o estado antigo sem erro."`
- `aviso` (copy fixa): `"Comparativo somado por grupo; nao e o teste de significancia da UI (a API nao o expoe). A API nao liga braco a anuncio (F181)."`

- [ ] **Step 1: testes** — `test_um_enabled_atribui_por_eliminacao`; `test_dois_enabled_atribuicao_null` (motivo cita F181, `grupos is None` nos dois); `test_anuncio_sem_trafego_aparece_com_zero` (variação sem linha de métrica → `impressions == 0`, ainda listada); `test_grupo_sem_base_enabled` (Review Focus 5); `test_bracos_vazios_nao_quebram` (não consulta `experiment_arm` — asserir que nenhuma query contém `experiment_arm`); `test_query_metricas_sem_data_no_select`; `test_experimento_de_campanha_sem_comparativo` (tipo `SEARCH_CUSTOM` → `grupos: None`).
- [ ] **Step 2: rodar** — FAIL.
- [ ] **Step 3: implementar.**
- [ ] **Step 4: rodar** — PASS; subagente `mcp-tool-quality-reviewer`.
- [ ] **Step 5: gate, commit** `feat(mcp): get_experiments com comparativo base x variacao (G1)`.

---

## Parte 5 — G2: `pinned_field` (depende da Parte 1 em `main`)

### Task 5: contrato, builder, pré-flight de pinos, releitura

**Files:**
- Create: `src/mcp/tools/_rsa_textos.py` (schema do item e normalização, compartilhado)
- Modify: `src/mcp/tools/create_rsa.py`, `src/mcp/tools/update_rsa.py`, `src/google_ads/mutates/ads.py:35-110`, `src/google_ads/preflight.py:303+` (`validate_existing_rsas_for_update`), `src/google_ads/confirmadores.py` (`_RSA.pos_check`)
- Test: `tests/unit/test_rsa_pinos.py`; estender `test_update_rsa.py`, `test_create_rsa_builder.py`, `test_update_rsa_builder.py`, `test_validate_existing_rsas.py`

**Interfaces:**
- `ITEM_TEXTO(max_len: int, posicoes: tuple[str, ...]) -> dict` — JSON schema `oneOf: [string, {text, pinned_field?}]`, `additionalProperties: false`.
- `POSICOES_HEADLINE = ("HEADLINE_1","HEADLINE_2","HEADLINE_3")`, `POSICOES_DESCRIPTION = ("DESCRIPTION_1","DESCRIPTION_2")`.
- `normalizar_textos(itens: list[str | dict]) -> list[dict]` → sempre `{"text", "pinned_field": str | None}`.
- `pinos_por_posicao(itens: list[dict]) -> dict[str, list[str]]` (mesmo shape de `parse_rsa_estado_row(...)["pinos"]`).
- `posicoes_perdidas(atuais: dict[str, list[str]], novos: dict[str, list[str]]) -> list[str]` — posições com pino hoje e **nenhum** pino na lista nova (critério por POSIÇÃO; texto reescrito na mesma posição não conta).
- `update_rsa` item ganha `remover_pinos: bool` (default `false`, por update).
- `validate_existing_rsas_for_update` acrescenta `responsive_search_ad.headlines/descriptions` à GAQL que já roda (zero round-trip novo) e devolve erro PT-BR listando `ad_id` + posições quando `posicoes_perdidas` não vazio e `remover_pinos` falso — só para updates que trazem `headlines`/`descriptions`.
- `_RSA.pos_check`: para cada linha com pino pedido, compara `pinos` relido com o pedido; divergência → `efeito: "sem_efeito"` + `pinos_resultantes`.
- Preview: `pinos` por posição por anúncio + aviso fixo `"Pinar reduz a forca do anuncio: o Google tem menos combinacoes para testar."`.
- Audit: `_build_params_summary` ganha `pinos_por_posicao_total: dict[str,int]`, sem texto.

- [ ] **Step 1: testes** — `test_item_string_payload_identico` (builder com strings produz o mesmo proto de hoje — capturar antes da mudança e comparar); `test_item_objeto_seta_pinned_field` (`.pinned_field.name == "HEADLINE_1"`); `test_update_sem_pino_sobre_pinado_recusa` (atual `{"HEADLINE_1":["A"]}`, novo sem pino → erro contém `"HEADLINE_1"` e `"remover_pinos"`); `test_reescrita_na_mesma_posicao_segue`; `test_remover_pinos_true_segue`; `test_update_so_final_urls_nao_checa_pinos`; `test_pino_nao_pegou_vira_sem_efeito` (pos_check); `test_audit_sem_texto`.
- [ ] **Step 2: rodar** — FAIL (`test_update_sem_pino_sobre_pinado_recusa` aceita no código de hoje).
- [ ] **Step 3: implementar `_rsa_textos.py`, schemas, builder, pré-flight, pos_check.**
- [ ] **Step 4: rodar** — PASS, incluindo os quatro arquivos antigos de RSA.
- [ ] **Step 5: gate + full sweep, commit** `feat(mcp): pinned_field em create_rsa/update_rsa com recusa de perda de pino (G2)`.

---

## Parte 6 — M2: teto 50 (depende das Partes 1 e 5)

### Task 6: constante, preview compacto, releitura única

**Files:**
- Modify: `src/mcp/tools/_rsa_textos.py` (`TETO_LOTE_RSA = 50`), `create_rsa.py`, `update_rsa.py` (`maxItems: TETO_LOTE_RSA`; preview compacto), `src/google_ads/confirmadores.py` (`_RSA` relê o lote numa GAQL)
- Test: `tests/unit/test_rsa_lote.py`

**Interfaces:**
- `TETO_LOTE_RSA: int = 50`.
- `preview_compacto(updates: list[dict]) -> list[dict]` — acima de 5 itens: por anúncio `{"ad_id", "fields_updated", "contagens": {"headlines","descriptions","pinos"}, "final_urls", "path1", "path2"}`; texto só quando `headlines`/`descriptions` mudam; até 5, o preview atual.

- [ ] **Step 1: testes** — `test_51_recusa_50_passa` (validação real do schema registrado da tool, não do dict); `test_constante_unica` (`create_rsa._SCHEMA[...]["maxItems"] is TETO_LOTE_RSA` nas duas); `test_preview_50_abaixo_do_teto` (`len(json.dumps(preview)) < 60_000` com 50 updates só de `final_urls`); `test_releitura_do_lote_e_uma_gaql` (50 resource_names → `run_report` chamado 1 vez); `test_lote_misto_so_rele_quem_mudou` (Review Focus 3); guard F183 existente segue passando.
- [ ] **Step 2: rodar** — FAIL (`maxItems` é 5).
- [ ] **Step 3: implementar.**
- [ ] **Step 4: rodar** — PASS.
- [ ] **Step 5: gate + full sweep, commit** `feat(mcp): teto de lote de RSA 5 -> 50 com preview compacto (M2)`.

---

## Parte 7 — M3: compatibilidade via `GoogleAdsFieldService`

### Task 7: parâmetro `resource` + aviso de null silencioso

**Files:**
- Create: `src/google_ads/campos_gaql.py`
- Modify: `src/mcp/tools/list_gaql_resources.py`, `src/google_ads/gaql_lint.py` (regra nova, só se a remedição do Step 0 confirmar)
- Test: `tests/unit/test_list_gaql_resources_compat.py`, `tests/unit/test_gaql_lint.py` (estender)

**Interfaces:**
- `async compatibilidade(resource: str, *, manager_id: UUID) -> dict[str, list[str]]` — `GoogleAdsFieldService.search_google_ads_fields(query=f"SELECT name, selectable_with WHERE name = '{resource}'")`, via `run_blocking`; separa `selectable_with` em `segments` (`segments.*`), `metrics` (`metrics.*`), `resources_atribuidos` (resto). Cache `dict[tuple[str, str], dict]` em módulo, chave `(versão da API, resource)`.
- `resource` validado por `^[a-z_]+$` no schema (não restrito ao catálogo curado); recurso que o Google não conhece → `compativel: null` + motivo do Google.
- Resposta com `resource`: resposta atual + `compativel: {...} | None`, `fonte: "GoogleAdsFieldService v25"`, `compativel_motivo: str | None`. Sem `resource`: idêntica à atual.
- Reserva de rate-limit + audit no molde do `validate_gaql` (`before_call`/`record_actual`, `audit_log.record` com `customer_id=None`).

- [ ] **Step 0: remedir o null silencioso** na MO (`run_gaql` com `ad_group_criterion.quality_info.quality_score` + `segments.date` no SELECT); se 100% `null` sem erro, a regra entra no lint com copy `"quality_info com segments.date volta null sem erro (medido em <data>): tire segments.date para ler o indice de qualidade."`; se não, a regra **não** entra e o doc registra.
- [ ] **Step 1: testes** — `test_com_resource_compativel_preenchido` (fake do serviço no formato real: objeto com `.results[].selectable_with`); `test_falha_compativel_null_com_motivo` (exceção → `compativel is None`, motivo não vazio; nunca `[]`); `test_sem_resource_resposta_identica` (comparar com o dict de hoje); `test_cache_uma_chamada` (duas chamadas → serviço chamado 1 vez).
- [ ] **Step 2: rodar** — FAIL.
- [ ] **Step 3: implementar.**
- [ ] **Step 4: rodar** — PASS.
- [ ] **Step 5: gate, commit** `feat(mcp): list_gaql_resources devolve compatibilidade do GoogleAdsFieldService (M3)`.

---

## Fecho de cada parte (fora do código)

- PR com aval nominal do Wellington; CI verde confirmado por `gh run view <id> --json conclusion`.
- Prova da tabela "Definição de pronto" do CLAUDE.md, por parte: leitura (N1+N2, G1, M3) → chamada real em sessão nova; mutate (M1, N3, G2, M2) → dry-run + apply com o gestor presente, sessão nova.
- Atualizar `docs/operacao/estado-atual.md` e a tabela de estado do backlog da sessão de tráfego (só a linha do item).
