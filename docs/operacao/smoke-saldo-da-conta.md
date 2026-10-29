# Smoke — saldo da conta (get_account_balance / meta_get_account_balance)

Fonte: [§5 do desenho](../superpowers/specs/2026-10-28-saldo-da-conta-design.md).

> **Roda em sessão NOVA, depois do merge e do deploy** (F140): tool nova só aparece para sessão
> aberta depois da reconexão, e o schema mostrado pode seguir velho — o smoke prova **chamando**.
> A Hosp Ocular é comparada com a tela de Faturamento do dia. Preencha "medido" com o que a tool devolveu.

| Conta | Plataforma | Esperado | Medido |
|---|---|---|---|
| Hosp Ocular | Google | `restante_brl` = "Fundos disponíveis" da tela de Faturamento no dia | 29/10: `restante_brl` 313,22 (limite 34.782,19 − gasto 34.468,97), `acabando`, 6,4 dias, média 7d 49,23 — igual ao "Fundos disponíveis" da tela de 28/10; a tela do dia 29 não foi conferida |
| Cantina | Google | `esgotada` | 29/10: `esgotada`, restante 0,85 |
| MDO JP | Google | `sem_teto` | 29/10: `sem_teto`, números `null` |
| Cantina | Meta | `trava_primeiro: limite_de_gastos`; saldo = texto do Gerenciador | 29/10, **depois do #165**: saldo 631,96 (do texto), limite 555,18, `trava_primeiro: limite_de_gastos`, `restante_brl` 555,18, `com_saldo`, 15,9 dias |
| 3 Lagoas | Meta | `esgotada` | 29/10, **depois do #165**: `esgotada`, "sem saldo restante" |
| Mi importss Resv | Meta | `sem_teto` + aviso de pagamento pendente, `a_faturar_brl` preenchido | 29/10: `sem_teto`, `PAGAMENTO_PENDENTE` com aviso, `a_faturar_brl` 1.218,58 |

**Antes do #165**, as duas contas Meta pré-pagas saíram `indeterminada` ("saldo pré-pago ilegível"): a Graph
manda U+00A0 antes de `BRL`, e as fixtures tinham sido transcritas da saída impressa da sondagem, que o mostra
como espaço. O smoke foi o primeiro a ver.

- [ ] Gestor comum, se houver um ativo: chamar as duas tools numa conta que ele alcança e uma que não alcança (esperado: recusa do gate de acesso). **Não medido** (29/10): nenhum outro gestor na sessão.
- [ ] `audit_log` com uma linha por chamada. **Não medido** (29/10).
