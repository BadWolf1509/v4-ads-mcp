# Correções da varredura de 30/10 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** corrigir os achados confirmados da varredura de 7 áreas de 30/10, em 6 PRs independentes e na ordem abaixo.

**Architecture:** cada bloco é uma branch a partir do `main` atualizado, um PR, auto-merge e vigia. Nenhum bloco depende de código de outro, mas todos rodam em sequência: o próximo só começa com o anterior no `main`. Os consertos usam o ponto único que já existe (`to_friendly`, `run_blocking`, `best_effort`, `Manager.is_deactivated`), sem mecanismo novo.

**Tech Stack:** Python 3.13, FastAPI, asyncpg, google-ads 31.4.0 (API v25), Graph v25.0 via httpx, HTMX, GitHub Actions.

**Spec:** não há spec de design: são correções. Os fatos estão em cada task, medidos em 30/10. As decisões do Wellington estão abaixo.

## Decisões já tomadas

- `primary_for_goal=True` passa a **exigir confirmação**.
- `dismiss_recommendation`: recusar prefixo de outra conta, **sem** teste de mutação real no Google.
- As 45 recusas do Pedro **ficam fora**: decisão de acesso, resolvida no painel pelo Wellington.

## Global Constraints

- Gate: `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py`, mudo, com o commit na mesma linha por `&&`. Nunca com pipe.
- Full sweep (`check_pre_push_full.py`) obrigatório nos blocos 1, 2, 3 e 5.
- Guard novo precisa falhar contra o código pré-fix: sabotagem por cópia em scratchpad, nunca `git checkout`.
- Não medido não é zero: ausente é `None`, nunca `0` nem `""`.
- `QuotaExhausted` sobe cru, nunca por `to_friendly` (F110).
- Commits em `fix(scope):`, `feat(scope):`, `chore:`, com o trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Mensagem por heredoc `<<'MSG'`.
- Migration commitada não se edita. Nenhum bloco deste plano cria migration: `had_effect` já existe (011).
- Subagente grava log só em `.superpowers/sdd/2026-10-30-varredura/`.
- Push e edição de `deploy.yml` só com autorização nominal do Wellington.

## Review Focus

1. **DDD 55 no telefone:** número local de Santa Maria (`55 9xxxx-xxxx`, 11 dígitos) não pode ganhar DDI como se já tivesse. Testado na Task 9.
2. **Conversão com 100% de recusa:** o audit diz erro, mas a resposta ao gestor continua trazendo as falhas por linha. Testado na Task 10.
3. **Aba velha na matriz de acesso:** clicar em estado já aplicado não pode inverter o acesso. Testado na Task 20.
4. **Job bloqueado com retry do Cloud Run:** repetir no mesmo dia não pode duplicar efeito. Testado na Task 5.
5. **Restore com tabela vazia:** `audit_log` sem linhas não pode dar `setval(0)` (erro de faixa). Testado na Task 4.

---

## Bloco 1 — `fix/oauth-erros-e-bloqueio`

### Task 1: Refresh do OAuth fora do event loop

Fato: `build_client` (`src/google_ads/client.py:35`) chama `GoogleAdsClient.load_from_dict`, que faz HTTP síncrono de refresh, dentro de `build_client_for_manager`, que é `async` e usa `run_blocking` em nada.

**Files:** Modify `src/google_ads/client.py`; Test `tests/unit/test_google_client.py` (ou o arquivo existente de `build_client_for_manager`); Modify o guard `test_chamada_bloqueante_sai_do_event_loop`.

**Interfaces:** Produces: `build_client_for_manager` continua `async`, mesma assinatura, agora com `await run_blocking(build_client, ...)`.

- [ ] Teste `test_build_client_nao_roda_no_event_loop`: monkeypatch de `build_client` que grava `threading.current_thread()`; assert `is not threading.main_thread()`.
- [ ] Rodar e ver falhar.
- [ ] Trocar o `return build_client(...)` por `await run_blocking(...)`, com os argumentos por `functools.partial` se o helper não aceitar kwargs.
- [ ] Incluir `load_from_dict` e `build_client` na lista de chamadas bloqueantes do guard estrutural.
- [ ] Rodar teste e guard; sabotar para ver o guard falhar; restaurar.
- [ ] Commit `fix(google_ads): refresh do OAuth sai do event loop`.

### Task 2: OAuth ausente ou revogado com mensagem que diz o que fazer

Fato: `NoOAuthConnectionError` e `RefreshError` nascem em `build_client_for_manager`, fora do `to_friendly` dos 6 executores e do `validate_gaql`, e viram "Erro interno" em `src/mcp/server.py:74`. O F70 cobriu só o decrypt.

**Files:** Modify `src/google_ads/client.py`, `src/google_ads/errors.py`; Test `tests/unit/test_google_ads_errors.py` e o teste de `_error_envelope`.

**Interfaces:** Produces: `class NoOAuthConnectionError(GoogleAdsFriendlyError)`. `to_friendly(RefreshError)` devolve `GoogleAdsFriendlyError` com o texto abaixo. Conferir o construtor de `GoogleAdsFriendlyError` e os `except NoOAuthConnectionError` existentes antes de mudar a base.

Texto fixo do `RefreshError`: `"A conexão Google Ads deste gestor expirou ou foi revogada. Reconecte em /oauth/google/start."`

- [ ] Teste `test_sem_oauth_chega_ao_gestor`: `_error_envelope("x", NoOAuthConnectionError(...))` traz `/oauth/google/start`.
- [ ] Teste `test_refresh_revogado_chega_ao_gestor`: `build_client_for_manager` com `build_client` levantando `google.auth.exceptions.RefreshError("invalid_grant")` → `GoogleAdsFriendlyError` com o texto fixo.
- [ ] Rodar e ver falhar.
- [ ] Mudar a base da exceção; em `build_client_for_manager`, `except RefreshError as e: raise to_friendly(e) from e`, mesmo molde do F70.
- [ ] Rodar; rodar `tests/unit -k "oauth or client or errors"`.
- [ ] Commit `fix(google_ads): OAuth revogado orienta a reconectar`.

Fora: o token de confirmação do `apply_change` já consumido nesse caminho. O gestor refaz o preview.

### Task 3: Login OAuth preso ao navegador

Fato: o `state` (`src/auth/oauth.py:157,227`) é HMAC sem vínculo com o navegador, e `verified_email`/`hd` são ignorados (`:271-273`). `/docs` e `/openapi.json` ficam públicos (`src/app.py:53`).

**Files:** Modify `src/auth/oauth.py`, `src/app.py`; Test `tests/unit/test_oauth*.py`.

**Interfaces:** Produces: cookie `v4_oauth_nonce` (HttpOnly, Secure, SameSite=Lax, 10 min) gravado no `/start`, com o nonce embutido no `state` assinado e comparado por `hmac.compare_digest` no callback.

- [ ] Testes: callback sem cookie → recusado; nonce divergente → recusado; nonce certo → segue; `verified_email=False` → recusado; `GET /docs` → 404.
- [ ] Rodar e ver falhar.
- [ ] Implementar. O fluxo de invite passa pelo mesmo `/start`: testar que continua funcionando. Conferir que `meta_oauth.py` não depende desse `state`.
- [ ] Rodar `tests/unit -k oauth`.
- [ ] Commit `fix(auth): state do OAuth preso ao navegador e e-mail verificado`.

**Fim do bloco:** full sweep, push, PR, auto-merge, vigia.

---

## Bloco 2 — `fix/restore-e-job-bloqueado`

### Task 4: Restore executável, com sequence

Fato: o runbook manda `copy_to_table` sem `setval`, e a sonda em Postgres 16 deu `UniqueViolationError (id)=(1)` no INSERT seguinte. O dump inclui `_migrations`, que conflita com o schema migrado. Só `audit_log` tem SERIAL. O `command_timeout=30` de `connection.py:171` vale para o COPY inteiro em `backup.py:89`.

**Files:** Create `src/jobs/restore.py`; Modify `docs/operacao/backup-restore-runbook.md`, `src/jobs/backup.py`; Test `tests/integration/test_backup_restore.py`.

**Interfaces:** Produces: `async def restaurar_tabelas(conn, pasta: Path) -> dict[str, int]`, que restaura na ordem de FK do runbook, pula `_migrations`, roda em uma transação e faz `SELECT setval(pg_get_serial_sequence('audit_log','id'), GREATEST((SELECT max(id) FROM audit_log), 1), (SELECT max(id) IS NOT NULL FROM audit_log))`. Entrada de linha de comando: `python -m src.jobs.restore <pasta>`.

- [ ] Teste de integração `test_backup_e_restore_ida_e_volta`: popula todas as tabelas com FK, faz dump por `_dump_table_to_blob`, restaura em banco migrado limpo, compara contagens, e um `audit_log.record` depois funciona.
- [ ] Teste `test_restore_com_audit_vazio` (Review Focus 5).
- [ ] Rodar e ver falhar.
- [ ] Implementar `restaurar_tabelas`. Em `backup.py:89`, passar `timeout=None` ao `copy_from_query`, com teste de que o argumento vai.
- [ ] Reescrever os passos 3 e o teste de restore do runbook para usar o módulo.
- [ ] Rodar `pytest -m integration tests/integration/test_backup_restore.py`.
- [ ] Commit `fix(jobs): restore executavel que recoloca a sequence do audit_log`.

### Task 5: Job bloqueado sai com falha

Fato: `account_resync.py:413` e `meta_resync.py:256` devolvem 0 mesmo com `blocked_reason`, e a policy de alerta só vê execução falhada. O crash do piggyback Meta também devolve 0.

**Files:** Modify `src/jobs/account_resync.py`, `src/jobs/meta_resync.py`; Test `tests/unit/test_account_resync.py`, `tests/unit/test_meta_resync_audit.py`, `tests/unit/test_resync_empty_inventory_guard.py`.

**Interfaces:** Produces: exit `1` quando houve `blocked_reason` em qualquer reconciliação ou crash do piggyback, depois de terminar upsert, audit e purge. Sem bloqueio, exit `0`.

- [ ] Testes: bloqueio Google → 1; bloqueio Meta → 1; sem bloqueio → 0; crash do piggyback → 1; segunda execução no mesmo dia não aplica nada duplicado (Review Focus 4).
- [ ] Rodar e ver falhar.
- [ ] Implementar. Ler `max-retries` do job em `deploy.yml`/`infra-setup.md` e registrar no commit se o retry repete o bloqueio.
- [ ] Atualizar `docs/operacao/infra-setup.md`: job bloqueado alerta.
- [ ] Commit `fix(jobs): reconciliacao bloqueada termina com falha e alerta`.

**Fim do bloco:** full sweep, push, PR, auto-merge, vigia.

---

## Bloco 3 — `fix/governanca-de-mutacao`

### Task 6: Micros arredondados num helper único

Fato: `int(2.01*1_000_000) == 2009999`, em 6 pontos: `update_keyword_bid.py:116`, `update_ad_group_bid.py:107`, `update_campaign_budget.py:122`, `update_campaign_bidding.py:69`, `mutates/campaigns.py:102`, `mutates/assets.py:99`.

**Files:** Modify os 6 acima e `src/google_ads/queries/_common.py`; Test `tests/unit/test_moeda.py` (novo) e o guard estrutural.

**Interfaces:** Produces: `def brl_para_micros(valor: float) -> int` em `_common.py`, ao lado de `micros_to_currency`, com `round(Decimal(str(valor)) * 1_000_000)`.

- [ ] Testes: `brl_para_micros(2.01) == 2_010_000`, `(4.10) == 4_100_000`, `(0.1) == 100_000`, e varredura de 0,01 a 1.000,00 com passo de centavo: todo resultado é múltiplo de 10.000.
- [ ] Guard: nenhum `int(... * 1_000_000)` em `src/`.
- [ ] Rodar e ver falhar.
- [ ] Implementar e trocar os 6 pontos; `_brl_to_micros` de `campaigns.py` passa a delegar ou sai.
- [ ] Rodar e sabotar o guard; restaurar.
- [ ] Commit `fix(google_ads): micros arredondados, preview igual ao payload`.

### Task 7: `had_effect` nas mutações MCP

Fato: 229 de 229 mutações MCP em 90 dias estão com `had_effect` nulo. `run_mutation` já calcula `changed_count` (`mutations.py:369`), e `audit_log.record` já aceita o campo.

**Files:** Modify `src/google_ads/mutations.py:~440`; Test `tests/unit/test_mutations*.py`.

**Interfaces:** Consumes: `audit_log.record(..., had_effect: bool | None)`. Regra: `None` se `changed_count is None`, senão `changed_count > 0`. Nas outras gravações (`:405`, `:428`, `:566`) só passar quando houver medida.

- [ ] Testes: 3 mudaram → `True`; 0 mudaram → `False`; não medido → `None`.
- [ ] Rodar, implementar, rodar.
- [ ] Commit `fix(google_ads): audit grava se a mutacao teve efeito`.

### Task 8: `primary_for_goal` exige confirmação e `dismiss_recommendation` checa a conta

**Files:** Modify `src/governance/blast_radius.py:209-210`, `src/mcp/tools/update_conversion_action.py`, `src/mcp/tools/dismiss_recommendation.py`; Test `tests/unit/test_blast_radius.py`, teste do dismiss.

- [ ] Trocar `test_set_primary_for_goal_true_is_auto_for_single` por `..._exige_confirmacao`, com o valor de risco que desligar já usa. Atualizar a description (hoje fala em "rename").
- [ ] Teste `test_dismiss_recusa_recomendacao_de_outra_conta`: `customer_id=A` com `customers/B/recommendations/x` → `error_envelope`, sem chamar `run_recommendation_action`. Teste do caminho certo.
- [ ] Rodar e ver falhar.
- [ ] Implementar. Mensagem igual à de `remove_asset_link`: `resource_name pertence a outra conta (esperado prefixo customers/{customer_id}/, recebido '...')`.
- [ ] Rodar; conferir que o `apply_change` trata o ramo novo de confirmação de `update_conversion_action`.
- [ ] Commit `fix(governance): primary exige confirmacao; dismiss presa a conta`.

### Task 9: Telefone com DDI sem `+`

Fato: `customer_match.py:59-61` transforma `5583999998888` em `+555583999998888`. No `remove` (opt-out LGPD), a pessoa segue na lista.

**Files:** Modify `src/google_ads/customer_match.py:59-61`; Test `tests/unit/test_customer_match*.py`.

Regra: só dígitos com 12 ou 13 caracteres começando em `55` → `+` + dígitos. Com 10 ou 11 dígitos → `+55` + dígitos, como hoje, inclusive DDD 55.

- [ ] Testes: `5583999998888` → `+5583999998888`; `83999998888` → `+5583999998888`; `55999998888` (DDD 55, 11 dígitos) → `+5555999998888`; `+5583999998888` inalterado.
- [ ] Rodar, implementar, rodar.
- [ ] Commit `fix(google_ads): telefone com DDI sem mais gera o hash certo`.

### Task 10: Upload de conversões conta no audit

Fato: `conversions.py:235-247` grava `status=success` e `target_count=100` com 100 recusas.

**Files:** Modify `src/google_ads/conversions.py`; Test `tests/unit/test_conversions*.py`.

**Interfaces:** `params_summary` ganha `applied_count` e `failed_count`; `had_effect = applied_count > 0`; com `applied_count == 0` e `target_count > 0`, o audit usa `status="error"` por uma variável própria (`status_audit`). O `status` que decide o envelope **não muda**, para a resposta seguir com as falhas por linha.

- [ ] Testes: 100 de 100 recusadas → audit `error`, resposta com `partial_failures`; 60 de 100 → audit `success` com as contagens; 100 aceitas → `had_effect=True`.
- [ ] Rodar, implementar, rodar.
- [ ] Commit `fix(google_ads): audit do upload de conversoes conta as recusas`.

**Fim do bloco:** full sweep, push, PR, auto-merge, vigia.

---

## Bloco 4 — `fix/meta-v25`

### Task 11: Graph v25.0 em ponto único

Fato: a Marketing API v22 expirou em 19/02/2026, e a Meta devolve `auto-upgraded to v25.0`. Nenhuma mudança de Insights nos changelogs lidos.

**Files:** Modify `src/meta_ads/client.py:24`, `src/auth/meta_oauth.py:45-46`, `scripts/probe_meta_auth_header.py:36`, `scripts/probe_meta_metricas.py:35`, `scripts/probe_meta_sort.py:35`, 9 testes com URL literal, `tests/unit/test_meta_client.py:30`.

**Interfaces:** Produces: `META_GRAPH_API_VERSION = "v25.0"` é a única fonte; `meta_oauth.py` importa a constante. Guard: `v22.0` não aparece em `src/` nem `scripts/`.

- [ ] Guard, rodar e ver falhar.
- [ ] Trocar. `test_structural_guards.py` usa v22 só como amostra de texto: deixar.
- [ ] Gate.
- [ ] Commit `fix(meta_ads): Graph em v25.0 numa constante so`.

### Task 12: Alarme de versão, contador em erro e `best_effort`

Fato: nada lê `x-ad-api-version-warning`. `_paginar_graph` levanta exceção e perde os headers, então chamada throttled não conta. O audit Meta (`reports.py:278,329`) não usa `best_effort`: audit falho após leitura boa vira erro cru, e no caminho de erro substitui a mensagem amigável.

**Files:** Modify `src/meta_ads/reports.py`, `src/meta_ads/graph.py`, `docs/convencoes/nucleo.md`; Test `tests/unit/test_meta_reports*.py`.

**Interfaces:** Produces:
- `def avisar_versao_meta(headers: httpx.Headers) -> None` em `graph.py`: com o header presente, `log.error("meta_api_version_warning", aviso=...)` uma vez por texto no processo. Chamada a cada resposta nos dois laços.
- `_paginar_graph` recebe `capturados: list[httpx.Headers]` e acrescenta cada resposta antes de levantar.
- `_contabilizar_uso(headers, ...)` extraído do bloco das linhas 314-328 e chamado nos dois caminhos.

- [ ] Testes: header presente → um log, mesmo com 3 respostas; resposta 429 com BUC → `record_actual_meta` chamado; audit quebrando na leitura boa → dados voltam; audit quebrando no erro → mensagem amigável preservada.
- [ ] Rodar e ver falhar.
- [ ] Implementar, com `best_effort` igual a `src/google_ads/reports.py:162`.
- [ ] Rodar; ajustar a frase do `nucleo.md` sobre `meta_buc_nao_lido`.
- [ ] Commit `fix(meta_ads): alarme de versao e contador tambem no erro`.

### Task 13: Mensagens Meta

**Files:** Modify `src/meta_ads/errors.py:14,130,140`, `src/mcp/tools/meta_get_account_overview.py:44`; Test `tests/unit/test_meta_errors.py`.

- [ ] Testes: code 80000 → "Limite Meta atingido"; code 190 → texto de rotação do token do system user, sem "reconecte".
- [ ] Rodar, adicionar 80000 a `CODIGOS_DE_THROTTLE`, ajustar os textos e a description ("Requer conexão Meta ativa" é falso no Modelo B).
- [ ] Commit `fix(meta_ads): limite 80000 e mensagens do Modelo B`.

**Fim do bloco:** gate, push, PR, auto-merge, vigia. Smoke em sessão nova: 1 leitura Meta sem aviso no log.

---

## Bloco 5 — `chore/deps-e-deploy`

### Task 14: Remover `facebook-business`

Fato: `src/` não importa o SDK desde o F190, e ele puxa `aiohttp`, com 9 dos 13 achados do `pip-audit`.

**Files:** Modify `pyproject.toml:16,19-23,74`, `requirements.txt`, `src/meta_ads/client.py:3-6`.

- [ ] Remover a dependência, o piso do `aiohttp` e o override do mypy.
- [ ] Regerar o lock com o comando do cabeçalho de `requirements.txt`, subindo `certifi` para `>=2026.10.18`.
- [ ] `pip-audit -r requirements.txt --no-deps --disable-pip`: anotar o que sobrou no corpo do PR.
- [ ] Gate e `check_lockfile_fechado`.
- [ ] Commit `chore: remove facebook-business morto e sobe certifi`.

### Task 15: Actions por SHA

**Files:** Modify `.github/workflows/*.yml`; Create `tests/unit/test_actions_pinadas.py`.

- [ ] Guard: toda `uses:` externa casa `@[0-9a-f]{40}`, com a tag em comentário.
- [ ] Ver falhar; resolver cada SHA com `gh api repos/<dono>/<repo>/git/ref/tags/<tag>` (tag anotada: seguir até o commit).
- [ ] Rodar. Dependabot `github-actions` segue atualizando.
- [ ] Commit `chore(ci): actions presas por SHA`.

### Task 16: Deploy e ordem dos jobs

Fatos: os jobs recebem a imagem antes do smoke (`deploy.yml:154-183`), então o job das 06:00 pode rodar código rejeitado. Push só de docs cancela o teste do push anterior (`ci.yml:21`), e o deploy dele não acontece. `|| true` com `2>/dev/null` (`deploy.yml:197`) pode apagar a revisão do rollback.

**Files:** Modify `.github/workflows/deploy.yml`, `.github/workflows/ci.yml`, `tests/unit/test_deploy_job_image_order.py`, `tests/unit/test_ci_deploy_gate.py`.

**Interfaces:** Produces: `cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}`. Os passos de imagem dos jobs `resync` e `backup` vão para depois do smoke verde; `migrate` continua antes.

- [ ] Testes: job só depois do smoke; `cancel-in-progress` falso em `main`; captura de revisão sem `|| true`.
- [ ] Ver falhar.
- [ ] Implementar. Captura: serviço inexistente continua vazio, e qualquer outro erro falha o passo.
- [ ] Rodar. Corrigir o comentário de `ci.yml` que chama o pulo de benigno.
- [ ] Commit `fix(ci): jobs so recebem imagem depois do smoke`.

### Task 17: Guard de migration destrutiva

**Files:** Create `tests/unit/test_migrations_nao_destrutivas.py`.

- [ ] Guard: migrations com número acima de 011 não contêm `DROP` nem `RENAME`, salvo a linha `-- destrutiva-aprovada:` com o motivo.
- [ ] Sabotar com arquivo temporário e ver falhar; apagar.
- [ ] Commit `test(db): guard contra migration destrutiva`.

**Fim do bloco:** full sweep, autorização nominal do `deploy.yml`, push, PR, auto-merge, vigia. Conferir revisão nova servindo e os jobs na imagem nova.

---

## Bloco 6 — `fix/painel-e-contratos`

### Task 18: Números do painel

**Files:** Modify `src/web/routes/admin_overview.py:50-60,68-73`, `src/web/routes/sessions.py:173-186,208`, `src/web/templates/admin/managers.html:54,62`; Tests `tests/integration/test_admin*`.

- [ ] Testes: uma mutação conta 1 em "Quota MCP hoje"; gestor com `is_active=False` aparece inativo e sai de "Gestores ativos"; série de 30 dias com zeros nos dias vazios; um único dia desenha ou mostra "Sem dados"; dia em `America/Sao_Paulo`.
- [ ] Ver falhar.
- [ ] Implementar: `developer_token_id NOT LIKE 'mgr:%'`; badge por `m.is_deactivated` (o F84 proíbe sincronizar as colunas); contagem por `status='active' AND is_active`; dia com `AT TIME ZONE 'America/Sao_Paulo'`, em intervalo sargável sobre `occurred_at`, como no gêmeo do dashboard.
- [ ] Commit `fix(web): quota, status e dia do painel batem com o dado`.

### Task 19: Confirmação em ações de admin

**Files:** Modify `src/web/templates/_components.html:180-183`, `src/web/templates/admin/managers.html:71-77`; Test de renderização.

- [ ] Teste: "Desativar" e "Promover a admin" renderizam com `data-v4-action="confirm"` e o texto da ação.
- [ ] Ver falhar; acrescentar `confirm` opcional no item do `dropdown`, seguindo o padrão das outras telas.
- [ ] Commit `fix(web): desativar e promover pedem confirmacao`.

### Task 20: Matriz de acesso idempotente

Fato: `admin_access.py:123,513` decide pelo estado do banco, então aba velha inverte o acesso, e o toast de `v4-panel.js:313` lê `el.checked`.

**Files:** Modify `src/web/routes/admin_access.py`, o template da matriz, `src/web/static/v4-panel.js`; Test `tests/integration/test_admin_access*`.

**Interfaces:** Produces: o checkbox envia `desejado=grant|revoke` por `hx-vals`, calculado na renderização. A rota aplica esse estado. Pedido igual ao estado atual não muda nada e não grava audit. O toast sai de `HX-Trigger` da resposta.

- [ ] Testes nas duas rotas (Google e Meta): `grant` em quem já tem mantém; `revoke` em quem não tem mantém; sem `desejado` → 422; toast diz o que aconteceu.
- [ ] Ver falhar; implementar; rodar.
- [ ] Commit `fix(web): matriz de acesso aplica o estado pedido`.

### Task 21: Textos, hora, feedback e contraste

**Files:** Modify `templates/admin/index.html:97`, `admin/access_meta.html:22,56`, `admin/accounts.html:113`, `sessions/detail.html:43`, `admin/audit.html:55-58,106`, `admin/accounts_meta.html`, `admin/invites.html`, `src/web/routes/admin_overview.py:129-130,154-155`, `src/web/routes/admin_access.py:243-251`, filtro Jinja; Test de renderização.

- [ ] Testes: filtro `|hora_brasilia` converte UTC para `America/Sao_Paulo`; `meta_connected=1` mostra aviso; filtro "Negado" existe e `denied` sai traduzido; numerador Meta filtra conta ativa como o Google.
- [ ] Ver falhar.
- [ ] Implementar: textos falsos corrigidos; `text-v4-green` em texto pequeno vira `--v4-green-text`; `strftime` das telas admin passa pelo filtro.
- [ ] `python scripts/build_tailwind.py` se alguma classe nova entrar.
- [ ] Commit `fix(web): textos, hora de Brasilia, feedback e contraste`.

### Task 22: Contratos das tools

**Files:** Modify `audit_orphan_smart_actions.py:24`, `audit_goal_attribution.py:31`, `validate_gaql.py:80-82`, `update_conversion_action.py`, `remove_audience.py`, `get_performance_breakdown.py`; Test `tests/unit/test_contratos_enum.py`.

- [ ] Guard: o enum dos dois audits contém todas as categorias de `create_conversion_action` (`PHONE_CALL_LEAD`, `ADD_TO_CART`, `BEGIN_CHECKOUT`, `SUBSCRIBE_PAID`).
- [ ] Ver falhar; compartilhar uma constante única.
- [ ] Textos: `validate_gaql` "consome 1 operação da quota"; token "8 caracteres"; `raw_grid` "blocos nomeados"; `remove_audience` avisa que audiência de campanha não vem de `get_audience_performance`.
- [ ] Commit `fix(mcp): enums e descriptions batem com o handler`.

### Task 23: Plugin, docs e findings

O plugin não tem fonte no disco, só a cópia instalada: as correções vão em arquivo para o Wellington aplicar.

**Files:** Create `docs/operacao/plugin-correcoes-2026-10-30.md`; Modify `CLAUDE.md`, `README.md:11`, `docs/operacao/estado-atual.md`, `docs/operacao/infra-setup.md:150-171`; Create `docs/operacao/session-2026-10-31-handoff.md`.

- [ ] Plugin: `age_view` → `age_range_view`; `date_range` objeto → `start_date`+`end_date`; retirar "não há tool de change_event"; chaves reais do pacing; `dismiss_recommendation` e status como são hoje; `validate_gaql` consome quota; regra de `null` em `v4-brand:43`.
- [ ] `CLAUDE.md`: API v25, Meta v25. `README`: 72 tools. `estado-atual`: uso medido em 30/10, sai a pendência do `null`, entra Dependabot.
- [ ] Handoff com a lista do que entrou e os textos prontos para `/findings-add`.
- [ ] Commit `docs(operacao): fecho da varredura de 30/10`.

**Fim do bloco:** full sweep, push, PR, auto-merge, vigia.

---

## Fora deste plano

Ficam registrados no handoff, com o motivo:

- As 45 recusas do Pedro: decisão no painel.
- Alertas do Dependabot: ajuste do repositório, feito pelo Wellington.
- Rotação da `aes-master-key` e `associated_data`: precisa de recifrar tokens, é frente própria.
- CSP (`base-uri`, `object-src`, `form-action`) e HTMX local: frente do painel, com teste em navegador.
- `run_gaql` lendo no stream: preventivo, sem pressão medida (pico de 50% de memória). Mexe no executor mais usado, então merece desenho próprio.
- Buckets, descriptions e Fase 2B: dependem da remedição de uso.
- `mcp` 2.x e `google-ads` novos: frente própria, com smoke de handshake.
- Hipóteses não medidas: atribuição mista na Meta, conta `CANCELED` no inventário, 2635 como subcode, `objectCreator`.
- `add_keywords` sem teto de lance: baixo, pede decisão de produto.
- Reativar gestor revive Bearer, `/logout` no servidor, invite sem conferir e-mail: baixos, próxima rodada de auth.
