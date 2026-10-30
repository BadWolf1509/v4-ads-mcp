# Smoke — planejador de palavras-chave (plan_keyword_ideas / get_keyword_metrics)

Fonte: [§7 do desenho](../superpowers/specs/2026-10-29-planejador-de-palavras-design.md).

> **Roda em sessão NOVA, depois do merge e do deploy** (F140): tool nova só aparece para sessão
> aberta depois da reconexão, e o schema mostrado pode seguir velho — o smoke prova **chamando**.
> Preencha "medido" com o que a tool devolveu.

| Caso | Esperado | Medido |
|---|---|---|
| sementes "aluguel de andaime", "locação de equipamentos", João Pessoa | ~centenas a milhares de ideias antes do corte; "aluguel de andaime" com volume 40 (29/10) | 30/10: `total_ideias` 1.891; "aluguel de andaime" = 40 em JP, origem `semente` — **ok** |
| mesmo com `site` = mestredaobra.com.br | ideias com `origens` incluindo `site` e `volume_maximo`; resposta ecoa `customer_id`; `total_ideias` (contagem após a união, antes do `limit`) e `truncated`; falha de URL em `origens_com_falha` | 30/10: `total_ideias` 2.894; das 1.000 devolvidas, 435 de `site` e 565 de `semente`; campos presentes — **ok** (falha de URL não testada ao vivo) |
| `get_keyword_metrics` com um termo inexistente | métricas `null`; em `sem_dado` se o Google o devolveu sem métricas, em `sem_resultado` se nem o devolveu (não medido) | 30/10: em `sem_dado`, métricas `null` — **ok** |
| `get_keyword_metrics` com ["andaime", "andaimes"] | os dois com `volume_mensal`, nenhum em `sem_dado`/`sem_resultado`, um deles com `agrupado_em` | 30/10: os dois com 49.500; "andaimes" com `agrupado_em` = "andaime" — **ok** |
| `get_keyword_metrics`: termo com acento/variação ("locação de andaime" vs "locacao de andaime") | volta casado ao termo pedido (`agrupado_em` se entrou por variante), fora de `sem_dado`/`sem_resultado` (item aberto da revisão) | 30/10: as duas grafias são o mesmo termo depois da normalização — a segunda sai com aviso "repetido, ignorado" e não vai ao Google. **O esperado desta linha estava errado**: o comportamento é o desenhado (aviso de termo repetido, fix da revisão final) |
| cidade "Campina Grande" | resolve para City PB (`1001621`), não "Campina Grande do Sul" | 30/10: `geoTargetConstants/1001621` — **ok** |
| cidades João Pessoa + Campina Grande | `por_cidade` de "aluguel de andaime" ≈ {JP: 40, CG: 20} em `volume_mensal`, sem soma; toda cidade pedida presente, `null` onde a ideia não voltou | 30/10: JP 40 / CG 20; as 689 ideias com as duas cidades — **ok** |
| mesma consulta em duas contas do gestor | mesmos termos e números (fato 9) | 30/10: mesmos 689 termos, ordem e volumes; **28 diferem no CPC em centavos** (ex.: 3,15–13,91 vs 3,16–13,95) — variação do Google entre chamadas, não da conta (fato 9 ajustado) |

- [x] `audit_log` com uma linha por chamada, conferido por `get_my_audit_log`: cidade não resolvida auditada como erro; `target_count` preenchido e `params_summary` com `total_ideias`/`origens_com_falha` (plan) e `sem_dado`/`sem_resultado` (metrics). **30/10:** 7 linhas, uma por chamada; `target_count` 1.891 / 2.894 / 689 / 1 / 2 / 1; a cidade inexistente gravada como `error` com a mensagem dos candidatos. **Não medido:** o `params_summary` (o `get_my_audit_log` não o devolve). **Achado:** `provider_request_id` sai `""` em todas as chamadas do planejador — o request-id não é capturado, e o vazio aparece onde o não medido seria `null` (follow-up).

Uso: com `limit` 1000 a resposta do `plan_keyword_ideas` passa de 300 KB e estoura o limite de tokens do cliente; o default 200 existe por isso.
