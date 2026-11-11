"""Varredura do `change_event` do Google (corpo do `get_change_history`).

Moveu de `src/mcp/tools/get_change_history.py` (Task G3): o dominio nao depende da
camada MCP, entao `today`, `manager_id` e `session_id` entram de fora. Nenhum
relogio do servidor aqui (F141).
"""

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from src.google_ads.change_freshness import assess_freshness
from src.google_ads.drift_detection import AUTO_APPLY_CLIENT_TYPES
from src.google_ads.limite import aplicar_limite
from src.google_ads.queries._common import (
    EntradaInvalidaError,
    nome_do_enum,
    parse_resource_path,
    resolve_date_window,
)
from src.google_ads.queries.change_history import (
    change_event_frontier_query,
    change_history_query,
)
from src.google_ads.reports import run_report

# F23 fix Sprint 3b.38: Google's change_event retention is 30 days exclusive
# (start_date must be > today-30). Our LAST_30_DAYS preset resolves to
# yesterday-29 = today-30 = boundary case Google rejects with
# "The requested start date is too old."
#
# Mitigation: clamp resolved start_date to max(start, today-28) — 2-day
# safety margin against UTC drift + add warning to response payload.
# Non-breaking: existing callers receive valid data + new field they can ignore.
_RETENTION_SAFETY_DAYS = 28

# Cap DURO do recurso `change_event`, medido em 2026-09-07 via `validate_gaql`
# na 786-223-0676: `LIMIT 10001` volta "Change event requests must specify a
# LIMIT less than or equal to 10k" e `LIMIT 10000` passa. E DESTE recurso, nao
# da GAQL — `FROM campaign|search_term_view|geographic_view|keyword_view|
# ad_group_audience_view ... LIMIT 10001` foi validado OK na mesma sonda, entao
# os outros builders desta frente nao tem nada a ajustar.
CAP_CHANGE_EVENT = 10_000

# Teto de eventos POR sub-janela. E o cap DURO do recurso `change_event`, nao
# uma escolha nossa: `LIMIT` e obrigatorio e acima de 10k a API recusa com
# "Change event requests must specify a LIMIT in query and LIMIT should be less
# than or equal to 10k" (sondado 2026-09-07 via `validate_gaql` na
# 786-223-0676). IMPORTADO de `get_change_history` em vez de recopiado: o mesmo
# numero escrito em dois lugares foi o vetor do F142, e aqui a divergencia
# seria pior — a copia menor voltaria a esconder evento em silencio.
#
# Ate a Task 5 este teto era `500` escrito no meio da chamada. Vinte vezes
# menor que o que a API aceita, sem aparecer em lugar nenhum da resposta.
TETO_POR_JANELA = CAP_CHANGE_EVENT

# Teto TOTAL de eventos examinados numa chamada, somando todas as sub-janelas.
# Duas janelas cheias: o bastante para a particao valer alguma coisa, pouco o
# bastante para a resposta caber em memoria e nao torrar a quota da conta numa
# tool que roda em D+1 de todo batch. Passando daqui, a resposta honesta e
# "estreite a janela" — e e o que `cobertura.varredura_truncada` diz.
TETO_EXAMINADO = 2 * TETO_POR_JANELA


def _row_formatter(row: Any) -> dict[str, Any]:
    ce = row.change_event
    resource_path = str(ce.change_resource_name)
    _rtype, rid = parse_resource_path(resource_path)
    # changed_fields is a FieldMask (paths joined by '.'); split into list
    changed = list(ce.changed_fields.paths) if hasattr(ce.changed_fields, "paths") else []

    # campaign / ad_group references on change_event are resource paths; convert
    campaign_path = str(ce.campaign) if ce.campaign else ""
    ad_group_path = str(ce.ad_group) if ce.ad_group else ""
    _, campaign_id = parse_resource_path(campaign_path) if campaign_path else (None, None)
    _, ad_group_id = parse_resource_path(ad_group_path) if ad_group_path else (None, None)

    op_enum = ce.resource_change_operation
    op_str = nome_do_enum(op_enum)
    rtype_enum = ce.change_resource_type
    rtype_str = nome_do_enum(rtype_enum)
    ct_enum = ce.client_type
    ct_str = nome_do_enum(ct_enum)
    old_status, new_status = _status_transition(ce, rtype_str)

    return {
        "change_date_time": str(ce.change_date_time),
        "user_email": str(ce.user_email),
        "client_type": ct_str,
        "resource_type": rtype_str,
        "resource_id": rid or "",
        "resource_name": "",  # filled in by _resolve_names after the fact
        "_resource_path": resource_path,  # internal, removed before returning
        "operation": op_str,
        "changed_fields": changed,
        "campaign_id": campaign_id,
        "ad_group_id": ad_group_id,
        # F145: remover campanha/grupo no Google e UPDATE de status -> REMOVED. A
        # transicao sai na resposta e alimenta as flags do detect_drift.
        "old_status": old_status,
        "new_status": new_status,
    }


# Tipos cujo `status` e mudanca estrutural. Keyed pelo resource_type de proposito:
# em proto-plus `new_resource.campaign` EXISTE (vazio, UNSPECIFIED) mesmo numa
# linha de keyword — olhar pela presenca do atributo inventaria status.
_STATUS_ATTR_BY_TYPE = {"CAMPAIGN": "campaign", "AD_GROUP": "ad_group"}


def _status_transition(ce: Any, rtype: str) -> tuple[str | None, str | None]:
    attr = _STATUS_ATTR_BY_TYPE.get(rtype)
    if attr is None:
        return None, None

    def _status(res: Any) -> str | None:
        sub = getattr(res, attr, None)
        st = getattr(sub, "status", None) if sub is not None else None
        name = getattr(st, "name", None)
        return None if not name or name == "UNSPECIFIED" else str(name)

    return _status(getattr(ce, "old_resource", None)), _status(getattr(ce, "new_resource", None))


def _parse_change_dt(raw: str) -> datetime | None:
    """Converte o `change_date_time` do Google em datetime, tolerando o formato.

    O Google devolve "YYYY-MM-DD HH:MM:SS.ffffff", mas os microssegundos nem
    sempre vem. Formato desconhecido devolve None — e a fronteira vira
    "indeterminado", que e a resposta honesta, em vez de frescor inventado.
    """
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate counts. Auto-apply rows collapse into synthetic 'auto-apply' user bucket."""
    by_user: Counter[str] = Counter()
    by_resource_type: Counter[str] = Counter()
    by_operation: Counter[str] = Counter()
    auto_applied = 0
    for r in rows:
        if r["client_type"] in AUTO_APPLY_CLIENT_TYPES:
            by_user["auto-apply"] += 1
            auto_applied += 1
        else:
            by_user[r["user_email"]] += 1
        by_resource_type[r["resource_type"]] += 1
        by_operation[r["operation"]] += 1

    return {
        "total_changes": len(rows),
        "by_user": dict(by_user),
        "by_resource_type": dict(by_resource_type),
        "by_operation": dict(by_operation),
        "auto_applied_count": auto_applied,
    }


async def _resolve_names(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], str]:
    """Resolve (resource_type, resource_id) -> human name via 0-2 follow-up queries."""
    name_map: dict[tuple[str, str], str] = {}

    campaign_ids = sorted({r["campaign_id"] for r in rows if r["campaign_id"]})
    ad_group_ids = sorted({r["ad_group_id"] for r in rows if r["ad_group_id"]})

    if campaign_ids:
        ids_clause = ",".join(str(int(c)) for c in campaign_ids)
        q = f"SELECT campaign.id, campaign.name FROM campaign WHERE campaign.id IN ({ids_clause})"
        rows_c = await run_report(
            manager_id=manager_id,
            session_id=session_id,
            customer_id=customer_id,
            query=q,
            row_formatter=lambda r: {"id": str(r.campaign.id), "name": str(r.campaign.name)},
            operation_name="get_change_history_resolve_campaigns",
            audit_this_call=False,
        )
        for c in rows_c:
            name_map[("campaign", c["id"])] = c["name"]

    if ad_group_ids:
        ids_clause = ",".join(str(int(a)) for a in ad_group_ids)
        q = f"SELECT ad_group.id, ad_group.name FROM ad_group WHERE ad_group.id IN ({ids_clause})"
        rows_a = await run_report(
            manager_id=manager_id,
            session_id=session_id,
            customer_id=customer_id,
            query=q,
            row_formatter=lambda r: {"id": str(r.ad_group.id), "name": str(r.ad_group.name)},
            operation_name="get_change_history_resolve_ad_groups",
            audit_this_call=False,
        )
        for a in rows_a:
            name_map[("ad_group", a["id"])] = a["name"]

    return name_map


async def consultar_change_history(
    args: dict[str, Any],
    *,
    today: date,
    manager_id: UUID,
    session_id: UUID,
) -> dict[str, Any]:
    """O corpo do `get_change_history`, com o `hoje` da conta INJETADO.

    Existe separado do handler registrado por um motivo so: quem ja resolveu
    `today` nesta request (hoje, `detect_drift`) precisa passar o MESMO valor
    adiante, e `register_tool` devolve o handler tipado como `ToolHandler`
    (`(dict) -> Awaitable[Any]`), que nao carrega kwarg nenhum.
    """
    customer_id = args["customer_id"]

    start, end = resolve_date_window(
        date_range=args.get("date_range", "LAST_7_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        today=today,
    )

    # F23 fix Sprint 3b.38 (estendido): clampamos start_date — preset OU custom — pro
    # teto de retenção do change_event (30 dias exclusivos), em vez de deixar o Google
    # rejeitar com "start date too old". Devolve dados + warning. Se a janela inteira
    # está fora da retenção (end < limite), não há o que retornar → erro claro.
    earliest_allowed = today - timedelta(days=_RETENTION_SAFETY_DAYS)
    retention_warning: str | None = None
    if end < earliest_allowed:
        raise EntradaInvalidaError(
            f"A janela pedida ({start.isoformat()}..{end.isoformat()}) está inteira fora "
            f"da retenção de 30 dias do change_event do Google (dados só a partir de "
            f"{earliest_allowed.isoformat()}). Peça uma janela dentro dos últimos 30 dias."
        )
    if start < earliest_allowed:
        original_start = start
        start = earliest_allowed
        retention_warning = (
            f"date_range coerced from {original_start.isoformat()} to "
            f"{start.isoformat()} (F23: change_event do Google retém 30 dias exclusivos "
            "— clamp pra today-28 evita rejeição na borda; vale pra preset E custom)."
        )

    limit = args.get("limit", 200)
    # O builder soma a sentinela (`LIMIT {limit + 1}`), e no teto do schema
    # isso pediria `LIMIT 10001` — que o change_event RECUSA. Pedir
    # `min(limit + 1, CAP)` e o idioma padrao de `fetch n+1` com teto de API:
    # preserva o `maximum` publico e paga o preco so na borda.
    limit_pedido = min(limit, CAP_CHANGE_EVENT - 1)

    query = change_history_query(
        start=start,
        end=end,
        resource_types=args.get("resource_types"),
        operation_types=args.get("operation_types"),
        user_emails=args.get("user_emails"),
        client_types=args.get("client_types"),
        limit=limit_pedido,
    )

    # F131: a sonda de fronteira vai EM PARALELO com a query principal — mesmo
    # padrao que o audit_competitor_keywords ja usa. Custa +1 chamada de quota
    # e ~0 de latencia, e e o que separa "nada mudou" de "ainda nao indexou".
    rows, frontier_rows = await asyncio.gather(
        run_report(
            manager_id=manager_id,
            session_id=session_id,
            customer_id=customer_id,
            query=query,
            row_formatter=_row_formatter,
            operation_name="get_change_history",
            audit_this_call=True,
        ),
        run_report(
            manager_id=manager_id,
            session_id=session_id,
            customer_id=customer_id,
            # A sonda deriva a propria janela (retencao inteira). Passar `start`/`end`
            # aqui era o bug: a fronteira da CONTA virava fronteira do PEDIDO.
            query=change_event_frontier_query(today=today),
            row_formatter=lambda r: {"change_date_time": str(r.change_event.change_date_time)},
            operation_name="get_change_history_frontier",
            # Query de apoio, como o _resolve_names: nao polui a trilha do gestor.
            audit_this_call=False,
        ),
    )

    # A UNICA borda em que a sentinela nao existe: com `limit == CAP` a
    # consulta pediu exatamente `CAP`, entao `len(linhas) > limit` e falso por
    # construcao e o detector morreria calado justamente onde o corte e mais
    # provavel. Ler `len == CAP` como corte degrada na direcao segura — num
    # universo de exatamente 10000 mudancas avisa um corte que nao houve, o
    # que e estritamente melhor que esconder um que houve.
    atingiu_o_cap = len(rows) == CAP_CHANGE_EVENT

    # ANTES do resolve e do summary: a consulta pediu `limit + 1`, e a linha
    # sentinela nao pode entrar em nenhum dos dois. Se o corte viesse depois da
    # agregacao, `summary.total_changes` nao bateria com `rows` — dois numeros
    # para a mesma pergunta.
    rows, truncado = aplicar_limite(rows, limit)
    truncado = truncado or atingiu_o_cap

    # Resolve campaign/ad_group names (0-2 extra ops)
    name_map = await _resolve_names(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        rows=rows,
    )
    # name_map only contains ('campaign', id) and ('ad_group', id) keys —
    # for other resource types (ASSET, CUSTOMER_ASSET, FEED, ASSET_SET, etc),
    # the raw resource path is used as resource_name per spec §4.5.
    for r in rows:
        resource_path = r.pop("_resource_path")
        key = (r["resource_type"].lower(), r["resource_id"])
        if key in name_map:
            r["resource_name"] = name_map[key]
        elif r["campaign_id"]:
            r["resource_name"] = name_map.get(("campaign", r["campaign_id"]), resource_path)
        else:
            r["resource_name"] = resource_path

    summary = _build_summary(rows)

    account_frontier = (
        _parse_change_dt(frontier_rows[0]["change_date_time"]) if frontier_rows else None
    )
    slice_dts = [
        dt for dt in (_parse_change_dt(r["change_date_time"]) for r in rows) if dt is not None
    ]

    response: dict[str, Any] = {
        "customer_id": customer_id,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "rows": rows,
        # Ortogonal ao `freshness`: `truncated` diz que HAVIA mais dentro da
        # janela e o `limit` cortou; `freshness` diz se o que existe ja foi
        # indexado. Ler um pelo outro inverte a conclusao — `truncated: true`
        # com `status: confiavel` e "peca mais", nao "espere".
        "truncated": truncado,
        "summary": summary,
        # F131: sem isto, `total_changes: 0` e a mesma resposta para "nada
        # mudou" e para "mudou e ainda nao indexou".
        "freshness": assess_freshness(
            account_frontier=account_frontier,
            slice_frontier=max(slice_dts) if slice_dts else None,
            window_end=end,
            today=today,
        ),
    }
    if retention_warning is not None:
        response["date_range_warning"] = retention_warning
    return response


def _dias_desc(inicio: date, fim: date) -> list[date]:
    """Os dias da janela, do mais RECENTE para o mais antigo.

    A ordem e contrato, nao estilo: quando o teto total corta, o que fica de
    fora tem que ser o PASSADO — a mesma direcao em que `get_change_history`
    corta ("as mais recentes ficam"). Varrer do antigo para o novo faria o teto
    esconder justamente a mudanca que acabou de acontecer, que e a que esta
    tool existe para achar.
    """
    return [fim - timedelta(days=i) for i in range((fim - inicio).days + 1)]


@dataclass(frozen=True, slots=True)
class Varredura:
    """O que a varredura leu — e, sobretudo, o que ela NAO leu."""

    linhas: list[dict[str, Any]]
    janelas: int
    # Dias que sozinhos bateram no cap do change_event: ali a particao chegou
    # ao fim da granularidade disponivel (a tool so alcanca o DIA).
    dias_no_cap: list[str]
    teto_total_atingido: bool
    # A janela DE FATO varrida, que e o que `cobertura.janela_efetiva` promete
    # — nao a pedida (essa fica em `period`). Duas coisas a encurtam: o clamp de
    # retencao do F23 na ponta antiga, e o teto total parando a particao antes
    # de chegar la. A segunda faltava (A3 da revisao final): a janela inteira
    # continuava anunciada com a varredura parada no segundo de 21 dias.
    janela: tuple[date, date]
    freshness: dict[str, Any]
    # O aviso de clamp de retencao (F23) que `get_change_history` emite quando
    # move o inicio da janela. `cobertura.janela_efetiva` ja mostra QUE a janela
    # mudou; sem este texto o gestor ve as duas datas diferentes e nao sabe por
    # que. Numa frente sobre honestidade dos numeros, descartar a explicacao do
    # numero e o mesmo defeito, um nivel acima.
    aviso_de_janela: str | None = None

    @property
    def truncada(self) -> bool:
        """Existe evento na janela que esta varredura NUNCA examinou.

        As duas causas contam igual para quem le o veredito: o teto total
        parou a varredura, OU um dia estourou o cap da API. Nos dois casos
        "zero drift" deixa de ser veredito e vira amostra.
        """
        return self.teto_total_atingido or bool(self.dias_no_cap)


async def _ler(
    customer_id: str,
    *,
    inicio: date,
    fim: date,
    teto: int,
    hoje: date,
    manager_id: UUID,
    session_id: UUID,
) -> dict[str, Any]:
    """Uma leitura de `get_change_history` (audit_this_call=True herdado).

    `hoje` vem de fora, resolvido UMA vez por request no fuso da conta: uma
    varredura particionada faz ate 30 destas, e deixar cada uma resolver o
    proprio relogio custaria uma leitura de banco por sub-janela e — pior —
    poderia trocar de `hoje` no meio de um request que atravessasse a
    meia-noite da conta. `account_clock.py` escreve essa regra na propria
    docstring: "Um `hoje` por request; nunca dois relogios na mesma resposta".
    """
    return await consultar_change_history(
        {
            "customer_id": customer_id,
            "start_date": inicio.isoformat(),
            "end_date": fim.isoformat(),
            "limit": teto,
        },
        today=hoje,
        manager_id=manager_id,
        session_id=session_id,
    )


async def varrer(
    customer_id: str,
    *,
    inicio: date,
    fim: date,
    hoje: date,
    manager_id: UUID,
    session_id: UUID,
) -> Varredura:
    """Le a janela inteira; se ela nao couber no cap do `change_event`, re-le dia a dia.

    Padrao: **particionamento de janela temporal** (range splitting), que e a
    resposta consolidada para API com teto por consulta e sem cursor. Sondado
    em 2026-09-07 (`validate_gaql`, conta 786-223-0676): o `change_event` EXIGE
    `LIMIT`, recusa acima de 10k e NAO oferece OFFSET nem cursor — a unica
    dimensao por onde passar do cap e o tempo. Como `get_change_history` recebe
    data em granularidade de DIA, a sub-janela mais fina alcancavel por este
    caminho e um dia; dia que estoura sozinho sai declarado em `dias_no_cap`,
    porque limite de API declarado nao e mentira, teto escondido e.

    **Adaptativo de proposito.** A janela inteira e lida PRIMEIRO e a particao
    so acontece quando ela nao coube. O caso comum (na 786-223-0676 a janela
    tipica tem ~141 eventos) segue custando UMA leitura, e o `freshness` da
    resposta continua sendo o da janela inteira, medido contra o `window_end`
    que o gestor pediu — exatamente como antes desta task. O preco e reler no
    caminho raro: as linhas da primeira leitura sao descartadas quando a
    particao entra. E o lado certo para errar, porque particionar sempre
    multiplicaria por ate 30 a quota de toda chamada de uma tool que roda em
    D+1 de todo batch.
    """
    primeira = await _ler(
        customer_id,
        inicio=inicio,
        fim=fim,
        teto=TETO_POR_JANELA,
        hoje=hoje,
        manager_id=manager_id,
        session_id=session_id,
    )

    # A janela EFETIVA e a que a leitura devolveu, nao a que pedimos: o clamp
    # de retencao (F23) pode ter movido o inicio, e varrer dia a dia a partir
    # do PEDIDO levantaria `ValueError` nos dias fora da retencao de 30 dias.
    efetiva_de = date.fromisoformat(primeira["period"]["from"])
    efetiva_ate = date.fromisoformat(primeira["period"]["to"])
    dias = _dias_desc(efetiva_de, efetiva_ate)

    if not primeira["truncated"] or len(dias) == 1:
        # Coube — ou a janela ja e de UM dia e a particao nao tem para onde ir.
        # No segundo caso o corte e da API, e repetir a mesma consulta so
        # gastaria quota para trazer as mesmas linhas.
        return Varredura(
            linhas=list(primeira["rows"]),
            janelas=1,
            dias_no_cap=[efetiva_ate.isoformat()] if primeira["truncated"] else [],
            teto_total_atingido=False,
            janela=(efetiva_de, efetiva_ate),
            freshness=primeira["freshness"],
            aviso_de_janela=primeira.get("date_range_warning"),
        )

    linhas: list[dict[str, Any]] = []
    dias_no_cap: list[str] = []
    janelas = 0
    teto_total_atingido = False
    # A3 (revisao final): o dia mais ANTIGO que a varredura chegou a consultar.
    # `dias` vem do mais recente para o mais antigo, entao ele so anda para tras
    # — e quando o teto total interrompe o laco, e ele que fecha a janela de
    # fato varrida. Ate aqui `janela_efetiva` anunciava a janela inteira mesmo
    # com a varredura parada no segundo dia de 21: o campo que o gestor le para
    # saber QUANTO ficou de fora afirmava justamente o que nao foi lido, e os
    # dias nao varridos nao apareciam em campo nenhum (`dias_no_teto_da_api`
    # nomeia so os que FORAM lidos e estouraram).
    mais_antigo_lido = efetiva_ate
    for dia in dias:
        if len(linhas) >= TETO_EXAMINADO:
            # Sobrou dia que nem chegou a ser consultado — e o teto total, nao
            # o da API, que parou a varredura.
            teto_total_atingido = True
            break
        parcial = await _ler(
            customer_id,
            inicio=dia,
            fim=dia,
            teto=TETO_POR_JANELA,
            hoje=hoje,
            manager_id=manager_id,
            session_id=session_id,
        )
        janelas += 1
        mais_antigo_lido = dia
        # Costura das sub-janelas, dita em voz alta: o `BETWEEN` do Google e
        # inclusivo nas duas pontas e o builder soma +1 dia no fim (F46), entao
        # dois dias vizinhos se sobrepoem em UM instante — `d+1 00:00:00`
        # exato, ao microssegundo. Evento carimbado ali seria contado duas
        # vezes. NAO ha dedup aqui de proposito: a chave disponivel
        # (timestamp+recurso+operacao) nao distingue duas mudancas reais que
        # coincidam nos tres, e trocar "duplicar visivelmente" por "descartar
        # em silencio" e o oposto do que esta tool existe para fazer.
        linhas.extend(parcial["rows"])
        if parcial["truncated"]:
            dias_no_cap.append(dia.isoformat())

    # `aplicar_limite` pelo mesmo motivo de sempre: `len > teto` e a unica
    # forma de distinguir "coube exato" de "havia mais". O contrato do helper
    # (pedir `limite + 1`) e satisfeito aqui pela via da acumulacao — as
    # sub-janelas entram INTEIRAS, entao ultrapassar o teto e prova de excesso.
    linhas, estourou_o_teto = aplicar_limite(linhas, TETO_EXAMINADO)

    return Varredura(
        linhas=linhas,
        janelas=janelas,
        dias_no_cap=dias_no_cap,
        teto_total_atingido=teto_total_atingido or estourou_o_teto,
        # A janela DE FATO varrida, nao a pedida — a pedida continua em
        # `period`. Sem teto atingido `mais_antigo_lido == efetiva_de` e as
        # duas coincidem; com teto, a diferenca entre os dois campos e o que
        # ficou sem varrer.
        janela=(mais_antigo_lido, efetiva_ate),
        freshness=primeira["freshness"],
        aviso_de_janela=primeira.get("date_range_warning"),
    )
