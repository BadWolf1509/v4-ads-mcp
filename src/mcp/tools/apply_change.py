# bucket: always
"""Tool: apply_change - consume a confirmation token + execute the saved mutation.

Sprint 3b.26 introduces branching: operation_type=="import_offline_conversions" routes
to run_conversion_upload (ConversionUploadService); else routes to run_mutation
(GoogleAdsService.mutate).

Dois ramos releem o estado ANTES de mutar e recusam na divergencia
(concorrencia otimista): `update_ad_schedule` compara o fingerprint da grade, e
`apply_recommendation` compara os valores que o preview prometeu — nos dois, o
que viaja no token e um retrato de ate `DEFAULT_TTL_MINUTES` atras.
"""

from typing import Any

import structlog

from src.db import connection
from src.google_ads.ad_schedule import (
    CurrentWindow,
    bid_modifier_diverge,
    schedule_fingerprint,
    summarize_current,
    window_from_input,
)
from src.google_ads.conversions import run_conversion_upload
from src.google_ads.mutations import run_mutation, run_recommendation_action
from src.google_ads.queries.ad_schedule import (
    GRADE_LIMIT,
    ad_schedule_query,
    parse_ad_schedule_row,
)
from src.google_ads.queries.recommendations import (
    descrever_divergencia,
    parse_recommendation_detail_row,
    recommendation_detail_query,
    recommendation_fingerprint,
)
from src.google_ads.reports import run_report
from src.governance.dry_run import DEFAULT_TTL_MINUTES, InvalidTokenError, consume
from src.mcp.context import get_current
from src.mcp.tools._common import aplicar_limite
from src.mcp.tools._mutate_common import (
    applied_envelope,
    error_envelope,
    submitted_envelope,
)
from src.mcp.tools._registry import register_tool
from src.mcp.tools.get_ad_schedule import campanhas_com_grade_incerta, rows_to_current

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


def _bid_modifier_bate(atual: float | None, esperado: float | None) -> bool:
    """Fix I2 (revisao final): `esperado` vem de `windows_bid_modifiers` (payload
    do update_ad_schedule) — o efetivo POR JANELA que a Task 4 ja calculava, so
    que nunca guardado pra confirmacao. `esperado is None` quer dizer "esta
    janela nao pediu bid_modifier nenhum" (nem por ela, nem pelo escalar da
    chamada) — nesse caso so a IDENTIDADE importa, e a comparacao passa por
    definicao. Com tolerancia (`bid_modifier_diverge`), a MESMA do item C1 —
    e a mesma comparacao Google-contra-pedido, so que na confirmacao pos-apply
    em vez do dry-run."""
    if esperado is None:
        return True
    return not bid_modifier_diverge(atual, esperado)


def _matches_requested(
    servindo: list[CurrentWindow],
    pedidas_com_modificador: dict[tuple[str, int, int, int, int], float | None],
) -> bool:
    """Fix I2 (revisao final): antes, `matches_requested` comparava SO o conjunto
    de identidades de janela (`{c.window.key()} == pedidas`) — a unica coisa que
    esta sprint acrescentou, o bid_modifier por janela, nunca entrava na
    confirmacao. O Google podia aceitar a operacao e aplicar um valor diferente
    do pedido (clamp, arredondamento, no-op) e `matches_requested` diria `true`
    do mesmo jeito. Agora confirma as DUAS coisas: identidade (chaves iguais) E
    o bid_modifier efetivo de cada janela pedida."""
    atual = {c.window.key(): c.bid_modifier for c in servindo}
    if set(atual) != set(pedidas_com_modificador):
        return False
    return all(
        _bid_modifier_bate(atual[chave], esperado)
        for chave, esperado in pedidas_com_modificador.items()
    )


@register_tool(
    name="apply_change",
    description=(
        "[CORE] Confirma e aplica uma mutacao previamente previewed via dry-run. Token "
        # O numero vem de DEFAULT_TTL_MINUTES: escrito a mao, ele e uma segunda
        # fonte de verdade e a description passa a mentir quando o TTL mudar.
        f"expira em {DEFAULT_TTL_MINUTES} minutos. Cada token e consumivel apenas 1 vez "
        "e amarrado a sessao MCP que o gerou. Lote com partial_failure devolve "
        "`partial_failures` (motivo por linha) e `failed_count` ao lado de "
        "`applied_count`."
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

    target_count = int(saved.payload.get("__target_count__", 1))
    params_summary = saved.payload.get("__params_summary__")  # None → default in dispatchers

    # Sprint 3b.26: branch dispatch based on operation_type.
    if saved.operation_type == "import_offline_conversions":
        # ConversionUploadService path (NOT GoogleAdsService.mutate).
        result = await run_conversion_upload(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=saved.customer_id,
            operation_type=saved.operation_type,
            payload=saved.payload,
            target_count=target_count,
            params_summary=params_summary,
        )
        # If error from dispatcher, return as-is.
        if result.get("status") == "error":
            return result
        # Conversion upload response — different shape from mutation response.
        return applied_envelope(
            saved.operation_type,
            saved.customer_id,
            saved.blast_summary,
            applied_count=result["applied_count"],
            provider_request_id=result["provider_request_id"],
            failed_count=result["failed_count"],
            failures=result["failures"],
        )

    # C2: RecommendationService path. Sem este ramo o token que o
    # `apply_recommendation` passou a emitir cairia no `run_mutation` la embaixo,
    # que so sabe montar operacoes do GoogleAdsService.mutate — a tool preveria
    # sem nunca aplicar (F150). O gate por conta e a quota vivem dentro do
    # `run_recommendation_action`, iguais aos do caminho auto.
    if saved.operation_type == "apply_recommendation":
        # I3 — concorrencia otimista, o mesmo padrao do ramo update_ad_schedule
        # 40 linhas abaixo (Ruling 10). Aqui e ainda mais necessario: a operacao
        # do RecommendationService viaja SO com o resource_name, sem parametro
        # nenhum — quem resolve o valor e o Google, no instante do apply. Entre o
        # preview e a confirmacao passa o TTL inteiro (DEFAULT_TTL_MINUTES), e nele
        # o Google pode revisar a recomendacao. Sem este recheck, o
        # `blast_summary` reexibido aqui diria "R$ 50,00 -> R$ 180,00" enquanto
        # outro numero aterrissa — o que anula o motivo de mostrar o numero.
        #
        # RECUSA, nao "aplica avisando": este e o caminho que o gestor percorre
        # DEPOIS de ter lido e aceito um numero. Consentimento dado a R$ 180 nao
        # cobre R$ 300, e um aviso emitido junto com a resposta chega quando a
        # escrita ja aconteceu — nao e decisao, e notificacao. O caminho de volta
        # custa uma chamada: a recomendacao continua pendente, o
        # `apply_recommendation` gera token novo sobre o valor novo, e o gestor
        # decide vendo o numero que vale.
        #
        # O read e ANTES da escrita, entao propagar excecao e o lado seguro (nada
        # mutou) — o tratamento best-effort do F83/F91 vale so depois da mutacao.
        esperado = saved.payload.get("valores_do_preview")
        rec_rn = saved.payload["recommendation_resource_name"]
        if esperado is None:
            # Token emitido por uma revisao anterior a este recheck. Nao e
            # fallback calado: sem a impressao guardada nao ha o que comparar, e
            # aplicar assim mesmo seria exatamente o buraco que este ramo fecha.
            return error_envelope(
                "apply_recommendation",
                "Este token foi emitido por uma versao anterior da tool e nao carrega "
                "os valores previstos, entao nao da pra conferir se a recomendacao "
                "mudou. Nada foi aplicado. Refaca o apply_recommendation para gerar "
                "um token novo.",
                customer_id=saved.customer_id,
            )
        linhas = await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=saved.customer_id,
            query=recommendation_detail_query(rec_rn),
            row_formatter=parse_recommendation_detail_row,
            operation_name="apply_recommendation_precheck",
        )
        if not linhas:
            return error_envelope(
                "apply_recommendation",
                f"A recomendacao {rec_rn} nao esta mais pendente na conta "
                f"{saved.customer_id} (aplicada, dispensada ou expirada desde o "
                "preview). Nada foi aplicado. Use get_recommendations para ver o que "
                "resta.",
                customer_id=saved.customer_id,
            )
        agora = recommendation_fingerprint(linhas[0])
        if agora != esperado:
            return error_envelope(
                "apply_recommendation",
                "O Google revisou esta recomendacao desde o preview — o valor que voce "
                "confirmou nao e mais o que seria aplicado ("
                f"{descrever_divergencia(esperado, agora)}). Nada foi aplicado. Refaca "
                "o apply_recommendation para ver o valor atual e gerar um token novo.",
                customer_id=saved.customer_id,
            )

        result = await run_recommendation_action(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=saved.customer_id,
            operation_type=saved.operation_type,
            payload=saved.payload,
        )
        return applied_envelope(
            saved.operation_type,
            saved.customer_id,
            saved.blast_summary,
            applied_count=result["applied_count"],
            provider_request_id=result["provider_request_id"],
        )

    # Sprint 3b.28: OfflineUserDataJobService path (Customer Match upload).
    if saved.operation_type == "upload_customer_match_list":
        from src.google_ads.customer_match import run_offline_user_data_job

        result = await run_offline_user_data_job(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=saved.customer_id,
            user_list_id=saved.payload["user_list_id"],
            operation_type=saved.payload["operation"],
            hashed_members=saved.payload["hashed_members"],
        )
        job_id = result["job_resource_name"].rsplit("/", 1)[-1]
        # `submitted`, nao `applied`: o job roda no backend do Google por horas.
        return submitted_envelope(
            "upload_customer_match_list",
            saved.customer_id,
            saved.blast_summary,
            user_list_id=saved.payload["user_list_id"],
            operation_type=saved.payload["operation"],
            # R1-I3: `members_submitted` e o que o Google ACEITOU. O que ele
            # recusou (hash mal formado, identificador nao suportado) aparece
            # ao lado, com o motivo por linha — antes o lote inteiro era
            # reportado como submetido.
            members_submitted=result["members_submitted"],
            members_failed=result["members_failed"],
            failures=result["failures"],
            job_resource_name=result["job_resource_name"],
            provider_request_id_create_job=result["provider_request_id_create_job"],
            provider_request_id_add_ops=result["provider_request_id_add_ops"],
            provider_request_id_run_job=result["provider_request_id_run_job"],
            to_check_status=(
                f"Job é assíncrono no backend Google (processa em horas). "
                f"Pra verificar status, use run_gaql com query 'SELECT "
                f"offline_user_data_job.status, offline_user_data_job."
                f"failure_reason FROM offline_user_data_job WHERE "
                f"offline_user_data_job.id = {job_id}'."
            ),
        )

    # ad_schedule §4.6: confirmacao de estado por GAQL. A UI falhou em silencio duas
    # vezes nessa conta; confiar no ACK da mutacao repetiria o problema num canal novo.
    if saved.operation_type == "update_ad_schedule":
        # Ruling 3 (ledger): estas chaves sao obrigatorias no payload (a tool sempre
        # grava); `.get(..., <default>)` seria o fallback calado que a Task 4 proibiu.
        campaign_ids = list(saved.payload["campaign_ids"])
        # Fix I2 (revisao final): `windows_bid_modifiers` e chave PARALELA a
        # `windows` (mesma ordem, gravada pelo update_ad_schedule) — dict por
        # chave de janela, nao lista, pra `_matches_requested` comparar direto.
        pedidas_com_modificador = {
            window_from_input(w).key(): m
            for w, m in zip(
                saved.payload["windows"], saved.payload["windows_bid_modifiers"], strict=True
            )
        }

        # Ruling 10 — concorrencia otimista. O que viaja no token e um DELTA calculado
        # ate 10 min antes, carregando resource_names observados naquele instante. Se a
        # grade mudou nesse meio tempo, aplicar o delta produz uma grade que nao e nem a
        # antiga nem a pedida — em silencio, porque partial_failure engole o erro por-op.
        # Este read e ANTES da escrita: se ele falhar, propagar e o lado seguro (nada
        # mutou ainda) — o tratamento best-effort do F83/F91 vale so depois da mutacao.
        rows_antes = await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=saved.customer_id,
            query=ad_schedule_query(campaign_ids=campaign_ids, status="enabled", limit=GRADE_LIMIT),
            row_formatter=parse_ad_schedule_row,
            operation_name="update_ad_schedule_precheck",
        )
        # Grade truncada aqui nao precisa de ramo proprio: o dry-run RECUSA acima de
        # GRADE_LIMIT, entao um fingerprint de 1001 linhas nunca bate com o guardado —
        # cai na divergencia abaixo, que e o lado seguro.
        if (
            schedule_fingerprint(rows_to_current(rows_antes), campaign_ids)
            != saved.payload["current_keys"]
        ):
            return error_envelope(
                "update_ad_schedule",
                "A grade mudou desde o preview (alguem alterou a agenda destas campanhas "
                "nos ultimos minutos). Nenhuma operacao foi aplicada. Refaca o "
                "update_ad_schedule para gerar um token novo sobre o estado atual.",
                customer_id=saved.customer_id,
            )

        result = await run_mutation(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=saved.customer_id,
            operation_type=saved.operation_type,
            payload=saved.payload,
            target_count=target_count,
            partial_failure=True,
            params_summary=params_summary,
        )
        # F83/F91: a mutacao ja aplicou (result acima e definitivo). A reconsulta e
        # I/O DEPOIS da escrita — se ela falhar (rede, GoogleAdsException transiente,
        # rate limit), isso nao pode transformar um sucesso em erro pro caller.
        resulting: dict[str, Any] | None
        confirmation_error: str | None = None
        try:
            # status="all" de proposito (spec §7): janela removida tem que ser
            # confirmada por PRESENCA de status REMOVED. Filtrar ENABLED confirmaria
            # a remocao por a linha NAO aparecer — exatamente o que a §7 proibe, e o
            # que a propria §7 estende "para a confirmacao que a tool faz pos-apply".
            rows = await run_report(
                manager_id=ctx.manager_id,
                session_id=ctx.session_id,
                customer_id=saved.customer_id,
                query=ad_schedule_query(campaign_ids=campaign_ids, status="all", limit=GRADE_LIMIT),
                row_formatter=parse_ad_schedule_row,
                operation_name="update_ad_schedule_confirm",
            )
            # `ad_schedule_query` pede `GRADE_LIMIT + 1`: a sobra e a prova de que a
            # leitura foi PARCIAL. Sem esta checagem, campanha cujas linhas cairam
            # alem do corte chega em `summarize_current([])`, que devolve
            # `has_schedule: false` + `hours_per_week: 168` — a frase "serve 24x7".
            # Aqui isso e pior do que no `get_ad_schedule`: e o resumo que o gestor
            # le DEPOIS de ter mudado a grade, e ele diria que a campanha que acabou
            # de ser restringida passou a servir o tempo todo. Mesmo defeito, pior
            # lugar (F128: a clausula ficou de fora de um dos gemeos).
            #
            # A1 (revisao final): o CORTE vem antes de qualquer derivacao. Ate aqui
            # `servindo` era montado sobre a lista NAO-cortada, entao a linha
            # sentinela — a `GRADE_LIMIT + 1`-esima, cuja unica funcao e provar que
            # havia mais — entrava no resumo: `windows_count: 2` ao lado de
            # `len(windows) == 1`, e um `matches_requested` decidido com uma janela
            # que a propria resposta declara nao ter lido. A gemea
            # (`get_ad_schedule`) sempre cortou primeiro; a ordem aqui e a mesma.
            rows, leitura_parcial = aplicar_limite(rows, GRADE_LIMIT)
            # O resumo (has_schedule/hours_per_week) conta so o que esta SERVINDO;
            # com status="all" nas linhas, somar REMOVED inflaria as horas.
            servindo = rows_to_current([r for r in rows if r["status"] == "ENABLED"])
            # A2 (revisao final, residuo do F147): "incerta" nao e so a campanha
            # AUSENTE do corte — e tambem a da BORDA, dona da ultima linha lida,
            # cuja grade pode ter sido cortada no meio. Mesma funcao que o gemeo
            # `get_ad_schedule` chama; duas copias da regra e como o F128 nasceu.
            incertas = campanhas_com_grade_incerta(
                rows, truncated=leitura_parcial, campanhas=campaign_ids
            )

            def _resumo(cid: str) -> dict[str, Any]:
                if cid in incertas:
                    return {
                        "has_schedule": None,
                        "windows_count": None,
                        "hours_per_week": None,
                        "schedule_desconhecida_por_truncamento": True,
                    }
                r = summarize_current(servindo.get(cid, []))
                return {
                    "has_schedule": r["has_schedule"],
                    "windows_count": r["windows"],
                    "hours_per_week": r["hours_per_week"],
                }

            # `windows` e a LISTA de linhas; `summarize_current` devolve um `windows`
            # que e CONTAGEM. Renomear a contagem para `windows_count` tira a colisao
            # que antes so nao mordia por ordem de spread — e ordem de spread e uma
            # garantia que some no primeiro refactor.
            resulting = {
                cid: {
                    **_resumo(cid),
                    "windows": [r for r in rows if r["campaign_id"] == cid],
                    "matches_requested": (
                        None
                        if cid in incertas
                        else _matches_requested(servindo.get(cid, []), pedidas_com_modificador)
                    ),
                    "truncated": leitura_parcial,
                }
                for cid in campaign_ids
            }
        except Exception as e:  # noqa: BLE001 — I/O apos escrita ja aplicada: nunca transformar sucesso em erro (F83/F91)
            log.warning(
                "update_ad_schedule_confirm_failed",
                customer_id=saved.customer_id,
                error=str(e),
                error_type=e.__class__.__name__,
            )
            resulting = None
            confirmation_error = (
                f"A mutacao foi aplicada (veja applied_count/provider_request_id), mas a "
                f"reconsulta da grade falhou ({e.__class__.__name__}). Confirme o estado "
                f"com get_ad_schedule antes de confiar no resultado."
            )
        return applied_envelope(
            saved.operation_type,
            saved.customer_id,
            saved.blast_summary,
            applied_count=result["applied_count"],
            provider_request_id=result["provider_request_id"],
            changed_count=result.get("changed_count"),
            # Spec §4.5: "a resposta separa aplicadas de falhas, com o motivo de cada
            # falha". Lote com partial_failure=True e onde isso acontece.
            partial_failures=result.get("partial_failures", []),
            resource_names=result.get("resource_names", []),
            resulting_schedule=resulting,
            confirmation_error=confirmation_error,
        )

    # Default path: chained mutation via GoogleAdsService.mutate (Sprint 3b.1-3b.25).
    partial_failure = bool(saved.payload.get("__partial_failure__", False))
    result = await run_mutation(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=saved.customer_id,
        operation_type=saved.operation_type,
        payload=saved.payload,
        target_count=target_count,
        partial_failure=partial_failure,
        params_summary=params_summary,
    )
    # R1-I1: cinco tools chegam aqui com `__partial_failure__` ligado —
    # `add_keywords`, `apply_audience`, `bulk_pause_by_query`,
    # `remove_asset_link` e `remove_audience` (a sexta, `update_ad_schedule`,
    # tem ramo proprio acima e ja devolvia isto). Quando o Google aceita parte,
    # o motivo de cada recusa vinha no `result` e morria nesta linha: o gestor
    # lia "applied" com `applied_count` menor que o pedido e nenhum porque.
    partial_failures = result.get("partial_failures", [])
    return applied_envelope(
        saved.operation_type,
        saved.customer_id,
        saved.blast_summary,
        applied_count=result["applied_count"],
        provider_request_id=result["provider_request_id"],
        # F139: quantos de fato mudaram. `applied_count` conta o tentado, entao
        # numa re-remocao ele diz 1 para uma operacao que nao mudou nada.
        changed_count=result.get("changed_count"),
        partial_failures=partial_failures,
        failed_count=sum(1 for r in partial_failures if r["status"] == "failed"),
        resource_names=result.get("resource_names", []),
    )
