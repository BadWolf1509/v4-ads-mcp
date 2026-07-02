# Sessão 2026-07-02 — Handoff (investigação → 6 ondas shipadas)

> Investigação multi-agente (código/docs/testes/segurança) + probe do `audit_log` de produção → **6 ondas executadas e mergeadas na main** (`8520aea..0ef5bcc`, 15 commits, CI+Deploy verdes). O **deploy agora é gated pelo CI**. Resolveu 3 problemas ativos pós-migração + 2 falhas de governança + buracos de pipeline + dívida da Onda 4. Findings **F68-F72** catalogados; **F64/F65/F66 resolvidos**.

## TL;DR

| # | Entrega | Findings | Commits |
|---|---|---|---|
| **A** | URL nova anunciada em `/help`/`/sessions`/admin (drift-proof) + erro amigável de decrypt no cutover | F68, F70 | `becea99`, `8520aea` |
| **B** | F66 resolvido (jobs CNB) + scheduler resync recriado + resync Meta deletion-detection | F66, F69, F65 | gcloud + `ab14268`, `0356a5d` |
| **C** | Customer Match audita+rate-limit + gate Meta obrigatório + guards estruturais + `create_rsa` policy topic | F71, F72 | `4da91ff`, `25fd1cc`, `b1cb1e7`, `9896621` |
| **D** | Deploy gated pelo CI (reusable workflow) + dependabot + polish | — | `b6fac2c`, `71dfe5e` |
| **E** | 41 testes dos módulos-núcleo + refactors Onda 4 (dedup + split `run_mutation`) | — | `0099a97`, `5b5955b`, `2d83a79`, `8a7f194` |
| **F** | Steering Fase 2B (nota deprecação nos 8 reports) + findings + doc-drift | F68-F72 | `45f0a25`, `0ef5bcc` |

Produção: `/health?deep=1` db=ok. Scheduler `v4-ads-mcp-resync-daily` ENABLED. 64 tools.

## Onda A — destravar cutover

- **F68 (URL antiga anunciada pelo serviço novo):** `src/config.py` tinha `public_base_url` = URL do projeto antigo (`…jf26mmrgqa-rj`) e os 4 snippets de `/help` eram hardcoded. Gestor que relogava no painel novo copiava o endpoint a decomissionar (Pedro caiu nisso em 07-02). Fix: default = URL nova; `/help` injeta `mcp_url` via contexto (`routes.py:help_page` — drift-proof, não mais hardcode); `PUBLIC_BASE_URL` no `--set-env-vars` do `deploy.yml`; README/admin.py. **Verificado em prod:** `/help` mostra URL nova 4×, antiga 0×. OAuth redirect_uri NÃO deriva de `public_base_url` (usa `request.url_for`) → mudança segura.
- **F70 (decrypt-failure críptico):** no cutover, o refresh token do gestor foi cifrado com a `aes-master-key` ANTIGA; o serviço novo tem a chave regenerada → `InvalidCiphertextError`. Mas `build_client_for_manager` é chamado FORA do wrap de `to_friendly` dos executores, então o erro chegava cru no `_error_envelope` e virava "Erro interno" genérico (Pedro ficou ~9min preso, 13:33-13:42). Fix: `build_client_for_manager` converte na ORIGEM via `to_friendly` (cobre TODOS os executores); `to_friendly` idempotente (não re-embrulha `GoogleAdsFriendlyError`). Mensagem: "reconecte sua conta Google no painel" + URL.

## Onda B — jobs (F66) + scheduler (F69) + resync deletion-detection (F65)

**F66 — causa-raiz DUPLA (a lição não-óbvia):**
1. A imagem CNB expõe cada process do Procfile via symlink `/cnb/process/<type>` (CNB Platform ≥0.4, confirmado lendo o config OCI do registry). `--command=/cnb/process/migrate --args=""` invoca o process certo.
2. O estado sujo do job resync era `command: C:/Program Files/Git/cnb/lifecycle/launcher` — o **Git Bash no Windows manglou `/cnb/...` pra caminho Windows** numa tentativa manual anterior (por isso o launcher "falhava"). **Comandos gcloud one-time com arg iniciando em `/` DEVEM rodar em PowerShell** (o `deploy.yml` no ubuntu é imune).

Comandos aplicados (PowerShell, `$P='v4-ads-mcp'; $R='southamerica-east1'`):
```powershell
gcloud run jobs update v4-ads-mcp-migrate --project=$P --region=$R --command="/cnb/process/migrate" --args="" --max-retries=1
gcloud run jobs update v4-ads-mcp-resync  --project=$P --region=$R --command="/cnb/process/resync"  --args=""
```
Validados executando: migrate → `migrations_no_pending` (schema já bate, exit 0); resync → `OK: upserted 25 accounts` (Google) + `OK: Meta upserted 19 accounts` (exit 0). `deploy.yml` agora repassa command/args nos 2 update-steps (self-healing contra drift) + **step de migrations reativado** (fim do skip silencioso) + **fix do rollback** (`id: deploy` + `if: failure() && steps.deploy.outcome != 'skipped'` — sem isso, falha ANTES do deploy rebaixaria produção).

**F69 — scheduler ausente no projeto novo:** `gcloud scheduler jobs list` = 0 items; o resync diário rodava pelo scheduler do projeto ANTIGO (DB compartilhada). Recriado com SA dedicada least-privilege:
```powershell
gcloud iam service-accounts create v4-ads-mcp-scheduler --project=$P --display-name="Cloud Scheduler invoker (resync diario)"
gcloud run jobs add-iam-policy-binding v4-ads-mcp-resync --project=$P --region=$R --member="serviceAccount:v4-ads-mcp-scheduler@$P.iam.gserviceaccount.com" --role="roles/run.invoker"
gcloud scheduler jobs create http v4-ads-mcp-resync-daily --project=$P --location=$R --schedule="0 6 * * *" --time-zone="America/Sao_Paulo" --uri="https://$R-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$P/jobs/v4-ads-mcp-resync:run" --http-method=POST --oauth-service-account-email="v4-ads-mcp-scheduler@$P.iam.gserviceaccount.com" --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform"
```
Validado via `gcloud scheduler jobs run …` → HTTP 200 → execução Completed.

**F65 (Onda 5) — deletion-detection Meta:** `resync_meta` agora chama `mark_inactive_except` **agrupado por `business_id`** (o SU vê múltiplos BMs; sem agrupar, o keep-list de um BM marcaria contas de outro como churned). Contas sem `business_id` (pessoais) são puladas.

## Onda C — governança

- **F71 — Customer Match sem audit/rate-limit:** `run_offline_user_data_job` (mutate de PII — sobe/remove membros hash) não gravava `audit_log` nem contava quota. Espelha `run_conversion_upload` (`before_call`/`record_actual`/`audit_log.record` em sucesso E erro; `params_summary` só metadados, nunca os hashes). No erro grava audit e levanta o friendly (apply_change espera dict de sucesso).
- **F72 — gate Meta fail-open:** `run_meta_graph_get` lia `ad_account_id = params.get(...)` + `if ad_account_id:` — um tool futuro (M.5) que esquecesse o param rodaria SEM gate. Agora `ad_account_id` é kwarg **OBRIGATÓRIO** e o gate roda incondicional. Os 6 call-sites já tinham o valor no escopo.
- **Guards estruturais** (`tests/unit/test_structural_guards.py`): F57 (call-site de `build_client_for_manager` sem `ensure_account_access` — **verificado que dispara quando sabotado**), F57-Meta (`build_meta_api` fora de reports.py), F58 (`.cursor()` sem `conn.transaction()`). Automatizam o "grep manual" que o CLAUDE.md prescrevia.
- **`create_rsa` policy topic (C4):** `to_friendly` agora extrai `policy_finding_details.policy_topic_entries` e nomeia QUAL política reprovou (o gestor tentava às cegas — 9× no dogfood 07-02). Best-effort via getattr, degrada pro sdk_msg.

## Onda D — deploy gated pelo CI

Antes CI e Deploy disparavam em paralelo no push → suíte quebrada deployava assim mesmo (rota de F58/F59 pra prod). Agora:
- `deploy.yml` → `on: {workflow_call, workflow_dispatch}` (dispatch = break-glass manual). Concurrency `deploy-prod` (cancel:false) + `timeout-minutes: 30` no job.
- `ci.yml` → job `deploy` com `needs: test` + `if: push && main` + `uses: ./.github/workflows/deploy.yml` + `secrets: inherit` + `permissions: id-token:write` (WIF). Concurrency do CI movida pro job `test` (cancel:true) — senão mataria o deploy no meio.
- **Recomendação `needs` > `workflow_run`:** correto por construção (mesmo SHA, sem plumbing de head_sha; evita corrida de push e re-run de CI antigo deployando commit velho).
- Polish: removido service postgres morto do ci.yml, timeouts, `.github/dependabot.yml` (github-actions + pip weekly, ignore major google-ads/facebook-business), removido `pytest-cov` não usado.
- **Validado:** test → deploy no MESMO run, ambos success (2 pushes já passaram pelo mecanismo novo).

## Onda E — testes do núcleo + refactors Onda 4

- **Testes** (5 arquivos, 41 testes, zero mudança em prod): `test_recommendations_builder.py` (fecha escape-hatch F16/F42/F44 de `mutates/recommendations.py`), `test_query_builders_gaql.py` (asserções de TEXTO GAQL em overview/client_report/recommendations — antes um typo GAQL passava), `test_google_accounts.py`, `test_account_resync.py`, `test_request_id.py`.
- **Refactors Onda 4:** `meta_error_message` em `_meta_common.py` (dedup dos 5 tools Meta); `classify_partial` em `_common.py` (dedup de 3 tools; remove_audience mantém o seu — pattern diferente); `_parse_partial_failures` + `_extract_resource_names` extraídos de `run_mutation` (~235→~150 linhas). Comportamento idêntico.

## Onda F — steering Fase 2B + docs

- **NÃO tombstonei a Fase 2B.** O `audit_log` provou que os 8 reports antigos seguem em uso ATIVO (`get_campaign_performance` 27× desde 06-20, último 07-02) e `get_performance_breakdown` parou em 06-24 → o gate falharia por construção. Ação = **steering:** cada uma das 8 descriptions abre com "Prefira get_performance_breakdown(level=X) — este report sera arquivado (Fase 2B)". A janela do soak reinicia quando os gestores migrarem pro tool novo.
- Findings F68-F72 + F64/F65/F66 resolvidos no catálogo; doc-drift reconciliado (CLAUDE.md, README, sprint-history, este handoff).

## Dado colhido do `audit_log` de prod

- **Checkpoint Meta (07-10):** só **43 chamadas** Meta na janela (meta era ~500/15d), **2,3% de erro** — longe de justificar re-submeter Full Access por volume. M.5 alimentaria, OU estender a janela (decisão do Wellington).
- **Erros de 07-02** (10 total, nenhum bug do MCP): 6× `Ciphertext authentication failed` (cutover do Pedro pré-reconexão às 13:42 — já resolvido); 3× `create_rsa PROHIBITED` (Google reprovou os anúncios de Goiânia por política — ação do Pedro no copy); 1× `update_ad_group_status` em ad_group REMOVED (ruído de limpeza, você).

## Pendências (AÇÕES HUMANAS — fora do que o Claude automatiza)

1. **Cutover restante:** **lucassoares** (token com chave antiga → vai ver a mensagem amigável F70 agora) + **anderson** (`invited` → 1º login). Runbook: no `~/.claude.json` deles trocar URL v4-ads → `…299432068772.southamerica-east1.run.app/mcp` (Bearer continua valendo) + relogar no painel novo (`/help` já mostra a URL certa) + restart.
2. **Decomissionar `v4-ads-mcp-prod`** — só depois dos cutovers (o scheduler antigo ainda cobre o resync até lá, agora redundante).
3. **Revisar as 4 skills `v4-trafego-google-ads`** no claude.ai/Cowork pra apontarem `get_performance_breakdown` (vivem fora do repo — não são plugin local).
4. **F67 custom domain** `mcpv4.fluxocerto.dev.br` via Load Balancer (southamerica-east1 não permite domain mapping direto).
5. **Atribuir o SU** às contas Meta faltantes no Business Manager (ML Antiguidades, MDO Pinda, `act_34358720650393626`).
6. **Revogar** o token BTW temporário do Wellington · **decisão do checkpoint Meta** (43 calls) · **decisão do steering 2B** (janela de soak).

## Próximo sprint candidato

**M.5** (Meta `meta_get_audience_performance` + `meta_get_top_creatives`) — alimentaria o volume do checkpoint Meta e é o próximo do roadmap Meta. Fase 2B fica pendente do soak real (gestores migrarem pro tool novo). Fases 3/4 do refactor (archive de zombies + roadmap Meta demand-pull) viram edição de doc pós-sinal de uso.
