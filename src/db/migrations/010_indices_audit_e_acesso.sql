-- 010: dois indices que faltavam, ambos para consultas que o painel ja faz.
--
-- 1. audit_log(occurred_at DESC, id DESC)
--    Existem tres indices compostos com occurred_at na SEGUNDA posicao
--    (manager_id, customer_id, platform). Nenhum serve a listagem geral do
--    audit, que ordena por occurred_at DESC, id DESC sem filtrar por nenhuma
--    das tres — o planner cai em scan + sort da tabela inteira. audit_log so
--    cresce. O desempate por `id` casa o `ORDER BY` das quatro listagens
--    (audit_log.py + routes.py, desde 45c95b8) — sem ele o indice nao cobre a
--    ordenacao de verdade e o planner ainda precisa de um sort extra pelas
--    linhas que empatam em occurred_at.
--
-- 2. manager_account_access(customer_id)
--    A PK e (manager_id, customer_id): busca por gestor usa a coluna lider,
--    busca por conta varre. "Quem tem acesso a esta conta?" e pergunta do
--    painel de admin e da revogacao — as duas varrem hoje.
--
-- IF NOT EXISTS nos dois: a convencao do repo e append-only, e migration que
-- falha por objeto ja existente trava o Job de migration inteiro no deploy.

CREATE INDEX IF NOT EXISTS idx_audit_occurred_at
    ON audit_log (occurred_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_mac_customer
    ON manager_account_access (customer_id);
