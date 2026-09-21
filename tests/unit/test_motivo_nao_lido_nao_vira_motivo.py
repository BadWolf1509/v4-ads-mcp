"""Nao ler o motivo e diferente de o motivo ser desconhecido.

Cobre os dois lados que consomem `erros_por_indice` (Task 2) por caminho
proprio -- `mutations._parse_partial_failures` (WhichOneof) e
`conversions._parse_upload_response` (heuristica em `results`) -- nos dois
estados de `LeituraDeFalhas.medido`:

- medido=False: o motivo vira `None` (nao mais uma string que afirma ter
  lido e nao achou).
- medido=True com o indice AUSENTE do mapa de erros: o texto/dict antigo
  ("Unknown partial failure" / {"UNKNOWN", "no detail"}) tem que continuar
  saindo -- esse caminho nao mudou, e um guard cobre o fallback pra um
  refactor futuro nao trocar `.get(idx, default)` por `.get(idx)` sem notar.
"""

from typing import Any
from unittest.mock import MagicMock

from src.google_ads.conversions import _parse_upload_response
from src.google_ads.mutations import _parse_partial_failures


class _FakeGoogleAdsError:
    """Imita um GoogleAdsError do proto real: message + error_code + location.index."""

    def __init__(self, idx: int, msg: str) -> None:
        self.message = msg
        self.error_code = f"criterion_error: {msg}"
        self.location = MagicMock()
        self.location.field_path_elements = [MagicMock(index=idx)]


def _fake_unpackable_detail(idx: int, msg: str) -> MagicMock:
    """Detail do partial_failure_error que desempacota com SUCESSO um erro no `idx` dado.

    Usado pelos testes "medido=True com indice ausente do mapa": o detail
    fala de um indice diferente do que de fato falhou na resposta, entao
    `erros_por_indice` mede (medido=True) mas nao cobre a linha que falhou.
    """
    fake_errors = [_FakeGoogleAdsError(idx, msg)]

    def fake_unpack(target_pb: MagicMock) -> bool:
        target_pb.errors = fake_errors
        return True

    raw_any = MagicMock()
    raw_any.type_url = "type.googleapis.com/google.ads.googleads.v20.errors.GoogleAdsFailure"
    raw_any.Unpack = fake_unpack

    fake_detail = MagicMock()
    fake_detail._pb = raw_any
    return fake_detail


def _client_com_google_ads_failure_stub() -> MagicMock:
    """Client cujo get_type("GoogleAdsFailure") devolve um stub desempacotavel."""
    failure_type_stub = MagicMock()
    failure_type_stub._meta.pb = lambda: MagicMock(errors=[])
    client = MagicMock()
    client.get_type = MagicMock(
        side_effect=lambda name: failure_type_stub if name == "GoogleAdsFailure" else MagicMock()
    )
    return client


# ---------------------------------------------------------------------------
# mutations._parse_partial_failures
# ---------------------------------------------------------------------------


def _resposta_com_uma_falha() -> Any:
    ok = MagicMock()
    ok._pb.WhichOneof.return_value = "ad_group_criterion_result"
    falhou = MagicMock()
    falhou._pb.WhichOneof.return_value = None

    resp = MagicMock()
    resp.mutate_operation_responses = [ok, falhou]
    resp.partial_failure_error.code = 1
    # Nenhum detail desempacotavel -> LeituraDeFalhas.medido = False
    resp.partial_failure_error.details = []
    return resp


def test_sem_medicao_o_erro_da_linha_e_none() -> None:
    linhas = _parse_partial_failures(
        _resposta_com_uma_falha(),
        MagicMock(),
        operation_type="add_keywords",
        customer_id="1234567890",
        target_count=2,
    )
    falha = [linha for linha in linhas if linha["status"] == "failed"]
    assert len(falha) == 1, "a CONTAGEM sobrevive: ela vem do WhichOneof, nao do mapa de erros"
    assert falha[0]["error"] is None, (
        "'Unknown partial failure' afirma que se leu o motivo e ele era desconhecido; "
        "a verdade e que nao se leu"
    )


def test_com_medicao_indice_ausente_do_mapa_preserva_string_antiga() -> None:
    """Guard do caminho MEDIDO (nao mudou nesta task, mas ficou sem cobertura).

    O detail desempacota com sucesso (medido=True), so que fala do indice 99
    -- a linha que de fato falhou (indice 1) fica fora do mapa de erros. O
    fallback tem que continuar "Unknown partial failure", NAO None: None e
    reservado para leitura nao-confiavel, e aqui a leitura foi confiavel, so
    nao cobriu esta linha.
    """
    ok = MagicMock()
    ok._pb.WhichOneof.return_value = "ad_group_criterion_result"
    falhou = MagicMock()
    falhou._pb.WhichOneof.return_value = None

    resp = MagicMock()
    resp.mutate_operation_responses = [ok, falhou]
    resp.partial_failure_error.code = 1
    resp.partial_failure_error.details = [
        _fake_unpackable_detail(99, "erro de um indice que nao e o 1")
    ]

    linhas = _parse_partial_failures(
        resp,
        _client_com_google_ads_failure_stub(),
        operation_type="add_keywords",
        customer_id="1234567890",
        target_count=2,
    )
    falha = [linha for linha in linhas if linha["status"] == "failed"]
    assert len(falha) == 1
    assert falha[0]["error"] == "Unknown partial failure", (
        "leitura.medido=True aqui -- so o indice que faltou no detail. Trocar "
        "o fallback por `.get(idx)` sem default devolveria None tambem neste "
        "caso, e as duas causas (nao lido vs lido-mas-sem-cobertura) "
        "ficariam indistinguiveis de novo"
    )


# ---------------------------------------------------------------------------
# conversions._parse_upload_response
# ---------------------------------------------------------------------------


def _resposta_upload_uma_falha(details: list[Any], *, code: int = 1) -> Any:
    falhou = MagicMock()
    falhou.conversion_action = ""  # vazio = linha falhou (heuristica do modulo)

    resp = MagicMock()
    resp.results = [falhou]
    resp.partial_failure_error.code = code
    resp.partial_failure_error.details = details
    return resp


def test_upload_sem_medicao_error_code_e_message_sao_none() -> None:
    resp = _resposta_upload_uma_falha(details=[])  # nada desempacotavel -> medido=False
    payload = {"conversions": [{"gclid": "Cj0_0"}]}

    applied, failed, failures = _parse_upload_response(resp, payload, MagicMock())

    assert applied == 0
    assert failed == 1
    assert failures[0]["error_code"] is None, (
        "'UNKNOWN' afirma que se leu o motivo; sob leitura nao-confiavel nao se leu"
    )
    assert failures[0]["error_message"] is None, (
        "'no detail' afirma que se leu o motivo; sob leitura nao-confiavel nao se leu"
    )


def test_upload_com_medicao_indice_ausente_preserva_unknown_no_detail() -> None:
    """Guard do caminho MEDIDO em conversions.py (mesma forma do teste em mutations)."""
    resp = _resposta_upload_uma_falha(
        details=[_fake_unpackable_detail(99, "erro de um indice que nao e o 0")]
    )
    payload = {"conversions": [{"gclid": "Cj0_0"}]}

    applied, failed, failures = _parse_upload_response(
        resp, payload, _client_com_google_ads_failure_stub()
    )

    assert applied == 0
    assert failed == 1
    assert failures[0]["error_code"] == "UNKNOWN", (
        "leitura.medido=True aqui -- o padrao antigo tem que sobreviver quando "
        "so falta cobertura do indice, nao quando a leitura falhou"
    )
    assert failures[0]["error_message"] == "no detail"
