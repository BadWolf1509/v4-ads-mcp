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

## Pendências

1. **Verificar em produção pós-deploy** (o deploy é gated pelo CI): `content-encoding: gzip` e `cache-control` nos estáticos, 0 ocorrências de `cdn.tailwindcss.com`, `h1` sem classe ainda em 14px, e `domContentLoaded` abaixo dos 1128 ms de baseline.
2. **Guard do Tailwind no CI é a primeira execução** — se `npx tailwindcss@3.4.17` gerar bytes diferentes no Linux, o job falha; nesse caso, regenerar no Linux e commitar.
3. **Adiado:** refatorar os 28 `onclick` inline + 6 `hx-on` pra listeners delegados, o que permitiria remover `'unsafe-inline'` de `script-src`.
4. **Não investigado:** as telas admin com autenticação (matriz de acessos, auditoria global) não foram vistas renderizadas — a investigação cobriu o código de todas, mas o smoke visual só alcançou o `/login` (sem credenciais na sessão).
