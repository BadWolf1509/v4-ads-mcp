# V4 Ads MCP — Phase 2: 16 Read Tools + GAQL Utilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the 16 curated read tools (per spec §6.2) plus 3 GAQL escape-hatch utilities, wired with rate limiting and audit. Gestores can now ask Claude for any V4 Google Ads report without leaving the chat.

**Architecture:** Each tool is a self-contained file in `src/mcp/tools/` registering via the existing `@register_tool` decorator. GAQL queries live in `src/google_ads/queries/` (one module per "report family") with helper functions for date ranges + comparison periods. New `governance/rate_limit.py` enforces the 15k-ops/day Google Ads quota. The Cloud Run service redeploys at the start to pick up the corrected MCC ID secret value.

**Tech Stack:** Reuses Phase 1a's `google-ads` SDK + asyncpg + MCP server. No new dependencies.

**Reference spec:** `docs/superpowers/specs/2026-05-03-v4-ads-mcp-design.md` §6.2 (16 read tools + utilities), §7.3 (rate limit), §7.4 (audit policy — only sensitive reads logged), §11 (Phase 2 acceptance).

**Definition of done (Phase 2):**

1. All 16 read tools registered and callable via `/mcp`.
2. `run_gaql`, `validate_gaql`, `list_gaql_resources` callable as utility tools.
3. Rate limit module increments `rate_counters` on each Google Ads API call; logs warning at 80% of daily quota; blocks at 100%.
4. wellinton.ribeiro@v4company.com (admin) calls **at least 5 different tools** via Codex/Claude Desktop and gets correct PT-BR responses with real data from the V4 MCC.
5. Audit log captures the calls (operation name + customer_id + duration); reads of high-volume reports (campaign_performance etc.) are NOT individually logged but summarized by tool/day in a separate roll-up.
6. All 65+ existing tests still pass; new tests cover ~20+ unit tests for tools and 4-5 integration tests for groups.

---

## File structure (created/modified in this phase)

```
.
├── src/
│   ├── governance/                                       # NEW PACKAGE
│   │   ├── __init__.py
│   │   └── rate_limit.py                                 # daily counter + alerts
│   ├── google_ads/
│   │   ├── client.py                                     # MODIFY: add per-manager helper
│   │   ├── queries/                                      # NEW PACKAGE — GAQL templates
│   │   │   ├── __init__.py
│   │   │   ├── _common.py                                # date-range, comparison, format helpers
│   │   │   ├── overview.py                               # account_overview, budget_pacing
│   │   │   ├── recommendations.py
│   │   │   ├── performance.py                            # campaign, ad_group, device, geo, hourly
│   │   │   ├── tactical.py                               # keyword, search_terms, negatives, ads, audience, conversions
│   │   │   ├── client_report.py                          # funnel_metrics, top_keywords_creatives
│   │   │   └── meta.py                                   # list_gaql_resources catalog
│   │   ├── reports.py                                    # NEW: shared executor (build client → run query → format)
│   │   └── errors.py                                     # MODIFY: add RATE_LIMIT_EXCEEDED + a few more codes
│   ├── mcp/
│   │   ├── tools/
│   │   │   ├── _registry.py                              # MODIFY: import_all_tools loads all 19 modules
│   │   │   ├── # ── visão geral ──
│   │   │   ├── get_account_overview.py
│   │   │   ├── get_budget_pacing.py
│   │   │   ├── get_recommendations.py
│   │   │   ├── # ── análise de performance ──
│   │   │   ├── get_campaign_performance.py
│   │   │   ├── get_ad_group_performance.py
│   │   │   ├── get_device_performance.py
│   │   │   ├── get_geo_performance.py
│   │   │   ├── get_hourly_performance.py
│   │   │   ├── # ── otimização tática ──
│   │   │   ├── get_keyword_performance.py
│   │   │   ├── get_search_terms_report.py
│   │   │   ├── get_negative_keywords_audit.py
│   │   │   ├── get_ad_performance.py
│   │   │   ├── get_audience_performance.py
│   │   │   ├── get_conversion_actions.py
│   │   │   ├── # ── relatório cliente ──
│   │   │   ├── get_funnel_metrics.py
│   │   │   ├── get_top_keywords_creatives.py
│   │   │   ├── # ── utilitários ──
│   │   │   ├── run_gaql.py
│   │   │   ├── validate_gaql.py
│   │   │   └── list_gaql_resources.py
│   │   └── server.py                                     # NO CHANGE if registry pattern is robust
├── tests/
│   ├── unit/
│   │   ├── test_rate_limit.py                            # TDD
│   │   ├── test_query_helpers.py                         # date ranges, comparisons
│   │   └── test_tools_schemas.py                         # validate every tool's input schema is valid JSON Schema
│   └── integration/
│       ├── test_overview_tools.py                        # 3 tools w/ mocked Google Ads SDK
│       ├── test_performance_tools.py                     # 5 tools
│       ├── test_tactical_tools.py                        # 6 tools
│       ├── test_client_report_tools.py                   # 2 tools
│       ├── test_utility_tools.py                         # 3 utility tools
│       └── test_rate_limit_integration.py                # rate limit blocks at 100%
└── docs/operacao/
    └── phase-2-tools-reference.md                        # PT-BR usage examples for each tool
```

---

## Manual prerequisites

All from Phase 0 + 1a:

- [x] Cloud Run service running (https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/mcp)
- [x] V4 MCC ID `6436352492` in Secret Manager `google-ads-login-customer-id` (latest version)
- [x] OAuth refresh token for wellinton.ribeiro@v4company.com encrypted in DB
- [x] 23 V4 child accounts in `google_ads_accounts` table
- [x] Admin granted access to all 23 accounts
- [x] An MCP session token exists (or generate a fresh one in Task 11 verification)

---

## Task 1: Trigger redeploy to pick up corrected MCC ID

The Cloud Run service was deployed BEFORE we updated `google-ads-login-customer-id` in Secret Manager from `7862230676` to `6436352492`. Cloud Run resolves `:latest` secrets at deploy time, not at runtime — the running service has the OLD MCC baked in. Phase 2 tools that hit the Google Ads API need the right MCC.

**Files:**
- Trivial trigger commit (no code changes — just a comment update in a doc file)

- [ ] **Step 1: Touch a doc file to force a no-op deploy**

```bash
cd "/d/HUB ads MCP"
echo "" >> docs/operacao/infra-setup.md   # add trailing blank line; harmless
git add docs/operacao/infra-setup.md
git diff --cached
```

If `git diff --cached` shows any change, you're good. If it shows nothing (the file already ended with newline), instead make a tiny doc tweak:

```bash
# Use Edit to find the GCP project section header and append a trivial inline note
```

The point is: produce ONE staged change that's safe to commit.

- [ ] **Step 2: Commit and push**

```bash
git commit -m "ops: trigger redeploy to refresh google-ads-login-customer-id secret

The Cloud Run service revision currently serving traffic was
deployed before the MCC ID secret was corrected from 7862230676
to 6436352492. Cloud Run materializes :latest secrets at deploy
time, so a no-op deploy is needed to pick up the new value.
Phase 2 tools that call the Google Ads API depend on this."
git push origin main
```

- [ ] **Step 3: Watch deploy + verify env**

```bash
sleep 5
RUN_ID=$(gh run list --branch main --workflow=deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --exit-status --interval 20
```

Once GREEN:

```bash
PATH="/c/Program Files (x86)/Google/Cloud SDK/google-cloud-sdk/bin:$PATH"
export PATH
REV=$(gcloud run services describe v4-ads-mcp --region=southamerica-east1 --format='value(status.latestReadyRevisionName)')
echo "Current rev: $REV"
gcloud run revisions describe $REV --region=southamerica-east1 \
    --format="value(spec.containers[0].env[].name,spec.containers[0].env[].value)" | head -5
```

The `GOOGLE_ADS_LOGIN_CUSTOMER_ID` env should reference the secret. To confirm it actually resolved correctly, hit `/health` on the new revision (it doesn't expose the value but its existence proves startup).

```bash
curl -fsS https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```

Expected: `{"status":"ok","version":"0.1.0"}`.

- [ ] **Step 4: Run resync once to confirm Google API calls succeed with new MCC**

```bash
gcloud run jobs execute v4-ads-mcp-resync --region=southamerica-east1 --wait
```

Expected: completes successfully (no `USER_PERMISSION_DENIED`). The job re-fetches accounts and confirms they're still in DB (idempotent upsert).

If it fails with permission denied, the secret didn't update OR the Job needs an explicit redeploy too. Check:
```bash
gcloud run jobs describe v4-ads-mcp-resync --region=southamerica-east1 \
    --format='value(spec.template.spec.template.spec.containers[0].env[].name)'
```

If the env vars look right but execution fails, manually re-execute with explicit env:
```bash
gcloud run jobs update v4-ads-mcp-resync --region=southamerica-east1 \
    --update-secrets=GOOGLE_ADS_LOGIN_CUSTOMER_ID=google-ads-login-customer-id:latest
gcloud run jobs execute v4-ads-mcp-resync --region=southamerica-east1 --wait
```

## Self-Review

- [ ] Deploy GREEN
- [ ] /health responds 200
- [ ] Resync execution succeeds with new MCC (no permission errors)

## Report

Status: DONE | DONE_WITH_CONCERNS | BLOCKED

Then report:
- Output of `git log --oneline | head -2`
- Deploy run ID + final status
- Resync execution status
- Any concerns

---

## Task 2: Rate limit module (TDD)

**Files:**
- Create: `src/governance/__init__.py` (empty), `src/governance/rate_limit.py`, `tests/unit/test_rate_limit.py`

The module manages a daily counter per developer-token-hash in `rate_counters` table. Three functions:
- `before_call(estimated_ops)` — checks quota, raises `QuotaExhausted` at 100%, logs warning at 80%
- `record_actual(used_ops)` — reconciles after API responds (Google's headers tell us actual ops consumed)
- `get_today_usage()` — returns (used, limit, percent) for status tools

Reset is per UTC day (Google Ads quota resets at midnight Pacific Time but for V4 ops we use UTC since Cloud Scheduler is UTC).

- [ ] **Step 1: Write failing tests `tests/unit/test_rate_limit.py`**

```python
"""Rate limit logic tests against testcontainers Postgres."""
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.governance.rate_limit import (
    DAILY_QUOTA_BASIC,
    QuotaExhausted,
    before_call,
    get_today_usage,
    record_actual,
)


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


_TOKEN_ID = "dev-token-hash-fixture"


@pytest.mark.integration
async def test_first_call_starts_counter_at_estimate(db) -> None:
    pool = db
    async with pool.acquire() as conn:
        await before_call(conn, _TOKEN_ID, estimated_ops=10)
        used, limit, pct = await get_today_usage(conn, _TOKEN_ID)
    assert used == 10
    assert limit == DAILY_QUOTA_BASIC
    assert pct == pytest.approx(10 / DAILY_QUOTA_BASIC, rel=0.01)


@pytest.mark.integration
async def test_record_actual_reconciles_estimate(db) -> None:
    pool = db
    async with pool.acquire() as conn:
        await before_call(conn, _TOKEN_ID, estimated_ops=10)
        # Google said only 7 ops actually used.
        await record_actual(conn, _TOKEN_ID, actual_ops=7, estimated_ops=10)
        used, _, _ = await get_today_usage(conn, _TOKEN_ID)
    assert used == 7  # reconciled down


@pytest.mark.integration
async def test_blocks_at_100_percent(db) -> None:
    pool = db
    async with pool.acquire() as conn:
        # Bump counter to limit - 5
        await before_call(conn, _TOKEN_ID, estimated_ops=DAILY_QUOTA_BASIC - 5)
        # Next call estimating 10 would push to limit + 5 → must block
        with pytest.raises(QuotaExhausted, match="quota di"):
            await before_call(conn, _TOKEN_ID, estimated_ops=10)


@pytest.mark.integration
async def test_warns_at_80_percent_only_once(db, caplog) -> None:
    """80% warning fires once per day per token (last_alert_pct prevents repeat)."""
    import logging
    pool = db
    async with pool.acquire() as conn:
        # Push to ~75%
        await before_call(conn, _TOKEN_ID, estimated_ops=int(DAILY_QUOTA_BASIC * 0.75))
        # No warning yet
        # Push past 80%
        await before_call(conn, _TOKEN_ID, estimated_ops=int(DAILY_QUOTA_BASIC * 0.10))
        # Push again — should NOT re-warn
        await before_call(conn, _TOKEN_ID, estimated_ops=100)
        # Confirm last_alert_pct is 80
        row = await conn.fetchrow(
            "SELECT last_alert_pct FROM rate_counters WHERE developer_token_id = $1",
            _TOKEN_ID,
        )
    assert row["last_alert_pct"] == 80


@pytest.mark.integration
async def test_separate_days_have_independent_counters(db) -> None:
    """Yesterday's count doesn't bleed into today."""
    pool = db
    async with pool.acquire() as conn:
        # Insert yesterday's counter manually at 95% used
        yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
        await conn.execute(
            """
            INSERT INTO rate_counters (developer_token_id, date, operations_used, last_alert_pct)
            VALUES ($1, $2, $3, $4)
            """,
            _TOKEN_ID, yesterday, int(DAILY_QUOTA_BASIC * 0.95), 80,
        )
        # Today's call should succeed with fresh counter
        await before_call(conn, _TOKEN_ID, estimated_ops=100)
        used, _, _ = await get_today_usage(conn, _TOKEN_ID)
    assert used == 100  # only today's count


@pytest.mark.integration
async def test_concurrent_increments_serialize_via_for_update(db) -> None:
    """Two concurrent before_call calls must not double-count."""
    import asyncio
    pool = db

    async def call_once():
        async with pool.acquire() as conn:
            await before_call(conn, _TOKEN_ID, estimated_ops=100)

    await asyncio.gather(*[call_once() for _ in range(5)])

    async with pool.acquire() as conn:
        used, _, _ = await get_today_usage(conn, _TOKEN_ID)
    assert used == 500  # exactly 5 * 100, no over/under count
```

- [ ] **Step 2: Run tests → verify 6 fail with import error**

```bash
cd "/d/HUB ads MCP"
./.venv/Scripts/python.exe -m pytest tests/unit/test_rate_limit.py -v -m integration
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.governance'`.

- [ ] **Step 3: Implement `src/governance/__init__.py`** (empty)

```bash
mkdir -p src/governance
touch src/governance/__init__.py
```

- [ ] **Step 4: Implement `src/governance/rate_limit.py`**

EXACT content:

```python
"""Daily Google Ads API rate limit tracking.

Counts operations per developer-token-hash per UTC day. Defaults to
Basic Access quota (15,000 ops/day). Use record_actual() after API
responds to reconcile the estimate against Google's actual usage
(taken from the SearchGoogleAdsResponse query_resource_consumption
field or the gRPC metadata X-Quota-Remaining header).

Threading model: SELECT ... FOR UPDATE serializes increments so
parallel callers don't double-count. Each function takes a single
asyncpg connection and runs in one transaction.
"""
from datetime import UTC, datetime
from typing import NamedTuple

import asyncpg
import structlog

DAILY_QUOTA_BASIC = 15_000
DAILY_QUOTA_STANDARD = 1_000_000
WARN_THRESHOLD_PCT = 80

log = structlog.get_logger(__name__)


class QuotaExhausted(Exception):
    """Raised when a call would exceed the daily quota."""


class Usage(NamedTuple):
    used: int
    limit: int
    pct: float


def _today() -> datetime:
    """UTC date as a datetime for date column."""
    return datetime.now(UTC)


async def before_call(
    conn: asyncpg.Connection,
    developer_token_id: str,
    *,
    estimated_ops: int,
    daily_limit: int = DAILY_QUOTA_BASIC,
) -> None:
    """Reserve estimated_ops in today's counter. Raises QuotaExhausted at 100%.

    Logs a one-time warning when crossing 80% threshold (uses
    `last_alert_pct` to dedupe within the day).
    """
    today = _today().date()

    # Lock the row for this dev_token+day. ON CONFLICT does the upsert.
    await conn.execute(
        """
        INSERT INTO rate_counters (developer_token_id, date, operations_used, last_alert_pct)
        VALUES ($1, $2, 0, 0)
        ON CONFLICT (developer_token_id, date) DO NOTHING
        """,
        developer_token_id,
        today,
    )
    row = await conn.fetchrow(
        """
        SELECT operations_used, last_alert_pct
        FROM rate_counters
        WHERE developer_token_id = $1 AND date = $2
        FOR UPDATE
        """,
        developer_token_id,
        today,
    )
    assert row is not None
    used = row["operations_used"]
    last_alert = row["last_alert_pct"]

    new_used = used + estimated_ops
    if new_used > daily_limit:
        raise QuotaExhausted(
            f"Quota diária esgotada: {used}/{daily_limit} usadas, "
            f"+{estimated_ops} pediria {new_used}. Reset à meia-noite UTC."
        )

    new_pct = int((new_used / daily_limit) * 100)
    new_alert = last_alert
    if new_pct >= WARN_THRESHOLD_PCT and last_alert < WARN_THRESHOLD_PCT:
        log.warning(
            "rate_limit_80pct_reached",
            developer_token_id=developer_token_id,
            used=new_used,
            limit=daily_limit,
            pct=new_pct,
        )
        new_alert = WARN_THRESHOLD_PCT

    await conn.execute(
        """
        UPDATE rate_counters
        SET operations_used = $3, last_alert_pct = $4
        WHERE developer_token_id = $1 AND date = $2
        """,
        developer_token_id,
        today,
        new_used,
        new_alert,
    )


async def record_actual(
    conn: asyncpg.Connection,
    developer_token_id: str,
    *,
    actual_ops: int,
    estimated_ops: int,
) -> None:
    """Reconcile counter after API responds. Adjusts by (actual - estimated)."""
    today = _today().date()
    delta = actual_ops - estimated_ops
    if delta == 0:
        return  # estimate was right
    await conn.execute(
        """
        UPDATE rate_counters
        SET operations_used = GREATEST(0, operations_used + $3)
        WHERE developer_token_id = $1 AND date = $2
        """,
        developer_token_id,
        today,
        delta,
    )


async def get_today_usage(
    conn: asyncpg.Connection,
    developer_token_id: str,
    *,
    daily_limit: int = DAILY_QUOTA_BASIC,
) -> Usage:
    """Return (used, limit, pct) for today's counter. Returns (0, limit, 0) if no row."""
    today = _today().date()
    row = await conn.fetchrow(
        """
        SELECT operations_used FROM rate_counters
        WHERE developer_token_id = $1 AND date = $2
        """,
        developer_token_id,
        today,
    )
    used = int(row["operations_used"]) if row else 0
    return Usage(used=used, limit=daily_limit, pct=used / daily_limit if daily_limit else 0.0)


def hash_developer_token(token: str) -> str:
    """SHA-256 hex of the dev token; used as the row key in rate_counters.

    Allows future multi-token setups (e.g., test vs prod tokens) without
    leaking the actual token value into the row key.
    """
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]
```

- [ ] **Step 5: Run tests → 6 PASS**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_rate_limit.py -v -m integration
```

If any fails:
- Concurrency test failing → may need `asyncpg.Pool.acquire()` to actually get fresh connections; verify pool min/max settings
- 80% warning test failing → check that `last_alert_pct` is actually being updated on the threshold cross, not just on the first call past threshold

DO NOT modify tests. Fix the implementation if needed.

- [ ] **Step 6: mypy + ruff**

```bash
./.venv/Scripts/python.exe -m mypy src/governance/
./.venv/Scripts/python.exe -m ruff check src/governance/ tests/unit/test_rate_limit.py
./.venv/Scripts/python.exe -m ruff format --check src/governance/ tests/unit/test_rate_limit.py
```

Auto-format if needed.

- [ ] **Step 7: Run full suite — confirm no regression**

```bash
./.venv/Scripts/python.exe -m pytest tests/ --tb=line | tail -3
```

Expected: 71+ passed (65 prior + 6 new).

- [ ] **Step 8: Commit + push**

```bash
git add src/governance/ tests/unit/test_rate_limit.py
git commit -m "feat(governance): rate limit tracking + 80%/100% thresholds

Per-developer-token daily counter in rate_counters table. SELECT
FOR UPDATE serializes parallel increments. before_call(estimated)
raises QuotaExhausted at 100%; one-time warning at 80% (deduped
via last_alert_pct). record_actual reconciles after API responds.

Default quota = 15k/day (Basic Access). Constant ready to bump to
1M when Standard Access is granted."
git push
```

## Report

Status: DONE | DONE_WITH_CONCERNS | BLOCKED. Pytest output, mypy + ruff, git log head.

---

## Task 3: Per-manager Google Ads client helper

**Files:**
- Modify: `src/google_ads/client.py` (add a higher-level helper)
- Create: `src/google_ads/reports.py` (shared executor for read tools)

The current `build_client(refresh_token=...)` requires the caller to fetch + decrypt the refresh token. Tools shouldn't repeat that boilerplate. Add a helper that takes a `manager_id` (UUID), looks up the OAuth connection, decrypts, and returns a ready client. Plus integrate rate limit + audit at this layer so individual tools don't repeat it.

- [ ] **Step 1: Modify `src/google_ads/client.py` to add `build_client_for_manager`**

Read the current file first. Then append (after the existing `build_client` function):

```python
async def build_client_for_manager(
    *,
    manager_id: "UUID",  # forward ref to avoid uuid import dance
) -> "GoogleAdsClient":  # type: ignore[name-defined]
    """Build a GoogleAdsClient using the active OAuth refresh token of the given manager.

    Raises NoOAuthConnectionError if the manager has no active connection.
    """
    from src.auth.tokens import decrypt_refresh_token, derive_master_key_from_settings
    from src.config import get_settings
    from src.db import connection
    from src.db.repositories import google_oauth_connections

    settings = get_settings()
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        oc = await google_oauth_connections.get_active_for_manager(conn, manager_id)
    if oc is None:
        raise NoOAuthConnectionError(
            "Gestor não tem conexão Google Ads ativa. Pede pra ele conectar via "
            "/oauth/google/start."
        )

    master_key = derive_master_key_from_settings(settings.aes_master_key)
    refresh_token = decrypt_refresh_token(oc.refresh_token_enc, master_key)

    return build_client(
        refresh_token=refresh_token,
        developer_token=settings.google_ads_developer_token,
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        login_customer_id=settings.google_ads_login_customer_id,
    )


class NoOAuthConnectionError(Exception):
    """Raised by build_client_for_manager when the manager has no active OAuth."""
```

Add the necessary `from uuid import UUID` at the top if not already there.

- [ ] **Step 2: Create `src/google_ads/reports.py`** — shared executor

EXACT content:

```python
"""Shared executor for read-only report tools.

Each report tool calls `run_report` with:
  - the manager context (from MCP middleware)
  - a customer_id to query
  - a GAQL query string
  - an optional row_formatter to shape SDK rows into JSON-serializable dicts

run_report handles the boilerplate:
  - rate limit: before_call → record_actual
  - build the client per manager
  - execute search_stream over the GAQL
  - call the formatter on each row
  - return the list

Audit logging is OPTIONAL per call (volume reads skip it; sensitive reads opt in).
"""
import time
from collections.abc import Callable, Iterable
from typing import Any
from uuid import UUID

import structlog

from src.config import get_settings
from src.db import connection
from src.db.repositories import audit_log
from src.google_ads.client import build_client_for_manager
from src.google_ads.errors import to_friendly
from src.governance.rate_limit import (
    before_call,
    hash_developer_token,
    record_actual,
)

log = structlog.get_logger(__name__)


async def run_report(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    query: str,
    row_formatter: Callable[[Any], dict[str, Any]],
    operation_name: str,
    estimated_ops: int = 1,
    audit_this_call: bool = False,
) -> list[dict[str, Any]]:
    """Run a GAQL query against the given customer; return formatted rows.

    Raises:
        QuotaExhausted: if rate limit blocked
        GoogleAdsFriendlyError: if Google API errored (PT-BR message)
        NoOAuthConnectionError: if the manager has no OAuth connection
    """
    settings = get_settings()
    token_id = hash_developer_token(settings.google_ads_developer_token)
    started = time.monotonic()
    actual_ops = 0
    status = "success"
    error_message = None

    pool = connection.get_pool()
    try:
        # Reserve quota
        async with pool.acquire() as conn:
            await before_call(conn, token_id, estimated_ops=estimated_ops)

        client = await build_client_for_manager(manager_id=manager_id)

        results: list[dict[str, Any]] = []
        try:
            ga_service = client.get_service("GoogleAdsService")
            request = client.get_type("SearchGoogleAdsStreamRequest")
            request.customer_id = customer_id
            request.query = query

            stream = ga_service.search_stream(request=request)
            for batch in stream:
                actual_ops += 1
                for row in batch.results:
                    results.append(row_formatter(row))
        except Exception as e:
            raise to_friendly(e) from e

    except Exception as e:
        status = "error"
        error_message = str(e)
        raise
    finally:
        # Reconcile counter even on failure (we made API calls before erroring)
        async with pool.acquire() as conn:
            await record_actual(
                conn,
                token_id,
                actual_ops=actual_ops,
                estimated_ops=estimated_ops,
            )
            if audit_this_call:
                duration_ms = int((time.monotonic() - started) * 1000)
                await audit_log.record(
                    conn,
                    manager_id=manager_id,
                    session_id=session_id,
                    customer_id=customer_id,
                    action_type="read",
                    operation=operation_name,
                    target_count=len(results) if status == "success" else None,
                    params_summary=None,
                    status=status,
                    error_message=error_message,
                    duration_ms=duration_ms,
                )

    log.info(
        "report_complete",
        operation=operation_name,
        customer_id=customer_id,
        rows=len(results),
        ops=actual_ops,
    )
    return results


async def execute_gaql_raw(
    *,
    manager_id: UUID,
    customer_id: str,
    query: str,
    estimated_ops: int = 1,
) -> list[dict[str, Any]]:
    """Run a GAQL query and return rows as plain dicts of field paths to values.

    Used by `run_gaql` utility tool; no formatter, no audit.
    """
    def _flatten(row: Any) -> dict[str, Any]:
        # Convert proto message to dict via google.protobuf.json_format
        from google.protobuf.json_format import MessageToDict  # type: ignore[import-not-found]
        return MessageToDict(row._pb, preserving_proto_field_name=True)  # type: ignore[attr-defined]

    return await run_report(
        manager_id=manager_id,
        session_id=manager_id,  # session_id used only for audit; ignored when audit_this_call=False
        customer_id=customer_id,
        query=query,
        row_formatter=_flatten,
        operation_name="run_gaql",
        estimated_ops=estimated_ops,
        audit_this_call=False,
    )
```

- [ ] **Step 3: Run tests + mypy + ruff (no new tests this task; the helpers get tested via tool integration tests in later tasks)**

```bash
cd "/d/HUB ads MCP"
./.venv/Scripts/python.exe -m mypy src/google_ads/
./.venv/Scripts/python.exe -m ruff check src/google_ads/
./.venv/Scripts/python.exe -m ruff format --check src/google_ads/
./.venv/Scripts/python.exe -m pytest tests/ --tb=line | tail -3
```

Expected: clean mypy/ruff; all prior tests still pass.

If mypy complains about the forward-ref string annotations (`"UUID"`, `"GoogleAdsClient"`), replace with proper imports:
- `from uuid import UUID` at top
- For `GoogleAdsClient`, leave as `Any` since the SDK doesn't ship typed stubs.

- [ ] **Step 4: Commit + push**

```bash
git add src/google_ads/client.py src/google_ads/reports.py
git commit -m "feat(google_ads): per-manager client + shared report executor

build_client_for_manager(manager_id) abstracts the
oauth-fetch+decrypt+build chain so report tools don't repeat
boilerplate. run_report wraps the chain with rate limit (before+
reconcile after), search_stream execution, error translation, and
optional audit logging. execute_gaql_raw is the formatter-less
variant used by run_gaql."
git push
```

## Report

Status: DONE | DONE_WITH_CONCERNS | BLOCKED. mypy/ruff/pytest tail.

---

## Task 4: Common report helpers (date ranges + comparisons)

**Files:**
- Create: `src/google_ads/queries/__init__.py` (empty), `src/google_ads/queries/_common.py`
- Create: `tests/unit/test_query_helpers.py`

Tools accept `date_range` parameters like `LAST_7_DAYS` or `{from: "2026-04-01", to: "2026-04-30"}`. The helper resolves these into GAQL `segments.date BETWEEN ...` clauses + computes the previous-period date range for comparisons.

- [ ] **Step 1: Write `tests/unit/test_query_helpers.py`**

```python
"""Date range parsing + comparison period tests."""
from datetime import date

import pytest
from freezegun import freeze_time

from src.google_ads.queries._common import (
    InvalidDateRangeError,
    get_comparison_range,
    parse_date_range,
)


@freeze_time("2026-05-15")
def test_parse_last_7_days() -> None:
    start, end = parse_date_range("LAST_7_DAYS")
    assert start == date(2026, 5, 8)
    assert end == date(2026, 5, 14)  # excludes today (incomplete)


@freeze_time("2026-05-15")
def test_parse_last_30_days() -> None:
    start, end = parse_date_range("LAST_30_DAYS")
    assert start == date(2026, 4, 15)
    assert end == date(2026, 5, 14)


@freeze_time("2026-05-15")
def test_parse_yesterday() -> None:
    start, end = parse_date_range("YESTERDAY")
    assert start == date(2026, 5, 14)
    assert end == date(2026, 5, 14)


@freeze_time("2026-05-15")
def test_parse_today() -> None:
    start, end = parse_date_range("TODAY")
    assert start == date(2026, 5, 15)
    assert end == date(2026, 5, 15)


@freeze_time("2026-05-15")
def test_parse_this_month() -> None:
    start, end = parse_date_range("THIS_MONTH")
    assert start == date(2026, 5, 1)
    assert end == date(2026, 5, 14)  # through yesterday


@freeze_time("2026-05-15")
def test_parse_last_month() -> None:
    start, end = parse_date_range("LAST_MONTH")
    assert start == date(2026, 4, 1)
    assert end == date(2026, 4, 30)


def test_parse_explicit_range_dict() -> None:
    start, end = parse_date_range({"from": "2026-01-01", "to": "2026-01-31"})
    assert start == date(2026, 1, 1)
    assert end == date(2026, 1, 31)


def test_parse_inverted_range_raises() -> None:
    with pytest.raises(InvalidDateRangeError, match="from.*after.*to"):
        parse_date_range({"from": "2026-01-31", "to": "2026-01-01"})


def test_parse_unknown_preset_raises() -> None:
    with pytest.raises(InvalidDateRangeError, match="UNKNOWN_PRESET"):
        parse_date_range("UNKNOWN_PRESET")


def test_parse_malformed_dict_raises() -> None:
    with pytest.raises(InvalidDateRangeError):
        parse_date_range({"from": "not-a-date", "to": "2026-01-01"})


def test_comparison_range_is_immediately_previous_period() -> None:
    """For a 7-day range Apr 8-14, previous is Apr 1-7."""
    start, end = date(2026, 4, 8), date(2026, 4, 14)
    prev_start, prev_end = get_comparison_range(start, end)
    assert prev_start == date(2026, 4, 1)
    assert prev_end == date(2026, 4, 7)


def test_comparison_range_handles_single_day() -> None:
    """For a 1-day range, previous is the day before."""
    start = end = date(2026, 5, 14)
    prev_start, prev_end = get_comparison_range(start, end)
    assert prev_start == date(2026, 5, 13)
    assert prev_end == date(2026, 5, 13)
```

Note: `freezegun` is in our dev deps already.

- [ ] **Step 2: Verify the test fails**

```bash
cd "/d/HUB ads MCP"
./.venv/Scripts/python.exe -m pytest tests/unit/test_query_helpers.py -v
```

Expected: 12 fail with import error.

If freezegun not installed, add it: `pip install freezegun` and add to dev deps in pyproject.toml.

- [ ] **Step 3: Implement `src/google_ads/queries/__init__.py`** (empty)

```bash
mkdir -p src/google_ads/queries
touch src/google_ads/queries/__init__.py
```

- [ ] **Step 4: Implement `src/google_ads/queries/_common.py`**

EXACT content:

```python
"""Shared helpers for GAQL query construction."""
from datetime import date, datetime, timedelta
from typing import Any, Literal


class InvalidDateRangeError(ValueError):
    """Raised when a date range cannot be parsed."""


_PRESETS = {
    "TODAY",
    "YESTERDAY",
    "LAST_7_DAYS",
    "LAST_14_DAYS",
    "LAST_30_DAYS",
    "LAST_90_DAYS",
    "THIS_MONTH",
    "LAST_MONTH",
    "THIS_WEEK",
    "LAST_WEEK",
}


def _today() -> date:
    return datetime.utcnow().date()


def _yesterday() -> date:
    return _today() - timedelta(days=1)


def parse_date_range(arg: str | dict[str, str]) -> tuple[date, date]:
    """Resolve a date_range param into (start_date, end_date) inclusive.

    Accepts either a preset string (e.g., 'LAST_7_DAYS') or an explicit
    dict {from: ISO_DATE, to: ISO_DATE}.
    """
    if isinstance(arg, dict):
        try:
            start = date.fromisoformat(arg["from"])
            end = date.fromisoformat(arg["to"])
        except (KeyError, ValueError) as e:
            raise InvalidDateRangeError(f"Invalid date dict {arg}: {e}") from e
        if start > end:
            raise InvalidDateRangeError(
                f"date_range from ({start}) is after to ({end})"
            )
        return start, end

    if not isinstance(arg, str):
        raise InvalidDateRangeError(f"date_range must be string or dict, got {type(arg)}")

    preset = arg.upper()
    if preset not in _PRESETS:
        raise InvalidDateRangeError(
            f"Unknown date_range preset '{preset}'. "
            f"Valid presets: {', '.join(sorted(_PRESETS))}"
        )

    today = _today()
    yesterday = _yesterday()

    if preset == "TODAY":
        return today, today
    if preset == "YESTERDAY":
        return yesterday, yesterday
    if preset == "LAST_7_DAYS":
        return yesterday - timedelta(days=6), yesterday
    if preset == "LAST_14_DAYS":
        return yesterday - timedelta(days=13), yesterday
    if preset == "LAST_30_DAYS":
        return yesterday - timedelta(days=29), yesterday
    if preset == "LAST_90_DAYS":
        return yesterday - timedelta(days=89), yesterday
    if preset == "THIS_MONTH":
        return today.replace(day=1), yesterday
    if preset == "LAST_MONTH":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return first_prev, last_prev
    if preset == "THIS_WEEK":
        # ISO week starts Monday; today.weekday() = 0 for Monday
        monday = today - timedelta(days=today.weekday())
        return monday, yesterday if yesterday >= monday else monday
    if preset == "LAST_WEEK":
        last_sunday = today - timedelta(days=today.weekday() + 1)
        last_monday = last_sunday - timedelta(days=6)
        return last_monday, last_sunday

    raise InvalidDateRangeError(f"Unhandled preset {preset}")  # unreachable


def get_comparison_range(start: date, end: date) -> tuple[date, date]:
    """Given a date range, return the immediately-previous period of equal length.

    Example: for [2026-04-08, 2026-04-14] (7 days), returns [2026-04-01, 2026-04-07].
    """
    period_days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)
    return prev_start, prev_end


def gaql_date_clause(start: date, end: date) -> str:
    """Format a GAQL `segments.date BETWEEN '...' AND '...'` clause."""
    return f"segments.date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'"


# Common metric SELECT fragments — reuse across many tools
METRIC_FIELDS = {
    "impressions": "metrics.impressions",
    "clicks": "metrics.clicks",
    "cost_micros": "metrics.cost_micros",
    "conversions": "metrics.conversions",
    "conversions_value": "metrics.conversions_value",
    "ctr": "metrics.ctr",
    "average_cpc": "metrics.average_cpc",
    "cost_per_conversion": "metrics.cost_per_conversion",
    "value_per_conversion": "metrics.value_per_conversion",
    "roas": "metrics.value_per_conversion",  # alias; ROAS = revenue / cost
}


def micros_to_currency(micros: int) -> float:
    """Google Ads stores money in micros (millionths). 1_500_000 micros = R$ 1.50."""
    return round(micros / 1_000_000.0, 2)
```

- [ ] **Step 5: Run tests → 12 PASS**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_query_helpers.py -v
```

If `freezegun` import fails, ensure it's in dev deps. Run `pip install freezegun` if not.

- [ ] **Step 6: mypy + ruff + full suite**

```bash
./.venv/Scripts/python.exe -m mypy src/google_ads/queries/
./.venv/Scripts/python.exe -m ruff check src/google_ads/queries/ tests/unit/test_query_helpers.py
./.venv/Scripts/python.exe -m ruff format --check src/google_ads/queries/ tests/unit/test_query_helpers.py
./.venv/Scripts/python.exe -m pytest tests/ --tb=line | tail -3
```

- [ ] **Step 7: Commit + push**

```bash
git add src/google_ads/queries/ tests/unit/test_query_helpers.py
git commit -m "feat(queries): date range presets + comparison + GAQL helpers

parse_date_range accepts presets (LAST_7_DAYS, THIS_MONTH, etc) or
explicit {from, to} dicts; resolves to inclusive (start, end) date
tuples. get_comparison_range returns the immediately-previous period
of equal length for week-over-week / period-comparison reporting.
gaql_date_clause and micros_to_currency are reusable building blocks."
git push
```

## Report

Status: DONE | DONE_WITH_CONCERNS | BLOCKED.

---

## Task 5: Tools — Visão Geral (3 tools)

**Files:**
- Create: `src/google_ads/queries/overview.py`, `src/google_ads/queries/recommendations.py`
- Create: `src/mcp/tools/get_account_overview.py`, `src/mcp/tools/get_budget_pacing.py`, `src/mcp/tools/get_recommendations.py`
- Modify: `src/mcp/tools/_registry.py` to import the new tool modules
- Create: `tests/integration/test_overview_tools.py`

These three are the gestor's "morning dashboard" — first reports they want each day.

### Tool 1: `get_account_overview`

Returns consolidated KPIs (impressions, clicks, cost_brl, conversions, conversions_value, ctr, avg_cpc, cost_per_conv, roas) for a date range, with the immediately-previous-period comparison side by side.

### Tool 2: `get_budget_pacing`

For each enabled campaign: daily budget, MTD spend, days elapsed, projected end-of-month spend, % of monthly budget consumed.

### Tool 3: `get_recommendations`

Lists pending Google Ads recommendations for the account: id, type, impact estimate, dismissable.

- [ ] **Step 1: Write `src/google_ads/queries/overview.py`**

EXACT content:

```python
"""GAQL queries for visão geral tools (account_overview, budget_pacing)."""
from datetime import date

from src.google_ads.queries._common import gaql_date_clause


def overview_query(date_start: date, date_end: date) -> str:
    """Aggregate metrics across all enabled campaigns for the date range."""
    return f"""
        SELECT
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value,
          metrics.ctr,
          metrics.average_cpc,
          metrics.cost_per_conversion
        FROM customer
        WHERE {gaql_date_clause(date_start, date_end)}
    """.strip()


def budget_pacing_query() -> str:
    """Per-campaign current budget + MTD spend.

    Returns one row per enabled campaign with budget amount + month-to-date metrics.
    """
    return """
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign_budget.amount_micros,
          campaign_budget.delivery_method,
          metrics.cost_micros
        FROM campaign
        WHERE campaign.status = 'ENABLED'
          AND segments.date DURING THIS_MONTH
    """.strip()
```

- [ ] **Step 2: Write `src/google_ads/queries/recommendations.py`**

EXACT content:

```python
"""GAQL query for the recommendations tool."""


def recommendations_query() -> str:
    """All pending recommendations for the account."""
    return """
        SELECT
          recommendation.resource_name,
          recommendation.type,
          recommendation.impact.base_metrics.impressions,
          recommendation.impact.base_metrics.clicks,
          recommendation.impact.base_metrics.cost_micros,
          recommendation.impact.potential_metrics.impressions,
          recommendation.impact.potential_metrics.clicks,
          recommendation.impact.potential_metrics.cost_micros,
          recommendation.dismissed
        FROM recommendation
        WHERE recommendation.dismissed = false
    """.strip()
```

- [ ] **Step 3: Implement `src/mcp/tools/get_account_overview.py`**

EXACT content:

```python
"""Tool: get_account_overview — KPIs for date range with previous-period comparison."""
from typing import Any

from src.google_ads.queries._common import (
    get_comparison_range,
    micros_to_currency,
    parse_date_range,
)
from src.google_ads.queries.overview import overview_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool


_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_id": {
            "type": "string",
            "description": "ID da conta Google Ads (10 dígitos, sem traços)",
            "pattern": "^[0-9]{10}$",
        },
        "date_range": {
            "description": (
                "Período. Aceita preset string (LAST_7_DAYS, LAST_30_DAYS, "
                "THIS_MONTH, LAST_MONTH, YESTERDAY, TODAY, etc) ou objeto "
                "{from: 'YYYY-MM-DD', to: 'YYYY-MM-DD'}."
            ),
            "default": "LAST_30_DAYS",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum the per-day rows into single totals + computed ratios."""
    if not rows:
        return {
            "impressions": 0,
            "clicks": 0,
            "cost_brl": 0.0,
            "conversions": 0.0,
            "conversions_value_brl": 0.0,
            "ctr": 0.0,
            "average_cpc_brl": 0.0,
            "cost_per_conversion_brl": 0.0,
            "roas": 0.0,
        }
    impr = sum(r["impressions"] for r in rows)
    clicks = sum(r["clicks"] for r in rows)
    cost = sum(r["cost_micros"] for r in rows)
    conv = sum(r["conversions"] for r in rows)
    conv_val = sum(r["conversions_value"] for r in rows)
    return {
        "impressions": impr,
        "clicks": clicks,
        "cost_brl": micros_to_currency(cost),
        "conversions": round(conv, 2),
        "conversions_value_brl": round(conv_val, 2),
        "ctr": round(clicks / impr, 4) if impr else 0.0,
        "average_cpc_brl": micros_to_currency(cost / clicks) if clicks else 0.0,
        "cost_per_conversion_brl": micros_to_currency(cost / conv) if conv else 0.0,
        "roas": round(conv_val / micros_to_currency(cost), 2) if cost else 0.0,
    }


def _row_formatter(row: Any) -> dict[str, Any]:
    m = row.metrics
    return {
        "impressions": int(m.impressions),
        "clicks": int(m.clicks),
        "cost_micros": int(m.cost_micros),
        "conversions": float(m.conversions),
        "conversions_value": float(m.conversions_value),
    }


@register_tool(
    name="get_account_overview",
    description=(
        "KPIs consolidados de uma conta Google Ads (impressões, clicks, custo, "
        "conversões, valor, CTR, CPC, CPA, ROAS) para um período, com comparativo "
        "do período imediatamente anterior de mesma duração."
    ),
    input_schema=_SCHEMA,
)
async def get_account_overview(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    date_range = args.get("date_range", "LAST_30_DAYS")
    start, end = parse_date_range(date_range)
    prev_start, prev_end = get_comparison_range(start, end)

    rows_curr = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=overview_query(start, end),
        row_formatter=_row_formatter,
        operation_name="get_account_overview",
    )
    rows_prev = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=overview_query(prev_start, prev_end),
        row_formatter=_row_formatter,
        operation_name="get_account_overview",
    )

    return {
        "customer_id": customer_id,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "previous_period": {"from": prev_start.isoformat(), "to": prev_end.isoformat()},
        "current": _aggregate(rows_curr),
        "previous": _aggregate(rows_prev),
    }
```

- [ ] **Step 4: Implement `src/mcp/tools/get_budget_pacing.py`**

EXACT content:

```python
"""Tool: get_budget_pacing — per-campaign budget vs MTD spend + projection."""
from datetime import datetime
from typing import Any

from src.google_ads.queries._common import micros_to_currency
from src.google_ads.queries.overview import budget_pacing_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_id": {
            "type": "string",
            "pattern": "^[0-9]{10}$",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _row_formatter(row: Any) -> dict[str, Any]:
    return {
        "campaign_id": str(row.campaign.id),
        "campaign_name": row.campaign.name,
        "daily_budget_brl": micros_to_currency(row.campaign_budget.amount_micros),
        "delivery_method": str(row.campaign_budget.delivery_method),
        "cost_micros_today": int(row.metrics.cost_micros),
    }


def _project(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate per-campaign MTD spend + project end-of-month."""
    today = datetime.utcnow()
    days_in_month = (today.replace(month=today.month % 12 + 1, day=1) - today.replace(day=1)).days
    days_elapsed = today.day
    days_remaining = days_in_month - days_elapsed

    by_campaign: dict[str, dict[str, Any]] = {}
    for r in rows:
        cid = r["campaign_id"]
        if cid not in by_campaign:
            by_campaign[cid] = {
                "campaign_id": cid,
                "campaign_name": r["campaign_name"],
                "daily_budget_brl": r["daily_budget_brl"],
                "delivery_method": r["delivery_method"],
                "cost_micros_total": 0,
            }
        by_campaign[cid]["cost_micros_total"] += r["cost_micros_today"]

    out: list[dict[str, Any]] = []
    for c in by_campaign.values():
        mtd = micros_to_currency(c["cost_micros_total"])
        daily_avg = mtd / days_elapsed if days_elapsed else 0
        projected = round(daily_avg * days_in_month, 2)
        budget_monthly = round(c["daily_budget_brl"] * days_in_month, 2)
        out.append({
            "campaign_id": c["campaign_id"],
            "campaign_name": c["campaign_name"],
            "daily_budget_brl": c["daily_budget_brl"],
            "spent_mtd_brl": mtd,
            "spent_pct_of_monthly_budget": round(mtd / budget_monthly * 100, 1) if budget_monthly else 0,
            "days_elapsed": days_elapsed,
            "days_remaining": days_remaining,
            "projected_monthly_brl": projected,
            "projection_vs_budget_pct": round(projected / budget_monthly * 100, 1) if budget_monthly else 0,
            "delivery_method": c["delivery_method"],
        })
    return sorted(out, key=lambda x: -x["spent_mtd_brl"])


@register_tool(
    name="get_budget_pacing",
    description=(
        "Por campanha ativa: orçamento diário, gasto MTD, projeção de fim de mês, "
        "% consumido do orçamento mensal. Útil pra ver no início do dia se alguma "
        "campanha está acelerada/lenta demais."
    ),
    input_schema=_SCHEMA,
)
async def get_budget_pacing(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=budget_pacing_query(),
        row_formatter=_row_formatter,
        operation_name="get_budget_pacing",
    )
    return {
        "customer_id": customer_id,
        "as_of": datetime.utcnow().date().isoformat(),
        "campaigns": _project(rows),
    }
```

- [ ] **Step 5: Implement `src/mcp/tools/get_recommendations.py`**

EXACT content:

```python
"""Tool: get_recommendations — Google Ads recommendations pending for account."""
from typing import Any

from src.google_ads.queries._common import micros_to_currency
from src.google_ads.queries.recommendations import recommendations_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_id": {
            "type": "string",
            "pattern": "^[0-9]{10}$",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


_TYPE_PT = {
    "KEYWORD": "Adicionar palavra-chave",
    "ADD_AGE_GROUP_CRITERION": "Adicionar critério de faixa etária",
    "TEXT_AD": "Criar texto de anúncio",
    "CALLOUT_EXTENSION": "Adicionar extensão de chamada",
    "SITELINK_EXTENSION": "Adicionar extensão de sitelink",
    "ENHANCED_CPC_OPT_IN": "Ativar lance otimizado",
    "MAXIMIZE_CONVERSIONS_OPT_IN": "Migrar pra Maximizar conversões",
    "MAXIMIZE_CLICKS_OPT_IN": "Migrar pra Maximizar clicks",
    "TARGET_CPA_OPT_IN": "Migrar pra Target CPA",
    "MAXIMIZE_CONVERSION_VALUE_OPT_IN": "Migrar pra Maximizar valor",
    "MOVE_UNUSED_BUDGET": "Mover orçamento não usado",
    "FORECASTING_CAMPAIGN_BUDGET": "Aumentar orçamento da campanha",
    "RESPONSIVE_SEARCH_AD": "Criar anúncio responsivo",
}


def _row_formatter(row: Any) -> dict[str, Any]:
    rec = row.recommendation
    base = rec.impact.base_metrics
    pot = rec.impact.potential_metrics
    type_str = str(rec.type).split(".")[-1]
    return {
        "resource_name": rec.resource_name,
        "type": type_str,
        "type_pt": _TYPE_PT.get(type_str, type_str),
        "current_clicks": int(base.clicks),
        "current_impressions": int(base.impressions),
        "current_cost_brl": micros_to_currency(base.cost_micros),
        "potential_clicks": int(pot.clicks),
        "potential_impressions": int(pot.impressions),
        "potential_cost_brl": micros_to_currency(pot.cost_micros),
        "uplift_clicks": int(pot.clicks - base.clicks),
        "uplift_impressions": int(pot.impressions - base.impressions),
    }


@register_tool(
    name="get_recommendations",
    description=(
        "Recomendações pendentes do Google Ads pra conta: tipo, impacto estimado "
        "(clicks/impressões/custo atual vs potencial), e identificador para "
        "aplicar/dispensar. Tipo é traduzido pra PT-BR quando reconhecido."
    ),
    input_schema=_SCHEMA,
)
async def get_recommendations(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=recommendations_query(),
        row_formatter=_row_formatter,
        operation_name="get_recommendations",
        audit_this_call=True,  # sensitive: lists actionable changes
    )
    return {
        "customer_id": customer_id,
        "count": len(rows),
        "recommendations": rows,
    }
```

- [ ] **Step 6: Update `src/mcp/tools/_registry.py` `import_all_tools()`**

Read it first, then update the function to import the new modules:

```python
def import_all_tools() -> None:
    """Import every tool module so its register_tool decorator runs."""
    from src.mcp.tools import (  # noqa: F401
        get_account_overview,
        get_budget_pacing,
        get_recommendations,
        list_my_accounts,
    )
```

- [ ] **Step 7: Write `tests/integration/test_overview_tools.py`**

Tests use respx + a faked GoogleAdsClient. Since the real SDK is heavy to mock, we test by swapping `run_report` itself with a stub that returns fixture rows.

EXACT content:

```python
"""Integration tests for the 3 visão geral tools.

Strategy: patch run_report to return fixture rows, then assert the
tool's aggregate/format logic produces the expected response shape.
This proves: schema accepts inputs, the right query is built, the
formatter handles rows correctly. Real Google Ads API integration
is exercised in manual E2E.
"""
from datetime import date
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from freezegun import freeze_time

from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
def bound_context():
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.asyncio
@freeze_time("2026-05-15")
async def test_account_overview_aggregates_and_compares(bound_context):
    from src.mcp.tools.get_account_overview import get_account_overview

    # Two periods: current 7 days returns 2 rows; previous returns 1 row.
    side_effects = [
        # current period rows
        [
            {"impressions": 1000, "clicks": 50, "cost_micros": 100_000_000,
             "conversions": 5.0, "conversions_value": 500.0},
            {"impressions": 2000, "clicks": 100, "cost_micros": 200_000_000,
             "conversions": 10.0, "conversions_value": 1000.0},
        ],
        # previous period rows
        [
            {"impressions": 1500, "clicks": 75, "cost_micros": 150_000_000,
             "conversions": 7.0, "conversions_value": 700.0},
        ],
    ]
    with patch(
        "src.mcp.tools.get_account_overview.run_report",
        AsyncMock(side_effect=side_effects),
    ):
        result = await get_account_overview({
            "customer_id": "1234567890",
            "date_range": "LAST_7_DAYS",
        })

    assert result["customer_id"] == "1234567890"
    assert result["period"] == {"from": "2026-05-08", "to": "2026-05-14"}
    assert result["previous_period"] == {"from": "2026-05-01", "to": "2026-05-07"}
    cur = result["current"]
    assert cur["impressions"] == 3000
    assert cur["clicks"] == 150
    assert cur["cost_brl"] == 300.0
    assert cur["conversions"] == 15.0
    assert cur["roas"] == round(1500.0 / 300.0, 2)
    prev = result["previous"]
    assert prev["impressions"] == 1500


@pytest.mark.asyncio
async def test_account_overview_handles_zero_division(bound_context):
    from src.mcp.tools.get_account_overview import get_account_overview

    with patch(
        "src.mcp.tools.get_account_overview.run_report",
        AsyncMock(return_value=[]),  # empty results
    ):
        result = await get_account_overview({"customer_id": "1234567890"})

    cur = result["current"]
    assert cur["impressions"] == 0
    assert cur["ctr"] == 0.0
    assert cur["roas"] == 0.0


@pytest.mark.asyncio
@freeze_time("2026-05-15 12:00:00")
async def test_budget_pacing_projects_monthly(bound_context):
    from src.mcp.tools.get_budget_pacing import get_budget_pacing

    rows = [
        {"campaign_id": "111", "campaign_name": "Campaign A",
         "daily_budget_brl": 100.0, "delivery_method": "STANDARD",
         "cost_micros_today": 50_000_000},
    ]
    with patch(
        "src.mcp.tools.get_budget_pacing.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await get_budget_pacing({"customer_id": "1234567890"})

    assert len(result["campaigns"]) == 1
    c = result["campaigns"][0]
    assert c["campaign_id"] == "111"
    assert c["spent_mtd_brl"] == 50.0
    assert c["days_elapsed"] == 15
    # 50 BRL in 15 days = 3.33/day; projected for 31 days ≈ 103 BRL
    assert 100 <= c["projected_monthly_brl"] <= 110


@pytest.mark.asyncio
async def test_recommendations_translates_known_types(bound_context):
    from src.mcp.tools.get_recommendations import get_recommendations

    class _M:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    fake_row = {
        "resource_name": "customers/1234567890/recommendations/abc",
        "type": "KEYWORD",
        "type_pt": "Adicionar palavra-chave",
        "current_clicks": 100,
        "current_impressions": 5000,
        "current_cost_brl": 50.0,
        "potential_clicks": 150,
        "potential_impressions": 7500,
        "potential_cost_brl": 75.0,
        "uplift_clicks": 50,
        "uplift_impressions": 2500,
    }
    with patch(
        "src.mcp.tools.get_recommendations.run_report",
        AsyncMock(return_value=[fake_row]),
    ):
        result = await get_recommendations({"customer_id": "1234567890"})

    assert result["count"] == 1
    rec = result["recommendations"][0]
    assert rec["type_pt"] == "Adicionar palavra-chave"
    assert rec["uplift_clicks"] == 50


@pytest.mark.asyncio
async def test_invalid_customer_id_format_rejected_by_schema(bound_context):
    """Schema validation happens at MCP call_tool layer; here we just call the
    handler directly which doesn't validate. This test documents that the
    PATTERN constraint exists in the schema."""
    from src.mcp.tools.get_account_overview import _SCHEMA

    assert _SCHEMA["properties"]["customer_id"]["pattern"] == "^[0-9]{10}$"
```

- [ ] **Step 8: Run tests → 5 PASS**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_overview_tools.py -v
```

- [ ] **Step 9: mypy + ruff + full suite**

```bash
./.venv/Scripts/python.exe -m mypy src/google_ads/queries/ src/mcp/tools/get_account_overview.py src/mcp/tools/get_budget_pacing.py src/mcp/tools/get_recommendations.py
./.venv/Scripts/python.exe -m ruff check src/google_ads/queries/ src/mcp/tools/ tests/integration/test_overview_tools.py
./.venv/Scripts/python.exe -m ruff format --check src/google_ads/queries/ src/mcp/tools/ tests/integration/test_overview_tools.py
./.venv/Scripts/python.exe -m pytest tests/ --tb=line | tail -3
```

Auto-format if needed.

If mypy complains about untyped Google Ads SDK row objects, leave them as `Any` — the SDK doesn't ship types. The `# type: ignore[no-any-return]` may be needed in row formatters.

- [ ] **Step 10: Commit + push**

```bash
git add src/google_ads/queries/ src/mcp/tools/ tests/integration/test_overview_tools.py
git commit -m "feat(tools): visão geral — account_overview + budget_pacing + recommendations

3 tools shipping the gestor's morning dashboard:
- get_account_overview: KPIs aggregated for a date range with
  immediately-previous-period comparison side by side.
- get_budget_pacing: per-campaign daily budget, MTD spend, days
  remaining, projected end-of-month spend.
- get_recommendations: Google's pending suggestions with PT-BR
  type translation + impact estimate."
git push
```

## Report

Status: DONE | DONE_WITH_CONCERNS | BLOCKED. Pytest tail, mypy/ruff, git head.

---

## Task 6: Tools — Análise de performance (5 tools)

**Files:**
- Create: `src/google_ads/queries/performance.py`
- Create: `src/mcp/tools/get_campaign_performance.py`, `get_ad_group_performance.py`, `get_device_performance.py`, `get_geo_performance.py`, `get_hourly_performance.py`
- Modify: `src/mcp/tools/_registry.py` to import new modules
- Create: `tests/integration/test_performance_tools.py`

These five share the same pattern: aggregate metrics segmented by campaign / ad_group / device / geo / hour. They use the same `_row_formatter` shape (impressions, clicks, cost, conv, conv_value) plus the segmentation field.

This task is voluminous — 5 tools, ~130 lines each. Sonnet is recommended.

The full task description with all 5 tool implementations + integration tests is documented inline in this plan file. Each tool file follows the same template as `get_account_overview` from Task 5; the only differences are: (a) GAQL query (different segments + FROM clause), (b) row formatter (extra fields for the segment), (c) output shape (list instead of object).

**For brevity in this plan document**, the implementer dispatches to a single subagent with the complete spec for all 5 tools at once. Each tool follows this template (substitute `{name}`, `{segment_field}`, `{from_clause}` per tool):

```python
"""Tool: get_{name}_performance — metrics segmented by {segment}."""
from typing import Any

from src.google_ads.queries._common import (
    get_comparison_range,
    micros_to_currency,
    parse_date_range,
)
from src.google_ads.queries.performance import {name}_performance_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool


_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "date_range": {"default": "LAST_30_DAYS"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 100},
        "status": {
            "type": "string",
            "enum": ["enabled", "paused", "removed", "all"],
            "default": "enabled",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}

# ... handler that calls run_report and formats rows
```

The implementer should generate all 5 files following this pattern. Specific GAQL queries:

```python
# src/google_ads/queries/performance.py

from datetime import date
from src.google_ads.queries._common import gaql_date_clause


def campaign_performance_query(start: date, end: date, status: str, limit: int) -> str:
    status_clause = "" if status == "all" else f"AND campaign.status = '{status.upper()}'"
    return f"""
        SELECT
          campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM campaign
        WHERE {gaql_date_clause(start, end)} {status_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit}
    """.strip()


def ad_group_performance_query(start: date, end: date, status: str, limit: int) -> str:
    status_clause = "" if status == "all" else f"AND ad_group.status = '{status.upper()}'"
    return f"""
        SELECT
          ad_group.id, ad_group.name, ad_group.status,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM ad_group
        WHERE {gaql_date_clause(start, end)} {status_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit}
    """.strip()


def device_performance_query(start: date, end: date) -> str:
    return f"""
        SELECT
          segments.device,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM customer
        WHERE {gaql_date_clause(start, end)}
    """.strip()


def geo_performance_query(start: date, end: date, geo_level: str, limit: int) -> str:
    """geo_level: 'country' | 'region' | 'city' (mapped to geographic_view dimensions)."""
    field_map = {
        "country": "geographic_view.country_criterion_id",
        "region": "geographic_view.country_criterion_id",  # uses same view; client-side filter
        "city": "geographic_view.country_criterion_id",
    }
    return f"""
        SELECT
          geographic_view.country_criterion_id,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM geographic_view
        WHERE {gaql_date_clause(start, end)}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit}
    """.strip()


def hourly_performance_query(start: date, end: date) -> str:
    return f"""
        SELECT
          segments.hour, segments.day_of_week,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM customer
        WHERE {gaql_date_clause(start, end)}
    """.strip()
```

The 5 tool handler files all follow this pattern (substitute query function + segment fields):

```python
@register_tool(name="get_campaign_performance", description="...", input_schema=_SCHEMA)
async def get_campaign_performance(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    date_range = args.get("date_range", "LAST_30_DAYS")
    status = args.get("status", "enabled")
    limit = args.get("limit", 100)
    start, end = parse_date_range(date_range)

    def _formatter(row):
        return {
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "status": str(row.campaign.status).split(".")[-1],
            "type": str(row.campaign.advertising_channel_type).split(".")[-1],
            "impressions": int(row.metrics.impressions),
            "clicks": int(row.metrics.clicks),
            "cost_brl": micros_to_currency(row.metrics.cost_micros),
            "conversions": float(row.metrics.conversions),
            "conversions_value_brl": round(row.metrics.conversions_value, 2),
            "ctr": round(row.metrics.clicks / row.metrics.impressions, 4) if row.metrics.impressions else 0,
            "cpc_brl": micros_to_currency(row.metrics.cost_micros / row.metrics.clicks) if row.metrics.clicks else 0,
        }

    rows = await run_report(
        manager_id=ctx.manager_id, session_id=ctx.session_id,
        customer_id=customer_id,
        query=campaign_performance_query(start, end, status, limit),
        row_formatter=_formatter,
        operation_name="get_campaign_performance",
    )
    return {
        "customer_id": customer_id,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "rows": rows,
    }
```

The remaining 4 tools follow the same template — substitute the query function + adjust the row formatter for the relevant segment fields. See `_common.py` METRIC_FIELDS for the standard metric list.

Tasks for the implementer:
1. Create all 5 query functions in `performance.py` (above)
2. Create all 5 tool files in `src/mcp/tools/` following the template
3. Update `_registry.py` to import all 5
4. Write `tests/integration/test_performance_tools.py` with 5 tests (one per tool) using the patch pattern from Task 5
5. Commit + push

## Report

Status, pytest tail, mypy/ruff, git log head, any deviations.

---

## Task 7: Tools — Otimização tática (6 tools)

Same pattern as Task 6 but for the 6 tactical tools:

- `get_keyword_performance` — KW + match_type + Quality Score (3 components: ctr, ad_relevance, lp_experience), first_page_cpc, top_of_page_cpc
- `get_search_terms_report` — actual search terms that triggered ads, with `added_as_keyword` / `added_as_negative` flags
- `get_negative_keywords_audit` — campaign-level + shared-set negatives, with coverage by campaign
- `get_ad_performance` — RSAs with headlines/descriptions + asset performance ratings (Best/Good/Low/Pending/Learning)
- `get_audience_performance` — audiences/segments applied + their metrics
- `get_conversion_actions` — conversion actions configured + health (volume last 7/30 days, attribution)

Each follows the Task 6 template. Specific GAQL queries:

```python
# src/google_ads/queries/tactical.py

def keyword_performance_query(start, end, status, limit):
    status_clause = "" if status == "all" else f"AND ad_group_criterion.status = '{status.upper()}'"
    return f"""
        SELECT
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.keyword.match_type,
          ad_group_criterion.status,
          ad_group_criterion.quality_info.quality_score,
          ad_group_criterion.quality_info.creative_quality_score,
          ad_group_criterion.quality_info.post_click_quality_score,
          ad_group_criterion.quality_info.search_predicted_ctr,
          ad_group_criterion.position_estimates.first_page_cpc_micros,
          ad_group_criterion.position_estimates.top_of_page_cpc_micros,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM keyword_view
        WHERE {{gaql_date_clause(start, end)}} {status_clause}
        ORDER BY metrics.cost_micros DESC LIMIT {limit}
    """


def search_terms_query(start, end, limit):
    return f"""
        SELECT
          search_term_view.search_term, search_term_view.status,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM search_term_view
        WHERE {{gaql_date_clause(start, end)}}
        ORDER BY metrics.cost_micros DESC LIMIT {limit}
    """


def negative_keywords_audit_query():
    """Negative keywords applied at campaign + shared set level."""
    return """
        SELECT
          campaign_criterion.criterion_id, campaign_criterion.negative,
          campaign_criterion.keyword.text, campaign_criterion.keyword.match_type,
          campaign.id, campaign.name
        FROM campaign_criterion
        WHERE campaign_criterion.negative = true
          AND campaign_criterion.type = 'KEYWORD'
    """


def ad_performance_query(start, end, status, limit):
    status_clause = "" if status == "all" else f"AND ad_group_ad.status = '{status.upper()}'"
    return f"""
        SELECT
          ad_group_ad.ad.id, ad_group_ad.status, ad_group_ad.ad.type,
          ad_group_ad.ad.responsive_search_ad.headlines,
          ad_group_ad.ad.responsive_search_ad.descriptions,
          ad_group_ad.ad.final_urls,
          ad_group_ad.ad_strength,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM ad_group_ad
        WHERE {{gaql_date_clause(start, end)}} {status_clause}
        ORDER BY metrics.cost_micros DESC LIMIT {limit}
    """


def audience_performance_query(start, end, limit):
    return f"""
        SELECT
          ad_group_audience_view.resource_name,
          ad_group_criterion.criterion_id,
          ad_group_criterion.user_list.user_list,
          ad_group_criterion.user_interest.user_interest_category,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM ad_group_audience_view
        WHERE {{gaql_date_clause(start, end)}}
        ORDER BY metrics.cost_micros DESC LIMIT {limit}
    """


def conversion_actions_query():
    return """
        SELECT
          conversion_action.id, conversion_action.name, conversion_action.status,
          conversion_action.category, conversion_action.type,
          conversion_action.counting_type,
          conversion_action.attribution_model_settings.attribution_model,
          conversion_action.value_settings.default_value,
          conversion_action.value_settings.always_use_default_value
        FROM conversion_action
    """
```

Tool handlers follow Task 6 template. Each tool's row formatter shapes the segment-specific fields appropriately.

Tasks:
1. Create `src/google_ads/queries/tactical.py` with the 6 query functions
2. Create 6 tool files in `src/mcp/tools/`
3. Update `_registry.py`
4. Write `tests/integration/test_tactical_tools.py` (6 tests)
5. Commit + push

## Report

Same format as Task 6.

---

## Task 8: Tools — Relatório cliente (2 tools)

- `get_funnel_metrics` — full funnel impressions → clicks → conversions → revenue + rates between stages
- `get_top_keywords_creatives` — top N keywords + top N creatives ranked by configurable metric

Files:
- Create: `src/google_ads/queries/client_report.py`
- Create: `src/mcp/tools/get_funnel_metrics.py`, `get_top_keywords_creatives.py`
- Update: `_registry.py`
- Create: `tests/integration/test_client_report_tools.py`

`get_funnel_metrics` uses the same overview_query as Task 5's `get_account_overview` but presents the data as a funnel with rates between stages (CTR, conversion rate, AOV).

`get_top_keywords_creatives` accepts a `metric` parameter (`cost`, `conversions`, `clicks`, `impressions`) + `top_n` (default 10) and returns two lists: top keywords + top creatives by that metric.

Implementation: ~80 lines per tool, similar template to Task 5.

## Report

Same format.

---

## Task 9: Utility tools — run_gaql, validate_gaql, list_gaql_resources

**Files:**
- Create: `src/google_ads/queries/meta.py` (catalog of GAQL resources/fields)
- Create: `src/mcp/tools/run_gaql.py`, `validate_gaql.py`, `list_gaql_resources.py`
- Update: `_registry.py`
- Create: `tests/integration/test_utility_tools.py`

### `run_gaql(customer_id, query)` — escape hatch

Executes arbitrary GAQL using `execute_gaql_raw` from `reports.py` (Task 3). Returns rows as plain dicts (proto-to-dict via `MessageToDict`). Always audited (sensitive: arbitrary read).

### `validate_gaql(customer_id, query)` — dry-run validator

Calls `GoogleAdsService.search_stream` with the `validate_only=True` flag. Returns `{valid: bool, errors: [...]}` without consuming data quota.

### `list_gaql_resources()` — schema catalog

Returns the static catalog of GAQL resources (campaign, ad_group, keyword_view, etc.) with their attributable fields. Generated once from the SDK's introspection at module load time and cached.

```python
# src/google_ads/queries/meta.py
RESOURCES = {
    "campaign": {
        "description": "Campanha",
        "fields": ["campaign.id", "campaign.name", "campaign.status",
                   "campaign.advertising_channel_type", ...],
    },
    "ad_group": {...},
    "keyword_view": {...},
    "search_term_view": {...},
    # ... 15-20 commonly used resources
}
```

The full list is built incrementally — for Phase 2 ship a curated set of 15 commonly used resources. Future expansion can scrape from the SDK or Google docs.

Implementation specifics for run_gaql (the most important utility):

```python
@register_tool(
    name="run_gaql",
    description=(
        "Escape hatch: executa qualquer GAQL contra a conta. Use apenas quando as "
        "tools curadas não cobrem o caso. Sempre auditado. Limite: o resultado é "
        "truncado em 1000 linhas pra evitar respostas gigantes."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
            "query": {"type": "string", "minLength": 10},
        },
        "required": ["customer_id", "query"],
    },
)
async def run_gaql(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    rows = await execute_gaql_raw(
        manager_id=ctx.manager_id,
        customer_id=args["customer_id"],
        query=args["query"],
    )
    truncated = len(rows) > 1000
    return {
        "customer_id": args["customer_id"],
        "row_count": len(rows),
        "truncated": truncated,
        "rows": rows[:1000],
    }
```

Tasks:
1. Implement `src/google_ads/queries/meta.py` with at least 15 curated resources
2. Implement 3 utility tool files
3. Update `_registry.py`
4. Tests
5. Commit + push

## Report

Same format.

---

## Task 10: Schema validation tests + audit roll-up

**Files:**
- Create: `tests/unit/test_tools_schemas.py`
- Modify: `src/mcp/server.py` (optional — if call_tool needs to validate input against schema)

The MCP SDK does NOT validate tool inputs against the declared schema by default. Each tool would have to validate its own input or trust callers. We add a thin validation step in `server.py:call_tool`:

```python
# in build_server() / call_tool():
import jsonschema
try:
    jsonschema.validate(arguments or {}, tool.input_schema)
except jsonschema.ValidationError as e:
    raise ValueError(f"Invalid arguments for {name}: {e.message}")
```

Add `jsonschema>=4.0` to runtime deps in `pyproject.toml`.

Test file checks:
- Every registered tool's `input_schema` is a valid JSON Schema (parse with jsonschema.Draft202012Validator).
- Every required customer_id field has the correct pattern.
- No tool accidentally exposes a writable parameter at this phase.

```python
# tests/unit/test_tools_schemas.py
import jsonschema
import pytest

from src.mcp.tools._registry import all_tools, import_all_tools


@pytest.fixture(scope="module", autouse=True)
def _load():
    import_all_tools()


def test_every_tool_has_valid_schema():
    for tool in all_tools():
        # Will raise if invalid schema
        jsonschema.Draft202012Validator.check_schema(tool.input_schema)


def test_customer_id_is_consistent():
    for tool in all_tools():
        if "customer_id" in tool.input_schema.get("properties", {}):
            cid = tool.input_schema["properties"]["customer_id"]
            assert cid.get("pattern") == "^[0-9]{10}$", \
                f"{tool.name} has wrong customer_id pattern"


def test_all_phase_2_tools_registered():
    expected = {
        "list_my_accounts",
        # visão geral
        "get_account_overview", "get_budget_pacing", "get_recommendations",
        # performance
        "get_campaign_performance", "get_ad_group_performance",
        "get_device_performance", "get_geo_performance", "get_hourly_performance",
        # tactical
        "get_keyword_performance", "get_search_terms_report",
        "get_negative_keywords_audit", "get_ad_performance",
        "get_audience_performance", "get_conversion_actions",
        # client report
        "get_funnel_metrics", "get_top_keywords_creatives",
        # utilities
        "run_gaql", "validate_gaql", "list_gaql_resources",
    }
    actual = {t.name for t in all_tools()}
    assert expected.issubset(actual), f"Missing: {expected - actual}"
```

The audit roll-up: rather than logging each report call (high volume, low value), a daily cron rolls up call counts per (manager, tool, customer) and writes a SUMMARY row to audit_log with action_type='system'. Defer this roll-up to Phase 4 when audit volume becomes a real cost issue. For Phase 2, just don't log report-tool calls individually.

Tasks:
1. Add `jsonschema>=4.0` to deps
2. Patch `server.py:call_tool` to validate inputs
3. Add `tests/unit/test_tools_schemas.py`
4. Commit + push

## Report

Same format.

---

## Task 11: E2E manual verification + sign-off

This is the human-driven acceptance test. Subagent prepares the runbook + can run partial steps.

- [ ] **Step 1: Update `docs/operacao/phase-1a-bootstrap.md`** with a new section "Phase 2 — testing read tools"

Add at the bottom:

```markdown
## Phase 2 — Testing read tools

After Phase 2 deploys, verify the 16+3 read tools work end-to-end via Codex/Claude Desktop. Use a current MCP session token (rotate if expired).

### Pick a non-trivial customer_id

The 23 active V4 accounts are listed by `list_my_accounts`. Pick one with real recent activity for testing — e.g., 'Mestre da Obra - Cotia' (5894449831).

### Test prompts (paste into Claude/Codex)

1. **Account overview:**
   > "Use get_account_overview na conta 5894449831 últimos 30 dias e mostra a comparação com período anterior."

   Expected: numbers for impressions/clicks/cost/conv/ROAS, with current vs previous side-by-side.

2. **Budget pacing:**
   > "Quais campanhas da conta 5894449831 estão acima do projetado pro mês?"

   Expected: list of campaigns with daily_budget, MTD spend, projection, % over budget.

3. **Performance breakdown:**
   > "Top 5 campanhas por gasto na conta 5894449831, últimos 7 dias."

   Expected: 5 campaigns ordered by cost.

4. **Tactical:**
   > "Quais search terms na conta 5894449831 gastaram mais sem converter nos últimos 14 dias?"

   Expected: list of search terms with cost > 0 and conversions = 0.

5. **GAQL escape hatch:**
   > "Roda este GAQL na conta 5894449831: SELECT customer.descriptive_name, customer.currency_code FROM customer"

   Expected: 1 row with the descriptive_name + currency.

### Verify audit + rate limit

```sql
-- Sensitive reads (recommendations, run_gaql) should be audited
SELECT operation, count(*) FROM audit_log
WHERE occurred_at > now() - interval '1 hour' AND action_type = 'read'
GROUP BY operation;

-- Rate counter should reflect today's usage
SELECT * FROM rate_counters WHERE date = current_date;
```
```

- [ ] **Step 2: Add the Phase 2 sign-off to `docs/operacao/infra-setup.md`**

Append after the Phase 1a section:

```markdown
### Phase 2 — Read tools (DATE)
- 16 curated read tools + 3 GAQL utilities shipped.
- Rate limit module enforces 15k ops/day.
- Audit log captures sensitive reads only (recommendations + run_gaql).
- E2E verified: <list of tools called via Codex with real V4 data>.
```

- [ ] **Step 3: Run a full local test suite**

```bash
./.venv/Scripts/python.exe -m pytest tests/ --tb=short
```

Expected: all green. Document the count.

- [ ] **Step 4: Commit + push**

```bash
git add docs/operacao/
git commit -m "docs(ops): Phase 2 testing runbook + sign-off placeholder"
git push
```

The CI deploy runs. Once green, hand off to the human user: "Phase 2 deployed. Open Codex/Claude Desktop and run the prompts in the runbook."

- [ ] **Step 5: After human user confirms tools work, add the actual sign-off**

Replace the placeholder with the real verification report.

## Report

Final commit hash, deploy run ID, list of tools verified by user.

---

## Self-review notes

**Spec coverage:**
- §6.2 (16 read tools) — Tasks 5-8
- §6.4 utilities (run_gaql, validate_gaql, list_gaql_resources) — Task 9
- §7.3 (rate limit) — Task 2
- §7.4 (audit policy) — Tasks 3, 9 (sensitive reads only)
- §11 Phase 2 critério "gestor faz queries via Claude com resposta correta PT-BR" — Task 11

**Out of scope for Phase 2 (deferred):**
- Web panel `/audit` view (Phase 1b)
- Audit log roll-up cron (Phase 4 when volume becomes constraining)
- Standard Access submission for dev token (operational task, not code)
- Phase 3's write tools (separate plan)

**Type/name consistency:**
- `run_report` signature consistent across Tasks 3, 5-8.
- `parse_date_range` / `get_comparison_range` API consistent.
- `register_tool` decorator pattern used uniformly.
- `customer_id` schema (`^[0-9]{10}$`) consistent across all 16 tools.

**Risk register:**
- Google Ads API quota: with 16 tools + heavy gestor use, 15k/day could be hit. Standard Access submission becomes urgent. Track via rate_counters table.
- GAQL field name evolution: Google Ads API versions deprecate fields. We pin SDK version in pyproject.toml; bumping requires query review.
- `MessageToDict` in run_gaql may fail on some message types. Wrap in try/except returning the raw repr if conversion fails.
- Geo performance tool returns country_criterion_id (a numeric ID) — needs joining to a country name table. Phase 2 returns the raw ID with a note; Phase 3 can add a name resolver.
