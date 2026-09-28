"""F141 em `get_budget_pacing`: a projecao mensal usava o dia UTC.

`days_elapsed = today.day` com `today` em UTC. Numa conta UTC-3, entre 21h e
meia-noite do ultimo dia do mes, o servidor ja esta no dia 1 do mes seguinte:
`days_elapsed` vira 1, `days_in_month` vira o do mes novo, e a projecao
(`mtd / days_elapsed * days_in_month`) explode — gasto de 31 dias projetado
como se fosse de um. Toda noite, fora dessa borda, o `days_elapsed` fica um a
mais e a projecao sai ~1/dia-do-mes menor do que deveria.

Nao usa `resolve_date_window` (nao tem preset), por isso escapou da lista dos
22 — mesma classe, mesmo fix: `today` vem do chamador, no fuso da conta.

Desde o F199 a projecao usa os dias FECHADOS (`today.day - 1`, ate ontem), e na borda
o dia UTC errado apaga a projecao (dia 1 nao tem dia fechado) em vez de multiplica-la.
"""

from __future__ import annotations

from datetime import date

from src.mcp.tools.get_budget_pacing import _project

LINHA = {
    "campaign_id": "1",
    "campaign_name": "c",
    "daily_budget_brl": 100.0,
    "delivery_method": "STANDARD",
    "cost_micros": 3_000_000_000,  # R$ 3.000 nos 30 dias fechados
}


def test_ultimo_dia_do_mes_na_conta_nao_vira_dia_um_do_servidor() -> None:
    """31/08 na conta: 30 dias fechados a R$ 100, projecao R$ 3.100 (31 dias)."""
    (c,) = _project([LINHA], today=date(2026, 8, 31))
    assert c["days_elapsed"] == 30
    assert c["days_remaining"] == 1
    assert c["projected_monthly_brl"] == 3100.0


def test_dia_um_do_servidor_apaga_a_projecao() -> None:
    """O que o dia UTC faria com o dado de 31/08 as 21h30 da conta: sem dia fechado."""
    (c,) = _project([LINHA], today=date(2026, 9, 1))
    assert c["days_elapsed"] == 0
    assert c["projected_monthly_brl"] is None


def test_project_exige_today() -> None:
    import pytest

    with pytest.raises(TypeError):
        _project([LINHA])  # type: ignore[call-arg]
