# bucket: always
"""Tool: remove_asset_link — desvincula asset, sem tocar na entidade.

Inverso do `create_and_link_assets`, que existia sem contraparte e custava idas
a UI. Formato precedente: `remove_audience.py`.

NAO remove a entidade `Asset` (spec secao 2): o que serve na SERP e o vinculo,
asset orfao e inerte, e remover a entidade e irreversivel numa coisa que pode
estar linkada onde a varredura nao alcancou.
"""

from typing import Any

from src.db import connection
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import error_envelope, preview_envelope
from src.mcp.tools._registry import register_tool

# O segmento de path e' derivavel do `level` — usado no pre-flight pra pegar
# um par que nao bate ANTES de mintar token (ver `_preflight_validate`).
_SEGMENTO_POR_NIVEL = {
    "CUSTOMER": "customerAssets",
    "CAMPAIGN": "campaignAssets",
    "AD_GROUP": "adGroupAssets",
}

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "level": {"type": "string", "enum": ["CUSTOMER", "CAMPAIGN", "AD_GROUP"]},
                    "resource_name": {"type": "string", "minLength": 1},
                },
                "required": ["level", "resource_name"],
                "additionalProperties": False,
            },
            "minItems": 1,
            "maxItems": 100,
        },
    },
    "required": ["customer_id", "links"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[CORE] Desvincula assets: remove o vínculo (customer_asset / campaign_asset "
    "/ ad_group_asset) e **não remove o asset** em si — asset órfão é inerte, e a "
    "entidade pode estar linkada onde a varredura não alcançou. Recebe `level` + "
    "`resource_name` exatamente como o `get_assets` devolve em cada linha; use "
    "aquela tool para descobrir o que remover, inclusive na camada de conta, que "
    "não aparece para quem olha só campanha. Sempre CONFIRM: devolve preview com "
    "confirmation_token, aplique via apply_change. Idempotente: vínculo já "
    "removido volta graciosamente via partial_failure. **Para confirmar a "
    "remoção, cheque `status == REMOVED` no registro alvo** — contagem de linhas "
    "NÃO distingue sucesso de falha, porque o vínculo removido continua na tabela."
)


def _preflight_validate(customer_id: str, links: list[dict[str, Any]]) -> str | None:
    """Devolve mensagem de erro PT-BR se algum link for invalido; None se OK.

    `level` escolhe o CAMPO da operacao no builder (`build_remove_asset_link`);
    `resource_name` e' copiado verbatim, sem checagem cruzada. Um par que nao
    bate — ex.: `level=CUSTOMER` com um `resource_name` de campaignAssets —
    monta uma operacao VALIDA (proto bem formado) que o Google rejeita
    POR OPERACAO em runtime. Como o payload leva `__partial_failure__: True`,
    essa rejeicao nunca levanta excecao, e `apply_change` descarta
    `partial_failures` do resultado — o gestor veria `status: "applied"` com
    `applied_count: 0` e nenhum motivo. Pre-flight local (sem GAQL: e' pura
    checagem de string, os dois valores ja' vieram no payload) pega isso antes
    de mintar o token, no mesmo espirito do `_preflight_validate` de
    `apply_audience.py` (audience_type vs segmento do resource_name).
    """
    for i, link in enumerate(links):
        nivel = link["level"]
        resource_name = link["resource_name"]
        segmento_esperado = _SEGMENTO_POR_NIVEL[nivel]
        if f"/{segmento_esperado}/" not in resource_name:
            return (
                f"links[{i}]: level='{nivel}' incompativel com resource_name "
                f"(esperado segmento /{segmento_esperado}/ no path, recebido "
                f"'{resource_name}')"
            )
        if not resource_name.startswith(f"customers/{customer_id}/"):
            return (
                f"links[{i}]: resource_name pertence a outra conta (esperado "
                f"prefixo customers/{customer_id}/, recebido '{resource_name}')"
            )
    return None


@register_tool(
    name="remove_asset_link",
    description=_DESCRIPTION,
    input_schema=_SCHEMA,
    bucket="always",
)
async def remove_asset_link(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    links = args["links"]
    target_count = len(links)

    # Schema nao expressa regra condicional entre level e resource_name (e o
    # repo evita oneOf/allOf/anyOf em input_schema) — pre-flight em Python,
    # ANTES de mintar token.
    preflight_error = _preflight_validate(customer_id, links)
    if preflight_error:
        return error_envelope("remove_asset_link", preflight_error, customer_id=customer_id)

    risk = classify(operation="remove_asset_link", params={"target_count": target_count})
    # Always-CONFIRM: nao ha branch AUTO.

    por_nivel: dict[str, int] = {}
    for link in links:
        por_nivel[link["level"]] = por_nivel.get(link["level"], 0) + 1

    payload = {
        "links": links,
        "__target_count__": target_count,
        "__partial_failure__": True,
        "__params_summary__": {"target_count": target_count, "by_level": por_nivel},
    }
    niveis = ", ".join(f"{n}×{c}" for n, c in sorted(por_nivel.items()))
    summary = f"Desvincular {target_count} asset(s) ({niveis}). A entidade Asset NÃO é removida."

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="remove_asset_link",
            payload=payload,
            blast_summary=summary,
        )
    return preview_envelope(
        "remove_asset_link",
        customer_id,
        summary,
        token,
        confirmation_reason=risk.reason,
        target_count=target_count,
    )
