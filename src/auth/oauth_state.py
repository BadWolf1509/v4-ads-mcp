"""HMAC-signed, time-bounded OAuth state token.

Format:  base64url(payload_json) + "." + base64url(hmac_sha256(payload_json))

Payload always includes 'iat' (issued-at unix seconds) and 'aud' (audiência).
Verify checks HMAC tag, exige a audiência esperada e rejeita se 'iat' for mais
velho que STATE_TTL_SECONDS.

Used in /oauth/google/start to encode {manager_id, kind} so the callback
can recover them WITHOUT a server-side session lookup. Stateless across
Cloud Run instances. Defende contra CSRF (atacante não forja HMAC) e LIMITA
replay a STATE_TTL_SECONDS. A audiência impede que o token valha para outro
propósito. O vínculo com o navegador NÃO está aqui: quem precisa dele embute um
nonce no payload e o confere contra um cookie (`oauth.py`, `OAUTH_NONCE_COOKIE`).
"""

from typing import Any, Literal

from src.auth.token_assinado import MENSAGENS_STATE, assinar, verificar

STATE_TTL_SECONDS = 10 * 60  # 10 minutes

StateAudience = Literal["google_oauth", "cli_invite"]
"""As audiências da família `state` — as únicas que `sign_state`/`verify_state` aceitam.

O tipo é dividido por família porque o conjunto plano ainda deixava a função
ERRADA emitir o token CERTO: com uma união só, `sign_state(..., aud="panel")`
cunhava um cookie de painel byte-idêntico ao de `sign_panel_session` (mesmo
formato, mesma chave, mesmo corpo), e o `mypy --strict` aprovava. É a mesma
confusão que a claim `aud` fecha, um nível acima — a separação entre as duas
famílias passa a ser do tipo, e não da disciplina de quem escrever o próximo
call-site.
"""

PanelAudience = Literal["panel"]
"""A audiência da família `cookie de painel`.

Só `sign_panel_session`/`verify_panel_session` a aceitam, e elas não aceitam
mais nada.
"""

Audience = Literal[StateAudience, PanelAudience]
"""A união das duas famílias — as três audiências do projeto, num lugar só.

`Literal` aninhado ACHATA, em tempo de tipo (PEP 586) e em tempo de execução:
isto é literalmente `Literal["google_oauth", "cli_invite", "panel"]`, e não um
`Union` de dois `Literal` (que quebraria `get_args`). Serve a quem precisa
falar das três de uma vez; nenhuma das quatro funções a usa como parâmetro,
de propósito. (A audiência do OAuth pessoal da Meta saiu com ele, em 11/2026.)

`panel_session` importa daqui, e os call-sites também devem: audiência com duas
definições é audiência com duas verdades. Fechar em `Literal` existe porque a
claim só vale enquanto as duas pontas escrevem a MESMA string — como `str`
livre, um typo casado entre quem assina e quem confere (`"pannel"` dos dois
lados) funciona, passa em todo teste e grava a audiência errada nos tokens.
Com o `Literal`, o `mypy --strict` do gate pega esse typo nos **7 call-sites
de `src/`** (eram 9 até a saída do OAuth pessoal da Meta, 11/2026) — que são
os que ele olha. O gate roda `mypy src`
(passo `mypy` de `scripts/_runner.py`, `ci.yml:170`) e **nunca** `tests/`; lá o typo não é
erro de tipo, e nem sempre vira teste vermelho. Medido em 2026-09-06 com dois
`aud="pannel"` plantados em `tests/`: `mypy src` ficou limpo nos dois, e o
pytest só pegou aquele cuja asserção dependia do valor.
"""


class InvalidStateError(Exception):
    """Raised when state is tampered, wrong key, wrong audience, expired, or malformed."""


def sign_state(
    payload: dict[str, Any],
    signing_key: str,
    *,
    aud: StateAudience,
    issued_at: float | None = None,
) -> str:
    """Build a signed state string from a JSON-serializable payload.

    `aud` (audiência) é obrigatório e não tem default. Três tipos de token
    deste projeto compartilham chave e formato; sem audiência, qualquer um vale
    como qualquer outro — medido em 2026-09-06, o convite de CLI era aceito
    verbatim como cookie de painel, e o TTL de 10 min virava 24 h no caminho.
    Default aqui silenciaria justamente o erro que a claim existe pra impedir.
    """
    return assinar(payload, signing_key, aud=aud, issued_at=issued_at)


def verify_state(state: str, signing_key: str, *, aud: StateAudience) -> dict[str, Any]:
    """Verify HMAC + audiência + TTL, return decoded payload. Raises on failure.

    A ordem importa: HMAC primeiro (nada do payload é confiável antes disso),
    audiência depois, TTL por último. A conferência de audiência mora AQUI e
    não no chamador — chamador que confere é chamador que pode esquecer, e foi
    o que aconteceu em três dos quatro tokens que existiam em 09/2026.

    O payload devolvido não traz 'aud' nem 'iat': são claims da própria
    verificação, e o chamador não deve nem vê-las.
    """
    return verificar(
        state,
        signing_key,
        aud=aud,
        ttl=STATE_TTL_SECONDS,
        erro=InvalidStateError,
        mensagens=MENSAGENS_STATE,
    )
