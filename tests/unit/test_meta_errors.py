"""Unit tests for Meta error → PT-BR friendly mapping (Sprint M.2a Task 6).

A familia de throttle do Graph e maior que o code 4.

Antes: 4 e subcode 2635 eram retryable; 17, 613 e 80004 caiam no ramo generico
com retryable=False. Throttle transitorio virava falha permanente na cara do
gestor, e nenhum caminho de retry disparava.

**F190 / onda final — o produtor mudou, o contrato nao.** Ate esta rodada, estes
testes dirigiam `FacebookRequestError`, do SDK `facebook_business`. A Task 3
trocou o transporte por `httpx` e o SDK SAIU do caminho de request: o ramo que
mapeava `FacebookRequestError` ficou **sem produtor**, com ~10 testes verdes por
cima. Um throttle Meta chegava ao gestor como JSON cru em ingles truncado em 200
chars, `retryable=False` — exatamente o estado que a PR 6 dizia ter corrigido.

A tabela curada agora mora em `_do_envelope_de_erro` e le `code`/`error_subcode`/
`message` do corpo que `MetaGraphHTTPError` carrega. **Cada codigo curado
continua tendo teste**; o que mudou foi o veiculo (`_erro(...)` monta uma
resposta HTTP real do Graph, nao um mock de SDK). Nada foi apagado pra
simplificar — os subcodes 460 e 463, que nunca tiveram teste proprio, ganharam
um de quebra pela parametrizacao sobre o frozenset inteiro.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from src.meta_ads.errors import (
    CODIGOS_DE_THROTTLE,
    SUBCODES_DE_CONEXAO_EXPIRADA,
    MetaAdsFriendlyError,
    to_friendly_meta_error,
)
from src.meta_ads.reports import MetaGraphHTTPError


def _erro(
    code: int | None = None,
    subcode: int | None = None,
    msg: str = "limite",
    *,
    status: int = 400,
) -> MetaGraphHTTPError:
    """A forma REAL do erro hoje: resposta HTTP do Graph com envelope no corpo.

    `status=400` e o default de proposito — e o que o Graph devolve pra quase
    tudo que a tabela curada classifica, inclusive throttle. Um `status` 5xx
    tornaria `retryable=True` por conta do status sozinho, e as asserções de
    `retryable is False` passariam a nao distinguir nada.
    """
    erro: dict[str, object] = {"message": msg}
    if code is not None:
        erro["code"] = code
    if subcode is not None:
        erro["error_subcode"] = subcode
    return MetaGraphHTTPError(status, json.dumps({"error": erro}))


@pytest.mark.parametrize("subcode", sorted(SUBCODES_DE_CONEXAO_EXPIRADA))
def test_conexao_expirada_manda_reconectar(subcode: int) -> None:
    """Os 4 subcodes de token invalidado server-side, nao so os 2 de antes.

    O teste anterior cobria 458 e 467 e deixava 460 e 463 sem asserção nenhuma,
    apesar de os dois estarem na tabela. Parametrizar sobre o frozenset fecha a
    lacuna e impede que ela reapareca quando alguem acrescentar um subcode.
    """
    result = to_friendly_meta_error(_erro(subcode=subcode))
    assert isinstance(result, MetaAdsFriendlyError)
    assert "expirou" in result.message.lower() or "reconecte" in result.message.lower()
    assert result.retryable is False


def test_rate_limit_subcode_2635() -> None:
    result = to_friendly_meta_error(_erro(subcode=2635))
    assert "limite" in result.message.lower()
    assert result.retryable is True


def test_rate_limit_code_4() -> None:
    result = to_friendly_meta_error(_erro(code=4))
    assert result.retryable is True


def test_permission_denied_code_190() -> None:
    result = to_friendly_meta_error(_erro(code=190))
    assert "permissão" in result.message.lower() or "permissao" in result.message.lower()
    assert result.retryable is False


def test_invalid_field_code_100() -> None:
    result = to_friendly_meta_error(_erro(code=100, msg="Field 'foo' not supported"))
    assert "campo" in result.message.lower() or "inválido" in result.message.lower()
    assert "Field 'foo' not supported" in result.message, (
        "a mensagem do Graph tem de sobreviver — e o unico diagnostico de qual campo caiu"
    )
    assert result.retryable is False


def test_unknown_falls_back_with_code_subcode() -> None:
    result = to_friendly_meta_error(_erro(code=999, subcode=888, msg="weird error"))
    assert "999" in result.message or "888" in result.message
    assert result.retryable is False


def test_non_graph_exception_falls_back() -> None:
    """Excecao que nao e do Graph (bug nosso, falha de transporte) nao some."""
    result = to_friendly_meta_error(ValueError("generic error"))
    assert "inesperado" in result.message.lower() or "generic error" in result.message
    assert result.retryable is False


@pytest.mark.parametrize("code", sorted(CODIGOS_DE_THROTTLE))
def test_toda_a_familia_de_throttle_e_retryable(code: int) -> None:
    r = to_friendly_meta_error(_erro(code))
    assert r.retryable is True, f"code {code} deveria ser retryable"
    assert "limite" in r.message.lower(), f"code {code}: mensagem nao fala de limite"


def test_subcode_2635_continua_retryable() -> None:
    assert to_friendly_meta_error(_erro(1, subcode=2635)).retryable is True


@pytest.mark.parametrize("code", [190, 100, 200, 3018])
def test_o_que_nao_e_throttle_continua_nao_retryable(code: int) -> None:
    """Contraprova: sem ela, `retryable=True` incondicional passaria verde.

    Um guard que so afirma o lado positivo nao distingue "classifica throttle"
    de "diz sim para tudo".
    """
    assert to_friendly_meta_error(_erro(code)).retryable is False


def test_throttle_em_4xx_ganha_retryable_que_o_status_sozinho_negaria() -> None:
    """O PONTO do achado, isolado: um 400 nao e retryable POR STATUS.

    Sem a tabela curada, `MetaGraphHTTPError(400, ...)` cai no ramo generico e
    devolve `retryable=False` com o JSON cru em ingles. E era exatamente isso
    que chegava ao gestor num throttle depois que o SDK saiu do caminho.
    """
    cru = MetaGraphHTTPError(400, json.dumps({"error": {"code": 4, "message": "rate"}}))
    assert cru.retryable is False, "premissa: o STATUS 400 sozinho diz nao-retryable"

    amigavel = to_friendly_meta_error(cru)
    assert amigavel.retryable is True
    assert amigavel.message == "Limite Meta atingido. Tente novamente em alguns minutos."


def test_5xx_nao_perde_retryable_para_um_code_curado_nao_retryable() -> None:
    """A uniao, do outro lado: a tabela curada pode GANHAR, nunca PERDER.

    Um 503 e transitorio por definicao, qualquer que seja o `code` que o Graph
    tenha posto no corpo. Se o mapeamento curado SUBSTITUISSE o veredito do
    status, este caso viraria `retryable=False` e o gestor desistiria de uma
    chamada que funcionaria em 30 segundos — a regressao que o F190 fechou,
    reaberta pelo outro lado.
    """
    r = to_friendly_meta_error(_erro(code=100, status=503))
    assert r.retryable is True


def test_corpo_sem_envelope_mantem_o_status_http_na_mensagem() -> None:
    """Sem `error` no corpo nao ha tabela curada — resta o status, e ele fica.

    Cobre pagina HTML de intermediario e corpo vazio: os dois casos em que o
    `code` e `None` e a unica informacao de diagnostico e o HTTP.
    """
    for corpo in ("<html><body>Bad Gateway</body></html>", "", '{"data": []}'):
        r = to_friendly_meta_error(MetaGraphHTTPError(502, corpo))
        assert "502" in r.message, f"status sumiu da mensagem para corpo {corpo!r}: {r.message!r}"
        assert r.retryable is True


def test_envelope_sobrevive_a_corpo_maior_que_o_trecho_da_mensagem() -> None:
    """Guard do motivo pelo qual a truncagem MUDOU DE LUGAR.

    O chamador passava `resp.text[:200]`. Com a truncagem antes do parse, um
    corpo mais longo que 200 chars chegava cortado no meio do JSON, `json.loads`
    falhava, e a tabela curada nunca via o `code` — o throttle voltava a ser
    JSON cru e permanente, exatamente por um caminho que nenhum teste com corpo
    curto detectaria. Hoje `MetaGraphHTTPError` recebe o corpo INTEIRO e trunca
    ela mesma so pra montar a mensagem.
    """
    longo = json.dumps({"error": {"code": 4, "message": "x" * 400}})
    assert len(longo) > 200, "premissa: o corpo tem de exceder o trecho de 200 chars"

    e = MetaGraphHTTPError(429, longo)
    assert e.code == 4, "o envelope foi perdido — a truncagem esta acontecendo antes do parse"
    assert to_friendly_meta_error(e).message == (
        "Limite Meta atingido. Tente novamente em alguns minutos."
    )


def test_errors_py_nao_depende_mais_do_sdk_facebook_business() -> None:
    """F190 / onda final: o ramo `FacebookRequestError` ficou SEM PRODUTOR.

    Com o SDK fora do caminho de request, `to_friendly_meta_error` nunca mais
    recebe um `FacebookRequestError` — o ramo era codigo morto com ~10 testes
    verdes por cima, que e pior que codigo morto porque PARECE cobertura.

    Este assert e estrutural de proposito: um `isinstance` de runtime nao
    distingue "o ramo sumiu" de "o ramo existe e ninguem o aciona neste teste".
    Se alguem reintroduzir o SDK aqui, tem de reintroduzir junto um produtor —
    e este teste obriga a conversa.
    """
    fonte = Path("src/meta_ads/errors.py").read_text(encoding="utf-8")
    assert "facebook_business" not in fonte, (
        "`errors.py` voltou a referenciar o SDK. Desde a Task 3 o transporte e "
        "httpx e o SDK nao produz excecao nenhuma no caminho de request: um "
        "ramo de `FacebookRequestError` aqui seria codigo morto com teste verde."
    )


def test_meta_graph_http_error_retryable_mesmo_sem_o_sdk_instalado() -> None:
    """F190/Task 3, fix round 1 (achado B da revisao): `MetaGraphHTTPError` nao
    tem relacao NENHUMA com o SDK `facebook_business`.

    Antes: o ramo que o mapeava vivia DEPOIS de um `try: from
    facebook_business.exceptions import ... except ImportError: return ...`. Se
    o import do SDK falhasse — ausente, quebrado, ou removido de vez — o
    `return` antecipado do `except ImportError` engolia o ramo inteiro, e um 503
    (retryable de verdade) virava "Erro inesperado" com `retryable=False`. O
    MESMO bug que a task existia pra fechar, reaberto por um caminho diferente.

    O `try/except` nao existe mais (ver o teste estrutural acima), entao o
    acoplamento que este teste perseguia e hoje impossivel POR CONSTRUCAO. Ele
    fica assim mesmo, porque a asserção de fundo — 5xx continua retryable — vale
    por si, e o `patch.dict` continua sendo o detector barato se o import do SDK
    algum dia voltar pra este modulo em posicao errada.
    """
    with patch.dict(sys.modules, {"facebook_business.exceptions": None}):
        resultado = to_friendly_meta_error(MetaGraphHTTPError(503, "Service Unavailable"))

    assert resultado.retryable is True, (
        "um MetaGraphHTTPError 5xx tem que continuar retryable mesmo quando o "
        "import do SDK falha — nenhum ramo pode ficar atras de um try/except "
        "ImportError que nao tem nada a ver com ele"
    )
    assert "503" in resultado.message
