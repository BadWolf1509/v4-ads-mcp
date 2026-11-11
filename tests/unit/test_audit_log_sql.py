"""Caracterização (G3) dos montadores de filtro do `audit_log`.

Grava o SQL normalizado (espaços colapsados) e os `params` que cada construtor
emitia ANTES do refactor para `_Filtros`: é a rede — não muda com o refactor.
A ordem dos filtros é a de cada construtor (o admin põe `customer_id` antes de
`action_type`; o de gestor, depois).
"""

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from src.db.repositories import audit_log

_MID = UUID("11111111-1111-1111-1111-111111111111")
_TS = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


class _Tx:
    async def __aenter__(self) -> "_Tx":
        return self

    async def __aexit__(self, *a: object) -> bool:
        return False


class _Cursor:
    def __init__(self, conn: "_Conn", sql: str, args: tuple[Any, ...]) -> None:
        self._conn, self._sql, self._args = conn, sql, args

    def __aiter__(self) -> "_Cursor":
        self._conn.calls.append((self._sql, list(self._args)))
        return self

    async def __anext__(self) -> Any:
        raise StopAsyncIteration


class _Conn:
    """Conexão que só grava o (SQL, params) que o repositório manda."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[Any]]] = []

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        self.calls.append((sql, list(args)))
        return []

    async def fetchrow(self, sql: str, *args: Any) -> None:
        self.calls.append((sql, list(args)))

    def transaction(self) -> _Tx:
        return _Tx()

    def cursor(self, sql: str, *args: Any) -> _Cursor:
        return _Cursor(self, sql, args)


# (construtor, caso, kwargs, sql normalizado, params)
_CASOS: list[tuple[str, str, dict[str, Any], str, list[Any]]] = [
    (
        "manager_page",
        "nenhum",
        {},
        "SELECT al.*, a.descriptive_name AS account_name FROM audit_log al LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id WHERE al.manager_id = $1 AND al.occurred_at > now() - ($2 || ' days')::interval AND ($3::timestamptz IS NULL OR (al.occurred_at, al.id) < ($3, $4)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $5",
        [_MID, "7", None, None, 51],
    ),
    (
        "manager_page",
        "nenhum+cursor",
        {"cursor_occurred_at": _TS, "cursor_id": 42},
        "SELECT al.*, a.descriptive_name AS account_name FROM audit_log al LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id WHERE al.manager_id = $1 AND al.occurred_at > now() - ($2 || ' days')::interval AND ($3::timestamptz IS NULL OR (al.occurred_at, al.id) < ($3, $4)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $5",
        [_MID, "7", _TS, 42, 51],
    ),
    (
        "manager_page",
        "todos",
        {"customer_id": "1234567890", "action_type": "mutate", "status": "error"},
        "SELECT al.*, a.descriptive_name AS account_name FROM audit_log al LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id WHERE al.manager_id = $1 AND al.occurred_at > now() - ($2 || ' days')::interval AND al.action_type = $3 AND al.customer_id = $4 AND al.status = $5 AND ($6::timestamptz IS NULL OR (al.occurred_at, al.id) < ($6, $7)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $8",
        [_MID, "7", "mutate", "1234567890", "error", None, None, 51],
    ),
    (
        "manager_page",
        "todos+cursor",
        {
            "customer_id": "1234567890",
            "action_type": "mutate",
            "status": "error",
            "cursor_occurred_at": _TS,
            "cursor_id": 42,
        },
        "SELECT al.*, a.descriptive_name AS account_name FROM audit_log al LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id WHERE al.manager_id = $1 AND al.occurred_at > now() - ($2 || ' days')::interval AND al.action_type = $3 AND al.customer_id = $4 AND al.status = $5 AND ($6::timestamptz IS NULL OR (al.occurred_at, al.id) < ($6, $7)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $8",
        [_MID, "7", "mutate", "1234567890", "error", _TS, 42, 51],
    ),
    (
        "manager_page",
        "so_customer_id",
        {"customer_id": "1234567890"},
        "SELECT al.*, a.descriptive_name AS account_name FROM audit_log al LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id WHERE al.manager_id = $1 AND al.occurred_at > now() - ($2 || ' days')::interval AND al.customer_id = $3 AND ($4::timestamptz IS NULL OR (al.occurred_at, al.id) < ($4, $5)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $6",
        [_MID, "7", "1234567890", None, None, 51],
    ),
    (
        "manager_page",
        "so_customer_id+cursor",
        {"customer_id": "1234567890", "cursor_occurred_at": _TS, "cursor_id": 42},
        "SELECT al.*, a.descriptive_name AS account_name FROM audit_log al LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id WHERE al.manager_id = $1 AND al.occurred_at > now() - ($2 || ' days')::interval AND al.customer_id = $3 AND ($4::timestamptz IS NULL OR (al.occurred_at, al.id) < ($4, $5)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $6",
        [_MID, "7", "1234567890", _TS, 42, 51],
    ),
    (
        "manager_page",
        "so_action_type",
        {"action_type": "mutate"},
        "SELECT al.*, a.descriptive_name AS account_name FROM audit_log al LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id WHERE al.manager_id = $1 AND al.occurred_at > now() - ($2 || ' days')::interval AND al.action_type = $3 AND ($4::timestamptz IS NULL OR (al.occurred_at, al.id) < ($4, $5)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $6",
        [_MID, "7", "mutate", None, None, 51],
    ),
    (
        "manager_page",
        "so_action_type+cursor",
        {"action_type": "mutate", "cursor_occurred_at": _TS, "cursor_id": 42},
        "SELECT al.*, a.descriptive_name AS account_name FROM audit_log al LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id WHERE al.manager_id = $1 AND al.occurred_at > now() - ($2 || ' days')::interval AND al.action_type = $3 AND ($4::timestamptz IS NULL OR (al.occurred_at, al.id) < ($4, $5)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $6",
        [_MID, "7", "mutate", _TS, 42, 51],
    ),
    (
        "manager_page",
        "so_status",
        {"status": "error"},
        "SELECT al.*, a.descriptive_name AS account_name FROM audit_log al LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id WHERE al.manager_id = $1 AND al.occurred_at > now() - ($2 || ' days')::interval AND al.status = $3 AND ($4::timestamptz IS NULL OR (al.occurred_at, al.id) < ($4, $5)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $6",
        [_MID, "7", "error", None, None, 51],
    ),
    (
        "manager_page",
        "so_status+cursor",
        {"status": "error", "cursor_occurred_at": _TS, "cursor_id": 42},
        "SELECT al.*, a.descriptive_name AS account_name FROM audit_log al LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id WHERE al.manager_id = $1 AND al.occurred_at > now() - ($2 || ' days')::interval AND al.status = $3 AND ($4::timestamptz IS NULL OR (al.occurred_at, al.id) < ($4, $5)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $6",
        [_MID, "7", "error", _TS, 42, 51],
    ),
    (
        "manager_page",
        "action_type_all",
        {"action_type": "all"},
        "SELECT al.*, a.descriptive_name AS account_name FROM audit_log al LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id WHERE al.manager_id = $1 AND al.occurred_at > now() - ($2 || ' days')::interval AND ($3::timestamptz IS NULL OR (al.occurred_at, al.id) < ($3, $4)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $5",
        [_MID, "7", None, None, 51],
    ),
    (
        "manager_page",
        "action_type_all+cursor",
        {"action_type": "all", "cursor_occurred_at": _TS, "cursor_id": 42},
        "SELECT al.*, a.descriptive_name AS account_name FROM audit_log al LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id WHERE al.manager_id = $1 AND al.occurred_at > now() - ($2 || ' days')::interval AND ($3::timestamptz IS NULL OR (al.occurred_at, al.id) < ($3, $4)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $5",
        [_MID, "7", _TS, 42, 51],
    ),
    (
        "manager_page",
        "status_all",
        {"status": "all"},
        "SELECT al.*, a.descriptive_name AS account_name FROM audit_log al LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id WHERE al.manager_id = $1 AND al.occurred_at > now() - ($2 || ' days')::interval AND ($3::timestamptz IS NULL OR (al.occurred_at, al.id) < ($3, $4)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $5",
        [_MID, "7", None, None, 51],
    ),
    (
        "manager_page",
        "status_all+cursor",
        {"status": "all", "cursor_occurred_at": _TS, "cursor_id": 42},
        "SELECT al.*, a.descriptive_name AS account_name FROM audit_log al LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id WHERE al.manager_id = $1 AND al.occurred_at > now() - ($2 || ' days')::interval AND ($3::timestamptz IS NULL OR (al.occurred_at, al.id) < ($3, $4)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $5",
        [_MID, "7", _TS, 42, 51],
    ),
    (
        "admin_page",
        "nenhum",
        {},
        "SELECT al.id, al.occurred_at, al.action_type, al.operation, al.customer_id, al.target_count, al.status, al.duration_ms, m.email AS manager_email, gaa.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND ($2::timestamptz IS NULL OR (al.occurred_at, al.id) < ($2, $3)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $4",
        ["7", None, None, 51],
    ),
    (
        "admin_page",
        "nenhum+cursor",
        {"cursor_occurred_at": _TS, "cursor_id": 42},
        "SELECT al.id, al.occurred_at, al.action_type, al.operation, al.customer_id, al.target_count, al.status, al.duration_ms, m.email AS manager_email, gaa.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND ($2::timestamptz IS NULL OR (al.occurred_at, al.id) < ($2, $3)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $4",
        ["7", _TS, 42, 51],
    ),
    (
        "admin_page",
        "todos",
        {
            "manager_id": _MID,
            "customer_id": "1234567890",
            "action_type": "mutate",
            "status": "error",
        },
        "SELECT al.id, al.occurred_at, al.action_type, al.operation, al.customer_id, al.target_count, al.status, al.duration_ms, m.email AS manager_email, gaa.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.manager_id = $2 AND al.customer_id = $3 AND al.action_type = $4 AND al.status = $5 AND ($6::timestamptz IS NULL OR (al.occurred_at, al.id) < ($6, $7)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $8",
        ["7", _MID, "1234567890", "mutate", "error", None, None, 51],
    ),
    (
        "admin_page",
        "todos+cursor",
        {
            "manager_id": _MID,
            "customer_id": "1234567890",
            "action_type": "mutate",
            "status": "error",
            "cursor_occurred_at": _TS,
            "cursor_id": 42,
        },
        "SELECT al.id, al.occurred_at, al.action_type, al.operation, al.customer_id, al.target_count, al.status, al.duration_ms, m.email AS manager_email, gaa.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.manager_id = $2 AND al.customer_id = $3 AND al.action_type = $4 AND al.status = $5 AND ($6::timestamptz IS NULL OR (al.occurred_at, al.id) < ($6, $7)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $8",
        ["7", _MID, "1234567890", "mutate", "error", _TS, 42, 51],
    ),
    (
        "admin_page",
        "so_manager_id",
        {"manager_id": _MID},
        "SELECT al.id, al.occurred_at, al.action_type, al.operation, al.customer_id, al.target_count, al.status, al.duration_ms, m.email AS manager_email, gaa.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.manager_id = $2 AND ($3::timestamptz IS NULL OR (al.occurred_at, al.id) < ($3, $4)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $5",
        ["7", _MID, None, None, 51],
    ),
    (
        "admin_page",
        "so_manager_id+cursor",
        {"manager_id": _MID, "cursor_occurred_at": _TS, "cursor_id": 42},
        "SELECT al.id, al.occurred_at, al.action_type, al.operation, al.customer_id, al.target_count, al.status, al.duration_ms, m.email AS manager_email, gaa.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.manager_id = $2 AND ($3::timestamptz IS NULL OR (al.occurred_at, al.id) < ($3, $4)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $5",
        ["7", _MID, _TS, 42, 51],
    ),
    (
        "admin_page",
        "so_customer_id",
        {"customer_id": "1234567890"},
        "SELECT al.id, al.occurred_at, al.action_type, al.operation, al.customer_id, al.target_count, al.status, al.duration_ms, m.email AS manager_email, gaa.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.customer_id = $2 AND ($3::timestamptz IS NULL OR (al.occurred_at, al.id) < ($3, $4)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $5",
        ["7", "1234567890", None, None, 51],
    ),
    (
        "admin_page",
        "so_customer_id+cursor",
        {"customer_id": "1234567890", "cursor_occurred_at": _TS, "cursor_id": 42},
        "SELECT al.id, al.occurred_at, al.action_type, al.operation, al.customer_id, al.target_count, al.status, al.duration_ms, m.email AS manager_email, gaa.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.customer_id = $2 AND ($3::timestamptz IS NULL OR (al.occurred_at, al.id) < ($3, $4)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $5",
        ["7", "1234567890", _TS, 42, 51],
    ),
    (
        "admin_page",
        "so_action_type",
        {"action_type": "mutate"},
        "SELECT al.id, al.occurred_at, al.action_type, al.operation, al.customer_id, al.target_count, al.status, al.duration_ms, m.email AS manager_email, gaa.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.action_type = $2 AND ($3::timestamptz IS NULL OR (al.occurred_at, al.id) < ($3, $4)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $5",
        ["7", "mutate", None, None, 51],
    ),
    (
        "admin_page",
        "so_action_type+cursor",
        {"action_type": "mutate", "cursor_occurred_at": _TS, "cursor_id": 42},
        "SELECT al.id, al.occurred_at, al.action_type, al.operation, al.customer_id, al.target_count, al.status, al.duration_ms, m.email AS manager_email, gaa.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.action_type = $2 AND ($3::timestamptz IS NULL OR (al.occurred_at, al.id) < ($3, $4)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $5",
        ["7", "mutate", _TS, 42, 51],
    ),
    (
        "admin_page",
        "so_status",
        {"status": "error"},
        "SELECT al.id, al.occurred_at, al.action_type, al.operation, al.customer_id, al.target_count, al.status, al.duration_ms, m.email AS manager_email, gaa.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.status = $2 AND ($3::timestamptz IS NULL OR (al.occurred_at, al.id) < ($3, $4)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $5",
        ["7", "error", None, None, 51],
    ),
    (
        "admin_page",
        "so_status+cursor",
        {"status": "error", "cursor_occurred_at": _TS, "cursor_id": 42},
        "SELECT al.id, al.occurred_at, al.action_type, al.operation, al.customer_id, al.target_count, al.status, al.duration_ms, m.email AS manager_email, gaa.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.status = $2 AND ($3::timestamptz IS NULL OR (al.occurred_at, al.id) < ($3, $4)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $5",
        ["7", "error", _TS, 42, 51],
    ),
    (
        "admin_page",
        "action_type_all",
        {"action_type": "all"},
        "SELECT al.id, al.occurred_at, al.action_type, al.operation, al.customer_id, al.target_count, al.status, al.duration_ms, m.email AS manager_email, gaa.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND ($2::timestamptz IS NULL OR (al.occurred_at, al.id) < ($2, $3)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $4",
        ["7", None, None, 51],
    ),
    (
        "admin_page",
        "action_type_all+cursor",
        {"action_type": "all", "cursor_occurred_at": _TS, "cursor_id": 42},
        "SELECT al.id, al.occurred_at, al.action_type, al.operation, al.customer_id, al.target_count, al.status, al.duration_ms, m.email AS manager_email, gaa.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND ($2::timestamptz IS NULL OR (al.occurred_at, al.id) < ($2, $3)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $4",
        ["7", _TS, 42, 51],
    ),
    (
        "admin_page",
        "status_all",
        {"status": "all"},
        "SELECT al.id, al.occurred_at, al.action_type, al.operation, al.customer_id, al.target_count, al.status, al.duration_ms, m.email AS manager_email, gaa.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND ($2::timestamptz IS NULL OR (al.occurred_at, al.id) < ($2, $3)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $4",
        ["7", None, None, 51],
    ),
    (
        "admin_page",
        "status_all+cursor",
        {"status": "all", "cursor_occurred_at": _TS, "cursor_id": 42},
        "SELECT al.id, al.occurred_at, al.action_type, al.operation, al.customer_id, al.target_count, al.status, al.duration_ms, m.email AS manager_email, gaa.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND ($2::timestamptz IS NULL OR (al.occurred_at, al.id) < ($2, $3)) ORDER BY al.occurred_at DESC, al.id DESC LIMIT $4",
        ["7", _TS, 42, 51],
    ),
    (
        "export",
        "admin:nenhum",
        {"manager_id": None},
        "SELECT al.occurred_at, m.email, al.operation, al.customer_id, al.action_type, al.status, al.target_count, al.duration_ms, al.error_message, al.provider_request_id FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id WHERE al.occurred_at > now() - ($1 || ' days')::interval ORDER BY al.occurred_at DESC, al.id DESC LIMIT $2",
        ["7", 50001],
    ),
    (
        "export",
        "admin:todos",
        {
            "manager_id": None,
            "customer_id": "1234567890",
            "action_type": "mutate",
            "status": "error",
        },
        "SELECT al.occurred_at, m.email, al.operation, al.customer_id, al.action_type, al.status, al.target_count, al.duration_ms, al.error_message, al.provider_request_id FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.customer_id = $2 AND al.action_type = $3 AND al.status = $4 ORDER BY al.occurred_at DESC, al.id DESC LIMIT $5",
        ["7", "1234567890", "mutate", "error", 50001],
    ),
    (
        "export",
        "admin:so_customer_id",
        {"manager_id": None, "customer_id": "1234567890"},
        "SELECT al.occurred_at, m.email, al.operation, al.customer_id, al.action_type, al.status, al.target_count, al.duration_ms, al.error_message, al.provider_request_id FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.customer_id = $2 ORDER BY al.occurred_at DESC, al.id DESC LIMIT $3",
        ["7", "1234567890", 50001],
    ),
    (
        "export",
        "admin:so_action_type",
        {"manager_id": None, "action_type": "mutate"},
        "SELECT al.occurred_at, m.email, al.operation, al.customer_id, al.action_type, al.status, al.target_count, al.duration_ms, al.error_message, al.provider_request_id FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.action_type = $2 ORDER BY al.occurred_at DESC, al.id DESC LIMIT $3",
        ["7", "mutate", 50001],
    ),
    (
        "export",
        "admin:so_status",
        {"manager_id": None, "status": "error"},
        "SELECT al.occurred_at, m.email, al.operation, al.customer_id, al.action_type, al.status, al.target_count, al.duration_ms, al.error_message, al.provider_request_id FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.status = $2 ORDER BY al.occurred_at DESC, al.id DESC LIMIT $3",
        ["7", "error", 50001],
    ),
    (
        "export",
        "admin:action_type_all",
        {"manager_id": None, "action_type": "all"},
        "SELECT al.occurred_at, m.email, al.operation, al.customer_id, al.action_type, al.status, al.target_count, al.duration_ms, al.error_message, al.provider_request_id FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id WHERE al.occurred_at > now() - ($1 || ' days')::interval ORDER BY al.occurred_at DESC, al.id DESC LIMIT $2",
        ["7", 50001],
    ),
    (
        "export",
        "admin:status_all",
        {"manager_id": None, "status": "all"},
        "SELECT al.occurred_at, m.email, al.operation, al.customer_id, al.action_type, al.status, al.target_count, al.duration_ms, al.error_message, al.provider_request_id FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id WHERE al.occurred_at > now() - ($1 || ' days')::interval ORDER BY al.occurred_at DESC, al.id DESC LIMIT $2",
        ["7", 50001],
    ),
    (
        "export",
        "gestor:nenhum",
        {"manager_id": _MID},
        "SELECT al.occurred_at, m.email, al.operation, al.customer_id, al.action_type, al.status, al.target_count, al.duration_ms, al.error_message, al.provider_request_id FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.manager_id = $2 ORDER BY al.occurred_at DESC, al.id DESC LIMIT $3",
        ["7", _MID, 50001],
    ),
    (
        "export",
        "gestor:todos",
        {
            "manager_id": _MID,
            "customer_id": "1234567890",
            "action_type": "mutate",
            "status": "error",
        },
        "SELECT al.occurred_at, m.email, al.operation, al.customer_id, al.action_type, al.status, al.target_count, al.duration_ms, al.error_message, al.provider_request_id FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.manager_id = $2 AND al.customer_id = $3 AND al.action_type = $4 AND al.status = $5 ORDER BY al.occurred_at DESC, al.id DESC LIMIT $6",
        ["7", _MID, "1234567890", "mutate", "error", 50001],
    ),
    (
        "export",
        "gestor:so_customer_id",
        {"manager_id": _MID, "customer_id": "1234567890"},
        "SELECT al.occurred_at, m.email, al.operation, al.customer_id, al.action_type, al.status, al.target_count, al.duration_ms, al.error_message, al.provider_request_id FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.manager_id = $2 AND al.customer_id = $3 ORDER BY al.occurred_at DESC, al.id DESC LIMIT $4",
        ["7", _MID, "1234567890", 50001],
    ),
    (
        "export",
        "gestor:so_action_type",
        {"manager_id": _MID, "action_type": "mutate"},
        "SELECT al.occurred_at, m.email, al.operation, al.customer_id, al.action_type, al.status, al.target_count, al.duration_ms, al.error_message, al.provider_request_id FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.manager_id = $2 AND al.action_type = $3 ORDER BY al.occurred_at DESC, al.id DESC LIMIT $4",
        ["7", _MID, "mutate", 50001],
    ),
    (
        "export",
        "gestor:so_status",
        {"manager_id": _MID, "status": "error"},
        "SELECT al.occurred_at, m.email, al.operation, al.customer_id, al.action_type, al.status, al.target_count, al.duration_ms, al.error_message, al.provider_request_id FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.manager_id = $2 AND al.status = $3 ORDER BY al.occurred_at DESC, al.id DESC LIMIT $4",
        ["7", _MID, "error", 50001],
    ),
    (
        "export",
        "gestor:action_type_all",
        {"manager_id": _MID, "action_type": "all"},
        "SELECT al.occurred_at, m.email, al.operation, al.customer_id, al.action_type, al.status, al.target_count, al.duration_ms, al.error_message, al.provider_request_id FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.manager_id = $2 ORDER BY al.occurred_at DESC, al.id DESC LIMIT $3",
        ["7", _MID, 50001],
    ),
    (
        "export",
        "gestor:status_all",
        {"manager_id": _MID, "status": "all"},
        "SELECT al.occurred_at, m.email, al.operation, al.customer_id, al.action_type, al.status, al.target_count, al.duration_ms, al.error_message, al.provider_request_id FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id WHERE al.occurred_at > now() - ($1 || ' days')::interval AND al.manager_id = $2 ORDER BY al.occurred_at DESC, al.id DESC LIMIT $3",
        ["7", _MID, 50001],
    ),
    (
        "list_for_manager",
        "nenhum",
        {},
        "SELECT id, occurred_at, operation, customer_id, action_type, target_count, status, duration_ms, provider_request_id, error_message, platform, dry_run FROM audit_log WHERE manager_id = $1 AND occurred_at > now() - ($2 || ' days')::interval ORDER BY occurred_at DESC, id DESC LIMIT $3",
        [_MID, "7", 100],
    ),
    (
        "list_for_manager",
        "todos",
        {"customer_id": "1234567890", "action_type": "mutate"},
        "SELECT id, occurred_at, operation, customer_id, action_type, target_count, status, duration_ms, provider_request_id, error_message, platform, dry_run FROM audit_log WHERE manager_id = $1 AND occurred_at > now() - ($2 || ' days')::interval AND customer_id = $3 AND action_type = $4 ORDER BY occurred_at DESC, id DESC LIMIT $5",
        [_MID, "7", "1234567890", "mutate", 100],
    ),
    (
        "list_for_manager",
        "so_customer_id",
        {"customer_id": "1234567890"},
        "SELECT id, occurred_at, operation, customer_id, action_type, target_count, status, duration_ms, provider_request_id, error_message, platform, dry_run FROM audit_log WHERE manager_id = $1 AND occurred_at > now() - ($2 || ' days')::interval AND customer_id = $3 ORDER BY occurred_at DESC, id DESC LIMIT $4",
        [_MID, "7", "1234567890", 100],
    ),
    (
        "list_for_manager",
        "so_action_type",
        {"action_type": "mutate"},
        "SELECT id, occurred_at, operation, customer_id, action_type, target_count, status, duration_ms, provider_request_id, error_message, platform, dry_run FROM audit_log WHERE manager_id = $1 AND occurred_at > now() - ($2 || ' days')::interval AND action_type = $3 ORDER BY occurred_at DESC, id DESC LIMIT $4",
        [_MID, "7", "mutate", 100],
    ),
    (
        "list_for_manager",
        "action_type_all",
        {"action_type": "all"},
        "SELECT id, occurred_at, operation, customer_id, action_type, target_count, status, duration_ms, provider_request_id, error_message, platform, dry_run FROM audit_log WHERE manager_id = $1 AND occurred_at > now() - ($2 || ' days')::interval ORDER BY occurred_at DESC, id DESC LIMIT $3",
        [_MID, "7", 100],
    ),
    (
        "get_by_id",
        "admin",
        {"manager_id": None},
        "SELECT al.*, m.email AS manager_email, s.label AS session_label, a.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN mcp_sessions s ON s.id = al.session_id LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id WHERE al.id = $1",
        [7],
    ),
    (
        "get_by_id",
        "gestor",
        {"manager_id": _MID},
        "SELECT al.*, m.email AS manager_email, s.label AS session_label, a.descriptive_name AS account_name FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id LEFT JOIN mcp_sessions s ON s.id = al.session_id LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id WHERE al.id = $1 AND al.manager_id = $2",
        [7, _MID],
    ),
]


async def _executa(construtor: str, kw: dict[str, Any]) -> tuple[str, list[Any]]:
    if construtor == "manager_page":
        return audit_log._build_manager_page_sql(
            manager_id=_MID,
            days=7,
            customer_id=kw.get("customer_id"),
            action_type=kw.get("action_type"),
            status=kw.get("status"),
            cursor_occurred_at=kw.get("cursor_occurred_at"),
            cursor_id=kw.get("cursor_id"),
            limit=50,
        )
    if construtor == "admin_page":
        return audit_log._build_admin_page_sql(
            days=7,
            manager_id=kw.get("manager_id"),
            customer_id=kw.get("customer_id"),
            action_type=kw.get("action_type"),
            status=kw.get("status"),
            cursor_occurred_at=kw.get("cursor_occurred_at"),
            cursor_id=kw.get("cursor_id"),
            limit=50,
        )
    conn = _Conn()
    if construtor == "export":
        extra = {k: v for k, v in kw.items() if k != "manager_id"}
        async for _ in audit_log.export_csv_rows(
            conn, manager_id=kw["manager_id"], days=7, **extra
        ):
            pass
    elif construtor == "list_for_manager":
        await audit_log.list_for_manager(conn, manager_id=_MID, days=7, limit=100, **kw)
    elif construtor == "get_by_id":
        await audit_log.get_by_id(conn, audit_id=7, manager_id=kw["manager_id"])
    else:
        raise AssertionError(construtor)
    return conn.calls[0]


@pytest.mark.parametrize(
    ("construtor", "caso", "kw", "sql_esperado", "params_esperados"),
    _CASOS,
    ids=[f"{c[0]}-{c[1]}" for c in _CASOS],
)
async def test_construtor_emite_o_mesmo_sql_e_params(
    construtor: str,
    caso: str,
    kw: dict[str, Any],
    sql_esperado: str,
    params_esperados: list[Any],
) -> None:
    sql, params = await _executa(construtor, kw)
    assert _norm(sql) == sql_esperado
    assert list(params) == params_esperados


def test_filtros_vazio_vira_true() -> None:
    f = audit_log._Filtros()
    assert f.sql == "TRUE"
    assert f.params == []


def test_filtros_numera_os_placeholders_na_ordem_dos_params() -> None:
    f = audit_log._Filtros()
    f.add("a = {}", "x")
    f.add("b > now() - ({} || ' days')::interval", "7")
    f.add_cursor(_TS, 42)
    limite = f.add_limit(51)
    assert f.sql == (
        "a = $1 AND b > now() - ($2 || ' days')::interval AND "
        "($3::timestamptz IS NULL OR (al.occurred_at, al.id) < ($3, $4))"
    )
    assert limite == "$5"
    assert f.params == ["x", "7", _TS, 42, 51]


def test_filtros_sem_cursor_mantem_a_numeracao() -> None:
    f = audit_log._Filtros()
    f.add("a = {}", 1)
    f.add_cursor(None, None)
    assert f.add_limit(10) == "$4"
    assert f.params == [1, None, None, 10]
