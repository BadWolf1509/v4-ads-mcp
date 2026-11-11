"""Todo import versionado do SDK do Google Ads em `src/` fala a versao do client.

O client usa a versao PADRAO do SDK (`_DEFAULT_VERSION`, v25 no google-ads 33).
Ate 11/11 o `recommendations.py` importava o enum do v24: o runtime recebia os 3
tipos novos do v25 e o modulo os tratava como desconhecidos. Era o lado seguro
por acaso — o import sozinho trocado para v25 faria os dois de lance cairem em
AUTO (levantamento K1). A versao do enum que decide o gate e a versao que o
servidor fala; divergir em silencio e o bug, nos dois sentidos.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from google.ads.googleads import client

_SRC = Path(__file__).resolve().parent.parent.parent / "src"
_VERSIONADO = re.compile(r"^google\.ads\.googleads\.(v\d+)(\.|$)")


def _imports_versionados() -> list[tuple[str, int, str]]:
    achados: list[tuple[str, int, str]] = []
    for arquivo in sorted(_SRC.rglob("*.py")):
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            modulos: list[str] = []
            if isinstance(no, ast.ImportFrom) and no.module:
                modulos = [no.module]
            elif isinstance(no, ast.Import):
                modulos = [a.name for a in no.names]
            for modulo in modulos:
                casou = _VERSIONADO.match(modulo)
                if casou:
                    achados.append((str(arquivo.relative_to(_SRC)), no.lineno, casou.group(1)))
    return achados


def test_src_importa_so_a_versao_padrao_do_sdk() -> None:
    padrao = client._DEFAULT_VERSION
    fora = [a for a in _imports_versionados() if a[2] != padrao]
    assert not fora, f"import fora da versao do client ({padrao}): {fora}"


def test_a_varredura_acha_o_import_do_enum_de_recomendacao() -> None:
    """Sem isto a varredura passaria verde achando zero imports."""
    arquivos = {a[0].replace("\\", "/") for a in _imports_versionados()}
    assert "google_ads/queries/recommendations.py" in arquivos, arquivos
