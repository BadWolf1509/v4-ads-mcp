"""Capture-client tests para src/google_ads/mutates/recommendations.py.

Os executores `execute_apply_recommendation` / `execute_dismiss_recommendation`
NÃO usam @register_builder (docstring do módulo) → escapam dos guards de builder
(classe F16/F42/F44 — MagicMock cru mascara bug de proto field). Estes testes
fecham o escape hatch: usam make_capture_client (CapturedOp) pra asseverar que o
resource_name é setado no campo proto certo, no operation type certo, com o
customer_id certo passado à service call.

Guard de rename (F51): asseveramos presença de `resource_name` E ausência de nomes
de campo errados (`recommendation_resource_name`, `resource`) — __setattr__ do
CapturedOp aceita qualquer atributo silenciosamente, então um rename passaria batido
sem o par presença+ausência.

Limitação: as service calls (apply_recommendation/dismiss_recommendation) são MagicMock
— só capturamos o `operation` que o executor montou (via get_type + CapturedOp), não
executamos gRPC real. É o mesmo nível de cobertura dos outros *_builder.py. O
`interceptors=` kwarg passado pro get_service é aceito pelo stub e ignorado (mirror do
comportamento SDK, que injeta o interceptor sem alterar o proto montado).
"""

from typing import Any
from unittest.mock import MagicMock

from src.google_ads.mutates.recommendations import (
    execute_apply_recommendation,
    execute_dismiss_recommendation,
)
from tests.unit.fixtures.proto_capture import CapturedOp, make_capture_client

_CUSTOMER_ID = "1234567890"
_REC_RESOURCE = "customers/1234567890/recommendations/AbCdEf123"


def _client_with_recommendation_service() -> tuple[MagicMock, MagicMock]:
    """make_capture_client + RecommendationService stub.

    O stub aceita `interceptors=` (kwarg interno do SDK que o make_capture_client
    base não conhece) e devolve um service cujos métodos apply/dismiss são MagicMock.
    get_type devolve CapturedOp (base) pros dois operation types.
    """
    client = make_capture_client()

    rec_service = MagicMock()
    rec_service.apply_recommendation = MagicMock(return_value=MagicMock())
    rec_service.dismiss_recommendation = MagicMock(return_value=MagicMock())

    def _get_service(name: str, interceptors: Any = None) -> Any:
        if name == "RecommendationService":
            return rec_service
        return client.get_service(name)

    # Substitui get_service preservando a assinatura com interceptors=.
    client.get_service = _get_service
    return client, rec_service


def test_apply_recommendation_sets_resource_name_on_operation() -> None:
    client, rec_service = _client_with_recommendation_service()

    execute_apply_recommendation(
        client, _CUSTOMER_ID, {"recommendation_resource_name": _REC_RESOURCE}
    )

    call = rec_service.apply_recommendation.call_args
    assert call.kwargs["customer_id"] == _CUSTOMER_ID
    ops = call.kwargs["operations"]
    assert len(ops) == 1
    op = ops[0]
    assert isinstance(op, CapturedOp)
    # Campo certo setado com o resource path certo.
    assert op.field("resource_name") == _REC_RESOURCE


def test_apply_recommendation_field_rename_guard() -> None:
    """F51: assevera ausência de nomes de campo errados no operation de apply."""
    client, rec_service = _client_with_recommendation_service()

    execute_apply_recommendation(
        client, _CUSTOMER_ID, {"recommendation_resource_name": _REC_RESOURCE}
    )

    op = rec_service.apply_recommendation.call_args.kwargs["operations"][0]
    assert op.has("resource_name") is True
    # Nomes plausíveis-porém-errados que um refactor poderia introduzir.
    assert op.has("recommendation_resource_name") is False
    assert op.has("resource") is False
    assert op.has("recommendation") is False


def test_dismiss_recommendation_sets_resource_name_on_operation() -> None:
    client, rec_service = _client_with_recommendation_service()

    execute_dismiss_recommendation(
        client, _CUSTOMER_ID, {"recommendation_resource_name": _REC_RESOURCE}
    )

    call = rec_service.dismiss_recommendation.call_args
    assert call.kwargs["customer_id"] == _CUSTOMER_ID
    ops = call.kwargs["operations"]
    assert len(ops) == 1
    op = ops[0]
    assert isinstance(op, CapturedOp)
    assert op.field("resource_name") == _REC_RESOURCE


def test_dismiss_recommendation_field_rename_guard() -> None:
    """F51: assevera ausência de nomes de campo errados no operation de dismiss."""
    client, rec_service = _client_with_recommendation_service()

    execute_dismiss_recommendation(
        client, _CUSTOMER_ID, {"recommendation_resource_name": _REC_RESOURCE}
    )

    op = rec_service.dismiss_recommendation.call_args.kwargs["operations"][0]
    assert op.has("resource_name") is True
    assert op.has("recommendation_resource_name") is False
    assert op.has("resource") is False
    assert op.has("recommendation") is False


def test_apply_uses_apply_recommendation_operation_type() -> None:
    """O executor pede get_type("ApplyRecommendationOperation") — não o dismiss type."""
    client, rec_service = _client_with_recommendation_service()

    requested: list[str] = []
    _orig_get_type = client.get_type

    def _spy_get_type(name: str) -> CapturedOp:
        requested.append(name)
        return _orig_get_type(name)

    client.get_type = _spy_get_type

    execute_apply_recommendation(
        client, _CUSTOMER_ID, {"recommendation_resource_name": _REC_RESOURCE}
    )

    assert requested == ["ApplyRecommendationOperation"]


def test_dismiss_uses_dismiss_recommendation_operation_type() -> None:
    """O executor pede o operation type aninhado do request de dismiss."""
    client, rec_service = _client_with_recommendation_service()

    requested: list[str] = []
    _orig_get_type = client.get_type

    def _spy_get_type(name: str) -> CapturedOp:
        requested.append(name)
        return _orig_get_type(name)

    client.get_type = _spy_get_type

    execute_dismiss_recommendation(
        client, _CUSTOMER_ID, {"recommendation_resource_name": _REC_RESOURCE}
    )

    assert requested == ["DismissRecommendationRequest.DismissRecommendationOperation"]


def test_executors_return_service_response() -> None:
    """O executor devolve o objeto response da service call (usado upstream p/ request_id)."""
    client, rec_service = _client_with_recommendation_service()
    sentinel = MagicMock(name="apply_response")
    rec_service.apply_recommendation = MagicMock(return_value=sentinel)

    out = execute_apply_recommendation(
        client, _CUSTOMER_ID, {"recommendation_resource_name": _REC_RESOURCE}
    )
    assert out is sentinel
