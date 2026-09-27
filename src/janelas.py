"""A janela de cada preset de data — uma regra só para o Google e a Meta (F195).

Mora na raiz de `src/` pela mesma razão que `clock.py`: é primitivo neutro. O Google
(`google_ads.queries._common.parse_date_range`) e a Meta
(`meta_ads.account_overview.resolve_meta_date_window`) tinham cada um a sua conta, e elas
divergiram: o `LAST_N_DAYS` Meta terminava HOJE, com o dia corrente pela metade dentro,
e o do Google terminava ontem. Mesmo nome de preset, janelas deslocadas de um dia — e no
comparativo do overview Meta o sinal da variação invertia (medido em 27/09 na MI Imports:
gasto −19,6% onde os 7 dias cheios davam +1,14%).

A regra aqui é a das duas plataformas: `LAST_N_DAYS` são os N dias COMPLETOS até ontem.
Sondado na Graph API em 27/09 (Cheiro | Conta 01, fuso da conta): `date_preset=last_7d`
devolveu 20/09–26/09 e `last_30d`, 28/08–26/09. Só `TODAY` e os presets "deste período"
(`THIS_MONTH`, `THIS_WEEK`) tocam o dia corrente.

O corpo dos presets veio sem mudança de `parse_date_range`: o lado Google não muda.
Puro: `today` vem do chamador, já no fuso da conta (F141) — sem default de propósito.
"""

from __future__ import annotations

from datetime import date, timedelta

PRESETS = frozenset(
    {
        "TODAY",
        "YESTERDAY",
        "LAST_7_DAYS",
        "LAST_14_DAYS",
        "LAST_30_DAYS",
        "LAST_90_DAYS",
        "THIS_MONTH",
        "LAST_MONTH",
        "THIS_WEEK",
        "LAST_WEEK",
    }
)

_ULTIMOS_N_DIAS = {"LAST_7_DAYS": 7, "LAST_14_DAYS": 14, "LAST_30_DAYS": 30, "LAST_90_DAYS": 90}


def janela_do_preset(preset: str, *, today: date) -> tuple[date, date]:
    """(início, fim) inclusivos do preset, relativos a `today` no fuso da conta."""
    yesterday = today - timedelta(days=1)

    if preset == "TODAY":
        return today, today
    if preset == "YESTERDAY":
        return yesterday, yesterday
    if preset in _ULTIMOS_N_DIAS:
        return yesterday - timedelta(days=_ULTIMOS_N_DIAS[preset] - 1), yesterday
    if preset == "THIS_MONTH":
        return today.replace(day=1), yesterday
    if preset == "LAST_MONTH":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return first_prev, last_prev
    if preset == "THIS_WEEK":
        # ISO week starts Monday; today.weekday() = 0 for Monday
        monday = today - timedelta(days=today.weekday())
        return monday, yesterday if yesterday >= monday else monday
    if preset == "LAST_WEEK":
        last_sunday = today - timedelta(days=today.weekday() + 1)
        last_monday = last_sunday - timedelta(days=6)
        return last_monday, last_sunday

    raise ValueError(
        f"preset de data desconhecido: {preset!r}. Validos: {', '.join(sorted(PRESETS))}"
    )
