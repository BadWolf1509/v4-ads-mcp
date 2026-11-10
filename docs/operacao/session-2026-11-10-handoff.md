# Sessão de 10/11 — Handoff (deps e varredura de refatoração de 10/11)

> Plano: [`2026-11-10-varredura-refatoracao.md`](../superpowers/plans/2026-11-10-varredura-refatoracao.md).
> Ledger da execução (fonte de verdade do progresso, git-ignored):
> `D:/v4-ads-mcp/.superpowers/sdd/2026-11-10-varredura-refatoracao/progress.md`.
> Anterior: [`session-2026-11-04-handoff.md`](session-2026-11-04-handoff.md).

## O que entrou em produção

| PR | o quê | revisão que subiu |
|---|---|---|
| #227 | 5 bumps do Dependabot juntos (grpcio 1.85.1, sse-starlette 3.6.0, tzdata 2026.6, starlette 1.10.0, protobuf 7.36.2) | `00188-qbr` |
| #223 | sse-starlette 3.7.0 (rebase do Dependabot; `/mcp` responde JSON, não SSE) | `00189-c2x` |
| #228 | **Parte A**, os 6 bugs da varredura (detalhe abaixo) | `00190-2zl` |
| #229 | **Parte B**, guards (só testes) e emenda do plano em F4 e G1 | `00191-684` |
| #230 | **Parte C**, Google de baixo risco | `00192-glq` |
| #231 | **Parte D**, tools MCP | `00193-9rf` |

Cada deploy foi verificado com `gh run view` (passos), revisão servindo (`gcloud`), `/health?deep=1` e leitura
real pelo MCP. **Atenção:** a linha `SERVING_REVISION` do log do deploy é a revisão de **antes** (a
referência do rollback), não a nova — medido nesta sessão.

**Parte A, os bugs:** audit agrupava "Hoje"/"Ontem" pelo dia em UTC (B1); toggles de gestor invertiam o
estado e auditavam gestor inexistente (B2/B3: agora `?desejado=` e 404); `bootstrap-admin` não reativava e o
CLI não gravava audit (B4); `reconcile_meta` sem configuração saía sem linha de execução (B5);
`fetch_paginated` caía com corpo 200 que não é objeto (B6: agora leitura incompleta, que não revoga). O
"não mudou nada" passou para a coluna `had_effect` (F179), e os toggles gravam linha com `had_effect=false`
— desvio declarado do plano, que dizia "sem audit".

## Como retomar (Partes E a I)

- **Aval do Wellington** (10/11, por menu, gravado no ledger): mergear cada parte com CI verde e revisão
  final limpa, verificando o deploy antes da próxima; **pular a Parte J** (depende do F207); nenhum
  clique que escreva em produção; decisões pendentes do plano ficam como estão.
- **Próximo:** Parte E, task E1. Worktree pronto em `D:/v4-ads-mcp-wt/meta-10-11` (branch
  `refactor/meta-varredura-10-11`, base `ba13ebf`), com os briefs em `.superpowers/sdd/…/task-E*-brief.md`.
  Copie o ledger mais novo para lá antes de despachar.
- **Método que funcionou:** implementador e revisor por task (no mínimo o modelo intermediário), revisão
  final da branch no mais capaz, full sweep antes do PR, uma onda de correção por parte.
- Worktrees das partes já mescladas (`bugs-10-11`, `guards-10-11`, `google-10-11`, `tools-10-11`) podem
  sair depois de copiar o `.superpowers/` deles; o `progress.md` do checkout principal já tem tudo.

## Pendências que dependem do Wellington

- **Clique em produção** nos toggles de gestor (A2), num gestor de teste: o aviso "O gestor já estava
  assim." sai junto com o `HX-Redirect` e pode piscar rápido.
- **Dry-run com o gestor presente** das tools de status (`update_*_status`, `bulk_pause_by_query`, builders
  refeitos na C1) e das 3 que passaram para o `emitir_preview` na D3 (`create_and_link_assets`,
  `import_offline_conversions`, `upload_customer_match_list`).
- **As 8 decisões pendentes foram tomadas em 10/11** (todas pela recomendação) e viraram tasks do plano:
  E3 Step 2, E6, E7, E8, G0, G5 e K1 — tabela na seção "Decisões do Wellington" do plano. Só a C2 (K1)
  volta a ele, com o levantamento dos 3 tipos de recomendação do v25.
- **`SMOKE_MCP_BEARER` expirado:** o check de handshake do smoke do deploy não roda (F186).
- **Starlette 1.10** avisa que `httpx` no `TestClient` está deprecated (`httpx2`); nada quebra hoje.
- **Parte J e F207** numa sessão com ele, começando pelos logs de produção do resync.

## Achados desta sessão para o catálogo (`/findings-add`, que é dele)

- Os 6 bugs da Parte A (corrigidos no #228).
- `SERVING_REVISION` do log do deploy é a revisão anterior — armadilha de verificação.
- Os 4 guards da Parte B nasceram mais estreitos que a invariante (registro binário, allowlist sem
  contagem, regex de literal, stub de enum único); todos fechados por revisão antes do merge.
- `classify` sem as duas operações acima.

## Não medido

- Clique no painel e dry-run de mutação em produção (acima).
- Logs da execução agendada dos jobs depois da Parte A (o `reconcile_meta` sem configuração não acontece
  em produção, onde token e BM existem).
- Tokens dos buckets de tools (sem remedição desde 05/10).
