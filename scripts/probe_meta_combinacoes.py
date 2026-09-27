"""Sonda as combinacoes de params que `build_insights_call` monta, contra a Graph API real.

Read-only. Cada parametro ja tinha sido sondado sozinho (`probe_meta_sort.py`: `sort` em
`level=campaign`; `probe_meta_metricas.py`: a atribuicao em `level=account` com
`fields=actions`), mas nenhuma chamada real tinha levado os dois JUNTOS com `breakdowns`
e com a lista de fields de cada nivel — a classe do F53/F54/F55, em que a API recusou a
combinacao e o primeiro a ver foi a producao (revisao final do F194).

Manda exatamente o que as tools mandam: o overview (`account`, sem breakdown), o trio
(`campaign`/`adset`/`ad`, sem breakdown) e o breakdown (os mesmos tres niveis x os quatro
cortes de `BREAKDOWN_META_PARAM`). Controle: a combinacao mais carregada com
`use_unified_attribution_setting` invalido tem de voltar 400 — sem isso, um 200 nas outras
nao provaria que a API le o parametro nelas.

Token do system user no header Authorization (F82), nunca na URL. Imprime so status,
contagem de linhas e a mensagem de erro da Graph — nenhum valor de metrica.

Uso, da raiz do repo (o `-m` poe a raiz no path, e o script importa o construtor de `src/`):
    python -m scripts.probe_meta_combinacoes act_<id>
"""

import asyncio
import subprocess
import sys
from datetime import date, timedelta
from typing import Any

import httpx

from src.meta_ads.client import META_GRAPH_API_VERSION
from src.meta_ads.insights import BREAKDOWN_META_PARAM, build_insights_call

BASE = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}"


def secret(nome: str) -> str:
    r = subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            f"--secret={nome}",
            "--project=v4-ads-mcp",
        ],
        capture_output=True,
        text=True,
        timeout=90,
        shell=(sys.platform == "win32"),
    )
    if r.returncode != 0:
        sys.exit(f"gcloud falhou: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def combinacoes(conta: str, inicio: date, fim: date) -> list[tuple[str, str, dict[str, Any]]]:
    """(rotulo, edge, params) na forma exata do construtor."""
    saida = []
    edge, params = build_insights_call(
        level="account", ad_account_id=conta, start=inicio, end=fim, limit=1
    )
    saida.append(("overview account", edge, params))
    for nivel in ("campaign", "adset", "ad"):
        edge, params = build_insights_call(
            level=nivel, ad_account_id=conta, start=inicio, end=fim, limit=5
        )
        saida.append((f"trio {nivel}", edge, params))
        for corte, valor in BREAKDOWN_META_PARAM.items():
            edge, params = build_insights_call(
                level=nivel,
                ad_account_id=conta,
                start=inicio,
                end=fim,
                limit=5,
                breakdowns=valor,
            )
            saida.append((f"breakdown {nivel} x {corte}", edge, params))
    return saida


async def main(conta: str) -> int:
    fim = date.today()
    inicio = fim - timedelta(days=29)
    cabecalho = {"Authorization": f"Bearer {secret('meta-system-user-token')}"}
    casos = combinacoes(conta, inicio, fim)
    rotulo, edge, params = next(c for c in casos if c[0] == "breakdown ad x hourly")
    controle = (
        f"CONTROLE {rotulo} + atribuicao invalida",
        edge,
        {**params, "use_unified_attribution_setting": "banana"},
    )
    recusadas = 0
    async with httpx.AsyncClient(timeout=60.0, headers=cabecalho) as http:
        for rotulo, edge, params in [*casos, controle]:
            r = await http.get(BASE + edge, params=params)
            corpo = r.json()
            if r.status_code == 200:
                linhas = corpo.get("data") or []
                com_acoes = sum(1 for linha in linhas if "actions" in linha)
                print(f"{rotulo:<40} 200  linhas={len(linhas)}  com_actions={com_acoes}")
            else:
                msg = (corpo.get("error") or {}).get("message", "")[:140]
                print(f"{rotulo:<40} {r.status_code}  {msg}")
                if not rotulo.startswith("CONTROLE"):
                    recusadas += 1
    return recusadas


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].startswith("act_"):
        sys.exit("uso: python -m scripts.probe_meta_combinacoes act_<id>")
    sys.exit(asyncio.run(main(sys.argv[1])))
