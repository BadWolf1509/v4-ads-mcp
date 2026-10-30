"""O toast do toggle de acesso vem do servidor (HX-Trigger), não de `el.checked`.

`el.checked` é o que o clique PEDIU; com aba velha o servidor pode não ter feito
nada, e o toast otimista mentiria.
"""

from pathlib import Path

JS = Path(__file__).parents[2] / "src" / "web" / "static" / "v4-panel.js"


def test_js_nao_decide_o_texto_do_toast_pelo_checkbox():
    texto = JS.read_text(encoding="utf-8")
    assert "Acesso liberado" not in texto
    assert "Acesso revogado" not in texto
