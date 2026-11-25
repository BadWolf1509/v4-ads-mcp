# Acesso pela tabela de gestores — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** tirar a trava fixa `@v4company.com` do login, da conexão do Google Ads e do convite, deixando a tabela `managers` como única allowlist.

**Architecture:** `is_allowed_email` (domínio) vira `is_valid_email_shape` (só formato: exatamente um `@`, parte local e domínio não vazios, case-insensitive). Os três pontos de chamada passam a usar o formato; a árvore de decisão do callback (F84, fail-closed, bootstrap, `not_invited`) não muda.

**Tech Stack:** Python 3.13, FastAPI, pytest, respx.

**Spec:** `docs/superpowers/specs/2026-11-24-allowlist-pela-tabela-design.md`

## Global Constraints

- Nenhum e-mail fora da tabela `managers` entra: ausente → `/access-denied?reason=not_invited`.
- `verified_email is False` continua dando 403 no callback.
- Não tocar em migration, secrets de API, MCC/BM.
- Textos em PT-BR. Commits `fix(auth): …` / `docs(…): …`, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Gate antes de commit: `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py` rodado mudo, conferindo `$?`.

## Review Focus

1. E-mail com dois `@` (`a@b@v4company.com`) precisa continuar recusado — dono: Task 1 (caso no parametrize).
2. E-mail de outro domínio **não convidado** precisa dar `not_invited`, não login — dono: Task 1 (`test_callback_gmail_nao_convidado_nao_entra`).
3. Gestor `@gmail.com` desativado continua barrado (F84 não depende do domínio) — dono: Task 1.
4. Convite com e-mail sem `@` ou vazio continua recusado — dono: Task 2.
5. Mudança de maiúsculas (`Wellington.Ribeiro.Eng@Gmail.com`) normaliza igual ao convite — dono: Task 1 (shape é case-insensitive; o callback já faz `lower()`).

---

### Task 1: Trava de formato no lugar da de domínio (login + conexão Ads)

**Files:**
- Modify: `src/auth/domain_check.py` (renomear função; `ALLOWED_DOMAIN` sai)
- Modify: `src/auth/oauth.py:23,71-74,471-478`
- Modify: `src/web/templates/access_denied.html` (ramo `domain` → `email`)
- Modify: `docs/convencoes/nucleo.md:32` (citar `is_valid_email_shape`)
- Modify: `tests/unit/test_nenhuma_regra_se_perdeu.py:97,182` (âncora `is_allowed_email` → `is_valid_email_shape`, piso 1) — **guard editado: justificar no commit** (a regra continua; só o nome da função mudou)
- Test: `tests/unit/test_domain_check.py`, `tests/unit/test_oauth_allowlist.py`, `tests/unit/test_auth_nao_importa_web.py:86-98`, `tests/unit/test_oauth_saidas_antecipadas.py:82-95`

**Interfaces:**
- Produces: `is_valid_email_shape(email: str | None) -> bool` em `src/auth/domain_check.py`. Task 2 usa.

- [ ] **Step 1: Testes que falham contra o código atual**
  - `test_domain_check.py`: parametrize de `is_valid_email_shape` com `("wellington.ribeiro.eng@gmail.com", True)`, `("a@v4company.com", True)`, `("A@GMAIL.COM", True)`, `("two@signs@x.com", False)`, `("", False)`, `(None, False)`, `("nodomain", False)`, `("@x.com", False)`, `("a@", False)`.
  - `test_oauth_allowlist.py`: substituir `test_callback_rejects_non_v4_domain` por
    - `test_callback_gmail_convidado_promove`: `email="wellington.ribeiro.eng@gmail.com"`, manager `{"status": "invited", "is_active": True}` → `kind == "login"`, `action == "promote_invited"`.
    - `test_callback_gmail_nao_convidado_nao_entra`: `existing_manager=None`, tabela não vazia → `location == "/access-denied?reason=not_invited"`.
    - `test_callback_gmail_desativado_barrado`: manager `{"status": "active", "is_active": False}` → `location == "/access-denied?reason=deactivated"`.
    - `test_callback_formato_invalido`: `email="a@b@v4company.com"` → `location == "/access-denied?reason=email"`.
  - `test_auth_nao_importa_web.py`: `("a@sub.v4company.com", ("login", None))`, `("a@b@v4company.com", ("redirect", "/access-denied?reason=email"))`; atualizar o comentário.
  - `test_oauth_saidas_antecipadas.py`: `test_dominio_nao_autorizado_devolve_403` vira `test_email_mal_formado_devolve_403` com `{"email": "a@b@outro.com", "verified_email": True}` → 403, `"a@b@outro.com" in resp.text`, `"inválido" in resp.text`, mesmas asserções de conexão/cookie/nonce. Acrescentar `test_gmail_verificado_passa_da_trava`: `{"email": "alguem@gmail.com", "verified_email": True}` em `mode=panel_login`. **Antes de escrever a asserção, rode o fluxo e registre a saída real** (esperado: redirect para `/access-denied?reason=not_invited`, porque `alguem` não está no `_Banco`); asserte essa saída exata, não `!= 403`.

- [ ] **Step 2: Rodar e ver falhar pelo motivo certo**
  Run: `D:/v4-ads-mcp/.venv/Scripts/python.exe -m pytest tests/unit/test_domain_check.py tests/unit/test_oauth_allowlist.py tests/unit/test_auth_nao_importa_web.py tests/unit/test_oauth_saidas_antecipadas.py -q`
  Expected: FAIL — `ImportError: is_valid_email_shape` e `reason=domain` onde se espera `login`/`not_invited`. Leia QUAL linha falhou.

- [ ] **Step 3: Implementar**
  - `is_valid_email_shape` com o parse que hoje está em `is_allowed_email`, sem a comparação de domínio.
  - `decide_callback` passo 1: `if not is_valid_email_shape(email_norm): redirect "/access-denied?reason=email"`; comentário atualizado (a allowlist é a tabela).
  - `oauth.py:471`: mesma função; texto `f"O e-mail {google_email} é inválido."`, status 403.
  - `access_denied.html`: ramo `reason == "email"` com título "E-mail inválido." e texto "O Google devolveu um e-mail que não conseguimos ler. Tente de novo ou fale com o admin." O ramo `domain` sai.
  - `nucleo.md:32` e âncora do ratchet: trocar o nome.

- [ ] **Step 4: Verde**
  Mesmo comando do Step 2 + `tests/unit/test_nenhuma_regra_se_perdeu.py`. Expected: PASS.
  Sabotagem: volte temporariamente a comparação de domínio dentro de `is_valid_email_shape` (edição, nunca `git checkout`), confirme que `test_callback_gmail_convidado_promove` e `test_gmail_verificado_passa_da_trava` ficam vermelhos, desfaça.

- [ ] **Step 5: Commit** `fix(auth): login e conexão Ads deixam de exigir @v4company.com; a tabela de gestores é a allowlist`

### Task 2: Convite aceita qualquer domínio + bootstrap

**Files:**
- Modify: `src/web/routes/admin_invites.py:38,84-85`
- Modify: `src/web/routes/_shared.py:40`
- Modify: `.github/workflows/deploy.yml:212` (`BOOTSTRAP_ADMIN_EMAILS=wellington.ribeiro.eng@gmail.com`)
- Test: `tests/integration/test_web_panel_admin.py:970-980` + teste novo no mesmo arquivo

**Interfaces:**
- Consumes: `is_valid_email_shape` (Task 1).

- [ ] **Step 1: Testes que falham**
  - `test_admin_invites_aceita_gmail` (integration): POST `/admin/invites/new` com `email="Novo.Gestor@Gmail.com"` como admin → 303 sem `error=`; linha em `managers` com `email == "novo.gestor@gmail.com"`, `status == "invited"`.
  - `test_admin_invites_recusa_email_mal_formado`: `email="sem-arroba"` → redirect `/admin/invites?error=bad_email`; nenhuma linha criada.
  - Flash: `?error=bad_email` mostra `"E-mail inválido."`; remover a asserção de `bad_domain`.

- [ ] **Step 2: Falhar** — `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push_full.py` (precisa do Docker). Expected: os dois novos vermelhos por `bad_domain`.

- [ ] **Step 3: Implementar** — `if not is_valid_email_shape(email): redirect ?error=bad_email`; `_shared.py`: chave `bad_email` → `"E-mail inválido."` (`bad_domain` sai); texto da mensagem de convite (linha 38): `f"1. Acessa {panel_url}/login e entra com o email que recebeu este convite"` (a função não recebe o e-mail; não acrescente parâmetro; se algum teste fixa o texto antigo, atualize-o); `deploy.yml`.

- [ ] **Step 4: Verde** — full sweep. Expected: PASS. Sabotagem: restaure o `endswith` (edição), confirme `test_admin_invites_aceita_gmail` vermelho, desfaça.

- [ ] **Step 5: Commit** `fix(admin): convite aceita qualquer domínio; bootstrap passa ao Gmail`

### Fecho (sem código)

- Gate + full sweep verdes; PR único. **Merge e deploy só com aval nominal do Wellington.**
- Prova pós-deploy (definição de pronto): login real do Gmail convidado em produção.
- `estado-atual.md`: registrar a mudança e os passos operacionais do spec (convite → `bootstrap-admin` → OAuth Ads → desativação dos 4).
