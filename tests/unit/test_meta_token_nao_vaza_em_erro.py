"""F190: o token de system user nao pode alcancar NENHUM sink de erro.

O SDK `facebook_business` assa o token na query string de toda requisicao
(`FacebookSession.__init__` faz `self.requests.params.update({'access_token': ...})`,
sem opt-out). `errors.py::to_friendly_meta_error` interpola `str(e)` cru no ramo
de fallback, que e justamente o ramo de TODA falha de transporte. O `str()` de uma
excecao de `requests`/`httpx` carrega a URL inteira.

Resultado: um soluco de rede manda o token para TRES destinos de uma vez —
`audit_log` (coluna TEXT no Postgres), Cloud Logging, e o envelope de erro que
chega ao contexto do LLM e a transcricao do chat. E o token que NAO expira e
alcanca ~24 contas de anuncio.

**Por que tres asserções e nao uma:** os tres sinks recebem o mesmo
`friendly.message` hoje, mas isso e coincidencia de implementacao, nao contrato.
Um refactor que formate o log separadamente reabriria o vazamento por um lado so
— e cobrir um lado so foi exatamente como o F82 ficou meio fechado.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

SENTINELA = "SENTINELA_TOKEN_NAO_E_SEGREDO"


def _pool() -> MagicMock:
    conn = AsyncMock()
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    return pool


async def _falha_de_transporte_carregando_o_token() -> tuple[str, list[Any], list[Any]]:
    """Roda o executor contra um transporte que levanta com o token na mensagem.

    Devolve `(mensagem_amigavel, kwargs_do_audit, eventos_de_log)`.

    F190/Task 3 (21/09): a falha nascia de `build_meta_api` mockado — depois da
    troca de transporte esse nome nem existe mais em `reports`. O acionador
    agora e um `httpx.MockTransport` cujo handler levanta a mesma excecao de
    antes. Com header auth a URL de verdade NUNCA carrega o token (essa e a
    invariante que a Task 3 fecha por construcao) — esta falha aqui e
    FABRICADA de proposito, pra provar que a redacao (defesa em profundidade)
    segura mesmo se um token aparecer por outro caminho que ninguem previu. As
    TRES assercoes dos testes abaixo e o SENTINELA ficam identicos; só a forma
    de acionar a falha muda.
    """
    from src.meta_ads import reports

    # A forma REAL da excecao: o transporte falha e a URL — com a query string —
    # vem dentro da mensagem. E assim que requests e httpx reportam.
    url_com_token = (
        f"https://graph.facebook.com/v22.0/act_1/insights?access_token={SENTINELA}&level=campaign"
    )
    erro = ConnectionError(f"Max retries exceeded with url: {url_com_token}")

    def _handler_que_falha(_request: httpx.Request) -> httpx.Response:
        raise erro

    audit_chamadas: list[Any] = []
    eventos: list[Any] = []

    async def _audit(_conn: Any, **kwargs: Any) -> int:
        audit_chamadas.append(kwargs)
        return 1

    def _warning(evento: str, **kwargs: Any) -> None:
        eventos.append({"evento": evento, **kwargs})

    log_falso = MagicMock()
    log_falso.warning = _warning
    log_falso.info = MagicMock()

    transporte = httpx.MockTransport(_handler_que_falha)
    cliente_real = httpx.AsyncClient(transport=transporte, timeout=reports._TIMEOUT_GRAPH)

    with (  # noqa: SIM117
        patch.object(reports.httpx, "AsyncClient", MagicMock(return_value=cliente_real)),
        patch.object(
            reports.manager_meta_account_access,
            "can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch.object(reports.connection, "get_pool", return_value=_pool()),
        patch.object(reports.audit_log, "record", _audit),
        patch.object(reports, "log", log_falso),
    ):
        with pytest.raises(Exception) as capturado:  # noqa: PT011 — tipo vem do modulo
            await reports.run_meta_graph_get(
                manager_id=uuid4(),
                session_id=uuid4(),
                ad_account_id="act_1",
                edge="/act_1/insights",
                params={"level": "campaign"},
                operation_name="meta_get_campaign_performance",
                audit_this_call=True,
            )

    mensagem = getattr(capturado.value, "message", str(capturado.value))
    return mensagem, audit_chamadas, eventos


@pytest.mark.asyncio
async def test_o_token_nao_aparece_na_mensagem_do_gestor() -> None:
    mensagem, _, _ = await _falha_de_transporte_carregando_o_token()
    assert SENTINELA not in mensagem, (
        "o token vazou na mensagem que chega ao gestor e ao contexto do LLM. "
        "`to_friendly_meta_error` interpola `str(e)` cru, e o `str()` de uma falha "
        "de transporte carrega a URL com a query string (F190)."
    )


@pytest.mark.asyncio
async def test_o_token_nao_aparece_no_audit_log() -> None:
    """Sink SEPARADO da mensagem, e o mais duradouro: coluna TEXT no Postgres."""
    _, audit_chamadas, _ = await _falha_de_transporte_carregando_o_token()
    assert audit_chamadas, (
        "piso de nao-vacuidade: o audit nao foi chamado, entao este teste nao "
        "afirmou nada sobre ele. Com `audit_this_call=True` e um erro, tem de haver "
        "exatamente uma escrita."
    )
    texto = repr(audit_chamadas)
    assert SENTINELA not in texto, (
        "o token vazou para o `audit_log` — a coluna e TEXT e a linha fica. "
        "Redigir so a mensagem do gestor nao fecha este sink (F190)."
    )


@pytest.mark.asyncio
async def test_o_token_nao_aparece_no_log_estruturado() -> None:
    """Terceiro sink: Cloud Logging, onde a retencao e longa e o acesso e amplo."""
    _, _, eventos = await _falha_de_transporte_carregando_o_token()
    assert eventos, (
        "piso de nao-vacuidade: nenhum evento de log foi emitido, entao este teste "
        "nao afirmou nada. O caminho de erro tem de logar."
    )
    texto = repr(eventos)
    assert SENTINELA not in texto, (
        "o token vazou para o log estruturado (Cloud Logging). Terceiro sink (F190)."
    )


def test_o_redator_preserva_o_nome_do_parametro_e_o_resto_da_url() -> None:
    """Redigir o par inteiro esconderia a ocorrencia; queremos saber QUE havia token.

    E o controle do lado oposto: a parte nao-sensivel da URL tem de sobreviver,
    senao a mensagem de erro perde o diagnostico junto com o segredo.
    """
    from src.meta_ads.errors import _redigir

    redigido = _redigir(
        f"url: https://graph.facebook.com/v22.0/act_1/insights"
        f"?access_token={SENTINELA}&level=campaign&limit=5"
    )
    assert SENTINELA not in redigido
    assert "access_token=<REDIGIDO>" in redigido
    assert "level=campaign" in redigido, "a parte diagnostica da URL tem de sobreviver"
    assert "limit=5" in redigido


def test_o_redator_cobre_appsecret_proof() -> None:
    """O SDK injeta os DOIS sem opt-out; redigir so um deixa o outro passar."""
    from src.meta_ads.errors import _redigir

    redigido = _redigir(f"?access_token={SENTINELA}&appsecret_proof=abc123def&x=1")
    assert "abc123def" not in redigido
    assert "appsecret_proof=<REDIGIDO>" in redigido
    assert "x=1" in redigido


def test_o_redator_nao_mexe_em_texto_sem_credencial() -> None:
    """Controle negativo: sem isto, um redator que devolvesse "" passaria em tudo."""
    from src.meta_ads.errors import _redigir

    limpo = "Erro Meta API (100/None): Tried accessing nonexisting field (ad_id)"
    assert _redigir(limpo) == limpo


def test_o_redator_cobre_aspas_coladas_e_formato_json() -> None:
    """F190 round 1: a primeira versao do regex so conhecia `nome=valor` sem
    aspas coladas — e essas TRES formas reais vazavam contra ela:

    - `access_token="X"`: a aspa colada no `=` fazia o `[^&\\s"']+` falhar de
      cara (o primeiro char depois do `=` ja era aspa, que a classe nega).
    - `{"access_token": "X"}`: JSON usa `:`, e o regex antigo so conhecia `=`.
    - `{'client_secret': 'X'}`: mesma lacuna do `:`, e aspa simples nem era
      cogitada.

    O contrato e esta lista de casos, nao o regex — cada forma tem de perder
    o valor E manter o nome do parametro (senao o log perde o diagnostico
    junto com o segredo).
    """
    from src.meta_ads.errors import _redigir

    caso_aspas_coladas = f'access_token="{SENTINELA}"'
    redigido = _redigir(caso_aspas_coladas)
    assert SENTINELA not in redigido, f"vazou em aspas coladas: {redigido!r}"
    assert redigido == 'access_token="<REDIGIDO>"'

    caso_json_aspas_duplas = f'{{"access_token": "{SENTINELA}"}}'
    redigido = _redigir(caso_json_aspas_duplas)
    assert SENTINELA not in redigido, f"vazou em JSON aspas duplas: {redigido!r}"
    assert redigido == '{"access_token": "<REDIGIDO>"}'

    caso_json_aspas_simples = f"{{'client_secret': '{SENTINELA}'}}"
    redigido = _redigir(caso_json_aspas_simples)
    assert SENTINELA not in redigido, f"vazou em JSON/repr aspas simples: {redigido!r}"
    assert redigido == "{'client_secret': '<REDIGIDO>'}"


def test_o_redator_cobre_o_token_no_header_authorization() -> None:
    """Onda final F190: o redator era CEGO a forma que a propria branch criou.

    `_PARAMS_SENSIVEIS` cobre `nome=valor` / `{"nome": "valor"}` — a forma de
    QUERY STRING, que era o mundo ANTES da troca de transporte. A Task 3 pos o
    token em `Authorization: Bearer <token>`, e as formas abaixo passavam
    INALTERADAS pelo redator (medido contra o codigo pre-fix). A camada 2
    existe pra cobrir o caminho que ninguem previu, e estava cega ao caminho
    que a camada 1 tinha acabado de criar.

    Cada forma tem de perder o VALOR e manter o nome do cabecalho E o esquema
    (`Bearer`) — mesmo contrato dos casos de query string acima: quem le o log
    precisa saber QUE tipo de credencial estava ali.
    """
    from src.meta_ads.errors import _redigir

    formas = {
        "cabecalho cru": f"Authorization: Bearer {SENTINELA}",
        "cabecalho minusculo": f"authorization: Bearer {SENTINELA}",
        "dict repr (aspas simples)": f"{{'authorization': 'Bearer {SENTINELA}'}}",
        "dict JSON (aspas duplas)": f'{{"Authorization": "Bearer {SENTINELA}"}}',
    }
    for rotulo, texto in formas.items():
        redigido = _redigir(texto)
        assert SENTINELA not in redigido, f"vazou em {rotulo}: {redigido!r}"
        assert "Bearer <REDIGIDO>" in redigido, (
            f"{rotulo}: o esquema tem de sobreviver junto com o nome — veio {redigido!r}"
        )

    # O nome do cabecalho sobrevive inteiro, nas duas caixas.
    assert _redigir(f"Authorization: Bearer {SENTINELA}") == "Authorization: Bearer <REDIGIDO>"
    assert (
        _redigir(f"{{'authorization': 'Bearer {SENTINELA}'}}")
        == "{'authorization': 'Bearer <REDIGIDO>'}"
    )


def test_o_reflexo_obvio_de_por_authorization_na_lista_de_nomes_deixaria_o_token() -> None:
    """Contraprova do DESENHO, nao do resultado: por que ancorar no esquema.

    O reflexo obvio seria acrescentar `authorization` a alternacao de nomes de
    `_PARAMS_SENSIVEIS`. Medido, isso produz `Authorization: <REDIGIDO>
    <token>`: a classe de valor daquele regex (`[^&\\s"']+`) para no primeiro
    espaco, entao ela redige o literal "Bearer" e deixa o TOKEN INTEIRO passar
    — pior que nao cobrir, porque o `<REDIGIDO>` no meio da linha PARECE
    cobertura.

    Este teste reconstroi o regex ingenuo e assere que ele vaza, e depois que o
    redator de verdade nao vaza sobre a MESMA entrada. Sem ele, nada distingue
    "o valor sumiu" de "alguma coisa sumiu" — a asserção `"<REDIGIDO>" in
    resultado` passaria nos dois casos, inclusive no que vaza.
    """
    import re

    from src.meta_ads.errors import _redigir

    ingenuo = re.compile(
        r"(access_token|appsecret_proof|client_secret|authorization)"
        r"([\"']?\s*[:=]\s*[\"']?)"
        r"[^&\s\"']+",
        re.IGNORECASE,
    )
    entrada = f"Authorization: Bearer {SENTINELA}"
    vazado = ingenuo.sub(r"\1\2<REDIGIDO>", entrada)

    assert "<REDIGIDO>" in vazado, "premissa do controle invalida: o regex ingenuo nem casou"
    assert SENTINELA in vazado, (
        "premissa deste teste invalida: o regex ingenuo deveria DEIXAR o token. "
        "Se ele passou a cobrir, a ancora no esquema virou redundante e este "
        "teste precisa ser reescrito, nao apagado."
    )
    assert SENTINELA not in _redigir(entrada), (
        "o redator de verdade tem de fechar a forma que o ingenuo deixa aberta"
    )


def test_o_redator_cobre_client_secret_isolado() -> None:
    """O brief nomeia tres parametros obrigatorios (access_token, appsecret_proof,
    client_secret); so os dois primeiros tinham teste dedicado ate agora.
    `client_secret` aparece no fluxo OAuth (troca de `code` por token), nao no
    SDK — cobrir em isolamento, no mesmo padrao do teste de appsecret_proof.
    """
    from src.meta_ads.errors import _redigir

    redigido = _redigir(
        f"POST https://graph.facebook.com/v22.0/oauth/access_token"
        f"?client_id=123456&client_secret={SENTINELA}&redirect_uri=https://x"
    )
    assert SENTINELA not in redigido
    assert "client_secret=<REDIGIDO>" in redigido
    assert "client_id=123456" in redigido, "parametro nao-sensivel tem de sobreviver"
    assert "redirect_uri=https://x" in redigido, "parametro nao-sensivel tem de sobreviver"
