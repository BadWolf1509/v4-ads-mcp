# Frontend Improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir dois bugs de layout confirmados em produção, aposentar o Tailwind Play CDN (407 KB de JS render-blocking → 12 KB de CSS estático), comprimir/cachear os assets e fechar as lacunas de acessibilidade do painel.

**Architecture:** Nenhuma mudança de arquitetura. O painel continua Jinja2 + HTMX + CSS próprio, sem build step no runtime. O Tailwind passa a ser **gerado offline** pelo CLI oficial (v3.4.17, via `npx`) e commitado como `src/web/static/v4-tailwind.css`; um guard no CI regenera e faz `git diff --exit-code` pra impedir drift. As cores do `tailwind.config.js` apontam pra `var(--v4-*)`, então `v4-tokens.css` vira a única fonte de verdade.

**Tech Stack:** Jinja2 · HTMX 2.0.3 · Tailwind CSS 3.4.17 (CLI offline) · FastAPI/Starlette · pytest

## Global Constraints

- **Nenhum build step no runtime nem no deploy.** O CSS do Tailwind é gerado na máquina do dev e **commitado**. O CI só *verifica* que está atualizado. Nada de node/Vite/React em `pyproject.toml` ou no buildpack.
- **Versão do Tailwind fixada em `3.4.17`** — é exatamente a versão que o Play CDN serve hoje. Não subir pra v4 (config CSS-first, quebra tudo).
- **ORDEM DA CASCATA É CRÍTICA.** O Play CDN injeta seu `<style>` **no fim do `<head>`**, depois dos quatro `<link>` do v4. Verificado em produção: `h1` sem classe = `14px/400/margin 0` (Preflight ganha), **não** os `36px/800` que `v4-base.css:17` declara. O `v4-tailwind.css` DEVE ser o **último** stylesheet do `<head>`. Inverter a ordem faz todo heading do painel saltar de 14px pra 36px.
- **Qualquer recurso externo novo exige atualizar `_CSP_POLICY`** no mesmo commit (`src/web/middleware.py`).
- **Gzip NÃO pode ser aplicado a `/mcp`** — é `StreamableHTTPServerTransport` (SSE); compressão com buffering quebra o streaming.
- Copy em **PT-BR**, sentence case.
- Verificação antes de cada commit: `python scripts/check_pre_push.py`.

---

### Task 1: P0 — hambúrguer fantasma e marca deslocada no mobile

Dois defeitos confirmados em produção a 375px: o botão de menu aparece **deslogado** e abre uma gaveta com 0 links (além de travar o scroll do `body`), e a marca é empurrada pro canto direito (hambúrguer em x=16–52, marca em x=241–359).

**Files:**
- Modify: `src/web/templates/_base.html:46-52` (hambúrguer), `:75-103` (drawer), `:105-114` (script)
- Modify: `src/web/static/v4-base.css:175-179` (media query mobile)
- Test: `tests/integration/test_web_panel_login.py`

**Interfaces:**
- Produces: nenhuma interface nova. Task 3 reescreve a mesma região do `<header>`/drawer — execute na ordem.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/integration/test_web_panel_login.py`:

```python
@pytest.mark.integration
async def test_login_nao_renderiza_hamburguer_nem_drawer(client):
    """Deslogado nao existe navegacao — o botao abria uma gaveta vazia e travava o scroll."""
    resp = await client.get("/login")
    assert resp.status_code == 200
    assert "v4-header__hamburger" not in resp.text
    assert 'id="mobile-drawer"' not in resp.text
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `pytest tests/integration/test_web_panel_login.py::test_login_nao_renderiza_hamburguer_nem_drawer -v`
Expected: FAIL — hoje ambos são renderizados sem condição.

- [ ] **Step 3: Condicionar hambúrguer e drawer a `current_user`**

Em `_base.html`, mover o `<button class="v4-header__hamburger">` pra dentro de um `{% if current_user %}` (a marca continua sempre visível):

```html
<header class="v4-header">
  {% if current_user %}
  <button class="v4-header__hamburger" type="button" aria-label="Abrir menu" aria-controls="mobile-drawer" aria-expanded="false" onclick="toggleDrawer()">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h16M4 12h16M4 18h16"/></svg>
  </button>
  {% endif %}
  <a class="v4-header__brand" href="/">
```

E envolver todo o bloco `<div id="mobile-drawer" …>…</div>` (linhas 75-103) em `{% if current_user %}…{% endif %}`, removendo o `{% if current_user %}` interno que hoje envolve só o conteúdo do painel.

- [ ] **Step 4: Proteger `toggleDrawer` contra drawer ausente**

Em `_base.html`, primeira linha do corpo da função:

```js
function toggleDrawer() {
  const drawer = document.getElementById('mobile-drawer');
  if (!drawer) return;
  const isOpen = drawer.classList.toggle('is-open');
```

- [ ] **Step 5: Corrigir a posição da marca no mobile**

Em `v4-base.css`, dentro da media query existente `@media (max-width: 767px)` (linha 175). O `justify-content: space-between` do header com só dois filhos visíveis joga a marca pra direita; `margin-right: auto` a ancora ao lado do hambúrguer. **Só no mobile** — no desktop a distribuição atual (marca / nav / usuário) deve permanecer intacta:

```css
@media (max-width: 767px) {
  .v4-header__hamburger { display: block; }
  .v4-header__nav { display: none; }
  .v4-header__user { display: none; }
  .v4-header__brand { margin-right: auto; }
}
```

- [ ] **Step 6: Rodar o teste e a suíte**

Run: `pytest tests/integration/test_web_panel_login.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/web/templates/_base.html src/web/static/v4-base.css tests/integration/test_web_panel_login.py
git commit -m "fix(web): esconder hamburguer/drawer deslogado e ancorar marca no mobile"
```

---

### Task 2: Acessibilidade — reduced motion, skip link, foco e contraste

Quatro lacunas medidas: **0** regras `prefers-reduced-motion` contra **3** animações infinitas; sem skip link (nav de 6 itens antes do conteúdo em toda página); foco só em `.v4-input`/`.v4-textarea` (3 ocorrências de `:focus` em 1100 linhas); e `--v4-gray-300` (#b3b3b3) usado como **texto** = **2,1:1**, violando a regra escrita pela própria equipe em 07-04.

**Files:**
- Modify: `src/web/static/v4-motion.css` (bloco reduced-motion no fim)
- Modify: `src/web/static/v4-tokens.css` (tokens de texto acessível)
- Modify: `src/web/static/v4-base.css` (skip link + `:focus-visible`)
- Modify: `src/web/static/v4-components.css:91-94` (badges), `:315-319` (alert), `:500` (toast)
- Modify: `src/web/templates/_base.html` (skip link, `<main id>`, toast roles)
- Modify: `src/web/templates/help.html:342-344`, `:356-364`
- Test: `tests/unit/test_frontend_a11y_guards.py` (novo)

**Interfaces:**
- Produces: tokens `--v4-gold-text`, `--v4-green-text`, `--v4-focus-color`; classe `.v4-skip-link`; âncora `#conteudo` em `<main>`.

- [ ] **Step 1: Escrever os guards que falham**

Novo arquivo `tests/unit/test_frontend_a11y_guards.py`. Guards grep-based seguem o padrão de `tests/unit/test_structural_guards.py` — impedem reincidência sem precisar de browser:

```python
"""Guards de acessibilidade do painel (grep-based, espelha test_structural_guards)."""

from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "web" / "static"
_TEMPLATES = Path(__file__).resolve().parents[2] / "src" / "web" / "templates"


def test_motion_css_respeita_prefers_reduced_motion():
    """3 animacoes infinitas no design system exigem um opt-out."""
    css = (_STATIC / "v4-motion.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion: reduce" in css


def test_base_define_focus_visible():
    """Foco visivel por teclado nao pode depender do default do browser."""
    css = (_STATIC / "v4-base.css").read_text(encoding="utf-8")
    assert ":focus-visible" in css


def test_base_tem_skip_link_ancorado_no_main():
    html = (_TEMPLATES / "_base.html").read_text(encoding="utf-8")
    assert 'href="#conteudo"' in html
    assert 'id="conteudo"' in html


@pytest.mark.parametrize("arquivo", ["v4-components.css", "v4-base.css"])
def test_gray_300_nunca_usado_como_cor_de_texto(arquivo):
    """#b3b3b3 = 2,1:1 sobre branco. So vale pra border e texto sobre fundo escuro."""
    for linha in (_STATIC / arquivo).read_text(encoding="utf-8").splitlines():
        limpa = linha.strip()
        if limpa.startswith("color:") and "--v4-gray-300" in limpa:
            pytest.fail(f"{arquivo}: gray-300 como texto -> {limpa}")


def test_help_nao_usa_gray_300_como_texto():
    html = (_TEMPLATES / "help.html").read_text(encoding="utf-8")
    for linha in html.splitlines():
        limpa = linha.strip()
        if limpa.startswith("color:") and "--v4-gray-300" in limpa:
            pytest.fail(f"help.html: gray-300 como texto -> {limpa}")
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `pytest tests/unit/test_frontend_a11y_guards.py -v`
Expected: FAIL — 5 dos 6 falham (reduced-motion, focus-visible, skip link, help.html).

- [ ] **Step 3: Adicionar o bloco reduced-motion**

No **fim** de `v4-motion.css`. O `!important` garante que vence independente da ordem de carga do `v4-tailwind.css`:

```css
/* Respeita "reduzir movimento" do SO (WCAG 2.3.3). Cobre as animacoes
   infinitas (v4-pulse, v4-skeleton-shimmer, v4-btn-spin), o drawer, os
   toasts e os utilitarios de transicao do Tailwind. */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

- [ ] **Step 4: Adicionar tokens de texto acessível**

Em `v4-tokens.css`, logo abaixo do bloco "Soft backgrounds":

```css
  /* Texto sobre os fundos soft — hex proprio porque --v4-gold/--v4-green
     puros reprovam em contraste sobre eles (gold: 3,8:1). Medido sobre o
     fundo soft composto: gold-text 4,9:1 · green-text 7,3:1 (AA >= 4.5:1). */
  --v4-gold-text:  #8a6500;
  --v4-green-text: #1a5b22;

  /* Foco por teclado */
  --v4-focus-color: var(--v4-red);
```

- [ ] **Step 5: Aplicar os tokens nos componentes**

Em `v4-components.css`, trocar os hexes hardcoded (que já eram drift de token):

```css
.v4-badge--success { background: rgba(82, 204, 90, 0.15); color: var(--v4-green-text); }
.v4-badge--warning { background: rgba(255, 192, 42, 0.15); color: var(--v4-gold-text); }
```

E em `.v4-alert--success` (linha ~318) trocar `color: #1a5b22;` por `color: var(--v4-green-text);`; em `.v4-toast--success` (linha ~500) trocar `background: #1a5b22;` por `background: var(--v4-green-text);`.

- [ ] **Step 6: Corrigir o contraste em `help.html`**

Trocar as duas ocorrências de `color: var(--v4-gray-300);` por `color: var(--v4-gray-500);` — `.v4-help__faq-arrow` (~linha 343) e `.v4-help__topo` (~linha 361).

- [ ] **Step 7: Skip link + foco visível**

Em `v4-base.css`, logo depois do bloco `main { … }`:

```css
/* Skip link — visivel so quando recebe foco por teclado */
.v4-skip-link {
  position: absolute;
  left: -9999px;
  top: 0;
  z-index: calc(var(--v4-z-modal) + 1);
  background: var(--v4-gray-900);
  color: var(--v4-white);
  padding: var(--v4-space-3) var(--v4-space-4);
  font-weight: 600;
  border-radius: 0 0 var(--v4-radius-md) 0;
}
.v4-skip-link:focus {
  left: 0;
  color: var(--v4-white);
  text-decoration: none;
}

/* Foco por teclado — token unico. Inputs ja tem anel proprio (:focus). */
:focus-visible {
  outline: 2px solid var(--v4-focus-color);
  outline-offset: 2px;
}
.v4-input:focus-visible,
.v4-select:focus-visible,
.v4-textarea:focus-visible {
  outline: none;
}
```

Em `_base.html`, primeiro elemento dentro de `<body>`:

```html
<body>
  <a class="v4-skip-link" href="#conteudo">Pular para o conteúdo</a>
```

E trocar `<main>` por `<main id="conteudo" tabindex="-1">`.

- [ ] **Step 8: Corrigir o anúncio dos toasts**

Em `_base.html`: remover `aria-atomic="true"` da `.v4-toast-region` (com `atomic` o leitor de tela re-anuncia a fila inteira a cada toast). E dar o papel certo por tipo dentro de `showToast`:

```js
  function showToast(message, kind) {
    kind = kind || 'success';
    const region = document.getElementById('v4-toast-region');
    const toast = document.createElement('div');
    toast.className = 'v4-toast v4-toast--' + kind;
    toast.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    toast.textContent = message;
```

- [ ] **Step 9: Rodar os guards e a suíte**

Run: `pytest tests/unit/test_frontend_a11y_guards.py -v && python scripts/check_pre_push.py`
Expected: 6 PASS + suíte verde.

- [ ] **Step 10: Commit**

```bash
git add src/web/static tests/unit/test_frontend_a11y_guards.py src/web/templates/_base.html src/web/templates/help.html
git commit -m "feat(web): reduced-motion, skip link, token de foco e contraste AA"
```

---

### Task 3: Navegação única + `aria-current` no drawer + foco contido

A nav existe duplicada (header + drawer) e é sincronizada à mão; o drawer não marca a página atual, então no mobile não dá pra saber onde você está. O drawer também não devolve o foco ao fechar nem impede o Tab de vazar pro conteúdo atrás.

**Files:**
- Modify: `src/web/templates/_base.html:54-126`
- Test: `tests/integration/test_web_panel_sessions.py`

**Interfaces:**
- Consumes: o `<header>`/drawer condicionados na Task 1.
- Produces: variável Jinja `nav_items` (lista de `{href, label, match}`), consumida pelo header e pelo drawer no mesmo template.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/integration/test_web_panel_sessions.py`:

```python
@pytest.mark.integration
async def test_drawer_marca_pagina_atual(client, seeded_manager_cookie):
    """No mobile o unico indicador de 'onde estou' e o aria-current do drawer."""
    resp = await client.get("/sessions", cookies=seeded_manager_cookie)
    assert resp.status_code == 200
    drawer = resp.text.split('id="mobile-drawer"', 1)[1].split("</div>", 1)[0]
    assert 'aria-current="page"' in drawer
```

> Use a fixture de sessão autenticada já existente no arquivo; se o nome diferir de `seeded_manager_cookie`, adote o do arquivo.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `pytest tests/integration/test_web_panel_sessions.py::test_drawer_marca_pagina_atual -v`
Expected: FAIL — o drawer não emite `aria-current`.

- [ ] **Step 3: Declarar a nav uma vez só**

No topo do `<body>` em `_base.html`, antes do `<header>`. `match` = `exact` ou `prefix`:

```jinja
{% set nav_items = [
  {"href": "/",         "label": "Dashboard", "match": "exact"},
  {"href": "/accounts", "label": "Contas",    "match": "exact"},
  {"href": "/sessions", "label": "Sessões",   "match": "prefix"},
  {"href": "/audit",    "label": "Auditoria", "match": "prefix"},
  {"href": "/help",     "label": "Ajuda",     "match": "exact"},
] %}
{% if current_user and current_user.is_admin %}
  {% set nav_items = nav_items + [{"href": "/admin", "label": "Admin", "match": "prefix"}] %}
{% endif %}
{% macro is_current(item) -%}
  {%- if item.match == "prefix" -%}
    {{ request.url.path.startswith(item.href) }}
  {%- else -%}
    {{ request.url.path == item.href }}
  {%- endif -%}
{%- endmacro %}
```

- [ ] **Step 4: Renderizar header e drawer a partir da lista**

Substituir o `<nav class="v4-header__nav">` por:

```jinja
<nav class="v4-header__nav">
  {% for item in nav_items %}
  <a href="{{ item.href }}" {% if is_current(item)|trim == "True" %}aria-current="page"{% endif %}>{{ item.label }}</a>
  {% endfor %}
</nav>
```

E a primeira `.v4-drawer__section` por:

```jinja
<div class="v4-drawer__section">
  {% for item in nav_items %}
  <a href="{{ item.href }}" class="v4-drawer__link" {% if is_current(item)|trim == "True" %}aria-current="page"{% endif %}>{{ item.label }}</a>
  {% endfor %}
</div>
```

A seção "Admin" do drawer (links de subpáginas: Visão geral, Gestores, Convites, Contas, Acessos, Auditoria global) **permanece como está** — é um sub-menu, não a nav principal.

- [ ] **Step 5: Estilo do item ativo no drawer**

Em `v4-base.css`, junto de `.v4-drawer__link`:

```css
.v4-drawer__link[aria-current="page"] {
  color: var(--v4-red);
  font-weight: 600;
}
```

- [ ] **Step 6: Devolver o foco e conter o Tab**

Em `toggleDrawer()`, substituir o corpo pós-`if (!drawer) return;`:

```js
  const isOpen = drawer.classList.toggle('is-open');
  drawer.setAttribute('aria-hidden', String(!isOpen));
  document.querySelector('.v4-header__hamburger')?.setAttribute('aria-expanded', String(isOpen));
  document.body.style.overflow = isOpen ? 'hidden' : '';
  // Contem o Tab: o resto da pagina fica inerte enquanto a gaveta esta aberta.
  for (const el of [document.querySelector('header'), document.querySelector('main'), document.querySelector('footer')]) {
    if (el) el.inert = isOpen;
  }
  if (isOpen) {
    window._v4DrawerReturnFocus = document.activeElement;
    document.querySelector('.v4-drawer__panel a, .v4-drawer__panel button')?.focus();
  } else {
    window._v4DrawerReturnFocus?.focus();
    window._v4DrawerReturnFocus = null;
  }
```

- [ ] **Step 7: Rodar o teste e a suíte**

Run: `pytest tests/integration/test_web_panel_sessions.py -v && python scripts/check_pre_push.py`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/web/templates/_base.html src/web/static/v4-base.css tests/integration/test_web_panel_sessions.py
git commit -m "feat(web): nav unica com aria-current no drawer e foco contido"
```

---

### Task 4: Aposentar o Tailwind Play CDN

Medido em produção: **407 KB** de JS (123 KB gzip), render-blocking (sem `defer`, ao contrário do htmx), **423 ms**, pra injetar **7 KB** de CSS em runtime. `domContentLoaded` do `/login` = **1128 ms**. O CLI offline gera o equivalente em **12,3 KB minificado / 3,3 KB gzip** e permite remover `'unsafe-eval'` da CSP.

**Files:**
- Create: `tailwind.config.js`, `scripts/tailwind-input.css`, `scripts/build_tailwind.py`
- Create (gerado, commitado): `src/web/static/v4-tailwind.css`
- Modify: `src/web/templates/_base.html:8-41` (trocar script por link), `src/web/static/v4-base.css:17-22` (comentário de cascata)
- Modify: `src/web/middleware.py:15-33` (CSP)
- Modify: `.github/workflows/ci.yml` (guard)
- Test: `tests/unit/test_frontend_a11y_guards.py` (adicionar guards de cascata/CSP)

**Interfaces:**
- Consumes: `src/web/templates/**/*.html` como content glob.
- Produces: `/static/v4-tailwind.css`, **último** `<link>` do `<head>`.

- [ ] **Step 1: Escrever os guards que falham**

Adicionar em `tests/unit/test_frontend_a11y_guards.py`:

```python
def test_sem_tailwind_play_cdn():
    """O Play CDN compila em runtime e exige 'unsafe-eval'. CSS e gerado offline."""
    html = (_TEMPLATES / "_base.html").read_text(encoding="utf-8")
    assert "cdn.tailwindcss.com" not in html


def test_csp_sem_unsafe_eval():
    mw = (Path(__file__).resolve().parents[2] / "src" / "web" / "middleware.py").read_text(encoding="utf-8")
    assert "unsafe-eval" not in mw
    assert "cdn.tailwindcss.com" not in mw


def test_tailwind_e_o_ultimo_stylesheet():
    """CRITICO: o Preflight tem que continuar vencendo v4-base.css.

    Hoje o Play CDN injeta seu <style> no fim do <head>, entao h1 sem classe
    e 14px/400 (Preflight), nao os 36px/800 de v4-base.css. Carregar o CSS
    gerado ANTES dos v4-*.css inverte isso e estoura todo heading do painel.
    """
    html = (_TEMPLATES / "_base.html").read_text(encoding="utf-8")
    hrefs = re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', html)
    locais = [h for h in hrefs if h.startswith("/static/")]
    assert locais, "nenhum stylesheet local encontrado"
    assert "v4-tailwind.css" in locais[-1], f"v4-tailwind.css precisa ser o ultimo: {locais}"
```

Adicionar `import re` no topo do arquivo.

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `pytest tests/unit/test_frontend_a11y_guards.py -k "tailwind or csp" -v`
Expected: 3 FAIL.

- [ ] **Step 3: Criar o config**

`tailwind.config.js` na raiz. As cores apontam pra `var(--v4-*)` — isso elimina a duplicação de tokens que o CLAUDE.md hoje documenta como sync manual. Seguro porque **nenhuma template usa opacity modifier** (`bg-v4-red/50`), que é o único caso em que `var()` sem `<alpha-value>` quebraria:

```js
/** Tailwind 3.4.17 — gerado offline por scripts/build_tailwind.py.
 *  NAO ha build step no runtime: o CSS resultante e commitado em
 *  src/web/static/v4-tailwind.css e o CI faz diff pra impedir drift.
 *  Cores referenciam as custom properties de v4-tokens.css (fonte unica). */
module.exports = {
  content: ['./src/web/templates/**/*.html'],
  theme: {
    extend: {
      colors: {
        'v4-red': {
          DEFAULT: 'var(--v4-red)',
          medium: 'var(--v4-red-medium)',
          dark: 'var(--v4-red-dark)',
          soft: 'var(--v4-red-soft)',
        },
        'v4-gray': {
          50: 'var(--v4-gray-50)',
          100: 'var(--v4-gray-100)',
          200: 'var(--v4-gray-200)',
          300: 'var(--v4-gray-300)',
          500: 'var(--v4-gray-500)',
          700: 'var(--v4-gray-700)',
          800: 'var(--v4-gray-800)',
          900: 'var(--v4-gray-900)',
        },
        'v4-green': { DEFAULT: 'var(--v4-green)', soft: 'var(--v4-green-soft)' },
        'v4-gold': { DEFAULT: 'var(--v4-gold)', soft: 'var(--v4-gold-soft)' },
      },
      fontFamily: {
        sans: ['Montserrat', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Consolas', 'monospace'],
      },
      fontSize: {
        display: ['56px', { lineHeight: '1.0', letterSpacing: '-0.025em' }],
      },
      transitionTimingFunction: {
        'v4-out': 'cubic-bezier(0.2, 0.8, 0.2, 1)',
        'v4-spring': 'cubic-bezier(0.34, 1.56, 0.64, 1)',
      },
    },
  },
}
```

`scripts/tailwind-input.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 4: Criar o gerador**

`scripts/build_tailwind.py` — espelha o estilo de `scripts/check_pre_push.py`:

```python
"""Gera src/web/static/v4-tailwind.css a partir das templates.

Roda o CLI oficial do Tailwind via npx (node so na maquina do dev e no CI —
o runtime e o buildpack nao veem node). O CSS gerado e COMMITADO; o CI
regenera e faz `git diff --exit-code` pra impedir drift silencioso.

Uso: python scripts/build_tailwind.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

TAILWIND_VERSION = "3.4.17"  # a versao que o Play CDN servia — nao subir pra v4
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src" / "web" / "static" / "v4-tailwind.css"


def main() -> int:
    npx = shutil.which("npx")
    if npx is None:
        print("npx nao encontrado. Instale Node LTS pra regenerar o CSS.", file=sys.stderr)
        return 1

    cmd = [
        npx, "--yes", f"tailwindcss@{TAILWIND_VERSION}",
        "-c", str(ROOT / "tailwind.config.js"),
        "-i", str(ROOT / "scripts" / "tailwind-input.css"),
        "-o", str(OUTPUT),
        "--minify",
    ]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return proc.returncode

    print(f"OK: {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Gerar o CSS**

Run: `python scripts/build_tailwind.py`
Expected: `OK: src\web\static\v4-tailwind.css (~12350 bytes)`

Conferir que o Preflight veio junto (é ele que domina a cascata hoje):

```bash
grep -c "font-size:inherit;font-weight:inherit" src/web/static/v4-tailwind.css
```
Expected: `1`

- [ ] **Step 6: Trocar o script pelo link**

Em `_base.html`, remover as linhas 15-41 (o `<script src="https://cdn.tailwindcss.com">` e todo o bloco `tailwind.config = {…}`) e adicionar o `<link>` **depois** de `v4-motion.css`, como último stylesheet:

```html
  <link rel="stylesheet" href="/static/v4-tokens.css">
  <link rel="stylesheet" href="/static/v4-base.css">
  <link rel="stylesheet" href="/static/v4-components.css">
  <link rel="stylesheet" href="/static/v4-motion.css">
  <!-- POR ULTIMO: o Preflight do Tailwind precisa vencer v4-base.css, como
       fazia o <style> que o Play CDN injetava no fim do <head>. Inverter a
       ordem faz todo heading sem classe saltar de 14px pra 36px. -->
  <link rel="stylesheet" href="/static/v4-tailwind.css">
```

- [ ] **Step 7: Documentar a cascata em `v4-base.css`**

Acima do bloco `h1 { … }` (linha 17) — essas regras são sobrescritas pelo Preflight e um dev que leia só este arquivo assumiria o contrário:

```css
/* ATENCAO: o Preflight do Tailwind (v4-tailwind.css, carregado por ultimo)
   reseta h1-h6 pra font-size/font-weight: inherit e zera as margens. Na
   pratica estas regras NAO valem para headings sem classe utilitaria — o
   tamanho vem de classes como `text-4xl font-extrabold` nas templates.
   Mantidas como fallback caso o Tailwind seja removido. */
```

- [ ] **Step 8: Enxugar a CSP**

Em `src/web/middleware.py`, atualizar o inventário no comentário e a policy. Sai `cdn.tailwindcss.com` e sai `'unsafe-eval'` (era exigido só pelo compilador em runtime do Play CDN). `'unsafe-inline'` **permanece** — os 28 `onclick=` das templates ainda dependem dele:

```python
#   - https://unpkg.com            → script (htmx.org@2.0.3, SRI-pinned)
#   - https://fonts.bunny.net      → stylesheet + font files
# O Tailwind deixou de ser CDN em 2026-08-11: o CSS e gerado offline
# (scripts/build_tailwind.py) e servido de /static, o que permitiu remover
# 'unsafe-eval'. 'unsafe-inline' segue necessario pelos onclick inline.
_CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.bunny.net; "
    "font-src 'self' https://fonts.bunny.net; "
    "img-src 'self' data:; "
    "connect-src 'self'"
)
```

- [ ] **Step 9: Guard no CI**

Em `.github/workflows/ci.yml`, no job `test`, depois do passo "Format check (ruff)":

```yaml
      - name: Tailwind CSS esta atualizado
        run: |
          python scripts/build_tailwind.py
          git diff --exit-code src/web/static/v4-tailwind.css \
            || (echo "::error::v4-tailwind.css desatualizado. Rode 'python scripts/build_tailwind.py' e commite." && exit 1)
```

`ubuntu-latest` já traz Node, então `npx` funciona sem `setup-node`.

- [ ] **Step 10: Verificar e commitar**

Run: `pytest tests/unit/test_frontend_a11y_guards.py -v && python scripts/check_pre_push.py`
Expected: todos PASS

```bash
git add tailwind.config.js scripts/tailwind-input.css scripts/build_tailwind.py \
        src/web/static/v4-tailwind.css src/web/templates/_base.html \
        src/web/static/v4-base.css src/web/middleware.py \
        .github/workflows/ci.yml tests/unit/test_frontend_a11y_guards.py
git commit -m "perf(web): aposentar Tailwind Play CDN (407KB JS -> 12KB CSS) e remover unsafe-eval"
```

---

### Task 5: Compressão e cache dos assets

Medido: `transferSize ≈ decodedBodySize` nos quatro CSS (**sem compressão**) e **nenhum `Cache-Control`** — só `etag`, então toda navegação revalida todos os assets. Cache-busting via `K_REVISION` (o Cloud Run troca a cada deploy), o que torna `immutable` seguro.

**Files:**
- Create: `src/web/static_files.py`
- Modify: `src/web/middleware.py` (gzip com exclusão de `/mcp`)
- Modify: `src/app.py:79-98`
- Modify: `src/web/routes.py` (global `asset_version` no Jinja)
- Modify: `src/web/templates/_base.html` (querystring de versão)
- Test: `tests/integration/test_web_static_caching.py` (novo)

**Interfaces:**
- Produces: `CachedStaticFiles`, `SelectiveGZipMiddleware`, global Jinja `asset_version`.

- [ ] **Step 1: Escrever o teste que falha**

`tests/integration/test_web_static_caching.py`:

```python
"""Assets estaticos: compressao + cache. Medido em prod 2026-08-11 como ausentes."""

import pytest


@pytest.mark.integration
async def test_static_tem_cache_control_imutavel(client):
    resp = await client.get("/static/v4-tokens.css")
    assert resp.status_code == 200
    assert "immutable" in resp.headers["cache-control"]
    assert "max-age=31536000" in resp.headers["cache-control"]


@pytest.mark.integration
async def test_html_e_comprimido(client):
    resp = await client.get("/login", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") == "gzip"


@pytest.mark.integration
async def test_mcp_nao_e_comprimido(client):
    """/mcp e SSE (StreamableHTTPServerTransport) — gzip com buffering quebra o stream."""
    resp = await client.post("/mcp", headers={"Accept-Encoding": "gzip"}, json={})
    assert resp.headers.get("content-encoding") != "gzip"
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `pytest tests/integration/test_web_static_caching.py -v`
Expected: os dois primeiros FAIL.

- [ ] **Step 3: `CachedStaticFiles`**

`src/web/static_files.py`:

```python
"""StaticFiles com Cache-Control longo.

Seguro porque as URLs carregam ?v=<asset_version> (K_REVISION do Cloud Run,
que muda a cada deploy) — o browser busca uma URL nova em vez de revalidar.
"""

from __future__ import annotations

import os
from typing import Any

from starlette.responses import Response
from starlette.staticfiles import StaticFiles

_ONE_YEAR = 31_536_000


def asset_version() -> str:
    """Identificador que muda a cada deploy. Cloud Run injeta K_REVISION."""
    return os.getenv("K_REVISION") or "dev"


class CachedStaticFiles(StaticFiles):
    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = f"public, max-age={_ONE_YEAR}, immutable"
        return resp
```

- [ ] **Step 4: Gzip com exclusão de `/mcp`**

Em `src/web/middleware.py`, no fim:

```python
class SelectiveGZipMiddleware(GZipMiddleware):
    """GZip em tudo menos /mcp.

    /mcp e StreamableHTTPServerTransport (SSE): comprimir com buffering
    atrasa/quebra a entrega dos eventos.
    """

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)
```

Imports no topo: `from typing import Any` e `from starlette.middleware.gzip import GZipMiddleware`.

- [ ] **Step 5: Plugar no app**

Em `src/app.py`, junto dos outros `add_middleware` (linha ~79):

```python
    app.add_middleware(SelectiveGZipMiddleware, minimum_size=500)
    app.add_middleware(CSRFOriginMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
```

E trocar o mount (linha ~98):

```python
    from src.web.static_files import CachedStaticFiles

    static_dir = Path(__file__).parent / "web" / "static"
    if static_dir.exists():
        app.mount("/static", CachedStaticFiles(directory=str(static_dir)), name="static")
```

Import de `SelectiveGZipMiddleware` junto do import existente de `CSRFOriginMiddleware`.

- [ ] **Step 6: Expor `asset_version` no Jinja**

Em `src/web/routes.py`, depois de `templates.env.filters["meta_status_label"] = meta_status_label`:

```python
from src.web.static_files import asset_version

templates.env.globals["asset_version"] = asset_version()
```

- [ ] **Step 7: Versionar os links**

Em `_base.html`, acrescentar `?v={{ asset_version }}` nos cinco stylesheets e no favicon:

```html
  <link rel="stylesheet" href="/static/v4-tokens.css?v={{ asset_version }}">
  <link rel="stylesheet" href="/static/v4-base.css?v={{ asset_version }}">
  <link rel="stylesheet" href="/static/v4-components.css?v={{ asset_version }}">
  <link rel="stylesheet" href="/static/v4-motion.css?v={{ asset_version }}">
  <link rel="stylesheet" href="/static/v4-tailwind.css?v={{ asset_version }}">
```

> O guard `test_tailwind_e_o_ultimo_stylesheet` usa regex em `href="..."`; com a querystring o `assert "v4-tailwind.css" in locais[-1]` continua válido.

- [ ] **Step 8: Rodar e commitar**

Run: `pytest tests/integration/test_web_static_caching.py -v && python scripts/check_pre_push.py`
Expected: PASS

```bash
git add src/web/static_files.py src/web/middleware.py src/app.py src/web/routes.py \
        src/web/templates/_base.html tests/integration/test_web_static_caching.py
git commit -m "perf(web): gzip seletivo e cache imutavel versionado por revisao"
```

---

### Task 6: Dívida — offsets sticky, CSS do help, fonte e meta tags

Quatro itens menores: offsets sticky mágicos (`53px`/`96px`/`120px`) amarrados à altura do header; ~90 linhas de `<style>` inline em `help.html`; peso **300** do Montserrat baixado sem nenhum uso; sem `meta description`/`theme-color`.

**Files:**
- Modify: `src/web/static/v4-tokens.css:106-111`, `src/web/static/v4-base.css:142`
- Create: `src/web/static/v4-help.css`
- Modify: `src/web/templates/help.html`, `src/web/templates/_base.html`
- Test: `tests/unit/test_frontend_a11y_guards.py`

- [ ] **Step 1: Derivar os offsets de uma altura única**

Em `v4-tokens.css`, substituir o bloco de "Sticky offset":

```css
  /* Sticky offsets — derivados da altura do header pra nao dessincronizar.
     header  = 12px+12px de padding + 28px de conteudo + 1px de borda
     subnav  = 12px+12px de padding + 18px de conteudo + 1px de borda
     filtros = barra de filtros da auditoria */
  --v4-header-h:          53px;
  --v4-subnav-h:          43px;
  --v4-filter-bar-h:      67px;
  --v4-subnav-offset:     var(--v4-header-h);
  --v4-tab-bar-offset:    calc(var(--v4-header-h) + var(--v4-subnav-h));
  --v4-audit-day-offset:  calc(var(--v4-header-h) + var(--v4-filter-bar-h));
```

Em `v4-base.css` linha ~142, trocar o literal por token:

```css
  top: var(--v4-header-h);
```

- [ ] **Step 2: Extrair o CSS do `help.html`**

Criar `src/web/static/v4-help.css` com o conteúdo do `<style>` de `help.html` (sem as tags). Adicionar um bloco de head no `_base.html`, logo antes de `</head>`:

```html
  {% block head_extra %}{% endblock %}
</head>
```

E em `help.html`, trocar o `<style>…</style>` por:

```jinja
{% block head_extra %}
<link rel="stylesheet" href="/static/v4-help.css?v={{ asset_version }}">
{% endblock %}
```

- [ ] **Step 3: Remover o peso 300 do Montserrat**

Confirmado sem uso (nenhum `font-weight: 300` nem `font-light` no projeto). Em `_base.html`:

```html
  <link rel="stylesheet" href="https://fonts.bunny.net/css?family=montserrat:400,500,600,700,800|jetbrains-mono:400,700&display=swap">
```

- [ ] **Step 4: Meta tags**

Em `_base.html`, depois do `<meta name="viewport">`:

```html
  <meta name="description" content="Painel interno da V4 Company para conectar contas Google Ads e Meta Ads ao Claude, Codex e Cursor via MCP.">
  <meta name="theme-color" content="#e50914">
```

- [ ] **Step 5: Guard dos offsets**

Adicionar em `tests/unit/test_frontend_a11y_guards.py`:

```python
def test_offsets_sticky_sao_derivados():
    """Offsets magicos dessincronizam em silencio quando o header muda."""
    css = (_STATIC / "v4-tokens.css").read_text(encoding="utf-8")
    assert "--v4-header-h:" in css
    assert "calc(var(--v4-header-h)" in css
    base = (_STATIC / "v4-base.css").read_text(encoding="utf-8")
    assert "top: 53px" not in base
```

- [ ] **Step 6: Rodar e commitar**

Run: `python scripts/check_pre_push.py`
Expected: verde

```bash
git add src/web/static src/web/templates tests/unit/test_frontend_a11y_guards.py
git commit -m "refactor(web): offsets derivados, CSS do help extraido, fonte enxuta e meta tags"
```

---

### Task 7: Documentação e verificação em produção

**Files:**
- Modify: `CLAUDE.md` (seções Stack, Conventions → Design system, Don't do)
- Create: `docs/operacao/session-2026-08-11-frontend-handoff.md`

- [ ] **Step 1: Atualizar `CLAUDE.md`**

Três edições:

1. **Stack** — trocar "Sem build step de frontend" por: "Sem build step no runtime; o CSS do Tailwind é **gerado offline** (`python scripts/build_tailwind.py`, pin 3.4.17) e **commitado** em `src/web/static/v4-tailwind.css`, com guard de diff no CI."
2. **Conventions → Design system** — substituir a nota de sync manual do `tailwind.config` por: "Token novo vai **só** no `v4-tokens.css`; o `tailwind.config.js` referencia `var(--v4-*)`. Alterou classe utilitária em template? Rode `python scripts/build_tailwind.py` e commite o CSS — o CI faz `git diff --exit-code`. **`v4-tailwind.css` é o ÚLTIMO stylesheet do `<head>`** (o Preflight precisa vencer o `v4-base.css`; inverter estoura todo heading)."
3. **Don't do** — acrescentar: "Don't mexer em classe utilitária de template sem rodar `scripts/build_tailwind.py` no mesmo commit. Don't reordenar os `<link>` do `<head>` — `v4-tailwind.css` por último. Don't usar `--v4-gray-300` como cor de texto (2,1:1); use `--v4-gray-500`. Don't aplicar gzip a `/mcp` (SSE)."

- [ ] **Step 2: Escrever o handoff**

`docs/operacao/session-2026-08-11-frontend-handoff.md` no formato dos handoffs existentes: TL;DR em tabela (grupo / entrega / commits), medições antes-e-depois, decisões do gestor (aposentar CDN: sim; refatorar os 28 `onclick`: adiado), e pendências.

- [ ] **Step 3: Push e confirmar o CI**

```bash
git push origin main
```

Confirmar via `gh run view <id> --json conclusion` — **nunca** pelo exit code de `gh run watch`.

- [ ] **Step 4: Verificar em produção**

```bash
curl -sI -H 'Accept-Encoding: gzip' https://v4-ads-mcp-299432068772.southamerica-east1.run.app/static/v4-tokens.css | grep -iE 'content-encoding|cache-control'
curl -s https://v4-ads-mcp-299432068772.southamerica-east1.run.app/login | grep -c 'cdn.tailwindcss.com'
```
Expected: `content-encoding: gzip` + `cache-control: public, max-age=31536000, immutable`; `0` ocorrências do CDN.

Conferir também no browser: `h1` sem classe continua 14px (Preflight vencendo), CSP sem `unsafe-eval`, e `domContentLoaded` do `/login` abaixo do baseline de 1128 ms.

- [ ] **Step 5: Commit final**

```bash
git add CLAUDE.md docs/operacao/session-2026-08-11-frontend-handoff.md
git commit -m "docs(operacao): handoff do pacote de frontend 2026-08-11"
git push origin main
```

---

## Self-Review

**Cobertura vs. investigação:** P0 hambúrguer+marca → Task 1 · reduced-motion, skip link, foco, contraste gray-300 e badge, toast aria → Task 2 · drawer `aria-current`/foco + nav duplicada → Task 3 · Tailwind CDN + duplicação de tokens + `unsafe-eval` → Task 4 · gzip + Cache-Control → Task 5 · offsets sticky, `<style>` do help, peso 300, meta tags → Task 6 · docs → Task 7. **Fora de escopo por decisão do gestor:** refatorar os 28 `onclick` inline pra remover `'unsafe-inline'`.

**Riscos e mitigação:**
1. **Ordem da cascata** (alto impacto): guard `test_tailwind_e_o_ultimo_stylesheet` + comentário no `_base.html` e no `v4-base.css`.
2. **Drift do CSS gerado**: guard de `git diff` no CI.
3. **Gzip no SSE do MCP**: `SelectiveGZipMiddleware` + teste dedicado.
4. **`immutable` servindo asset velho**: mitigado pelo `?v=K_REVISION`, que muda a cada deploy.
