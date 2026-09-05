"""Decide o que reconciliar no lado Google. Puro de propósito: nenhuma I/O.

Separar decisão de efeito é o que torna testável a única parte que pode revogar
acesso indevidamente. O repositório aplica; este módulo escolhe.

Espelha `src/meta_ads/reconcile.py`, com uma diferença deliberada: aqui não há
`unreachable`. No Meta, `su_reachable` separa "saiu da parceria" de "SU não
atribuído" — duas ações humanas diferentes.

Sondado em 2026-09-05 (Task 0): `customer_manager_link.status` é GAQL válida e
devolve estados reais — em 3 das 26 contas ativas, o vínculo com o nosso MCC
(`6436352492`) saiu `ACTIVE` nas três. O único `INACTIVE` observado é vínculo com
um MCC ALHEIO (`5971862342`), que não nos diz nada. Nenhum `PENDING` apareceu.

Isto NÃO prova que `PENDING` não exista: são 3 de 26, e o que decidiria é
consultar `customer_client` a partir do MCC, alcance que o job tem e a sessão
não. Se algum dia entrar no inventário conta que ninguém consegue ler, o campo
`unreachable` entra aqui — com a evidência na mão, não por analogia com o Meta.
"""

import math
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class InventoryRow:
    customer_id: str
    is_active: bool
    missed_syncs: int


@dataclass(frozen=True, slots=True)
class Plan:
    to_add: list[str] = field(default_factory=list)
    to_bump: list[str] = field(default_factory=list)
    to_remove: list[str] = field(default_factory=list)
    to_reset: list[str] = field(default_factory=list)
    blocked_reason: str | None = None


def build_plan(
    *,
    mcc_ids: set[str],
    inventory: list[InventoryRow],
    complete: bool,
    threshold: int = 3,
    max_removal_ratio: float = 0.2,
    max_removal_abs: int = 5,
) -> Plan:
    """(MCC, inventário) → plano. Aditivo sempre; destrutivo só com leitura completa."""
    ativos = [r for r in inventory if r.is_active]
    ids_ativos = {r.customer_id for r in ativos}

    to_add = sorted(mcc_ids - ids_ativos)
    to_reset = sorted(r.customer_id for r in ativos if r.missed_syncs and r.customer_id in mcc_ids)

    if not complete:
        # Metade da lista não sustenta "esta conta saiu do MCC".
        return Plan(to_add=to_add, to_reset=to_reset, blocked_reason="leitura incompleta")

    ausentes = [r for r in ativos if r.customer_id not in mcc_ids]
    # missed_syncs conta as ausências ANTERIORES; esta execução é a próxima.
    remover = sorted(r.customer_id for r in ausentes if r.missed_syncs + 1 >= threshold)
    marcar = sorted(r.customer_id for r in ausentes if r.missed_syncs + 1 < threshold)

    # `max(1, ...)`: sem o piso, inventário pequeno zera o teto (2 ativas → 20% →
    # floor 0) e o guard barraria ATÉ a saída de uma conta só. O guard existe
    # contra remoção em massa, não contra o caso normal.
    teto = max(1, min(max_removal_abs, math.floor(len(ativos) * max_removal_ratio)))
    if remover and len(remover) > teto:
        return Plan(
            to_add=to_add,
            to_reset=to_reset,
            blocked_reason=(
                f"remocao em massa barrada: {len(remover)} contas de {len(ativos)} ativas "
                f"(teto {teto})"
            ),
        )

    return Plan(to_add=to_add, to_bump=marcar, to_remove=remover, to_reset=to_reset)
