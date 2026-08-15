"""Probe F82 — fecha a validacao empirica antes de migrar os 3 call-sites Meta.

Os `access_token`/`client_secret`/`input_token` de `src/auth/meta_oauth.py`
viajam na QUERY STRING, logo aparecem em qualquer log de URL. O vazamento
observado ja foi fechado silenciando os loggers httpx/httpcore, mas a causa
raiz e o transporte. A migracao pro header `Authorization` esta bloqueada em
UMA duvida — e este script a resolve.

**O que ja esta provado** (sem gastar segredo, so mandando um token falso):
`Bearer <lixo>` e `OAuth <lixo>` devolvem code 190 "Cannot parse access
token", enquanto a AUSENCIA do header devolve code 2500 "An active access
token must be used". Erros diferentes = nos dois formatos o header foi lido e
o token entregue ao parser. Ou seja, `Bearer` e aceito.

**O que falta:** confirmar que um token VALIDO autentica igual pelo header, o
que exige o token real — e por isso este script existe.

Requer `gcloud auth login` (le os secrets do Secret Manager em memoria).
Imprime SOMENTE status, contagem e nomes de campo — nunca o segredo.

    python scripts/probe_meta_auth_header.py

Leia o resultado assim:
  (B) igual a (A)  -> pode migrar /me/adaccounts pro header
  (E) HTTP 200     -> da pra remover o access_token da URL de paging.next
                      (sem isso o vazamento volta na 2a pagina)
  (G) HTTP 200     -> /debug_token aceita POST, tirando o input_token da URL
                      (ele NAO e credencial do chamador, entao nao cabe no header)
"""

import subprocess
import sys

import httpx

BASE = "https://graph.facebook.com/v22.0"


def secret(nome: str) -> str:
    out = subprocess.run(
        f"gcloud secrets versions access latest --secret={nome} --project=v4-ads-mcp",
        capture_output=True,
        text=True,
        check=True,
        shell=True,
    )
    return out.stdout.strip()


def resumo(r: httpx.Response) -> str:
    try:
        corpo = r.json()
    except Exception:
        return f"HTTP {r.status_code} (corpo nao-JSON)"
    if "error" in corpo:
        e = corpo["error"]
        return f"HTTP {r.status_code} ERRO code={e.get('code')} sub={e.get('error_subcode')} msg={e.get('message')[:70]!r}"
    dados = corpo.get("data")
    if isinstance(dados, list):
        return f"HTTP {r.status_code} OK data={len(dados)} item(s) chaves={sorted(dados[0])[:4] if dados else []}"
    return f"HTTP {r.status_code} OK chaves={sorted(corpo)[:6]}"


def main() -> int:
    su = secret("meta-system-user-token")
    app_id = secret("meta-app-id")
    app_secret = secret("meta-app-secret")
    app_token = f"{app_id}|{app_secret}"

    with httpx.Client(timeout=30) as http:
        print("=== A) /me/adaccounts — query param (como esta hoje) ===")
        r = http.get(
            f"{BASE}/me/adaccounts", params={"fields": "id,name", "limit": 2, "access_token": su}
        )
        print("  ", resumo(r))
        base_ok = r.status_code == 200
        ids_query = [d["id"] for d in r.json().get("data", [])] if base_ok else []

        print("=== B) /me/adaccounts — Authorization: Bearer ===")
        r = http.get(
            f"{BASE}/me/adaccounts",
            params={"fields": "id,name", "limit": 2},
            headers={"Authorization": f"Bearer {su}"},
        )
        print("  ", resumo(r))
        ids_bearer = [d["id"] for d in r.json().get("data", [])] if r.status_code == 200 else []
        print("   MESMO RESULTADO QUE (A)?", ids_query == ids_bearer and bool(ids_query))

        print("=== C) /me/adaccounts — Authorization: OAuth ===")
        r = http.get(
            f"{BASE}/me/adaccounts",
            params={"fields": "id,name", "limit": 2},
            headers={"Authorization": f"OAuth {su}"},
        )
        print("  ", resumo(r))

        print("=== D) paging.next traz access_token embutido? ===")
        r = http.get(
            f"{BASE}/me/adaccounts",
            params={"fields": "id,name", "limit": 1},
            headers={"Authorization": f"Bearer {su}"},
        )
        nxt = ((r.json().get("paging") or {}).get("next") or "") if r.status_code == 200 else ""
        print("   next existe?", bool(nxt), "| contem access_token=?", "access_token=" in nxt)
        if nxt:
            from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

            u = urlparse(nxt)
            q = parse_qs(u.query)
            q.pop("access_token", None)
            limpa = urlunparse(u._replace(query=urlencode(q, doseq=True)))
            print("=== E) next SEM access_token + header Bearer funciona? ===")
            r2 = http.get(limpa, headers={"Authorization": f"Bearer {su}"})
            print("  ", resumo(r2))

        print("=== F) /debug_token — app token no header, input_token na query ===")
        r = http.get(
            f"{BASE}/debug_token",
            params={"input_token": su},
            headers={"Authorization": f"Bearer {app_token}"},
        )
        print("  ", resumo(r))

        print("=== G) /debug_token via POST (tiraria input_token da URL) ===")
        r = http.post(
            f"{BASE}/debug_token",
            data={"input_token": su},
            headers={"Authorization": f"Bearer {app_token}"},
        )
        print("  ", resumo(r))

        print("=== H) /me com Bearer ===")
        r = http.get(
            f"{BASE}/me", params={"fields": "id,name"}, headers={"Authorization": f"Bearer {su}"}
        )
        print("  ", resumo(r))

    return 0


if __name__ == "__main__":
    sys.exit(main())
