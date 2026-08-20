"""Guards de acessibilidade e entrega do painel (grep-based).

Espelha o padrao de test_structural_guards.py: varre o source pra impedir
reincidencia de classes de bug que so apareceriam num browser. Cada guard
referencia a medicao que o motivou (investigacao de frontend 2026-08-11).
"""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "src" / "web" / "static"
_TEMPLATES = _ROOT / "src" / "web" / "templates"


def test_motion_css_respeita_prefers_reduced_motion():
    """3 animacoes infinitas no design system exigem um opt-out (WCAG 2.3.3)."""
    css = (_STATIC / "v4-motion.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion: reduce" in css


def test_base_define_focus_visible():
    """Foco por teclado nao pode depender do default do browser."""
    css = (_STATIC / "v4-base.css").read_text(encoding="utf-8")
    assert ":focus-visible" in css


def test_base_tem_skip_link_ancorado_no_main():
    html = (_TEMPLATES / "_base.html").read_text(encoding="utf-8")
    assert 'href="#conteudo"' in html
    assert 'id="conteudo"' in html


# gray-300 como texto so e legitimo sobre fundo escuro (ex.: o code block, 7,2:1).
# Como um guard grep-based nao enxerga o background, a intencao tem que ser
# declarada na propria linha com este marcador.
_ON_DARK = "/* on-dark */"


def _gray_300_como_texto(conteudo: str) -> list[str]:
    ofensores = []
    for linha in conteudo.splitlines():
        limpa = linha.strip()
        if limpa.startswith("color:") and "--v4-gray-300" in limpa and _ON_DARK not in limpa:
            ofensores.append(limpa)
    return ofensores


@pytest.mark.parametrize("arquivo", ["v4-components.css", "v4-base.css", "v4-help.css"])
def test_gray_300_nunca_usado_como_cor_de_texto(arquivo):
    """#b3b3b3 = 2,1:1 sobre branco. So vale pra border e texto sobre fundo escuro."""
    caminho = _STATIC / arquivo
    if not caminho.exists():
        pytest.skip(f"{arquivo} ainda nao existe")
    ofensores = _gray_300_como_texto(caminho.read_text(encoding="utf-8"))
    assert not ofensores, f"{arquivo}: gray-300 como texto sem marcador {_ON_DARK} -> {ofensores}"


def test_templates_nao_usam_gray_300_como_texto():
    for template in _TEMPLATES.rglob("*.html"):
        ofensores = _gray_300_como_texto(template.read_text(encoding="utf-8"))
        assert not ofensores, f"{template.name}: gray-300 como texto -> {ofensores}"


def test_sem_tailwind_play_cdn():
    """O Play CDN compila em runtime (407 KB de JS) e exigia 'unsafe-eval'."""
    html = (_TEMPLATES / "_base.html").read_text(encoding="utf-8")
    assert "cdn.tailwindcss.com" not in html


def test_sem_handler_inline_em_template():
    """script-src sem 'unsafe-inline' bloqueia on*= e hx-on em atributo.

    O comportamento vive em v4-panel.js, acionado por data-v4-*.
    """
    # A aspa pode vir escapada (\") quando o HTML e montado dentro de uma string
    # Jinja passada pra macro — foi assim que um onclick sobreviveu a primeira
    # varredura, em admin/index.html.
    padrao = re.compile(r'\b(on[a-z]+|hx-on[^\s=]*)\s*=\s*\\?["\']')
    ofensores = []
    for template in _TEMPLATES.rglob("*.html"):
        for attr in padrao.findall(template.read_text(encoding="utf-8")):
            ofensores.append(f"{template.name}:{attr}")
    assert not ofensores, f"handler inline em template: {ofensores}"


def test_sem_script_inline_em_template():
    """Bloco <script> sem src também exige 'unsafe-inline'."""
    ofensores = [
        t.name for t in _TEMPLATES.rglob("*.html") if "<script>" in t.read_text(encoding="utf-8")
    ]
    assert not ofensores, f"<script> inline em: {ofensores}"


def test_fragmento_de_toggle_nao_carrega_handler():
    """F74: o handler do checkbox é delegado, então o fragmento não pode
    depender de re-emitir `hx-on` pra sobreviver ao swap."""
    rotas = (_ROOT / "src" / "web" / "routes.py").read_text(encoding="utf-8")
    fragmento = rotas.split("def _toggle_checkbox_fragment")[1].split("\ndef ")[0]
    assert "data-v4-access-toggle" in fragmento
    assert 'hx-on::after-request="' not in fragmento


def test_toda_acao_usada_existe_no_modulo():
    """data-v4-action com nome errado falharia calado no browser."""
    js = (_STATIC / "v4-panel.js").read_text(encoding="utf-8")
    declaradas = set(re.findall(r"^  '?([a-z-]+)'?:", js, re.M))
    usadas = set()
    for template in _TEMPLATES.rglob("*.html"):
        usadas.update(
            re.findall(r'data-v4-action="([a-z-]+)"', template.read_text(encoding="utf-8"))
        )
    orfas = usadas - declaradas
    assert not orfas, f"data-v4-action sem handler em v4-panel.js: {sorted(orfas)}"


def test_csp_sem_unsafe_eval():
    """Assertado sobre o valor da policy, nao sobre o source (comentarios citam o termo)."""
    from src.web.middleware import _CSP_POLICY

    assert "unsafe-eval" not in _CSP_POLICY
    assert "cdn.tailwindcss.com" not in _CSP_POLICY


def test_script_src_sem_unsafe_inline():
    """O comportamento vive em v4-panel.js; nada de script inline sobrou.

    style-src ainda precisa de 'unsafe-inline' — o htmx injeta um <style> em
    runtime e ha atributos style= nas templates. CSS inline nao executa codigo,
    entao o risco nao e o mesmo.
    """
    from src.web.middleware import _CSP_POLICY

    assert "unsafe-inline" not in _CSP_POLICY, _CSP_POLICY


def test_sem_atributo_style_em_template():
    """style-src sem 'unsafe-inline' bloqueia atributo style= (style-src-attr).

    Escrita via CSSOM (el.style.x = y) NAO e afetada — por isso os filtros e o
    drawer seguem valendo. So o atributo no HTML precisa virar classe.
    A aspa pode vir escapada quando o HTML e montado em string Jinja.
    """
    padrao = re.compile(r'\bstyle\s*=\s*\\?["\']')
    ofensores = [
        t.name for t in _TEMPLATES.rglob("*.html") if padrao.search(t.read_text(encoding="utf-8"))
    ]
    assert not ofensores, f"atributo style= em: {ofensores}"


def test_htmx_nao_injeta_style_do_indicador():
    """Sem esse config o htmx injeta um <style> em runtime e a CSP o bloqueia.

    As regras equivalentes ja existem em v4-motion.css.
    """
    html = (_TEMPLATES / "_base.html").read_text(encoding="utf-8")
    assert "includeIndicatorStyles" in html
    css = (_STATIC / "v4-motion.css").read_text(encoding="utf-8")
    assert ".htmx-indicator" in css


def test_tailwind_e_o_ultimo_stylesheet():
    """CRITICO: o Preflight tem que continuar vencendo o v4-base.css.

    O Play CDN injetava seu <style> no fim do <head>, entao h1 sem classe
    e 14px/400 (Preflight), nao os 36px/800 de v4-base.css. Carregar o CSS
    gerado ANTES dos v4-*.css inverte isso e estoura todo heading do painel.
    """
    html = (_TEMPLATES / "_base.html").read_text(encoding="utf-8")
    hrefs = re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', html)
    locais = [h for h in hrefs if h.startswith("/static/")]
    assert locais, "nenhum stylesheet local encontrado"
    assert "v4-tailwind.css" in locais[-1], f"v4-tailwind.css precisa ser o ultimo: {locais}"


def test_css_gerado_do_tailwind_esta_commitado():
    """O CI regenera e faz diff; aqui so garantimos que o artefato existe."""
    gerado = _STATIC / "v4-tailwind.css"
    assert gerado.exists(), "rode: python scripts/build_tailwind.py"
    conteudo = gerado.read_text(encoding="utf-8")
    # Preflight: e ele que domina a cascata dos headings.
    assert "font-size:inherit;font-weight:inherit" in conteudo
    # Cores resolvem pra custom property (fonte unica em v4-tokens.css).
    assert "var(--v4-red)" in conteudo


def test_offsets_sticky_sao_derivados():
    """Tres literais (53/96/120px) dessincronizavam em silencio se o header mudasse."""
    tokens = (_STATIC / "v4-tokens.css").read_text(encoding="utf-8")
    assert "--v4-header-h:" in tokens
    assert "calc(var(--v4-header-h)" in tokens
    base = (_STATIC / "v4-base.css").read_text(encoding="utf-8")
    assert "top: 53px" not in base


def test_paginas_admin_nao_usam_o_offset_de_header_puro():
    """Toda pagina /admin tem a subnav acima, entao sticky ali parte da PILHA.

    Com --v4-subnav-offset a barra de filtros de /admin/audit grudava no mesmo
    topo da subnav e a cobria por inteiro (mesmo z-index, e ela vem depois no
    DOM). Medido no smoke autenticado de 2026-08-11.
    """
    # Casa a FORMA DE USO (`var(...)`), nao o token nu — comentarios citam o
    # nome legitimamente ao explicar por que nao se usa ele aqui.
    for template in (_TEMPLATES / "admin").rglob("*.html"):
        conteudo = template.read_text(encoding="utf-8")
        assert "var(--v4-subnav-offset)" not in conteudo, (
            f"admin/{template.name}: use --v4-tab-bar-offset (header+subnav), "
            "nao --v4-subnav-offset (so header)"
        )


def test_toda_barra_que_alimenta_offset_sticky_e_medida():
    """A barra embrulha (88/164/240px) em pontos que nao sao breakpoints padrao.

    Quem gruda embaixo dela (cabecalho de dia em /audit, thead em /admin/audit)
    tira o offset de --v4-filter-bar-h, que so recebe valor real se o
    ResizeObserver achar um [data-sticky-measure] NA PAGINA. Sem o atributo o
    valor fica no fallback de v4-tokens.css, aferido em OUTRA barra. Ver F79.

    A lista de paginas e DERIVADA do consumo do token — listar template a mao
    foi o que deixou /admin/audit de fora quando o mecanismo nasceu.
    """
    js = (_STATIC / "v4-panel.js").read_text(encoding="utf-8")
    assert "ResizeObserver" in js
    assert "--v4-filter-bar-h" in js

    css = (_STATIC / "v4-components.css").read_text(encoding="utf-8")
    assert "var(--v4-filter-bar-h)" in css, "quem consome o token mudou de nome"

    consumidores = 0
    for template in _TEMPLATES.rglob("*.html"):
        conteudo = template.read_text(encoding="utf-8")
        consome = (
            "v4-table--sticky-head-under-filters" in conteudo
            or "var(--v4-audit-day-offset)" in conteudo
        )
        if not consome:
            continue
        consumidores += 1
        assert "data-sticky-measure" in conteudo, (
            f"{template.name}: usa offset derivado de --v4-filter-bar-h mas nao marca "
            "a barra com data-sticky-measure — o valor fica no fallback"
        )
    assert consumidores >= 2, "esperado /audit e /admin/audit consumindo o token"


def test_barras_de_filtro_nao_grudam_no_celular():
    """Embrulhadas elas chegam a 240px: 301px de pilha fixa em /audit (~36% da
    tela) e 356px em /admin/audit (~42%, por causa da subnav). Abaixo de 640px
    rolam junto com a pagina."""
    for caminho in ["audit.html", "admin/audit.html"]:
        html = (_TEMPLATES / caminho).read_text(encoding="utf-8")
        classes = re.search(r'class="((?:[^"]*\s)?sticky(?:\s[^"]*)?)"', html)
        assert classes, f"{caminho}: barra de filtros sticky nao encontrada"
        assert "max-sm:static" in classes.group(1), (
            f"{caminho}: a barra sticky precisa de max-sm:static"
        )


def test_input_busca_compacto_preserva_espaco_do_icone():
    """O shorthand `padding` de --small zerava o padding-left de --search e o
    icone de lupa cobria o placeholder nas matrizes de acesso."""
    css = (_STATIC / "v4-components.css").read_text(encoding="utf-8")
    assert ".v4-input--search.v4-input--small" in css


def test_help_css_esta_num_arquivo_estatico():
    """~60 linhas de <style> inline saiam do cache e do alcance da CSP."""
    html = (_TEMPLATES / "help.html").read_text(encoding="utf-8")
    assert "<style>" not in html
    assert (_STATIC / "v4-help.css").exists()


def test_montserrat_nao_baixa_peso_sem_uso():
    """Peso 300 era baixado em toda visita sem nenhum font-weight:300 no projeto."""
    html = (_TEMPLATES / "_base.html").read_text(encoding="utf-8")
    assert "montserrat:400,500,600,700,800" in html


def test_toast_de_erro_interrompe_a_leitura():
    """aria-atomic na regiao re-anunciava a fila inteira; erro precisa de role=alert."""
    html = (_TEMPLATES / "_base.html").read_text(encoding="utf-8")
    assert 'id="v4-toast-region"' in html
    assert "aria-atomic=" not in html
    js = (_STATIC / "v4-panel.js").read_text(encoding="utf-8")
    assert "'alert' : 'status'" in js


# --------------------------------------------------- investigacao 2026-08-19

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
    No detail o aria-label ainda VENCIA o <label> que embrulha, entao texto
    visivel e nome acessivel passavam a discordar.
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
    assert 'aria-labelledby="v4-mgr-11111111-1111-1111-1111-111111111111 v4-acc-9876543210"' in frag
    assert "aria-label=" not in frag.replace("aria-labelledby=", "")
    assert '"customer_id": "9876543210"' in frag.replace("&quot;", '"')


def test_todo_controle_de_formulario_tem_nome_acessivel():
    """select/input/textarea sem <label for>, sem aria-label e sem <label> que
    embrulha e anunciado como "caixa de combinacao" sem nome nenhum.

    Os 5 filtros de /admin/audit tinham o rotulo VISUAL do lado e nenhum
    vinculo — a pagina irma /audit faz certo com os mesmos filtros.
    """
    sem_nome = []
    for template in _TEMPLATES.rglob("*.html"):
        conteudo = template.read_text(encoding="utf-8")
        labels_for = set(re.findall(r'<label[^>]*[ ]for="([^"]+)"', conteudo))
        embrulhados = re.findall(r"<label[^>]*>.*?</label>", conteudo, re.S)
        for numero, linha in enumerate(conteudo.splitlines(), 1):
            for tag, attrs in re.findall(r"<(select|textarea|input)[ ]([^>]*)>", linha):
                tipo = re.search(r'type="([^"]+)"', attrs)
                if tag == "input" and tipo and tipo.group(1) in ("hidden", "submit"):
                    continue
                if "aria-label" in attrs:
                    continue
                identificador = re.search(r'id="([^"]+)"', attrs)
                if identificador and identificador.group(1) in labels_for:
                    continue
                if any(f"<{tag} {attrs}>" in bloco for bloco in embrulhados):
                    continue
                sem_nome.append(f"{template.name}:{numero} <{tag}>")
    assert not sem_nome, "controles sem nome acessivel: " + "; ".join(sem_nome)


def test_todo_th_declara_scope():
    """Sem scope o leitor de tela nao associa celula a cabecalho na tabela de dados."""
    sem_scope = []
    for template in _TEMPLATES.rglob("*.html"):
        for numero, linha in enumerate(template.read_text(encoding="utf-8").splitlines(), 1):
            for attrs in re.findall(r"<th([^a-z>][^>]*)?>", linha):
                if "scope=" not in (attrs or ""):
                    sem_scope.append(f"{template.name}:{numero}")
    assert not sem_scope, "<th> sem scope: " + "; ".join(sem_scope)


def test_linha_expansivel_nao_vira_button():
    """role=button torna os filhos PRESENTACIONAIS (ARIA): a linha inteira vira
    um nome so e a associacao com os <th scope="col"> some. tabindex + o
    handler de Enter/Espaco dao o teclado; aria-expanded e suportado em
    role=row, entao a expansao segue anunciada."""
    for template in _TEMPLATES.rglob("*.html"):
        conteudo = template.read_text(encoding="utf-8")
        for abertura in re.findall(r"<tr[^>]*>", conteudo):
            assert 'role="button"' not in abertura, (
                f"{template.name}: <tr role=button> achata a linha pro leitor de tela"
            )


_CLASSES_SEM_CONSUMIDOR = [
    ".v4-dialog",
    ".v4-stat-grid",
    ".v4-card--compact",
    ".v4-alert--copyable",
    ".v4-skeleton",
    ".v4-slide-up",
    ".v4-pulse",
]


@pytest.mark.parametrize("classe", _CLASSES_SEM_CONSUMIDOR)
def test_classe_sem_consumidor_nao_fica_no_bundle(classe):
    """CSS que nenhuma template aplica viaja em toda visita.

    O @keyframes v4-fade-in FICA — .v4-dropdown.is-open e o alert o usam;
    o que sai e a CLASSE .v4-fade-in, que ninguem aplica.
    """
    for css in ("v4-components.css", "v4-motion.css"):
        conteudo = (_STATIC / css).read_text(encoding="utf-8")
        assert classe + " " not in conteudo, f"{css}: {classe} nao e aplicada em template"


def test_panel_js_nao_le_atributo_que_ninguem_emite():
    """Ler data-v4-reload / data-v4-confirm-kind sem nenhum emissor e ramo morto."""
    js = (_STATIC / "v4-panel.js").read_text(encoding="utf-8")
    for atributo in ("v4Reload", "v4ConfirmKind"):
        assert atributo not in js, f"{atributo} nao e emitido por nenhuma template"
