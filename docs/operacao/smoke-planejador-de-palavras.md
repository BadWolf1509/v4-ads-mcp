# Smoke — planejador de palavras-chave (plan_keyword_ideas / get_keyword_metrics)

Fonte: [§7 do desenho](../superpowers/specs/2026-10-29-planejador-de-palavras-design.md).

> **Roda em sessão NOVA, depois do merge e do deploy** (F140): tool nova só aparece para sessão
> aberta depois da reconexão, e o schema mostrado pode seguir velho — o smoke prova **chamando**.
> Preencha "medido" com o que a tool devolveu.

| Caso | Esperado | Medido |
|---|---|---|
| sementes "aluguel de andaime", "locação de equipamentos", João Pessoa | ~centenas a milhares de ideias antes do corte; "aluguel de andaime" com volume 40 (29/10) | |
| mesmo com `site` = mestredaobra.com.br | ideias com `origens` incluindo `site` e `volume_maximo`; resposta ecoa `customer_id`; `total_ideias` (contagem após a união, antes do `limit`) e `truncated`; falha de URL em `origens_com_falha` | |
| `get_keyword_metrics` com um termo inexistente | métricas `null`; em `sem_dado` se o Google o devolveu sem métricas, em `sem_resultado` se nem o devolveu (não medido) | |
| `get_keyword_metrics` com ["andaime", "andaimes"] | os dois com `volume_mensal`, nenhum em `sem_dado`/`sem_resultado`, um deles com `agrupado_em` | |
| `get_keyword_metrics`: termo com acento/variação ("locação de andaime" vs "locacao de andaime") | volta casado ao termo pedido (`agrupado_em` se entrou por variante), fora de `sem_dado`/`sem_resultado` (item aberto da revisão) | |
| cidade "Campina Grande" | resolve para City PB (`1001621`), não "Campina Grande do Sul" | |
| cidades João Pessoa + Campina Grande | `por_cidade` de "aluguel de andaime" ≈ {JP: 40, CG: 20} em `volume_mensal`, sem soma; toda cidade pedida presente, `null` onde a ideia não voltou | |
| mesma consulta em duas contas do gestor | mesmos termos e números (fato 9) | |

- [ ] `audit_log` com uma linha por chamada, conferido por `get_my_audit_log`: cidade não resolvida auditada como erro; `target_count` preenchido e `params_summary` com `total_ideias`/`origens_com_falha` (plan) e `sem_dado`/`sem_resultado` (metrics). **Não medido.**
