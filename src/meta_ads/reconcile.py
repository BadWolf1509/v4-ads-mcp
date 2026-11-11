"""Decide o que reconciliar. Puro de propósito: nenhuma I/O entra aqui.

Separar decisão de efeito é o que torna testável a única parte que pode revogar
acesso indevidamente. O repositório aplica; este módulo escolhe.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

from src.reconciliacao import LinhaNeutra, plano_neutro


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


def build_plan(
    *,
    partnership_ids: set[str],
    refused_ids: set[str],
    inventory: list[InventoryRow],
    complete: bool,
    now: datetime,
    threshold: int = 3,
    max_removal_ratio: float = 0.2,
    max_removal_abs: int = 5,
) -> Plan:
    """(parceria, recusas medidas, inventário, instante) → plano.

    Aditivo sempre; destrutivo só com leitura completa e dentro do teto.

    `now` é o instante da EXECUÇÃO, o MESMO que o job lê uma vez e passa a
    `apply_absences`. Obrigatório de propósito: com default o call-site que o
    esquecesse voltaria em silêncio a somar `+1` por execução, que é o defeito
    que este parâmetro existe para fechar (a família F150/F151 — caminho não
    tratado que três revisões deixam passar porque revisão lê o código
    ESCRITO).

    Adaptador: a regra (carência, retry do mesmo dia, teto, leitura incompleta)
    mora em `src.reconciliacao.plano_neutro`, a MESMA do Google. Aqui ficam a
    tradução de `InventoryRow` (colunas de `meta_ad_accounts`), os limites
    default e a única diferença deliberada entre os dois lados: `unreachable`,
    que sai em TODO plano — inclusive o barrado.
    """
    # T3c (revisão de branch): o sinal da §3 é `in_partnership ∧ recusada` —
    # sem interseção com o inventário. Intersectar com `ids_ativos` (lido ANTES
    # do upsert) apagaria justamente a conta nova-e-recusada: ela entra por
    # `to_add` no mesmo ciclo, e o audit reportaria `unreachable: 0` no dia 1.
    # (Os dois casos de produção que a motivaram, `CA - V4 Lima Soares` e
    # `CHUTE 07`, eram artefato do índice — F154.)
    #
    # F154: `refused_ids` sao as RECUSAS medidas pela sonda (`meta_ads.alcance`), nao o
    # complemento de um indice. `parceria - alcancadas` punha no sinal tambem o que nao foi
    # lido — a CHUTE 07, lida pelo system user e ausente de `/me/adaccounts`, saia como
    # inalcancavel todo dia. Conta nao medida fica fora: nao medido nao e resposta.
    unreachable = sorted(partnership_ids & refused_ids)
    p = plano_neutro(
        presentes=partnership_ids,
        inventario=[
            LinhaNeutra(
                conta=r.ad_account_id,
                is_active=r.is_active,
                missed_syncs=r.missed_syncs,
                fuso=r.timezone_name,
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
    # Plano barrado (leitura incompleta ou remoção em massa) já vem do núcleo sem
    # to_bump/to_remove; `unreachable` entra igual nos dois casos — um bloqueio
    # não deixa de medir a recusa (`test_plano_barrado_do_meta_carrega_unreachable`).
    return Plan(
        to_add=p.to_add,
        to_bump=p.to_bump,
        to_remove=p.to_remove,
        to_reset=p.to_reset,
        unreachable=unreachable,
        blocked_reason=p.blocked_reason,
    )
