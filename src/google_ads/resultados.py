"""Contratos tipados do que os executores do Google devolvem.

So tipos: nenhum comportamento. `TypedDict` nao e atribuivel a `dict[str, Any]`,
por isso o `Executor` de `confirmadores.py` devolve `Mapping[str, Any]`.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class ResultadoMutacao(TypedDict):
    """`run_mutation`."""

    provider_request_id: str | None
    applied_count: int
    # None quando a resposta nao traz resource_names (drift de SDK).
    changed_count: int | None
    partial_failures: list[dict[str, Any]]
    resource_names: list[str | None]
    # None quando partial_failure=False ("nao perguntei").
    motivos_medidos: bool | None


class ResultadoRecomendacao(TypedDict):
    """`run_recommendation_action`."""

    provider_request_id: str | None
    applied_count: int


class ResultadoUploadAplicado(TypedDict):
    """`run_conversion_upload`, caminho de sucesso."""

    status: Literal["applied"]
    operation: str
    customer_id: str
    applied_count: int
    failed_count: int
    failures: list[dict[str, Any]]
    provider_request_id: str
    motivos_medidos: bool | None


class ResultadoUploadErro(TypedDict):
    """`run_conversion_upload`, caminho de erro."""

    status: Literal["error"]
    operation: str
    customer_id: str
    # None so se o status virou erro sem texto (nao ocorre hoje).
    error_message: str | None
    provider_request_id: str


class ResultadoCustomerMatch(TypedDict):
    """`run_offline_user_data_job`."""

    job_resource_name: str | None
    provider_request_id_create_job: str
    provider_request_id_add_ops: str
    provider_request_id_run_job: str
    # None nos tres quando a leitura de recusas nao foi confiavel.
    members_submitted: int | None
    members_failed: int | None
    failures: list[dict[str, Any]] | None
    recusas_medidas: bool
