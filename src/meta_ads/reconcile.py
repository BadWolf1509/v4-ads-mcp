"""Decide o que reconciliar. Puro de propósito: nenhuma I/O entra aqui.

Separar decisão de efeito é o que torna testável a única parte que pode revogar
acesso indevidamente. O repositório aplica; este módulo escolhe.
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime

from src.clock import account_today


@dataclass(frozen=True, slots=True)
class InventoryRow:
    ad_account_id: str
    is_active: bool
    missed_syncs: int
    # C4/F141: `build_plan` NÃO lê este campo — ele viaja junto do inventário
    # porque quem aplica a ausência precisa saber em que dia ela caiu, e o dia é
    # propriedade da CONTA. Resolvê-lo por leitura separada seria uma consulta
    # por conta, cada uma adquirindo uma segunda conexão do pool DENTRO da
    # transação já aberta da reconciliação.
    #
    # Nome diferente do gêmeo Google (`InventoryRow.time_zone`) porque a COLUNA
    # é outra: `meta_ad_accounts.timezone_name` vs `google_ads_accounts.time_zone`.
    # A linha espelha a tabela dela; renomear aqui esconderia de onde o dado vem.
    #
    # O default existe por compatibilidade com os construtores POSICIONAIS dos
    # testes unitários do job (`InventoryRow("act_2", True, 9)`) — não porque o
    # campo seja opcional de verdade. O preço: um produtor novo que o esqueça
    # carimba o inventário inteiro em UTC em silêncio, e o que segura isso é
    # `test_list_inventory_rows_traz_o_fuso_da_conta_meta`.
    timezone_name: str | None = None
    # C4, segunda metade: este campo `build_plan` LÊ. `missed_syncs` conta as
    # ausências JÁ GRAVADAS, e desde o C4 o `UPDATE` é idempotente por dia —
    # então "esta execução ainda não está no contador" deixou de ser verdade
    # num retry do mesmo dia. `last_missed_on` é o que distingue os dois casos,
    # e por isso viaja junto do contador: sem ele a decisão é cega ao retry,
    # e deste lado a decisão revoga acesso de gestor em produção.
    # Default nulo pelo mesmo motivo do fuso (construtores posicionais dos
    # unit tests); quem preenche de verdade é `list_inventory_rows`.
    last_missed_on: date | None = None


@dataclass(frozen=True, slots=True)
class Plan:
    to_add: list[str] = field(default_factory=list)
    to_bump: list[str] = field(default_factory=list)
    to_remove: list[str] = field(default_factory=list)
    to_reset: list[str] = field(default_factory=list)
    unreachable: list[str] = field(default_factory=list)
    blocked_reason: str | None = None


def _faltas_com_esta_execucao(r: InventoryRow, *, now: datetime) -> int:
    """`missed_syncs` já incluindo a ausência DESTA execução — o `+1` condicional.

    O `+1` era incondicional, com o comentário "esta execução é a próxima".
    Deixou de ser verdade no C4: `apply_absences` passou a contar uma ausência
    por DIA (no fuso da conta), não uma por execução, então num retry do mesmo
    dia a ausência de hoje JÁ está no contador. Somar de novo aqui queima um
    dia de carência sem gravar nada — e na execução da fronteira desativa a
    conta e REVOGA os grants dos gestores um dia antes da hora, com o contador
    parado no valor certo (o sintoma não aparece na coluna). Deste lado a
    trava `meta_reconcile_apply` está ligada desde 05/09: era dano vivo.

    O dia é o da CONTA (F141), derivado do mesmo instante que o job vai
    carimbar: comparar com o dia do SERVIDOR erraria justamente das 21h à
    meia-noite locais, que é a janela em que ninguém testa. `account_today` só
    é chamado quando há data gravada — hoje `last_missed_on` é NULL no
    inventário inteiro (a 009 subiu sem backfill), e o curto-circuito evita
    resolver fuso de conta que não tem série de ausências.
    """
    if r.last_missed_on is not None and r.last_missed_on == account_today(r.timezone_name, now=now):
        return r.missed_syncs
    return r.missed_syncs + 1


def build_plan(
    *,
    partnership_ids: set[str],
    reachable_ids: set[str],
    inventory: list[InventoryRow],
    complete: bool,
    now: datetime,
    threshold: int = 3,
    max_removal_ratio: float = 0.2,
    max_removal_abs: int = 5,
) -> Plan:
    """(parceria, alcance, inventário, instante) → plano.

    Aditivo sempre; destrutivo só com leitura completa e dentro do teto.

    `now` é o instante da EXECUÇÃO, o MESMO que o job lê uma vez e passa a
    `apply_absences`. Obrigatório de propósito: com default o call-site que o
    esquecesse voltaria em silêncio a somar `+1` por execução, que é o defeito
    que este parâmetro existe para fechar (a família F150/F151 — caminho não
    tratado que três revisões deixam passar porque revisão lê o código
    ESCRITO). Continua puro: recebe o instante, não lê relógio, e a única
    dependência nova é `src.clock.account_today`, que é função pura de
    (nome de fuso, instante).
    """
    ativos = [r for r in inventory if r.is_active]
    ids_ativos = {r.ad_account_id for r in ativos}

    to_add = sorted(partnership_ids - ids_ativos)
    # T3c (revisão de branch): o sinal da §3 é `in_partnership ∧ ¬reachable` —
    # sem interseção com o inventário. Intersectar com `ids_ativos` (lido ANTES
    # do upsert) apagava justamente a conta nova-e-inalcançável, que é o caso
    # real em produção (`CA - V4 Lima Soares`, `CHUTE 07`): ela entra por
    # `to_add` no mesmo ciclo, e o audit reportaria `unreachable: 0` no dia 1.
    unreachable = sorted(partnership_ids - reachable_ids)
    to_reset = sorted(
        r.ad_account_id for r in ativos if r.missed_syncs and r.ad_account_id in partnership_ids
    )

    if not complete:
        # Metade da lista não sustenta a afirmação "esta conta saiu da parceria".
        return Plan(
            to_add=to_add,
            to_reset=to_reset,
            unreachable=unreachable,
            blocked_reason="leitura incompleta",
        )

    ausentes = [r for r in ativos if r.ad_account_id not in partnership_ids]
    # `missed_syncs` conta as ausências JÁ GRAVADAS; a desta execução entra
    # aqui — e SÓ se ainda não estiver lá. É por isso que a soma é condicional:
    # ver `_faltas_com_esta_execucao`.
    faltas = [(r.ad_account_id, _faltas_com_esta_execucao(r, now=now)) for r in ausentes]
    remover = sorted(aid for aid, n in faltas if n >= threshold)
    marcar = sorted(aid for aid, n in faltas if n < threshold)

    # `max(1, ...)`: sem o piso, inventário pequeno zera o teto (2 ativas → 20% →
    # floor 0) e o guard barraria ATÉ a saída de uma conta só — o recurso nunca
    # dispararia. O guard existe contra remoção em massa, não contra o caso normal.
    teto = max(1, min(max_removal_abs, math.floor(len(ativos) * max_removal_ratio)))
    if remover and len(remover) > teto:
        return Plan(
            to_add=to_add,
            to_reset=to_reset,
            unreachable=unreachable,
            blocked_reason=(
                f"remocao em massa barrada: {len(remover)} contas de {len(ativos)} ativas "
                f"(teto {teto})"
            ),
        )

    return Plan(
        to_add=to_add, to_bump=marcar, to_remove=remover, to_reset=to_reset, unreachable=unreachable
    )
