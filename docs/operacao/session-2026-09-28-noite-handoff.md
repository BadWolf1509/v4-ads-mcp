# Sessão 2026-09-28 (tarde e noite) — Handoff (F199, erro de data, infra e guards)

> Continuação de [`session-2026-09-28-handoff.md`](session-2026-09-28-handoff.md), que cobre o
> F196, o F197, o F198, as dependências e a verificação das 09:00. Este é o **mapa**; a
> enciclopédia é o [`findings-catalog.md`](findings-catalog.md), e o estado vivo é o
> [`estado-atual.md`](estado-atual.md).

## TL;DR

| PR | O quê | Em produção |
|---|---|---|
| #130 | docs: compact de 28/09 (estado-atual enxuto) | sem deploy (só docs) |
| #131 | **F199** — `get_budget_pacing` projeta pelos dias FECHADOS (janela do `THIS_MONTH` de `janelas.py`); gasto de hoje em `gasto_hoje_brl`; dia 1 sem projeção (`null`); `period` e `inclui_dia_corrente` na resposta | `00137-qsd` |
| #132 | data inválida numa tool Google chega ao LLM com a mensagem (PT-BR), não "Erro interno" — o `_error_envelope` trata o `InvalidDateRangeError` | `00138-8j8` |
| #133 | **infra e guards** — conexão testada na retirada do pool; revoke idempotente; desempate por `id`; pagers `limit >= 1`; dry-run pelo relógio do banco; quota no mesmo dia UTC; lock nas migrations; teto do CSV | **`00139-fpf`** |

**Catálogo:** F199 e a frente infra e guards (F200) **ainda não estão no catálogo** — o
`/findings-add` só o Wellington roda. Os textos prontos estão em `.superpowers/findings-pendentes/`
(git-ignored, no checkout principal).

## O que foi medido

- **O pacing contava hoje, parcial, como dia inteiro** (Mestre da Obra – João Pessoa, 28/09): −3,6%
  antes do primeiro gasto do dia 28; na manhã do dia 1, R$ 600 contra ~R$ 9.271 (~−94%). Decisão do
  Wellington: dias fechados (contra "manter e avisar" e "ratear pela hora" — o gasto não é uniforme:
  84% de um dia típico em 56% das horas). Smoke em produção: janela 01–27/09, R$ 7.566,82 = a GAQL,
  projeção R$ 8.407,58.
- **"Erro interno" em data inválida** era reproduzível de ponta a ponta (a tool real,
  `start_date` depois de `end_date`); só 2 das ~23 chamadas de `resolve_date_window` capturavam.
  Smoke em produção: a mensagem PT-BR chega.
- **A conexão ociosa derrubada** (F76) reproduzida com asyncpg real: um proxy TCP no processo corta
  a conexão na próxima escrita — o pool cru entrega o erro ao chamador; o `PoolValidado` reconecta
  com 1 e com 2 mortas abrindo **uma** conexão nova (a fila do asyncpg é LIFO).
- **Migrations concorrentes** colidiam já no bootstrap (`pg_type_typname_nsp_index` do
  `CREATE TABLE IF NOT EXISTS _migrations`). O DSN está no Supavisor **modo sessão** (porta 5432);
  a variante `pg_advisory_xact_lock` foi escolhida por funcionar nos dois modos.
- **`audit_log`:** 5.795 linhas em 365 dias (3,2 MB) — o teto de 50.000 do CSV não corta nada hoje.
- **O token de dry-run** era gravado com o `now()` do banco e conferido com o relógio da app;
  com a app atrasada, aceitava token vencido.
- **Linha de base do §6** (antes do deploy do #133): p50 16,9 ms, p95 708 ms (serviço inteiro, 24 h);
  2 `db_dropped_connection_retry` em 7 dias. Script e roteiro em `.superpowers/verificacao-2026-09-29/`.
- **Deploy do #133:** o job de migration rodou com o lock (`migrations_no_pending`, `exit(0)`);
  smoke de leitura em `get_my_rate_limit_status`, `meta_list_my_ad_accounts` e `list_my_accounts`.

## Como a frente infra e guards foi feita

Método dos planos (memória `planos-precisam-rodar`), 3ª vez: código executado antes do plano, uma
task por commit (full sweep verde em cada uma), plano gerado dos commits e reaplicado do próprio
arquivo com árvore idêntica. O Wellington escolheu **aplicar os commits validados + revisões** em vez
de re-implementar por subagente. Revisões: 7 por task (Sonnet, em paralelo) e a da branch (Opus). A
rodada de correção fechou os Important — guards mais estreitos que a invariante (formas com `+`,
f-string, CTE, alias, `connection._pool` cru, o retorno do `init_pool`), a premissa do asyncpg
testada só por fake, o `nucleo.md` contradizendo o código — e os Minors; uma re-revisão confirmou
12 de 14, com dois Minors estacionados com motivo no ledger (`.superpowers/sdd/2026-09-28-infra-e-guards/`).

## O que ficou pendente

- **29/09 (depois das 00:10 UTC de 30/09 para 24 h cheias):** verificação do §6 — latência contra a
  base, eventos de reconexão, primeiro acesso da manhã, o job das 09:00 UTC com o pool novo. Roteiro
  em `.superpowers/verificacao-2026-09-29/LEIA.md`. Depois, trocar o "fechado no código" dos
  sub-projetos 3 e 4 por fechado.
- **01/10:** smoke do F196 e do F199 (dia 1: `THIS_MONTH` devolve o dia; pacing com projeção `null`).
- **Do Wellington:** `/findings-add` do F199 e do F200; as três recomendações da revisão final que
  mudam produção (timeout curto no ping; invalidar o pool na primeira queda; repetir em qualquer
  erro do ping); os chips "orçamento compartilhado no pacing" e "default aberto do
  `export_csv_rows`".

## Operacional que custou tempo

- **`capture_logs` do structlog vem vazio na suíte inteira** (outro teste deixa o logger em cache):
  o teste do proxy passou isolado e falhou no full sweep; a prova virou contagem de conexões no proxy.
- **Barra invertida dupla em `python - <<'EOF'` chega simples** — script com regex vai por arquivo.
- **O guard `test_nenhuma_regra_se_perdeu`** pegou a reescrita do `nucleo.md` apagando a âncora
  `pool.acquire()` da regra #13 — a regra voltou dentro do texto novo, sem baixar o piso.
- **Remover um worktree apaga o `.superpowers/` git-ignored dele** — o ledger e as revisões foram
  copiados para o checkout principal antes.
