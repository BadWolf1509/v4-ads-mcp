"""Tabela dos alvos de mutate de status (campanha, grupo, anuncio, palavra-chave).

Os quatro builders `update_*_status` e os quatro ramos de `bulk_pause_by_query`
montam a mesma operacao: `resource_name` + `status` + mascara `status`. So mudam
o servico, o helper de caminho, o campo do oneof e o enum. Essa diferenca mora
aqui, numa tabela; o payload persistido nos tokens pendentes nao muda.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AlvoDeStatus:
    servico: str
    caminho: str
    campo_op: str
    enum: str


ALVOS_DE_STATUS: dict[str, AlvoDeStatus] = {
    "campaign": AlvoDeStatus(
        "CampaignService", "campaign_path", "campaign_operation", "CampaignStatusEnum"
    ),
    "ad_group": AlvoDeStatus(
        "AdGroupService", "ad_group_path", "ad_group_operation", "AdGroupStatusEnum"
    ),
    "ad": AlvoDeStatus(
        "AdGroupAdService", "ad_group_ad_path", "ad_group_ad_operation", "AdGroupAdStatusEnum"
    ),
    "keyword": AlvoDeStatus(
        "AdGroupCriterionService",
        "ad_group_criterion_path",
        "ad_group_criterion_operation",
        "AdGroupCriterionStatusEnum",
    ),
}


def funcao_de_caminho(client: Any, alvo: AlvoDeStatus) -> Any:
    """O helper de caminho do servico do alvo (ex.: `campaign_path`)."""
    return getattr(client.get_service(alvo.servico), alvo.caminho)


def enum_de_status(client: Any, alvo: AlvoDeStatus) -> Any:
    return getattr(client.enums, alvo.enum)


def operacao_de_status(
    client: Any, alvo: AlvoDeStatus, resource_name: str, status: Any, mascara: Any
) -> Any:
    """Devolve o MutateOperation que atualiza so o `status` do recurso."""
    op = client.get_type("MutateOperation")
    sub_op = getattr(op, alvo.campo_op)
    recurso = sub_op.update
    recurso.resource_name = resource_name
    recurso.status = status
    client.copy_from(sub_op.update_mask, mascara)
    return op
