-- 002_managers_status.sql
-- Adds invite-only allowlist support per FE Redesign v2 Phase 2 (Q8).

ALTER TABLE managers
  ADD COLUMN status text NOT NULL DEFAULT 'active'
    CHECK (status IN ('invited', 'active', 'inactive'));

ALTER TABLE managers
  ADD COLUMN invited_by uuid REFERENCES managers(id),
  ADD COLUMN invited_at timestamptz;

CREATE INDEX idx_managers_status ON managers(status)
  WHERE status IN ('invited', 'inactive');

-- Backfill is implicit via DEFAULT 'active'. Existing 'is_active=false' rows
-- can be migrated to status='inactive' in a follow-up cleanup PR; for now
-- they remain status='active' but is_active=false (functionally inactive
-- because login flow checks both).

COMMENT ON COLUMN managers.status IS
  'Invite lifecycle: invited (pre-OAuth) -> active (post first login) -> inactive (admin disabled)';
