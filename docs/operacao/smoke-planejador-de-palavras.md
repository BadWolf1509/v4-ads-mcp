# Smoke — planejador de palavras-chave (plan_keyword_ideas / get_keyword_metrics)

Fonte: [§7 do desenho](../superpowers/specs/2026-10-29-planejador-de-palavras-design.md).

> **Roda em sessão NOVA, depois do merge e do deploy** (F140): tool nova só aparece para sessão
> aberta depois da reconexão, e o schema mostrado pode seguir velho — o smoke prova **chamando**.
> Preencha "medido" com o que a tool devolveu.

| Caso | Esperado | Medido |
|---|---|---|
| sementes "aluguel de andaime", "locação de equipamentos", João Pessoa | ~centenas a milhares de ideias antes do corte; "aluguel de andaime" com volume 40 (29/10) | |
| mesmo com `site` = mestredaobra.com.br | ideias com `origens` incluindo `site` | |
| `get_keyword_metrics` com um termo inexistente | métricas `null`, termo em `sem_dado` | |
| `get_keyword_metrics`: termo com acento/variação ("locação de andaime" vs "locacao de andaime") | volta casado ao termo pedido, não em `sem_dado` (item aberto da revisão) | |
| cidade "Campina Grande" | resolve para City PB (`1001621`), não "Campina Grande do Sul" | |
| cidades João Pessoa + Campina Grande | `volume_por_cidade` de "aluguel de andaime" ≈ {JP: 40, CG: 20}, sem soma | |
| mesma consulta em duas contas do gestor | mesmos termos e números (fato 9) | |

- [ ] `audit_log` com uma linha por chamada, conferido por `get_my_audit_log` (cidade não resolvida auditada como erro). **Não medido.**
