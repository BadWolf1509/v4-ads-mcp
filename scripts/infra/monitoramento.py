"""Monitoramento como código: canal de e-mail, uptime check, métricas log-based e policies.

As definições vivem em `scripts/infra/monitoramento_defs/*.json`, copiadas do estado real de
produção, com marcadores `{PROJECT}`, `{HOST}`, `{CHANNEL}`, `{CHECK_ID}` e `{EMAIL}`. O aplicador
só CRIA o que falta: recurso que existe diferente do modelo é apontado e nunca sobrescrito nem
apagado (sai com 1 para o operador olhar). Sem `--apply`, só imprime o plano.

    python -m scripts.infra.monitoramento --project-id X --host H --alert-email E [--apply]

Rode depois do primeiro deploy: o uptime check precisa do serviço no ar, senão alarma na hora.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DEFS = Path(__file__).resolve().parent / "monitoramento_defs"
_RECURSOS_DOS_ARQUIVOS = ("canal", "uptime", "metricas", "policies")
_MARCADOR = re.compile(r"\{([A-Z_]+)\}")


def carregar_modelos(defs: Path = DEFS) -> dict[str, list[dict[str, Any]]]:
    """Lê os 4 arquivos de modelo; cada chave é sempre uma lista."""
    return {
        nome: json.loads((defs / f"{nome}.json").read_text(encoding="utf-8"))
        for nome in _RECURSOS_DOS_ARQUIVOS
    }


def renderizar(obj: Any, valores: Mapping[str, str]) -> Any:
    """Troca `{CHAVE}` em toda string, recursivamente. Marcador que sobra levanta `ValueError`."""
    if isinstance(obj, dict):
        return {k: renderizar(v, valores) for k, v in obj.items()}
    if isinstance(obj, list):
        return [renderizar(v, valores) for v in obj]
    if isinstance(obj, str):
        texto = obj
        for chave, valor in valores.items():
            texto = texto.replace("{" + chave + "}", valor)
        sobra = _MARCADOR.search(texto)
        if sobra:
            raise ValueError(f"marcador sem valor: {{{sobra.group(1)}}} em {obj!r}")
        return texto
    return obj


def contem(modelo: Any, real: Any) -> bool:
    """O recurso real satisfaz o modelo? Dicts por subconjunto (o servidor acrescenta campos);
    listas com o mesmo tamanho, elemento a elemento; escalares por igualdade."""
    if isinstance(modelo, dict):
        return isinstance(real, dict) and all(
            k in real and contem(v, real[k]) for k, v in modelo.items()
        )
    if isinstance(modelo, list):
        return (
            isinstance(real, list)
            and len(modelo) == len(real)
            and all(contem(m, r) for m, r in zip(modelo, real, strict=True))
        )
    return bool(modelo == real)
