"""F145: `structural_change` procurava `REMOVE` numa entidade que nunca emite `REMOVE`.

Remover campanha ou grupo no Google Ads NAO e uma operacao de remocao — e um
`UPDATE` do campo `status` para `REMOVED`. Medido em 2026-09-02 na conta
116-386-2076 (remocao real pela UI): `change_resource_type: CAMPAIGN`,
`old_resource.campaign.status: PAUSED`, `new_resource.campaign.status:
REMOVED`, `resource_change_operation: UPDATE`. A flag comparava
`operation == "REMOVE"` e ficou vazia.

Probe agregada sobre 141 eventos / 28 dias deu a regra geral: entidade com
campo `status` que aceita `REMOVED` e soft-deleted e sai como `UPDATE`;
entidade sem esse campo e hard-deleted e sai como `REMOVE`. `CAMPAIGN` nunca
aparece como `REMOVE`. A flag procurava um verbo que a entidade nao emite —
e a description da tool, escrita ao fechar o F136, PROMETIA essa cobertura.

## O desenho

- O SELECT ganha `old_resource`/`new_resource` (o Google so popula os campos
  que mudaram — payload pequeno, medido).
- O formatter extrai `old_status`/`new_status` so para CAMPAIGN/AD_GROUP,
  keyed pelo `resource_type` — porque em proto-plus `new_resource.campaign`
  EXISTE sempre (vazio, `status = UNSPECIFIED`) mesmo numa linha de keyword.
- `ChangeEventRow` ganha os dois campos SEM default: default aqui seria a
  forma exata do F145 de volta — formatter esquece de popular, tudo vira
  `None`, o predicado nunca casa, a flag fica cega em silencio.
- `structural_change` (high): `REMOVE` OU `new_status == REMOVED`.
- `status_change_detected` (medium, decisao registrada): ENABLED<->PAUSED por
  nao-autorizado. Reativar campanha alheia = gasto comeca; pausar = entrega
  para. Reversivel, por isso nao e `structural_change`.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.google_ads.drift_detection import (
    ChangeEventRow,
    detect_drift,
    dict_to_change_event_row,
)
from src.google_ads.queries.change_history import change_history_query
from src.mcp.tools.get_change_history import _row_formatter

TERCEIRO = "terceiro@exemplo.com"
AUTORIZADO = "wellington.ribeiro@v4company.com"


def _row(
    *,
    resource_type: str = "CAMPAIGN",
    operation: str = "UPDATE",
    old_status: str | None = "PAUSED",
    new_status: str | None = "REMOVED",
    user_email: str = TERCEIRO,
) -> ChangeEventRow:
    return ChangeEventRow(
        change_date_time="2026-09-02 23:37:35.965555",
        user_email=user_email,
        client_type="GOOGLE_ADS_WEB_CLIENT",
        resource_type=resource_type,
        resource_id="23861545627",
        resource_name="[3b.24.4] T1 - max_conv",
        operation=operation,
        changed_fields=("status",),
        campaign_id="23861545627",
        ad_group_id=None,
        old_status=old_status,
        new_status=new_status,
    )


def _flags(rows: list[ChangeEventRow]) -> dict[str, object]:
    r = detect_drift(rows, responsible_user_emails=[AUTORIZADO], limit=100)
    return {f.code: f for f in r.flags}


# --- structural_change: o caso do campo -----------------------------------


def test_remocao_de_campanha_e_update_de_status_e_levanta_structural_change() -> None:
    """O evento REAL: UPDATE, PAUSED -> REMOVED. Ontem: flags []."""
    flags = _flags([_row()])
    assert "structural_change" in flags
    f = flags["structural_change"]
    assert f.severity == "high"
    assert "PAUSED" in f.message_pt and "REMOVED" in f.message_pt, (
        "a mensagem tem que citar a transicao, nao um verbo que a entidade nao emite"
    )


def test_ad_group_removido_tambem_levanta() -> None:
    flags = _flags([_row(resource_type="AD_GROUP")])
    assert "structural_change" in flags


def test_remove_de_verdade_continua_levantando() -> None:
    """Regressao: hard-delete (o unico caso que a flag antiga pegava) segue coberto."""
    flags = _flags([_row(operation="REMOVE", old_status=None, new_status=None)])
    assert "structural_change" in flags


def test_update_de_status_para_removed_em_tipo_nao_estrutural_nao_e_structural() -> None:
    """Keyword removida (AD_GROUP_CRITERION) nao e mudanca estrutural."""
    flags = _flags([_row(resource_type="AD_GROUP_CRITERION")])
    assert "structural_change" not in flags


# --- status_change_detected: a decisao de escopo ---------------------------


def test_pausar_campanha_de_terceiro_levanta_status_change_medium() -> None:
    flags = _flags([_row(old_status="ENABLED", new_status="PAUSED")])
    assert "structural_change" not in flags, "pausar e reversivel; nao e estrutural"
    assert "status_change_detected" in flags
    f = flags["status_change_detected"]
    assert f.severity == "medium"
    assert "ENABLED" in f.message_pt and "PAUSED" in f.message_pt


def test_reativar_campanha_de_terceiro_tambem_levanta() -> None:
    """PAUSED -> ENABLED por terceiro: o gasto comeca sem ninguem autorizar."""
    flags = _flags([_row(old_status="PAUSED", new_status="ENABLED")])
    assert "status_change_detected" in flags


def test_pausa_por_gestor_autorizado_nao_levanta_nada() -> None:
    """A flag e sobre drift; mudanca de quem esta na lista nao e drift."""
    flags = _flags([_row(old_status="ENABLED", new_status="PAUSED", user_email=AUTORIZADO)])
    assert flags == {}


def test_remocao_nao_levanta_status_change_por_cima() -> None:
    """REMOVED e so structural_change — nao as duas flags para o mesmo evento."""
    flags = _flags([_row()])
    assert "status_change_detected" not in flags


# --- o dado precisa chegar: SELECT, formatter, converter -------------------


def test_query_seleciona_old_e_new_resource() -> None:
    q = change_history_query(
        start=date(2026, 9, 1),
        end=date(2026, 9, 2),
        resource_types=None,
        operation_types=None,
        user_emails=None,
        client_types=None,
        limit=10,
    )
    assert "change_event.old_resource" in q
    assert "change_event.new_resource" in q


def _linha_proto(*, rtype: str, old: str, new: str) -> SimpleNamespace:
    """Espelha o proto real: `new_resource.campaign` e `.ad_group` EXISTEM sempre.

    Numa linha de CAMPAIGN, `.ad_group.status` e UNSPECIFIED (vazio), e
    vice-versa. O formatter tem que olhar pelo `resource_type`, nao pela
    presenca do atributo.
    """

    def _res(status_campaign: str, status_ad_group: str) -> SimpleNamespace:
        return SimpleNamespace(
            campaign=SimpleNamespace(status=SimpleNamespace(name=status_campaign)),
            ad_group=SimpleNamespace(status=SimpleNamespace(name=status_ad_group)),
        )

    if rtype == "CAMPAIGN":
        old_res, new_res = _res(old, "UNSPECIFIED"), _res(new, "UNSPECIFIED")
    elif rtype == "AD_GROUP":
        old_res, new_res = _res("UNSPECIFIED", old), _res("UNSPECIFIED", new)
    else:
        old_res, new_res = _res("UNSPECIFIED", "UNSPECIFIED"), _res("UNSPECIFIED", "UNSPECIFIED")

    ce = SimpleNamespace(
        change_date_time="2026-09-02 23:37:35.965555",
        user_email=TERCEIRO,
        client_type=SimpleNamespace(name="GOOGLE_ADS_WEB_CLIENT"),
        change_resource_type=SimpleNamespace(name=rtype),
        change_resource_name="customers/1163862076/campaigns/23861545627",
        resource_change_operation=SimpleNamespace(name="UPDATE"),
        changed_fields=SimpleNamespace(paths=["status"]),
        campaign="customers/1163862076/campaigns/23861545627",
        ad_group="",
        old_resource=old_res,
        new_resource=new_res,
    )
    return SimpleNamespace(change_event=ce)


def test_formatter_extrai_a_transicao_de_campaign() -> None:
    d = _row_formatter(_linha_proto(rtype="CAMPAIGN", old="PAUSED", new="REMOVED"))
    assert d["old_status"] == "PAUSED"
    assert d["new_status"] == "REMOVED"


def test_formatter_extrai_a_transicao_de_ad_group() -> None:
    d = _row_formatter(_linha_proto(rtype="AD_GROUP", old="ENABLED", new="PAUSED"))
    assert (d["old_status"], d["new_status"]) == ("ENABLED", "PAUSED")


def test_formatter_nao_inventa_status_para_tipo_nao_estrutural() -> None:
    """`new_resource.campaign` existe (vazio) numa linha de keyword; UNSPECIFIED nao e status."""
    d = _row_formatter(_linha_proto(rtype="AD_GROUP_CRITERION", old="X", new="Y"))
    assert d["old_status"] is None
    assert d["new_status"] is None


def test_ponta_a_ponta_formatter_converter_detector() -> None:
    """O guard que importa: se QUALQUER elo derrubar o campo, a flag some de novo.

    Linha real-shaped -> _row_formatter -> dict_to_change_event_row ->
    detect_drift -> structural_change. E a unica assercao que distingue
    "o campo existe no dataclass" de "o campo chega vivo ao predicado".
    """
    d = _row_formatter(_linha_proto(rtype="CAMPAIGN", old="PAUSED", new="REMOVED"))
    d["resource_name"] = "X"
    row = dict_to_change_event_row(d)
    r = detect_drift([row], responsible_user_emails=[AUTORIZADO], limit=100)
    assert "structural_change" in {f.code for f in r.flags}
    assert r.drift_changes[0].new_status == "REMOVED", "a transicao tem que sair na resposta"
    assert r.drift_changes[0].old_status == "PAUSED"


# --- pelo TOOL inteiro: a serializacao e manual, campo a campo ----------------


async def test_a_transicao_e_a_flag_chegam_ao_json_do_detect_drift() -> None:
    """detect_drift monta o dict de cada change a mao. Se esquecer os campos novos,
    o dataclass tem a transicao e o gestor nao ve. So um teste pelo tool pega isso.
    """
    from unittest.mock import patch
    from uuid import uuid4

    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools.detect_drift import detect_drift as tool

    linha = {
        "change_date_time": "2026-09-02 23:37:35.965555",
        "user_email": TERCEIRO,
        "client_type": "GOOGLE_ADS_WEB_CLIENT",
        "resource_type": "CAMPAIGN",
        "resource_id": "23861545627",
        "resource_name": "[3b.24.4] T1 - max_conv",
        "operation": "UPDATE",
        "changed_fields": ["status"],
        "campaign_id": "23861545627",
        "ad_group_id": None,
        "old_status": "PAUSED",
        "new_status": "REMOVED",
        # chave interna que o formatter real adiciona e o tool remove antes de devolver
        "_resource_path": "customers/1163862076/campaigns/23861545627",
    }

    async def _run(**kwargs):
        q = kwargs["query"]
        if q.rstrip().endswith("LIMIT 1"):
            return [{"change_date_time": "2026-09-02 23:37:35.965555"}]
        return [linha] if "FROM change_event" in q else []

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    try:
        with patch("src.mcp.tools.get_change_history.run_report", _run):
            out = await tool(
                {
                    "customer_id": "1163862076",
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-02",
                    "responsible_user_emails": [AUTORIZADO],
                }
            )
    finally:
        clear_current()

    assert "structural_change" in {f["code"] for f in out["flags"]}
    assert out["changes"][0]["old_status"] == "PAUSED"
    assert out["changes"][0]["new_status"] == "REMOVED"


# --- a licao do F141, aplicada aqui: "sem default" se assere por introspecao ---


def test_os_campos_de_status_nao_tem_default_no_dataclass() -> None:
    """Default em `new_status` e a forma exata do F145 de volta.

    Se o formatter esquecer de popular, tudo vira None, o predicado nunca casa
    e a flag fica cega em silencio — e nenhum teste de comportamento pega,
    porque o converter continua populando. So a assinatura denuncia.
    """
    import dataclasses

    from src.google_ads.drift_detection import DriftChange

    for cls in (ChangeEventRow, DriftChange):
        campos = {f.name: f for f in dataclasses.fields(cls)}
        for nome in ("old_status", "new_status"):
            f = campos[nome]
            assert f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING, (
                f"{cls.__name__}.{nome} ganhou default — e o F145 voltando calado"
            )
