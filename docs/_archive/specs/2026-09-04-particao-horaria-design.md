# Partição horária por campanha — design

**Data:** 2026-09-04 · **Origem:** uso real na MO-JP durante o smoke 3b.42, discutido entre
a sessão do repo e a sessão de gestão de tráfego JP.

## O problema, em um número

A campanha JPA teve CPA de **18,47** na madrugada. A CAB, **24,46** na mesma faixa. Mesma
conta, mesma janela, direções opostas.

Hoje não existe forma de ver isso por uma tool curada:

- `get_hourly_performance` faz hora × dia da semana, mas é **conta inteira** — não aceita
  `campaign_ids`. O agregado esconde exatamente o que decide.
- `get_performance_breakdown` restringe `breakdown` a `level=account` ("só no v0", pelo
  próprio schema).
- `get_ad_schedule` devolve a grade, sem métrica nenhuma.

O único lugar do sistema onde CPA por faixa existe é **o preview do `update_ad_schedule`**,
que é a tool de escrita. Consequência medida: para responder "devo mudar a grade?" foi
preciso chamar a tool de mutação em dry-run, e o classificador de auto mode barrou até vir
aval humano. **Análise de grade está gated atrás de autorização de mutação.**

## A decisão de desenho: partição como default, grade crua sob flag

A tentação é devolver a grade dia × hora completa. Ela é errada por dois motivos, e o
segundo só apareceu porque quem usou relatou o que de fato queria.

**Cardinalidade.** 24 × 7 = **168 células por campanha**.

| Limite | Valor | Efeito |
|---|---|---|
| `default` do `limit` em `get_performance_breakdown` | 100 | **trunca antes de terminar UMA campanha** |
| teto de linhas do `run_gaql` | 1000 | 5 campanhas cabem, a 6ª trunca |
| payload observado por célula | ~120-300 chars | ~20 KB por campanha |

O defeito aparece com **uma** campanha, não com muitas. Uma tool que nasce truncando em uso
normal nasce com fama de quebrada.

**O que o operador realmente pediu.** Ninguém quis as 168 células. O que decidiu a conta
foram **três blocos**: comercial, fora de hora em dia útil, e fim de semana. A pergunta que
faz alguém abrir a tool é "comercial contra fora de hora contra fim de semana", não "o que
aconteceu às 3h de terça".

Devolver a **partição** responde a pergunta real e mata a cardinalidade de uma vez: **3
linhas por campanha em vez de 168**. Quinze campanhas viram 45 linhas.

**Portanto:** partição é o default, com os blocos parametrizáveis. Grade crua só sob flag
explícita, com `campaign_ids` obrigatório e pequeno, e com o teto elevado para pelo menos
`168 × nº de campanhas pedidas` — senão a sentinela dispara em uso normal.

## Escopo

**Dentro:**

1. `get_performance_breakdown` aceita `level=campaign` + `breakdown=hourly`, devolvendo
   partição por default.
2. `get_ad_schedule` ganha a partição dia × hora **opt-in por flag**, reusando
   `partition_metrics`, `covers` e `day_hour_metrics_query`, que já existem em
   `src/google_ads/ad_schedule.py` e são puros. É fiação, não desenho novo.

Teto e sentinela de truncamento em ambos — família F98.

**Fora, declarado:**

- **Geo por cidade.** É regra de merge com risco próprio, não mudança de nível. Medido
  nesta conta: o mesmo município aparece com dois `geoTargetConstant`, e **o canônico não
  colapsa** — `Bayeux,State of Paraiba,Brazil` contra `Bayeux,Bayeux,State of Paraiba,Brazil`
  (ids `1031477` e `9074272`); `Goiana` idem (`1031648` e `9074147`). Ambos com
  `target_type: City`. Fundir por nome é pior ainda: há dezenas de municípios homônimos em
  estados diferentes no Brasil. **A regra é não fundir sem prova e expor o id.**
- **Métrica pendurada em janela existente.** Não resolve caso nenhum enquanto as contas
  estiverem em `has_schedule: false` — não há janela onde pendurar CPA.
- **`aggregate_by` somando** (`run_gaql`). Sprint próprio: carrega a regra de que **razão
  nunca se soma** (média de médias). `ctr`, `cpc` e qualquer razão futura precisam ser
  recomputados a partir das somas ou recusados — pela **forma** do campo, não pelo nome.

## Limitação do Google, documentar na descrição

`segments.hour` é incompatível com `geographic_view` **e** com `user_location_view`. Probado
via `validate_gaql`, `code: QUERY_ERROR`. Texto do Google, verbatim:

> Cannot select or filter on the following segments: 'segments.hour'(could not support
> requested resources: 'GEOGRAPHIC_VIEW'), since segment is incompatible with the resource in
> the FROM clause or other selected segmenting resources.

Idêntico trocando para `'USER_LOCATION_VIEW'`. **Cidade × hora não existe na GAQL.** Ao citar
na descrição, use só esta parte: o restante da string devolvida é hint nosso, do wrapper, e
citá-lo como se fosse do Google seria falso.

Relacionado, e é a limitação por trás do item do `aggregate_by`: segmento usado no `WHERE`
precisa estar no `SELECT` (`segments.date` é a exceção).

> The following fields must be present in SELECT clause: 'segments.hour',
> 'segments.day_of_week'.

## Ordem

Depois do **F148**, que é o único item da fila que faz a trilha de auditoria responder
**errado** em vez de não responder.
