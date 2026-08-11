# Sessão 2026-08-11 — Handoff (investigação de frontend → pacote shipado)

> Investigação de oportunidades de melhoria no frontend do painel (templates Jinja2 + design system CSS + entrega de assets + CSP) → **7 commits na main** (`aebdb8f..<docs>`). Execução inline (sem subagentes), TDD por task, plano em [`2026-08-11-frontend-improvements.md`](../superpowers/plans/2026-08-11-frontend-improvements.md).
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

**Decisões do gestor:** aposentar o CDN → **sim** (revertendo a decisão de 07-04, que foi tomada sem os números). Refatorar os 28 `onclick` inline pra remover `'unsafe-inline'` → **adiado** (só vale depois do CDN sair, e toca todo handler interativo).

## Medições — antes e depois

Baseline coletado no `/login` em produção (`00028-lvc`), via `performance.getEntriesByType` e `curl`:

| Métrica | Antes | Depois (esperado) |
|---|---|---|
| Tailwind | 407 KB JS (123 KB gzip), render-blocking, 423 ms, compilando em runtime | 11,6 KB CSS (~3,3 KB gzip), estático |
| `domContentLoaded` | 1128 ms | — verificar pós-deploy |
| Compressão dos estáticos | nenhuma (`transferSize == decodedBodySize`) | gzip |
| `Cache-Control` | ausente (só `etag`, revalidação a cada navegação) | `public, max-age=31536000, immutable` + `?v=K_REVISION` |
| CSP `script-src` | `'unsafe-inline' 'unsafe-eval'` + cdn.tailwindcss.com | `'unsafe-inline'` + unpkg |
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

- `check_pre_push.py` **5/5 verde** em cada um dos 7 commits.
- **Docker não está instalado nesta máquina** — os testes de integração (testcontainers) só rodam no CI. Compensado com uma harness local que renderiza as templates Jinja direto (19 asserts: presença condicional do hambúrguer/drawer, `aria-current` header vs drawer, paridade das duas navs, exact vs prefix, ordem dos stylesheets, `head_extra` no head e não no corpo).
- Build do Tailwind **determinístico** (md5 estável entre execuções) — pré-requisito do guard de diff no CI.
- Guards novos: `tests/unit/test_frontend_a11y_guards.py` (13) + `tests/unit/test_web_static_caching.py` (4) + 2 integration (login sem hambúrguer, drawer com `aria-current`).
- `tests/unit/test_security_headers.py` atualizado: agora **assere a ausência** de `unsafe-eval` e do CDN.

## Smoke autenticado das telas admin (2ª rodada, mesma sessão)

Feito via Claude in Chrome na sessão real do admin. **Só navegação e inspeção** — nenhum controle de mutação foi clicado (dados de produção).

Verificado em prod (`00030-slz`) nas 14 telas (`/`, `/accounts`, `/sessions`, `/audit`, `/help` + as 9 de `/admin`):

- **Zero classes utilitárias sem CSS em todas as 14** — a geração offline do Tailwind está completa (auditado comparando as classes do HTML de cada página contra o CSSOM carregado). Nenhum erro de console, nenhuma violação de CSP.
- Cascata preservada em todas (`h1` sem classe = 14px), `0` `<style>` injetado em runtime, skip link e `aria-current` (header + drawer) presentes em todas.
- `/help`: `v4-help.css` carrega por último via `head_extra`, uma vez só, e o "Voltar ao topo" está em `#6b6b6b` (correção de contraste no ar). O único `<style>` restante na página é injetado pelo **próprio HTMX** (`.htmx-indicator`) — não é nosso, e é mais um motivo pelo qual `style-src 'unsafe-inline'` continua necessário.
- Dropdown de Gestores abre e não é clipado (a exclusão do `.v4-table-wrap` de 07-04 segue correta).

**O smoke encontrou 3 bugs pré-existentes** (F78-F80 no catálogo) — dois deles expostos justamente por eu ter nomeado os offsets como tokens. Corrigidos em `fc8c0a8`, com CI+deploy verdes e re-verificados no ar:

| | Antes | Depois |
|---|---|---|
| `/admin/audit` | filtros em `top:53` **cobrindo a subnav inteira** (subnav cortada em "Aud…") | header 0–65 · subnav 65–120 · filtros 120–208 |
| `/admin/access` | tab bar 12px sob a subnav | subnav 65–120 · tab bar 120–175 |
| `/audit` | cabeçalho de dia 33px sob os filtros | header 0–65 · filtros 65–153 · dia 153–183 |
| Busca das matrizes | ícone sobre o placeholder ("🔍scar gestor…") | "🔍 Buscar gestor…" |

## Pendências

1. **Adiado:** refatorar os 28 `onclick` inline + 6 `hx-on` pra listeners delegados, o que permitiria remover `'unsafe-inline'` de `script-src`. (O `<style>` do HTMX mantém o `'unsafe-inline'` de `style-src` independentemente.)
2. ~~Limitação do `--v4-audit-day-offset` no mobile~~ — **resolvido em `eab6099`** (3ª rodada). Ver abaixo.
3. **Meta OAuth pessoal do Wellington** aparece no painel como "Expira em 27/07/2026 (0 dias)" — a data já passou (hoje é 11/08). É o OAuth dormante (Modelo B usa o system-user token), então não afeta as tools; mas o contador exibindo "0 dias" pra uma data no passado é enganoso. Fora do escopo deste pacote.

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

## Ainda em aberto (decisão de design, não bug)

Com o offset correto, no celular a pilha fixa passa a ser header (61px) + barra de filtros (240px) = **301px**, ~36% de um viewport de 844px. Está *correto* — nada se sobrepõe — mas é muito espaço preso. Se quiser recuperá-lo, a mudança é uma linha, com o trade-off de perder o filtro fixo em telas estreitas:

```css
@media (max-width: 617px) { #audit-filters { position: static; } }
```

O `ResizeObserver` já cobre esse caso: passa a publicar `0` e o cabeçalho de dia sobe automaticamente pro topo logo abaixo do header. Não aplicado — é escolha de produto.
