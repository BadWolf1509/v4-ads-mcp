"""Paridade das duas regras de reconciliação (Google × Meta).

As duas decidem quais contas PERDEM acesso e hoje são cópias uma da outra
(`_faltas_com_esta_execucao`, o teto `max(1, min(abs, floor(n * ratio)))`). Este
teste é a rede de quem for extrair o núcleo comum: a mesma situação, montada nos
dois, tem de dar o mesmo plano. Divergência aqui é uma das duas regras mudando de
comportamento em silêncio — e o que muda é quem perde acesso.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest

from src.google_ads import reconcile as google
from src.meta_ads import reconcile as meta

# 00:30 UTC = 21:30 do dia anterior em America/Sao_Paulo: o dia da CONTA (02/09)
# difere do dia UTC (03/09), que é a janela onde o retry do mesmo dia erra.
AGORA = datetime(2026, 9, 3, 0, 30, tzinfo=UTC)
HOJE_NA_CONTA = date(2026, 9, 2)
HOJE_UTC = date(2026, 9, 3)
SP = "America/Sao_Paulo"


@dataclass(frozen=True)
class Linha:
    id: str
    ativo: bool = True
    faltas: int = 0
    fuso: str | None = SP
    ultima_falta: date | None = None


@dataclass(frozen=True)
class Cenario:
    nome: str
    linhas: list[Linha]
    na_origem: set[str]
    completo: bool = True


def _muitas(n: int, *, ausentes: int, faltas: int) -> list[Linha]:
    """`n` ativas; as `ausentes` últimas não estão na origem (ver `na_origem`)."""
    return [Linha(f"c{i:02d}", faltas=faltas if i >= n - ausentes else 0) for i in range(n)]


def _massa() -> list[Linha]:
    """10 ativas: c00 volta (to_reset), c01..c04 ausentes, 3 delas além da carência."""
    return [
        Linha("c00", faltas=1),
        Linha("c01"),
        Linha("c02", faltas=2),
        Linha("c03", faltas=2),
        Linha("c04", faltas=2),
        *[Linha(f"c{i:02d}") for i in range(5, 10)],
    ]


CENARIOS = [
    Cenario("conta_nova", [Linha("a")], {"a", "nova"}),
    Cenario("ausencia_dentro_da_carencia", [Linha("a"), Linha("b", faltas=0)], {"a"}),
    Cenario("ausencia_que_cruza_a_carencia", [Linha("a"), Linha("b", faltas=2)], {"a"}),
    Cenario(
        "retry_no_mesmo_dia_do_limiar",
        [Linha("a"), Linha("b", faltas=2, ultima_falta=HOJE_NA_CONTA)],
        {"a"},
    ),
    Cenario("volta_depois_de_ausencia", [Linha("a", faltas=2)], {"a"}),
    Cenario(
        "leitura_incompleta",
        [Linha("a", faltas=1), Linha("b", faltas=9)],
        {"a", "nova"},
        completo=False,
    ),
    Cenario(
        "remocao_em_massa_acima_do_teto",
        _massa(),
        {"c00", "c05", "c06", "c07", "c08", "c09", "nova"},
    ),
    # 30 ativas, 6 ausentes além da carência: floor(30*0.2)=6, mas o teto
    # absoluto (5) vence o percentual. Só aqui `max_removal_abs` decide.
    Cenario(
        "teto_absoluto_vence_o_percentual",
        _muitas(30, ausentes=6, faltas=2),
        {f"c{i:02d}" for i in range(24)},
    ),
    # Inativas: a que está na origem vira to_add; a ausente não é marcada nem
    # removida. 4 inativas inflam o inventário para 10: quem contasse inativa
    # em `len(ativos)` daria teto 2 (não 1) e deixaria de barrar as 2 remoções.
    Cenario(
        "inativas_nao_contam_no_teto_nem_viram_falta",
        [
            *[Linha(i) for i in ("a", "b", "c", "d")],
            Linha("e", faltas=2),
            Linha("f", faltas=2),
            Linha("x1", ativo=False),
            Linha("y1", ativo=False, faltas=2),
            Linha("y2", ativo=False, faltas=2),
            Linha("y3", ativo=False),
        ],
        {"a", "b", "c", "d", "x1"},
    ),
    Cenario(
        "inativa_ausente_nao_marca_nem_remove",
        [Linha("a"), Linha("y", ativo=False, faltas=2), Linha("z", ativo=False)],
        {"a", "x"},
    ),
    # Falta de ONTEM no fuso da conta: não é retry, então a ausência de hoje soma.
    Cenario(
        "ultima_falta_ontem_nao_e_retry",
        [Linha("a"), Linha("b", faltas=2, ultima_falta=date(2026, 9, 1))],
        {"a"},
    ),
    # Ids fora de ordem alfabética na inserção: sem `sorted()` o plano sai trocado.
    Cenario(
        "ordenacao_com_varios_em_cada_lista",
        [
            *[Linha(f"c{i:02d}") for i in range(15)],
            Linha("zb"),
            Linha("zr", faltas=2),
            Linha("zv", faltas=1),
            Linha("mb"),
            Linha("mr", faltas=2),
            Linha("mv", faltas=1),
        ],
        {f"c{i:02d}" for i in range(15)} | {"zv", "mv", "zn", "mn"},
    ),
    Cenario("piso_do_teto_com_inventario_de_1", [Linha("a", faltas=2)], set()),
    # `last_missed_on` == dia UTC com fuso None: o fallback é UTC, então o retry
    # é reconhecido (2 faltas, não 3) e a conta só é marcada, não removida.
    Cenario(
        "fuso_none",
        [Linha("a"), Linha("b", faltas=2, fuso=None, ultima_falta=HOJE_UTC)],
        {"a"},
    ),
]


def _plano_google(c: Cenario) -> google.Plan:
    inv = [
        google.InventoryRow(
            customer_id=r.id,
            is_active=r.ativo,
            missed_syncs=r.faltas,
            time_zone=r.fuso,
            last_missed_on=r.ultima_falta,
        )
        for r in c.linhas
    ]
    return google.build_plan(mcc_ids=c.na_origem, inventory=inv, complete=c.completo, now=AGORA)


def _plano_meta(c: Cenario) -> meta.Plan:
    inv = [
        meta.InventoryRow(
            ad_account_id=r.id,
            is_active=r.ativo,
            missed_syncs=r.faltas,
            timezone_name=r.fuso,
            last_missed_on=r.ultima_falta,
        )
        for r in c.linhas
    ]
    return meta.build_plan(
        partnership_ids=c.na_origem,
        refused_ids=set(),
        inventory=inv,
        complete=c.completo,
        now=AGORA,
    )


def _campos(p: google.Plan | meta.Plan) -> tuple[object, ...]:
    return (p.to_add, p.to_bump, p.to_remove, p.to_reset, p.blocked_reason)


# Aqui `refused_ids=set()` fixa `unreachable` em []: o campo só existe no Meta, e o
# plano BARRADO (que nenhum outro teste cobre) é guardado em
# `test_plano_barrado_do_meta_carrega_unreachable`, logo abaixo.
@pytest.mark.parametrize("cenario", CENARIOS, ids=lambda c: c.nome)
def test_mesma_entrada_mesmo_plano(cenario: Cenario) -> None:
    g = _plano_google(cenario)
    m = _plano_meta(cenario)
    assert _campos(g) == _campos(m)
    assert m.unreachable == []


_POR_NOME = {c.nome: c for c in CENARIOS}


# O plano barrado do Meta tem de levar `unreachable`: é o sinal de conta recusada,
# e um bloqueio (leitura incompleta, remoção em massa) não deixa de medi-la. As
# recusas incluem uma conta já no inventário, uma conta NOVA (em `to_add` no mesmo
# ciclo) e uma fora da parceria, que não entra no sinal.
@pytest.mark.parametrize("nome", ["leitura_incompleta", "remocao_em_massa_acima_do_teto"])
def test_plano_barrado_do_meta_carrega_unreachable(nome: str) -> None:
    c = _POR_NOME[nome]
    existente = sorted(c.na_origem - {"nova"})[0]
    refused_ids = {existente, "nova", "fora_da_parceria"}
    inv = [
        meta.InventoryRow(
            ad_account_id=r.id,
            is_active=r.ativo,
            missed_syncs=r.faltas,
            timezone_name=r.fuso,
            last_missed_on=r.ultima_falta,
        )
        for r in c.linhas
    ]
    m = meta.build_plan(
        partnership_ids=c.na_origem,
        refused_ids=refused_ids,
        inventory=inv,
        complete=c.completo,
        now=AGORA,
    )
    assert m.blocked_reason is not None
    assert "nova" in m.to_add
    assert m.unreachable == sorted(c.na_origem & refused_ids)
    assert m.unreachable == sorted([existente, "nova"])


# Cada cenário tem de exercitar um ramo DIFERENTE: se dois dessem o mesmo plano,
# um deles não estaria provando nada. O plano esperado vai explícito.
ESPERADO = {
    "conta_nova": (["nova"], [], [], [], None),
    "ausencia_dentro_da_carencia": ([], ["b"], [], [], None),
    "ausencia_que_cruza_a_carencia": ([], [], ["b"], [], None),
    "retry_no_mesmo_dia_do_limiar": ([], ["b"], [], [], None),
    "volta_depois_de_ausencia": ([], [], [], ["a"], None),
    "leitura_incompleta": (["nova"], [], [], ["a"], "leitura incompleta"),
    # O plano barrado não carrega `to_bump` (o `Plan` do bloqueio só leva
    # to_add/to_reset), então só esses dois são observáveis aqui.
    "remocao_em_massa_acima_do_teto": (
        ["nova"],
        [],
        [],
        ["c00"],
        "remocao em massa barrada: 3 contas de 10 ativas (teto 2)",
    ),
    "teto_absoluto_vence_o_percentual": (
        [],
        [],
        [],
        [],
        "remocao em massa barrada: 6 contas de 30 ativas (teto 5)",
    ),
    "inativas_nao_contam_no_teto_nem_viram_falta": (
        ["x1"],
        [],
        [],
        [],
        "remocao em massa barrada: 2 contas de 6 ativas (teto 1)",
    ),
    "inativa_ausente_nao_marca_nem_remove": (["x"], [], [], [], None),
    "ultima_falta_ontem_nao_e_retry": ([], [], ["b"], [], None),
    "ordenacao_com_varios_em_cada_lista": (
        ["mn", "zn"],
        ["mb", "zb"],
        ["mr", "zr"],
        ["mv", "zv"],
        None,
    ),
    "piso_do_teto_com_inventario_de_1": ([], [], ["a"], [], None),
    "fuso_none": ([], ["b"], [], [], None),
}


@pytest.mark.parametrize("cenario", CENARIOS, ids=lambda c: c.nome)
def test_plano_esperado_de_cada_cenario(cenario: Cenario) -> None:
    assert _campos(_plano_google(cenario)) == ESPERADO[cenario.nome]


# O mesmo esperado, LITERAL, do lado Meta. A paridade acima já o implica, mas só
# por transitividade: se as duas regras mudassem juntas (o risco de um núcleo
# comum), a paridade seguiria verde. Aqui o texto de cada `blocked_reason` do
# Meta fica preso byte a byte, independente do Google.
@pytest.mark.parametrize("cenario", CENARIOS, ids=lambda c: c.nome)
def test_plano_esperado_de_cada_cenario_no_meta(cenario: Cenario) -> None:
    assert _campos(_plano_meta(cenario)) == ESPERADO[cenario.nome]
