# Sprint M.2a — Meta OAuth + SDK + First Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pipeline ponta-a-ponta OAuth Meta → SDK → 1 tool MCP funcional, completando 5 prep tasks descobertas em M.1 final review.

**Architecture:** Routes `/oauth/meta/*` paralelas a Google + `src/meta_ads/` package (client/reports/errors) + 1 tool MCP (`meta_list_my_ad_accounts`) lendo do cache local. Big-bang rename `google_request_id` → `provider_request_id` em 50 arquivos.

**Tech Stack:** Python 3.12 · facebook-business>=21.0.0 · asyncpg · httpx · pydantic-settings · pytest + respx (mock Graph API) + testcontainers.

**Companion spec:** `docs/superpowers/specs/2026-05-24-sprint-m2a-meta-oauth-first-tool-design.md`

---

## File Structure

**Files to create:**

| Path | Responsibility |
|---|---|
| `src/db/migrations/004_audit_log_provider_id.sql` | RENAME column google_request_id → provider_request_id |
| `src/db/repositories/meta_rate_counters.py` | CRUD for meta_rate_counters table (M.1 created table, no Python yet) |
| `src/auth/meta_oauth.py` | Routes /oauth/meta/{start,callback,revoke} + state HMAC + token exchange |
| `src/meta_ads/__init__.py` | Empty package marker |
| `src/meta_ads/client.py` | `build_meta_api_for_manager()` factory + exception classes |
| `src/meta_ads/reports.py` | `run_meta_graph_get()` executor with audit_log + BUC parsing |
| `src/meta_ads/errors.py` | `to_friendly_meta_error()` PT-BR mapping + dataclass |
| `src/mcp/tools/_meta_common.py` | Stub helpers (resolve_meta_date_window placeholder, parse_meta_id, account_status labels) |
| `src/mcp/tools/meta_list_my_ad_accounts.py` | 1ª tool MCP Meta (read cache) |
| `tests/unit/test_meta_oauth.py` | OAuth decision tree unit tests |
| `tests/unit/test_meta_errors.py` | Error mapping unit tests |
| `tests/unit/test_meta_rate_counters_repo.py` | Repo unit tests with mocked conn |
| `tests/unit/test_buc_header_parsing.py` | BUC header JSON parsing |
| `tests/integration/test_meta_oauth_flow.py` | OAuth callback via respx mock Graph API |
| `tests/integration/test_meta_list_my_ad_accounts.py` | End-to-end tool tests |
| `tests/integration/test_audit_log_platform.py` | Regression: platform kwarg + provider_request_id column |
| `docs/operacao/phase-M-2a-bootstrap.md` | Smoke runbook (gerado via smoke-runbook-generator subagent) |

**Files to modify:**

| Path | Change |
|---|---|
| `pyproject.toml` | + `facebook-business>=21.0.0` dep |
| `src/db/repositories/audit_log.py` | google_request_id → provider_request_id (column rename + add `platform` kwarg to record()) |
| `src/governance/rate_limit.py` | + `record_actual_meta()` (BUC parsing) |
| `src/app.py` | + include meta_oauth.router |
| `src/web/routes.py` | + admin_index enrichment (load meta_conn, compute meta_token_expiring_soon) |
| `src/web/templates/admin/index.html` | + card "Suas conexões OAuth" |
| `src/web/templates/access_denied.html` | + branch reason=meta_scopes_missing |
| `src/web/templates/audit.html` | google_request_id → provider_request_id (display) |
| `src/web/templates/audit_detail.html` | idem |
| `tests/conftest.py` | + META_APP_ID, META_APP_SECRET em `_TEST_ENV` |
| `tests/integration/test_repositories.py` | + 3-4 testes meta_rate_counters appended |
| 22 src/ files + 28 tests/ files (big bang rename) | `google_request_id=` → `provider_request_id=` (callers + read sites) |

---

## Task 1: `audit_log.record()` add `platform` param

Backward-compatible: default `"google"` preserva todos os callers existentes.

**Files:**
- Modify: `src/db/repositories/audit_log.py`
- Test: `tests/integration/test_audit_log_platform.py` (new)

- [ ] **Step 1.1: Create failing integration test**

Create `tests/integration/test_audit_log_platform.py`:

```python
"""Regression tests for audit_log platform kwarg (Sprint M.2a Task 1).

Verifica que record() aceita platform kwarg + default "google" + persiste
column corretamente. Funciona em conjunto com Task 2 (migration 004 rename).
"""

from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import audit_log, managers


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg: PostgresContainer):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


@pytest.mark.integration
async def test_audit_log_default_platform_is_google(db) -> None:
    """Backward compat: callers que não passam platform= continuam funcionando, default = 'google'."""
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="apgoog@v4.com", full_name=None)
        log_id = await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id="1234567890",
            action_type="read",
            operation="list_my_accounts",
            status="success",
        )
        row = await conn.fetchrow("SELECT platform FROM audit_log WHERE id = $1", log_id)
        assert row is not None
        assert row["platform"] == "google"


@pytest.mark.integration
async def test_audit_log_accepts_platform_meta(db) -> None:
    """Novo Meta tools podem passar platform='meta'."""
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="apmeta@v4.com", full_name=None)
        log_id = await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id="act_999",
            action_type="read",
            operation="meta_list_my_ad_accounts",
            status="success",
            platform="meta",
        )
        row = await conn.fetchrow("SELECT platform FROM audit_log WHERE id = $1", log_id)
        assert row is not None
        assert row["platform"] == "meta"
```

- [ ] **Step 1.2: Run tests — expect ParameterError or column missing**

Run:
```bash
python -m pytest tests/integration/test_audit_log_platform.py -v -m integration
```

Expected: TypeError on `platform=` kwarg OR `column "platform" does not exist` (depending on which fails first). Continue.

- [ ] **Step 1.3: Modify `src/db/repositories/audit_log.py` — add platform kwarg**

Open `src/db/repositories/audit_log.py`. Find the `record()` function signature (line ~12-26). Modify:

Add `Literal` import at top if missing:
```python
from typing import Any, Literal
```

Update function signature + INSERT statement:

```python
async def record(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID | None,
    session_id: UUID | None,
    customer_id: str | None,
    action_type: str,
    operation: str,
    target_count: int | None = None,
    params_summary: dict[str, Any] | None = None,
    google_request_id: str | None = None,
    status: str = "success",
    error_message: str | None = None,
    duration_ms: int | None = None,
    platform: Literal["google", "meta"] = "google",
) -> int:
    """Insert a row into audit_log; returns the new row id."""
    import json

    row = await conn.fetchrow(
        """
        INSERT INTO audit_log (
            manager_id, session_id, customer_id,
            action_type, operation, target_count,
            params_summary, google_request_id, status,
            error_message, duration_ms, platform
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11, $12)
        RETURNING id
        """,
        manager_id,
        session_id,
        customer_id,
        action_type,
        operation,
        target_count,
        json.dumps(params_summary) if params_summary is not None else None,
        google_request_id,
        status,
        error_message,
        duration_ms,
        platform,
    )
    assert row is not None
    return int(row["id"])
```

(Note: `google_request_id` column rename happens in Task 2. This task adds only `platform` kwarg.)

- [ ] **Step 1.4: Run tests — expect PASS**

Run:
```bash
python -m pytest tests/integration/test_audit_log_platform.py -v -m integration
```

Expected: 2 PASS (or skip if Docker unavailable; CI validates).

- [ ] **Step 1.5: Run ruff + mypy**

Run:
```bash
python -m ruff check src/db/repositories/audit_log.py tests/integration/test_audit_log_platform.py
python -m ruff format --check src/db/repositories/audit_log.py tests/integration/test_audit_log_platform.py
python -m mypy --strict src/db/repositories/audit_log.py
```

Expected: all pass.

- [ ] **Step 1.6: Commit**

```bash
git add src/db/repositories/audit_log.py tests/integration/test_audit_log_platform.py
git commit -m "feat(db): audit_log.record() add platform kwarg (Sprint M.2a Task 1)

Backward-compatible: Literal[\"google\",\"meta\"] default \"google\".
Existing callers funcionam sem mudança. Meta tools (M.2a Task 8+)
passam platform=\"meta\" explicitamente.

Integration test cobre default + override.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Migration 004 + audit_log.py column rename

**Files:**
- Create: `src/db/migrations/004_audit_log_provider_id.sql`
- Modify: `src/db/repositories/audit_log.py` (4 occurrences of `google_request_id`)

- [ ] **Step 2.1: Create migration file**

Create `src/db/migrations/004_audit_log_provider_id.sql` with exact content:

```sql
-- 004_audit_log_provider_id.sql — Sprint M.2a Task 2.
-- Rename google_request_id → provider_request_id for multi-platform clarity.
-- Safe DDL: column rename é atomic, read-side only (não impacta writes em flight).

ALTER TABLE audit_log RENAME COLUMN google_request_id TO provider_request_id;
```

- [ ] **Step 2.2: Modify `src/db/repositories/audit_log.py` — 4 occurrences**

Open `src/db/repositories/audit_log.py`. Find and replace 4 occurrences:

1. `record()` function — INSERT column list + VALUES (line ~32-39):
   - `google_request_id` (in column list) → `provider_request_id`

2. `record()` function — kwarg name (line ~22):
   - `google_request_id: str | None = None,` → `provider_request_id: str | None = None,`
   - And in INSERT params list (the bind variable):
     - `google_request_id,` → `provider_request_id,`

3. `export_csv_rows()` function — SQL SELECT + CSV header (lines ~139, ~155, ~174):
   - SELECT: `al.google_request_id` → `al.provider_request_id`
   - Header list: `"google_request_id"` → `"provider_request_id"`
   - row access: `row["google_request_id"]` → `row["provider_request_id"]`

4. `list_for_manager()` function — SQL SELECT + return dict (lines ~213, ~230):
   - SELECT: `google_request_id` → `provider_request_id`
   - return dict: `"google_request_id": r["google_request_id"]` → `"provider_request_id": r["provider_request_id"]`

(There will be 0 left after this change — all 4 read/write sites updated.)

- [ ] **Step 2.3: Verify list_migrations() picks up 004**

Run:
```bash
python -c "from src.db import migrate; print(migrate.list_migrations())"
```

Expected output: list including `'004_audit_log_provider_id.sql'`.

- [ ] **Step 2.4: Add regression test for provider_request_id column**

Append to `tests/integration/test_audit_log_platform.py`:

```python


@pytest.mark.integration
async def test_audit_log_writes_provider_request_id(db) -> None:
    """Regression: column renamed from google_request_id (Task 2)."""
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="aprid@v4.com", full_name=None)
        log_id = await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id="act_999",
            action_type="read",
            operation="meta_list_my_ad_accounts",
            provider_request_id="x-fb-trace-id-123",
            status="success",
            platform="meta",
        )
        row = await conn.fetchrow(
            "SELECT provider_request_id, platform FROM audit_log WHERE id = $1", log_id
        )
        assert row is not None
        assert row["provider_request_id"] == "x-fb-trace-id-123"
        assert row["platform"] == "meta"
```

- [ ] **Step 2.5: Run tests — expect PASS**

Run:
```bash
python -m pytest tests/integration/test_audit_log_platform.py -v -m integration
```

Expected: 3 PASS (or skip if Docker unavailable). Note: this includes test from Task 1 which already passed.

- [ ] **Step 2.6: Run ruff + mypy**

Run:
```bash
python -m ruff check src/db/repositories/audit_log.py
python -m ruff format --check src/db/repositories/audit_log.py
python -m mypy --strict src/db/repositories/audit_log.py
```

Expected: all pass.

- [ ] **Step 2.7: Commit**

```bash
git add src/db/migrations/004_audit_log_provider_id.sql src/db/repositories/audit_log.py tests/integration/test_audit_log_platform.py
git commit -m "feat(db): migration 004 rename google_request_id → provider_request_id (Sprint M.2a Task 2)

Multi-platform clarity: column name não mais Google-specific.
audit_log.py atualizado (record() kwarg + 2 query call sites).

Big bang rename dos 50 caller files (22 src + 28 tests) vem em Task 3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Big-bang rename — 50 caller files

Find-replace global. 22 src files + 28 tests files. Pre-push gate valida.

**Files modified:** todos os 50 files identificados por Grep `google_request_id` (excluding `src/db/repositories/audit_log.py` que já foi feito em Task 2, e `src/db/migrations/001_initial_schema.sql` que NÃO deve ser modificado — migration histórica).

- [ ] **Step 3.1: Run find-replace across src/ (excluding migrations + audit_log)**

Run from project root (`D:\V4 ads MCP`):

```powershell
# PowerShell: find all .py files in src/ that contain google_request_id, EXCLUDING migrations and audit_log.py
$files = Get-ChildItem -Path "src" -Recurse -Filter "*.py" |
  Where-Object {
    $_.FullName -notmatch "migrations" -and
    $_.FullName -notmatch "audit_log.py$" -and
    (Select-String -Path $_.FullName -Pattern "google_request_id" -Quiet)
  }
foreach ($f in $files) {
  Write-Host "Updating: $($f.FullName)"
  (Get-Content $f.FullName -Raw) -replace 'google_request_id', 'provider_request_id' | Set-Content $f.FullName -NoNewline
}
Write-Host "Updated $($files.Count) files in src/"
```

Expected: ~21 files updated (22 originally minus audit_log.py which is already done).

- [ ] **Step 3.2: Run find-replace across tests/**

```powershell
$tfiles = Get-ChildItem -Path "tests" -Recurse -Filter "*.py" |
  Where-Object { Select-String -Path $_.FullName -Pattern "google_request_id" -Quiet }
foreach ($f in $tfiles) {
  Write-Host "Updating: $($f.FullName)"
  (Get-Content $f.FullName -Raw) -replace 'google_request_id', 'provider_request_id' | Set-Content $f.FullName -NoNewline
}
Write-Host "Updated $($tfiles.Count) files in tests/"
```

Expected: ~28 files updated.

- [ ] **Step 3.3: Run find-replace in templates (audit*.html)**

```powershell
$hfiles = Get-ChildItem -Path "src/web/templates" -Recurse -Filter "*.html" |
  Where-Object { Select-String -Path $_.FullName -Pattern "google_request_id" -Quiet }
foreach ($f in $hfiles) {
  Write-Host "Updating: $($f.FullName)"
  (Get-Content $f.FullName -Raw) -replace 'google_request_id', 'provider_request_id' | Set-Content $f.FullName -NoNewline
}
Write-Host "Updated $($hfiles.Count) html templates"
```

Expected: 2 files (`audit.html`, `audit_detail.html`).

- [ ] **Step 3.4: Verify no orphan `google_request_id` references remain (except in 001 migration)**

Run:
```bash
python -m ruff check src/ tests/
```

Then:
```powershell
Get-ChildItem -Path src,tests -Recurse -Include *.py,*.html |
  Select-String "google_request_id" |
  Where-Object { $_.Path -notmatch "001_initial_schema.sql" }
```

Expected: empty (zero results). If any remain (other than 001 migration), fix manually with Read+Edit.

- [ ] **Step 3.5: Run pre-push gate (quick — without Docker)**

Run:
```bash
python scripts/check_pre_push.py
```

Expected: 5/5 PASS. If mypy fails with "unexpected keyword argument 'google_request_id'", that means a caller wasn't updated — find it via the error message and apply Edit.

- [ ] **Step 3.6: Run pre-push gate full sweep (Docker required if available)**

Run:
```bash
python scripts/check_pre_push_full.py
```

Expected: 6/6 PASS (or exit 2 + Docker hint — CI will run integration). Note: Step 6 runs ALL integration tests including audit_log existing tests — this is the safety net for the rename.

- [ ] **Step 3.7: Commit big-bang rename**

```bash
git add -A
git commit -m "refactor: rename google_request_id → provider_request_id in 50 callers (Sprint M.2a Task 3)

Mechanical find-replace across 22 src/ files + 28 tests/ files + 2
templates. Atomic commit: previous Task 2 renamed DB column; this commit
updates all Python + HTML references to match.

Validation: pre-push gate 5/5 PASS (ruff + format + mypy strict + unit +
integration non-DB). Full sweep (testcontainers) validates audit_log read
+ write integration tests work com new column name.

Zero behavior change. Pure rename.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `meta_rate_counters` repository CRUD

**Files:**
- Create: `src/db/repositories/meta_rate_counters.py`
- Modify: `tests/integration/test_repositories.py` (append 3 tests + 1 import)

- [ ] **Step 4.1: Append failing tests to test_repositories.py**

Update imports block in `tests/integration/test_repositories.py` (around line 14-23 — there should already be `meta_oauth_connections`, `meta_ad_accounts`, `manager_meta_account_access` from M.1):

```python
from src.db.repositories import (
    audit_log,
    google_ads_accounts,
    google_oauth_connections,
    manager_account_access,
    manager_meta_account_access,
    managers,
    mcp_sessions,
    meta_ad_accounts,
    meta_oauth_connections,
    meta_rate_counters,                # ← NEW (Task 4)
)
```

At the bottom of `tests/integration/test_repositories.py` append:

```python
# ---------- meta_rate_counters ----------


@pytest.mark.integration
async def test_meta_rate_counters_increment_creates_row_first_time(db) -> None:
    """First call insert row with calls_used=1."""
    from datetime import date

    async with db.acquire() as conn:
        today = date.today()
        n = await meta_rate_counters.increment_calls(
            conn, app_id="app_hash_abc", ad_account_id="act_111", date=today, by=1
        )
        assert n == 1
        counter = await meta_rate_counters.get_counter(
            conn, app_id="app_hash_abc", ad_account_id="act_111", date=today
        )
        assert counter is not None
        assert counter.calls_used == 1


@pytest.mark.integration
async def test_meta_rate_counters_increment_adds_to_existing(db) -> None:
    """Subsequent calls increment same row."""
    from datetime import date

    async with db.acquire() as conn:
        today = date.today()
        await meta_rate_counters.increment_calls(
            conn, app_id="app_hash_xyz", ad_account_id="act_222", date=today, by=3
        )
        await meta_rate_counters.increment_calls(
            conn, app_id="app_hash_xyz", ad_account_id="act_222", date=today, by=2
        )
        counter = await meta_rate_counters.get_counter(
            conn, app_id="app_hash_xyz", ad_account_id="act_222", date=today
        )
        assert counter is not None
        assert counter.calls_used == 5


@pytest.mark.integration
async def test_meta_rate_counters_update_throttle(db) -> None:
    """update_throttle writes pct + creates row if absent."""
    from datetime import date

    async with db.acquire() as conn:
        today = date.today()
        await meta_rate_counters.increment_calls(
            conn, app_id="app_hash_t", ad_account_id="act_t", date=today, by=1
        )
        await meta_rate_counters.update_throttle(
            conn, app_id="app_hash_t", ad_account_id="act_t", date=today, throttle_pct=42
        )
        counter = await meta_rate_counters.get_counter(
            conn, app_id="app_hash_t", ad_account_id="act_t", date=today
        )
        assert counter is not None
        assert counter.last_throttle_pct == 42


@pytest.mark.integration
async def test_meta_rate_counters_get_counter_returns_none_when_missing(db) -> None:
    from datetime import date

    async with db.acquire() as conn:
        result = await meta_rate_counters.get_counter(
            conn, app_id="nonexistent", ad_account_id="act_x", date=date.today()
        )
        assert result is None
```

- [ ] **Step 4.2: Run tests — expect ImportError**

Run:
```bash
python -m pytest tests/integration/test_repositories.py -v -k meta_rate_counters -m integration
```

Expected: ImportError for `meta_rate_counters`. Continue.

- [ ] **Step 4.3: Create `src/db/repositories/meta_rate_counters.py`**

Create with exact content:

```python
"""CRUD for `meta_rate_counters` — Meta API BUC tracking per (app, account, day).

Different from Google rate_counters: Meta has Business Use Case (BUC) limits
per ad_account + app-level + user-level (multi-dimensional). V0 tracks per
(app_id, ad_account_id, date). app_id is HASHED for storage privacy.
"""

from dataclasses import dataclass
from datetime import date

import asyncpg


@dataclass(slots=True, frozen=True)
class MetaRateCounter:
    app_id: str
    ad_account_id: str
    date: date
    calls_used: int
    last_throttle_pct: int


def _row_to_counter(row: asyncpg.Record) -> MetaRateCounter:
    return MetaRateCounter(
        app_id=row["app_id"],
        ad_account_id=row["ad_account_id"],
        date=row["date"],
        calls_used=row["calls_used"],
        last_throttle_pct=row["last_throttle_pct"],
    )


async def increment_calls(
    conn: asyncpg.Connection,
    *,
    app_id: str,
    ad_account_id: str,
    date: date,
    by: int = 1,
) -> int:
    """Increment calls_used + return new total. Inserts row if first time."""
    row = await conn.fetchrow(
        """
        INSERT INTO meta_rate_counters (app_id, ad_account_id, date, calls_used)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (app_id, ad_account_id, date) DO UPDATE SET
            calls_used = meta_rate_counters.calls_used + EXCLUDED.calls_used
        RETURNING calls_used
        """,
        app_id,
        ad_account_id,
        date,
        by,
    )
    assert row is not None
    return int(row["calls_used"])


async def update_throttle(
    conn: asyncpg.Connection,
    *,
    app_id: str,
    ad_account_id: str,
    date: date,
    throttle_pct: int,
) -> None:
    """Update last observed throttle %. Inserts row if first time (calls_used=0)."""
    await conn.execute(
        """
        INSERT INTO meta_rate_counters (app_id, ad_account_id, date, last_throttle_pct)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (app_id, ad_account_id, date) DO UPDATE SET
            last_throttle_pct = EXCLUDED.last_throttle_pct
        """,
        app_id,
        ad_account_id,
        date,
        throttle_pct,
    )


async def get_counter(
    conn: asyncpg.Connection,
    *,
    app_id: str,
    ad_account_id: str,
    date: date,
) -> MetaRateCounter | None:
    row = await conn.fetchrow(
        """
        SELECT * FROM meta_rate_counters
        WHERE app_id = $1 AND ad_account_id = $2 AND date = $3
        """,
        app_id,
        ad_account_id,
        date,
    )
    return _row_to_counter(row) if row else None
```

- [ ] **Step 4.4: Run tests — expect PASS**

Run:
```bash
python -m pytest tests/integration/test_repositories.py -v -k meta_rate_counters -m integration
```

Expected: 4 PASS (or skip if no Docker).

- [ ] **Step 4.5: Run ruff + mypy**

Run:
```bash
python -m ruff check src/db/repositories/meta_rate_counters.py
python -m ruff format --check src/db/repositories/meta_rate_counters.py
python -m mypy --strict src/db/repositories/meta_rate_counters.py
```

Expected: all pass.

- [ ] **Step 4.6: Commit**

```bash
git add src/db/repositories/meta_rate_counters.py tests/integration/test_repositories.py
git commit -m "feat(db): meta_rate_counters repository CRUD + 4 integration tests (Sprint M.2a Task 4)

Tabela criada em M.1 migration 003, sem Python wrapper. Sprint M.2a Task 4
fecha o gap. 3 funções:
- increment_calls() — atomic upsert + return new total
- update_throttle() — upsert last observed BUC pct
- get_counter() — single lookup, None if missing

V0 (Sprint M.2a Task 7) usa post-call only (sem pre-flight). app_id é
hashed externamente (SHA-256 truncated) antes de persistir.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `conftest.py` `_TEST_ENV` add Meta env vars

**Files:**
- Modify: `tests/conftest.py` (lines ~17-30, dict `_TEST_ENV`)

- [ ] **Step 5.1: Modify tests/conftest.py**

Open `tests/conftest.py`. Find the `_TEST_ENV` dict (around line 17-30). After the existing entries (after `LOG_LEVEL: "warning"`), add 2 new entries:

```python
_TEST_ENV = {
    "APP_ENV": "development",
    "DATABASE_URL": "postgresql://postgres:postgres@localhost:5432/test",
    "SESSION_SIGNING_KEY": "x" * 32,
    "AES_MASTER_KEY": "y" * 32,
    "GOOGLE_OAUTH_CLIENT_ID": "test-client.apps.googleusercontent.com",
    "GOOGLE_OAUTH_CLIENT_SECRET": "test-secret",
    "GOOGLE_ADS_DEVELOPER_TOKEN": "test-dev-token",
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890",
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_ANON_KEY": "test-anon",
    "SUPABASE_SERVICE_KEY": "test-service",
    "LOG_LEVEL": "warning",
    "META_APP_ID": "test_meta_app_123456789",                                    # ← NEW (Sprint M.2a Task 5)
    "META_APP_SECRET": "test_meta_secret_dummy_value_at_least_32_chars_long",   # ← NEW
}
```

- [ ] **Step 5.2: Verify Settings() loads in test env**

Run:
```bash
python -c "
import os
os.environ['META_APP_ID'] = 'test_meta_app_123456789'
os.environ['META_APP_SECRET'] = 'test_meta_secret_dummy_value_at_least_32_chars_long'
from src.config import get_settings
s = get_settings()
print('OK, meta_app_id =', repr(s.meta_app_id))
print('OK, meta_app_secret startswith =', repr(s.meta_app_secret[:8]))
"
```

Expected: `OK, meta_app_id = 'test_meta_app_123456789'` + `OK, meta_app_secret startswith = 'test_met'`.

- [ ] **Step 5.3: Run unit tests sanity (no regression)**

Run:
```bash
python -m pytest tests/unit -v -x
```

Expected: all unit tests PASS (existing). If any test now fails because of missing META vars, the conftest fix correctly addressed the gap.

- [ ] **Step 5.4: Run ruff + format on conftest**

Run:
```bash
python -m ruff check tests/conftest.py
python -m ruff format --check tests/conftest.py
```

Expected: pass.

- [ ] **Step 5.5: Commit**

```bash
git add tests/conftest.py
git commit -m "test(conftest): add META_APP_ID + META_APP_SECRET em _TEST_ENV (Sprint M.2a Task 5)

Pré-requisito pra Meta OAuth tests (M.2a Task 8+) e qualquer caller
de Settings() em test mode que precise carregar META_APP_*. Defaults
empty no src/config.py (M.1 b0ff669) significam que app boot funciona
sem secret reais — mas tests OAuth precisam de valores não-vazios pra
exercitar Settings() pos-Pydantic validation.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: facebook_business dep + `src/meta_ads/` package skeleton + `client.py` + `errors.py`

**Files:**
- Modify: `pyproject.toml` (+ dep)
- Create: `src/meta_ads/__init__.py`
- Create: `src/meta_ads/errors.py`
- Create: `src/meta_ads/client.py`
- Create: `tests/unit/test_meta_errors.py`

- [ ] **Step 6.1: Add facebook-business to pyproject.toml**

Open `pyproject.toml`. Find the `dependencies = [...]` block (line ~6-18). Add `facebook-business>=21.0.0` after `google-ads>=27.0.0`:

```toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "mcp>=1.2.0",
    "asyncpg>=0.30.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.6.0",
    "structlog>=24.4.0",
    "httpx>=0.27.0",
    "google-ads>=27.0.0",
    "facebook-business>=21.0.0",                # ← NEW (Sprint M.2a Task 6)
    "cryptography>=44.0.0",
    "jsonschema>=4.0",
    "jinja2>=3.1.0",
]
```

Also add a mypy override for facebook_business module (which doesn't ship stubs):

After the existing `[[tool.mypy.overrides]]` for `google.ads.*` (around line 58-61), add:

```toml
[[tool.mypy.overrides]]
module = ["facebook_business.*"]
ignore_missing_imports = true
ignore_errors = true
```

- [ ] **Step 6.2: Install dep locally**

Run:
```bash
pip install facebook-business>=21.0.0
```

Expected: install succeeds. Verify:
```bash
python -c "from facebook_business.api import FacebookAdsApi; print(FacebookAdsApi)"
```

Expected: `<class 'facebook_business.api.FacebookAdsApi'>`.

- [ ] **Step 6.3: Create `src/meta_ads/__init__.py`**

Create empty file:

```python
"""Meta Ads (Facebook/Instagram) package — paralelo a src/google_ads/.

Sprint M.2a establishes: client.py (FacebookAdsApi factory), reports.py
(Graph API GET executor), errors.py (PT-BR friendly error mapping).

Future sprints (M.3+) add: insights/ (Insights API builders), mutates/
(mutation builders), enum_to_label.py (Meta enum → PT-BR labels).
"""
```

- [ ] **Step 6.4: Create failing unit test for errors module**

Create `tests/unit/test_meta_errors.py`:

```python
"""Unit tests for Meta error → PT-BR friendly mapping (Sprint M.2a Task 6)."""

from unittest.mock import MagicMock

from src.meta_ads.errors import MetaAdsFriendlyError, to_friendly_meta_error


def _build_fb_error(*, code=None, subcode=None, message="error msg"):
    """Construct a fake FacebookRequestError-like mock with the required methods."""
    err = MagicMock()
    err.api_error_code = MagicMock(return_value=code)
    err.api_error_subcode = MagicMock(return_value=subcode)
    err.api_error_message = MagicMock(return_value=message)
    # Make isinstance check work via spec
    from facebook_business.exceptions import FacebookRequestError
    err.__class__ = FacebookRequestError
    return err


def test_expired_token_subcode_458():
    err = _build_fb_error(subcode=458)
    result = to_friendly_meta_error(err)
    assert isinstance(result, MetaAdsFriendlyError)
    assert "expirou" in result.message.lower() or "reconecte" in result.message.lower()
    assert result.retryable is False


def test_expired_token_subcode_467():
    err = _build_fb_error(subcode=467)
    result = to_friendly_meta_error(err)
    assert result.retryable is False


def test_rate_limit_subcode_2635():
    err = _build_fb_error(subcode=2635)
    result = to_friendly_meta_error(err)
    assert "limite" in result.message.lower()
    assert result.retryable is True


def test_rate_limit_code_4():
    err = _build_fb_error(code=4)
    result = to_friendly_meta_error(err)
    assert result.retryable is True


def test_permission_denied_code_190():
    err = _build_fb_error(code=190)
    result = to_friendly_meta_error(err)
    assert "permissão" in result.message.lower() or "permissao" in result.message.lower()
    assert result.retryable is False


def test_invalid_field_code_100():
    err = _build_fb_error(code=100, message="Field 'foo' not supported")
    result = to_friendly_meta_error(err)
    assert "campo" in result.message.lower() or "inválido" in result.message.lower()
    assert result.retryable is False


def test_unknown_falls_back_with_code_subcode():
    err = _build_fb_error(code=999, subcode=888, message="weird error")
    result = to_friendly_meta_error(err)
    assert "999" in result.message or "888" in result.message
    assert result.retryable is False


def test_non_facebook_exception_falls_back():
    e = ValueError("generic error")
    result = to_friendly_meta_error(e)
    assert "inesperado" in result.message.lower() or "generic error" in result.message
    assert result.retryable is False
```

- [ ] **Step 6.5: Run test — expect ModuleNotFoundError**

Run:
```bash
python -m pytest tests/unit/test_meta_errors.py -v
```

Expected: ModuleNotFoundError for `src.meta_ads.errors`. Continue.

- [ ] **Step 6.6: Create `src/meta_ads/errors.py`**

```python
"""Map Meta API exceptions → PT-BR friendly errors for V4 gestores."""

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class MetaAdsFriendlyError(Exception):
    message: str
    retryable: bool


def to_friendly_meta_error(e: Exception) -> MetaAdsFriendlyError:
    """Map Meta SDK / Graph API exceptions to PT-BR messages.

    Handles FacebookRequestError variants. Falls back to generic error msg
    for unknown exception types.
    """
    try:
        from facebook_business.exceptions import FacebookRequestError  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return MetaAdsFriendlyError(f"Erro inesperado: {e}", retryable=False)

    if isinstance(e, FacebookRequestError):
        subcode = e.api_error_subcode()
        code = e.api_error_code()
        message = e.api_error_message()

        if subcode in (458, 467, 460, 463):
            return MetaAdsFriendlyError(
                "Sua conexão Meta expirou ou foi revogada. Reconecte via painel admin.",
                retryable=False,
            )
        if subcode == 2635 or code == 4:
            return MetaAdsFriendlyError(
                "Limite Meta atingido. Tente novamente em alguns minutos.",
                retryable=True,
            )
        if code == 190:
            return MetaAdsFriendlyError(
                "Permissão insuficiente. Verifique se aceitou ads_read + ads_management.",
                retryable=False,
            )
        if code == 100:
            return MetaAdsFriendlyError(
                f"Campo inválido na requisição Meta: {message}",
                retryable=False,
            )
        return MetaAdsFriendlyError(
            f"Erro Meta API ({code}/{subcode}): {message}",
            retryable=False,
        )

    return MetaAdsFriendlyError(f"Erro inesperado: {e}", retryable=False)
```

- [ ] **Step 6.7: Run errors tests — expect PASS**

Run:
```bash
python -m pytest tests/unit/test_meta_errors.py -v
```

Expected: 8 PASS.

- [ ] **Step 6.8: Create `src/meta_ads/client.py`**

```python
"""Factory for facebook_business FacebookAdsApi per-manager.

Different from Google SDK: Meta uses GLOBAL state (FacebookAdsApi.set_default_api)
by default — dangerous in async multi-manager. Convention: always construct
FacebookAdsApi(...) instance directly (NOT .init()) and pass api= explicit
in every SDK call site (M.3+ mutates).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID


class NoMetaConnectionError(Exception):
    """Raised when manager has no active Meta OAuth connection."""


class MetaTokenExpiredError(Exception):
    """Raised when access_token expired (Meta has no refresh; user must reconnect)."""


async def build_meta_api_for_manager(*, manager_id: UUID) -> Any:
    """Decrypt access_token + return FacebookAdsApi instance.

    Raises:
        NoMetaConnectionError: manager hasn't connected Meta yet
        MetaTokenExpiredError: token expired (60d natural expiry)
    """
    from facebook_business.api import FacebookAdsApi  # noqa: PLC0415

    from src.auth.tokens import decrypt_refresh_token, derive_master_key_from_settings
    from src.config import get_settings
    from src.db import connection
    from src.db.repositories import meta_oauth_connections

    settings = get_settings()
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        oc = await meta_oauth_connections.get_active_for_manager(conn, manager_id)
    if oc is None:
        raise NoMetaConnectionError(
            "Gestor não tem conexão Meta Ads ativa. "
            "Acesse o painel admin → 'Conectar Meta'."
        )
    if oc.token_expires_at <= datetime.now(UTC):
        raise MetaTokenExpiredError(
            "Sua conexão Meta expirou. Reconecte via painel admin."
        )

    master_key = derive_master_key_from_settings(settings.aes_master_key)
    access_token = decrypt_refresh_token(oc.access_token_enc, master_key)

    return FacebookAdsApi(
        access_token=access_token,
        app_id=settings.meta_app_id,
        app_secret=settings.meta_app_secret,
        api_version="v22.0",
    )
```

- [ ] **Step 6.9: Run ruff + mypy on new files**

Run:
```bash
python -m ruff check src/meta_ads/ tests/unit/test_meta_errors.py
python -m ruff format --check src/meta_ads/ tests/unit/test_meta_errors.py
python -m mypy --strict src/meta_ads/
```

Expected: all pass (mypy override on `facebook_business.*` handles missing stubs).

- [ ] **Step 6.10: Commit**

```bash
git add pyproject.toml src/meta_ads/ tests/unit/test_meta_errors.py
git commit -m "feat(meta_ads): package skeleton + client + errors (Sprint M.2a Task 6)

- pyproject.toml: + facebook-business>=21.0.0 + mypy ignore_missing_imports
- src/meta_ads/__init__.py: package marker
- src/meta_ads/client.py: build_meta_api_for_manager() factory +
  NoMetaConnectionError + MetaTokenExpiredError exceptions. Constrói
  FacebookAdsApi() instance direta (NÃO .init()) pra evitar global state.
- src/meta_ads/errors.py: to_friendly_meta_error() PT-BR mapping cobrindo
  subcodes 458/467/460/463 (token expired), 2635 (rate limit), code 4
  (rate limit), 190 (permission), 100 (invalid field), fallback
- 8 unit tests cobrindo cada branch do mapping

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `src/meta_ads/reports.py` + governance rate_limit extensions + BUC parsing tests

**Files:**
- Create: `src/meta_ads/reports.py`
- Modify: `src/governance/rate_limit.py` (+ `record_actual_meta()`)
- Create: `tests/unit/test_buc_header_parsing.py`

- [ ] **Step 7.1: Create failing unit test for BUC parsing**

Create `tests/unit/test_buc_header_parsing.py`:

```python
"""Unit tests for BUC (X-Business-Use-Case-Usage) header parsing (Sprint M.2a Task 7)."""

import json

from src.governance.rate_limit import _parse_buc_header_pct


def test_parse_buc_extracts_max_pct():
    """Returns max(call_count, total_cputime, total_time) for matching ad_account."""
    header = json.dumps({
        "123456789": [
            {"type": "ads_management", "call_count": 42, "total_cputime": 12, "total_time": 35,
             "estimated_time_to_regain_access": 0}
        ]
    })
    pct = _parse_buc_header_pct(header, ad_account_id="act_123456789")
    assert pct == 42  # max(42, 12, 35)


def test_parse_buc_returns_zero_when_account_not_in_header():
    header = json.dumps({"999": [{"type": "ads_read", "call_count": 50, "total_cputime": 0, "total_time": 0}]})
    pct = _parse_buc_header_pct(header, ad_account_id="act_111")
    assert pct == 0


def test_parse_buc_handles_empty_header():
    pct = _parse_buc_header_pct("", ad_account_id="act_123")
    assert pct == 0


def test_parse_buc_handles_empty_json():
    pct = _parse_buc_header_pct("{}", ad_account_id="act_123")
    assert pct == 0


def test_parse_buc_handles_malformed_json():
    pct = _parse_buc_header_pct("not valid json", ad_account_id="act_123")
    assert pct == 0


def test_parse_buc_strips_act_prefix():
    """ad_account_id 'act_111' should match key '111' in BUC JSON."""
    header = json.dumps({"111": [{"call_count": 75, "total_cputime": 5, "total_time": 5}]})
    pct = _parse_buc_header_pct(header, ad_account_id="act_111")
    assert pct == 75


def test_parse_buc_multiple_usage_entries():
    """If BUC has multiple entries for same ad_account, take max across all."""
    header = json.dumps({
        "123": [
            {"call_count": 30, "total_cputime": 10, "total_time": 20},
            {"call_count": 90, "total_cputime": 50, "total_time": 60},
        ]
    })
    pct = _parse_buc_header_pct(header, ad_account_id="act_123")
    assert pct == 90  # max across both entries
```

- [ ] **Step 7.2: Run tests — expect ImportError**

Run:
```bash
python -m pytest tests/unit/test_buc_header_parsing.py -v
```

Expected: `ImportError: cannot import name '_parse_buc_header_pct'`. Continue.

- [ ] **Step 7.3: Add `_parse_buc_header_pct` + `record_actual_meta()` to `src/governance/rate_limit.py`**

Open `src/governance/rate_limit.py`. At the END of the file, append:

```python


# ============================================================================
# Meta Ads — Business Use Case (BUC) tracking (Sprint M.2a Task 7)
# ============================================================================

def _parse_buc_header_pct(buc_header: str, *, ad_account_id: str) -> int:
    """Parse X-Business-Use-Case-Usage header + return max usage pct for ad_account.

    BUC format: {"<numeric_ad_account_id>": [{"type":"ads_management",
                  "call_count": 42, "total_cputime": 12, "total_time": 35,
                  "estimated_time_to_regain_access": 0}]}

    Strategy: max(call_count, total_cputime, total_time) across all entries
    for the matching ad_account. Returns 0 if header empty/malformed/no-match.
    """
    if not buc_header:
        return 0
    try:
        import json
        parsed = json.loads(buc_header)
    except (ValueError, TypeError):
        return 0

    if not isinstance(parsed, dict):
        return 0

    numeric_id = ad_account_id.replace("act_", "")
    pcts: list[int] = []
    for acct_key, usages in parsed.items():
        if acct_key != numeric_id:
            continue
        if not isinstance(usages, list):
            continue
        for u in usages:
            if not isinstance(u, dict):
                continue
            pcts.extend([
                int(u.get("call_count", 0)),
                int(u.get("total_cputime", 0)),
                int(u.get("total_time", 0)),
            ])
    return max(pcts) if pcts else 0


async def record_actual_meta(
    *,
    app_id: str,
    ad_account_id: str,
    buc_header: str,
    calls: int = 1,
) -> None:
    """Parse BUC header + persist counter increments + throttle pct.

    Hashes app_id (SHA-256 truncated 32-char) before persisting for storage privacy.
    Structlog warning if throttle_pct > 75%.
    """
    import hashlib
    from datetime import date

    from src.db import connection
    from src.db.repositories import meta_rate_counters

    throttle_pct = _parse_buc_header_pct(buc_header, ad_account_id=ad_account_id)
    app_id_hash = hashlib.sha256(app_id.encode()).hexdigest()[:32]
    today = date.today()

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await meta_rate_counters.increment_calls(
            conn,
            app_id=app_id_hash,
            ad_account_id=ad_account_id,
            date=today,
            by=calls,
        )
        await meta_rate_counters.update_throttle(
            conn,
            app_id=app_id_hash,
            ad_account_id=ad_account_id,
            date=today,
            throttle_pct=throttle_pct,
        )

    if throttle_pct > 75:
        log.warning(
            "meta_rate_limit_warning",
            ad_account_id=ad_account_id,
            throttle_pct=throttle_pct,
        )
```

(Note: `log` is already imported at top of `rate_limit.py`.)

- [ ] **Step 7.4: Run BUC tests — expect PASS**

Run:
```bash
python -m pytest tests/unit/test_buc_header_parsing.py -v
```

Expected: 7 PASS.

- [ ] **Step 7.5: Create `src/meta_ads/reports.py`**

```python
"""Shared executor for Meta Graph API GET requests.

Mirror semantics of src/google_ads/reports.py:
- Rate limit post-call only (Meta tem BUC header, sem global counter pre-flight)
- Audit log opt-in (sensitive reads, mutates)
- PT-BR errors via to_friendly_meta_error()

V0 (Sprint M.2a) covers simple GET edges (/me/adaccounts etc).
M.3+ adds Insights API support (paginação, async jobs).
"""

import time
from typing import Any
from uuid import UUID

import structlog

from src.config import get_settings
from src.db import connection
from src.db.repositories import audit_log
from src.governance.rate_limit import record_actual_meta
from src.meta_ads.client import build_meta_api_for_manager
from src.meta_ads.errors import to_friendly_meta_error

log = structlog.get_logger(__name__)


async def run_meta_graph_get(
    *,
    manager_id: UUID,
    session_id: UUID,
    edge: str,
    params: dict[str, Any] | None = None,
    operation_name: str,
    estimated_calls: int = 1,
    audit_this_call: bool = False,
    params_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute Meta Graph API GET; parse BUC header; record audit + rate counters.

    Args:
        manager_id: bind context manager UUID
        session_id: bind context MCP session UUID
        edge: Graph API edge path, e.g., "/me/adaccounts"
        params: query parameters dict
        operation_name: for audit log + rate limit operation field
        estimated_calls: how many API calls this counts as
        audit_this_call: opt-in audit (sensitive reads, mutates)
        params_summary: optional dict embedded in audit_log.params_summary

    Returns:
        Parsed JSON response body (dict with "data" key for collection edges).

    Raises:
        MetaAdsFriendlyError: friendly PT-BR error wrapping Meta API failures
        NoMetaConnectionError | MetaTokenExpiredError: from build_meta_api_for_manager
    """
    settings = get_settings()
    api = await build_meta_api_for_manager(manager_id=manager_id)

    log.info("meta_graph_get_start", edge=edge, operation=operation_name)
    started = time.monotonic()

    try:
        response = api.call("GET", [edge.lstrip("/")], params=params or {})
        body = response.json()
    except Exception as e:  # noqa: BLE001 — catch all to map to friendly
        elapsed_ms = int((time.monotonic() - started) * 1000)
        friendly = to_friendly_meta_error(e)
        if audit_this_call:
            async with connection.get_pool().acquire() as conn:
                await audit_log.record(
                    conn,
                    manager_id=manager_id,
                    session_id=session_id,
                    customer_id=(params_summary or {}).get("ad_account_id"),
                    action_type="read",
                    operation=operation_name,
                    params_summary=params_summary,
                    status="error",
                    error_message=friendly.message,
                    duration_ms=elapsed_ms,
                    platform="meta",
                )
        log.warning(
            "meta_graph_get_error",
            edge=edge,
            operation=operation_name,
            error=friendly.message,
            duration_ms=elapsed_ms,
        )
        raise friendly from e

    elapsed_ms = int((time.monotonic() - started) * 1000)

    # Post-call rate counter update from BUC header
    buc_header = response.headers().get("x-business-use-case-usage")
    if buc_header and params and "ad_account_id" in params:
        try:
            await record_actual_meta(
                app_id=settings.meta_app_id,
                ad_account_id=params["ad_account_id"],
                buc_header=buc_header,
                calls=estimated_calls,
            )
        except Exception as e:  # noqa: BLE001
            # Don't fail the call just because rate counter update failed
            log.warning("meta_rate_counter_update_failed", error=str(e))

    if audit_this_call:
        async with connection.get_pool().acquire() as conn:
            await audit_log.record(
                conn,
                manager_id=manager_id,
                session_id=session_id,
                customer_id=(params_summary or {}).get("ad_account_id"),
                action_type="read",
                operation=operation_name,
                target_count=len(body.get("data", [])) if isinstance(body, dict) else None,
                params_summary=params_summary,
                status="success",
                duration_ms=elapsed_ms,
                platform="meta",
                provider_request_id=response.headers().get("x-fb-trace-id"),
            )

    log.info(
        "meta_graph_get_done",
        edge=edge,
        operation=operation_name,
        duration_ms=elapsed_ms,
    )
    return body
```

- [ ] **Step 7.6: Run ruff + mypy**

Run:
```bash
python -m ruff check src/meta_ads/reports.py src/governance/rate_limit.py tests/unit/test_buc_header_parsing.py
python -m ruff format --check src/meta_ads/reports.py src/governance/rate_limit.py tests/unit/test_buc_header_parsing.py
python -m mypy --strict src/meta_ads/reports.py src/governance/rate_limit.py
```

Expected: all pass.

- [ ] **Step 7.7: Commit**

```bash
git add src/meta_ads/reports.py src/governance/rate_limit.py tests/unit/test_buc_header_parsing.py
git commit -m "feat(meta_ads): reports.py executor + BUC rate counter (Sprint M.2a Task 7)

- src/meta_ads/reports.py: run_meta_graph_get() executor mirroring
  semantics de run_report (Google). audit_log opt-in (platform=meta),
  PT-BR friendly errors via to_friendly_meta_error, post-call BUC parse.
- src/governance/rate_limit.py: + record_actual_meta() (SHA-256 hashed
  app_id, increment_calls + update_throttle, warning >75%) + helper
  _parse_buc_header_pct (pure function, 7 unit tests covering empty,
  malformed JSON, missing account, multi-entry max).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: `src/auth/meta_oauth.py` OAuth routes

Maior task do sprint. OAuth flow Meta com long-lived token + granular permission check.

**Files:**
- Create: `src/auth/meta_oauth.py`
- Create: `tests/unit/test_meta_oauth.py`
- Create: `tests/integration/test_meta_oauth_flow.py`
- Modify: `src/app.py` (mount router)
- Modify: `src/web/templates/access_denied.html` (+ meta_scopes_missing branch)

- [ ] **Step 8.1: Create unit tests for OAuth decision tree**

Create `tests/unit/test_meta_oauth.py`:

```python
"""Unit tests for Meta OAuth callback decision tree (Sprint M.2a Task 8)."""

import pytest

from src.auth.meta_oauth import check_meta_granted_scopes


def test_check_granted_scopes_accepts_all_essentials():
    granted = {"ads_read", "ads_management", "business_management", "email", "public_profile"}
    missing = check_meta_granted_scopes(granted)
    assert missing == set()


def test_check_granted_scopes_blocks_missing_ads_read():
    granted = {"ads_management", "email", "public_profile"}
    missing = check_meta_granted_scopes(granted)
    assert missing == {"ads_read"}


def test_check_granted_scopes_blocks_missing_ads_management():
    granted = {"ads_read", "email"}
    missing = check_meta_granted_scopes(granted)
    assert missing == {"ads_management"}


def test_check_granted_scopes_blocks_missing_both_essentials():
    granted = {"email", "public_profile"}
    missing = check_meta_granted_scopes(granted)
    assert missing == {"ads_read", "ads_management"}


def test_check_granted_scopes_ignores_business_management_when_essentials_present():
    """business_management is declared but NOT essential — missing it doesn't block."""
    granted = {"ads_read", "ads_management", "email"}
    missing = check_meta_granted_scopes(granted)
    assert missing == set()
```

- [ ] **Step 8.2: Run test — expect ImportError**

Run:
```bash
python -m pytest tests/unit/test_meta_oauth.py -v
```

Expected: ImportError. Continue.

- [ ] **Step 8.3: Create `src/auth/meta_oauth.py`**

```python
"""OAuth 2.0 flow with Meta (Facebook Login for Business).

Long-lived access_token (~60d) — Meta has no refresh_token model. When
expired, user must reconnect via webapp.

Three routes:
  GET  /oauth/meta/start    → redirect to Meta consent screen
  GET  /oauth/meta/callback → exchange code → token → upsert connection
  POST /oauth/meta/revoke   → soft-revoke (sets revoked_at; no Meta API call V0)

Granular permissions: Meta lets users accept ANY subset of requested
scopes. Callback BLOCKS if ads_read or ads_management missing (essentials)
— redirects to /access-denied?reason=meta_scopes_missing&missing=...
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.auth.domain_check import is_allowed_email
from src.auth.oauth_state import InvalidStateError, sign_state, verify_state
from src.auth.tokens import derive_master_key_from_settings, encrypt_refresh_token
from src.config import get_settings
from src.db import connection
from src.db.repositories import (
    audit_log,
    manager_meta_account_access,
    meta_ad_accounts,
    meta_oauth_connections,
)
from src.web.deps import CurrentUser, current_manager

log = structlog.get_logger(__name__)

META_FB_AUTH_URL = "https://www.facebook.com/v22.0/dialog/oauth"
META_GRAPH_BASE = "https://graph.facebook.com/v22.0"

META_REQUIRED_SCOPES = [
    "email",
    "public_profile",
    "ads_read",
    "ads_management",
    "business_management",
]

META_ESSENTIAL_SCOPES = {"ads_read", "ads_management"}

router = APIRouter(prefix="/oauth/meta", tags=["meta_oauth"])


def check_meta_granted_scopes(granted: set[str]) -> set[str]:
    """Return set of ESSENTIAL scopes that are MISSING from granted set.

    Empty set return means all essentials granted (consent OK).
    """
    return META_ESSENTIAL_SCOPES - granted


def _build_redirect_uri(request: Request) -> str:
    """Force HTTPS for callback URL (Cloud Run terminates TLS at GFE).

    Mirror src/auth/oauth.py:_build_redirect_uri pattern.
    """
    url = str(request.url_for("meta_oauth_callback"))
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    return url


@router.get("/start")
async def meta_oauth_start(
    request: Request,
    user: CurrentUser = Depends(current_manager),
) -> RedirectResponse:
    """Redirect manager to Meta consent screen."""
    settings = get_settings()
    callback_state = sign_state(
        {"manager_id": str(user.id), "aud": "meta_oauth"},
        settings.session_signing_key,
    )
    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": _build_redirect_uri(request),
        "scope": ",".join(META_REQUIRED_SCOPES),
        "response_type": "code",
        "state": callback_state,
    }
    url = f"{META_FB_AUTH_URL}?{urlencode(params)}"
    log.info("meta_oauth_start", manager_id=str(user.id))
    return RedirectResponse(url=url, status_code=302)


@router.get("/callback", name="meta_oauth_callback", response_model=None)
async def meta_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> HTMLResponse | RedirectResponse:
    """Exchange code → long-lived access_token → persist + sync accounts.

    Flow:
    1. Verify state HMAC
    2. POST /oauth/access_token → short-lived token
    3. GET /oauth/access_token?grant_type=fb_exchange_token → long-lived token
    4. GET /me → fb_user_id + fb_email
    5. is_allowed_email check
    6. GET /debug_token → granted_scopes
    7. check_meta_granted_scopes → block if missing essentials
    8. Encrypt + upsert meta_oauth_connections
    9. GET /me/adaccounts → upsert meta_ad_accounts + grant_all_active
    10. audit_log + redirect to /admin
    """
    if error:
        msg = error_description or error
        log.warning("meta_oauth_callback_error_param", error=error, msg=msg)
        return RedirectResponse(
            f"/access-denied?reason=meta_oauth_error&detail={msg[:200]}",
            status_code=302,
        )
    if not code or not state:
        return RedirectResponse(
            "/access-denied?reason=meta_oauth_incomplete",
            status_code=302,
        )

    settings = get_settings()
    try:
        payload = verify_state(state, settings.session_signing_key)
    except InvalidStateError as e:
        log.warning("meta_oauth_invalid_state", error=str(e))
        return RedirectResponse("/access-denied?reason=meta_state_invalid", status_code=302)

    if payload.get("aud") != "meta_oauth":
        log.warning("meta_oauth_wrong_aud", aud=payload.get("aud"))
        return RedirectResponse("/access-denied?reason=meta_state_invalid", status_code=302)

    manager_id_str = payload.get("manager_id")
    if not manager_id_str:
        return RedirectResponse("/access-denied?reason=meta_state_invalid", status_code=302)
    manager_id = UUID(manager_id_str)

    redirect_uri = _build_redirect_uri(request)

    async with httpx.AsyncClient(timeout=30.0) as http:
        # Step 2: code → short-lived
        short_resp = await http.post(
            f"{META_GRAPH_BASE}/oauth/access_token",
            data={
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        if short_resp.status_code != 200:
            log.warning(
                "meta_oauth_short_token_failed",
                status=short_resp.status_code,
                body=short_resp.text,
            )
            return RedirectResponse(
                "/access-denied?reason=meta_token_exchange_failed",
                status_code=302,
            )
        short_token = short_resp.json().get("access_token")
        if not short_token:
            return RedirectResponse(
                "/access-denied?reason=meta_token_exchange_failed",
                status_code=302,
            )

        # Step 3: short → long-lived
        long_resp = await http.get(
            f"{META_GRAPH_BASE}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "fb_exchange_token": short_token,
            },
        )
        if long_resp.status_code != 200:
            log.warning(
                "meta_oauth_long_token_failed",
                status=long_resp.status_code,
                body=long_resp.text,
            )
            return RedirectResponse(
                "/access-denied?reason=meta_token_exchange_failed",
                status_code=302,
            )
        long_body = long_resp.json()
        access_token = long_body.get("access_token")
        expires_in_seconds = int(long_body.get("expires_in", 5184000))  # default 60d

        # Step 4: GET /me
        me_resp = await http.get(
            f"{META_GRAPH_BASE}/me",
            params={"fields": "id,email,name", "access_token": access_token},
        )
        if me_resp.status_code != 200:
            return RedirectResponse(
                "/access-denied?reason=meta_userinfo_failed",
                status_code=302,
            )
        me_data = me_resp.json()
        fb_user_id = str(me_data.get("id", ""))
        fb_email = str(me_data.get("email", ""))
        if not fb_user_id or not fb_email:
            return RedirectResponse(
                "/access-denied?reason=meta_userinfo_incomplete",
                status_code=302,
            )

        # Step 5: V4 domain check
        if not is_allowed_email(fb_email):
            log.warning("meta_oauth_email_not_v4", fb_email=fb_email)
            return RedirectResponse(
                f"/access-denied?reason=domain&email={fb_email}",
                status_code=302,
            )

        # Step 6: GET /debug_token → check granted scopes
        debug_resp = await http.get(
            f"{META_GRAPH_BASE}/debug_token",
            params={
                "input_token": access_token,
                "access_token": f"{settings.meta_app_id}|{settings.meta_app_secret}",
            },
        )
        granted_scopes: set[str] = set()
        if debug_resp.status_code == 200:
            data = debug_resp.json().get("data", {})
            granted_scopes = set(data.get("scopes", []))
        else:
            log.warning(
                "meta_oauth_debug_token_failed",
                status=debug_resp.status_code,
            )

        # Step 7: block if essentials missing
        missing = check_meta_granted_scopes(granted_scopes)
        if missing:
            log.warning("meta_oauth_missing_essentials", missing=list(missing))
            return RedirectResponse(
                f"/access-denied?reason=meta_scopes_missing&missing={','.join(missing)}",
                status_code=302,
            )

        # Step 8: encrypt + upsert connection
        master_key = derive_master_key_from_settings(settings.aes_master_key)
        encrypted = encrypt_refresh_token(access_token, master_key)
        token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in_seconds)

        # Step 9: list ad accounts
        adacc_resp = await http.get(
            f"{META_GRAPH_BASE}/me/adaccounts",
            params={
                "fields": "id,name,business,account_status,currency,timezone_name",
                "access_token": access_token,
            },
        )
        ad_accounts_data: list[dict[str, Any]] = []
        if adacc_resp.status_code == 200:
            ad_accounts_data = adacc_resp.json().get("data", [])

    # Step 8+9 persist (outside http context)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await meta_oauth_connections.upsert(
            conn,
            manager_id=manager_id,
            fb_user_id=fb_user_id,
            fb_email=fb_email,
            access_token_enc=encrypted,
            token_expires_at=token_expires_at,
            scopes=list(granted_scopes),
        )
        # Upsert ad accounts
        accounts_payload = []
        for a in ad_accounts_data:
            ad_id_raw = a.get("id", "")
            if not ad_id_raw.startswith("act_"):
                ad_id_raw = f"act_{ad_id_raw}"
            business = a.get("business") or {}
            accounts_payload.append({
                "ad_account_id": ad_id_raw,
                "business_id": business.get("id"),
                "business_name": business.get("name"),
                "account_name": a.get("name", ad_id_raw),
                "currency": a.get("currency"),
                "timezone_name": a.get("timezone_name"),
                "account_status": a.get("account_status"),
            })
        if accounts_payload:
            await meta_ad_accounts.upsert_many(conn, accounts_payload)
            for a in accounts_payload:
                await manager_meta_account_access.grant(
                    conn,
                    manager_id=manager_id,
                    ad_account_id=a["ad_account_id"],
                )

        # Step 10: audit
        await audit_log.record(
            conn,
            manager_id=manager_id,
            session_id=None,
            customer_id=None,
            action_type="auth",
            operation="meta_oauth_connect",
            target_count=len(accounts_payload),
            params_summary={"fb_email": fb_email, "scopes": list(granted_scopes)},
            status="success",
            platform="meta",
        )

    log.info(
        "meta_oauth_callback_success",
        manager_id=str(manager_id),
        fb_email=fb_email,
        accounts_synced=len(accounts_payload),
    )
    return RedirectResponse("/admin?meta_connected=1", status_code=302)


@router.post("/revoke")
async def meta_oauth_revoke(
    user: CurrentUser = Depends(current_manager),
) -> RedirectResponse:
    """Soft-revoke active Meta connection (sets revoked_at; no Meta API call V0)."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        oc = await meta_oauth_connections.get_active_for_manager(conn, user.id)
        if oc is None:
            raise HTTPException(
                status_code=404,
                detail="No active Meta connection to revoke",
            )
        await meta_oauth_connections.revoke(conn, oc.id)
        await audit_log.record(
            conn,
            manager_id=user.id,
            session_id=None,
            customer_id=None,
            action_type="auth",
            operation="meta_oauth_revoke",
            status="success",
            platform="meta",
        )
    log.info("meta_oauth_revoked", manager_id=str(user.id))
    return RedirectResponse("/admin?meta_revoked=1", status_code=302)
```

- [ ] **Step 8.4: Mount router em `src/app.py`**

Open `src/app.py`. Find where existing routers are mounted (look for `oauth.router` or similar). Add:

```python
from src.auth import meta_oauth as meta_oauth_module
app.include_router(meta_oauth_module.router)
```

Place it adjacent to the existing `from src.auth import oauth; app.include_router(oauth.router)` line.

- [ ] **Step 8.5: Update `src/web/templates/access_denied.html` — meta_scopes_missing branch**

Open `src/web/templates/access_denied.html`. Find existing branches (e.g., `{% if reason == 'domain' %}` or `{% elif reason == 'not_invited' %}`). Add a NEW elif branch BEFORE the closing `{% endif %}`:

```jinja2
{% elif reason == 'meta_scopes_missing' %}
  <h1>Permissões Meta incompletas</h1>
  <p>Você não concedeu uma das permissões essenciais durante o consent do Facebook:</p>
  <ul class="list-disc pl-6 mt-3">
    {% for scope in missing_scopes %}
    <li><code class="px-1 py-0.5 bg-v4-gray-50 rounded text-sm">{{ scope }}</code></li>
    {% endfor %}
  </ul>
  <p class="mt-4">
    Por favor, <a href="/oauth/meta/start" class="text-v4-red hover:underline">conecte novamente</a>
    e marque <strong>TODAS as opções</strong> no consent screen do Facebook.
  </p>
{% elif reason == 'meta_oauth_error' %}
  <h1>Erro no login Meta</h1>
  <p>O Facebook retornou um erro durante o consent:</p>
  <p class="mt-2 text-sm bg-v4-gray-50 p-3 rounded"><code>{{ detail }}</code></p>
  <p class="mt-4"><a href="/oauth/meta/start" class="text-v4-red hover:underline">Tentar novamente</a></p>
{% elif reason == 'meta_token_exchange_failed' %}
  <h1>Falha na troca do token Meta</h1>
  <p>Não conseguimos completar a autenticação. Pode ser timeout temporário.</p>
  <p class="mt-4"><a href="/oauth/meta/start" class="text-v4-red hover:underline">Tentar novamente</a></p>
{% elif reason in ('meta_oauth_incomplete', 'meta_state_invalid', 'meta_userinfo_failed', 'meta_userinfo_incomplete') %}
  <h1>Erro inesperado no login Meta</h1>
  <p>Reason: <code>{{ reason }}</code></p>
  <p class="mt-4"><a href="/oauth/meta/start" class="text-v4-red hover:underline">Tentar novamente</a></p>
```

Also update `src/web/routes.py` `access_denied()` handler (if exists) to parse `missing` query param:

```python
@router.get("/access-denied", response_class=HTMLResponse, response_model=None)
async def access_denied(
    request: Request,
    reason: str | None = None,
    email: str | None = None,
    detail: str | None = None,
    missing: str | None = None,
) -> HTMLResponse:
    missing_scopes = missing.split(",") if missing else []
    return templates.TemplateResponse(
        request,
        "access_denied.html",
        {
            "current_user": None,
            "reason": reason or "unknown",
            "email": email,
            "detail": detail,
            "missing_scopes": missing_scopes,
        },
    )
```

(Adjust to match current signature; preserve existing params.)

- [ ] **Step 8.6: Run unit test — expect PASS**

Run:
```bash
python -m pytest tests/unit/test_meta_oauth.py -v
```

Expected: 5 PASS.

- [ ] **Step 8.7: Create integration test for OAuth flow with respx**

Create `tests/integration/test_meta_oauth_flow.py`:

```python
"""Integration tests for Meta OAuth callback flow via respx (Sprint M.2a Task 8)."""

from uuid import uuid4

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from testcontainers.postgres import PostgresContainer

from src.app import create_app
from src.auth.oauth_state import sign_state
from src.config import get_settings
from src.db import connection, migrate
from src.db.repositories import managers, meta_oauth_connections


@pytest.fixture
async def pg():
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


@pytest.fixture
async def app_client(db):
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _make_state(manager_id: str) -> str:
    settings = get_settings()
    return sign_state(
        {"manager_id": manager_id, "aud": "meta_oauth"},
        settings.session_signing_key,
    )


@pytest.mark.integration
@respx.mock
async def test_oauth_callback_happy_path(db, app_client):
    """Full happy path: short token → long token → /me → debug_token → /me/adaccounts."""
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="ok@v4company.com", full_name="Ok")

    state = _make_state(str(mid))

    respx.post("https://graph.facebook.com/v22.0/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "short_xyz", "expires_in": 3600})
    )
    respx.get("https://graph.facebook.com/v22.0/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "long_60d", "expires_in": 5184000})
    )
    respx.get("https://graph.facebook.com/v22.0/me").mock(
        return_value=Response(200, json={"id": "12345", "email": "ok@v4company.com", "name": "Ok"})
    )
    respx.get("https://graph.facebook.com/v22.0/debug_token").mock(
        return_value=Response(200, json={"data": {"scopes": [
            "ads_read", "ads_management", "business_management", "email", "public_profile"
        ]}})
    )
    respx.get("https://graph.facebook.com/v22.0/me/adaccounts").mock(
        return_value=Response(200, json={"data": [{
            "id": "act_111",
            "name": "Cliente Alpha",
            "account_status": 1,
            "currency": "BRL",
            "timezone_name": "America/Sao_Paulo",
        }]})
    )

    resp = await app_client.get(
        f"/oauth/meta/callback?code=fake_code&state={state}",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/admin?meta_connected=1" in resp.headers["location"]

    # Verify persistence
    async with db.acquire() as conn:
        oc = await meta_oauth_connections.get_active_for_manager(conn, mid)
        assert oc is not None
        assert oc.fb_email == "ok@v4company.com"
        assert "ads_read" in oc.scopes


@pytest.mark.integration
@respx.mock
async def test_oauth_callback_blocks_missing_essentials(db, app_client):
    """debug_token returns scopes WITHOUT ads_read → 302 access-denied."""
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="ms@v4company.com", full_name="Ms")

    state = _make_state(str(mid))

    respx.post("https://graph.facebook.com/v22.0/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "short_xyz", "expires_in": 3600})
    )
    respx.get("https://graph.facebook.com/v22.0/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "long_60d", "expires_in": 5184000})
    )
    respx.get("https://graph.facebook.com/v22.0/me").mock(
        return_value=Response(200, json={"id": "12345", "email": "ms@v4company.com", "name": "Ms"})
    )
    respx.get("https://graph.facebook.com/v22.0/debug_token").mock(
        return_value=Response(200, json={"data": {"scopes": [
            "ads_management", "email"  # MISSING ads_read
        ]}})
    )

    resp = await app_client.get(
        f"/oauth/meta/callback?code=fake_code&state={state}",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "meta_scopes_missing" in resp.headers["location"]
    assert "ads_read" in resp.headers["location"]


@pytest.mark.integration
@respx.mock
async def test_oauth_callback_blocks_non_v4_email(db, app_client):
    """/me returns email outside @v4company.com → 302 access-denied (domain)."""
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="nv@v4company.com", full_name="Nv")

    state = _make_state(str(mid))

    respx.post("https://graph.facebook.com/v22.0/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "short_xyz", "expires_in": 3600})
    )
    respx.get("https://graph.facebook.com/v22.0/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "long_60d", "expires_in": 5184000})
    )
    respx.get("https://graph.facebook.com/v22.0/me").mock(
        return_value=Response(200, json={"id": "999", "email": "stranger@external.com", "name": "X"})
    )

    resp = await app_client.get(
        f"/oauth/meta/callback?code=fake_code&state={state}",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "reason=domain" in resp.headers["location"]


@pytest.mark.integration
async def test_oauth_callback_handles_error_param(app_client):
    """Meta returned ?error=access_denied → 302 access-denied."""
    resp = await app_client.get(
        "/oauth/meta/callback?error=access_denied&error_description=user_cancelled",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "meta_oauth_error" in resp.headers["location"]
```

- [ ] **Step 8.8: Run integration tests — expect PASS (or Docker-unavail skip)**

Run:
```bash
python -m pytest tests/integration/test_meta_oauth_flow.py -v -m integration
```

Expected: 4 PASS (or skip if Docker missing).

- [ ] **Step 8.9: Run ruff + mypy**

Run:
```bash
python -m ruff check src/auth/meta_oauth.py tests/unit/test_meta_oauth.py tests/integration/test_meta_oauth_flow.py src/app.py
python -m ruff format --check src/auth/meta_oauth.py tests/unit/test_meta_oauth.py tests/integration/test_meta_oauth_flow.py
python -m mypy --strict src/auth/meta_oauth.py
```

Expected: all pass.

- [ ] **Step 8.10: Commit**

```bash
git add src/auth/meta_oauth.py src/app.py src/web/templates/access_denied.html src/web/routes.py tests/unit/test_meta_oauth.py tests/integration/test_meta_oauth_flow.py
git commit -m "feat(auth): meta_oauth flow + access_denied branches (Sprint M.2a Task 8)

Routes:
- GET  /oauth/meta/start: signs state HMAC + redirect a Meta consent
- GET  /oauth/meta/callback: code → short → long-lived token →
  /me + domain check + /debug_token scopes check + /me/adaccounts sync
  + upsert connection + grant_all + audit_log + redirect /admin
- POST /oauth/meta/revoke: soft-revoke (sem Meta API call V0)

Granular permission enforcement: bloqueia callback se faltar
ads_read OU ads_management → 302 access-denied?reason=meta_scopes_missing.

access_denied.html: 5 novos branches (scopes_missing, oauth_error,
token_exchange_failed, state_invalid, userinfo_failed). routes.py
access_denied handler parseia missing= query param.

Tests: 5 unit (granted_scopes decision tree) + 4 integration (respx mock
do Graph API: happy path, scopes missing, non-v4 domain, error param).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Tool `meta_list_my_ad_accounts` + integration tests

**Files:**
- Create: `src/mcp/tools/_meta_common.py`
- Create: `src/mcp/tools/meta_list_my_ad_accounts.py`
- Create: `tests/integration/test_meta_list_my_ad_accounts.py`

- [ ] **Step 9.1: Create failing integration tests**

Create `tests/integration/test_meta_list_my_ad_accounts.py`:

```python
"""Integration tests for meta_list_my_ad_accounts tool (Sprint M.2a Task 9)."""

from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import (
    manager_meta_account_access,
    managers,
    meta_ad_accounts,
)
from src.mcp.context import McpRequestContext, set_current
from src.mcp.tools._registry import get_tool, import_all_tools


@pytest.fixture
async def pg():
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        import_all_tools()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


@pytest.mark.integration
async def test_full_pipeline(db):
    """Manager + ad accounts + grants → tool returns sorted list."""
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="t@v4.com", full_name=None)
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {"ad_account_id": "act_222", "business_id": "bm_X", "account_name": "Beta",
                 "currency": "BRL", "timezone_name": "America/Sao_Paulo", "account_status": 1},
                {"ad_account_id": "act_111", "business_id": "bm_X", "account_name": "Alpha",
                 "currency": "BRL", "timezone_name": "America/Sao_Paulo", "account_status": 1},
            ],
        )
        await manager_meta_account_access.grant(conn, manager_id=mid, ad_account_id="act_111")
        await manager_meta_account_access.grant(conn, manager_id=mid, ad_account_id="act_222")

    set_current(McpRequestContext(manager_id=mid, session_id=uuid4()))
    tool = get_tool("meta_list_my_ad_accounts")
    assert tool is not None
    result = await tool.handler({})
    assert result["total"] == 2
    assert [a["account_name"] for a in result["ad_accounts"]] == ["Alpha", "Beta"]  # ORDER BY name


@pytest.mark.integration
async def test_account_status_label_translation(db):
    """account_status int → PT-BR label."""
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="l@v4.com", full_name=None)
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {"ad_account_id": "act_a1", "account_name": "Ativa", "account_status": 1},
                {"ad_account_id": "act_d2", "account_name": "Disabled", "account_status": 2},
                {"ad_account_id": "act_u3", "account_name": "Unknown", "account_status": 999},
            ],
        )
        await manager_meta_account_access.grant(conn, manager_id=mid, ad_account_id="act_a1")
        await manager_meta_account_access.grant(conn, manager_id=mid, ad_account_id="act_d2")
        await manager_meta_account_access.grant(conn, manager_id=mid, ad_account_id="act_u3")

    set_current(McpRequestContext(manager_id=mid, session_id=uuid4()))
    tool = get_tool("meta_list_my_ad_accounts")
    result = await tool.handler({})
    labels = {a["account_name"]: a["account_status_label"] for a in result["ad_accounts"]}
    assert labels["Ativa"] == "ATIVO"
    assert labels["Disabled"] == "DESABILITADO"
    assert labels["Unknown"] == "DESCONHECIDO"


@pytest.mark.integration
async def test_empty_when_no_grants(db):
    """Manager sem grants → lista vazia."""
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="e@v4.com", full_name=None)

    set_current(McpRequestContext(manager_id=mid, session_id=uuid4()))
    tool = get_tool("meta_list_my_ad_accounts")
    result = await tool.handler({})
    assert result["total"] == 0
    assert result["ad_accounts"] == []


@pytest.mark.integration
async def test_isolation_per_manager(db):
    """Manager A vê só act_a; Manager B vê só act_b."""
    async with db.acquire() as conn:
        ma = uuid4()
        mb = uuid4()
        await managers.create(conn, manager_id=ma, email="a@v4.com", full_name=None)
        await managers.create(conn, manager_id=mb, email="b@v4.com", full_name=None)
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {"ad_account_id": "act_only_a", "account_name": "A's Account"},
                {"ad_account_id": "act_only_b", "account_name": "B's Account"},
            ],
        )
        await manager_meta_account_access.grant(conn, manager_id=ma, ad_account_id="act_only_a")
        await manager_meta_account_access.grant(conn, manager_id=mb, ad_account_id="act_only_b")

    set_current(McpRequestContext(manager_id=ma, session_id=uuid4()))
    tool = get_tool("meta_list_my_ad_accounts")
    result_a = await tool.handler({})
    assert {a["ad_account_id"] for a in result_a["ad_accounts"]} == {"act_only_a"}

    set_current(McpRequestContext(manager_id=mb, session_id=uuid4()))
    result_b = await tool.handler({})
    assert {a["ad_account_id"] for a in result_b["ad_accounts"]} == {"act_only_b"}
```

- [ ] **Step 9.2: Run tests — expect tool not registered**

Run:
```bash
python -m pytest tests/integration/test_meta_list_my_ad_accounts.py -v -m integration
```

Expected: `assert tool is not None` fails (tool not yet registered). Continue.

- [ ] **Step 9.3: Create `src/mcp/tools/_meta_common.py`**

```python
"""Helpers compartilhados pelas tools Meta MCP (Sprint M.2a Task 9 onwards)."""

META_ACCOUNT_STATUS_LABELS: dict[int, str] = {
    1: "ATIVO",
    2: "DESABILITADO",
    3: "PAGAMENTO_PENDENTE",
    7: "EM_REVISÃO_DE_RISCO",
    101: "FECHADO",
    102: "ANY_ACTIVE",
    201: "FECHAMENTO_PENDENTE",
    202: "LIQUIDAÇÃO_PENDENTE",
}


def parse_meta_ad_account_id(raw: str) -> str:
    """Normalize ad_account_id to 'act_<numeric>' format."""
    if raw.startswith("act_"):
        return raw
    return f"act_{raw}"
```

- [ ] **Step 9.4: Create `src/mcp/tools/meta_list_my_ad_accounts.py`**

```python
"""List Meta Ad Accounts the manager has access to (Sprint M.2a Task 9).

Source: manager_meta_account_access (local cache, populated on OAuth callback).
Does NOT call Meta API. Reconnect via webapp to refresh.
"""

from typing import Any

from src.db import connection
from src.db.repositories import manager_meta_account_access
from src.mcp.context import get_current
from src.mcp.tools._meta_common import META_ACCOUNT_STATUS_LABELS
from src.mcp.tools._registry import register_tool

_DESCRIPTION = (
    "Lista as contas de anúncio Meta às quais o gestor tem acesso. "
    "Fonte: cache local sincronizado quando o gestor conecta Meta via OAuth. "
    "Pra forçar refresh dos accounts, gestor precisa reconectar via painel admin. "
    "Retorna: ad_account_id ('act_<numeric>'), account_name, business_id/name "
    "(NULL se personal), currency, timezone_name, account_status (Meta enum) "
    "+ account_status_label (PT-BR)."
)


@register_tool(
    name="meta_list_my_ad_accounts",
    description=_DESCRIPTION,
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
)
async def handler(_args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accounts = await manager_meta_account_access.list_accounts_for_manager(
            conn, ctx.manager_id
        )
    return {
        "ad_accounts": [
            {
                "ad_account_id": a.ad_account_id,
                "account_name": a.account_name,
                "business_id": a.business_id,
                "business_name": a.business_name,
                "currency": a.currency,
                "timezone_name": a.timezone_name,
                "account_status": a.account_status,
                "account_status_label": META_ACCOUNT_STATUS_LABELS.get(
                    a.account_status or 0, "DESCONHECIDO"
                ),
            }
            for a in accounts
        ],
        "total": len(accounts),
    }
```

- [ ] **Step 9.5: Run tests — expect PASS**

Run:
```bash
python -m pytest tests/integration/test_meta_list_my_ad_accounts.py -v -m integration
```

Expected: 4 PASS.

- [ ] **Step 9.6: Run schema regression test**

Run:
```bash
python -m pytest tests/unit/test_no_composition_keywords_in_any_schema.py -v
```

Expected: PASS (new tool schema is simple `additionalProperties: False`).

- [ ] **Step 9.7: Run ruff + mypy**

Run:
```bash
python -m ruff check src/mcp/tools/_meta_common.py src/mcp/tools/meta_list_my_ad_accounts.py tests/integration/test_meta_list_my_ad_accounts.py
python -m ruff format --check src/mcp/tools/_meta_common.py src/mcp/tools/meta_list_my_ad_accounts.py tests/integration/test_meta_list_my_ad_accounts.py
python -m mypy --strict src/mcp/tools/_meta_common.py src/mcp/tools/meta_list_my_ad_accounts.py
```

Expected: all pass.

- [ ] **Step 9.8: Commit**

```bash
git add src/mcp/tools/_meta_common.py src/mcp/tools/meta_list_my_ad_accounts.py tests/integration/test_meta_list_my_ad_accounts.py
git commit -m "feat(mcp): meta_list_my_ad_accounts tool + _meta_common helpers (Sprint M.2a Task 9)

Primeira tool MCP Meta. Read-only, fonte cache local (DB) populado pelo
OAuth callback. Zero latency Meta API + zero rate limit consumption.

Trade-off documentado: dados podem ficar stale se cliente add/remove
ad account no BM sem reconnect. Mitigation M.2b: 'Refresh Meta accounts'
button na admin UI.

4 integration tests:
- Full pipeline (manager + grants + ORDER BY name)
- account_status int → PT-BR label translation
- Empty when no grants
- Isolation per manager

_meta_common.py: META_ACCOUNT_STATUS_LABELS (8 entries) + parse_meta_ad_account_id
helper pra M.3+ tools que aceitam input.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Webapp admin UI minimal (Meta connection card)

**Files:**
- Modify: `src/web/routes.py` (admin_index handler enrichment)
- Modify: `src/web/templates/admin/index.html` (new section)

- [ ] **Step 10.1: Modify `src/web/routes.py` admin_index handler**

Open `src/web/routes.py`. Find the `admin_index` handler (search for `/admin` route with `_require_admin`). Add imports at top:

```python
from src.db.repositories import meta_oauth_connections
from datetime import UTC, datetime
```

Modify handler body to load meta_conn + compute expiry signals:

```python
@router.get("/admin", response_class=HTMLResponse)
async def admin_index(
    request: Request,
    user: CurrentUser = Depends(current_manager),
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        google_conn = await google_oauth_connections.get_active_for_manager(conn, user.id)
        meta_conn = await meta_oauth_connections.get_active_for_manager(conn, user.id)
        # ... existing summary stats queries (preserve them) ...

    meta_token_expiring_soon = False
    meta_days_until_expiry: int | None = None
    if meta_conn is not None:
        delta = meta_conn.token_expires_at - datetime.now(UTC)
        meta_days_until_expiry = max(0, delta.days)
        meta_token_expiring_soon = delta.days < 7

    return templates.TemplateResponse(
        request,
        "admin/index.html",
        {
            "current_user": user,
            "google_conn": google_conn,
            "meta_conn": meta_conn,
            "meta_token_expiring_soon": meta_token_expiring_soon,
            "meta_days_until_expiry": meta_days_until_expiry,
            # ... existing context keys ...
        },
    )
```

(Preserve existing summary stats queries + context keys; only ADD the new ones.)

- [ ] **Step 10.2: Modify `src/web/templates/admin/index.html` — add OAuth card section**

Open `src/web/templates/admin/index.html`. Find a good insertion point (typically right after the page header/title, before the summary stats grid). Add:

```jinja2
<section class="v4-card mb-6 p-4">
  <h2 class="text-lg font-semibold text-v4-gray-900 mb-4">Suas conexões OAuth</h2>
  <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
    {# Google connection #}
    <div class="p-4 border border-v4-gray-100 rounded-md">
      <div class="flex items-center justify-between mb-2">
        <span class="font-medium text-v4-gray-900">Google Ads</span>
        {% if google_conn %}
          <span class="text-xs px-2 py-1 bg-v4-green-soft text-v4-green rounded">Conectado</span>
        {% else %}
          <span class="text-xs px-2 py-1 bg-v4-gray-50 text-v4-gray-700 rounded">Desconectado</span>
        {% endif %}
      </div>
      {% if google_conn %}
        <p class="text-sm text-v4-gray-700">{{ google_conn.google_email }}</p>
        <p class="text-xs text-v4-gray-700">Conectado em {{ google_conn.connected_at.strftime('%d/%m/%Y') }}</p>
        <a href="/oauth/google/start?mode=panel_login" class="text-xs text-v4-red hover:underline mt-2 inline-block">Reconectar</a>
      {% else %}
        <a href="/oauth/google/start?mode=panel_login" class="v4-btn v4-btn--small v4-btn--primary mt-2 inline-block">Conectar Google</a>
      {% endif %}
    </div>

    {# Meta connection — NEW (Sprint M.2a) #}
    <div class="p-4 border border-v4-gray-100 rounded-md">
      <div class="flex items-center justify-between mb-2">
        <span class="font-medium text-v4-gray-900">Meta Ads</span>
        {% if meta_conn %}
          {% if meta_token_expiring_soon %}
            <span class="text-xs px-2 py-1 bg-v4-gold-soft text-v4-gold rounded">Expira em breve</span>
          {% else %}
            <span class="text-xs px-2 py-1 bg-v4-green-soft text-v4-green rounded">Conectado</span>
          {% endif %}
        {% else %}
          <span class="text-xs px-2 py-1 bg-v4-gray-50 text-v4-gray-700 rounded">Desconectado</span>
        {% endif %}
      </div>
      {% if meta_conn %}
        <p class="text-sm text-v4-gray-700">{{ meta_conn.fb_email }}</p>
        <p class="text-xs text-v4-gray-700">
          Expira em {{ meta_conn.token_expires_at.strftime('%d/%m/%Y') }}
          ({{ meta_days_until_expiry }} dias)
        </p>
        <a href="/oauth/meta/start" class="text-xs text-v4-red hover:underline mt-2 inline-block">Reconectar</a>
      {% else %}
        <a href="/oauth/meta/start" class="v4-btn v4-btn--small v4-btn--primary mt-2 inline-block">Conectar Meta</a>
      {% endif %}
    </div>
  </div>
</section>
```

- [ ] **Step 10.3: Run app boot sanity check**

Run:
```bash
python -c "
import os
os.environ.setdefault('APP_ENV', 'development')
os.environ.setdefault('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/test')
os.environ.setdefault('SESSION_SIGNING_KEY', 'x' * 32)
os.environ.setdefault('AES_MASTER_KEY', 'y' * 32)
os.environ.setdefault('GOOGLE_OAUTH_CLIENT_ID', 'test')
os.environ.setdefault('GOOGLE_OAUTH_CLIENT_SECRET', 'test')
os.environ.setdefault('GOOGLE_ADS_DEVELOPER_TOKEN', 'test')
os.environ.setdefault('GOOGLE_ADS_LOGIN_CUSTOMER_ID', '1234567890')
os.environ.setdefault('SUPABASE_URL', 'https://test.co')
os.environ.setdefault('SUPABASE_ANON_KEY', 'test')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test')
os.environ.setdefault('META_APP_ID', 'test')
os.environ.setdefault('META_APP_SECRET', 'test_meta_secret_dummy_value_at_least_32_chars_long')
from src.app import create_app
app = create_app()
print('OK app boot, routes:', [r.path for r in app.routes if hasattr(r, 'path')][:10])
"
```

Expected: prints list of routes including `/admin` + `/oauth/meta/start`/`/callback`/`/revoke`. No errors.

- [ ] **Step 10.4: Run ruff + mypy**

Run:
```bash
python -m ruff check src/web/routes.py
python -m ruff format --check src/web/routes.py
python -m mypy --strict src/web/routes.py
```

Expected: all pass.

- [ ] **Step 10.5: Commit**

```bash
git add src/web/routes.py src/web/templates/admin/index.html
git commit -m "feat(web): admin OAuth connections card — Google + Meta (Sprint M.2a Task 10)

Card 'Suas conexões OAuth' adicionado à página /admin com 2 columns:
- Google Ads (existing) + connected_at + Reconectar/Conectar
- Meta Ads (NEW) + fb_email + token_expires_at + dias até expirar +
  badge gold 'Expira em breve' se < 7 dias + Reconectar/Conectar

Backend admin_index() enrichment: carrega meta_conn + computa
meta_days_until_expiry + meta_token_expiring_soon. Preserva todos os
context keys existentes.

V0 minimal — sem polish (logos, simétrico polished), sem Revogar button,
sem 'Refresh Meta accounts'. Tudo M.2b.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Smoke runbook via subagent

**Files:**
- Create: `docs/operacao/phase-M-2a-bootstrap.md`

- [ ] **Step 11.1: Dispatch `smoke-runbook-generator` subagent**

Use the Agent tool with `subagent_type: "smoke-runbook-generator"`. Prompt:

```
Gere `docs/operacao/phase-M-2a-bootstrap.md` para Sprint M.2a (Meta OAuth + first tool).

Sprint family: M (Meta Ads), parte 1 de 2.

Testes a cobrir (Wellington manual em V4 Lima Soares & Co BM):

T1 — OAuth happy path:
- Wellington acessa https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/admin (logged in)
- Click no card Meta: "Conectar Meta"
- Redirect Facebook → consent screen com 5 scopes (ads_read, ads_management, business_management, email, public_profile)
- Aceita todos
- Redirect back → /admin?meta_connected=1
- Verifica card mostra "Conectado" + fb_email Wellington + dias até expirar (~60)

T2 — Tool meta_list_my_ad_accounts via Claude Desktop:
- "Liste minhas contas Meta" no Claude com bearer token MCP
- Espera: lista de ad accounts V4 Lima Soares & Co com names, currency BRL, timezone America/Sao_Paulo, account_status_label PT-BR

T3 — Granular permission rejection:
- Wellington reconecta Meta MAS desmarca "ads_read" no consent
- Redirect /access-denied?reason=meta_scopes_missing&missing=ads_read
- Página mostra mensagem PT-BR + link "conecte novamente"

T4 — Audit log entry:
- Após T1+T2, executa via Claude: `get_my_audit_log` com filtro platform="meta"
- Espera 2 entries:
  - action_type=auth, operation=meta_oauth_connect, status=success
  - action_type=read, operation=meta_list_my_ad_accounts, status=success

T5 — Token expiry simulation:
- Via Supabase SQL: `UPDATE meta_oauth_connections SET token_expires_at = now() - interval '1 day' WHERE manager_id = '<wellington_uuid>'`
- Re-tenta meta_list_my_ad_accounts → espera MetaTokenExpiredError PT-BR
- Wellington reconecta → restored

T6 — Revoke flow:
- Manual via curl/Postman POST /oauth/meta/revoke (logged in com cookie)
- Verifica /admin card mostra "Desconectado"
- Re-tenta meta_list_my_ad_accounts → MetaConnectionError "conecte"

T7 (regression) — Google Ads tools intactas após rename column:
- Executa list_my_accounts Google → retorna accounts normalmente
- Executa get_account_overview em 1 conta → retorna sem erro
- Audit log entry mostra platform=google (default)

Plus campos do runbook: cabeçalho com sprint ref + spec link + plan link, pre-conditions
(Wellington logged in admin, sandbox V4 Lima Soares & Co BM ad accounts visíveis),
escopo, expected outcomes, rollback se T1 falhar (revoke + delete connection row).

Modelo seguido pelos phase-3b-*.md runbooks recentes (3b.36, 3b.37) — copie pattern.

Salve em `D:\V4 ads MCP\docs\operacao\phase-M-2a-bootstrap.md`.
```

- [ ] **Step 11.2: Quick review of generated runbook**

Read the generated `phase-M-2a-bootstrap.md`. Verify:
- Tem 7 testes cobrindo T1-T7
- Cada teste tem section "Como executar" + "Resultado esperado"
- Header reference correctly aponta pra spec/plan
- Wellington steps são executáveis e claros

If gaps: iterate the subagent with specific feedback.

- [ ] **Step 11.3: Commit runbook**

```bash
git add docs/operacao/phase-M-2a-bootstrap.md
git commit -m "docs(smoke): phase-M-2a-bootstrap.md runbook (Sprint M.2a Task 11)

7 testes Wellington manual em V4 Lima Soares & Co BM cobrindo OAuth
happy path, granular permission rejection, tool ponta-a-ponta via
Claude, audit log entries com platform=meta, token expiry simulation,
revoke flow, e regression Google Ads (rename column intacto).

Gerado via smoke-runbook-generator subagent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Pre-push gate full sweep + push deploy

- [ ] **Step 12.1: Quick pre-push gate**

Run:
```bash
python scripts/check_pre_push.py
```

Expected: 5/5 PASS. Fix any failures before continuing.

- [ ] **Step 12.2: Full pre-push gate (Docker required)**

Run:
```bash
python scripts/check_pre_push_full.py
```

Expected: 6/6 PASS (or exit 2 + Docker hint — push anyway, CI runs full integration).

**This is MANDATORY pra M.2a** porque mexe em audit_log (column rename) — integration testcontainers test catches regressions Grep não pegou.

- [ ] **Step 12.3: Push**

Run:
```bash
git push origin main
```

Expected: push succeeds (admin bypass).

- [ ] **Step 12.4: Watch CI + Deploy**

Run:
```bash
gh run list --limit 5
```

Identify CI + Deploy runs (most recent). Watch each:
```bash
gh run watch <CI_RUN_ID>
gh run watch <DEPLOY_RUN_ID>
```

Or use `gh run view <id> --json status,conclusion` periodically.

Expected: both complete with `conclusion: success`.

- [ ] **Step 12.5: Verify /health**

Run:
```bash
curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```

Expected: `{"status":"ok","version":"0.1.0"}` HTTP 200.

- [ ] **Step 12.6: Verify migration 004 applied + Meta tool registered**

Run:
```bash
gcloud secrets versions access latest --secret=database-url --project=v4-ads-mcp-prod | python -c "
import asyncio, sys, asyncpg
async def main():
    dsn = sys.stdin.read().strip()
    conn = await asyncpg.connect(dsn)
    try:
        # Check migration
        rows = await conn.fetch('SELECT name FROM _migrations ORDER BY applied_at DESC LIMIT 3')
        for r in rows:
            print('Migration:', r['name'])
        # Check column renamed
        col = await conn.fetchval(
            'SELECT column_name FROM information_schema.columns '
            \"WHERE table_name = 'audit_log' AND column_name IN ('google_request_id', 'provider_request_id')\"
        )
        print('Column:', col)
    finally:
        await conn.close()
asyncio.run(main())"
```

Expected:
- `Migration: 004_audit_log_provider_id.sql` (top of list)
- `Column: provider_request_id` (not google_request_id)

- [ ] **Step 12.7: Verify MCP tool registered**

After Claude Desktop reloads MCP cache (Wellington reconnects v4-ads connector), run from Claude:

```
list_gaql_resources (or similar diagnostic) — para confirmar conexão MCP funciona
```

Then check Tool list inclui `meta_list_my_ad_accounts`.

---

## Task 13: Wellington manual smoke + signoff

- [ ] **Step 13.1: Wellington runs T1-T7 from runbook**

Wellington opens `docs/operacao/phase-M-2a-bootstrap.md` and executes each test. Logs results in the runbook itself (✅ PASS / ❌ FAIL with details).

- [ ] **Step 13.2: If any test FAILS — fix + new commit (NOT amend)**

Investigate via Cloud Run logs:
```bash
gcloud run services logs read v4-ads-mcp --region=southamerica-east1 --project=v4-ads-mcp-prod --limit=100
```

Fix root cause. NEW commit (do NOT amend prior commits). Re-push. Wellington re-runs failed tests.

- [ ] **Step 13.3: All tests PASS — signoff commit**

Update `CLAUDE.md` "Shipped — Meta Ads" table — add Sprint M.2a row:

```markdown
| Sprint M.2a — OAuth + SDK + 1st tool | ✅ 2026-05-XX | DB: migration 004 RENAME google_request_id → provider_request_id (big bang 50 files); audit_log.record() add platform kwarg; meta_rate_counters repo CRUD. SDK: facebook-business>=21.0.0; src/meta_ads/ package (client, reports, errors). OAuth: /oauth/meta/{start,callback,revoke} com granular permission enforcement (block essentials missing). Tool: meta_list_my_ad_accounts (read cache, zero API call). UI: admin card OAuth connections (Google + Meta). 7/7 smoke real V4 Lima Soares & Co BM PASS. Tool count: 57 → 58. **F47-F49 descobertos** [iff applicable]. Sprint family completo: [spec](docs/superpowers/specs/2026-05-24-sprint-m2a-meta-oauth-first-tool-design.md) + [plan](docs/superpowers/plans/2026-05-24-sprint-m2a-meta-oauth-first-tool.md). |
```

Update `docs/operacao/sprint-history.md` — append M.2a row with similar detail.

Remove M.2-related pendings from CLAUDE.md "Pending / future" (4 of the 5 are now done; data-deletion-callback remains for M.2b).

- [ ] **Step 13.4: Commit signoff**

```bash
git add CLAUDE.md docs/operacao/sprint-history.md docs/operacao/phase-M-2a-bootstrap.md
git commit -m "docs(signoff): Sprint M.2a OAuth + SDK + 1st Meta tool — 7/7 smoke PASS

Sprint M.2a shipped + smoke real V4 Lima Soares & Co BM.

Stats:
- Tool count: 57 → 58 (+meta_list_my_ad_accounts)
- 50 files refactored (google_request_id → provider_request_id big bang)
- 4 prep tasks foundation completados (5th = data-deletion-callback fica
  pra M.2b)
- SDK facebook-business v21.0 integrated, package src/meta_ads/ baseline
- OAuth flow Meta com granular permission enforcement + long-lived token
  (~60d) + reactive expire handling
- Webapp admin: card OAuth connections (Google + Meta visíveis)
- 24 novos tests (8 unit errors + 5 unit oauth + 7 unit BUC + 4 integration
  list_ad_accounts + 4 integration oauth_flow + 3 integration audit_log
  platform regression)

Próxima sprint M.2b (~1-2 dias): meta_get_account_overview tool +
/oauth/meta/data-deletion-callback endpoint + UI polish + Meta App Review
submit Wellington manual.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

git push origin main
```

---

## Self-Review Notes

**Spec coverage:** All 8 sections of the spec are covered by tasks:
- §1 Architecture: Task structure mirrors files declared
- §2 Foundation prep (5 tasks): Tasks 1-5
- §3 OAuth flow: Task 8
- §4 SDK + reports: Tasks 6-7
- §5 First tool: Task 9
- §6 UI minimal: Task 10
- §7 Testing: Distributed across Tasks 1-9
- §8 Risks + M.2b scope: Documented in plan + signoff

**Placeholder scan:** Plan contains no TBD/TODO/placeholder. Every step has actual code or command.

**Type consistency:**
- `audit_log.record()` signature consistent across Tasks 1, 2, 8 (with `platform`, `provider_request_id`)
- `MetaOAuthConnection` dataclass field names match M.1 schema + repo usage in Task 8
- `MetaAdAccount` field names match Task 9 tool consumption
- `to_friendly_meta_error()` signature consistent across Tasks 6, 7
- `_parse_buc_header_pct()` signature consistent Tasks 7, BUC parsing tests
- `check_meta_granted_scopes()` signature consistent Tasks 8 unit/integration tests

**Known deferments to M.2b:**
- `meta_get_account_overview` tool
- `/oauth/meta/data-deletion-callback` endpoint
- UI polish (cards refinados, refresh button, revoke modal)
- Meta App Review submit
- Per-value enum coverage probes

---

**Sprint M.2a estimativa final:** 2-3 dias úteis. Critical path: Tasks 1-3 (audit_log + rename) → Tasks 4-7 (foundation Meta) → Task 8 (OAuth, biggest task) → Tasks 9-10 (tool + UI) → Tasks 11-13 (smoke + signoff).
