# Sessão 2026-09-27 — Handoff (F194 em produção, F195, o alerta Meta, F154 em execução)

> Um dia, quatro PRs mergeados (#116–#119, três com deploy), um alerta criado no GCP e a frente
> **F154** em execução na branch `spec/f154-alcance` (seção abaixo). Este é o **mapa**; a
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

## A frente F154 — em execução (branch `spec/f154-alcance`, sem push)

Spec (`b038ba2`) → plano (`6158397`) → execução por subagentes, em segundo plano. O plano foi
**gerado de commits executados** num rascunho e **reaplicado do próprio arquivo sem diferença**;
os "ver falhar" foram medidos por script. **T1** `99a6736` (review limpo) e **T2** `eb908c5`
(idêntica ao rascunho; **review pendente**).

**Para retomar:** o ledger está em
`D:/v4-ads-mcp-wt/f154/.superpowers/sdd/2026-09-27-f154-alcance-pela-leitura/progress.md`
(git-ignored), com o estado, os modelos medidos e os próximos passos: review da T2 → T3 e T4
(Sonnet) → T5 (Haiku) → revisão final (Opus) → full sweep → PR **com autorização nominal** (o merge
muda o que o job grava) → verificação pós-deploy (spec §6). Dois worktrees fora do repo:
`D:/v4-ads-mcp-wt/f154` (o trabalho) e `D:/v4-ads-mcp-wt/f154-proto` (o rascunho que o conferidor
compara). As ferramentas do método estão em `.superpowers/ferramentas-plano/` do repo principal.

## O que ficou pendente

- **28/09:** conferir a reconciliação Google — a Alumínios Veneza com `removed=1`,
  `revoked_grants=4`.
- **01/10:** o `THIS_MONTH` invertido dispara — a sessão sugerida mede o que a GAQL faz e propõe o
  conserto.
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
