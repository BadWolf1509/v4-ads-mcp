# Schema, migrations e datas

> Pegadinhas de schema, migrations append-only, janelas de data. Leia ao mexer em query, repository ou migration.
>
> Extraído do `CLAUDE.md` em 2026-08-19: convenção é estável e específica de
> área, então carregá-la em toda sessão era imposto de contexto. As regras
> curtas (o que faz parar) seguem no `Don't do` do `CLAUDE.md`; aqui fica o
> **porquê**.
>
> Taxonomia completa dos bugs: [`findings-catalog.md`](../operacao/findings-catalog.md).

---

### Schema gotchas (commonly-tripped)


- `audit_log.id` é `BIGSERIAL` (int8), NÃO UUID. `RETURNING id`.
- `audit_log.platform`: `Literal["google","meta"]`, default `"google"` — Meta tools passam explícito.
- `audit_log.provider_request_id` (renomeado de `google_request_id` em M.2a): genérico.
- `managers.id` UUID sem DEFAULT — caller provê `uuid4()`. `managers.status`: `'invited'|'active'|'inactive'` (+ `is_active` bool).
- `mcp_sessions.id` UUID DEFAULT `gen_random_uuid()`.
- `rate_counters` tem `operations_used` (NÃO `used_today`), PK `(developer_token_id, date)`.
- `pending_confirmations.token` (NÃO `id`) é PK; `payload` é jsonb.
- **JOIN + coluna duplicada (F59):** `audit_log` E `managers` têm coluna `status` → qualifique TODA clause com alias (`al.status`) em queries com JOIN.
- **asyncpg cursor exige transação (F58):** `async for row in conn.cursor(...)` PRECISA de `async with conn.transaction():`.

### Date range conventions (post-3b.20)


Reads + `bulk_pause_by_query`: **preset** (`date_range: str` com `type:"string"` + `enum`) ou **custom** (`start_date`+`end_date`, `^\d{4}-\d{2}-\d{2}$`, override). Resolve via `resolve_date_window` em `src/google_ads/queries/_common.py` (F1: schema sem `type` → Claude serializa dict como string literal). GAQL `BETWEEN end_date` é midnight-exclusive (F46) — `_format_change_date_between` aplica `+1 day`.

### Migrations


`src/db/migrations/NNN_name.sql`, append-only (hook PreToolUse bloqueia editar migration commitada). **Sempre atualize a lista hardcoded em `tests/integration/test_migrations.py`** ao adicionar migration (M.1+M.2a tropeçaram). Manual apply (sem psql no Windows): `python -c` + asyncpg + `DATABASE_URL` do Secret Manager.
