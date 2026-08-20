-- 005_meta_missed_syncs.sql — F128.
-- Contador de execucoes COMPLETAS do resync em que a conta nao apareceu em
-- /me/adaccounts.
--
-- Por que nao bastava o que ja existia: a deteccao de churn do Meta e escopada
-- por business_id (F65) — agrupa o payload por BM e, para cada BM VISTO,
-- desativa o que faltou. Quando a parceria com o cliente cai, o system user
-- perde o acesso e o BM inteiro some do payload: sem BM nao ha keep-list, e a
-- conta fica is_active=true indefinidamente (confirmado em 2026-08-20 com
-- `Mestre da Obra Petrolina`, que respondia #200 no Graph e seguia ativa aqui).
--
-- Escopar por TEMPO em vez de por BM fecha esse ponto cego sem reabrir o
-- F65/F85 (desativar inventario vivo por leitura incompleta), porque so sync
-- completo incrementa e lista de vistas vazia e no-op.
--
-- DDL segura: coluna nova com default, sem reescrita de tabela no PG >= 11.

ALTER TABLE meta_ad_accounts
    ADD COLUMN IF NOT EXISTS missed_syncs INTEGER NOT NULL DEFAULT 0;
