"""Helpers HTMX do painel: detecção, toast e fechamento de mutação (Task F1)."""

import json

import pytest
from starlette.requests import Request

from src.web.routes._shared import eh_htmx, resposta_hx, toast_trigger


def _req(**headers: str) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "POST", "headers": raw, "query_string": b""})


def _hx(valor: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "headers": [(b"hx-request", valor.encode())],
            "query_string": b"",
        }
    )


def test_eh_htmx_so_com_true():
    assert eh_htmx(_hx("true")) is True
    assert eh_htmx(_hx("false")) is False
    assert eh_htmx(_req()) is False


def test_toast_trigger_escapa_aspas_e_acento():
    bruto = toast_trigger('Sessão "revogada".', "error")
    bruto.encode("latin-1")  # header seguro
    assert json.loads(bruto) == {"toast": {"message": 'Sessão "revogada".', "kind": "error"}}
    assert json.loads(toast_trigger("ok"))["toast"]["kind"] == "success"


def test_resposta_hx_refresh_sem_toast():
    r = resposta_hx(_hx("true"), destino="/x")
    assert r.status_code == 204
    assert r.headers["HX-Refresh"] == "true"
    assert "HX-Redirect" not in r.headers
    assert "HX-Trigger" not in r.headers


def test_resposta_hx_redirect_com_toast():
    r = resposta_hx(_hx("true"), destino="/x?y=1", hx="redirect", toast="Feito.")
    assert r.status_code == 204
    assert r.headers["HX-Redirect"] == "/x?y=1"
    assert "HX-Refresh" not in r.headers
    assert json.loads(r.headers["HX-Trigger"])["toast"]["message"] == "Feito."


@pytest.mark.parametrize("req", [_req(), _hx("false")])
def test_resposta_hx_sem_htmx_e_303_para_destino(req):
    r = resposta_hx(req, destino="/x?ok=1", toast="ignorado")
    assert r.status_code == 303
    assert r.headers["location"] == "/x?ok=1"
    assert "HX-Trigger" not in r.headers
