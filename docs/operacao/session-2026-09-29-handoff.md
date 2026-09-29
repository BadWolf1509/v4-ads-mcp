# Sessão 2026-09-29 — Handoff (verificação da infra e guards, BM, F202, F203)

> Mapa da sessão. O defeito de cada finding está no [catálogo](findings-catalog.md); o estado
> vivo, no [`estado-atual`](estado-atual.md). Anterior:
> [`session-2026-09-28-noite-handoff.md`](session-2026-09-28-noite-handoff.md).

## O que entrou

| PR / branch | o quê | produção |
|---|---|---|
| #135 | F199, F200, F201 no catálogo | não deploya (docs) |
| #136 | F202, F203 no catálogo; o "30 s" do F200 corrigido | não deploya (docs) |
| `fix/pacing-orcamento-compartilhado` (`1082e61`) | **F202** | **commitado, sem push** |
| `fix/pool-timeout-no-teste` (`bc7e343`, `91c0c9f`) | **F203** (retirada e devolução) | **commitado, sem push** |

Os worktrees das duas branches estão em `D:/v4-ads-mcp-wt/pacing-compartilhado` e
`D:/v4-ads-mcp-wt/pool-timeout`. Nenhum deploy hoje: a janela de 24 h da verificação fecha em
30/09 00:10 UTC.

## O que foi medido

- **As 4 contas Meta das clientes que saíram** (Dr. Dérick Vinhas, Dra. Paula Minchillo, Imperial
  Alimentos, Panelas Veneza) foram tiradas do BM pelo Wellington em 28–29/09; conferido na Graph
  (`client_ad_accounts` + `owned_ad_accounts`): parceria com 21 contas, as 4 fora. O job de 29/09
  marcou a 1ª ausência das 4 (`to_bump`), como previsto; revogação dos 16 grants em 01/10.
- **Verificação parcial da infra e guards:** job `success`, zero reconexão, zero erro, zero 5xx;
  custo do `SELECT 1` = +7 ms no p50 do `/health?deep=1`. A linha de base de latência antiga
  estava errada (métrica do serviço); a certa é por rota, pelos logs de request.
- **F202:** na Mestre da Obra – João Pessoa, duas campanhas dividem o orçamento `15803241252` —
  a tool dizia 85% e 9% de R$ 9.300 cada; juntas, 94,6%. A GAQL aceita `metrics.cost_micros FROM
  campaign_budget` (R$ 8.795,07, a soma exata).
- **F203:** com um proxy TCP que para de repassar bytes, a retirada do pool ficava presa aos 75 s
  (a revisão dizia 30 s) e, com o socket mudo no meio do uso, a devolução aos 90 s — com
  `asyncio.timeout` em volta, quem chamou preso junto e a vaga do pool perdida.

## Método que valeu

- **Sonda com controle antes de consertar** — nos dois buracos do F203, a variante normal do
  mesmo proxy voltou em 0,0 s; sem ela, "presa" podia ser defeito da sonda (e foi, uma vez: o
  proxy da sonda não repassava EOF).
- **Guard que trava não é guard:** o `asyncio.timeout` dentro do teste não sai do asyncpg preso;
  o guard vigia de fora (tarefa separada + `asyncio.wait`) e o teardown tem prazo.
- **Latência se compara por rota e pela mesma requisição** — o percentil agregado do serviço
  mistura health e chamadas à API do Google.

## Pendente

- **Hoje à noite (depois de 00:10 UTC):** leitura das 24 h (`latencia_por_rota.py`) e PR de docs
  fechando o F200; depois, deploy do F203 e do F202, cada um com autorização nominal.
- **30/09:** 2ª ausência das 4 contas; **01/10:** revogação + smoke do dia 1; **04/10:** buckets e
  Fase 2B.
- **Do Wellington:** ajuste do `null` no plugin (agora com o pacing), Full Access Meta, identidade
  no TI (F186), F129, F67.

## Lições operacionais

- `git branch -r` não é o GitHub: o repo apaga a branch no merge (`delete_branch_on_merge`);
  estado remoto se mede com `git ls-remote --heads origin`.
- `gcloud` perdeu a credencial durante a noite — conferir antes de tarefa de infra; o login é no
  terminal do Wellington.
- Docker Desktop fechado sobe com o executável e o engine responde em ~15 s, mesmo com
  `com.docker.service` em `Stopped`.
