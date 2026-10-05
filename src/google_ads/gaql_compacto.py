"""Linha plana do `run_gaql` com `compact: true` (spec 2026-10-05, §3.4).

O `MessageToDict` devolve o `resource_name` de cada objeto da linha mesmo fora do SELECT — e
isso, mais o aninhamento, incha a saída (medido em 05/10: −39% numa amostra de
`campaign_criterion`). Só sai o `resource_name` que o SELECT NÃO pediu; se a lista do SELECT
não puder ser lida, nenhum sai (falha segura: achatar sem perder campo pedido).
"""

import re
from typing import Any

_SELECT = re.compile(r"\bSELECT\b(.*?)\bFROM\b", re.IGNORECASE | re.DOTALL)


def campos_do_select(query: str) -> set[str] | None:
    """Os campos entre SELECT e FROM, em minúsculas — ou `None` quando não dá para ler."""
    # `findall`, nao `.search`: o guard do F86 acusa qualquer chamada de atributo com o nome
    # do metodo bloqueante do SDK (`ga_service.search`), e esta funcao roda no event loop.
    achados = _SELECT.findall(query)
    if not achados:
        return None
    campos = {c.strip().lower() for c in achados[0].split(",") if c.strip()}
    return campos or None


def linha_compacta(linha: dict[str, Any], pedidos: set[str] | None) -> dict[str, Any]:
    """`{"campaign": {"id": "1"}}` → `{"campaign.id": "1"}`, sem os `resource_name` implícitos."""
    plana: dict[str, Any] = {}

    def _pedido(caminho: str) -> bool:
        # O campo pedido E tudo o que mora dentro dele: `SELECT change_event.old_resource`
        # pede o `old_resource.campaign.resource_name` junto (revisao 05/10, I1).
        c = caminho.lower()
        return pedidos is None or any(c == p or c.startswith(p + ".") for p in pedidos)

    def _desce(no: dict[str, Any], prefixo: str) -> None:
        for k, v in no.items():
            caminho = f"{prefixo}{k}"
            if isinstance(v, dict) and v:
                _desce(v, f"{caminho}.")
                continue
            if isinstance(v, dict) and not _pedido(caminho):
                continue  # mensagem vazia que ninguem pediu
            if k == "resource_name" and not _pedido(caminho):
                continue
            plana[caminho] = v

    _desce(linha, "")
    return plana
