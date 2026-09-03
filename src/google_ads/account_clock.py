"""F141: `hoje` e uma propriedade da CONTA, nao do servidor.

O Google le predicado de data no fuso da conta anunciante. As 25 contas do MCC
estao em cinco fusos, todos UTC-3 ou UTC-4 — nenhuma em UTC, que era onde o
servidor resolvia `TODAY`/`YESTERDAY`/`LAST_N_DAYS`. Entre 21h e meia-noite
locais, todo dia, todo preset deslizava um dia em silencio.

Este modulo e o unico ponto de I/O do fix: le o fuso do inventario
(`google_ads_accounts.time_zone`, populado pelo resync) e delega o calculo puro
a `account_today`. Cada tool chama UMA vez por request e passa o mesmo `today`
a tudo que precisa dele — resolucao de janela, clamp de retencao, sonda de
fronteira, freshness. Um `hoje` por request; nunca dois relogios na mesma
resposta.

Leitura idempotente em hot path -> `run_with_reconnect` (F76/F77).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from src.db import connection
from src.db.repositories import google_ads_accounts
from src.google_ads.queries._common import account_today


async def resolve_account_today(customer_id: str, *, now: datetime | None = None) -> date:
    """Dia corrente no fuso da conta `customer_id`. `now` injetavel para teste."""
    account = await connection.run_with_reconnect(
        lambda conn: google_ads_accounts.get_by_customer_id(conn, customer_id)
    )
    time_zone = account.time_zone if account is not None else None
    return account_today(time_zone, now=now if now is not None else datetime.now(UTC))
