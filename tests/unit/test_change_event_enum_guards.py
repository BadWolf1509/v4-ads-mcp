"""F135/F134: o enum de `change_resource_type` divergia da API nas DUAS direcoes.

`get_change_history._RESOURCE_TYPES` era lista mantida a mao. Medido em
2026-09-02 contra o SDK v24 instalado: a API tem 19 valores (fora
UNSPECIFIED/UNKNOWN), a lista tinha 12 — **faltavam 10 e sobravam 3**.

As duas direcoes falham diferente, e por isso as duas precisam de guard:

- **O que falta some em silencio.** `get_change_history(TODAY,
  resource_types=["AD_GROUP_AD"])` devolveu `total_changes: 0` na conta
  786-223-0676 num dia com **20 linhas `AD`** — editar RSA emite `AD`, e
  `AD_GROUP_AD` era o unico enum de anuncio oferecido. Quem perguntava
  "mexeram nos meus anuncios?" pelo caminho que a tool oferece recebia zero
  com 20 edicoes no periodo. Familia silent-acceptance, agora na camada do
  nosso proprio enum.
- **O que sobra quebra alto.** `BIDDING_STRATEGY`, `CONVERSION_ACTION` e
  `CUSTOMER_NEGATIVE_CRITERION` nao existem no enum; os tres foram probados
  contra a API e devolvem `Invalid enum value cannot be included in WHERE
  clause`.

## Por que a producao NAO deriva do SDK

O desenho inicial era derivar `_RESOURCE_TYPES` do enum em tempo de import.
Foi descartado por duas razoes:

1. **O schema de uma tool MCP e contrato publico.** Derivando, um bump do
   `google-ads` no lockfile mudaria os valores aceitos pelo gestor sem diff,
   sem revisao e sem linha de catalogo. Trocar divergencia silenciosa por
   mudanca silenciosa de contrato nao e progresso.
2. **Cravaria a versao da API num import do caminho que atende request.** O
   `src/` inteiro fala com o SDK por `client.get_type()`/`client.enums`; nao ha
   nenhum `from google.ads.googleads.v24...` em producao, e o unico jeito de
   seguir a versao seria depender de `client._DEFAULT_VERSION`, que e privado.
   Um upgrade de SDK derrubaria o servidor no import.

Entao: **a fonte autoritativa e o enum do SDK, o reconciliador e este arquivo.**
A producao guarda um snapshot revisado; o CI cruza as duas pontas a cada push.
Divergencia vira falha alta com diff legivel, em vez de zero silencioso.
"""

from __future__ import annotations

import importlib

from google.ads.googleads.client import _DEFAULT_VERSION

from src.google_ads.queries._common import _RESOURCE_PLURAL_TO_TYPE
from src.mcp.tools.get_change_history import _RESOURCE_TYPES, _SCHEMA

# Dump verificado em 2026-09-02, com o SDK que estava instalado (v24).
# Serve de tripwire: se o SDK ganhar/perder valor, o teste que compara com ele
# falha e a mudanca entra por revisao humana em vez de calada.
SDK_SNAPSHOT_2026_09_02 = [
    "AD",
    "AD_GROUP",
    "AD_GROUP_AD",
    "AD_GROUP_ASSET",
    "AD_GROUP_BID_MODIFIER",
    "AD_GROUP_CRITERION",
    "AD_GROUP_FEED",
    "ASSET",
    "ASSET_SET",
    "ASSET_SET_ASSET",
    "CAMPAIGN",
    "CAMPAIGN_ASSET",
    "CAMPAIGN_ASSET_SET",
    "CAMPAIGN_BUDGET",
    "CAMPAIGN_CRITERION",
    "CAMPAIGN_FEED",
    "CUSTOMER_ASSET",
    "FEED",
    "FEED_ITEM",
]

# Probados um a um contra a API em 2026-09-02: os tres devolvem
# "Invalid enum value cannot be included in WHERE clause".
VALORES_QUE_A_API_REJEITA = [
    "BIDDING_STRATEGY",
    "CONVERSION_ACTION",
    "CUSTOMER_NEGATIVE_CRITERION",
]

# Sentinelas de proto — nao sao filtro valido pro gestor.
_SENTINELAS = {"UNSPECIFIED", "UNKNOWN"}


def _resource_types_do_sdk() -> list[str]:
    """Le o enum do SDK instalado, seguindo a versao default do proprio client.

    Usa `_DEFAULT_VERSION` de proposito: se o SDK subir de versao, este teste
    passa a ler o enum novo e o snapshot acusa a diferenca — que e o sinal que
    queremos. Um `v24` cravado aqui daria erro de import em vez de diff.
    """
    mod = importlib.import_module(
        f"google.ads.googleads.{_DEFAULT_VERSION}.enums.types.change_event_resource_type"
    )
    enum_cls = mod.ChangeEventResourceTypeEnum.ChangeEventResourceType
    return sorted(n for n in enum_cls.__members__ if n not in _SENTINELAS)


def test_ad_e_oferecido_como_resource_type() -> None:
    """O caso que originou o F135: editar RSA emite `AD`, nao `AD_GROUP_AD`."""
    assert "AD" in _RESOURCE_TYPES


def test_customer_asset_e_oferecido_como_resource_type() -> None:
    """Vinculo de asset em nivel de conta era invisivel ao filtro."""
    assert "CUSTOMER_ASSET" in _RESOURCE_TYPES


def test_enum_nao_oferece_valor_que_a_api_rejeita() -> None:
    """Oferecer filtro que a API recusa transforma pergunta valida em erro."""
    sobrando = sorted(set(VALORES_QUE_A_API_REJEITA) & set(_RESOURCE_TYPES))
    assert sobrando == [], f"schema oferece valores que a API rejeita: {sobrando}"


def test_producao_bate_com_o_enum_do_sdk_instalado() -> None:
    """O guard central: reconcilia o snapshot de producao com a fonte autoritativa.

    Falha quando a lista de producao diverge do SDK — em qualquer direcao. Foi
    esta divergencia (10 faltando, 3 sobrando) que produziu o F135.
    """
    do_sdk = _resource_types_do_sdk()
    assert sorted(_RESOURCE_TYPES) == do_sdk, (
        "_RESOURCE_TYPES divergiu do enum do SDK. "
        f"Faltando: {sorted(set(do_sdk) - set(_RESOURCE_TYPES))}. "
        f"Sobrando: {sorted(set(_RESOURCE_TYPES) - set(do_sdk))}."
    )


def test_sdk_nao_mudou_desde_a_verificacao_de_2026_09_02() -> None:
    """Tripwire de upgrade de SDK, com causa distinta do teste acima.

    Se este falhar e o outro passar, o `google-ads` mudou o enum: revise os
    valores novos, atualize `_RESOURCE_TYPES` e este snapshot no mesmo commit.
    """
    assert _resource_types_do_sdk() == sorted(SDK_SNAPSHOT_2026_09_02)


def test_enum_exclui_unspecified_e_unknown() -> None:
    """Nao falha contra o codigo pre-fix — a lista a mao ja nao os tinha.

    Existe porque a producao passa a espelhar o enum, onde as sentinelas EXISTEM.
    """
    assert _SENTINELAS.isdisjoint(_RESOURCE_TYPES)


def test_schema_publica_a_lista_revisada() -> None:
    """Guard de fiacao, nao de bug: a lista tem que chegar ao consumidor.

    Este NAO falha contra o codigo pre-fix (a fiacao ja estava certa; o
    conteudo e que estava errado).
    """
    assert _SCHEMA["properties"]["resource_types"]["items"]["enum"] == _RESOURCE_TYPES


def test_parser_de_resource_path_conhece_customer_assets() -> None:
    """F134: o mapa tinha as duas outras camadas de asset e nao esta."""
    assert _RESOURCE_PLURAL_TO_TYPE.get("customerAssets") == "customer_asset"
