"""Recomendação aceita à mão pelo app sai igual a edição manual (spec 2026-10-05, §3.5).

Sondado em 05/10 no `change_event` da MO-JP (03/10 17:43, `acabadora de piso` e `locação de
sapinho`): `client_type: GOOGLE_ADS_MOBILE_APP`, o e-mail do gestor, `changed_fields` de qualquer
criação de keyword — nenhum campo de origem. As duas tools que leem o `change_event` dizem isso.
"""

import pytest

from src.mcp.tools._registry import get_tool, import_all_tools


@pytest.mark.parametrize("nome", ["detect_drift", "get_change_history"])
def test_a_description_diz_que_a_aceita_pelo_app_e_indistinguivel(nome: str) -> None:
    import_all_tools()
    t = get_tool(nome)
    assert t is not None
    d = t.description
    assert "Recomendacao aceita a mao pelo APP" in d
    assert "GOOGLE_ADS_MOBILE_APP" in d
    assert "nenhum campo do change_event a distingue" in d
    assert "web" not in d.lower().split("recomendacao aceita a mao")[1][:200]
