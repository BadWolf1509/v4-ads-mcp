"""Monitoramento como código: modelos versionados, plano e aplicação (scripts/infra/monitoramento.py)."""

from __future__ import annotations

import json

import pytest

from scripts.infra.monitoramento import carregar_modelos, contem, renderizar

VALORES = {
    "PROJECT": "proj-x",
    "HOST": "h.run.app",
    "CHANNEL": "projects/proj-x/notificationChannels/1",
    "CHECK_ID": "chk-1",
    "EMAIL": "a@b.c",
}


def test_modelos_tem_os_9_recursos() -> None:
    m = carregar_modelos()
    assert [len(m[k]) for k in ("canal", "uptime", "metricas", "policies")] == [1, 1, 2, 5]


def test_renderizados_sem_marcador_nem_projeto_antigo() -> None:
    texto = json.dumps(renderizar(carregar_modelos(), VALORES))
    for marcador in VALORES:
        assert "{" + marcador + "}" not in texto
    assert "v4-ads-mcp-299432068772" not in texto
    assert "projects/v4-ads-mcp/" not in texto
    assert "IWQz5PfF6KU" not in texto
    assert "fluxo-certo-ads" not in texto, "valor do projeto vivo vazou para o modelo"


def test_modelos_sem_campos_de_saida() -> None:
    texto = json.dumps(carregar_modelos())
    assert '"creationRecord"' not in texto
    assert '"mutationRecord"' not in texto
    for p in carregar_modelos()["policies"]:
        assert "name" not in p
        assert all("name" not in c for c in p["conditions"])


def test_rate_limit_so_em_policy_de_log() -> None:
    for p in carregar_modelos()["policies"]:
        if "notificationRateLimit" in p.get("alertStrategy", {}):
            assert all("conditionMatchedLog" in c for c in p["conditions"])


def test_marcador_sobrando_levanta() -> None:
    with pytest.raises(ValueError, match="CHANNEL"):
        renderizar({"x": ["ok", "{CHANNEL}"]}, {})


def test_renderizar_troca_dentro_de_listas_e_dicts() -> None:
    assert renderizar({"a": ["{HOST}/x"], "b": {"c": "{PROJECT}"}}, VALORES) == {
        "a": ["h.run.app/x"],
        "b": {"c": "proj-x"},
    }


def test_contem_ignora_campos_extras_do_servidor() -> None:
    assert contem({"a": 1, "l": [{"b": 2}]}, {"a": 1, "z": 9, "l": [{"b": 2, "name": "n"}]})


def test_contem_detecta_valor_e_tamanho_de_lista_diferentes() -> None:
    assert not contem({"a": 1}, {"a": 2})
    assert not contem({"l": [1, 2]}, {"l": [1]})
    assert not contem({"a": 1}, {})
    assert not contem({"a": {"b": 1}}, {"a": 1})
