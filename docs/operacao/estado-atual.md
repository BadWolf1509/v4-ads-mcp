# Estado atual — V4 Ads MCP

> **Volátil por natureza** — o `CLAUDE.md` mantém um resumo de poucas linhas e aponta para cá.
> **Ao terminar uma sessão, atualize ESTE arquivo** e mantenha-o curto (teto prático: ~10 KB; em 20/09
> chegou a 91 KB). **Trabalho que fechou sai daqui:** o defeito vai para o catálogo, a narrativa para o
> handoff ou o [`_archive/`](../_archive/estado-atual-2026-10-30-a-11-04.md), e aqui fica uma linha.

> **Última sessão:** [`session-2026-11-17-handoff.md`](session-2026-11-17-handoff.md) — 15–17/11: faxina
> P0–P6 (#264–#272), F212–F215 (#273), **revogação na desativação** (#274, F213) e a trava ligada. Antes:
> [`session-2026-11-15-handoff.md`](session-2026-11-15-handoff.md) (S1–S3 do smoke, `remove_ad`).

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

## Produção — medido em 2026-11-11 e 15/11

| | |
|---|---|
| Revisão servindo | **`v4-ads-mcp-00224-9sn`**, 100% (`gcloud`, 15/11, depois do #270). A linha `SERVING_REVISION` do log do deploy é a revisão de **antes**; meça no `gcloud` |
| Comportamento novo (14–15/11) | **`conferencia`** no `apply_change` (veredito da releitura pós-write; `efeito`/`changed_count` = ACK do Google); `estado_revisao` e pinos em RSA; lote RSA até 50; `update_rsa` igual ao atual fora do token; **`remove_ad`**; `avisos[]` em `run_gaql`/`validate_gaql`; `get_experiments`, `update_recommendation_subscription`, `list_gaql_resources(resource, customer_id)`. Detalhe nos handoffs de [14/11](session-2026-11-14-handoff.md) e [15/11](session-2026-11-15-handoff.md); o de 10–11/11 está no [handoff](../_archive/handoffs/session-2026-11-10-handoff.md) |
| Dependências | grpcio 1.85.1, protobuf 7.36.2, starlette 1.10.0 (avisa `httpx` deprecated no `TestClient`), sse-starlette 3.7.0, tzdata 2026.6 |
| Tools | **83** (68 Google + 15 Meta), registry e `/health?deep=1` (15/11) |
| Buckets | **14 always + 69 defer** (registry, 15/11); tokens **não remedidos** desde a [remedição](tool-buckets-2026-10-05.md) |
| Catálogo | até **F215** (~6.400 linhas, 631 KB) |
| APIs | Meta Graph **v25.0** (constante única); Google Ads **v25**, sunset estimado em ago/2027 (**não lido** na página oficial) |
| Smoke do pipeline | sem handshake MCP **autenticado** (F186); desde 10/11 o `SMOKE_MCP_BEARER` está **expirado** (401) e o deploy segue com aviso |

**Uso real, 30 dias até 30/10** (`audit_log`): 2.211 chamadas, 5 gestores (Pedro 801, Luiz 773,
Wellington 590, Lucas 37, Anderson 4); Google 1.752, Meta 459; `run_gaql` 34%. **27 tools sem chamada em
90 dias** — contagem errada: 7 leituras não gravavam audit no sucesso, corrigido no #264; remedir com
`scripts/medir_uso_tools.py --dias 90` (exige `DATABASE_URL`, só leitura) depois do 02/12, antes de
decidir remoção. Memória: pico de p99 horário 50%; um único 5xx em 30 dias (503 no health, 01/10, causa
desconhecida).

⚠️ **`deploy: skipped` não significa "PR de documentação":** o gate do F138 pula só push
exclusivamente em `docs/` e markdown; `tests/` publica revisão. **Cheque a revisão servindo.**
Contagens de tool e bucket vêm do registry (`import_all_tools()`), nunca de `grep` (F183).

## Faxina de 15/11 — fechada (#264–#270)

Sem mudança no que o gestor vê, salvo o P0 (audit). Achados em
[`varredura-faxina-2026-11-15.md`](varredura-faxina-2026-11-15.md); ledger com rulings e minors
adiados em `.superpowers/sdd/2026-11-15-varredura-faxina/progress.md` (git-ignored).

| PR | parte | o quê |
|---|---|---|
| [#264](https://github.com/BadWolf1509/v4-ads-mcp/pull/264) | P0 | 7 leituras gravam audit no sucesso; `scripts/medir_uso_tools.py` |
| [#265](https://github.com/BadWolf1509/v4-ads-mcp/pull/265) | P1 | ~246 KB de docs para `_archive/`, fatos corrigidos |
| [#266](https://github.com/BadWolf1509/v4-ads-mcp/pull/266) | P2 | guards AST memoizados: 48 s → ~8 s |
| [#267](https://github.com/BadWolf1509/v4-ads-mcp/pull/267) | P3 | código morto pontual |
| [#268](https://github.com/BadWolf1509/v4-ads-mcp/pull/268) | P4 | testes: schema guard global, `ctx_mcp`, fakes comuns (−1.000 linhas) |
| [#269](https://github.com/BadWolf1509/v4-ads-mcp/pull/269) | P5 | duplicação em `src`: AUTO/CONFIRM (3 tools), janela de data, páginas de acesso, plano de reconciliação |
| [#270](https://github.com/BadWolf1509/v4-ads-mcp/pull/270) | P6 | `finally` dos 6 executores Google em `encerrar_execucao` |

**Medido depois do deploy (15/11):** as 6 páginas de acesso batem com o banco (4 gestores ativos × 24
contas Google e × 26 Meta); `get_performance_breakdown` e `plan_keyword_ideas` reais gravaram audit
`success`. **Não medido:** dry-run de mutação depois do P5/P6 (pede o gestor presente). **Aberto:** o
log `conversion_upload_executed` diz `success` quando o audit falha num upload 100% recusado
(comportamento antigo, **F214**).

## Revogação na desativação — em produção (15/11, #274, `00226-5p4`; F213)

Desativar um gestor revoga os grants Google e Meta (motivo `manager_deactivated`); reativar devolve só
esses. Medido: ciclo no painel num gestor ativo, 24+26 revogados e devolvidos, os 4 de churn intactos
(audit 11272/11273). Rodadas de 16 e 17/11 com `apply: false` bateram o plano (48 + 47, só os 2
desativados). **Trava `MANAGER_OFFBOARDING_APPLY` ligada em 17/11** (`deploy.yml`, `JOB_ENV_VARS`).
**Aplicada em 17/11** (revisão `00227-7th`, execução manual `v4-ads-mcp-resync-sk5h7`, audits 11628/11629):
48 + 47 revogados, os 2 desativados com **0 grants vivos**, nenhum gestor ativo tocado. Minors no
[handoff](session-2026-11-17-handoff.md).

## Backlog de tráfego — fechado (14–15/11, #249–#262)

🔴 **Contrato do `apply_change` (#255):** `efeito`/`changed_count` são o **ACK do Google**; o veredito da
releitura pós-write vai em **`conferencia: {campo, pedido, relido, motivo}`** (RSA: `pinos`; N3 e
`remove_ad`: `status`; `null` = não lido). Em RSA o anúncio FOI gravado mesmo com `conferencia`
divergente — não recriar. **`remove_ad` é irreversível:** sempre token, smoke na MO em 15/11.
**Não medido:** TOCTOU entre preview e apply da `remove_ad`; catálogo no Codex/Cursor; frescor da
**aprovação** pós-write; preview de 50 no pior caso. Minors nos ledgers `.superpowers/sdd/2026-11-14-*`.

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
4. Minors registrados no [handoff](../_archive/handoffs/session-2026-11-10-handoff.md) (âncora `optional` que vira zero no
   preview; guard de versão do SDK não pega `importlib`; parâmetro `manager` morto no helper de teste
   do resync).

## Pendências que dependem do Wellington

- **Da varredura de 10/11** (lista completa no [handoff](../_archive/handoffs/session-2026-11-10-handoff.md)): login novo pelo Google (Parte H); dry-run com gestor das tools de
  status, das 3 do `emitir_preview`, das 5 de mutate da Parte I e do `apply_recommendation` num tipo de
  lance do v25; reemitir o `SMOKE_MCP_BEARER` (expirado: o handshake do smoke não roda). Achados
  catalogados em 11/11: **F208–F211**. **`grant-all` agora pede `--by <seu e-mail>`.**
- **Escrita em produção, com aval próprio:** apagar as linhas de `meta_oauth_connections` (o OAuth
  pessoal saiu no #215); **teste real de convite e cancelamento** (pendente desde 31/10).
- **Desligamento do Pedro:** desativado em 31/10, conexão e sessão revogadas com auditoria; fora do BM.
  **No MCC segue admin** (remoção pedida em 02/11, aguardando admin); conferir as 2 contas de e-mail
  pessoal com admin no MCC, convidadas por ele.
- **Alertas do Dependabot** do repositório.
- **Alerta de saldo:** manual do gestor em [`guia-alerta-de-saldo.md`](guia-alerta-de-saldo.md).
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
| **F214** | log `conversion_upload_executed` diz `success` num upload 100% recusado quando o audit não pega conexão (só observabilidade) |
| **F186** | 🔴 smoke autenticado do `/mcp` **desarmado**, risco ACEITO até a identidade do TI |
| — | negativas de grupo e listas compartilhadas na auditoria de negativas (frente própria) |
| — | follow-ups Minor do **F193** (corpo do [#111](https://github.com/BadWolf1509/v4-ads-mcp/pull/111)) |
| — | orçamento de período fixo (`CUSTOM_PERIOD`) no `get_budget_pacing` (Fora do F202) |
| — | o que ficou fora da varredura de 30/10: seção "O que ficou fora" do [handoff](../_archive/handoffs/session-2026-10-31-handoff.md) |

**Fechados de 20/09 a 04/11:** F154, F179, F181–F184, F188–F191, F193–F206. O defeito de cada um está no
[catálogo](findings-catalog.md). 🔑 A lição que atravessa todos: **existia a regra e não existia o
mecanismo**.
