# Estado atual — V4 Ads MCP

> **Volátil por natureza** — o `CLAUDE.md` mantém um resumo de poucas linhas e aponta para cá.
> **Ao terminar uma sessão, atualize ESTE arquivo** e mantenha-o curto (teto prático: ~10 KB; em 20/09
> chegou a 91 KB). **Trabalho que fechou sai daqui:** o defeito vai para o catálogo, a narrativa para o
> handoff ou o [`_archive/`](../_archive/estado-atual-2026-10-30-a-11-04.md), e aqui fica uma linha.

> **Última sessão:** [`session-2026-11-14-handoff.md`](session-2026-11-14-handoff.md) — 14/11: backlog
> de tráfego da MO-JP, **7 itens em produção** (#249–#255), smoke 7/7, **contrato `conferencia`** no
> `apply_change`. Antes: [`session-2026-11-10-handoff.md`](session-2026-11-10-handoff.md) (varredura de
> refatoração de 10/11, #228–#247).

## Direção e restrições

- **Meta híbrida (02/11):** o nosso MCP mantém Google, leitura Meta e governança; escrita, públicos e
  pixel ficam com o MCP oficial da Meta (atribuição do usuário no BM). Onda 3 congelada; **Onda 2
  pausada** ([plano](../superpowers/plans/2026-11-02-meta-onda-2-auditorias.md)). Escrita do MCP oficial
  liberada por padrão nas contas: bloqueio pendente de decisão.
- **Teste de 30 dias, até 02/12:** 3+ gestores ativos por semana e escritas Google recorrentes →
  continua; uso alto só em leitura → reduz ao mínimo; menos de 2 gestores ativos → encerra a evolução e
  migra para os oficiais. Não medido na decisão: uso depois de 30/10, custo de infra, satisfação.
- **Google Ads (02/11):** MCC `6436352492` da V4 Lima Soares & Co; nível **Básico** (15.000 operações/dia);
  developer token aposentado em 09/09 (`google-ads` 33.0.0). A política de 31/08 proíbe MCP que só
  reexpõe o Google Ads a empresas independentes — uso interno fica fora, pela nossa leitura; abrir outra
  unidade ou cliente pede revisão antes.
- **Onda 1 Meta** (8 tools de leitura, #201/#203) em produção, conferida no Gerenciador em 02/11. Não
  medido: paginação de `meta_get_entities` além de uma página, render da prévia, objetivos além de REACH.
  Detalhe no [arquivo](../_archive/estado-atual-2026-10-30-a-11-04.md).

## Produção — medido em 2026-11-11 e 14/11

| | |
|---|---|
| Revisão servindo | **não medida em 14/11** (`gcloud` sem credencial). A última medida é **`v4-ads-mcp-00206-24r`** (#246, 11/11); depois dela entraram 8 deploys de 14/11 (#249–#255, #257), todos com `gh run view` = `success` e `/health?deep=1` ok. A linha `SERVING_REVISION` do log do deploy é a revisão de **antes**; meça no `gcloud` |
| Comportamento novo (14/11) | **`conferencia`** no `apply_change` (veredito da releitura pós-write; `efeito`/`changed_count` = ACK do Google); `estado_revisao` em RSA; pinos em RSA; lote RSA até 50; `avisos[]` em `run_gaql`/`validate_gaql`; `get_experiments`, `update_recommendation_subscription`, `list_gaql_resources(resource, customer_id)`. Detalhe no [handoff](session-2026-11-14-handoff.md) |
| Comportamento novo (10–11/11) | moeda Meta lida do inventário; contador BUC conta só o lido; re-concessão grava `granted_at`/`granted_by`; revoke Meta grava `admin_revoked`; audit mostra o nome da conta Meta; `classify` com motivo próprio para `create_and_link_assets`, `import_offline_conversions`, `create_campaign`; `APP_TIMEZONE` saiu do deploy; **enum de recomendação no v25** (2 tipos de lance confirmam, `CAMPAIGN_SPECIFIC_APP_GOAL` só leitura); `grant-all` exige `--by` e só toca o que muda |
| Dependências | grpcio 1.85.1, protobuf 7.36.2, starlette 1.10.0 (avisa `httpx` deprecated no `TestClient`), sse-starlette 3.7.0, tzdata 2026.6 |
| Tools | **82** (67 Google + 15 Meta), registry e `/health?deep=1` (14/11) |
| Buckets | **14 always + 68 defer** (registry, 14/11); tokens **não remedidos** desde a [remedição](tool-buckets-2026-10-05.md) |
| Catálogo | até **F211** (~6.300 linhas, 621 KB) |
| APIs | Meta Graph **v25.0** (constante única); Google Ads **v25**, sunset estimado em ago/2027 (**não lido** na página oficial) |
| Smoke do pipeline | sem handshake MCP **autenticado** (F186); desde 10/11 o `SMOKE_MCP_BEARER` está **expirado** (401) e o deploy segue com aviso |

**Uso real, 30 dias até 30/10** (`audit_log`): 2.211 chamadas, 5 gestores (Pedro 801, Luiz 773,
Wellington 590, Lucas 37, Anderson 4); Google 1.752, Meta 459; `run_gaql` 34%. **27 tools sem chamada em
90 dias.** Memória: pico de p99 horário 50%; um único 5xx em 30 dias (503 no health, 01/10, causa
desconhecida).

⚠️ **`deploy: skipped` não significa "PR de documentação":** o gate do F138 pula só push
exclusivamente em `docs/` e markdown; `tests/` publica revisão. **Cheque a revisão servindo.**
Contagens de tool e bucket vêm do registry (`import_all_tools()`), nunca de `grep` (F183).

## Backlog de tráfego — 14/11 (#249–#255, smoke 7/7)

🔴 **Contrato do `apply_change` mudou no #255:** `efeito`/`changed_count` são o **ACK do Google**; o
veredito da releitura pós-write vai em **`conferencia: {campo, pedido, relido, motivo}`** (RSA: `pinos`;
N3: `status`; `null` = não lido). Em RSA o anúncio FOI gravado mesmo com `conferencia` divergente — não
recriar. Narrativa, medições e rulings no [handoff](session-2026-11-14-handoff.md).

**Abertos (baixa):** **S1** lista estática `segments` do `list_gaql_resources` com `segments.hour` e
`segments.network_type` inexistente · **S2** preview do `update_rsa` não acusa no-op (URL igual sai como
mudança) · **S3** não há tool para remover anúncio. Minors adiados no ledger
`.superpowers/sdd/2026-11-14-backlog-trafego/progress.md` (resumo no handoff).
**Não medido:** catálogo no Codex/Cursor; frescor da **aprovação** pós-write; preview de 50 no pior caso.

## Decision gates abertos

**As duas reconciliações revogam** — Meta desde 05/09, Google desde 26/09. **Para desligar:** `false`
nas **duas** linhas do `.github/workflows/deploy.yml` (o `JOB_ENV_VARS`, que o job lê, e o
`--set-env-vars` do serviço); a revogação é soft (`revoked_at`) e o painel reconcede com um clique.

**Fase 2B travada no soak** — o tombstone dos 8 reports antigos espera os gestores migrarem para
`get_performance_breakdown` (breakdown × antigo em 30/10: Luiz 138 × 28, Wellington 12 × 113; o Pedro,
que mais usava os antigos, saiu em 31/10). O plugin 0.5.0 já manda usar o breakdown.

## Próximo trabalho (em ordem)

1. **Conferir o primeiro resync agendado com o F207 e a Parte J** (06:00 de 12/11): exit code, as
   três etapas no log e as linhas `google_reconcile`/`meta_reconcile`/`db_purge` no `audit_log`; e o
   backup semanal, agora com log JSON.
2. **Alerta log-based** sobre `job_init_pool_failed` (decisão sua, 11/11: fica com você).
3. **Retry no `playwright install --with-deps`** do CI (proposta): em 11/11 o DNS dos mirrors Ubuntu
   no runner travou todos os PRs por ~3 h (problema conhecido do `actions/runner-images`).
4. Minors registrados no [handoff](session-2026-11-10-handoff.md) (âncora `optional` que vira zero no
   preview; guard de versão do SDK não pega `importlib`; parâmetro `manager` morto no helper de teste
   do resync).

## Pendências que dependem do Wellington

- **Da varredura de 10/11** (lista completa no [handoff](session-2026-11-10-handoff.md)): clique nos
  toggles de gestor em produção; login novo pelo Google (Parte H); dry-run com gestor das tools de
  status, das 3 do `emitir_preview`, das 5 de mutate da Parte I e do `apply_recommendation` num tipo de
  lance do v25; reemitir o `SMOKE_MCP_BEARER` (expirado: o handshake do smoke não roda). Achados
  catalogados em 11/11: **F208–F211**. **`grant-all` agora pede `--by <seu e-mail>`.**
- **Escrita em produção, com aval próprio:** apagar as linhas de `meta_oauth_connections` (o OAuth
  pessoal saiu no #215); **teste real de convite e cancelamento** (pendente desde 31/10).
- **Desligamento do Pedro:** desativado em 31/10, conexão e sessão revogadas com auditoria; fora do BM.
  **No MCC segue admin** (remoção pedida em 02/11, aguardando admin); conferir as 2 contas de e-mail
  pessoal com admin no MCC, convidadas por ele.
- **Alertas do Dependabot** do repositório.
- **Plugin `v4-trafego-google-ads`:** resta `shared/v4-brand.md:43` de
  [`plugin-correcoes-2026-10-30.md`](plugin-correcoes-2026-10-30.md).
- **`hd` do login Google sem conferência** (decisão registrada).
- **Nível de acesso da API Meta** — `development_access`; a regra do D1 pede 500 chamadas em 15 dias.
- **Identidade `@v4company.com` sem caixa postal no TI** — desbloqueia o **F186** inteiro.
- **F129** (governança do system user Meta) e **F67** (custom domain via LB).
- **`ads_get_field_context` nos 9 fields de `GET /act_<id>`** (saldo Meta), quando o MCP oficial da Meta
  voltar à sessão.
- **Duas recomendações da revisão final da infra** (`expire_connections`; repetir a retirada em qualquer
  erro): sem dado que as peça.

## Findings abertos

| ID | o que é |
|---|---|
| **F180** | **em parte, provavelmente para sempre** — o Google aceita operação impossível em vez de errar, então `failed_count` é constante zero: leia `efeito` e `changed_count` |
| **F185** | `recommendation_subscription`: 4 de 11 opacos e sem chave — limitação da API |
| **F187** | o **resumo no topo** decide e o **detalhe embaixo** é a verdade — 4 instâncias; remédio: derivar o resumo, ou guard da igualdade |
| **F186** | 🔴 smoke autenticado do `/mcp` **desarmado**, risco ACEITO até a identidade do TI |
| — | negativas de grupo e listas compartilhadas na auditoria de negativas (frente própria) |
| — | follow-ups Minor do **F193** (corpo do [#111](https://github.com/BadWolf1509/v4-ads-mcp/pull/111)) |
| — | orçamento de período fixo (`CUSTOM_PERIOD`) no `get_budget_pacing` (Fora do F202) |
| — | o que ficou fora da varredura de 30/10: seção "O que ficou fora" do [handoff](../_archive/handoffs/session-2026-10-31-handoff.md) |

**Fechados de 20/09 a 04/11:** F154, F179, F181–F184, F188–F191, F193–F206. O defeito de cada um está no
[catálogo](findings-catalog.md). 🔑 A lição que atravessa todos: **existia a regra e não existia o
mecanismo**.
