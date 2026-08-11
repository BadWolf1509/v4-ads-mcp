"""Guards de acessibilidade e entrega do painel (grep-based).

Espelha o padrao de test_structural_guards.py: varre o source pra impedir
reincidencia de classes de bug que so apareceriam num browser. Cada guard
referencia a medicao que o motivou (investigacao de frontend 2026-08-11).
"""

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


def test_toast_de_erro_interrompe_a_leitura():
    """aria-atomic na regiao re-anunciava a fila inteira; erro precisa de role=alert."""
    html = (_TEMPLATES / "_base.html").read_text(encoding="utf-8")
    assert 'id="v4-toast-region"' in html
    assert "aria-atomic=" not in html
    assert "'alert' : 'status'" in html
