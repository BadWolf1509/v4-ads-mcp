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
- **JOIN + coluna duplicada (F59):** `audit_log` E `managers` têm coluna `status` → qualifique TODA clause com alias (`al.status`) em queries com JOIN — nunca deixe coluna sem alias nesse cenário: o nome ambíguo só estoura em runtime, quando as duas tabelas de fato colidem no nome da coluna.
- **asyncpg cursor exige transação (F58):** `async for row in conn.cursor(...)` PRECISA de `async with conn.transaction():` — nunca use `conn.cursor(...)` fora dessa transação explícita.

### Date range conventions (post-3b.20)


Reads + `bulk_pause_by_query`: **preset** (`date_range: str` com `type:"string"` + `enum`) ou **custom** (`start_date`+`end_date`, `^\d{4}-\d{2}-\d{2}$`, override). Resolve via `resolve_date_window` em `src/google_ads/queries/_common.py` (F1: schema sem `type` → Claude serializa dict como string literal). GAQL `BETWEEN end_date` é midnight-exclusive (F46) — `_format_change_date_between` aplica `+1 day`.

**`hoje` é sempre da conta, nunca do servidor (F141).** Nunca leia o relógio do servidor (`datetime.now`/`date.today`) pra decidir data numa tool Google: `hoje` é `await resolve_account_today(customer_id)`, resolvido no fuso da conta UMA vez por request e passado a tudo — janela, clamp, sonda, freshness. As contas do MCC são todas UTC−3/−4 (26 contas em 04/09, seis fusos — a contagem muda, a regra não); em UTC puro todo preset deslizava um dia inteiro entre 21h e meia-noite locais. A mesma exigência vale pro lado escrita: mutate que grava timestamp no Google nunca hardcoda fuso ou offset (`-03:00`, `_BRT`) — o fuso é `await resolve_account_zone(customer_id)` já no dry-run, guardado no payload pendente e mostrado no preview, e sem fuso resolvido a tool recusa (em escrita, offset chutado é corrupção de dado, não ruído — F146). Contraste deliberado com o parágrafo acima, confirmado no código: em leitura, `account_today` (`src/clock.py`) cai em UTC com warning quando o fuso está ausente ou é desconhecido — dado errado por até um dia é tolerável, recusar a tool não seria melhor. Em escrita, `resolve_account_zone` devolve `None` em vez de cair em UTC, e é o chamador quem decide recusar — porque aqui, ao contrário da leitura, um offset chutado não é ruído, é corrupção do timestamp gravado no Google.

**As duas são guardadas pelo mesmo guard AST, `test_no_server_clock_in_google_tools.py`.** Ele varre `src/mcp/tools/`, `src/jobs/` e os primitivos de resolução de conta, e reprova qualquer chamada direta às cinco formas de `_RELOGIO` (`datetime.now`, `datetime.today`, `datetime.utcnow`, `date.today`, `time.time` — a lista vive nessa constante, no próprio guard; não a reenumere de cabeça) fora dos quatro leitores legítimos (os dois `account_clock.py` — Google e Meta — e os dois jobs de resync), que por sua vez só podem ler o relógio como default injetável (`now if now is not None else datetime.now(UTC)`). O próprio guard cita o F146 pelo nome na exceção documentada de `import_offline_conversions.py`. É o que torna seguro falar das duas regras aqui em vez de só no `CLAUDE.md`: o CI reprova a violação mesmo que ninguém leia esta página — não é recomendação, é mecanismo.

### `change_event`: remoção de entidade com `status` é UPDATE, não REMOVE


Campanha, grupo de anúncios, keyword e anúncio têm campo `status` — no Google, remover uma dessas entidades é um evento `UPDATE` de `status → REMOVED`, nunca um `REMOVE`. `REMOVE` só aparece pra vínculos, critérios e orçamentos, que não têm `status`. Nunca procure `REMOVE` no `change_event` pra detectar remoção de entidade com `status`: a busca vai vir vazia. Medido por `aggregate_by` em 141 eventos (F145). O predicado de flag de mudança estrutural olha `new_resource.<entidade>.status`, chaveado pelo `resource_type` — não pela presença do atributo, que em proto-plus existe sempre.

### Migrations


`src/db/migrations/NNN_name.sql`, append-only (hook PreToolUse bloqueia editar migration commitada). **Sempre atualize a lista hardcoded em `tests/integration/test_migrations.py`** ao adicionar migration (M.1+M.2a tropeçaram). Manual apply (sem psql no Windows): `python -c` + asyncpg + `DATABASE_URL` do Secret Manager.
