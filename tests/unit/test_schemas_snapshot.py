"""Snapshot do que o cliente MCP ve no handshake (`tools/list`).

O fixture `fixtures/schemas_das_tools.json` guarda name, description, inputSchema
e _meta de cada tool, gerados pelo MESMO handler que o servidor expoe
(`build_server()` -> `list_tools`). Refatoracao que mexe em tool nao pode mudar
o contrato silenciosamente: o teste aponta qual tool divergiu.

Mudanca DELIBERADA de description/schema: regrave o fixture com

    V4_REGRAVAR_SCHEMAS=1 python -m pytest tests/unit/test_schemas_snapshot.py

e revise o diff do JSON no mesmo commit. O fixture vai num repo publico: nenhum
dado de cliente em description.
"""

import json
import os
from pathlib import Path

from mcp import types
from src.mcp.server import build_server

FIXTURE = Path(__file__).parent / "fixtures" / "schemas_das_tools.json"
_REGRAVAR = "V4_REGRAVAR_SCHEMAS"


async def _tools_do_handshake() -> dict[str, dict]:
    server = build_server()
    handler = server.request_handlers[types.ListToolsRequest]
    resp = await handler(types.ListToolsRequest(method="tools/list"))
    return {
        t.name: t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in resp.root.tools
    }


def _serializar(tools: dict[str, dict]) -> str:
    ordenado = [tools[n] for n in sorted(tools)]
    return json.dumps(ordenado, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


async def test_schemas_das_tools_batem_com_o_snapshot():
    atual = await _tools_do_handshake()
    assert len(atual) >= 1, "handshake sem nenhuma tool"
    texto = _serializar(atual)

    if os.environ.get(_REGRAVAR) == "1":
        FIXTURE.write_bytes(texto.encode("utf-8"))
        return

    esperado = {t["name"]: t for t in json.loads(FIXTURE.read_text(encoding="utf-8"))}
    como_regravar = (
        f"Se a mudanca for deliberada: {_REGRAVAR}=1 python -m pytest "
        "tests/unit/test_schemas_snapshot.py e revise o diff do fixture."
    )

    novas = sorted(set(atual) - set(esperado))
    sumidas = sorted(set(esperado) - set(atual))
    divergentes = sorted(n for n in set(atual) & set(esperado) if atual[n] != esperado[n])
    assert not (novas or sumidas or divergentes), (
        f"Contrato das tools mudou. novas={novas} sumidas={sumidas} "
        f"divergentes={divergentes}. {como_regravar}"
    )
    em_disco = FIXTURE.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert texto == em_disco, f"Fixture fora do formato canonico. {como_regravar}"
