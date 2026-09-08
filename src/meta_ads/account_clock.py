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

from src.clock import account_today
from src.db import connection
from src.db.repositories import meta_ad_accounts


async def resolve_meta_account_today(ad_account_id: str, *, now: datetime | None = None) -> date:
    """Dia corrente no fuso da conta `ad_account_id`. `now` injetavel para teste."""
    account = await connection.run_with_reconnect(
        lambda conn: meta_ad_accounts.get_by_id(conn, ad_account_id)
    )
    time_zone = account.timezone_name if account is not None else None
    return account_today(time_zone, now=now if now is not None else datetime.now(UTC))
