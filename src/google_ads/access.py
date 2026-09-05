"""Per-account authorization gate for Google MCP tools.

The MCC OAuth token reaches all client accounts; this gate makes
`manager_account_access` the authoritative boundary at the MCP layer
(mirrors src/meta_ads/reports.py's can_manager_access check).
"""

from uuid import UUID

import asyncpg
import structlog

from src.db.repositories import audit_log, google_ads_accounts, manager_account_access
from src.governance.bookkeeping import best_effort

log = structlog.get_logger(__name__)


class AccountAccessDeniedError(Exception):
    """Raised when a manager has no grant for the requested Google customer_id."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def ensure_account_access(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    customer_id: str,
    session_id: UUID,
    operation_name: str,
    level: str = "read",
) -> None:
    """Raise AccountAccessDeniedError (PT-BR) + audit denied if the manager lacks
    `level` access to customer_id. No-op when access is granted.
    """
    allowed = await manager_account_access.can_manager_access(
        conn, manager_id, customer_id, level=level
    )
    if allowed:
        return
    # F91 — o gate roda dentro de `run_with_reconnect` (read idempotente). O
    # audit da negação, porém, é WRITE: se ele estourasse por conexão morta, a
    # exceção subiria e o retry re-executaria o INSERT, podendo duplicar a linha.
    # `best_effort` mantém o retry restrito ao read. Perder o registro é pior que
    # tê-lo, mas hoje a mesma falha virava 500 — sem audit E sem negação clara.
    async with best_effort(
        "account_access_denial_audit_failed",
        manager_id=str(manager_id),
        customer_id=customer_id,
        operation=operation_name,
    ):
        await audit_log.record(
            conn,
            manager_id=manager_id,
            session_id=session_id,
            customer_id=customer_id,
            action_type="mutate" if level == "write" else "read",
            operation=operation_name,
            status="denied",
            error_message="Gestor sem acesso à conta Google",
            platform="google",
        )
    log.warning(
        "account_access_denied",
        manager_id=str(manager_id),
        customer_id=customer_id,
        operation=operation_name,
        level=level,
        platform="google",
    )
    # Item 2 (revisão final): "peça ao admin pra liberar no painel" é conselho
    # que só funciona quando a causa é falta de grant numa conta ATIVA. Se a
    # conta está fora do inventário (nunca sincronizada) ou saiu do MCC
    # (`is_active = false`), esse conselho não pode funcionar — ela nem
    # aparece na matriz do painel (`google_ads_accounts.list_all` só lista
    # ativas), e mesmo um grant novo não ajuda, porque o gate nega por
    # `is_active` antes de olhar o grant. Só no caminho de negação (raro) vale
    # a leitura extra pra escolher a mensagem certa; audit_log acima já
    # gravou o motivo genérico e não muda.
    account = await google_ads_accounts.get_by_customer_id(conn, customer_id)
    if account is None or not account.is_active:
        raise AccountAccessDeniedError(
            f"A conta {customer_id} não está no MCC (ou já saiu dele) — liberar "
            "acesso no painel não resolve. O caminho é a conta voltar ao MCC e "
            "o resync rodar."
        )
    raise AccountAccessDeniedError(
        f"Você não tem acesso à conta {customer_id}. Peça ao admin pra liberar no painel."
    )
