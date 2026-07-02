"""Testes de src/google_ads/request_id.py — contextvar + interceptor gRPC.

Cobre:
- get_request_id / reset_request_id (ContextVar por task).
- get_capture_interceptor (singleton).
- A lógica do interceptor: lê a trailing metadata via _underlay_call (bypass do
  bug de trailing_metadata() do wrapper SDK 30.x), captura só a chave 'request-id',
  e NUNCA deixa a hook de observabilidade quebrar a mutation (swallow de exceção).

O interceptor é exercitado com um `continuation` fake + objeto response fake que expõe
`_underlay_call.trailing_metadata()` — não precisa de infra gRPC real (a lógica só faz
getattr + itera pares (key, value)).
"""

from typing import Any

from src.google_ads.request_id import (
    _CaptureTrailingMetadataInterceptor,
    get_capture_interceptor,
    get_request_id,
    reset_request_id,
)


class _FakeUnderlay:
    """Stub do _underlay_call: trailing_metadata() devolve pares (key, value)."""

    def __init__(self, metadata: Any) -> None:
        self._metadata = metadata

    def trailing_metadata(self) -> Any:
        return self._metadata


class _FakeResponse:
    """Response fake com _underlay_call (o caminho feliz que o interceptor busca)."""

    def __init__(self, metadata: Any) -> None:
        self._underlay_call = _FakeUnderlay(metadata)


def _run_interceptor(response: Any) -> Any:
    """Roda intercept_unary_unary com uma continuation que devolve `response`."""
    interceptor = _CaptureTrailingMetadataInterceptor()

    def _continuation(details: Any, request: Any) -> Any:
        return response

    return interceptor.intercept_unary_unary(_continuation, object(), object())


# ---------------------------------------------------------------------------
# contextvar helpers
# ---------------------------------------------------------------------------


def test_reset_then_get_is_none() -> None:
    reset_request_id()
    assert get_request_id() is None


def test_get_reads_value_set_by_interceptor() -> None:
    reset_request_id()
    _run_interceptor(_FakeResponse([("request-id", "REQ-ABC-123")]))
    assert get_request_id() == "REQ-ABC-123"


def test_reset_clears_previously_captured() -> None:
    _run_interceptor(_FakeResponse([("request-id", "REQ-XYZ")]))
    assert get_request_id() == "REQ-XYZ"
    reset_request_id()
    assert get_request_id() is None


# ---------------------------------------------------------------------------
# singleton
# ---------------------------------------------------------------------------


def test_get_capture_interceptor_is_singleton() -> None:
    assert get_capture_interceptor() is get_capture_interceptor()
    assert isinstance(get_capture_interceptor(), _CaptureTrailingMetadataInterceptor)


# ---------------------------------------------------------------------------
# interceptor logic
# ---------------------------------------------------------------------------


def test_interceptor_returns_response_unchanged() -> None:
    """Passthrough: o interceptor DEVE devolver o response da continuation intacto."""
    reset_request_id()
    resp = _FakeResponse([("request-id", "R1")])
    out = _run_interceptor(resp)
    assert out is resp


def test_interceptor_captures_only_request_id_key() -> None:
    reset_request_id()
    _run_interceptor(
        _FakeResponse(
            [
                ("some-other-key", "ignore-me"),
                ("request-id", "THE-ONE"),
                ("trailing-junk", "nope"),
            ]
        )
    )
    assert get_request_id() == "THE-ONE"


def test_interceptor_empty_value_stored_as_none() -> None:
    """Valor vazio na metadata → armazenado como None (o `value or None`)."""
    reset_request_id()
    _run_interceptor(_FakeResponse([("request-id", "")]))
    assert get_request_id() is None


def test_interceptor_no_request_id_leaves_context_untouched() -> None:
    """Metadata sem 'request-id' → contextvar permanece no que estava (aqui: None)."""
    reset_request_id()
    _run_interceptor(_FakeResponse([("other", "x")]))
    assert get_request_id() is None


def test_interceptor_none_metadata_does_not_raise() -> None:
    """trailing_metadata() → None é normalizado pra [] (o `or []`), sem raise."""
    reset_request_id()
    out = _run_interceptor(_FakeResponse(None))
    assert get_request_id() is None
    assert out is not None  # response devolvido


def test_interceptor_swallows_exception_from_trailing_metadata() -> None:
    """Se trailing_metadata() explode, a hook NÃO pode quebrar a mutation.

    O response ainda é devolvido; o request_id fica None (defensivo, docstring).
    """
    reset_request_id()

    class _BoomUnderlay:
        def trailing_metadata(self) -> Any:
            raise RuntimeError("gRPC internals mudaram")

    class _BoomResponse:
        _underlay_call = _BoomUnderlay()

    resp = _BoomResponse()
    out = _run_interceptor(resp)
    assert out is resp
    assert get_request_id() is None


def test_interceptor_falls_back_to_response_when_no_underlay_attr() -> None:
    """Sem _underlay_call, o getattr cai no próprio response (ainda deve ter
    trailing_metadata()). Guard do fallback documentado no módulo."""
    reset_request_id()

    class _DirectResponse:
        def trailing_metadata(self) -> Any:
            return [("request-id", "FROM-DIRECT")]

    _run_interceptor(_DirectResponse())
    assert get_request_id() == "FROM-DIRECT"
