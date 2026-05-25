-- 004_audit_log_provider_id.sql — Sprint M.2a Task 2.
-- Rename google_request_id → provider_request_id for multi-platform clarity.
-- Safe DDL: column rename é atomic, read-side only (não impacta writes em flight).

ALTER TABLE audit_log RENAME COLUMN google_request_id TO provider_request_id;
