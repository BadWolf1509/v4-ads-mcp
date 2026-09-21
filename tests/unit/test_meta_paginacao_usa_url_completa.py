"""F189: seguir `paging.next` exige passar a URL como STRING, nao dentro de lista.

O SDK instalado documenta o contrato no proprio docstring de
`FacebookAdsApi.call`: *"path: A tuple of path tokens **or a full URL string**"*,
e ramifica em `isinstance(path, six.string_types)`. Com lista ele toma o ramo
"nao e caminho completo" e monta `GRAPH/vXX/<a-url-inteira-aqui>` — a URL sai
dobrada, o `level` se perde no caminho e a Graph API responde
`(#100) Tried accessing nonexisting field (ad_id)`.

Medido em producao em 2026-09-21, conta `act_4051924171730156` (17 anuncios),
mesma janela, isolando a paginacao com um anuncio de diferenca:

| `limit` | paginas necessarias | resultado          |
|---------|---------------------|--------------------|
| 17      | 1                   | 200, 17 linhas     |
| 16      | 2                   | erro (#100)        |

## Por que o guard que ja existia nao pegou

`test_meta_pagination_and_ranking.py` cobre a paginacao desde o F88 e passou
verde o tempo inteiro, porque o fake era:

    def fake_call(method: str, path: list[str], params): ...  # devolve por contagem

Ele nunca olha `path` — lista ou string dao o mesmo verde. E a anotacao
`path: list[str]` **codifica a convencao errada**, que o `CLAUDE.md` classifica
como pior que teste ausente. Um mock que nao consegue expressar o bug nao e
cobertura, e a familia F84/F89.

## O irmao certo mora no repo

`src/meta_ads/graph.py` segue `paging.next` passando a URL como string pro
httpx. Duas implementacoes de paginacao, uma certa e uma errada — o contraste e
que torna este guard obvio depois de escrito.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

_PROXIMA = "https://graph.facebook.com/v23.0/act_1/insights?after=cursor123&level=campaign"


def _pagina(rows: list[dict[str, Any]], proxima: str | None) -> dict[str, Any]:
    corpo: dict[str, Any] = {"data": rows}
    if proxima:
        corpo["paging"] = {"next": proxima}
    return corpo


def _pool() -> MagicMock:
    conn = AsyncMock()
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    return pool


async def _rodar(max_pages: int) -> tuple[dict[str, Any], list[Any]]:
    """Roda o executor com um fake que REGISTRA o `path` de cada chamada."""
    from src.meta_ads import reports

    paginas = [
        _pagina([{"campaign_id": "a", "spend": "10"}], _PROXIMA),
        _pagina([{"campaign_id": "b", "spend": "5"}], None),
    ]
    caminhos: list[Any] = []

    def fake_call(method: str, path: Any, params: dict[str, Any]) -> MagicMock:
        caminhos.append(path)
        resp = MagicMock()
        resp.json = MagicMock(return_value=paginas[min(len(caminhos) - 1, len(paginas) - 1)])
        resp.headers = MagicMock(return_value={})
        return resp

    api = MagicMock()
    api.call = fake_call

    with (
        patch.object(reports, "build_meta_api", MagicMock(return_value=api)),
        patch.object(
            reports.manager_meta_account_access,
            "can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch.object(reports.connection, "get_pool", return_value=_pool()),
        patch.object(reports.audit_log, "record", AsyncMock(return_value=1)),
    ):
        corpo = await reports.run_meta_graph_get(
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_1",
            edge="/act_1/insights",
            params={"level": "campaign"},
            operation_name="meta_get_campaign_performance",
            max_pages=max_pages,
        )
    return corpo, caminhos


@pytest.mark.asyncio
async def test_a_pagina_seguinte_recebe_a_url_como_string() -> None:
    """A invariante. Vermelho contra `api.call("GET", [proxima], ...)`.

    O piso de nao-vacuidade vem antes da assercao: sem as DUAS chamadas nao houve
    paginacao nenhuma, e um `assert` sobre `caminhos[1]` que nunca roda passaria
    por nao ter olhado nada — a forma mais silenciosa de um guard morrer.
    """
    _, caminhos = await _rodar(max_pages=5)

    assert len(caminhos) == 2, (
        f"a paginacao nao rodou: {len(caminhos)} chamada(s). Sem seguir o "
        "`paging.next` este guard nao afirma nada sobre a forma do `path`."
    )
    assert isinstance(caminhos[1], str), (
        "a chamada que segue `paging.next` passou `path` como "
        f"{type(caminhos[1]).__name__}, nao `str`. O SDK ramifica em "
        "`isinstance(path, six.string_types)`: com nao-string ele concatena na "
        "URL base e produz `graph.facebook.com/vXX/https://graph.facebook.com/...` "
        "— a Graph API recusa com (#100). Passe `proxima`, nao `[proxima]` (F189)."
    )


@pytest.mark.asyncio
async def test_a_url_seguinte_e_a_do_paging_next_intacta() -> None:
    """Nao basta ser string: tem de ser A URL que o Meta mandou.

    Sem esta, `str(["..."])` ou qualquer derivacao passariam no teste irmao —
    seria asserir o ADJACENTE (o tipo) em vez da invariante (o destino).
    """
    _, caminhos = await _rodar(max_pages=5)

    assert len(caminhos) == 2, "sem a segunda chamada nao ha URL de paginacao para conferir"
    assert caminhos[1] == _PROXIMA, (
        f"a segunda chamada foi para {caminhos[1]!r}, nao para a URL que o Meta "
        f"devolveu em `paging.next` ({_PROXIMA!r}). O `next` ja carrega cursor, "
        "fields e token — qualquer remontagem perde algum deles."
    )


@pytest.mark.asyncio
async def test_a_primeira_chamada_segue_usando_token_de_caminho() -> None:
    """Controle: a PRIMEIRA chamada nao e URL completa, e nao pode virar uma.

    Sem este, "passe sempre string" seria satisfeito mandando a edge crua como
    string — o SDK trataria `/act_1/insights` como URL absoluta e a requisicao
    iria para lugar nenhum. O contrato tem dois lados, e o guard cobra os dois.
    """
    _, caminhos = await _rodar(max_pages=1)

    assert len(caminhos) == 1, "com max_pages=1 o executor faz exatamente uma chamada"
    assert not isinstance(caminhos[0], str), (
        f"a primeira chamada passou `path` como str ({caminhos[0]!r}); ela tem de "
        "ser sequencia de tokens para o SDK montar a URL sobre a base do Graph."
    )


def test_o_teto_de_paginas_e_um_porque_o_truncated_depende_disso() -> None:
    """A honestidade do `truncated` repousa neste 1 — entao ele fica preso aqui.

    O executor devolve `rows[:limit]` e calcula `truncated` a partir do
    `paging.next` da ULTIMA pagina lida. Sao duas perguntas diferentes, e elas so
    coincidem enquanto o teto for UMA pagina: a API devolve no maximo `limit`
    linhas por pagina, entao o corte vira no-op e "sobrou `next`" e exatamente
    "ficou linha de fora".

    Com o teto em 5 (como era ate 2026-09-21) elas divergem no caso COMUM: uma
    conta com entre `limit+1` e `5*limit` entidades esgota os dados antes do
    teto, nao sobra `next`, e `truncated: false` sai depois de `rows[:limit]`
    ter descartado ate `4*limit` linhas. O sinal afirma "nada ficou de fora"
    tendo deixado.

    **Se voce esta subindo este numero**, o `truncated` tem de passar a ver o
    corte local no mesmo commit — algo como `next_existe or len(antes) > limit`.
    Subir so o teto reintroduz o F189 pela porta dos fundos, e nenhum outro
    teste deste repo pega isso.
    """
    from src.mcp.tools._meta_performance import _MAX_PAGES

    assert _MAX_PAGES == 1, (
        f"_MAX_PAGES virou {_MAX_PAGES}. Com mais de uma pagina o `rows[:limit]` "
        "passa a descartar linhas que o `truncated` nao enxerga (ele so le "
        "`paging.next`), e a description promete o contrario. Leia a docstring: "
        "subir o teto exige corrigir o `truncated` no mesmo commit."
    )
