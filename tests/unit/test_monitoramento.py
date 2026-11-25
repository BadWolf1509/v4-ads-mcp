"""Monitoramento como código: modelos versionados, plano e aplicação (scripts/infra/monitoramento.py)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from scripts.infra.monitoramento import (
    aplicar,
    carregar_modelos,
    codigo_de_saida,
    contem,
    renderizar,
)

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


# --- Task 2: plano e aplicação sobre API injetável -------------------------------------------

ARGS: dict[str, Any] = {"project_id": "p", "host": "h.run.app", "alert_email": "e@x.com"}


class FakeApi:
    """Em memória, imitando o servidor: `criar` gera `name` e acrescenta campos que o modelo não tem."""

    def __init__(self) -> None:
        self.dados: dict[str, list[dict[str, Any]]] = {
            "notificationChannels": [],
            "uptimeCheckConfigs": [],
            "metrics": [],
            "alertPolicies": [],
        }
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def listar(self, recurso: str) -> list[dict[str, Any]]:
        return [json.loads(json.dumps(r)) for r in self.dados[recurso]]

    def criar(self, recurso: str, corpo: dict[str, Any]) -> dict[str, Any]:
        self.posts.append((recurso, corpo))
        real: dict[str, Any] = json.loads(json.dumps(corpo))
        n = len(self.dados[recurso]) + 1
        if recurso == "notificationChannels":
            real["name"] = f"projects/p/notificationChannels/{n}"
            real["verificationStatus"] = "X"
        elif recurso == "uptimeCheckConfigs":
            real["name"] = f"projects/p/uptimeCheckConfigs/chk-{n}"
            real["isInternal"] = False
        elif recurso == "alertPolicies":
            real["name"] = f"projects/p/alertPolicies/{n}"
            for i, c in enumerate(real["conditions"]):
                c["name"] = f"{real['name']}/conditions/{i}"
        self.dados[recurso].append(real)
        return real


def test_projeto_vazio_dry_run_planeja_9_criar_e_nao_posta() -> None:
    api = FakeApi()
    linhas = aplicar(api, **ARGS, apply=False)
    assert [linha.acao for linha in linhas] == ["criar"] * 9
    assert api.posts == []
    assert codigo_de_saida(linhas) == 0


def test_apply_cria_9_e_segunda_rodada_e_toda_igual() -> None:
    api = FakeApi()
    assert [linha.acao for linha in aplicar(api, **ARGS, apply=True)] == ["criado"] * 9
    assert [linha.acao for linha in aplicar(api, **ARGS, apply=True)] == ["igual"] * 9
    assert len(api.posts) == 9


def test_ordem_canal_uptime_metricas_policies() -> None:
    api = FakeApi()
    aplicar(api, **ARGS, apply=True)
    assert [r for r, _ in api.posts] == (
        ["notificationChannels", "uptimeCheckConfigs"] + ["metrics"] * 2 + ["alertPolicies"] * 5
    )


def test_policies_apontam_o_canal_e_o_check_criados() -> None:
    api = FakeApi()
    aplicar(api, **ARGS, apply=True)
    canal = api.dados["notificationChannels"][0]["name"]
    check = api.dados["uptimeCheckConfigs"][0]["name"].rsplit("/", 1)[1]
    assert all(p["notificationChannels"] == [canal] for p in api.dados["alertPolicies"])
    up = next(p for p in api.dados["alertPolicies"] if p["displayName"].startswith("Uptime"))
    assert check in up["conditions"][0]["conditionThreshold"]["filter"]
    assert api.dados["notificationChannels"][0]["labels"]["email_address"] == "e@x.com"


def test_canal_existente_e_reusado_pelas_policies() -> None:
    api = FakeApi()
    api.dados["notificationChannels"].append(
        {
            "type": "email",
            "displayName": "Wellington (e-mail)",
            "labels": {"email_address": "e@x.com"},
            "name": "projects/p/notificationChannels/77",
        }
    )
    linhas = aplicar(api, **ARGS, apply=True)
    assert linhas[0].acao == "igual"
    assert all(
        p["notificationChannels"] == ["projects/p/notificationChannels/77"]
        for p in api.dados["alertPolicies"]
    )


def test_diferente_nao_e_tocado_e_sai_1() -> None:
    api = FakeApi()
    aplicar(api, **ARGS, apply=True)
    api.dados["alertPolicies"][0]["enabled"] = False
    linhas = aplicar(api, **ARGS, apply=True)
    assert [linha.acao for linha in linhas].count("diferente") == 1
    assert len(api.posts) == 9
    assert api.dados["alertPolicies"][0]["enabled"] is False
    assert codigo_de_saida(linhas) == 1


# --- Task 3: cliente REST e CLI ----------------------------------------------------------------


class _Resp:
    def __init__(self, corpo: dict[str, Any]) -> None:
        self._b = json.dumps(corpo).encode()

    def read(self) -> bytes:
        return self._b

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def test_rest_listar_segue_paginacao_e_trata_chave_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.infra import monitoramento as mon

    pedidos: list[Any] = []
    paginas: list[dict[str, Any]] = [
        {"alertPolicies": [{"displayName": "a"}], "nextPageToken": "T2"},
        {"alertPolicies": [{"displayName": "b"}]},
        {},  # projeto sem nenhum canal: a API omite a chave
    ]

    def fake_urlopen(req: Any, timeout: float) -> _Resp:
        pedidos.append(req)
        return _Resp(paginas.pop(0))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    api = mon.RestApi("proj-x", "tok")
    assert [p["displayName"] for p in api.listar("alertPolicies")] == ["a", "b"]
    assert "pageToken=T2" in pedidos[1].full_url
    assert pedidos[0].get_header("X-goog-user-project") == "proj-x"
    assert api.listar("notificationChannels") == []


def test_rest_metricas_vao_para_o_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.infra import monitoramento as mon

    urls: list[str] = []

    def fake_urlopen(req: Any, timeout: float) -> _Resp:
        urls.append(req.full_url)
        return _Resp({})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    mon.RestApi("proj-x", "tok").listar("metrics")
    assert urls[0].startswith("https://logging.googleapis.com/v2/projects/proj-x/metrics")


def test_main_dry_run_nao_posta(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.infra import monitoramento as mon

    api = FakeApi()
    monkeypatch.setattr(mon, "_api_real", lambda project_id, email: api)
    rc = mon.main(["--project-id", "p", "--host", "h", "--alert-email", "e@x.com"])
    assert rc == 0
    assert api.posts == []
    assert capsys.readouterr().out.count("criar") == 9
