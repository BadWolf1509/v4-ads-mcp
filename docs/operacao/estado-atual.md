# Estado atual — V4 Ads MCP

> **Volátil por natureza** — o `CLAUDE.md` mantém um resumo de poucas linhas e aponta para cá.
> **Ao terminar uma sessão, atualize ESTE arquivo** e mantenha-o curto: em 20/09 ele tinha
> **91 KB**, 83 deles narrando frente já concluída e contradizendo a própria tabela. **Trabalho
> que fechou sai daqui:** o defeito vai para o catálogo, a narrativa para o arquivo
> ([`_archive/`](../_archive/varredura-2026-09-06-frentes.md)), e aqui fica uma linha.

> **Última sessão:** [`session-2026-10-31-handoff.md`](session-2026-10-31-handoff.md) — 30/10, tarde:
> a **varredura de correções** em 6 blocos (#174 a #184): OAuth, restore e job bloqueado, governança de
> mutação, Graph v25, deps e deploy, painel e contratos das tools. Textos prontos para o
> `/findings-add` estão no handoff. Antes: [`session-2026-10-30-handoff.md`](session-2026-10-30-handoff.md).

> **Direção Meta (02/11): híbrida.** O nosso MCP mantém Google, leitura Meta e governança. A Onda 3 está
> congelada; escrita, públicos e pixel ficam com o MCP oficial da Meta, ligado à conta do usuário.
>
> **Teste de 30 dias, até 02/12 (decisão de 02/11):** evolução Meta pausada, com Google e governança
> mantidos. Em 02/12: 3 ou mais gestores ativos por semana e escritas Google recorrentes, continua; uso alto
> só em leitura, reduz ao mínimo; menos de 2 gestores ativos, encerra a evolução e migra para os oficiais.
> **Não medido na decisão:** uso depois de 30/10, custo de infra e satisfação dos gestores.
>
> **MCP oficial da Meta (02/11):** a lista segue a atribuição do usuário no BM, com efeito imediato; alcançou
> todas as contas ativas do portfólio depois da atribuição. Em uma conta de cliente, gasto, impressões, cliques
> e alcance bateram com o nosso MCP. `adset_schedule` e `delivery` vieram; `learning_stage_info` veio sem
> `status` e `delivery_sub_status` não veio. Escrita não testada. Escrita liberada por padrão nas contas:
> bloqueio pendente de decisão.
>
> **Onda 2 Meta pausada**, 3 auditorias, plano em
> [`2026-11-02-meta-onda-2-auditorias.md`](../superpowers/plans/2026-11-02-meta-onda-2-auditorias.md). Retomada
> só se o teste de 30 dias pedir.
>
> **Onda 1 Meta em produção, com smoke real feito em 02/11 (#201 `00168-jxv`, correções no #203 `00169-h9n`):** 8 tools de
> leitura Meta, todas somente leitura: `meta_get_entities`, `meta_get_change_history`, `meta_get_creatives`,
> `meta_get_ad_preview`, `meta_get_budget_pacing`, `meta_search_targeting`, `meta_get_delivery_estimate`,
> `meta_get_pages`. Retiradas do plano: `meta_get_custom_audiences` e `meta_get_signal_health` (sem prova de
> que o token enxerga público e pixel; ver [sonda](sonda-meta-onda1-2026-10-31.md)). As descriptions de
> desempenho agora apontam para `meta_get_entities`.
>
> **Smoke:** as 8 tools rodaram na conta interna; 4 delas, mais `meta_get_campaign_performance`, rodaram na
> conta de cliente com campanha ativa; a terceira conta veio vazia, sem distinguir conta vazia de falta de
> alcance do token. Achou 4 defeitos, todos corrigidos no #203 e reconferidos em produção: `truncated` da
> busca, janela do histórico fora do fuso da conta, `alcance_diario` 0 parecendo medição e totais do pacing
> sem explicação. Com a correção, o corte de fuso, o último dia do histórico e a paginação do histórico
> foram provados em conta real.
>
> **Não medido na Onda 1:** paginação de `meta_get_entities` além de uma página, render da prévia, objetivos
> além de REACH, causa do `estimate_dau` 0, texto
> publicado das descriptions depois do #203, uso das tools desde o deploy, `ads_get_field_context`.
> **Conferência no Gerenciador (02/11, conta de cliente):** gasto e impressões da semana, gasto e
> impressões do dia, orçamentos e a cobrança de 30/10 bateram com o MCP, o que cumpre a definição de
> pronto da Onda 1. O gasto zero de domingo vem da programação de anúncios do conjunto, vista em uma
> das 6 campanhas vitalícias. O saldo restante não foi lido na tela. Orçamento menos gasto fica um pouco
> abaixo do valor do MCP nas 6, o que combina com gasto depois da leitura, sem provar. Das 12 campanhas
> encerradas, só 1 foi lida individualmente.

---

## Produção — medido em 2026-10-30

| | |
|---|---|
| Revisão servindo | **`v4-ads-mcp-00169-h9n`** (#203, correções do smoke da Onda 1 Meta, 02/11), 100% do tráfego, `/health?deep=1` com 80 tools. Antes: #201 `00168-jxv`, Onda 1 Meta. Sequência da varredura: #174 `00155-flr`, #175 `00156-2lh`, #176 `00157-n24`, #177 `00158-bxt`, #178 `00159-2zs`, #184 `00160-bcd`. Dependências de 31/10, uma por deploy, com leitura real no Google Ads depois de cada uma: #186 `00161-nfg`, #183 `00162-dqd` (`websockets` 17), #179 `00163-qwq` (`grpcio` 1.85). Confirmação do painel: #188 `00164-x6w`; htmx local e smoke de navegador: #190 `00165-n4w`; teste do hook publicou a `00166-692`; a `00167-b57` veio depois, sem mudança de produto. O smoke do pipeline segue sem handshake MCP **autenticado** (F186); o pipeline novo (smoke antes dos jobs, rollback pulado) rodou de verdade no #178 |
| Tools | **80 em produção** (65 Google + 15 Meta), contagem do registry e do `/health?deep=1` |
| Buckets | **14 always + 66 defer** em produção (registry); tokens **não remedidos** desde a [remedição](tool-buckets-2026-10-05.md) de 13 + 59 |
| Catálogo | até **F203** (~6.000 linhas, 601 KB); os defeitos da varredura aguardam o `/findings-add` |
| Meta Graph | **v25.0**, constante única. A v22 expirou em 19/02/2026 |
| Google Ads | API **v25**; sunset estimado em ago/2027 (busca, **não lido** na página oficial) |

**Uso real, 30 dias até 30/10** (`audit_log`): **2.211 chamadas**, 5 gestores — `pedro.vytor` 801,
`luizfelipe` 773 (entrou em 07/10), Wellington 590, `lucassoares` 37 (só admin), Anderson 4. Google
1.752, Meta 459. Por mês: mai 361, jun 654, jul 1.071, ago 1.484, set 1.896, out 2.211.
`run_gaql` 757 (34%). Falhas quase só do Wellington (42 de 349; Pedro 1 erro + 10 recusas em 238;
Luiz 0 em 170). **27 tools sem chamada em 90 dias** (`apply_change` fora: é registrado na tool de
origem, ausência não provada).

**Fase 2B, por gestor:** breakdown × antigo — Luiz 138 × 28; Pedro 5 × 106; Wellington 12 × 113.
Segue travada no soak; não tombstonar.

**Memória e erros:** pico de p99 horário 50% em 30 dias; um único 5xx (503 em `/health?deep=1`,
01/10 17:09 UTC, causa desconhecida, sem deploy no dia).

**Smoke da varredura:** leitura Meta real após o #177, sem aviso de versão. Login real feito pelo
Wellington em 31/10. **Não feito:** convite (ver Pendências).

⚠️ **`deploy: skipped` não significa "PR de documentação":** o gate do F138 pula só push
exclusivamente em `docs/` e markdown; `tests/` publica revisão. **Cheque a revisão servindo.**
Contagens de tool e bucket vêm do registry (`import_all_tools()`), nunca de `grep` (F183).

## Decision gates abertos

**As duas reconciliações revogam** — Meta desde 05/09, Google desde 26/09. **Para desligar:** `false`
nas **duas** linhas do `.github/workflows/deploy.yml` (o `JOB_ENV_VARS`, que o job lê, e o
`--set-env-vars` do serviço); a revogação é soft (`revoked_at`) e o painel reconcede com um clique.

**Fase 2B travada no soak** — o tombstone dos 8 reports antigos espera os gestores migrarem para
`get_performance_breakdown`; só o Luiz migrou, e o Pedro, que mais usava os antigos, saiu em 31/10. O plugin 0.5.0 já manda usar o breakdown.

## Pendências que dependem do Wellington

- **Rodar: convite e cancelamento de convite** — o login real passou em 31/10; o convite segue sem
  teste, e o clique em "Cancelar" só foi corrigido no #188.
- **Desligamento do Pedro:** desativado em 31/10; conexão Google e sessão MCP revogadas no banco, com
  auditoria (`admin_manager_offboarding_revoke`). Os 50 acessos a contas ficaram, de propósito. Conferido em
  02/11: ele não está em Pessoas no BM. **No MCC segue admin, com a remoção pedida em 02/11 aguardando
  análise de admin.** O token segue válido no Google até lá, mas o MCP não o usa mais. Conferir também as
  2 contas de e-mail pessoal com admin no MCC, convidadas por ele.
- **Alertas do Dependabot** do repositório: ajuste do repositório, feito por você.
- **Plugin `v4-trafego-google-ads`:** aplicar as correções de
  [`plugin-correcoes-2026-10-30.md`](plugin-correcoes-2026-10-30.md) na fonte. O `null` já foi tratado
  no 0.5.0; **resta `shared/v4-brand.md:43`**.
- **`hd` do login Google sem conferência** (decisão do Wellington, registrada no handoff).
- **Nível de acesso da API Meta** — `ads_api_access_tier: development_access` (26/09); a regra do
  D1 pede 500 chamadas em 15 dias; Meta fez 459 em 30 dias. Pedir agora ou esperar.
- **Identidade `@v4company.com` sem caixa postal no TI** — desbloqueia o **F186** inteiro.
- **F129** (governança do system user Meta) e **F67** (custom domain via LB).
- **`ads_get_field_context` não rodado nos 9 fields de `GET /act_<id>`** (saldo Meta): evidência ao
  vivo aceita em 29/10; rodar quando o MCP oficial da Meta voltar à sessão.
- **Duas recomendações da revisão final da infra** (`expire_connections` na primeira queda; repetir a
  retirada em qualquer erro do teste): sem dado que as peça.
- **`recommendation_subscription`** — a tool de LEITURA, contando os opacos (F185); a de escrita, não.

## Findings abertos

| ID | o que é |
|---|---|
| **F180** | **em parte, provavelmente para sempre** — o Google aceita operação impossível em vez de errar, então `failed_count` é constante zero: leia `efeito` e `changed_count` |
| **F185** | `recommendation_subscription`: 4 de 11 opacos e sem chave — limitação da API |
| **F187** | o **resumo no topo** decide e o **detalhe embaixo** é a verdade — 4 instâncias; remédio: derivar o resumo, ou guard da igualdade |
| **F186** | 🔴 smoke autenticado do `/mcp` **desarmado**, risco ACEITO até a identidade do TI |
| — | negativas de grupo e listas compartilhadas na auditoria de negativas (frente própria) |
| — | follow-ups Minor do **F193** (corpo do [#111](https://github.com/BadWolf1509/v4-ads-mcp/pull/111)) |
| — | `export_csv_rows(manager_id=None)` exporta o audit de todos os gestores por default — falha aberta latente (as rotas passam o gestor) |
| — | orçamento de período fixo (`CUSTOM_PERIOD`) no `get_budget_pacing` (Fora do F202) |
| — | o que ficou fora da varredura de 30/10: seção "O que ficou fora" do [handoff](session-2026-10-31-handoff.md) |

**Fechados de 20/09 a 30/10:** F154, F179, F181–F184, F188–F191, F193–F203 e os da varredura de
30/10 (textos no handoff). O defeito de cada um está no [catálogo](findings-catalog.md); a narrativa
antiga, em [`_archive/`](../_archive/estado-atual-2026-09-27-a-28.md). 🔑 A lição que atravessa todos:
**existia a regra e não existia o mecanismo**.
