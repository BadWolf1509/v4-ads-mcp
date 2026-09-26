# Orçamento do `CLAUDE.md`: restaurar a separação por área — design

**Data:** 2026-09-22
**Origem:** pedido de "ajustar a documentação para eficiência máxima de contexto".
A medição **reenquadrou o pedido** e depois **invalidou o primeiro método proposto**;
as correções estão registradas abaixo em vez de apagadas — inclusive a de 25/09, que
achou errado o número do §3.

---

## 1. O pedido, e por que ele não era o problema

`CLAUDE.md` é o **único custo incondicional** da documentação — entra inteiro em toda
sessão. Medido:

| | custo |
|---|---|
| **`CLAUDE.md`** | 23.976 bytes ≈ **6.000 tokens, toda sessão** |
| `docs/convencoes/*` (5 arquivos, 2–13 KB) | só quando roteados |
| `findings-catalog.md` (540 KB) | só o que o grep traz |

Dentro dele, **`Don't do` é 54%** — 12.751 bytes, 45 bullets, 61 regras.

**Mas 6.000 tokens numa janela de 200k+ é ~3%.** Comprimir 35% economiza ~1.000 tokens:
ruído. **A dor medida é outra:** a folga é de **24 bytes** num teto de 24.000 com guard.
O arquivo está num batente rígido, e o próximo finding que precisar de tripwire não tem
onde entrar.

**O objetivo deste trabalho é espaço, não token.** O critério de sucesso muda junto: não
"quantos bytes economizei", e sim "quantos bytes de folga sobraram para os próximos meses".

## 2. O teto não é arbitrário, e isso decide a abordagem

O racional está escrito em `tests/unit/test_docs_links.py`:

> *"2026-08-19: o arquivo chegou a **54.852 bytes** carregados em TODA sessão — 88% deles
> em `Current state`, `Conventions` e `Don't do`. **Separar por volatilidade** derrubou
> pra ~17,7 KB. O teto existe pra que a separação não seja desfeita por **acúmulo**: cada
> sessão acrescenta um pouco, e sem limite o arquivo volta ao que era em poucos meses —
> **foi o que aconteceu**."*

Três consequências, e elas eliminam duas das três opções:

1. **Subir o teto está fora.** É o modo de falha que o guard existe para impedir, já
   observado uma vez. O comentário não especula: diz *"foi o que aconteceu"*.
2. **Comprimir sozinho trata o sintoma.** O arquivo foi de 17,7 KB a 24,0 KB **por
   acúmulo**. Comprimir devolve alguns KB que reenchem pelo mesmo mecanismo.
3. **Separar por área não é risco novo** — é o conserto que funcionou em 08-19, e de onde
   vieram `docs/convencoes/` e a tabela de roteamento. Este trabalho **restaura um desenho
   existente que o acúmulo corroeu**, não inventa um.

## 3. O método que eu propus primeiro, e por que ele caiu

A proposta inicial era: *"história já no catálogo ⇒ comprime para regra + ponteiro F-N"*.
Medido nas 45:

| | |
|---|---|
| Bullets com entrada própria no catálogo | **12** (3.211 B, 24%) |
| **Bullets órfãos — o `CLAUDE.md` é o único registro** | **33** (9.540 B, **74%**) |

Comprimir para ponteiro exigiria **escrever 33 entradas de catálogo antes**, inflando o
catálogo muito mais do que economizaria. Método descartado.

*(O instrumento errou duas vezes antes de acertar: o catálogo registra findings em **duas**
formas — 62 em linha de tabela `| **F<n>** |` e 52 em cabeçalho `## F<n>` — e o primeiro
detector via só a segunda, produzindo "21 regras sem entrada" que era artefato meu. Fica
registrado porque é a classe de defeito que este repo mais paga.)*

**Correção de 25/09 — o instrumento não tinha acertado.** O catálogo tem uma **terceira**
forma, item de lista `- **F<n> (SEV) —`, com 69 findings (F57–F60, F74–F138) registrados só
nela. Com as três — e com o detector de duas reproduzindo o 12/33 acima exato, como
controle —, são **27 bullets com entrada (60% dos bytes) e 18 órfãos (40%)**; os 18 são
exatamente os que não citam F-number nenhum. O método continuaria exigindo 18 entradas
escritas antes, e a decisão fica: ela se apoia no §2, não neste número. Registro no F192.

## 4. O eixo do corte

O mesmo de 08-19: **onde a regra dispara**.

| fica no `CLAUDE.md` | vai para o arquivo roteado |
|---|---|
| dispara onde **não há como rotear** — shell, git, CI, deploy, segredo, autorização, processo | só importa **depois** que você já está na área — painel, query/janela, teste, executor |

O teste é direto: *"existe uma linha da tabela de roteamento que me levaria a esta regra
antes de eu poder violá-la?"* Você não é roteado para um pipe de shell. Você **é** roteado
para `painel.md` antes de tocar um template.

**Segundo eixo, que refina o primeiro:** uma regra **coberta por guard** é mais segura de
mover, porque o mecanismo não depende da minha atenção — o CI reprova mesmo que ninguém
tenha lido o texto. Medido: 14 arquivos de guard, e entre eles
`test_frontend_a11y_guards`, `test_frontend_responsive_guards`,
`test_no_server_clock_in_google_tools`, `test_no_secrets_in_query_params` e
`test_rotas_de_mutacao_tem_guard` cobrem boa parte das regras de painel e de janela de
data. **Onde há guard, o texto é lembrete; onde não há, o texto é a única defesa.**

## 5. A classificação medida

45 bullets, 12.751 bytes:

| destino | bullets | bytes | % |
|---|---:|---:|---:|
| **FICA no `CLAUDE.md`** | 8 | 2.765 | 22% |
| → `convencoes/painel.md` | 12 | 3.121 | 24% |
| → `convencoes/nucleo.md` | 11 | 3.047 | 24% |
| → `convencoes/dados.md` | 4 | 1.450 | 11% |
| → `convencoes/testes.md` | 5 | 824 | 6% |
| → `convencoes/processo.md` | 5 | 1.543 | 12% |

**O que FICA, e o motivo de cada um:**

- *guard que passou de primeira / asserir o adjacente* — dispara ao verificar **qualquer**
  fix, não só ao escrever teste. **Fica a regra; as três ilustrações de 02/09 vão para
  `testes.md`.** É o único bullet que sofre os dois tratamentos.
- *pipe entre o gate e o `&&`* · *exit code de `gh run watch`* · *PR empilhado sem checks* —
  shell, CI e git. Nada roteia para um pipe.
- *smoke de tool que muta sem o gestor presente* — autorização humana; freio de segurança.
- *SQL cru em produção* · *segredo em pipe/chat* — destrutivo e segredo.
- *pular `brainstorming`* — é a regra que manda **rotear**; não pode viver no destino.

**Nota de destino:** as regras de dependência e deploy (`uv pip compile --universal`,
revisão de rollback, "no build step") não têm linha própria na tabela de roteamento hoje.
Vão para `processo.md` ("procedimento operacional raro"), e a tabela ganha a linha que
faltava.

## 6. A mitigação, e ela é o que torna o corte aceitável

78% dos tripwires saem do arquivo sempre-carregado. Três coisas seguram isso:

1. **A tabela de roteamento passa a declarar que os tripwires foram junto.** Hoje ela diz
   *"vai mexer em `src/web/` → leia `painel.md`"*. Passa a dizer que **as regras daquela
   área vivem lá** — sem isso, quem lê a tabela acha que `painel.md` só tem convenção.
2. **Um bloco de ponteiros fica no `Don't do`**, nomeando o que saiu e para onde. Custa
   ~400 bytes e preserva a propriedade que importa: **saber que a regra existe** mesmo sem
   carregá-la.
3. **O guard do orçamento continua, no mesmo teto.** O ganho é folga, não licença.

## 7. Resultado esperado, medido

```
Don't do:    12.751 B  →  ~3.200 B  (8 bullets que ficam + bloco de ponteiros)
CLAUDE.md:   23.976 B  →  ~14.400 B
folga:           24 B  →   ~9.600 B
```

Abaixo dos 17,7 KB que a separação de 08-19 alcançou — e a folga volta a comportar
meses de acúmulo.

## 8. Fora de escopo, nomeado

- **Comprimir o `findings-catalog.md`** (540 KB, 52 entradas cheias, média 5,7 KB, maior
  28 KB). O custo dele é **por grep**, limitado pelo que se procura — não é incondicional.
  Comprimi-lo arrisca perder o *"o que ficou deliberadamente de fora"* de cada entrada,
  que é o que as torna úteis.
- **Arquivar os 16 planos órfãos** (556 KB de 1.396 KB em `superpowers/plans`, **medidos
  sem link de entrada**; os outros 18 são apontados por doc vivo e ficam). É trabalho
  separado e independente deste — um `git mv` para `_archive/`, que o `CLAUDE.md` já manda
  não grepar. Não custa contexto hoje; polui busca.
- **Subir o teto de 24.000.** Ver §2.
- **Mexer nas outras seções do `CLAUDE.md`.** Somadas dão 46% e nenhuma passa de 2,1 KB;
  o retorno não paga o risco de mexer no que toda sessão lê.

## 9. Critério de pronto

1. `python scripts/check_pre_push.py` 6/6, EXIT=0 — inclui o guard do orçamento e o de
   links relativos, que **falha se um ponteiro novo não resolver**.
2. **Nenhuma regra perdida.** Um scan compara o conjunto de regras `Don't` antes e depois
   (união do `CLAUDE.md` com os cinco arquivos de convenção) e exige igualdade. É a
   invariante desta mudança, e ela é verificável — não uma promessa.
3. Folga do `CLAUDE.md` ≥ 8.000 bytes, medida com CRLF normalizado (como o guard mede).
4. A tabela de roteamento cobre as cinco áreas de destino, e a linha nova de
   dependência/deploy existe.
5. O bloco de ponteiros nomeia as cinco áreas e o que cada uma contém.
