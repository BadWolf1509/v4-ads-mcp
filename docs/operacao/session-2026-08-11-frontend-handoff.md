# Sessão 2026-08-11 — Handoff (investigação de frontend → pacote shipado)

> Investigação de oportunidades de melhoria no frontend do painel (templates Jinja2 + design system CSS + entrega de assets + CSP) → **6 rodadas na main** (`aebdb8f..5dc81fa`). Execução inline (sem subagentes), TDD por task, plano em [`2026-08-11-frontend-improvements.md`](../superpowers/plans/2026-08-11-frontend-improvements.md).
>
> Diferencial desta investigação: as hipóteses foram **medidas em produção** (DOM real via browser + curl), não deduzidas de leitura de código. Duas delas viraram bug confirmado e uma terceira quase quebrou o deploy — ver "A descoberta que salvou o pacote".

## TL;DR

| Grupo | Entrega | Commit |
|---|---|---|
| **P0 — bugs em produção** | hambúrguer/drawer escondidos deslogado (abria gaveta vazia + travava scroll) · marca ancorada no mobile | `aebdb8f` |
| **A11y** | `prefers-reduced-motion` · skip link · token `:focus-visible` · contraste AA (gray-300 → gray-500, tokens `--v4-gold-text`/`--v4-green-text`) · toast `role=alert` | `bfb9c41` |
| **Navegação** | `nav_items` única alimentando header + drawer · `aria-current` no drawer · foco devolvido + Tab contido via `inert` | `7a8075a` |
| **Perf — Tailwind** | **Play CDN aposentado**: 407 KB de JS → 12 KB de CSS estático · `unsafe-eval` fora da CSP · tokens deduplicados | `34735f7` |
| **Perf — assets** | gzip seletivo (exclui `/mcp`) · `Cache-Control: immutable` versionado por `K_REVISION` | `2503ac2` |
| **Dívida** | offsets sticky derivados de `--v4-header-h` · CSS do help extraído · peso 300 do Montserrat removido · meta tags | `7ee974d` |

**Decisões do gestor:** aposentar o CDN → **sim** (revertendo a decisão de 07-04, que foi tomada sem os números). Refatorar os handlers inline → inicialmente **adiado**, depois **aprovado** (5ª rodada) e estendido a `style-src` (6ª).

## Medições — antes e depois

Baseline coletado no `/login` em produção (`00028-lvc`), via `performance.getEntriesByType` e `curl`:

| Métrica | Antes | Depois (esperado) |
|---|---|---|
| Tailwind | 407 KB JS (123 KB gzip), render-blocking, 423 ms, compilando em runtime | 11,6 KB CSS (~3,3 KB gzip), estático |
| `domContentLoaded` | 1128 ms | — verificar pós-deploy |
| Compressão dos estáticos | nenhuma (`transferSize == decodedBodySize`) | gzip |
| `Cache-Control` | ausente (só `etag`, revalidação a cada navegação) | `public, max-age=31536000, immutable` + `?v=K_REVISION` |
| CSP | `script-src` com `'unsafe-inline' 'unsafe-eval'` + CDN; `style-src` com `'unsafe-inline'` | **nenhuma diretiva `unsafe-*`** (ver 5ª e 6ª rodadas) |
| `prefers-reduced-motion` | 0 regras / 3 animações infinitas | coberto |

## A descoberta que salvou o pacote

O Play CDN injetava seu `<style>` **no fim do `<head>`**, depois dos quatro `<link>` do v4. Testado no DOM de produção com um `h1` sem classe:

```
h1 sem classe → font-size: 14px · font-weight: 400 · margin-bottom: 0px
v4-base.css:17 declara → 36px / 800 / 16px
```

Ou seja: **o Preflight do Tailwind vence, e as regras de heading/parágrafo do `v4-base.css` são código morto**. Todo heading do painel tira o tamanho de classes utilitárias.

Se o CSS gerado tivesse sido carregado na posição "natural" (junto dos outros `v4-*.css`), o `v4-base.css` passaria a vencer e **todo heading sem classe saltaria de 14px pra 36px** — uma regressão visual em todas as páginas, invisível em qualquer teste server-side. O `<link>` novo é o último do `<head>`, com guard (`test_tailwind_e_o_ultimo_stylesheet`) e comentário nos dois arquivos.

## Armadilha nova: o scanner do Tailwind lê comentários

Ao documentar a remoção do peso 300 eu escrevi a palavra `font-light` num comentário Jinja — e o scanner gerou `.font-light { font-weight: 300 }`, justamente o peso que eu tinha acabado de tirar do carregamento. Pego pelo diff de seletores entre o CSS antigo e o novo.

**Regra:** não cite nome de utilitário em comentário de template. O diff de seletores (`old - new` / `new - old`) é a forma de auditar uma regeneração — o diff de linha é inútil em CSS minificado (tudo numa linha só).

Resultado final da regeneração: saíram só `.transform` e `.transition`, que eram gerados pelo texto do `<style>` do help e não aparecem em nenhum `class=`.

## Verificação

- `check_pre_push.py` **5/5 verde** em cada commit.
- **Docker não está instalado nesta máquina** — os testes de integração (testcontainers) só rodam no CI. Compensado com uma harness local que renderiza as templates Jinja direto (19 asserts: presença condicional do hambúrguer/drawer, `aria-current` header vs drawer, paridade das duas navs, exact vs prefix, ordem dos stylesheets, `head_extra` no head e não no corpo).
- Build do Tailwind **determinístico** (md5 estável entre execuções) — pré-requisito do guard de diff no CI.
- Guards novos: `tests/unit/test_frontend_a11y_guards.py` (13) + `tests/unit/test_web_static_caching.py` (4) + 2 integration (login sem hambúrguer, drawer com `aria-current`).
- `tests/unit/test_security_headers.py` atualizado: agora **assere a ausência** de `unsafe-eval` e do CDN.

## Smoke autenticado das telas admin (2ª rodada, mesma sessão)

Feito via Claude in Chrome na sessão real do admin. **Só navegação e inspeção** — nenhum controle de mutação foi clicado (dados de produção).

Verificado em prod (`00030-slz`) nas 14 telas (`/`, `/accounts`, `/sessions`, `/audit`, `/help` + as 9 de `/admin`):

- **Zero classes utilitárias sem CSS em todas as 14** — a geração offline do Tailwind está completa (auditado comparando as classes do HTML de cada página contra o CSSOM carregado). Nenhum erro de console, nenhuma violação de CSP.
- Cascata preservada em todas (`h1` sem classe = 14px), `0` `<style>` injetado em runtime, skip link e `aria-current` (header + drawer) presentes em todas.
- `/help`: `v4-help.css` carrega por último via `head_extra`, uma vez só, e o "Voltar ao topo" está em `#6b6b6b` (correção de contraste no ar). O único `<style>` restante na página é injetado pelo **próprio HTMX** (`.htmx-indicator`) — não é nosso — foi desligado na 6ª rodada via `htmx-config`, o que permitiu tirar o `'unsafe-inline'` de `style-src`.
- Dropdown de Gestores abre e não é clipado (a exclusão do `.v4-table-wrap` de 07-04 segue correta).

**O smoke encontrou 3 bugs pré-existentes** (F78-F80 no catálogo) — dois deles expostos justamente por eu ter nomeado os offsets como tokens. Corrigidos em `fc8c0a8`, com CI+deploy verdes e re-verificados no ar:

| | Antes | Depois |
|---|---|---|
| `/admin/audit` | filtros em `top:53` **cobrindo a subnav inteira** (subnav cortada em "Aud…") | header 0–65 · subnav 65–120 · filtros 120–208 |
| `/admin/access` | tab bar 12px sob a subnav | subnav 65–120 · tab bar 120–175 |
| `/audit` | cabeçalho de dia 33px sob os filtros | header 0–65 · filtros 65–153 · dia 153–183 |
| Busca das matrizes | ícone sobre o placeholder ("🔍scar gestor…") | "🔍 Buscar gestor…" |

## Pendências

1. ~~Adiado: refatorar os `onclick` inline pra remover `'unsafe-inline'`~~ — **feito na 5ª rodada** (`bfd438d`+`9374638`). Eram 53 atributos e 13 blocos `<script>`, não 28. Ver abaixo.
2. ~~Limitação do `--v4-audit-day-offset` no mobile~~ — **resolvido em `eab6099`** (3ª rodada). Ver abaixo.
3. ~~Meta OAuth pessoal exibindo "0 dias" pra data passada~~ — **corrigido** (`d1d0750`): o cálculo fazia `max(0, delta.days)`, achatando vencido em zero. Agora há três estados (Conectado / Expira em breve / Expirado) com plural correto e "hoje". Nota: o token foi reconectado pelo Wellington em 11/08 às 23:35 (audit `meta_oauth_connect`), então o estado expirado não reproduz mais em produção — foi verificado localmente nos 6 casos.

## 3ª rodada — o offset da barra de filtros virou medição de runtime (`eab6099`)

A pendência do mobile acabou revelando que o problema era maior do que "mobile". Medindo a altura da barra de filtros da `/audit` por largura disponível:

| Largura | Linhas | Altura |
|---|---|---|
| ≥ 831px | 1 | 88px |
| 618–830px | 2 | **164px** |
| < 618px | 3 | **240px** |

Os pontos de quebra (**831px** e **618px**) emergem da largura do conteúdo e não coincidem com nenhum breakpoint padrão (Tailwind: 640 / 768 / 1024). Duas consequências:

1. **Não era só mobile.** O offset já estava errado por 76px em qualquer janela entre 618 e 831px — faixa comum de laptop estreito ou tela dividida.
2. **Media query com valor chutado não resolve.** Qualquer literal erra perto das bordas, e os pontos de quebra mudam se alguém adicionar um filtro ou mexer num rótulo.

**Fix:** um `ResizeObserver` em `_base.html` publica a altura real da barra em `--v4-filter-bar-h`, que alimenta `--v4-audit-day-offset`. A barra é marcada com `data-sticky-measure` (só a da `/audit` — é a única cuja altura alimenta um offset). Publica `0` quando a barra não está sticky, então continua correto se alguém desligar o sticky depois. Sem JS, o literal de `v4-tokens.css` segue como fallback.

Isso fecha o F79 no mecanismo, não só no valor: a lição era "offset sticky é altura medida, não estimada", e agora a medição é contínua em vez de um snapshot que apodrece.

**Verificado em produção** nas três faixas — publicado bate com a altura real em 1200px (88), 800px (164) e 500px (240), com o offset resolvendo pra `calc(65px + 240px)` na mais estreita.

> **Nota de método:** o `ResizeObserver` parecia não disparar nos primeiros testes (0 entregas, nem a inicial). Não era bug: a aba do Chrome estava com `visibilityState: "hidden"`, e a entrega de `ResizeObserver` — como `requestAnimationFrame` — acontece nos *rendering steps*, que não rodam em aba que não pinta. Forçar uma pintura (screenshot) entre a mudança de largura e a leitura destravou. **Ao medir layout responsivo por automação, intercale uma pintura** — senão você "confirma" um bug que não existe. Mesma família do falso negativo do skip link (`:focus` não casa sem foco no documento).

## 4ª rodada — barras de filtro rolam junto no celular (`15903f5`)

Decisão do gestor: aplicar. Com o offset já correto, o que sobrava era espaço preso — embrulhadas, as barras chegam a 240px:

| Tela | Pilha fixa no celular | % de um viewport de 844px |
|---|---|---|
| `/audit` | 61 (header) + 240 (barra) = **301px** | ~36% |
| `/admin/audit` | 61 + 55 (subnav) + 240 = **356px** | ~42% |

`max-sm:static` (< 640px) faz as duas rolarem junto com a página. **Aplicado nas duas** — `/admin/audit` é o caso pior, deixar só `/audit` seria incoerente.

Usei o breakpoint `sm` padrão em vez do literal de 617px que eu tinha proposto: fica a 22px do ponto de quebra medido (618px, onde a barra vai pra 3 linhas) e o codebase já usa as escalas do Tailwind em vez de valores arbitrários.

O `ResizeObserver` ganhou um listener de `resize` junto: a troca de `position` no breakpoint pode acontecer **sem** mudança de altura, que é o único gatilho do observer. Ambos saem cedo quando o valor não mudou, então o custo é duas leituras por evento.

**Verificação em duas partes** (a janela do Chrome estava maximizada e o `resize_window` não encolhe o viewport, então não deu pra testar com uma tela real < 640px):

1. **Estrutural, no CSS servido em produção:** `.max-sm\:static{position:static}` existe dentro de `@media not all and (min-width:640px)` (a forma como o Tailwind expressa `max-width`) e aparece na posição 10764, depois do `.sticky` na 4660 — mesma especificidade, então a regra do breakpoint vence.
2. **Integração, end-to-end em produção:** forçando `position: static` por stylesheet, o observer publica `0px` e `--v4-audit-day-offset` colapsa pra `calc(65px + 0px)`; voltando a sticky, republica `88px`. Isso exercita exatamente o listener novo.

O que **não** foi verificado com viewport real abaixo de 640px é a media query casando — mas com a regra confirmada presente e na ordem certa, isso é semântica determinística de CSS.

## 5ª rodada — CSP sem script inline (`bfd438d` + `163650f` + `9374638`)

Decisão do gestor: fazer agora. A superfície era maior que os "28 onclick" que eu tinha estimado:

| | Quantidade |
|---|---|
| Atributos inline (`on*=` + `hx-on`) | **53** em 15 arquivos |
| Blocos `<script>` inline | **13** em 8 arquivos |

Todos exigem `script-src 'unsafe-inline'`, então todos tinham que sair. Foram **dois commits de propósito**: o primeiro só realoca comportamento (inofensivo por si só) e o segundo aperta a CSP — assim o passo arriscado é um revert de uma linha, e uma quebra é atribuível sem ambiguidade.

Tudo virou listener delegado em [`v4-panel.js`](../../src/web/static/v4-panel.js), acionado por `data-v4-*`: `drawer-toggle`, `dropdown-toggle`, `row-toggle`, `dialog-open`/`dialog-close`, `copy`, `confirm`, mais `data-v4-autosubmit`, `data-v4-submit-once`, `data-v4-filter` e `data-v4-matrix-filter`.

```
antes:  script-src 'self' 'unsafe-inline' 'unsafe-eval' cdn.tailwindcss.com unpkg.com
agora:  script-src 'self' https://unpkg.com
```

`style-src` **mantém** `'unsafe-inline'` e não dá pra tirar hoje: o próprio htmx injeta um `<style>` (`.htmx-indicator`) em runtime, além dos atributos `style=` nas templates. CSS inline não executa código — não é o mesmo risco.

### Ganhos além da CSP

- **F74 virou impossível por construção.** O fragmento de reposição do toggle de acesso não carrega mais handler nenhum — só o marcador `data-v4-access-toggle` — então não há o que esquecer de re-emitir no swap.
- **F81: quatro filtros de tabela que estavam mortos voltaram a funcionar** (ver catálogo). O mecanismo novo mira por atributo, não por `id`, então o acoplamento que os quebrava deixou de existir.
- 4 filtros quase idênticos viraram um mecanismo declarativo; os 2 scripts da matriz (byte-idênticos) viraram uma função.
- O link "Detalhe" dentro da linha expansível não precisa mais de `stopPropagation`.
- O botão de copiar deixou de mentir: o antigo trocava o rótulo pra "Copiado!" e mostrava toast de sucesso **sem esperar** o `writeText`, então numa falha afirmava um sucesso que não houve. Agora só confirma depois que a escrita resolve, e avisa se falhar.

### Verificação

- CI pegou o que o gate local não pega: dois testes de integração fixavam o contrato antigo do fragmento (`hx-on::after-request`). Corrigidos em `163650f` — o contrato mudou de propósito.
- **Um `onclick` sobreviveu à varredura estática**: estava dentro de uma string Jinja com aspas escapadas (`\"`) passada pra macro `modal()`. Pego varrendo as 14 telas **renderizadas** em produção; o guard passou a casar aspa escapada.
- Exercitado em produção sob a CSP restrita, com listener de `securitypolicyviolation` ativo — **zero violações**: filtros de tabela e da matriz, dropdown, drawer (inclusive `inert`), toasts (`status`/`alert`), diálogo de confirmação (aberto e **cancelado**), modais, linha expansível (mouse e teclado), link que não expande, e o listener delegado do checkbox (evento simulado, sem request).
- **Nada de controle de mutação foi clicado** — dados de produção.

### Não verificado

A cópia real pro clipboard. `clipboard-write` está `granted`, mas `navigator.clipboard.writeText` exige documento em foco e a aba de automação roda com `hasFocus() === false`. O handler roda, resolve a origem certa e cai no fallback de erro. É a mesma dependência do código antigo — só que agora tratada.

## 6ª rodada — CSP sem nenhum `unsafe-*` (`384059e` + `5dc81fa`)

Decisão do gestor: tirar `'unsafe-inline'` de `style-src` também.

**A pergunta que decidia a viabilidade veio antes do código:** `style-src` sem `'unsafe-inline'` bloqueia atributo `style=` — e os filtros de tabela fazem `tr.style.display`, o drawer faz `body.style.overflow`, a medição sticky faz `setProperty`. Se CSP bloqueasse escrita via CSSOM, metade do painel morreria.

Testei numa página isolada sob `style-src 'none'`:

| | Resultado |
|---|---|
| `el.style.display = 'none'` | **funciona** |
| `setProperty('--v4-filter-bar-h')` | **funciona** |
| `body.style.overflow` | **funciona** |
| `style="color:red"` no HTML | **bloqueado** (`style-src-attr`) |

CSSOM não é afetado por CSP; só o atributo no HTML. Então o trabalho era finito: 28 atributos `style=`.

Viraram utilitários (que passam a viver no CSS gerado) ou classe do design system: `m-0` (12x), `w-[200px]` (5x), `w-[140px]`, `p-0`, `flex-1 max-w-[320px]`, os 4 offsets sticky como `top-[var(--v4-*)]`, e o "Sair" da gaveta como `.v4-drawer__link--button`. O `<style>` que o htmx injetava foi desligado com `<meta name="htmx-config" content='{"includeIndicatorStyles": false}'>` — as regras já existiam em `v4-motion.css`.

```
final:  default-src 'self'; script-src 'self' https://unpkg.com;
        style-src 'self' https://fonts.bunny.net; font-src 'self' https://fonts.bunny.net;
        img-src 'self' data:; connect-src 'self'
```

**A CSP do painel não tem mais nenhuma diretiva `unsafe-*`.**

### O erro que quase passou

Trocar `style=` por `class=` num elemento que **já tinha** `class=` cria dois atributos `class` — e o browser usa só o primeiro. Os quatro offsets sticky teriam sumido em silêncio. Peguei relendo o diff, fundi no atributo existente e adicionei uma verificação de que nenhuma tag ficou com `class` duplicado.

### Verificação em produção

Zero violações de CSP, `0` `<style>` injetado, `.htmx-indicator` vindo do arquivo, CSSOM funcionando. E os dois regimes de largura, com o CSS de produção:

| | mobile (414px real) | desktop (1280px) |
|---|---|---|
| `--v4-header-h` | 61px | 65px |
| barra da `/audit` | `static` (rola junto) | `sticky` @ 65px |
| barra do `/admin/audit` | `static` | `sticky` @ 120px |
| cabeçalho de dia | @ 61px | `sticky` @ 153px |
| `--v4-filter-bar-h` | `0px` | 88px |

O mobile foi verificado **em viewport real de 414px** — a janela do Chrome acabou encolhendo de fato, o que fechou a lacuna que eu tinha declarado em aberto na 4ª rodada. Screenshot confirma hambúrguer à esquerda com a marca ao lado (fix do F78) e a barra de filtros rolando com a página.
