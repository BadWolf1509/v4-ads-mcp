# Sessão 2026-09-30 a 10-02 — Handoff (revogação, dia 1, uso real, conversões e parcela)

> Mapa da sessão. Estado vivo no [`estado-atual`](estado-atual.md); defeitos no
> [catálogo](findings-catalog.md). Anterior: [`session-2026-09-29-handoff.md`](session-2026-09-29-handoff.md).

## O que entrou

| PR / branch | o quê | produção |
|---|---|---|
| #140 | F200 verificado; F203 e F202 no ar | docs |
| #141 | teste do `detect_drift` com data fixa (quebrou sozinho em 02/10: a janela 01–02/09 saiu da retenção de 30 dias) + docs do fechamento de 01/10 | `00142-fcx` |
| `spec/conversoes-e-parcela` | spec, 4 tasks, plano gerado dos commits | **sem push** — em revisão |

## O que foi medido

- **01/10:** as 4 contas Meta desativadas e os 16 grants revogados no job; smoke do dia 1 ok
  (`THIS_MONTH` = 01/10–01/10 com dados; pacing com projeção `null`, também no bloco do orçamento
  compartilhado). O smoke do dia 1 só vale até a meia-noite **do fuso da conta** — foi feito às 22h.
- **30/09 02:22 UTC:** a 1ª queda real de conexão pega pelo pool validado (F200), health 200.
- **Uso de 30 dias:** `run_gaql` = 38% das chamadas; o Pedro roda ~38 GAQL cruas por sessão, o
  roteiro que o skill do plugin prescreve.
- **Para a frente nova (02/10, MO-JP):** recorte por ação recusa custo; `conversions` por ação
  segue `include_in_conversions_metric` (a nota do plugin estava errada); "Conversation started"
  não existe no recurso `conversion_action`; parcela de impressão: 5 campos em `campaign`, 3 em
  `customer`; campo `optional` ausente no proto (campanha não-search ou sem impressão) — ler o
  atributo direto daria `0.0`.

## Método

- Código antes do plano, uma task por commit, plano gerado dos commits e reaplicado num worktree
  limpo: árvore idêntica (4ª vez do método). Revisões por par de tasks em paralelo + final (Opus).
- A revisão das tasks 3-4 pegou o padrão F191 num formatter que nenhum teste exercitava: os testes
  mockavam o `run_report` inteiro, então `bool(campo_optional)` nunca rodou.

## Pendente

- A rodada de correção da frente nova e o deploy — o ledger
  `.superpowers/sdd/2026-10-02-conversoes-e-parcela-de-impressao/progress.md` diz tudo.
- Texto do plugin 0.5.0 (na mesma pasta) para o Wellington aplicar depois do deploy.
- **04/10:** buckets e Fase 2B por gestor.

## Lições operacionais

- O Controle de Aplicativos do Windows passou a bloquear o `mypy` compilado do Python global: o
  gate roda com `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py`.
- Teste com data fixa contra recurso de retenção móvel é bomba-relógio: congele o relógio.
