"""C3 — confusão de tipo de token entre state de OAuth e cookie de painel.

Quatro tipos de token compartilham uma chave (`settings.session_signing_key`) e
um formato (`b64url(json).b64url(hmac_sha256)`), e só um carrega claim de
audiência. Medido em 2026-09-06: `verify_panel_session` aceita verbatim o
convite emitido por `admin.py:102`, devolvendo a sessão daquele gestor.

Cada `pytest.raises` fixa a MENSAGEM esperada, e não só o tipo da exceção. Sem
isso o teste afirma o adjacente à invariante: medido por sabotagem em
2026-09-06, remover a checagem de audiência de `verify_panel_session` deixava a
suíte inteira verde, porque os payloads de outra audiência também carecem de
`email` e a recusa vinha desse outro ramo.

A segunda leva (2026-09-06, pós-revisão) guarda o que o código já fazia certo e
nada afirmava: a assinatura sem default, a recusa do token sem a claim, a ordem
HMAC → audiência e a remoção de `aud`/`iat`. Cada uma nomeia, na própria
docstring, a mutação de produção que a deixa vermelha.

A terceira leva (2026-09-06, Task 4) fecha dois mutantes medidos sobrevivendo à
suíte inteira com 0 vermelhos: a audiência comparada por contingência em vez de
igualdade, e o ramo `email` do cookie, que nenhum payload da suíte alcançava
porque `manager_id` é conferido antes e abocanhava todos os casos.

A quarta leva (2026-09-06, onda de correção da revisão final) fecha as duas
metades da ordem declarada que ainda não tinham asserção: `audiência → TTL`
(M1) e a precedência `kwarg vence payload` do `sign_state` (M2). As duas
sobreviviam à suíte inteira com 0 vermelhos.
"""

from __future__ import annotations

import base64
import hmac
import inspect
import json
import time
from collections.abc import Callable
from hashlib import sha256
from typing import Any, get_args, get_type_hints

import pytest

from src.auth.oauth_state import (
    STATE_TTL_SECONDS,
    Audience,
    InvalidStateError,
    PanelAudience,
    StateAudience,
    sign_state,
    verify_state,
)
from src.auth.panel_session import (
    PANEL_SESSION_TTL_SECONDS,
    InvalidPanelSessionError,
    sign_panel_session,
    verify_panel_session,
)

CHAVE = "chave-de-teste-com-no-minimo-32-caracteres-ok"
OUTRA_CHAVE = "outra-chave-de-teste-com-no-minimo-32-caracteres"
GESTOR = "11111111-2222-3333-4444-555555555555"
AUD_INVALIDA = "Audiência inválida"


def _cunha(payload: dict[str, Any], chave: str) -> str:
    """Cunha um token no formato público do projeto, com HMAC VÁLIDO.

    Escrito com a stdlib de propósito, sem os `_b64url` dos módulos: quem forja
    um token em produção conhece o formato de rede, não os nossos helpers. Um
    forjador que reusasse o helper acompanharia calado qualquer mudança de
    codificação, e os testes que dependem dele deixariam de morder.
    """

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    tag = hmac.new(chave.encode("utf-8"), body, sha256).digest()
    return f"{b64(body)}.{b64(tag)}"


def test_state_de_oauth_nao_vale_como_cookie_de_painel() -> None:
    """O payload que `admin.py:102` emite como convite não pode virar sessão."""
    convite = sign_state({"manager_id": GESTOR}, CHAVE, aud="cli_invite")
    with pytest.raises(InvalidPanelSessionError, match=AUD_INVALIDA):
        verify_panel_session(convite, CHAVE, aud="panel")


def test_cookie_completo_de_outra_audiencia_e_recusado_pelo_painel() -> None:
    """Isola a checagem de audiência do painel dos demais ramos de recusa.

    Os outros casos usam payloads que também carecem de `email`, então seguiriam
    verdes mesmo sem checagem de audiência nenhuma. Aqui o token é um cookie
    COMPLETO e válido em tudo — HMAC, `manager_id`, `email`, TTL — menos a
    audiência, então só a checagem de `aud` pode recusá-lo.
    """
    outra_aud = sign_panel_session(
        manager_id=GESTOR,
        email="a@v4company.com",
        signing_key=CHAVE,
        aud="cli_invite",
    )
    with pytest.raises(InvalidPanelSessionError, match=AUD_INVALIDA):
        verify_panel_session(outra_aud, CHAVE, aud="panel")


def test_cookie_de_painel_nao_vale_como_state_de_oauth() -> None:
    """E o inverso: o cookie não pode ser replayado como state de callback."""
    cookie = sign_panel_session(
        manager_id=GESTOR, email="a@v4company.com", signing_key=CHAVE, aud="panel"
    )
    with pytest.raises(InvalidStateError, match=AUD_INVALIDA):
        verify_state(cookie, CHAVE, aud="google_oauth")


def test_state_do_google_nao_vale_como_state_do_meta() -> None:
    """As duas audiências de OAuth também são distintas entre si."""
    google = sign_state({"manager_id": GESTOR}, CHAVE, aud="google_oauth")
    with pytest.raises(InvalidStateError, match=AUD_INVALIDA):
        verify_state(google, CHAVE, aud="meta_oauth")


@pytest.mark.parametrize(
    ("verificar", "excecao", "esperada"),
    [
        pytest.param(verify_state, InvalidStateError, "google_oauth", id="verify_state"),
        pytest.param(
            verify_panel_session,
            InvalidPanelSessionError,
            "panel",
            id="verify_panel_session",
        ),
    ],
)
def test_recusa_nao_ecoa_o_aud_recebido(
    verificar: Callable[..., object], excecao: type[Exception], esperada: str
) -> None:
    """A mensagem diz a audiência ESPERADA e nada mais — nem token, nem o `aud`
    que veio no payload. Segredo não vaza para log por mensagem de erro.

    Mutação que derruba: a mensagem de qualquer um dos dois passar a incluir a
    audiência recebida.

    Parametrizado sobre as DUAS funções. Enquanto só o painel era exercitado,
    fazer apenas `verify_state` ecoar não derrubava teste algum — e ele é o
    vetor mais exposto, porque o state viaja na query string e cai em histórico,
    `Referer` e log de acesso.
    """
    convite = sign_state({"manager_id": GESTOR}, CHAVE, aud="cli_invite")
    with pytest.raises(excecao) as excinfo:
        verificar(convite, CHAVE, aud=esperada)
    msg = str(excinfo.value)
    assert esperada in msg
    assert "cli_invite" not in msg
    assert convite not in msg
    assert GESTOR not in msg


def test_ttl_do_state_nao_e_estendido_por_verificacao_de_outra_audiencia() -> None:
    """A inversão de TTL era o que alargava a janela de 10 min para 24 h.

    Medido em 2026-09-06: um token de 1 hora era recusado por `verify_state`
    ("State expired") e ACEITO por `verify_panel_session`, porque o TTL do
    cookie é 24 h. Com audiência, o token sequer chega à checagem de TTL do
    outro lado.
    """
    velho = sign_state(
        {"manager_id": GESTOR}, CHAVE, aud="cli_invite", issued_at=time.time() - 3600
    )
    with pytest.raises(InvalidStateError, match="State expired"):
        verify_state(velho, CHAVE, aud="cli_invite")
    with pytest.raises(InvalidPanelSessionError, match=AUD_INVALIDA):
        verify_panel_session(velho, CHAVE, aud="panel")


def test_payload_sem_manager_id_e_recusado() -> None:
    """`panel_session.py:85` devolvia `manager_id=""` em vez de recusar — sessão
    anônima válida é pior que sessão inválida."""
    from src.auth.oauth_state import _b64url as _b64url_do_state  # noqa: PLC2701
    from src.auth.panel_session import _b64url as _b64url_do_painel  # noqa: PLC2701

    # O formato é literalmente o mesmo dos dois lados — é por isso que um token
    # de um módulo é byte-compatível com o outro, e por isso a audiência precisa
    # existir. Os bytes têm bit alto de propósito: `b"formato"` codificava IGUAL
    # nos dois alfabetos, urlsafe e padrão, então a igualdade era verdadeira
    # independente da implementação e não discriminava nada. Estes três são
    # `-__-` em urlsafe e `+//+` em base64 padrão.
    assert _b64url_do_painel(b"\xfb\xff\xfe") == _b64url_do_state(b"\xfb\xff\xfe")
    assert _b64url_do_painel(b"\xfb\xff\xfe") == "-__-"

    # Audiência CERTA de propósito: aqui o que está sob teste é o `manager_id`.
    sem_id = sign_state({"mode": "panel_login"}, CHAVE, aud="panel")
    with pytest.raises(InvalidPanelSessionError, match="Missing manager_id"):
        verify_panel_session(sem_id, CHAVE, aud="panel")


# ---------------------------------------------------------------------------
# Segunda leva (pós-revisão da Task 1-3): as invariantes declaradas que nenhuma
# asserção prendia. Todas medidas por mutação em cópia fora do repositório.
# ---------------------------------------------------------------------------

_FUNCOES_COM_AUDIENCIA = [
    pytest.param(sign_state, StateAudience, id="sign_state"),
    pytest.param(verify_state, StateAudience, id="verify_state"),
    pytest.param(sign_panel_session, PanelAudience, id="sign_panel_session"),
    pytest.param(verify_panel_session, PanelAudience, id="verify_panel_session"),
]


@pytest.mark.parametrize(("funcao", "familia"), _FUNCOES_COM_AUDIENCIA)
def test_aud_e_keyword_only_sem_default_e_tipado_pela_familia(
    funcao: Callable[..., object], familia: object
) -> None:
    """`aud` não pode ganhar default — é o que torna "esquecer" impossível —, e
    o tipo de cada função é o da SUA família, nunca a união.

    Mutação que derruba: `aud: Audience = "panel"` em qualquer uma das quatro,
    afrouxar o tipo de volta para `str`, **ou alargar qualquer uma das quatro de
    volta para `Audience`**. Esta última é o achado I1: com a união nas quatro,
    `sign_state(..., aud="panel")` cunha um cookie de painel byte-idêntico ao de
    `sign_panel_session` e o `mypy --strict` aprova — a função errada emitindo o
    token certo. A asserção é de igualdade contra a família, e não "está contido
    em `Audience`", porque a união satisfaria a contingência e o alargamento
    passaria batido.

    Um default reabre o furo inteiro, porque a chamada que esquecer o `aud`
    volta a funcionar em silêncio com a audiência de outra família. E a mutação
    é invisível sem esta asserção: medido em 2026-09-06, pôr default nas quatro
    deixava a suíte MAIS verde que o código correto, por consertar de carona os
    15 testes que ainda não passam o kwarg. Aquele sinal é acidental, e a
    Task 4 vai apagá-lo ao escrever `aud=` em cada call-site.

    O tipo fechado entra aqui pelo mesmo motivo: voltar para `str` não quebra
    nada em lugar nenhum, e o `mypy --strict` deixa de pegar o typo casado nos
    ~70 literais que a Task 4 vai escrever à mão.
    """
    parametro = inspect.signature(funcao).parameters["aud"]
    assert parametro.kind is inspect.Parameter.KEYWORD_ONLY
    assert parametro.default is inspect.Parameter.empty
    assert get_type_hints(funcao)["aud"] == familia
    assert get_type_hints(funcao)["aud"] != Audience


def test_familias_de_audiencia_sao_disjuntas_e_cobrem_as_quatro() -> None:
    """As duas famílias particionam `Audience`: nada em comum, nada de fora.

    Mutação que derruba: pôr `"panel"` de volta em `StateAudience` (ou qualquer
    audiência de state em `PanelAudience`) — a interseção deixa de ser vazia e o
    cruzamento entre famílias volta a passar no `mypy`. Também derruba tirar uma
    audiência de uma família sem pôr em outra, que a deixaria inalcançável.

    O teste irmão (`test_audiencias_sao_exatamente_quatro`) afirma o total; este
    afirma a PARTIÇÃO, e os dois juntos são o que impede a divisão de virar
    decorativa. Sozinho, o total sobrevive a `StateAudience` com as quatro.
    """
    de_state = set(get_args(StateAudience))
    de_painel = set(get_args(PanelAudience))
    assert de_state == {"google_oauth", "cli_invite", "meta_oauth"}
    assert de_painel == {"panel"}
    assert de_state & de_painel == set()
    assert de_state | de_painel == set(get_args(Audience))


def test_audiencias_sao_exatamente_quatro() -> None:
    """A Global Constraint nº 3 ("quatro audiências, exatamente") como mecanismo.

    Mutação que derruba: acrescentar uma quinta audiência ao `Literal`.

    Cada audiência a mais é uma família de token a mais dividindo a mesma
    chave. A lista cresce por descuido, não por decisão, se ninguém a afirmar.
    """
    assert get_args(Audience) == ("google_oauth", "cli_invite", "meta_oauth", "panel")


def test_state_sem_a_claim_aud_e_recusado() -> None:
    """Token no formato ANTIGO — sem a claim — falha fechado.

    Mutação que derruba: aceitar quando a claim não existe, isto é
    `if payload.get("aud") is not None and payload.get("aud") != aud`.

    É a exceção de compatibilidade que o rollout convida a escrever: este PR
    invalida todo state em voo e todo convite de CLI já distribuído, e quem
    sentir a dor vai querer "tolerar durante a transição". A tolerância é o
    furo de volta por inteiro — o convite de CLI de hoje não tem `aud`, logo
    voltaria a valer como cookie de painel.

    O payload é completo e o `iat` é fresco: nenhum outro ramo pode recusá-lo.
    """
    antigo = _cunha({"manager_id": GESTOR, "iat": int(time.time())}, CHAVE)
    with pytest.raises(InvalidStateError, match=AUD_INVALIDA):
        verify_state(antigo, CHAVE, aud="google_oauth")


def test_cookie_sem_a_claim_aud_e_recusado() -> None:
    """O mesmo backdoor no cookie de painel — o lado que entrega sessão.

    Mutação que derruba: a mesma tolerância a claim ausente em
    `verify_panel_session`.

    O payload é o cookie pré-deploy verbatim: `manager_id`, `email` e `iat`
    válidos, faltando só a audiência. Sem a recusa, ele volta a virar sessão.
    """
    antigo = _cunha(
        {"manager_id": GESTOR, "email": "a@v4company.com", "iat": int(time.time())},
        CHAVE,
    )
    with pytest.raises(InvalidPanelSessionError, match=AUD_INVALIDA):
        verify_panel_session(antigo, CHAVE, aud="panel")


@pytest.mark.parametrize(
    ("verificar", "excecao", "esperada"),
    [
        pytest.param(verify_state, InvalidStateError, "google_oauth", id="verify_state"),
        pytest.param(
            verify_panel_session,
            InvalidPanelSessionError,
            "panel",
            id="verify_panel_session",
        ),
    ],
)
def test_hmac_e_conferido_antes_da_audiencia(
    verificar: Callable[..., object], excecao: type[Exception], esperada: str
) -> None:
    """A ordem é HMAC → audiência → TTL, e ela é desenho, não acaso.

    Mutação que derruba: mover a comparação de `aud` para antes do
    `compare_digest` (levando junto o `json.loads`, que ela exige).

    Nada do payload é confiável antes do HMAC: ler `aud` primeiro é decidir com
    dado não autenticado, que qualquer um escreve. O token abaixo tem audiência
    ERRADA **e** tag inválida — é o único par que discrimina. Com audiência
    CERTA e tag inválida as duas ordens respondem `HMAC mismatch` igualmente, e
    o teste passaria dos dois lados sem provar nada.
    """
    forjado = sign_state({"manager_id": GESTOR}, OUTRA_CHAVE, aud="cli_invite")
    with pytest.raises(excecao, match="HMAC mismatch"):
        verificar(forjado, CHAVE, aud=esperada)


def test_verify_state_nao_devolve_aud_nem_iat() -> None:
    """`aud` e `iat` são claims da verificação; o chamador não deve nem vê-las.

    Mutação que derruba: parar de fazer o `pop` das duas antes do `return`.

    É interface declarada e é load-bearing: `meta_oauth.py:247` conferia
    `payload.get("aud")` à mão, e a Task 4 removeu aquela linha PORQUE `aud`
    não vem mais no payload — mantida, ela leria `None` e mandaria TODO
    callback do Meta para /access-denied. Contrato do qual outra task depende
    para raciocinar precisa de asserção. A igualdade é exata de propósito: pega tanto a claim
    que sobra quanto a que sumiria.
    """
    token = sign_state({"manager_id": GESTOR, "kind": "panel_login"}, CHAVE, aud="google_oauth")
    assert verify_state(token, CHAVE, aud="google_oauth") == {
        "manager_id": GESTOR,
        "kind": "panel_login",
    }


def test_manager_id_presente_e_vazio_e_recusado() -> None:
    """String vazia é o valor exato da sessão anônima que o fix existe pra matar.

    Mutação que derruba: afrouxar a guarda para só `not isinstance(..., str)`,
    deixando `""` passar.

    O teste irmão usa a chave AUSENTE, que já cai no `isinstance(None, str)`;
    o ramo `or not manager_id` ficava sem ninguém.
    """
    vazio = _cunha(
        {"manager_id": "", "email": "a@v4company.com", "aud": "panel", "iat": int(time.time())},
        CHAVE,
    )
    with pytest.raises(InvalidPanelSessionError, match="Missing manager_id"):
        verify_panel_session(vazio, CHAVE, aud="panel")


# ---------------------------------------------------------------------------
# Terceira leva (Task 4): dois mutantes que a revisão mediu sobrevivendo à
# suíte inteira — os dois com 0 testes vermelhos antes destas asserções.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("verificar", "excecao", "esperada"),
    [
        pytest.param(verify_state, InvalidStateError, "google_oauth", id="verify_state"),
        pytest.param(
            verify_panel_session,
            InvalidPanelSessionError,
            "panel",
            id="verify_panel_session",
        ),
    ],
)
@pytest.mark.parametrize(
    ("forjar", "rotulo"),
    [
        pytest.param(
            lambda esperada: f"{esperada}-forjada", "sufixo", id="recebida_contem_a_esperada"
        ),
        pytest.param(lambda esperada: esperada[:-1], "prefixo", id="esperada_contem_a_recebida"),
    ],
)
def test_audiencia_exige_igualdade_e_nao_continencia(
    verificar: Callable[..., object],
    excecao: type[Exception],
    esperada: str,
    forjar: Callable[[str], str],
    rotulo: str,
) -> None:
    """A comparação de audiência é igualdade EXATA — nada de `in` nem `startswith`.

    Mutação que derruba: trocar `payload.get("aud") != aud` por uma checagem de
    contingência, `aud not in str(payload.get("aud"))`. Medida em 2026-09-06:
    ela sobrevive à suíte inteira, 0 testes vermelhos, nos DOIS módulos — todo
    teste de audiência existente usa pares disjuntos (`cli_invite` contra
    `panel`), e nenhum par disjunto distingue igualdade de contingência.

    Sob aquele mutante, `aud="panelXYZ"` vira cookie de painel válido: o
    forjador não precisa adivinhar chave nenhuma para escolher a audiência, só
    pendurar um sufixo. As duas direções entram porque matam mutantes
    diferentes — o sufixo mata `esperada in recebida` (e `startswith`), o
    prefixo mata a contingência invertida, `recebida in esperada`.

    O payload é completo para os dois verificadores (`manager_id`, `email`,
    `iat` fresco): só o ramo da audiência pode recusá-lo.
    """
    forjada = forjar(esperada)
    assert forjada != esperada, rotulo
    token = _cunha(
        {
            "manager_id": GESTOR,
            "email": "a@v4company.com",
            "aud": forjada,
            "iat": int(time.time()),
        },
        CHAVE,
    )
    with pytest.raises(excecao, match=AUD_INVALIDA):
        verificar(token, CHAVE, aud=esperada)


def test_cookie_com_manager_id_e_sem_email_e_recusado() -> None:
    """O ramo `email` do `verify_panel_session` — o único sem guard no repo.

    Mutação que derruba: apagar as duas linhas do `if not isinstance(email, str)`.
    Medida em 2026-09-06: apagá-las deixa 0 testes vermelhos, porque nenhum
    payload da suíte tem `manager_id` presente **e** `email` ausente — e
    `manager_id` é conferido primeiro, então ele abocanha todos os casos.

    Sem a guarda, `PanelSession(email=None)` é construído sem erro: a dataclass
    tem `slots=True` e `frozen=True`, mas nenhuma das duas valida tipo em
    runtime. A sessão sai com `email` nulo e o `None` viaja para dentro de
    template e log, quebrando longe daqui.

    Audiência e `manager_id` corretos de propósito: aqui o que está sob teste
    é o `email`, e todo ramo anterior tem que passar limpo.
    """
    sem_email = _cunha(
        {"manager_id": GESTOR, "aud": "panel", "iat": int(time.time())},
        CHAVE,
    )
    with pytest.raises(InvalidPanelSessionError, match="Missing email"):
        verify_panel_session(sem_email, CHAVE, aud="panel")


# ---------------------------------------------------------------------------
# Quarta leva (onda de correção da revisão final): a segunda metade da ordem
# declarada, e a precedência do kwarg sobre o payload. Ambas medidas
# sobrevivendo à suíte inteira, 43/43 verdes, antes destas asserções.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("verificar", "excecao", "esperada", "audiencia_no_corpo", "ttl", "erro_de_ttl"),
    [
        pytest.param(
            verify_state,
            InvalidStateError,
            "google_oauth",
            "panel",
            STATE_TTL_SECONDS,
            "State expired",
            id="verify_state",
        ),
        pytest.param(
            verify_panel_session,
            InvalidPanelSessionError,
            "panel",
            "cli_invite",
            PANEL_SESSION_TTL_SECONDS,
            "Cookie expired",
            id="verify_panel_session",
        ),
    ],
)
def test_audiencia_e_conferida_antes_do_ttl(
    verificar: Callable[..., object],
    excecao: type[Exception],
    esperada: str,
    audiencia_no_corpo: str,
    ttl: int,
    erro_de_ttl: str,
) -> None:
    """A outra metade da ordem HMAC → audiência → TTL, que ficou sem guard.

    Mutação que derruba: mover o bloco de `aud` para DEPOIS do bloco de TTL, nos
    dois módulos. Medida em 2026-09-06: ela sobrevive à suíte inteira, 43/43
    verdes — `test_hmac_e_conferido_antes_da_audiencia` prende só a primeira
    metade, e o teste que chega perto
    (`test_ttl_do_state_nao_e_estendido_por_verificacao_de_outra_audiencia`) usa
    um token de 1 h contra o TTL de 24 h do painel, que as duas ordens
    concordam em não expirar.

    O único par que discrimina viola as DUAS regras ao mesmo tempo: audiência
    de outra família **e** `iat` além do TTL. Na ordem declarada a resposta é
    `Audiência inválida`; sob o mutante, o erro de TTL. Sem impacto de
    segurança — nas duas o token é recusado —, mas "ler `iat` é usar o payload",
    e a Global Constraint manda comparar a audiência antes de qualquer uso dele.

    O controle no fim é o que impede a asserção de ser verdadeira por acidente:
    com o MESMO `iat` e a audiência CERTA, a recusa tem de ser por TTL. Sem ele,
    um `iat` que não estivesse de fato expirado deixaria o teste verde nas duas
    ordens, provando nada.
    """
    iat_expirado = int(time.time() - ttl - 60)
    corpo = {"manager_id": GESTOR, "email": "a@v4company.com", "iat": iat_expirado}

    viola_as_duas = _cunha({**corpo, "aud": audiencia_no_corpo}, CHAVE)
    with pytest.raises(excecao, match=AUD_INVALIDA):
        verificar(viola_as_duas, CHAVE, aud=esperada)

    so_viola_o_ttl = _cunha({**corpo, "aud": esperada}, CHAVE)
    with pytest.raises(excecao, match=erro_de_ttl):
        verificar(so_viola_o_ttl, CHAVE, aud=esperada)
