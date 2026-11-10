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
        [Linha("a"), Linha("b", faltas=9)],
        {"a", "nova"},
        completo=False,
    ),
    Cenario(
        "remocao_em_massa_acima_do_teto",
        _muitas(10, ausentes=3, faltas=2),
        {f"c{i:02d}" for i in range(7)},
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


@pytest.mark.parametrize("cenario", CENARIOS, ids=lambda c: c.nome)
def test_mesma_entrada_mesmo_plano(cenario: Cenario) -> None:
    g = _plano_google(cenario)
    m = _plano_meta(cenario)
    assert _campos(g) == _campos(m)
    assert m.unreachable == []


# Cada cenário tem de exercitar um ramo DIFERENTE: se dois dessem o mesmo plano,
# um deles não estaria provando nada. O plano esperado vai explícito.
ESPERADO = {
    "conta_nova": (["nova"], [], [], [], None),
    "ausencia_dentro_da_carencia": ([], ["b"], [], [], None),
    "ausencia_que_cruza_a_carencia": ([], [], ["b"], [], None),
    "retry_no_mesmo_dia_do_limiar": ([], ["b"], [], [], None),
    "volta_depois_de_ausencia": ([], [], [], ["a"], None),
    "leitura_incompleta": (["nova"], [], [], [], "leitura incompleta"),
    "remocao_em_massa_acima_do_teto": (
        [],
        [],
        [],
        [],
        "remocao em massa barrada: 3 contas de 10 ativas (teto 2)",
    ),
    "piso_do_teto_com_inventario_de_1": ([], [], ["a"], [], None),
    "fuso_none": ([], ["b"], [], [], None),
}


@pytest.mark.parametrize("cenario", CENARIOS, ids=lambda c: c.nome)
def test_plano_esperado_de_cada_cenario(cenario: Cenario) -> None:
    assert _campos(_plano_google(cenario)) == ESPERADO[cenario.nome]
