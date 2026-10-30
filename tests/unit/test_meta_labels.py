"""Rotulos PT-BR dos enums de conta da Meta conferidos contra a referencia oficial.

Fonte: developers.facebook.com/docs/marketing-api/reference/ad-account (campos
`account_status` e `disable_reason`), lida em 30/10. A tabela antiga de `account_status`
tinha 102 (que nao existe), 201/202 com o significado de 100/8, e nao tinha 8, 9 e 100:
conta em fechamento ou em carencia saia sem rotulo.
"""

from __future__ import annotations

from src.meta_ads.labels import META_ACCOUNT_STATUS_LABELS, META_DISABLE_REASON_LABELS

_ACCOUNT_STATUS_OFICIAL = {1, 2, 3, 7, 8, 9, 100, 101, 201, 202}


def test_account_status_tem_exatamente_os_codigos_da_meta() -> None:
    assert set(META_ACCOUNT_STATUS_LABELS) == _ACCOUNT_STATUS_OFICIAL


def test_account_status_codigos_que_estavam_trocados_ou_faltando() -> None:
    assert META_ACCOUNT_STATUS_LABELS[8] == "LIQUIDAÇÃO_PENDENTE"
    assert META_ACCOUNT_STATUS_LABELS[9] == "EM_PERÍODO_DE_CARÊNCIA"
    assert META_ACCOUNT_STATUS_LABELS[100] == "FECHAMENTO_PENDENTE"
    assert META_ACCOUNT_STATUS_LABELS[201] == "QUALQUER_ATIVA"
    assert META_ACCOUNT_STATUS_LABELS[202] == "QUALQUER_FECHADA"


def test_account_status_rotulos_existentes_nao_mudam() -> None:
    """Testes e avisos dependem destes (ex.: build_warnings compara com "ATIVO")."""
    assert META_ACCOUNT_STATUS_LABELS[1] == "ATIVO"
    assert META_ACCOUNT_STATUS_LABELS[2] == "DESABILITADO"
    assert META_ACCOUNT_STATUS_LABELS[3] == "PAGAMENTO_PENDENTE"
    assert META_ACCOUNT_STATUS_LABELS[7] == "EM_REVISÃO_DE_RISCO"
    assert META_ACCOUNT_STATUS_LABELS[101] == "FECHADO"


def test_disable_reason_cobre_0_a_15() -> None:
    assert set(META_DISABLE_REASON_LABELS) == set(range(16))
    assert META_DISABLE_REASON_LABELS[0] == "NENHUM"
    assert META_DISABLE_REASON_LABELS[3] == "RISCO_DE_PAGAMENTO"
    assert META_DISABLE_REASON_LABELS[15] == "CONTA_COMPROMETIDA"
