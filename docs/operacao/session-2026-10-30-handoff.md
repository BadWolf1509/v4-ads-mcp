# Sessão 2026-10-28 a 10-30 — Handoff (saldo da conta, planejador de palavras-chave, F110, rótulos Meta)

> Mapa da sessão. Estado vivo no [`estado-atual`](estado-atual.md); defeitos no
> [catálogo](findings-catalog.md). Anterior: [`session-2026-10-06-handoff.md`](session-2026-10-06-handoff.md).

## O que entrou

| PR | o quê | produção |
|---|---|---|
| #162 | os 5 bumps do Dependabot de 11/10 num PR (fecharam os #157–#161) | deploy ✅ |
| #163, #164 | desenho e tools de **saldo da conta**: `get_account_balance` (Google) e `meta_get_account_balance` (Meta) | deploy ✅ (`00150-2fs` com o #165) |
| #165 | saldo pré-pago Meta com U+00A0 antes de "BRL" — o smoke pegou | deploy ✅ |
| #166 | fecho do saldo (70 tools, smoke medido) | docs |
| #167 | **planejador de palavras-chave**: `plan_keyword_ideas` e `get_keyword_metrics`, executor `run_keyword_planning` | deploy ✅ (`00151-qk7`) |
| #168 | fecho do planejador (72 tools, smoke medido, fato 9 ajustado) | docs |
| #169 | F110 fora do planejador: `customer_match` e `conversions` diziam "Erro inesperado" na quota esgotada | deploy ✅ |
| #170 | `provider_request_id` do planejador (interceptor ausente + `""` no lugar de `None`); decisão do alerta de saldo | deploy ✅ |
| #171 | [guia do gestor para o alerta de saldo](guia-alerta-de-saldo.md) | docs |
| #172 | rótulos de `account_status` corrigidos pela referência da Meta + `disable_reason_label` | deploy ✅ (nome da revisão não medido: `gcloud` sem credencial em 30/10) |

## Decisões do Wellington

- **Saldo:** uma conta por chamada (sem varredura), Google e Meta juntos, ritmo pela média de 7 dias,
  data de fim do orçamento conta como freio, saldo Meta ilegível → `indeterminada`.
- **Alerta de saldo (30/10): não há job central** — cada gestor monta a própria automação sobre as tools
  de saldo ([guia](guia-alerta-de-saldo.md)).
- **Planejador:** conta nova é o caso principal; entradas site + sementes + cidades + concorrentes; roda
  numa conta que o gestor já alcança, sem exceção no gate (medido: a conta não muda o resultado);
  volume **por cidade**, sem soma; previsão de orçamento fica para a próxima frente.
- `ads_get_field_context` não rodou (MCP oficial da Meta indisponível); a evidência ao vivo foi aceita.

## O que foi medido

- **Saldo Google:** `adjusted_spending_limit − amount_served` bate ao centavo com "Fundos disponíveis"
  (Hosp Ocular, R$ 313,22); o `approved` daria R$ 152.
- **Saldo Meta:** dois freios (saldo pré-pago só em texto; `spend_cap`); a Graph manda **U+00A0** antes de
  "BRL" — fixture copiada da saída impressa escondeu isso até o smoke.
- **Planejador:** volume em degraus; só sementes = 1.923 ideias, **URL sozinha = 964 (off-topic no topo)**,
  sementes + URL juntas = 40; cidades numa chamada não fecham (JP 40 + CG 20 = 50); a conta não muda termos
  nem volumes, o CPC varia em centavos entre chamadas; "sem dado" vem **sem o bloco** de métricas.
- **Estados BR no Google:** 25 seguem "State of X"; CE = "Ceara", DF = "Federal District".
- **Request-id:** a mesma chamada devolve `None` sem o interceptor e o id real com ele.

## Método

- Saldo e planejador: brainstorming em menu → spec com fatos medidos → builder check → plano → SDD (7 tasks
  cada, revisão por task, revisão final Opus, uma onda de correção revisada) → smoke em sessão nova.
- As revisões pegaram antes do merge: fato medido com a forma errada de chamada (URL), `QuotaExhausted`
  virando "Erro inesperado", cidade não resolvida auditada como sucesso, paginação fora da quota,
  `close_variants` ignorado (singular/plural caía em "sem dado").

## Pendente

- **`ads_get_field_context`** nos 9 fields de `GET /act_<id>` quando o MCP oficial da Meta estiver na sessão.
- **Previsão de orçamento no planejador** (`generate_keyword_forecast_metrics`) — próxima frente grande.
- **Findings para o catálogo** (o `/findings-add` é do Wellington): textos prontos na lista abaixo.
- Bordas deixadas por decisão: paginação do planejador estimada (2 páginas por chamada), `agrupado_em`
  com várias cidades, sazonalidade com mais de 12 meses.

### Textos prontos para `/findings-add`

1. **(MEDIUM, corrigido 30/10, #172)** `META_ACCOUNT_STATUS_LABELS` divergia da referência da Meta:
   102 inexistente, 201/202 com o significado de 100/8, sem 8, 9 e 100 — conta em fechamento ou em carência
   saía sem rótulo em `meta_list_my_ad_accounts`, overview, painel e saldo. Fora: nenhum guard compara a
   tabela com a API (a fonte é a página de referência, lida à mão).
2. **(MEDIUM, corrigido 30/10, #169)** F110 fora do planejador: `customer_match.run_offline_user_data_job`
   e `conversions.run_conversion_upload` passavam `QuotaExhausted` pelo `to_friendly` — "Erro inesperado"
   sem dizer qual cota. Um teste antigo travava o comportamento errado. Fora: guard estrutural "nenhum
   executor passa `QuotaExhausted` pelo `to_friendly`".
3. **(MEDIUM, corrigido 29/10, #165)** saldo pré-pago Meta ilegível em produção: U+00A0 antes de "BRL";
   fixtures transcritas da saída impressa da sondagem (que mostra o U+00A0 como espaço) passavam.
4. **(LOW, corrigido 30/10, #170)** `provider_request_id` `""` no planejador: serviços sem
   `get_capture_interceptor()` e `None` trocado por `""` no executor.
