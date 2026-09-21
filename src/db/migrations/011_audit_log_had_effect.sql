-- 011_audit_log_had_effect.sql — F179.
-- `admin_invites_cancel` descartava o retorno de `delete_invite` (que e `bool`
-- e existe exatamente para isto) e chamava `_audit_admin` INCONDICIONALMENTE.
-- Convidado que loga entre o SELECT e o DELETE vira `status='active'`, o DELETE
-- nao afeta linha nenhuma, e o audit afirma que um admin cancelou um convite
-- que virou conta ativa.
--
-- A transacao do F174 tornou o par escrita+audit ATOMICO, nao VERDADEIRO: os
-- dois commitam juntos mesmo quando a escrita nao teve efeito.
--
-- Coluna NOVA e NULLABLE, moldada na 007 (F148, `dry_run`): NULL nao afirma
-- nada sobre as linhas anteriores ao fix. NAO virou valor novo em `status`
-- (success|error|denied) porque aquele enum e filtro publico de
-- `get_my_audit_log` e mexer nele quebraria consumidor — mesma razao escrita
-- na 007.
--
-- Safe DDL: ADD COLUMN nullable sem default nao reescreve a tabela.

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS had_effect boolean;

COMMENT ON COLUMN audit_log.had_effect IS
  'true = a escrita afetou linha; false = passou sem efeito; NULL = nao medido ou anterior ao fix (F179).';
