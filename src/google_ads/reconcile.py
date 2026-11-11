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

from dataclasses import dataclass, field
from datetime import date, datetime

from src.reconciliacao import LinhaNeutra, plano_neutro


@dataclass(frozen=True, slots=True)
class InventoryRow:
    customer_id: str
    is_active: bool
    missed_syncs: int
    # C4/F141: `build_plan` NÃO lê este campo — ele viaja junto do inventário
    # porque quem aplica a ausência precisa saber em que dia ela caiu, e o dia é
    # propriedade da CONTA. Resolvê-lo por `resolve_account_today` seria uma
    # leitura por conta, cada uma adquirindo uma segunda conexão do pool
    # (`run_with_reconnect`) DENTRO da transação já aberta da reconciliação.
    # Default nulo porque o plano é indiferente a ele; que o produtor real
    # (`list_inventory_rows`) sempre o preencha é o que o teste prende.
    time_zone: str | None = None
    # C4, segunda metade: este campo `build_plan` LÊ. `missed_syncs` conta as
    # ausências JÁ GRAVADAS, e desde o C4 o `UPDATE` é idempotente por dia —
    # então "esta execução ainda não está no contador" deixou de ser verdade
    # num retry do mesmo dia. `last_missed_on` é o que distingue os dois casos,
    # e por isso viaja junto do contador: sem ele a decisão é cega ao retry.
    # Default nulo pelo mesmo motivo do fuso (construtores posicionais dos
    # unit tests); quem preenche de verdade é `list_inventory_rows`.
    last_missed_on: date | None = None


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
    now: datetime,
    threshold: int = 3,
    max_removal_ratio: float = 0.2,
    max_removal_abs: int = 5,
) -> Plan:
    """(MCC, inventário, instante) → plano. Aditivo sempre; destrutivo só com leitura completa.

    Adaptador: a regra (carência, retry do mesmo dia, teto, leitura incompleta)
    mora em `src.reconciliacao.plano_neutro`, a MESMA do Meta. Aqui só a tradução
    de `InventoryRow` (colunas de `google_ads_accounts`) e os limites default.

    `now` é o instante da EXECUÇÃO, o MESMO que o job lê uma vez e passa a
    `apply_absences`. Obrigatório de propósito: com default o call-site que o
    esquecesse voltaria em silêncio a somar `+1` por execução, que é o defeito
    que este parâmetro existe para fechar (a família F150/F151 — caminho não
    tratado que três revisões deixam passar porque revisão lê o código
    ESCRITO).
    """
    p = plano_neutro(
        presentes=mcc_ids,
        inventario=[
            LinhaNeutra(
                conta=r.customer_id,
                is_active=r.is_active,
                missed_syncs=r.missed_syncs,
                fuso=r.time_zone,
                last_missed_on=r.last_missed_on,
            )
            for r in inventory
        ],
        complete=complete,
        now=now,
        threshold=threshold,
        max_removal_ratio=max_removal_ratio,
        max_removal_abs=max_removal_abs,
    )
    return Plan(
        to_add=p.to_add,
        to_bump=p.to_bump,
        to_remove=p.to_remove,
        to_reset=p.to_reset,
        blocked_reason=p.blocked_reason,
    )
