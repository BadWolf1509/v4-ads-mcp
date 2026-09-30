# Estado atual — V4 Ads MCP

> **Volátil por natureza** — o `CLAUDE.md` mantém um resumo de poucas linhas e aponta para cá.
> **Ao terminar uma sessão, atualize ESTE arquivo** e mantenha-o curto: em 20/09 ele tinha
> **91 KB**, 83 deles narrando frente já concluída e contradizendo a própria tabela. **Trabalho
> que fechou sai daqui:** o defeito vai para o catálogo, a narrativa para o arquivo
> ([`_archive/`](../_archive/varredura-2026-09-06-frentes.md)), e aqui fica uma linha.

> **Última sessão:** [`session-2026-09-29-handoff.md`](session-2026-09-29-handoff.md) — 29/09: a
> verificação parcial da infra e guards, a saída das 4 contas Meta do BM, e três consertos
> commitados **sem deploy** (F202 pacing; F203 pool). Antes:
> [`session-2026-09-28-noite-handoff.md`](session-2026-09-28-noite-handoff.md) (F199, erro de data,
> infra e guards).

---

## Produção — medido em 2026-09-29

| | |
|---|---|
| Revisão servindo | **`v4-ads-mcp-00139-fpf`**, 100% do tráfego (29/09) — o deploy do **#133** (infra e guards). Os PRs de docs #134–#136 não deployaram. ⚠️ O smoke do pipeline segue sem handshake MCP **autenticado** (F186) |
| Tools | **68** (62 Google + 6 Meta) |
| Buckets | 22 always + 46 defer — **próxima remedição 04/10** ([método](tool-buckets-2026-09-04.md)) |
| Catálogo | até **F203** (~6.000 linhas, 601 KB) |

**Infra e guards verificada em produção (F200, 24 h até 30/09 00:08 UTC):** zero reconexão, zero
`severity>=ERROR`, zero 5xx em ~2.500 requests (o filtro acha os 2 eventos da base); job de 29/09
`success`. **Custo do `SELECT 1` na retirada: +8 ms no p50** do `/health?deep=1` (16,0 → 24,1 ms;
p95 80,2 → 95,1) — o A/B limpo. Latência se mede **por rota, pelos logs de request**
(`latencia_por_rota.py`); a métrica do serviço agrega percentil entre séries e não compara. Scripts
em `.superpowers/verificacao-2026-09-29/` (`latencia_por_rota.py`, `contas_no_bm.py`).

**Aguardando deploy (commitado, sem push):**

| branch | commits | o quê |
|---|---|---|
| `fix/pool-timeout-no-teste` | `bc7e343`, `91c0c9f` | **F203** — prazo de 2 s no `SELECT 1` da retirada, com `terminate()`; e a conexão que sai do corpo por timeout ou cancelamento é descartada. As duas travas eram **sem limite** (medido: 75 s e 90 s), a segunda levando junto quem chamou e a vaga do pool |
| `fix/pacing-orcamento-compartilhado` | `1082e61` | **F202** — `get_budget_pacing` mede o orçamento compartilhado pelo orçamento: percentuais `null` na campanha e bloco `orcamentos_compartilhados` com o gasto lido do `campaign_budget` |

Deploy: o F203 primeiro (mexe no pool de toda requisição), cada um em PR próprio com autorização
nominal; o segundo fica BEHIND quando o primeiro mescla (`git merge origin/main`, nunca force-push).

**Com data:**
- **30/09, 09:00 UTC** — 2ª ausência das 4 contas Meta no job (`missed_syncs=2`).
- **01/10, 09:00 UTC** — as 4 contas desativadas e os **16 grants revogados** (a 1ª ausência
  entrou em 29/09, como previsto; teto de remoção 5 com 25 ativas, não barra). Smoke de leitura do
  F196 (`THIS_MONTH` devolve o dia 1), do F199 (projeção `null`) e do F202, se já no ar.
- **04/10** — remedição dos buckets e do uso da Fase 2B por gestor.

⚠️ **`deploy: skipped` não significa "PR de documentação":** o gate do F138 pula só push
exclusivamente em `docs/` e markdown; `tests/` publica revisão. **Cheque a revisão servindo.**
Contagens de tool e bucket vêm do registry (`import_all_tools()`), nunca de `grep` (F183).

## Decision gates abertos

**As duas reconciliações revogam** — Meta desde 05/09, Google desde 26/09 (22 execuções de soak
antes; conferidas depois 26/09 `removed=3`/`revoked_grants=46` e 28/09 `removed=1`/`4`, zero grant
vivo em conta inativa). **Para desligar:** `false` nas **duas** linhas do
`.github/workflows/deploy.yml` (o `JOB_ENV_VARS`, que o job lê, e o `--set-env-vars` do serviço);
a revogação é soft (`revoked_at`) e o painel reconcede com um clique.

**Fase 2B travada no soak** — o tombstone dos 8 reports antigos espera os gestores migrarem para
`get_performance_breakdown`. Medido em 25/09: `get_campaign_performance` 148 chamadas de 3
gestores contra 33 do breakdown (1 gestor) em 30 dias, com o plugin 0.4.1 (que já manda usar o
breakdown) instalado desde 20/09 — o motor está na versão do plugin dos outros gestores ou no LLM
escolhendo pelo nome. Separar por gestor é a medida de 04/10.

## Pendências que dependem do Wellington

- **Duas recomendações restantes da revisão final da infra e guards** (`expire_connections` na
  primeira queda; repetir a retirada em qualquer erro do teste): **sem dado que as peça** — zero
  quedas desde o deploy. A terceira virou o F203.
- **Ajuste do `null` no plugin `v4-trafego-google-ads`** — seis pontos fazem conta com campos que
  podem vir `null` desde 26/09 (`analise-performance-google-ads/SKILL.md:44,137`;
  `relatorio-cliente-google-ads/SKILL.md:33,76-89,112-116`; `shared/v4-brand.md:43`); com o F202,
  também `spent_pct_of_monthly_budget` e `projection_vs_budget_pct` do pacing em orçamento
  compartilhado. A cópia instalada é upload do app: o ajuste é na fonte. Até lá o relatório de
  cliente pode imprimir `None`.
- **Nível de acesso da API Meta** — `ads_api_access_tier: development_access` (26/09); a regra do
  D1 pede 500 chamadas em 15 dias, o uso é ~200. Pedir agora ou esperar.
- **Identidade `@v4company.com` sem caixa postal no TI** — desbloqueia o **F186** inteiro. Emitir
  token sob um manager existente está recusado (~38 contas Google e 26 Meta no GitHub Actions).
- **F129** (governança do system user Meta) e **F67** (custom domain via LB).
- **`recommendation_subscription`** — recomendada a tool de LEITURA, varrendo só o que o gestor
  alcança e contando os opacos (F185: 4 de 11 sem chave); a de escrita, não.

## Findings abertos

### Varredura de 21/09 (5 agentes, 4 sub-projetos)

Relatórios e destino de cada achado em
[`_archive/varredura-2026-09-21/`](../_archive/varredura-2026-09-21/README.md).

| sub-projeto | status |
|---|---|
| 1 · credencial + contratos do SDK Meta | fechado — **F190** |
| 2 · respostas que afirmam mais do que mediram | fechado — **F191** e **F193** (as métricas Meta, fora dele, no **F194**) |
| 3 · infra de dados | **fechado** — CSV no F191; o resto no **F200**, verificado em produção em 30/09 ([spec](../superpowers/specs/2026-09-28-infra-e-guards-design.md)) |
| 4 · guards que não cobrem | **fechado** — mock no F191; o resto no **F200**: o pool valida a conexão num ponto só |

### Ordem de ataque (atualizada em 29/09)

Medir a exposição, dar dado às decisões, consertos pequenos, e só então specs — um por vez.

1. **Deploy do F203 e do F202**, e o smoke de 01/10.
2. **Fase 2B** — em 04/10, o uso por gestor, junto dos buckets.
3. **`recommendation_subscription`** — spec da tool de leitura.
4. **F187** — o remédio do resumo × detalhe.

### Os abertos, um por linha

| ID | o que é |
|---|---|
| **F180** | **em parte, provavelmente para sempre** — o Google aceita operação impossível em vez de errar, então `failed_count` é constante zero: leia `efeito` e `changed_count`. O único gatilho conhecido (variação de experimento) o **F181** bloqueia no pre-flight |
| **F185** | `recommendation_subscription`: 4 de 11 opacos e sem chave — limitação da API |
| **F187** | o **resumo no topo** decide e o **detalhe embaixo** é a verdade — 4 instâncias; remédio: derivar o resumo, ou guard da igualdade |
| **F186** | 🔴 smoke autenticado do `/mcp` **desarmado**, risco ACEITO até a identidade do TI; no lugar, `tools` no `/health?deep=1` e o `::warning::` em todo deploy |
| — | *negativas de grupo e listas compartilhadas na auditoria de negativas* (frente própria) |
| — | follow-ups Minor do **F193** (corpo do [#111](https://github.com/BadWolf1509/v4-ads-mcp/pull/111)) |
| — | **`export_csv_rows(manager_id=None)` exporta o audit de todos os gestores por default** — falha aberta latente (as duas rotas passam o gestor explícito); chip de 28/09 |
| — | **orçamento de período fixo** (`CUSTOM_PERIOD`) no `get_budget_pacing` — a tool não o trata (Fora do F202) |

**Fechados de 20 a 29/09:** **F154**, **F179**, **F181–F184**, **F188–F191**, **F193–F199**,
**F200**, **F201**; no código, **F202** e **F203** (deploy pendente). O
defeito de cada um está no [catálogo](findings-catalog.md); a narrativa desses dias, em
[`_archive/estado-atual-2026-09-20-a-26.md`](../_archive/estado-atual-2026-09-20-a-26.md) e
[`_archive/estado-atual-2026-09-27-a-28.md`](../_archive/estado-atual-2026-09-27-a-28.md). 🔑 A
lição que atravessa todos: **existia a regra e não existia o mecanismo**.
