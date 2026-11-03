"""Confirmadores do `apply_change`: o que cada operacao faz ao ser confirmada.

O `apply_change` e um despachante (Task G5): consome o token, escolhe o
confirmador pelo `operation_type` e roda os tres passos dele, nesta ordem:

1. `pre_check` — leitura ANTES da escrita. Devolve o envelope de recusa ou
   `None`. Se a leitura levantar, a excecao propaga: nada mutou ainda, entao
   propagar e o lado seguro.
2. `executar` — a escrita. Uma vez, sem retry (mutacao nao e idempotente).
3. `pos_check` — monta a resposta. I/O aqui vem DEPOIS de uma escrita ja
   aplicada, entao nunca pode virar erro (F83/F91).

O token ja foi consumido quando o `pre_check` roda: a recusa manda o gestor
gerar um token novo, e a caracterizacao (`test_apply_change_caracterizacao.py`)
prende essa ordem.

Este modulo nao importa `src.mcp` (guard `test_dominio_google_nao_importa_a_camada_mcp`).
O que vive na camada MCP — o contexto da request, os envelopes, o logger da tool —
e os executores chegam em `Pendente` e `Portas`, montados pelo `apply_change` a cada
chamada.

Dois ramos releem o estado ANTES de mutar e recusam na divergencia
(concorrencia otimista): `update_ad_schedule` compara o fingerprint da grade, e
`apply_recommendation` compara os valores que o preview prometeu — nos dois, o
que viaja no token e um retrato de ate `DEFAULT_TTL_MINUTES` atras.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from src.google_ads.ad_schedule import (
    CurrentWindow,
    bid_modifier_diverge,
    campanhas_com_grade_incerta,
    rows_to_current,
    schedule_fingerprint,
    summarize_current,
    window_from_input,
)
from src.google_ads.limite import aplicar_limite
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

Executor = Callable[..., Awaitable[dict[str, Any]]]
Envelope = Callable[..., dict[str, Any]]


@dataclass(frozen=True, slots=True)
class Pendente:
    """A mutacao que o token guardou, com quem a confirma."""

    manager_id: UUID
    session_id: UUID
    customer_id: str
    operation_type: str
    payload: dict[str, Any]
    blast_summary: str
    target_count: int
    params_summary: Any


@dataclass(frozen=True, slots=True)
class Portas:
    """Executores, envelopes e logger que o despachante injeta.

    Injetados, e nao importados aqui, por dois motivos: os envelopes e o logger
    vivem na camada MCP, e os testes do `apply_change` substituem os executores
    no modulo da tool — o despachante os le de la a cada chamada.
    """

    run_report: Callable[..., Awaitable[list[dict[str, Any]]]]
    run_mutation: Executor
    run_conversion_upload: Executor
    run_recommendation_action: Executor
    # Nao `run_offline_user_data_job`: `portas.<nome>(...)` com o nome do metodo do
    # SDK e o que o guard do F86 (`test_chamada_bloqueante_sai_do_event_loop`) acusa.
    run_customer_match: Executor
    applied_envelope: Envelope
    submitted_envelope: Envelope
    error_envelope: Envelope
    log: Any


class Confirmador(Protocol):
    async def pre_check(self, p: Pendente, portas: Portas) -> dict[str, Any] | None: ...

    async def executar(self, p: Pendente, portas: Portas) -> dict[str, Any]: ...

    async def pos_check(
        self, p: Pendente, portas: Portas, resultado: dict[str, Any]
    ) -> dict[str, Any]: ...


class _SemPreCheck:
    async def pre_check(self, p: Pendente, portas: Portas) -> dict[str, Any] | None:
        return None


# --- import_offline_conversions -----------------------------------------------------


class _ConversoesOffline(_SemPreCheck):
    """Sprint 3b.26: ConversionUploadService, NAO GoogleAdsService.mutate."""

    async def executar(self, p: Pendente, portas: Portas) -> dict[str, Any]:
        return await portas.run_conversion_upload(
            manager_id=p.manager_id,
            session_id=p.session_id,
            customer_id=p.customer_id,
            operation_type=p.operation_type,
            payload=p.payload,
            target_count=p.target_count,
            params_summary=p.params_summary,
        )

    async def pos_check(
        self, p: Pendente, portas: Portas, resultado: dict[str, Any]
    ) -> dict[str, Any]:
        # Erro do executor volta como veio.
        if resultado.get("status") == "error":
            return resultado
        # Resposta de upload de conversao — forma diferente da de mutacao.
        return portas.applied_envelope(
            p.operation_type,
            p.customer_id,
            p.blast_summary,
            applied_count=resultado["applied_count"],
            provider_request_id=resultado["provider_request_id"],
            failed_count=resultado["failed_count"],
            failures=resultado["failures"],
            # Item 3 (revisao final, spec §4.2): conversions sempre roda com
            # partial_failure=True (hardcoded em run_conversion_upload), entao
            # isto e sempre um bool medido, nunca None por "nao perguntei".
            motivos_medidos=resultado.get("motivos_medidos"),
        )


# --- apply_recommendation -----------------------------------------------------------


class _Recomendacao:
    """C2: RecommendationService. Sem este confirmador o token que o
    `apply_recommendation` emite cairia no padrao, que so sabe montar operacoes do
    GoogleAdsService.mutate — a tool preveria sem nunca aplicar (F150). O gate por
    conta e a quota vivem dentro do `run_recommendation_action`, iguais aos do
    caminho auto."""

    async def pre_check(self, p: Pendente, portas: Portas) -> dict[str, Any] | None:
        # I3 — concorrencia otimista, o mesmo padrao do `update_ad_schedule`
        # (Ruling 10). Aqui e ainda mais necessario: a operacao do
        # RecommendationService viaja SO com o resource_name, sem parametro nenhum —
        # quem resolve o valor e o Google, no instante do apply. Entre o preview e a
        # confirmacao passa o TTL inteiro (DEFAULT_TTL_MINUTES), e nele o Google pode
        # revisar a recomendacao. Sem este recheck, o `blast_summary` reexibido diria
        # "R$ 50,00 -> R$ 180,00" enquanto outro numero aterrissa — o que anula o
        # motivo de mostrar o numero.
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
        esperado = p.payload.get("valores_do_preview")
        rec_rn = p.payload["recommendation_resource_name"]
        if esperado is None:
            # Token emitido por uma revisao anterior a este recheck. Nao e
            # fallback calado: sem a impressao guardada nao ha o que comparar, e
            # aplicar assim mesmo seria exatamente o buraco que este ramo fecha.
            return portas.error_envelope(
                "apply_recommendation",
                "Este token foi emitido por uma versao anterior da tool e nao carrega "
                "os valores previstos, entao nao da pra conferir se a recomendacao "
                "mudou. Nada foi aplicado. Refaca o apply_recommendation para gerar "
                "um token novo.",
                customer_id=p.customer_id,
            )
        linhas = await portas.run_report(
            manager_id=p.manager_id,
            session_id=p.session_id,
            customer_id=p.customer_id,
            query=recommendation_detail_query(rec_rn),
            row_formatter=parse_recommendation_detail_row,
            operation_name="apply_recommendation_precheck",
        )
        if not linhas:
            return portas.error_envelope(
                "apply_recommendation",
                f"A recomendacao {rec_rn} nao esta mais pendente na conta "
                f"{p.customer_id} (aplicada, dispensada ou expirada desde o "
                "preview). Nada foi aplicado. Use get_recommendations para ver o que "
                "resta.",
                customer_id=p.customer_id,
            )
        agora = recommendation_fingerprint(linhas[0])
        if agora != esperado:
            return portas.error_envelope(
                "apply_recommendation",
                "O Google revisou esta recomendacao desde o preview — o valor que voce "
                "confirmou nao e mais o que seria aplicado ("
                f"{descrever_divergencia(esperado, agora)}). Nada foi aplicado. Refaca "
                "o apply_recommendation para ver o valor atual e gerar um token novo.",
                customer_id=p.customer_id,
            )
        return None

    async def executar(self, p: Pendente, portas: Portas) -> dict[str, Any]:
        return await portas.run_recommendation_action(
            manager_id=p.manager_id,
            session_id=p.session_id,
            customer_id=p.customer_id,
            operation_type=p.operation_type,
            payload=p.payload,
        )

    async def pos_check(
        self, p: Pendente, portas: Portas, resultado: dict[str, Any]
    ) -> dict[str, Any]:
        return portas.applied_envelope(
            p.operation_type,
            p.customer_id,
            p.blast_summary,
            applied_count=resultado["applied_count"],
            provider_request_id=resultado["provider_request_id"],
        )


# --- upload_customer_match_list -----------------------------------------------------


class _CustomerMatch(_SemPreCheck):
    """Sprint 3b.28: OfflineUserDataJobService."""

    async def executar(self, p: Pendente, portas: Portas) -> dict[str, Any]:
        return await portas.run_customer_match(
            manager_id=p.manager_id,
            session_id=p.session_id,
            customer_id=p.customer_id,
            user_list_id=p.payload["user_list_id"],
            operation_type=p.payload["operation"],
            hashed_members=p.payload["hashed_members"],
        )

    async def pos_check(
        self, p: Pendente, portas: Portas, resultado: dict[str, Any]
    ) -> dict[str, Any]:
        job_id = resultado["job_resource_name"].rsplit("/", 1)[-1]
        # `submitted`, nao `applied`: o job roda no backend do Google por horas.
        return portas.submitted_envelope(
            "upload_customer_match_list",
            p.customer_id,
            p.blast_summary,
            user_list_id=p.payload["user_list_id"],
            operation_type=p.payload["operation"],
            # R1-I3: `members_submitted` e o que o Google ACEITOU. O que ele
            # recusou (hash mal formado, identificador nao suportado) aparece
            # ao lado, com o motivo por linha — antes o lote inteiro era
            # reportado como submetido.
            members_submitted=resultado["members_submitted"],
            members_failed=resultado["members_failed"],
            failures=resultado["failures"],
            # Item 3 (revisao final, spec §4.2): diz PORQUE os tres campos
            # acima podem vir `null` juntos — leitura de recusas nao confiavel,
            # nunca "ninguem foi recusado".
            recusas_medidas=resultado["recusas_medidas"],
            job_resource_name=resultado["job_resource_name"],
            provider_request_id_create_job=resultado["provider_request_id_create_job"],
            provider_request_id_add_ops=resultado["provider_request_id_add_ops"],
            provider_request_id_run_job=resultado["provider_request_id_run_job"],
            to_check_status=(
                f"Job é assíncrono no backend Google (processa em horas). "
                f"Pra verificar status, use run_gaql com query 'SELECT "
                f"offline_user_data_job.status, offline_user_data_job."
                f"failure_reason FROM offline_user_data_job WHERE "
                f"offline_user_data_job.id = {job_id}'."
            ),
        )


# --- update_ad_schedule -------------------------------------------------------------


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


def _pedidas(
    p: Pendente,
) -> tuple[list[str], dict[tuple[str, int, int, int, int], float | None]]:
    """Campanhas e janelas pedidas, com o bid_modifier efetivo de cada janela.

    Fix I2 (revisao final): `windows_bid_modifiers` e chave PARALELA a `windows`
    (mesma ordem, gravada pelo update_ad_schedule) — dict por chave de janela, nao
    lista, pra `_matches_requested` comparar direto."""
    campaign_ids = list(p.payload["campaign_ids"])
    pedidas_com_modificador = {
        window_from_input(w).key(): m
        for w, m in zip(p.payload["windows"], p.payload["windows_bid_modifiers"], strict=True)
    }
    return campaign_ids, pedidas_com_modificador


class _AdSchedule:
    """ad_schedule §4.6: confirmacao de estado por GAQL. A UI falhou em silencio duas
    vezes nessa conta; confiar no ACK da mutacao repetiria o problema num canal novo.

    Ruling 3 (ledger): as chaves do payload sao obrigatorias (a tool sempre grava);
    `.get(..., <default>)` seria o fallback calado que a Task 4 proibiu."""

    async def pre_check(self, p: Pendente, portas: Portas) -> dict[str, Any] | None:
        # Payload ruim (chave ausente, listas de tamanho diferente) tem que levantar
        # AQUI, antes da escrita — derivar so no `pos_check` faria a excecao nascer
        # com a mutacao ja aplicada (F83/F91).
        campaign_ids, _ = _pedidas(p)
        # Ruling 10 — concorrencia otimista. O que viaja no token e um DELTA calculado
        # ate 10 min antes, carregando resource_names observados naquele instante. Se a
        # grade mudou nesse meio tempo, aplicar o delta produz uma grade que nao e nem a
        # antiga nem a pedida — em silencio, porque partial_failure engole o erro por-op.
        # Este read e ANTES da escrita: se ele falhar, propagar e o lado seguro (nada
        # mutou ainda) — o tratamento best-effort do F83/F91 vale so depois da mutacao.
        rows_antes = await portas.run_report(
            manager_id=p.manager_id,
            session_id=p.session_id,
            customer_id=p.customer_id,
            query=ad_schedule_query(campaign_ids=campaign_ids, status="enabled", limit=GRADE_LIMIT),
            row_formatter=parse_ad_schedule_row,
            operation_name="update_ad_schedule_precheck",
        )
        # Grade truncada aqui nao precisa de ramo proprio: o dry-run RECUSA acima de
        # GRADE_LIMIT, entao um fingerprint de 1001 linhas nunca bate com o guardado —
        # cai na divergencia abaixo, que e o lado seguro.
        if (
            schedule_fingerprint(rows_to_current(rows_antes), campaign_ids)
            != p.payload["current_keys"]
        ):
            return portas.error_envelope(
                "update_ad_schedule",
                "A grade mudou desde o preview (alguem alterou a agenda destas campanhas "
                "nos ultimos minutos). Nenhuma operacao foi aplicada. Refaca o "
                "update_ad_schedule para gerar um token novo sobre o estado atual.",
                customer_id=p.customer_id,
            )
        return None

    async def executar(self, p: Pendente, portas: Portas) -> dict[str, Any]:
        return await portas.run_mutation(
            manager_id=p.manager_id,
            session_id=p.session_id,
            customer_id=p.customer_id,
            operation_type=p.operation_type,
            payload=p.payload,
            target_count=p.target_count,
            partial_failure=True,
            params_summary=p.params_summary,
        )

    async def pos_check(
        self, p: Pendente, portas: Portas, resultado: dict[str, Any]
    ) -> dict[str, Any]:
        # Nao levanta aqui: o `pre_check` ja derivou os dois do mesmo payload antes da
        # escrita, e payload ruim parou la.
        campaign_ids, pedidas_com_modificador = _pedidas(p)
        # F83/F91: a mutacao ja aplicou (resultado acima e definitivo). A reconsulta e
        # I/O DEPOIS da escrita — se ela falhar (rede, GoogleAdsException transiente,
        # rate limit), isso nao pode transformar um sucesso em erro pro caller.
        resulting: dict[str, Any] | None
        confirmation_error: str | None = None
        try:
            # status="all" de proposito (spec §7): janela removida tem que ser
            # confirmada por PRESENCA de status REMOVED. Filtrar ENABLED confirmaria
            # a remocao por a linha NAO aparecer — exatamente o que a §7 proibe, e o
            # que a propria §7 estende "para a confirmacao que a tool faz pos-apply".
            rows = await portas.run_report(
                manager_id=p.manager_id,
                session_id=p.session_id,
                customer_id=p.customer_id,
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
            # A1 (revisao final): o CORTE vem antes de qualquer derivacao. A linha
            # sentinela — a `GRADE_LIMIT + 1`-esima, cuja unica funcao e provar que
            # havia mais — nao pode entrar no resumo nem no `matches_requested`. A
            # gemea (`get_ad_schedule`) sempre cortou primeiro; a ordem aqui e a mesma.
            rows, leitura_parcial = aplicar_limite(rows, GRADE_LIMIT)
            # O resumo (has_schedule/hours_per_week) conta so o que esta SERVINDO;
            # com status="all" nas linhas, somar REMOVED inflaria as horas.
            servindo = rows_to_current([r for r in rows if r["status"] == "ENABLED"])
            # A2 (revisao final, residuo do F147): "incerta" nao e so a campanha
            # AUSENTE do corte — e tambem a da BORDA, dona da ultima linha lida,
            # cuja grade pode ter sido cortada no meio. Mesma funcao que o gemeo
            # `get_ad_schedule` chama; duas copias da regra e como o F128 nasceu.
            #
            # status="enabled" aqui, NAO o "all" literal da query acima (Task 8,
            # 2026-09-21): a terceira familia de `campanhas_com_grade_incerta`
            # existe pra vazio-por-FILTRO — quando o status pedido e um SUBCONJUNTO
            # que pode esconder janelas ENABLED que existem mas nao vieram (paused/
            # removed/all). Aqui `status="all"` e uma SUPERCONJUNTO deliberado (§7:
            # confirmar REMOVED por presenca), e `servindo`, duas linhas acima, ja
            # derivou o subconjunto ENABLED dele por filtro client-side ANTES desta
            # chamada — a leitura que embasa o resumo e literalmente a enabled, so
            # que lida via uma query mais larga. Declarar "all" aqui marcaria toda
            # confirmacao pos-apply como incerta, inclusive as que leram a grade
            # inteira sem corte nenhum — reintroduziria o F128 pela porta dos fundos.
            incertas = campanhas_com_grade_incerta(
                rows, truncated=leitura_parcial, campanhas=campaign_ids, status="enabled"
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
            portas.log.warning(
                "update_ad_schedule_confirm_failed",
                customer_id=p.customer_id,
                error=str(e),
                error_type=e.__class__.__name__,
            )
            resulting = None
            confirmation_error = (
                f"A mutacao foi aplicada (veja applied_count/provider_request_id), mas a "
                f"reconsulta da grade falhou ({e.__class__.__name__}). Confirme o estado "
                f"com get_ad_schedule antes de confiar no resultado."
            )
        return portas.applied_envelope(
            p.operation_type,
            p.customer_id,
            p.blast_summary,
            applied_count=resultado["applied_count"],
            provider_request_id=resultado["provider_request_id"],
            changed_count=resultado.get("changed_count"),
            # Spec §4.5: "a resposta separa aplicadas de falhas, com o motivo de cada
            # falha". Lote com partial_failure=True e onde isso acontece.
            #
            # F182: este ramo SEMPRE roda com a flag ligada (ver o `partial_failure=True`
            # em `executar`), e declara isso em vez de deixar o caller adivinhar. Sem os
            # dois campos aqui, o contrato ficaria uniforme "exceto neste ramo", que e
            # uma inconsistencia nova no lugar da antiga.
            partial_failure=True,
            failed_count=sum(
                1 for r in resultado.get("partial_failures", []) if r["status"] == "failed"
            ),
            partial_failures=resultado.get("partial_failures", []),
            resource_names=resultado.get("resource_names", []),
            resulting_schedule=resulting,
            confirmation_error=confirmation_error,
            # Item 3 (revisao final, spec §4.2): este ramo sempre roda com
            # partial_failure=True — bool medido, nao None.
            motivos_medidos=resultado.get("motivos_medidos"),
        )


# --- padrao: GoogleAdsService.mutate (Sprint 3b.1-3b.25) ----------------------------


class _Padrao(_SemPreCheck):
    """Mutacao encadeada via GoogleAdsService.mutate."""

    async def executar(self, p: Pendente, portas: Portas) -> dict[str, Any]:
        return await portas.run_mutation(
            manager_id=p.manager_id,
            session_id=p.session_id,
            customer_id=p.customer_id,
            operation_type=p.operation_type,
            payload=p.payload,
            target_count=p.target_count,
            partial_failure=_partial_failure(p),
            params_summary=p.params_summary,
        )

    async def pos_check(
        self, p: Pendente, portas: Portas, resultado: dict[str, Any]
    ) -> dict[str, Any]:
        partial_failure = _partial_failure(p)
        # R1-I1: cinco tools chegam aqui com `__partial_failure__` ligado —
        # `add_keywords`, `apply_audience`, `bulk_pause_by_query`,
        # `remove_asset_link` e `remove_audience` (a sexta, `update_ad_schedule`,
        # tem confirmador proprio). Quando o Google aceita parte, o motivo de cada
        # recusa vinha no `resultado` e morria aqui: o gestor lia "applied" com
        # `applied_count` menor que o pedido e nenhum porque.
        partial_failures = resultado.get("partial_failures", [])
        return portas.applied_envelope(
            p.operation_type,
            p.customer_id,
            p.blast_summary,
            applied_count=resultado["applied_count"],
            provider_request_id=resultado["provider_request_id"],
            # F139: quantos de fato mudaram. `applied_count` conta o tentado, entao
            # numa re-remocao ele diz 1 para uma operacao que nao mudou nada.
            changed_count=resultado.get("changed_count"),
            # F182: o REGIME vem na resposta. A flag e decisao interna da tool de
            # origem (`__partial_failure__` no payload), invisivel de fora; a propria
            # resposta diz sob qual regime rodou.
            partial_failure=partial_failure,
            partial_failures=partial_failures,
            # F182: com a flag DESLIGADA o Google nao reporta nada por linha, a lista
            # vem vazia, e derivar 0 dela afirma "nenhuma falhou" onde o correto e "nao
            # perguntei". `None` diz "nao medido" — mesma familia do `efeito: null` do
            # F184: nao saber e diferente de saber que e zero.
            failed_count=(
                sum(1 for r in partial_failures if r["status"] == "failed")
                if partial_failure
                else None
            ),
            resource_names=resultado.get("resource_names", []),
            # Item 3 (revisao final, spec §4.2): mesma familia do `failed_count`
            # acima — `None` quando `partial_failure=False` (run_mutation nao
            # tentou ler motivo nenhum, "nao perguntei"), bool medido quando True.
            motivos_medidos=resultado.get("motivos_medidos"),
        )


def _partial_failure(p: Pendente) -> bool:
    return bool(p.payload.get("__partial_failure__", False))


CONFIRMADORES: dict[str, Confirmador] = {
    "import_offline_conversions": _ConversoesOffline(),
    "apply_recommendation": _Recomendacao(),
    "upload_customer_match_list": _CustomerMatch(),
    "update_ad_schedule": _AdSchedule(),
}

# O padrao nao tem chave: e o que cobre todo `operation_type` fora do registro.
CONFIRMADOR_PADRAO: Confirmador = _Padrao()


def confirmador_para(operation_type: str) -> Confirmador:
    return CONFIRMADORES.get(operation_type, CONFIRMADOR_PADRAO)
