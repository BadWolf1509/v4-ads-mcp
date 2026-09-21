"""Nao ler o motivo e diferente de o motivo ser desconhecido."""

from typing import Any
from unittest.mock import MagicMock

from src.google_ads.mutations import _parse_partial_failures


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
