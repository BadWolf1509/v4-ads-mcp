"""Leitura da claim `aud` direto do corpo do token, sem passar por `verify_*`.

Existe porque os dois verificadores **removem** a audiência do que devolvem
(`raw_payload.pop("aud", None)` em `oauth_state.verify_state`; `PanelSession`
nem tem o campo). Então `verify_*` não serve para afirmar qual audiência um
call-site **assinou** — ela só responde "casa com a que eu pedi", e um teste
que só chama `verify_*(…, aud=X)` prova apenas que o token casa com X, sem
distinguir X de qualquer outro valor que o call-site pudesse ter escrito.

Formato do token: ``b64url(payload_json) "." b64url(hmac_sha256(payload_json))``.
O primeiro segmento é o JSON e se lê sem chave nenhuma — o HMAC protege contra
adulteração, não contra leitura.
"""

from __future__ import annotations

import base64
import json
from typing import Any


def audiencia_crua(token: str) -> str | None:
    """Devolve a claim `aud` do corpo do token (ou None se ela não existir).

    Levanta `AssertionError` quando o token não tem a forma esperada: num teste,
    corpo ilegível é falha de teste, não `None` silencioso que passaria por
    "audiência ausente".
    """
    body_b64 = token.split(".", 1)[0]
    pad = (-len(body_b64)) % 4
    try:
        corpo: Any = json.loads(base64.urlsafe_b64decode(body_b64 + ("=" * pad)))
    except Exception as e:  # noqa: BLE001 — em teste, qualquer falha aqui é falha do teste
        raise AssertionError(f"corpo do token ilegível: {token[:40]}…") from e
    if not isinstance(corpo, dict):
        raise AssertionError(f"corpo do token não é objeto JSON: {corpo!r}")
    aud = corpo.get("aud")
    if aud is not None and not isinstance(aud, str):
        raise AssertionError(f"claim 'aud' não é string: {aud!r}")
    return aud


def state_da_url(location: str) -> str:
    """Extrai o parâmetro `state` da URL de consentimento para onde a rota redireciona."""
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(location).query)
    states = qs.get("state") or []
    assert len(states) == 1, f"esperava exatamente um `state` na URL, achei {states!r}"
    return states[0]
