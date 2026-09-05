-- 008_google_reconciliation.sql
-- Reconciliação do lado Google contra o MCC (spec 2026-09-05).
--
-- missed_syncs dá ao Google a carência que o Meta ganhou na 005. Sem ela,
-- `mark_inactive_except` desativa na PRIMEIRA ausência, e amarrar revogação a
-- esse sinal revoga grant real na primeira leitura parcial (F93).
--
-- revoked_at/revoked_reason tornam a revogação SOFT: a linha do grant fica, o
-- gate nega, e a conta que volta ao MCC restaura com um clique. Antes era
-- DELETE — sem trilha e sem caminho de volta.
--
-- Sem backfill de propósito: missed_syncs = 0 é o estado correto de partida, e
-- revoked_at nulo é o que as 138 linhas existentes já são (medido 2026-09-05).

ALTER TABLE google_ads_accounts
    ADD COLUMN IF NOT EXISTS missed_syncs INTEGER NOT NULL DEFAULT 0;

ALTER TABLE manager_account_access
    ADD COLUMN IF NOT EXISTS revoked_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS revoked_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_mac_revoked
    ON manager_account_access (customer_id)
    WHERE revoked_at IS NOT NULL;
