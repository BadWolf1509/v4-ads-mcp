"""Janela de cada preset: uma regra só para o Google e a Meta (F195).

O `LAST_N_DAYS` das tools Meta terminava HOJE, com o dia corrente pela metade; o do Google
terminava ontem. Mesmo nome de preset, janelas deslocadas de um dia — e no comparativo do
overview Meta o sinal da variação invertia (medido em 27/09 na MI Imports: gasto −19,6% onde
os 7 dias cheios davam +1,14%). As duas pontas passam a delegar para `src.janelas`; a
paridade abaixo é o guard de que não divergem de novo, por qualquer caminho.
"""

from datetime import date

import pytest

from src.google_ads.queries._common import parse_date_range
from src.meta_ads.account_overview import resolve_meta_date_window

# Os presets que as tools Meta aceitam (o enum dos input schemas das 5 tools de métrica).
_PRESETS_META = (
    "TODAY",
    "YESTERDAY",
    "LAST_7_DAYS",
    "LAST_14_DAYS",
    "LAST_30_DAYS",
    "LAST_90_DAYS",
)
# Viradas de mês e de ano, uma segunda-feira, um domingo, fevereiro.
_HOJES = (
    date(2026, 9, 27),
    date(2026, 9, 28),
    date(2026, 10, 1),
    date(2026, 1, 1),
    date(2026, 3, 1),
)


@pytest.mark.parametrize("hoje", _HOJES)
@pytest.mark.parametrize("preset", _PRESETS_META)
def test_meta_e_google_resolvem_o_mesmo_preset_na_mesma_janela(preset: str, hoje: date) -> None:
    meta = resolve_meta_date_window(preset, None, None, hoje)
    assert meta == parse_date_range(preset, today=hoje), (preset, hoje, meta)


def test_last_n_days_sao_os_n_dias_completos_ate_ontem_como_na_propria_meta() -> None:
    """A regra da própria Meta, sondada em 27/09 na Cheiro | Conta 01 (fuso da conta,
    America/Sao_Paulo): `date_preset=last_7d` devolveu 20/09–26/09 e `last_30d`,
    28/08–26/09; `today`, 27/09–27/09."""
    hoje = date(2026, 9, 27)
    assert resolve_meta_date_window("LAST_7_DAYS", None, None, hoje) == (
        date(2026, 9, 20),
        date(2026, 9, 26),
    )
    assert resolve_meta_date_window("LAST_30_DAYS", None, None, hoje) == (
        date(2026, 8, 28),
        date(2026, 9, 26),
    )
    assert resolve_meta_date_window("TODAY", None, None, hoje) == (hoje, hoje)


def test_preset_desconhecido_e_value_error_que_a_tool_ja_trata() -> None:
    """As tools Meta capturam `ValueError` e devolvem erro legível; `KeyError` escapava."""
    with pytest.raises(ValueError, match="LAST_8_DAYS"):
        resolve_meta_date_window("LAST_8_DAYS", None, None, date(2026, 9, 27))
