# Estado atual — V4 Ads MCP

> **Volátil por natureza** — o `CLAUDE.md` mantém um resumo de poucas linhas e aponta para cá.
> **Ao terminar uma sessão, atualize ESTE arquivo** e mantenha-o curto (teto prático: ~10 KB; em 20/09
> chegou a 91 KB). **Trabalho que fechou sai daqui:** o defeito vai para o catálogo, a narrativa para o
> handoff ou o [`_archive/`](../_archive/estado-atual-2026-10-30-a-11-04.md), e aqui fica uma linha.

> **Última sessão:** [`session-2026-11-10-handoff.md`](session-2026-11-10-handoff.md) — 10 e 11/11: deps
> (#227, #223) e a [varredura de refatoração de 10/11](../superpowers/plans/2026-11-10-varredura-refatoracao.md),
> **Partes A a I em produção** (#228 a #236); J pulada (depende do F207). À tarde de 11/11: ruff/mypy
> fixados (#238), **C2** (#239) e follow-ups (#240). Antes:
> [`session-2026-11-04-handoff.md`](session-2026-11-04-handoff.md).

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

## Produção — medido em 2026-11-11

| | |
|---|---|
| Revisão servindo | **`v4-ads-mcp-00201-vwn`** (#240), 100% do tráfego medido no `gcloud`. De 10 a 11/11: `00188` a `00201` (tabela no [handoff](session-2026-11-10-handoff.md)). A linha `SERVING_REVISION` do log do deploy é a revisão de **antes**; meça no `gcloud` |
| Comportamento novo (10–11/11) | moeda Meta lida do inventário; contador BUC conta só o lido; re-concessão grava `granted_at`/`granted_by`; revoke Meta grava `admin_revoked`; audit mostra o nome da conta Meta; `classify` com motivo próprio para `create_and_link_assets`, `import_offline_conversions`, `create_campaign`; `APP_TIMEZONE` saiu do deploy; **enum de recomendação no v25** (2 tipos de lance confirmam, `CAMPAIGN_SPECIFIC_APP_GOAL` só leitura); `grant-all` exige `--by` e só toca o que muda |
| Dependências | grpcio 1.85.1, protobuf 7.36.2, starlette 1.10.0 (avisa `httpx` deprecated no `TestClient`), sse-starlette 3.7.0, tzdata 2026.6 |
| Tools | **80** (65 Google + 15 Meta), contagem do registry e do `/health?deep=1` |
| Buckets | **14 always + 66 defer** (registry); tokens **não remedidos** desde a [remedição](tool-buckets-2026-10-05.md) |
| Catálogo | até **F207** (~6.100 linhas, 603 KB) |
| APIs | Meta Graph **v25.0** (constante única); Google Ads **v25**, sunset estimado em ago/2027 (**não lido** na página oficial) |
| Smoke do pipeline | sem handshake MCP **autenticado** (F186); desde 10/11 o `SMOKE_MCP_BEARER` está **expirado** (401) e o deploy segue com aviso |

**Uso real, 30 dias até 30/10** (`audit_log`): 2.211 chamadas, 5 gestores (Pedro 801, Luiz 773,
Wellington 590, Lucas 37, Anderson 4); Google 1.752, Meta 459; `run_gaql` 34%. **27 tools sem chamada em
90 dias.** Memória: pico de p99 horário 50%; um único 5xx em 30 dias (503 no health, 01/10, causa
desconhecida).

⚠️ **`deploy: skipped` não significa "PR de documentação":** o gate do F138 pula só push
exclusivamente em `docs/` e markdown; `tests/` publica revisão. **Cheque a revisão servindo.**
Contagens de tool e bucket vêm do registry (`import_all_tools()`), nunca de `grep` (F183).

## Decision gates abertos

**As duas reconciliações revogam** — Meta desde 05/09, Google desde 26/09. **Para desligar:** `false`
nas **duas** linhas do `.github/workflows/deploy.yml` (o `JOB_ENV_VARS`, que o job lê, e o
`--set-env-vars` do serviço); a revogação é soft (`revoked_at`) e o painel reconcede com um clique.

**Fase 2B travada no soak** — o tombstone dos 8 reports antigos espera os gestores migrarem para
`get_performance_breakdown` (breakdown × antigo em 30/10: Luiz 138 × 28, Wellington 12 × 113; o Pedro,
que mais usava os antigos, saiu em 31/10). O plugin 0.5.0 já manda usar o breakdown.

## Próximo trabalho (em ordem)

1. **F207** — as 4 falhas silenciosas dos jobs, um TDD por bug, num PR; depois a **Parte J** da
   varredura. Numa sessão com você. (Os logs do resync de 04 a 11/11 já foram lidos: as três etapas
   rodam e saem com `exit(0)`.)
2. **Decisões suas da tarde de 11/11** ([handoff](session-2026-11-10-handoff.md)): regerar o snapshot
   para atualizar as descrições de `apply_recommendation`/`get_recommendations`; confirmar que a
   promoção read→write no `grant-all` ganha autor novo.
3. Minors registrados no handoff (âncora `optional` que vira zero, guards de versão/reexport/I4).

## Pendências que dependem do Wellington

- **Da varredura de 10/11** (lista completa no [handoff](session-2026-11-10-handoff.md)): clique nos
  toggles de gestor em produção; login novo pelo Google (Parte H); dry-run com gestor das tools de
  status, das 3 do `emitir_preview`, das 5 de mutate da Parte I e do `apply_recommendation` num tipo de
  lance do v25; reemitir o `SMOKE_MCP_BEARER` (expirado: o handshake do smoke não roda); achados novos
  para o `/findings-add`. **`grant-all` agora pede `--by <seu e-mail>`.**
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
| **F207** | quatro falhas silenciosas pré-existentes nos jobs (purge sem exit code nem audit, mensagem enganosa, audit "sem OAuth" vira crash, `init_pool` sem audit) |
| **F180** | **em parte, provavelmente para sempre** — o Google aceita operação impossível em vez de errar, então `failed_count` é constante zero: leia `efeito` e `changed_count` |
| **F185** | `recommendation_subscription`: 4 de 11 opacos e sem chave — limitação da API |
| **F187** | o **resumo no topo** decide e o **detalhe embaixo** é a verdade — 4 instâncias; remédio: derivar o resumo, ou guard da igualdade |
| **F186** | 🔴 smoke autenticado do `/mcp` **desarmado**, risco ACEITO até a identidade do TI |
| — | negativas de grupo e listas compartilhadas na auditoria de negativas (frente própria) |
| — | follow-ups Minor do **F193** (corpo do [#111](https://github.com/BadWolf1509/v4-ads-mcp/pull/111)) |
| — | orçamento de período fixo (`CUSTOM_PERIOD`) no `get_budget_pacing` (Fora do F202) |
| — | o que ficou fora da varredura de 30/10: seção "O que ficou fora" do [handoff](session-2026-10-31-handoff.md) |

**Fechados de 20/09 a 04/11:** F154, F179, F181–F184, F188–F191, F193–F206. O defeito de cada um está no
[catálogo](findings-catalog.md). 🔑 A lição que atravessa todos: **existia a regra e não existia o
mecanismo**.
