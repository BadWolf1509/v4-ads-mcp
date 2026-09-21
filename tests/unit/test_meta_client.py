"""Unit tests pra `src/meta_ads/client.py` — constantes e erros do lado Meta.

**O que saiu daqui, e por quê.** Este arquivo nasceu como mitigação do F48
(`facebook_business` v21 mudou a assinatura de `FacebookAdsApi.__init__`) e
tinha 8 testes de `build_facebook_ads_api` mais 2 de sanidade sobre a
assinatura do próprio SDK. Na onda final do F190 a função foi **medida** com
zero consumidores em `src/` (`grep -rn "build_facebook_ads_api" src/` só
achava a definição), porque a troca de transporte tirou o SDK do caminho de
request. Os 10 testes foram junto:

- os 8 da fábrica, porque a fábrica não existe mais;
- os 2 de sanidade do SDK (`FacebookSession(...)`, `FacebookAdsApi(session=)`),
  porque eles afirmavam a forma de uma API de terceiro que **nenhum código
  nosso chama** — ficariam verdes para sempre protegendo nada, que é a mesma
  doença um andar acima: teste morto sobre código morto parece cobertura em
  dobro.

O que sobrou é o que o resto do código realmente importa daqui.
"""

from src.meta_ads.client import (
    META_GRAPH_API_VERSION,
    MetaAccessDeniedError,
    MetaSystemUserTokenMissingError,
)


def test_meta_graph_api_version_constant_pinned():
    """META_GRAPH_API_VERSION must be explicit string (not env var, not auto)."""
    assert META_GRAPH_API_VERSION == "v22.0"


def test_meta_system_user_token_missing_error_is_exception():
    assert issubclass(MetaSystemUserTokenMissingError, Exception)


def test_meta_access_denied_error_is_exception():
    assert issubclass(MetaAccessDeniedError, Exception)


def test_meta_access_denied_error_stores_message():
    err = MetaAccessDeniedError("sem acesso à conta 123")
    assert err.message == "sem acesso à conta 123"
    assert str(err) == "sem acesso à conta 123"
