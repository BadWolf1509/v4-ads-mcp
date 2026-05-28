"""Tests for meta_status_label Jinja filter helper."""

from src.web.routes import meta_status_label


def test_meta_status_label_known() -> None:
    assert meta_status_label(1) == "ATIVO"
    assert meta_status_label(3) == "PAGAMENTO_PENDENTE"


def test_meta_status_label_unknown_or_none() -> None:
    assert meta_status_label(99999) == "DESCONHECIDO"
    assert meta_status_label(None) == "DESCONHECIDO"
