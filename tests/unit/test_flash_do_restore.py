"""O aviso do Restaurar diz quantos grants ficaram retidos por gestor desativado.

Revisão final (I1): depois da T2 o Restaurar não devolve o churn de gestor
desativado (remarca `manager_deactivated`), e o aviso era o `?ok=restored`
genérico — o admin via a conta sumir da fila sem saber que um grant ficou
retido. O número chega pela URL (`&retidos=N`), e a macro `alert` renderiza
`|safe`: o valor do query param nunca pode entrar na mensagem como veio.
"""

from starlette.requests import Request

from src.web.routes._shared import (
    _GOOGLE_ACCOUNTS_FLASH_OK,
    destino_do_restore,
    flash_do_restore,
)


def _request(query: str) -> Request:
    return Request({"type": "http", "query_string": query.encode(), "headers": []})


_BASE = _GOOGLE_ACCOUNTS_FLASH_OK["restored"]


def test_destino_sem_retidos_e_o_de_sempre() -> None:
    assert destino_do_restore("/admin/accounts", retidos=0) == "/admin/accounts?ok=restored"


def test_destino_com_retidos_leva_o_numero() -> None:
    assert (
        destino_do_restore("/admin/accounts/meta", retidos=3)
        == "/admin/accounts/meta?ok=restored&retidos=3"
    )


def test_flash_diz_quantos_ficaram_retidos() -> None:
    um = flash_do_restore(_request("ok=restored&retidos=1"), ok_codes=_GOOGLE_ACCOUNTS_FLASH_OK)
    assert um == {
        "kind": "success",
        "message": f"{_BASE} 1 acesso continua revogado porque o gestor está desativado; "
        "volta quando ele for reativado.",
    }
    dois = flash_do_restore(_request("ok=restored&retidos=2"), ok_codes=_GOOGLE_ACCOUNTS_FLASH_OK)
    assert dois is not None
    assert dois["message"].endswith(
        "2 acessos continuam revogados porque os gestores estão desativados; "
        "voltam quando eles forem reativados."
    )


def test_flash_sem_retidos_e_a_mensagem_fixa() -> None:
    assert flash_do_restore(_request("ok=restored"), ok_codes=_GOOGLE_ACCOUNTS_FLASH_OK) == {
        "kind": "success",
        "message": _BASE,
    }


def test_retidos_fora_do_formato_nunca_entra_na_mensagem() -> None:
    """Eco do param = XSS (painel.md). Só inteiro ASCII de 1 a 9999 vira número;
    o resto fica na mensagem fixa, sem pedaço nenhum do valor."""
    for bruto in (
        "0",
        "-1",
        "01",
        "1%20",
        "12345",
        "%3Cscript%3E",
        "1%3Cb%3E",
        "%D9%A3",  # dígito arábico-índico: `int()` aceitaria
    ):
        flash = flash_do_restore(
            _request(f"ok=restored&retidos={bruto}"), ok_codes=_GOOGLE_ACCOUNTS_FLASH_OK
        )
        assert flash == {"kind": "success", "message": _BASE}, bruto


def test_retidos_so_vale_no_ok_restored() -> None:
    erro = flash_do_restore(
        _request("error=conta_inativa_google&retidos=2"), ok_codes=_GOOGLE_ACCOUNTS_FLASH_OK
    )
    assert erro is not None
    assert erro["kind"] == "error"
    assert "revogado" not in erro["message"]
    assert (
        flash_do_restore(_request("ok=outro&retidos=2"), ok_codes=_GOOGLE_ACCOUNTS_FLASH_OK) is None
    )
