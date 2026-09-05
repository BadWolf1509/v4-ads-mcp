from src.google_ads.reconcile import InventoryRow, build_plan


def _inv(cid: str, *, ativo: bool = True, miss: int = 0) -> InventoryRow:
    return InventoryRow(customer_id=cid, is_active=ativo, missed_syncs=miss)


def test_ausencia_dentro_da_carencia_nao_remove():
    p = build_plan(mcc_ids={"a"}, inventory=[_inv("a"), _inv("b", miss=0)], complete=True)
    assert p.to_remove == []
    assert p.to_bump == ["b"]


def test_ausencia_que_cruza_a_carencia_remove():
    p = build_plan(mcc_ids={"a"}, inventory=[_inv("a"), _inv("b", miss=2)], complete=True)
    assert p.to_remove == ["b"]
    assert p.to_bump == []


def test_leitura_incompleta_bloqueia_destrutivo_mas_ainda_adiciona():
    p = build_plan(mcc_ids={"a", "novo"}, inventory=[_inv("a"), _inv("b", miss=9)], complete=False)
    assert p.to_remove == []
    assert p.blocked_reason == "leitura incompleta"
    assert p.to_add == ["novo"]


def test_conta_que_voltou_zera_o_contador():
    p = build_plan(mcc_ids={"a"}, inventory=[_inv("a", miss=2)], complete=True)
    assert p.to_reset == ["a"]
    assert p.to_remove == []


def test_teto_percentual_barra_remocao_em_massa():
    inv = [_inv(str(i), miss=5) for i in range(20)]
    p = build_plan(mcc_ids=set(), inventory=inv, complete=True)
    assert p.to_remove == []
    assert p.blocked_reason is not None
    assert "remocao em massa" in p.blocked_reason


def test_piso_do_teto_deixa_passar_a_saida_de_uma_conta_so():
    """Sem `max(1, ...)`, 2 ativas -> floor(0.4) = 0 e o guard barraria ATE uma."""
    p = build_plan(mcc_ids={"a"}, inventory=[_inv("a"), _inv("b", miss=5)], complete=True)
    assert p.to_remove == ["b"]
    assert p.blocked_reason is None


def test_conta_ja_inativa_nao_entra_em_plano_nenhum():
    """Documenta o limite do planejador — os 34 grants legados NAO saem daqui.

    Quem os cobre e `revoke_for_inactive_accounts`, que opera sobre o estado.
    """
    p = build_plan(mcc_ids=set(), inventory=[_inv("velha", ativo=False, miss=9)], complete=True)
    assert p.to_remove == []
    assert p.to_bump == []


def test_guard_mede_o_inventario_ativo_e_nao_so_os_ausentes():
    """Protege contra regressao: teto precisa de len(ativos), nao len(ausentes).

    Se alguma mudanca cometer o erro de usar o tamanho dos ausentes, este
    teste falha: 25 ativas, 3 ausentes com carencia ja esgotada. Com
    len(ativos), teto=5 e a remocao prossegue; com len(ausentes) bugado,
    teto=0, bloqueia.
    """
    mcc = {f"c_p_{i}" for i in range(22)}
    presentes = [_inv(f"c_p_{i}") for i in range(22)]
    ausentes = [_inv(f"c_a_{i}", miss=2) for i in range(3)]

    p = build_plan(
        mcc_ids=mcc,
        inventory=presentes + ausentes,
        complete=True,
        threshold=3,
        max_removal_ratio=0.2,
        max_removal_abs=5,
    )
    assert sorted(p.to_remove) == ["c_a_0", "c_a_1", "c_a_2"]
    assert p.blocked_reason is None


def test_teto_absoluto_e_o_vinculante_quando_a_conta_cresce():
    """O ramo `max_removal_abs` do `min()` nao tinha teste nenhum.

    O percentual so supera o absoluto com >= 30 ativas (floor(30*0.2)=6 > 5)
    — o MCC real tem 26 hoje, quatro de distancia. Aqui: 50 ativas,
    floor(50*0.2)=10, cap absoluto 5. Seis remocoes tem de barrar (10
    passaria, 5 nao).
    """
    mcc = {f"c_p_{i}" for i in range(44)}
    presentes = [_inv(f"c_p_{i}") for i in range(44)]
    ausentes = [_inv(f"c_a_{i}", miss=2) for i in range(6)]

    p = build_plan(
        mcc_ids=mcc,
        inventory=presentes + ausentes,
        complete=True,
        threshold=3,
        max_removal_ratio=0.2,
        max_removal_abs=5,
    )

    assert p.to_remove == []
    assert p.blocked_reason is not None
    assert "teto 5" in p.blocked_reason, (
        "o teto anunciado tem de ser o absoluto (5), nao o percentual (10) "
        "— se vier 10, o min() foi invertido e o cap absoluto virou "
        "decorativo"
    )

    # Contraprova: cinco remocoes cabem no mesmo teto, entao o guard nao esta
    # simplesmente barrando tudo.
    p_ok = build_plan(
        mcc_ids=mcc,
        inventory=presentes + ausentes[:5],
        complete=True,
        threshold=3,
        max_removal_ratio=0.2,
        max_removal_abs=5,
    )
    assert len(p_ok.to_remove) == 5
    assert p_ok.blocked_reason is None


def test_conta_inativa_que_volta_ao_mcc_entra_em_to_add():
    """to_add parte so das ATIVAS, nao do inventario inteiro.

    O unico teste com linha inativa que ja existia usa mcc_ids=set(), o que
    zera to_add nas duas variantes (correta e bugada) e nao distingue nada.
    Aqui a conta inativa "velha" volta a aparecer no MCC: com ids_ativos (so
    as ativas) ela nao esta coberta e cai em to_add; se o calculo trocar
    ids_ativos pelo inventario inteiro, "velha" ja "existe" mesmo inativa e
    nunca chega a to_add — corrompe a metrica added do audit log exatamente
    no dia em que a conta volta.
    """
    p = build_plan(
        mcc_ids={"velha", "nova"},
        inventory=[_inv("velha", ativo=False, miss=9), _inv("outra")],
        complete=True,
    )
    assert p.to_add == ["nova", "velha"]
