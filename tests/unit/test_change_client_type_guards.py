"""F142: a whitelist de `client_type` divergia da API nas DUAS direcoes.

Espelha [`test_change_event_enum_guards.py`](test_change_event_enum_guards.py),
que fez o mesmo por `ChangeEventResourceType` no F135/F136 — **e e por isso que
este arquivo existe**. Aquele guard foi escrito no mesmo dia, no mesmo arquivo de
producao, e nao foi estendido ao enum ao lado. O guard tinha sido aplicado a
instancia do problema, nao a classe dele.

Medido em 2026-09-02 contra o SDK v24 instalado: `ChangeClientType` tem 15
valores, `_CLIENT_TYPES` tinha 14, e a diferenca era dupla.

## As duas direcoes, e como cada uma falha

- **`GOOGLE_ADS_AUTOMATED_RULES` sobrava — plural que nao existe.** Probado
  contra a API com o valor tirado do *proprio schema da tool*:
  `Invalid enum value cannot be included in WHERE clause`. O gestor que escolhe
  a opcao oferecida leva erro duro.
- **`GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION` faltava — e producao emite.** Na
  conta 443-298-6150 (Camacari), linha real de 2026-09-01 00:18:46 com
  `user_email: "Recommendations Auto-Apply"`. Nao era filtravel.

## Por que isso e HIGH e nao cosmetico

`_AUTO_APPLY_CLIENT_TYPE` era string unica, entao o valor `_SUBSCRIPTION` nao
casava nada. Medido em producao na mesma conta:

- `get_change_history` devolveu `auto_applied_count: 0` para um auto-apply real;
- `detect_drift` devolveu `total_drift_changes: 1` com **`flags: []`** — a flag
  `auto_apply_detected` nao subiu.

A linha ainda entrava em drift, mas **por acidente**: `"Recommendations
Auto-Apply"` nao e e-mail valido, logo nunca estara em `responsible_user_emails`
(que e `format: email`). O mecanismo desenhado falhava; o que salvava era efeito
colateral. E o caminho que virava falso negativo de verdade e a pergunta natural
do gestor — `client_types=["GOOGLE_ADS_RECOMMENDATIONS"]`, *"o que o Google
aplicou sozinho?"* — que devolvia **vazio** numa conta com auto-apply ativo, e le
como atestado de limpeza.

## Producao NAO deriva do SDK — de proposito

Mesma razao documentada no guard irmao: o schema de uma tool MCP e contrato
publico, e derivar faria um bump do `google-ads` mudar os valores aceitos sem
diff e sem revisao. A fonte autoritativa e o enum do SDK; o reconciliador e o
CI. Aqui o snapshot de producao e cruzado com ele a cada push.
"""

from __future__ import annotations

import importlib

from google.ads.googleads.client import _DEFAULT_VERSION

from src.google_ads.drift_detection import (
    AUTO_APPLY_CLIENT_TYPES,
    ChangeEventRow,
    detect_drift,
)
from src.mcp.tools.get_change_history import _CLIENT_TYPES, _SCHEMA, _build_summary

# Dump verificado em 2026-09-02 com o SDK instalado (v24). Tripwire de upgrade:
# se o `google-ads` ganhar ou perder valor, este teste falha com causa distinta
# do guard de reconciliacao, e a mudanca entra por revisao humana.
SDK_SNAPSHOT_2026_09_02 = [
    "GOOGLE_ADS_API",
    "GOOGLE_ADS_AUTOMATED_RULE",
    "GOOGLE_ADS_BULK_UPLOAD",
    "GOOGLE_ADS_EDITOR",
    "GOOGLE_ADS_MOBILE_APP",
    "GOOGLE_ADS_RECOMMENDATIONS",
    "GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION",
    "GOOGLE_ADS_SCRIPTS",
    "GOOGLE_ADS_WEB_CLIENT",
    "INTERNAL_TOOL",
    "OTHER",
    "SEARCH_ADS_360_POST",
    "SEARCH_ADS_360_SYNC",
    "UNKNOWN",
    "UNSPECIFIED",
]

# Probado contra a API em 2026-09-02 com o valor tirado do proprio schema:
# "Invalid enum value cannot be included in WHERE clause".
VALORES_QUE_A_API_REJEITA = ["GOOGLE_ADS_AUTOMATED_RULES"]


def _client_types_do_sdk() -> list[str]:
    """Le o enum do SDK instalado, seguindo a versao default do proprio client.

    `_DEFAULT_VERSION` de proposito: um `v24` cravado daria erro de import no
    upgrade, em vez do diff legivel que se quer.
    """
    mod = importlib.import_module(
        f"google.ads.googleads.{_DEFAULT_VERSION}.enums.types.change_client_type"
    )
    return sorted(mod.ChangeClientTypeEnum.ChangeClientType.__members__)


def _linha(client_type: str, *, user_email: str = "Recommendations Auto-Apply") -> ChangeEventRow:
    """Espelha a linha REAL medida na conta 443-298-6150 em 2026-09-01."""
    return ChangeEventRow(
        change_date_time="2026-09-01 00:18:46.24211",
        user_email=user_email,
        client_type=client_type,
        resource_type="AD_GROUP_CRITERION",
        resource_id="184539552373~375174278350",
        resource_name="[CPA] [PESQUISA][V4] [TOPO]",
        operation="CREATE",
        changed_fields=["keyword.text"],
        campaign_id="22958589284",
        ad_group_id="184539552373",
        old_status=None,
        new_status=None,
    )


# --- As duas direcoes da divergencia -----------------------------------------


def test_schema_nao_oferece_valor_que_a_api_rejeita() -> None:
    """Oferecer filtro que a API recusa transforma pergunta valida em erro duro."""
    sobrando = sorted(set(VALORES_QUE_A_API_REJEITA) & set(_CLIENT_TYPES))
    assert sobrando == [], f"schema oferece valores que a API rejeita: {sobrando}"


def test_auto_apply_por_assinatura_e_filtravel() -> None:
    """O valor que producao emite e que nao dava pra filtrar."""
    assert "GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION" in _CLIENT_TYPES


def test_producao_bate_com_o_enum_do_sdk_instalado() -> None:
    """O guard central: reconcilia o snapshot de producao com a fonte autoritativa.

    Igualdade de CONJUNTOS, nao de tamanho — `len(...) == 15` passaria com dois
    nomes trocados, que e exatamente o defeito que o F142 foi.
    """
    do_sdk = _client_types_do_sdk()
    assert sorted(_CLIENT_TYPES) == do_sdk, (
        "_CLIENT_TYPES divergiu do enum do SDK. "
        f"Faltando: {sorted(set(do_sdk) - set(_CLIENT_TYPES))}. "
        f"Sobrando: {sorted(set(_CLIENT_TYPES) - set(do_sdk))}."
    )


def test_sdk_nao_mudou_desde_a_verificacao_de_2026_09_02() -> None:
    """Tripwire de upgrade de SDK, com causa distinta do teste acima."""
    assert _client_types_do_sdk() == sorted(SDK_SNAPSHOT_2026_09_02)


def test_schema_publica_exatamente_a_lista_de_producao() -> None:
    """O schema tem que servir a constante, nao uma copia que envelhece sozinha."""
    assert _SCHEMA["properties"]["client_types"]["items"]["enum"] == _CLIENT_TYPES


# --- O efeito que tornou isto HIGH -------------------------------------------


def test_auto_apply_por_assinatura_conta_em_auto_applied_count() -> None:
    """O sintoma medido: auto-apply real com `auto_applied_count: 0`."""
    linha = {
        "client_type": "GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION",
        "user_email": "Recommendations Auto-Apply",
        "resource_type": "AD_GROUP_CRITERION",
        "operation": "CREATE",
    }
    resumo = _build_summary([linha])
    assert resumo["auto_applied_count"] == 1
    assert resumo["by_user"] == {"auto-apply": 1}, (
        "auto-apply tem que colapsar no bucket sintetico, nao virar um 'usuario' "
        "chamado 'Recommendations Auto-Apply'"
    )


def test_variante_antiga_de_auto_apply_continua_contando() -> None:
    """Guard contra fix que troca um valor pelo outro em vez de aceitar os dois."""
    linha = {
        "client_type": "GOOGLE_ADS_RECOMMENDATIONS",
        "user_email": "",
        "resource_type": "CAMPAIGN",
        "operation": "UPDATE",
    }
    assert _build_summary([linha])["auto_applied_count"] == 1


def test_drift_levanta_flag_para_auto_apply_por_assinatura() -> None:
    """O sintoma medido: `total_drift_changes: 1` com `flags: []`."""
    resultado = detect_drift(
        [_linha("GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION")],
        responsible_user_emails=["wellington.ribeiro@v4company.com"],
        limit=100,
    )
    codigos = [f.code for f in resultado.flags]
    assert "auto_apply_detected" in codigos, (
        f"auto-apply por assinatura nao levantou a flag; flags={codigos}"
    )


def test_drift_conta_auto_apply_por_assinatura_como_drift_mesmo_com_email_autorizado() -> None:
    """A pegada nao pode depender do nome de exibicao nao ser e-mail valido.

    Hoje a linha entra em drift por acidente: `"Recommendations Auto-Apply"` nao
    e e-mail, logo nunca estara na lista de autorizados. Este teste forca a
    invariante DECLARADA — auto-apply sempre e drift — passando um
    `user_email` que ESTA autorizado. Se o codigo so partisse pelo e-mail, a
    linha sairia da contagem e o teste falha.
    """
    autorizado = "wellington.ribeiro@v4company.com"
    resultado = detect_drift(
        [_linha("GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION", user_email=autorizado)],
        responsible_user_emails=[autorizado],
        limit=100,
    )
    assert resultado.summary.total_drift_changes == 1


def test_os_dois_valores_de_auto_apply_estao_no_conjunto() -> None:
    """A constante compartilhada, que substitui as duas copias divergentes."""
    assert (
        frozenset({"GOOGLE_ADS_RECOMMENDATIONS", "GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION"})
        == AUTO_APPLY_CLIENT_TYPES
    )
