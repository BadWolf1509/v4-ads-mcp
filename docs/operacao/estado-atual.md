# Estado atual — V4 Ads MCP

> **Volátil por natureza** — o `CLAUDE.md` mantém um resumo de poucas linhas e aponta para cá.
> **Ao terminar uma sessão, atualize ESTE arquivo** e mantenha-o curto: em 20/09 ele tinha
> **91 KB**, 83 deles narrando frente já concluída e contradizendo a própria tabela. **Trabalho
> que fechou sai daqui:** o defeito vai para o catálogo, a narrativa para o arquivo
> ([`_archive/`](../_archive/varredura-2026-09-06-frentes.md)), e aqui fica uma linha.

> **Última sessão:** [`session-2026-10-06-handoff.md`](session-2026-10-06-handoff.md) — 03/10–06/10:
> remedição de 30 dias (buckets 22 → 13 always; Fase 2B parada), deps e a frente **negativas com
> acento e cobertura + `run_gaql` compacto** (no ar desde 05/10, #154). Antes:
> [`session-2026-10-02-handoff.md`](session-2026-10-02-handoff.md) (conversões por ação e parcela).

> Sem frente em curso. Pendências pequenas da última frente estão no handoff de 06/10.

---

## Produção — medido em 2026-10-06

| | |
|---|---|
| Revisão servindo | **`v4-ads-mcp-00146-qv5`**, 100% do tráfego (05/10) — o **#154** (negativas com acento e cobertura, `run_gaql` compacto), sobre o **#152** (`00145`, 5 bumps de patch do Dependabot), sobre o **#151** (`00144`, buckets de 05/10) e o **#143** (`00143`, conversões por ação e parcela de impressão), sobre o **#141** (`00142`, o teste do `detect_drift` com relógio congelado). ⚠️ O smoke do pipeline segue sem handshake MCP **autenticado** (F186) |
| Tools | **68** (62 Google + 6 Meta) |
| Buckets | **13 always + 55 defer** (05/10, 9 desceram sem uso de gestor) — [remedição](tool-buckets-2026-10-05.md); próxima com a Fase 2B, ~15/10 |
| Catálogo | até **F203** (~6.000 linhas, 601 KB) |

**Infra e guards verificada em produção (F200, 24 h até 30/09 00:08 UTC):** zero reconexão, zero
`severity>=ERROR`, zero 5xx em ~2.500 requests (o filtro acha os 2 eventos da base); job de 29/09
`success`. **Custo do `SELECT 1` na retirada: +8 ms no p50** do `/health?deep=1` (16,0 → 24,1 ms;
p95 80,2 → 95,1) — o A/B limpo. Latência se mede **por rota, pelos logs de request**
(`latencia_por_rota.py`); a métrica do serviço agrega percentil entre séries e não compara. Scripts
em `.superpowers/verificacao-2026-09-29/` (`latencia_por_rota.py`, `contas_no_bm.py`).

**Conferido em 30/09–01/10:** as 4 contas Meta que saíram do BM foram **desativadas no job de 01/10,
com os 16 grants revogados** (ausências em 29 e 30/09; zero grant vivo). **Smoke do dia 1** (Mestre da
Obra – João Pessoa, 01/10 22h): `THIS_MONTH` devolve `01/10–01/10` com dados (F196); pacing com
`inclui_dia_corrente: true` e projeção `null` (F199), também no bloco do orçamento compartilhado
(F202, R$ 299,42 = a soma das duas campanhas). **1ª queda real pega pelo pool validado:** 30/09
02:22 UTC, `db_conexao_testada_reconectou` (`connection was closed in the middle of operation`) e o
`/health?deep=1` daquele instante devolveu 200 em 90 ms (F200).

**Com data:** **~15/10** — remedir a Fase 2B por gestor com o plugin 0.5.0 (aplicado em 05/10) em uso.

**Uso real, 30 dias até 30/09** (`audit_log`): 1.896 chamadas, 4 gestores (uso de verdade: Wellington
e `pedro.vytor`). O **`run_gaql` é 38%** (725) — 259 do Pedro em rajadas de ~38 por sessão, roteiro
que o skill `analise-performance-google-ads` do plugin prescreve em GAQL cru: **conversões por ação
de conversão** (94 consultas), totais da conta em janela longa e **parcela de impressão**. As duas
viraram recorte curado no **#143**: `get_performance_breakdown(breakdown='conversion_action')`
(conta e campanha; flags do cadastro `null` com `flags_motivo` quando não medidas) e a parcela nas
linhas de `level='campaign'` sem breakdown e no `get_account_overview`. **Smoke de 03/10** (Mestre
da Obra, setembro): conta e campanha somam igual; "Conversation started" `null` com motivo;
parcela bit a bit com o `run_gaql` (campanhas, conta e período anterior); `audit_log` com uma linha
por chamada. **Não medido:** campanha com meta própria — as duas ativas da MO-JP usam as metas da
conta (`goal_config_level: CUSTOMER`); a description diz "indica", não afirma. A nota do plugin
sobre a ação secundária estava **errada** — a correção está no texto do plugin 0.5.0.

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
escolhendo pelo nome. **Remedido em 05/10:** `get_campaign_performance` 120 (Pedro 96, Anderson 24) e
`get_keyword_performance` 70 contra **1** do breakdown — nada mudou; espera o plugin 0.5.0
([detalhe](tool-buckets-2026-10-05.md)).

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

1. **Conversões por ação e parcela de impressão curadas** — implementada, em revisão (ledger acima).
2. **Plugin na fonte** (com o Wellington): ajuste do `null` e troca do GAQL cru do skill pelas tools
   curadas — destrava também a Fase 2B.
3. **Fase 2B** — em 04/10, o uso por gestor, junto dos buckets.
4. **`recommendation_subscription`** — spec da tool de leitura.
5. **F187** — o remédio do resumo × detalhe.

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
**F200–F203**. O
defeito de cada um está no [catálogo](findings-catalog.md); a narrativa desses dias, em
[`_archive/estado-atual-2026-09-20-a-26.md`](../_archive/estado-atual-2026-09-20-a-26.md) e
[`_archive/estado-atual-2026-09-27-a-28.md`](../_archive/estado-atual-2026-09-27-a-28.md). 🔑 A
lição que atravessa todos: **existia a regra e não existia o mecanismo**.
