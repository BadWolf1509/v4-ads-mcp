"""F141 em `get_budget_pacing`: a projecao mensal usava o dia UTC.

`days_elapsed = today.day` com `today` em UTC. Numa conta UTC-3, entre 21h e
meia-noite do ultimo dia do mes, o servidor ja esta no dia 1 do mes seguinte:
`days_elapsed` vira 1, `days_in_month` vira o do mes novo, e a projecao
(`mtd / days_elapsed * days_in_month`) explode — gasto de 31 dias projetado
como se fosse de um. Toda noite, fora dessa borda, o `days_elapsed` fica um a
mais e a projecao sai ~1/dia-do-mes menor do que deveria.

Nao usa `resolve_date_window` (nao tem preset), por isso escapou da lista dos
22 — mesma classe, mesmo fix: `today` vem do chamador, no fuso da conta.
"""

from __future__ import annotations

from datetime import date

from src.mcp.tools.get_budget_pacing import _project

LINHA = {
    "campaign_id": "1",
    "campaign_name": "c",
    "daily_budget_brl": 100.0,
    "delivery_method": "STANDARD",
    "cost_micros_today": 3_100_000_000,  # R$ 3.100 no mes
}


def test_ultimo_dia_do_mes_na_conta_nao_vira_dia_um_do_servidor() -> None:
    """31/08 na conta: 31 dias corridos, projecao = MTD. Com o dia 1 UTC, seria 31x."""
    (c,) = _project([LINHA], today=date(2026, 8, 31))
    assert c["days_elapsed"] == 31
    assert c["days_remaining"] == 0
    assert c["projected_monthly_brl"] == 3100.0


def test_dia_um_projeta_trinta_vezes() -> None:
    """O que o servidor UTC fazia com o dado de 31/08 as 21h30 da conta."""
    (c,) = _project([LINHA], today=date(2026, 9, 1))
    assert c["days_elapsed"] == 1
    assert c["projected_monthly_brl"] == 3100.0 * 30


def test_project_exige_today() -> None:
    import pytest

    with pytest.raises(TypeError):
        _project([LINHA])  # type: ignore[call-arg]
