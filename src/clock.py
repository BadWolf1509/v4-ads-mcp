"""`hoje` é propriedade da CONTA, não do servidor — e isso vale pros DOIS provedores.

Mora na raiz de `src/` pela mesma razão que `blocking.py`: é primitivo neutro,
consumido pelo Google (`google_ads.account_clock`, `jobs.account_resync`) e
pelo Meta (`jobs.meta_resync`). O lado Meta precisa da função sem importar
`src.google_ads.*` — e duplicá-la seria criar DUAS fontes de verdade do mesmo
fix do F141, que é exatamente a família que mais mordeu este projeto (o F91
reincidiu três vezes assim). Um só corpo, um só fallback, um só warning.

Puro de propósito: nenhuma I/O entra aqui. Quem lê o fuso do inventário é o
chamador — `google_ads.account_clock.resolve_account_today` no caminho de
request, e os dois jobs de resync no caminho de lote, onde o fuso já viaja
junto do inventário e uma leitura por conta abriria uma segunda conexão do
pool dentro da transação aberta da reconciliação.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

log = structlog.get_logger(__name__)


def account_today(time_zone: str | None, *, now: datetime) -> date:
    """Data corrente NO FUSO DA CONTA — o unico lugar deste modulo que sabe de fuso.

    F141: o Google le predicado de data no fuso da conta, e as 25 contas do MCC
    estao em UTC-3/UTC-4. Resolver `hoje` em UTC deslizava todo preset um dia
    entre 21h e meia-noite locais, todo dia, em silencio.

    Pura: recebe o instante em vez de ler o relogio, para o teste poder injetar
    um `now` em que UTC e a conta discordam — a diferenca que `freezegun` nao
    consegue representar.

    Fallback DECIDIDO (nao acidental): `None` ou chave desconhecida -> data UTC
    + warning. Todas as contas sincronizadas tem fuso; conta sem sync nao passa
    no gate de acesso. Recusar a chamada trocaria dado faltante de inventario
    por tool indisponivel.

    Lado Meta (probe de 2026-09-06, exigida antes de reusar isto la): a coluna
    `meta_ad_accounts.timezone_name` guarda nome IANA. Medido nas 25 contas
    vivas do cache de producao — `America/Sao_Paulo` (22), `America/Noronha`
    (2) e `America/Manaus` (1), todas resolvidas por `ZoneInfo` com o `tzdata`
    pinado no lockfile. A doc do Graph so promete "string", entao o fallback
    acima e o que cobre um valor fora do formato: warning
    `account_time_zone_unknown` e UTC, nunca excecao.
    """
    if time_zone:
        try:
            return now.astimezone(ZoneInfo(time_zone)).date()
        except ZoneInfoNotFoundError:
            log.warning("account_time_zone_unknown", time_zone=time_zone)
    else:
        log.warning("account_time_zone_missing")
    return now.astimezone(UTC).date()
