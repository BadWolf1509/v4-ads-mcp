"""Sonda `time_increment` no /insights de `level=account`, contra a Graph API real.

Read-only. O saldo da conta soma o gasto diario; para isso `build_insights_call` ganhou
`time_increment`. Nao entrou por analogia: este script manda o param na forma exata do
construtor e um CONTROLE com valor invalido — sem o 400 do controle, um 200 nao provaria
que a API le o parametro (a classe do F53/F54/F55).

Tres casos: `time_increment=1`, controle `abc` e sem o param.

Resultado de 29/10 (act_3709029949237406): `1` -> 200, uma linha por dia COM entrega
(dias sem entrega omitidos), ordenadas por gasto; `abc` -> HTTP 400
`(#100) ... must be one of the following values: monthly, all_days`; sem o param -> 200,
uma linha so.

Token do system user no header Authorization (F82), nunca na URL. Imprime so status,
contagem de linhas, as 4 primeiras datas e a mensagem de erro — nenhum valor de metrica.

Uso, da raiz do repo:
    python -m scripts.probe_meta_time_increment act_<id>
"""

import asyncio
import sys
from datetime import date, timedelta
from typing import Any

import httpx

from scripts.probe_meta_combinacoes import BASE, secret
from src.meta_ads.insights import build_insights_call


async def main(conta: str) -> int:
    fim = date.today()
    inicio = fim - timedelta(days=29)
    cabecalho = {"Authorization": f"Bearer {secret('meta-system-user-token')}"}
    edge, base = build_insights_call(
        level="account", ad_account_id=conta, start=inicio, end=fim, limit=100, time_increment=1
    )
    sem = {k: v for k, v in base.items() if k != "time_increment"}
    casos: list[tuple[str, dict[str, Any], int]] = [
        ("time_increment=1", base, 200),
        ("CONTROLE time_increment=abc", {**base, "time_increment": "abc"}, 400),
        ("sem time_increment", sem, 200),
    ]
    divergentes = 0
    async with httpx.AsyncClient(timeout=60.0, headers=cabecalho) as http:
        for rotulo, params, esperado in casos:
            r = await http.get(BASE + edge, params=params)
            corpo = r.json()
            if r.status_code == 200:
                linhas = corpo.get("data") or []
                datas = [linha.get("date_start") for linha in linhas[:4]]
                print(f"{rotulo:<30} 200  linhas={len(linhas)}  datas={datas}")
            else:
                msg = (corpo.get("error") or {}).get("message", "")[:140]
                print(f"{rotulo:<30} {r.status_code}  {msg}")
            if r.status_code != esperado:
                divergentes += 1
    return divergentes


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].startswith("act_"):
        sys.exit("uso: python -m scripts.probe_meta_time_increment act_<id>")
    sys.exit(asyncio.run(main(sys.argv[1])))
