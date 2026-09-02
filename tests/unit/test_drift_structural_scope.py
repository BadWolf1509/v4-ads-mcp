"""F136: `structural_change` prometia vigiar conversion action e nao via nenhuma.

`_STRUCTURAL_RESOURCE_TYPES` guardava `{CAMPAIGN, AD_GROUP, CONVERSION_ACTION}` e a
flag (severity **high**) so dispara com `operation == "REMOVE"` e `resource_type`
nesse conjunto. Mas **`CONVERSION_ACTION` nao existe em `ChangeEventResourceType`**
— ausente do enum do SDK v24 e rejeitado pela API em `WHERE` com "Invalid enum
value". O terceiro membro era codigo morto: a flag so podia disparar em CAMPAIGN e
AD_GROUP, enquanto o docstring e a `message_pt` entregue ao gestor diziam
"CAMPAIGN/AD_GROUP/CONVERSION_ACTION".

Remover uma conversion action quebra Smart Bidding — e das mudancas mais caras que
um terceiro pode fazer numa conta — e o gestor acreditava estar coberto.

## Por que o fix nao foi so apagar o membro

Apagar sozinho deixaria o codigo honesto e a cobertura **pior, calada**: o gestor
continuaria achando que `detect_drift` cobre conversion action, agora sem nem o
vestigio no codigo para alguem notar. E a mesma armadilha que este catalogo cataloga.

Antes de decidir, foi verificado se havia caminho de cobertura. **Nao ha:**
`change_status`, o recurso irmao do `change_event`, tem 21 tipos e tambem **nao**
inclui `CONVERSION_ACTION`. Nenhum dos dois recursos de rastreamento de mudanca da
API enxerga conversion action. Cobertura real exigiria snapshot proprio + diff —
feature separada, nao fix.

Entao o fix e: **apagar o membro morto E declarar o limite** onde o gestor le.
Mesma forma do F131 (fronteira medida em vez de silencio) e do F132 (nenhuma
magnitude prometida): parar de fingir e dizer o que da para saber.

O guard central e o ultimo teste — ele nao cuida deste valor, cuida da CLASSE:
todo membro do conjunto tem de existir no enum autoritativo do SDK.
"""

from __future__ import annotations

import importlib

from google.ads.googleads.client import _DEFAULT_VERSION

import src.mcp.tools.detect_drift  # noqa: F401  — registra a tool no _registry
from src.google_ads.drift_detection import _STRUCTURAL_RESOURCE_TYPES, ChangeEventRow
from src.google_ads.drift_detection import detect_drift as _detect_drift_pure
from src.mcp.tools._registry import get_tool


def _resource_types_do_sdk() -> set[str]:
    mod = importlib.import_module(
        f"google.ads.googleads.{_DEFAULT_VERSION}.enums.types.change_event_resource_type"
    )
    enum_cls = mod.ChangeEventResourceTypeEnum.ChangeEventResourceType
    return {n for n in enum_cls.__members__ if n not in {"UNSPECIFIED", "UNKNOWN"}}


def _row(*, resource_type: str, operation: str = "REMOVE") -> ChangeEventRow:
    return ChangeEventRow(
        change_date_time="2026-09-02 11:00:00",
        user_email="terceiro@exemplo.com",
        client_type="GOOGLE_ADS_WEB_CLIENT",
        resource_type=resource_type,
        resource_id="123",
        resource_name="X",
        operation=operation,
        changed_fields=["status"],
        campaign_id=None,
        ad_group_id=None,
    )


def test_conjunto_estrutural_nao_guarda_valor_que_a_api_nunca_emite() -> None:
    """O caso concreto do F136."""
    assert "CONVERSION_ACTION" not in _STRUCTURAL_RESOURCE_TYPES


def test_mensagem_da_flag_nao_promete_conversion_action() -> None:
    """A promessa chegava ao gestor pela `message_pt`, nao pelo codigo."""
    resultado = _detect_drift_pure(
        [_row(resource_type="CAMPAIGN")],
        responsible_user_emails=[],
        limit=10,
    )
    estruturais = [f for f in resultado.flags if f.code == "structural_change"]
    assert len(estruturais) == 1
    assert "CONVERSION_ACTION" not in estruturais[0].message_pt


def test_description_da_tool_declara_o_limite() -> None:
    """Apagar o membro sem declarar o limite deixaria a cobertura pior, calada."""
    registrada = get_tool("detect_drift")
    assert registrada is not None
    assert "conversion action" in registrada.description.lower()


def test_todo_membro_do_conjunto_existe_no_enum_do_sdk() -> None:
    """O guard da CLASSE, nao do valor.

    Falha para QUALQUER tipo estrutural que a API nao emita — inclusive um que
    alguem adicione de boa-fe no futuro, como foi o caso do CONVERSION_ACTION.
    """
    inexistentes = sorted(_STRUCTURAL_RESOURCE_TYPES - _resource_types_do_sdk())
    assert inexistentes == [], (
        f"tipos estruturais que a API nunca emite (flag morta): {inexistentes}"
    )


def test_a_flag_segue_disparando_no_que_e_coberto() -> None:
    """Guard de nao-regressao: estreitar o conjunto nao pode matar o que funciona."""
    resultado = _detect_drift_pure(
        [_row(resource_type="CAMPAIGN"), _row(resource_type="AD_GROUP")],
        responsible_user_emails=[],
        limit=10,
    )
    codigos = {f.code for f in resultado.flags}
    assert "structural_change" in codigos
