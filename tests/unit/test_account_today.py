"""F141: os presets de data resolviam em UTC, e nenhuma das 25 contas esta em UTC.

Medido em 2026-09-02 na conta 786-223-0676 (`America/Fortaleza`, UTC-3):
`date_range="TODAY"` resolveu `period` para **2026-09-03** quando na conta
ainda era 02/09. `_today()` era `datetime.now(UTC).date()`, e o Google le
predicado de data no fuso da CONTA. As 25 contas do MCC estao em cinco fusos
(UTC-3 e UTC-4) — nao existe conta para a qual o calculo estivesse certo.

Das 21:00 a meia-noite locais (20:00 nas duas contas UTC-4), todo dia:
`TODAY` devolvia vazio em silencio, `YESTERDAY` devolvia o dia parcial, e a
familia `LAST_N_DAYS` deslizava um dia — entrava o parcial de hoje, saia o dia
inteiro mais antigo. Essa ultima e a pior por parecer certa.

## Por que nenhum teste pegava

Os testes congelavam o relogio com `freezegun`. Sob relogio congelado a data
UTC e a data da conta sao a mesma coisa — **a diferenca que constitui o bug
nao era representavel no fixture**. Por isso o desenho do fix e:

- `account_today(time_zone, *, now)` e PURA e recebe o instante. O teste
  injeta um `now` em que UTC e a conta discordam. Sem `freezegun`.
- `parse_date_range`/`resolve_date_window` recebem `today` como kwarg
  **obrigatorio**. Sem default: um call-site que esquecer quebra no mypy e no
  import, em vez de cair calado no comportamento antigo. O guard e a
  assinatura, nao um grep.
"""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime

from src.google_ads.queries._common import (
    account_today,
    parse_date_range,
    resolve_date_window,
)

# O instante do bug: 00:30 UTC de 03/09 — na conta (UTC-3) ainda sao 21:30 de 02/09.
INSTANTE_DO_BUG = datetime(2026, 9, 3, 0, 30, tzinfo=UTC)


# --- account_today: o unico lugar que sabe de fuso -----------------------------


def test_fortaleza_ainda_e_ontem_quando_utc_ja_virou() -> None:
    """O caso medido: UTC diz 03/09, a conta diz 02/09."""
    assert account_today("America/Fortaleza", now=INSTANTE_DO_BUG) == date(2026, 9, 2)


def test_campo_grande_utc_menos_4_tambem_e_ontem() -> None:
    """As duas contas UTC-4 (Campo Grande, Boa Vista) viram uma hora depois."""
    assert account_today("America/Campo_Grande", now=INSTANTE_DO_BUG) == date(2026, 9, 2)


def test_de_dia_utc_e_conta_concordam() -> None:
    """Fora da janela 21h-0h o bug nao aparece — e o fix nao pode inventar deslize."""
    meio_dia = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    assert account_today("America/Fortaleza", now=meio_dia) == date(2026, 9, 3)


def test_fuso_ausente_cai_em_utc_sem_estourar() -> None:
    """Decisao registrada: `None` -> UTC + log. Conta sem sync nao passa no gate."""
    assert account_today(None, now=INSTANTE_DO_BUG) == date(2026, 9, 3)


def test_fuso_desconhecido_cai_em_utc_sem_estourar() -> None:
    """Chave invalida no inventario nao pode derrubar 22 tools."""
    assert account_today("Nao/Existe", now=INSTANTE_DO_BUG) == date(2026, 9, 3)


# --- parse_date_range / resolve_date_window: `today` vem de fora ---------------


def test_today_resolve_para_o_dia_que_o_chamador_disse() -> None:
    hoje = date(2026, 9, 2)
    assert parse_date_range("TODAY", today=hoje) == (hoje, hoje)


def test_last_7_days_termina_no_ontem_do_chamador() -> None:
    """A familia LAST_N_DAYS: com `today` certo, o dia parcial fica de fora."""
    start, end = parse_date_range("LAST_7_DAYS", today=date(2026, 9, 2))
    assert end == date(2026, 9, 1)
    assert start == date(2026, 8, 26)


def _sem_default(fn, nome: str) -> bool:
    p = inspect.signature(fn).parameters[nome]
    return p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is inspect.Parameter.empty


def test_resolve_date_window_exige_today() -> None:
    """Sem default. O call-site que esquecer quebra alto (mypy + TypeError), nao cai em UTC calado.

    Asserido pela ASSINATURA, nao por `pytest.raises(TypeError)`: com um default
    `None`, `today - timedelta` levanta TypeError pelo motivo ERRADO e o teste
    ficaria verde — foi exatamente o que a sabotagem (b) mostrou. Tipo de excecao
    e o adjacente da invariante; a invariante e "nao ha default".
    """
    assert _sem_default(resolve_date_window, "today")


def test_parse_date_range_exige_today() -> None:
    assert _sem_default(parse_date_range, "today")


def test_janela_explicita_ignora_today() -> None:
    """start/end custom nao dependem do relogio — `today` e obrigatorio mas inerte."""
    start, end = resolve_date_window(
        date_range=None,
        start_date="2026-08-06",
        end_date="2026-09-01",
        today=date(2026, 9, 2),
    )
    assert (start, end) == (date(2026, 8, 6), date(2026, 9, 1))
