"""Enums e descriptions das tools batem com o handler (Task 22)."""

import importlib

from src.mcp.tools import create_conversion_action as criar
from src.mcp.tools._registry import get_tool, import_all_tools

_AUDITS = ("audit_orphan_smart_actions", "audit_goal_attribution")


def _descricao(nome: str) -> str:
    import_all_tools()
    tool = get_tool(nome)
    assert tool is not None
    return tool.description


def _enum_categoria(modulo: str) -> list[str]:
    mod = importlib.import_module(f"src.mcp.tools.{modulo}")
    return mod._SCHEMA["properties"]["category"]["enum"]


def test_audits_aceitam_toda_categoria_que_create_conversion_action_cria():
    """Uma conversao criada com PHONE_CALL_LEAD tem que ser auditavel."""
    criadas = set(criar._CATEGORY_ENUM)
    for modulo in _AUDITS:
        faltando = criadas - set(_enum_categoria(modulo))
        assert not faltando, f"{modulo} nao aceita {sorted(faltando)}"


def test_os_dois_audits_compartilham_a_mesma_constante():
    assert _enum_categoria(_AUDITS[0]) == _enum_categoria(_AUDITS[1])


def test_validate_gaql_nao_diz_que_nao_consome_quota():
    desc = _descricao("validate_gaql")
    assert "sem consumir quota" not in desc
    assert "consome 1 operação da quota" in desc


def test_update_conversion_action_descreve_token_de_8_caracteres():
    desc = _descricao("update_conversion_action")
    assert "UUID" not in desc
    assert "8 caracteres" in desc


def test_raw_grid_fala_em_blocos_nomeados():
    from src.mcp.tools.get_performance_breakdown import _SCHEMA

    desc = _SCHEMA["properties"]["raw_grid"]["description"]
    assert "3 blocos" not in desc
    assert "blocos nomeados" in desc


def test_remove_audience_avisa_que_audiencia_de_campanha_nao_vem_do_report():
    desc = _descricao("remove_audience")
    assert "audiência de campanha" in desc
    assert "get_audience_performance" in desc
