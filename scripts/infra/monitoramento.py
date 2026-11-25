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
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, NamedTuple, Protocol

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


class Api(Protocol):
    """Recursos: notificationChannels, uptimeCheckConfigs, alertPolicies (Monitoring v3) e metrics (Logging v2)."""

    def listar(self, recurso: str) -> list[dict[str, Any]]: ...

    def criar(self, recurso: str, corpo: dict[str, Any]) -> dict[str, Any]: ...


class Linha(NamedTuple):
    tipo: str
    chave: str
    acao: str  # criar | criado | igual | diferente


A_CRIAR = "<a criar>"  # sentinela do dry-run para ID que só existe depois do POST


def _um(
    api: Api,
    *,
    recurso: str,
    modelo: dict[str, Any],
    chave: Callable[[dict[str, Any]], str],
    existentes: list[dict[str, Any]],
    apply: bool,
) -> tuple[Linha, dict[str, Any] | None]:
    alvo = chave(modelo)
    real = next((e for e in existentes if chave(e) == alvo), None)
    if real is not None:
        return Linha(recurso, alvo, "igual" if contem(modelo, real) else "diferente"), real
    if not apply:
        return Linha(recurso, alvo, "criar"), None
    return Linha(recurso, alvo, "criado"), api.criar(recurso, modelo)


def aplicar(api: Api, *, project_id: str, host: str, alert_email: str, apply: bool) -> list[Linha]:
    """Canal → uptime → métricas → policies; cada etapa resolve o ID que a seguinte usa.

    Só cria o que falta. O que existe e diverge do modelo vira `diferente` e não é tocado."""
    modelos = carregar_modelos()
    valores = {"PROJECT": project_id, "HOST": host, "EMAIL": alert_email}
    linhas: list[Linha] = []

    def etapa(
        recurso: str, lista: list[dict[str, Any]], chave: Callable[[dict[str, Any]], str]
    ) -> list[dict[str, Any] | None]:
        existentes = api.listar(recurso)
        reais = []
        for m in lista:
            linha, real = _um(
                api,
                recurso=recurso,
                modelo=renderizar(m, valores),
                chave=chave,
                existentes=existentes,
                apply=apply,
            )
            linhas.append(linha)
            reais.append(real)
        return reais

    def chave_canal(c: dict[str, Any]) -> str:
        return f"{c.get('type')}:{c.get('labels', {}).get('email_address')}"

    [canal] = etapa("notificationChannels", modelos["canal"], chave_canal)
    valores["CHANNEL"] = canal["name"] if canal else A_CRIAR
    [check] = etapa("uptimeCheckConfigs", modelos["uptime"], lambda u: str(u.get("displayName")))
    valores["CHECK_ID"] = check["name"].rsplit("/", 1)[1] if check else A_CRIAR
    etapa("metrics", modelos["metricas"], lambda m: str(m.get("name")))
    etapa("alertPolicies", modelos["policies"], lambda p: str(p.get("displayName")))
    return linhas


def codigo_de_saida(linhas: list[Linha]) -> int:
    return 1 if any(linha.acao == "diferente" for linha in linhas) else 0
