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


@dataclass(frozen=True, slots=True)
class LeituraDeFalhas:
    """O que se sabe sobre QUEM falhou num lote — e se da para saber.

    `medido=False` NAO e "nenhuma linha falhou": e "nao consegui ler quem
    falhou". Quem consome traduz isso para o vocabulario da sua superficie; o
    que nao pode e ler `erros` vazio como ausencia de falha.

    E um dataclass, nao `tuple[dict, bool]`, de proposito: tupla e
    desempacotavel por descuido, e `erros, _ = ...` passaria batido numa
    revisao. Sem `.items()`, os tres call-sites de hoje quebram no MYPY, que e
    onde se quer que quebrem.
    """

    erros: dict[int, ErroDeLinha]
    medido: bool


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
) -> LeituraDeFalhas:
    """Mapa `indice da operacao -> erro`, mais se a leitura foi CONFIAVEL.

    Antes devolvia `dict` cru, e `{}` significava duas coisas incompativeis:
    "nenhuma linha falhou" e "nao consegui ler". A justificativa escrita aqui
    para engolir a falha era que "quem chama ja tem a contagem de falhas por
    outra via" — verdade em `run_mutation` (le `WhichOneof`) e em
    `run_conversion_upload` (heuristica em `results`), e FALSA no Customer
    Match, cuja resposta so tem o `partial_failure_error`. A docstring do
    modulo ja dizia isso, dois paragrafos acima, sem que ninguem cruzasse os
    dois fatos.
    """
    erros: dict[int, ErroDeLinha] = {}
    medido = True
    desempacotou_algum = False
    try:
        # As duas leituras abaixo ficavam FORA do `try` (minor 5 do F191).
        # `getattr` com default so engole `AttributeError`: qualquer outra
        # excecao ao LER o erro subia inteira, com a PII ja anexada, e o
        # Customer Match ficava com o default `membros_recusados=[]` — "zero
        # recusados", medido. Dentro do `try`, ela vira "nao medido".
        pfe = getattr(response, "partial_failure_error", None)
        if pfe is None or getattr(pfe, "code", 0) == 0:
            return LeituraDeFalhas(erros, medido=True)

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
            # O retorno do `Unpack` era DESCARTADO. Sondado em 21/09: ele
            # devolve bool, NAO levanta na divergencia, e compara pelo NOME
            # COMPLETO do tipo — entao um type_url de outra versao deixa
            # `failure_pb` zerado e o laco abaixo nao roda. O filtro acima e
            # agnostico de versao de proposito; o alvo aqui e versionado. A
            # defesa esta num lado e a sensibilidade no outro.
            if not raw.Unpack(failure_pb):
                medido = False
                log.warning(
                    "partial_failure_unpack_recusou",
                    type_url=str(raw.type_url),
                    **contexto,
                )
                continue
            desempacotou_algum = True
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
        medido = False

    # `code != 0` afirma que HOUVE falha. Chegar aqui sem ter desempacotado
    # nenhum detail significa que nao se sabe QUAIS — dizer "medi e nao achei"
    # seria o defeito original com roupa nova. O mesmo vale quando ALGUM
    # detail desempacotou (`desempacotou_algum=True`) mas nenhum erro dentro
    # dele trouxe `field_path_elements`: o `continue` do laco acima deixa
    # `erros` vazio do mesmo jeito, e `desempacotou_algum` sozinho nao prova
    # que alguma linha foi atribuida (item 1 da revisao final — reproduzido em
    # `test_unpack_ok_mas_nenhum_erro_com_indice_nao_e_medido`).
    if not desempacotou_algum or not erros:
        medido = False
    return LeituraDeFalhas(erros, medido=medido)
