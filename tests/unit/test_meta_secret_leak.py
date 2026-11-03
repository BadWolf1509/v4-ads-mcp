"""F82: segredo do Meta nao pode chegar ao Cloud Logging pela URL do request.

O httpx loga `request.url` INTEIRA — com query string — em `logger.info`
(`httpx/_client.py`, "HTTP Request: %s %s ..."). `configure_logging` chama
`basicConfig(level=info)` e nada silenciava o logger `httpx`, entao a URL caia
no stdout, que no Cloud Run e o Cloud Logging. O codigo Meta passava segredo em
`params=` (query string): `client_secret`, o app access token `app_id|app_secret`
e o token system-user all-targets.

Gravidade especifica deste projeto: o token system-user NAO expira e da acesso as
~19 contas do BM. No Modelo B a matriz de acesso e o unico freio e ela vive na
camada MCP — quem le o Cloud Logging contorna a matriz inteira sem passar por
gate nenhum.

Camadas cobertas aqui:
1. o logger do httpx nao emite INFO (mata a classe, inclusive pra call-sites
   que ainda carregam segredo na URL);
2. (removida em 11/2026) a troca short->long-lived mandava o `client_secret` no
   CORPO; a troca saiu com o OAuth pessoal da Meta, e com ela o unico call-site
   que enviava o `meta_app_secret` pela rede. O que resta de segredo da Meta em
   `src/auth/` e o HMAC do `signed_request` em `meta_data_deletion.py`, que nao
   faz requisicao — e segue no escopo da camada 4;
3. o token vai no header e acompanha a paginacao;
4. propriedade sobre todo arquivo de `src/meta_ads/` e `src/auth/`.

O lado Google ja era correto e serve de referencia: `data=` no POST do token e
header `Authorization: Bearer` no userinfo — nada na URL.
"""

from __future__ import annotations

import ast
import logging

import httpx
import pytest
import respx

_FAKE_APP_SECRET = "s3cr3t-do-app-que-nao-pode-vazar"  # noqa: S105 — valor de teste


def test_configure_logging_silencia_o_logger_do_httpx() -> None:
    """F82 camada 1: httpx nao pode emitir INFO — e nesse nivel que ele loga a URL."""
    from src.logging import configure_logging

    logging.getLogger("httpx").setLevel(logging.NOTSET)  # estado limpo
    configure_logging(level="info", json_output=True)

    # Nivel PROPRIO, nao o efetivo: o efetivo herda do root e passaria vazio
    # (basicConfig e no-op quando o root ja tem handler, como sob pytest). So um
    # setLevel explicito no logger `httpx` satisfaz este assert.
    assert logging.getLogger("httpx").level >= logging.WARNING, (
        "httpx loga a URL completa (com query string) em INFO — manter INFO ligado "
        "publica qualquer segredo que esteja em params= no Cloud Logging."
    )
    # httpcore so loga em DEBUG, mas LOG_LEVEL=debug e opcao real em config.py.
    assert logging.getLogger("httpcore").level >= logging.WARNING


def test_httpx_realmente_logaria_a_query_string_sem_o_silenciamento(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Prova que a ameaca e real: com INFO ligado, o segredo aparece no log record.

    Sem esta prova, o teste acima vira ritual — ninguem sabe se `httpx` de fato
    emite a URL. Aqui forcamos INFO e verificamos o vazamento.
    """
    logging.getLogger("httpx").setLevel(logging.INFO)
    try:
        with respx.mock:
            respx.get("https://graph.facebook.com/v25.0/oauth/access_token").mock(
                return_value=httpx.Response(200, json={"access_token": "x"})
            )
            with caplog.at_level(logging.INFO, logger="httpx"), httpx.Client() as client:
                client.get(
                    "https://graph.facebook.com/v25.0/oauth/access_token",
                    params={"client_secret": _FAKE_APP_SECRET},
                )
    finally:
        logging.getLogger("httpx").setLevel(logging.NOTSET)

    vazou = any(_FAKE_APP_SECRET in record.getMessage() for record in caplog.records)
    assert vazou, "premissa do F82 invalida: httpx nao esta logando a query string"


# ---------------------------------------------------------------------------
# Camada 3 (2026-08-15): o token sai da URL e vai pro header `Authorization`.
#
# Probe empirica contra o Graph real ANTES de escrever isto (scripts/
# probe_meta_auth_header.py) — a licao F53/F54/F55 e nao mexer em superficie da
# API Meta por analogia. O que ela estabeleceu:
#
#   (B) `Authorization: Bearer <token>` devolve EXATAMENTE os mesmos dados que
#       `?access_token=` — migracao segura.
#   (D) autenticando por header, o Graph NAO embute mais o token no
#       `paging.next`. Otimo pro vazamento, mas vira requisito: o header tem
#       que ir em TODA pagina, senao a 2a volta 401.
#   (G) `/debug_token` NAO aceita POST (400, code 100 subcode 33), entao o
#       `input_token` continua na query — ele nao e credencial do chamador e
#       nao cabe no header. O que sai de la e o `app_id|app_secret`, que e o
#       segredo permanente.
# ---------------------------------------------------------------------------

_FAKE_SU_TOKEN = "system-user-token-que-nao-expira"  # noqa: S105 — valor de teste


@pytest.mark.asyncio
@respx.mock
async def test_header_acompanha_a_paginacao_ate_o_fim() -> None:
    """F82 + (D): o `next` vem SEM token; sem o header a 2a pagina daria 401.

    Este e o teste que o probe tornou obrigatorio — antes dele eu ia reescrever
    a URL do `next` pra tirar o token, que e o oposto do que o Graph faz. Mira o
    paginador (`fetch_paginated`) desde o F197 — o wrapper de `/me/adaccounts`
    que ele exercitava saiu, e a parceria do BM pagina pelo mesmo caminho.
    """
    from src.meta_ads.client import META_GRAPH_API_VERSION
    from src.meta_ads.graph import fetch_paginated

    edge = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/619664032237208/client_ad_accounts"
    proxima = f"{edge}?after=cursor2&fields=id"
    respx.get(edge).mock(
        side_effect=[
            httpx.Response(200, json={"data": [{"id": "act_1"}], "paging": {"next": proxima}}),
            httpx.Response(200, json={"data": [{"id": "act_2"}], "paging": {}}),
        ]
    )

    async with httpx.AsyncClient() as http:
        resultado = await fetch_paginated(
            http, edge, access_token=_FAKE_SU_TOKEN, params={"fields": "id"}
        )

    assert [c["id"] for c in resultado.rows] == ["act_1", "act_2"]
    assert resultado.complete is True
    assert len(respx.calls) == 2
    for chamada in respx.calls:
        assert chamada.request.headers.get("Authorization") == f"Bearer {_FAKE_SU_TOKEN}", (
            "alguma pagina foi pedida sem o header — o `next` do Graph nao "
            "carrega mais o token quando a autenticacao vem por header"
        )
        assert _FAKE_SU_TOKEN not in str(chamada.request.url)


# ---------------------------------------------------------------------------
# Camada 4 (2026-09-21, F190 Task 5): os testes acima cobriam a invariante
# exercitando FUNÇÕES especificas do antigo `src/auth/meta_oauth.py` (removido
# em 11/2026) — nenhum deles
# toca `src/meta_ads/`. Foi assim que `reports.py` (que fala com a Graph API
# pelo SDK `facebook_business`, e o SDK assa o token na query por baixo dos
# panos) ficou fora do alcance por meses: nao havia teste que sequer abrisse
# aquele arquivo. O teste abaixo troca "um teste por funcao que eu lembrei de
# escrever" por "uma propriedade sobre todo arquivo que existe", varrendo os
# DOIS diretorios onde codigo Meta roda em vez de enumerar nomes.
# ---------------------------------------------------------------------------


def test_nenhum_caminho_meta_poe_credencial_em_query() -> None:
    """Propriedade, nao lista: TODO arquivo de `src/meta_ads/` e `src/auth/` obedece.

    A versao anterior cobria a invariante enumerando funcoes de UM arquivo
    (o antigo `meta_oauth.py`, removido em 11/2026). `reports.py` falava com a Graph API
    pelo SDK, que assa o token na query — e ficou fora do escopo por nao estar
    na lista. Guard que enumera absolve o arquivo que ninguem lembrou de
    listar, que e precisamente o arquivo onde o bug mora.

    Escopo cobre as DUAS pastas onde codigo Meta roda — `src/meta_ads/`
    (SDK/Graph/relatorios) e `src/auth/` (onde o F82 original morava, no OAuth
    pessoal removido em 11/2026, e onde o `meta_app_secret` segue em uso no
    HMAC de `meta_data_deletion.py`). Varrer so uma das duas repetiria, no eixo do escopo
    de diretorio, o mesmo defeito que esta propriedade existe para corrigir
    no eixo da lista de arquivos — por isso o piso abaixo soma as duas.

    A checagem em si mira LITERAL DE STRING (`h._literais_de_string` +
    `h._texto_logico`), nao o texto cru do arquivo inteiro. Round 1 desta
    task usava substring no arquivo inteiro e precisava de uma lista de
    isencao pra absolver `access_token=access_token` — kwarg Python passado
    pro bridge do SDK (F48) ou pro `fetch_paginated()` (que poe o valor em
    `headers=`, nunca em `params=`). Essa lista era a MESMA doenca que esta
    task existe pra curar, so que na isencao em vez do escopo: `client.py`
    ficaria absolvido de `access_token=` para sempre, inclusive se um dia
    ganhasse uma construcao de query real ao lado do kwarg ja vetado.

    Resolvido pela CONSTRUCAO, nao por lista: um kwarg (`access_token=
    access_token`) nao e literal de string nenhum — `ast` nao o enxerga como
    tal —, entao nunca aparece pra `_literais_de_string`. Um f-string real
    (`f"...?access_token={token}"`, a forma que de fato vaza) vira
    `...?access_token=X` no texto logico (`{token}` -> placeholder) e casa o
    termo. Sem lista, sem precisar saber de antemao qual arquivo faz o que —
    e sem a isencao por `_PARAMS_SENSIVEIS` do round 1: o proprio regex de
    `errors.py` e uma string concatenada (`"...client_secret)(..."`) que
    nunca contem `nome=` colado, entao nunca batia o termo e nunca precisou
    de isencao — era isencao que nao isentava nada.

    Round 2 (fix, mesmo dia) acrescentou DUAS defesas que o round 1 nao
    tinha:

    1. O piso numerico (>= 15) e um RETRATO de hoje, nao uma invariante — ele
       so pega a varredura ESVAZIANDO. Se `meta_ads/` crescer sozinho ate uns
       20 arquivos e alguem apagar o termo do `auth/` (exatamente o
       diretorio onde o F82 original morava), o total ainda passa de 15 e o
       guard volta a varrer so METADE do escopo, em silencio — o mesmo
       defeito desta task, reencarnado. Por isso a asserção abaixo AFIRMA OS
       DIRETORIOS (`{"meta_ads", "auth"}`), nao so a contagem. As duas
       ficam: uma pega o colapso pra um so lado, a outra pega a varredura
       esvaziando dentro de uma raiz que continua existindo — cobrem eixos
       diferentes.
    2. O scanner agora filtra docstring via `h._nos_de_docstring` (o mesmo
       helper que `html_em_python` usa, no harness irmao). Sem isso, prosa
       que CITA `access_token=` pra EXPLICAR o codigo — o jeito natural de
       documentar esta area depois de um incidente como o F190 — dispara
       falso positivo, e a reacao natural de quem for documentar e pedir
       isencao: a doenca que este teste inteiro existe pra extirpar.

    ⚠️ **LIMITE DECLARADO (onda final, 2026-09-21): este guard so ve LITERAL DE
    STRING — nao ve `params=`.** Medido:

        f"https://g/x?access_token={token}"           -> PEGO aqui
        http.get(url, params={"access_token": token}) -> NAO pego aqui

    E `params=` e exatamente o mecanismo que o SDK usava, ou seja: sozinho,
    este guard nao pegaria o bug do F190 escrito em codigo nosso.

    **Quem cobre isso e `tests/unit/test_no_secrets_in_query_params.py`** — e
    cobre MELHOR do que caberia aqui, verificado rodando um arquivo-probe
    contra ele: varre `src/` INTEIRO (nao so estas duas raizes), pega o dict
    inline **e** o dict montado numa variavel e passado depois (`p = {...}` …
    `params=p`), e tem allowlist que so encolhe, com guard proprio contra
    entrada obsoleta.

    Escrever um 2o eixo aqui foi TENTADO e DESFEITO na mesma sessao: era um
    duplicado estritamente mais fraco do que ja existia, e invariante com duas
    implementacoes diverge — a pergunta certa e qual e a autoritativa. Esta
    fica sendo a do literal; a de `params=` e a do arquivo irmao, que ganhou
    `appsecret_proof` e `authorization` no conjunto de chaves na mesma passada
    (eram os dois nomes desta familia que faltavam la).
    """
    from tests.unit import _guard_harness as h

    arquivos = h.fontes_py(h.SRC / "meta_ads") + h.fontes_py(h.SRC / "auth")
    # Medido em 2026-09-21: 11 arquivos .py em src/meta_ads/ + 8 em src/auth/
    # = 19. O piso fica ACIMA do maior dos dois diretorios sozinho (11): se a
    # varredura algum dia colapsar pra so `meta_ads/` (auth silenciosamente
    # cai) ou so `auth/`, o piso ainda dispara — nao so no zero absoluto que
    # `fontes_py` ja cobre via EscopoVazioError. Cobre a varredura esvaziando
    # DENTRO de uma raiz que continua existindo; NAO cobre uma raiz inteira
    # sumir enquanto a outra cresce o bastante pra compensar a contagem — e
    # pra isso que serve o assert de diretorios logo abaixo.
    assert len(arquivos) >= 15, (
        f"piso de nao-vacuidade: so {len(arquivos)} arquivos em "
        "src/meta_ads/+src/auth/ (medido em 2026-09-21: 11+8=19). O "
        "localizador parou de casar, ou o escopo colapsou pra um so "
        "diretorio, e o guard estaria absolvendo por vacuidade parcial."
    )
    # Afirma os DIRETORIOS, nao a contagem: um piso numerico sozinho expira
    # sem avisar quando `meta_ads/` (a area mais ativa do repo) crescer o
    # bastante pra compensar `auth/` sumindo do scan — e `auth/` e onde o F82
    # original morava. Verificado contra os caminhos reais que
    # `fontes_py` devolve (absolutos, resolvidos): `p.relative_to(h.SRC)` da
    # `meta_ads\arquivo.py` ou `auth\arquivo.py`, e `.parts[0]` isola a raiz.
    diretorios = {p.relative_to(h.SRC).parts[0] for p in arquivos}
    assert diretorios == {"meta_ads", "auth"}, (
        f"a varredura perdeu uma das duas raizes: achou {diretorios}. O F82 "
        "morava em `auth/` — varrer so `meta_ads/` reproduz o defeito."
    )
    # E afirma o ARQUIVO onde o segredo da Meta segue em uso em `auth/` desde
    # 11/2026: o `meta_app_secret` do HMAC do callback de exclusao. Sem isto,
    # `auth/` poderia continuar no escopo so com o OAuth do Google e o guard
    # deixaria de olhar justamente o arquivo Meta que sobrou ali.
    assert (h.SRC / "auth" / "meta_data_deletion.py").resolve() in {
        p.resolve() for p in arquivos
    }, "src/auth/meta_data_deletion.py saiu da varredura do F82"
    ofensores: list[str] = []
    for arq in arquivos:
        arv = h.arvore(arq)
        ids_docstring = h._nos_de_docstring(arv)
        for literal in h._literais_de_string(arv):
            if isinstance(literal, ast.Constant) and id(literal) in ids_docstring:
                continue  # prosa explicando o codigo, nao codigo
            texto = h._texto_logico(literal)
            for termo in ("access_token=", "appsecret_proof=", "client_secret="):
                if termo in texto:
                    ofensores.append(f"{h.rel(arq)}:{literal.lineno}: {termo}")
    # `params=` NAO e varrido aqui — e o limite declarado no docstring, coberto
    # por `test_no_secrets_in_query_params.py`, que faz isso melhor.
    assert ofensores == [], (
        "credencial montada em query string (literal de string, nao kwarg, "
        f"nao docstring) fora do redator: {ofensores}. A invariante do F82 "
        "e header, nunca query."
    )
