# Sprint M.1 — Meta Ads Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay the database + settings foundation for Meta Ads incorporation (Sprint family M.1-M.25). ZERO MCP tools exposed. Pure infrastructure: migrations, repositories, settings.

**Architecture:** 4 new Meta-specific tables (`meta_oauth_connections`, `meta_ad_accounts`, `manager_meta_account_access`, `meta_rate_counters`) + 2 ALTER on existing tables (add `platform` column to `audit_log` + `pending_confirmations`). 3 new repositories mirroring Google patterns. 2 new settings (`meta_app_id`, `meta_app_secret`).

**Tech Stack:** Python 3.12 · asyncpg · pydantic-settings · pytest + testcontainers · raw SQL migrations · AES via `src.auth.tokens`.

**Companion spec:** `docs/superpowers/specs/2026-05-24-meta-ads-incorporation-design.md`

**Scope explicitly EXCLUDED from M.1 (handled in M.2 or later):**
- Meta SDK integration (`facebook_business` dep) — M.2
- OAuth flow Meta (routes + webapp UI) — M.2
- Any MCP tool — M.2 onwards
- Rename `audit_log.google_request_id` → `provider_request_id` (descovered 22 caller files; safer as M.2 first task)
- Creating Meta App in BM (Wellington manual step — checklist appended)
- Submitting Meta App Review — M.2 (after webapp + 1 tool ponta-a-ponta works)

---

## File Structure

**Files to create:**

| Path | Responsibility |
|---|---|
| `src/db/migrations/003_meta_schema.sql` | 4 new tables + 2 ALTERs (append-only migration, never edit once deployed) |
| `src/db/repositories/meta_oauth_connections.py` | CRUD for Meta OAuth connections (upsert, get_active_for_manager, revoke) |
| `src/db/repositories/meta_ad_accounts.py` | CRUD for Meta ad accounts (upsert_many, list_all, mark_inactive_except) |
| `src/db/repositories/manager_meta_account_access.py` | M:N grant/revoke between managers and Meta ad accounts |

**Files to modify:**

| Path | Change |
|---|---|
| `src/config.py` | Add `meta_app_id: str` + `meta_app_secret: str` settings |
| `tests/integration/test_repositories.py` | Append 8 integration tests (3 repos × ~3 tests each) |

**No-code deliverables (Wellington manual after code merge):**

| Step | Detail |
|---|---|
| Create Meta App in BM V4 Lima Soares & Co | Facebook Business Manager UI; Development Mode |
| Add Wellington + 3 colaboradores as App Admins | App Roles UI in Meta App |
| Set Privacy Policy URL + Terms URL | Reuse existing `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/legal/privacy` + `/legal/terms` (verify they exist; create stubs if missing) |
| Store `meta_app_id` + `meta_app_secret` in GCP Secret Manager | `gcloud secrets create meta-app-id ...` |

---

## Task 1: Create migration 003_meta_schema.sql

**Files:**
- Create: `src/db/migrations/003_meta_schema.sql`

This task creates the migration file only. Application happens automatically via `migrate.run_all()` next time tests or local dev run. Production deploy applies it via Cloud Run Job.

- [ ] **Step 1.1: Create the migration file with full SQL**

Create `src/db/migrations/003_meta_schema.sql` with this exact content:

```sql
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
```

- [ ] **Step 1.2: Verify migration syntax is valid Python-readable**

Run:
```bash
python -c "from src.db import migrate; print(migrate.list_migrations())"
```

Expected output: list including `'003_meta_schema.sql'`. If error: fix SQL syntax in file.

- [ ] **Step 1.3: Commit**

```bash
git add src/db/migrations/003_meta_schema.sql
git commit -m "feat(db): migration 003_meta_schema.sql — Meta Ads foundation tables (Sprint M.1)

4 new tables: meta_oauth_connections, meta_ad_accounts,
manager_meta_account_access, meta_rate_counters. ALTER audit_log +
pending_confirmations adding platform column (default 'google' = backfill).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: meta_oauth_connections repository (TDD)

**Files:**
- Test: `tests/integration/test_repositories.py` (append section)
- Create: `src/db/repositories/meta_oauth_connections.py`

Mirror pattern of `src/db/repositories/google_oauth_connections.py` with one key difference: `access_token_enc` + `token_expires_at` instead of `refresh_token_enc` (Meta has no refresh_token model).

- [ ] **Step 2.1: Append failing integration tests to test_repositories.py**

Open `tests/integration/test_repositories.py` and add these tests at the bottom (after the existing audit_log section). Also update the import block near the top to add **just one new module** for now (the others come in Tasks 3 and 4):

In the imports block (around line 14-21), add `meta_oauth_connections` keeping alphabetical order:
```python
from src.db.repositories import (
    audit_log,
    google_ads_accounts,
    google_oauth_connections,
    manager_account_access,
    managers,
    mcp_sessions,
    meta_oauth_connections,         # ← NEW (Task 2)
)
```

At the bottom of the file, append:

```python
# ---------- meta_oauth_connections ----------


@pytest.mark.integration
async def test_meta_oauth_upsert_then_update(db) -> None:
    from datetime import datetime, timedelta, timezone

    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="mo@v4.com", full_name=None)
        future = datetime.now(timezone.utc) + timedelta(days=60)
        c1 = await meta_oauth_connections.upsert(
            conn,
            manager_id=mid,
            fb_user_id="123456789",
            fb_email="mo@gmail.com",
            access_token_enc=b"enc-v1",
            token_expires_at=future,
            scopes=["ads_read", "ads_management"],
        )
        c2 = await meta_oauth_connections.upsert(
            conn,
            manager_id=mid,
            fb_user_id="123456789",
            fb_email="mo@gmail.com",
            access_token_enc=b"enc-v2",
            token_expires_at=future,
            scopes=["ads_read", "ads_management", "business_management"],
        )
        # Same row (UNIQUE on manager_id + fb_user_id), token updated.
        assert c1.id == c2.id
        assert c2.access_token_enc == b"enc-v2"
        assert "business_management" in c2.scopes


@pytest.mark.integration
async def test_meta_oauth_get_active_returns_latest_non_revoked(db) -> None:
    from datetime import datetime, timedelta, timezone

    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="mg@v4.com", full_name=None)
        future = datetime.now(timezone.utc) + timedelta(days=60)
        c1 = await meta_oauth_connections.upsert(
            conn,
            manager_id=mid,
            fb_user_id="111",
            fb_email="primary@fb.com",
            access_token_enc=b"e1",
            token_expires_at=future,
            scopes=["ads_read"],
        )
        c2 = await meta_oauth_connections.upsert(
            conn,
            manager_id=mid,
            fb_user_id="222",
            fb_email="other@fb.com",
            access_token_enc=b"e2",
            token_expires_at=future,
            scopes=["ads_read"],
        )
        active = await meta_oauth_connections.get_active_for_manager(conn, mid)
        assert active is not None
        # Most recent inserted wins.
        assert active.id == c2.id

        await meta_oauth_connections.revoke(conn, c2.id)
        active_after = await meta_oauth_connections.get_active_for_manager(conn, mid)
        assert active_after is not None
        assert active_after.id == c1.id


@pytest.mark.integration
async def test_meta_oauth_get_active_none_when_no_connection(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="mn@v4.com", full_name=None)
        result = await meta_oauth_connections.get_active_for_manager(conn, mid)
        assert result is None
```

- [ ] **Step 2.2: Run tests — expect ModuleNotFoundError**

Run:
```bash
python -m pytest tests/integration/test_repositories.py::test_meta_oauth_upsert_then_update -v
```

Expected: ImportError or ModuleNotFoundError for `meta_oauth_connections`. If Docker not available locally, the testcontainers fixture will fail at startup — that's OK; CI will validate. Continue to Step 2.3.

- [ ] **Step 2.3: Create meta_oauth_connections.py**

Create `src/db/repositories/meta_oauth_connections.py` with this exact content:

```python
"""CRUD for `meta_oauth_connections` — Meta Ads OAuth tokens.

Diferente de google_oauth_connections: Meta usa long-lived access_token
(~60 dias) em vez de refresh_token. token_expires_at é NOT NULL para
permitir job background avisar gestor antes de expirar.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg


@dataclass(slots=True, frozen=True)
class MetaOAuthConnection:
    id: UUID
    manager_id: UUID
    fb_user_id: str
    fb_email: str
    access_token_enc: bytes
    token_expires_at: datetime
    scopes: list[str]
    connected_at: datetime
    revoked_at: datetime | None


def _row_to_conn(row: asyncpg.Record) -> MetaOAuthConnection:
    return MetaOAuthConnection(
        id=row["id"],
        manager_id=row["manager_id"],
        fb_user_id=row["fb_user_id"],
        fb_email=row["fb_email"],
        access_token_enc=row["access_token_enc"],
        token_expires_at=row["token_expires_at"],
        scopes=row["scopes"],
        connected_at=row["connected_at"],
        revoked_at=row["revoked_at"],
    )


async def upsert(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    fb_user_id: str,
    fb_email: str,
    access_token_enc: bytes,
    token_expires_at: datetime,
    scopes: list[str],
) -> MetaOAuthConnection:
    """INSERT new connection or update access_token if (manager_id, fb_user_id) exists."""
    row = await conn.fetchrow(
        """
        INSERT INTO meta_oauth_connections
            (manager_id, fb_user_id, fb_email, access_token_enc, token_expires_at, scopes)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (manager_id, fb_user_id) DO UPDATE SET
            fb_email = EXCLUDED.fb_email,
            access_token_enc = EXCLUDED.access_token_enc,
            token_expires_at = EXCLUDED.token_expires_at,
            scopes = EXCLUDED.scopes,
            connected_at = now(),
            revoked_at = NULL
        RETURNING *
        """,
        manager_id,
        fb_user_id,
        fb_email,
        access_token_enc,
        token_expires_at,
        scopes,
    )
    assert row is not None
    return _row_to_conn(row)


async def get_active_for_manager(
    conn: asyncpg.Connection, manager_id: UUID
) -> MetaOAuthConnection | None:
    """Return the most recent NON-REVOKED connection for the manager."""
    row = await conn.fetchrow(
        """
        SELECT * FROM meta_oauth_connections
        WHERE manager_id = $1 AND revoked_at IS NULL
        ORDER BY connected_at DESC
        LIMIT 1
        """,
        manager_id,
    )
    return _row_to_conn(row) if row else None


async def revoke(conn: asyncpg.Connection, connection_id: UUID) -> None:
    await conn.execute(
        "UPDATE meta_oauth_connections SET revoked_at = now() WHERE id = $1",
        connection_id,
    )
```

- [ ] **Step 2.4: Run tests — expect PASS (if Docker available)**

Run:
```bash
python -m pytest tests/integration/test_repositories.py -v -k meta_oauth -m integration
```

Expected: 3 PASS if Docker running. If Docker not available: skip with note "validated in CI".

- [ ] **Step 2.5: Run ruff + mypy on new file**

Run:
```bash
python -m ruff check src/db/repositories/meta_oauth_connections.py
python -m ruff format --check src/db/repositories/meta_oauth_connections.py
python -m mypy --strict src/db/repositories/meta_oauth_connections.py
```

Expected: all three pass with no issues.

- [ ] **Step 2.6: Commit**

```bash
git add src/db/repositories/meta_oauth_connections.py tests/integration/test_repositories.py
git commit -m "feat(db): meta_oauth_connections repository + 3 integration tests (Sprint M.1)

Mirror pattern of google_oauth_connections.py. Key difference:
access_token_enc + token_expires_at (Meta has no refresh_token model;
long-lived token ~60 days expires; webapp UI pede reconectar).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: meta_ad_accounts repository (TDD)

**Files:**
- Test: `tests/integration/test_repositories.py` (append)
- Create: `src/db/repositories/meta_ad_accounts.py`

Mirror pattern of `src/db/repositories/google_ads_accounts.py` with Meta-specific fields (business_id, business_name, account_status as int).

- [ ] **Step 3.1: Append failing tests to test_repositories.py**

Update the imports block to add `meta_ad_accounts` (alphabetical):
```python
from src.db.repositories import (
    audit_log,
    google_ads_accounts,
    google_oauth_connections,
    manager_account_access,
    managers,
    mcp_sessions,
    meta_ad_accounts,               # ← NEW (Task 3)
    meta_oauth_connections,
)
```

At the bottom of `tests/integration/test_repositories.py` append:

```python
# ---------- meta_ad_accounts ----------


@pytest.mark.integration
async def test_meta_accounts_upsert_and_list(db) -> None:
    async with db.acquire() as conn:
        n = await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_111",
                    "business_id": "bm_999",
                    "business_name": "V4 Lima Soares & Co",
                    "account_name": "Cliente Alpha Meta",
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                    "account_status": 1,
                },
                {
                    "ad_account_id": "act_222",
                    "business_id": "bm_999",
                    "business_name": "V4 Lima Soares & Co",
                    "account_name": "Cliente Beta Meta",
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                    "account_status": 1,
                },
            ],
        )
        assert n == 2
        all_accounts = await meta_ad_accounts.list_all(conn)
        assert len(all_accounts) == 2
        names = [a.account_name for a in all_accounts]
        assert names == sorted(names)  # ORDER BY account_name


@pytest.mark.integration
async def test_meta_accounts_mark_inactive_except(db) -> None:
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {"ad_account_id": "act_1", "business_id": "bm_A", "account_name": "A"},
                {"ad_account_id": "act_2", "business_id": "bm_A", "account_name": "B"},
                {"ad_account_id": "act_3", "business_id": "bm_A", "account_name": "C"},
            ],
        )
        deactivated = await meta_ad_accounts.mark_inactive_except(
            conn, business_id="bm_A", keep_ad_account_ids=["act_1", "act_3"]
        )
        assert deactivated == 1
        active = await meta_ad_accounts.list_all(conn)
        ids = {a.ad_account_id for a in active}
        assert ids == {"act_1", "act_3"}


@pytest.mark.integration
async def test_meta_accounts_personal_no_business_id(db) -> None:
    """Ad account 'personal' (sem Business Manager) é legal Meta — business_id NULL."""
    async with db.acquire() as conn:
        n = await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_personal",
                    "business_id": None,
                    "account_name": "Personal Account",
                    "account_status": 1,
                }
            ],
        )
        assert n == 1
        all_accounts = await meta_ad_accounts.list_all(conn)
        assert len(all_accounts) == 1
        assert all_accounts[0].business_id is None
```

- [ ] **Step 3.2: Run tests — expect failures**

Run:
```bash
python -m pytest tests/integration/test_repositories.py -v -k meta_accounts -m integration
```

Expected: ImportError or test failures. Continue.

- [ ] **Step 3.3: Create meta_ad_accounts.py**

Create `src/db/repositories/meta_ad_accounts.py` with:

```python
"""CRUD for `meta_ad_accounts`. Populated by Meta sync job (M.2+)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg


@dataclass(slots=True, frozen=True)
class MetaAdAccount:
    ad_account_id: str
    business_id: str | None
    business_name: str | None
    account_name: str
    currency: str | None
    timezone_name: str | None
    account_status: int | None
    is_active: bool
    synced_at: datetime


def _row_to_account(row: asyncpg.Record) -> MetaAdAccount:
    return MetaAdAccount(
        ad_account_id=row["ad_account_id"],
        business_id=row["business_id"],
        business_name=row["business_name"],
        account_name=row["account_name"],
        currency=row["currency"],
        timezone_name=row["timezone_name"],
        account_status=row["account_status"],
        is_active=row["is_active"],
        synced_at=row["synced_at"],
    )


async def upsert_many(
    conn: asyncpg.Connection,
    accounts: list[dict[str, Any]],
) -> int:
    """Insert or update accounts in bulk; returns count touched.

    Each dict accepts: ad_account_id, business_id, business_name,
    account_name, currency, timezone_name, account_status.
    """
    if not accounts:
        return 0
    rows = [
        (
            a["ad_account_id"],
            a.get("business_id"),
            a.get("business_name"),
            a["account_name"],
            a.get("currency"),
            a.get("timezone_name"),
            a.get("account_status"),
        )
        for a in accounts
    ]
    await conn.executemany(
        """
        INSERT INTO meta_ad_accounts
            (ad_account_id, business_id, business_name, account_name,
             currency, timezone_name, account_status, is_active, synced_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, true, now())
        ON CONFLICT (ad_account_id) DO UPDATE SET
            business_id = EXCLUDED.business_id,
            business_name = EXCLUDED.business_name,
            account_name = EXCLUDED.account_name,
            currency = EXCLUDED.currency,
            timezone_name = EXCLUDED.timezone_name,
            account_status = EXCLUDED.account_status,
            is_active = true,
            synced_at = now()
        """,
        rows,
    )
    return len(rows)


async def mark_inactive_except(
    conn: asyncpg.Connection,
    *,
    business_id: str,
    keep_ad_account_ids: list[str],
) -> int:
    """Mark accounts under business_id as inactive if not in keep list (deletion detection)."""
    if not keep_ad_account_ids:
        result = await conn.execute(
            "UPDATE meta_ad_accounts SET is_active = false "
            "WHERE business_id = $1 AND is_active = true",
            business_id,
        )
    else:
        result = await conn.execute(
            """
            UPDATE meta_ad_accounts SET is_active = false
            WHERE business_id = $1
              AND is_active = true
              AND ad_account_id <> ALL($2::text[])
            """,
            business_id,
            keep_ad_account_ids,
        )
    return int(result.split()[-1]) if result.startswith("UPDATE") else 0


async def list_all(conn: asyncpg.Connection) -> list[MetaAdAccount]:
    rows = await conn.fetch(
        "SELECT * FROM meta_ad_accounts WHERE is_active = true ORDER BY account_name"
    )
    return [_row_to_account(r) for r in rows]


async def get_by_id(
    conn: asyncpg.Connection, ad_account_id: str
) -> MetaAdAccount | None:
    row = await conn.fetchrow(
        "SELECT * FROM meta_ad_accounts WHERE ad_account_id = $1",
        ad_account_id,
    )
    return _row_to_account(row) if row else None
```

- [ ] **Step 3.4: Run tests — expect PASS**

Run:
```bash
python -m pytest tests/integration/test_repositories.py -v -k meta_accounts -m integration
```

Expected: 3 PASS (or skip if no Docker).

- [ ] **Step 3.5: Run ruff + mypy**

Run:
```bash
python -m ruff check src/db/repositories/meta_ad_accounts.py
python -m ruff format --check src/db/repositories/meta_ad_accounts.py
python -m mypy --strict src/db/repositories/meta_ad_accounts.py
```

Expected: all pass.

- [ ] **Step 3.6: Commit**

```bash
git add src/db/repositories/meta_ad_accounts.py tests/integration/test_repositories.py
git commit -m "feat(db): meta_ad_accounts repository + 3 integration tests (Sprint M.1)

Mirror google_ads_accounts.py. Diferenças:
- ad_account_id TEXT prefix 'act_' (e.g., 'act_123456789')
- business_id NULL allowed (personal ad accounts são raros mas legais)
- account_status INT (Meta enum: 1=ACTIVE, 2=DISABLED, 3=UNSETTLED, etc)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: manager_meta_account_access repository (TDD)

**Files:**
- Test: `tests/integration/test_repositories.py` (append)
- Create: `src/db/repositories/manager_meta_account_access.py`

Mirror pattern of `manager_account_access.py` (existing Google) with Meta types.

- [ ] **Step 4.1: Append failing tests**

Update imports block adding `manager_meta_account_access` (alphabetical — comes after `manager_account_access`):
```python
from src.db.repositories import (
    audit_log,
    google_ads_accounts,
    google_oauth_connections,
    manager_account_access,
    manager_meta_account_access,    # ← NEW (Task 4)
    managers,
    mcp_sessions,
    meta_ad_accounts,
    meta_oauth_connections,
)
```

At the bottom of `tests/integration/test_repositories.py` append:

```python
# ---------- manager_meta_account_access ----------


@pytest.mark.integration
async def test_meta_access_grant_list_revoke(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="ma@v4.com", full_name=None)
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {"ad_account_id": "act_111", "business_id": "bm_X", "account_name": "X"},
            ],
        )
        await manager_meta_account_access.grant(
            conn, manager_id=mid, ad_account_id="act_111"
        )

        accounts = await manager_meta_account_access.list_accounts_for_manager(conn, mid)
        assert len(accounts) == 1
        assert accounts[0].ad_account_id == "act_111"

        assert (
            await manager_meta_account_access.can_manager_access(conn, mid, "act_111") is True
        )
        assert (
            await manager_meta_account_access.can_manager_access(conn, mid, "act_999") is False
        )

        await manager_meta_account_access.revoke(
            conn, manager_id=mid, ad_account_id="act_111"
        )
        accounts2 = await manager_meta_account_access.list_accounts_for_manager(conn, mid)
        assert accounts2 == []


@pytest.mark.integration
async def test_meta_access_grant_all_active(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="mga@v4.com", full_name=None)
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {"ad_account_id": "act_a", "business_id": "bm_A", "account_name": "A"},
                {"ad_account_id": "act_b", "business_id": "bm_A", "account_name": "B"},
            ],
        )
        n = await manager_meta_account_access.grant_all_active(conn, manager_id=mid)
        assert n == 2
        accounts = await manager_meta_account_access.list_accounts_for_manager(conn, mid)
        assert len(accounts) == 2

        # Idempotent re-run inserts 0 (ON CONFLICT DO NOTHING).
        n2 = await manager_meta_account_access.grant_all_active(conn, manager_id=mid)
        assert n2 == 0
```

- [ ] **Step 4.2: Run tests — expect failures**

Run:
```bash
python -m pytest tests/integration/test_repositories.py -v -k meta_access -m integration
```

Expected: ImportError. Continue.

- [ ] **Step 4.3: Create manager_meta_account_access.py**

Create `src/db/repositories/manager_meta_account_access.py` with:

```python
"""CRUD for `manager_meta_account_access` (which manager can operate which Meta ad account)."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg

from src.db.repositories.meta_ad_accounts import MetaAdAccount, _row_to_account


@dataclass(slots=True, frozen=True)
class MetaAccountAccess:
    manager_id: UUID
    ad_account_id: str
    access_level: str  # 'read' | 'write'
    granted_at: datetime
    granted_by: UUID | None


async def grant(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    ad_account_id: str,
    access_level: str = "write",
    granted_by: UUID | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO manager_meta_account_access
            (manager_id, ad_account_id, access_level, granted_by)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (manager_id, ad_account_id) DO UPDATE SET
            access_level = EXCLUDED.access_level,
            granted_at = now(),
            granted_by = EXCLUDED.granted_by
        """,
        manager_id,
        ad_account_id,
        access_level,
        granted_by,
    )


async def grant_all_active(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    granted_by: UUID | None = None,
) -> int:
    """Grant write access to every active meta_ad_accounts row for this manager."""
    result = await conn.execute(
        """
        INSERT INTO manager_meta_account_access
            (manager_id, ad_account_id, access_level, granted_by)
        SELECT $1, ad_account_id, 'write', $2
        FROM meta_ad_accounts
        WHERE is_active = true
        ON CONFLICT (manager_id, ad_account_id) DO NOTHING
        """,
        manager_id,
        granted_by,
    )
    return int(result.split()[-1]) if result.startswith("INSERT") else 0


async def revoke(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    ad_account_id: str,
) -> None:
    await conn.execute(
        "DELETE FROM manager_meta_account_access "
        "WHERE manager_id = $1 AND ad_account_id = $2",
        manager_id,
        ad_account_id,
    )


async def list_accounts_for_manager(
    conn: asyncpg.Connection, manager_id: UUID
) -> list[MetaAdAccount]:
    """Return MetaAdAccount rows the manager has any access to (active accounts only)."""
    rows = await conn.fetch(
        """
        SELECT a.*
        FROM meta_ad_accounts a
        INNER JOIN manager_meta_account_access m ON m.ad_account_id = a.ad_account_id
        WHERE m.manager_id = $1
          AND a.is_active = true
        ORDER BY a.account_name
        """,
        manager_id,
    )
    return [_row_to_account(r) for r in rows]


async def can_manager_access(
    conn: asyncpg.Connection,
    manager_id: UUID,
    ad_account_id: str,
    *,
    level: str = "read",
) -> bool:
    """Return True if manager has at least `level` access to ad_account_id."""
    row = await conn.fetchrow(
        """
        SELECT access_level FROM manager_meta_account_access
        WHERE manager_id = $1 AND ad_account_id = $2
        """,
        manager_id,
        ad_account_id,
    )
    if row is None:
        return False
    if level == "read":
        return True
    return bool(row["access_level"] == "write")


async def bulk_grant(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    ad_account_ids: list[str],
    granted_by: UUID,
    access_level: str = "write",
) -> int:
    """Idempotent bulk grant. Inserts rows that don't exist; ignores duplicates."""
    if not ad_account_ids:
        return 0
    rows = [(manager_id, aid, access_level, granted_by) for aid in ad_account_ids]
    await conn.executemany(
        """INSERT INTO manager_meta_account_access
               (manager_id, ad_account_id, access_level, granted_by)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (manager_id, ad_account_id) DO NOTHING""",
        rows,
    )
    return len(rows)
```

- [ ] **Step 4.4: Run tests — expect PASS**

Run:
```bash
python -m pytest tests/integration/test_repositories.py -v -k meta_access -m integration
```

Expected: 2 PASS (or skip if no Docker).

- [ ] **Step 4.5: Run ruff + mypy**

Run:
```bash
python -m ruff check src/db/repositories/manager_meta_account_access.py
python -m ruff format --check src/db/repositories/manager_meta_account_access.py
python -m mypy --strict src/db/repositories/manager_meta_account_access.py
```

Expected: all pass.

- [ ] **Step 4.6: Commit**

```bash
git add src/db/repositories/manager_meta_account_access.py tests/integration/test_repositories.py
git commit -m "feat(db): manager_meta_account_access repository + 2 integration tests (Sprint M.1)

Mirror manager_account_access.py com tipos Meta:
- ad_account_id TEXT (e.g., 'act_123') em vez de customer_id
- INNER JOIN com meta_ad_accounts em vez de google_ads_accounts

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Settings — meta_app_id + meta_app_secret

**Files:**
- Modify: `src/config.py:35-37` (add 2 settings após `google_ads_login_customer_id`)
- Test: `tests/unit/test_settings.py` (if exists; otherwise inline check)

- [ ] **Step 5.1: Check if test_settings.py exists**

Run:
```bash
ls tests/unit/test_settings.py 2>/dev/null || echo "missing"
```

If "missing": skip Step 5.2 unit test — settings validation is exercised in CI via running the app. If exists: continue Step 5.2.

- [ ] **Step 5.2: (Conditional) Add failing test if test_settings.py exists**

Append to `tests/unit/test_settings.py`:

```python
def test_settings_loads_meta_app_id_and_secret(monkeypatch) -> None:
    monkeypatch.setenv("META_APP_ID", "1234567890123456")
    monkeypatch.setenv("META_APP_SECRET", "abc123xyz789abc123xyz789abc123xy")
    # ... existing required env vars to make Settings() construct ...
    from src.config import Settings
    s = Settings()
    assert s.meta_app_id == "1234567890123456"
    assert s.meta_app_secret.startswith("abc")
```

Run to fail: `python -m pytest tests/unit/test_settings.py::test_settings_loads_meta_app_id_and_secret -v`
Expected: AttributeError (settings don't exist yet).

- [ ] **Step 5.3: Add settings to src/config.py**

In `src/config.py`, after the line:
```python
    google_ads_login_customer_id: str
```

Add (before the Supabase block):
```python

    # Meta Ads API (Sprint M.1 foundation)
    meta_app_id: str = ""
    meta_app_secret: str = ""
```

Default empty allows app to boot without Meta secrets (graceful — Meta tools só M.2+ vão usar). Production deploy populates via Secret Manager via Cloud Run env vars.

- [ ] **Step 5.4: Run tests (if Step 5.2 applied)**

Run:
```bash
python -m pytest tests/unit/test_settings.py -v
```

Expected: PASS if test was added in 5.2.

- [ ] **Step 5.5: Verify config still loads in app boot**

Run (this exercises Settings construction):
```bash
python -c "from src.config import get_settings; s = get_settings(); print('OK, meta_app_id =', repr(s.meta_app_id))"
```

Expected: `OK, meta_app_id = ''` (or actual value if env populated). If error: fix config.py syntax.

- [ ] **Step 5.6: Run ruff + mypy on config.py**

Run:
```bash
python -m ruff check src/config.py
python -m ruff format --check src/config.py
python -m mypy --strict src/config.py
```

Expected: all pass.

- [ ] **Step 5.7: Commit**

```bash
git add src/config.py tests/unit/test_settings.py
git commit -m "feat(config): meta_app_id + meta_app_secret settings (Sprint M.1)

Default empty strings — app boots sem secrets Meta. Produção popula via
Secret Manager binding em Cloud Run env. Wellington adiciona secrets em
manual checklist após code merge.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

(Note: if test_settings.py didn't exist in Step 5.1, skip its `git add`.)

---

## Task 6: Pre-push gate full sweep

The full sweep is **mandatory** here because we touched DB migrations + repositories (lesson learned em Sprints 3b.5/3b.8).

- [ ] **Step 6.1: Run quick pre-push first**

Run:
```bash
python scripts/check_pre_push.py
```

Expected: 5/5 PASS (ruff, format, mypy, unit, non-DB integration). Fix any issue before continuing.

- [ ] **Step 6.2: Run full pre-push (Docker required)**

Run:
```bash
python scripts/check_pre_push_full.py
```

Expected: 6/6 PASS. Step 6 runs all integration tests including new Meta repo tests via testcontainers (~60-90s). Fix any issue.

**If Docker is not running locally:** Exit code 2 + PT-BR hint. Push anyway — CI will run the full integration suite. Verify in PR/post-push that CI green.

- [ ] **Step 6.3: Commit any cleanup (only if there are uncommitted fixes from gates)**

If ruff/format/mypy made auto-fix changes:
```bash
git add -u
git commit -m "chore: ruff format + mypy fixes from pre-push gate (Sprint M.1)"
```

Skip this step if no changes.

---

## Task 7: Push to origin/main

- [ ] **Step 7.1: Check git status**

Run:
```bash
git status
git log --oneline origin/main..HEAD
```

Expected: working tree clean. Log shows 5-6 commits (1 migration + 3 repos + 1 settings + optional cleanup).

- [ ] **Step 7.2: Push**

Run:
```bash
git push origin main
```

Expected: push succeeds (admin bypass).

- [ ] **Step 7.3: Watch CI + Deploy**

Run:
```bash
gh run list --limit 5
```

Then:
```bash
gh run watch <RUN_ID>
```

Wait for both CI and Deploy workflows to complete with success status.

- [ ] **Step 7.4: Verify /health**

Run:
```bash
curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```

Expected: HTTP 200 with JSON body. Migrations applied automatically by Cloud Run Job em deploy.yml.

- [ ] **Step 7.5: Confirm migrations applied em production DB**

Run:
```bash
gcloud secrets versions access latest --secret=database-url --project=v4-ads-mcp-prod | python -c "
import asyncio, sys, asyncpg
async def main():
    dsn = sys.stdin.read().strip()
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch('SELECT name FROM _migrations ORDER BY applied_at DESC LIMIT 5')
        for r in rows:
            print(r['name'])
    finally:
        await conn.close()
asyncio.run(main())"
```

Expected output includes `003_meta_schema.sql` at top. Plus quick sanity:
```bash
gcloud secrets versions access latest --secret=database-url --project=v4-ads-mcp-prod | python -c "
import asyncio, sys, asyncpg
async def main():
    dsn = sys.stdin.read().strip()
    conn = await asyncpg.connect(dsn)
    try:
        for t in ['meta_oauth_connections', 'meta_ad_accounts', 'manager_meta_account_access', 'meta_rate_counters']:
            count = await conn.fetchval(f'SELECT count(*) FROM {t}')
            print(f'{t}: {count} rows (expect 0)')
    finally:
        await conn.close()
asyncio.run(main())"
```

Expected: all 4 tables exist + report 0 rows.

---

## Task 8: Wellington manual checklist (após code merge)

This task is **executed by Wellington manually** — not by an automated agent. Lista pra Wellington seguir após Task 7 confirma deploy success:

- [ ] **8.1: Criar Meta App em Business Manager V4 Lima Soares & Co**

1. Acessa https://business.facebook.com (logado como admin V4 Lima Soares & Co)
2. Business Settings → Apps → Add → Create New App ID
3. App Type: **Business**
4. App Name: `V4 Ads MCP — Lima Soares & Co`
5. App Contact Email: wellinton.ribeiro@v4company.com
6. Business Account: V4 Lima Soares & Co
7. Click "Create App"

- [ ] **8.2: Adicionar Wellington + 3 colaboradores como App Admins**

1. App Dashboard → Roles → Roles
2. Add Wellington como Admin
3. Add 3 colaboradores (emails) como Admin ou Developer
4. Confirme cada email manualmente (Meta exige owner confirmation)

- [ ] **8.3: Configurar Facebook Login product**

1. App Dashboard → Add Product → Facebook Login → Set Up
2. Settings → Valid OAuth Redirect URIs:
   - `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/oauth/meta/callback`
   - `http://localhost:8080/oauth/meta/callback` (dev only)
3. Settings → Client OAuth Login: ON
4. Settings → Web OAuth Login: ON
5. Save

- [ ] **8.4: Configurar Privacy Policy + Terms URLs**

App Dashboard → App Settings → Basic:
- Privacy Policy URL: `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/legal/privacy`
- Terms of Service URL: `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/legal/terms`

**Verifique primeiro:** essas URLs públicas devem retornar HTML válido. Se 404, criar páginas stub via Sprint M.1.1 hotfix (não bloqueia M.1).

- [ ] **8.5: Pegar App ID + App Secret**

App Dashboard → App Settings → Basic:
- Copy "App ID" (~16 digits)
- Click "Show" em App Secret, copy

- [ ] **8.6: Criar secrets no GCP Secret Manager**

```bash
echo -n "<APP_ID>" | gcloud secrets create meta-app-id \
    --project=v4-ads-mcp-prod \
    --data-file=- \
    --replication-policy=automatic

echo -n "<APP_SECRET>" | gcloud secrets create meta-app-secret \
    --project=v4-ads-mcp-prod \
    --data-file=- \
    --replication-policy=automatic
```

- [ ] **8.7: Adicionar Secret Manager bindings em Cloud Run**

Edit `deploy.yml` (CI workflow) ou Cloud Run service config — add env var mappings:
- `META_APP_ID` ← secret `meta-app-id` latest version
- `META_APP_SECRET` ← secret `meta-app-secret` latest version

Re-deploy (push trivial change ou trigger workflow_dispatch).

- [ ] **8.8: Verificar app boot com novos secrets**

Após re-deploy:
```bash
curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```

Expected: HTTP 200. Logs structlog mostram zero error sobre missing META_APP_*.

- [ ] **8.9: Signoff M.1**

Update `CLAUDE.md` "Current state — Meta" subsection (criar se não existir):
```markdown
### Shipped (Meta — Sprint family M)

| Phase | Status | Notes |
|---|---|---|
| Sprint M.1 — Foundation | ✅ 2026-05-XX | DB schema + repos + settings + Meta App Dev Mode. Wellington manual checklist done. |
```

Update `docs/operacao/sprint-history.md` appending Sprint M.1 row.

Commit:
```bash
git add CLAUDE.md docs/operacao/sprint-history.md
git commit -m "docs(signoff): Sprint M.1 Meta foundation — schema + repos + Meta App ready

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin main
```

---

## Self-Review Notes

This plan deliberately stops short of:
1. **Submitting Meta App Review** — deferred to Sprint M.2 (after webapp OAuth + 1 tool ponta-a-ponta works, screencast makes more sense)
2. **Renaming `google_request_id` → `provider_request_id`** — descoberto 22 caller files; safer as M.2 first task (low-risk antes de SDK integration)
3. **Adicionar `facebook-business` dep ao pyproject.toml** — Sprint M.2 quando SDK começa a ser usado
4. **MCP tools Meta** — Sprint M.2 começa com `meta_list_my_ad_accounts` + `meta_get_account_overview`

Após M.1 ship + signoff, próximo passo: `/sprint-bootstrap` skill gera spec + plan para Sprint M.2.

---

**Plan estimativa:** 3-5 dias úteis (1-2 dias code + 1-2 dias Wellington manual setup + 1 dia smoke/signoff).

**Critical path:** Tasks 1-7 são code (subagent pode executar). Task 8 é manual Wellington.
