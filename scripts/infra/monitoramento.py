"""Monitoramento como código: canal de e-mail, uptime check, métricas log-based e policies.

As definições vivem em `scripts/infra/monitoramento_defs/*.json`, copiadas do estado real de
produção, com marcadores `{PROJECT}`, `{HOST}`, `{CHANNEL}`, `{CHECK_ID}` e `{EMAIL}`. O aplicador
só CRIA o que falta: recurso que existe diferente do modelo é apontado e nunca sobrescrito nem
apagado (sai com 1 para o operador olhar). Sem `--apply`, só imprime o plano.

    python -m scripts.infra.monitoramento --project-id X --host H --alert-email E [--apply]

Rode depois do primeiro deploy: o uptime check precisa do serviço no ar, senão alarma na hora.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
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
    acao: str  # criar | criado | igual | diferente | duplicado | bloqueado


class MonitoramentoApiError(Exception):
    """Falha de chamada à API, com método, URL e o corpo que o Google devolveu."""


A_CRIAR = "<a criar>"  # sentinela do dry-run para ID que só existe depois do POST
PROBLEMAS = frozenset({"diferente", "duplicado", "bloqueado"})


def _um(
    api: Api,
    *,
    recurso: str,
    modelo: dict[str, Any],
    chave: Callable[[dict[str, Any]], str],
    existentes: list[dict[str, Any]],
    apply: bool,
    bloqueado: bool,
) -> tuple[Linha, dict[str, Any] | None]:
    alvo = chave(modelo)
    achados = [e for e in existentes if chave(e) == alvo]
    if len(achados) > 1:
        # Duas cópias com a mesma identidade: qual vale dependeria da ordem da lista. Não escolhe.
        return Linha(recurso, alvo, "duplicado"), None
    if achados:
        real = achados[0]
        return Linha(recurso, alvo, "igual" if contem(modelo, real) else "diferente"), real
    if bloqueado:
        # Depende de um pai divergente ou duplicado: criar agora o amarraria ao recurso errado.
        return Linha(recurso, alvo, "bloqueado"), None
    if not apply:
        return Linha(recurso, alvo, "criar"), None
    return Linha(recurso, alvo, "criado"), api.criar(recurso, modelo)


def aplicar(
    api: Api,
    *,
    project_id: str,
    host: str,
    alert_email: str,
    apply: bool,
    ao_registrar: Callable[[Linha], None] | None = None,
) -> list[Linha]:
    """Canal → uptime → métricas → policies; cada etapa resolve o ID que a seguinte usa.

    Só cria o que falta. O que existe e diverge do modelo vira `diferente` e não é tocado; o que
    existe em duplicata vira `duplicado`; o que depende de um pai assim vira `bloqueado` e não é
    criado. `ao_registrar` recebe cada linha assim que ela é decidida (antes do próximo POST)."""
    modelos = carregar_modelos()
    valores = {"PROJECT": project_id, "HOST": host, "EMAIL": alert_email}
    pais_com_problema: set[str] = set()
    linhas: list[Linha] = []

    def etapa(
        recurso: str, lista: list[dict[str, Any]], chave: Callable[[dict[str, Any]], str]
    ) -> list[tuple[Linha, dict[str, Any] | None]]:
        existentes = api.listar(recurso)
        saida = []
        for m in lista:
            cru = json.dumps(m)
            linha, real = _um(
                api,
                recurso=recurso,
                modelo=renderizar(m, valores),
                chave=chave,
                existentes=existentes,
                apply=apply,
                bloqueado=any("{" + pai + "}" in cru for pai in pais_com_problema),
            )
            linhas.append(linha)
            if ao_registrar is not None:
                ao_registrar(linha)
            saida.append((linha, real))
        return saida

    def resolver_pai(
        marcador: str, resultado: tuple[Linha, dict[str, Any] | None], so_o_id: bool
    ) -> None:
        linha, real = resultado
        if linha.acao in PROBLEMAS:
            pais_com_problema.add(marcador)
        if real is None:
            valores[marcador] = A_CRIAR
        else:
            valores[marcador] = real["name"].rsplit("/", 1)[1] if so_o_id else real["name"]

    def chave_canal(c: dict[str, Any]) -> str:
        return f"{c.get('type')}:{c.get('labels', {}).get('email_address')}"

    [canal] = etapa("notificationChannels", modelos["canal"], chave_canal)
    resolver_pai("CHANNEL", canal, so_o_id=False)
    [check] = etapa("uptimeCheckConfigs", modelos["uptime"], lambda u: str(u.get("displayName")))
    resolver_pai("CHECK_ID", check, so_o_id=True)
    etapa("metrics", modelos["metricas"], lambda m: str(m.get("name")))
    etapa("alertPolicies", modelos["policies"], lambda p: str(p.get("displayName")))
    return linhas


def codigo_de_saida(linhas: list[Linha]) -> int:
    return 1 if any(linha.acao in PROBLEMAS for linha in linhas) else 0


_BASES = {
    "notificationChannels": "https://monitoring.googleapis.com/v3/projects/{p}/notificationChannels",
    "uptimeCheckConfigs": "https://monitoring.googleapis.com/v3/projects/{p}/uptimeCheckConfigs",
    "alertPolicies": "https://monitoring.googleapis.com/v3/projects/{p}/alertPolicies",
    "metrics": "https://logging.googleapis.com/v2/projects/{p}/metrics",
}


class RestApi:
    """Monitoring v3 + Logging v2 por REST. `listar` segue `nextPageToken`; chave ausente = []."""

    def __init__(self, project_id: str, token: str) -> None:
        self._p = project_id
        self._token = token

    def _req(self, url: str, corpo: dict[str, Any] | None = None) -> dict[str, Any]:
        req = urllib.request.Request(
            url,
            method="GET" if corpo is None else "POST",
            data=None if corpo is None else json.dumps(corpo).encode(),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "x-goog-user-project": self._p,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                dados: dict[str, Any] = json.loads(r.read() or b"{}")
                return dados
        except urllib.error.HTTPError as e:
            # O corpo é o que diz o que corrigir (ex.: "only log-based alert policies may ...").
            corpo_erro = e.read().decode("utf-8", "replace")
            raise MonitoramentoApiError(
                f"{req.get_method()} {url} -> {e.code}: {corpo_erro}"
            ) from e
        except urllib.error.URLError as e:
            raise MonitoramentoApiError(f"{req.get_method()} {url} -> {e.reason}") from e

    def listar(self, recurso: str) -> list[dict[str, Any]]:
        base = _BASES[recurso].format(p=self._p)
        itens: list[dict[str, Any]] = []
        token = ""
        while True:
            url = base + (f"?pageToken={urllib.parse.quote(token)}" if token else "")
            pagina = self._req(url)
            itens.extend(pagina.get(recurso, []))
            token = pagina.get("nextPageToken", "")
            if not token:
                return itens

    def criar(self, recurso: str, corpo: dict[str, Any]) -> dict[str, Any]:
        return self._req(_BASES[recurso].format(p=self._p), corpo)


def _api_real(project_id: str, conta: str | None = None) -> Api:
    """Token do `gcloud` da conta ATIVA, ou de `conta` (`--gcloud-account`), que precisa ser dona
    do projeto. Credencial vencida: o timeout corta em vez de pendurar calado, e o `main` mostra
    o stderr do gcloud."""
    gcloud = shutil.which("gcloud")
    if gcloud is None:
        raise SystemExit("gcloud não encontrado no PATH")
    cmd = [gcloud, "auth", "print-access-token", *([f"--account={conta}"] if conta else [])]
    token = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60).stdout
    return RestApi(project_id, token.strip())


def _imprimir(linha: Linha) -> None:
    print(f"{linha.acao:<10} {linha.tipo:<22} {linha.chave}", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--project-id", required=True)
    ap.add_argument(
        "--host", required=True, help="host do serviço, ex. v4-ads-mcp-<n>.<região>.run.app"
    )
    ap.add_argument("--alert-email", required=True)
    ap.add_argument("--gcloud-account", help="conta do gcloud (padrão: a ativa)")
    ap.add_argument("--apply", action="store_true", help="cria o que falta (sem isto, só o plano)")
    a = ap.parse_args(argv)
    try:
        api = _api_real(a.project_id, a.gcloud_account)
        linhas = aplicar(
            api,
            project_id=a.project_id,
            host=a.host,
            alert_email=a.alert_email,
            apply=a.apply,
            ao_registrar=_imprimir,
        )
    except subprocess.TimeoutExpired:
        print("gcloud não respondeu: rode `gcloud auth login` e repita.", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"gcloud falhou ao emitir o token:\n{e.stderr}", file=sys.stderr)
        return 1
    except MonitoramentoApiError as e:
        print(f"\nParou com erro da API (o que saiu acima já foi feito):\n{e}", file=sys.stderr)
        return 1
    rc = codigo_de_saida(linhas)
    if rc:
        print(
            "\nHá recurso diferente, duplicado ou bloqueado: nada disso foi tocado."
            " Compare com scripts/infra/monitoramento_defs/.",
            file=sys.stderr,
        )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
