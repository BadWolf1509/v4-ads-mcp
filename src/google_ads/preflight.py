"""Pre-flights async dos mutates Google (validate_*): leem o estado da conta via GAQL
antes do preview e recusam entrada que o Google engoliria em silencio.

Moveram de `queries/_common.py` (Task C3): eles chamam `run_report`, entao pertencem a
camada de execucao; `queries/` fica so com construcao de GAQL, datas, micros e filtros.
Patch de teste em `src.google_ads.preflight.run_report` (namespace de quem chama).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from src.google_ads.queries._common import nome_do_enum
from src.google_ads.queries._gaql import gaql_string_literal
from src.google_ads.queries.keyword_lookup import (
    _lookup_row_formatter,
    build_keyword_text_lookup_query,
)
from src.google_ads.queries.rsa_estado import pinos_do_rsa
from src.google_ads.reports import run_report
from src.google_ads.rsa_textos import (
    campos_de_texto,
    pinos_pedidos,
    posicoes_dos_campos,
    posicoes_perdidas,
    restringir,
)


async def validate_manual_cpc_strategy(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    ad_group_ids: list[str],
) -> str | None:
    """Returns PT-BR error string if any ad_group is in non-MANUAL_CPC/ENHANCED_CPC
    campaign; else None.

    Performs 1 GAQL batch lookup. Whitelist {MANUAL_CPC, ENHANCED_CPC} matches
    strategies que honram cpc_bid_micros field (Google Ads API v23 docs:
    https://developers.google.com/google-ads/api/docs/campaigns/bidding/override-strategies).

    Sprint 3b.8 (P3 dogfood F12 finding — silent-acceptance bug family 6th variant).
    """
    if not ad_group_ids:
        return None

    ids_clause = ", ".join(str(int(x)) for x in ad_group_ids)
    query = (
        f"SELECT ad_group.id, campaign.id, campaign.name, "
        f"campaign.bidding_strategy_type "
        f"FROM ad_group WHERE ad_group.id IN ({ids_clause})"
    )

    def _format(row: Any) -> dict[str, str]:
        return {
            "ad_group_id": str(row.ad_group.id),
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "strategy": row.campaign.bidding_strategy_type.name,
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_manual_cpc_strategy",
    )

    whitelist = {"MANUAL_CPC", "ENHANCED_CPC"}
    for r in rows:
        if r["strategy"] not in whitelist:
            return (
                f"Campaign '{r['campaign_name']}' (id {r['campaign_id']}) usa "
                f"bidding_strategy_type '{r['strategy']}'. Manual CPC bids sao "
                f"ignorados nesta estrategia (Google API silent-failure). Mude "
                f"para MANUAL_CPC via update_campaign_bidding, ou ajuste budget/"
                f"targeting via outras tools."
            )
    return None


async def validate_parent_campaigns_for_ad_group_create(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    ad_groups: list[dict[str, Any]],
) -> str | None:
    """Returns PT-BR error string if any parent campaign fails validation; else None.

    Validates per ad_group spec:
    1. Parent campaign exists
    2. campaign.status != REMOVED
    3. ad_group.type matches campaign.advertising_channel_type
       (SEARCH_STANDARD → SEARCH; SHOPPING_PRODUCT_ADS → SHOPPING)
    4. If cpc_bid_micros provided, campaign.bidding_strategy_type IN
       {MANUAL_CPC, ENHANCED_CPC} (F12 lesson — Sprint 3b.8)

    Performs 1 GAQL batch lookup for all unique campaign_ids.
    Returns first-found offender error message (matches Sprint 3b.5 A3 pattern).
    """
    campaign_ids = list({ag["campaign_id"] for ag in ad_groups})
    if not campaign_ids:
        return None

    ids_clause = ", ".join(str(int(x)) for x in campaign_ids)
    query = (
        f"SELECT campaign.id, campaign.name, campaign.status, "
        f"campaign.advertising_channel_type, campaign.bidding_strategy_type "
        f"FROM campaign WHERE campaign.id IN ({ids_clause})"
    )

    def _format(row: Any) -> dict[str, str]:
        return {
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "status": row.campaign.status.name,
            "channel_type": row.campaign.advertising_channel_type.name,
            "strategy": row.campaign.bidding_strategy_type.name,
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_parent_campaigns_for_ad_group_create",
    )

    by_id = {r["campaign_id"]: r for r in rows}

    type_to_channel = {
        "SEARCH_STANDARD": "SEARCH",
        "SHOPPING_PRODUCT_ADS": "SHOPPING",
    }
    manual_strategies = {"MANUAL_CPC", "ENHANCED_CPC"}

    for ag in ad_groups:
        cid = ag["campaign_id"]
        camp = by_id.get(cid)

        if camp is None:
            return f"Campaign {cid} nao encontrada na conta. Verifique o campaign_id."

        if camp["status"] == "REMOVED":
            return (
                f"Campaign '{camp['campaign_name']}' (id {cid}) esta REMOVED. "
                f"Nao e possivel criar ad_group em campaign removida."
            )

        ag_type = ag.get("type", "SEARCH_STANDARD")
        expected_channel = type_to_channel.get(ag_type)
        if expected_channel and camp["channel_type"] != expected_channel:
            return (
                f"Ad_group type '{ag_type}' incompativel com campaign "
                f"'{camp['campaign_name']}' (id {cid}) — advertising_channel_type "
                f"= '{camp['channel_type']}'. Use type matching o canal."
            )

        if "cpc_bid_micros" in ag and camp["strategy"] not in manual_strategies:
            return (
                f"Campaign '{camp['campaign_name']}' (id {cid}) usa "
                f"bidding_strategy_type '{camp['strategy']}'. cpc_bid_micros "
                f"sera ignorado silenciosamente pela Google nesta estrategia "
                f"(Sprint 3b.8 F12 lesson). Remova cpc_bid_micros do payload "
                f"ou mude campaign para MANUAL_CPC."
            )

    return None


async def validate_parent_ad_groups_for_rsa_create(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    rsas: list[dict[str, Any]],
) -> str | None:
    """Returns PT-BR error string if any parent ad_group fails validation; else None.

    Validates per RSA spec:
    1. Parent ad_group exists
    2. ad_group.status != REMOVED
    3. ad_group's parent campaign.advertising_channel_type IN {SEARCH, SEARCH_PARTNERS}

    Performs 1 GAQL batch lookup for unique ad_group_ids.
    Returns first-found offender error message (matches Sprint 3b.5 A3 pattern).
    """
    ad_group_ids = list({rsa["ad_group_id"] for rsa in rsas})
    if not ad_group_ids:
        return None

    ids_clause = ", ".join(str(int(x)) for x in ad_group_ids)
    query = (
        f"SELECT ad_group.id, ad_group.name, ad_group.status, "
        f"campaign.id, campaign.name, campaign.advertising_channel_type "
        f"FROM ad_group WHERE ad_group.id IN ({ids_clause})"
    )

    def _format(row: Any) -> dict[str, str]:
        return {
            "ad_group_id": str(row.ad_group.id),
            "ad_group_name": row.ad_group.name,
            "ad_group_status": row.ad_group.status.name,
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "channel_type": row.campaign.advertising_channel_type.name,
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_parent_ad_groups_for_rsa_create",
    )

    by_id = {r["ad_group_id"]: r for r in rows}
    valid_channels = {"SEARCH", "SEARCH_PARTNERS"}

    for rsa in rsas:
        agid = rsa["ad_group_id"]
        ag = by_id.get(agid)

        if ag is None:
            return f"Ad_group {agid} nao encontrado na conta. Verifique o ad_group_id."

        if ag["ad_group_status"] == "REMOVED":
            return (
                f"Ad_group '{ag['ad_group_name']}' (id {agid}) esta REMOVED. "
                f"Nao e possivel criar RSA em ad_group removido."
            )

        if ag["channel_type"] not in valid_channels:
            return (
                f"Ad_group '{ag['ad_group_name']}' (id {agid}) pertence a campaign "
                f"'{ag['campaign_name']}' com advertising_channel_type "
                f"'{ag['channel_type']}'. RSAs (Responsive Search Ads) so funcionam "
                f"em campaigns SEARCH ou SEARCH_PARTNERS."
            )

    return None


def _format_rsa_preflight_row(row: Any) -> dict[str, Any]:
    """Uma linha de `ad_group_ad` -> dict do pre-flight de RSA.

    Nivel de modulo (nao aninhada) pra ser testavel com row proto-like: o
    caminho `.system_managed_resource_source.name` e o que separa variacao de
    anuncio comum, e caminho de proto so se confere olhando.
    """
    return {
        "ad_id": str(row.ad_group_ad.ad.id),
        "ad_type": row.ad_group_ad.ad.type.name,
        # F181: em proto-plus este atributo EXISTE SEMPRE — o que varia e o valor
        # (UNSPECIFIED no anuncio comum, AD_VARIATIONS na variacao). Por isso a
        # comparacao no laco de validacao e por valor, nunca por presenca (F145).
        "system_managed_source": row.ad_group_ad.ad.system_managed_resource_source.name,
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": row.ad_group.name,
        "ad_group_status": row.ad_group.status.name,
        "campaign_id": str(row.campaign.id),
        "campaign_name": row.campaign.name,
        "channel_type": row.campaign.advertising_channel_type.name,
        # G2: pinos atuais por posicao; `None` = assets nao lidos (nao e "sem pino").
        "pinos": pinos_do_rsa(row.ad_group_ad.ad.responsive_search_ad),
    }


async def _buscar_ad_base_do_grupo(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    ad_group_id: str,
) -> str | None:
    """`ad_id` do unico RSA nao-variacao do grupo, ou None se ambiguo.

    So roda no caminho de falha do pre-flight (anuncio system-managed detectado),
    entao o custo nao entra no caminho feliz. Devolve None — em vez de chutar o
    primeiro — quando ha zero ou mais de um candidato: nomear o anuncio errado e
    pior que nao nomear nenhum.
    """
    query = (
        f"SELECT ad_group_ad.ad.id, "
        f"ad_group_ad.ad.system_managed_resource_source "
        f"FROM ad_group_ad "
        f"WHERE ad_group.id = {int(ad_group_id)} "
        f"AND ad_group_ad.status != 'REMOVED'"
    )

    def _format(row: Any) -> dict[str, str]:
        return {
            "ad_id": str(row.ad_group_ad.ad.id),
            "system_managed_source": row.ad_group_ad.ad.system_managed_resource_source.name,
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="buscar_ad_base_do_grupo",
    )
    candidatos = [r["ad_id"] for r in rows if r["system_managed_source"] != "AD_VARIATIONS"]
    return candidatos[0] if len(candidatos) == 1 else None


async def validate_existing_rsas_for_update(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    updates: list[dict[str, Any]],
    pinos_atuais: dict[str, dict[str, list[str]] | None] | None = None,
) -> str | None:
    """Returns PT-BR error string if any ad fails validation; else None.

    Validates per update spec:
    1. Ad exists
    2. ad.type == RESPONSIVE_SEARCH_AD (cannot update other types via this tool)
    3. Parent ad_group.status != REMOVED
    4. Parent campaign.advertising_channel_type IN {SEARCH, SEARCH_PARTNERS}
    5. Ad nao e system-managed (variacao de Ad Variation nao aceita mutate — F181)
    6. G2: update que traz headlines/descriptions nao tira o pino de uma POSICAO que
       hoje tem pino, salvo `remover_pinos: true` naquele update. Checa so as posicoes
       dos campos que o update traz (update so de descriptions nao perde pino de headline).

    Performs 1 GAQL batch lookup for unique ad_ids (os pinos vem nela: zero round-trip).
    Returns first-found offender error message for 1-5; para 6, lista TODOS os ads que
    perdem pino, depois que 1-5 passaram para o lote inteiro.

    `pinos_atuais`, se passado, recebe `{ad_id: pinos}` lidos (None = nao lidos) para o
    preview mostrar antes->depois sem reler.
    """
    ad_ids = list({u["ad_id"] for u in updates})
    if not ad_ids:
        return None

    ids_clause = ", ".join(str(int(x)) for x in ad_ids)
    query = (
        f"SELECT ad_group_ad.ad.id, ad_group_ad.ad.type, "
        # F181: custo zero — o campo entra na query que o pre-flight ja rodava.
        f"ad_group_ad.ad.system_managed_resource_source, "
        # G2: custo zero — os pinos atuais vem na mesma query (posicao por asset).
        f"ad_group_ad.ad.responsive_search_ad.headlines, "
        f"ad_group_ad.ad.responsive_search_ad.descriptions, "
        f"ad_group.id, ad_group.name, ad_group.status, "
        f"campaign.id, campaign.name, campaign.advertising_channel_type "
        f"FROM ad_group_ad WHERE ad_group_ad.ad.id IN ({ids_clause})"
    )

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format_rsa_preflight_row,
        operation_name="validate_existing_rsas_for_update",
    )

    by_id = {r["ad_id"]: r for r in rows}
    if pinos_atuais is not None:
        pinos_atuais.update({aid: r["pinos"] for aid, r in by_id.items()})
    valid_channels = {"SEARCH", "SEARCH_PARTNERS"}

    for u in updates:
        aid = u["ad_id"]
        ad = by_id.get(aid)

        if ad is None:
            return f"Ad {aid} nao encontrado na conta. Verifique o ad_id."

        # F181: variacao de Ad Variation E um RESPONSIVE_SEARCH_AD, fica em ad_group
        # ENABLED e em campanha SEARCH — atravessa os tres filtros abaixo. So este
        # campo a separa do anuncio base. Comparacao por VALOR: em proto-plus o
        # atributo existe sempre (F145). Acesso por chave, nao `.get()`: fixture ou
        # formatter que deixe de trazer a chave tem que falhar alto, nao pular a
        # checagem em silencio.
        if ad["system_managed_source"] == "AD_VARIATIONS":
            base_id = await _buscar_ad_base_do_grupo(
                manager_id=manager_id,
                session_id=session_id,
                customer_id=customer_id,
                ad_group_id=ad["ad_group_id"],
            )
            alvo = (
                f"o anuncio BASE {base_id}"
                if base_id is not None
                else (
                    f"o anuncio BASE do ad_group '{ad['ad_group_name']}' "
                    f"(id {ad['ad_group_id']}) — o RSA que nao e variacao"
                )
            )
            return (
                f"Ad {aid} e uma variacao de Ad Variation (gerenciada pelo Google) "
                f"e nao aceita mutate. Edite {alvo}: a variacao herda a mudanca em "
                f"minutos. Atencao: reler a variacao logo apos editar o base "
                f"devolve o estado ANTIGO sem erro nenhum."
            )

        if ad["ad_type"] != "RESPONSIVE_SEARCH_AD":
            return (
                f"Ad {aid} tem type '{ad['ad_type']}', nao RESPONSIVE_SEARCH_AD. "
                f"update_rsa so suporta RSAs — outros types (ETA legacy, Display, "
                f"Video) precisam de tools dedicados."
            )

        if ad["ad_group_status"] == "REMOVED":
            return (
                f"Ad_group '{ad['ad_group_name']}' (id {ad['ad_group_id']}) parent "
                f"do Ad {aid} esta REMOVED. Nao e possivel atualizar RSA em "
                f"ad_group removido."
            )

        if ad["channel_type"] not in valid_channels:
            return (
                f"Campaign '{ad['campaign_name']}' (id {ad['campaign_id']}) parent "
                f"do Ad {aid} tem channel_type '{ad['channel_type']}'. RSAs so "
                f"funcionam em campaigns SEARCH ou SEARCH_PARTNERS."
            )

    perdas = [m for u in updates if (m := _perda_de_pino(u, by_id[u["ad_id"]])) is not None]
    if perdas:
        return (
            "Update que tira pino de posicao recusado (os textos substituem a lista "
            "inteira): "
            + "; ".join(perdas)
            + ". Para manter, repita o pino na lista nova ({text, pinned_field}); para "
            "tirar de proposito, passe remover_pinos: true naquele update."
        )
    return None


def _perda_de_pino(u: dict[str, Any], ad: dict[str, Any]) -> str | None:
    """Mensagem do ad que perde pino, ou None. So posicao, nunca texto (vai ao audit)."""
    campos = campos_de_texto(u)
    if not campos or u.get("remover_pinos", False):
        return None
    # Acesso por chave (como o F181): formatter que deixe de trazer `pinos` falha alto.
    atuais = ad["pinos"]
    if atuais is None:
        return (
            f"Ad {u['ad_id']}: os pinos atuais nao foram lidos, entao nao da para "
            f"garantir que a lista nova nao tira nenhum"
        )
    posicoes = posicoes_dos_campos(campos)
    perdidas = posicoes_perdidas(restringir(atuais, posicoes), pinos_pedidos(u))
    if not perdidas:
        return None
    return f"Ad {u['ad_id']} perde o pino de {', '.join(perdidas)}"


async def validate_conversion_action_create(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    actions: list[dict[str, Any]],
) -> str | None:
    """Returns PT-BR error string if any ConversionAction name already exists; else None.

    Validates name uniqueness per Google API constraint:
    - ConversionAction.name is unique per customer (server-side enforced)

    Performs 1 GAQL batch lookup over input names. Returns first-found
    offender error message in INPUT order (deterministic UX).

    Mirrors Sprint 3b.16 validate_parent_ad_groups_for_rsa_create pattern.
    """
    if not actions:
        return None

    names = [a["name"] for a in actions]
    # F87: nome de ConversionAction é texto livre (≤100 chars) e GAQL escapa com
    # BARRA INVERTIDA, não com doubling de SQL — `Lead - D'Or` virava duas strings
    # coladas e o pré-flight falhava com erro opaco do Google num nome válido.
    quoted = ", ".join(gaql_string_literal(n) for n in names)
    query = (
        f"SELECT conversion_action.name FROM conversion_action "
        f"WHERE conversion_action.name IN ({quoted})"
    )

    def _format(row: Any) -> dict[str, str]:
        return {"conversion_action_name": row.conversion_action.name}

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_conversion_action_create",
    )

    existing = {r["conversion_action_name"] for r in rows}

    for a in actions:
        if a["name"] in existing:
            return (
                f"ConversionAction '{a['name']}' ja existe na conta. "
                "Use outro nome (nomes sao unicos por customer)."
            )

    return None


async def validate_campaign_for_value_rule_set(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    campaign_id: str,
) -> str | None:
    """Returns PT-BR error string if campaign invalid for value rule set attachment; else None.

    Validates:
    1. Campaign exists
    2. campaign.status != REMOVED

    Sprint 3b.19B — pre-flight for create_conversion_value_rule_set when
    attachment_type=CAMPAIGN.
    """
    # int() cast: fail-fast on non-numeric input + defense against future callers
    # bypassing schema validation. campaign.id is numeric so bare interpolation
    # is safe (no quotes needed).
    query = (
        f"SELECT campaign.id, campaign.name, campaign.status "
        f"FROM campaign WHERE campaign.id = {int(campaign_id)}"
    )

    def _format(row: Any) -> dict[str, str]:
        return {
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "campaign_status": row.campaign.status.name,
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_campaign_for_value_rule_set",
    )

    if not rows:
        return f"Campaign {campaign_id} nao encontrada na conta. Verifique o campaign_id."

    camp = rows[0]
    if camp["campaign_status"] == "REMOVED":
        return (
            f"Campaign '{camp['campaign_name']}' (id {camp['campaign_id']}) "
            f"esta REMOVED. Nao e possivel anexar RuleSet a campaign removida."
        )

    return None


async def validate_geo_target_constants_br_only(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    geo_paths: list[str],
) -> str | None:
    """Returns PT-BR error string if any geo target is non-BR; else None.

    Validates each geo_target_constant resource_name:
    1. Exists in Google Ads (queryable via GAQL)
    2. country_code == "BR" (V4 invariant — all V4 accounts in Brazil)

    Performs 1 GAQL batch lookup. Returns first-offender error in INPUT order.

    Sprint 3b.19B (initial) + 3b.24 (renamed generic) — pre-flight for any
    create_* tool that accepts BR-only geo_target_constant paths.
    """
    if not geo_paths:
        return None

    # F87: os schemas que alimentam isto validam `^geoTargetConstants/[0-9]+$`,
    # então na prática nunca chega caractere especial — mas o escape aqui estava
    # errado do mesmo jeito, e um schema novo mais frouxo herdaria a falha.
    quoted = ", ".join(gaql_string_literal(p) for p in geo_paths)
    query = (
        f"SELECT geo_target_constant.resource_name, "
        f"geo_target_constant.country_code, geo_target_constant.name "
        f"FROM geo_target_constant "
        f"WHERE geo_target_constant.resource_name IN ({quoted})"
    )

    def _format(row: Any) -> dict[str, str]:
        return {
            "resource_name": row.geo_target_constant.resource_name,
            "country_code": row.geo_target_constant.country_code,
            "name": row.geo_target_constant.name,
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_geo_target_constants_br_only",
    )

    by_path = {r["resource_name"]: r for r in rows}

    for path in geo_paths:
        row = by_path.get(path)
        if row is None:
            return f"Geo target '{path}' nao encontrado. Verifique o resource path."
        if row["country_code"] != "BR":
            return (
                f"Geo target '{row['name']}' ({path}) tem country_code "
                f"'{row['country_code']}', esperado 'BR' (V4 invariant: todas "
                "contas V4 sao do Brasil)."
            )

    return None


async def validate_conversion_action_for_upload(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    conversion_action_id: str,
) -> str | None:
    """GAQL pre-flight: conversion_action exists + type=UPLOAD_CLICKS + status != REMOVED.

    Sprint 3b.26 — pre-flight for import_offline_conversions tool.
    Returns PT-BR error message OR None if valid.
    """
    query = (
        "SELECT conversion_action.id, conversion_action.type, conversion_action.status "
        "FROM conversion_action "
        # int() guard: fail-fast on non-numeric + injection defense (mirrors
        # validate_campaign_for_value_rule_set pattern)
        f"WHERE conversion_action.id = {int(conversion_action_id)}"
    )

    def _format(row: Any) -> dict[str, Any]:
        return {
            "conversion_action": {
                "id": str(row.conversion_action.id),
                "type": nome_do_enum(row.conversion_action.type),
                "status": nome_do_enum(row.conversion_action.status),
            }
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_conversion_action_for_upload",
    )

    if not rows:
        return (
            f"conversion_action_id={conversion_action_id} não existe em customer_id={customer_id}"
        )

    row = rows[0]["conversion_action"]
    if row["type"] != "UPLOAD_CLICKS":
        return (
            f"conversion_action_id={conversion_action_id} tem type={row['type']}; "
            f"UploadClickConversions requer type=UPLOAD_CLICKS. Crie ConversionAction "
            f"nova via create_conversion_action com type=UPLOAD_CLICKS."
        )

    if row["status"] == "REMOVED":
        return f"conversion_action_id={conversion_action_id} está REMOVED; não aceita uploads."

    return None


async def validate_conversion_actions_exist(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    conversion_action_ids: list[str],
) -> dict[str, Any] | None:
    """GAQL pre-flight: each ID exists + status != REMOVED.

    Returns:
        None if all valid
        dict with {error, missing_ids} OR {error, removed_ids} if issues.

    Missing IDs short-circuit before REMOVED check (cleaner error UX).

    Sprint 3b.27 — pre-flight for update_conversion_action tool.
    """
    ids_clause = ", ".join(str(int(cid)) for cid in conversion_action_ids)
    query = (
        "SELECT conversion_action.id, conversion_action.status "
        "FROM conversion_action "
        f"WHERE conversion_action.id IN ({ids_clause})"
    )

    def _format(row: Any) -> dict[str, Any]:
        return {
            "conversion_action": {
                "id": str(row.conversion_action.id),
                "status": nome_do_enum(row.conversion_action.status),
            }
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_conversion_actions_exist",
    )

    found_ids = {r["conversion_action"]["id"] for r in rows}
    missing = [cid for cid in conversion_action_ids if cid not in found_ids]
    if missing:
        return {
            "error": (
                f"conversion_action_ids não existem em customer_id={customer_id}: "
                f"{missing}. Verifique IDs via get_conversion_actions(customer_id='{customer_id}')."
            ),
            "missing_ids": missing,
        }

    removed = [
        r["conversion_action"]["id"] for r in rows if r["conversion_action"]["status"] == "REMOVED"
    ]
    if removed:
        return {
            "error": (
                f"conversion_action_ids com status=REMOVED não aceitam updates: {removed}. "
                f"Para reativar, use Google Ads UI (sem tool MCP dedicada hoje)."
            ),
            "removed_ids": removed,
        }

    return None


async def validate_keyword_criterion_types(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    keyword_pairs: list[tuple[str, str]],
) -> dict[str, Any] | None:
    """GAQL pre-flight: each (ad_group_id, criterion_id) exists + is positive.

    Returns:
        None if all positive valid
        dict with {error, negative_ids_blocked, positive_ids_safe, to_retry_with}
            for negative mixture
        dict with {error, missing_ids} for IDs not found (short-circuit)

    Sprint 3b.27 fix B1/F43 (Silent-acceptance design gap family — F43).

    Discovered via dogfood 2026-05-19 MO-JP cleanup massivo: update_keyword_status
    accepts batches silently when including criterion with negative=true; only
    apply_change fails with Google generic error "Negative ad group criteria are
    not updateable" which doesn't identify problematic IDs.
    """
    if not keyword_pairs:
        return None

    crit_ids = sorted({c for _, c in keyword_pairs})
    ids_clause = ", ".join(str(int(c)) for c in crit_ids)
    query = (
        "SELECT ad_group.id, ad_group_criterion.criterion_id, "
        "ad_group_criterion.negative, ad_group_criterion.type "
        "FROM ad_group_criterion "
        f"WHERE ad_group_criterion.criterion_id IN ({ids_clause})"
    )

    def _format(row: Any) -> dict[str, Any]:
        return {
            "ad_group_id": str(row.ad_group.id),
            "criterion_id": str(row.ad_group_criterion.criterion_id),
            "negative": bool(row.ad_group_criterion.negative),
            "type": nome_do_enum(row.ad_group_criterion.type),
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_keyword_criterion_types",
    )

    # Key found rows by (ad_group_id, criterion_id) for O(1) lookup
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        key = (r["ad_group_id"], r["criterion_id"])
        found[key] = r

    missing: list[dict[str, str]] = []
    negative_blocked: list[dict[str, str]] = []
    positive_safe: list[dict[str, str]] = []

    for ad_group_id, criterion_id in keyword_pairs:
        key = (ad_group_id, criterion_id)
        if key not in found:
            missing.append({"ad_group_id": ad_group_id, "criterion_id": criterion_id})
            continue
        if found[key]["negative"]:
            negative_blocked.append({"ad_group_id": ad_group_id, "criterion_id": criterion_id})
        else:
            positive_safe.append({"ad_group_id": ad_group_id, "criterion_id": criterion_id})

    # Short-circuit: missing IDs antes do negative check
    if missing:
        return {
            "error": (
                f"criterion_ids não encontrados em customer_id={customer_id}: "
                f"{[m['criterion_id'] for m in missing]}. Verifique se IDs estão "
                f"corretos (ad_group_id + criterion_id) e se o gestor ainda tem "
                f"acesso à conta."
            ),
            "missing_ids": missing,
        }

    if negative_blocked:
        return {
            "error": (
                f"{len(negative_blocked)}/{len(keyword_pairs)} criterion_ids são "
                f"ad_group_criterion com negative=true. Google API rejeita updates "
                f"em negative criteria (state machine separada). Re-chame "
                f"update_keyword_status apenas com os criterion_ids POSITIVE "
                f"listados em positive_ids_safe. Pra desnegativar uma keyword, "
                f"use Google Ads UI (sem tool MCP dedicada hoje)."
            ),
            "negative_ids_blocked": negative_blocked,
            "positive_ids_safe": positive_safe,
            "to_retry_with": (
                f"update_keyword_status(customer_id='{customer_id}', "
                f"keywords=positive_ids_safe, new_status=<your_status>)"
            ),
        }

    return None


async def validate_user_list_for_upload(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    user_list_id: str,
) -> dict[str, Any] | None:
    """GAQL pre-flight: user_list existe + type=CRM_BASED_USER_LIST + writable.

    Checks (em ordem, curto-circuita no primeiro fail):
    1. Lista existe (else: missing_id)
    2. type == CRM_BASED_USER_LIST (else: wrong_type)
    3. read_only == False (else: customer_match_policy_not_accepted likely)
    4. membership_status == OPEN (else: closed)

    Returns None if valid, dict com {error, ...} se issue.

    Sprint 3b.28 — pre-flight pra upload_customer_match_list tool.
    """
    query = (
        "SELECT user_list.id, user_list.name, user_list.type, "
        "user_list.read_only, user_list.membership_status "
        "FROM user_list "
        f"WHERE user_list.id = {int(user_list_id)}"
    )

    def _format(row: Any) -> dict[str, Any]:
        return {
            "user_list": {
                "id": str(row.user_list.id),
                "name": row.user_list.name,
                "type": nome_do_enum(row.user_list.type),
                "read_only": bool(row.user_list.read_only),
                "membership_status": nome_do_enum(row.user_list.membership_status),
            }
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_user_list_for_upload",
    )

    if not rows:
        return {
            "error": (
                f"user_list_id={user_list_id} não existe em customer_id={customer_id}. "
                f"Verifique IDs via run_gaql ou Google Ads UI > Audience Manager."
            ),
            "missing_id": user_list_id,
        }

    ul = rows[0]["user_list"]

    if ul["type"] != "CRM_BASED_USER_LIST":
        return {
            "error": (
                f"user_list_id={user_list_id} type={ul['type']}; upload requer "
                f"CRM_BASED_USER_LIST. Crie nova lista via Google Ads UI > "
                f"Audience Manager > Customer Match."
            ),
        }

    if ul["read_only"]:
        return {
            "error": (
                f"user_list_id={user_list_id} está read_only. Provável causa: "
                f"Customer Match policy não aceita pra conta. Aceite em Google Ads "
                f"UI > Tools > Audience Manager > Customer lists > Accept terms."
            ),
        }

    if ul["membership_status"] != "OPEN":
        return {
            "error": (
                f"user_list_id={user_list_id} membership_status={ul['membership_status']}; "
                f"não aceita uploads agora. Status esperado: OPEN."
            ),
        }

    return None


async def fetch_keyword_texts(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    keyword_pairs: list[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, str]]:
    """Resolve (ad_group_id, criterion_id) → {keyword_text, match_type}.

    Used by update_keyword_status DRY_RUN path pra preview sample.
    Graceful: returns partial dict if some pairs not found (no exception).

    Returns:
        dict keyed by (ad_group_id, criterion_id) tuple. Missing pairs
        simply absent from dict — caller iterates pairs e checks presence
        via `.get()`.
    """
    if not keyword_pairs:
        return {}
    query = build_keyword_text_lookup_query(keyword_pairs)
    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_lookup_row_formatter,
        operation_name="keyword_text_lookup",
    )
    return {
        (r["ad_group_id"], r["criterion_id"]): {
            "keyword_text": r["keyword_text"],
            "match_type": r["match_type"],
        }
        for r in rows
    }


def _linha_de_lance_de_grupo(row: Any) -> dict[str, Any]:
    return {
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": row.ad_group.name,
        "current_cpc_bid_micros": int(row.ad_group.cpc_bid_micros),
    }


async def buscar_lances_de_grupo(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    ad_group_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Lance atual (CPC) de cada grupo, indexado por `ad_group_id`.

    1 lookup GAQL. Id ausente na conta simplesmente nao aparece no dict: quem chama
    decide o que fazer. `int(x)` recusa id nao numerico antes de a query sair.
    """
    ids_clause = ", ".join(str(int(x)) for x in ad_group_ids)
    query = f"""
        SELECT ad_group.id, ad_group.name, ad_group.cpc_bid_micros
        FROM ad_group
        WHERE ad_group.id IN ({ids_clause})
    """.strip()

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_linha_de_lance_de_grupo,
        operation_name="update_ad_group_bid_lookup",
    )
    return {r["ad_group_id"]: r for r in rows}


def _linha_de_lance_de_keyword(row: Any) -> dict[str, Any]:
    return {
        "ad_group_id": str(row.ad_group.id),
        "criterion_id": str(row.ad_group_criterion.criterion_id),
        "keyword_text": row.ad_group_criterion.keyword.text,
        "current_cpc_bid_micros": int(row.ad_group_criterion.cpc_bid_micros),
    }


async def buscar_lances_de_keyword(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    pares: list[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Lance atual de cada keyword, indexado por `(ad_group_id, criterion_id)`.

    `pares` e `(ad_group_id, criterion_id)`; a query filtra so por `criterion_id`
    (como sempre), entao o par que nao volta e o que a conta nao tem naquele grupo.
    `int(x)` recusa id nao numerico antes de a query sair.
    """
    crit_ids = [crit for _grupo, crit in pares]
    ids_clause = ", ".join(str(int(x)) for x in crit_ids)
    query = f"""
        SELECT
          ad_group.id,
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.cpc_bid_micros
        FROM keyword_view
        WHERE ad_group_criterion.criterion_id IN ({ids_clause})
    """.strip()

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_linha_de_lance_de_keyword,
        operation_name="update_keyword_bid_lookup",
    )
    return {(r["ad_group_id"], r["criterion_id"]): r for r in rows}


def _linha_de_orcamento_da_campanha(row: Any) -> dict[str, Any]:
    return {
        "campaign_budget_resource_name": row.campaign_budget.resource_name,
        "current_amount_micros": int(row.campaign_budget.amount_micros),
        "campaign_name": row.campaign.name,
        "budget_id": str(row.campaign_budget.id),
        # C1: sem este campo a tool escreve no recurso ORCAMENTO nomeando uma campanha
        # so. Proto-plus devolve o zero-value do campo nao selecionado (F145), entao
        # tirar `explicitly_shared` da GAQL apagaria o aviso em silencio.
        "explicitly_shared": bool(row.campaign_budget.explicitly_shared),
    }


async def buscar_orcamento_da_campanha(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    campaign_id: str,
) -> dict[str, Any] | None:
    """Orcamento atual da campanha (resource name, valor, compartilhamento), ou `None`
    quando a campanha nao existe na conta.

    `campaign_budget.id` e `.explicitly_shared` sao superficie ja probada por
    `validate_gaql` em 02/09 (ver docstring de src/google_ads/queries/ad_schedule.py).
    """
    query = f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign_budget.id,
          campaign_budget.resource_name,
          campaign_budget.explicitly_shared,
          campaign_budget.amount_micros
        FROM campaign
        WHERE campaign.id = {int(campaign_id)}
        LIMIT 1
    """.strip()

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_linha_de_orcamento_da_campanha,
        operation_name="update_campaign_budget_lookup",
    )
    return rows[0] if rows else None


def _linha_de_interesse(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.user_interest.user_interest_id),
        "taxonomy_type": row.user_interest.taxonomy_type.name,
    }


async def buscar_interesses(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    ids: list[str],
) -> list[dict[str, Any]]:
    """`{id, taxonomy_type}` de cada `user_interest` pedido (1 lookup GAQL em lote).

    Leitura interna de validacao: nao entra no audit do gestor (`audit_this_call=False`).
    `ids` vem de `audience_resource_name.rsplit("/")` — texto do gestor —, entao `int(x)`
    recusa id nao numerico antes de a query sair.
    """
    ids_clause = ", ".join(str(int(x)) for x in ids)
    query = (
        f"SELECT user_interest.user_interest_id, user_interest.taxonomy_type "
        f"FROM user_interest "
        f"WHERE user_interest.user_interest_id IN ({ids_clause})"
    )
    return await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_linha_de_interesse,
        operation_name="apply_audience_preflight_taxonomy_lookup",
        audit_this_call=False,  # internal read for validation, not user-facing audit
    )
