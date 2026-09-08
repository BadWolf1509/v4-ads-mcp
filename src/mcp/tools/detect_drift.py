# bucket: always
"""Tool: detect_drift — auditar mudanças NÃO-autorizadas pós-batch V4.

Sprint 3b.33 — W1 do dogfood 2026-05-21 MO-JP+CAB (ICE 486).
Wrapper sobre get_change_history + pure aggregator com 3 flags acionáveis.
Use case primário: co-management (lição 46 dogfood).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from src.google_ads.account_clock import resolve_account_today
from src.google_ads.drift_detection import detect_drift as _detect_drift_pure
from src.google_ads.drift_detection import dict_to_change_event_row
from src.google_ads.queries._common import resolve_date_window
from src.mcp.context import get_current
from src.mcp.tools._common import aplicar_limite
from src.mcp.tools._registry import register_tool
from src.mcp.tools.get_change_history import _CAP_CHANGE_EVENT, get_change_history

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
_TETO_POR_JANELA = _CAP_CHANGE_EVENT

# Teto TOTAL de eventos examinados numa chamada, somando todas as sub-janelas.
# Duas janelas cheias: o bastante para a particao valer alguma coisa, pouco o
# bastante para a resposta caber em memoria e nao torrar a quota da conta numa
# tool que roda em D+1 de todo batch. Passando daqui, a resposta honesta e
# "estreite a janela" — e e o que `cobertura.varredura_truncada` diz.
_TETO_EXAMINADO = 2 * _TETO_POR_JANELA

_DATE_PRESETS = [
    "LAST_2_DAYS",  # NEW — sane default for D+1/D+2 post-batch audit
    "TODAY",
    "YESTERDAY",
    "LAST_7_DAYS",
    "LAST_14_DAYS",
    "LAST_30_DAYS",
]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "responsible_user_emails": {
            "type": "array",
            "items": {"type": "string", "format": "email"},
            "maxItems": 20,
            "description": (
                "Emails AUTORIZADOS pra mexer na conta (gestor responsável + "
                "co-gestores V4). Changes com user_email NESSA lista NÃO contam "
                "como drift. Lista vazia = incident mode (todos os changes "
                "contam como drift). Auto-apply "
                "(client_type=GOOGLE_ADS_RECOMMENDATIONS) sempre conta como "
                "drift (não tem user_email)."
            ),
        },
        "date_range": {
            "type": "string",
            "enum": _DATE_PRESETS,
            "default": "LAST_2_DAYS",
            "description": (
                "Periodo via preset. LAST_2_DAYS sane default pra D+1/D+2 "
                "pos-batch. Para periodo custom, use start_date+end_date."
            ),
        },
        "start_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": (
                "Data inicial YYYY-MM-DD inclusive. Quando informado junto com "
                "end_date, sobrepoe date_range preset. Obriga end_date."
            ),
        },
        "end_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Data final YYYY-MM-DD inclusive. Obrigatorio se start_date informado.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
            "default": 100,
            "description": (
                "Cap em changes[] na response. Summary + flags refletem o total "
                "bruto EXAMINADO — quanto foi examinado, e o que ficou de fora, "
                "sai em `cobertura`, nao aqui."
            ),
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _resolve_date_window_local(
    date_range: str | None,
    start_date: str | None,
    end_date: str | None,
    *,
    today: date,
) -> tuple[date, date]:
    """Resolve date window including LAST_2_DAYS preset (not in shared _PRESETS).

    Precedence: explicit start_date+end_date override date_range.
    LAST_2_DAYS = yesterday + day before yesterday (2-day window).
    Delegates all other presets to shared resolve_date_window helper.
    """
    # Explicit dates always win
    if start_date is not None or end_date is not None:
        return resolve_date_window(
            date_range=None,
            start_date=start_date,
            end_date=end_date,
            today=today,
        )

    # Handle LAST_2_DAYS locally (not in shared _PRESETS)
    preset = (date_range or "LAST_2_DAYS").upper()
    if preset == "LAST_2_DAYS":
        # F141: `today` e o da CONTA, vindo do chamador — nao o do servidor.
        yesterday = today - timedelta(days=1)
        day_before = today - timedelta(days=2)
        return day_before, yesterday

    # Delegate all other presets to shared helper
    return resolve_date_window(
        date_range=date_range,
        start_date=None,
        end_date=None,
        today=today,
    )


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
class _Varredura:
    """O que a varredura leu — e, sobretudo, o que ela NAO leu."""

    linhas: list[dict[str, Any]]
    janelas: int
    # Dias que sozinhos bateram no cap do change_event: ali a particao chegou
    # ao fim da granularidade disponivel (a tool so alcanca o DIA).
    dias_no_cap: list[str]
    teto_total_atingido: bool
    janela: tuple[date, date]
    freshness: dict[str, Any]

    @property
    def truncada(self) -> bool:
        """Existe evento na janela que esta varredura NUNCA examinou.

        As duas causas contam igual para quem le o veredito: o teto total
        parou a varredura, OU um dia estourou o cap da API. Nos dois casos
        "zero drift" deixa de ser veredito e vira amostra.
        """
        return self.teto_total_atingido or bool(self.dias_no_cap)


async def _ler(customer_id: str, *, inicio: date, fim: date, teto: int) -> dict[str, Any]:
    """Uma leitura de `get_change_history` (audit_this_call=True herdado).

    A anotacao no meio do caminho e necessaria: `register_tool` devolve o
    handler como `ToolHandler`, cujo retorno e `Awaitable[Any]`, entao sem ela
    o mypy strict acusa `no-any-return` aqui.
    """
    resposta: dict[str, Any] = await get_change_history(
        {
            "customer_id": customer_id,
            "start_date": inicio.isoformat(),
            "end_date": fim.isoformat(),
            "limit": teto,
        }
    )
    return resposta


async def _varrer(customer_id: str, *, inicio: date, fim: date) -> _Varredura:
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
    primeira = await _ler(customer_id, inicio=inicio, fim=fim, teto=_TETO_POR_JANELA)

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
        return _Varredura(
            linhas=list(primeira["rows"]),
            janelas=1,
            dias_no_cap=[efetiva_ate.isoformat()] if primeira["truncated"] else [],
            teto_total_atingido=False,
            janela=(efetiva_de, efetiva_ate),
            freshness=primeira["freshness"],
        )

    linhas: list[dict[str, Any]] = []
    dias_no_cap: list[str] = []
    janelas = 0
    teto_total_atingido = False
    for dia in dias:
        if len(linhas) >= _TETO_EXAMINADO:
            # Sobrou dia que nem chegou a ser consultado — e o teto total, nao
            # o da API, que parou a varredura.
            teto_total_atingido = True
            break
        parcial = await _ler(customer_id, inicio=dia, fim=dia, teto=_TETO_POR_JANELA)
        janelas += 1
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
    linhas, estourou_o_teto = aplicar_limite(linhas, _TETO_EXAMINADO)

    return _Varredura(
        linhas=linhas,
        janelas=janelas,
        dias_no_cap=dias_no_cap,
        teto_total_atingido=teto_total_atingido or estourou_o_teto,
        janela=(efetiva_de, efetiva_ate),
        freshness=primeira["freshness"],
    )


@register_tool(
    name="detect_drift",
    description=(
        "[CORE] Detecta mudanças NÃO-autorizadas em conta Google Ads (workflow "
        "co-management V4 pós-batch). Compara change_event com lista de "
        "responsible_user_emails: tudo NÃO-listado conta como drift. Auto-apply "
        "Recommendations sempre conta como drift. Output: summary (count + "
        "by_user/resource/operation) + freshness (fronteira de indexacao "
        "medida) + flags[] (auto_apply_detected, "
        "multiple_users_detected, structural_change, status_change_detected) + "
        "changes[] (até limit, "
        "default 100 max 500). ATENCAO: roda sobre change_event, que e audit "
        "log LAGGING com lag SEM contrato (medido de ~3h a >4 dias na mesma "
        "conta) — por isso a resposta traz `freshness.status`. ZERO DRIFT "
        "COM status != confiavel NAO significa conta intacta: pode ser "
        "mudanca de terceiro ainda nao indexada. Pra validar estado atual, "
        "use run_gaql FROM campaign como leading indicator. "
        "COBERTURA (F136/F145): remover campanha ou grupo no Google NAO e uma "
        "operacao REMOVE — e UPDATE de status para REMOVED; a flag "
        "structural_change (high) cobre as duas formas em CAMPAIGN e AD_GROUP, e "
        "cada change traz old_status/new_status. status_change_detected (medium) "
        "levanta em ENABLED<->PAUSED por nao-autorizado — reativar campanha alheia "
        "comeca gasto, pausar para entrega. NAO cobre conversion action — nem o change_event "
        "nem o change_status rastreiam esse recurso, entao remocao de conversion "
        "action (que quebra Smart Bidding) NAO aparece aqui e nao seria detectada "
        "por esta tool. Para o estado atual das conversion actions, use "
        "get_conversion_actions. "
        "COBERTURA DA VARREDURA: a tool le a janela inteira numa consulta e, se "
        "ela nao couber no cap de 10k do change_event, RE-LE dia a dia — o "
        "recurso nao tem OFFSET nem cursor (sondado 2026-09-07), entao a unica "
        "particao possivel e a do tempo, e a mais fina alcancavel aqui e UM DIA. "
        "O bloco `cobertura` diz o que a leitura de fato viu: "
        "`eventos_examinados` (quantos entraram na classificacao), "
        "`janelas_consultadas` (1 quando a janela coube; uma por dia quando "
        "nao), `janela_efetiva` (a janela realmente lida — o clamp de retencao "
        "pode te-la encurtado) e `dias_no_teto_da_api` (dias que sozinhos "
        "bateram nos 10k: ali a particao chegou ao fim da granularidade "
        "disponivel e o que ficou de fora e limite da API — estreite a janela "
        "ou filtre por resource_type). "
        "NAO confunda os dois truncados: `truncated` (topo) fala do SEU `limit` "
        "e diz que `changes[]` foi cortada, com a classificacao feita sobre "
        "tudo; `cobertura.varredura_truncada` fala da LEITURA e diz que existe "
        "evento na janela que NUNCA foi classificado — com ele true, 'zero "
        "drift' nao e veredito, e amostra. Sempre auditado."
    ),
    input_schema=_SCHEMA,
    bucket="always",
)
async def detect_drift(args: dict[str, Any]) -> dict[str, Any]:
    get_current()  # ensure context is bound (programmer-error guard)
    customer_id = args["customer_id"]
    responsible_user_emails = args.get("responsible_user_emails", [])
    limit = args.get("limit", 100)

    # Resolve date window LOCALLY (LAST_2_DAYS é preset detect_drift-only).
    # Passamos start_date+end_date explícitos pro get_change_history.
    today = await resolve_account_today(customer_id)
    start_date_obj, end_date_obj = _resolve_date_window_local(
        date_range=args.get("date_range", "LAST_2_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        today=today,
    )
    start_date = start_date_obj.isoformat()
    end_date = end_date_obj.isoformat()

    # Varredura da janela (audit_this_call=True herdado de get_change_history).
    # Passa start_date+end_date explícitos pra evitar acoplar LAST_2_DAYS ao
    # enum do schema de lá. O teto interno de 500 morreu aqui: quem decide
    # quanto se le e `_TETO_POR_JANELA`/`_TETO_EXAMINADO`, e o que ficou de
    # fora sai declarado em `cobertura`.
    varredura = await _varrer(customer_id, inicio=start_date_obj, fim=end_date_obj)

    # Boundary conversion: dict → dataclass
    rows = [dict_to_change_event_row(d) for d in varredura.linhas]

    # Pure aggregator
    drift_result = _detect_drift_pure(
        rows,
        responsible_user_emails=responsible_user_emails,
        limit=limit,
    )

    days = (end_date_obj - start_date_obj).days + 1

    return {
        "customer_id": customer_id,
        "period": {
            "from": start_date,
            "to": end_date,
            "days": days,
        },
        "responsible_user_emails": responsible_user_emails,
        "summary": {
            "total_drift_changes": drift_result.summary.total_drift_changes,
            "total_changes_in_window": drift_result.summary.total_changes_in_window,
            "by_user": drift_result.summary.by_user,
            "by_resource_type": drift_result.summary.by_resource_type,
            "by_operation": drift_result.summary.by_operation,
        },
        "flags": [
            {
                "code": f.code,
                "severity": f.severity,
                "message_pt": f.message_pt,
                "evidence": f.evidence,
            }
            for f in drift_result.flags
        ],
        "changes": [
            {
                "change_date_time": c.change_date_time,
                "user_email": c.user_email,
                "client_type": c.client_type,
                "resource_type": c.resource_type,
                "resource_id": c.resource_id,
                "resource_name": c.resource_name,
                "operation": c.operation,
                "changed_fields": list(c.changed_fields),
                "campaign_id": c.campaign_id,
                "ad_group_id": c.ad_group_id,
                "old_status": c.old_status,
                "new_status": c.new_status,
            }
            for c in drift_result.drift_changes
        ],
        # Cuidado: sao DOIS truncados, e falam de coisas diferentes. Este e o
        # do `limit` DO GESTOR sobre `changes[]` — a classificacao rodou sobre
        # tudo que foi lido, so a lista de saida foi cortada.
        "truncated": drift_result.truncated,
        # Task 5: o outro. Este fala da LEITURA — quanto da janela a varredura
        # chegou a examinar. Ate aqui a tool lia 500 eventos e nao dizia; numa
        # janela maior que isso o veredito saia calculado sobre uma amostra,
        # com a mesma cara de um veredito completo.
        "cobertura": {
            "eventos_examinados": len(varredura.linhas),
            "janelas_consultadas": varredura.janelas,
            "varredura_truncada": varredura.truncada,
            "dias_no_teto_da_api": varredura.dias_no_cap,
            "janela_efetiva": {
                "from": varredura.janela[0].isoformat(),
                "to": varredura.janela[1].isoformat(),
            },
            "teto_por_janela": _TETO_POR_JANELA,
            "teto_examinado": _TETO_EXAMINADO,
        },
        # F131: `detect_drift` e tool de seguranca — nao pode dizer "zero
        # drift" sem dizer ate quando a fonte esta indexada.
        "freshness": varredura.freshness,
        "returned_count": len(drift_result.drift_changes),
    }
