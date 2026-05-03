-- 001_initial_schema.sql — Phase 0 baseline.
-- Schema documented in docs/superpowers/specs/2026-05-03-v4-ads-mcp-design.md §4.

CREATE TABLE IF NOT EXISTS managers (
    id              UUID PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    full_name       TEXT,
    role            TEXT NOT NULL DEFAULT 'gestor',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ,
    CONSTRAINT managers_role_check CHECK (role IN ('gestor', 'admin'))
);

CREATE TABLE IF NOT EXISTS google_oauth_connections (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    manager_id          UUID NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
    google_email        TEXT NOT NULL,
    refresh_token_enc   BYTEA NOT NULL,
    scopes              TEXT[] NOT NULL,
    connected_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at          TIMESTAMPTZ,
    UNIQUE (manager_id, google_email)
);

CREATE TABLE IF NOT EXISTS google_ads_accounts (
    customer_id      TEXT PRIMARY KEY,
    mcc_id           TEXT NOT NULL,
    descriptive_name TEXT NOT NULL,
    currency_code    TEXT,
    time_zone        TEXT,
    is_test_account  BOOLEAN NOT NULL DEFAULT false,
    is_active        BOOLEAN NOT NULL DEFAULT true,
    synced_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manager_account_access (
    manager_id      UUID NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
    customer_id     TEXT NOT NULL REFERENCES google_ads_accounts(customer_id) ON DELETE CASCADE,
    access_level    TEXT NOT NULL DEFAULT 'write',
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by      UUID REFERENCES managers(id),
    PRIMARY KEY (manager_id, customer_id),
    CONSTRAINT mac_access_level_check CHECK (access_level IN ('read', 'write'))
);

CREATE TABLE IF NOT EXISTS mcp_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    manager_id      UUID NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
    token_hash      TEXT NOT NULL UNIQUE,
    label           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at    TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS pending_confirmations (
    token           TEXT PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES mcp_sessions(id) ON DELETE CASCADE,
    customer_id     TEXT NOT NULL,
    operation_type  TEXT NOT NULL,
    payload         JSONB NOT NULL,
    blast_summary   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    consumed_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS audit_log (
    id              BIGSERIAL PRIMARY KEY,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    manager_id      UUID REFERENCES managers(id),
    session_id      UUID REFERENCES mcp_sessions(id),
    customer_id     TEXT,
    action_type     TEXT NOT NULL,
    operation       TEXT NOT NULL,
    target_count    INT,
    params_summary  JSONB,
    google_request_id TEXT,
    status          TEXT NOT NULL,
    error_message   TEXT,
    duration_ms     INT,
    CONSTRAINT audit_action_type_check CHECK (action_type IN ('mutate', 'read', 'auth', 'system')),
    CONSTRAINT audit_status_check CHECK (status IN ('success', 'error', 'denied'))
);
CREATE INDEX IF NOT EXISTS idx_audit_manager_time ON audit_log (manager_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_account_time ON audit_log (customer_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS rate_counters (
    developer_token_id TEXT NOT NULL,
    date            DATE NOT NULL,
    operations_used INT NOT NULL DEFAULT 0,
    last_alert_pct  INT NOT NULL DEFAULT 0,
    PRIMARY KEY (developer_token_id, date)
);
