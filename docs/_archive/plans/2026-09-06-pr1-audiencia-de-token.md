# PR 1 — Audiência de token (C3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Impedir que um token assinado para um propósito valha para outro — hoje o `state` do OAuth Google e o convite de CLI são aceitos verbatim como cookie de sessão do painel.

**Architecture:** Claim de audiência (`aud`) no payload, obrigatório na assinatura e **conferido na verificação**. É o padrão que este repositório já aplica corretamente em um dos quatro tokens (`meta_oauth.py:190` assina, `:247` confere); o trabalho é estender aos outros três e mover a conferência para dentro de `verify_state`, para que esquecer de conferir deixe de ser possível.

**Tech Stack:** `hmac`/`hashlib` da stdlib. Sem dependência nova. Sem migration.

**Spec:** [`docs/superpowers/specs/2026-09-06-correcoes-varredura-design.md`](../specs/2026-09-06-correcoes-varredura-design.md) — PR 1 da seção 4.

## Global Constraints

- **`aud` é keyword obrigatória** em `sign_state`, `verify_state`, `sign_panel_session` e `verify_panel_session`. Não tem default: um default silenciaria exatamente o erro que este PR existe para tornar impossível.
- **A conferência mora dentro de `verify_*`**, nunca no chamador. O `meta_oauth.py:247` faz a conferência à mão hoje e será migrado — chamador que confere é chamador que pode esquecer.
- **Quatro audiências, exatamente:** `"google_oauth"` (state do callback Google), `"cli_invite"` (convite emitido pelo `admin.py`), `"meta_oauth"` (state do callback Meta, já existente), `"panel"` (cookie de sessão).
- **Este PR desloga todos os gestores.** Decisão registrada na spec: os cookies vivos deixam de valer e todo mundo refaz OAuth. Fluxos de OAuth em voo também quebram, dentro da janela de 10 minutos do state.
- **Comparação de `aud` com `hmac.compare_digest`** não é necessária (o HMAC já foi conferido antes; a audiência não é segredo), mas a conferência tem que vir **depois** da validação de HMAC e **antes** de qualquer uso do payload.
- Nada de segredo em log. A mensagem de recusa diz a audiência **esperada**, nunca o token.
- `mypy --strict` e `ruff` limpos.

---

## Estrutura de arquivos

| arquivo | mudança |
|---|---|
| `src/auth/oauth_state.py` | `aud` obrigatório em `sign_state`/`verify_state`; nova `AudienciaInvalidaError` |
| `src/auth/panel_session.py` | `aud` obrigatório; `manager_id` ausente passa a recusar |
| `src/auth/oauth.py` | 2 `sign_state`, 2 `verify_state`, 1 `sign_panel_session` |
| `src/auth/meta_oauth.py` | 1 `sign_state`, 1 `verify_state`; remove a conferência manual do `:247` |
| `src/scripts/admin.py` | 1 `sign_state` (o convite) |
| `src/web/deps.py` | 1 `verify_panel_session` |
| `tests/unit/test_confusao_de_token.py` (criar) | os testes que provam o furo antes do fix |

---

### Task 1: Provar o furo antes de fechá-lo

**Files:**
- Create: `tests/unit/test_confusao_de_token.py`

**Interfaces:**
- Consumes: `sign_state`, `verify_state` de `src.auth.oauth_state`; `verify_panel_session` de `src.auth.panel_session`.
- Produces: nada — é a prova, e ela vira o guard permanente da invariante.

**Este teste tem que passar AGORA, contra o código atual, porque ele afirma o defeito.** Na Task 2 ele é invertido para afirmar a correção. Escrevê-lo primeiro é o que garante que o fix da Task 2 conserta o que se pensa que conserta — sem ele, o teste do fix poderia estar verde por outro motivo.

- [ ] **Step 1: Escrever o teste que documenta o furo**

```python
# tests/unit/test_confusao_de_token.py
"""C3 — confusão de tipo de token entre state de OAuth e cookie de painel.

Quatro tipos de token compartilham uma chave (`settings.session_signing_key`) e
um formato (`b64url(json).b64url(hmac_sha256)`), e só um carrega claim de
audiência. Medido em 2026-09-06: `verify_panel_session` aceita verbatim o
convite emitido por `admin.py:102`, devolvendo a sessão daquele gestor.
"""

from __future__ import annotations

import time

import pytest

from src.auth.oauth_state import InvalidStateError, sign_state, verify_state
from src.auth.panel_session import InvalidPanelSessionError, verify_panel_session

CHAVE = "chave-de-teste-com-no-minimo-32-caracteres-ok"
GESTOR = "11111111-2222-3333-4444-555555555555"


def test_state_de_oauth_nao_vale_como_cookie_de_painel() -> None:
    """O payload que `admin.py:102` emite como convite não pode virar sessão."""
    convite = sign_state({"manager_id": GESTOR}, CHAVE, aud="cli_invite")
    with pytest.raises(InvalidPanelSessionError):
        verify_panel_session(convite, CHAVE, aud="panel")


def test_cookie_de_painel_nao_vale_como_state_de_oauth() -> None:
    """E o inverso: o cookie não pode ser replayado como state de callback."""
    from src.auth.panel_session import sign_panel_session

    cookie = sign_panel_session(
        manager_id=GESTOR, email="a@v4company.com", signing_key=CHAVE, aud="panel"
    )
    with pytest.raises(InvalidStateError):
        verify_state(cookie, CHAVE, aud="google_oauth")


def test_state_do_google_nao_vale_como_state_do_meta() -> None:
    """As duas audiências de OAuth também são distintas entre si."""
    google = sign_state({"manager_id": GESTOR}, CHAVE, aud="google_oauth")
    with pytest.raises(InvalidStateError):
        verify_state(google, CHAVE, aud="meta_oauth")


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
    with pytest.raises(InvalidStateError):
        verify_state(velho, CHAVE, aud="cli_invite")
    with pytest.raises(InvalidPanelSessionError):
        verify_panel_session(velho, CHAVE, aud="panel")


def test_payload_sem_manager_id_e_recusado() -> None:
    """`panel_session.py:85` devolvia `manager_id=""` em vez de recusar — sessão
    anônima válida é pior que sessão inválida."""
    from src.auth.panel_session import _b64url  # noqa: PLC2701

    sem_id = sign_state({"mode": "panel_login"}, CHAVE, aud="panel")
    assert _b64url  # o import documenta que o formato é o mesmo
    with pytest.raises(InvalidPanelSessionError):
        verify_panel_session(sem_id, CHAVE, aud="panel")
```

- [ ] **Step 2: Rodar para verificar que falha**

Run: `python -m pytest tests/unit/test_confusao_de_token.py -q`
Expected: FAIL — `TypeError: sign_state() got an unexpected keyword argument 'aud'`. É a falha certa: prova que a assinatura ainda não aceita audiência.

- [ ] **Step 3: Registrar o comportamento de HOJE, para a comparação ficar no histórico**

Rode este script e cole a saída no corpo do PR. Ele é a prova do furo contra o código pré-fix, e some assim que a Task 2 entra:

```bash
python -c "
from src.auth.oauth_state import sign_state
from src.auth.panel_session import verify_panel_session
C='chave-de-teste-com-no-minimo-32-caracteres-ok'
t=sign_state({'manager_id':'11111111-2222-3333-4444-555555555555'}, C)
print('verify_panel_session aceitou o convite ->', verify_panel_session(t, C))
"
```
Expected: imprime `PanelSession(manager_id='11111111-...', email='')`.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_confusao_de_token.py
git commit -m "test(auth): prova a confusao de tipo de token antes do fix (C3)"
```

---

### Task 2: `aud` obrigatório em `oauth_state`

**Files:**
- Modify: `src/auth/oauth_state.py:38-80`

**Interfaces:**
- Produces: `sign_state(payload: dict[str, Any], signing_key: str, *, aud: str, issued_at: float | None = None) -> str`; `verify_state(state: str, signing_key: str, *, aud: str) -> dict[str, Any]`. `verify_state` levanta `InvalidStateError` quando `aud` não bate, e **remove `aud` e `iat`** do payload devolvido.

- [ ] **Step 1: Implementar**

```python
def sign_state(
    payload: dict[str, Any],
    signing_key: str,
    *,
    aud: str,
    issued_at: float | None = None,
) -> str:
    """Build a signed state string from a JSON-serializable payload.

    `aud` (audiência) é obrigatório e não tem default. Quatro tipos de token
    deste projeto compartilham chave e formato; sem audiência, qualquer um vale
    como qualquer outro — medido em 2026-09-06, o convite de CLI era aceito
    verbatim como cookie de painel, e o TTL de 10 min virava 24 h no caminho.
    Default aqui silenciaria justamente o erro que a claim existe pra impedir.
    """
    full = dict(payload)
    full["aud"] = aud
    full["iat"] = int(issued_at if issued_at is not None else time.time())
    body = json.dumps(full, sort_keys=True, separators=(",", ":")).encode("utf-8")
    tag = hmac.new(signing_key.encode("utf-8"), body, sha256).digest()
    return f"{_b64url(body)}.{_b64url(tag)}"


def verify_state(state: str, signing_key: str, *, aud: str) -> dict[str, Any]:
    """Verify HMAC + audiência + TTL, return decoded payload. Raises on failure.

    A ordem importa: HMAC primeiro (nada do payload é confiável antes disso),
    audiência depois, TTL por último. A conferência de audiência mora AQUI e
    não no chamador — chamador que confere é chamador que pode esquecer, e foi
    o que aconteceu em três dos quatro tokens.
    """
    try:
        body_b64, tag_b64 = state.split(".", 1)
        body = _b64url_decode(body_b64)
        tag = _b64url_decode(tag_b64)
    except (ValueError, binascii.Error) as e:
        raise InvalidStateError("Malformed state") from e

    expected = hmac.new(signing_key.encode("utf-8"), body, sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise InvalidStateError("HMAC mismatch (tampered or wrong key)")

    try:
        raw_payload: Any = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise InvalidStateError("Payload is not valid JSON") from e

    if not isinstance(raw_payload, dict):
        raise InvalidStateError("Payload is not a dict")

    if raw_payload.get("aud") != aud:
        # Não ecoa o `aud` recebido: a mensagem diz o esperado, nunca o token.
        raise InvalidStateError(f"Audiência inválida (esperada: {aud})")

    iat = raw_payload.get("iat")
    if not isinstance(iat, int):
        raise InvalidStateError("Missing or invalid 'iat'")
    if (time.time() - iat) > STATE_TTL_SECONDS:
        raise InvalidStateError("State expired")

    raw_payload.pop("iat", None)
    raw_payload.pop("aud", None)
    return raw_payload
```

- [ ] **Step 2: Corrigir a docstring do módulo (`oauth_state.py:10-11`)**

Ela afirma defender contra "replay (TTL)". TTL **limita** a janela de replay; não a elimina. Trocar por: `Defende contra CSRF (atacante não forja HMAC) e LIMITA replay a STATE_TTL_SECONDS. A audiência impede que o token valha para outro propósito.`

- [ ] **Step 3: Rodar os testes de audiência do state**

Run: `python -m pytest tests/unit/test_confusao_de_token.py -q -k "meta or ttl"`
Expected: `test_state_do_google_nao_vale_como_state_do_meta` PASSA. Os que envolvem `verify_panel_session` seguem falhando — é a Task 3.

- [ ] **Step 4: Commit**

```bash
git add src/auth/oauth_state.py
git commit -m "fix(auth): aud obrigatorio em sign_state/verify_state (C3)"
```

---

### Task 3: `aud` em `panel_session`, e `manager_id` deixa de ser opcional

**Files:**
- Modify: `src/auth/panel_session.py:42-95`

**Interfaces:**
- Produces: `sign_panel_session(*, manager_id: str, email: str, signing_key: str, aud: str, issued_at: float | None = None) -> str`; `verify_panel_session(cookie: str, signing_key: str, *, aud: str) -> PanelSession`.

- [ ] **Step 1: Implementar**

```python
def sign_panel_session(
    *,
    manager_id: str,
    email: str,
    signing_key: str,
    aud: str,
    issued_at: float | None = None,
) -> str:
    """Build a signed cookie value. `aud` obrigatório — ver oauth_state."""
    payload = {
        "manager_id": manager_id,
        "email": email,
        "aud": aud,
        "iat": int(issued_at if issued_at is not None else time.time()),
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    tag = hmac.new(signing_key.encode("utf-8"), body, sha256).digest()
    return f"{_b64url(body)}.{_b64url(tag)}"


def verify_panel_session(cookie: str, signing_key: str, *, aud: str) -> PanelSession:
    """Verify HMAC + audiência + TTL, return the decoded PanelSession."""
    try:
        body_b64, tag_b64 = cookie.split(".", 1)
        body = _b64url_decode(body_b64)
        tag = _b64url_decode(tag_b64)
    except (ValueError, binascii.Error) as e:
        raise InvalidPanelSessionError("Malformed cookie") from e

    expected = hmac.new(signing_key.encode("utf-8"), body, sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise InvalidPanelSessionError("HMAC mismatch")

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise InvalidPanelSessionError("Bad JSON") from e

    if not isinstance(payload, dict):
        raise InvalidPanelSessionError("Payload is not a dict")

    if payload.get("aud") != aud:
        raise InvalidPanelSessionError(f"Audiência inválida (esperada: {aud})")

    iat = payload.get("iat")
    if not isinstance(iat, int):
        raise InvalidPanelSessionError("Missing iat")
    if (time.time() - iat) > PANEL_SESSION_TTL_SECONDS:
        raise InvalidPanelSessionError("Cookie expired")

    # Antes: `payload.get("manager_id", "")`. Um payload sem manager_id virava
    # sessão com id vazio — sessão anônima VÁLIDA é pior que sessão inválida,
    # porque segue por todo o caminho de autorização parecendo legítima.
    manager_id = payload.get("manager_id")
    email = payload.get("email")
    if not isinstance(manager_id, str) or not manager_id:
        raise InvalidPanelSessionError("Missing manager_id")
    if not isinstance(email, str):
        raise InvalidPanelSessionError("Missing email")

    return PanelSession(manager_id=manager_id, email=email)
```

- [ ] **Step 2: Rodar a suíte de confusão inteira**

Run: `python -m pytest tests/unit/test_confusao_de_token.py -q`
Expected: PASS (5 testes). Se algum ainda falhar, o fix não fecha o furo que o teste descreve — pare e leia qual.

- [ ] **Step 3: Commit**

```bash
git add src/auth/panel_session.py
git commit -m "fix(auth): aud no cookie de painel; manager_id vazio passa a recusar"
```

---

### Task 4: Atualizar os 9 call-sites e migrar a conferência manual do Meta

**Files:**
- Modify: `src/auth/oauth.py` (linhas ~157, ~169, ~185, ~219, ~363)
- Modify: `src/auth/meta_oauth.py` (linhas ~190, ~242, ~247)
- Modify: `src/scripts/admin.py` (linha ~102)
- Modify: `src/web/deps.py` (linha ~42)

**Interfaces:**
- Consumes: as assinaturas novas das Tasks 2 e 3.

Mapa exato — cada linha, com a audiência que recebe:

| arquivo:linha | chamada | audiência |
|---|---|---|
| `oauth.py:157` | `sign_state({"mode": "panel_login"}, …)` | `aud="google_oauth"` |
| `oauth.py:169` | `verify_state(invite, …)` | `aud="cli_invite"` |
| `oauth.py:185` | `sign_state({"manager_id": …}, …)` | `aud="google_oauth"` |
| `oauth.py:219` | `verify_state(state, …)` | `aud="google_oauth"` |
| `oauth.py:363` | `sign_panel_session(…)` | `aud="panel"` |
| `meta_oauth.py:190` | `sign_state({"manager_id":…, "aud":"meta_oauth"}, …)` | passa a `aud="meta_oauth"` como **kwarg**; tirar do dict |
| `meta_oauth.py:242` | `verify_state(state, …)` | `aud="meta_oauth"` |
| `admin.py:102` | `sign_state({"manager_id": …}, …)` | `aud="cli_invite"` |
| `deps.py:42` | `verify_panel_session(cookie, …)` | `aud="panel"` |

- [ ] **Step 1: Aplicar os 9**

Atenção ao `meta_oauth.py:190`: hoje a audiência vai **dentro do dict do payload**. Ela sai de lá e vira kwarg — senão o `sign_state` grava `aud` duas vezes e o dict do chamador vence ou perde por ordem de escrita, o que é ambíguo.

- [ ] **Step 2: Remover a conferência manual do Meta (`meta_oauth.py:247-249`)**

```python
    if payload.get("aud") != "meta_oauth":
        log.warning("meta_oauth_wrong_aud", aud=payload.get("aud"))
        return RedirectResponse("/access-denied?reason=meta_state_invalid", status_code=302)
```

Este bloco **sai**: `verify_state(state, key, aud="meta_oauth")` já levanta `InvalidStateError`, que o `except` logo acima captura e transforma no mesmo redirect. Manter os dois deixaria duas fontes de verdade da mesma regra — o defeito que este PR existe para acabar.

- [ ] **Step 3: Rodar a suíte inteira e consertar os testes que chamavam sem `aud`**

Run: `python -m pytest tests/ -q -x -k "oauth or panel or session or auth"`
Expected: falhas em testes que chamam `sign_state`/`sign_panel_session` sem `aud` — **isso é o esperado**, é a assinatura obrigatória fazendo efeito. Corrija cada um passando a audiência correta. `tests/integration/test_meta_oauth_flow.py:26` já passa `"aud": "meta_oauth"` dentro do dict: mover para kwarg.

- [ ] **Step 4: Grep de garantia — nenhum call-site ficou para trás**

Run:
```bash
grep -rn "sign_state(\|verify_state(\|sign_panel_session(\|verify_panel_session(" --include=*.py src/ tests/
```
Expected: **toda** ocorrência tem `aud=`. Uma sem `aud` seria erro de tipo no mypy, mas o grep é barato e pega chamada dinâmica que o mypy não vê.

- [ ] **Step 5: Rodar o gate inteiro**

Run: `python scripts/check_pre_push.py`
Expected: 6/6. Leia o exit code do próprio processo — nunca o de um `tail` ou `grep` encadeado.

- [ ] **Step 6: Commit**

```bash
git add src/auth/oauth.py src/auth/meta_oauth.py src/scripts/admin.py src/web/deps.py tests/
git commit -m "fix(auth): audiencia nos 9 call-sites; conferencia manual do Meta sai"
```

---

### Task 5: Fecho — registro e aviso operacional

**Files:**
- Modify: `docs/operacao/findings-catalog.md`
- Modify: `docs/operacao/estado-atual.md`

- [ ] **Step 1: Abrir o ID no catálogo**

Sugestão: **F156 — confusão de tipo de token entre state de OAuth e cookie de painel**. Registrar: os quatro tokens, a tabela de qual tinha `aud`, a prova por execução (o convite aceito como cookie e a inversão de TTL de 10 min → 24 h), a escalada medida (`routes.py:487-495`, cookie ⇒ Bearer MCP de até 180 dias) e **o que ficou de fora**: a chave continua única, sem separação de domínio por HKDF — a audiência resolve a confusão, não a partilha de chave.

- [ ] **Step 2: Registrar o aviso operacional no `estado-atual.md`**

Uma linha dizendo que o deploy deste PR **desloga todos os gestores** e que a ação deles é refazer o login em `/`. Sem isso, a primeira pessoa a abrir o painel depois do deploy abre um incidente.

- [ ] **Step 3: Abrir o PR**

```bash
git push -u origin pr1/audiencia-de-token
gh pr create --base main --title "fix(auth): audiencia de token — state de OAuth deixa de valer como sessao" --body "..."
```

No corpo, cole a saída do script do Task 1 Step 3 (a prova contra o código pré-fix) e o aviso do logout. O merge é do Wellington.

---

## Auto-revisão do plano

**Cobertura da spec (PR 1 da seção 4):** `aud` obrigatório nas quatro funções (Tasks 2 e 3) ✓; as quatro audiências nomeadas (Global Constraints) ✓; consequência do logout aceita e comunicada (Task 5, Step 2) ✓; os dois testes exigidos pela spec — confusão e inversão de TTL — são `test_state_de_oauth_nao_vale_como_cookie_de_painel` e `test_ttl_do_state_nao_e_estendido_por_verificacao_de_outra_audiencia` (Task 1) ✓; `panel_session.py:85` recusando payload sem `manager_id` (Task 3) ✓; docstring do TTL corrigida (Task 2, Step 2) ✓.

**Decisão que o plano toma e a spec não detalhava:** a conferência de audiência mora **dentro** de `verify_*`, e a checagem manual do `meta_oauth.py:247` é removida em vez de mantida. Manter as duas seria duas fontes de verdade da mesma regra — o teste 2 de gambiarra do `CLAUDE.md`. O risco é que a remoção altere o caminho de log (hoje há um `meta_oauth_wrong_aud` específico); o `except InvalidStateError` logo acima já loga `meta_oauth_invalid_state`, então a informação não se perde, só deixa de ter um rótulo próprio.

**Consistência de tipos:** `sign_state` e `sign_panel_session` devolvem `str`; `verify_state` devolve `dict[str, Any]` sem `iat` nem `aud`; `verify_panel_session` devolve `PanelSession`. `aud: str` é keyword-only nas quatro. Os nomes das audiências usados na tabela da Task 4 são exatamente os quatro das Global Constraints.

**O que este plano NÃO faz:** não separa a chave por domínio (HKDF), não rotaciona `session_signing_key`, e não mexe no TTL de 180 dias do Bearer MCP (`routes.py:494`) — os três são decisões próprias, e o Bearer de 180 dias merece uma conversa, porque com a audiência no lugar ele deixa de ser alcançável por este caminho mas segue longo.
