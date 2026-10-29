"""Regra comum de saldo e dias restantes (spec saldo-da-conta §3.1)."""

from datetime import date

from src.saldo import classificar, media_7d, media_dias_com_gasto, serie_diaria

ONTEM = date(2026, 10, 28)


def test_serie_preenche_dia_ausente_com_zero():
    s = serie_diaria({date(2026, 10, 27): 10.0}, ontem=date(2026, 10, 28), dias=3)
    assert s == [0.0, 10.0, 0.0]


def test_serie_ignora_dia_fora_da_janela():
    s = serie_diaria({date(2026, 10, 20): 99.0, date(2026, 10, 28): 4.0}, ontem=ONTEM, dias=2)
    assert s == [0.0, 4.0]


def test_media_7d_divide_por_sete_com_dias_sem_gasto():
    gastos = {date(2026, 10, 28): 70.0, date(2026, 10, 22): 0.0, date(2026, 10, 21): 500.0}
    # 21/10 fica fora dos 7 dias (22..28); soma 70 / 7
    assert media_7d(gastos, ontem=ONTEM) == 10.0


def test_media_dias_com_gasto_ignora_dias_zerados():
    gastos = {date(2026, 10, 28): 40.0, date(2026, 10, 10): 60.0, date(2026, 10, 11): 0.0}
    assert media_dias_com_gasto(gastos, ontem=ONTEM) == 50.0


def test_media_dias_com_gasto_none_sem_nenhum_dia_positivo():
    assert media_dias_com_gasto({date(2026, 10, 28): 0.0}, ontem=ONTEM) is None
    # gasto anterior a janela de 30 dias nao conta
    assert media_dias_com_gasto({date(2026, 9, 1): 80.0}, ontem=ONTEM) is None


def test_esgotada_com_media_7d_zero():  # Cantina Google, spec §1.4
    c = classificar(restante=0.85, media7=0.0, media_com_gasto=55.0)
    assert c.situacao == "esgotada"
    assert c.motivo == "restante menor que um dia de gasto"


def test_sem_gasto_com_dinheiro():
    c = classificar(restante=500.0, media7=0.0, media_com_gasto=55.0, dias_ate_fim=3)
    assert (c.situacao, c.dias_restantes) == ("sem_gasto", None)
    assert c.motivo == "sem gasto nos últimos 7 dias"


def test_sem_gasto_sem_historico_e_restante_positivo():
    assert classificar(restante=10.0, media7=0.0, media_com_gasto=None).situacao == "sem_gasto"


def test_restante_zero_sem_historico_e_esgotada():
    assert classificar(restante=0.0, media7=0.0, media_com_gasto=None).situacao == "esgotada"


def test_hosp_ocular_acabando():  # R$ 313,22 a ~R$ 49/dia
    c = classificar(restante=313.22, media7=49.23, media_com_gasto=49.23)
    assert c.situacao == "acabando" and c.dias_restantes == 6.4
    assert c.dias_pelo_dinheiro == 6.4 and c.trava_por_data is False


def test_data_de_fim_trava_antes():
    c = classificar(restante=1000.0, media7=50.0, media_com_gasto=50.0, dias_ate_fim=5)
    assert (c.dias_restantes, c.trava_por_data, c.situacao) == (5, True, "acabando")
    assert c.dias_pelo_dinheiro == 20.0


def test_data_de_fim_passada_e_esgotada():
    c = classificar(restante=1000.0, media7=50.0, media_com_gasto=50.0, dias_ate_fim=-1)
    assert c.situacao == "esgotada"
    assert c.motivo == "orçamento da conta encerrado"


def test_com_saldo():
    c = classificar(restante=1000.0, media7=50.0, media_com_gasto=50.0)
    assert c.situacao == "com_saldo" and c.dias_restantes == 20.0 and c.motivo is None


def test_restante_negativo_e_esgotada():
    c = classificar(restante=-5.0, media7=50.0, media_com_gasto=50.0)
    assert c.situacao == "esgotada"


def test_limiar_acabando_usa_o_valor_arredondado():
    # 7.04 dias aparece como 7.0: tem de ser "acabando", nao "com_saldo" mostrando 7.0
    c = classificar(restante=352.0, media7=50.0, media_com_gasto=50.0)
    assert c.dias_restantes == 7.0
    assert c.situacao == "acabando"


def test_restante_zero_tem_motivo():
    c = classificar(restante=0.0, media7=10.0, media_com_gasto=None)
    assert (c.situacao, c.motivo) == ("esgotada", "sem saldo restante")
