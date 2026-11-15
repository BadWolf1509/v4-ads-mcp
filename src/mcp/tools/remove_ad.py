# bucket: defer
"""Tool: remove_ad — remove anuncios (ad_group_ad), sempre com token (S3).

**Por que tool propria.** Remocao e IRREVERSIVEL: anuncio REMOVED nao volta a ENABLED.
O `update_ad_status` aceita so ENABLED/PAUSED e auto-aplica ate 5; misturar o
irreversivel numa tool que auto-aplica foi descartado no desenho (spec 2026-11-14, S3).

Dry-run le cada anuncio por GAQL e recusa: `ad_id` inexistente, anuncio em mais de um
grupo (nao ha como escolher qual remover), e variacao de experimento (`AD_VARIATIONS`,
F181 — gerenciada pelo Google), apontando o anuncio base. Os que ja estao REMOVED saem
do lote; todos REMOVED -> `no_changes`, sem token. Fora isso, sempre token (CONFIRM
fixo); o `apply_change` rele o status de cada anuncio depois da escrita.
"""

from typing import Any

from src.google_ads.preflight import buscar_ads_base_do_grupo, descrever_base
from src.google_ads.queries.remover_anuncio import (
    anuncios_query,
    enabled_por_grupo_query,
    parse_anuncio_row,
    parse_enabled_row,
)
from src.google_ads.reports import run_report
from src.governance.blast_radius import classify
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import emitir_preview, error_envelope, no_changes_envelope
from src.mcp.tools._registry import register_tool

_OPERACAO = "remove_ad"

_AVISO_IRREVERSIVEL = (
    "A remocao e irreversivel: anuncio REMOVED nao volta a ENABLED; para voltar, crie outro."
)
_AVISO_ULTIMO_ENABLED = "ultimo anuncio ENABLED do grupo — o grupo para de servir"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "ad_ids": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "uniqueItems": True,
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "description": (
                "ad_id dos anuncios a remover (ad_group_ad.ad.id). O grupo de cada um e "
                "lido pela tool."
            ),
        },
    },
    "required": ["customer_id", "ad_ids"],
    "additionalProperties": False,
}


@register_tool(
    name=_OPERACAO,
    description=(
        "[DEFER] Remove (REMOVED) ate 20 anuncios pelo ad_id. A remocao e irreversivel: "
        "anuncio REMOVED nao volta a ENABLED; para voltar, crie outro. Para so pausar, "
        "use update_ad_status. Recusa ad_id inexistente, anuncio em mais de um grupo e "
        "variacao de experimento (AD_VARIATIONS, gerenciada pelo Google — aponta o "
        "anuncio base). Anuncio que ja esta REMOVED sai do lote; se todos estao, "
        "responde no_changes sem token. Senao, SEMPRE devolve preview (grupo, campanha, "
        "status atual e aviso quando o lote tira o ultimo anuncio ENABLED do grupo) com "
        "confirmation_token. Aplicar via apply_change, que rele o status de cada anuncio; "
        "o veredito vai em `conferencia` na linha, e `efeito` segue sendo o ACK do Google. "
        "Anuncio que muda de estado entre o preview e o apply volta na linha do "
        "apply_change (partial failure ou `conferencia`); nada e refeito as cegas."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def remove_ad(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    # Normaliza ANTES de tudo: `uniqueItems` do schema compara a string crua, e "22" e
    # "022" viram a mesma remocao duas vezes — a segunda voltaria `failed` para um
    # anuncio que foi removido, o sinal que leva o gestor a tentar de novo.
    ad_ids: list[str] = [str(int(a)) for a in args["ad_ids"]]
    duplicados = sorted({a for a in ad_ids if ad_ids.count(a) > 1}, key=int)
    if duplicados:
        return error_envelope(
            _OPERACAO,
            f"ad_id repetido depois de normalizar (zeros a esquerda): {', '.join(duplicados)}. "
            "Mande cada anuncio uma vez so. Nada foi feito.",
            customer_id=customer_id,
        )

    linhas = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=anuncios_query(ad_ids),
        row_formatter=parse_anuncio_row,
        operation_name=f"{_OPERACAO}_lookup",
    )
    por_ad: dict[str, list[dict[str, Any]]] = {}
    for linha in linhas:
        por_ad.setdefault(linha["ad_id"], []).append(linha)

    inexistentes = [a for a in ad_ids if a not in por_ad]
    if inexistentes:
        return error_envelope(
            _OPERACAO,
            f"Anuncio(s) {', '.join(inexistentes)} nao encontrado(s) na conta "
            f"{customer_id}. Verifique o ad_id. Nada foi feito.",
            customer_id=customer_id,
        )

    for aid in ad_ids:
        grupos = sorted({linha["ad_group_id"] for linha in por_ad[aid]})
        if len(grupos) > 1:
            return error_envelope(
                _OPERACAO,
                f"O anuncio {aid} aparece em mais de um grupo ({', '.join(grupos)}): nao ha "
                "como escolher qual vinculo remover. Nada foi feito; remova pela UI do "
                "Google Ads.",
                customer_id=customer_id,
            )

    atuais = {aid: por_ad[aid][0] for aid in ad_ids}

    for aid in ad_ids:
        ad = atuais[aid]
        # F181: comparacao por VALOR — em proto-plus o atributo existe sempre (F145).
        if ad["system_managed_source"] == "AD_VARIATIONS":
            base_ids = await buscar_ads_base_do_grupo(
                manager_id=ctx.manager_id,
                session_id=ctx.session_id,
                customer_id=customer_id,
                ad_group_id=ad["ad_group_id"],
            )
            alvo = descrever_base(base_ids, ad["ad_group_name"], ad["ad_group_id"])
            return error_envelope(
                _OPERACAO,
                f"O anuncio {aid} e uma variacao de experimento (AD_VARIATIONS, gerenciada "
                f"pelo Google) e nao aceita remocao. Para mudar o que veicula no grupo, "
                f"atue sobre {alvo}: a variacao herda a mudanca. Para tirar a variacao, "
                f"encerre o experimento na UI do Google Ads. Nada foi feito.",
                customer_id=customer_id,
            )

    ja_removidos = [aid for aid in ad_ids if atuais[aid]["status"] == "REMOVED"]
    lote = [aid for aid in ad_ids if aid not in ja_removidos]
    if not lote:
        return no_changes_envelope(
            _OPERACAO,
            customer_id,
            # Mesmo "ja esta X" do N3 (update_recommendation_subscription).
            message=(
                f"{len(ja_removidos)} anuncio(s) pedido(s), e cada um ja esta REMOVED. "
                "Nenhum token emitido."
            ),
            ja_removidos=ja_removidos,
        )

    grupos_do_lote = list(dict.fromkeys(atuais[aid]["ad_group_id"] for aid in lote))
    enabled = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=enabled_por_grupo_query(grupos_do_lote),
        row_formatter=parse_enabled_row,
        operation_name=f"{_OPERACAO}_enabled_por_grupo",
    )
    enabled_por_grupo: dict[str, set[str]] = {}
    for linha in enabled:
        enabled_por_grupo.setdefault(linha["ad_group_id"], set()).add(linha["ad_id"])
    no_lote = set(lote)

    anuncios: list[dict[str, Any]] = []
    for aid in lote:
        ad = atuais[aid]
        item: dict[str, Any] = {
            "ad_id": aid,
            "ad_group_id": ad["ad_group_id"],
            "ad_group_name": ad["ad_group_name"],
            "campaign_name": ad["campaign_name"],
            "status_atual": ad["status"],
        }
        # So remover um ENABLED muda o que o grupo serve. O que sobra ENABLED no grupo e
        # o lido MENOS o lote inteiro: dois ENABLED removidos juntos tambem esvaziam.
        restantes = enabled_por_grupo.get(ad["ad_group_id"], set()) - no_lote
        if ad["status"] == "ENABLED" and not restantes:
            item["aviso"] = _AVISO_ULTIMO_ENABLED
        anuncios.append(item)

    n = len(lote)
    grupos_esvaziados = sorted({i["ad_group_id"] for i in anuncios if "aviso" in i})
    resumo = f"Remover {n} anuncio(s) ({', '.join(lote[:3])}{'...' if n > 3 else ''})."
    if ja_removidos:
        resumo += f" {len(ja_removidos)} ja estava(m) REMOVED e saiu(ram) do lote."
    if grupos_esvaziados:
        # O `apply_change` reexibe o `blast_summary`: aviso fora dele some na hora de
        # confirmar.
        resumo += f" ATENCAO: {_AVISO_ULTIMO_ENABLED} (grupo(s) {', '.join(grupos_esvaziados)})."
    resumo += f" {_AVISO_IRREVERSIVEL}"

    risk = classify(operation="remove_ad", params={"target_count": n})
    payload = {
        "ads": [{"ad_group_id": atuais[aid]["ad_group_id"], "ad_id": aid} for aid in lote],
        "__target_count__": n,
        # Relatorio por linha: e nele que vivem o `efeito` (ACK do Google) e a
        # `conferencia` que o pos-check preenche com a releitura.
        "__partial_failure__": True,
        # Audit: so contagem e ids, nada de nome de grupo/campanha.
        "__params_summary__": {"count": n, "ad_ids": lote},
    }
    return await emitir_preview(
        ctx,
        operation=_OPERACAO,
        customer_id=customer_id,
        payload=payload,
        resumo=resumo,
        risk=risk,
        anuncios=anuncios,
        ja_removidos=ja_removidos,
        aviso_irreversivel=_AVISO_IRREVERSIVEL,
    )
