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
