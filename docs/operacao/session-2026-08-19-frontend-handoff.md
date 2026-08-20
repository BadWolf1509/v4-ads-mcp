# Sessão 2026-08-19 — Handoff (investigação de frontend → 8 findings fechados)

> Segunda varredura do painel sem escopo prévio, uma semana depois do pacote de frontend de 08-11. **8 achados reais (F101-F108), todos fechados na mesma sessão**, um commit por achado, cada um com guard que falha ANTES do fix. Plano em [`2026-08-19-frontend-findings-fixes.md`](../superpowers/plans/2026-08-19-frontend-findings-fixes.md).
>
> Uma nona hipótese, forte o bastante pra virar task no plano, **caiu na verificação** — está registrada abaixo porque o modo de falha vale mais que o achado teria valido.

## TL;DR

| # | Achado | Commit |
|---|---|---|
| **F101** | Nome acessível da matriz degrada no 1º swap HTMX (F74 na a11y) | `75202f6` |
| **F102** | Logo servido `immutable` por 1 ano sem `?v=`, e baixado 2× | `34a77b4` |
| **F103** | 8 controles de formulário sem nome acessível | `dab2247` |
| **F104 + F105** | 15 `<th>` sem `scope`; `<tr role="button">` achata a linha | `ecd07b7` |
| **F106** | Isenção de CSRF cobria 2 mutações do painel | `59f6694` |
| **F107** | `sessions_revoke` sem HTMX devolvia 200 num POST | `a1d2dd7` |
| **F108** | 9 regras CSS + 2 ramos de JS sem consumidor | `6c9fae3` |
| — | Guard do offset sticky deriva os consumidores do CSS (reforço) | `11675ea` |

`check_pre_push.py` **5/5 verde** em cada commit. Nenhum push — o deploy é decisão do gestor.

## O padrão da sessão

**Os três achados mais graves caíram cada um num ponto cego de um guard que existia e estava verde.**

| Achado | Guard que "cobria" a área | O que ele não olhava |
|---|---|---|
| F101 | `test_fragmento_de_toggle_nao_carrega_handler` | só a ausência de `hx-on`; nada sobre o rótulo |
| F102 | 4 testes de caching de assets | o header da resposta, nunca a cobertura do `?v=` no consumidor |
| offset sticky | `test_barra_de_filtros_..._medida_em_runtime` | citava `audit.html` pelo nome; `/admin/audit` fora |

A lição operacional não é "faltavam guards" — é que **guard verde não é cobertura**. Ao herdar uma área com guard, a pergunta útil é "o que este guard NÃO olha", não "existe guard?". Nos três casos a resposta apareceu em menos de um minuto de leitura do próprio teste.

Consequência de método adotada nos fixes: onde deu, o guard passou a **derivar** o alvo em vez de listá-lo. O de offset sticky varre quem consome `--v4-filter-bar-h` no template; o de asset varre toda referência a `/static`; o de nome acessível varre todo controle de formulário. Lista escrita à mão envelhece; derivação não.

## O achado que não existia

A barra de filtros de `/admin/audit` parecia não ter `data-sticky-measure`. Se fosse verdade, `--v4-filter-bar-h` ficaria no fallback de 88px — aferido na barra **flex** do `/audit`, não naquele **grid de 5 colunas**, que entre 640px e 767px tem 3 linhas — e o `<thead>` sticky sumiria sob a barra nessa faixa. Diagnóstico plausível, com a aritmética fechando e a classe F79 como precedente.

**Era falso.** O atributo está na **linha 16**, na abertura do `<form>`, desde o F97. Duas coisas se somaram:

1. A leitura do arquivo começou na **linha 20** (`sed -n '20,75p'`), então a linha do atributo nunca entrou no campo de visão.
2. O comentário do F97, que está ali para explicar **por que a medição é necessária naquele grid**, foi lido como se admitisse a ausência dela — "o literal de `v4-tokens.css` foi aferido na barra de `/audit`, não neste grid" descreve a *motivação* do `data-sticky-measure`, não uma lacuna.

O erro só apareceu porque **o guard passou de primeira** e isso foi tratado como sinal de alerta em vez de sucesso. Investigar *por que* passou levou ao arquivo inteiro em 30 segundos. O CLAUDE.md já manda desconfiar de guard que passa de primeira; aqui a regra pegou um falso positivo do investigador, não um guard fraco — o que amplia o uso dela.

O guard novo ficou assim mesmo, e vale por si: o antigo citava `audit.html` pelo nome, então **remover `data-sticky-measure` de `/admin/audit` não falhava teste nenhum**.

## Detalhe dos dois fixes com decisão de desenho

### F101 — o rótulo saiu do nó trocado

O fragmento servido por `/admin/access/toggle` atende **quatro** templates com duas estratégias de rótulo:

- matrizes (`access.html`, `access_meta.html`) → `aria-label="Acesso de {gestor} à conta {conta}"`;
- views por gestor (`access_manager_detail*.html`) → nome vem do `<label>` que embrulha o input.

O fragmento emitia `aria-label="Alternar acesso"` e não casava com nenhuma. Pior no detail: `aria-label` **vence** o `<label>` na computação do nome acessível, então depois do primeiro toggle o texto visível dizia "Mestre da Obra JP" e o leitor de tela dizia "Alternar acesso" — e é justamente a view que a matriz recomenda no celular.

Duas saídas possíveis:

1. **A rota computa o texto.** Um `fetchrow` a mais por toggle, e o formato do rótulo duplicado entre template e rota — exatamente a divergência que se quer eliminar, agora vigiada por um teste.
2. **O rótulo sai do nó trocado.** `aria-labelledby="v4-mgr-<id> v4-acc-<id>"`, apontando pro cabeçalho do gestor e pro da conta. O valor é **função pura dos dois ids que já chegam no form**.

Foi a segunda. Sem leitura de banco, sem texto duplicado, e a divergência deixa de ser possível em vez de ser vigiada — mesma estratégia do F74, que resolveu o handler tirando-o do fragmento em vez de exigir que ele fosse re-emitido.

Efeito colateral bom: a assinatura perdeu o `vals: dict` (que já continha o `manager_id`) e ganhou `manager_id`/`account_id`/`account_field`, acabando com a redundância.

**Armadilha que quase passou:** existia `tests/unit/test_toggle_fragment_escape.py` usando a assinatura antiga. O CLAUDE.md avisa em duas linhas separadas pra grepar todos os patch-sites em `tests/` ao mexer numa função — e mesmo assim escapou na primeira passada. Pego pelo `check_pre_push`, não pelo cuidado. O teste ficou melhor depois: o id injetado agora alimenta **dois** atributos, então o escape é assertado nos dois.

### F106 — isenção de CSRF por rota, não por prefixo

`_CSRF_EXEMPT_PREFIXES` isentava `/oauth/` inteiro. O comentário justificava com "callbacks (GET) ou o data-deletion POST que valida o próprio HMAC" — mas `POST /oauth/meta/revoke` e `POST /oauth/meta/refresh-accounts` são **mutações do painel autenticadas por cookie**, disparadas por `<form method="post">` em `admin/index.html`. Vivem sob `/oauth` por acidente de roteamento: o `APIRouter` do Meta tem `prefix="/oauth/meta"`.

**Não era explorável.** SameSite=Lax não manda o cookie num POST cross-site, e o docstring da própria classe diz que essa é a defesa primária e que a checagem de origem é defense-in-depth. Mas a segunda camada existe pra não depender da primeira, e ali não se aplicava.

A isenção passou a ser por rota: `("/oauth/meta/data-deletion-callback", "/mcp")`. Os demais endpoints OAuth são GET — método seguro, nunca checado —, então a isenção larga não protegia nada que precisasse dela.

**Lição que generaliza:** isenção por prefixo herda automaticamente tudo que um roteador com `prefix=` vier a pendurar ali depois. A rota nova entra na isenção sem passar por revisão nenhuma.

## Verificação

- `check_pre_push.py` **5/5** em cada um dos 8 commits.
- **Docker não está instalado nesta máquina** — os testes de integração só rodam no CI. Todo guard novo é unit (grep/AST sobre o source, ou chamada direta da função), exceto um: `test_sessions_revoke_sem_htmx_redireciona`, que é integração de propósito, porque a forma da resposta merece um teste comportamental além do estrutural.
- Build do Tailwind rodado a cada commit que tocou template; **o CSS gerado não mudou** (md5 estável, `git status` limpo) — as mudanças foram atributos (`id`, `aria-*`, `scope`, `?v=`), não classes utilitárias.
- Balanço de chaves conferido em todos os CSS depois da remoção do F108.
- Guards novos: **13** (4 parametrizados de rótulo + 1 de fragmento + 1 de cache-buster + 1 de nome acessível + 1 de `scope` + 1 de `role=button` + 7 parametrizados de classe morta + 1 de JS morto + 3 de CSRF + 2 de redirect).

## O que foi verificado e estava limpo

Vale registrar o negativo — foram várias horas de varredura que **não** viraram achado:

- **CSP e inline:** zero JS/CSS inline nas templates, nenhuma diretiva `unsafe-*` na política. Intactos desde 08-11.
- **Classes órfãs:** nenhuma classe `v4-*` usada em template sem regra CSS (o inverso, regra sem uso, virou o F108).
- **Links:** nenhuma das 48 URLs distintas das templates sem rota correspondente (47 rotas declaradas, contando os prefixos `/oauth/*`).
- **Contexto de template:** nenhuma variável exigida por template faltando nas 26 chamadas de `TemplateResponse` (varredura por `jinja2.meta.find_undeclared_variables` cruzada com AST das rotas). `asset_version` é global do Jinja, registrado no import.
- **XSS:** todo `|safe` recebe literal ou o mapa fixo do flash; `request.query_params` nunca chega na macro `alert`; o `{{ reason }}` dentro de comentário HTML em `access_denied.html` está num branch de enum fechado (e `>` é escapado de qualquer forma).
- **A11y mecânica:** nenhum `id` duplicado, nenhum `<img>` sem `alt`, nenhum `<button>` sem nome acessível.
- **Token de sessão:** cookie httponly, `SameSite=strict`, path-scoped na página de detalhe, 60s. Nunca em query param.

## Pendente

Nada deste pacote. Os 8 estão fechados e commitados na `main`, **sem push** — subir dispara o deploy gated pelo CI, e essa é decisão do gestor.
