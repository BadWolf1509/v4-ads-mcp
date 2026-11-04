# Sessão de 03 e 04/11 — Handoff (varredura de refatoração em produção)

> Mapa da sessão. Estado vivo no [`estado-atual`](estado-atual.md); defeitos no
> [catálogo](findings-catalog.md). Anterior: [`session-2026-10-31-handoff.md`](session-2026-10-31-handoff.md).
> Plano: [`2026-11-03-varredura-refatoracao.md`](../superpowers/plans/2026-11-03-varredura-refatoracao.md).

## O que entrou

| PR | o quê | prova |
|---|---|---|
| #196 a #200 | Dependabot, um merge por vez | deploy `success` e health a cada um |
| #210 | parte A: os 3 bugs da varredura | entrada inválida com texto acionável |
| #211 | parte B: reserva de cota única | dry-run de orçamento, audit `dry_run: true`, request-id do `run_report` gravado |
| #212 | pre-check `docker info` com teto de 15 s (era 2 s; medido 2,5 a 3,4 s) | guard vermelho com 2, verde com 15 |
| #213 | parte C: limpezas Google, pré-flights em `google_ads/preflight.py` | deploy e health |
| #214 | parte D: leitura de coleção Meta unificada | leitura Meta real |
| #215 | parte E: OAuth pessoal da Meta removido | rotas 404, callback de exclusão 400 |
| #216 | parte F: painel | clique logado em produção (8 páginas, CSV, 422, filtro) |
| #217 | parte G: tools MCP | dry-run de orçamento e de `bulk_pause_by_query` |
| #218 | parte H: jobs e testes | dry-run e cota com a chave nova |
| #219 | teste instável do CSP | guard de POST lento: antigo 3/3 vermelho, novo 5/5 verde |

Todos os dry-runs foram na conta interna, só preview: nenhum `apply_change`.

**Não medido:** revisão servindo desde 03/11 (`gcloud` sem credencial); logs da execução agendada dos
jobs depois da H; caminho `denied` da A; paginação Meta da D. O deploy do #217 aconteceu durante um
incidente do GitHub Actions: os passos do job terminaram em `success` às 15:53 UTC, mas o job ficou
`in_progress` por ~25 min na API — a conclusão veio dos passos, não do status do job.

## Achados da sessão (para o `/findings-add`)

- **`wait_for_function` com string sob CSP sem `unsafe-eval` (corrigido no #219).** O Playwright
  1.64 reavalia a expressão com `globalThis.eval` a cada frame (`waitForFunctionExpression`); só o
  primeiro poll, dentro da chamada CDP, passa pelo CSP. O teste passava quando a recarga começava antes
  do segundo poll, ou seja, quando o POST era rápido. A primeira hipótese (recarga lenta) estava errada:
  atrasar a recarga não reproduzia, porque o Chrome para o rAF do documento que sai. Lição: **a forma
  função é avaliada uma vez; a string, a cada frame** — sob CSP estrito, espera por string é corrida.
- **`export_csv_rows(manager_id=None)` como default** era falha aberta latente: corrigido na branch
  `fix/export-audit-escopo-explicito` (argumento obrigatório), aguardando merge.
- Os 3 bugs da parte A e os 4 bugs pré-existentes dos jobs (achados na H1) estão descritos no plano e
  no [`estado-atual`](estado-atual.md).

## Pendente (nesta ordem)

1. **`gcloud auth login`** (Wellington): medir a revisão servindo e ler os logs dos jobs das 06:00 de 05/11.
2. **`/findings-add`** (Wellington): os achados acima.
3. **Os 4 bugs dos jobs**: um TDD por bug, um PR, depois dos logs de 05/11.
4. **C2**: whitelist dos 3 tipos de recomendação do v25 (decisão do Wellington).
5. Limpeza do worktree `meta-onda-1` (branch já mergeada) e das branches locais mergeadas.
6. Escrita em produção, cada uma com aval próprio: apagar `meta_oauth_connections`; teste real de convite.
