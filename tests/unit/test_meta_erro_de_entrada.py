"""D6: `erro_de_entrada` é o envelope único de erro de entrada das tools Meta."""

from __future__ import annotations

from src.mcp.tools._meta_common import erro_de_entrada


def test_erro_de_entrada_tem_exatamente_duas_chaves_na_ordem() -> None:
    resposta = erro_de_entrada("`limit` deve estar entre 1 e 500 (recebido 0).")

    assert resposta == {
        "status": "error",
        "error_message": "`limit` deve estar entre 1 e 500 (recebido 0).",
    }
    # A ordem sai no JSON que o cliente LLM lê.
    assert list(resposta) == ["status", "error_message"]
