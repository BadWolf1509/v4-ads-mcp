"""Trava a lista estatica do list_gaql_resources contra o proto do SDK (S1).

O catalogo curado em `src/google_ads/queries/meta.py` carregava
`segments.network_type`, que a API recusa ("Unrecognized field"); o nome real
e `segments.ad_network_type`. Este teste resolve cada campo pontuado contra
`GoogleAdsRow` da mesma versao (v25) que o `src` usa.
"""

from google.ads.googleads.v25.services.types.google_ads_service import GoogleAdsRow

from src.google_ads.queries.meta import RESOURCES, SEGMENTS


def campo_existe_no_proto(caminho: str) -> bool:
    """Resolve `a.b.c` contra GoogleAdsRow; intermediarios tem que ser mensagem."""
    classe = GoogleAdsRow
    segmentos = caminho.split(".")
    for i, nome in enumerate(segmentos):
        campos = classe.meta.fields
        # proto-plus renomeia campo que colide com palavra reservada do Python
        # (`type` vira `type_`); o nome na GAQL continua `type`.
        if nome not in campos and f"{nome}_" in campos:
            nome = f"{nome}_"
        if nome not in campos:
            return False
        if i == len(segmentos) - 1:
            return True
        campo = campos[nome]
        if not campo.message:
            return False
        classe = campo.message
    return False


def test_todo_segmento_estatico_existe_no_proto() -> None:
    inexistentes = [s for s in SEGMENTS if not campo_existe_no_proto(s)]
    assert inexistentes == []


def test_todo_campo_estatico_existe_no_proto() -> None:
    inexistentes = [
        (recurso, campo)
        for recurso, meta in RESOURCES.items()
        for campo in meta["fields"]
        if not campo_existe_no_proto(campo)
    ]
    assert inexistentes == []


def test_resolvedor_recusa_campo_inventado() -> None:
    assert not campo_existe_no_proto("segments.network_type")
    assert campo_existe_no_proto("segments.ad_network_type")
    assert campo_existe_no_proto("ad_group_ad.ad.responsive_search_ad.headlines")
