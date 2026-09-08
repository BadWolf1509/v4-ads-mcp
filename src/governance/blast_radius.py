"""Blast radius classifier — decides auto-apply vs require-confirmation per operation.

Defaults are conservative. Unknown operations always require confirmation.
Each rule cites the spec section it implements (§7.1).
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.google_ads.queries.recommendations import (
    TIPOS_CONHECIDOS,
    TIPOS_DE_MIGRACAO,
    TIPOS_QUE_CONFIRMAM,
)


class RiskLevel(StrEnum):
    AUTO = "auto"
    CONFIRM = "confirm"


@dataclass(slots=True, frozen=True)
class RiskClassification:
    level: RiskLevel
    reason: str  # Human-readable PT-BR explanation


# Threshold constants from spec §7.1
_BULK_THRESHOLD = 5
_BID_DELTA_PCT_THRESHOLD = 20.0


def _bulk_status_classify(operation: str, target_count: int) -> RiskClassification:
    if target_count <= 0:
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"{operation}: target_count={target_count} desconhecido — confirmar por seguranca",
        )
    if target_count == 1:
        return RiskClassification(
            RiskLevel.AUTO,
            f"{operation}: single entity — auto",
        )
    if target_count <= _BULK_THRESHOLD:
        return RiskClassification(
            RiskLevel.AUTO,
            f"{operation}: bulk pequeno ({target_count} entities <= {_BULK_THRESHOLD}) — auto",
        )
    return RiskClassification(
        RiskLevel.CONFIRM,
        f"{operation}: more than {_BULK_THRESHOLD} entities ({target_count}) — confirmar",
    )


def _bid_classify(operation: str, target_count: int, max_delta_pct: float) -> RiskClassification:
    if target_count <= 0:
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"{operation}: target_count={target_count} desconhecido — confirmar",
        )
    if max_delta_pct > _BID_DELTA_PCT_THRESHOLD:
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"{operation}: variacao maxima {max_delta_pct:.1f}% > 20% — confirmar",
        )
    if target_count > _BULK_THRESHOLD:
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"{operation}: more than {_BULK_THRESHOLD} entities ({target_count}) — confirmar",
        )
    return RiskClassification(
        RiskLevel.AUTO,
        f"{operation}: small variation ({max_delta_pct:.1f}%) AND {target_count} entities — auto",
    )


def classify(*, operation: str, params: dict[str, Any]) -> RiskClassification:
    """Classify a mutation operation as auto-apply or requires-confirmation.

    `params` is a dict like {target_count: int, delta_pct?: float, max_delta_pct?: float,
    new_status?: 'ENABLED'|'PAUSED'}.
    """
    target_count = int(params.get("target_count", 0))

    # Status changes (campaign/ad_group/ad/keyword) — bulk-aware
    if operation in (
        "update_campaign_status",
        "update_ad_group_status",
        "update_ad_status",
        "update_keyword_status",
    ):
        return _bulk_status_classify(operation, target_count)

    # Budget mutations — always confirm (spec §7.1)
    if operation == "update_campaign_budget":
        return RiskClassification(
            RiskLevel.CONFIRM,
            "Mudanca de orcamento de campanha — confirmar sempre (budget)",
        )

    # Bidding strategy mutations — always confirm
    if operation == "update_campaign_bidding":
        return RiskClassification(
            RiskLevel.CONFIRM,
            "Mudanca de estrategia de bidding — confirmar sempre",
        )

    # Bid mutations (ad_group_bid, keyword_bid) — variation+count aware
    if operation in ("update_ad_group_bid", "update_keyword_bid"):
        max_delta_pct = float(params.get("max_delta_pct", 100.0))  # unknown = high
        return _bid_classify(operation, target_count, max_delta_pct)

    # Negatives — safe, always auto (spec §7.1)
    if operation in (
        "add_negative_keywords",
        "remove_negative_keywords",
        "add_negatives_from_search_terms",
    ):
        return RiskClassification(
            RiskLevel.AUTO,
            f"{operation} ({target_count} negatives) — auto, negatives raramente quebram",
        )

    # Add keywords — additive operation (per spec §7.1: Add KWs ≤20 em 1 ad_group = auto)
    if operation == "add_keywords":
        if target_count <= 0:
            return RiskClassification(
                RiskLevel.CONFIRM,
                f"add_keywords: target_count={target_count} desconhecido — confirmar",
            )
        if target_count <= 20:
            return RiskClassification(
                RiskLevel.AUTO,
                f"add_keywords ({target_count} KWs em 1 ad_group) — auto",
            )
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"add_keywords: more than 20 KWs ({target_count}) — confirmar",
        )

    # Apply audience — mode-aware (observation additive ≤20 = auto;
    # exclusion always confirms per spec §7.1 delivery-impact policy)
    if operation == "apply_audience":
        mode = (params.get("mode") or "").lower()
        if mode == "exclusion":
            return RiskClassification(
                RiskLevel.CONFIRM,
                "apply_audience: exclusion mode — sempre confirma (delivery impact)",
            )
        if target_count <= 0:
            return RiskClassification(
                RiskLevel.CONFIRM,
                f"apply_audience: target_count={target_count} desconhecido — confirmar",
            )
        if target_count <= 20:
            return RiskClassification(
                RiskLevel.AUTO,
                f"apply_audience observation ({target_count} attachments) — auto",
            )
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"apply_audience: observation com >20 attachments ({target_count}) — confirmar",
        )

    # Create ad_group — always CONFIRM (spec §7.1 creates sensitive)
    if operation == "create_ad_group":
        return RiskClassification(
            RiskLevel.CONFIRM,
            "create_ad_group: criacao de entidade(s) — sempre CONFIRM (spec §7.1)",
        )

    # Create RSA — always CONFIRM (spec §7.1 creates sensitive)
    elif operation == "create_rsa":
        return RiskClassification(
            RiskLevel.CONFIRM,
            "create_rsa: criacao de RSA(s) — sempre CONFIRM (spec §7.1)",
        )

    # Update RSA — always CONFIRM (spec §7.1)
    elif operation == "update_rsa":
        return RiskClassification(
            RiskLevel.CONFIRM,
            "update_rsa: modificacao de RSA(s) existente(s) — sempre CONFIRM (spec §7.1)",
        )

    # Create conversion action — always CONFIRM (spec §7.1 creates sensitive +
    # tracking affects ROAS attribution + Smart Bidding strategies)
    elif operation == "create_conversion_action":
        return RiskClassification(
            RiskLevel.CONFIRM,
            "create_conversion_action: criacao de ConversionAction(s) — sempre CONFIRM (spec §7.1)",
        )

    # Create conversion value rule set — always CONFIRM (spec §7.1 creates
    # sensitive + rules afetam ROAS attribution via conditional value boost)
    elif operation == "create_conversion_value_rule_set":
        return RiskClassification(
            RiskLevel.CONFIRM,
            "create_conversion_value_rule_set: criacao de RuleSet com rules — sempre CONFIRM (spec §7.1)",
        )

    # Update conversion action — AUTO single rename; CONFIRM otherwise
    # (Sprint 3b.27). Disabling primary_for_goal turns off Smart Bidding signal —
    # high impact, always CONFIRM.
    # F44 (3b.27.1): include_in_conversions_metric removed from V0 (immutable in v24).
    elif operation == "update_conversion_action":
        updates = params.get("updates", [])
        has_unsafe_disable = any(u.get("primary_for_goal") is False for u in updates)
        if len(updates) == 1 and not has_unsafe_disable:
            return RiskClassification(
                RiskLevel.AUTO,
                "update_conversion_action: 1 entity sem desligar Smart Bidding signal",
            )
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"update_conversion_action: {len(updates)} entity/ies — requer preview",
        )

    # Upload Customer Match list — sempre CONFIRM (Sprint 3b.28).
    # PII upload tem alto blast radius (LGPD audit + Google billing baseado
    # em members ingeridos). Não há AUTO path V0.
    elif operation == "upload_customer_match_list":
        members = params.get("members", [])
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"upload_customer_match_list: {len(members)} membro(s) — PII upload, sempre CONFIRM",
        )

    # Remove audience — always CONFIRM (spec §7.1 "Remove qualquer coisa = sempre confirma")
    # Audience criterion removal can restore audience to delivery pool (if exclusion).
    # Symmetric with Sprint 3b.2 REMOVED policy principle.
    if operation == "remove_audience":
        if target_count <= 0:
            return RiskClassification(
                RiskLevel.CONFIRM,
                f"remove_audience: target_count={target_count} desconhecido — confirmar",
            )
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"remove_audience ({target_count} criteria) — sempre confirma (spec §7.1 remove)",
        )

    # Unlink de asset — remove, sempre confirma (spec §7.1). O vinculo sai; a
    # entidade Asset NAO. Fallback de unknown ja daria CONFIRM, mas a razao
    # ficaria ilegivel pro gestor e a intencao nao ficaria registrada.
    if operation == "remove_asset_link":
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"remove_asset_link ({target_count} vínculo(s)) — sempre confirma (spec §7.1 remove)",
        )

    # Recommendations — o veredito depende do TIPO da recomendacao (C2).
    #
    # "Sugestao do Google" nao e uma categoria de risco: `CAMPAIGN_BUDGET` medida
    # em 07/09 propunha R$ 50,00 -> R$ 180,00 (3,6x) numa campanha viva. O MESMO
    # efeito pelo `update_campaign_budget` sempre foi CONFIRM logo acima nesta
    # funcao — duas portas com governanca oposta. Os 23 tipos saem de
    # `CAMPOS_DE_DETALHE`, lida do proto do v24 por DOIS eixos: mexer numa
    # alavanca de gasto ja existente, ou MIGRAR a campanha (C1, 07/09). O eixo da
    # irreversibilidade faltava, e por isso os cinco `*_TO_PERFORMANCE_MAX` /
    # `PERFORMANCE_MAX_OPT_IN` auto-aplicavam uma conversao sem volta.
    if operation == "apply_recommendation":
        tipo = str(params.get("recommendation_type") or "").upper()
        if not tipo:
            # Tipo nao resolvido (lookup falhou / caller antigo): lado seguro.
            return RiskClassification(
                RiskLevel.CONFIRM,
                "apply_recommendation: tipo da recomendacao desconhecido — confirmar por seguranca",
            )
        # O EIXO 2 vem primeiro, e a ordem e o ponto: os cinco de migracao sao
        # SUBCONJUNTO de `TIPOS_QUE_CONFIRMAM`, entao cair no ramo de baixo os
        # rotulava "mexe em orcamento ou lance" — que nao e o que eles fazem.
        # Eles MIGRAM a campanha, e e por isso que confirmam. `confirmation_reason`
        # e o campo que o gestor le no preview: quem aprova uma conversao sem
        # volta lendo "mexe em orcamento" esta sendo informado errado sobre a
        # NATUREZA do que aprova, nao so sobre o tamanho.
        if tipo in TIPOS_DE_MIGRACAO:
            return RiskClassification(
                RiskLevel.CONFIRM,
                f"apply_recommendation ({tipo}): MIGRA a campanha para outro tipo de "
                "campanha e o Google nao expoe operacao de volta — confirmar sempre "
                "(eixo da irreversibilidade, spec §7.1)",
            )
        if tipo in TIPOS_QUE_CONFIRMAM:
            return RiskClassification(
                RiskLevel.CONFIRM,
                f"apply_recommendation ({tipo}): mexe em orcamento ou lance — "
                "confirmar sempre, mesma regra do update_campaign_budget (spec §7.1 budget)",
            )
        # Tipo que o SDK v24 nao sabe nomear. Ate 07/09 ele caia no AUTO abaixo:
        # `type_ = 999` parseava como a string "999", `type_pt` vinha None, e a
        # tool aplicava com o resumo "Aplicar recomendacao 999" — sem gate e sem
        # rotulo. Este modulo declara na linha 3 que "unknown operations always
        # require confirmation", e o fallback final desta funcao honra isso; o
        # ramo de recomendacao era a unica contradicao viva da propria politica.
        #
        # A checagem e de PERTINENCIA ao enum do SDK, nao contra uma lista nova:
        # nao ha o que manter. E desconhecido aqui nao quer dizer "provavelmente
        # inofensivo" — quer dizer "nao sei o que isto faz com o dinheiro do
        # cliente", e tipo novo de gasto e justamente o que o Google acrescenta
        # entre uma versao do SDK e a seguinte.
        if tipo not in TIPOS_CONHECIDOS:
            return RiskClassification(
                RiskLevel.CONFIRM,
                f"apply_recommendation ({tipo}): tipo que o SDK v24 nao conhece — "
                "nao da pra afirmar que nao mexe em orcamento nem lance, entao confirmar",
            )
        return RiskClassification(
            RiskLevel.AUTO,
            f"apply_recommendation ({tipo}): nao mexe em orcamento nem lance — auto",
        )

    # Dismiss so descarta a sugestao: nao muda entrega nem gasto.
    if operation == "dismiss_recommendation":
        return RiskClassification(
            RiskLevel.AUTO,
            "dismiss_recommendation — auto, so descarta a sugestao do Google",
        )

    # update_ad_schedule — always CONFIRM (spec ad_schedule §4: define as janelas
    # em que a campanha serve; o que fica de fora PARA de servir)
    elif operation == "update_ad_schedule":
        return RiskClassification(
            RiskLevel.CONFIRM,
            "update_ad_schedule: redefine a grade de veiculacao (conjunto, nao incremento) — sempre CONFIRM",
        )

    # Unknown operation — default safe to confirm
    return RiskClassification(
        RiskLevel.CONFIRM,
        f"{operation}: unknown operation — default seguro: confirmar",
    )
