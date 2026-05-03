# V4 Ads MCP — Phase 0: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provision the repo, CI/CD pipeline, infrastructure (GCP + Supabase), and a minimal FastAPI app exposing `/healthz` and an empty MCP `/mcp` endpoint deployable to Cloud Run.

**Architecture:** Python 3.12 monolith with FastAPI; MCP via Streamable HTTP; Postgres via Supabase + asyncpg; Cloud Run + Cloud Buildpacks; Secret Manager for secrets; GitHub Actions CI/CD with Workload Identity Federation (no JSON keys).

**Tech Stack:** Python 3.12, `uv`, FastAPI, `mcp` (Anthropic Python SDK), `asyncpg`, `structlog`, `pytest`, `pytest-asyncio`, `httpx`, `ruff`, `mypy`, `testcontainers-python`, GitHub Actions, Google Cloud Run, Google Cloud Buildpacks, Google Secret Manager, Supabase.

**Reference spec:** `docs/superpowers/specs/2026-05-03-v4-ads-mcp-design.md`

**Definition of done (Phase 0):** push to `main` → GitHub Actions runs lint + tests + deploys to Cloud Run in <5min. `curl https://<service>.run.app/healthz` returns 200. `curl -X POST https://<service>.run.app/mcp` with valid MCP handshake returns empty `tools/list`. DB migrations applied. Supabase project provisioned. All secrets in Secret Manager (placeholders OK at this phase).

---

## File structure (created in this phase)

```
.
├── .github/workflows/
│   ├── ci.yml                          # lint + test on PR
│   └── deploy.yml                      # deploy to Cloud Run on push to main
├── .gitignore
├── .python-version                     # 3.12
├── pyproject.toml                      # deps + ruff/mypy/pytest config
├── README.md                           # project overview, dev setup
├── Procfile                            # Buildpacks entry point
├── docs/
│   └── operacao/
│       └── infra-setup.md              # one-time manual setup steps (GCP/Supabase)
├── src/
│   ├── __init__.py
│   ├── app.py                          # FastAPI bootstrap, mounts /mcp + /healthz
│   ├── config.py                       # Pydantic Settings
│   ├── logging.py                      # structlog config
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── server.py                   # MCP Streamable HTTP server (empty tools)
│   │   └── session.py                  # Bearer token middleware (stub)
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py               # asyncpg pool factory
│   │   ├── migrate.py                  # idempotent migration runner
│   │   └── migrations/
│   │       └── 001_initial_schema.sql  # 8 tables from spec section 4
│   └── jobs/
│       └── __init__.py                 # placeholder
└── tests/
    ├── __init__.py
    ├── conftest.py                     # shared fixtures (db, app, client)
    ├── unit/
    │   ├── __init__.py
    │   ├── test_config.py              # Pydantic Settings validation
    │   └── test_mcp_session.py         # Bearer token parsing stub
    └── integration/
        ├── __init__.py
        ├── test_healthz.py             # GET /healthz
        ├── test_mcp_handshake.py       # POST /mcp returns empty tools
        └── test_migrations.py          # migrations are idempotent
```

---

## Manual prerequisites (do before Task 1)

These cannot be automated — they require human action in cloud consoles. Document under `docs/operacao/infra-setup.md` for posterity.

- [ ] **Create GCP project `v4-ads-mcp-prod`** at https://console.cloud.google.com (or use existing V4 GCP organization)
- [ ] **Enable APIs in the GCP project:** Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Cloud Logging, Cloud Scheduler, Google Ads (`googleads.googleapis.com`)
- [ ] **Create Supabase project** at https://supabase.com → name "v4-ads-mcp" → region "South America (São Paulo)" → strong DB password (save in 1Password)
- [ ] **Note the Supabase connection string** (`postgresql://postgres:<pwd>@db.<ref>.supabase.co:5432/postgres`) — needed in Task 4
- [ ] **Reserve Google Ads developer token** at https://ads.google.com/aw/apicenter (already exists: `<set in Secret Manager — see 1Password "v4-ads-mcp / google-ads-dev-token">`)
- [x] **GitHub repo:** `BadWolf1509/v4-ads-mcp` (private), URL `https://github.com/BadWolf1509/v4-ads-mcp.git`. Working directory: `D:\HUB ads MCP\`

When all done, mark this section complete in `docs/operacao/infra-setup.md` and continue with Task 1.

---

## Task 1: Initialize repository skeleton

**Files:**
- Create: `.gitignore`, `.python-version`, `README.md`, `pyproject.toml`, `Procfile`, `docs/operacao/infra-setup.md`
- Create directory tree: `src/`, `src/mcp/`, `src/db/`, `src/db/migrations/`, `src/jobs/`, `tests/unit/`, `tests/integration/`, `.github/workflows/`

- [ ] **Step 1: Initialize git repo and create `.gitignore`**

```bash
cd "/d/HUB ads MCP"
git init -b main
```

Create `.gitignore`:

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.venv/
venv/
.env
.env.*
!.env.example
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/
.coverage
coverage.xml

# IDE / editor / agent state
.vscode/
.idea/
*.swp
.claude/
.cursor/

# OS
.DS_Store
Thumbs.db

# Build artifacts
dist/
build/
*.log
```

- [ ] **Step 2: Create `.python-version`**

```
3.12
```

- [ ] **Step 3: Create directory skeleton**

```bash
mkdir -p src/mcp src/db/migrations src/jobs
mkdir -p tests/unit tests/integration
mkdir -p .github/workflows
mkdir -p docs/operacao
touch src/__init__.py src/mcp/__init__.py src/db/__init__.py src/jobs/__init__.py
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py
```

- [ ] **Step 4: Create `pyproject.toml`**

```toml
[project]
name = "v4-ads-mcp"
version = "0.1.0"
description = "V4 Ads MCP — Google Ads + Meta Ads control via MCP"
requires-python = ">=3.12,<3.14"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "mcp>=1.2.0",
    "asyncpg>=0.30.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.6.0",
    "structlog>=24.4.0",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=6.0.0",
    "ruff>=0.7.0",
    "mypy>=1.13.0",
    "testcontainers[postgres]>=4.8.0",
    "respx>=0.21.0",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "SIM", "ASYNC"]
ignore = ["E501"]  # handled by formatter

[tool.mypy]
python_version = "3.12"
strict = true
warn_unreachable = true
no_implicit_reexport = true

[[tool.mypy.overrides]]
module = ["testcontainers.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = ["-q", "--strict-markers", "--strict-config"]
markers = [
    "integration: tests that require a live DB",
]
```

- [ ] **Step 5: Create `Procfile` for Buildpacks**

```
web: uvicorn src.app:app --host 0.0.0.0 --port $PORT --workers 1
```

- [ ] **Step 6: Create `README.md`**

```markdown
# V4 Ads MCP

MCP server giving Claude (and other MCP clients) native control over V4 Company's Google Ads accounts. See `docs/superpowers/specs/2026-05-03-v4-ads-mcp-design.md` for the design spec.

## Dev setup

1. Install Python 3.12 (`pyenv install 3.12` or via your system).
2. Create venv: `python -m venv .venv && source .venv/bin/activate` (or `.venv\Scripts\activate` on Windows).
3. Install deps: `pip install -e ".[dev]"`
4. Copy `.env.example` to `.env` and fill in values.
5. Run tests: `pytest`
6. Run app locally: `uvicorn src.app:app --reload --port 8080`

## Stack

Python 3.12 · FastAPI · MCP Python SDK · asyncpg · Postgres (Supabase) · Cloud Run · GitHub Actions

## Documentation

- Design spec: [`docs/superpowers/specs/2026-05-03-v4-ads-mcp-design.md`](docs/superpowers/specs/2026-05-03-v4-ads-mcp-design.md)
- Infra setup: [`docs/operacao/infra-setup.md`](docs/operacao/infra-setup.md)
```

- [ ] **Step 7: Create `docs/operacao/infra-setup.md`** with a checklist mirroring the "Manual prerequisites" section above (so future devs know what was done manually).

```markdown
# Infra setup — one-time manual steps

This document records the cloud-console actions performed once to bootstrap the project. Re-doing them is only necessary in disaster recovery or to provision a new environment.

## GCP project
- [x] Project created: `v4-ads-mcp-prod` (project ID: ____)
- [x] APIs enabled: Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Cloud Logging, Cloud Scheduler, Google Ads
- [ ] Workload Identity Federation pool/provider configured (Task 11)
- [ ] Secret Manager secrets created (Task 11)

## Supabase project
- [x] Project: `v4-ads-mcp`, region `sa-east-1` (São Paulo)
- [x] DB password saved in 1Password under "v4-ads-mcp / supabase"
- [x] Connection string saved in 1Password (will be put in Secret Manager in Task 11)

## Google Ads
- [x] Developer token: `<set in Secret Manager — see 1Password "v4-ads-mcp / google-ads-dev-token">` (Test Account mode at MVP; submit Standard Access during Phase 1)

## GitHub
- [x] Repo: `v4company/ads-mcp` (private)
- [ ] Branch protection on `main`: require PR + passing CI (set after Task 11)
```

- [ ] **Step 8: Verify directory structure**

Run:
```bash
ls -la
find . -type d -not -path './.git*' | sort
```
Expected: see `.github/workflows`, `src/{mcp,db/migrations,jobs}`, `tests/{unit,integration}`, `docs/operacao`.

- [ ] **Step 9: Commit**

```bash
git add .
git commit -m "chore: initialize repository skeleton

- Python 3.12 + uv + ruff + mypy + pytest configured via pyproject.toml
- Procfile for Cloud Buildpacks deploy
- src/ and tests/ directory structure scaffolded
- docs/operacao/infra-setup.md tracks one-time manual cloud setup"
```

---

## Task 2: Create application config module

**Files:**
- Create: `src/config.py`, `tests/unit/test_config.py`, `.env.example`

- [ ] **Step 1: Write the failing test `tests/unit/test_config.py`**

```python
import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.config import Settings


def test_settings_loads_required_envs():
    env = {
        "APP_ENV": "development",
        "DATABASE_URL": "postgresql://u:p@localhost:5432/test",
        "SESSION_SIGNING_KEY": "x" * 32,
        "AES_MASTER_KEY": "y" * 32,
        "GOOGLE_OAUTH_CLIENT_ID": "client.apps.googleusercontent.com",
        "GOOGLE_OAUTH_CLIENT_SECRET": "secret",
        "GOOGLE_ADS_DEVELOPER_TOKEN": "dev-token",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890",
        "SUPABASE_URL": "https://abc.supabase.co",
        "SUPABASE_ANON_KEY": "anon",
        "SUPABASE_SERVICE_KEY": "service",
    }
    with patch.dict(os.environ, env, clear=True):
        s = Settings()
        assert s.app_env == "development"
        assert s.app_timezone == "America/Sao_Paulo"  # default
        assert s.log_level == "info"  # default


def test_settings_rejects_short_signing_key():
    env = {
        "APP_ENV": "development",
        "DATABASE_URL": "postgresql://u:p@localhost:5432/test",
        "SESSION_SIGNING_KEY": "tooshort",  # < 32
        "AES_MASTER_KEY": "y" * 32,
        "GOOGLE_OAUTH_CLIENT_ID": "client",
        "GOOGLE_OAUTH_CLIENT_SECRET": "secret",
        "GOOGLE_ADS_DEVELOPER_TOKEN": "dev-token",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890",
        "SUPABASE_URL": "https://abc.supabase.co",
        "SUPABASE_ANON_KEY": "anon",
        "SUPABASE_SERVICE_KEY": "service",
    }
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValidationError):
            Settings()


def test_login_customer_id_must_be_digits():
    env = {
        "APP_ENV": "development",
        "DATABASE_URL": "postgresql://u:p@localhost:5432/test",
        "SESSION_SIGNING_KEY": "x" * 32,
        "AES_MASTER_KEY": "y" * 32,
        "GOOGLE_OAUTH_CLIENT_ID": "client",
        "GOOGLE_OAUTH_CLIENT_SECRET": "secret",
        "GOOGLE_ADS_DEVELOPER_TOKEN": "dev-token",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "123-456-7890",  # has dashes
        "SUPABASE_URL": "https://abc.supabase.co",
        "SUPABASE_ANON_KEY": "anon",
        "SUPABASE_SERVICE_KEY": "service",
    }
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValidationError):
            Settings()
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest tests/unit/test_config.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'src.config'`.

- [ ] **Step 3: Implement `src/config.py`**

```python
"""Application settings loaded from environment variables."""
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration; values come from env vars."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # App
    app_env: Literal["development", "staging", "production"]
    app_timezone: str = "America/Sao_Paulo"
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    # Database
    database_url: str

    # Crypto
    session_signing_key: str = Field(min_length=32)
    aes_master_key: str = Field(min_length=32)

    # Google OAuth (for the panel's Google Ads connection)
    google_oauth_client_id: str
    google_oauth_client_secret: str

    # Google Ads API
    google_ads_developer_token: str
    google_ads_login_customer_id: str

    # Supabase (auth + DB)
    supabase_url: str
    supabase_anon_key: str
    supabase_service_key: str

    @field_validator("google_ads_login_customer_id")
    @classmethod
    def validate_customer_id_format(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError(
                "google_ads_login_customer_id must be digits only (no dashes)"
            )
        return v


def get_settings() -> Settings:
    """Factory used by FastAPI dependency injection."""
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
pytest tests/unit/test_config.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Create `.env.example`**

```bash
# App
APP_ENV=development
APP_TIMEZONE=America/Sao_Paulo
LOG_LEVEL=debug

# Database (Supabase Postgres)
DATABASE_URL=postgresql://postgres:CHANGEME@db.YOURPROJECTREF.supabase.co:5432/postgres

# Crypto (generate with: python -c 'import secrets; print(secrets.token_urlsafe(32))')
SESSION_SIGNING_KEY=CHANGEME_minimum_32_characters_long_random
AES_MASTER_KEY=CHANGEME_minimum_32_characters_long_random

# Google OAuth (from Google Cloud Console → APIs & Services → Credentials)
GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-yoursecret

# Google Ads API
GOOGLE_ADS_DEVELOPER_TOKEN=<set in Secret Manager — see 1Password "v4-ads-mcp / google-ads-dev-token">
GOOGLE_ADS_LOGIN_CUSTOMER_ID=1234567890   # digits only, no dashes

# Supabase
SUPABASE_URL=https://YOURPROJECTREF.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_KEY=eyJ...
```

- [ ] **Step 6: Commit**

```bash
git add src/config.py tests/unit/test_config.py .env.example
git commit -m "feat(config): typed Settings with env var validation

Pydantic Settings loads required envs and validates: signing/AES
keys minimum length, login_customer_id digits-only. .env.example
documents the variables needed locally."
```

---

## Task 3: Create structured logging module

**Files:**
- Create: `src/logging.py`

- [ ] **Step 1: Implement `src/logging.py`**

```python
"""Structured logging via structlog. JSON in prod, pretty in dev."""
import logging
import sys
from typing import Any

import structlog


def configure_logging(level: str = "info", json_output: bool = True) -> None:
    """Configure root logger and structlog.

    Call once at app startup. After that, get loggers via
    `structlog.get_logger(__name__)` from any module.
    """
    log_level = getattr(logging, level.upper())

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def bind_request_context(**kwargs: Any) -> None:
    """Attach contextual fields to all logs in current async task."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_request_context() -> None:
    """Clear contextual fields between requests."""
    structlog.contextvars.clear_contextvars()
```

- [ ] **Step 2: Smoke test it manually**

Run:
```bash
python -c "
from src.logging import configure_logging, bind_request_context
import structlog
configure_logging(level='debug', json_output=False)
log = structlog.get_logger('smoke')
bind_request_context(request_id='abc', manager_id='123')
log.info('hello', foo='bar')
"
```
Expected: pretty-printed log line containing `hello`, `foo=bar`, `request_id=abc`, `manager_id=123`.

- [ ] **Step 3: Commit**

```bash
git add src/logging.py
git commit -m "feat(logging): structured logging via structlog

JSON output in production (Cloud Logging-friendly), pretty colored
output for local dev. Contextvars-based binding lets us attach
request_id/manager_id once per request and have it appear on all
subsequent log lines automatically."
```

---

## Task 4: Set up DB connection layer

**Files:**
- Create: `src/db/connection.py`

- [ ] **Step 1: Implement `src/db/connection.py`**

```python
"""asyncpg connection pool factory."""
from typing import AsyncIterator

import asyncpg
import structlog

log = structlog.get_logger(__name__)

_pool: asyncpg.Pool | None = None


async def init_pool(database_url: str, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    """Create the global pool. Call once at app startup."""
    global _pool
    if _pool is not None:
        return _pool
    _pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=min_size,
        max_size=max_size,
        command_timeout=30,
    )
    log.info("db_pool_created", min_size=min_size, max_size=max_size)
    return _pool


async def close_pool() -> None:
    """Close the global pool. Call once at app shutdown."""
    global _pool
    if _pool is None:
        return
    await _pool.close()
    _pool = None
    log.info("db_pool_closed")


def get_pool() -> asyncpg.Pool:
    """Get the global pool. Raises if init_pool was not called."""
    if _pool is None:
        raise RuntimeError("DB pool not initialized; call init_pool() first")
    return _pool


async def acquire() -> AsyncIterator[asyncpg.Connection]:
    """FastAPI-compatible dependency that yields a connection."""
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn
```

- [ ] **Step 2: Commit**

```bash
git add src/db/connection.py
git commit -m "feat(db): asyncpg pool factory with init/close lifecycle

Global pool managed via init_pool() at startup and close_pool()
at shutdown. Connection acquisition exposed via async context
manager and FastAPI-style dependency."
```

---

## Task 5: Create initial DB migration (8 tables from spec)

**Files:**
- Create: `src/db/migrations/001_initial_schema.sql`

- [ ] **Step 1: Write `src/db/migrations/001_initial_schema.sql`**

```sql
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
```

- [ ] **Step 2: Commit**

```bash
git add src/db/migrations/001_initial_schema.sql
git commit -m "feat(db): initial schema migration (8 tables)

Mirrors spec §4: managers, google_oauth_connections,
google_ads_accounts, manager_account_access, mcp_sessions,
pending_confirmations, audit_log, rate_counters. CHECK
constraints enforce enum values. All CREATEs are IF NOT EXISTS
so the migration is safely re-runnable."
```

---

## Task 6: Build idempotent migration runner

**Files:**
- Create: `src/db/migrate.py`, `tests/integration/test_migrations.py`

- [ ] **Step 1: Write the failing test `tests/integration/test_migrations.py`**

```python
"""Integration tests for the migration runner.

Uses testcontainers to spin up a real Postgres so we test the actual
behavior (idempotency, schema correctness) and not a mock.
"""
import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.mark.integration
async def test_migrations_run_clean(pg: PostgresContainer) -> None:
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=2)
    try:
        await migrate.run_all()
        # Verify a known table exists.
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT to_regclass('public.audit_log') AS tbl"
            )
            assert row["tbl"] == "audit_log"
    finally:
        await connection.close_pool()


@pytest.mark.integration
async def test_migrations_are_idempotent(pg: PostgresContainer) -> None:
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=2)
    try:
        await migrate.run_all()
        await migrate.run_all()  # second run must not raise
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            applied = await conn.fetch("SELECT name FROM _migrations ORDER BY name")
            assert [r["name"] for r in applied] == ["001_initial_schema.sql"]
    finally:
        await connection.close_pool()
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest tests/integration/test_migrations.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'src.db.migrate'`.

- [ ] **Step 3: Implement `src/db/migrate.py`**

```python
"""Idempotent SQL migration runner.

Reads files from `src/db/migrations/*.sql` in lexical order, applies
each one inside a transaction, and records applied migrations in a
`_migrations` table to avoid re-running them.
"""
import asyncio
from pathlib import Path

import structlog

from src.config import get_settings
from src.db import connection

log = structlog.get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS _migrations (
    name        TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


async def _list_pending(conn) -> list[Path]:
    rows = await conn.fetch("SELECT name FROM _migrations")
    applied = {r["name"] for r in rows}
    all_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    return [f for f in all_files if f.name not in applied]


async def run_all() -> None:
    """Apply every pending migration in order. Idempotent."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(_BOOTSTRAP_SQL)
        pending = await _list_pending(conn)
        if not pending:
            log.info("migrations_no_pending")
            return
        for path in pending:
            sql = path.read_text(encoding="utf-8")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO _migrations (name) VALUES ($1)",
                    path.name,
                )
            log.info("migration_applied", name=path.name)


async def main() -> None:
    """CLI entrypoint: `python -m src.db.migrate`."""
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        await run_all()
    finally:
        await connection.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run integration test to verify it passes**

Run:
```bash
pytest tests/integration/test_migrations.py -v -m integration
```
Expected: 2 passed (testcontainers will pull the postgres image on first run, ~30s).

If it fails with "Docker not available", install Docker Desktop and retry.

- [ ] **Step 5: Commit**

```bash
git add src/db/migrate.py tests/integration/test_migrations.py
git commit -m "feat(db): idempotent migration runner

Applies pending .sql files from src/db/migrations in lexical order,
each inside a transaction, recording applied names in _migrations
to skip on subsequent runs. Integration test uses testcontainers
to verify against real Postgres."
```

---

## Task 7: Create FastAPI app with /healthz

**Files:**
- Create: `src/app.py`, `tests/integration/test_healthz.py`

- [ ] **Step 1: Write the failing test `tests/integration/test_healthz.py`**

```python
import pytest
from httpx import AsyncClient, ASGITransport

from src.app import create_app


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app(skip_db_init=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_healthz_returns_200(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest tests/integration/test_healthz.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'src.app'`.

- [ ] **Step 3: Implement `src/app.py`**

```python
"""FastAPI application factory."""
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI

from src.config import get_settings
from src.db import connection
from src.logging import configure_logging
from src.mcp.server import mount_mcp

__version__ = "0.1.0"

log = structlog.get_logger(__name__)


def create_app(skip_db_init: bool = False) -> FastAPI:
    """Build the FastAPI app. Test code uses `skip_db_init=True`."""
    settings = get_settings()
    configure_logging(
        level=settings.log_level,
        json_output=settings.app_env != "development",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not skip_db_init:
            await connection.init_pool(settings.database_url)
            log.info("app_started", env=settings.app_env)
        yield
        if not skip_db_init:
            await connection.close_pool()
            log.info("app_stopped")

    app = FastAPI(
        title="V4 Ads MCP",
        version=__version__,
        lifespan=lifespan,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    mount_mcp(app)
    return app


# Module-level instance for uvicorn / Buildpacks
app = create_app()
```

- [ ] **Step 4: Create stub `src/mcp/server.py`** (full implementation in Task 8)

```python
"""MCP server stub. Real implementation in Task 8."""
from fastapi import FastAPI


def mount_mcp(app: FastAPI) -> None:
    """Mount the MCP transport at /mcp. Stubbed in Task 7, completed in Task 8."""
    @app.post("/mcp")
    async def mcp_stub() -> dict[str, list]:
        return {"tools": []}
```

- [ ] **Step 5: Run test to verify it passes**

Run:
```bash
pytest tests/integration/test_healthz.py -v
```
Expected: 1 passed.

- [ ] **Step 6: Manual smoke test**

Set up local env first:
```bash
cp .env.example .env
# Edit .env: set SESSION_SIGNING_KEY and AES_MASTER_KEY to 32+ random chars,
# DATABASE_URL to your Supabase connection string
python -c "import secrets; print(secrets.token_urlsafe(32))"  # generate keys
```

Then run locally:
```bash
uvicorn src.app:app --reload --port 8080
```

In another terminal:
```bash
curl http://localhost:8080/healthz
```
Expected: `{"status":"ok","version":"0.1.0"}`

- [ ] **Step 7: Commit**

```bash
git add src/app.py src/mcp/server.py tests/integration/test_healthz.py
git commit -m "feat(app): FastAPI app with /healthz and MCP stub

Application factory wires settings, structlog config, DB pool
lifecycle, and mounts an /mcp stub (proper implementation in
next task). Healthz returns version + status for Cloud Run probes."
```

---

## Task 8: Implement MCP server with Streamable HTTP transport (empty tools)

**Files:**
- Modify: `src/mcp/server.py`
- Create: `src/mcp/session.py`, `tests/integration/test_mcp_handshake.py`, `tests/unit/test_mcp_session.py`

- [ ] **Step 1: Write failing test `tests/unit/test_mcp_session.py`**

```python
import pytest

from src.mcp.session import extract_bearer_token


def test_extracts_bearer_from_header():
    token = extract_bearer_token("Bearer mcp_abc123")
    assert token == "mcp_abc123"


def test_returns_none_for_missing_header():
    assert extract_bearer_token(None) is None


def test_returns_none_for_wrong_scheme():
    assert extract_bearer_token("Basic dXNlcjpwYXNz") is None


def test_returns_none_for_empty_token():
    assert extract_bearer_token("Bearer ") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest tests/unit/test_mcp_session.py -v
```
Expected: FAIL with import error.

- [ ] **Step 3: Implement `src/mcp/session.py`**

```python
"""MCP session resolution from Bearer tokens.

This module is a stub at Phase 0 — it only parses the Authorization
header. Full session resolution (DB lookup, manager_id binding) lands
in Phase 1.
"""


def extract_bearer_token(authorization_header: str | None) -> str | None:
    """Parse 'Bearer <token>' header, returning the token or None.

    Returns None when the header is missing, uses a non-Bearer scheme,
    or has an empty token.
    """
    if not authorization_header:
        return None
    parts = authorization_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None
```

- [ ] **Step 4: Run unit test to verify it passes**

Run:
```bash
pytest tests/unit/test_mcp_session.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Write failing test `tests/integration/test_mcp_handshake.py`**

```python
import pytest
from httpx import AsyncClient, ASGITransport

from src.app import create_app


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app(skip_db_init=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_mcp_initialize(client: AsyncClient) -> None:
    """Server responds to MCP initialize handshake."""
    response = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        },
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    assert "result" in body
    assert body["result"]["protocolVersion"] == "2024-11-05"
    assert body["result"]["serverInfo"]["name"] == "v4-ads-mcp"


async def test_mcp_tools_list_empty(client: AsyncClient) -> None:
    """tools/list returns an empty array at Phase 0."""
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["tools"] == []
```

- [ ] **Step 6: Run integration test to verify it fails**

Run:
```bash
pytest tests/integration/test_mcp_handshake.py -v
```
Expected: FAIL — the stub from Task 7 doesn't implement the JSON-RPC handshake.

- [ ] **Step 7: Replace `src/mcp/server.py` with proper implementation**

Replace the entire file content:

```python
"""MCP server using the official Anthropic Python SDK with Streamable HTTP transport."""
from fastapi import FastAPI
from mcp.server import Server
from mcp.server.streamable_http import StreamableHTTPSessionManager
from mcp.types import Tool

# Server name surfaced to MCP clients in initialize handshake
SERVER_NAME = "v4-ads-mcp"
SERVER_VERSION = "0.1.0"


def build_server() -> Server:
    """Construct the MCP Server. At Phase 0, no tools are registered."""
    server = Server(SERVER_NAME, version=SERVER_VERSION)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return []

    return server


def mount_mcp(app: FastAPI) -> None:
    """Mount the MCP server's Streamable HTTP transport at /mcp."""
    server = build_server()
    session_manager = StreamableHTTPSessionManager(app=server)

    @app.post("/mcp")
    async def mcp_endpoint(request):  # type: ignore[no-untyped-def]
        return await session_manager.handle_request(request)
```

> **Note on the MCP SDK API:** the exact import paths and class names may evolve between SDK releases. If the names above don't match your installed version, run `pip show mcp` and check the SDK's docs/examples to get the current `StreamableHTTPSessionManager` (or equivalent) constructor signature, and adjust this file accordingly. The shape stays the same: build a `Server`, register tool handlers, mount the HTTP transport at `/mcp`.

- [ ] **Step 8: Run integration test to verify it passes**

Run:
```bash
pytest tests/integration/test_mcp_handshake.py -v
```
Expected: 2 passed.

- [ ] **Step 9: Commit**

```bash
git add src/mcp/server.py src/mcp/session.py tests/unit/test_mcp_session.py tests/integration/test_mcp_handshake.py
git commit -m "feat(mcp): Streamable HTTP MCP server with empty tool list

POST /mcp speaks the JSON-RPC 2.0 MCP protocol via the official
Anthropic SDK. Bearer token parsing is stubbed; real session
resolution lands in Phase 1. tools/list returns []."
```

---

## Task 9: Configure pytest fixtures and shared test infrastructure

**Files:**
- Create: `tests/conftest.py`

- [ ] **Step 1: Implement `tests/conftest.py`**

```python
"""Shared pytest fixtures.

Most tests should consume `app` and `client` from here. The DB-backed
integration tests use the `pg` fixture (from individual test files)
because not every test needs a Postgres container.
"""
import os
from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

# Provide a complete env so `Settings()` validates everywhere.
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
}


@pytest.fixture(autouse=True)
def _test_env() -> AsyncIterator[None]:
    """Inject a complete env into every test, clearing real env to avoid leaks."""
    with patch.dict(os.environ, _TEST_ENV, clear=True):
        yield


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Async HTTP client bound to the FastAPI app (no real DB)."""
    from src.app import create_app

    app = create_app(skip_db_init=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

- [ ] **Step 2: Update existing tests to use shared `client` fixture**

In `tests/integration/test_healthz.py`, remove the local `client` fixture and rely on `conftest.py`:

```python
from httpx import AsyncClient


async def test_healthz_returns_200(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
```

Do the same for `tests/integration/test_mcp_handshake.py` — remove the local `client` fixture, keep only the test functions.

- [ ] **Step 3: Run all unit + integration (non-DB) tests to verify still passing**

Run:
```bash
pytest tests/unit tests/integration -v -m "not integration" 
pytest tests/integration -v -m integration  # DB tests separately
```
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/integration/test_healthz.py tests/integration/test_mcp_handshake.py
git commit -m "test: shared fixtures in conftest.py

_test_env autouse fixture injects a complete env into every test
to avoid Settings validation errors. client fixture provides an
ASGI-bound httpx AsyncClient; healthz and mcp_handshake tests now
consume it instead of redefining locally."
```

---

## Task 10: GitHub Actions CI workflow (lint + test on PR)

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_PASSWORD: postgres
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"

      - name: Lint (ruff)
        run: ruff check src tests

      - name: Format check (ruff)
        run: ruff format --check src tests

      - name: Type check (mypy)
        run: mypy src

      - name: Unit + non-DB integration tests
        run: pytest tests/unit tests/integration -m "not integration" -v

      - name: DB integration tests
        env:
          # testcontainers will use Docker if available; the postgres service
          # above provides a fallback for envs where Docker-in-Docker is awkward.
          TESTCONTAINERS_RYUK_DISABLED: "true"
        run: pytest tests/integration -m integration -v
```

- [ ] **Step 2: Open PR with current changes and verify CI runs**

```bash
git checkout -b chore/initial-ci
git add .github/workflows/ci.yml
git commit -m "ci: lint + type check + tests on PR

Runs ruff (lint + format check), mypy (strict), pytest (unit
non-DB then integration with Postgres service container)."
git push -u origin chore/initial-ci
gh pr create --title "chore: initial CI workflow" --body "Adds GitHub Actions CI."
```

Expected: PR created. CI runs and passes within ~3-5 min. Merge it manually after green.

- [ ] **Step 3: Merge PR and pull main locally**

After merging in GitHub UI:
```bash
git checkout main
git pull
```

---

## Task 11: Provision GCP — Workload Identity Federation + Secret Manager

**Manual cloud-console + gcloud CLI work.** No code, but every step recorded so this is reproducible.

Pre-req: install `gcloud` CLI and run `gcloud auth login`. Set the project:

```bash
gcloud config set project v4-ads-mcp-prod
```

- [ ] **Step 1: Create a service account for Cloud Run**

```bash
gcloud iam service-accounts create v4-ads-mcp-runtime \
    --display-name="V4 Ads MCP runtime"
```

Grant roles needed at runtime:

```bash
PROJECT_ID=v4-ads-mcp-prod
SA_EMAIL=v4-ads-mcp-runtime@${PROJECT_ID}.iam.gserviceaccount.com

for role in \
    roles/secretmanager.secretAccessor \
    roles/logging.logWriter \
    roles/cloudtrace.agent
do
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:${SA_EMAIL}" --role="$role"
done
```

- [ ] **Step 2: Set up Workload Identity Federation for GitHub**

```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")

gcloud iam workload-identity-pools create github-pool \
    --location=global \
    --display-name="GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc github-provider \
    --location=global \
    --workload-identity-pool=github-pool \
    --display-name="GitHub OIDC" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.actor=assertion.actor" \
    --attribute-condition="assertion.repository == 'BadWolf1509/v4-ads-mcp'"
```

Create a deploy service account and bind GitHub repo to impersonate it:

```bash
gcloud iam service-accounts create github-deployer \
    --display-name="GitHub Actions deployer"

DEPLOY_SA=github-deployer@${PROJECT_ID}.iam.gserviceaccount.com

for role in \
    roles/run.admin \
    roles/cloudbuild.builds.editor \
    roles/iam.serviceAccountUser \
    roles/artifactregistry.writer \
    roles/storage.admin
do
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:${DEPLOY_SA}" --role="$role"
done

gcloud iam service-accounts add-iam-policy-binding $DEPLOY_SA \
    --role="roles/iam.workloadIdentityUser" \
    --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/BadWolf1509/v4-ads-mcp"
```

Note the values needed by the deploy workflow:
```bash
echo "WIF provider: projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/providers/github-provider"
echo "Deploy SA:    ${DEPLOY_SA}"
```

Save both in GitHub repo secrets:
- `GCP_WIF_PROVIDER`
- `GCP_DEPLOY_SA`

(Also save: `GCP_PROJECT_ID=v4-ads-mcp-prod`, `GCP_REGION=southamerica-east1`.)

- [ ] **Step 3: Create Secret Manager secrets (placeholders for Phase 0)**

```bash
SECRETS=(
    "session-signing-key"
    "aes-master-key"
    "google-oauth-client-id"
    "google-oauth-client-secret"
    "google-ads-developer-token"
    "google-ads-login-customer-id"
    "supabase-url"
    "supabase-anon-key"
    "supabase-service-key"
    "database-url"
)

for secret in "${SECRETS[@]}"; do
    gcloud secrets create "$secret" --replication-policy="automatic" || true
    # Phase 0 placeholders; real values added before Phase 1.
    echo -n "PLACEHOLDER_PHASE_0" | gcloud secrets versions add "$secret" --data-file=-
    gcloud secrets add-iam-policy-binding "$secret" \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="roles/secretmanager.secretAccessor"
done
```

Then **immediately** populate the real values for Phase 0:

```bash
echo -n "$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
    | gcloud secrets versions add session-signing-key --data-file=-

echo -n "$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
    | gcloud secrets versions add aes-master-key --data-file=-

echo -n "<set in Secret Manager — see 1Password "v4-ads-mcp / google-ads-dev-token">" \
    | gcloud secrets versions add google-ads-developer-token --data-file=-

# Login customer ID (digits only, the V4 MCC CID — fill in)
echo -n "ENTER_MCC_CID_DIGITS_ONLY" \
    | gcloud secrets versions add google-ads-login-customer-id --data-file=-

# Supabase: paste connection string + URL + keys from Supabase dashboard
echo -n "postgresql://..." | gcloud secrets versions add database-url --data-file=-
echo -n "https://YOURREF.supabase.co" | gcloud secrets versions add supabase-url --data-file=-
echo -n "eyJ..." | gcloud secrets versions add supabase-anon-key --data-file=-
echo -n "eyJ..." | gcloud secrets versions add supabase-service-key --data-file=-

# Google OAuth client (create at console.cloud.google.com → APIs → Credentials → OAuth client ID, type "Web app")
# Add authorized redirect URI: https://v4-ads-mcp-<HASH>-rj.a.run.app/oauth/google/callback (you'll get the URL after first deploy in Task 13)
echo -n "client-id.apps.googleusercontent.com" | gcloud secrets versions add google-oauth-client-id --data-file=-
echo -n "GOCSPX-secret" | gcloud secrets versions add google-oauth-client-secret --data-file=-
```

- [ ] **Step 4: Update `docs/operacao/infra-setup.md`** with the actual values created (not the secrets themselves — just notes like "WIF pool created", "10 secrets created", and the GitHub repo secrets that need to exist).

- [ ] **Step 5: Commit doc updates**

```bash
git add docs/operacao/infra-setup.md
git commit -m "docs(ops): record GCP IAM + Secret Manager setup

Workload Identity Federation pool/provider + deploy SA for GitHub
Actions, runtime SA for Cloud Run, 10 Secret Manager entries
populated with Phase 0 values."
```

---

## Task 12: GitHub Actions deploy workflow

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: Write `.github/workflows/deploy.yml`**

```yaml
name: Deploy

on:
  push:
    branches: [main]

concurrency:
  group: deploy-prod
  cancel-in-progress: false

jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write   # required for Workload Identity Federation

    steps:
      - uses: actions/checkout@v4

      - name: Authenticate to GCP
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.GCP_WIF_PROVIDER }}
          service_account: ${{ secrets.GCP_DEPLOY_SA }}

      - name: Set up gcloud
        uses: google-github-actions/setup-gcloud@v2

      - name: Submit build via Buildpacks
        env:
          PROJECT_ID: ${{ secrets.GCP_PROJECT_ID }}
        run: |
          gcloud builds submit \
            --pack image=southamerica-east1-docker.pkg.dev/${PROJECT_ID}/v4-ads-mcp/app:${{ github.sha }} \
            --region=southamerica-east1

      - name: Deploy to Cloud Run
        env:
          PROJECT_ID: ${{ secrets.GCP_PROJECT_ID }}
          REGION: ${{ secrets.GCP_REGION }}
        run: |
          gcloud run deploy v4-ads-mcp \
            --image=southamerica-east1-docker.pkg.dev/${PROJECT_ID}/v4-ads-mcp/app:${{ github.sha }} \
            --region=${REGION} \
            --service-account=v4-ads-mcp-runtime@${PROJECT_ID}.iam.gserviceaccount.com \
            --allow-unauthenticated \
            --min-instances=0 \
            --max-instances=10 \
            --concurrency=80 \
            --cpu=1 \
            --memory=512Mi \
            --timeout=300 \
            --set-env-vars="APP_ENV=production,APP_TIMEZONE=America/Sao_Paulo,LOG_LEVEL=info" \
            --set-secrets="DATABASE_URL=database-url:latest,SESSION_SIGNING_KEY=session-signing-key:latest,AES_MASTER_KEY=aes-master-key:latest,GOOGLE_OAUTH_CLIENT_ID=google-oauth-client-id:latest,GOOGLE_OAUTH_CLIENT_SECRET=google-oauth-client-secret:latest,GOOGLE_ADS_DEVELOPER_TOKEN=google-ads-developer-token:latest,GOOGLE_ADS_LOGIN_CUSTOMER_ID=google-ads-login-customer-id:latest,SUPABASE_URL=supabase-url:latest,SUPABASE_ANON_KEY=supabase-anon-key:latest,SUPABASE_SERVICE_KEY=supabase-service-key:latest"

      - name: Run database migrations
        env:
          PROJECT_ID: ${{ secrets.GCP_PROJECT_ID }}
          REGION: ${{ secrets.GCP_REGION }}
        run: |
          # Use a one-shot Cloud Run Job execution to apply migrations against
          # the same secrets the service uses. (Job created in Task 13.)
          gcloud run jobs execute v4-ads-mcp-migrate --region=${REGION} --wait

      - name: Smoke test
        run: |
          SERVICE_URL=$(gcloud run services describe v4-ads-mcp \
            --region=${{ secrets.GCP_REGION }} --format='value(status.url)')
          echo "Service URL: $SERVICE_URL"
          echo "Probing /healthz..."
          curl -fsS "${SERVICE_URL}/healthz" | grep -q '"status":"ok"'
          echo "Probing /mcp tools/list..."
          curl -fsS -X POST "${SERVICE_URL}/mcp" \
            -H "Content-Type: application/json" \
            -H "Accept: application/json, text/event-stream" \
            -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
            | grep -q '"tools":\[\]'
          echo "Smoke tests passed."

      - name: Rollback on failure
        if: failure()
        env:
          REGION: ${{ secrets.GCP_REGION }}
        run: |
          # Roll service traffic to previous healthy revision.
          PREV=$(gcloud run revisions list --service=v4-ads-mcp --region=${REGION} \
            --format='value(metadata.name)' --limit=2 | tail -n 1)
          if [ -n "$PREV" ]; then
            gcloud run services update-traffic v4-ads-mcp \
              --region=${REGION} --to-revisions="${PREV}=100"
          fi
```

- [ ] **Step 2: Commit and push to a branch (don't merge yet — Task 13 needs to set up the migrate job first)**

```bash
git checkout -b chore/deploy-workflow
git add .github/workflows/deploy.yml
git commit -m "ci: deploy workflow targeting Cloud Run

Buildpacks build → deploy with secrets bound from Secret Manager →
run migrations via one-shot Cloud Run Job → smoke test → automatic
rollback on smoke test failure. Triggered on push to main."
git push -u origin chore/deploy-workflow
```

Don't open a PR yet — Task 13 adds the migration job that this workflow assumes exists.

---

## Task 13: Create one-shot Cloud Run Job for migrations

**Manual gcloud step + tiny code to verify entrypoint works.**

- [ ] **Step 1: Create Artifact Registry repo and migrate Cloud Run Job (one-time)**

```bash
PROJECT_ID=v4-ads-mcp-prod
REGION=southamerica-east1

gcloud artifacts repositories create v4-ads-mcp \
    --repository-format=docker \
    --location=${REGION} \
    --description="V4 Ads MCP container images"

# Build an initial image so the Job creation has something to point at.
# (CI will overwrite with each deploy; this is just to bootstrap.)
gcloud builds submit \
    --pack image=${REGION}-docker.pkg.dev/${PROJECT_ID}/v4-ads-mcp/app:bootstrap

gcloud run jobs create v4-ads-mcp-migrate \
    --image=${REGION}-docker.pkg.dev/${PROJECT_ID}/v4-ads-mcp/app:bootstrap \
    --region=${REGION} \
    --service-account=v4-ads-mcp-runtime@${PROJECT_ID}.iam.gserviceaccount.com \
    --command=python --args="-m,src.db.migrate" \
    --max-retries=1 \
    --task-timeout=300 \
    --set-env-vars="APP_ENV=production,APP_TIMEZONE=America/Sao_Paulo,LOG_LEVEL=info" \
    --set-secrets="DATABASE_URL=database-url:latest,SESSION_SIGNING_KEY=session-signing-key:latest,AES_MASTER_KEY=aes-master-key:latest,GOOGLE_OAUTH_CLIENT_ID=google-oauth-client-id:latest,GOOGLE_OAUTH_CLIENT_SECRET=google-oauth-client-secret:latest,GOOGLE_ADS_DEVELOPER_TOKEN=google-ads-developer-token:latest,GOOGLE_ADS_LOGIN_CUSTOMER_ID=google-ads-login-customer-id:latest,SUPABASE_URL=supabase-url:latest,SUPABASE_ANON_KEY=supabase-anon-key:latest,SUPABASE_SERVICE_KEY=supabase-service-key:latest"
```

- [ ] **Step 2: Update deploy workflow to also update the migrate job's image to the same SHA as the service**

Edit `.github/workflows/deploy.yml`. Add a step **before "Run database migrations"**:

```yaml
      - name: Update migration job image
        env:
          PROJECT_ID: ${{ secrets.GCP_PROJECT_ID }}
          REGION: ${{ secrets.GCP_REGION }}
        run: |
          gcloud run jobs update v4-ads-mcp-migrate \
            --image=southamerica-east1-docker.pkg.dev/${PROJECT_ID}/v4-ads-mcp/app:${{ github.sha }} \
            --region=${REGION}
```

- [ ] **Step 3: Commit, push, open PR, and merge**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: update migration job image alongside service deploy

Each deploy bumps both the Cloud Run service and the one-shot
migrate Job to the same SHA so migrations run against fresh code."

git push
gh pr create --title "ci: deploy workflow + migration job" \
    --body "Phase 0 deploy pipeline. After merge, push to main triggers full deploy."
```

Wait for CI green, then merge via GitHub UI.

- [ ] **Step 4: Watch the deploy workflow run on `main`**

```bash
gh run watch
```

Expected: workflow completes in <8 min (first deploy includes initial Buildpacks pull). Smoke test step passes.

If the smoke test fails:
- Check Cloud Run logs: `gcloud run services logs read v4-ads-mcp --region=southamerica-east1 --limit=50`
- Most common cause: `DATABASE_URL` secret not populated. Fix by re-running step 3 of Task 11 with the real value, then re-trigger deploy: `gh workflow run deploy.yml --ref main`.

- [ ] **Step 5: Note the live service URL**

```bash
gcloud run services describe v4-ads-mcp --region=southamerica-east1 --format='value(status.url)'
```

Update `docs/operacao/infra-setup.md` with the URL.

- [ ] **Step 6: Add the OAuth redirect URI to the Google OAuth client**

In Google Cloud Console → APIs & Services → Credentials → your OAuth client → Authorized redirect URIs: add `<SERVICE_URL>/oauth/google/callback`. Update the secret `google-oauth-client-id` if you had to recreate the client.

- [ ] **Step 7: Commit doc update**

```bash
git add docs/operacao/infra-setup.md
git commit -m "docs(ops): record live Cloud Run URL and OAuth redirect setup"
git push
```

---

## Task 14: End-to-end manual verification (Phase 0 acceptance)

**No code. Final acceptance checklist.**

- [ ] **Step 1: Confirm `/healthz` returns 200 from production URL**

```bash
SERVICE_URL=$(gcloud run services describe v4-ads-mcp --region=southamerica-east1 --format='value(status.url)')
curl -i "${SERVICE_URL}/healthz"
```
Expected: `HTTP/2 200`, body `{"status":"ok","version":"0.1.0"}`.

- [ ] **Step 2: Confirm `/mcp` speaks JSON-RPC handshake**

```bash
curl -i -X POST "${SERVICE_URL}/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"manual","version":"1"}}}'
```
Expected: 200 with `result.protocolVersion` = `2024-11-05`, `result.serverInfo.name` = `v4-ads-mcp`.

- [ ] **Step 3: Confirm migrations applied in Supabase**

In Supabase dashboard → SQL Editor:
```sql
SELECT name, applied_at FROM _migrations ORDER BY name;
SELECT to_regclass('public.audit_log') AS audit_log,
       to_regclass('public.managers') AS managers;
```
Expected: row for `001_initial_schema.sql`, both `to_regclass` results non-null.

- [ ] **Step 4: Connect a real MCP client (Claude Desktop) end-to-end**

Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "v4-ads-dev": {
      "url": "<SERVICE_URL>/mcp"
    }
  }
}
```
Restart Claude Desktop. In a new chat, ask: "What MCP tools do you have available?" Expected: Claude responds confirming the `v4-ads-dev` server is connected and reports zero tools (Phase 1 will add the first one).

- [ ] **Step 5: Confirm a deploy round-trip is <5min**

Trigger a no-op deploy:
```bash
git commit --allow-empty -m "chore: phase 0 acceptance dry run"
git push
gh run watch
```
Expected: workflow finishes in <5min. Note the time in `docs/operacao/infra-setup.md`.

- [ ] **Step 6: Final commit closing Phase 0**

```bash
git checkout -b docs/phase-0-complete
echo "
## Phase 0 sign-off

- [x] Repo + tooling
- [x] DB migrations applied (Supabase)
- [x] CI runs in <3 min
- [x] Deploy runs in <5 min
- [x] /healthz, /mcp, MCP client smoke all green
- [x] Service URL: <FILL IN>
- [x] Date: $(date +%Y-%m-%d)
" >> docs/operacao/infra-setup.md

git add docs/operacao/infra-setup.md
git commit -m "docs(ops): close Phase 0 with acceptance sign-off"
git push -u origin docs/phase-0-complete
gh pr create --title "docs: close Phase 0" --body "Acceptance criteria met."
```

After merge, Phase 0 is **done**. Move to Phase 1 plan.

---

## Self-review notes

**Spec coverage:**
- §1 architecture (monolith FastAPI) — Task 7
- §3.1 component layers (`src/{mcp,db,jobs,...}/`) — Task 1
- §4 schema (8 tables) — Task 5
- §9.1 Cloud Run topology — Tasks 11, 12
- §9.3 CI/CD (Buildpacks + WIF + smoke + rollback) — Tasks 11, 12, 13
- §9.4 structured logging — Task 3
- Phase 0 critério "push em main faz deploy em <5min" — Task 14 step 5
- Phase 0 critério "/mcp responde MCP handshake" — Task 8 + Task 14 step 2

**Out of scope for Phase 0 (deferred to later phases):**
- §5 auth (Phase 1)
- §6 tools other than `list_my_accounts` (Phase 1) and the rest (Phases 2-3)
- §7 governance (Phase 3)
- §8 web panel (Phase 1+)
- §9.2 cron jobs other than migrate (Phase 4 will add audit-rotation, account-resync, etc.)

**Type/name consistency:**
- `Settings` class used consistently across config and conftest.
- `init_pool` / `close_pool` / `get_pool` API consistent across `src/db/connection.py` and consumers.
- `create_app(skip_db_init: bool)` signature consistent across `src/app.py` and tests.
- MCP server name `v4-ads-mcp` matches across server module and smoke test assertions.
