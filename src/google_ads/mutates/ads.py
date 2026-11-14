"""Mutate builders for ad_group_ad (individual ad) operations."""

from typing import Any

from google.protobuf.field_mask_pb2 import FieldMask

from src.google_ads.mutates._common import register_builder
from src.google_ads.mutates._status import (
    ALVOS_DE_STATUS,
    operacao_de_status,
)
from src.google_ads.rsa_textos import POSICOES_POR_CAMPO, normalizar_textos


def _anexar_textos(client: Any, rsa: Any, campo: str, itens: list[Any]) -> None:
    """Anexa `AdTextAsset`s; item string ou `{text, pinned_field?}` (G2).

    Sem pino o campo `pinned_field` NAO e tocado: fica no default UNSPECIFIED e o proto
    sai byte a byte igual ao de antes do G2 (guard `test_item_string_payload_identico`).
    O schema ja restringe a posicao ao campo; o builder e publico, entao confere de novo
    (F87) — levanta ANTES de qualquer escrita, porque o build roda antes da chamada.
    """
    permitidas = POSICOES_POR_CAMPO[campo]
    for item in normalizar_textos(itens):
        a = client.get_type("AdTextAsset")
        a.text = item["text"]
        pino = item["pinned_field"]
        if pino is not None:
            if pino not in permitidas:
                raise ValueError(f"pinned_field {pino!r} nao vale para {campo}: use {permitidas}")
            a.pinned_field = client.enums.ServedAssetFieldTypeEnum[pino]
        # `getattr` a cada append, como os lacos de antes: o repeated e relido do pai.
        getattr(rsa, campo).append(a)


@register_builder("update_ad_status")
def build_update_ad_status(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {ads: [{ad_group_id: str, ad_id: str}], new_status: 'ENABLED'|'PAUSED'|'REMOVED'}"""
    new_status = payload["new_status"].upper()
    alvo = ALVOS_DE_STATUS["ad"]
    caminho = getattr(client.get_service(alvo.servico), alvo.caminho)
    status_enum = getattr(client.enums, alvo.enum)
    mascara = FieldMask(paths=["status"])
    return [
        operacao_de_status(
            client,
            alvo,
            caminho(customer_id, ad["ad_group_id"], ad["ad_id"]),
            status_enum[new_status],
            mascara,
        )
        for ad in payload["ads"]
    ]


@register_builder("create_rsa")
def build_create_rsa(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {rsas: [{ad_group_id, headlines[], descriptions[], final_urls[],
                        path1?, path2?, status?}]}

    headlines/descriptions: item string ou `{text, pinned_field?}` (G2).

    Defaults: status=PAUSED. Headlines/descriptions/final_urls counts validated
    by JSONSchema layer (3-15/2-4/1+). path1/path2 only set if provided.
    """
    operations: list[Any] = []
    ag_service = client.get_service("AdGroupService")
    status_enum = client.enums.AdGroupAdStatusEnum
    for rsa_spec in payload["rsas"]:
        op = client.get_type("MutateOperation")
        ad_op = op.ad_group_ad_operation
        aga = ad_op.create
        aga.ad_group = ag_service.ad_group_path(customer_id, rsa_spec["ad_group_id"])
        aga.status = status_enum[rsa_spec.get("status", "PAUSED")]
        ad = aga.ad
        rsa = ad.responsive_search_ad
        # NOTE (Sprint 3b.16 F16 fix): proto-plus repeated message fields use
        # .append() with new typed instance, NOT .add() (raw protobuf API).
        # Smoke test in Nutry caught this — tests passed with ProtoFieldCapture
        # mock supporting .add() but real google-ads SDK doesn't.
        _anexar_textos(client, rsa, "headlines", rsa_spec["headlines"])
        _anexar_textos(client, rsa, "descriptions", rsa_spec["descriptions"])
        for url in rsa_spec["final_urls"]:
            ad.final_urls.append(url)
        if "path1" in rsa_spec:
            rsa.path1 = rsa_spec["path1"]
        if "path2" in rsa_spec:
            rsa.path2 = rsa_spec["path2"]
        operations.append(op)
    return operations


@register_builder("update_rsa")
def build_update_rsa(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {updates: [{ad_id, headlines?, descriptions?, final_urls?,
                            path1?, path2?, remover_pinos?}]}

    headlines/descriptions: item string ou `{text, pinned_field?}` (G2). `remover_pinos`
    e so do pre-flight (libera a perda de pino); o builder o ignora.

    Uses AdService (not AdGroupAdService) — Ad resource holds RSA content.
    Builds update_mask from set fields. Provided list replaces existing
    (proto-plus semantics with field_mask).

    Note (Sprint 3b.17 F16 lesson): repeated message fields use .append()
    with typed instance, NOT .add(). Mirrors create_rsa pattern.
    """
    operations: list[Any] = []
    ad_service = client.get_service("AdService")
    for spec in payload["updates"]:
        op = client.get_type("MutateOperation")
        ad_op = op.ad_operation
        ad = ad_op.update
        ad.resource_name = ad_service.ad_path(customer_id, spec["ad_id"])
        rsa = ad.responsive_search_ad
        mask_paths: list[str] = []
        if "headlines" in spec:
            _anexar_textos(client, rsa, "headlines", spec["headlines"])
            mask_paths.append("responsive_search_ad.headlines")
        if "descriptions" in spec:
            _anexar_textos(client, rsa, "descriptions", spec["descriptions"])
            mask_paths.append("responsive_search_ad.descriptions")
        if "final_urls" in spec:
            for url in spec["final_urls"]:
                ad.final_urls.append(url)
            mask_paths.append("final_urls")
        if "path1" in spec:
            rsa.path1 = spec["path1"]
            mask_paths.append("responsive_search_ad.path1")
        if "path2" in spec:
            rsa.path2 = spec["path2"]
            mask_paths.append("responsive_search_ad.path2")
        client.copy_from(ad_op.update_mask, FieldMask(paths=mask_paths))
        operations.append(op)
    return operations
