# Negativas com acento e cobertura, `run_gaql` compacto — design

**Data:** 2026-10-05. **Aprovado por:** Wellington, em 05/10.

**Origem:** quatro apontamentos de campo da sessão "Gestor de Tráfego JP" na MO-JP (`7862230676`),
em 05/10. Nenhum estava no catálogo.

## 1. Fatos medidos (premissas do desenho)

1. **O Google não aplica variante próxima em negativa.** A negativa PHRASE `material de construção`
   deixou passar `material de construcao`, e a BROAD `macaco hidraulico` deixou passar `aluguel de
   macaco hidráulico` (relato de campo, MO-JP, 90 dias). Acento, plural e erro de digitação são
   negativas distintas.
2. **Keyword duplicada é descartada em silêncio, sem erro** (catálogo A1). Por isso repetir uma
   negativa não derruba o lote. O problema é a resposta dizer "aplicada" sobre o que não mudou nada,
   a família do F184.
3. **Uma PHRASE nova já coberta por uma BROAD existente do mesmo texto** foi aceita pelo Google
   sem aviso (relato de campo: `patrol`, `exaustor`, `retroescavadeira`, `valetadeira`).
4. **Recomendação aceita à mão pelo app sai igual a edição manual.** Sondado em 05/10 no
   `change_event` da MO-JP, nas criações de 03/10 17:43:
   - `client_type: GOOGLE_ADS_MOBILE_APP`, com o e-mail do gestor;
   - `changed_fields` são os campos de qualquer criação de keyword;
   - nenhum campo de origem.

   Não há heurística confiável.
5. **O `run_gaql` devolve o `resource_name` de cada objeto da linha, mesmo fora do SELECT**
   (`MessageToDict` em `reports.py`). Medido numa amostra de `campaign_criterion`: a linha plana sem
   esses campos fica **39% menor** (858 → 525 caracteres). Linhas com muitas métricas ganham menos.
6. **A campanha JPA tem 262 negativas de keyword** (05/10). A leitura prévia lê todas, sem `limit`.

## 2. Escopo

| Item | Onde | O quê |
|---|---|---|
| 1. Acento | `add_negative_keywords`, `add_negatives_from_search_terms` | Avisa a negativa acentuada sem o par sem acento. Com `incluir_variante_sem_acento: true`, grava o par. |
| 4. Cobertura | `add_negative_keywords` | A repetida sai do lote (`ja_existia`); a coberta por uma mais ampla é gravada e avisada. |
| 3. Compacto | `run_gaql` | `compact: true` devolve linhas planas com chave pontilhada, sem os `resource_name` implícitos. |
| 2. Origem | descriptions de `detect_drift` e `get_change_history` | Dizem que a recomendação aceita à mão é indistinguível de edição manual. |

**Fora de escopo:**
- **Plural e erro de digitação:** não há regra confiável em PT-BR. A description diz que a tool não
  os cobre.
- **Cobertura em `add_negatives_from_search_terms`:** o relato é da outra tool, e esta já classifica
  `already_exists` pelo `partial_failure`.
- **`remove_negative_keywords` não conferir se o critério é negativo:** é outro achado, registrado
  para depois.
- **Flag heurística de recomendação aceita:** o fato 4 mostra que ela não teria sinal.

## 3. Desenho

### 3.1 Módulo puro `src/google_ads/negativas.py`

Sem google-ads, testável com dados simples.

- **`sem_acento(texto: str) -> str | None`:** remove só os diacríticos (NFD menos as marcas
  combinantes, recomposto em NFC). Não mexe em caixa nem em espaço. Devolve `None` quando o resultado
  é igual ao texto, ou seja, quando não havia acento.
- **`chave(texto: str) -> str`:** minúsculas mais espaços colapsados. **O acento é mantido**, porque
  ele distingue negativa (fato 1).
- **`AMPLITUDE`:** `{"EXACT": 0, "PHRASE": 1, "BROAD": 2}`.
- **`classificar(nova, existentes) -> tuple[str, dict | None]`:**
  - `("repetida", existente)` se houver o mesmo texto (pela `chave`) com o mesmo tipo;
  - `("coberta", existente)` se houver o mesmo texto com tipo de amplitude maior;
  - `("nova", None)` caso contrário.

  Uma PHRASE ou BROAD de várias palavras não é comparada com textos diferentes: a regra é só
  mesmo texto. A cobertura entre textos distintos (BROAD `a` cobre BROAD `a b`) fica fora, porque a
  semântica da negativa ampla de várias palavras exige todos os termos e isso não é medido aqui.

### 3.2 `add_negative_keywords`

1. **Leitura prévia:** as negativas de keyword da campanha (`campaign_criterion`, `negative = TRUE`,
   `type = 'KEYWORD'`, `campaign.id = X`), por `run_report` sem audit e sem `limit`, com `int()` no id.
2. **Para cada keyword pedida:**
   - repetida (contra as existentes **e** contra as anteriores do mesmo pedido): sai do lote e vai
     para `ja_existia[]` com a existente;
   - coberta: fica no lote e entra em `avisos[]` com a que cobre;
   - com acento (`sem_acento` não nulo) e sem o par sem acento no pedido nem na campanha: entra em
     `avisos[]` com a grafia sugerida. Com `incluir_variante_sem_acento: true`, o par entra no lote,
     com o mesmo match type, passando pelas mesmas regras, e é listado em `variantes_incluidas[]`.
3. **Lote vazio depois do filtro:** não chama o mutate e responde com `applied_count: 0` e o
   `ja_existia`.
4. **Falha da leitura prévia:**
   - `AccountAccessDeniedError` propaga;
   - erro amigável (`GoogleAdsFriendlyError`, `QuotaExhausted`) grava como hoje e devolve
     `cobertura_verificada: false` com `cobertura_motivo` contendo a mensagem;
   - outro erro grava igual, com motivo fixo e `log.exception`, sem `str(e)` (a lição do #143).

   Com a leitura bem-sucedida, `cobertura_verificada: true`.
5. **Resposta:** o envelope de hoje mais `ja_existia`, `avisos`, `variantes_incluidas` e
   `cobertura_verificada`, com `cobertura_motivo` só quando `false`. Listas vazias vêm como `[]`.
6. **Schema:** `incluir_variante_sem_acento: boolean`, default `false`. A description ganha:
   - os fatos 1 e 2;
   - os campos novos;
   - que plural e erro de digitação não são cobertos.

### 3.3 `add_negatives_from_search_terms`

Só o item 1. Mesmo aviso e mesmo opt-in, nos três escopos (`campaign`, `ad_group`, `shared_set`). A
variante gravada sai no `added[]` com `variante_de: <termo original>`. Não há leitura prévia: o
"par sem acento já existe" só é conferido dentro do próprio pedido, e a description diz isso.

### 3.4 `run_gaql`

- **`compact: boolean`**, default `false`. A resposta só muda para quem pedir.
- **Com `compact: true`**, cada linha vira dict plano com chave pontilhada (`campaign.id`,
  `metrics.clicks`). Os valores ficam como vêm: o int64 continua string, como no `MessageToDict`.
- **Sai todo `*.resource_name` que não está no SELECT.** A lista do SELECT é lida entre `SELECT` e
  `FROM`, sem distinguir caixa. Se a lista não puder ser lida, nenhum `resource_name` é tirado e a
  linha só é achatada (falha segura).
- **Com `aggregate_by`:** o `compact` não muda nada, porque a saída já é `groups[]`.
- **Description:** cita os −39% medidos em `campaign_criterion` e diz que o ganho depende da
  consulta.

### 3.5 Descriptions do `detect_drift` e do `get_change_history`

Uma frase em cada uma: recomendação aceita à mão **pelo app de celular** sai com
`client_type: GOOGLE_ADS_MOBILE_APP` e o e-mail do gestor, igual a uma edição manual (sondado em
05/10). A aceitação pela UI web de Recomendações **não foi medida**: o comentário existente no
`get_change_history` diz que ela pode sair como `GOOGLE_ADS_RECOMMENDATIONS`, igual ao auto-apply,
e a description não afirma nada sobre ela.

## 4. Testes e guards

- **`negativas.py`:**
  - `sem_acento` em `construção`, `hidráulico`, `ÇÃO`, sem acento (`None`), texto com espaço duplo
    (preservado);
  - `chave`;
  - `classificar` nas três saídas e nas amplitudes em ambas as direções (PHRASE nova contra BROAD
    existente é coberta; BROAD nova contra PHRASE existente é nova);
  - plural (`material` / `materiais`) fixado como "não tratado".
- **`add_negative_keywords`:**
  - o formatter da leitura prévia com `GoogleAdsRow` real;
  - repetida fora do lote, inclusive a repetida dentro do pedido;
  - lote vazio sem mutate;
  - aviso de acento;
  - opt-in grava o par;
  - o par já existente não gera aviso;
  - falha da leitura em três sabores: denied propaga, amigável com mensagem, interno sem vazar host;
  - o lote enviado ao builder é conferido (o que vai ao Google).
- **`add_negatives_from_search_terms`:** aviso e opt-in nos três escopos.
- **`run_gaql`:** `compact` com `GoogleAdsRow` real, tirando o implícito e mantendo o pedido;
  SELECT ilegível tira nada; default `false` inalterado.
- **Descriptions:** âncoras das frases novas nas quatro tools.
- **Sabotagem por cópia** em cada guard novo (`.superpowers/ferramentas-plano/sabota_modelo.py`).

## 5. Smoke (MO-JP, depois do deploy)

Precisa do Wellington presente, porque as negativas são mutate auto-apply.

1. `add_negative_keywords` com uma negativa já existente: `ja_existia` com ela e `applied_count: 0`.
   Não grava nada.
2. Com uma acentuada nova, sem o opt-in: `avisos` com a grafia sugerida. Grava uma negativa, que o
   Wellington escolhe.
3. `run_gaql` com `compact: true` na consulta das negativas: o tamanho cai, e os campos do SELECT
   ficam.
