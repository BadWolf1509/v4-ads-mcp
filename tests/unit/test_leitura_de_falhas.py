"""`erros_por_indice` sabe dizer que NAO conseguiu ler quem falhou."""

from typing import Any
from unittest.mock import MagicMock

from src.google_ads.partial_failure import LeituraDeFalhas, erros_por_indice


def _resposta(*, code: int, unpack_ok: bool, com_detail: bool = True) -> Any:
    resp = MagicMock()
    resp.partial_failure_error.code = code
    if not com_detail:
        resp.partial_failure_error.details = []
        return resp

    erro = MagicMock()
    erro.message = "invalid format"
    erro.error_code = "offline_user_data_job_error: invalid format"
    erro.location.field_path_elements = [MagicMock(index=2)]

    def fake_unpack(target_pb: MagicMock) -> bool:
        if not unpack_ok:
            return False
        target_pb.errors = [erro]
        return True

    raw = MagicMock()
    raw.type_url = "type.googleapis.com/google.ads.googleads.v24.errors.GoogleAdsFailure"
    raw.Unpack = fake_unpack
    detail = MagicMock()
    detail._pb = raw
    resp.partial_failure_error.details = [detail]
    return resp


def _cliente() -> Any:
    client = MagicMock()
    client.get_type.return_value._meta.pb.return_value = MagicMock(errors=[])
    return client


def test_unpack_recusado_nao_vira_lote_limpo() -> None:
    leitura = erros_por_indice(_resposta(code=1, unpack_ok=False), _cliente())
    assert isinstance(leitura, LeituraDeFalhas)
    assert leitura.medido is False, "Unpack False tem de virar 'nao medi', nao '{}' mudo"


def test_sem_falha_alguma_e_medido() -> None:
    """CONTROLE POSITIVO. Sem ele, uma implementacao que devolve medido=False
    sempre passaria no teste de cima — e o guard nao distinguiria codigo bom de
    quebrado, que e a definicao de nao-guard."""
    leitura = erros_por_indice(_resposta(code=0, unpack_ok=True), _cliente())
    assert leitura.medido is True
    assert leitura.erros == {}


def test_unpack_ok_le_os_erros_e_afirma_que_mediu() -> None:
    leitura = erros_por_indice(_resposta(code=1, unpack_ok=True), _cliente())
    assert leitura.medido is True
    assert leitura.erros[2].error_message == "invalid format"


def test_code_nao_zero_sem_detail_nenhum_nao_e_medido() -> None:
    """`code != 0` afirma que HOUVE falha. Sair dali com erros={} e medido=True
    seria o defeito original com roupa nova."""
    leitura = erros_por_indice(_resposta(code=1, unpack_ok=True, com_detail=False), _cliente())
    assert leitura.medido is False
    assert leitura.erros == {}
