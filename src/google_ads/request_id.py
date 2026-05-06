"""Capture Google Ads request_id from gRPC trailing metadata on success path.

The official google-ads SDK only exposes ``request_id`` via
``GoogleAdsException`` (failure path).  On success, the high-level service
calls (e.g. ``ga_service.mutate(request)``) return the unwrapped proto-plus
message — there's no public attribute that surfaces the request_id from
the trailing gRPC metadata.

This module provides a custom ``UnaryUnaryClientInterceptor`` that reads
the ``request-id`` trailing-metadata key and stores it in a per-task
``ContextVar``.  Mutation helpers register the interceptor by passing it
explicitly to ``client.get_service(name, interceptors=[...])`` (an
internal-but-stable kwarg of the SDK), reset the context variable before
the call, and read it back after.

Why bypass ``response.trailing_metadata()``?  In SDK 30.x the SDK still
wraps responses in ``_UnaryUnaryWrapper`` whose ``trailing_metadata()``
method has a long-standing copy-paste bug — it returns
``self._underlay_call.initial_metadata()`` instead of trailing metadata
(see ``response_wrappers.py:139-140``).  We reach through the private
``_underlay_call`` attribute to call gRPC's real ``trailing_metadata()``.
If a future SDK refactor renames the attribute, the ``getattr`` fallback
keeps the call from raising — we just won't capture the id and audit_log
shows ``None``.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

import grpc

_REQUEST_ID_METADATA_KEY = "request-id"

_last_request_id: ContextVar[str | None] = ContextVar("v4ads_last_request_id", default=None)


class _CaptureTrailingMetadataInterceptor(grpc.UnaryUnaryClientInterceptor):  # type: ignore[misc]
    """Captures the gRPC ``request-id`` trailing metadata into a ContextVar.

    Installed via ``client.get_service(name, interceptors=[...])``.  Runs
    on every unary-unary call (e.g. ``GoogleAdsService.mutate``).  Stores
    only the ``request-id`` key; everything else is ignored.
    """

    def intercept_unary_unary(
        self,
        continuation: Any,
        client_call_details: Any,
        request: Any,
    ) -> Any:
        response = continuation(client_call_details, request)
        try:
            # SDK 30.x wraps in _UnaryUnaryWrapper; its trailing_metadata() is
            # broken (returns initial_metadata).  Reach through _underlay_call.
            underlay = getattr(response, "_underlay_call", response)
            metadata = underlay.trailing_metadata() or []
            for key, value in metadata:
                if key == _REQUEST_ID_METADATA_KEY:
                    _last_request_id.set(value or None)
                    break
        except Exception:
            # Defensive: trailing metadata not always populated; never let
            # the observability hook fail the actual mutation.
            pass
        return response


_INTERCEPTOR_SINGLETON = _CaptureTrailingMetadataInterceptor()


def get_capture_interceptor() -> grpc.UnaryUnaryClientInterceptor:
    """Singleton interceptor to pass into ``client.get_service(..., interceptors=[...])``."""
    return _INTERCEPTOR_SINGLETON


def reset_request_id() -> None:
    """Clear the captured request_id before issuing a new call."""
    _last_request_id.set(None)


def get_request_id() -> str | None:
    """Read the request_id captured by the most recent intercepted call in this context."""
    return _last_request_id.get()
