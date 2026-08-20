# Painel web e design system

> Templates Jinja, CSP, Tailwind gerado offline, HTMX. Leia ao mexer em `src/web/`.
>
> Extraído do `CLAUDE.md` em 2026-08-19: convenção é estável e específica de
> área, então carregá-la em toda sessão era imposto de contexto. As regras
> curtas (o que faz parar) seguem no `Don't do` do `CLAUDE.md`; aqui fica o
> **porquê**.
>
> Taxonomia completa dos bugs: [`findings-catalog.md`](../operacao/findings-catalog.md).

---

### Segurança web (middleware) — post sessão 2026-05-29


`src/web/middleware.py`: `CSRFOriginMiddleware` (bloqueia método unsafe com Origin/Referer presente-e-divergente de Host; ausência permitida — SameSite=Lax é a defesa primária; isenta **por rota**: `/oauth/meta/data-deletion-callback` + `/mcp`. O prefixo `/oauth/` inteiro saiu em 08-19/F106 — pendurava duas mutações do painel autenticadas por cookie dentro da isenção) + `SecurityHeadersMiddleware` (XFO/XCTO/Referrer/HSTS + **CSP enforcing** com allowlist em `_CSP_POLICY`).

- **Adicionou recurso externo** (script/style/font de novo host)? **Atualize `_CSP_POLICY`** no mesmo commit ou ele é bloqueado em produção. Allowlist atual (verificada 08-15): `unpkg.com` (script), `fonts.bunny.net` (style+font). `cdn.tailwindcss.com` **saiu** em 08-11 e há guard assertando a ausência — não re-adicione.
- Toda página renderiza HTML de input? Jinja autoescape cobre `{{ }}`; em f-strings/HTML manual use `html.escape` (XSS — `_error_page`, `_toggle_checkbox_fragment`).
- Exception handler em `src/app.py` (`StarletteHTTPException`): 3xx vira redirect (preserva 302→/login), `/mcp`+`/oauth` → JSON, resto → `error.html`. Ao mexer, **preserve o branch 3xx** (senão prende usuário não-autenticado).

### Design system


Tailwind **gerado offline e commitado** (não CDN — ver Stack) + tokens em `src/web/static/v4-tokens.css`. **16 macros** em `_components.html`. **Editorial mode** (login/access-denied/help/hero): display 36-56px (use `text-4xl md:text-display` pra responsivo), red `#e50914`. **Operational mode** (audit/matriz/admin): compact 12-14px. `button()`/`<button>` dentro de `<form>` MUST `type="submit"` (F49). Status Meta na UI via filtro Jinja `meta_status_label` (registrado em routes.py). Card por padrão: `v4-card__header`/`v4-card__title` (h3).

Padrões pós-pacote UI/UX 2026-07-04 (2ª sessão):
- **Ação de mutação do painel via HTMX = HX-aware** (espelha `sessions_revoke` em routes.py): se `HX-Request` → `204` + `HX-Redirect`/`HX-Refresh` + `HX-Trigger` toast; senão `303`. NUNCA retornar `303` cru pra um `hx-post` — o XHR segue o redirect e injeta a página inteira no `hx-target` (era o bug do dropdown de Managers). `204` = no-swap por spec, então o `hx-target` legado fica inofensivo.
- **Flash de `?error=`/`?ok`**: mapa fixo código→mensagem PT-BR no handler; o query param NUNCA é ecoado no contexto (a macro `alert` renderiza `{{ message|safe }}` → eco = XSS). Código desconhecido → sem flash.
- **Contraste AA**: texto secundário sobre fundo claro usa `--v4-gray-500` (`#6b6b6b`, ~5.7:1); `--v4-gray-300` fica só em borders e texto sobre fundo escuro (code-block) — e ali exige o marcador `/* on-dark */` na linha, senão o guard `test_gray_300_nunca_usado_como_cor_de_texto` falha. Sobre os fundos soft use `--v4-gold-text`/`--v4-green-text` (o gold puro dava 3,8:1). **Token novo vai SÓ no `v4-tokens.css`** — o `tailwind.config.js` referencia `var(--v4-*)`, não há mais duplicação de hex.

Padrões pós-pacote de frontend 2026-08-11:
- **Tailwind é gerado offline.** Mexeu em classe utilitária de template? Rode `python scripts/build_tailwind.py` e **commite o CSS no mesmo commit** — o CI faz `git diff --exit-code`. O scanner lê o arquivo **inteiro, comentários incluídos**: citar o nome de um utilitário num comentário faz o CSS crescer.
- **`v4-tailwind.css` é o ÚLTIMO stylesheet do `<head>`** (guard `test_tailwind_e_o_ultimo_stylesheet`). O Preflight precisa vencer o `v4-base.css`: hoje `h1` sem classe utilitária é 14px/400, **não** os 36px/800 que o `v4-base.css` declara (essas regras são fallback morto). Reordenar os `<link>` estoura todo heading do painel.
- **Assets versionados**: os `<link>` levam `?v={{ asset_version }}` (de `K_REVISION`), o que torna seguro o `Cache-Control: immutable` do `CachedStaticFiles`. CSS de página específica entra via `{% block head_extra %}` — **top-level na template, nunca dentro de `{% block content %}`** (lá o Jinja renderiza o `<link>` no corpo).
- **Gzip**: `SelectiveGZipMiddleware` comprime tudo menos `/mcp` (SSE — buffering quebra o stream).
- **A11y**: `prefers-reduced-motion` no fim do `v4-motion.css`; foco por teclado via `:focus-visible` com `--v4-focus-color`; skip link `#conteudo`; nav declarada uma vez em `nav_items` e renderizada no header E no drawer (macro `current_attr`).
- **ZERO JavaScript E ZERO CSS inline. A CSP não tem nenhuma diretiva `unsafe-*`.** Atributo `on*=`/`hx-on`, bloco `<script>` ou atributo `style=` numa template é **bloqueado pelo browser**, silenciosamente.
  - Comportamento → [`v4-panel.js`](../../src/web/static/v4-panel.js), listener delegado por `data-v4-action` (`drawer-toggle`, `dropdown-toggle`, `row-toggle`, `dialog-open`/`dialog-close`, `copy`, `confirm`) ou `data-v4-autosubmit` / `data-v4-submit-once` / `data-v4-filter` / `data-v4-matrix-filter`. Ação nova = entrada no mapa `ACOES` (o guard confere).
  - Estilo → classe (utilitário Tailwind, inclusive arbitrary com `var()`: `top-[var(--v4-subnav-offset)]`) ou classe do design system. CSS de página entra por `{% block head_extra %}`.
  - **Escrita via CSSOM (`el.style.x = y`, `setProperty`) NÃO é bloqueada** — verificado empiricamente sob `style-src 'none'`. É por isso que os filtros, o drawer e a medição sticky funcionam.
  - Trocar `style=` por `class=` num elemento que já tem `class=` cria **dois atributos `class`** e o browser usa só o primeiro — funda no existente.
  - O `<style>` que o htmx injetava está desligado por `<meta name="htmx-config" content='{"includeIndicatorStyles": false}'>`; as regras vivem em `v4-motion.css`.
- **Fragmento HTMX não carrega handler.** O comportamento pós-swap é delegado (`data-v4-access-toggle`), então o HTML de reposição servido por rota não precisa re-emitir nada — era o F74, agora impossível por construção.
- **Tabela responsiva** = envolver em `.v4-table-wrap` (overflow-x + `white-space:nowrap` ESCOPADO ao wrapper em `th`/`.col-mono`) **+ `tabindex="0" role="region" aria-label`** — scroller sem foco não rola por teclado no Firefox nem no Safari (F125). **Sem exceção**: as duas que existiam caíram em 2026-08-20, porque o preço delas era a página inteira rolando na horizontal (F118/F119, medido +751px e +545px em 375). Tabela com `v4-table--sticky-head` usa também `.v4-table-wrap--wide`, que desliga o scroller acima de 1200px e devolve o sticky do F97; tabela com dropdown não precisa de nada — `v4DesancorarMenu` tira o menu do clip sozinho. Matriz de acesso segue com `overflow-x-auto` (o `nowrap` de `th` do wrapper vazaria por herança e impediria o cabeçalho de gestor de quebrar).
- **Fragmento HTMX de reposição** (ex.: `_toggle_checkbox_fragment`): o HTML de reposição DEVE re-emitir `hx-on::after-request` + `aria-label`, senão o feedback some após o 1º swap (F74). `hx-on` é string estática (sem XSS); preserve `html.escape` nos valores dinâmicos (`hx-vals`).
- **Fontes**: via `<link rel="preconnect">` + `<link rel="stylesheet">` no head de `_base.html` (NÃO `@import` no CSS — waterfall). Host `fonts.bunny.net` já na CSP (Montserrat + JetBrains Mono, sintaxe dual-family `family=a:...|b:...`).
