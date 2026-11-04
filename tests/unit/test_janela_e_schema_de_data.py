"""`propriedades_de_data` e `janela_da_conta` (src/mcp/tools/_common.py, Task G2).

O trio date_range/start_date/end_date estava copiado em cada tool, e o `hoje` +
`resolve_date_window` repetido em cada handler. Os dois helpers sao o corpo unico.
O contrato que o cliente MCP ve fica preso por `test_schemas_snapshot.py`; aqui se
prende o helper em si: o schema canonico literal e a janela resolvida no `hoje` da
CONTA (F141), nunca no relogio do servidor.
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.google_ads.queries._common import EntradaInvalidaError, InvalidDateRangeError
from src.janelas import PRESETS, PRESETS_EM_ORDEM
from src.mcp.tools._common import janela_da_conta, propriedades_de_data

_PADRAO = r"^\d{4}-\d{2}-\d{2}$"

# O trio literal que as tools canonicas expunham antes do helper (fixture da G1).
_CANONICO = {
    "date_range": {
        "type": "string",
        "enum": [
            "TODAY",
            "YESTERDAY",
            "LAST_7_DAYS",
            "LAST_14_DAYS",
            "LAST_30_DAYS",
            "LAST_90_DAYS",
            "THIS_MONTH",
            "LAST_MONTH",
            "THIS_WEEK",
            "LAST_WEEK",
        ],
        "default": "LAST_30_DAYS",
        "description": "Periodo via preset. Para periodo custom, use start_date+end_date.",
    },
    "start_date": {
        "type": "string",
        "pattern": _PADRAO,
        "description": (
            "Data inicial YYYY-MM-DD inclusive. Quando informado junto com end_date, "
            "sobrepoe date_range preset. Obriga end_date."
        ),
    },
    "end_date": {
        "type": "string",
        "pattern": _PADRAO,
        "description": "Data final YYYY-MM-DD inclusive. Obrigatorio se start_date informado.",
    },
}


def test_presets_em_ordem_e_o_mesmo_conjunto_de_presets():
    assert frozenset(PRESETS_EM_ORDEM) == PRESETS
    assert len(PRESETS_EM_ORDEM) == len(PRESETS)


def test_propriedades_de_data_padrao_e_o_trio_canonico():
    assert propriedades_de_data() == _CANONICO


def test_propriedades_de_data_respeita_default_e_ordem_dos_presets():
    props = propriedades_de_data(default="LAST_7_DAYS", presets=("LAST_90_DAYS", "LAST_7_DAYS"))
    assert props["date_range"]["default"] == "LAST_7_DAYS"
    assert props["date_range"]["enum"] == ["LAST_90_DAYS", "LAST_7_DAYS"]


def test_propriedades_de_data_recusa_default_fora_dos_presets():
    with pytest.raises(ValueError, match="LAST_2_DAYS"):
        propriedades_de_data(default="LAST_2_DAYS")


def test_propriedades_de_data_devolve_copias_independentes():
    a = propriedades_de_data()
    a["date_range"]["enum"].append("X")
    a["start_date"]["pattern"] = "mudou"
    assert propriedades_de_data() == _CANONICO


class _Relogio:
    """Stub do `resolve_account_today`: conta as chamadas e devolve um dia fixo."""

    def __init__(self, hoje: date) -> None:
        self.hoje = hoje
        self.chamadas: list[str] = []

    async def __call__(self, customer_id: str, *, now: object = None) -> date:
        self.chamadas.append(customer_id)
        return self.hoje


_CTX = SimpleNamespace(manager_id=None, session_id=None)


async def test_janela_da_conta_resolve_preset_no_hoje_da_conta():
    relogio = _Relogio(date(2026, 5, 15))
    with patch("src.mcp.tools._common.resolve_account_today", relogio):
        inicio, fim, hoje = await janela_da_conta(_CTX, {"date_range": "LAST_7_DAYS"}, "1234567890")
    assert (inicio, fim, hoje) == (date(2026, 5, 8), date(2026, 5, 14), date(2026, 5, 15))
    assert relogio.chamadas == ["1234567890"]


async def test_janela_da_conta_usa_o_default_sem_date_range():
    relogio = _Relogio(date(2026, 5, 15))
    with patch("src.mcp.tools._common.resolve_account_today", relogio):
        inicio, fim, _ = await janela_da_conta(_CTX, {}, "1234567890", default="LAST_7_DAYS")
        inicio30, fim30, _ = await janela_da_conta(_CTX, {}, "1234567890")
    assert (inicio, fim) == (date(2026, 5, 8), date(2026, 5, 14))
    assert (inicio30, fim30) == (date(2026, 4, 15), date(2026, 5, 14))


async def test_janela_da_conta_custom_sobrepoe_o_preset():
    relogio = _Relogio(date(2026, 5, 15))
    args = {"date_range": "LAST_90_DAYS", "start_date": "2026-05-01", "end_date": "2026-05-03"}
    with patch("src.mcp.tools._common.resolve_account_today", relogio):
        inicio, fim, hoje = await janela_da_conta(_CTX, args, "1234567890")
    assert (inicio, fim, hoje) == (date(2026, 5, 1), date(2026, 5, 3), date(2026, 5, 15))


@pytest.mark.parametrize(
    ("args", "trecho"),
    [
        ({"start_date": "2026-13-01", "end_date": "2026-05-03"}, "Data invalida"),
        ({"start_date": "2026-05-04", "end_date": "2026-05-03"}, "e depois de end_date"),
        ({"start_date": "2026-05-01"}, "end_date e obrigatorio"),
        ({"date_range": "ONTEM"}, "desconhecido"),
    ],
)
async def test_janela_da_conta_recusa_entrada_invalida_com_a_mensagem_de_sempre(args, trecho):
    relogio = _Relogio(date(2026, 5, 15))
    with (
        patch("src.mcp.tools._common.resolve_account_today", relogio),
        pytest.raises(InvalidDateRangeError, match=trecho) as exc,
    ):
        await janela_da_conta(_CTX, args, "1234567890")
    assert isinstance(exc.value, EntradaInvalidaError)
