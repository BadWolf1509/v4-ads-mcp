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


def _resposta_unpack_ok_sem_indice(*, code: int) -> Any:
    """Como `_resposta(unpack_ok=True)`, mas o erro desempacotado NAO traz
    `location.field_path_elements` — o buraco residual do item 1 da revisao
    final: `Unpack` teve sucesso (desempacotou_algum=True), so que nenhum erro
    dentro do detail aponta pra uma linha."""
    resp = MagicMock()
    resp.partial_failure_error.code = code

    erro = MagicMock()
    erro.message = "internal error"
    erro.error_code = "internal_error: internal_error"
    erro.location.field_path_elements = []  # sem indice -> `continue` no laco interno

    def fake_unpack(target_pb: MagicMock) -> bool:
        target_pb.errors = [erro]
        return True

    raw = MagicMock()
    raw.type_url = "type.googleapis.com/google.ads.googleads.v24.errors.GoogleAdsFailure"
    raw.Unpack = fake_unpack
    detail = MagicMock()
    detail._pb = raw
    resp.partial_failure_error.details = [detail]
    return resp


def test_unpack_ok_mas_nenhum_erro_com_indice_nao_e_medido() -> None:
    """O buraco que sobrava: Unpack desempacota com sucesso, mas o erro dentro
    do detail nao traz `field_path_elements` -- o laco interno da `continue` e
    `erros` fica vazio. Antes do fix, `desempacotou_algum=True` sozinho bastava
    pra `medido` ficar `True`: `code=1` (o Google afirma que HOUVE falha) virava
    `erros={} medido=True`, e em `customer_match` isso reportava um lote de PII
    como 100% aceito. `medido` so pode ficar `True` aqui se ALGUM erro tiver
    sido de fato atribuido a uma linha."""
    leitura = erros_por_indice(_resposta_unpack_ok_sem_indice(code=1), _cliente())
    assert leitura.medido is False, (
        "Unpack teve sucesso mas nenhum erro trouxe indice de linha -- "
        "nao da pra dizer QUEM falhou, e isso e 'nao medido', nao '{}' mudo"
    )
    assert leitura.erros == {}


class _RespostaQueLevantaAoLerOErro:
    """`partial_failure_error` que explode ao ser LIDO, nao ao ser desempacotado."""

    @property
    def partial_failure_error(self) -> Any:
        raise RuntimeError("proto corrompido na leitura")


class _ErroComCodeQueLevanta:
    @property
    def code(self) -> int:
        raise RuntimeError("proto corrompido no code")


class _RespostaComCodeQueLevanta:
    partial_failure_error = _ErroComCodeQueLevanta()


def test_leitura_do_partial_failure_error_que_levanta_nao_e_medida() -> None:
    """Minor 5 do F191: as leituras de `partial_failure_error` e de `.code` ficavam
    FORA do `try`. `getattr` com default so engole `AttributeError`; qualquer outra
    excecao ali subia com a PII ja anexada, e o Customer Match ficava com o default
    `membros_recusados=[]` -- "zero recusados", medido. Tem que virar "nao medido",
    como toda leitura que falha dentro do `try`."""
    leitura = erros_por_indice(_RespostaQueLevantaAoLerOErro(), _cliente())
    assert leitura.medido is False
    assert leitura.erros == {}


def test_code_que_levanta_ao_ser_lido_nao_e_medido() -> None:
    leitura = erros_por_indice(_RespostaComCodeQueLevanta(), _cliente())
    assert leitura.medido is False
    assert leitura.erros == {}
