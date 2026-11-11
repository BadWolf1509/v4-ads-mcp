"""Codec único dos tokens assinados do projeto (state de OAuth e cookie de painel).

Formato:  base64url(body_json) + "." + base64url(hmac_sha256(chave, body_json))

O HMAC é calculado sobre os BYTES do body (não sobre a string base64). O body é
`json.dumps(claims, sort_keys=True, separators=(",", ":"))` em UTF-8, com as
claims `aud` e `iat` embutidas. Dois módulos tinham cada um a sua cópia deste
formato; as duas cópias eram idênticas salvo pelo texto das mensagens de erro,
que agora é dado (`MensagensDeErro`) e não código.

`verificar` confere, nesta ordem: formato → HMAC → JSON → dict → audiência →
`iat` inteiro → TTL. A ordem importa: nada do payload é confiável antes do HMAC.

Privado a `oauth_state` e `panel_session`: `assinar`/`verificar` aceitam a união de
audiências, então só os wrappers tipados deles podem importá-lo. O guard
`tests/unit/test_token_assinado_privado.py` falha se outro módulo de `src/` o importar.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.auth.oauth_state import Audience


@dataclass(frozen=True)
class MensagensDeErro:
    """O texto de cada recusa. `audiencia` leva `{aud}` no lugar da esperada."""

    malformado: str
    hmac: str
    json: str
    nao_dict: str
    audiencia: str
    iat: str
    expirado: str


MENSAGENS_STATE = MensagensDeErro(
    malformado="Malformed state",
    hmac="HMAC mismatch (tampered or wrong key)",
    json="Payload is not valid JSON",
    nao_dict="Payload is not a dict",
    audiencia="Audiência inválida (esperada: {aud})",
    iat="Missing or invalid 'iat'",
    expirado="State expired",
)

MENSAGENS_PAINEL = MensagensDeErro(
    malformado="Malformed cookie",
    hmac="HMAC mismatch",
    json="Bad JSON",
    nao_dict="Payload is not a dict",
    audiencia="Audiência inválida (esperada: {aud})",
    iat="Missing iat",
    expirado="Cookie expired",
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + ("=" * pad))


def assinar(
    claims: dict[str, Any],
    chave: str,
    *,
    aud: Audience,
    issued_at: float | None = None,
) -> str:
    """Assina `claims` + `aud` + `iat`. `aud` e `iat` do argumento vencem os de `claims`."""
    full = dict(claims)
    full["aud"] = aud
    full["iat"] = int(issued_at if issued_at is not None else time.time())
    body = json.dumps(full, sort_keys=True, separators=(",", ":")).encode("utf-8")
    tag = hmac.new(chave.encode("utf-8"), body, sha256).digest()
    return f"{_b64url(body)}.{_b64url(tag)}"


def verificar(
    token: str,
    chave: str,
    *,
    aud: Audience,
    ttl: int,
    erro: type[Exception],
    mensagens: MensagensDeErro,
) -> dict[str, Any]:
    """Confere o token e devolve as claims sem `aud` e `iat`. Levanta `erro`.

    A mensagem da audiência diz só a esperada: não ecoa a recebida nem o token.
    """
    try:
        body_b64, tag_b64 = token.split(".", 1)
        body = _b64url_decode(body_b64)
        tag = _b64url_decode(tag_b64)
    except (ValueError, binascii.Error) as e:
        raise erro(mensagens.malformado) from e

    expected = hmac.new(chave.encode("utf-8"), body, sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise erro(mensagens.hmac)

    try:
        raw: Any = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise erro(mensagens.json) from e

    if not isinstance(raw, dict):
        raise erro(mensagens.nao_dict)

    if raw.get("aud") != aud:
        raise erro(mensagens.audiencia.format(aud=aud))

    iat = raw.get("iat")
    if not isinstance(iat, int):
        raise erro(mensagens.iat)
    if (time.time() - iat) > ttl:
        raise erro(mensagens.expirado)

    raw.pop("iat", None)
    raw.pop("aud", None)
    return raw
