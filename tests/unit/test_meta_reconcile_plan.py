"""O plano e onde mora a decisao de revogar acesso — entao ele e PURO.

Sem I/O, sem banco, sem rede: da pra cobrir por tabela de casos, e um erro aqui
nao precisa de container pra aparecer.
"""

from datetime import UTC, datetime, timedelta

from src.clock import account_today
from src.meta_ads.reconcile import InventoryRow, build_plan

# `build_plan` passou a receber o instante da EXECUCAO (C4, segunda metade): a
# ausencia de hoje so entra na conta se ainda nao estiver em `missed_syncs`, e
# isso se decide comparando `last_missed_on` com o dia da CONTA. Nos casos
# abaixo `last_missed_on` e None, entao o instante nao muda o resultado — o
# parametro e obrigatorio para que nenhum call-site volte a somar +1 por
# execucao em silencio.
AGORA = datetime(2026, 9, 3, 0, 30, tzinfo=UTC)


def inv(id_: str, ativo: bool = True, faltas: int = 0) -> InventoryRow:
    return InventoryRow(ad_account_id=id_, is_active=ativo, missed_syncs=faltas)


def test_conta_nova_da_parceria_entra() -> None:
    plano = build_plan(
        partnership_ids={"act_1", "act_2"},
        reachable_ids={"act_1", "act_2"},
        inventory=[inv("act_1")],
        complete=True,
        now=AGORA,
    )
    assert plano.to_add == ["act_2"]
    assert plano.to_remove == []


def test_ausencia_na_parceria_conta_carencia_antes_de_remover() -> None:
    """Primeira e segunda ausencia so marcam; a terceira remove."""
    for faltas, espera_remocao in ((0, False), (1, False), (2, True)):
        plano = build_plan(
            partnership_ids={"act_1"},
            reachable_ids={"act_1"},
            inventory=[inv("act_1"), inv("act_2", faltas=faltas)],
            complete=True,
            now=AGORA,
            threshold=3,
        )
        assert (plano.to_remove == ["act_2"]) is espera_remocao, f"faltas={faltas}"
        assert (plano.to_bump == ["act_2"]) is not espera_remocao


def test_leitura_incompleta_bloqueia_o_lado_destrutivo_mas_nao_o_aditivo() -> None:
    """F93: pagina que falhou nao e churn. Adicionar segue seguro."""
    plano = build_plan(
        partnership_ids={"act_1", "act_novo"},
        reachable_ids={"act_1"},
        inventory=[inv("act_1"), inv("act_sumiu", faltas=9)],
        complete=False,
        now=AGORA,
    )
    assert plano.to_add == ["act_novo"]
    assert plano.to_remove == []
    assert plano.to_bump == []
    assert plano.blocked_reason == "leitura incompleta"


def test_guard_percentual_barra_remocao_em_massa() -> None:
    """F85: uma resposta estranha nao pode revogar a conta inteira."""
    inventario = [inv(f"act_{i}", faltas=9) for i in range(10)]
    plano = build_plan(
        partnership_ids=set(),
        reachable_ids=set(),
        inventory=inventario,
        complete=True,
        now=AGORA,
        max_removal_ratio=0.2,
        max_removal_abs=5,
    )
    assert plano.to_remove == []
    assert plano.blocked_reason is not None
    assert "10" in plano.blocked_reason  # diz quantas seriam


def test_conta_na_parceria_sem_su_e_sinalizada_nunca_removida() -> None:
    """A distincao que o F128 nao tinha: 'nao alcanco' != 'nao e mais nossa'."""
    plano = build_plan(
        partnership_ids={"act_1"},
        reachable_ids=set(),
        inventory=[inv("act_1")],
        complete=True,
        now=AGORA,
    )
    assert plano.unreachable == ["act_1"]
    assert plano.to_remove == []
    assert plano.to_bump == []


def test_conta_que_reaparece_zera_a_carencia() -> None:
    plano = build_plan(
        partnership_ids={"act_1"},
        reachable_ids={"act_1"},
        inventory=[inv("act_1", faltas=2)],
        complete=True,
        now=AGORA,
    )
    assert plano.to_reset == ["act_1"]
    assert plano.to_remove == []


def test_conta_ja_desativada_nao_reaparece_no_plano_destrutivo() -> None:
    plano = build_plan(
        partnership_ids=set(),
        reachable_ids=set(),
        inventory=[inv("act_velha", ativo=False, faltas=9)],
        complete=True,
        now=AGORA,
    )
    assert plano.to_remove == []
    assert plano.to_bump == []


def test_guard_mede_o_inventario_ativo_e_nao_so_os_ausentes() -> None:
    """Protege contra regressao: teto precisa de len(ativos), nao len(ausentes).

    Se alguma mudanca cometeu o erro de dividir por len(ausentes), este teste
    falharia: 25 ativas, 3 ausentes com threshold ja atingido. Com len(ativos),
    teto=5 e remocao prossegue; com len(ausentes) bugado, teto=0, bloqueia.
    """
    partnership = {f"act_p_{i}" for i in range(22)}
    ausentes = [inv(f"act_a_{i}", faltas=2) for i in range(3)]
    parceiros = [inv(f"act_p_{i}") for i in range(22)]
    inventario = parceiros + ausentes

    plano = build_plan(
        partnership_ids=partnership,
        reachable_ids=partnership,
        inventory=inventario,
        complete=True,
        now=AGORA,
        threshold=3,
        max_removal_ratio=0.2,
        max_removal_abs=5,
    )
    assert sorted(plano.to_remove) == ["act_a_0", "act_a_1", "act_a_2"]
    assert plano.blocked_reason is None


def test_teto_absoluto_e_o_vinculante_quando_a_conta_cresce() -> None:
    """T3b: o ramo `max_removal_abs` do `min()` nao tinha teste nenhum.

    Com o inventario de hoje (24 ativas) `floor(24 * 0.2) = 4 < 5`, entao a
    RAZAO e sempre a vinculante e o cap absoluto e codigo que ninguem exercita —
    ele so passa a valer se a conta crescer. Aqui: 50 ativas, `floor(50*0.2)=10`,
    cap absoluto 5. Seis remocoes tem de barrar (10 passaria, 5 nao).
    """
    parceria = {f"act_p_{i}" for i in range(44)}
    ausentes = [inv(f"act_a_{i}", faltas=2) for i in range(6)]
    inventario = [inv(f"act_p_{i}") for i in range(44)] + ausentes

    plano = build_plan(
        partnership_ids=parceria,
        reachable_ids=parceria,
        inventory=inventario,
        complete=True,
        now=AGORA,
        threshold=3,
        max_removal_ratio=0.2,
        max_removal_abs=5,
    )

    assert plano.to_remove == []
    assert plano.blocked_reason is not None
    assert "teto 5" in plano.blocked_reason, (
        "o teto anunciado tem de ser o absoluto (5), nao o percentual (10) — se "
        "vier 10, o min() foi invertido e o cap absoluto virou decorativo"
    )

    # Contraprova: cinco remocoes cabem no mesmo teto, entao o guard nao esta
    # simplesmente barrando tudo.
    plano_ok = build_plan(
        partnership_ids=parceria,
        reachable_ids=parceria,
        inventory=[inv(f"act_p_{i}") for i in range(44)] + ausentes[:5],
        complete=True,
        now=AGORA,
        threshold=3,
        max_removal_ratio=0.2,
        max_removal_abs=5,
    )
    assert len(plano_ok.to_remove) == 5
    assert plano_ok.blocked_reason is None


def test_conta_nova_e_inalcancavel_sinaliza_no_mesmo_ciclo() -> None:
    """T3c: a conta que entra JA sem o SU atribuido precisa aparecer em
    `unreachable` na MESMA execucao em que entra.

    Sao as duas contas reais de producao (`CA - V4 Lima Soares`, `CHUTE 07`):
    estao na parceria, nunca entraram no inventario justamente por falta do SU.
    Com `unreachable` intersectando o inventario ativo (lido antes do upsert),
    o audit reportaria `unreachable: 0` no dia 1 — o unico dia em que o admin
    olharia. A §3 define o sinal como `in_partnership ∧ ¬reachable`, so isso.
    """
    plano = build_plan(
        partnership_ids={"act_nova_sem_su", "act_ja_dentro"},
        reachable_ids={"act_ja_dentro"},
        inventory=[inv("act_ja_dentro")],
        complete=True,
        now=AGORA,
    )

    assert plano.to_add == ["act_nova_sem_su"]
    assert plano.unreachable == ["act_nova_sem_su"]
    assert plano.to_remove == []


def test_retry_no_mesmo_dia_nao_soma_a_ausencia_ja_contada() -> None:
    """O `+1` virou condicional — e este e o caso em que isso decide a remocao.

    O C4 tornou `apply_absences` idempotente por dia, mas a DECISAO continuava
    somando `+1` por EXECUCAO. Num retry do mesmo dia a ausencia de hoje ja
    esta em `missed_syncs`, e o `+1` a contava de novo: na vespera do limiar o
    retry desativava a conta e REVOGAVA os grants dos gestores com dois dias de
    ausencia — neste lado, com `meta_reconcile_apply` ligada desde 05/09, era
    dano vivo.

    Tambem prende o F141 DENTRO da decisao: neste instante o dia da conta
    (02/09 em `America/Noronha`) nao e o dia UTC (03/09), entao comparar
    `last_missed_on` com o dia do servidor nao casaria e o `+1` voltaria.
    """
    hoje_na_conta = account_today("America/Noronha", now=AGORA)
    assert hoje_na_conta != AGORA.date(), "premissa: dia da conta != dia do servidor"

    ja_contada = InventoryRow(
        ad_account_id="act_2",
        is_active=True,
        missed_syncs=2,
        timezone_name="America/Noronha",
        last_missed_on=hoje_na_conta,
    )
    plano = build_plan(
        partnership_ids={"act_1"},
        reachable_ids={"act_1"},
        inventory=[inv("act_1"), ja_contada],
        complete=True,
        now=AGORA,
        threshold=3,
    )
    assert plano.to_remove == [], "a ausencia de hoje foi contada duas vezes"
    assert plano.to_bump == ["act_2"]


def test_ausencia_carimbada_em_outro_dia_continua_somando() -> None:
    """Contraparte obrigatoria: so o dia de HOJE suprime o `+1`.

    Sem esta, `if last_missed_on is not None: return missed_syncs` — ignorando
    a comparacao de data — passaria verde, e a carencia nunca mais avancaria:
    conta que saiu da parceria ficaria viva para sempre.
    """
    ontem = account_today("America/Noronha", now=AGORA) - timedelta(days=1)
    de_ontem = InventoryRow(
        ad_account_id="act_2",
        is_active=True,
        missed_syncs=2,
        timezone_name="America/Noronha",
        last_missed_on=ontem,
    )
    plano = build_plan(
        partnership_ids={"act_1"},
        reachable_ids={"act_1"},
        inventory=[inv("act_1"), de_ontem],
        complete=True,
        now=AGORA,
        threshold=3,
    )
    assert plano.to_remove == ["act_2"], "carencia parou de avancar em dia novo"
    assert plano.to_bump == []
