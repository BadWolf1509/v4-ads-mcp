"""Leitura do `partial_failure_error` — a unica forma de saber QUEM falhou num lote.

As tres APIs de escrita que este projeto usa (`GoogleAdsService.mutate`,
`ConversionUploadService.UploadClickConversions` e
`OfflineUserDataJobService.AddOfflineUserDataJobOperations`) reportam falha
por-linha do MESMO jeito: um `google.rpc.Status` no TOPO da resposta, cujo
`details[]` traz um `GoogleAdsFailure` empacotado, e cada erro dentro dele
aponta a linha por `location.field_path_elements[0].index`.

Este modulo existe porque a terceira leitora (Customer Match, R1-I3) precisava
do mesmo desempacotamento que `mutations.py` e `conversions.py` ja faziam cada
uma por conta propria. Uma terceira copia seria a terceira fonte de verdade do
mesmo conhecimento de proto — e drift de SDK quebraria as tres em momentos
diferentes.

O que este modulo NAO faz: dizer quantas linhas houve. Isso e diferente em cada
API (`mutate_operation_responses` no mutate, `results` no upload, e NADA no
Customer Match, cuja resposta so tem o `partial_failure_error`) e continua com
cada leitora.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ErroDeLinha:
    """O que o Google diz sobre UMA linha recusada.

    `error_code` e a forma legivel do enum (`str(gae.error_code)` cortado no
    ultimo `:`); `error_message` e a mensagem. As duas leitoras antigas usavam
    metades diferentes disto — `mutations.py` so a mensagem, `conversions.py` as
    duas — entao o tipo carrega as duas e quem chama escolhe.
    """

    error_code: str
    error_message: str


def _codigo(gae: Any) -> str:
    """`error_code` do erro, e "UNKNOWN" quando ele nao vier.

    Deliberadamente tolerante, e nao por comodidade: das tres leitoras, so duas
    usam o codigo — `run_mutation` sempre leu apenas `message` e `location`.
    Se a ausencia do codigo derrubasse a extracao inteira (o `except` la de
    baixo engoliria o lote todo), o refactor teria tornado o caminho de mutate
    MAIS fragil do que era, trocando "sem codigo" por "sem motivo nenhum". A
    mensagem e a parte que carrega o peso; o codigo e complemento.
    """
    bruto = getattr(gae, "error_code", None)
    if bruto is None:
        return "UNKNOWN"
    return str(bruto).split(":")[-1].strip() or "UNKNOWN"


def erros_por_indice(
    response: Any,
    client: Any,
    **contexto: Any,
) -> dict[int, ErroDeLinha]:
    """Mapa `indice da operacao -> erro`, extraido do `partial_failure_error`.

    Devolve `{}` quando nao houve falha alguma (`code == 0`), quando a resposta
    nem tem o campo, e tambem quando o desempacotamento quebra (drift de SDK,
    forma inesperada) — nesse ultimo caso loga com o `contexto` recebido. Cair
    para "nao sei quem falhou" e mais seguro que levantar: quem chama ja tem a
    contagem de falhas por outra via e monta um erro generico por linha.
    """
    erros: dict[int, ErroDeLinha] = {}
    pfe = getattr(response, "partial_failure_error", None)
    if pfe is None or getattr(pfe, "code", 0) == 0:
        return erros

    try:
        for detail in getattr(pfe, "details", []) or []:
            # proto-plus embrulha; o `Any` cru mora em `_pb`.
            raw = detail._pb if hasattr(detail, "_pb") else detail
            # Duck-typing em vez de isinstance: a classe `google.protobuf.any_pb2.Any`
            # muda de caminho entre versoes do SDK.
            if not (hasattr(raw, "type_url") and hasattr(raw, "Unpack")):
                continue
            # `GoogleAdsFailure` e o unico detail que o Google manda aqui; o
            # type_url evita importar a classe versionada do proto.
            if "GoogleAdsFailure" not in raw.type_url:
                continue
            failure_pb = client.get_type("GoogleAdsFailure")._meta.pb()
            raw.Unpack(failure_pb)
            for gae in failure_pb.errors:
                if not gae.location.field_path_elements:
                    continue
                idx = int(gae.location.field_path_elements[0].index)
                erros[idx] = ErroDeLinha(
                    error_code=_codigo(gae),
                    error_message=str(gae.message),
                )
    except Exception:
        log.exception("partial_failure_detail_unpack_failed", **contexto)
    return erros
