# Smoke — saldo da conta (get_account_balance / meta_get_account_balance)

Fonte: [§5 do desenho](../superpowers/specs/2026-10-28-saldo-da-conta-design.md).

> **Roda em sessão NOVA, depois do merge e do deploy** (F140): tool nova só aparece para sessão
> aberta depois da reconexão, e o schema mostrado pode seguir velho — o smoke prova **chamando**.
> A Hosp Ocular é comparada com a tela de Faturamento do dia. Preencha "medido" com o que a tool devolveu.

| Conta | Plataforma | Esperado | Medido |
|---|---|---|---|
| Hosp Ocular | Google | `restante_brl` = "Fundos disponíveis" da tela de Faturamento no dia | |
| Cantina | Google | `esgotada` | |
| MDO JP | Google | `sem_teto` | |
| Cantina | Meta | `trava_primeiro: limite_de_gastos`; saldo = texto do Gerenciador | |
| 3 Lagoas | Meta | `esgotada` | |
| Mi importss Resv | Meta | `sem_teto` + aviso de pagamento pendente, `a_faturar_brl` preenchido | |

- [ ] Gestor comum, se houver um ativo: chamar as duas tools numa conta que ele alcança e uma que não alcança (esperado: recusa do gate de acesso). Medido:
- [ ] `audit_log` com uma linha por chamada.
