# Sessão 2026-09-27 (noite) e 28/09 — Handoff (F196, F197, F198, dependências, a verificação)

> Continuação de [`session-2026-09-27-handoff.md`](session-2026-09-27-handoff.md), que cobre o
> F194, o F195 e o F154. Este é o **mapa**; a enciclopédia é o
> [`findings-catalog.md`](findings-catalog.md), e o estado vivo é o [`estado-atual.md`](estado-atual.md).

## TL;DR

| PR / ação | O quê | Em produção |
|---|---|---|
| #121 | **F196** — `THIS_MONTH` no dia 1 = só hoje; janela invertida falha na fonte; o custom Meta recusa início depois do fim | sim — `00133-sqf` |
| #122 | **F197** — só o job escreve o inventário: saem o botão "Sincronizar contas", o "Atualizar lista" e a gravação no callback do OAuth; guard do escritor único derivado do SQL | sim — `00134-rps`; a rota antiga responde `404` |
| #128 | lote de dependências (google-crc32c, google-ads, watchfiles, pydantic + core) e **F198** — o lockfile passa a ser fechado (`scripts/check_lockfile_fechado.py`, no CI e no full sweep) | sim — `00135-lf4` |
| #124 | `mcp` 1.28.1 → 1.30.0, sozinho | sim — `v4-ads-mcp-00136-lxv` |
| repo | 63 branches apagadas (29 locais + 34 remotas, todas na `main`) e `delete_branch_on_merge` ligado | — |

## O que foi medido

- **A GAQL responde `BETWEEN` invertido com 0 linhas e sem erro** (controle de um dia na mesma conta:
  R$ 180,08). E o `DURING THIS_MONTH` do Google inclui hoje; as 15 tools terminam ontem — a
  diferença é o dia corrente, registrada no F196 como decisão pendente.
- **O botão "Sincronizar contas" foi usado 3× em 21/09**; o callback do OAuth pessoal, 0 vezes em 30
  dias. Os dois gravavam o inventário com `is_active = true` e a série de ausências zerada.
- **O `opentelemetry-api` era instalado por resolução desde 20/09** (o CI do merge do #122 baixou o
  1.45.0): o lote #89 subiu o `google-api-core` aplicando só a linha do Dependabot.
- **`mcp` 1.30.0 contra o nosso `/mcp`:** a expiração de sessão ociosa e o limite de 4 MiB moram no
  `StreamableHTTPSessionManager`, que não usamos (um transporte sem estado por request); nenhuma
  tool declara `outputSchema`. Lockfile fechado com ele (medido antes do merge).
- **A execução diária de 28/09 (09:00:03 → 09:00:39, imagem `e9e728c`): 18 de 18 conferidos.** CHUTE
  07 com `su_reachable = true`; `meta_reconcile` com `unreachable: 0`, `alcance_nao_medido: 0`,
  completo e aplicado; fila "Sem o SU" vazia; 25 contas Meta ativas; a etapa Meta inteira em ~8 s.
  Google: a Alumínios Veneza saiu na 3ª ausência (`removed=1`, `revoked_grants=4`), zero grant vivo em
  conta inativa. Nenhum aviso no log do job.

## O que ficou pendente

- **01/10:** smoke de leitura do F196 — `THIS_MONTH` numa conta real devolve o dia 1, não vazio.
- **04/10:** remedição dos buckets e do uso da Fase 2B por gestor.
- **Do Wellington:** remover do BM as 4 contas Meta das clientes que saíram — seguro agora (o F197
  tirou o botão que reiniciava a carência); o ajuste do `null` no plugin Google; o Full Access da API
  Meta; F129; F67; a identidade de serviço (F186). E a decisão das duas definições de `THIS_MONTH`.

## Operacional que custou tempo

- **O `gcloud` pediu reautenticação de novo** de uma noite para a manhã; o horário do
  `credentials.db` confirmou o login antes de seguir.
- **O Dependabot fecha sozinho os PRs cobertos** por um lote mesclado — fechar à mão antes do merge
  tiraria a fila se o lote fosse revertido.
