"""F141, gêmeo Meta: `hoje` e uma propriedade da CONTA, nao do servidor.

O lado Google fechou isto em 2026-09-06 e o guard
(`tests/unit/test_no_server_clock_in_google_tools.py`) isentou `meta_*` de
proposito, com a isencao escrita como divida: "estes SAO a mesma classe". Este
modulo paga a divida.

Espelha `src/google_ads/account_clock.py` deliberadamente — mesmo formato, mesmo
fallback, mesma delegacao ao corpo unico em `src.clock.account_today`. O que
muda e SO a fonte do fuso: `meta_ad_accounts.timezone_name` (nome IANA) em vez
de `google_ads_accounts.time_zone`. Nomes de coluna diferentes porque as duas
tabelas os batizaram diferente; a dataclass de cada lado espelha a sua tabela, e
renomear aqui esconderia de onde o dado vem.

Sonda empirica ja feita (2026-09-06, registrada em `src/clock.py`): as 25 contas
vivas do cache de producao trazem `America/Sao_Paulo` (22), `America/Noronha`
(2) e `America/Manaus` (1), todas resolvidas por `ZoneInfo` com o `tzdata`
pinado no lockfile. A doc do Graph so promete "string", entao o fallback
cobre valor fora do formato com warning + UTC, nunca excecao.

Leitura idempotente em hot path -> `run_with_reconnect` (F76/F77).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.clock import account_today
from src.db import connection
from src.db.repositories import meta_ad_accounts


async def _timezone_name(ad_account_id: str) -> str | None:
    account = await connection.run_with_reconnect(
        lambda conn: meta_ad_accounts.get_by_id(conn, ad_account_id)
    )
    return account.timezone_name if account is not None else None


async def resolve_meta_account_today(ad_account_id: str, *, now: datetime | None = None) -> date:
    """Dia corrente no fuso da conta `ad_account_id`. `now` injetavel para teste."""
    time_zone = await _timezone_name(ad_account_id)
    return account_today(time_zone, now=now if now is not None else datetime.now(UTC))


async def resolve_meta_account_zone(ad_account_id: str) -> str | None:
    """Nome IANA do fuso da conta, ou None se ausente ou invalido, sem cair em UTC.

    Mesmo contrato do `resolve_account_zone` do Google: quem decide o que fazer sem fuso e o
    chamador. O fallback UTC serve para `hoje`, nao para decidir se um evento esta na janela.
    """
    time_zone = await _timezone_name(ad_account_id)
    if not time_zone:
        return None
    try:
        ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return time_zone
