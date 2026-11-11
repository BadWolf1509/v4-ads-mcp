"""A description que o modelo le diz a mesma versao e os mesmos tipos que o codigo.

Ate 11/11 (#239) a description do `apply_recommendation` seguia dizendo "SDK v24"
depois que o enum foi para o v25, e nem ela nem a do `get_recommendations` citavam o
tipo so leitura — o modelo prometeria ao gestor aplicar o que a tool recusa.
"""

from __future__ import annotations

import re

from google.ads.googleads import client

from src.google_ads.queries.recommendations import TIPOS_SO_LEITURA
from src.mcp.tools import _registry
from src.mcp.tools._registry import import_all_tools


def _descricao(nome: str) -> str:
    import_all_tools()
    return next(t.description for t in _registry.all_tools() if t.name == nome)


def test_a_versao_do_sdk_na_description_e_a_do_client() -> None:
    citadas = set(re.findall(r"SDK (v\d+)", _descricao("apply_recommendation")))
    assert citadas == {client._DEFAULT_VERSION}, citadas


def test_as_duas_descriptions_nomeiam_cada_tipo_so_leitura() -> None:
    assert TIPOS_SO_LEITURA
    for nome in ("apply_recommendation", "get_recommendations"):
        texto = _descricao(nome)
        for tipo in TIPOS_SO_LEITURA:
            assert tipo in texto, f"{nome} nao cita o tipo so leitura {tipo}"
