# Varredura de faxina (15/11): desenho curto

**Por quê.** O que pesa hoje é a **manutenção**. Desde as varreduras de 30/10, 03/11 e 10/11, acumularam-se:
- código sem uso;
- duplicação;
- testes que não guardam nada;
- docs velhos;
- minors adiados em vários ledgers.

O objetivo é ler e manter menos, sem mudar o comportamento que o gestor vê.

**Decisões do Wellington (menu, 15/11):**
- **Motivo:** peso para quem mantém.
- **Tools ociosas:** remedir o uso das 27 tools sem chamada em 90 dias e **só listar**. Remover qualquer uma fica para depois do 02/12, quando o uso real do teste de 30 dias estiver medido.
- **Entrega:** varredura só de leitura → você escolhe os achados → plano por partes, um PR por parte.
- **Fora, por decisão registrada:** Fase 2B (travada no soak), divisão do `recommendations.py`, `accounts.html` × `accounts_meta.html`. A varredura só os cita se achar dado novo.
- **Abordagem:** detector + agentes por área.
- **Ferramentas:** temporárias, fora do projeto.

## Objetivos, não-objetivos, anti-objetivos

- **Objetivo:** uma lista de achados **com prova**, cada um com:
  - onde está (`arquivo:linha`);
  - a evidência (comando + saída, ou grep de uso);
  - o custo de manter;
  - o risco de mexer;
  - a sugestão.
- **Não-objetivo:** mudar comportamento, contrato de tool, schema ou o catálogo nesta fase. Remover tool também está fora.
- **Anti-objetivo:** declarar código "morto" sem medir quem o usa. Na lista, isso conta como afirmação falsa. Alguns usos que o grep simples não vê:
  - tool registrada por decorator;
  - rota FastAPI;
  - fixture do pytest;
  - template Jinja;
  - job do Cloud Run;
  - script de operação;
  - `getattr` dinâmico.

## Abordagens

| | o quê | troca |
|---|---|---|
| **Escolhida:** detector + agentes | as ferramentas geram candidatos; 4 agentes de leitura confirmam cada um na sua área, com grep do uso | mede mais e filtra o falso positivo; custa uma rodada de agentes |
| só agentes | como em 03/11 e 10/11 | não instala nada, mas acha menos código morto e mede menos |
| só detectores | saída filtrada pelo controlador | mais barato, mas o falso positivo passa sem confirmação |

## Desenho

**1. Detectores (controlador)**

Rodam num venv descartável no scratchpad. Não entram no `pyproject.toml`, no lock nem no repo.

- **`vulture src`** com confiança ≥ 60, mais uma whitelist dos usos dinâmicos que o projeto já tem (decorators de tool e rota, fixtures).
- **Cobertura** da suíte unit + integração não-DB (`pytest --cov=src`), para achar ramos e módulos nunca exercitados.
- **`pytest --durations=30`**, para ver os testes mais lentos.
- **Duplicação** entre arquivos: blocos de ≥ 10 linhas iguais ou quase iguais, por script simples ou `pylint --disable=all --enable=duplicate-code`.
- **Docs:**
  - links relativos quebrados em `docs/` fora do `_archive/`;
  - arquivos de `docs/operacao/` que nenhum doc vivo cita.
- **Uso das tools:** contagem no `audit_log` por tool em 90 dias até 15/11, via `python+asyncpg`, só leitura.

A saída de cada detector vai para arquivo no workspace da varredura, não para o contexto.

**2. Agentes por área (leitura, em paralelo)**

Cada agente recebe a saída dos detectores filtrada para a sua área e confirma, descarta ou acrescenta achados.

- **A:** `src/google_ads/`, `src/mcp/`, `src/governance/`.
- **B:** `src/meta_ads/`, `src/web/`, `src/db/`, jobs.
- **C:** `tests/`: testes redundantes, mocks que repetem o código, fixtures sem uso, guards que não distinguem código bom de quebrado.
- **D:** `docs/` vivos, `scripts/`, `.github/`, mais os minors adiados nos ledgers e handoffs ainda abertos.

Regras para os agentes:
- achado sem a prova do uso medido não entra;
- descartar é tão útil quanto achar;
- cada descarte vai listado com o motivo.

**3. Relatório**

Vai em `docs/operacao/varredura-faxina-2026-11-15.md`, commitado. Tem:
- os achados agrupados por área, com prova, custo, risco e sugestão;
- a lista das tools ociosas com o uso remedido;
- os descartados com o motivo;
- o que não foi medido.

Você escolhe o que entra, por menu, e daí sai o plano (`writing-plans`), um PR por parte.

**Fica com o executor:** os thresholds dos detectores, o formato do relatório e a ordem das partes do plano.
