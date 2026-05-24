-- 003_meta_schema.sql — Sprint M.1 Meta Ads foundation.
-- Schema documented em docs/superpowers/specs/2026-05-24-meta-ads-incorporation-design.md §2.

-- meta_oauth_connections: 1 conexão Meta por (manager, fb_user_id).
-- Diferente de Google: usa long-lived access_token (~60 dias) em vez de refresh_token.
CREATE TABLE IF NOT EXISTS meta_oauth_connections (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    manager_id            UUID NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
    fb_user_id            TEXT NOT NULL,
    fb_email              TEXT NOT NULL,
    access_token_enc      BYTEA NOT NULL,
    token_expires_at      TIMESTAMPTZ NOT NULL,
    scopes                TEXT[] NOT NULL,
    connected_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at            TIMESTAMPTZ,
    UNIQUE (manager_id, fb_user_id)
);

-- meta_ad_accounts: ad accounts visíveis pra V4.
CREATE TABLE IF NOT EXISTS meta_ad_accounts (
    ad_account_id     TEXT PRIMARY KEY,
    business_id       TEXT,
    business_name     TEXT,
    account_name      TEXT NOT NULL,
    currency          TEXT,
    timezone_name     TEXT,
    account_status    INT,
    is_active         BOOLEAN NOT NULL DEFAULT true,
    synced_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_meta_ad_accounts_active ON meta_ad_accounts (is_active, account_name);

-- manager_meta_account_access: M:N entre manager e meta ad accounts.
CREATE TABLE IF NOT EXISTS manager_meta_account_access (
    manager_id        UUID NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
    ad_account_id     TEXT NOT NULL REFERENCES meta_ad_accounts(ad_account_id) ON DELETE CASCADE,
    access_level      TEXT NOT NULL DEFAULT 'write',
    granted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by        UUID REFERENCES managers(id),
    PRIMARY KEY (manager_id, ad_account_id),
    CONSTRAINT mmaa_access_level_check CHECK (access_level IN ('read', 'write'))
);

-- meta_rate_counters: tracks Meta API throttling per (app, account, day).
CREATE TABLE IF NOT EXISTS meta_rate_counters (
    app_id            TEXT NOT NULL,
    ad_account_id     TEXT NOT NULL,
    date              DATE NOT NULL,
    calls_used        INT NOT NULL DEFAULT 0,
    last_throttle_pct INT NOT NULL DEFAULT 0,
    PRIMARY KEY (app_id, ad_account_id, date)
);

-- ALTER existing tables: add platform discriminator (default 'google' = backfill).
ALTER TABLE audit_log
    ADD COLUMN IF NOT EXISTS platform TEXT NOT NULL DEFAULT 'google';
CREATE INDEX IF NOT EXISTS idx_audit_platform_time
    ON audit_log (platform, occurred_at DESC);

ALTER TABLE pending_confirmations
    ADD COLUMN IF NOT EXISTS platform TEXT NOT NULL DEFAULT 'google';
