# Correções dos achados da investigação de frontend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) ou superpowers:executing-plans para implementar task-a-task. Os passos usam checkbox (`- [ ]`).

**Goal:** Fechar os 9 achados da investigação de frontend de 2026-08-19 — dois bugs funcionais (rótulo acessível que degrada no swap HTMX, offset sticky nunca medido), um de entrega de asset, quatro de acessibilidade, um de defesa em profundidade e uma limpeza de código morto — cada um com um guard que falha ANTES do fix.

**Architecture:** Nenhuma mudança de arquitetura. O painel segue Jinja2 + HTMX + CSS próprio, sem build step no runtime. A correção central (Task 1) troca `aria-label` com texto duplicado por `aria-labelledby` derivado dos ids que a rota **já recebe** — o nome acessível passa a viver uma única vez no DOM, fora do nó trocado, o que torna a divergência entre template e fragmento impossível por construção. É a lição do F74 aplicada ao rótulo.

**Tech Stack:** Jinja2 · HTMX 2.0.3 · Tailwind CSS 3.4.17 (gerado offline) · FastAPI/Starlette · pytest

**Spec:** não há spec separada — a investigação está no relatório da sessão 2026-08-19 e vira `docs/operacao/session-2026-08-19-frontend-handoff.md` na Task 9.

## Global Constraints

- **ZERO JavaScript e ZERO CSS inline em template.** A CSP não tem nenhuma diretiva `unsafe-*`; `on*=`, `hx-on`, `<script>` sem `src` e `style=` são bloqueados pelo browser em silêncio. Comportamento vai em `v4-panel.js` via `data-v4-*`; estilo vai em classe.
- **`v4-tailwind.css` é o ÚLTIMO stylesheet do `<head>`.** Não reordenar os `<link>` — o Preflight precisa vencer o `v4-base.css`.
- **Mexeu em classe utilitária de template?** Rodar `python scripts/build_tailwind.py` e **commitar o CSS no mesmo commit** (o CI faz `git diff --exit-code`). O scanner lê o arquivo inteiro, comentários incluídos — não citar nome de utilitário em comentário.
- **Recurso externo novo exige atualizar `_CSP_POLICY`** no mesmo commit.
- Copy em **PT-BR**, sentence case.
- Verificação antes de CADA commit: `python scripts/check_pre_push.py` (5/5 verde).
- Docker não está instalado nesta máquina: os testes de integração (testcontainers) só rodam no CI. Todo guard novo deve ser **unit** (grep/AST sobre o source, ou render direto), não integration.
- Commits: `fix(scope): …` / `chore: …` / `docs: …`, com trailer `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

### Task 1: Rótulo acessível da matriz de acessos sobrevive ao swap

`_toggle_checkbox_fragment` serve `aria-label="Alternar acesso"` para **quatro** templates com duas estratégias de rótulo diferentes. Em `access.html`/`access_meta.html` o original diz "Acesso de {gestor} à conta {conta}"; em `access_manager_detail*.html` o nome vem de um `<label>` que embrulha o input. Depois do primeiro toggle, todos viram "Alternar acesso" — e no detail o `aria-label` **vence** o `<label>`, então o texto visível e o nome acessível passam a discordar.

**Fix:** o fragmento deixa de carregar texto. Passa a emitir `aria-labelledby="v4-mgr-<manager_id> v4-acc-<account_id>"`, valor que é função pura dos dois ids que a rota já recebe no form. Os quatro templates emitem o MESMO atributo no HTML inicial e ganham os ids nos elementos que já contêm o nome do gestor e o da conta. Zero leitura extra de banco, zero texto duplicado.

**Files:**
- Modify: `src/web/routes.py:98-114` (`_toggle_checkbox_fragment`), `:1385-1391` (call site Google), `:1075-1081` (call site Meta)
- Modify: `src/web/templates/admin/access.html:46,55,61-68`
- Modify: `src/web/templates/admin/access_meta.html:46,55,61-74`
- Modify: `src/web/templates/admin/access_manager_detail.html:14,20-32`
- Modify: `src/web/templates/admin/access_manager_detail_meta.html:14,20-35`
- Test: `tests/unit/test_frontend_a11y_guards.py`

**Interfaces:**
- Produces: `_toggle_checkbox_fragment(*, post_url: str, manager_id: str, account_id: str, account_field: str, checked: bool) -> str` — assinatura NOVA (o antigo `vals: dict` sai; o dict passa a ser montado dentro a partir de `account_field`, que vale `"customer_id"` no Google e `"ad_account_id"` no Meta).

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/unit/test_frontend_a11y_guards.py`, no fim do arquivo:

```python
_TEMPLATES_COM_TOGGLE = [
    "admin/access.html",
    "admin/access_meta.html",
    "admin/access_manager_detail.html",
    "admin/access_manager_detail_meta.html",
]


@pytest.mark.parametrize("caminho", _TEMPLATES_COM_TOGGLE)
def test_checkbox_de_acesso_referencia_rotulo_fora_do_no_trocado(caminho):
    """O swap troca o proprio <input>, entao o nome acessivel nao pode morar nele.

    Era `aria-label` com texto: o fragmento servido pela rota nao tinha como
    reproduzi-lo e todo checkbox virava "Alternar acesso" depois do 1o toggle.
    """
    html = (_TEMPLATES / caminho).read_text(encoding="utf-8")
    assert "data-v4-access-toggle" in html, f"{caminho}: template sem checkbox de acesso"
    assert 'aria-labelledby="v4-mgr-' in html, (
        f"{caminho}: o checkbox precisa referenciar o rotulo por id (aria-labelledby)"
    )
    assert 'id="v4-mgr-' in html, f"{caminho}: falta o id do gestor referenciado"
    assert 'id="v4-acc-' in html, f"{caminho}: falta o id da conta referenciado"


def test_fragmento_de_toggle_rotula_pelos_mesmos_ids():
    """Paridade por construcao: o atributo e funcao pura dos ids que a rota recebe."""
    from src.web.routes import _toggle_checkbox_fragment

    frag = _toggle_checkbox_fragment(
        post_url="/admin/access/toggle",
        manager_id="11111111-1111-1111-1111-111111111111",
        account_id="9876543210",
        account_field="customer_id",
        checked=True,
    )
    assert (
        'aria-labelledby="v4-mgr-11111111-1111-1111-1111-111111111111 v4-acc-9876543210"' in frag
    )
    assert "aria-label=" not in frag.replace("aria-labelledby=", "")
    assert '"customer_id": "9876543210"' in frag.replace("&quot;", '"')
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_frontend_a11y_guards.py -k "rotul" -q`
Expected: FAIL — 4 falhas de `aria-labelledby` ausente + `TypeError` no fragmento (assinatura antiga exige `vals`).

- [ ] **Step 3: Reescrever o fragmento**

Em `src/web/routes.py`, substituir a função inteira:

```python
def _toggle_checkbox_fragment(
    *,
    post_url: str,
    manager_id: str,
    account_id: str,
    account_field: str,
    checked: bool,
) -> str:
    """Checkbox de reposição servido após o toggle de acesso.

    O comportamento (toast, revert-on-fail) vive num listener delegado em
    v4-panel.js acionado por `data-v4-access-toggle` — era o F74.

    O NOME ACESSÍVEL segue a mesma regra: `aria-label` com texto obrigava a
    rota a reproduzir o que o template escreve, e ela não reproduzia — todo
    checkbox virava "Alternar acesso" depois do primeiro toggle. Agora o nome
    vem por `aria-labelledby`, apontando pro cabeçalho do gestor e pro da
    conta, que estão FORA do nó trocado. O valor é função pura dos dois ids
    que já chegam no form, então template e fragmento não têm como divergir.
    """
    state = "checked " if checked else ""
    vals = {"manager_id": manager_id, account_field: account_id}
    hx_vals = html.escape(json.dumps(vals), quote=True)
    rotulo = html.escape(f"v4-mgr-{manager_id} v4-acc-{account_id}", quote=True)
    return (
        f'<input type="checkbox" {state}hx-post="{post_url}" '
        f'hx-vals=\'{hx_vals}\' hx-trigger="change" hx-swap="outerHTML" '
        f'data-v4-access-toggle aria-labelledby="{rotulo}">'
    )
```

- [ ] **Step 4: Atualizar os dois call sites**

`src/web/routes.py`, rota `admin_access_toggle`:

```python
    return HTMLResponse(
        _toggle_checkbox_fragment(
            post_url="/admin/access/toggle",
            manager_id=manager_id,
            account_id=customer_id,
            account_field="customer_id",
            checked=granted,
        )
    )
```

Rota `admin_access_meta_toggle`:

```python
    return HTMLResponse(
        _toggle_checkbox_fragment(
            post_url="/admin/access/meta/toggle",
            manager_id=manager_id,
            account_id=ad_account_id,
            account_field="ad_account_id",
            checked=granted,
        )
    )
```

- [ ] **Step 5: Dar ids aos rótulos e trocar o atributo nos 4 templates**

`admin/access.html` — cabeçalho de coluna (gestor), cabeçalho de linha (conta) e o input:

```jinja
            <th scope="col" class="text-center min-w-[120px]" id="v4-mgr-{{ m.id }}" data-manager-email="{{ m.email|lower }}">
```

```jinja
          <th scope="row" id="v4-acc-{{ a.customer_id }}" class="sticky left-0 bg-white whitespace-nowrap">
```

```jinja
            <input type="checkbox"
                   aria-labelledby="v4-mgr-{{ m.id }} v4-acc-{{ a.customer_id }}"
                   {% if (m.id|string, a.customer_id) in access_set %}checked{% endif %}
```

`admin/access_meta.html` — idêntico, trocando `a.customer_id` por `a.ad_account_id`.

`admin/access_manager_detail.html` — o `<h1>` já tem o email do gestor e o `<strong>` já tem o nome da conta:

```jinja
    <h1 class="text-2xl font-bold" id="v4-mgr-{{ manager.id }}">{{ manager.email }}</h1>
```

```jinja
      <input type="checkbox"
             aria-labelledby="v4-mgr-{{ manager.id }} v4-acc-{{ a.customer_id }}"
             {% if a.customer_id in access_set %}checked{% endif %}
```

```jinja
      <div class="flex-1">
        <strong id="v4-acc-{{ a.customer_id }}">{{ a.descriptive_name }}</strong>
```

`admin/access_manager_detail_meta.html` — idêntico, com `a.ad_account_id` e `a.account_name`.

- [ ] **Step 6: Rodar e confirmar que passa**

Run: `python -m pytest tests/unit/test_frontend_a11y_guards.py -q`
Expected: PASS (todos).

- [ ] **Step 7: Regenerar o Tailwind e verificar**

```bash
python scripts/build_tailwind.py
python scripts/check_pre_push.py
```

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "fix(web): rotulo acessivel da matriz sobrevive ao swap HTMX"
```

---

### Task 2: `/admin/audit` mede a própria barra de filtros

`.v4-table--sticky-head-under-filters` calcula o offset com `var(--v4-filter-bar-h)`, e o comentário no CSS afirma que esse valor é medido em runtime pelo `[data-sticky-measure]`. Só que `admin/audit.html` — **o único consumidor da classe** — não tem o atributo. O `ResizeObserver` de `v4-panel.js` sai cedo e o valor fica no fallback de 88px, aferido na barra **flex do `/audit`**. A barra do admin é `grid grid-cols-2 md:grid-cols-5`: entre 640px e 767px ela é sticky e tem 3 linhas, então o `<thead>` gruda alto demais e some sob a barra.

**Files:**
- Modify: `src/web/templates/admin/audit.html:16-25`
- Test: `tests/unit/test_frontend_a11y_guards.py:215-226`

**Interfaces:**
- Consumes: nada da Task 1. Produces: nada.

- [ ] **Step 1: Escrever o teste que falha**

Substituir `test_barra_de_filtros_da_auditoria_e_medida_em_runtime` por uma versão que deriva o alvo do CSS em vez de listar uma página:

```python
def test_toda_barra_que_alimenta_offset_sticky_e_medida():
    """A barra embrulha (88/164/240px) em pontos que nao sao breakpoints padrao.

    Quem gruda embaixo dela (cabecalho de dia em /audit, thead em /admin/audit)
    tira o offset de --v4-filter-bar-h, que so existe se o ResizeObserver achar
    um [data-sticky-measure] NA PAGINA. Sem o atributo o valor fica no fallback
    de v4-tokens.css, aferido em OUTRA barra. Ver F79.
    """
    js = (_STATIC / "v4-panel.js").read_text(encoding="utf-8")
    assert "ResizeObserver" in js
    assert "--v4-filter-bar-h" in js

    css = (_STATIC / "v4-components.css").read_text(encoding="utf-8")
    assert "var(--v4-filter-bar-h)" in css, "quem consome o token mudou de nome"

    for template in _TEMPLATES.rglob("*.html"):
        conteudo = template.read_text(encoding="utf-8")
        consome = (
            "v4-table--sticky-head-under-filters" in conteudo
            or "var(--v4-audit-day-offset)" in conteudo
        )
        if consome:
            assert "data-sticky-measure" in conteudo, (
                f"{template.name}: usa offset derivado de --v4-filter-bar-h mas nao "
                "marca a barra com data-sticky-measure — o valor fica no fallback"
            )
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_frontend_a11y_guards.py -k medida -q`
Expected: FAIL — `audit.html: usa offset derivado ... mas nao marca a barra` para `admin/audit.html`.

- [ ] **Step 3: Marcar a barra do admin**

Em `src/web/templates/admin/audit.html`, no `<form>` de filtros, adicionar `data-sticky-measure`:

```jinja
  <form method="GET" action="/admin/audit" data-sticky-measure
```

E trocar o comentário que dizia que o literal foi aferido em outra barra por:

```jinja
        {# data-sticky-measure: esta barra e um grid de 5 colunas que vira 3
           LINHAS entre 640px e 767px — o fallback de 88px de v4-tokens.css foi
           aferido na barra flex do /audit e nao serve aqui. O thead abaixo tira
           o offset de --v4-filter-bar-h, entao ela precisa ser MEDIDA. #}
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/unit/test_frontend_a11y_guards.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
python scripts/check_pre_push.py && git add -A && git commit -m "fix(web): barra de filtros do /admin/audit passa a ser medida"
```

---

### Task 3: Todo asset estático servido `immutable` carrega `?v=`

`CachedStaticFiles` marca **todo** `/static` como `public, max-age=31536000, immutable`. O docstring do módulo declara a invariante: só é seguro porque as URLs levam `?v=`. Duas não levam — o logo do header (`_base.html:69`, toda página autenticada) e o do hero de login. Efeito duplo: trocar o logo não chega em quem já visitou, e como o favicon usa a MESMA URL com `?v=`, o arquivo é baixado duas vezes sob chaves de cache distintas.

**Files:**
- Modify: `src/web/templates/_base.html:69`, `src/web/templates/login.html:7`
- Test: `tests/unit/test_web_static_caching.py`

**Interfaces:**
- Consumes: nada. Produces: nada.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/unit/test_web_static_caching.py` (adicionar `import re` no topo):

```python
_TEMPLATES = Path(__file__).resolve().parents[2] / "src" / "web" / "templates"


def test_toda_referencia_a_static_carrega_cache_buster():
    """immutable por 1 ano sem ?v= = asset preso pra sempre no browser.

    CachedStaticFiles marca TUDO sob /static como immutable, e o docstring do
    modulo condiciona isso a versionar as URLs. O logo escapava em dois lugares
    — e como o favicon usa a mesma URL COM ?v=, o arquivo era baixado duas
    vezes sob chaves de cache diferentes.
    """
    faltando = []
    for template in _TEMPLATES.rglob("*.html"):
        for numero, linha in enumerate(template.read_text(encoding="utf-8").split("\n"), 1):
            for url in re.findall(r'(?:href|src)="(/static/[^"]+)"', linha):
                if "?v=" not in url:
                    faltando.append(f"{template.name}:{numero} {url}")
    assert not faltando, "referencias a /static sem ?v=: " + "; ".join(faltando)
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_web_static_caching.py -k cache_buster -q`
Expected: FAIL listando `_base.html:69` e `login.html:7`.

- [ ] **Step 3: Versionar as duas URLs**

`src/web/templates/_base.html:69`:

```jinja
      <img src="/static/logo/logo_v4_puro_round.svg?v={{ asset_version }}" class="v4-header__logo" alt="V4">
```

`src/web/templates/login.html:7`:

```jinja
  <img src="/static/logo/logo_v4_puro_round.svg?v={{ asset_version }}" alt="V4" class="h-12 w-auto mb-10">
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/unit/test_web_static_caching.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
python scripts/check_pre_push.py && git add -A && git commit -m "fix(web): logo entra no cache-busting dos estaticos"
```

---

### Task 4: Todo controle de formulário tem nome acessível

Oito controles sem nome. Em `admin/audit.html` os cinco `<label class="v4-form__label">` não têm `for=`, os `<select>` não têm `id`, e o label não embrulha — o rótulo visual está ali e simplesmente não está ligado (a página irmã `/audit` faz certo, com os mesmos filtros). Em `admin/accounts.html` e `admin/managers.html` os três selects de filtro não têm label nenhum nem `aria-label`, ao lado de um `search_input` que recebe `aria_label` pela macro.

**Files:**
- Modify: `src/web/templates/admin/audit.html:26-68`
- Modify: `src/web/templates/admin/accounts.html:17`
- Modify: `src/web/templates/admin/managers.html:19,24`
- Test: `tests/unit/test_frontend_a11y_guards.py`

**Interfaces:**
- Consumes: Task 2 já tocou o `<form>` de `admin/audit.html` — executar T2 antes. Produces: nada.

- [ ] **Step 1: Escrever o teste que falha**

```python
def test_todo_controle_de_formulario_tem_nome_acessivel():
    """select/input/textarea sem <label for>, sem aria-label e sem label que
    embrulha e anunciado como "caixa de combinacao" sem nome nenhum."""
    sem_nome = []
    for template in _TEMPLATES.rglob("*.html"):
        conteudo = template.read_text(encoding="utf-8")
        labels_for = set(re.findall(r'<label[^>]*\bfor="([^"]+)"', conteudo))
        embrulhados = re.findall(r"<label\b[^>]*>.*?</label>", conteudo, re.S)
        for numero, linha in enumerate(conteudo.split("\n"), 1):
            for tag, attrs in re.findall(r"<(select|textarea|input)\b([^>]*)>", linha):
                tipo = re.search(r'type="([^"]+)"', attrs)
                if tag == "input" and tipo and tipo.group(1) in ("hidden", "submit"):
                    continue
                if "aria-label" in attrs:
                    continue
                identificador = re.search(r'\bid="([^"]+)"', attrs)
                if identificador and identificador.group(1) in labels_for:
                    continue
                if any(f"<{tag}{attrs}>" in bloco for bloco in embrulhados):
                    continue
                sem_nome.append(f"{template.name}:{numero} <{tag}>")
    assert not sem_nome, "controles sem nome acessivel: " + "; ".join(sem_nome)
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_frontend_a11y_guards.py -k nome_acessivel -q`
Expected: FAIL listando os 8 (`audit.html` ×5, `accounts.html` ×1, `managers.html` ×2).

- [ ] **Step 3: Ligar os cinco labels do /admin/audit**

Para cada um dos 5 grupos, adicionar `for=` no label e `id=` no select (mesmo par que `/audit` já usa):

```jinja
      <label class="v4-form__label" for="manager_id">Gestor</label>
      <select id="manager_id" name="manager_id" class="v4-select" data-v4-autosubmit>
```

Repetir com os pares `customer_id`, `action_type`, `status`, `days`.

- [ ] **Step 4: Nomear os três selects de filtro**

`src/web/templates/admin/accounts.html:17`:

```jinja
      <select id="mcc-filter" aria-label="Filtrar contas por MCC" data-v4-filter="#adm-accs-table" data-v4-filter-field="mcc" class="v4-select w-[200px]">
```

`src/web/templates/admin/managers.html:19` e `:24`:

```jinja
      <select id="mgr-role" aria-label="Filtrar gestores por role" data-v4-filter="#managers-table" data-v4-filter-field="role" class="v4-select w-[140px]">
```

```jinja
      <select id="mgr-status" aria-label="Filtrar gestores por status" data-v4-filter="#managers-table" data-v4-filter-field="status" class="v4-select w-[140px]">
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `python -m pytest tests/unit/test_frontend_a11y_guards.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
python scripts/check_pre_push.py && git add -A && git commit -m "fix(web): controles de filtro ganham nome acessivel"
```

---

### Task 5: Cabeçalho de tabela declara `scope`, e linha expansível volta a ser linha

Dois defeitos de semântica de tabela. (a) 15 `<th>` sem `scope` em 4 templates — todas as outras tabelas usam `scope="col"`. (b) `audit.html` põe `role="button"` no `<tr>` expansível: resolve o teclado, mas pela spec ARIA os filhos de um `button` são presentacionais, então a linha inteira vira um nome só e a associação com os `<th scope="col">` se perde. `tabindex="0"` + `aria-expanded` (suportado em `role=row`) mantém o teclado sem destruir a tabela.

**Files:**
- Modify: `src/web/templates/accounts.html:69-71`, `dashboard.html:85-88`, `admin/index.html:212-214`, `admin/invites.html:38-42`
- Modify: `src/web/templates/audit.html:92-94`
- Test: `tests/unit/test_frontend_a11y_guards.py`

**Interfaces:**
- Consumes: nada. Produces: nada.

- [ ] **Step 1: Escrever os testes que falham**

```python
def test_todo_th_declara_scope():
    """Sem scope o leitor de tela nao associa celula a cabecalho em tabela de dados."""
    sem_scope = []
    for template in _TEMPLATES.rglob("*.html"):
        for numero, linha in enumerate(template.read_text(encoding="utf-8").split("\n"), 1):
            for attrs in re.findall(r"<th\b([^>]*)>", linha):
                if "scope=" not in attrs:
                    sem_scope.append(f"{template.name}:{numero}")
    assert not sem_scope, "<th> sem scope: " + "; ".join(sem_scope)


def test_linha_expansivel_nao_vira_button():
    """role=button torna os filhos PRESENTACIONAIS: a linha inteira vira um nome
    so e a associacao com os <th scope=col> some. tabindex + aria-expanded
    (suportado em role=row) mantem o teclado sem quebrar a tabela."""
    for template in _TEMPLATES.rglob("*.html"):
        conteudo = template.read_text(encoding="utf-8")
        for bloco in re.findall(r"<tr\b[^>]*>", conteudo):
            assert 'role="button"' not in bloco, (
                f"{template.name}: <tr role=button> achata a linha pro leitor de tela"
            )
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_frontend_a11y_guards.py -k "scope or expansivel" -q`
Expected: FAIL — 15 `<th>` listados e 1 `<tr role="button">`.

- [ ] **Step 3: Declarar `scope="col"` nos 15 `<th>`**

Trocar `<th>` por `<th scope="col">` em `accounts.html:69-71`, `dashboard.html:85-88`, `admin/index.html:212-214`, `admin/invites.html:38-42`.

- [ ] **Step 4: Tirar o `role=button` da linha expansível**

Em `src/web/templates/audit.html`:

```jinja
          {# tabindex + o handler de Enter/Espaco em v4-panel.js dao o teclado.
             SEM role=button: ele tornaria as celulas presentacionais e a linha
             perderia a associacao com os <th scope="col">. aria-expanded e
             suportado em role=row. #}
          <tr id="row-{{ r.id }}" class="is-expandable"
              data-v4-action="row-toggle" data-v4-target="row-{{ r.id }}"
              tabindex="0" aria-expanded="false">
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `python -m pytest tests/unit/test_frontend_a11y_guards.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
python scripts/check_pre_push.py && git add -A && git commit -m "fix(web): semantica de tabela (scope em th, tr deixa de ser button)"
```

---

### Task 6: Isenção de CSRF cobre só quem precisa dela

`_CSRF_EXEMPT_PREFIXES` isenta o prefixo `/oauth/` inteiro, justificado no comentário por "callbacks (GET) ou o data-deletion POST que valida o próprio HMAC". Mas `POST /oauth/meta/revoke` e `POST /oauth/meta/refresh-accounts` são ações do painel autenticadas por cookie (`Depends(current_manager)`), disparadas por `<form method="post">` em `admin/index.html`. Não é explorável hoje — SameSite=Lax não manda o cookie num POST cross-site, que é a defesa primária declarada — mas é exatamente a camada de defense-in-depth que existe e que não se aplica ali. Os GETs (`/start`, `/callback`) nunca são checados: método seguro.

**Files:**
- Modify: `src/web/middleware.py:12-15`
- Test: `tests/unit/test_csrf_middleware.py`

**Interfaces:**
- Produces: `_CSRF_EXEMPT_PREFIXES = ("/oauth/meta/data-deletion-callback", "/mcp")`

- [ ] **Step 1: Escrever o teste que falha**

Adicionar as rotas ao app de teste:

```python
    @a.post("/oauth/meta/revoke")
    async def meta_revoke() -> dict[str, bool]:
        return {"ok": True}

    @a.post("/oauth/meta/data-deletion-callback")
    async def data_deletion() -> dict[str, bool]:
        return {"ok": True}
```

E os casos:

```python
@pytest.mark.asyncio
async def test_mutacao_do_painel_sob_oauth_nao_e_isenta():
    """revoke e refresh-accounts sao acoes do painel autenticadas por COOKIE.

    A isencao de /oauth existe pro callback de data-deletion, que valida o
    proprio HMAC — nao pra mutacao de painel. Origin divergente tem que bater
    no 403 como qualquer outro POST de cookie.
    """
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://testserver") as c:
        r = await c.post(
            "/oauth/meta/revoke", headers={"origin": "http://evil.com", "host": "testserver"}
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_callback_de_data_deletion_segue_isento():
    """Server-to-server da Meta, com HMAC proprio no signed_request."""
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://testserver") as c:
        r = await c.post(
            "/oauth/meta/data-deletion-callback",
            headers={"origin": "https://facebook.com", "host": "testserver"},
        )
    assert r.status_code == 200
```

Ajustar o teste existente que usa `/oauth/callback` para refletir a política nova (passa a esperar 403 com Origin divergente).

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_csrf_middleware.py -q`
Expected: FAIL — `assert 200 == 403` no revoke (hoje isento).

- [ ] **Step 3: Estreitar a isenção**

Em `src/web/middleware.py`:

```python
# Isento: só o callback de exclusão de dados da Meta (POST server-to-server que
# valida o próprio HMAC no signed_request) e o endpoint MCP (auth por Bearer, não
# por cookie). O prefixo `/oauth/` inteiro era largo demais: `/oauth/meta/revoke` e
# `/oauth/meta/refresh-accounts` são mutações do PAINEL autenticadas por cookie e
# precisam da checagem. Os demais endpoints OAuth são GET — método seguro, nunca
# checado.
_CSRF_EXEMPT_PREFIXES = ("/oauth/meta/data-deletion-callback", "/mcp")
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/unit/test_csrf_middleware.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
python scripts/check_pre_push.py && git add -A && git commit -m "fix(security): isencao de CSRF deixa de cobrir mutacoes do painel"
```

---

### Task 7: `sessions_revoke` sem HTMX volta a respeitar POST-redirect-GET

O ramo final de `sessions_revoke` renderiza `sessions/list.html` com 200 num POST: recarregar a página re-executa a revogação. A convenção do projeto (e o próprio ramo HTMX da rota) é `303` quando não é HTMX. De quebra, a lista é buscada do banco duas vezes no caminho HTMX-da-lista.

**Files:**
- Modify: `src/web/routes.py:473-530`
- Test: `tests/unit/test_sessions_revoke_redirect.py` (novo)

**Interfaces:**
- Consumes: nada. Produces: nada.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/unit/test_sessions_revoke_redirect.py`:

```python
"""POST-redirect-GET no revoke sem HTMX (sem DB — inspeciona o codigo da rota).

Rodar o handler exigiria pool + grants; o que importa aqui e a FORMA da
resposta no ramo nao-HTMX, e ela e estatica no source.
"""

import ast
from pathlib import Path

_ROTAS = Path(__file__).resolve().parents[2] / "src" / "web" / "routes.py"


def _funcao(nome: str) -> ast.AsyncFunctionDef:
    arvore = ast.parse(_ROTAS.read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if isinstance(no, ast.AsyncFunctionDef) and no.name == nome:
            return no
    raise AssertionError(f"{nome} nao encontrada em routes.py")


def test_revoke_sem_htmx_redireciona_em_vez_de_renderizar():
    """Renderizar a lista com 200 num POST faz o refresh re-executar a acao."""
    funcao = _funcao("sessions_revoke")
    renders = [
        no
        for no in ast.walk(funcao)
        if isinstance(no, ast.Call)
        and isinstance(no.func, ast.Attribute)
        and no.func.attr == "TemplateResponse"
    ]
    assert len(renders) == 1, (
        "o ramo nao-HTMX nao pode renderizar template: so o fragmento da lista "
        "(caminho HTMX) deve usar TemplateResponse"
    )
    redirects = [
        no
        for no in ast.walk(funcao)
        if isinstance(no, ast.Call)
        and isinstance(no.func, ast.Name)
        and no.func.id == "RedirectResponse"
    ]
    assert redirects, "o ramo nao-HTMX precisa de RedirectResponse"
    codigos = {
        kw.value.value
        for chamada in redirects
        for kw in chamada.keywords
        if kw.arg == "status_code" and isinstance(kw.value, ast.Constant)
    }
    assert codigos == {303}, f"POST-redirect-GET exige 303, achei {codigos}"
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_sessions_revoke_redirect.py -q`
Expected: FAIL — 2 `TemplateResponse` e nenhum `RedirectResponse`.

- [ ] **Step 3: Trocar o ramo final por 303 e remover a query duplicada**

Apagar a pré-busca de `sessions` no primeiro bloco (só o ramo HTMX-da-lista usa a lista, e ele a busca de novo com o `include_revoked` certo). Substituir o `return templates.TemplateResponse(...)` final por:

```python
    # Sem HTMX: POST-redirect-GET. Renderizar a lista com 200 faria o refresh
    # re-executar a revogacao.
    return RedirectResponse(url="/sessions", status_code=303)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/unit/test_sessions_revoke_redirect.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
python scripts/check_pre_push.py && git add -A && git commit -m "fix(web): revoke de sessao sem HTMX volta a redirecionar"
```

---

### Task 8: Remover CSS e JS mortos

Seis blocos CSS sem nenhum consumidor (`.v4-dialog`, `.v4-dialog__panel`, `.v4-skeleton`, `.v4-stat-grid`, `.v4-card--compact`, `.v4-alert--copyable`) e três classes de motion (`.v4-fade-in`, `.v4-slide-up`, `.v4-pulse`) que ninguém aplica. **Os `@keyframes v4-fade-in` FICAM** — `.v4-dropdown.is-open` e o alert os usam. E `v4-panel.js` lê `data-v4-reload` e `data-v4-confirm-kind`, que nenhum template emite.

**Files:**
- Modify: `src/web/static/v4-components.css`, `src/web/static/v4-motion.css`, `src/web/static/v4-panel.js`
- Test: `tests/unit/test_frontend_a11y_guards.py`

**Interfaces:**
- Consumes: nada. Produces: nada.

- [ ] **Step 1: Escrever o teste que falha**

```python
_CLASSES_MORTAS = [
    ".v4-dialog",
    ".v4-stat-grid",
    ".v4-card--compact",
    ".v4-alert--copyable",
    ".v4-skeleton",
    ".v4-slide-up",
    ".v4-pulse",
]


@pytest.mark.parametrize("classe", _CLASSES_MORTAS)
def test_classe_sem_consumidor_nao_fica_no_bundle(classe):
    """CSS que nenhuma template aplica viaja em toda visita. O keyframes
    v4-fade-in continua — .v4-dropdown e o alert o consomem."""
    for css in ("v4-components.css", "v4-motion.css"):
        conteudo = (_STATIC / css).read_text(encoding="utf-8")
        assert classe + " " not in conteudo, f"{css}: {classe} nao e aplicada em template"


def test_panel_js_nao_le_atributo_que_ninguem_emite():
    js = (_STATIC / "v4-panel.js").read_text(encoding="utf-8")
    for atributo in ("v4Reload", "v4ConfirmKind"):
        assert atributo not in js, f"{atributo} nao e emitido por nenhuma template"
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_frontend_a11y_guards.py -k "sem_consumidor or ninguem_emite" -q`
Expected: FAIL nas 7 classes + 2 atributos.

- [ ] **Step 3: Remover os blocos**

De `v4-components.css`: `.v4-alert--copyable code`, `.v4-stat-grid`, `.v4-dialog`, `.v4-dialog__panel`, `.v4-card--compact` (3 regras).
De `v4-motion.css`: `.v4-fade-in`, `.v4-slide-up`, `.v4-pulse`, `.v4-skeleton` e os `@keyframes v4-slide-up`, `v4-pulse`, `v4-skeleton-shimmer` — **manter `@keyframes v4-fade-in`**. Ajustar o comentário do bloco `prefers-reduced-motion`, que cita as animações removidas.

De `v4-panel.js`: na ação `confirm`, trocar `kind: el.dataset.v4ConfirmKind || 'danger'` por `kind: 'danger'` e apagar a linha `if (el.dataset.v4Reload !== undefined) req.then(...)` (o `HX-Refresh` das rotas já cobre o reload).

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/unit/test_frontend_a11y_guards.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
python scripts/check_pre_push.py && git add -A && git commit -m "chore(web): remove CSS e JS sem consumidor"
```

---

### Task 9: Catalogar e documentar

Os 9 achados viram IDs no catálogo, com a lição de cada um. O CLAUDE.md ganha os invariantes novos e o ponteiro pro handoff.

**Files:**
- Modify: `docs/operacao/findings-catalog.md`
- Create: `docs/operacao/session-2026-08-19-frontend-handoff.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Descobrir o próximo ID livre**

```bash
grep -oE 'F[0-9]+' docs/operacao/findings-catalog.md | grep -oE '[0-9]+' | sort -n | tail -1
```

- [ ] **Step 2: Acrescentar as linhas no catálogo**, uma por achado, no formato já usado no arquivo, cada uma com sintoma → causa → guard que impede a reincidência.

- [ ] **Step 3: Escrever o handoff** com: o que foi investigado, os 9 achados, o padrão que os une (os três mais graves caem cada um num ponto cego de um guard existente e verde) e o que ficou verificado-e-limpo.

- [ ] **Step 4: Atualizar o CLAUDE.md** — "Current state" (data + resumo), "Don't do" (as regras novas: `aria-labelledby` fora do nó trocado; `data-sticky-measure` em quem alimenta o offset; `?v=` em todo `/static`; isenção de CSRF por rota, não por prefixo) e o ponteiro do handoff mais recente.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "docs: cataloga os achados da investigacao de frontend de 19/08"
```

---

## Self-review

**Cobertura:** os 9 achados do relatório têm task — 1→T1, 2→T2, 3→T3, 4→T4, 6+7→T5, 5→T6, 8→T7, 9→T8, documentação→T9.

**Placeholders:** nenhum passo diz "adicionar tratamento apropriado" ou "escrever testes pro acima" — todo passo de código traz o código.

**Consistência de tipos:** `_toggle_checkbox_fragment` é a única assinatura que muda; os dois call sites estão explicitados na Task 1 e nenhuma task posterior a consome.

**Ordem:** T2 e T4 tocam ambos `admin/audit.html` — executar T2 antes de T4 (T2 mexe no `<form>`, T4 nos `<label>`/`<select>` de dentro).
