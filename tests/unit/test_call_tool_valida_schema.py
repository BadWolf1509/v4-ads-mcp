"""O `call_tool` do servidor recusa argumento que viola o `input_schema`.

`src/mcp/server.py` tem UMA linha que aplica `pattern`, `enum` e `required` dos
schemas das 74 tools — a `jsonschema.validate(args, tool.input_schema)` dentro de
`build_server().call_tool`. Dela dependem a whitelist de enum do F17-F19 (valor
fora da lista tem que morrer antes de virar GAQL), a não-interpolação do F87 (o
`pattern` de `customer_id` é o que garante que só dígito entra) e todo pré-flight
que assume argumento já na forma certa. Até aqui, **nenhum teste a exercitava**.

## Por que os testes não passam pela tabela de despacho

Medido em 2026-09-07, SDK `mcp` 1.28.1: `@server.call_tool()` embrulha a nossa
função num handler do próprio SDK que valida ANTES, com o mesmo schema
(`validate_input=True` é o default) — e o schema vem do `list_tools`, que devolve
todas as tools registradas, então o cache nunca erra. Chamando
`server.request_handlers[CallToolRequest]` com os três argumentos inválidos, as
três respostas voltam com a mensagem do SDK (`"Input validation error: ..."`), e
a nossa linha **não roda em nenhuma delas**.

Consequência para o teste: um guard escrito sobre a tabela de despacho fica VERDE
com a nossa validação apagada — o SDK recusa igual. Seria o modo clássico de
guard que não cobre (exercita o adjacente e afirma o que a camada de terceiro já
garante). Por isso os três casos abaixo chamam a **função `call_tool` que o
`build_server()` registrou** — o objeto vivo, extraído do closure do wrapper do
SDK, não uma cópia nem uma reimplementação.

Consequência para o código: a nossa linha é a rede que sobra se o default do SDK
mudar ou se alguém passar `validate_input=False`. Ela é defesa em profundidade,
não código morto — e é a única metade que este repositório controla.

## Por que a recusa não pode vir de dentro do handler

Cada teste troca o handler REAL da tool por um espião (`handler_espiao`) antes de
chamar. Se a recusa viesse de um `if` dentro do handler, trocar o handler a
apagaria e a chamada passaria. Como o espião não valida nada e mesmo assim
**nunca é chamado**, a recusa é necessariamente anterior a ele.

## A tool escolhida

`get_campaign_performance`: é de LEITURA (nenhum mock de mutação, nenhum token de
confirmação no caminho), é `bucket="always"` (a tool mais quente da conta) e o
schema dela traz as três formas de uma vez — `pattern` em `customer_id`, `enum`
em `date_range` e `required: ["customer_id"]`.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, TextContent

from src.mcp.server import build_server
from src.mcp.tools import _registry

NOME_DA_TOOL = "get_campaign_performance"

# `customer_id` válido para os casos em que o inválido é OUTRO campo — sem ele o
# teste de `enum` morreria pelo `pattern` e não provaria nada sobre `enum`.
CUSTOMER_ID_VALIDO = "1234567890"

_CallTool = Callable[[str, dict[str, Any] | None], Awaitable[list[TextContent]]]


def _call_tool_do_servidor() -> _CallTool:
    """A função `call_tool` que `build_server()` registrou — o objeto vivo.

    O decorator `@server.call_tool()` devolve a nossa função, mas quem fica na
    tabela de despacho é o wrapper do SDK, que a guarda no closure sob o nome
    `func`. Extrair dali é o único jeito de chamar a nossa camada sem a do SDK
    na frente — e sem reescrever `build_server` no teste, que provaria só que a
    cópia funciona.

    As asserções de identidade existem para o dia em que o SDK renomear a
    variável ou parar de embrulhar: aí este helper fica VERMELHO com a causa
    escrita, em vez de devolver silenciosamente outro objeto qualquer.
    """
    servidor = build_server()
    wrapper: Any = servidor.request_handlers[CallToolRequest]
    freevars: tuple[str, ...] = wrapper.__code__.co_freevars
    assert "func" in freevars, (
        f"o wrapper de CallToolRequest do SDK mudou de forma: freevars={freevars!r}. "
        "Este teste precisa da função registrada por @server.call_tool()."
    )
    assert wrapper.__closure__ is not None, "wrapper sem closure — o SDK parou de embrulhar"
    alvo = wrapper.__closure__[freevars.index("func")].cell_contents
    assert alvo.__module__ == "src.mcp.server", f"peguei o objeto errado: {alvo.__module__}"
    assert alvo.__qualname__ == "build_server.<locals>.call_tool", (
        f"peguei o objeto errado: {alvo.__qualname__}"
    )
    return cast(_CallTool, alvo)


@pytest.fixture
def handler_espiao(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Troca o handler REAL da tool por um espião e devolve a lista de chamadas.

    Lista vazia depois da chamada = o handler não foi alcançado. É esta fixture
    que separa "o servidor recusou" de "a tool se defendeu sozinha": o espião não
    valida coisa nenhuma.
    """
    original = _registry.get_tool(NOME_DA_TOOL)
    assert original is not None, (
        f"tool {NOME_DA_TOOL!r} sumiu do registry — este teste ficaria vazio. "
        "Escolha outra tool de LEITURA com pattern + enum + required no schema."
    )
    chamadas: list[dict[str, Any]] = []

    async def espiao(args: dict[str, Any]) -> dict[str, Any]:
        chamadas.append(args)
        return {"status": "ok", "sentinela": "handler alcancado"}

    monkeypatch.setitem(
        _registry._TOOLS, NOME_DA_TOOL, dataclasses.replace(original, handler=espiao)
    )
    return chamadas


async def _recusa(args: dict[str, Any]) -> str:
    """Chama o `call_tool` do servidor e devolve a mensagem da recusa."""
    call_tool = _call_tool_do_servidor()
    with pytest.raises(ValueError) as exc:
        await call_tool(NOME_DA_TOOL, args)
    return str(exc.value)


def test_a_tool_escolhida_tem_as_tres_formas_no_schema() -> None:
    """Âncora da escolha: se o schema drenar, os três testes abaixo viram vácuo.

    Sem esta âncora, apagar o `enum` de `date_range` deixaria o teste de enum
    vermelho por um motivo que ninguém consegue ler na mensagem. Aqui a causa
    fica escrita.
    """
    tool = _registry.get_tool(NOME_DA_TOOL)
    assert tool is not None
    props = tool.input_schema["properties"]

    assert props["customer_id"]["pattern"] == "^[0-9]{10}$"
    assert "LAST_7_DAYS" in props["date_range"]["enum"]
    assert tool.input_schema["required"] == ["customer_id"]


async def test_pattern_customer_id_de_9_digitos_e_recusado(
    handler_espiao: list[dict[str, Any]],
) -> None:
    """`pattern` — a metade do F87 que impede texto livre de virar GAQL.

    O `gaql_string_literal` cuida do escape; este `pattern` é o que garante que
    `customer_id` nem chega a precisar dele. Nove dígitos é o erro de digitação
    real (um dígito a menos), não um caractere exótico.
    """
    mensagem = await _recusa({"customer_id": "123456789"})

    assert handler_espiao == [], "o handler foi alcançado: a validação não recusou"
    assert f"Invalid arguments for tool '{NOME_DA_TOOL}'" in mensagem
    assert "does not match '^[0-9]{10}$'" in mensagem
    # O sufixo `(at path: ...)` só existe na nossa camada — o SDK não o escreve.
    assert "(at path: customer_id)" in mensagem


async def test_enum_fora_da_whitelist_e_recusado(handler_espiao: list[dict[str, Any]]) -> None:
    """`enum` — a whitelist que o F17-F19 estabeleceu.

    O valor tem que morrer aqui, antes de o executor montar `DURING <preset>` e
    o Google devolver um erro que o gestor não sabe ler. `customer_id` vai
    VÁLIDO de propósito: com ele inválido, quem recusaria seria o `pattern`, e o
    teste passaria sem nunca exercitar `enum`.
    """
    mensagem = await _recusa({"customer_id": CUSTOMER_ID_VALIDO, "date_range": "LAST_666_DAYS"})

    assert handler_espiao == [], "o handler foi alcançado: a validação não recusou"
    assert f"Invalid arguments for tool '{NOME_DA_TOOL}'" in mensagem
    assert "'LAST_666_DAYS' is not one of" in mensagem
    assert "(at path: date_range)" in mensagem


async def test_required_ausente_e_recusado(handler_espiao: list[dict[str, Any]]) -> None:
    """`required` — o que todo pré-flight assume já estar presente.

    Sem esta recusa, `args["customer_id"]` vira `KeyError` lá dentro (envelope
    genérico, causa apagada) ou, pior, `args.get("customer_id")` vira `None` e
    segue viagem.
    """
    mensagem = await _recusa({})

    assert handler_espiao == [], "o handler foi alcançado: a validação não recusou"
    assert f"Invalid arguments for tool '{NOME_DA_TOOL}'" in mensagem
    assert "'customer_id' is a required property" in mensagem
    # `required` falha na raiz do objeto, não num campo — o `<root>` é o default
    # do nosso `'/'.join(...)` quando `absolute_path` vem vazio.
    assert "(at path: <root>)" in mensagem


async def test_argumentos_validos_alcancam_o_handler(handler_espiao: list[dict[str, Any]]) -> None:
    """Controle positivo: sem ele, um `call_tool` que recusasse TUDO passaria nos três.

    É a metade que transforma os testes acima em guard: eles afirmam que o
    inválido não passa, este afirma que o válido passa. Um só, sem o outro, é
    satisfeito por `raise ValueError` na primeira linha da função.
    """
    call_tool = _call_tool_do_servidor()
    args = {"customer_id": CUSTOMER_ID_VALIDO, "date_range": "LAST_7_DAYS"}

    resultado = await call_tool(NOME_DA_TOOL, args)

    assert handler_espiao == [args], "argumento válido não chegou ao handler"
    assert len(resultado) == 1
    assert json.loads(resultado[0].text)["sentinela"] == "handler alcancado"


@pytest.mark.parametrize(
    ("caso", "args"),
    [
        ("pattern", {"customer_id": "123456789"}),
        ("enum", {"customer_id": CUSTOMER_ID_VALIDO, "date_range": "LAST_666_DAYS"}),
        ("required", {}),
    ],
)
async def test_despacho_do_servidor_devolve_iserror_nas_tres_formas(
    handler_espiao: list[dict[str, Any]], caso: str, args: dict[str, Any]
) -> None:
    """Contrato visto pelo CLIENTE MCP, com as DUAS camadas no caminho.

    Este teste **não morde a nossa linha** — o SDK recusa primeiro (ver o
    docstring do módulo), então ele fica verde com a nossa validação apagada.
    Está aqui de propósito e rotulado: ele só vira vermelho se as duas camadas
    caírem, que é o estado em que argumento inválido chega ao Google. Quem quiser
    a mordida da nossa linha olha os três testes acima.
    """
    servidor = build_server()
    despacho = servidor.request_handlers[CallToolRequest]
    requisicao = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=NOME_DA_TOOL, arguments=args),
    )

    resultado = await despacho(requisicao)

    assert resultado.root.isError is True, f"caso {caso}: cliente não viu recusa"
    assert handler_espiao == [], f"caso {caso}: o handler foi alcançado"
