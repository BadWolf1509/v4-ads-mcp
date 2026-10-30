"""Hora de Brasilia, contraste e textos do painel (Task 21)."""

import re
from datetime import UTC, datetime
from pathlib import Path

from src.web.routes._shared import templates
from tests.unit import _guard_harness as h

_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATES = _ROOT / "src" / "web" / "templates"


def test_filtro_hora_brasilia_converte_utc_para_sao_paulo():
    filtro = templates.env.filters["hora_brasilia"]
    # 02:30 UTC = 23:30 do dia anterior em Brasilia (UTC-3, sem DST desde 2019).
    dt = datetime(2026, 10, 30, 2, 30, 15, tzinfo=UTC)
    assert filtro(dt) == "29/10 23:30"
    assert filtro(dt, "%d/%m/%Y %H:%M:%S") == "29/10/2026 23:30:15"


def test_filtro_hora_brasilia_trata_naive_como_utc_e_none_como_traco():
    filtro = templates.env.filters["hora_brasilia"]
    assert filtro(datetime(2026, 10, 30, 15, 0)) == "30/10 12:00"
    assert filtro(None) == "—"


def test_templates_nao_formatam_datetime_cru_com_strftime():
    """`strftime` direto mostra UTC como se fosse horario local."""
    ofensores = [
        t.name for t in h.templates_html() if re.search(r"\.strftime\(", t.read_text("utf-8"))
    ]
    assert not ofensores, f"use |hora_brasilia: {ofensores}"


def test_texto_pequeno_nao_usa_green_ou_gold_puros():
    """green/gold puros dao ~2:1 e 3,8:1 sobre branco; texto usa -text."""
    pad = re.compile(r"\btext-v4-(green|gold)(?![\w-])")
    ofensores = [t.name for t in h.templates_html() if pad.search(t.read_text("utf-8"))]
    assert not ofensores, f"use text-v4-green-text / text-v4-gold-text: {ofensores}"


def test_textos_falsos_do_modelo_b_nao_voltam():
    index = (_TEMPLATES / "admin" / "index.html").read_text("utf-8")
    assert "Vai desativar todas as tools Meta" not in index
    access_meta = (_TEMPLATES / "admin" / "access_meta.html").read_text("utf-8")
    assert "Rode o refresh" not in access_meta
    src = (_ROOT / "src" / "meta_ads" / "account_overview.py").read_text("utf-8")
    assert "Conectar Meta" not in src
