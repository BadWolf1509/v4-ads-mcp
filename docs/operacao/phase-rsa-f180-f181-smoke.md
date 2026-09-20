# Smoke — F180 (lote parcial de RSA) + F181 (pre-flight de variação de experimento)

> 🔴🔴 **ESTE SMOKE MUTA CONTA REAL DE CLIENTE — LEIA ANTES DE EXECUTAR QUALQUER PASSO.**
> T4 e T5 alteram `final_urls` de anúncios que estão **servindo** na MO-JP. **O gestor
> precisa autorizar CADA rodada de mutação NA PRÓPRIA SESSÃO QUE EXECUTA** — aval relayado
> por outra sessão Claude **não passa** no classificador de auto mode. Isso foi **medido em
> 04/09** (`phase-3b-42-ad-schedule-smoke.md`): T2b (conta de cliente) e T3 (conta de teste,
> campanha PAUSED, **dry-run**) foram recusados **de forma idêntica**, e os dois só passaram
> depois de o Wellington autorizar **com as próprias palavras**, na sessão que executava.
> **Nem dry-run nem conta de teste isentam.** Não agende isto sem o gestor presente.

> ⚠️ **RODE NUMA SESSÃO ABERTA DEPOIS DO DEPLOY.** O catálogo de tools é negociado no
> handshake do MCP (F140), então uma sessão já aberta continua com a **descrição antiga** do
> `update_rsa` enquanto o servidor já tem o **comportamento novo**. O sintoma é traiçoeiro
> aqui: a descrição velha diz que o pre-flight rejeita só quatro coisas, e a variação passa
> a ser recusada mesmo assim — parece bug do servidor, é skew de handshake. Reconecte antes
> de começar. (O mesmo efeito foi observado em 19/09 no `empsis-mcp` após deploy: servidor
> respondendo o formato novo e recusando parâmetros novos na sessão velha.)

> 🔁 **A ORDEM AQUI É INVERTIDA, e de propósito.** As tools deste smoke são servidas pelo
> Cloud Run de **produção** — não existe instância local no caminho. Logo **não dá para
> testar a branch**: o roteiro só exerce o código novo **depois** de `merge na main → CI →
> deploy`. A sequência é **merge → deploy → reconectar → smoke → fix-forward**, e o caminho
> de volta, se algum caso reprovar, é rollback da revisão do Cloud Run (capture a revisão
> que está servindo **antes** do deploy — F116).

**Branch:** `fix/rsa-lote-parcial-e-preflight-de-variacao` · **HEAD ao escrever:** `ff78792`
(confira com `git rev-parse HEAD`). Commits: `git log --oneline main..HEAD`.

**Conta:** MO-JP `7862230676` — é onde F180 e F181 foram medidos.
**Par base + variação vivo:** ad_group `204135195030` (CONTAINER), base `825140457725`,
variação `825281476311`, experimento `10061636855` (`AD_VARIATION`, ativo até 2026-11-14).

---

## Setup — capture o estado ANTES (obrigatório, não pule)

T4 e T5 trocam `final_urls`. Sem os valores originais em mãos, não há restauração possível
— e fechar sprint de tool mutante com a restauração pendente é o F151.

```
run_gaql(customer_id="7862230676", query="
  SELECT ad_group_ad.ad.id, ad_group_ad.ad.final_urls, ad_group_ad.status,
         ad_group_ad.ad.system_managed_resource_source, ad_group.id
  FROM ad_group_ad
  WHERE ad_group.id = 204135195030 AND ad_group_ad.status != 'REMOVED'")
```

- [ ] **Cole a saída inteira no final deste arquivo, na seção "Estado capturado".** É dela
      que sai a restauração.
- [ ] Confirme que a variação ainda traz `AD_VARIATIONS` e o base não traz o campo. Se o
      experimento tiver terminado, T1/T3 não têm alvo — escolha outro par ou encerre aqui.

---

## Os casos

| # | Cenário | Muta? | Esperado |
|---|---|---|---|
| **T1** | Variação recusada no pre-flight | ❌ não | Erro nomeando a variação **e o anúncio base**, sem token |
| **T2** | Anúncio comum passa no dry-run | ❌ não | Token emitido, preview correto — **NÃO aplicar** |
| **T3** | Lote misto é barrado inteiro | ❌ não | Mesmo erro do T1; nenhum token para nenhum dos 3 |
| **T4** | Lote parcial de verdade (F180) | ✅ **sim** | `applied_count: 1`, `failed_count: 1`, motivo por linha |
| **T5** | Caminho feliz ponta a ponta | ✅ **sim** | `applied_count: 2`, `failed_count: 0` |

### T1 — a recusa que teria poupado as horas (F181)

```
update_rsa(customer_id="7862230676",
           updates=[{"ad_id": "825281476311", "final_urls": ["https://exemplo.invalido/"]}])
```

- [ ] Devolve **erro**, não `dry_run`. Nenhum `confirmation_token` no envelope.
- [ ] A mensagem contém `825281476311` (a variação) **e `825140457725`** (o base).
- [ ] A mensagem avisa que reler a variação cedo demais devolve o estado antigo sem erro.

🔑 **Se o base NÃO for nomeado** e a mensagem cair no genérico (“o RSA que não é variação”),
não é falha: significa que o grupo tem zero ou 2+ RSAs não-variação e a tool recusou-se a
chutar. Confira contra o Setup quantos não-variação existem. **Nomear o anúncio errado seria
pior que não nomear** — é o caso que o teste `test_sem_base_unico_a_mensagem_nao_inventa_id`
cobre.

### T2 — o controle: anúncio comum não foi confundido

```
update_rsa(customer_id="7862230676",
           updates=[{"ad_id": "825140457725", "final_urls": [<a URL ATUAL do Setup>]}])
```

- [ ] Devolve `dry_run` com `confirmation_token`.
- [ ] **NÃO chame `apply_change`.** Deixe o token expirar (10 min).

Sem este caso, um pre-flight que recusasse TUDO passaria no T1.

### T3 — o lote misto é barrado antes de existir

```
update_rsa(customer_id="7862230676", updates=[
  {"ad_id": "825140457725", "final_urls": [<URL atual>]},
  {"ad_id": "<outro RSA comum do Setup>", "final_urls": [<URL atual dele>]},
  {"ad_id": "825281476311", "final_urls": ["https://exemplo.invalido/"]}])
```

- [ ] Devolve **erro**, sem token. O pre-flight é first-found-offender: basta um inválido
      para o lote inteiro não nascer.
- [ ] 🔑 **Se isto emitir token, o F181 falhou** — e o T4 vira o teste do F180 sozinho.

### T4 — a aplicação parcial de verdade (F180) ✅ MUTA

**É o único caso que prova o F180 em produção, e exige coordenação manual.**

1. - [ ] Monte um lote de **2 RSAs comuns** (do Setup), trocando `final_urls` por um valor
        novo e válido. Guarde o token.
2. - [ ] **Antes de aplicar**, remova **um** dos dois anúncios pela UI do Google Ads.
3. - [ ] `apply_change(confirmation_token=<token>)`.

- [ ] `applied_count: 1` e `failed_count: 1`.
- [ ] `partial_failures` traz o índice e o **motivo** da linha que falhou.
- [ ] `run_gaql` confirma: o anúncio sobrevivente tem a URL nova.

🔑 **Antes deste fix, o resultado esperado seria `status: error` e os DOIS intactos.** Se for
isso que acontecer, a flag não chegou ao Google — confira se a sessão foi aberta depois do
deploy (F140).

### T5 — caminho feliz ponta a ponta ✅ MUTA

```
update_rsa → 2 RSAs comuns, URLs novas → apply_change
```

- [ ] `applied_count: 2`, `failed_count: 0`, `partial_failures: []`.
- [ ] `run_gaql` confirma os dois com a URL nova.
- [ ] Os dois voltam a `approval_status` / `review_status` de revisão — **esperado**, e é
      exatamente o que o item M1 do backlog pede que a tool passe a reportar sozinha. Hoje
      só se vê por GAQL separado.

---

## Restauração — obrigatória, e verificada por dois instrumentos

- [ ] `update_rsa` + `apply_change` devolvendo `final_urls` de CADA anúncio tocado ao valor
      da seção "Estado capturado".
- [ ] `run_gaql` (a mesma query do Setup) confirma que todos batem com o capturado.
- [ ] O anúncio removido na UI no T4: **recrie ou reative pela UI** — `update_rsa` não
      restaura anúncio removido, e `update_ad_status` não aceita sair de `REMOVED`.
- [ ] Anote abaixo o que ficou diferente do estado inicial, se algo ficou.

⚠️ Restauração em `⬜ pending` = sprint não fechado. Foi assim que o F151 passou.

---

## Estado capturado

_(cole aqui a saída do Setup antes de rodar qualquer caso)_

## Resultado

### T1 — ✅ verificado em produção em 2026-09-20 (relato da sessão de gestão de tráfego)

**Atribuição, porque importa:** não foi medido nesta sessão. Veio da sessão que abriu o
backlog, rodando o caso real na MO-JP logo após o deploy da revisão
`v4-ads-mcp-00110-5nd`. Trate como relato de terceiro verificável, não como medição própria
— quem for assinar o smoke pode refazer em 30 segundos, porque T1 **não muta nada**.

`update_rsa` no `ad_id` `825281476311` devolveu:

> "Ad 825281476311 e uma variacao de Ad Variation (gerenciada pelo Google) e nao aceita
> mutate. Edite o anuncio BASE 825140457725: a variacao herda a mudanca em minutos.
> Atencao: reler a variacao logo apos editar o base devolve o estado ANTIGO sem erro nenhum."

- ✅ Erro no pre-flight, **sem token emitido**.
- ✅ Os dois ids nomeados, e o base (`825140457725`) **correto** — o caminho do
      `_buscar_ad_base_do_grupo` resolveu para candidato único, como no grupo real.
- ✅ **Sem prompt de permissão**, porque a recusa acontece antes de qualquer write.

🔑 **Rodado SEM reconectar, de propósito e com o resultado certo.** A sessão tinha o
catálogo antigo (F140) e sabia disso: a descrição velha não lista variação entre as
rejeições, então a recusa **parece** contradizer a tool. Saber de antemão que a recusa era o
resultado esperado foi o que evitou o diagnóstico errado. É a prova de que o aviso no topo
deste runbook não é burocracia.

**Os demais casos seguem ⬜ pendentes.** T2 e T3 não mutam; **T4 e T5 mutam anúncio
servindo** e exigem o Setup de captura e a Restauração desta página.

### T2–T5 — executados em 2026-09-20, autorizados pelo Wellington nesta sessão

Revisão em produção `v4-ads-mcp-00110-5nd`. **O classificador de auto mode recusou o
primeiro `apply_change`** (`Real-World Transactions`) mesmo com a autorização já dada, e
passou depois de ele autorizar o apply **explicitamente** — exatamente o padrão medido em
04/09 e descrito no topo deste arquivo.

| Caso | Resultado |
|---|---|
| **Setup** | ✅ 33 RSAs capturados |
| **T2** | ✅ token `HCN0JN45` emitido e **não aplicado** (expirou) |
| **T3** | ✅ lote misto recusado inteiro, sem token |
| **T4** | ⚠️ **inconclusivo** — ver abaixo |
| **T5** | ✅ `applied_count: 2`, `failed_count: 0`, `changed_count: 2`, `resource_names` para os dois |
| **Restauração** | ✅ verificada por dois instrumentos |

**Dois desvios do roteiro, feitos de propósito:**

1. **Alvos trocados.** O roteiro mandava usar RSAs comuns do grupo CONTAINER — que estão
   **servindo e dentro do experimento**. O Setup revelou alvos melhores: os dois anúncios
   de ROÇADEIRA (`814964022612`, `814964022615`) vivem em ad_groups **PAUSED**, logo não
   servem, e ficam fora dos três grupos do experimento. Mesma cobertura, zero impacto no
   cliente, zero contaminação do A/B.
2. **T4 sem UI.** Remover anúncio pela UI não é coisa que sessão Claude faça. Tentei duas
   substituições, e **as duas falharam em produzir a falha**: anúncio em campanha `REMOVED`
   foi aceito normalmente, e URL inválida virou o **F184**. T4 segue devendo uma falha
   por-linha real, e o caminho da UI continua sendo o único conhecido.

🔑 **Caso extra que o Setup tornou possível, e que vale mais que o T2:** a variação
`825281476308` vive num grupo com DOIS RSAs não-variação. A recusa apontou o ad_group e
**não nomeou id nenhum** — era o ramo ambíguo, que até então só tinha prova por sabotagem
em unit test.

🔴 **Achado novo: [F184](findings-catalog.md).** Op com `final_urls` inválida devolveu
`status: "success"`, `failed_count: 0` e `applied_count: 2` — e não mudou nada. Só
`changed_count: 1` e `resource_names[1] == null` denunciam. Silent-acceptance, classe 1 do
catálogo.

**Resíduo declarado:** os dois anúncios restaurados ficaram em `REVIEW_IN_PROGRESS`, porque
restaurar também é edição. Ambos em ad_groups PAUSED — nada deixou de servir. O
`811361679009` nunca mudou.
