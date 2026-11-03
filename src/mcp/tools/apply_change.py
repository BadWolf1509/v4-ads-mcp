# bucket: always
"""Tool: apply_change - consume a confirmation token + execute the saved mutation.

Despachante (Task G5): consome o token UMA vez, escolhe o confirmador pelo
`operation_type` (`src/google_ads/confirmadores.py`) e roda `pre_check` ->
`executar` -> `pos_check`. O que cada operacao faz ao ser confirmada — recheck de
concorrencia otimista, a escrita, a reconsulta pos-apply e o envelope — vive no
confirmador dela; aqui fica so o que e da camada MCP: contexto da request,
consumo do token e as portas (executores, envelopes, logger) que o confirmador
recebe.
"""

from typing import Any

import structlog

from src.db import connection
from src.google_ads.confirmadores import Pendente, Portas, confirmador_para
from src.google_ads.conversions import run_conversion_upload
from src.google_ads.mutations import run_mutation, run_recommendation_action
from src.google_ads.queries.ad_schedule import (
    GRADE_LIMIT as GRADE_LIMIT,  # reexport: testes leem mod.GRADE_LIMIT
)
from src.google_ads.reports import run_report
from src.governance.dry_run import DEFAULT_TTL_MINUTES, InvalidTokenError, consume
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import (
    applied_envelope,
    error_envelope,
    submitted_envelope,
)
from src.mcp.tools._registry import register_tool

log = structlog.get_logger(__name__)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confirmation_token": {
            "type": "string",
            "pattern": "^[A-Z0-9]{8}$",
            "description": "Token de 8 chars retornado por uma tool de mutacao em modo dry-run.",
        },
    },
    "required": ["confirmation_token"],
    "additionalProperties": False,
}


@register_tool(
    name="apply_change",
    description=(
        "[CORE] Confirma e aplica uma mutacao previamente previewed via dry-run. Token "
        # O numero vem de DEFAULT_TTL_MINUTES: escrito a mao, ele e uma segunda
        # fonte de verdade e a description passa a mentir quando o TTL mudar.
        f"expira em {DEFAULT_TTL_MINUTES} minutos. Cada token e consumivel apenas 1 vez "
        "e amarrado a sessao MCP que o gerou. A RESPOSTA DIZ sob qual regime rodou: "
        "`partial_failure: true` traz `partial_failures` (motivo por linha) e "
        "`failed_count` medido; `partial_failure: false` traz `partial_failures` VAZIA "
        "e `failed_count: null` — null significa NAO MEDIDO, nao 'nenhuma falhou' "
        "(F182). O regime e decisao da tool de origem, nao um parametro seu. "
        "`partial_failures[].error` tambem pode vir `null`: a linha FALHOU (a "
        "contagem e medida, via WhichOneof/heuristica), so o MOTIVO que nao foi "
        "lido — nao e 'sem motivo', e 'nao consegui ler'. `motivos_medidos` "
        "(bool; `null` quando `partial_failure: false`) resume isso pra resposta "
        "inteira de uma vez: `false` explica todo `error: null` sem exigir "
        "conferencia linha a linha. "
        "ATENCAO (F184): `status: success` numa linha NAO prova que "
        "ela mudou algo — o Google aceita operacao e nao a executa. Cada linha traz "
        "`efeito`: 'mudou', 'sem_efeito' (passou sem mudar nada), ou null "
        "(desconhecido, ou a linha falhou). Para 'aplicou de verdade', leia `efeito` e "
        "`changed_count`. NUNCA leia `failed_count` — ele mede ACEITACAO, nao "
        "execucao: em tres modos de falha medidos em producao (campanha removida, URL "
        "invalida, anuncio apagado entre o preview e o apply) o Google aceitou tudo, e "
        "`failed_count` veio 0 nos tres. Zero ali costuma significar 'ele nao "
        "reportou', nao 'nada falhou', e o `partial_failure: true` ao lado so diz que "
        "a pergunta foi feita, nao que houve resposta. `applied_count` tem UMA "
        "leitura legitima, a subtracao: `applied_count` - `changed_count` = quantas "
        "linhas passaram sem efeito. Isolado ele afirma aceitacao como se fosse "
        "execucao, e engana igual ao `failed_count`."
    ),
    input_schema=_SCHEMA,
    bucket="always",
)
async def apply_change(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    token = args["confirmation_token"]

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        try:
            saved = await consume(conn, token=token, session_id=ctx.session_id)
        except InvalidTokenError as e:
            return error_envelope("apply_change", str(e))

    pendente = Pendente(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=saved.customer_id,
        operation_type=saved.operation_type,
        payload=saved.payload,
        blast_summary=saved.blast_summary,
        target_count=int(saved.payload.get("__target_count__", 1)),
        params_summary=saved.payload.get("__params_summary__"),  # None -> default nos executores
    )
    confirmador = confirmador_para(saved.operation_type)
    portas = _portas()

    # O token ja esta consumido: a recusa manda gerar um novo. Excecao no pre-check
    # propaga — nada mutou ainda, e esse e o lado seguro.
    recusa = await confirmador.pre_check(pendente, portas)
    if recusa is not None:
        return recusa
    # Uma vez, sem retry: mutacao nao e idempotente.
    resultado = await confirmador.executar(pendente, portas)
    # I/O daqui em diante vem depois da escrita aplicada e nunca vira erro (F83/F91).
    return await confirmador.pos_check(pendente, portas, resultado)


def _portas() -> Portas:
    """Lidas do modulo a cada chamada, e nao fixadas no import: os testes substituem
    os executores AQUI (`src.mcp.tools.apply_change.run_mutation` etc.), e o
    Customer Match e resolvido no proprio modulo dele, como sempre foi."""
    from src.google_ads.customer_match import run_offline_user_data_job

    return Portas(
        run_report=run_report,
        run_mutation=run_mutation,
        run_conversion_upload=run_conversion_upload,
        run_recommendation_action=run_recommendation_action,
        run_customer_match=run_offline_user_data_job,
        applied_envelope=applied_envelope,
        submitted_envelope=submitted_envelope,
        error_envelope=error_envelope,
        log=log,
    )
