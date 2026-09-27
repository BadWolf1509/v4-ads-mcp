# Sessão 2026-09-27 — Handoff (F194 em produção, F195, o alerta Meta, F154)

> Um dia, quatro PRs mergeados (#116–#119, três com deploy), um alerta criado no GCP e a frente
> **F154** executada por subagentes na branch `spec/f154-alcance` (seção abaixo). Este é o **mapa**; a
> enciclopédia é o [`findings-catalog.md`](findings-catalog.md), e o estado vivo é o
> [`estado-atual.md`](estado-atual.md). O dia anterior está em
> [`session-2026-09-25-26-handoff.md`](session-2026-09-25-26-handoff.md).

## TL;DR

| PR / ação | O quê | Em produção |
|---|---|---|
| #116 | **F194** — métricas Meta dizem o que mediram: contrato único, construtor único, BUC que não grava "não sei" como 0 | sim — `00129-vf9`; smoke de leitura em 27/09 pela sessão-par (#117) |
| #117 | docs do smoke do F194 (sessão "V4 ads MCP"); o smoke abriu o **F195** | só docs |
| #118 | **F195** — `LAST_N_DAYS` Meta até ontem, pela regra única `src/janelas.py` (o Google e a Meta delegam); o overview ecoa `previous_date_range` e `inclui_dia_corrente` | sim — run `36332640719`; smoke em 27/09 |
| #119 | descriptions Meta nomeiam as chaves reais da resposta, derivadas do contrato; a sonda de combinações falha sem o 400 do controle; docs do alerta; o `THIS_MONTH` registrado | sim — `00131-cjv`, run `36333559354` |
| GCP | métrica por log `meta_avisos_de_quota` + policy `3565996587605688856` (autorização nominal) | criadas; o projeto tem 5 policies |

## O que foi medido

- **O `date_preset` da própria Meta termina ontem:** `last_7d` → `20/09–26/09` em 27/09 (fuso da
  conta). Foi o dado que decidiu o F195 — as tools Meta discordavam da plataforma que leem.
- **As combinações de parâmetros do F194, juntas:** 16 de 16 com `200`, e o controle (atribuição
  inválida na mais carregada) `400` (`scripts/probe_meta_combinacoes.py`).
- **F154:** `/me/adaccounts` com 24 das 25 contas ativas; a CHUTE 07 fora do índice e lida pelo
  system user (`200`); recusa de verdade = `403` com `code 200`; token inválido = `401` com
  `code 190`. O confundidor de 05/09 caiu.
- **`THIS_MONTH` do Google no dia 1 do mês devolve janela invertida** (em 01/10: `01/10–30/09`),
  achado ao mover o código no F195; aceito por 15 tools Google. Sugerido como sessão separada.

## A frente F154 — o alcance medido pela leitura

Spec (`b038ba2`) → plano (`6158397`) → execução por subagentes, em segundo plano. O plano foi
**gerado de commits executados** num rascunho e **reaplicado do próprio arquivo sem diferença**;
os "ver falhar" foram medidos por script, e o patch de cada task saiu **idêntico ao do rascunho**:
T1 a sonda (`99a6736`), T2 o plano (`eb908c5`), T3 o `set_reachable` (`14bdddb`), T4 o job
(`e02a986`), T5 os docs (`383de21`), cada uma com revisão limpa; full sweep 7/7.

**A revisão final (Opus) achou o que as cinco revisões por task não viam, porque mora entre as
tasks:** nenhum teste cobria `false → true` — o caminho que conserta a CHUTE 07 em produção; a
sabotagem que só grava `false` passava em tudo — e o laço da sonda não tinha prazo total: rodava
em série, com a conexão do job adquirida e ociosa, num job de 600 s. A rodada final pôs prazo
total de 60 s e até 5 sondas em paralelo (conta fora do prazo sai não medida), o guard do
`false → true` e a sonda na lista do guard do relógio.

**Depois do merge:** a verificação da spec §6 está no [`estado-atual`](estado-atual.md), na
execução diária seguinte ao deploy.

## O que ficou pendente

- **28/09:** conferir a reconciliação Google — a Alumínios Veneza com `removed=1`,
  `revoked_grants=4`.
- ~~**01/10:** o `THIS_MONTH` invertido~~ — fechado no mesmo dia como **F196**: a GAQL responde a
  janela invertida com 0 linhas, sem erro; no dia 1 a janela passou a ser só hoje.
- **04/10:** remedição dos buckets e do uso da Fase 2B por gestor.
- **Do Wellington:** remover do BM as 4 contas Meta das clientes que saíram; o ajuste do `null`
  no plugin Google; o pedido de Full Access da API Meta; F129; F67; a identidade de serviço (F186).

## Operacional que custou tempo

- **O falso gate reincidiu** num commit de rascunho (`;` no lugar de `&&`), com a regra escrita na
  memória — o plano do F154 passou a mandar o `&&` literal.
- **O `gcloud` pede reautenticação que só termina no terminal do Wellington**; "logado" chegou com
  o login parado no prompt de senha. Confira o horário do `credentials.db` antes de repetir.
- **Duas sessões no mesmo checkout:** o worktree vai para fora do repo (`D:/v4-ads-mcp-wt/`) — o
  `.worktrees/` não está no `.gitignore`.
- **Subagente em segundo plano, sempre**, e o modelo dito pelo transcript, não pelo trailer.
