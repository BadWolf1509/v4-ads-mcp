"""Append-only audit log writes."""

import csv
import io
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import asyncpg
import structlog

log = structlog.get_logger(__name__)

# Excel/Sheets treat a leading =, +, -, @ (or tab) as a formula trigger — a
# manager_email, operation, or error_message that happens to start with one of
# these (e.g. a keyword/campaign name echoed into an error string) would
# execute as a formula when the CSV is opened. Prefixing with a single quote
# forces Excel to treat the cell as plain text (standard CSV-injection mitigation).
_CSV_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t")


def _csv_safe(value: str) -> str:
    """Prefix `'` if value starts with a formula-trigger char, else return as-is."""
    if value.startswith(_CSV_FORMULA_TRIGGERS):
        return "'" + value
    return value


# Fonte ÚNICA do nome da conta em toda leitura do audit (página do gestor, detalhe,
# admin, dashboard): o JOIN e a coluna, com alias fixo `gaa`. Quem lê tem de ter
# `audit_log` com alias `al`. `google_ads_accounts.customer_id` é PK, então o
# JOIN não multiplica linha.
_SQL_NOME_DA_CONTA = "LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id"
_SQL_COLUNA_NOME_DA_CONTA = "gaa.descriptive_name AS account_name"


class _Filtros:
    """Monta o WHERE de uma consulta do audit com `$n` numerados em ordem.

    Cada `add` troca o `{}` do fragmento pelo próximo `$n` e guarda o valor em
    `params`, então a numeração nunca sai do compasso dos valores — o descuido
    que o `idx += 1` à mão deixava aberto em cada construtor. A ordem dos
    `add` é a ordem dos filtros no SQL e dos `params`.
    """

    def __init__(self) -> None:
        self._fragmentos: list[str] = []
        self.params: list[Any] = []

    def _proximo(self) -> int:
        return len(self.params) + 1

    def add(self, fragmento: str, valor: Any) -> None:
        self._fragmentos.append(fragmento.replace("{}", f"${self._proximo()}"))
        self.params.append(valor)

    def add_cursor(self, occurred_at: datetime | None, cursor_id: int | None) -> None:
        """Seek keyset `(occurred_at, id) < cursor`; sem cursor (ambos None) não filtra."""
        n = self._proximo()
        self._fragmentos.append(
            f"(${n}::timestamptz IS NULL OR (al.occurred_at, al.id) < (${n}, ${n + 1}))"
        )
        self.params.extend([occurred_at, cursor_id])

    def add_limit(self, limite: int) -> str:
        """Guarda o LIMIT como último param e devolve o `$n` dele para o SQL."""
        n = self._proximo()
        self.params.append(limite)
        return f"${n}"

    @property
    def sql(self) -> str:
        return " AND ".join(self._fragmentos) or "TRUE"


async def record(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID | None,
    session_id: UUID | None,
    customer_id: str | None,
    action_type: str,  # 'mutate' | 'read' | 'auth' | 'system'
    operation: str,
    target_count: int | None = None,
    params_summary: dict[str, Any] | None = None,
    provider_request_id: str | None = None,
    status: str = "success",  # 'success' | 'error' | 'denied'
    error_message: str | None = None,
    duration_ms: int | None = None,
    platform: Literal["google", "meta"] = "google",
    dry_run: bool | None = None,
    had_effect: bool | None = None,
) -> int:
    """Insert a row into audit_log; returns the new row id.

    platform: 'google' (default, preserves existing callers) | 'meta'.
    dry_run: True marca preview que mintou token sem aplicar (F148). None nos
        demais caminhos — a coluna e nullable justamente para nao afirmar nada
        sobre as linhas anteriores ao fix.
    had_effect: true = a escrita afetou linha; false = passou sem efeito; None
        nos caminhos que nao medem. Nullable pelo mesmo motivo do `dry_run`
        (F148): NULL nao afirma nada sobre as linhas anteriores ao fix.
    """
    import json

    row = await conn.fetchrow(
        """
        INSERT INTO audit_log (
            manager_id, session_id, customer_id,
            action_type, operation, target_count,
            params_summary, provider_request_id, status,
            error_message, duration_ms, platform, dry_run, had_effect
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11, $12, $13, $14)
        RETURNING id
        """,
        manager_id,
        session_id,
        customer_id,
        action_type,
        operation,
        target_count,
        json.dumps(params_summary) if params_summary is not None else None,
        provider_request_id,
        status,
        error_message,
        duration_ms,
        platform,
        dry_run,
        had_effect,
    )
    assert row is not None
    return int(row["id"])


async def get_by_id(
    conn: asyncpg.Connection,
    *,
    audit_id: int,
    manager_id: UUID | None,
) -> dict[str, Any] | None:
    """Fetch a single audit event by its BIGSERIAL id.

    If manager_id is provided, scoped to that gestor (returns None if event belongs to another).
    If manager_id is None (admin context), returns any event by id.
    """
    filtros = _Filtros()
    filtros.add("al.id = {}", audit_id)
    if manager_id is not None:
        filtros.add("al.manager_id = {}", manager_id)
    row = await conn.fetchrow(
        f"""SELECT al.*, m.email AS manager_email,
                   s.label AS session_label,
                   {_SQL_COLUNA_NOME_DA_CONTA}
            FROM audit_log al
            LEFT JOIN managers m ON m.id = al.manager_id
            LEFT JOIN mcp_sessions s ON s.id = al.session_id
            {_SQL_NOME_DA_CONTA}
            WHERE {filtros.sql}""",
        *filtros.params,
    )
    return dict(row) if row else None


# Spec 2026-09-28 §3.3.2: teto de linhas do export CSV. Medido em 28/09: 5.795 linhas
# em 365 dias (o teto de `days`), então 50.000 dá folga de anos e não corta nada hoje.
_TETO_LINHAS_EXPORT = 50_000


async def export_csv_rows(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID | None,
    customer_id: str | None = None,
    action_type: str | None = None,
    status: str | None = None,
    days: int = 7,
) -> AsyncIterator[str]:
    """Yield CSV lines (header + data) for streaming response.

    `manager_id` nao tem default: `None` e o export de TODOS os gestores (admin), e
    esse escopo so vale escrito por quem chama, nunca por esquecimento.
    """
    # All WHERE clauses qualified with the `al` alias: the SELECT joins `managers m`,
    # which ALSO has a `status` column → unqualified `status` is ambiguous (asyncpg
    # AmbiguousColumnError). Qualify everything for safety/consistency with the SELECT.
    filtros = _Filtros()
    filtros.add("al.occurred_at > now() - ({} || ' days')::interval", str(days))
    if manager_id is not None:
        filtros.add("al.manager_id = {}", manager_id)
    if customer_id:
        filtros.add("al.customer_id = {}", customer_id)
    if action_type and action_type != "all":
        filtros.add("al.action_type = {}", action_type)
    if status and status != "all":
        filtros.add("al.status = {}", status)
    teto = _TETO_LINHAS_EXPORT
    # F98: pede teto + 1 — a linha extra é o que revela que havia mais.
    limite = filtros.add_limit(teto + 1)
    params = filtros.params
    sql = f"""SELECT al.occurred_at, m.email, al.operation, al.customer_id,
                     al.action_type, al.status, al.target_count, al.duration_ms,
                     al.error_message, al.provider_request_id
              FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id
              WHERE {filtros.sql}
              ORDER BY al.occurred_at DESC, al.id DESC
              LIMIT {limite}"""

    # Header
    header = [
        "occurred_at",
        "manager_email",
        "operation",
        "customer_id",
        "action_type",
        "status",
        "target_count",
        "duration_ms",
        "error_message",
        "provider_request_id",
    ]
    buf = io.StringIO()
    csv.writer(buf).writerow(header)
    yield buf.getvalue()

    # O cliente ja recebeu 200 OK + Content-Disposition quando a primeira linha
    # saiu (StreamingResponse) — nao ha status a corrigir se o cursor quebrar
    # no meio. A unica honestidade possivel e MARCAR o arquivo: a linha-
    # sentinela de sucesso so existe para que a AUSENCIA dela, sob exceçao,
    # signifique "incompleto" — fail-closed por construçao (ver brief da Task 6).
    lidas = 0
    cortado = False
    try:
        # asyncpg server-side cursors MUST run inside an explicit transaction.
        # (Pre-existing bug surfaced by the first test to actually iterate this
        # generator: NoActiveSQLTransactionError without this wrapper.)
        async with conn.transaction():
            async for row in conn.cursor(sql, *params):
                if lidas == teto:
                    cortado = True
                    break
                buf = io.StringIO()
                csv.writer(buf).writerow(
                    [
                        row["occurred_at"].isoformat() if row["occurred_at"] else "",
                        _csv_safe(row["email"] or ""),
                        _csv_safe(row["operation"] or ""),
                        row["customer_id"] or "",
                        row["action_type"] or "",
                        row["status"] or "",
                        row["target_count"] if row["target_count"] is not None else "",
                        row["duration_ms"] if row["duration_ms"] is not None else "",
                        _csv_safe(row["error_message"] or ""),
                        _csv_safe(row["provider_request_id"] or ""),
                    ]
                )
                lidas += 1
                yield buf.getvalue()
    except Exception as e:
        buf = io.StringIO()
        # Item 5 (revisao final): `{e}` cru vazava infra do servidor pro
        # arquivo — probe real: mensagem de erro do asyncpg trazia host,
        # porta e usuario do Postgres, num CSV baixavel por gestor nao-admin.
        # O TIPO da excecao basta pra sentinela dizer "algo quebrou e onde
        # parou"; o `raise` abaixo preserva a excecao original (com o texto
        # completo) pro traceback do servidor — o detalhe nao some, so nao
        # vai pro arquivo que sai da porta.
        csv.writer(buf).writerow(
            [f"# v4-ads-mcp: EXPORT INCOMPLETO apos {lidas} linhas — {type(e).__name__}"]
        )
        yield buf.getvalue()
        raise
    buf = io.StringIO()
    if cortado:
        log.warning("audit_export_cortado", teto=teto, days=days)
        csv.writer(buf).writerow(
            [f"# v4-ads-mcp: EXPORT CORTADO em {teto} linhas — reduza o periodo (days={days})"]
        )
    else:
        csv.writer(buf).writerow([f"# v4-ads-mcp: export completo, {lidas} linhas"])
    yield buf.getvalue()


async def list_for_manager(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    days: int = 7,
    limit: int = 100,
    customer_id: str | None = None,
    action_type: str | None = None,
) -> list[dict[str, Any]]:
    """Paginated list of audit_log rows scoped to a manager.

    Filters (all optional except manager_id):
    - days: time window (default 7)
    - limit: row cap (default 100, max enforced by caller schema)
    - customer_id: filter by account
    - action_type: filter by 'mutate'/'read'/'auth'/'system'; None or 'all' → no filter

    Returns rows ORDER BY occurred_at DESC, id DESC — o desempate por `id` nao
    e enfeite: `occurred_at` e `DEFAULT now()`, hora de TRANSACAO no Postgres,
    entao linhas gravadas na mesma transacao empatam por construcao e o corte
    do `LIMIT` cairia num ponto arbitrario do empate (medido: com 5 linhas
    empatadas e `limit=3` vinham as 3 MAIS ANTIGAS). F98/F88.

    Subset of columns (omits params_summary to keep response compact; use
    get_by_id() for full detail).
    """
    filtros = _Filtros()
    filtros.add("manager_id = {}", manager_id)
    filtros.add("occurred_at > now() - ({} || ' days')::interval", str(days))
    if customer_id:
        filtros.add("customer_id = {}", customer_id)
    if action_type and action_type != "all":
        filtros.add("action_type = {}", action_type)
    limite = filtros.add_limit(limit)
    sql = f"""SELECT id, occurred_at, operation, customer_id, action_type,
                     target_count, status, duration_ms, provider_request_id,
                     error_message, platform, dry_run
              FROM audit_log
              WHERE {filtros.sql}
              ORDER BY occurred_at DESC, id DESC
              LIMIT {limite}"""
    rows = await conn.fetch(sql, *filtros.params)
    return [
        {
            "id": int(r["id"]),
            "occurred_at": r["occurred_at"].isoformat() if r["occurred_at"] else None,
            "operation": r["operation"],
            "customer_id": r["customer_id"],
            "action_type": r["action_type"],
            "target_count": int(r["target_count"]) if r["target_count"] is not None else None,
            "status": r["status"],
            "duration_ms": int(r["duration_ms"]) if r["duration_ms"] is not None else None,
            "provider_request_id": r["provider_request_id"],
            "error_message": r["error_message"],
            "platform": r["platform"],
            # F148: sem esta chave, uma mutacao APLICADA e um preview sao
            # indistinguiveis pela tool — os dois gravam action_type "mutate" com
            # o target_count planejado. O unico diferenciador acidental seria
            # duration_ms NULL, que nao e sinal desenhado e nem e exclusivo
            # (admin_access_grant tambem grava mutate com duracao nula).
            "dry_run": r["dry_run"],
        }
        for r in rows
    ]


def _build_manager_page_sql(
    *,
    manager_id: UUID,
    days: int,
    customer_id: str | None,
    action_type: str | None,
    status: str | None,
    cursor_occurred_at: datetime | None,
    cursor_id: int | None,
    limit: int,
) -> tuple[str, list[Any]]:
    """Builds the parameterized SELECT that `list_page_for_manager` runs.

    Split out (Task 7, rodada 1, Achado 1) so a test can `EXPLAIN` the query
    the route ACTUALLY executes — join with `google_ads_accounts` included —
    instead of a hand-copied approximation that can silently drift from this
    function. `list_page_for_manager` is the only other caller; there is no
    second copy of this SQL to diverge from it.
    """
    filtros = _Filtros()
    filtros.add("al.manager_id = {}", manager_id)
    filtros.add("al.occurred_at > now() - ({} || ' days')::interval", str(days))
    if action_type and action_type != "all":
        filtros.add("al.action_type = {}", action_type)
    if customer_id:
        filtros.add("al.customer_id = {}", customer_id)
    if status and status != "all":
        filtros.add("al.status = {}", status)
    filtros.add_cursor(cursor_occurred_at, cursor_id)
    limite = filtros.add_limit(limit + 1)

    sql = f"""SELECT al.*, {_SQL_COLUNA_NOME_DA_CONTA}
              FROM audit_log al {_SQL_NOME_DA_CONTA}
              WHERE {filtros.sql}
              ORDER BY al.occurred_at DESC, al.id DESC
              LIMIT {limite}"""
    return sql, filtros.params


def _recusa_limite_menor_que_um(limit: int) -> None:
    """Spec 2026-09-28 §3.2.3: com `limit=0`, a página fica vazia, a linha sentinela
    diz "tem mais" e o `page[-1]` do cursor estoura `IndexError`."""
    if limit < 1:
        raise ValueError(f"limit tem de ser >= 1, veio {limit}")


async def list_page_for_manager(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    days: int = 7,
    customer_id: str | None = None,
    action_type: str | None = None,
    status: str | None = None,
    cursor_occurred_at: datetime | None = None,
    cursor_id: int | None = None,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], tuple[datetime, int] | None]:
    """Keyset ("seek") page of one manager's own audit rows, for `GET /audit`.

    Task 7 (PR 5): replaces `LIMIT/OFFSET`. Frente 6 already shipped the
    stable tie-break this seeks on (`ORDER BY occurred_at DESC, id DESC`,
    covered end-to-end by migration 010's `idx_audit_occurred_at`). `OFFSET n`
    makes Postgres scan-and-discard the first n rows on every page — cost
    that grows with depth — and it SLIDES when a row is inserted mid-
    navigation: page 2 silently repeats whatever page 1 already showed,
    because the n-th row from the top moved. Seeking off `(occurred_at, id)
    < (cursor_occurred_at, cursor_id)` anchors on the last row the caller
    actually saw, so it neither scans the skipped rows nor slides.

    cursor_occurred_at/cursor_id: the `(occurred_at, id)` of the last row on
    the PREVIOUS page, or both None for the first page. Pass both or neither —
    a lone cursor_id can't anchor a tuple seek and is treated as "no cursor"
    by the caller (the two route call-sites normalize this before calling in).

    Returns (rows, next_cursor). `rows` has at most `limit` items, newest
    first. `next_cursor` is `(occurred_at, id)` of the last row, to pass back
    for the next page — or None when this page reached the end. Detecting
    "reached the end" without a separate COUNT(*) needs a sentinel row: this
    asks the DB for `limit + 1` and trims to `limit`, the same peek-ahead
    idiom `aplicar_limite()` (`src/mcp/tools/_common.py`) already uses for
    `ad_schedule`/`overview`/`recommendations`/`get_my_audit_log` — inlined
    here rather than imported, since a repository must not depend on the MCP
    tools layer. The SQL itself lives in `_build_manager_page_sql` — see its
    docstring for why it isn't inlined here anymore.
    """
    _recusa_limite_menor_que_um(limit)
    sql, params = _build_manager_page_sql(
        manager_id=manager_id,
        days=days,
        customer_id=customer_id,
        action_type=action_type,
        status=status,
        cursor_occurred_at=cursor_occurred_at,
        cursor_id=cursor_id,
        limit=limit,
    )
    fetched = await conn.fetch(sql, *params)
    page = fetched[:limit]
    next_cursor = (page[-1]["occurred_at"], int(page[-1]["id"])) if len(fetched) > limit else None
    return [dict(r) for r in page], next_cursor


def _build_admin_page_sql(
    *,
    days: int,
    manager_id: UUID | None,
    customer_id: str | None,
    action_type: str | None,
    status: str | None,
    cursor_occurred_at: datetime | None,
    cursor_id: int | None,
    limit: int,
) -> tuple[str, list[Any]]:
    """Builds the parameterized SELECT that `list_page_admin` runs.

    Split out for the same reason as `_build_manager_page_sql` (Task 7,
    rodada 1, Achado 1) — see its docstring. `list_page_admin` is the only
    other caller.
    """
    filtros = _Filtros()
    filtros.add("al.occurred_at > now() - ({} || ' days')::interval", str(days))
    if manager_id:
        filtros.add("al.manager_id = {}", manager_id)
    if customer_id:
        filtros.add("al.customer_id = {}", customer_id)
    if action_type and action_type != "all":
        filtros.add("al.action_type = {}", action_type)
    if status and status != "all":
        filtros.add("al.status = {}", status)
    filtros.add_cursor(cursor_occurred_at, cursor_id)
    limite = filtros.add_limit(limit + 1)

    sql = f"""SELECT al.id, al.occurred_at, al.action_type, al.operation,
                     al.customer_id, al.target_count, al.status, al.duration_ms,
                     m.email AS manager_email,
                     {_SQL_COLUNA_NOME_DA_CONTA}
              FROM audit_log al
              LEFT JOIN managers m ON m.id = al.manager_id
              {_SQL_NOME_DA_CONTA}
              WHERE {filtros.sql}
              ORDER BY al.occurred_at DESC, al.id DESC
              LIMIT {limite}"""
    return sql, filtros.params


async def list_page_admin(
    conn: asyncpg.Connection,
    *,
    days: int = 7,
    manager_id: UUID | None = None,
    customer_id: str | None = None,
    action_type: str | None = None,
    status: str | None = None,
    cursor_occurred_at: datetime | None = None,
    cursor_id: int | None = None,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], tuple[datetime, int] | None]:
    """Keyset page of the GLOBAL audit log (every gestor), for `GET /admin/audit`.

    Same seek strategy as `list_page_for_manager` — see its docstring for why
    keyset replaces OFFSET. The difference here is shape, not mechanism:
    `manager_id` is an optional FILTER (an admin may look at any gestor's
    rows, or all of them), not a scope, and the SELECT/JOIN mirror what the
    admin table shows (gestor e-mail, no per-row dry_run/params_summary). The
    SQL itself lives in `_build_admin_page_sql`.
    """
    _recusa_limite_menor_que_um(limit)
    sql, params = _build_admin_page_sql(
        days=days,
        manager_id=manager_id,
        customer_id=customer_id,
        action_type=action_type,
        status=status,
        cursor_occurred_at=cursor_occurred_at,
        cursor_id=cursor_id,
        limit=limit,
    )
    fetched = await conn.fetch(sql, *params)
    page = fetched[:limit]
    next_cursor = (page[-1]["occurred_at"], int(page[-1]["id"])) if len(fetched) > limit else None
    return [dict(r) for r in page], next_cursor


async def top_operations_7d(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    """As 5 operações mais chamadas nos últimos 7 dias (overview do admin)."""
    rows = await conn.fetch(
        """SELECT operation, count(*) AS count FROM audit_log
           WHERE occurred_at > now() - interval '7 days'
           GROUP BY operation ORDER BY count DESC LIMIT 5"""
    )
    return list(rows)


async def top_managers_7d(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    """Os 5 gestores com mais chamadas nos últimos 7 dias (overview do admin)."""
    rows = await conn.fetch(
        """SELECT m.email, count(*) AS count
           FROM audit_log al JOIN managers m ON m.id = al.manager_id
           WHERE al.occurred_at > now() - interval '7 days'
           GROUP BY m.email ORDER BY count DESC LIMIT 5"""
    )
    return list(rows)


async def list_recent_for_manager(
    conn: asyncpg.Connection, manager_id: UUID
) -> list[asyncpg.Record]:
    """As 5 últimas chamadas do gestor, com o nome da conta Google (dashboard)."""
    rows = await conn.fetch(
        f"""SELECT al.occurred_at, al.operation, al.customer_id, al.status,
                  {_SQL_COLUNA_NOME_DA_CONTA}
           FROM audit_log al {_SQL_NOME_DA_CONTA}
           WHERE al.manager_id = $1
           ORDER BY al.occurred_at DESC, al.id DESC LIMIT 5""",
        manager_id,
    )
    return list(rows)
