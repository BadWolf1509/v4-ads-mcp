"""Sondagens do spec 2026-09-26 (metricas Meta dizem o que mediram). So leitura.

Refaca quando a Graph API mudar de versao ou entrar conta com pixel de compra: o mapa
canonico do spec (omni_purchase, lead, conversa iniciada) foi confirmado numa conta so.

O que cada bloco decide (nao basta "voltou 200" — F53/F54/F55):
  (1) taxonomia: quais action_type cada conta devolve em actions/action_values/
      purchase_roas, e se os nomes de compra/lead sao recortes do MESMO numero;
      escala do ctr (porcentagem ou fracao), comparada com cliques/impressoes.
  (2) reach/frequency: presentes nas linhas de cada breakdown, ou ausentes.
  (3) atribuicao: o padrao contra unified/action_report_time/janela, com CONTROLE de
      valor invalido — se o invalido tambem voltasse 200, a API ignoraria o parametro.
  (4) cabecalhos de uso: forma do BUC, e onde vem a quota do app.

Token do system user no header Authorization (F82), nunca na URL. Imprime so nomes de
conta, tipos de acao e numeros agregados — nenhum segredo. Requer `gcloud auth login`.

    python scripts/probe_meta_metricas.py
"""

import asyncio
import collections
import json
import subprocess
import sys
from datetime import date, timedelta
from typing import Any

import asyncpg
import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://graph.facebook.com/v22.0"
FIM = date.today() - timedelta(days=1)
INICIO = FIM - timedelta(days=29)
JANELA = json.dumps({"since": INICIO.isoformat(), "until": FIM.isoformat()})
BREAKDOWNS = (
    "publisher_platform",
    "impression_device",
    "country",
    "hourly_stats_aggregated_by_advertiser_time_zone",
)
ATRIBUICAO = {
    "padrao": {},
    "unified=true": {"use_unified_attribution_setting": "true"},
    "CONTROLE unified=xyz": {"use_unified_attribution_setting": "xyz"},
    "report_time=conversion": {"action_report_time": "conversion"},
    "report_time=impression": {"action_report_time": "impression"},
    "CONTROLE report_time=xyz": {"action_report_time": "xyz"},
    "janela=1d_click": {"action_attribution_windows": '["1d_click"]'},
    "CONTROLE janela=xyz": {"action_attribution_windows": '["xyz"]'},
}


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


async def contas() -> list[tuple[str, str]]:
    conn = await asyncpg.connect(secret("database-url"), timeout=30)
    try:
        async with conn.transaction(readonly=True):
            rows = await conn.fetch(
                "SELECT ad_account_id, account_name FROM meta_ad_accounts "
                "WHERE is_active AND su_reachable ORDER BY account_name"
            )
    finally:
        await conn.close()
    return [(r["ad_account_id"], r["account_name"]) for r in rows]


async def insights(
    http: httpx.AsyncClient, conta: str, **params: Any
) -> tuple[int, dict[str, Any], httpx.Headers]:
    r = await http.get(f"{BASE}/{conta}/insights", params={"time_range": JANELA, **params})
    try:
        corpo = r.json()
    except ValueError:
        corpo = {"_nao_json": r.text[:120]}
    return r.status_code, corpo, r.headers


def tipos(lista: list[dict[str, Any]] | None) -> dict[str, Any]:
    return {a["action_type"]: a.get("value") for a in lista or []}


async def main() -> None:
    lista = await contas()
    token = secret("meta-system-user-token")
    print(f"janela {INICIO}..{FIM}; contas ativas e alcancaveis: {len(lista)}")
    em_actions: collections.Counter[str] = collections.Counter()
    em_values: collections.Counter[str] = collections.Counter()
    em_roas: collections.Counter[str] = collections.Counter()
    com_conversao: list[tuple[str, str]] = []
    cabecalho = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30.0, headers=cabecalho) as http:
        print("\n== (1) taxonomia e ctr, nivel conta")
        for conta, nome in lista:
            campos = "spend,impressions,clicks,ctr,actions,action_values,purchase_roas"
            st, corpo, _ = await insights(http, conta, level="account", fields=campos)
            if st != 200 or not corpo.get("data"):
                print("  ", nome, "HTTP", st, "sem linha" if st == 200 else str(corpo)[:120])
                continue
            linha = corpo["data"][0]
            acts = tipos(linha.get("actions"))
            em_actions.update(acts.keys())
            em_values.update(tipos(linha.get("action_values")).keys())
            em_roas.update(tipos(linha.get("purchase_roas")).keys())
            imp = float(linha.get("impressions") or 0)
            calc = round(float(linha.get("clicks") or 0) / imp * 100, 4) if imp else None
            compra = {k: v for k, v in acts.items() if "purchase" in k}
            lead = {k: v for k, v in acts.items() if "lead" in k}
            print(
                "  ",
                nome[:28].ljust(28),
                "ctr",
                linha.get("ctr"),
                "calc%",
                calc,
                "| compra",
                compra or "-",
                "| lead",
                lead or "-",
            )
            if compra or lead:
                com_conversao.append((conta, nome))
        print("\n  actions:", dict(em_actions.most_common()))
        print("  action_values:", dict(em_values.most_common()))
        print("  purchase_roas:", dict(em_roas.most_common()))

        alvos = com_conversao[:2] or lista[:1]
        print("\n== (2) reach/frequency por breakdown, nivel campanha")
        for conta, nome in alvos:
            for bd in BREAKDOWNS:
                st, corpo, _ = await insights(
                    http,
                    conta,
                    level="campaign",
                    breakdowns=bd,
                    fields="spend,reach,frequency",
                    limit=50,
                )
                linhas = corpo.get("data") or []
                sem = sum(1 for x in linhas if "reach" not in x or "frequency" not in x)
                print(
                    "  ",
                    nome[:24],
                    bd,
                    "HTTP",
                    st,
                    "linhas",
                    len(linhas),
                    "sem reach/frequency:",
                    sem,
                )

        print("\n== (3) atribuicao, nivel conta")
        for conta, nome in alvos:
            for rotulo, extra in ATRIBUICAO.items():
                st, corpo, _ = await insights(
                    http, conta, level="account", fields="actions", **extra
                )
                linha = (corpo.get("data") or [{}])[0] if st == 200 else {}
                conv = {
                    k: v
                    for k, v in tipos(linha.get("actions")).items()
                    if "purchase" in k or "lead" in k
                }
                print(
                    "  ",
                    nome[:24],
                    rotulo.ljust(26),
                    "HTTP",
                    st,
                    conv if st == 200 else str(corpo)[:140],
                )

        print("\n== (4) cabecalhos de uso")
        if lista:
            _, _, h = await insights(http, lista[0][0], level="account", fields="spend")
            for k in (
                "x-business-use-case-usage",
                "x-app-usage",
                "x-ad-account-usage",
                "x-fb-ads-insights-throttle",
            ):
                print("  ", k, "=>", h.get(k))


if __name__ == "__main__":
    asyncio.run(main())
