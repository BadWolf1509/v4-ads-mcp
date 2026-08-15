"""Probe F88 — o Meta Insights aceita `sort` server-side, e ele e confiavel?

Hoje as tools Meta leem ate 5 paginas e ordenam por gasto NO CLIENTE. Funciona,
mas numa conta que exceda esse teto o "top gastadores" pode nao conter o maior
gastador — por isso a resposta traz `truncated`. O certo definitivo e ordenar
server-side (`sort=spend_descending`) e deixar o `limit` cortar a cauda, como o
lado Google ja faz com `ORDER BY metrics.cost_micros DESC LIMIT n`.

Isso e superficie de API Meta nao validada, e a regra F53/F54/F55 diz pra nao
shippar sem probe. Este script fecha a duvida.

O teste que decide NAO e "o request com sort volta 200". A Graph API tem
historico de ACEITAR CALADA param que nao entende (foi assim que F53/F54/F55
nasceram), entao um 200 nao prova que o sort foi aplicado. Os testes que
importam sao:

  (D) valor INVALIDO de sort -> se voltar 200 igual, a API ignora o param e o
      sort server-side e uma ilusao;
  (E) sort + limit MENOR que o total -> a resposta contem o topo REAL
      (comparado contra o ranking calculado no cliente sobre a lista inteira)?
      Este e o ganho todo: ordenar antes de cortar.

Requer `gcloud auth login`. Imprime so nomes de campanha e valores agregados de
gasto da propria conta do gestor — nenhum segredo.

    python scripts/probe_meta_sort.py
"""

import subprocess
import sys
from datetime import UTC, datetime, timedelta

import httpx

BASE = "https://graph.facebook.com/v22.0"

# Nome de campanha em PT-BR nao cabe no cp1252 do console do Windows.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

P = lambda *a: print(*a, flush=True)  # noqa: E731


def secret(nome: str) -> str:
    r = subprocess.run(
        f"gcloud secrets versions access latest --secret={nome} --project=v4-ads-mcp",
        capture_output=True,
        text=True,
        check=True,
        shell=True,
    )
    return r.stdout.strip()


def insights(http: httpx.Client, token: str, conta: str, **extra) -> tuple[int, list, str]:
    fim = datetime.now(UTC).date()
    inicio = fim - timedelta(days=90)
    params = {
        "level": "campaign",
        "fields": "campaign_name,spend",
        "time_range": f'{{"since":"{inicio}","until":"{fim}"}}',
        "limit": 100,
        **extra,
    }
    r = http.get(
        f"{BASE}/{conta}/insights",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
    )
    corpo = r.json()
    if "error" in corpo:
        e = corpo["error"]
        return (
            r.status_code,
            [],
            f"code={e.get('code')} sub={e.get('error_subcode')} {e.get('message')[:80]}",
        )
    return r.status_code, corpo.get("data", []), ""


def gastos(linhas: list) -> list[tuple[str, float]]:
    return [(d.get("campaign_name", "?"), float(d.get("spend", 0) or 0)) for d in linhas]


def main() -> int:
    token = secret("meta-system-user-token")
    with httpx.Client(timeout=60) as http:
        P("=== escolhendo uma conta com campanhas suficientes ===")
        r = http.get(
            f"{BASE}/me/adaccounts",
            params={"fields": "id,name", "limit": 25},
            headers={"Authorization": f"Bearer {token}"},
        )
        conta = None
        for c in r.json().get("data", []):
            st, linhas, err = insights(http, token, c["id"])
            if not err and len(linhas) >= 4:
                conta = c["id"]
                P(f"   usando {c['id']} ({len(linhas)} campanhas com dados em 90d)\n")
                break
        if conta is None:
            P("   nenhuma conta com >=4 campanhas em 90d — probe inconclusiva")
            return 1

        st, base, err = insights(http, token, conta)
        ranking_cliente = sorted(gastos(base), key=lambda x: -x[1])
        P("=== A) sem sort — ranking calculado no CLIENTE (verdade de referencia) ===")
        for nome, v in ranking_cliente[:5]:
            P(f"   {v:>10.2f}  {nome[:52]}")
        P(f"   (total {len(base)} campanhas)\n")

        P("=== B) sort=spend_descending (forma de lista) ===")
        st, linhas, err = insights(http, token, conta, **{"sort[0]": "spend_descending"})
        P(f"   HTTP {st} {err or 'OK'}")
        if not err:
            ordem = gastos(linhas)
            ok = ordem == sorted(ordem, key=lambda x: -x[1])
            P(f"   veio ordenado por gasto desc? {ok}")

        P("=== C) sort=spend_descending (forma escalar) ===")
        st, linhas_c, err_c = insights(http, token, conta, sort="spend_descending")
        P(f"   HTTP {st} {err_c or 'OK'}")
        if not err_c:
            ordem = gastos(linhas_c)
            P(f"   veio ordenado por gasto desc? {ordem == sorted(ordem, key=lambda x: -x[1])}")

        P("\n=== D) DECISIVO — valor INVALIDO de sort ===")
        st, linhas_d, err_d = insights(http, token, conta, sort="banana_ascending")
        if err_d:
            P(f"   HTTP {st} ERRO -> {err_d}")
            P("   ==> a API VALIDA o param; logo o 200 dos testes acima significa algo")
        else:
            P(f"   HTTP {st} OK (!!) — a API ACEITOU um sort inexistente")
            P("   ==> aceitacao silenciosa: 200 com sort NAO prova que ordenou")

        P("\n=== E) DECISIVO — sort + limit menor que o total ===")
        topo_real = [n for n, _ in ranking_cliente[:3]]
        st, linhas_e, err_e = insights(http, token, conta, sort="spend_descending", limit=3)
        if err_e:
            P(f"   HTTP {st} ERRO -> {err_e}")
        else:
            veio = [n for n, _ in gastos(linhas_e)]
            P(f"   topo real (cliente): {topo_real}")
            P(f"   veio do servidor   : {veio}")
            P(f"   ==> ordena ANTES de cortar? {veio == topo_real}")

        P("\n=== F) controle: limit=3 SEM sort (o que aconteceria hoje) ===")
        st, linhas_f, err_f = insights(http, token, conta, limit=3)
        if not err_f:
            veio = [n for n, _ in gastos(linhas_f)]
            P(f"   veio: {veio}")
            P(f"   ==> por acaso ja era o topo? {veio == topo_real}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
