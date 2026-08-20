-- 006_meta_partnership_reconciliation.sql
-- Reconciliação contra a lista autoritativa da parceria (spec 2026-08-20).
--
-- su_reachable separa duas condições que hoje colapsam em "sumiu": conta que
-- saiu da parceria (deve sair do MCP) e conta que está na parceria mas cujo
-- system user não foi atribuído (ação humana no Business Manager, NUNCA
-- desativar). Medido em 2026-08-20: 25 na parceria, 23 alcançáveis.
--
-- revoked_at/revoked_reason tornam a revogação SOFT: a linha do grant fica, o
-- gate nega, e a parceria que volta restaura com um clique. Antes era DELETE.

ALTER TABLE meta_ad_accounts
    ADD COLUMN IF NOT EXISTS su_reachable BOOLEAN NOT NULL DEFAULT true;

ALTER TABLE manager_meta_account_access
    ADD COLUMN IF NOT EXISTS revoked_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS revoked_reason TEXT;
