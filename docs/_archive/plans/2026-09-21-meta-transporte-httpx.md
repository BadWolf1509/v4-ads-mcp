# Transporte Meta no httpx — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar o vazamento do token de system user Meta e remover a causa raiz, trocando o transporte de `run_meta_graph_get` do SDK `facebook_business` (token na query string) para `httpx` com autenticação por header.

**Architecture:** O SDK assa o token na query de toda requisição e `errors.py` interpola `str(e)` cru, então qualquer falha de transporte manda o token para o `audit_log`, o Cloud Logging e o contexto do LLM. A Task 2 **estanca a sangria** com redação no único ponto por onde toda exceção Meta passa; as Tasks 3–4 **removem a causa** trocando o transporte. Ordem deliberada: o primeiro commit já é seguro, mesmo que o resto demore.

**Tech Stack:** Python 3.13 · httpx (async, já usado em 3 caminhos Meta) · pytest + `unittest.mock` · structlog · asyncpg

**Spec:** [`docs/superpowers/specs/2026-09-21-meta-transporte-httpx-design.md`](../specs/2026-09-21-meta-transporte-httpx-design.md)

## Global Constraints

- **PT-BR** em toda mensagem que chega ao gestor, docstring e comentário novo.
- **Guard antes do fix**, sempre. Teste que não foi visto VERMELHO contra o código pré-fix não fecha nada (`CLAUDE.md`, teste 5 de gambiarra).
- **`python scripts/check_pre_push.py` mudo, lendo `$?`** antes de qualquer push. **Nunca** pipe entre o gate e o `&&` — o exit code do pipeline é o do último comando, e isso já deixou passar commit vermelho.
- **Nunca colar segredo em chat, log ou teste.** Os testes usam o sentinela literal `SENTINELA_TOKEN_NAO_E_SEGREDO`.
- **Não chamar SDK de ads fora de `run_blocking`** em caminho que atende request (F109) — esta mudança **elimina** a necessidade, porque httpx é async.
- Commits: `fix(meta_ads): …` / `test(meta_ads): …` / `docs(operacao): …`, com trailer `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **Branch:** `fix/f190-transporte-meta-httpx` (já criada, já contém o commit da spec).

---

### Task 1: O guard dos três sinks, visto VERMELHO

O teste central de toda a mudança. Ele aciona uma falha de transporte carregando um token-sentinela e afirma que o sentinela **não aparece em nenhum dos três destinos**: a mensagem amigável, os kwargs de `audit_log.record`, e o evento de `structlog`.

Asserir só a mensagem não basta — a escrita de auditoria é sink separado, e foi por cobrir um lado só que o F82 ficou meio fechado.

**Files:**
- Create: `tests/unit/test_meta_token_nao_vaza_em_erro.py`

**Interfaces:**
- Consumes: `src.meta_ads.reports.run_meta_graph_get` (assinatura atual, inalterada por esta task)
- Produces: nada que outra task importe. As Tasks 2 e 3 são validadas por ele.

- [ ] **Step 1: Escrever o teste que falha**

```python
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
    """
    from src.meta_ads import reports

    # A forma REAL da excecao: o transporte falha e a URL — com a query string —
    # vem dentro da mensagem. E assim que requests e httpx reportam.
    url_com_token = (
        f"https://graph.facebook.com/v22.0/act_1/insights"
        f"?access_token={SENTINELA}&level=campaign"
    )
    erro = ConnectionError(f"Max retries exceeded with url: {url_com_token}")

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

    with (
        patch.object(reports, "build_meta_api", MagicMock(side_effect=erro)),
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
```

- [ ] **Step 2: Rodar e confirmar que falha pelo motivo certo**

Run: `python -m pytest tests/unit/test_meta_token_nao_vaza_em_erro.py -q`

Expected: **3 FAILED**, cada um com sua mensagem — o sentinela presente nos três sinks. Se algum falhar com `KeyError`, `AttributeError` ou `TypeError` em vez da asserção, **o teste está quebrado, não o código**: conserte o teste antes de seguir. Vermelho que não explica é vermelho que a próxima sessão interpreta errado.

- [ ] **Step 3: Commitar o guard vermelho**

```bash
git add tests/unit/test_meta_token_nao_vaza_em_erro.py
git commit -m "test(meta_ads): F190 - guard dos tres sinks do vazamento de token

Vermelho contra o codigo atual, de proposito: o fix vem na proxima task.
Os tres sinks recebem o mesmo friendly.message hoje, mas isso e coincidencia
de implementacao, nao contrato — por isso sao tres assercoes e nao uma.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Redação em `to_friendly_meta_error` — estanca a sangria

O vazamento fecha **aqui**, antes de qualquer mudança de transporte. A redação vive dentro de `to_friendly_meta_error` e não nos call sites: é o único ponto por onde toda exceção Meta já passa, então nenhum chamador futuro precisa lembrar de aplicá-la. Mecanismo no lugar de disciplina.

**Files:**
- Modify: `src/meta_ads/errors.py` (acrescenta `_redigir`, usa nos dois `f"...{e}"` e no ramo do código 100)
- Test: `tests/unit/test_meta_token_nao_vaza_em_erro.py` (da Task 1, sem alteração)

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces: `src.meta_ads.errors._redigir(texto: str) -> str` — a Task 5 referencia este nome no guard estrutural.

- [ ] **Step 1: Escrever o redator e aplicá-lo**

Em `src/meta_ads/errors.py`, adicionar logo após `CODIGOS_DE_THROTTLE`:

```python
import re

# F190 — qualquer coisa que pareca credencial numa query string sai ANTES de a
# mensagem chegar a um sink. Cobre `access_token`, `appsecret_proof` e
# `client_secret`; o SDK injeta os dois primeiros sem opt-out
# (`FacebookSession.__init__`), e o terceiro aparece no fluxo OAuth.
#
# Denylist e reconhecidamente fraca — por isso ela e a SEGUNDA linha de defesa.
# A primeira e o transporte nao pôr o token na URL (Task 3). Esta existe porque
# uma camada so e a que falha, e este finding e a prova: a invariante do F82
# estava escrita e mesmo assim o vazamento ficou aberto num dos dois caminhos.
_PARAMS_SENSIVEIS = re.compile(
    r"(access_token|appsecret_proof|client_secret)=[^&\s\"']+",
    re.IGNORECASE,
)


def _redigir(texto: str) -> str:
    """Troca o VALOR de parametro sensivel por `<REDIGIDO>`, preservando o nome.

    Preserva o nome de proposito: quem le o log precisa saber QUE havia um token
    ali — apagar o par inteiro esconderia a propria ocorrencia do problema.
    """
    return _PARAMS_SENSIVEIS.sub(r"\1=<REDIGIDO>", texto)
```

E trocar as três interpolações. No `except ImportError`:

```python
    except ImportError:  # pragma: no cover
        return MetaAdsFriendlyError(f"Erro inesperado: {_redigir(str(e))}", retryable=False)
```

No ramo do código 100:

```python
        if code == 100:
            return MetaAdsFriendlyError(
                f"Campo inválido na requisição Meta: {_redigir(str(message))}",
                retryable=False,
            )
```

No ramo genérico do `FacebookRequestError`:

```python
        return MetaAdsFriendlyError(
            f"Erro Meta API ({code}/{subcode}): {_redigir(str(message))}",
            retryable=False,
        )
```

E no fallback final:

```python
    return MetaAdsFriendlyError(f"Erro inesperado: {_redigir(str(e))}", retryable=False)
```

- [ ] **Step 2: Rodar o guard da Task 1 e confirmar VERDE**

Run: `python -m pytest tests/unit/test_meta_token_nao_vaza_em_erro.py -q`

Expected: **3 passed**.

- [ ] **Step 3: Escrever o teste do redator em isolamento**

Acrescentar a `tests/unit/test_meta_token_nao_vaza_em_erro.py`:

```python
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
```

- [ ] **Step 4: Rodar tudo e confirmar VERDE**

Run: `python -m pytest tests/unit/test_meta_token_nao_vaza_em_erro.py -q`

Expected: **6 passed**.

- [ ] **Step 5: Gate e commit**

```bash
python scripts/check_pre_push.py > /tmp/gate.txt 2>&1; echo "EXIT=$?"
```

Expected: `EXIT=0`. Se falhar, ler `/tmp/gate.txt` e corrigir antes de commitar.

```bash
git add src/meta_ads/errors.py tests/unit/test_meta_token_nao_vaza_em_erro.py
git commit -m "fix(meta_ads): F190 - redige credencial antes de qualquer sink de erro

Estanca o vazamento. A redacao vive DENTRO de to_friendly_meta_error, nao nos
call sites: e o unico ponto por onde toda excecao Meta ja passa, entao nenhum
chamador futuro precisa lembrar. Mecanismo no lugar de disciplina.

Preserva o NOME do parametro de proposito — quem le o log precisa saber que
havia um token ali; apagar o par inteiro esconderia a ocorrencia.

Denylist e segunda linha de defesa. A primeira (transporte nao por o token na
URL) vem na proxima task.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Transporte httpx — remove a causa

Troca `api.call` por `httpx` com auth por header. O token deixa de existir em qualquer URL. Absorve dois outros achados da varredura de graça: o **timeout ausente** e a **mentira do `cast(dict)`** sobre corpo não-JSON.

**Files:**
- Modify: `src/meta_ads/reports.py:129-176` — substitui `build_meta_api` + o closure `_paginar` + o `run_blocking`. **O intervalo começa em `api = build_meta_api(` (129) e termina na linha `body = {**body, "data": linhas}`.** O `except Exception` logo abaixo **fica como está**.
- Modify: `src/meta_ads/reports.py` — a leitura do header BUC (`response.headers()` → `headers_ultima.get(...)`), e imports no topo
- Modify: `src/meta_ads/errors.py` — mapeia o erro HTTP novo
- Test: `tests/unit/test_meta_transporte_httpx.py` (criar)

> ⚠️ `log.info("meta_graph_get_start", ...)` (135) e `started = time.monotonic()` (136) estão **dentro** do intervalo substituído — por isso o bloco novo os reinclui. Não são duplicata; conferido antes de escrever este plano.

**Interfaces:**
- Consumes: `src.meta_ads.errors._redigir` (Task 2); `src.meta_ads.client.META_GRAPH_API_VERSION` e `MetaSystemUserTokenMissingError` (já existem)
- Produces: `src.meta_ads.reports._TIMEOUT_GRAPH: float` e `src.meta_ads.reports._paginar_graph(...)` — a Task 5 referencia o módulo; nenhuma outra task chama estes nomes diretamente.

- [ ] **Step 1: Escrever os testes do transporte, que falham**

Criar `tests/unit/test_meta_transporte_httpx.py`:

```python
"""F190/varredura 21-09: o transporte Meta fala por header, com timeout e status real.

Tres achados da mesma varredura fecham aqui:

1. **Token na URL** — o SDK assa `access_token` na query de toda requisicao, sem
   opt-out. Com header auth ele nunca entra numa URL, e o vazamento fica
   impossivel POR CONSTRUCAO em vez de por vigilancia.
2. **Sem timeout** — `FacebookSession` guarda `timeout=None` e repassa a
   `requests`, que bloqueia indefinidamente. Como a chamada era offloadada com
   `run_blocking`, uma conexao pendurada prendia um slot do pool de threads do
   anyio — COMPARTILHADO com os cinco executores Google. Com httpx async nao ha
   thread para prender, e o timeout e explicito.
3. **`cast(dict)` que mente** — `FacebookResponse.json()` devolve o corpo CRU
   quando ele nao e JSON, e `is_success()` cai num teste de substring, entao uma
   pagina de erro HTML de intermediario passava como sucesso e virava
   `'str' object has no attribute 'get'` — apresentado ao gestor como falha
   PERMANENTE. Agora a forma e validada na borda, com o status no texto.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest


def _pool() -> MagicMock:
    conn = AsyncMock()
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    return pool


async def _rodar(handler: Any, **kwargs: Any) -> Any:
    """Roda o executor contra um transporte httpx falso (MockTransport)."""
    from src.meta_ads import reports

    transporte = httpx.MockTransport(handler)
    cliente_real = httpx.AsyncClient(transport=transporte, timeout=reports._TIMEOUT_GRAPH)

    with (
        patch.object(reports.httpx, "AsyncClient", MagicMock(return_value=cliente_real)),
        patch.object(
            reports.manager_meta_account_access,
            "can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch.object(reports.connection, "get_pool", return_value=_pool()),
        patch.object(reports.audit_log, "record", AsyncMock(return_value=1)),
    ):
        return await reports.run_meta_graph_get(
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_1",
            edge="/act_1/insights",
            params={"level": "campaign"},
            operation_name="meta_get_campaign_performance",
            **kwargs,
        )


@pytest.mark.asyncio
async def test_o_token_vai_no_header_e_nunca_na_url() -> None:
    """A invariante do F82, agora tambem no caminho que as 5 tools usam."""
    vistos: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vistos.append(request)
        return httpx.Response(200, json={"data": [], "paging": {}})

    await _rodar(handler)

    assert len(vistos) == 1, "piso: sem requisicao nao ha o que afirmar"
    req = vistos[0]
    assert "access_token" not in str(req.url), (
        f"o token foi para a URL: {req.url}. A invariante do F82 diz header, "
        "nunca query — quem le a URL num log contorna o gate de acesso."
    )
    assert req.headers.get("authorization", "").startswith("Bearer "), (
        "a autenticacao tem de ir no header Authorization"
    )


@pytest.mark.asyncio
async def test_o_cliente_e_construido_com_timeout() -> None:
    """Falha contra `timeout=None`, que e o default do SDK que saiu daqui."""
    from src.meta_ads import reports

    assert reports._TIMEOUT_GRAPH is not None
    assert reports._TIMEOUT_GRAPH > 0, (
        "sem timeout, uma conexao pendurada fica pendurada para sempre"
    )


@pytest.mark.asyncio
async def test_corpo_nao_json_levanta_erro_nomeado_com_o_status() -> None:
    """Pagina HTML de intermediario nao pode virar AttributeError.

    Antes: `cast(dict, resposta.json())` — o cast e no-op em runtime, o corpo cru
    (str) seguia, e `corpo.get("data")` estourava com
    `'str' object has no attribute 'get'`, marcado como retryable=False.
    """
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html><body>Bad Gateway</body></html>")

    with pytest.raises(Exception) as capturado:
        await _rodar(handler)

    texto = getattr(capturado.value, "message", str(capturado.value))
    assert "502" in texto, f"o status HTTP tem de aparecer na mensagem; veio: {texto!r}"
    assert "attribute" not in texto.lower(), (
        f"vazou erro de atributo em vez de erro nomeado: {texto!r}"
    )


@pytest.mark.asyncio
async def test_erro_5xx_e_marcado_retryable() -> None:
    """Falha transitoria de upstream nao pode ser apresentada como permanente."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    with pytest.raises(Exception) as capturado:
        await _rodar(handler)

    assert getattr(capturado.value, "retryable", False) is True, (
        "5xx e transitorio; marca-lo permanente faz o gestor desistir de uma "
        "chamada que funcionaria em 30 segundos"
    )


@pytest.mark.asyncio
async def test_erro_4xx_nao_e_retryable() -> None:
    """Controle do teste irmao: se tudo fosse retryable, a assercao dele nao valeria."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad", "code": 100}})

    with pytest.raises(Exception) as capturado:
        await _rodar(handler)

    assert getattr(capturado.value, "retryable", True) is False
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `python -m pytest tests/unit/test_meta_transporte_httpx.py -q`

Expected: **FAILED** — começando por `AttributeError: module 'src.meta_ads.reports' has no attribute '_TIMEOUT_GRAPH'`. É o vermelho certo: o transporte novo ainda não existe.

- [ ] **Step 3: Trocar o transporte**

Em `src/meta_ads/reports.py`, acrescentar aos imports do topo:

```python
import httpx

from src.meta_ads.client import META_GRAPH_API_VERSION, MetaSystemUserTokenMissingError
```

Acrescentar após os imports:

```python
# F190 — timeout explicito. O SDK que saiu daqui guardava `timeout=None` e
# repassava a `requests`, que bloqueia indefinidamente; como a chamada ia por
# `run_blocking`, uma conexao pendurada prendia um slot do pool de threads do
# anyio, compartilhado com os cinco executores Google. Espelha o valor que os
# outros call sites Meta em httpx ja usam (`auth/meta_oauth.py`).
_TIMEOUT_GRAPH = 30.0
```

Substituir o bloco que vai de `api = build_meta_api(` até o fim do `body = {**body, "data": linhas}` por:

```python
    token = settings.meta_system_user_token
    if not token:
        raise MetaSystemUserTokenMissingError(
            "Token do system user Meta não configurado. "
            "O admin precisa subir o secret meta-system-user-token."
        )

    log.info("meta_graph_get_start", edge=edge, operation=operation_name)
    started = time.monotonic()
    try:
        # F190 — token no HEADER, nunca na query. Mesma postura de
        # `graph.py::fetch_paginated`, que ja rodava assim em producao: e a
        # evidencia empirica de que este app nao exige `appsecret_proof`.
        cabecalhos = {"Authorization": f"Bearer {token}"}
        url = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}{edge}"
        async with httpx.AsyncClient(timeout=_TIMEOUT_GRAPH) as http:
            body, linhas, headers_ultima = await _paginar_graph(
                http, url, params or {}, cabecalhos, max_pages
            )
        if "data" in body or linhas:
            body = {**body, "data": linhas}
```

E acrescentar, no nível do módulo (antes de `run_meta_graph_get`):

```python
class MetaGraphHTTPError(Exception):
    """Status HTTP nao-2xx da Graph API, com o codigo no texto.

    Existe porque `FacebookResponse.is_success()` decidia sucesso por teste de
    SUBSTRING sobre o corpo: uma pagina HTML de erro de intermediario passava, e
    o estouro chegava ao gestor como `'str' object has no attribute 'get'`,
    marcado como permanente. Agora o status e o veredito.
    """

    def __init__(self, status: int, trecho: str):
        self.status = status
        self.retryable = status >= 500 or status == 429
        super().__init__(f"Graph API respondeu HTTP {status}: {trecho}")


async def _paginar_graph(
    http: httpx.AsyncClient,
    url: str,
    params: dict[str, Any],
    cabecalhos: dict[str, str],
    max_pages: int,
) -> tuple[dict[str, Any], list[Any], httpx.Headers]:
    """Segue `paging.next` ate `max_pages`. Devolve `(ultimo_corpo, linhas, headers)`.

    O `paging` que sobrevive e o da ULTIMA pagina lida — e assim que o chamador
    sabe se ficou dado para tras. Os headers da ultima resposta saem junto porque
    o contador BUC os le.

    F189: a URL do `next` vai como STRING. Foi embrulhada em lista uma vez, e o
    SDK — que so trata string como URL completa — concatenou na base e produziu
    uma URL dobrada; qualquer resultado com mais de uma pagina virava erro.
    """
    linhas: list[Any] = []
    corpo: dict[str, Any] = {}
    proxima: str | None = None
    headers = httpx.Headers()
    for _ in range(max_pages):
        if proxima is None:
            resp = await http.get(url, params=params, headers=cabecalhos)
        else:
            # `paging.next` ja carrega cursor e fields na propria URL.
            resp = await http.get(proxima, headers=cabecalhos)
        headers = resp.headers
        if resp.status_code != 200:
            raise MetaGraphHTTPError(resp.status_code, resp.text[:200])
        bruto = resp.json()
        if not isinstance(bruto, dict):
            # Nao e `cast`: o cast satisfaz o mypy e nao existe em runtime.
            raise MetaGraphHTTPError(resp.status_code, f"corpo nao-JSON: {type(bruto).__name__}")
        corpo = bruto
        linhas.extend(corpo.get("data") or [])
        proxima = (corpo.get("paging") or {}).get("next")
        if not proxima:
            break
    return corpo, linhas, headers
```

Trocar a leitura do header BUC, que hoje é `response.headers()` (método do SDK):

```python
    buc_header = headers_ultima.get("x-business-use-case-usage")
```

Acrescentar o mapeamento do erro novo em `errors.py::to_friendly_meta_error`, **antes** do fallback final:

```python
    from src.meta_ads.reports import MetaGraphHTTPError  # noqa: PLC0415

    if isinstance(e, MetaGraphHTTPError):
        return MetaAdsFriendlyError(_redigir(str(e)), retryable=e.retryable)
```

> ⚠️ Import tardio de propósito: `reports.py` importa `errors.py`, então importar no topo criaria ciclo. Se o ciclo incomodar, mova `MetaGraphHTTPError` para `client.py` — **mas então atualize este plano e os testes que a importam de `reports`.**

- [ ] **Step 4: Rodar os testes do transporte**

Run: `python -m pytest tests/unit/test_meta_transporte_httpx.py -q`

Expected: **5 passed**.

- [ ] **Step 5: Rodar os guards vizinhos que não podem ter regredido**

Run: `python -m pytest tests/unit/test_meta_paginacao_usa_url_completa.py tests/unit/test_meta_pagination_and_ranking.py tests/unit/test_meta_token_nao_vaza_em_erro.py tests/unit/test_meta_reports_gate.py -q`

Expected: **todos passam.** O guard do F189 é o mais importante aqui: se ele ficar vermelho, a paginação regrediu junto com a troca de transporte.

> ⚠️ `test_meta_pagination_and_ranking.py` mocka `api.call`, que **não existe mais neste caminho**. Espera-se que ele falhe. **Não o delete:** reescreva os dois fakes para `httpx.MockTransport`, preservando o que eles afirmam (páginas seguidas e concatenadas; teto respeitado com o `paging` sobrevivendo). Perder essas duas asserções para fazer o gate passar seria trocar cobertura por verde.

- [ ] **Step 6: Gate e commit**

```bash
python scripts/check_pre_push.py > /tmp/gate.txt 2>&1; echo "EXIT=$?"
```

```bash
git add src/meta_ads/reports.py src/meta_ads/errors.py tests/unit/test_meta_transporte_httpx.py tests/unit/test_meta_pagination_and_ranking.py
git commit -m "fix(meta_ads): F190 - transporte Meta no httpx, token no header

Remove a causa: o token deixa de existir em qualquer URL. Absorve dois outros
achados da mesma varredura — o timeout ausente (o SDK guardava None e repassava
a requests) e o cast(dict) que mentia sobre corpo nao-JSON.

O run_blocking sai junto: httpx async nao precisa de thread, entao o risco de
esgotar o pool compartilhado com os executores Google morre por construcao, em
vez de ser mitigado por timeout.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Amarrar o gate à URL

O hard-gate roda contra o kwarg `ad_account_id`; a requisição vai para `edge`; nada liga os dois. O F72 tornou o kwarg **obrigatório**, não **autoritativo sobre a URL**. Hoje todos os chamadores derivam os dois da mesma variável, então concordam — mas uma tool futura cujo edge seja `/{campaign_id}/insights` gatearia a conta A e leria a conta B, num token que alcança ~24 contas.

**Files:**
- Modify: `src/meta_ads/reports.py` (uma checagem logo após o gate)
- Test: `tests/unit/test_meta_transporte_httpx.py` (acrescentar)

**Interfaces:**
- Consumes: `run_meta_graph_get` como reescrita na Task 3.
- Produces: nada.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/unit/test_meta_transporte_httpx.py`:

```python
@pytest.mark.asyncio
async def test_edge_divergente_do_ad_account_gateado_e_recusado() -> None:
    """A conta que o gate aprovou tem de ser a conta na URL.

    Hoje os tres chamadores derivam os dois do mesmo valor, entao concordam — e
    e por isso que os testes de gate existentes passam por cima desta mudanca:
    eles sempre passam um par casado. O risco e a tool futura cujo edge seja
    `/{campaign_id}/insights`: gate na conta A, leitura na conta B, num token que
    alcanca ~24 contas. F57 um andar acima — o gate existe e o escopo dele nao
    esta amarrado ao que de fato e lido.
    """
    from src.meta_ads import reports

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [], "paging": {}})

    transporte = httpx.MockTransport(handler)
    cliente_real = httpx.AsyncClient(transport=transporte, timeout=reports._TIMEOUT_GRAPH)

    with (
        patch.object(reports.httpx, "AsyncClient", MagicMock(return_value=cliente_real)),
        patch.object(
            reports.manager_meta_account_access,
            "can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch.object(reports.connection, "get_pool", return_value=_pool()),
        patch.object(reports.audit_log, "record", AsyncMock(return_value=1)),
        pytest.raises(ValueError, match="act_1"),
    ):
        await reports.run_meta_graph_get(
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_1",
            edge="/act_999/insights",  # conta DIFERENTE da gateada
            params={"level": "campaign"},
            operation_name="meta_get_campaign_performance",
        )
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_meta_transporte_httpx.py::test_edge_divergente_do_ad_account_gateado_e_recusado -q`

Expected: **FAILED** — `DID NOT RAISE`.

- [ ] **Step 3: Implementar a checagem**

Em `src/meta_ads/reports.py`, logo após o bloco do hard-gate (depois do `raise MetaAccessDeniedError(...)`), acrescentar:

```python
    # F190 — o gate aprovou `ad_account_id`; a requisicao vai para `edge`. Sem
    # amarrar os dois, o F72 garante que o gate RODA, nao que ele rodou sobre a
    # conta certa. Falha fechado: prefere recusar uma edge legitima e exotica a
    # ler uma conta que ninguem gateou.
    if ad_account_id not in edge:
        raise ValueError(
            f"edge {edge!r} nao contem a conta gateada {ad_account_id!r} — "
            "o gate de acesso e a requisicao apontam para contas diferentes."
        )
```

- [ ] **Step 4: Rodar e confirmar VERDE, incluindo os vizinhos**

Run: `python -m pytest tests/unit/test_meta_transporte_httpx.py tests/unit/test_meta_reports_gate.py -q`

Expected: **todos passam.** Se algum teste de gate existente quebrar, ele estava passando um par divergente sem perceber — **investigue antes de afrouxar a checagem**.

- [ ] **Step 5: Gate e commit**

```bash
python scripts/check_pre_push.py > /tmp/gate.txt 2>&1; echo "EXIT=$?"
```

```bash
git add src/meta_ads/reports.py tests/unit/test_meta_transporte_httpx.py
git commit -m "fix(meta_ads): amarra o gate de acesso a conta que esta na URL

O F72 tornou ad_account_id obrigatorio, nao autoritativo sobre a edge. Os tres
chamadores de hoje derivam os dois do mesmo valor — e e por isso que os testes
de gate passavam por cima: sempre um par casado. Falha fechado.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Escopo estrutural do guard de vazamento

`test_meta_secret_leak.py` cobre a invariante do F82 **enumerando dois arquivos**. Foi exatamente por isso que o caminho do SDK ficou de fora por meses. Enquanto o guard enumerar, um transporte novo escapa de novo.

**Files:**
- Modify: `tests/unit/test_meta_secret_leak.py`

**Interfaces:**
- Consumes: `src.meta_ads.errors._redigir` (Task 2).
- Produces: nada.

- [ ] **Step 1: Ler o guard atual e localizar a enumeração**

Run: `grep -n "meta_oauth\|graph.py\|_ARQUIVOS\|SRC /" tests/unit/test_meta_secret_leak.py`

Identifique a lista literal de arquivos que ele varre. **Não altere o que ele afirma** — só de onde ele tira o escopo.

- [ ] **Step 2: Escrever o teste da propriedade**

Acrescentar a `tests/unit/test_meta_secret_leak.py`:

```python
def test_nenhum_caminho_meta_poe_credencial_em_query() -> None:
    """Propriedade, nao lista: TODO arquivo de `src/meta_ads/` obedece.

    A versao anterior enumerava `meta_oauth.py` e `graph.py`. `reports.py` falava
    com a Graph API pelo SDK, que assa o token na query — e ficou fora do escopo
    por nao estar na lista. Guard que enumera absolve o arquivo que ninguem
    lembrou de listar, que e precisamente o arquivo onde o bug mora.
    """
    from tests.unit import _guard_harness as h

    arquivos = h.fontes_py(h.SRC / "meta_ads")
    assert len(arquivos) >= 5, (
        f"piso de nao-vacuidade: so {len(arquivos)} arquivos em src/meta_ads/. "
        "O localizador parou de casar e o guard estaria absolvendo por vacuidade."
    )
    ofensores: list[str] = []
    for arq in arquivos:
        texto = arq.read_text(encoding="utf-8")
        for termo in ("access_token=", "appsecret_proof="):
            if termo in texto and "_PARAMS_SENSIVEIS" not in texto:
                ofensores.append(f"{h.rel(arq)}: {termo}")
    assert ofensores == [], (
        "credencial montada em query string fora do redator: "
        f"{ofensores}. A invariante do F82 e header, nunca query."
    )
```

- [ ] **Step 3: Rodar**

Run: `python -m pytest tests/unit/test_meta_secret_leak.py -q`

Expected: **todos passam** (depois das Tasks 2–3, nenhum arquivo monta credencial em query). Se algum ofensor aparecer, **é achado real** — investigue antes de acrescentar isenção.

- [ ] **Step 4: Gate e commit**

```bash
python scripts/check_pre_push.py > /tmp/gate.txt 2>&1; echo "EXIT=$?"
```

```bash
git add tests/unit/test_meta_secret_leak.py
git commit -m "test(meta_ads): guard de vazamento vira propriedade, nao lista

Ele enumerava dois arquivos, e foi por isso que o caminho do SDK ficou de fora.
Guard que enumera absolve exatamente o arquivo que ninguem lembrou de listar.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Remover o `build_meta_api` órfão

Depois da Task 3 ele fica sem consumidor. Código morto com teste verde é pior que código morto: dá a impressão de cobertura.

**Files:**
- Modify: `src/meta_ads/client.py` (remove `build_meta_api`; **mantém** o resto)
- Modify: `tests/unit/test_meta_client.py` (remove os testes de `build_meta_api`)

**Interfaces:**
- Consumes: nada.
- Produces: nada.

- [ ] **Step 1: Confirmar que está órfão, por medição**

Run: `grep -rn "build_meta_api" src/ tests/ --include=*.py`

Expected: só a definição em `client.py` e os testes em `test_meta_client.py`. **Se aparecer outro consumidor, pare** — a Task 3 não terminou.

Run: `grep -rn "build_facebook_ads_api" src/ tests/ --include=*.py`

> ⚠️ `build_facebook_ads_api` é citado no `CLAUDE.md` pelo F48 e pode ter consumidor próprio. **Só remova o que estiver comprovadamente órfão.** Em dúvida, deixe.

- [ ] **Step 2: Remover `build_meta_api` e seus testes**

Apagar a função `build_meta_api` de `src/meta_ads/client.py` e os testes correspondentes de `tests/unit/test_meta_client.py`.

**Mantenha em `client.py`:** `META_GRAPH_API_VERSION` (usado por `partnership.py` e pela Task 3), `MetaAccessDeniedError` (usado por `src/mcp/server.py`) e `MetaSystemUserTokenMissingError` (usado pela Task 3).

- [ ] **Step 3: Rodar a suíte inteira**

Run: `python -m pytest tests/unit -q`

Expected: **todos passam**, sem `ImportError`.

- [ ] **Step 4: Gate e commit**

```bash
python scripts/check_pre_push.py > /tmp/gate.txt 2>&1; echo "EXIT=$?"
```

```bash
git add src/meta_ads/client.py tests/unit/test_meta_client.py
git commit -m "chore(meta_ads): remove build_meta_api, sem consumidor apos o httpx

Codigo morto com teste verde e pior que codigo morto — parece cobertura.
client.py fica: META_GRAPH_API_VERSION, MetaAccessDeniedError e
MetaSystemUserTokenMissingError seguem tendo consumidores.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Catálogo, estado e o débito declarado

**Files:**
- Modify: `docs/operacao/findings-catalog.md` (entrada F190 + faixa)
- Modify: `CLAUDE.md` (faixa, 2 sítios)
- Modify: `docs/operacao/estado-atual.md` (faixa)

**Interfaces:** nenhuma.

- [ ] **Step 1: Escrever a entrada F190**

Acrescentar ao fim de `docs/operacao/findings-catalog.md` uma entrada `## F190 (CRITICAL, ✅ CORRIGIDO 2026-09-21)` cobrindo: a cadeia dos três elos (SDK assa o token na query → `errors.py` interpola cru → `audit_log`/log/LLM), os três sinks, **por que passou** (F82 fechado num dos dois caminhos; guard enumerando dois arquivos), o fix em duas camadas (redação + transporte), e — obrigatoriamente — o **débito declarado**:

> ⚠️ **Não foi medido se o token já vazou.** Decisão do Wellington em 21/09: consertar para frente, sem rotação nem expurgo. A contagem que responderia é um `COUNT(*)` em `audit_log` por `error_message` contendo o nome do parâmetro de token, e **ela não foi executada**. Registrado para que "ninguém mediu" não vire "nunca aconteceu".

- [ ] **Step 2: Atualizar a faixa nos quatro sítios**

Run: `grep -rn "F1 a F189\|F1–F189\|até \*\*F189\*\*" --include=*.md . | grep -v _archive`

Trocar `F189` por `F190` em cada um, e remedir linhas/KB do catálogo:

```bash
wc -l < docs/operacao/findings-catalog.md; du -k docs/operacao/findings-catalog.md | cut -f1
```

⚠️ **`CLAUDE.md` tem teto de 24000 bytes com guard.** Medir do jeito do guard (normalizando CRLF) antes de commitar:

```bash
python -c "from pathlib import Path; b=len(Path('CLAUDE.md').read_bytes().replace(b'\r\n', b'\n')); print(b, 'folga', 24000-b)"
```

- [ ] **Step 3: Gate e commit**

```bash
python scripts/check_pre_push.py > /tmp/gate.txt 2>&1; echo "EXIT=$?"
```

```bash
git add docs/operacao/findings-catalog.md CLAUDE.md docs/operacao/estado-atual.md
git commit -m "docs(operacao): F190 no catalogo, com o debito declarado

Registra que NAO foi medido se o token ja vazou, e qual consulta responderia.
Sem isso, "ninguem mediu" vira "nunca aconteceu" em tres meses — foi assim que
o F186 deslizou.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Verificação em produção (após o merge e o deploy)

Não é uma task porque não produz commit — mas o trabalho **não está pronto** sem ela.

1. **Capturar a revisão servindo ANTES do deploy** (F116) — `gcloud run services describe`, nunca deduzir por ordem de criação.
2. **Probe de fronteira do F189**, conta `act_4051924171730156` (17 anúncios):
   - `meta_get_ad_performance(limit=16)` → **16 linhas, `truncated: true`**
   - `meta_get_ad_performance(limit=17)` → **17 linhas, `truncated: false`**
   O segundo é o controle: sem ele, "consertei" e "quebrei para o outro lado" têm a mesma aparência.
3. **Uma leitura Meta ponta a ponta em outra conta**, para exercitar o transporte novo fora da conta da probe.
4. Se o app exigir `appsecret_proof`, aparece **aqui**, como 4xx. A evidência contrária é empírica: `graph.py` já chama a Graph API com header auth, sem `appsecret_proof`, em produção.
