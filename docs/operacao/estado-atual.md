# Estado atual — V4 Ads MCP

> **Volátil por natureza.** Esta é a seção que muda a cada sessão; ela vivia no
> `CLAUDE.md` e era o motivo de ele reinchar — estado e convenção no mesmo arquivo
> significa que todo trabalho novo empurra bytes para dentro do que é carregado sempre.
> O `CLAUDE.md` mantém um resumo de poucas linhas e aponta para cá.

> **Ao terminar uma sessão, atualize ESTE arquivo**, não o `CLAUDE.md`.

> 🔑 **E mantenha-o curto.** Em 20/09 ele estava com **91 KB**, dos quais 83 eram a
> narrativa de uma frente **já concluída** — narrando como *"falta só o merge"* sete PRs
> mesclados, e contradizendo a própria tabela duas telas abaixo. Arquivo de estado que
> narra o passado deixa de ser confiável sobre o presente, que é a única coisa que ele
> faz. A narrativa foi para
> [`_archive/varredura-2026-09-06-frentes.md`](../_archive/varredura-2026-09-06-frentes.md).
> **Trabalho que fechou sai daqui:** o defeito vai para o catálogo, a narrativa para o
> arquivo, e aqui fica uma linha.

---

## Produção — medido em 2026-09-20

| | |
|---|---|
| Revisão servindo | **`v4-ads-mcp-00113-qv2`** |
| Tools | **68** (62 Google + 6 Meta) |
| Buckets | 22 always + 46 defer — **próxima remedição 04/10** ([método](tool-buckets-2026-09-04.md)) |
| Catálogo | até **F184** (~3.830 linhas) |

Contagens de tool e bucket vêm do registry (`import_all_tools()`), não de `grep` —
**`grep` e `ast.literal_eval` já erraram esta medição**, o segundo devolvendo zero (F183).

## Decision gates abertos

**`GOOGLE_RECONCILE_APPLY=false`** — verificado em produção em 20/09. O laço de
reconciliação Google roda em **observação**: compara, conta, e **não revoga**. Virar a
trava depende do soak. O lado **Meta já revoga** (`META_RECONCILE_APPLY=true` desde
09/09, verificado no mesmo dia).

**Fase 2B travada no soak** — o tombstone dos 8 reports antigos não acontece enquanto os
gestores não migrarem para `get_performance_breakdown`. Re-checar por `audit_log`.
⚠️ O plugin `v4-trafego-google-ads` **0.4.0 empurrava ativamente na direção errada**, com
duas afirmações falsas sobre o breakdown; o **0.4.1 corrigiu e está instalado** (20/09).

## Pendências que dependem do Wellington

- **Smoke 3b.42 (`ad_schedule`) parou em 5 de 10**, em 04/09. T4, T7 e T8 mutam a conta de
  teste `1163862076` e precisam do aval **na sessão que executa**; T5/T6 dependem do T4.
  Runbook: [`phase-3b-42-ad-schedule-smoke.md`](phase-3b-42-ad-schedule-smoke.md).
- **F129** — governança do system user Meta: ação humana, fora do código.
- **F67** — custom domain `mcpv4.fluxocerto.dev.br`, pendente via LB.

## Findings abertos

| ID | o que é |
|---|---|
| **F178** | callback OAuth renderiza sem CSS — `<style>` inline barrado pela CSP |
| **F179** | `admin_invites_cancel` audita cancelamento que pode não ter ocorrido |
| **F180** | **em parte** — ver abaixo |
| **F154** | `/me/adaccounts` não é prova de alcance |

Fechados em 20/09: **F181, F182, F183, F184** (sprint de RSA, abaixo).

---

## Sprint RSA — F180 a F184, fechado em 2026-09-20

Nasceu de um backlog da sessão de gestão de tráfego, em uso real na MO-JP
(`7862230676`). Seis PRs ([#75](https://github.com/BadWolf1509/v4-ads-mcp/pull/75)–[#80](https://github.com/BadWolf1509/v4-ads-mcp/pull/80)), todos em produção.

| ID | o quê | estado |
|---|---|---|
| **F181** | pre-flight não via `system_managed_resource_source = AD_VARIATIONS`; dry-run emitia token para operação impossível | ✅ verificado em produção |
| **F184** | `partial_failures` dizia `success` em operação que o Google não executou | ✅ verificado em produção |
| **F182** | resposta não declarava o regime; `failed_count: 0` afirmava "nenhuma falhou" sem ter medido | ✅ **sem verificação em produção** |
| **F183** | 8 arrays de tool sem teto (o finding dizia 2; metade em tool de leitura) | ✅ sem verificação em produção |
| **F180** | lote de RSA morria inteiro por uma linha | ⚠️ **em parte** |

### 🔴 F180: por que fica "em parte", provavelmente para sempre

A flag `partial_failure` foi ligada e a resposta passa a trazer o relato por linha. **Mas
a falha por-linha nunca foi exercitada contra o Google**, e três tentativas explicam por
quê: campanha `REMOVED` aceita, `final_urls` inválida aceita, **anúncio removido pela UI
entre o preview e o apply também aceito**. **O Google não erra: ele engole.**

O único erro por-linha já visto é o `"Mutates are not allowed"` da variação de
experimento — que **originou** o F180 e que o **F181 agora bloqueia no pre-flight**. A
máquina que o F180 ligou pode não ter gatilho alcançável.

**Consequência prática, e é a que importa:** `failed_count` é constante zero.
Quem audita lote lê **`efeito`** e **`changed_count`**; `applied_count` só na subtração
`applied_count - changed_count` (= linhas que passaram sem efeito), nunca isolado.

### O que o sprint ensinou sobre medição

Os quatro enunciados **subestimaram** o problema: uma variação eram três; "uma frase
imprecisa" eram quatro defeitos, incluindo um teste que mentia sobre o próprio escopo;
"dois arrays" eram oito. Nos quatro, o que corrigiu foi **medir com o instrumento certo
antes de escrever o fix** — e no F183 isso quase falhou, porque o scan que eu escrevi
devolveu **zero** e zero só não virou "nada a fazer" porque contradizia uma contagem
anterior.

**Smoke:** [`phase-rsa-f180-f181-smoke.md`](phase-rsa-f180-f181-smoke.md) — T1–T3 e T5
PASS, T4 inconclusivo, restauração verificada por dois instrumentos. A conta ficou limpa;
o único artefato é um RSA descartável em `REMOVED`, criado para morrer no teste.
