"""Decide o que reconciliar. Puro de propósito: nenhuma I/O entra aqui.

Separar decisão de efeito é o que torna testável a única parte que pode revogar
acesso indevidamente. O repositório aplica; este módulo escolhe.
"""

import math
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class InventoryRow:
    ad_account_id: str
    is_active: bool
    missed_syncs: int


@dataclass(frozen=True, slots=True)
class Plan:
    to_add: list[str] = field(default_factory=list)
    to_bump: list[str] = field(default_factory=list)
    to_remove: list[str] = field(default_factory=list)
    to_reset: list[str] = field(default_factory=list)
    unreachable: list[str] = field(default_factory=list)
    blocked_reason: str | None = None


def build_plan(
    *,
    partnership_ids: set[str],
    reachable_ids: set[str],
    inventory: list[InventoryRow],
    complete: bool,
    threshold: int = 3,
    max_removal_ratio: float = 0.2,
    max_removal_abs: int = 5,
) -> Plan:
    """(parceria, alcance, inventário) → plano.

    Aditivo sempre; destrutivo só com leitura completa e dentro do teto.
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
    # missed_syncs conta as ausências ANTERIORES; esta execução é a próxima.
    remover = sorted(r.ad_account_id for r in ausentes if r.missed_syncs + 1 >= threshold)
    marcar = sorted(r.ad_account_id for r in ausentes if r.missed_syncs + 1 < threshold)

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
