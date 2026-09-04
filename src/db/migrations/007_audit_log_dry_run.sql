-- 007_audit_log_dry_run.sql — F148.
-- O dry-run de todo mutate always-CONFIRM era invisivel na trilha: as 24 tools que
-- chamam create_pending nao gravavam linha propria, e o proprio create_pending
-- tambem nao. Pior, o ensure_account_access que ele chama com level="write" audita
-- SO QUANDO NEGA — a trilha guardava os previews recusados e perdia os que
-- funcionavam.
--
-- Coluna NOVA e NULLABLE de proposito. Nao virou valor novo em action_type porque
-- aquele enum e filtro publico de get_my_audit_log (mutate|read|auth|system) e
-- mexer nele quebraria consumidor.
--
-- NULL = linha anterior a este fix, ou caminho que nao passa por preview.
-- Safe DDL: ADD COLUMN nullable sem default nao reescreve a tabela.

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS dry_run boolean;

COMMENT ON COLUMN audit_log.dry_run IS
  'true = preview que mintou token sem aplicar (F148). NULL = anterior ao fix ou nao-preview.';
