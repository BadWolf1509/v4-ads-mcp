"""Sinais de expiração do OAuth pessoal Meta exibidos no painel admin.

O cálculo antigo fazia `max(0, delta.days)`, então um token vencido aparecia
como "0 dias" — indistinguível de "expira hoje". O do Wellington venceu em
27/07/2026 e o painel seguiu dizendo "expira em 27/07/2026 (0 dias)".
"""

from datetime import UTC, datetime, timedelta

from src.web.routes import meta_expiry_signals

AGORA = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def test_sem_conexao_nao_produz_sinal():
    s = meta_expiry_signals(None, agora=AGORA)
    assert s.expired is False
    assert s.expiring_soon is False
    assert s.days_until is None
    assert s.days_since is None


def test_token_com_folga():
    s = meta_expiry_signals(AGORA + timedelta(days=60), agora=AGORA)
    assert (s.expired, s.expiring_soon) == (False, False)
    assert s.days_until == 60


def test_token_expirando_em_breve():
    s = meta_expiry_signals(AGORA + timedelta(days=3), agora=AGORA)
    assert (s.expired, s.expiring_soon) == (False, True)
    assert s.days_until == 3


def test_token_expirado_nao_e_zero_dias():
    """O bug: 15 dias vencido virava days_until=0 e 'expira em ... (0 dias)'."""
    s = meta_expiry_signals(AGORA - timedelta(days=15), agora=AGORA)
    assert s.expired is True
    assert s.expiring_soon is False, "vencido nao e 'expirando em breve'"
    assert s.days_until is None
    assert s.days_since == 15


def test_dias_desde_o_vencimento_arredonda_pra_baixo():
    """15,4 dias vencido são 15 dias completos, não 16.

    `timedelta(days=-15.4).days` é -16 (floor); calcular na direção positiva
    evita o off-by-one.
    """
    s = meta_expiry_signals(AGORA - timedelta(days=15, hours=10), agora=AGORA)
    assert s.days_since == 15


def test_fronteira_expira_exatamente_agora_conta_como_expirado():
    s = meta_expiry_signals(AGORA, agora=AGORA)
    assert s.expired is True
    assert s.days_since == 0
