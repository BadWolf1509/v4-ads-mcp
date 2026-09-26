> **Relatório bruto** de um dos 5 agentes da varredura de 21/09 — recorte: camada de banco e migrations.
> Recuperado do transcript da sessão em 25/09 e reproduzido **sem edição**. Os status
> ("CONFIRMADO", "PLAUSÍVEL") são do agente, não verificação nossa; o destino de cada
> achado está no [índice](README.md).

---

I have what I need. Here's the audit.

## Measurements first

| | |
|---|---|
| `src/db/` | 12 files, 2622 lines — 10 repository modules, `connection.py` (112), `migrate.py` (67), 10 migrations (`001`–`010`) |
| `conn.cursor(...)` | **1** in the whole project (`audit_log.py:181`) — correctly inside `conn.transaction()` |
| SQL JOINs in `src/db` | 17 JOIN clauses across 11 queries in 5 of the 10 repos |
| `pool.acquire()` raw vs `run_with_reconnect` | 103 vs 35 across `src/` |
| Postgres `SELECT` with `LIMIT` and no `ORDER BY` | **0** (AST scan over all of `src/`; the 13 hits were GAQL, not Postgres) |
| `finally:` blocks | 16, none in `src/db/repositories/`; every one doing bookkeeping I/O uses `best_effort` |

**Classes 1, 2, 5 came back clean, verified not assumed.** F58 is guarded structurally over all of `src/` by `test_structural_guards.py::test_cursor_usage_is_wrapped_in_transaction`, with bite tests. F59: every JOIN query qualifies its columns; the `al.*`/`a.*` expansions have no name collision with the aliased extras (checked against `001_initial_schema.sql`). F83: no bookkeeping I/O in `finally` inside `src/db/`.

---

## Ranked findings

### 1. Audit CSV export fails OPEN — truncated file, HTTP 200 — CONFIRMED
`src/db/repositories/audit_log.py:173-181`, consumed by `src/web/routes/audit.py:105-135` and `src/web/routes/admin_audit.py:108-142`

The header row is yielded at line 175, **before** `async with conn.transaction():` opens at line 180. By then Starlette has committed `200` + `Content-Disposition`. Anything that raises afterward — a stale pooled connection (asyncpg has no pre-ping; F76/F77 was measured 6× in production), pool exhaustion, the per-statement `command_timeout=30` on a `FETCH`, a Cloud Run edge timeout — produces a **syntactically valid CSV with the header and fewer rows, possibly zero**. Nothing distinguishes that from "no events matched the filter."

This is the brief's own concern realized: the audit log is the last line of defense, and its export can under-report silently. It is also why the reconnect guard exempts these two sites (`test_rotas_usam_run_with_reconnect.py:57-67`) — the exemption is right (a retry would re-emit delivered bytes), but nothing was put in its place. A terminating sentinel row, or buffering the first data row before yielding the header, would make truncation detectable.

### 2. Raw `pool.acquire()` on idempotent hot-path reads, outside the one structural guard — CONFIRMED (class 3)
The guard at `tests/unit/test_rotas_usam_run_with_reconnect.py:75` sets `_ROTAS = h.SRC / "web" / "routes"`. It is green **because it only looks there**. Running the project's own matcher over the rest of `src/` finds:

- `src/auth/oauth.py:184` and `src/auth/oauth.py:281` — the **login path**. This is literally the scenario `src/web/deps.py:57-59` names as its own reason for existing ("o primeiro acesso da manhã vira 500").
- `src/mcp/tools/list_my_accounts.py:39`, `get_my_audit_log.py:80`, `get_my_rate_limit_status.py:60`, `meta_list_my_ad_accounts.py:35`, `meta_get_account_overview.py:113`, `meta_get_performance_breakdown.py:126`, `_meta_performance.py:97` — all pure single-statement reads, all verified by reading the blocks.

The companion `tests/unit/test_hot_reads_reconnect.py` is an **enumeration of 6 named call sites**, not a structural property — the "guard que enumera em vez de afirmar a propriedade" mode. I excluded `src/jobs/` (batch, not hot-path; and `_audit.py:35` is a matcher false positive — it writes, under `best_effort`).

### 3. `migrate.py` has no advisory lock — PLAUSIBLE (classes 7/8)
`src/db/migrate.py:36-53`. `_list_pending` is computed outside any lock; each migration then gets its own transaction. Two concurrent `v4-ads-mcp-migrate` executions (overlapping deploys — this repo merges many PRs/day — or Cloud Run Jobs' default `maxRetries: 3` re-running a task) both see the same pending list and both attempt the same DDL. Postgres DDL is transactional, so there is no half-applied schema; the loser aborts on the `_migrations` PK and can fail the deploy step, which `rollback-on-failure` then acts on. `grep -rni "pg_advisory"` over `src/` and `.github/` returns nothing. The market pattern is `pg_advisory_lock` — Flyway, Liquibase, Alembic and Rails all take one.

Related: `004_audit_log_provider_id.sql` is the only non-idempotent DDL (`RENAME COLUMN`, no guard); `010`'s own comment states the convention it breaks.

**What I could not verify:** the configured `maxRetries`/parallelism on the job — that needs gcloud, which your constraints exclude. Reachability is argued from the Cloud Run default, not measured.

### 4. Unbounded `days` + unbounded result set on both CSV exports — CONFIRMED
`src/web/routes/audit.py:112` and `src/web/routes/admin_audit.py:116` declare `days: int = 7` with no `Query(le=...)`; `export_csv_rows` has no `LIMIT`. `?days=100000` streams the whole `audit_log` while pinning 1 of `db_pool_max_size=5` (`src/config.py:33`) and holding a read transaction open for the entire download. The unboundedness is confirmed; pool starvation as a consequence is plausible, not measured.

Adjacent: `export_csv_rows(manager_id: UUID | None = None)` at line 124 — the default means *no manager filter*, i.e. every gestor's rows. Both call sites pass it explicitly and the admin one checks `_require_admin` first, so it is correct today — but the default fails open.

### 5. Meta `revoke` missing `AND revoked_at IS NULL` — asymmetric with its Google twin — PLAUSIBLE-latent (class 7)
`src/db/repositories/manager_meta_account_access.py:108-117` vs `src/db/repositories/manager_account_access.py:138-147`.

The toggle route reads `exists` **outside** the transaction (`src/web/routes/admin_access.py:119-131`), so two concurrent or duplicated POSTs both see `exists=1` and both call `revoke()`. Google's is a no-op the second time; Meta's re-stamps `revoked_at = now()` and rewrites `revoked_reason`.

Today the only caller passes the default `'manual'`, so the damage is a moved timestamp — cosmetic, and I could not construct a currently-reachable path that loses data. The latent risk is what makes it worth naming: `restore_for_account` (line 158) filters on `revoked_reason = PARTNERSHIP_ENDED_REASON`, so any future caller passing a different reason over a churn-revoked row makes it **permanently unrestorable, silently**. This is the exact shape of F128 — a clause that stayed on one side only.

### 6. `get_active_for_manager` — `LIMIT 1` over a non-unique sort key — PLAUSIBLE, low (class 6)
`src/db/repositories/google_oauth_connections.py:67-75` and `meta_oauth_connections.py:165-173`: `ORDER BY connected_at DESC LIMIT 1`. `connected_at` is `DEFAULT now()` (transaction time) and the UNIQUE is `(manager_id, google_email)` / `(manager_id, fb_user_id)` — one manager can hold several live rows, and nothing breaks the tie. Same shape as F98/F88, which was fixed in `audit_log` by appending `, id DESC`; that fix was not carried here. A tie requires two rows written in the same transaction, so it is unlikely — but the consequence is that the **credential used for Google Ads API calls flips non-deterministically between requests**.

### 7. `IndexError` at `limit=0` in both keyset pagers — CONFIRMED, unreachable today
`src/db/repositories/audit_log.py:374` and `:469`: `page = fetched[:limit]` then `page[-1]` guarded only by `len(fetched) &gt; limit`. With `limit=0` and ≥1 matching row, `page` is empty. Both routes hardcode `limit = 50`. Latent landmine in a public repo function with a default.

### 8. Smaller items, all low
- `src/governance/dry_run.py:154` — `row["expires_at"] &lt; datetime.now(UTC)` compares a **DB-generated** timestamp against the app process clock. Cloud Run and Supabase are different hosts; skew shifts the effective TTL. Immaterial against 10 min, but the predicate could live in the SQL `WHERE`. (The token consume itself is correct: `SELECT ... FOR UPDATE` + `UPDATE` in one transaction — race-safe.)
- `src/governance/rate_limit.py:227` — `date.today()` (naive local) where the Google side uses `datetime.now(UTC).date()` (`rate_limit.py:37-39`). Agrees in production because Cloud Run is UTC. Also, `increment_calls` and `update_throttle` at lines 236-250 share a connection but **not a transaction**.
- `src/governance/rate_limit.py:118-128` — `record_actual` has no upsert. A call spanning UTC midnight reconciles against a row that does not exist → 0 rows → the correction is silently dropped.

### 9. F179 located precisely — still open, and the repo side is not the bug
`src/db/repositories/managers.py:140-149` — `delete_invite` correctly returns `bool`. `src/web/routes/admin_invites.py:110-119` **discards the return** and writes `admin_invite_cancel` unconditionally, inside the same transaction. Cancelling a non-`invited` row deletes 0 rows and still produces an audit line asserting the cancel happened. The fix is one `if` at the caller; the repository already exposes the signal.

---

## What I did NOT examine

- **I never connected to a database.** Nothing here is confirmed against live data or a real `EXPLAIN` — every claim is from reading code. The bug class your brief says escapes local verification (SQL/JOIN/cursor/transaction) is exactly the class I could only verify by reading.
- I did not run the integration suite or `check_pre_push.py`, so none of this SQL was executed.
- Cloud Run job settings for `v4-ads-mcp-migrate` (`maxRetries`, parallelism) — needs gcloud. Finding 3's reachability is argued from the default, not measured.
- The 8 pure-read raw acquires in `src/jobs/` — batch paths, not hot-path, and at least one is a matcher false positive. I excluded them from finding 2 rather than counting them.
- `src/scripts/admin.py` (6 raw acquires, CLI not request path) and `src/jobs/backup.py`'s restore path.
- Index coverage and query plans. Migration 010 added the two indices the audit listings need; I did **not** check whether the keyset queries' `LEFT JOIN google_ads_accounts` defeats `idx_audit_occurred_at` and forces a sort.
- `build_plan` in `src/google_ads/reconcile.py` and `src/meta_ads/reconcile.py` — I read only the repository functions they call.
- `src/web/routes/accounts.py` and `sessions.py` beyond the grep; `src/auth/meta_oauth.py`'s 4 raw acquires.
