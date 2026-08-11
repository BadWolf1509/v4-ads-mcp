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


def test_csp_sem_unsafe_eval():
    """Assertado sobre o valor da policy, nao sobre o source (comentarios citam o termo)."""
    from src.web.middleware import _CSP_POLICY

    assert "unsafe-eval" not in _CSP_POLICY
    assert "cdn.tailwindcss.com" not in _CSP_POLICY


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


def test_barra_de_filtros_da_auditoria_e_medida_em_runtime():
    """A barra embrulha (88/164/240px) em pontos que nao sao breakpoints padrao.

    Os cabecalhos de dia grudam abaixo dela, entao o offset tem que vir de
    medicao, nao de literal. Ver F79.
    """
    audit = (_TEMPLATES / "audit.html").read_text(encoding="utf-8")
    assert "data-sticky-measure" in audit, "a barra de filtros precisa ser medida"
    base = (_TEMPLATES / "_base.html").read_text(encoding="utf-8")
    assert "ResizeObserver" in base
    assert "--v4-filter-bar-h" in base


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
    assert "'alert' : 'status'" in html
