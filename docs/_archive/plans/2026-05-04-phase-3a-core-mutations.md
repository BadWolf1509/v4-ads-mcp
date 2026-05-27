# V4 Ads MCP — Phase 3a: Core Write Tools + Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Ship the governance machinery (blast_radius + dry_run + apply_change) plus the 10 most-used mutation tools (status changes, budget, lance, negatives, recommendations) with full audit + safety guardrails. Phase 3b will add the remaining 15 advanced mutations on top of this foundation.

**Architecture:** Each write tool returns a "preview" with `confirmation_token` (dry-run) by default; the user confirms via the `apply_change` utility tool, which consumes the token and executes the mutation. Operations classified as low-risk (e.g., add_negative_keywords) auto-apply without dry-run. Every mutation is audited regardless.

**Tech Stack:** Reuses Phase 2 stack — google-ads SDK + asyncpg + jsonschema. No new deps.

**Reference spec:** `docs/superpowers/specs/2026-05-03-v4-ads-mcp-design.md` §6.3 (write tools), §7.1 (blast radius rules), §7.2 (dry-run flow), §7.4 (audit policy).

**Definition of done (Phase 3a):**

1. `governance/blast_radius.py` classifies each operation as auto|confirm|always_confirm based on parameters.
2. `governance/dry_run.py` generates a preview + 8-char alphanumeric confirmation token, persists payload in `pending_confirmations` with 10-min TTL.
3. `apply_change(token)` MCP tool consumes the token, executes the saved mutation, audits success/failure.
4. 10 core mutation tools registered:
   - **Campaigns:** `update_campaign_status`, `update_campaign_budget`, `update_campaign_bidding`
   - **Ad groups:** `update_ad_group_status`, `update_ad_group_bid`
   - **Keywords:** `update_keyword_status`, `update_keyword_bid`
   - **Negatives:** `add_negative_keywords` (auto-applies)
   - **Recommendations:** `apply_recommendation`, `dismiss_recommendation`
5. wellinton.ribeiro@v4company.com tests at least 3 mutation flows via Codex on a real V4 account, confirms changes appear in Google Ads UI Change History under their name.
6. Audit log captures every mutation with manager_id, customer_id, operation, target_count, status, google_request_id.
7. All 114+ existing tests still pass; new tests cover ~25 unit tests (blast radius rules, payload serialization) + 5 integration tests (dry-run → apply cycle).

---

## File structure

```
src/
├── governance/
│   ├── blast_radius.py                # NEW
│   ├── dry_run.py                     # NEW
│   └── audit.py                       # not new; we already have repos/audit_log.py
├── google_ads/
│   ├── mutates/                       # NEW PACKAGE
│   │   ├── __init__.py
│   │   ├── _common.py                 # shared mutate helpers
│   │   ├── campaigns.py               # campaign mutate ops
│   │   ├── ad_groups.py
│   │   ├── keywords.py
│   │   ├── negatives.py
│   │   └── recommendations.py
│   └── mutations.py                   # NEW — run_mutation executor (analogous to run_report)
└── mcp/
    └── tools/
        ├── apply_change.py            # NEW — the confirmation tool
        ├── # campaigns
        ├── update_campaign_status.py
        ├── update_campaign_budget.py
        ├── update_campaign_bidding.py
        ├── # ad_groups
        ├── update_ad_group_status.py
        ├── update_ad_group_bid.py
        ├── # keywords
        ├── update_keyword_status.py
        ├── update_keyword_bid.py
        ├── # negatives
        ├── add_negative_keywords.py
        └── # recommendations
        ├── apply_recommendation.py
        └── dismiss_recommendation.py

tests/
├── unit/
│   ├── test_blast_radius.py           # parameterized rules
│   └── test_dry_run.py                # token gen + TTL + consume
└── integration/
    ├── test_dry_run_apply_cycle.py    # end-to-end with mocked SDK
    └── test_mutation_tools.py         # one test per tool group (4 tests covering 10 tools)
```

---

## Task 1: Blast radius classifier (TDD)

**Goal:** Pure-logic module that takes `(operation_name, params)` and returns a `RiskClassification(level: 'auto'|'confirm', reason: str)`.

**Files:**
- Create: `src/governance/blast_radius.py`
- Create: `tests/unit/test_blast_radius.py`

### The rules (from spec §7.1)

| Operation | Auto if… | Confirm if… |
|---|---|---|
| `update_campaign_status` (single) | Always | Never |
| `update_campaign_status` (bulk) | ≤ 5 entities | > 5 entities |
| `update_campaign_budget` | Never | Always |
| `update_campaign_bidding` | Never | Always |
| `update_ad_group_status` (single) | Always | Never |
| `update_ad_group_status` (bulk) | ≤ 5 entities | > 5 entities |
| `update_ad_group_bid` (single) | Variation ≤ 20% | Variation > 20% |
| `update_ad_group_bid` (bulk) | ≤ 5 entities AND var ≤ 20% | > 5 OR var > 20% |
| `update_keyword_status` (single) | Always | Never |
| `update_keyword_status` (bulk) | ≤ 5 entities | > 5 entities |
| `update_keyword_bid` (single) | Variation ≤ 20% | Variation > 20% |
| `update_keyword_bid` (bulk) | ≤ 5 entities AND var ≤ 20% | > 5 OR var > 20% |
| `add_negative_keywords` | Always | Never (negatives are safe) |
| `apply_recommendation` | Always | Never |
| `dismiss_recommendation` | Always | Never |

### Step 1: Write failing test `tests/unit/test_blast_radius.py`

EXACT content:

```python
"""Parameterized tests covering all blast_radius rules from spec §7.1."""
import pytest

from src.governance.blast_radius import RiskLevel, classify


# (operation, params, expected_level, hint_substring_in_reason)
_CASES: list[tuple[str, dict, RiskLevel, str]] = [
    # Status changes — single
    ("update_campaign_status", {"target_count": 1}, RiskLevel.AUTO, "single"),
    ("update_ad_group_status", {"target_count": 1}, RiskLevel.AUTO, "single"),
    ("update_keyword_status", {"target_count": 1}, RiskLevel.AUTO, "single"),
    # Status changes — bulk small
    ("update_campaign_status", {"target_count": 3}, RiskLevel.AUTO, "bulk"),
    ("update_keyword_status", {"target_count": 5}, RiskLevel.AUTO, "bulk"),
    # Status changes — bulk large
    ("update_campaign_status", {"target_count": 6}, RiskLevel.CONFIRM, "more than 5"),
    ("update_ad_group_status", {"target_count": 50}, RiskLevel.CONFIRM, "more than 5"),
    # Budget always confirms
    ("update_campaign_budget", {"target_count": 1, "delta_pct": 5.0}, RiskLevel.CONFIRM, "budget"),
    ("update_campaign_budget", {"target_count": 1, "delta_pct": 0.1}, RiskLevel.CONFIRM, "budget"),
    # Bidding strategy always confirms
    ("update_campaign_bidding", {"target_count": 1}, RiskLevel.CONFIRM, "bidding"),
    # Bid changes — small variation
    ("update_keyword_bid", {"target_count": 1, "max_delta_pct": 10.0}, RiskLevel.AUTO, "small"),
    ("update_ad_group_bid", {"target_count": 5, "max_delta_pct": 19.5}, RiskLevel.AUTO, "small"),
    # Bid changes — large variation
    ("update_keyword_bid", {"target_count": 1, "max_delta_pct": 25.0}, RiskLevel.CONFIRM, "20%"),
    ("update_ad_group_bid", {"target_count": 1, "max_delta_pct": 21.0}, RiskLevel.CONFIRM, "20%"),
    # Bid changes — bulk
    ("update_keyword_bid", {"target_count": 6, "max_delta_pct": 5.0}, RiskLevel.CONFIRM, "more than 5"),
    # Negatives always auto
    ("add_negative_keywords", {"target_count": 100}, RiskLevel.AUTO, "negatives"),
    # Recommendations always auto
    ("apply_recommendation", {"target_count": 1}, RiskLevel.AUTO, "recommendation"),
    ("dismiss_recommendation", {"target_count": 1}, RiskLevel.AUTO, "recommendation"),
]


@pytest.mark.parametrize("operation,params,expected_level,hint", _CASES)
def test_classify_returns_expected(operation, params, expected_level, hint):
    result = classify(operation=operation, params=params)
    assert result.level == expected_level, (
        f"{operation} with {params}: got {result.level}, expected {expected_level}"
    )
    assert hint.lower() in result.reason.lower(), (
        f"{operation}: reason '{result.reason}' missing hint '{hint}'"
    )


def test_unknown_operation_defaults_to_confirm():
    """Defensive: never auto-apply an unknown operation."""
    result = classify(operation="future_dangerous_tool", params={"target_count": 1})
    assert result.level == RiskLevel.CONFIRM
    assert "unknown" in result.reason.lower() or "default" in result.reason.lower()


def test_target_count_zero_is_confirm():
    """Edge case: target_count=0 means we don't know — be safe."""
    result = classify(operation="update_campaign_status", params={"target_count": 0})
    assert result.level == RiskLevel.CONFIRM


def test_missing_target_count_is_confirm():
    """Edge case: caller forgot to pass target_count."""
    result = classify(operation="update_keyword_bid", params={})
    assert result.level == RiskLevel.CONFIRM
```

### Step 2: Run test → fail with import error

```bash
cd "/d/HUB ads MCP"
./.venv/Scripts/python.exe -m pytest tests/unit/test_blast_radius.py -v
```

### Step 3: Implement `src/governance/blast_radius.py`

EXACT content:

```python
"""Blast radius classifier — decides auto-apply vs require-confirmation per operation.

Defaults are conservative. Unknown operations always require confirmation.
Each rule cites the spec section it implements.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    AUTO = "auto"
    CONFIRM = "confirm"


@dataclass(slots=True, frozen=True)
class RiskClassification:
    level: RiskLevel
    reason: str  # Human-readable PT-BR explanation


# Threshold constants from spec §7.1
_BULK_THRESHOLD = 5
_BID_DELTA_PCT_THRESHOLD = 20.0


def _bulk_status_classify(operation: str, target_count: int) -> RiskClassification:
    if target_count <= 0:
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"{operation}: target_count={target_count} desconhecido — confirmar por seguranca",
        )
    if target_count == 1:
        return RiskClassification(
            RiskLevel.AUTO,
            f"{operation}: single entity — auto",
        )
    if target_count <= _BULK_THRESHOLD:
        return RiskClassification(
            RiskLevel.AUTO,
            f"{operation}: bulk pequeno ({target_count} entities <= {_BULK_THRESHOLD}) — auto",
        )
    return RiskClassification(
        RiskLevel.CONFIRM,
        f"{operation}: more than {_BULK_THRESHOLD} entities ({target_count}) — confirmar",
    )


def _bid_classify(operation: str, target_count: int, max_delta_pct: float) -> RiskClassification:
    if target_count <= 0:
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"{operation}: target_count={target_count} desconhecido — confirmar",
        )
    if max_delta_pct > _BID_DELTA_PCT_THRESHOLD:
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"{operation}: variacao maxima {max_delta_pct:.1f}% > 20% — confirmar",
        )
    if target_count > _BULK_THRESHOLD:
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"{operation}: more than {_BULK_THRESHOLD} entities ({target_count}) — confirmar",
        )
    return RiskClassification(
        RiskLevel.AUTO,
        f"{operation}: small variation ({max_delta_pct:.1f}%) AND {target_count} entities — auto",
    )


def classify(*, operation: str, params: dict[str, Any]) -> RiskClassification:
    """Classify a mutation operation as auto-apply or requires-confirmation.

    `params` is a dict like {target_count: int, delta_pct?: float, max_delta_pct?: float}.
    """
    target_count = int(params.get("target_count", 0))

    # Status changes (campaign/ad_group/keyword) — bulk-aware
    if operation in (
        "update_campaign_status",
        "update_ad_group_status",
        "update_keyword_status",
    ):
        return _bulk_status_classify(operation, target_count)

    # Budget mutations — always confirm (spec §7.1)
    if operation == "update_campaign_budget":
        return RiskClassification(
            RiskLevel.CONFIRM,
            "Mudanca de orcamento de campanha — confirmar sempre",
        )

    # Bidding strategy mutations — always confirm
    if operation == "update_campaign_bidding":
        return RiskClassification(
            RiskLevel.CONFIRM,
            "Mudanca de estrategia de bidding — confirmar sempre",
        )

    # Bid mutations (ad_group_bid, keyword_bid) — variation+count aware
    if operation in ("update_ad_group_bid", "update_keyword_bid"):
        max_delta_pct = float(params.get("max_delta_pct", 100.0))  # unknown = high
        return _bid_classify(operation, target_count, max_delta_pct)

    # Negatives — safe, always auto
    if operation == "add_negative_keywords":
        return RiskClassification(
            RiskLevel.AUTO,
            f"add_negative_keywords ({target_count} negatives) — auto, negatives raramente quebram",
        )

    # Recommendations — Google's own suggestions; auto-apply
    if operation in ("apply_recommendation", "dismiss_recommendation"):
        return RiskClassification(
            RiskLevel.AUTO,
            f"{operation} — auto, recommendation flow do Google",
        )

    # Unknown operation — default safe to confirm
    return RiskClassification(
        RiskLevel.CONFIRM,
        f"{operation}: unknown operation — default seguro: confirmar",
    )
```

### Step 4: Run tests → all pass

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_blast_radius.py -v
```

Expected: ~22 tests pass.

### Step 5: mypy + ruff + full suite + commit

```bash
./.venv/Scripts/python.exe -m mypy src/governance/blast_radius.py
./.venv/Scripts/python.exe -m ruff check src/governance/ tests/unit/test_blast_radius.py
./.venv/Scripts/python.exe -m ruff format --check src/governance/ tests/unit/test_blast_radius.py
./.venv/Scripts/python.exe -m pytest tests/ --tb=line | tail -3

git add src/governance/blast_radius.py tests/unit/test_blast_radius.py
git commit -m "feat(governance): blast radius classifier (auto vs confirm)

Pure-logic classifier for mutation operations. Defaults conservatively
to CONFIRM for unknown operations. Implements spec §7.1 rules:
- status changes: single+bulk<=5 auto, >5 confirm
- budget/bidding: always confirm
- bid changes: <=20% variation AND <=5 entities auto
- negatives + recommendations: always auto"
git push
```

## Report

Status, pytest tail, mypy/ruff, git head.

---

## Task 2: Dry-run + pending_confirmations module (TDD)

**Goal:** Generate confirmation tokens, persist mutation payloads, validate + consume on apply.

**Files:**
- Create: `src/governance/dry_run.py`
- Create: `tests/integration/test_dry_run.py` (uses testcontainers since it touches DB)

### Step 1: Write `tests/integration/test_dry_run.py`

EXACT content:

```python
"""dry_run module integration tests against testcontainers Postgres."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import managers, mcp_sessions
from src.governance.dry_run import (
    ConsumeResult,
    InvalidTokenError,
    consume,
    create_pending,
    generate_token,
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


@pytest.fixture
async def session_id(db):
    """Create a manager + session for the tests."""
    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="t@v4.com", full_name=None)
        from src.auth.sessions import generate_session_token, hash_session_token
        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token), label="t"
        )
        yield sess.id


@pytest.mark.integration
async def test_generate_token_format() -> None:
    """Tokens are 8 alphanumeric chars."""
    import re
    for _ in range(20):
        t = generate_token()
        assert re.match(r"^[A-Z0-9]{8}$", t), f"Got {t!r}"


@pytest.mark.integration
async def test_create_and_consume_roundtrip(db, session_id) -> None:
    pool = db
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=session_id,
            customer_id="1234567890",
            operation_type="update_campaign_budget",
            payload={"campaign_id": "111", "new_amount_micros": 100_000_000},
            blast_summary="Budget mudara de R$ 50 pra R$ 100",
        )
        assert len(token) == 8

    async with pool.acquire() as conn:
        result = await consume(conn, token=token, session_id=session_id)
        assert isinstance(result, ConsumeResult)
        assert result.customer_id == "1234567890"
        assert result.operation_type == "update_campaign_budget"
        assert result.payload["campaign_id"] == "111"

    # Second consume must fail (already consumed)
    async with pool.acquire() as conn:
        with pytest.raises(InvalidTokenError, match="already consumed"):
            await consume(conn, token=token, session_id=session_id)


@pytest.mark.integration
async def test_consume_rejects_unknown_token(db, session_id) -> None:
    pool = db
    async with pool.acquire() as conn:
        with pytest.raises(InvalidTokenError, match="not found"):
            await consume(conn, token="ABCD1234", session_id=session_id)


@pytest.mark.integration
async def test_consume_rejects_wrong_session(db, session_id) -> None:
    """Token from session A can't be applied by session B."""
    pool = db
    other_session = uuid4()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=session_id,
            customer_id="1234567890",
            operation_type="update_campaign_budget",
            payload={},
            blast_summary="...",
        )

    async with pool.acquire() as conn:
        with pytest.raises(InvalidTokenError, match="session"):
            await consume(conn, token=token, session_id=other_session)


@pytest.mark.integration
async def test_consume_rejects_expired_token(db, session_id) -> None:
    """Tokens older than 10 minutes can't be applied."""
    pool = db
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=session_id,
            customer_id="1234567890",
            operation_type="update_campaign_budget",
            payload={},
            blast_summary="...",
        )
        # Manually expire it
        await conn.execute(
            "UPDATE pending_confirmations SET expires_at = now() - interval '1 minute' WHERE token = $1",
            token,
        )

    async with pool.acquire() as conn:
        with pytest.raises(InvalidTokenError, match="expired"):
            await consume(conn, token=token, session_id=session_id)
```

### Step 2: Run → fail

### Step 3: Implement `src/governance/dry_run.py`

EXACT content:

```python
"""Dry-run + pending confirmations: generate token, persist payload, consume.

Tokens are 8 alphanumeric chars (uppercase + digits) — short enough for
a human to type from chat if needed, long enough to be unguessable
(36^8 ~ 2.8 trillion). Always tied to (session_id, customer_id) and a
TTL of 10 minutes.

Concurrent consumes are race-safe via `SELECT ... FOR UPDATE` + immediate
update of consumed_at.
"""
import json
import secrets
import string
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg

DEFAULT_TTL_MINUTES = 10
_TOKEN_ALPHABET = string.ascii_uppercase + string.digits  # 36 chars
_TOKEN_LEN = 8


class InvalidTokenError(Exception):
    """Raised when a confirmation token is not found, expired, already consumed,
    or belongs to a different session."""


@dataclass(slots=True, frozen=True)
class ConsumeResult:
    customer_id: str
    operation_type: str
    payload: dict[str, Any]
    blast_summary: str


def generate_token() -> str:
    """8 random alphanumeric chars (uppercase + digits)."""
    return "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(_TOKEN_LEN))


async def create_pending(
    conn: asyncpg.Connection,
    *,
    session_id: UUID,
    customer_id: str,
    operation_type: str,
    payload: dict[str, Any],
    blast_summary: str,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
) -> str:
    """Persist a pending confirmation. Returns the token."""
    token = generate_token()
    # Loop on collision (extremely unlikely with 36^8 space + 10min TTL).
    for _ in range(5):
        try:
            await conn.execute(
                """
                INSERT INTO pending_confirmations
                  (token, session_id, customer_id, operation_type, payload, blast_summary, expires_at)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6, now() + ($7 || ' minutes')::interval)
                """,
                token,
                session_id,
                customer_id,
                operation_type,
                json.dumps(payload),
                blast_summary,
                str(ttl_minutes),
            )
            return token
        except asyncpg.UniqueViolationError:
            token = generate_token()
            continue
    raise RuntimeError("Could not generate unique confirmation token after 5 attempts")


async def consume(
    conn: asyncpg.Connection,
    *,
    token: str,
    session_id: UUID,
) -> ConsumeResult:
    """Atomically validate + mark a token as consumed. Returns the saved payload.

    Raises:
        InvalidTokenError: not found / expired / already consumed / wrong session
    """
    async with conn.transaction():
        row = await conn.fetchrow(
            """
            SELECT session_id, customer_id, operation_type, payload, blast_summary,
                   expires_at, consumed_at
            FROM pending_confirmations
            WHERE token = $1
            FOR UPDATE
            """,
            token,
        )
        if row is None:
            raise InvalidTokenError(f"Token '{token}' not found")
        if row["consumed_at"] is not None:
            raise InvalidTokenError(f"Token '{token}' already consumed")
        if row["session_id"] != session_id:
            raise InvalidTokenError(
                f"Token '{token}' belongs to a different session — refuse to apply"
            )
        from datetime import UTC, datetime
        if row["expires_at"] < datetime.now(UTC):
            raise InvalidTokenError(f"Token '{token}' expired")

        await conn.execute(
            "UPDATE pending_confirmations SET consumed_at = now() WHERE token = $1",
            token,
        )

    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return ConsumeResult(
        customer_id=row["customer_id"],
        operation_type=row["operation_type"],
        payload=payload,
        blast_summary=row["blast_summary"],
    )
```

### Step 4: Run tests → 5 PASS

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_dry_run.py -v -m integration
```

### Step 5: mypy + ruff + commit

```bash
./.venv/Scripts/python.exe -m mypy src/governance/dry_run.py
./.venv/Scripts/python.exe -m ruff check src/governance/ tests/integration/test_dry_run.py
./.venv/Scripts/python.exe -m ruff format --check src/governance/ tests/integration/test_dry_run.py
./.venv/Scripts/python.exe -m pytest tests/ --tb=line | tail -3

git add src/governance/dry_run.py tests/integration/test_dry_run.py
git commit -m "feat(governance): dry_run + pending confirmations

Generates 8-char alphanumeric tokens (uppercase + digits, 36^8 space).
Persists mutation payloads in pending_confirmations with 10-min TTL,
session-scoped (token from session A can't apply via session B).
SELECT FOR UPDATE ensures atomic consume — no double-apply race."
git push
```

## Report

Status, pytest tail, mypy/ruff, git head.

---

## Task 3: Mutation executor + apply_change tool (TDD)

**Goal:** Wire dry-run + Google Ads SDK execution + audit. `apply_change(token)` is the user-facing tool.

**Files:**
- Create: `src/google_ads/mutations.py` — shared `run_mutation` executor
- Create: `src/google_ads/mutates/__init__.py` (empty)
- Create: `src/google_ads/mutates/_common.py` — dispatcher mapping operation_type → builder
- Create: `src/mcp/tools/apply_change.py` — confirmation tool
- Update: `src/mcp/tools/_registry.py` to import apply_change

### Step 1: Implement `src/google_ads/mutates/_common.py`

EXACT content:

```python
"""Operation dispatcher — maps operation_type strings to mutate builders.

Each mutate builder takes (client, customer_id, payload) and returns
a list of MutateOperation messages ready to send via GoogleAdsService.mutate.

Tools register their builders here at import time so the apply_change
tool can dispatch by operation_type without coupling to specific tools.
"""
from collections.abc import Callable
from typing import Any

# Builder signature: (client, customer_id, payload) -> list of MutateOperations
MutateBuilder = Callable[[Any, str, dict[str, Any]], list[Any]]

_BUILDERS: dict[str, MutateBuilder] = {}


def register_builder(operation_type: str) -> Callable[[MutateBuilder], MutateBuilder]:
    """Decorator: registers a mutate builder for an operation type."""
    def decorator(fn: MutateBuilder) -> MutateBuilder:
        if operation_type in _BUILDERS:
            raise RuntimeError(f"Builder '{operation_type}' already registered")
        _BUILDERS[operation_type] = fn
        return fn
    return decorator


def get_builder(operation_type: str) -> MutateBuilder | None:
    return _BUILDERS.get(operation_type)


def reset() -> None:
    """Test helper."""
    _BUILDERS.clear()


def import_all_builders() -> None:
    """Eagerly import every mutate module so its register_builder runs."""
    from src.google_ads.mutates import (  # noqa: F401
        ad_groups,
        campaigns,
        keywords,
        negatives,
        recommendations,
    )
```

### Step 2: Implement `src/google_ads/mutations.py`

EXACT content:

```python
"""Shared executor for write tools.

run_mutation handles:
  - rate limit reservation
  - building the mutate operations via registered builders
  - executing via GoogleAdsService.mutate
  - audit logging (always for mutations — sensitive)
  - error translation
"""
import time
from typing import Any
from uuid import UUID

import structlog

from src.config import get_settings
from src.db import connection
from src.db.repositories import audit_log
from src.google_ads.client import build_client_for_manager
from src.google_ads.errors import to_friendly
from src.google_ads.mutates._common import get_builder, import_all_builders
from src.governance.rate_limit import (
    before_call,
    hash_developer_token,
    record_actual,
)

log = structlog.get_logger(__name__)

# Eagerly import builders so they're registered before any tool runs.
import_all_builders()


async def run_mutation(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    operation_type: str,
    payload: dict[str, Any],
    target_count: int,
) -> dict[str, Any]:
    """Execute a mutation. Returns {google_request_id, applied_count, partial_failures}."""
    settings = get_settings()
    token_id = hash_developer_token(settings.google_ads_developer_token)
    started = time.monotonic()
    pool = connection.get_pool()
    google_request_id: str | None = None
    error_message: str | None = None
    status = "success"

    try:
        async with pool.acquire() as conn:
            await before_call(conn, token_id, estimated_ops=max(1, target_count))

        builder = get_builder(operation_type)
        if builder is None:
            raise ValueError(f"No mutate builder registered for '{operation_type}'")

        client = await build_client_for_manager(manager_id=manager_id)

        try:
            operations = builder(client, customer_id, payload)
            ga_service = client.get_service("GoogleAdsService")
            request = client.get_type("MutateGoogleAdsRequest")
            request.customer_id = customer_id
            for op in operations:
                request.mutate_operations.append(op)
            response = ga_service.mutate(request=request)
            # Capture request_id if available
            google_request_id = getattr(response, "request_id", None) or None
        except Exception as e:
            raise to_friendly(e) from e

        return {
            "google_request_id": google_request_id,
            "applied_count": target_count,
            "partial_failures": [],
        }
    except Exception as e:
        status = "error"
        error_message = str(e)
        raise
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        async with pool.acquire() as conn:
            await record_actual(
                conn, token_id,
                actual_ops=target_count,
                estimated_ops=max(1, target_count),
            )
            # Always audit mutations (sensitive — every change is logged)
            await audit_log.record(
                conn,
                manager_id=manager_id,
                session_id=session_id,
                customer_id=customer_id,
                action_type="mutate",
                operation=operation_type,
                target_count=target_count,
                params_summary={"keys": sorted(payload.keys())},  # don't log full payload
                google_request_id=google_request_id,
                status=status,
                error_message=error_message,
                duration_ms=duration_ms,
            )
        log.info(
            "mutation_executed",
            operation=operation_type,
            customer_id=customer_id,
            target_count=target_count,
            status=status,
        )
```

### Step 3: Implement `src/mcp/tools/apply_change.py`

EXACT content:

```python
"""Tool: apply_change - consume a confirmation token + execute the saved mutation."""
from typing import Any

from src.db import connection
from src.google_ads.mutations import run_mutation
from src.governance.dry_run import InvalidTokenError, consume
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confirmation_token": {
            "type": "string",
            "pattern": "^[A-Z0-9]{8}$",
            "description": "Token de 8 chars retornado por uma tool de mutacao em modo dry-run.",
        },
    },
    "required": ["confirmation_token"],
    "additionalProperties": False,
}


@register_tool(
    name="apply_change",
    description=(
        "Confirma e aplica uma mutacao previamente previewed via dry-run. Token "
        "expira em 10 minutos. Cada token e consumivel apenas 1 vez e amarrado "
        "a sessao MCP que o gerou."
    ),
    input_schema=_SCHEMA,
)
async def apply_change(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    token = args["confirmation_token"]

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        try:
            saved = await consume(conn, token=token, session_id=ctx.session_id)
        except InvalidTokenError as e:
            return {
                "status": "error",
                "error": str(e),
            }

    target_count = int(saved.payload.get("__target_count__", 1))
    result = await run_mutation(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=saved.customer_id,
        operation_type=saved.operation_type,
        payload=saved.payload,
        target_count=target_count,
    )
    return {
        "status": "applied",
        "operation": saved.operation_type,
        "customer_id": saved.customer_id,
        "blast_summary": saved.blast_summary,
        "google_request_id": result["google_request_id"],
        "applied_count": result["applied_count"],
    }
```

### Step 4: Update `src/mcp/tools/_registry.py` to include apply_change

Add `apply_change` to the alphabetical import list.

### Step 5: Write basic integration test for apply_change with mocked SDK

Create `tests/integration/test_apply_change.py`:

```python
"""apply_change end-to-end with mocked Google Ads SDK."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import managers, mcp_sessions
from src.governance.dry_run import create_pending
from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
async def pg() -> PostgresContainer:
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
async def session_ctx(db):
    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="t@v4.com", full_name=None)
        from src.auth.sessions import generate_session_token, hash_session_token
        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token), label="t"
        )
    ctx = McpRequestContext(manager_id=mid, session_id=sess.id)
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.integration
async def test_apply_change_executes_mutation(db, session_ctx):
    """Token saved as 'update_campaign_status' is consumed and a mock mutation is run."""
    from src.mcp.tools.apply_change import apply_change

    pool = db
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=session_ctx.session_id,
            customer_id="1234567890",
            operation_type="update_campaign_status",
            payload={
                "campaign_ids": ["111"],
                "new_status": "PAUSED",
                "__target_count__": 1,
            },
            blast_summary="Pausar campanha 111",
        )

    # Mock both build_client_for_manager (so we never call Google) AND
    # the builder dispatch (so we never construct real protos).
    fake_client = MagicMock()
    fake_service = MagicMock()
    fake_response = MagicMock()
    fake_response.request_id = "fake-google-request-id"
    fake_service.mutate = MagicMock(return_value=fake_response)
    fake_client.get_service = MagicMock(return_value=fake_service)
    fake_client.get_type = MagicMock(return_value=MagicMock(mutate_operations=[]))

    with patch(
        "src.google_ads.mutations.build_client_for_manager",
        AsyncMock(return_value=fake_client),
    ), patch(
        "src.google_ads.mutations.get_builder",
        return_value=lambda c, cid, p: [MagicMock()],
    ):
        result = await apply_change({"confirmation_token": token})

    assert result["status"] == "applied"
    assert result["operation"] == "update_campaign_status"
    assert result["google_request_id"] == "fake-google-request-id"


@pytest.mark.integration
async def test_apply_change_returns_error_on_invalid_token(db, session_ctx):
    from src.mcp.tools.apply_change import apply_change
    result = await apply_change({"confirmation_token": "ABCD1234"})
    assert result["status"] == "error"
    assert "not found" in result["error"]
```

### Step 6: Run tests + commit

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_apply_change.py -v -m integration
./.venv/Scripts/python.exe -m mypy src/google_ads/mutations.py src/google_ads/mutates/_common.py src/mcp/tools/apply_change.py
./.venv/Scripts/python.exe -m ruff check src/google_ads/ src/mcp/tools/apply_change.py tests/integration/test_apply_change.py
./.venv/Scripts/python.exe -m ruff format --check src/google_ads/ src/mcp/tools/apply_change.py tests/integration/test_apply_change.py
./.venv/Scripts/python.exe -m pytest tests/ --tb=line | tail -3

git add src/google_ads/mutates/ src/google_ads/mutations.py src/mcp/tools/apply_change.py src/mcp/tools/_registry.py tests/integration/test_apply_change.py
git commit -m "feat(mutations): apply_change tool + run_mutation executor

apply_change consumes a confirmation token, dispatches to the
registered mutate builder, executes via GoogleAdsService.mutate,
and audits. Builder dispatch is decoupled (each mutate module
self-registers via @register_builder)."
git push
```

## Report

Status, pytest tail, mypy/ruff, git head.

---

## Task 4: Campaign mutations (3 tools — status, budget, bidding)

**Files:**
- Create: `src/google_ads/mutates/campaigns.py` — 3 builders
- Create: `src/mcp/tools/update_campaign_status.py`, `update_campaign_budget.py`, `update_campaign_bidding.py`
- Update: `_registry.py` to import them
- Create: `tests/integration/test_campaign_mutations.py`

The full content for each tool follows the standard write-tool template. Implementer fills in:

1. **Builder** (`src/google_ads/mutates/campaigns.py`):

```python
"""Mutate builders for campaign operations."""
from typing import Any

from src.google_ads.mutates._common import register_builder


@register_builder("update_campaign_status")
def build_update_campaign_status(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {campaign_ids: [str], new_status: 'ENABLED'|'PAUSED'|'REMOVED'}"""
    new_status = payload["new_status"].upper()
    operations = []
    for cid in payload["campaign_ids"]:
        op = client.get_type("MutateOperation")
        campaign_op = op.campaign_operation
        campaign = campaign_op.update
        campaign.resource_name = client.get_service("CampaignService").campaign_path(customer_id, cid)
        campaign.status = client.enums.CampaignStatusEnum.CampaignStatus[new_status]
        # Set field mask
        client.copy_from(campaign_op.update_mask, client.get_type("FieldMask")(paths=["status"]))
        operations.append(op)
    return operations


@register_builder("update_campaign_budget")
def build_update_campaign_budget(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {campaign_id: str, new_amount_micros: int}"""
    op = client.get_type("MutateOperation")
    budget_op = op.campaign_budget_operation
    budget = budget_op.update
    budget.resource_name = payload["campaign_budget_resource_name"]  # caller resolved this
    budget.amount_micros = payload["new_amount_micros"]
    client.copy_from(budget_op.update_mask, client.get_type("FieldMask")(paths=["amount_micros"]))
    return [op]


@register_builder("update_campaign_bidding")
def build_update_campaign_bidding(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {campaign_id, strategy: 'TARGET_CPA'|'TARGET_ROAS'|..., target_value_micros?}"""
    op = client.get_type("MutateOperation")
    campaign_op = op.campaign_operation
    campaign = campaign_op.update
    campaign.resource_name = client.get_service("CampaignService").campaign_path(customer_id, payload["campaign_id"])
    strategy = payload["strategy"].upper()
    if strategy == "TARGET_CPA":
        campaign.target_cpa.target_cpa_micros = payload["target_value_micros"]
        client.copy_from(campaign_op.update_mask, client.get_type("FieldMask")(paths=["target_cpa.target_cpa_micros"]))
    elif strategy == "TARGET_ROAS":
        campaign.target_roas.target_roas = payload["target_roas"]
        client.copy_from(campaign_op.update_mask, client.get_type("FieldMask")(paths=["target_roas.target_roas"]))
    elif strategy == "MAXIMIZE_CONVERSIONS":
        campaign.maximize_conversions.target_cpa_micros = payload.get("target_value_micros", 0)
        client.copy_from(campaign_op.update_mask, client.get_type("FieldMask")(paths=["maximize_conversions.target_cpa_micros"]))
    else:
        raise ValueError(f"Unsupported bidding strategy: {strategy}")
    return [op]
```

2. **Tools** — each one follows this pattern (status example shown; budget + bidding analogous):

```python
"""Tool: update_campaign_status - pause/enable/remove campaigns."""
from typing import Any

from src.db import connection
from src.governance.blast_radius import RiskLevel, classify
from src.governance.dry_run import create_pending
from src.google_ads.mutations import run_mutation
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "campaign_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "minItems": 1,
        },
        "new_status": {"type": "string", "enum": ["ENABLED", "PAUSED", "REMOVED"]},
    },
    "required": ["customer_id", "campaign_ids", "new_status"],
    "additionalProperties": False,
}


@register_tool(
    name="update_campaign_status",
    description=(
        "Pausa, ativa ou remove uma ou mais campanhas. <=5 campanhas auto-aplica; "
        ">5 retorna preview com confirmation_token (chamar apply_change pra aplicar)."
    ),
    input_schema=_SCHEMA,
)
async def update_campaign_status(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    campaign_ids = args["campaign_ids"]
    new_status = args["new_status"]
    target_count = len(campaign_ids)

    risk = classify(
        operation="update_campaign_status",
        params={"target_count": target_count},
    )
    payload = {
        "campaign_ids": campaign_ids,
        "new_status": new_status,
        "__target_count__": target_count,
    }
    summary = (
        f"Mudar status de {target_count} campanha(s) "
        f"({', '.join(campaign_ids[:3])}{'...' if target_count > 3 else ''}) "
        f"para {new_status}."
    )

    if risk.level == RiskLevel.AUTO:
        result = await run_mutation(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_campaign_status",
            payload=payload,
            target_count=target_count,
        )
        return {
            "status": "applied",
            "operation": "update_campaign_status",
            "customer_id": customer_id,
            "blast_summary": summary,
            "applied_count": result["applied_count"],
            "google_request_id": result["google_request_id"],
            "auto_applied_reason": risk.reason,
        }

    # Confirm path: create token, return preview
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_campaign_status",
            payload=payload,
            blast_summary=summary,
        )
    return {
        "status": "dry_run",
        "operation": "update_campaign_status",
        "customer_id": customer_id,
        "blast_summary": summary,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
```

`update_campaign_budget` and `update_campaign_bidding` follow the same pattern with their own params + always-confirm path (skipping the auto branch).

For `update_campaign_budget`, the tool also needs to RESOLVE the `campaign_budget_resource_name` first via a small GAQL lookup. Add a helper in `mutates/campaigns.py` or inline in the tool.

3. **Tests** (`tests/integration/test_campaign_mutations.py`): one test per tool covering both auto and dry-run paths. Use the same mock pattern as `test_apply_change.py`.

4. **Update _registry.py** with the 3 new imports.

5. **Commit + push.**

## Report

Status, pytest tail, mypy/ruff, git head.

---

## Task 5: Ad group mutations (2 tools — status, bid)

Same pattern as Task 4. Files:
- Create: `src/google_ads/mutates/ad_groups.py` (2 builders)
- Create: `src/mcp/tools/update_ad_group_status.py`, `update_ad_group_bid.py`
- Update: `_registry.py`
- Create: `tests/integration/test_ad_group_mutations.py`

`update_ad_group_status` mirrors `update_campaign_status` — bulk-aware, status enum.

`update_ad_group_bid` is the first BID tool — it uses `_bid_classify` blast rules (variation + count). The tool must resolve current bid first to compute `max_delta_pct`:

```python
# In the tool:
# 1. GAQL lookup to fetch current cpc_bid_micros for each ad_group
# 2. Compute max_delta_pct across all ad_groups
# 3. Pass max_delta_pct to classify(...)
```

This adds complexity vs status mutations. The lookup uses `run_report` from Phase 2 — reuse that.

## Report

Status, pytest tail, mypy/ruff, git head.

---

## Task 6: Keyword mutations (2 tools — status, bid)

Same pattern as Task 5 but for keywords. Files:
- Create: `src/google_ads/mutates/keywords.py` (2 builders for `update_keyword_status` + `update_keyword_bid`)
- Create: `src/mcp/tools/update_keyword_status.py`, `update_keyword_bid.py`
- Update: `_registry.py`
- Create: `tests/integration/test_keyword_mutations.py`

Keyword mutations target `ad_group_criterion` resource. The status enum is `AdGroupCriterionStatusEnum.AdGroupCriterionStatus`. Bid is `cpc_bid_micros` on the criterion.

## Report

Status, pytest tail, mypy/ruff, git head.

---

## Task 7: Negative keywords (1 tool — add_negative_keywords)

Files:
- Create: `src/google_ads/mutates/negatives.py` (1 builder)
- Create: `src/mcp/tools/add_negative_keywords.py`
- Update: `_registry.py`
- Create: `tests/integration/test_negative_keywords.py`

Builder creates `campaign_criterion` operations with `negative=True` and `keyword.match_type` from input.

Tool always auto-applies (per blast_radius rules — negatives are safe).

`payload`: `{level: "campaign", target_id: "<campaign_id>", keywords: [{text, match_type}]}`.

## Report

Status, pytest tail, mypy/ruff, git head.

---

## Task 8: Recommendations (2 tools — apply, dismiss)

Files:
- Create: `src/google_ads/mutates/recommendations.py` (2 builders)
- Create: `src/mcp/tools/apply_recommendation.py`, `dismiss_recommendation.py`
- Update: `_registry.py`
- Create: `tests/integration/test_recommendations.py`

Apply uses `RecommendationService.apply_recommendation`. Dismiss uses `dismiss_recommendation`. Both auto-apply.

## Report

Status, pytest tail, mypy/ruff, git head.

---

## Task 9: E2E + sign-off

After all 10 mutation tools are deployed, the user runs 3 mutation prompts via Codex/Claude on a test customer (V4 has a sandbox account, OR pause then re-enable a real campaign):

1. **Auto-apply path:** "Use add_negative_keywords na conta XXX para adicionar 'free' como BROAD na campanha YYY" — should apply immediately.
2. **Dry-run path:** "Use update_campaign_budget na conta XXX, campanha YYY, novo orçamento R$ 200" — should return a confirmation_token. Then "apply_change com token Z" should execute.
3. **Bulk path:** "Pausa as 10 keywords menos performantes da conta XXX" — should require dry-run because >5.

Verify in Google Ads UI Change History that changes show under wellinton.ribeiro@v4company.com (proves OAuth-per-manager works for writes too).

Update `docs/operacao/infra-setup.md` with Phase 3a sign-off summarizing what was tested.

## Report

Status, sign-off commit hash, list of mutations actually executed in production.

---

## Self-review notes

**Spec coverage (Phase 3a subset):**
- §6.3 status mutations (campaign, ad_group, keyword) — Tasks 4-6
- §6.3 update_campaign_budget + update_campaign_bidding — Task 4
- §6.3 update_ad_group_bid + update_keyword_bid — Tasks 5-6
- §6.3 add_negative_keywords — Task 7
- §6.3 apply_recommendation + dismiss_recommendation — Task 8
- §7.1 blast radius — Task 1
- §7.2 dry-run flow — Task 2
- §7.4 audit (always for mutations) — Task 3 (run_mutation)

**Out of scope for Phase 3a (deferred to 3b):**
- create_campaign, create_ad_group (these require many more params; nice but lower-frequency)
- add_keywords (also bulk-capable, requires schema for new keyword definitions)
- update_keyword_match_type
- add_negatives_from_search_terms (atalho semântico over add_negative_keywords)
- create_rsa, update_rsa, update_ad_status (RSAs need headlines/descriptions/asset arrays)
- create_asset, link_assets
- apply_audience, upload_customer_match_list
- create_conversion_action, import_offline_conversions
- bulk_pause_by_query

**Risk register:**
- Real Google Ads mutations are irreversible; tests must NEVER hit the real API. Always use mocks.
- `update_campaign_budget` requires resolving the `campaign_budget_resource_name` from `campaign.id` — adds a GAQL lookup per call.
- `update_ad_group_bid` and `update_keyword_bid` need to fetch CURRENT bid to compute `max_delta_pct`. Adds latency but ensures blast classification is accurate.
- Concurrent dry-run + apply on same token: race-safe via `SELECT FOR UPDATE` in `consume()`.
