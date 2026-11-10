# Varredura de refatoração de 10/11 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir os bugs confirmados e executar os guards, as refatorações e as limpezas apontadas pela varredura de 10/11, sem mudar comportamento além do que cada task declara.

**Architecture:** Dez partes, **uma por PR**, nesta ordem: A (bugs) → B (guards) → C (Google) → D (tools MCP) → E (Meta, jobs e scripts) → F (db e web, baixo risco) → G (acesso e audit) → H (auth) → I (núcleo das tools grandes) → J (depois do F207). Cada parte sai de `main` atualizado, passa pelo gate (e pelo full sweep quando indicado) e só é mesclada com o aval nominal do Wellington. B vem antes de C, D, F, G e I porque os ratchets dela são a rede que essas partes encolhem. Refatoração é estrutural: o teste existente é a rede; onde não houver, a task escreve caracterização **antes** de mexer e vê PASS no código atual.

**Tech Stack:** Python 3.13, asyncpg, FastAPI + Jinja2 + HTMX, `google-ads` 33.0.0 (API v25), Meta Graph v25 via httpx, pytest + testcontainers + freezegun.

**Spec:** não há documento de spec. A origem é a varredura de 10/11 (quatro agentes só de leitura, por área) e a segunda rodada de levantamento de fatos, com as evidências centrais reconferidas no código em 10/11. A ordem de execução e as escolhas marcadas **(decisão)** são provisórias até a revisão do Wellington; as que ficaram para ele estão em "Decisões pendentes", no fim.

## Global Constraints

- Gate antes de todo commit, sem pipe: `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py > log 2>&1 && git add ... && git commit ...`.
- Full sweep (`scripts/check_pre_push_full.py`, Docker) obrigatório nas partes A, C, D, E, F, G, I e J (query, repositório, transação, mutate, `_common`, job). H roda o gate e `tests/browser`.
- Painel e template: `python -m pytest tests/browser` e clique em produção depois do deploy (A2, G2).
- Guard novo só vale com sabotagem conferida contra o código pré-fix; **nunca `git checkout`** para isso (cópia ou edição reversa).
- Guard de varredura usa `tests/unit/_guard_harness.py` (`h.fontes_py`, `h.arvore`, `h.rel`, `h._texto_logico` para ignorar docstring); scanner que devolve vazio levanta `EscopoVazioError`. Allowlist que só encolhe segue `tests/unit/test_no_secrets_in_query_params.py`: um teste barra entrada nova, outro exige `allowlist - reais == set()`.
- Gate `ensure_account_access` continua **no topo de cada executor**, fora de `try` e de helper (`test_structural_guards.py`). `can_manager_access` fica explícito por plataforma: nenhuma task o unifica.
- As duas reconciliações REVOGAM acesso; nenhuma task muda o que é revogado, quando, ou o texto do `blocked_reason`.
- Patch de teste aponta para onde o nome é **procurado**: mover função entre módulos exige varrer `patch("src....` e `monkeypatch.setattr("src....` do nome antigo (contagens nas tasks D5, I2, I3).
- Schemas e descriptions das tools não mudam (`tests/unit/test_schemas_snapshot.py`, fixture `tests/unit/fixtures/schemas_das_tools.json`); regravar o fixture é proibido neste plano.
- Rotas: nomes e ordem preservados (`tests/unit/fixtures/tabela_de_rotas.json`).
- Migration commitada não se edita. Mensagens ao gestor em PT-BR. Nenhum dado de cliente em arquivo.
- Template com classe utilitária nova: `python scripts/build_tailwind.py` no mesmo commit.
- Escrever sem ler: barra invertida em heredoc é alterada pelo shell do Windows; edição com `\` usa o editor.
- Fora deste plano, por decisão registrada: os 8 reports da **Fase 2B** (soak); o **C2** da versão da API (decisão pendente em `estado-atual.md`); a sincronização de `status` com `is_active` (F84); dividir `recommendations.py`; `ler_colecao` em segmentação/histórico/criativos (D2 de 03/11); o helper de lista de IDs (F163); `META_EFFECTIVE_STATUS_LABELS` (F54); unificar a parte destrutiva de `reconcile_google`/`reconcile_meta`.

## Review Focus

1. Reconciliação: depois de G4, as mesmas entradas dão o mesmo `Plan` (inclusive `blocked_reason` e `unreachable`) nos dois jobs — conferido pelo teste de paridade B1, não por leitura.
2. Clique duplo, aba velha e gestor inexistente nos toggles do painel (A2): nenhum estado invertido, nenhum audit de sucesso falso.
3. Corpo da Graph que não é objeto na leitura da parceria (A5): leitura marcada incompleta, nada revogado.
4. Token e cookie (H1): os tokens emitidos depois da refatoração são byte a byte os de antes, e uma audiência nunca vale pela outra.
5. Mover nomes entre módulos (D5, I2, I3): nenhum patch de teste fica apontando para o módulo antigo — o full sweep tem de rodar verde, e um grep por cada alvo antigo dá zero.

Cada linha tem teste na task dona (B1/G4, A2, A5, H1, D5/I2/I3).

---

## Parte A — Bugs (PR `fix/bugs-varredura-10-11`, full sweep)

### Task A1: o audit agrupa "Hoje"/"Ontem" pelo dia de Brasília

**Files:** Modify `src/web/routes/audit.py:63-74`. Test: `tests/integration/test_web_panel_audit.py`.

- [ ] **Step 1: teste que falha.** `test_audit_agrupa_pelo_dia_de_brasilia`: com freezegun em `2026-11-10T02:30:00Z` (23h30 de 09/11 em Brasília), gravar uma linha com `occurred_at = 2026-11-10T01:00:00Z` (22h de 09/11) e outra com `2026-11-09T12:00:00Z`; GET `/audit`; assert as duas linhas sob o cabeçalho "Hoje" e nenhum cabeçalho "Ontem" nem `10/11/2026`.
- [ ] **Step 2:** rodar o teste. Expected: FAIL (a linha das 22h cai num grupo de 10/11 em UTC).
- [ ] **Step 3:** em `audit.py`, `today = dias_do_painel(1)[0]` e `d = r["occurred_at"].astimezone(FUSO_PAINEL).date()`, importando `FUSO_PAINEL` e `dias_do_painel` de `src/web/numeros.py`.
- [ ] **Step 4:** rodar o teste e o arquivo inteiro. Expected: PASS. Commit `fix(web): audit agrupa pelo dia de Brasília`.

### Task A2: toggles de gestor aplicam o estado pedido

**Files:** Modify `src/web/routes/admin_overview.py:151-210`, `src/db/repositories/managers.py`, `src/web/templates/admin/managers.html:71-79`. Test: `tests/integration/test_web_panel_admin.py`, `tests/browser/test_confirmacoes.py`, `tests/unit/test_managers_menu_toggle.py`.

**Interfaces — Produces:**
- `async def definir_ativo(conn, *, manager_id: UUID, ativo: bool) -> tuple[str, bool] | None` em `managers.py`: `None` se o gestor não existe; senão `(email, mudou)`.
- `async def definir_role(conn, *, manager_id: UUID, role: Literal["admin", "gestor"]) -> tuple[str, bool] | None` em `managers.py`, mesma semântica.
- Rotas (paths e nomes inalterados) recebem `desejado` por **query string**: `toggle-active?desejado=ativo|inativo` e `toggle-role?desejado=admin|gestor` — `desejado: Literal[...] = Query(...)`. **(decisão)** query string em vez de campo de form para não mexer no JS do `data-v4-post` nem no macro `dropdown`; o template só troca o `post_url`.

- [ ] **Step 1: testes que falham.** `test_toggle_active_e_idempotente`: dois POST `?desejado=inativo` seguidos → gestor inativo, **uma** linha de audit. `test_toggle_role_e_idempotente`: dois POST `?desejado=admin` → admin, uma linha de audit. `test_toggle_de_gestor_inexistente_da_404_sem_audit`: UUID aleatório → 404 e zero linhas de audit, nos dois toggles. `test_toggle_sem_desejado_da_422`.
- [ ] **Step 2:** rodar. Expected: FAIL (o segundo POST inverte de volta; inexistente dá 204).
- [ ] **Step 3:** implementar as duas funções: `SELECT email, is_active FROM managers WHERE id = $1 FOR UPDATE` (ou `role`); `None` se não há linha; se o valor já é o pedido, `(email, False)` sem escrever; senão `UPDATE` e `(email, True)`. Rodam dentro da transação que já existe na rota (F91). A rota: `None` → 404; `mudou=False` → toast "O gestor já estava assim." e nenhum audit; `mudou=True` → audit e toast atuais. A trava "não pode desativar você mesmo" continua antes de tudo. No template, `post_url` ganha `?desejado=` com o estado oposto ao atual de `m`.
- [ ] **Step 4:** ajustar `tests/browser/test_confirmacoes.py` (o fake de rota passa a ver a query string) e `test_admin_managers_toggle_*` existentes para mandar `desejado`. Rodar o arquivo de integração, `tests/unit/test_managers_menu_toggle.py`, `tests/unit/test_structural_guards.py` e `tests/browser`. Expected: PASS. Commit `fix(web): toggles de gestor aplicam o estado pedido`.

### Task A3: `bootstrap-admin` reativa e os comandos do CLI gravam audit

**Files:** Modify `src/scripts/admin.py:42-65` e `:117-138`. Test: `tests/integration/test_admin_script.py`.

- [ ] **Step 1: testes que falham.** `test_bootstrap_admin_reativa_admin_inativo`: admin existente com `is_active=false` e `status='inactive'` → depois do comando, `Manager.is_deactivated` é False. `test_bootstrap_admin_nao_toca_convidado`: gestor `status='invited'` promovido → `status` continua `'invited'` (F84: só `'inactive'` vira `'active'`). `test_bootstrap_admin_grava_audit` e `test_grant_all_grava_audit`: uma linha `action_type='system'`, `operation='cli_bootstrap_admin'` / `'cli_grant_all'`, `manager_id` = o gestor alvo, `target_count` = contas concedidas no grant-all.
- [ ] **Step 2:** rodar. Expected: FAIL.
- [ ] **Step 3:** no gestor existente (admin ou não), um só `UPDATE managers SET role='admin', is_active=true, status = CASE WHEN status='inactive' THEN 'active' ELSE status END WHERE id=$1`; gravar com `audit_log.record(conn, manager_id=..., session_id=None, customer_id=None, action_type="system", operation=...)` na mesma transação da escrita.
- [ ] **Step 4:** rodar o arquivo. Expected: PASS. Commit `fix(admin): bootstrap-admin reativa e o CLI grava audit`.

### Task A4: `reconcile_meta` sem configuração grava a execução

**Files:** Modify `src/jobs/meta_resync.py:69-74`. Test: `tests/unit/test_meta_reconcile_job.py:221`.

- [ ] **Step 1: teste que falha.** Reescrever `test_sem_business_id_o_job_nao_reconcilia` e criar `test_sem_token_o_job_nao_reconcilia`: com `record_job_run` trocado por um `AsyncMock`, assert `blocked_reason` atual **e** uma chamada com `operation="meta_reconcile", platform="meta", status="error", error_message=<o blocked_reason>`. O comentário que dizia "se algum dia o no-op passar a escrever, o teste quebra" sai: escrever passa a ser o certo (mesma regra do `_etapa_google`, `account_resync.py:310-325`).
- [ ] **Step 2:** rodar. Expected: FAIL (zero chamadas).
- [ ] **Step 3:** antes de cada `return Plan(blocked_reason=...)`, chamar `record_job_run(...)` dentro de `best_effort`, como no fim da função.
- [ ] **Step 4:** rodar o arquivo e `tests/unit/test_meta_resync_audit.py`. Expected: PASS. Commit `fix(meta_ads): reconcile sem configuração grava a execução`.

### Task A5: `fetch_paginated` trata corpo que não é objeto

**Files:** Modify `src/meta_ads/graph.py:83-110`. Test: `tests/unit/test_meta_reports_versao_e_uso.py`.

- [ ] **Step 1: teste que falha.** `test_fetch_paginated_corpo_lista_devolve_incompleto`: primeira página `200 {"data": [{"id": "1"}], "paging": {"next": "..."}}`, segunda `200 [1, 2]` → `PagedFetch(rows=[{"id": "1"}], complete=False)`, sem exceção. `test_fetch_paginated_corpo_lista_na_primeira`: `200 [1, 2]` → `PagedFetch(rows=[], complete=False)`.
- [ ] **Step 2:** rodar. Expected: FAIL com `AttributeError: 'list' object has no attribute 'get'`.
- [ ] **Step 3:** em `fetch_paginated`, `if not isinstance(body, dict): return PagedFetch(rows, complete=False)` antes do `body.get`. `complete=False` bloqueia o lado destrutivo do reconcile (F93).
- [ ] **Step 4:** rodar o arquivo, `tests/unit/test_meta_graph_paginacao.py` e `tests/unit/test_meta_paginacao_usa_url_completa.py`. Expected: PASS. Commit `fix(meta_ads): fetch_paginated marca incompleto o corpo que não é objeto`.

---

## Parte B — Guards (PR `test/guards-varredura-10-11`)

### Task B1: paridade das duas regras de reconciliação

**Files:** Create `tests/unit/test_reconcile_paridade.py`.

- [ ] **Step 1:** teste parametrizado `test_mesma_entrada_mesmo_plano` sobre cenários em comum: conta nova; ausência dentro da carência; ausência que cruza a carência; retry no mesmo dia do limiar (`last_missed_on == hoje`); volta depois de ausência (`to_reset`); `complete=False`; remoção em massa acima do teto; piso `max(1, ...)` com inventário de 1; fuso `None`. Cada cenário monta a mesma situação nos dois (`InventoryRow(customer_id=..., time_zone=...)` × `InventoryRow(ad_account_id=..., timezone_name=...)`, `mcc_ids` × `partnership_ids` com `refused_ids=set()`) e assert `to_add, to_bump, to_remove, to_reset, blocked_reason` iguais, e `unreachable == []` no Meta.
- [ ] **Step 2:** rodar. Expected: PASS (hoje as cópias são iguais).
- [ ] **Step 3:** sabotagem: trocar `threshold` padrão do Meta para 4, e numa segunda rodada o `max(1, ...)` do Google para `max(0, ...)` → FAIL nas duas; desfazer. Commit `test(meta_ads): paridade das regras de reconciliação`.

### Task B2: conformidade dos repositórios de acesso gêmeos

**Files:** Create `tests/unit/test_acesso_gemeos_conformes.py`.

**Interfaces — Produces:** `_DIVERGENCIAS_REGISTRADAS: dict[str, str]` (função → motivo), lida por G1.

- [ ] **Step 1:** para cada um dos 7 pares (`grant`, `grant_all_active`, `revoke`, `list_accounts_for_manager`, `can_manager_access`, `bulk_grant`, `copy_access`), extrair por AST as strings SQL da função em `manager_account_access.py` e `manager_meta_account_access.py`, normalizar espaços e trocar os nomes Meta pelos Google (`manager_meta_account_access`→`manager_account_access`, `meta_ad_accounts`→`google_ads_accounts`, `ad_account_id`→`customer_id`, `account_name`→`descriptive_name`) e comparar; comparar também o default de cada parâmetro. `test_gemeos_iguais_fora_do_registrado` falha em diferença não registrada; `test_registro_descreve_a_realidade` falha em entrada registrada que não diverge mais. Registro inicial: `grant_all_active` (Meta atualiza `granted_at`/`granted_by` no `ON CONFLICT`, Google não — **decisão pendente**) e `revoke` (motivo padrão `admin_revoked` × `manual`: valor gravado no banco e lido pelas filas).
- [ ] **Step 2:** rodar. Expected: PASS com o registro.
- [ ] **Step 3:** sabotagem: tirar `access_level = EXCLUDED.access_level` do `bulk_grant` Meta (a classe F167) → FAIL; desfazer. Commit `test(db): conformidade dos repositórios de acesso gêmeos`.

### Task B3: ratchets de SQL nas rotas e de `create_pending`

**Files:** Create `tests/unit/test_ratchet_camadas.py`.

**Interfaces — Produces:** `_SQL_EM_ROTA_CONHECIDO: set[tuple[str, str]]` (arquivo, função) e `_CREATE_PENDING_FORA_DO_HELPER: set[str]`, encolhidos por A2, D3 e G2.

- [ ] **Step 1:** `test_rota_nao_chama_conn_direto`: AST em `src/web/routes/*.py`, chamada de atributo `fetch|fetchrow|fetchval|execute|executemany` cujo objeto é um nome qualquer (não só `conn`) → `(arquivo, linha)`; allowlist inicial = os 20 sítios medidos em 10/11: `_acesso.py:107`; `accounts.py:32,69`; `admin_access.py:42,79,185,202,245,329,346,394`; `admin_invites.py:53,98,138`; `admin_overview.py:56,62,69,166,194`; `dashboard.py:42` (a chave é `(arquivo, nome da função)`, não a linha, para a allowlist não quebrar a cada edição). `test_create_pending_so_no_helper`: chamadas a `create_pending` em `src/mcp/tools/` fora de `_mutate_common.py`; allowlist = `bulk_pause_by_query`, `create_and_link_assets`, `import_offline_conversions`, `update_keyword_status`, `upload_customer_match_list`. Mais os dois testes de "allowlist descreve a realidade".
- [ ] **Step 2:** rodar. Expected: PASS. Sabotagem: um `await conn.fetch("SELECT 1")` em `dashboard.py` e um `create_pending(` em `update_ad_status.py` → FAIL; desfazer.
- [ ] **Step 3:** commit `test: ratchets de SQL nas rotas e de create_pending`.

### Task B4: ratchets de GAQL nas tools e de janela de data

**Files:** Modify `tests/unit/test_ratchet_camadas.py`.

- [ ] **Step 1:** `test_gaql_so_fora_das_tools`: em `src/mcp/tools/*.py`, literais de string (sem docstring, via `h._texto_logico`) que casam `\bSELECT\b.+\bFROM\s+[a-z_]+` → arquivo; allowlist = `apply_audience`, `update_ad_group_bid`, `update_campaign_budget`, `update_keyword_bid`. Medido em 10/11: os textos de description e mensagem de `detect_drift`, `get_change_history`, `validate_gaql`, `upload_customer_match_list` e `bulk_pause_by_query` não podem casar — se casarem, o scanner está largo demais, não a allowlist curta. `test_janela_so_no_common`: `segments.date BETWEEN` em literal de `src/` fora de `queries/_common.py`; allowlist = `audit_competitor_keywords.py`, `audit_quality_score.py`.
- [ ] **Step 2:** rodar. Expected: PASS. Sabotagem: uma GAQL em `get_ad_performance.py` e um `BETWEEN` em `queries/overview.py` → FAIL; desfazer. Commit `test: ratchets de GAQL nas tools e de janela de data`.

---

## Parte C — Google, baixo risco (PR `refactor/google-varredura-10-11`, full sweep)

### Task C1: builders de status por tabela

**Files:** Modify `src/google_ads/mutates/campaigns.py:17`, `ad_groups.py:11`, `ads.py:11`, `keywords.py:11`, `bulk.py:19-87`; Create `src/google_ads/mutates/_status.py`. Test: `tests/unit/test_status_builders_paridade.py` (novo).

**Interfaces — Produces:**
- `@dataclass(frozen=True) class AlvoDeStatus: servico: str; caminho: str; campo_op: str; enum: str` e `ALVOS_DE_STATUS: dict[str, AlvoDeStatus]` com chaves `campaign`, `ad_group`, `ad`, `keyword` (`"CampaignService"`, `"campaign_path"`, `"campaign_operation"`, `"CampaignStatusEnum"` etc.).
- `def operacao_de_status(client: Any, alvo: AlvoDeStatus, resource_name: str, status: Any, mascara: Any) -> Any` — devolve o `MutateOperation`.

- [ ] **Step 1: caracterização.** `test_proto_igual_ao_de_antes`: para cada alvo e para o `build_bulk_pause`, serializar as operações geradas por `make_capture_client()` com um payload fixo e comparar com o valor gravado **antes** da mudança num dict do próprio teste. Rodar: PASS.
- [ ] **Step 2:** criar `_status.py`; os 4 builders e os 4 ramos do bulk passam a montar o `resource_name` com o `caminho` do alvo e chamar `operacao_de_status`. O payload (`campaign_ids`, `ad_group_ids`, `ads`, `keywords`, `new_status`) não muda: é contrato persistido no token pendente.
- [ ] **Step 3:** rodar a caracterização e os 5 `test_*_mutate_builder.py`/`test_bulk_pause_builder.py`. Expected: PASS. Commit `refactor(mcp): builders de status por tabela`.

### Task C2: builders `audit_*` recebem `date` e usam os helpers da janela

**Files:** Modify `src/google_ads/queries/audit_quality_score.py:9-53`, `audit_competitor_keywords.py:32-45`, `audit_zombie_keywords.py:17-61`, `audit_orphan_smart_actions.py:17-57`; as 4 tools em `src/mcp/tools/` (linhas do `isoformat`: `audit_quality_score.py:105`, `audit_competitor_keywords.py:106`, `audit_zombie_keywords.py:91`, `audit_orphan_smart_actions.py:99`); `tests/unit/test_ratchet_camadas.py`.

- [ ] **Step 1:** os testes `test_audit_*_query` existentes comparam a string da query: rodar e ver PASS antes.
- [ ] **Step 2:** os 4 builders passam a `*, start_date: date, end_date: date`; cláusula via `gaql_date_clause(start, end)`; `"date_range"` via `janela_aplicada(start, end)`; os `fromisoformat` internos saem; as tools passam o `date` direto. Ajustar os testes que chamavam com `str`.
- [ ] **Step 3:** tirar os 2 arquivos de `test_janela_so_no_common` (allowlist vazia). Rodar os testes de audit e o ratchet. Expected: PASS, mesma string de query. Commit `refactor(mcp): builders audit_* usam a janela comum`.

### Task C3: um helper só para nome de enum

**Files:** Modify `src/google_ads/queries/_common.py`, `queries/ad_schedule.py:27`, `queries/assets.py:53`, `queries/recommendations.py:683`, `change_scan.py:61-65`, `preflight.py:598,601,663,743,841,845`, `src/mcp/tools/get_recommendations.py:43`. Test: `tests/unit/test_nome_do_enum.py` (novo).

**Interfaces — Produces:** `def nome_do_enum(valor: Any) -> str` em `_common.py`: `str(valor.name) if hasattr(valor, "name") else str(valor)`.

- [ ] **Step 1:** testes: enum real do SDK → nome; `int` → `str(int)`; `None` → `"None"`. Guard `test_idioma_so_no_helper`: `hasattr(` com `"name"` em `src/` só dentro de `nome_do_enum`.
- [ ] **Step 2:** trocar as 3 definições e os 10 sítios inline. Rodar os testes novos e `pytest tests/unit -q -k "assets or schedule or recommendation or preflight or change"`. Expected: PASS. Sabotagem do guard: recolocar um `x.name if hasattr(x, "name")` → FAIL. Commit `refactor(mcp): helper único de nome de enum`.

### Task C4: resultado dos executores tipado

**Files:** Modify `src/google_ads/mutations.py:370,511`, `conversions.py:42-255`, `customer_match.py:202-494`, `confirmadores.py:58`; Create `src/google_ads/resultados.py`.

**Interfaces — Produces:** em `resultados.py`, `TypedDict` `ResultadoMutacao` (`provider_request_id, applied_count, changed_count, partial_failures, resource_names, motivos_medidos`), `ResultadoRecomendacao` (`provider_request_id, applied_count`), `ResultadoUploadAplicado` e `ResultadoUploadErro` (as chaves de sucesso e de erro medidas em `conversions.py:255` e `:76/:237`), `ResultadoCustomerMatch` (as 8 chaves de `customer_match.py:494`). `Executor = Callable[..., Awaitable[Mapping[str, Any]]]` em `confirmadores.py` (`TypedDict` não é atribuível a `dict[str, Any]`).

- [ ] **Step 1:** teste `test_chaves_do_resultado_batem_com_o_tipo`: para cada executor, com os fakes dos testes `test_run_*` existentes, o conjunto de chaves devolvido == `Tipo.__annotations__.keys()` (para o upload, uma das duas).
- [ ] **Step 2:** anotar os 4 retornos e o `Executor`; trocar nos consumidores os `.get` de chave obrigatória por indexação só onde o tipo a declara obrigatória. Rodar mypy e os testes. Expected: verde, sem `type: ignore` novo. Commit `refactor(mcp): resultado dos executores tipado`.

### Task C5: miudezas de micros

**Files:** Modify `src/google_ads/mutates/campaigns.py:97,176,227,240,251`, `src/google_ads/ad_schedule.py:252`, `queries/ad_schedule.py:98`.

- [ ] **Step 1:** `_brl_to_micros` sai; as 4 chamadas usam `brl_para_micros`. Os dois `round(x / 1_000_000, 2)` viram `micros_to_currency(x)`.
- [ ] **Step 2:** rodar `pytest tests/unit -q -k "campaign or schedule"`. Expected: PASS. Commit `refactor(mcp): conversão de micros pelos helpers`.

---

## Parte D — Tools MCP (PR `refactor/tools-varredura-10-11`, full sweep)

### Task D1: `aplicar_limite` nas 3 tools que cortam à mão

**Files:** Modify `src/mcp/tools/get_budget_pacing.py:261`, `get_conversion_actions.py:78`, `get_recommendations.py:80`.

- [ ] **Step 1:** trocar `truncated = len(x) > limit; x = x[:limit]` por `x, truncated = aplicar_limite(x, limit)`. O `run_gaql` fica como está: a resposta dele traz `row_count` anterior ao corte e o `aggregate_by` tem teto fixo de 1000 (medido em 10/11).
- [ ] **Step 2:** rodar os testes das 3 tools e `tests/unit/test_declaracao_de_truncamento.py`. Expected: PASS. Commit `refactor(mcp): corte por limite pelo helper`.

### Task D2: fragmentos de schema num lugar só

**Files:** Modify `src/mcp/tools/_meta_performance.py`, `_meta_common.py`, as 13 tools Meta com o bloco `ad_account_id` idêntico (lista medida: `account_balance`, `account_overview`, `ad_performance`, `ad_preview`, `ad_set_performance`, `budget_pacing`, `campaign_performance`, `change_history`, `creatives`, `delivery_estimate`, `entities`, `pages`, `search_targeting`), `get_performance_breakdown.py:30-41`.

**Interfaces — Produces:** `SCHEMA_PERFORMANCE_META: dict[str, Any]` em `_meta_performance.py`; `PROPRIEDADE_AD_ACCOUNT_ID: dict[str, Any]` em `_meta_common.py`. `meta_get_performance_breakdown` mantém a description própria (é contrato).

- [ ] **Step 1:** as 3 tools de performance usam `SCHEMA_PERFORMANCE_META`; as 13 usam `PROPRIEDADE_AD_ACCOUNT_ID` (cópia rasa por tool, `dict(PROPRIEDADE_AD_ACCOUNT_ID)`, para ninguém mutar o compartilhado); `_DATE_PRESETS = list(PRESETS_EM_ORDEM)`.
- [ ] **Step 2:** rodar `tests/unit/test_schemas_snapshot.py` **sem** `V4_REGRAVAR_SCHEMAS`. Expected: PASS, fixture intacto. Commit `refactor(mcp): fragmentos de schema compartilhados`.

### Task D3: resíduo do `emitir_preview`

**Files:** Modify `src/mcp/tools/_mutate_common.py:147-156` e os 21 chamadores, `create_and_link_assets.py:311`, `import_offline_conversions.py:303`, `upload_customer_match_list.py:208`, `tests/unit/test_ratchet_camadas.py`.

- [ ] **Step 1:** renomear o kwarg `summary` de `emitir_preview` para `resumo` em todos os chamadores (libera `summary` como extra do envelope).
- [ ] **Step 2: caracterização.** Para `create_and_link_assets`, `import_offline_conversions` e `upload_customer_match_list`, gravar no teste o envelope de dry-run de uma entrada fixa (todas as chaves e valores, menos o token) e ver PASS no código atual.
- [ ] **Step 3:** migrar as 3 para `emitir_preview`. Se o envelope de `upload_customer_match_list` não sair idêntico (a ordem do `extra` em `_mutate_common.py:143` é a suspeita), ela fica fora e o motivo vai no ledger.
- [ ] **Step 4:** tirar da allowlist de `test_create_pending_so_no_helper` as migradas. Rodar a caracterização, `tests/unit/test_envelope_applied_e_unico.py` e o ratchet. Expected: PASS. Commit `refactor(mcp): tools restantes no emitir_preview`.

### Task D4: bloco de orçamento compartilhado numa função

**Files:** Create `src/google_ads/orcamento_compartilhado.py`; Modify `src/mcp/tools/update_campaign_budget.py:52-104`, `update_ad_schedule.py:481-528`.

**Interfaces — Produces:** `def montar_bloco(*, budget_id: str, budget_resource_name: str, amount_brl: float, irmas: list[dict[str, Any]], no_lote: Callable[[str], bool], sufixo_aviso: str) -> dict[str, Any]` — as 8 chaves medidas (`budget_id`, `budget_resource_name`, `explicitly_shared`, `amount_brl`, `campaigns_in_batch`, `campaigns_outside_batch`, `ativas_fora_do_lote`, `warning_pt`). A leitura (`consulta(campaigns_on_budgets_query(...))`) e o `sorted` do schedule ficam nas tools.

- [ ] **Step 1:** o teste de paridade de chaves de `test_update_campaign_budget.py:201` é a rede: rodar, PASS.
- [ ] **Step 2:** as duas tools passam a chamar `montar_bloco`, cada uma com o seu `no_lote` e o seu sufixo (ATINGE × REALOCA).
- [ ] **Step 3:** rodar `test_update_campaign_budget.py`, `test_update_ad_schedule.py`, `test_apply_change_ad_schedule.py`. Expected: PASS. Commit `refactor(mcp): bloco de orçamento compartilhado numa função`.

### Task D5: pacing Google no domínio e helpers numéricos neutros

**Files:** Create `src/google_ads/pacing.py`, `src/razoes.py`; Modify `src/mcp/tools/get_budget_pacing.py:63-197`, `src/google_ads/queries/_common.py:196-239`, `src/meta_ads/pacing.py:12`, `tests/unit/test_budget_pacing_today.py:21`, `tests/unit/test_razao_indefinida.py:212`. Test: `tests/unit/test_meta_nao_importa_google.py` (novo).

**Interfaces — Produces:** `razao`, `arredondado`, `percentual` em `src/razoes.py`, reexportados por `_common.py` (os ~18 importadores atuais não mudam); `ritmo`, `projetar_linhas`, `projetar_orcamentos` em `src/google_ads/pacing.py` (as três de hoje, sem o `_`, mesmas assinaturas).

- [ ] **Step 1:** guard `test_meta_ads_nao_importa_google_ads`: nenhum `import`/`from` de `src.google_ads` em `src/meta_ads/` (usar `h.origens_de_import`). Rodar: FAIL hoje (o `pacing.py`).
- [ ] **Step 2:** criar `src/razoes.py` movendo as três funções; `meta_ads/pacing.py` importa de lá. Mover as três de pacing para `google_ads/pacing.py`. Reapontar os 2 sítios de patch/import nos testes; grep por `get_budget_pacing._ritmo`, `._project`, `._projeta_orcamentos` em `tests/` dá zero.
- [ ] **Step 3:** rodar o guard, os testes de pacing e `test_razao_indefinida.py`. Expected: PASS. Commit `refactor(mcp): pacing Google no domínio`.

### Task D6: envelope de erro de entrada das tools Meta

**Files:** Modify `src/mcp/tools/_meta_common.py` e as tools Meta com `{"status": "error", "error_message": ...}` literal; `meta_get_ad_preview.py:64` (`_erro` local sai).

**Interfaces — Produces:** `def erro_de_entrada(mensagem: str) -> dict[str, Any]` → `{"status": "error", "error_message": mensagem}`. Só substitui literal com **exatamente** essas duas chaves; literal com outras chaves fica (mudaria o contrato).

- [ ] **Step 1:** grep dos literais; trocar só os de duas chaves. Rodar `pytest tests/unit -q -k meta`. Expected: PASS. Commit `refactor(meta_ads): envelope de erro de entrada num helper`.

---

## Parte E — Meta, jobs e scripts (PR `refactor/meta-varredura-10-11`, full sweep)

### Task E1: URL base da Graph num lugar só

**Files:** Modify `src/meta_ads/client.py:28`, `alcance.py:30`, `partnership.py:17`, `reports.py:338`. Test: `tests/unit/test_structural_guards.py`.

**Interfaces — Produces:** `META_GRAPH_BASE_URL = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}"` em `client.py`.

- [ ] **Step 1:** guard `test_host_da_graph_so_no_client`: o literal `graph.facebook.com` em `src/` só em `client.py`. Rodar: FAIL. Trocar os 3 sítios. Rodar: PASS; sabotagem com um literal em `alcance.py` → FAIL. Commit `refactor(meta_ads): URL base da Graph num lugar só`.

### Task E2: `paginas_graph` entrega a página já lida

**Files:** Modify `src/meta_ads/graph.py:46-110`, `src/meta_ads/reports.py:92-130`. Consumes: A5.

**Interfaces — Produces:** `paginas_graph(...) -> AsyncIterator[tuple[httpx.Response, Any]]` — o corpo é lido **uma** vez; o gerador não decide o que fazer com corpo que não é objeto (só para de paginar). Cada consumidor mantém a sua regra: `fetch_paginated` marca incompleto (A5), `_paginar_graph` levanta `MetaGraphHTTPError` (como hoje).

- [ ] **Step 1:** teste `test_corpo_lido_uma_vez`: `httpx.Response` com `json` contado por wrapper → uma leitura por página.
- [ ] **Step 2:** implementar; rodar os testes de A5, `test_paginar_graph_corpo_nao_json_objeto_levanta`, `test_meta_graph_paginacao.py`, `test_meta_paginacao_usa_url_completa.py`, `test_meta_secret_leak.py`. Expected: PASS. Commit `refactor(meta_ads): página da Graph lida uma vez`.

### Task E3: pré-condição de conta em BRL num helper

**Files:** Create `src/meta_ads/moeda.py`; Modify `src/mcp/tools/meta_get_entities.py:101-119`, `meta_get_budget_pacing.py:269-287`.

**Interfaces — Produces:** `async def exigir_brl(ad_account_id: str, *, manager_id: UUID, session_id: UUID) -> dict[str, Any] | None` — `None` quando a conta é BRL; senão o envelope de erro que as tools devolvem hoje, idêntico. **Decisão do Wellington (10/11):** a fonte passa a ser a coluna `meta_ad_accounts.currency` (lida pelo repositório, sem chamada à Graph); a conta já passou pelo gate, que exige a linha ativa no inventário.

- [ ] **Step 1:** os testes "moeda não-BRL" das duas tools são a rede: PASS antes. Extrair o helper com a fonte de hoje; rodar de novo. Expected: PASS. Commit `refactor(meta_ads): pré-condição de BRL num helper`.
- [ ] **Step 2 (decisão de 10/11):** teste que falha: com o fake da Graph trocado por um que levanta ao ser chamado, a tool com conta BRL na tabela responde normalmente e a com conta USD na tabela devolve o envelope de hoje. Trocar a fonte para o repositório (função `currency_of(conn, ad_account_id) -> str | None` em `meta_ad_accounts.py`; `None` → o mesmo envelope de "moeda não confirmada" que a tool já usa quando a Graph não responde, se existir; se não existir, o de não-BRL). Rodar os testes das duas tools e o full sweep. Commit `feat(meta_ads): moeda da conta lida do inventário`.

### Task E4: docstrings desatualizadas

**Files:** `src/meta_ads/reports.py:8-9,108,234`, `client.py:11-12`, `meta_ads/__init__.py:8-9`, `labels.py:3-5`, `src/scripts/admin.py:1`, `scripts/probe_meta_auth_header.py:3`.

- [ ] **Step 1:** corrigir cada texto para o estado atual (sem `/me/adaccounts` como exemplo; `ler_colecao` usa `max_pages>1`; o tratamento dos dois erros é das tools; sem "future sprints"; sem re-export removido; o painel existe; o OAuth pessoal saiu). Rodar o gate. Commit `docs(meta_ads): docstrings no estado atual`.

### Task E5: `admin.py` com um gerenciador de conexão

**Files:** Modify `src/scripts/admin.py:44-202`. Consumes: A3.

**Interfaces — Produces:** `@asynccontextmanager async def _conexao() -> AsyncIterator[asyncpg.Connection]` — abre o pool, entrega uma conexão, fecha o pool no `finally`.

- [ ] **Step 1:** os 6 comandos usam `_conexao()`. Rodar `tests/integration/test_admin_script.py`. Expected: PASS. Commit `refactor(admin): um gerenciador de conexão no CLI`.

### Task E6: o contador das leituras Meta conta só as páginas lidas (decisão de 10/11)

**Files:** Modify `src/meta_ads/reports.py` (~L352 e ~L395, o `max(estimated, lidas)`). Test: `tests/unit/test_meta_reports_versao_e_uso.py`.

- [ ] **Step 1: teste que falha.** Leitura com `max_pages=5` que traz 2 páginas: o valor gravado no audit (`target_count` ou o campo que hoje recebe o `max`) e o reconciliado na cota é **2**, não 5. Rodar: FAIL. Trocar o `max(estimated, lidas)` por `lidas` nos dois sítios; a reserva antes da chamada continua usando `estimated`. Rodar o arquivo e `test_meta_graph_paginacao.py`. Commit `fix(meta_ads): cota e audit gravam as páginas lidas`.

### Task E7: a sonda de alcance passa pelo aviso de versão (decisão de 10/11)

**Files:** Modify `src/meta_ads/alcance.py` (~L102). Test: o arquivo de teste da sonda (`tests/unit/test_meta_alcance*.py`).

- [ ] **Step 1: teste que falha.** Resposta da Graph com o cabeçalho de versão descontinuada que os outros dois caminhos já tratam: a sonda chama `avisar_versao_meta` uma vez. Rodar: FAIL. Chamar o aviso como `reports.py`/`graph.py` fazem. Rodar o teste e os de versão existentes. Commit `fix(meta_ads): sonda de alcance avisa a versão da API`.

### Task E8: `classify` conhece as duas operações sem registro (decisão de 10/11)

**Files:** Modify o módulo de classificação de risco (`src/governance/blast_radius.py` ou onde `classify` vive), `tests/unit/test_preview_caracterizacao.py` (o texto "unknown operation" congelado na D3). Test: `tests/unit/test_blast_radius_bate_com_as_tools.py`.

- [ ] **Step 1: teste que falha.** `classify` de `create_and_link_assets` e `import_offline_conversions` devolve "sempre confirmar" com motivo próprio em PT-BR (não "unknown operation"); e um guard: toda operação de mutate registrada no `CONFIRMADORES` tem entrada explícita na classificação. Rodar: FAIL. Registrar as duas como sempre-confirmar; atualizar o texto esperado na caracterização da D3 (mudança deliberada, citada no commit). Rodar o arquivo, a caracterização e `test_envelope_applied_e_unico.py`. Commit `fix(mcp): classify registra create_and_link_assets e import_offline_conversions`.

---

## Parte F — db, web e governança, baixo risco (PR `refactor/db-varredura-10-11`, full sweep)

### Task F1: uma fonte só para o fuso

**Files:** Modify `src/config.py:21`, `src/web/templating.py:28`, `src/web/numeros.py:55,64`, `tests/unit/test_config.py:23`, `.github/workflows/deploy.yml:202`.

- [ ] **Step 1:** `templating.py` importa `FUSO_PAINEL` de `src/web/numeros.py` (o `_BRASILIA` sai); o SQL de `numeros.py` usa `FUSO_PAINEL.key` como parâmetro, não literal; `app_timezone` sai do `Settings` e do teste; `APP_TIMEZONE=...` sai do `--set-env-vars` (o `extra="ignore"` torna a ordem do deploy indiferente). Guard: o literal `America/Sao_Paulo` em `src/` só em `numeros.py:23`.
- [ ] **Step 2:** rodar o gate e o guard; sabotagem com o literal em `templating.py` → FAIL. Commit `refactor(web): uma fonte só para o fuso`.

### Task F2: tipos do gate, da cota e lixo

**Files:** Modify `src/db/repositories/manager_account_access.py:21,170`, `manager_meta_account_access.py:195`, `src/google_ads/access.py:35`, `src/governance/reserva.py:34,52`.

**Interfaces — Produces:** `NivelDeAcesso = Literal["read", "write"]` em `manager_account_access.py`, importado pelos outros dois.

- [ ] **Step 1:** `AccountAccess` sai (zero usos medidos); `level: NivelDeAcesso`; `pool: asyncpg.Pool`. Rodar mypy e o gate. Expected: verde. Commit `refactor(db): tipos do gate e da cota`.

### Task F3: contagem de linhas afetadas num helper

**Files:** Create `src/db/repositories/_comum.py`; Modify `google_ads_accounts.py:173,252`, `manager_account_access.py:103,325`, `manager_meta_account_access.py:93,327`, `meta_ad_accounts.py:12-14,189`, `src/jobs/purge.py:37`.

**Interfaces — Produces:** `def linhas_afetadas(status: str) -> int` — último token do status do `execute` (`"UPDATE 3"` → 3, `"INSERT 0 2"` → 2). `_rows_affected` sai.

- [ ] **Step 1:** teste unitário com `UPDATE 3`, `INSERT 0 2`, `DELETE 0`. Trocar os 9 sítios. Rodar o teste e o full sweep. Commit `refactor(db): linhas afetadas num helper`.

### Task F4: ciclo de import entre inventário e acesso

**Files:** Create `src/db/repositories/motivos.py`; Modify `manager_account_access.py:16-17,301`, `manager_meta_account_access.py:14,304`, `google_ads_accounts.py:300`, `meta_ad_accounts.py:308`, `manager_account_access.py:9`, `manager_meta_account_access.py:7`; `tests/unit/test_acesso_gemeos_conformes.py` (B2 tem que continuar resolvendo a constante até o valor: o default `reason=ADMIN_REVOKED_REASON` reexportado de `motivos.py` compara `'admin_revoked'` × `'manual'`, não o nome da constante).

**Interfaces — Produces:** `LEFT_MCC_REASON`, `ADMIN_REVOKED_REASON`, `PARTNERSHIP_ENDED_REASON`, `BULK_COPY_REPLACED_REASON = "bulk_copy_replaced"` em `motivos.py`, reexportados pelos módulos de hoje. `_row_to_account` vira `row_to_account` nos dois inventários.

- [ ] **Step 1:** os imports locais de `:300`/`:308` sobem para o topo, vindos de `motivos.py`; os dois `'bulk_copy_replaced'` usam a constante. Rodar o gate e o full sweep. Commit `refactor(db): motivos de revogação num módulo neutro`.

---

## Parte G — Acesso e audit (PR `refactor/acesso-varredura-10-11`, full sweep, `tests/browser` e clique em produção)

### Task G0: as decisões de 10/11 sobre acesso, antes do núcleo

**Files:** Modify `src/db/repositories/manager_account_access.py` (`grant_all_active`, `bulk_grant`), `manager_meta_account_access.py` (`bulk_grant`, `revoke`), `tests/unit/test_acesso_gemeos_conformes.py`. Test: `tests/integration/test_manager_account_access.py`, `test_manager_meta_account_access.py`.

- [ ] **Step 1: medir.** grep em `src/` e `tests/` por `"manual"` como motivo de revogação: listar cada leitor (fila, painel, relatório) e o que ele faz com o valor. Se algum código depende de `manual`, PARE e registre no ledger (decisão volta ao Wellington). Linhas antigas no banco ficam como estão (histórico; leitura direta do banco de produção é barrada).
- [ ] **Step 2: testes que falham (integração).** Re-concessão de conta revogada por `grant_all_active` (Google) e por `bulk_grant` (Google e Meta) atualiza `granted_at` e `granted_by`; `revoke` Meta sem motivo explícito grava `admin_revoked`. Rodar: FAIL.
- [ ] **Step 3:** `ON CONFLICT` dos três com `granted_at = now(), granted_by = EXCLUDED.granted_by`; default de `revoke` Meta = `ADMIN_REVOKED_REASON` (constante movida para `motivos.py` na F4). B2: sai do registro e do snapshot o que deixou de divergir (`grant_all_active`, `revoke`); fica `can_manager_access`. Rodar os testes, B2 e o full sweep. Commit `fix(db): re-concessão registra quem e quando, e revogação manual unificada`.

### Task G1: escritas dos repositórios de acesso num núcleo

**Files:** Create `src/db/repositories/_acesso_comum.py`; Modify `manager_account_access.py`, `manager_meta_account_access.py`. Consumes: B2.

**Interfaces — Produces:** `@dataclass(frozen=True) class TabelaDeAcesso: tabela: str; coluna_conta: str; inventario: str; atualiza_concessao_no_grant_all: bool; motivo_revoke_padrao: str` e `GOOGLE`, `META`; `grant`, `grant_all_active`, `revoke`, `bulk_grant`, `copy_access` em `_acesso_comum.py` recebendo `t: TabelaDeAcesso` primeiro. Os dois módulos mantêm as assinaturas públicas de hoje, como funções finas. `can_manager_access` e `list_accounts_for_manager` **não** passam pelo núcleo. O registro de B2 tem TRÊS entradas: as duas de escrita (`grant_all_active` → `atualiza_concessao_no_grant_all`, `revoke` → `motivo_revoke_padrao`) viram campos do descritor (o comportamento de hoje se mantém até a decisão pendente); a de `can_manager_access` (ordem dos predicados do `WHERE`) fica como está, porque a função não entra no núcleo nem vira campo.

- [ ] **Step 1:** os testes de B2 e os 9 arquivos de teste dos repositórios são a rede, verdes antes: `tests/integration/test_manager_account_access.py`, `test_manager_meta_account_access.py`, `test_meta_grants_soft_revoke.py`, `test_repositories.py`, `test_admin_access_idempotente.py`, `test_admin_meta_access.py`; `tests/unit/test_account_access.py`, `test_gate_google_exige_conta_ativa.py`, `test_gate_meta_exige_conta_ativa.py`.
- [ ] **Step 2:** criar o núcleo com SQL montado só a partir dos campos do descritor (nada de entrada externa no SQL); trocar as 5 funções de cada módulo.
- [ ] **Step 3:** B2 em duas metades. As assinaturas das funções finas e os 2 pares fora do núcleo (`list_accounts_for_manager`, `can_manager_access`) continuam comparados por AST, como hoje. O SQL do núcleo para `GOOGLE` e para `META` é capturado em runtime com uma conexão falsa (cada uma das 5 funções de escrita tem que emitir ao menos um statement; entrada vazia não conta, porque a função pode retornar antes de falar com o banco) e comparado com a mesma normalização e os mesmos `_DIFERENCAS_ESPERADAS`. As divergências que viraram campo ganham um teste: `{campo: (GOOGLE.x, META.x)}`, só dos campos que diferem (fora os de nome: `tabela`, `coluna_conta`, `inventario`), é igual ao que o registro descreve (`{"atualiza_concessao_no_grant_all": (False, True), "motivo_revoke_padrao": ("admin_revoked", "manual")}`); e os argumentos de bind capturados confirmam o `reason` que `revoke` grava em cada lado. Rodar o full sweep. Expected: verde. Commit `refactor(db): escritas de acesso num núcleo`.

### Task G2: leituras das rotas em repositórios

**Files:** Modify `src/web/routes/admin_access.py:42,79,185,202,245,329,346,394`, `_acesso.py:68-107`, `accounts.py:32,69`, `admin_invites.py:53,98,138`, `admin_overview.py:56,62,69`, `dashboard.py:42`; os repositórios donos (`manager_account_access`, `manager_meta_account_access`, `google_oauth_connections`, `managers`, `audit_log`); `tests/unit/test_ratchet_camadas.py`. Consumes: A2, G1.

- [ ] **Step 1:** para cada leitura, uma função no repositório dono, com o SQL de hoje sem alteração; os pares gêmeos (matriz de grants, gestores com contagem, contas ativas, grants de um gestor) entram nos dois repositórios de acesso com a mesma assinatura. Um teste de integração por função nova (mesmo resultado que a rota mostrava).
- [ ] **Step 2:** as rotas chamam as funções; `sql_acesso_vivo` vira função de repositório. Allowlist de `test_rota_nao_chama_conn_direto` vazia.
- [ ] **Step 3:** rodar o full sweep e `tests/browser`. Expected: verde. Commit `refactor(web): leituras das rotas em repositórios`. Depois do deploy: clique logado nas 8 páginas do admin.

### Task G3: montador de filtros do `audit_log`

**Files:** Modify `src/db/repositories/audit_log.py:90-125,134-160,256-290,326-370,442-500`, `src/web/routes/dashboard.py:42-49` (já movido em G2). Test: `tests/unit/test_audit_log_sql.py` (novo), `tests/integration/test_audit_keyset.py`.

**Interfaces — Produces:** `class _Filtros: def __init__(self) -> None; def add(self, fragmento: str, valor: Any) -> None` (o `fragmento` traz `{}` onde vai o `$n`); `sql: str` (`" AND ".join` ou `"TRUE"`); `params: list[Any]`. `_SQL_NOME_DA_CONTA`: o `LEFT JOIN google_ads_accounts` padronizado.

- [ ] **Step 1: caracterização.** Para cada um dos 4 construtores e para `get_by_id`, uma matriz de combinações de filtro (nenhum, todos, cada um sozinho, com cursor): gravar no teste o SQL normalizado (espaços colapsados) e os `params` de hoje; PASS.
- [ ] **Step 2:** os 4 construtores usam `_Filtros`, **cada um na sua ordem de filtros de hoje** (o admin põe `customer_id` antes de `action_type`, o de gestor não); `get_by_id` vira uma consulta com o filtro de gestor opcional. `export_csv_rows` mantém `manager_id` sem default (F205).
- [ ] **Step 3:** rodar a caracterização, `test_audit_keyset.py` (EXPLAIN) e o full sweep. Expected: verde. Commit `refactor(db): montador de filtros do audit`.

> **Nota de 10/11 para a G1:** com a G0 feita, os dois lados escrevem igual; o descritor fica só com os
> campos de nome (`tabela`, `coluna_conta`, `inventario`), sem `atualiza_concessao_no_grant_all` nem
> `motivo_revoke_padrao`, e o teste de campos divergentes do Step 3 afirma que eles são só os de nome.

### Task G5: nome da conta Meta no audit (decisão de 10/11)

**Files:** Modify `src/db/repositories/audit_log.py` (`_SQL_NOME_DA_CONTA` da G3 e o `get_by_id`), `src/web/routes/dashboard.py` (subquery do nome). Consumes: G3. Test: `tests/integration/test_web_panel_audit.py`, `tests/integration/test_audit_keyset.py`.

- [ ] **Step 1: teste que falha.** Linha de audit com `customer_id = act_<id>` presente em `meta_ad_accounts`: a página `/audit` e o dashboard mostram o `account_name`; linha Google segue com o `descriptive_name`. Rodar: FAIL.
- [ ] **Step 2:** `LEFT JOIN meta_ad_accounts` ao lado do de `google_ads_accounts`, nome = `COALESCE` dos dois. Rodar os testes, o EXPLAIN de `test_audit_keyset.py` (o JOIN novo não pode tirar o uso do índice), `tests/browser` e o full sweep. Commit `feat(web): audit mostra o nome da conta Meta`. Depois do deploy: abrir `/audit` em produção (só leitura).

### Task G4: núcleo da regra de reconciliação

**Files:** Create `src/reconciliacao.py`; Modify `src/google_ads/reconcile.py:60-136`, `src/meta_ads/reconcile.py:56-158`. Consumes: B1.

**Interfaces — Produces:** `@dataclass(frozen=True, slots=True) class LinhaNeutra: conta: str; is_active: bool; missed_syncs: int; fuso: str | None; last_missed_on: date | None`; `def faltas_com_esta_execucao(r: LinhaNeutra, *, now: datetime) -> int`; `def plano_neutro(*, presentes: set[str], inventario: list[LinhaNeutra], complete: bool, now: datetime, threshold: int, max_removal_ratio: float, max_removal_abs: int) -> PlanoNeutro` com `PlanoNeutro(to_add, to_bump, to_remove, to_reset, blocked_reason)`. Os dois `build_plan` mantêm as assinaturas de hoje, convertem a sua `InventoryRow` em `LinhaNeutra` e montam o seu `Plan`; o Meta acrescenta `unreachable` e o propaga também no plano bloqueado.

- [ ] **Step 1:** verdes antes: B1, `tests/unit/test_google_reconcile.py`, `test_meta_reconcile_plan.py`, `test_meta_reconcile_job.py`, `test_account_resync.py`, `test_resync_empty_inventory_guard.py`, `test_job_partial_failure_audit.py`, `test_meta_resync_audit.py`; `tests/integration/test_google_reconcile_repo.py`, `test_meta_reconcile_repo.py`, `test_repositories.py`.
- [ ] **Step 2:** extrair; nenhum texto de `blocked_reason` muda.
- [ ] **Step 3:** rodar todos e o full sweep. Expected: verde. Commit `refactor(meta_ads): núcleo da regra de reconciliação`.

---

## Parte H — Auth (PR `refactor/auth-varredura-10-11`, gate e `tests/browser`)

### Task H1: um codec de token assinado

**Files:** Create `src/auth/token_assinado.py`; Modify `src/auth/oauth_state.py:74-148`, `src/auth/panel_session.py:42-115`. Test: `tests/unit/test_token_assinado.py` (novo).

**Interfaces — Produces:** `def assinar(claims: dict[str, Any], chave: str, *, aud: Audience, issued_at: float | None = None) -> str` e `def verificar(token: str, chave: str, *, aud: Audience, ttl: int, erro: type[Exception]) -> dict[str, Any]` (devolve as claims sem `aud` e `iat`), com o formato e a ordem de checagens medidos (body JSON `sort_keys`, separadores `(",", ":")`; tag HMAC-SHA256; `split(".", 1)` → HMAC → JSON → dict → `aud` → `iat` int → TTL) e as mesmas mensagens de erro. `sign_state`, `verify_state`, `sign_panel_session`, `verify_panel_session` e as audiências mantêm as assinaturas.

- [ ] **Step 1: caracterização.** `test_token_byte_a_byte`: para `sign_state` (as duas audiências) e `sign_panel_session`, com `issued_at` fixo e chave fixa, gravar no teste o token de hoje; PASS. `test_mensagens_de_erro_iguais`: cada falha (malformado, HMAC, audiência, `iat`, expirado) com a mensagem de hoje; PASS.
- [ ] **Step 2:** criar o codec; os 4 públicos passam a usá-lo; os `_b64url*` duplicados saem.
- [ ] **Step 3:** rodar o arquivo novo, `test_confusao_de_token.py`, `test_oauth_state.py`, `test_panel_session.py`, `test_oauth_flow.py`. Expected: PASS. Commit `refactor(auth): um codec de token assinado`.

### Task H2: `_concluir_callback` em passos

**Files:** Modify `src/auth/oauth.py:282-461`.

**Interfaces — Produces:** `class _RespostaAntecipada(Exception): resposta: Response`; `async def _trocar_code(http: httpx.AsyncClient, code: str, settings: Settings) -> tuple[str, str, bool | None]` (refresh_token, email, verified_email); `async def _resolver_gestor_do_painel(email: str) -> UUID`; `def _cookie_do_painel(resposta: RedirectResponse, *, manager_id: UUID, email: str, settings: Settings) -> None`. Cada saída antecipada de hoje (502, 400, 403, redirect de acesso negado) vira `raise _RespostaAntecipada(<a mesma resposta>)`; `_concluir_callback` a captura e devolve. Os imports locais de `:399` e `:435` sobem para o topo.

- [ ] **Step 1:** `test_oauth_flow.py` e `test_oauth_navegador.py` são a rede: verdes antes. Extrair; rodar. Expected: PASS. Commit `refactor(auth): callback do OAuth em passos`.

### Task H3: `handle_callback_decision` síncrona e sem parâmetros mortos

**Files:** Modify `src/auth/oauth.py:48,367`, `tests/unit/test_oauth_allowlist.py` (8 chamadas), `tests/unit/test_auth_nao_importa_web.py:77`, `tests/unit/test_manager_deactivation_gate.py:169`.

- [ ] **Step 1:** tirar `async`, `google_id` e `google_email`; atualizar a chamada em `oauth.py` e as 10 dos testes. Rodar os 3 arquivos e `test_oauth_flow.py`. Expected: PASS. Commit `refactor(auth): decisão do callback síncrona`.

---

## Parte I — Núcleo das tools grandes (PR `refactor/nucleo-tools-10-11`, full sweep)

### Task I1: plano da grade de horário como função pura

**Files:** Modify `src/mcp/tools/update_ad_schedule.py:264-354,438-475`, `src/google_ads/ad_schedule.py`. Test: `tests/unit/test_planejar_grade.py` (novo).

**Interfaces — Produces:** `def planejar_grade(*, atual: dict[str, list[CurrentWindow]], desejada: list[Window], bid_modifier: float | None, campaign_ids: list[str], metricas: list[MetricCell], limpar: bool, status_da_campanha: dict[str, str], orcamento_compartilhado: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]` em `ad_schedule.py` — `(preview, ops)`, com os 3 formatos de `op` medidos (`add`, `remove`, `update`). `_aviso_status`, `_aviso_cobertura` e `_w` vão junto.

- [ ] **Step 1: caracterização.** Antes de mover, chamar a tool com entradas fixas (24x7 → faixas; faixas → limpar; só bid; campanha pausada) com os fakes de `test_update_ad_schedule.py` e gravar `preview` e `payload["ops"]`; PASS.
- [ ] **Step 2:** mover o laço; a tool chama `planejar_grade` e mantém o I/O. Testes unitários diretos da função para os mesmos 4 casos, sem mock.
- [ ] **Step 3:** rodar a caracterização, `test_update_ad_schedule*.py`, `test_ad_schedule_guards.py`, `test_apply_change_ad_schedule.py`. Expected: PASS. Commit `refactor(mcp): plano da grade como função pura`.

### Task I2: varredura particionada do `detect_drift` no `change_scan`

**Files:** Modify `src/mcp/tools/detect_drift.py:146-346`, `src/google_ads/change_scan.py`, `tests/unit/test_detect_drift.py` (18 alvos), `tests/integration/test_detect_drift.py` (3), `tests/unit/test_change_freshness.py` (1).

**Interfaces — Produces:** em `change_scan.py`, `TETO_POR_JANELA`, `TETO_EXAMINADO`, `@dataclass Varredura` (os campos de `_Varredura` e a property `truncada`) e `async def varrer(customer_id: str, *, inicio: date, fim: date, hoje: date, manager_id: UUID, session_id: UUID) -> Varredura`.

- [ ] **Step 1:** mover; reapontar os 22 alvos de patch: `_TETO_POR_JANELA` e `_TETO_EXAMINADO` → `src.google_ads.change_scan.TETO_*`; `consultar_change_history` → patch onde `varrer` o procura (`src.google_ads.change_scan.consultar_change_history`). `resolve_account_today` continua na tool.
- [ ] **Step 2:** grep em `tests/` por `detect_drift._TETO` e `detect_drift.consultar_change_history` dá zero. Rodar o full sweep. Expected: verde. Commit `refactor(mcp): varredura do drift no change_scan`.

### Task I3: lookups GAQL das tools no `preflight`

**Files:** Modify `src/google_ads/preflight.py`, `src/mcp/tools/update_ad_group_bid.py:76-90`, `update_keyword_bid.py:78-98`, `update_campaign_budget.py:131-157`, `apply_audience.py:165-182`; os testes com patch de `run_report` nessas tools (24 alvos: 12, 5, 5, 2); `tests/unit/test_ratchet_camadas.py`.

**Interfaces — Produces:** em `preflight.py`, keyword-only, cada uma com a query e o retorno medidos de hoje: `buscar_lances_de_grupo(*, manager_id, session_id, customer_id, ad_group_ids: list[str]) -> dict[str, dict[str, Any]]`; `buscar_lances_de_keyword(*, ..., pares: list[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]`; `buscar_orcamento_da_campanha(*, ..., campaign_id: str) -> dict[str, Any] | None`; `buscar_interesses(*, ..., ids: list[str]) -> list[dict[str, Any]]` (com `audit_this_call=False`, como hoje).

- [ ] **Step 1:** mover cada lookup; reapontar os 24 alvos para `src.google_ads.preflight.run_report`; o `_consulta` de `update_campaign_budget` que serve a outra leitura fica na tool.
- [ ] **Step 2:** allowlist de `test_gaql_so_fora_das_tools` vazia; grep em `tests/` pelos 4 alvos antigos de `run_report` dá zero. Rodar o full sweep. Expected: verde. Commit `refactor(mcp): lookups GAQL das tools no preflight`.

### Task I4: adaptadores `dict_to_*` estritos

**Files:** Modify `src/google_ads/queries/audit_zombie_keywords.py:91-105`, `audit_orphan_smart_actions.py:81-92`, `src/google_ads/goal_attribution.py:78,94`, `src/google_ads/drift_detection.py:132`, `tests/unit/test_audit_zombie_keywords_queries.py:70`, `tests/unit/test_audit_orphan_smart_actions_queries.py:74`.

- [ ] **Step 1: testes que falham.** Os 2 testes que prendem o default viram `test_dict_to_*_chave_ausente_levanta`: `pytest.raises(KeyError)`. Guard AST `test_dict_to_sem_default`: em funções `dict_to_*` de `src/google_ads/`, nenhuma chamada `.get` com dois argumentos. Os campos que **podem** faltar de propósito (`changed_fields`, `campaign_id`, `ad_group_id`, `old_status`, `new_status` em `drift_detection`) seguem com `.get(k)` de um argumento.
- [ ] **Step 2:** rodar. Expected: FAIL. Trocar os `.get(k, padrão)` por `d[k]`. Rodar os testes, o guard e os de audit/drift. Expected: PASS. Sabotagem: um `.get("impressions", 0)` → guard FAIL. Commit `fix(mcp): adaptadores de linha não inventam zero`.

---

## Parte J — Depois do F207 (PR próprio; só começa com o PR do F207 mesclado)

### Task J1: `backup.py` no esqueleto comum

**Files:** Modify `src/jobs/backup.py:101-104,176-182`. Test: `tests/integration/test_backup_restore.py`.

- [ ] **Step 1:** teste `test_crash_do_backup_grava_e_fecha_o_pool`: falha forçada na leitura → uma linha `db_backup`/`error` e o pool fechado. Usar `executar_job` e `configure_logging` como os dois resyncs. Rodar o arquivo e o full sweep. Commit `refactor(jobs): backup no esqueleto comum`.

### Task J2: desfecho explícito na etapa Google

**Files:** Modify `src/jobs/account_resync.py:43-54,310-325`.

**Interfaces — Produces:** `_pick_oauth_connection(...) -> Any | None` (só a conexão; a leitura extra de `managers.get_by_id` sai); `class Desfecho(Enum): OK, FALHOU, SEM_OAUTH` como retorno de `_etapa_google`.

- [ ] **Step 1:** `tests/unit/test_account_resync.py` e `test_job_partial_failure_audit.py` verdes antes e depois, sem alteração. Commit `refactor(jobs): desfecho explícito na etapa Google`.

---

## Decisões do Wellington (10/11, por menu) e onde entram

| # | decisão | task |
|---|---|---|
| 1 | re-concessão sempre atualiza `granted_at`/`granted_by`, nas duas plataformas e em todas as funções | G0 |
| 2 | motivo padrão do `revoke` unificado em `admin_revoked` (medindo antes quem lê `manual`) | G0 |
| 3 | moeda Meta lida de `meta_ad_accounts.currency` | E3, Step 2 |
| 4 | cota e audit das leituras Meta gravam só as páginas lidas | E6 |
| 5 | a sonda de alcance passa pelo `avisar_versao_meta` | E7 |
| 6 | audit mostra o nome da conta Meta | G5 |
| 7 | `classify` registra `create_and_link_assets` e `import_offline_conversions` como sempre-confirmar | E8 |
| 8 | C2: levantar os 3 tipos de recomendação novos do v25 e decidir depois | K1 |

## Parte K — Levantamento (sem código)

### Task K1: os 3 tipos de recomendação novos do v25

- [ ] Agente só de leitura: comparar o enum `RecommendationType` do SDK v24 × v25 (instalado no `.venv`), achar os 3 tipos novos, e para cada um dizer o que `apply` faz na conta, o risco e se algo no código já os trata (`src/google_ads/queries/recommendations.py`, ~L151 importa `v24`). O relatório volta ao Wellington para decidir a whitelist; só depois se troca o import. Nenhum commit de código.

## Fecho

- [ ] Ao fim de cada parte: gate, full sweep quando indicado, PR, aval nominal do Wellington para o merge, deploy verificado (revisão servindo, `/health?deep=1`, leitura real).
- [ ] Atualizar `docs/operacao/estado-atual.md` e o handoff da sessão; os achados novos vão ao catálogo pelo `/findings-add`, que é do Wellington.
