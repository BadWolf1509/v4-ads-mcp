"""BRL -> micros: arredondado, nunca truncado (preview == payload)."""

import re
from pathlib import Path

from src.google_ads.queries._common import brl_para_micros

SRC = Path(__file__).resolve().parents[2] / "src"


def test_valores_conhecidos() -> None:
    assert brl_para_micros(2.01) == 2_010_000
    assert brl_para_micros(4.10) == 4_100_000
    assert brl_para_micros(0.1) == 100_000


def test_varredura_de_centavos_e_multiplo_de_10000() -> None:
    for centavos in range(1, 100_001):
        micros = brl_para_micros(centavos / 100)
        assert micros == centavos * 10_000, centavos


def test_nenhum_int_vezes_milhao_em_src() -> None:
    padrao = re.compile(r"int\([^)\n]*\*\s*1_000_000")
    ofensores = [
        f"{p.relative_to(SRC)}:{n}"
        for p in SRC.rglob("*.py")
        for n, linha in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if padrao.search(linha)
    ]
    assert ofensores == []
