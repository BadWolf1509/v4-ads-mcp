"""Sonda o KeywordPlanIdeaService (Planejador de palavras-chave) contra a API real.

Read-only. Registra os fatos medidos em 29/10 que sustentam o desenho das tools do
planejador (spec `2026-10-29-planejador-de-palavras-design.md`, secao 1, fatos 2-6, 9 e 10).
Monta o cliente como `build_client_for_manager` (refresh token do gestor lido do banco em
transacao `readonly`, decifrado com `decrypt_refresh_token`; developer token, client id/secret
e login customer id vem dos mesmos secrets do servico).

Resultado de 29/10 (conta Conta Interna - 02, 6728568947):
  1. sementes ["aluguel de andaime", "locacao de equipamentos"]: 1.923 ideias no Brasil e em
     JP (1001622); o volume de "aluguel de andaime" muda (Brasil 8.100, JP 40).
  2. com url_seed https://www.mestredaobra.com.br: 40 ideias.
  3. "aluguel de andaime": JP 40 / Campina Grande (1001621) 20 / as duas numa chamada 50.
  4. generate_keyword_historical_metrics: o termo inexistente volta SEM `keyword_metrics`.
  5. suggest_geo_target_constants: `1001622` e City "Joao Pessoa,State of Paraiba,Brazil".
O volume pode variar mes a mes; a forma, nao.

Imprime so formas e numeros — nenhum segredo. Segredos via `gcloud` (nunca `2>/dev/null`:
com credencial vencida ele tenta reautenticar e pendura em silencio).

Uso, da raiz do repo:
    python -m scripts.probe_keyword_planner <customer_id> [manager_uuid]
O gestor vem do 2o argumento ou de MANAGER_ID (default: o do Wellington).
"""

import asyncio
import os
import subprocess
import sys
from typing import Any
from uuid import UUID

import asyncpg

from src.auth.tokens import decrypt_refresh_token, derive_master_key_from_settings
from src.google_ads.client import build_client

DEFAULT_MANAGER = "fc67c099-e229-4190-8175-d610fd933b15"
LANGUAGE_PT = "languageConstants/1014"
BRASIL = "geoTargetConstants/2076"
JOAO_PESSOA = "geoTargetConstants/1001622"
CAMPINA_GRANDE = "geoTargetConstants/1001621"
TERMO = "aluguel de andaime"
SEMENTES = [TERMO, "locação de equipamentos"]
URL = "https://www.mestredaobra.com.br"


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
        sys.exit(f"gcloud falhou ({nome}): {r.stderr.strip()[:200]}")
    return r.stdout.strip()


async def refresh_token_do_gestor(manager_id: str) -> str:
    conn = await asyncpg.connect(secret("database-url"))
    try:
        async with conn.transaction(readonly=True):
            blob = await conn.fetchval(
                "SELECT refresh_token_enc FROM google_oauth_connections "
                "WHERE manager_id = $1 AND revoked_at IS NULL "
                "ORDER BY connected_at DESC, id DESC LIMIT 1",
                UUID(manager_id),
            )
    finally:
        await conn.close()
    if blob is None:
        sys.exit("gestor sem conexao Google ativa")
    key = derive_master_key_from_settings(secret("aes-master-key"))
    return decrypt_refresh_token(blob, key)


def ideias(
    client: Any,
    customer_id: str,
    geos: list[str],
    *,
    sementes: list[str] | None = None,
    url: str | None = None,
) -> list[Any]:
    svc = client.get_service("KeywordPlanIdeaService")
    req = client.get_type("GenerateKeywordIdeasRequest")
    req.customer_id = customer_id
    req.language = LANGUAGE_PT
    req.geo_target_constants.extend(geos)
    req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    if sementes and url:
        req.keyword_and_url_seed.url = url
        req.keyword_and_url_seed.keywords.extend(sementes)
    elif url:
        req.url_seed.url = url
    else:
        req.keyword_seed.keywords.extend(sementes or [])
    return list(svc.generate_keyword_ideas(request=req))


def volume(resultados: list[Any], termo: str) -> int | None:
    for r in resultados:
        if r.text == termo:
            return int(r.keyword_idea_metrics.avg_monthly_searches)
    return None


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("uso: python -m scripts.probe_keyword_planner <customer_id> [manager_uuid]")
    customer_id = sys.argv[1]
    manager_id = (sys.argv[2] if len(sys.argv) > 2 else None) or os.environ.get(
        "MANAGER_ID", DEFAULT_MANAGER
    )
    client = build_client(
        refresh_token=asyncio.run(refresh_token_do_gestor(manager_id)),
        developer_token=secret("google-ads-developer-token"),
        client_id=secret("google-oauth-client-id"),
        client_secret=secret("google-oauth-client-secret"),
        login_customer_id=secret("google-ads-login-customer-id"),
    )

    print("== 1. sementes: Brasil vs Joao Pessoa")
    for rotulo, geo in (("BR", BRASIL), ("JP", JOAO_PESSOA)):
        r = ideias(client, customer_id, [geo], sementes=SEMENTES)
        print(f"  {rotulo}: ideias={len(r)} volume({TERMO!r})={volume(r, TERMO)}")

    print("== 2. sementes + url_seed")
    r = ideias(client, customer_id, [JOAO_PESSOA], sementes=SEMENTES, url=URL)
    print(f"  keyword_and_url_seed: ideias={len(r)}")

    print("== 3. varias cidades numa chamada")
    for rotulo, geos in (
        ("JP", [JOAO_PESSOA]),
        ("CG", [CAMPINA_GRANDE]),
        ("JP+CG", [JOAO_PESSOA, CAMPINA_GRANDE]),
    ):
        r = ideias(client, customer_id, geos, sementes=[TERMO])
        print(f"  {rotulo}: volume({TERMO!r})={volume(r, TERMO)}")

    print("== 4. historical metrics: presenca de keyword_metrics")
    svc = client.get_service("KeywordPlanIdeaService")
    req = client.get_type("GenerateKeywordHistoricalMetricsRequest")
    req.customer_id = customer_id
    req.keywords.extend([TERMO, "xyzzy termo inexistente"])
    req.language = LANGUAGE_PT
    req.geo_target_constants.append(JOAO_PESSOA)
    req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    for res in svc.generate_keyword_historical_metrics(request=req).results:
        print(f"  {res.text!r}: keyword_metrics presente={'keyword_metrics' in res}")

    print("== 5. suggest_geo_target_constants (repr de cada sugestao)")
    geo_svc = client.get_service("GeoTargetConstantService")
    for nome in ("João Pessoa", "Campina Grande"):
        req = client.get_type("SuggestGeoTargetConstantsRequest")
        req.locale = "pt"
        req.country_code = "BR"
        req.location_names.names.append(nome)
        print(f"  -- {nome}")
        for s in geo_svc.suggest_geo_target_constants(request=req).geo_target_constant_suggestions:
            g = s.geo_target_constant
            print(
                "  "
                + repr(
                    {
                        "resource_name": g.resource_name,
                        "name": g.name,
                        "target_type": g.target_type,
                        "canonical_name": g.canonical_name,
                    }
                )
            )


if __name__ == "__main__":
    main()
