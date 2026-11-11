"""Núcleo da regra de reconciliação, comum ao Google (MCC) e ao Meta (parceria do BM).

Puro de propósito: nenhuma I/O. As duas reconciliações REVOGAM acesso de gestor
a conta que sai da origem, e até aqui a regra que decide QUEM sai era duas
cópias (`src/google_ads/reconcile.py`, `src/meta_ads/reconcile.py`) — cópia que
diverge em silêncio muda quem perde acesso. Agora a regra mora aqui uma vez só;
cada `build_plan` virou adaptador: traduz a sua `InventoryRow` (que espelha a
tabela dela, com nomes de coluna diferentes) para `LinhaNeutra` e monta o seu
`Plan` a partir do `PlanoNeutro`.

O que NÃO veio para cá, por decisão registrada no plano de 10/11:
- `unreachable` é só do Meta (`su_reachable` separa "saiu da parceria" de "SU não
  atribuído") e continua no adaptador Meta, que o propaga também no plano barrado;
- a parte destrutiva (`reconcile_google`/`reconcile_meta`, que aplica o plano e
  revoga) segue uma por plataforma. Só a DECISÃO é comum.
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime

from src.clock import account_today


@dataclass(frozen=True, slots=True)
class LinhaNeutra:
    """Uma linha do inventário, sem o nome de coluna de cada plataforma.

    `conta` é `customer_id` (Google) ou `ad_account_id` (Meta); `fuso` é
    `time_zone` (Google) ou `timezone_name` (Meta).
    """

    conta: str
    is_active: bool
    missed_syncs: int
    fuso: str | None
    last_missed_on: date | None


@dataclass(frozen=True, slots=True)
class PlanoNeutro:
    to_add: list[str] = field(default_factory=list)
    to_bump: list[str] = field(default_factory=list)
    to_remove: list[str] = field(default_factory=list)
    to_reset: list[str] = field(default_factory=list)
    blocked_reason: str | None = None


def faltas_com_esta_execucao(r: LinhaNeutra, *, now: datetime) -> int:
    """`missed_syncs` já incluindo a ausência DESTA execução — o `+1` condicional.

    O `+1` era incondicional, com o comentário "esta execução é a próxima".
    Deixou de ser verdade no C4: `apply_absences` passou a contar uma ausência
    por DIA (no fuso da conta), não uma por execução, então num retry do mesmo
    dia a ausência de hoje JÁ está no contador. Somar de novo aqui queima um
    dia de carência sem gravar nada — e na execução da fronteira desativa a
    conta e REVOGA os grants dos gestores um dia antes da hora, com o contador
    parado no valor certo (o sintoma não aparece na coluna). No Meta a trava
    `meta_reconcile_apply` está ligada desde 05/09: era dano vivo.

    O dia é o da CONTA (F141), derivado do mesmo instante que o job vai
    carimbar: comparar com o dia do SERVIDOR erraria justamente das 21h à
    meia-noite locais, que é a janela em que ninguém testa. `account_today` só
    é chamado quando há data gravada — hoje `last_missed_on` é NULL no
    inventário inteiro (a 009 subiu sem backfill), e o curto-circuito evita
    resolver fuso de conta que não tem série de ausências.
    """
    if r.last_missed_on is not None and r.last_missed_on == account_today(r.fuso, now=now):
        return r.missed_syncs
    return r.missed_syncs + 1


def plano_neutro(
    *,
    presentes: set[str],
    inventario: list[LinhaNeutra],
    complete: bool,
    now: datetime,
    threshold: int,
    max_removal_ratio: float,
    max_removal_abs: int,
) -> PlanoNeutro:
    """(origem, inventário, instante) → plano. Aditivo sempre; destrutivo só com leitura completa.

    `presentes` são os ids que a origem (MCC ou parceria) devolveu. Sem defaults
    de propósito: os limites (`threshold`, teto) são da política de cada
    plataforma e ficam nas assinaturas dos `build_plan`, que não mudaram.

    `now` é o instante da EXECUÇÃO, o MESMO que o job lê uma vez e passa a
    `apply_absences`. Obrigatório: com default o call-site que o esquecesse
    voltaria em silêncio a somar `+1` por execução (a família F150/F151).
    Continua puro: recebe o instante, não lê relógio, e `account_today` é função
    pura de (nome de fuso, instante).
    """
    ativos = [r for r in inventario if r.is_active]
    ids_ativos = {r.conta for r in ativos}

    to_add = sorted(presentes - ids_ativos)
    to_reset = sorted(r.conta for r in ativos if r.missed_syncs and r.conta in presentes)

    if not complete:
        # Metade da lista não sustenta a afirmação "esta conta saiu da origem".
        return PlanoNeutro(to_add=to_add, to_reset=to_reset, blocked_reason="leitura incompleta")

    ausentes = [r for r in ativos if r.conta not in presentes]
    # `missed_syncs` conta as ausências JÁ GRAVADAS; a desta execução entra
    # aqui — e SÓ se ainda não estiver lá. É por isso que a soma é condicional:
    # ver `faltas_com_esta_execucao`.
    faltas = [(r.conta, faltas_com_esta_execucao(r, now=now)) for r in ausentes]
    remover = sorted(conta for conta, n in faltas if n >= threshold)
    marcar = sorted(conta for conta, n in faltas if n < threshold)

    # `max(1, ...)`: sem o piso, inventário pequeno zera o teto (2 ativas → 20% →
    # floor 0) e o guard barraria ATÉ a saída de uma conta só — o recurso nunca
    # dispararia. O guard existe contra remoção em massa, não contra o caso normal.
    teto = max(1, min(max_removal_abs, math.floor(len(ativos) * max_removal_ratio)))
    if remover and len(remover) > teto:
        return PlanoNeutro(
            to_add=to_add,
            to_reset=to_reset,
            blocked_reason=(
                f"remocao em massa barrada: {len(remover)} contas de {len(ativos)} ativas "
                f"(teto {teto})"
            ),
        )

    return PlanoNeutro(to_add=to_add, to_bump=marcar, to_remove=remover, to_reset=to_reset)
