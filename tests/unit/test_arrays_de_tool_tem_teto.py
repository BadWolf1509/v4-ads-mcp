"""F183: nenhuma tool aceita array sem teto.

O finding nasceu de `update_keyword_status` e `update_ad_group_status` sem `maxItems`,
e a contagem errou TRÊS vezes antes deste guard existir — 3, depois 2, depois 4 — porque
cada medição usou um instrumento diferente e mais grosseiro que a invariante: `grep` de
`maxItems` no arquivo, leitura de três tools escolhidas a dedo, e `ast.literal_eval` do
`_SCHEMA` (que devolve ZERO, porque os schemas referenciam constantes e não são literais).

A medição que vale é a do schema **registrado**, que é o que o cliente MCP recebe no
handshake. Ela achou 8.

A invariante é `array => maxItems`, sem recorte por tool mutante ou de leitura. Recortar
exigiria classificar, a classificação exigiria uma lista, e lista é exatamente o que
absolve quem ficou de fora dela. Aqui não há exceção nenhuma — e se alguma tool precisar
de uma no futuro, ela entra com motivo escrito, não por omissão.

Por que array sem teto importa nos dois lados: em tool mutante, o lote vai ao Google
inteiro e atômico; em tool de leitura, os valores viram cláusula `IN` de uma GAQL.
"""

from __future__ import annotations

from tests.unit._guard_harness import EscopoVazioError

# Observados 37 arrays em 2026-09-20. O piso protege contra o registry carregar pela
# metade: um guard que varre 3 arrays passa por vacuidade e não diz nada.
_PISO_DE_ARRAYS = 30


def _arrays_registrados() -> list[tuple[str, str, dict]]:
    """`(tool, propriedade, subschema)` de todo array declarado no schema REGISTRADO."""
    from src.mcp.tools._registry import all_tools, import_all_tools

    import_all_tools()
    achados: list[tuple[str, str, dict]] = []
    for t in all_tools():
        props = (t.input_schema or {}).get("properties", {})
        for nome, p in props.items():
            if isinstance(p, dict) and p.get("type") == "array":
                achados.append((t.name, nome, p))
    if len(achados) < _PISO_DE_ARRAYS:
        raise EscopoVazioError(
            f"só {len(achados)} arrays encontrados (piso: {_PISO_DE_ARRAYS}, "
            "observados 37 em 2026-09-20). O registry não carregou por inteiro, e o "
            "guard estaria passando sobre uma fração da superfície."
        )
    return sorted(achados)


def test_nenhum_array_de_tool_aceita_tamanho_ilimitado() -> None:
    sem_teto = [f"{tool}.{prop}" for tool, prop, p in _arrays_registrados() if "maxItems" not in p]
    assert not sem_teto, (
        "array sem `maxItems` no schema registrado: "
        + ", ".join(sem_teto)
        + ". Em tool mutante isso e lote sem limite indo atomico ao Google; em tool de "
        "leitura, clausula IN de GAQL sem limite. Escolha um teto pela ENTIDADE (quanto "
        "maior o raio de cada item, menor o teto) ou pelo tamanho do enum, quando o "
        "array for de enum."
    )


def test_teto_de_array_de_enum_nao_excede_o_proprio_enum() -> None:
    """Teto maior que o enum é teto que não limita nada — e finge limitar.

    Não é purismo: um array de 3 valores possíveis declarado com `maxItems: 500` passa
    neste guard pela porta da frente e mente pro cliente MCP sobre o que aceita.
    """
    exageros = []
    for tool, prop, p in _arrays_registrados():
        itens = p.get("items")
        if not isinstance(itens, dict):
            continue
        enum = itens.get("enum")
        if not isinstance(enum, list) or "maxItems" not in p:
            continue
        if p["maxItems"] > len(enum):
            exageros.append(f"{tool}.{prop}: maxItems={p['maxItems']} > enum={len(enum)}")
    assert not exageros, "teto acima da cardinalidade do enum: " + ", ".join(exageros)
