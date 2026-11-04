# Negativas com acento e cobertura, `run_gaql` compacto — plano

> **Para agentes:** este plano foi GERADO dos commits validados (memória `planos-precisam-rodar`):
> cada task é um commit que passou o gate rápido isolado; o bloco `diff` de cada task é o
> `git show` exato do commit. Reaplicar os blocos em ordem sobre a spec dá a árvore do último
> commit (conferido pelo gerador). Execução escolhida: commits validados + revisões. As Tasks 6 e
> 7 são as rodadas da revisão final (Opus) e da re-revisão (Sonnet); os relatórios ficam no ledger.

**Objetivo:** os quatro apontamentos de campo da MO-JP (05/10) — aviso e opt-in de acento nas
duas tools que criam negativa, cobertura no `add_negative_keywords`, `compact` no `run_gaql` e a
recomendação aceita pelo app nas descriptions de `detect_drift`/`get_change_history`.

**Spec:** `docs/superpowers/specs/2026-10-05-negativas-e-gaql-compacto-design.md` (autoridade).

**Ver falhar:** provado por **26 sabotagens de cópia** sobre o código final (uma por guard novo,
cada uma caindo pelo motivo certo), não por vermelhos medidos task a task.

## Restrições globais

- Gate pelo Python do `.venv` (`scripts/check_pre_push.py`), commit encadeado por `&&`.
- Full sweep (Docker) obrigatório: a Task 2 mexe no pré-flight de um mutate.
- Texto cru de erro interno nunca chega ao gestor (lição do #143); denied propaga.
- Acento distingue negativa: `chave()` mantém o acento; `sem_acento()` só sugere o par.

---

### Task 1: feat(mcp): regras puras das negativas - sem_acento, chave e cobertura

Spec 2026-10-05 §3.1. O Google nao aplica variante proxima em negativa: a chave
mantem o acento, e sem_acento so sugere o par.

**Arquivos:**

```text
A	src/google_ads/negativas.py
A	tests/unit/test_negativas_puro.py
```

- [ ] Aplicar o bloco, rodar o gate, commitar com a mensagem acima.

```diff
diff --git a/src/google_ads/negativas.py b/src/google_ads/negativas.py
new file mode 100644
index 0000000..5149c98
--- /dev/null
+++ b/src/google_ads/negativas.py
@@ -0,0 +1,49 @@
+"""Regras puras das negativas de keyword (spec 2026-10-05, §3.1).
+
+O Google não aplica variante próxima em negativa (medido na MO-JP, 05/10): acento, plural e
+erro de digitação são negativas distintas. Por isso a `chave` de comparação mantém o acento, e
+`sem_acento` existe para SUGERIR o par, nunca para igualar os dois.
+
+Cobertura só entre negativas de MESMO texto: BROAD cobre PHRASE e EXACT, PHRASE cobre EXACT.
+Texto diferente não se compara — a semântica de negativa ampla de várias palavras entre textos
+distintos não foi medida.
+"""
+
+import unicodedata
+from typing import Any
+
+AMPLITUDE: dict[str, int] = {"EXACT": 0, "PHRASE": 1, "BROAD": 2}
+
+
+def sem_acento(texto: str) -> str | None:
+    """O texto sem diacríticos, ou `None` quando não havia acento. Caixa e espaço intactos."""
+    decomposto = unicodedata.normalize("NFD", texto)
+    limpo = unicodedata.normalize(
+        "NFC", "".join(c for c in decomposto if not unicodedata.combining(c))
+    )
+    return None if limpo == unicodedata.normalize("NFC", texto) else limpo
+
+
+def chave(texto: str) -> str:
+    """Chave de comparação: minúsculas e espaços colapsados — o acento fica."""
+    return " ".join(texto.lower().split())
+
+
+def classificar(
+    nova: dict[str, Any], existentes: list[dict[str, Any]]
+) -> tuple[str, dict[str, Any] | None]:
+    """`("repetida", e)`, `("coberta", e)` ou `("nova", None)`.
+
+    `nova` e cada existente têm `text` e `match_type`. Repetida vence coberta.
+    """
+    alvo = chave(nova["text"])
+    amplitude = AMPLITUDE[nova["match_type"]]
+    cobre: dict[str, Any] | None = None
+    for e in existentes:
+        if chave(e["text"]) != alvo:
+            continue
+        if e["match_type"] == nova["match_type"]:
+            return "repetida", e
+        if cobre is None and AMPLITUDE[e["match_type"]] > amplitude:
+            cobre = e
+    return ("coberta", cobre) if cobre is not None else ("nova", None)
diff --git a/tests/unit/test_negativas_puro.py b/tests/unit/test_negativas_puro.py
new file mode 100644
index 0000000..e667259
--- /dev/null
+++ b/tests/unit/test_negativas_puro.py
@@ -0,0 +1,87 @@
+"""Regras puras das negativas (spec 2026-10-05, §3.1).
+
+O Google não aplica variante próxima em negativa (medido na MO-JP, 05/10): `material de
+construção` deixou passar `material de construcao`. Acento distingue negativa — por isso a
+`chave` o mantém e a `sem_acento` sugere o par.
+"""
+
+from __future__ import annotations
+
+import pytest
+
+from src.google_ads.negativas import chave, classificar, sem_acento
+
+
+@pytest.mark.parametrize(
+    ("texto", "esperado"),
+    [
+        ("material de construção", "material de construcao"),
+        ("macaco hidráulico", "macaco hidraulico"),
+        ("LOCAÇÃO", "LOCACAO"),
+        ("aluguel  de  andaime", None),  # sem acento: nada a sugerir, espaço preservado
+        ("andaime", None),
+    ],
+)
+def test_sem_acento(texto: str, esperado: str | None) -> None:
+    assert sem_acento(texto) == esperado
+
+
+def test_sem_acento_preserva_caixa_e_espacos() -> None:
+    assert sem_acento("Construção  Civil") == "Construcao  Civil"
+
+
+def test_chave_mantem_acento_e_normaliza_caixa_e_espaco() -> None:
+    assert chave("  Material   de Construção ") == "material de construção"
+    assert chave("material de construcao") != chave("material de construção")
+
+
+def _neg(texto: str, tipo: str) -> dict[str, str]:
+    return {"text": texto, "match_type": tipo, "criterion_id": "1"}
+
+
+def test_mesmo_texto_mesmo_tipo_e_repetida() -> None:
+    existente = _neg("Patrol", "PHRASE")
+    assert classificar({"text": "patrol", "match_type": "PHRASE"}, [existente]) == (
+        "repetida",
+        existente,
+    )
+
+
+@pytest.mark.parametrize(
+    ("nova", "existente"),
+    [("PHRASE", "BROAD"), ("EXACT", "BROAD"), ("EXACT", "PHRASE")],
+)
+def test_tipo_mais_estreito_contra_mais_amplo_e_coberta(nova: str, existente: str) -> None:
+    e = _neg("patrol", existente)
+    assert classificar({"text": "patrol", "match_type": nova}, [e]) == ("coberta", e)
+
+
+@pytest.mark.parametrize(
+    ("nova", "existente"),
+    [("BROAD", "PHRASE"), ("BROAD", "EXACT"), ("PHRASE", "EXACT")],
+)
+def test_tipo_mais_amplo_contra_mais_estreito_e_nova(nova: str, existente: str) -> None:
+    assert classificar({"text": "patrol", "match_type": nova}, [_neg("patrol", existente)]) == (
+        "nova",
+        None,
+    )
+
+
+def test_repetida_vence_coberta_quando_as_duas_existem() -> None:
+    igual = _neg("patrol", "PHRASE")
+    ampla = _neg("patrol", "BROAD")
+    assert classificar({"text": "patrol", "match_type": "PHRASE"}, [ampla, igual]) == (
+        "repetida",
+        igual,
+    )
+
+
+def test_textos_diferentes_nao_se_comparam() -> None:
+    """Plural, acento e texto contido não são tratados (spec §2, fora de escopo)."""
+    existentes = [_neg("material", "BROAD"), _neg("construção", "BROAD")]
+    assert classificar({"text": "materiais", "match_type": "BROAD"}, existentes) == ("nova", None)
+    assert classificar({"text": "construcao", "match_type": "BROAD"}, existentes) == ("nova", None)
+    assert classificar({"text": "material de x", "match_type": "BROAD"}, existentes) == (
+        "nova",
+        None,
+    )
```

### Task 2: feat(mcp): add_negative_keywords le as negativas da campanha antes de gravar

Spec 2026-10-05 §3.2. A repetida sai do lote (ja_existia) - o Google a
descartaria em silencio; a coberta por uma mais ampla e gravada e avisada; a
acentuada sem o par sem acento e avisada, e incluir_variante_sem_acento grava
o par. Nada a gravar responde no_changes sem mutate. Falha da leitura previa:
denied propaga, amigavel grava com o motivo, interna grava com motivo fixo.

**Arquivos:**

```text
M	src/google_ads/queries/tactical.py
M	src/mcp/tools/add_negative_keywords.py
M	tests/integration/test_negative_keywords.py
A	tests/unit/test_add_negative_keywords_cobertura.py
M	tests/unit/test_filters_applied_chega_na_resposta.py
M	tests/unit/test_filters_applied_e_derivado.py
```

- [ ] Aplicar o bloco, rodar o gate, commitar com a mensagem acima.

```diff
diff --git a/src/google_ads/queries/tactical.py b/src/google_ads/queries/tactical.py
index cb3ca49..99d9a50 100644
--- a/src/google_ads/queries/tactical.py
+++ b/src/google_ads/queries/tactical.py
@@ -104,6 +104,31 @@ def negative_keywords_audit_query() -> tuple[str, dict[str, Any]]:
     return gaql, filtros
 
 
+def campaign_negative_keywords_query(campaign_id: str) -> tuple[str, dict[str, Any]]:
+    """As negativas de keyword de UMA campanha — a leitura previa do `add_negative_keywords`.
+
+    Sem LIMIT: a cobertura so vale sobre a lista inteira (a campanha JPA da MO-JP tinha 262
+    em 05/10). `int()` no id (F163). Spec 2026-10-05 §3.2.
+    """
+    gaql = f"""
+        SELECT
+          campaign_criterion.criterion_id,
+          campaign_criterion.keyword.text,
+          campaign_criterion.keyword.match_type
+        FROM campaign_criterion
+        WHERE campaign_criterion.negative = true
+          AND campaign_criterion.type = 'KEYWORD'
+          AND campaign.id = {int(campaign_id)}
+    """.strip()
+    filtros: dict[str, Any] = {
+        "nivel": "campanha",
+        "negative": True,
+        "criterion_type": "KEYWORD",
+        "campaign_ids": [campaign_id],
+    }
+    return gaql, filtros
+
+
 def ad_performance_query(
     start: date, end: date, status: str, limit: int
 ) -> tuple[str, dict[str, Any]]:
diff --git a/src/mcp/tools/add_negative_keywords.py b/src/mcp/tools/add_negative_keywords.py
index 232f936..af40cc4 100644
--- a/src/mcp/tools/add_negative_keywords.py
+++ b/src/mcp/tools/add_negative_keywords.py
@@ -1,14 +1,31 @@
 # bucket: defer
-"""Tool: add_negative_keywords - add campaign-level negative keywords. Auto-applies."""
+"""Tool: add_negative_keywords - add campaign-level negative keywords. Auto-applies.
+
+Spec 2026-10-05 §3.2: antes de gravar, le as negativas da campanha. A repetida (mesmo texto e
+tipo) sai do lote — o Google a descartaria em silencio (catalogo A1) e a resposta diria
+"aplicada" sobre nada. A coberta por uma mais ampla e gravada e avisada. A acentuada sem o par
+sem acento e avisada — o Google nao aplica variante proxima em negativa — e, com
+`incluir_variante_sem_acento`, o par entra no lote.
+"""
 
 from typing import Any
 
+import structlog
+
+from src.google_ads.access import AccountAccessDeniedError
+from src.google_ads.errors import GoogleAdsFriendlyError
 from src.google_ads.mutations import run_mutation
+from src.google_ads.negativas import classificar, sem_acento
+from src.google_ads.queries.tactical import campaign_negative_keywords_query
+from src.google_ads.reports import run_report
 from src.governance.blast_radius import classify
+from src.governance.rate_limit import QuotaExhausted
 from src.mcp.context import get_current
 from src.mcp.tools._mutate_common import applied_envelope
 from src.mcp.tools._registry import register_tool
 
+log = structlog.get_logger(__name__)
+
 _SCHEMA: dict[str, Any] = {
     "type": "object",
     "properties": {
@@ -31,11 +48,99 @@ _SCHEMA: dict[str, Any] = {
             "minItems": 1,
             "maxItems": 500,
         },
+        "incluir_variante_sem_acento": {
+            "type": "boolean",
+            "default": False,
+            "description": (
+                "Grava tambem a grafia sem acento de cada negativa acentuada (mesmo match type), "
+                "quando ela ainda nao existe — o Google nao aplica variante proxima em negativa."
+            ),
+        },
     },
     "required": ["customer_id", "campaign_id", "keywords"],
     "additionalProperties": False,
 }
 
+# Motivo FIXO: o texto cru do erro (host, SQL, driver) nao chega ao gestor — o scrub do
+# `_error_envelope` do servidor. So o erro escrito para ele (friendly, quota) vai junto.
+_MOTIVO_LEITURA_FALHOU = "leitura das negativas da campanha falhou"
+
+
+def _negativa_existente(row: Any) -> dict[str, Any]:
+    cc = row.campaign_criterion
+    return {
+        "criterion_id": str(cc.criterion_id),
+        "text": cc.keyword.text,
+        "match_type": cc.keyword.match_type.name,
+    }
+
+
+def _planejar(
+    pedidas: list[dict[str, Any]],
+    existentes: list[dict[str, Any]],
+    incluir_variante: bool,
+) -> dict[str, list[dict[str, Any]]]:
+    """O lote que vai ao Google e o que a resposta conta sobre o resto."""
+    lote: list[dict[str, Any]] = []
+    ja_existia: list[dict[str, Any]] = []
+    avisos: list[dict[str, Any]] = []
+    variantes: list[dict[str, Any]] = []
+    conhecidas = list(existentes)
+    for kw in pedidas:
+        estado, existente = classificar(kw, conhecidas)
+        if estado == "repetida":
+            ja_existia.append({**kw, "existente": existente})
+            continue
+        if estado == "coberta":
+            avisos.append({"tipo": "coberta", **kw, "coberta_por": existente})
+        lote.append(kw)
+        conhecidas.append(kw)
+    for kw in pedidas:
+        texto = sem_acento(kw["text"])
+        if texto is None:
+            continue
+        par = {"text": texto, "match_type": kw["match_type"]}
+        if classificar(par, conhecidas + pedidas)[0] != "nova":
+            continue
+        if incluir_variante:
+            lote.append(par)
+            conhecidas.append(par)
+            variantes.append({**par, "variante_de": kw["text"]})
+        else:
+            avisos.append({"tipo": "sem_variante_sem_acento", **kw, "sugestao": texto})
+    return {
+        "lote": lote,
+        "ja_existia": ja_existia,
+        "avisos": avisos,
+        "variantes_incluidas": variantes,
+    }
+
+
+async def _negativas_da_campanha(
+    customer_id: str, campaign_id: str
+) -> tuple[list[dict[str, Any]] | None, str | None]:
+    """As negativas existentes, ou `(None, motivo)` quando a leitura nao mediu."""
+    ctx = get_current()
+    gaql, _ = campaign_negative_keywords_query(campaign_id)
+    try:
+        linhas = await run_report(
+            manager_id=ctx.manager_id,
+            session_id=ctx.session_id,
+            customer_id=customer_id,
+            query=gaql,
+            row_formatter=_negativa_existente,
+            operation_name="add_negative_keywords",
+        )
+    except AccountAccessDeniedError:
+        raise  # acesso negado nao e "cobertura desconhecida": o envelope responde `denied`
+    except (GoogleAdsFriendlyError, QuotaExhausted) as e:
+        log.info("negativas_leitura_previa_falhou", customer_id=customer_id, error=str(e))
+        return None, f"{_MOTIVO_LEITURA_FALHOU}: {e}"
+    except Exception:
+        log.exception("negativas_leitura_previa_falhou", customer_id=customer_id)
+        return None, _MOTIVO_LEITURA_FALHOU
+    return linhas, None
+
 
 @register_tool(
     name="add_negative_keywords",
@@ -43,6 +148,17 @@ _SCHEMA: dict[str, Any] = {
         "[DEFER] Adiciona palavras-chave negativas em nivel de campanha. Sempre auto-aplica "
         "(negativas raramente quebram coisas - spec §7.1). Aceita ate 500 negativas "
         "por chamada com match_type EXACT, PHRASE ou BROAD."
+        " O Google NAO aplica variante proxima em negativa: acento, plural e erro de digitacao"
+        " sao negativas distintas (medido em 05/10: `material de construção` deixou passar"
+        " `material de construcao`). Antes de gravar a tool le as negativas da campanha:"
+        " a de mesmo texto e mesmo tipo sai do lote e vem em `ja_existia` (o Google a"
+        " descartaria em silencio); a coberta por uma mais ampla do mesmo texto (BROAD cobre"
+        " PHRASE e EXACT; PHRASE cobre EXACT) e gravada e vem em `avisos`. A acentuada sem a"
+        " grafia sem acento vem em `avisos` com a `sugestao`; com"
+        " `incluir_variante_sem_acento: true` o par e gravado e listado em"
+        " `variantes_incluidas`. Plural e erro de digitacao NAO sao tratados."
+        " `cobertura_verificada: false` (com `cobertura_motivo`) diz que a leitura previa"
+        " falhou e a tool gravou sem conferir. Nada a gravar responde `status: no_changes`."
     ),
     input_schema=_SCHEMA,
     bucket="defer",
@@ -51,9 +167,32 @@ async def add_negative_keywords(args: dict[str, Any]) -> dict[str, Any]:
     ctx = get_current()
     customer_id = args["customer_id"]
     campaign_id = args["campaign_id"]
-    keywords = args["keywords"]
-    target_count = len(keywords)
 
+    existentes, motivo = await _negativas_da_campanha(customer_id, campaign_id)
+    plano = _planejar(
+        args["keywords"], existentes or [], args.get("incluir_variante_sem_acento", False)
+    )
+    keywords = plano["lote"]
+    relato: dict[str, Any] = {
+        "campaign_id": campaign_id,
+        "ja_existia": plano["ja_existia"],
+        "avisos": plano["avisos"],
+        "variantes_incluidas": plano["variantes_incluidas"],
+        "cobertura_verificada": existentes is not None,
+    }
+    if motivo is not None:
+        relato["cobertura_motivo"] = motivo
+
+    if not keywords:
+        return {
+            "status": "no_changes",
+            "operation": "add_negative_keywords",
+            "customer_id": customer_id,
+            "applied_count": 0,
+            **relato,
+        }
+
+    target_count = len(keywords)
     risk = classify(
         operation="add_negative_keywords",
         params={"target_count": target_count},
@@ -85,6 +224,6 @@ async def add_negative_keywords(args: dict[str, Any]) -> dict[str, Any]:
         applied_count=result["applied_count"],
         provider_request_id=result["provider_request_id"],
         auto_applied_reason=risk.reason,
-        campaign_id=campaign_id,
         resource_names=result.get("resource_names", []),
+        **relato,
     )
diff --git a/tests/integration/test_negative_keywords.py b/tests/integration/test_negative_keywords.py
index 1bd0df1..ec9a43b 100644
--- a/tests/integration/test_negative_keywords.py
+++ b/tests/integration/test_negative_keywords.py
@@ -36,6 +36,13 @@ async def session_ctx(db):
     clear_current()
 
 
+@pytest.fixture
+def sem_negativas():
+    """A leitura previa (spec 2026-10-05 §3.2) acha a campanha sem negativas."""
+    with patch("src.mcp.tools.add_negative_keywords.run_report", AsyncMock(return_value=[])) as rr:
+        yield rr
+
+
 def _fake_client():
     fc = MagicMock()
     fs = MagicMock()
@@ -47,7 +54,7 @@ def _fake_client():
 
 
 @pytest.mark.integration
-async def test_add_negative_keywords_auto_applies_single(db, session_ctx):
+async def test_add_negative_keywords_auto_applies_single(db, session_ctx, sem_negativas):
     from src.mcp.tools.add_negative_keywords import add_negative_keywords
 
     with (
@@ -77,7 +84,7 @@ async def test_add_negative_keywords_auto_applies_single(db, session_ctx):
 
 
 @pytest.mark.integration
-async def test_add_negative_keywords_auto_applies_bulk(db, session_ctx):
+async def test_add_negative_keywords_auto_applies_bulk(db, session_ctx, sem_negativas):
     """Even 100+ negatives auto-apply (spec §7.1: negatives are safe)."""
     from src.mcp.tools.add_negative_keywords import add_negative_keywords
 
@@ -110,7 +117,7 @@ async def test_add_negative_keywords_auto_applies_bulk(db, session_ctx):
 
 
 @pytest.mark.integration
-async def test_add_negative_keywords_summary_lists_match_types(db, session_ctx):
+async def test_add_negative_keywords_summary_lists_match_types(db, session_ctx, sem_negativas):
     from src.mcp.tools.add_negative_keywords import add_negative_keywords
 
     with (
diff --git a/tests/unit/test_add_negative_keywords_cobertura.py b/tests/unit/test_add_negative_keywords_cobertura.py
new file mode 100644
index 0000000..73f9072
--- /dev/null
+++ b/tests/unit/test_add_negative_keywords_cobertura.py
@@ -0,0 +1,238 @@
+"""`add_negative_keywords` com leitura previa, cobertura e acento (spec 2026-10-05, §3.2).
+
+O que vai ao Google se confere pelo `payload` do `run_mutation` — o lote real, nao a resposta.
+"""
+
+from __future__ import annotations
+
+from collections.abc import Iterator
+from typing import Any
+from unittest.mock import AsyncMock, patch
+from uuid import uuid4
+
+import pytest
+
+from src.mcp.context import McpRequestContext, clear_current, set_current
+
+_CONTA = "7862230676"
+_CAMPANHA = "21359547724"
+_MOD = "src.mcp.tools.add_negative_keywords"
+
+
+@pytest.fixture(autouse=True)
+def _ctx() -> Iterator[None]:
+    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
+    yield
+    clear_current()
+
+
+def _existente(texto: str, tipo: str, cid: str = "1745061730") -> dict[str, str]:
+    return {"criterion_id": cid, "text": texto, "match_type": tipo}
+
+
+async def _chamar(
+    existentes: list[dict[str, Any]] | Exception,
+    keywords: list[dict[str, str]],
+    **extra: Any,
+) -> tuple[dict[str, Any], AsyncMock]:
+    from src.mcp.tools.add_negative_keywords import add_negative_keywords
+
+    rr = AsyncMock()
+    if isinstance(existentes, Exception):
+        rr.side_effect = existentes
+    else:
+        rr.return_value = existentes
+    with (
+        patch(f"{_MOD}.run_report", rr),
+        patch(f"{_MOD}.run_mutation", new_callable=AsyncMock) as rm,
+    ):
+        rm.return_value = {"applied_count": 1, "provider_request_id": "req", "resource_names": []}
+        out = await add_negative_keywords(
+            {"customer_id": _CONTA, "campaign_id": _CAMPANHA, "keywords": keywords, **extra}
+        )
+    return out, rm
+
+
+def _lote(rm: AsyncMock) -> list[dict[str, str]]:
+    return list(rm.await_args.kwargs["payload"]["keywords"])
+
+
+def test_formatter_le_a_negativa_da_linha_real() -> None:
+    from google.ads.googleads.v24.common.types.criteria import KeywordInfo
+    from google.ads.googleads.v24.enums.types.keyword_match_type import KeywordMatchTypeEnum
+    from google.ads.googleads.v24.resources.types.campaign_criterion import CampaignCriterion
+    from google.ads.googleads.v24.services.types.google_ads_service import GoogleAdsRow
+
+    from src.mcp.tools.add_negative_keywords import _negativa_existente
+
+    row = GoogleAdsRow(
+        campaign_criterion=CampaignCriterion(
+            criterion_id=1745061730,
+            keyword=KeywordInfo(
+                text="viga metálica", match_type=KeywordMatchTypeEnum.KeywordMatchType.BROAD
+            ),
+        )
+    )
+    assert _negativa_existente(row) == {
+        "criterion_id": "1745061730",
+        "text": "viga metálica",
+        "match_type": "BROAD",
+    }
+
+
+async def test_a_leitura_previa_e_da_campanha_pedida() -> None:
+    from src.mcp.tools.add_negative_keywords import add_negative_keywords
+
+    with (
+        patch(f"{_MOD}.run_report", new_callable=AsyncMock) as rr,
+        patch(f"{_MOD}.run_mutation", new_callable=AsyncMock) as rm,
+    ):
+        rr.return_value = []
+        rm.return_value = {"applied_count": 1, "provider_request_id": "r", "resource_names": []}
+        await add_negative_keywords(
+            {
+                "customer_id": _CONTA,
+                "campaign_id": _CAMPANHA,
+                "keywords": [{"text": "x", "match_type": "BROAD"}],
+            }
+        )
+    q = rr.await_args.kwargs["query"]
+    assert f"campaign.id = {_CAMPANHA}" in q and "campaign_criterion.negative = true" in q
+
+
+async def test_repetida_sai_do_lote_e_vem_em_ja_existia() -> None:
+    e = _existente("Patrol", "BROAD")
+    out, rm = await _chamar(
+        [e], [{"text": "patrol", "match_type": "BROAD"}, {"text": "brita", "match_type": "BROAD"}]
+    )
+    assert _lote(rm) == [{"text": "brita", "match_type": "BROAD"}]
+    assert out["ja_existia"] == [{"text": "patrol", "match_type": "BROAD", "existente": e}]
+    assert out["cobertura_verificada"] is True
+    assert out["status"] == "applied"
+
+
+async def test_repetida_dentro_do_proprio_pedido_vai_uma_vez() -> None:
+    out, rm = await _chamar(
+        [], [{"text": "brita", "match_type": "BROAD"}, {"text": "Brita ", "match_type": "BROAD"}]
+    )
+    assert _lote(rm) == [{"text": "brita", "match_type": "BROAD"}]
+    assert len(out["ja_existia"]) == 1
+
+
+async def test_nada_a_gravar_nao_chama_o_mutate() -> None:
+    out, rm = await _chamar(
+        [_existente("brita", "BROAD")], [{"text": "brita", "match_type": "BROAD"}]
+    )
+    rm.assert_not_awaited()
+    assert out["status"] == "no_changes"
+    assert out["applied_count"] == 0
+    assert len(out["ja_existia"]) == 1
+
+
+async def test_coberta_e_gravada_e_avisada() -> None:
+    ampla = _existente("patrol", "BROAD")
+    out, rm = await _chamar([ampla], [{"text": "patrol", "match_type": "PHRASE"}])
+    assert _lote(rm) == [{"text": "patrol", "match_type": "PHRASE"}]
+    assert out["avisos"] == [
+        {"tipo": "coberta", "text": "patrol", "match_type": "PHRASE", "coberta_por": ampla}
+    ]
+
+
+async def test_acentuada_sem_par_e_avisada_com_a_sugestao() -> None:
+    out, rm = await _chamar([], [{"text": "material de construção", "match_type": "PHRASE"}])
+    assert _lote(rm) == [{"text": "material de construção", "match_type": "PHRASE"}]
+    assert out["avisos"] == [
+        {
+            "tipo": "sem_variante_sem_acento",
+            "text": "material de construção",
+            "match_type": "PHRASE",
+            "sugestao": "material de construcao",
+        }
+    ]
+    assert out["variantes_incluidas"] == []
+
+
+async def test_opt_in_grava_o_par_sem_acento() -> None:
+    out, rm = await _chamar(
+        [],
+        [{"text": "macaco hidráulico", "match_type": "BROAD"}],
+        incluir_variante_sem_acento=True,
+    )
+    assert _lote(rm) == [
+        {"text": "macaco hidráulico", "match_type": "BROAD"},
+        {"text": "macaco hidraulico", "match_type": "BROAD"},
+    ]
+    assert out["variantes_incluidas"] == [
+        {"text": "macaco hidraulico", "match_type": "BROAD", "variante_de": "macaco hidráulico"}
+    ]
+    assert out["avisos"] == []
+
+
+@pytest.mark.parametrize("onde", ["campanha", "pedido"])
+async def test_par_que_ja_existe_nao_gera_aviso_nem_variante(onde: str) -> None:
+    par = {"text": "material de construcao", "match_type": "PHRASE"}
+    existentes = [_existente(par["text"], "PHRASE")] if onde == "campanha" else []
+    pedido = [{"text": "material de construção", "match_type": "PHRASE"}]
+    if onde == "pedido":
+        pedido.append(par)
+    out, rm = await _chamar(existentes, pedido, incluir_variante_sem_acento=True)
+    assert out["avisos"] == [] and out["variantes_incluidas"] == []
+    assert len(_lote(rm)) == (1 if onde == "campanha" else 2)
+
+
+async def test_acesso_negado_na_leitura_previa_propaga() -> None:
+    from src.google_ads.access import AccountAccessDeniedError
+
+    with pytest.raises(AccountAccessDeniedError):
+        await _chamar(
+            AccountAccessDeniedError("sem acesso"), [{"text": "x", "match_type": "BROAD"}]
+        )
+
+
+async def test_falha_amigavel_grava_sem_conferir_e_diz_o_motivo() -> None:
+    from src.governance.rate_limit import QuotaExhausted
+
+    out, rm = await _chamar(
+        QuotaExhausted("cota diaria esgotada"), [{"text": "brita", "match_type": "BROAD"}]
+    )
+    assert _lote(rm) == [{"text": "brita", "match_type": "BROAD"}]
+    assert out["cobertura_verificada"] is False
+    assert "cota diaria esgotada" in out["cobertura_motivo"]
+
+
+async def test_falha_interna_nao_vaza_a_mensagem() -> None:
+    from src.mcp.tools.add_negative_keywords import _MOTIVO_LEITURA_FALHOU
+
+    out, rm = await _chamar(
+        ConnectionRefusedError("connect failed ('10.8.0.5', 5432)"),
+        [{"text": "brita", "match_type": "BROAD"}],
+    )
+    rm.assert_awaited_once()
+    assert out["cobertura_verificada"] is False
+    assert out["cobertura_motivo"] == _MOTIVO_LEITURA_FALHOU
+
+
+async def test_leitura_bem_sucedida_nao_traz_motivo() -> None:
+    out, _ = await _chamar([], [{"text": "brita", "match_type": "BROAD"}])
+    assert "cobertura_motivo" not in out
+
+
+def test_description_diz_o_contrato() -> None:
+    from src.mcp.tools._registry import get_tool, import_all_tools
+
+    import_all_tools()
+    t = get_tool("add_negative_keywords")
+    assert t is not None
+    d = t.description
+    for ancora in (
+        "NAO aplica variante proxima em negativa",
+        "ja_existia",
+        "avisos",
+        "incluir_variante_sem_acento",
+        "variantes_incluidas",
+        "Plural e erro de digitacao NAO sao tratados",
+        "cobertura_verificada: false",
+        "no_changes",
+    ):
+        assert ancora in d, ancora
+    assert "incluir_variante_sem_acento" in t.input_schema["properties"]
diff --git a/tests/unit/test_filters_applied_chega_na_resposta.py b/tests/unit/test_filters_applied_chega_na_resposta.py
index 2e44eb8..0a36664 100644
--- a/tests/unit/test_filters_applied_chega_na_resposta.py
+++ b/tests/unit/test_filters_applied_chega_na_resposta.py
@@ -193,7 +193,10 @@ _MODULOS_DE_QUERY = {
 }
 # O preview do bulk_pause_by_query e um dry-run de mutacao (grava token no banco):
 # o eco dele e conferido em tests/unit/test_bulk_pause_tool.py.
-_FORA_DO_ECO_DE_LEITURA = {"bulk_pause_by_query"}
+# O add_negative_keywords le as negativas da campanha INTEIRA antes de gravar (spec
+# 2026-10-05 §3.2): leitura previa de mutate, sem recorte a declarar — a resposta
+# e o envelope do mutate, nao um relatorio.
+_FORA_DO_ECO_DE_LEITURA = {"bulk_pause_by_query", "add_negative_keywords"}
 
 
 def _tools_que_usam_as_funcoes_de_query() -> set[str]:
diff --git a/tests/unit/test_filters_applied_e_derivado.py b/tests/unit/test_filters_applied_e_derivado.py
index b4ebf77..33b1e32 100644
--- a/tests/unit/test_filters_applied_e_derivado.py
+++ b/tests/unit/test_filters_applied_e_derivado.py
@@ -169,6 +169,7 @@ def _chamadas() -> dict[str, Callable[[], tuple[str, dict[str, Any]]]]:
             _S, _E, 10, min_cost_brl=10.0, min_clicks=5, min_conversions=1.0
         ),
         "negative_keywords_audit_query": lambda: t.negative_keywords_audit_query(),
+        "campaign_negative_keywords_query": lambda: t.campaign_negative_keywords_query("123"),
         "conversion_actions_query": lambda: t.conversion_actions_query(limit=10),
         "funnel_query": lambda: c.funnel_query(_S, _E),
         "top_keywords_query": lambda: c.top_keywords_query(_S, _E, 10, metric="cost"),
```

### Task 3: feat(mcp): add_negatives_from_search_terms avisa termo acentuado sem o par

Spec 2026-10-05 §3.3. Aviso com a sugestao sem acento, nos tres escopos; com
incluir_variante_sem_acento o par e gravado e sai em added com variante_de. O
par so e conferido dentro do proprio pedido e escopo (a tool nao le as existentes).

**Arquivos:**

```text
M	src/mcp/tools/add_negatives_from_search_terms.py
A	tests/unit/test_add_negatives_from_search_terms_acento.py
```

- [ ] Aplicar o bloco, rodar o gate, commitar com a mensagem acima.

```diff
diff --git a/src/mcp/tools/add_negatives_from_search_terms.py b/src/mcp/tools/add_negatives_from_search_terms.py
index 1153e03..abbec5d 100644
--- a/src/mcp/tools/add_negatives_from_search_terms.py
+++ b/src/mcp/tools/add_negatives_from_search_terms.py
@@ -11,6 +11,7 @@ from collections import Counter
 from typing import Any
 
 from src.google_ads.mutations import run_mutation
+from src.google_ads.negativas import classificar, sem_acento
 from src.governance.blast_radius import classify
 from src.mcp.context import get_current
 from src.mcp.tools._common import classify_partial
@@ -44,6 +45,15 @@ _SCHEMA: dict[str, Any] = {
                 "additionalProperties": False,
             },
         },
+        "incluir_variante_sem_acento": {
+            "type": "boolean",
+            "default": False,
+            "description": (
+                "Grava tambem a grafia sem acento de cada termo acentuado (mesmo match type e "
+                "escopo), quando ela nao esta no proprio pedido — o Google nao aplica variante "
+                "proxima em negativa."
+            ),
+        },
     },
     "required": ["customer_id", "negatives"],
     "additionalProperties": False,
@@ -69,6 +79,54 @@ def _build_params_summary(negatives: list[dict[str, Any]]) -> dict[str, Any]:
     }
 
 
+def _variantes_sem_acento(
+    negatives: list[dict[str, Any]], incluir: bool
+) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
+    """Os pares sem acento a gravar (opt-in) e os avisos (spec 2026-10-05, §3.3).
+
+    O "par ja existe" so e conferido DENTRO do pedido, no mesmo escopo: esta tool nao le as
+    negativas existentes antes de gravar.
+    """
+    escopos: dict[tuple[str, str], list[dict[str, Any]]] = {}
+    for n in negatives:
+        escopos.setdefault((n["scope"], n["scope_id"]), []).append(
+            {"text": n["search_term"], "match_type": n.get("match_type", "EXACT")}
+        )
+    variantes: list[dict[str, Any]] = []
+    avisos: list[dict[str, Any]] = []
+    for n in negatives:
+        texto = sem_acento(n["search_term"])
+        if texto is None:
+            continue
+        mt = n.get("match_type", "EXACT")
+        conhecidas = escopos[(n["scope"], n["scope_id"])]
+        if classificar({"text": texto, "match_type": mt}, conhecidas)[0] != "nova":
+            continue
+        if incluir:
+            conhecidas.append({"text": texto, "match_type": mt})
+            variantes.append(
+                {
+                    "search_term": texto,
+                    "match_type": mt,
+                    "scope": n["scope"],
+                    "scope_id": n["scope_id"],
+                    "variante_de": n["search_term"],
+                }
+            )
+        else:
+            avisos.append(
+                {
+                    "tipo": "sem_variante_sem_acento",
+                    "search_term": n["search_term"],
+                    "match_type": mt,
+                    "scope": n["scope"],
+                    "scope_id": n["scope_id"],
+                    "sugestao": texto,
+                }
+            )
+    return variantes, avisos
+
+
 @register_tool(
     name="add_negatives_from_search_terms",
     description=(
@@ -77,6 +135,11 @@ def _build_params_summary(negatives: list[dict[str, Any]]) -> dict[str, Any]:
         "(spec §7.1) — idempotente: termos ja existentes retornam status "
         "'already_exists' sem falha. Use apos get_search_terms_report pra picar "
         "termos performando mal e exclui-los do leilao."
+        " O Google NAO aplica variante proxima em negativa: termo acentuado sem a grafia"
+        " sem acento no mesmo pedido e escopo vem em `avisos` com a `sugestao`; com"
+        " `incluir_variante_sem_acento: true` o par e gravado e sai em `added` com"
+        " `variante_de`. A tool nao le as negativas existentes: o par so e conferido"
+        " dentro do proprio pedido. Plural e erro de digitacao NAO sao tratados."
     ),
     input_schema=_SCHEMA,
     bucket="defer",
@@ -84,7 +147,10 @@ def _build_params_summary(negatives: list[dict[str, Any]]) -> dict[str, Any]:
 async def add_negatives_from_search_terms(args: dict[str, Any]) -> dict[str, Any]:
     ctx = get_current()
     customer_id = args["customer_id"]
-    negatives = args["negatives"]
+    variantes, avisos = _variantes_sem_acento(
+        args["negatives"], args.get("incluir_variante_sem_acento", False)
+    )
+    negatives = [*args["negatives"], *variantes]
     target_count = len(negatives)
 
     risk = classify(
@@ -92,7 +158,7 @@ async def add_negatives_from_search_terms(args: dict[str, Any]) -> dict[str, Any
         params={"target_count": target_count},
     )
 
-    payload = {"negatives": negatives}
+    payload = {"negatives": [{k: v for k, v in n.items() if k != "variante_de"} for n in negatives]}
     params_summary = _build_params_summary(negatives)
 
     result = await run_mutation(
@@ -126,6 +192,8 @@ async def add_negatives_from_search_terms(args: dict[str, Any]) -> dict[str, Any
             "scope_id": n["scope_id"],
             "status": row_status,
         }
+        if "variante_de" in n:
+            item["variante_de"] = n["variante_de"]
         if per_op and per_op["error"] and row_status == "failed":
             item["error"] = per_op["error"]
         added.append(item)
@@ -148,4 +216,5 @@ async def add_negatives_from_search_terms(args: dict[str, Any]) -> dict[str, Any
         provider_request_id=result["provider_request_id"],
         auto_applied_reason=risk.reason,
         added=added,
+        avisos=avisos,
     )
diff --git a/tests/unit/test_add_negatives_from_search_terms_acento.py b/tests/unit/test_add_negatives_from_search_terms_acento.py
new file mode 100644
index 0000000..e295c16
--- /dev/null
+++ b/tests/unit/test_add_negatives_from_search_terms_acento.py
@@ -0,0 +1,101 @@
+"""`add_negatives_from_search_terms`: acento (spec 2026-10-05, §3.3).
+
+O que vai ao Google se confere pelo `payload` do `run_mutation`.
+"""
+
+from __future__ import annotations
+
+from collections.abc import Iterator
+from typing import Any
+from unittest.mock import AsyncMock, patch
+from uuid import uuid4
+
+import pytest
+
+from src.mcp.context import McpRequestContext, clear_current, set_current
+
+_MOD = "src.mcp.tools.add_negatives_from_search_terms"
+
+
+@pytest.fixture(autouse=True)
+def _ctx() -> Iterator[None]:
+    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
+    yield
+    clear_current()
+
+
+async def _chamar(negatives: list[dict[str, Any]], **extra: Any) -> tuple[dict[str, Any], Any]:
+    from src.mcp.tools.add_negatives_from_search_terms import add_negatives_from_search_terms
+
+    with patch(f"{_MOD}.run_mutation", new_callable=AsyncMock) as rm:
+        rm.return_value = {"applied_count": 1, "provider_request_id": "r", "partial_failures": []}
+        out = await add_negatives_from_search_terms(
+            {"customer_id": "7862230676", "negatives": negatives, **extra}
+        )
+    return out, rm.await_args.kwargs["payload"]["negatives"]
+
+
+def _n(termo: str, scope: str = "campaign", sid: str = "1", mt: str = "PHRASE") -> dict[str, str]:
+    return {"search_term": termo, "match_type": mt, "scope": scope, "scope_id": sid}
+
+
+@pytest.mark.parametrize("scope", ["campaign", "ad_group", "shared_set"])
+async def test_acentuado_sem_par_e_avisado_em_todo_escopo(scope: str) -> None:
+    out, lote = await _chamar([_n("material de construção", scope)])
+    assert lote == [_n("material de construção", scope)]
+    assert out["avisos"] == [
+        {
+            "tipo": "sem_variante_sem_acento",
+            "search_term": "material de construção",
+            "match_type": "PHRASE",
+            "scope": scope,
+            "scope_id": "1",
+            "sugestao": "material de construcao",
+        }
+    ]
+
+
+@pytest.mark.parametrize("scope", ["campaign", "ad_group", "shared_set"])
+async def test_opt_in_grava_o_par_no_mesmo_escopo(scope: str) -> None:
+    out, lote = await _chamar([_n("hidráulico", scope)], incluir_variante_sem_acento=True)
+    assert lote == [_n("hidráulico", scope), _n("hidraulico", scope)]
+    assert out["avisos"] == []
+    variante = out["added"][1]
+    assert variante["search_term"] == "hidraulico"
+    assert variante["variante_de"] == "hidráulico"
+    assert "variante_de" not in out["added"][0]
+
+
+async def test_par_no_mesmo_pedido_e_escopo_nao_gera_aviso() -> None:
+    out, lote = await _chamar(
+        [_n("construção"), _n("construcao")], incluir_variante_sem_acento=True
+    )
+    assert out["avisos"] == []
+    assert len(lote) == 2
+
+
+async def test_par_em_outro_escopo_nao_conta() -> None:
+    out, _ = await _chamar([_n("construção", sid="1"), _n("construcao", sid="2")])
+    assert [a["scope_id"] for a in out["avisos"]] == ["1"]
+
+
+async def test_o_payload_nao_leva_a_chave_interna() -> None:
+    _, lote = await _chamar([_n("construção")], incluir_variante_sem_acento=True)
+    assert all("variante_de" not in n for n in lote)
+
+
+def test_description_e_schema() -> None:
+    from src.mcp.tools._registry import get_tool, import_all_tools
+
+    import_all_tools()
+    t = get_tool("add_negatives_from_search_terms")
+    assert t is not None
+    for ancora in (
+        "NAO aplica variante proxima em negativa",
+        "incluir_variante_sem_acento",
+        "variante_de",
+        "so e conferido dentro do proprio pedido",
+        "Plural e erro de digitacao NAO sao tratados",
+    ):
+        assert ancora in t.description, ancora
+    assert "incluir_variante_sem_acento" in t.input_schema["properties"]
```

### Task 4: feat(mcp): run_gaql compact - linhas planas sem os resource_name implicitos

Spec 2026-10-05 §3.4. O Google manda o resource_name de cada objeto da linha
mesmo fora do SELECT; compact: true achata e tira so os nao pedidos (-39% medido
numa consulta de campaign_criterion). SELECT ilegivel: so achata. Default false.

**Arquivos:**

```text
A	src/google_ads/gaql_compacto.py
M	src/mcp/tools/run_gaql.py
A	tests/unit/test_run_gaql_compacto.py
```

- [ ] Aplicar o bloco, rodar o gate, commitar com a mensagem acima.

```diff
diff --git a/src/google_ads/gaql_compacto.py b/src/google_ads/gaql_compacto.py
new file mode 100644
index 0000000..1c19448
--- /dev/null
+++ b/src/google_ads/gaql_compacto.py
@@ -0,0 +1,41 @@
+"""Linha plana do `run_gaql` com `compact: true` (spec 2026-10-05, §3.4).
+
+O `MessageToDict` devolve o `resource_name` de cada objeto da linha mesmo fora do SELECT — e
+isso, mais o aninhamento, incha a saída (medido em 05/10: −39% numa amostra de
+`campaign_criterion`). Só sai o `resource_name` que o SELECT NÃO pediu; se a lista do SELECT
+não puder ser lida, nenhum sai (falha segura: achatar sem perder campo pedido).
+"""
+
+import re
+from typing import Any
+
+_SELECT = re.compile(r"\bSELECT\b(.*?)\bFROM\b", re.IGNORECASE | re.DOTALL)
+
+
+def campos_do_select(query: str) -> set[str] | None:
+    """Os campos entre SELECT e FROM, em minúsculas — ou `None` quando não dá para ler."""
+    # `findall`, nao `.search`: o guard do F86 acusa qualquer chamada de atributo com o nome
+    # do metodo bloqueante do SDK (`ga_service.search`), e esta funcao roda no event loop.
+    achados = _SELECT.findall(query)
+    if not achados:
+        return None
+    campos = {c.strip().lower() for c in achados[0].split(",") if c.strip()}
+    return campos or None
+
+
+def linha_compacta(linha: dict[str, Any], pedidos: set[str] | None) -> dict[str, Any]:
+    """`{"campaign": {"id": "1"}}` → `{"campaign.id": "1"}`, sem os `resource_name` implícitos."""
+    plana: dict[str, Any] = {}
+
+    def _desce(no: dict[str, Any], prefixo: str) -> None:
+        for k, v in no.items():
+            caminho = f"{prefixo}{k}"
+            if isinstance(v, dict):
+                _desce(v, f"{caminho}.")
+                continue
+            if k == "resource_name" and pedidos is not None and caminho.lower() not in pedidos:
+                continue
+            plana[caminho] = v
+
+    _desce(linha, "")
+    return plana
diff --git a/src/mcp/tools/run_gaql.py b/src/mcp/tools/run_gaql.py
index d810fbc..4c4dd3f 100644
--- a/src/mcp/tools/run_gaql.py
+++ b/src/mcp/tools/run_gaql.py
@@ -8,6 +8,7 @@ GROUP BY + COUNT (resolve B5 token overflow em queries densas).
 from typing import Any
 
 from src.google_ads.aggregation import aggregate_rows
+from src.google_ads.gaql_compacto import campos_do_select, linha_compacta
 from src.google_ads.reports import execute_gaql_raw
 from src.mcp.context import get_current
 from src.mcp.tools._registry import register_tool
@@ -45,6 +46,14 @@ _SCHEMA: dict[str, Any] = {
                 "DESC ao inves de rows[]. Limite hard: 10k raw rows antes de agregar."
             ),
         },
+        "compact": {
+            "type": "boolean",
+            "default": False,
+            "description": (
+                'Linhas planas com chave pontilhada ({"campaign.id": ...}) e sem os '
+                "resource_name que o SELECT nao pediu. Ignorado com aggregate_by."
+            ),
+        },
     },
     "required": ["customer_id", "query"],
     "additionalProperties": False,
@@ -67,6 +76,11 @@ _MAX_RAW_ROWS_FOR_AGGREGATE = 10_000
         "chame list_gaql_resources (catálogo válido) ou validate_gaql (valida sem "
         "executar) ANTES — métricas existem só em certos recursos e auction insights "
         "(overlap/position-above/outranking share) não existem na GAQL."
+        ' `compact: true` devolve linhas planas (`{"campaign.id": ..., "metrics.clicks":'
+        " ...}`) sem os `resource_name` que o Google manda em todo objeto da linha mesmo"
+        " fora do SELECT (o pedido no SELECT fica): -39% medido em 05/10 numa consulta de"
+        " campaign_criterion — o ganho depende da consulta (linha cheia de metricas ganha"
+        " menos). Use quando a resposta estoura o limite do cliente."
     ),
     input_schema=_SCHEMA,
     bucket="always",
@@ -107,11 +121,15 @@ async def run_gaql(args: dict[str, Any]) -> dict[str, Any]:
         }
 
     truncated = len(rows) > limit
+    linhas = rows[:limit]
+    if args.get("compact", False):
+        pedidos = campos_do_select(query)
+        linhas = [linha_compacta(r, pedidos) for r in linhas]
     result: dict[str, Any] = {
         "customer_id": customer_id,
         "row_count": len(rows),
         "truncated": truncated,
-        "rows": rows[:limit],
+        "rows": linhas,
         "returned": min(len(rows), limit),
     }
     if truncated:
diff --git a/tests/unit/test_run_gaql_compacto.py b/tests/unit/test_run_gaql_compacto.py
new file mode 100644
index 0000000..dc58f83
--- /dev/null
+++ b/tests/unit/test_run_gaql_compacto.py
@@ -0,0 +1,111 @@
+"""`run_gaql` com `compact: true` (spec 2026-10-05, §3.4).
+
+A linha de entrada vem de `GoogleAdsRow` real pelo MESMO `MessageToDict` do `execute_gaql_raw`:
+o `resource_name` implícito que se quer tirar só existe na mensagem real.
+"""
+
+from __future__ import annotations
+
+from collections.abc import Iterator
+from typing import Any
+from unittest.mock import AsyncMock, patch
+from uuid import uuid4
+
+import pytest
+from google.protobuf.json_format import MessageToDict
+
+from src.google_ads.gaql_compacto import campos_do_select, linha_compacta
+from src.mcp.context import McpRequestContext, clear_current, set_current
+
+_Q = (
+    "SELECT campaign.id, campaign_criterion.criterion_id, campaign_criterion.keyword.text "
+    "FROM campaign_criterion WHERE campaign_criterion.negative = TRUE"
+)
+
+
+def _linha_real() -> dict[str, Any]:
+    from google.ads.googleads.v24.common.types.criteria import KeywordInfo
+    from google.ads.googleads.v24.resources.types.campaign import Campaign
+    from google.ads.googleads.v24.resources.types.campaign_criterion import CampaignCriterion
+    from google.ads.googleads.v24.services.types.google_ads_service import GoogleAdsRow
+
+    row = GoogleAdsRow(
+        campaign=Campaign(resource_name="customers/1/campaigns/2", id=2),
+        campaign_criterion=CampaignCriterion(
+            resource_name="customers/1/campaignCriteria/2~3",
+            criterion_id=3,
+            keyword=KeywordInfo(text="brita"),
+        ),
+    )
+    return MessageToDict(row._pb, preserving_proto_field_name=True)  # type: ignore[no-any-return]
+
+
+def test_a_linha_real_traz_resource_name_que_o_select_nao_pediu() -> None:
+    """Controle: sem isto o teste abaixo nao prova nada."""
+    linha = _linha_real()
+    assert linha["campaign"]["resource_name"] == "customers/1/campaigns/2"
+
+
+def test_compacta_achata_e_tira_o_resource_name_implicito() -> None:
+    assert linha_compacta(_linha_real(), campos_do_select(_Q)) == {
+        "campaign.id": "2",
+        "campaign_criterion.criterion_id": "3",
+        "campaign_criterion.keyword.text": "brita",
+    }
+
+
+def test_resource_name_pedido_no_select_fica() -> None:
+    q = _Q.replace("campaign.id,", "campaign.id, Campaign_Criterion.Resource_Name,")
+    plana = linha_compacta(_linha_real(), campos_do_select(q))
+    assert plana["campaign_criterion.resource_name"] == "customers/1/campaignCriteria/2~3"
+    assert "campaign.resource_name" not in plana
+
+
+def test_select_ilegivel_nao_tira_nada() -> None:
+    assert campos_do_select("FROM campaign") is None
+    plana = linha_compacta(_linha_real(), None)
+    assert plana["campaign.resource_name"] == "customers/1/campaigns/2"
+    assert plana["campaign_criterion.resource_name"] == "customers/1/campaignCriteria/2~3"
+
+
+@pytest.fixture
+def _ctx() -> Iterator[None]:
+    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
+    yield
+    clear_current()
+
+
+async def _rodar(**args: Any) -> dict[str, Any]:
+    from src.mcp.tools.run_gaql import run_gaql
+
+    linhas = [_linha_real(), _linha_real(), _linha_real()]
+    with patch("src.mcp.tools.run_gaql.execute_gaql_raw", AsyncMock(return_value=linhas)):
+        return await run_gaql({"customer_id": "7862230676", "query": _Q, **args})
+
+
+@pytest.mark.usefixtures("_ctx")
+async def test_a_tool_compacta_e_conta_as_linhas_de_antes_do_corte() -> None:
+    out = await _rodar(compact=True, limit=2)
+    assert out["row_count"] == 3 and out["returned"] == 2 and out["truncated"] is True
+    assert out["rows"][0] == {
+        "campaign.id": "2",
+        "campaign_criterion.criterion_id": "3",
+        "campaign_criterion.keyword.text": "brita",
+    }
+
+
+@pytest.mark.usefixtures("_ctx")
+async def test_sem_compact_a_resposta_nao_muda() -> None:
+    out = await _rodar()
+    assert out["rows"][0] == _linha_real()
+
+
+def test_description_e_schema() -> None:
+    from src.mcp.tools._registry import get_tool, import_all_tools
+
+    import_all_tools()
+    t = get_tool("run_gaql")
+    assert t is not None
+    assert "compact: true" in t.description and "-39%" in t.description
+    assert "o ganho depende da consulta" in t.description
+    assert t.input_schema["properties"]["compact"]["default"] is False
```

### Task 5: docs(mcp): detect_drift e get_change_history dizem que a recomendacao aceita pelo app e indistinguivel

Spec 2026-10-05 §3.5. Sondado em 05/10 no change_event da MO-JP: client_type
GOOGLE_ADS_MOBILE_APP + e-mail do gestor, sem campo de origem. A aceitacao pela
UI web nao foi medida e a description nao afirma nada sobre ela (spec corrigida).

**Arquivos:**

```text
M	docs/superpowers/specs/2026-10-05-negativas-e-gaql-compacto-design.md
M	src/mcp/tools/detect_drift.py
M	src/mcp/tools/get_change_history.py
A	tests/unit/test_recomendacao_aceita_pelo_app.py
```

- [ ] Aplicar o bloco, rodar o gate, commitar com a mensagem acima.

```diff
diff --git a/docs/superpowers/specs/2026-10-05-negativas-e-gaql-compacto-design.md b/docs/superpowers/specs/2026-10-05-negativas-e-gaql-compacto-design.md
index 0f2a4e9..d9239b1 100644
--- a/docs/superpowers/specs/2026-10-05-negativas-e-gaql-compacto-design.md
+++ b/docs/superpowers/specs/2026-10-05-negativas-e-gaql-compacto-design.md
@@ -114,9 +114,11 @@ variante gravada sai no `added[]` com `variante_de: <termo original>`. Não há
 
 ### 3.5 Descriptions do `detect_drift` e do `get_change_history`
 
-Uma frase em cada uma: recomendação aceita à mão (app ou web) sai com o `client_type` do cliente e o
-e-mail do gestor, igual a uma edição manual (sondado em 05/10). Só o auto-apply sai como
-`GOOGLE_ADS_RECOMMENDATIONS`.
+Uma frase em cada uma: recomendação aceita à mão **pelo app de celular** sai com
+`client_type: GOOGLE_ADS_MOBILE_APP` e o e-mail do gestor, igual a uma edição manual (sondado em
+05/10). A aceitação pela UI web de Recomendações **não foi medida**: o comentário existente no
+`get_change_history` diz que ela pode sair como `GOOGLE_ADS_RECOMMENDATIONS`, igual ao auto-apply,
+e a description não afirma nada sobre ela.
 
 ## 4. Testes e guards
 
diff --git a/src/mcp/tools/detect_drift.py b/src/mcp/tools/detect_drift.py
index bd9daf0..703d972 100644
--- a/src/mcp/tools/detect_drift.py
+++ b/src/mcp/tools/detect_drift.py
@@ -318,7 +318,10 @@ async def _varrer(customer_id: str, *, inicio: date, fim: date, hoje: date) -> _
         "[CORE] Detecta mudanças NÃO-autorizadas em conta Google Ads (workflow "
         "co-management V4 pós-batch). Compara change_event com lista de "
         "responsible_user_emails: tudo NÃO-listado conta como drift. Auto-apply "
-        "Recommendations sempre conta como drift. Output: summary (count + "
+        "Recommendations sempre conta como drift. Recomendacao aceita a mao pelo APP de "
+        "celular sai com client_type GOOGLE_ADS_MOBILE_APP e o e-mail do gestor, igual a "
+        "uma edicao manual (sondado em 05/10: nenhum campo do change_event a distingue) — "
+        "se o gestor esta na lista, ela nao conta como drift. Output: summary (count + "
         "by_user/resource/operation) + freshness (fronteira de indexacao "
         "medida) + flags[] (auto_apply_detected, "
         "multiple_users_detected, structural_change, status_change_detected) + "
diff --git a/src/mcp/tools/get_change_history.py b/src/mcp/tools/get_change_history.py
index 75a71fe..0f8ce03 100644
--- a/src/mcp/tools/get_change_history.py
+++ b/src/mcp/tools/get_change_history.py
@@ -366,6 +366,9 @@ async def _resolve_names(
         "filtros opcionais (resource_types, operation_types, user_emails, "
         "client_types). Util pra auditoria 'CRITICO antes de tudo': detectar "
         "auto-apply Recommendations, mudancas estruturais, e quem mexeu no que. "
+        "Recomendacao aceita a mao pelo APP de celular sai com client_type "
+        "GOOGLE_ADS_MOBILE_APP e o e-mail do gestor, igual a uma edicao manual (sondado em "
+        "05/10: nenhum campo do change_event a distingue). "
         "ATENCAO: change_event e audit log LAGGING e o lag NAO tem contrato "
         "— medido de ~3h a >4 dias na MESMA conta. Por isso a resposta traz "
         "`freshness` com a fronteira MEDIDA: `account_frontier` (evento mais "
diff --git a/tests/unit/test_recomendacao_aceita_pelo_app.py b/tests/unit/test_recomendacao_aceita_pelo_app.py
new file mode 100644
index 0000000..bbef9bb
--- /dev/null
+++ b/tests/unit/test_recomendacao_aceita_pelo_app.py
@@ -0,0 +1,22 @@
+"""Recomendação aceita à mão pelo app sai igual a edição manual (spec 2026-10-05, §3.5).
+
+Sondado em 05/10 no `change_event` da MO-JP (03/10 17:43, `acabadora de piso` e `locação de
+sapinho`): `client_type: GOOGLE_ADS_MOBILE_APP`, o e-mail do gestor, `changed_fields` de qualquer
+criação de keyword — nenhum campo de origem. As duas tools que leem o `change_event` dizem isso.
+"""
+
+import pytest
+
+from src.mcp.tools._registry import get_tool, import_all_tools
+
+
+@pytest.mark.parametrize("nome", ["detect_drift", "get_change_history"])
+def test_a_description_diz_que_a_aceita_pelo_app_e_indistinguivel(nome: str) -> None:
+    import_all_tools()
+    t = get_tool(nome)
+    assert t is not None
+    d = t.description
+    assert "Recomendacao aceita a mao pelo APP" in d
+    assert "GOOGLE_ADS_MOBILE_APP" in d
+    assert "nenhum campo do change_event a distingue" in d
+    assert "web" not in d.lower().split("recomendacao aceita a mao")[1][:200]
```

### Task 6: fix(mcp): rodada da revisao final - compact mantem o que mora no campo pedido, cobertura sem depender da ordem

- I1: compact mantem resource_name dentro de campo-mensagem pedido no SELECT
  (change_event.old_resource); M8: mensagem vazia pedida fica.
- I2: add_negatives_from_search_terms nao promete mais already_exists - o Google
  descarta a duplicata em silencio (catalogo A1) e ela volta added.
- M1: chave em NFC; M6: existente com match_type fora do enum nao derruba.
- M3: cobertura dentro do pedido independe da ordem; M4: aviso de acento nao
  duplica (nas duas tools); M5: ja_existia[].origem (campanha|pedido).
- M2: descriptions dizem que o opt-in pode dobrar o lote; M9: -39% numa amostra
  de linhas; M10: blast_summary separa as variantes; M7: teste do friendly do Google.

24 sabotagens de copia caem sobre o codigo final.

**Arquivos:**

```text
M	src/google_ads/gaql_compacto.py
M	src/google_ads/negativas.py
M	src/mcp/tools/add_negative_keywords.py
M	src/mcp/tools/add_negatives_from_search_terms.py
M	src/mcp/tools/run_gaql.py
M	tests/unit/test_add_negative_keywords_cobertura.py
A	tests/unit/test_negativas_rodada_revisao.py
```

- [ ] Aplicar o bloco, rodar o gate, commitar com a mensagem acima.

```diff
diff --git a/src/google_ads/gaql_compacto.py b/src/google_ads/gaql_compacto.py
index 1c19448..b4255eb 100644
--- a/src/google_ads/gaql_compacto.py
+++ b/src/google_ads/gaql_compacto.py
@@ -27,13 +27,21 @@ def linha_compacta(linha: dict[str, Any], pedidos: set[str] | None) -> dict[str,
     """`{"campaign": {"id": "1"}}` → `{"campaign.id": "1"}`, sem os `resource_name` implícitos."""
     plana: dict[str, Any] = {}
 
+    def _pedido(caminho: str) -> bool:
+        # O campo pedido E tudo o que mora dentro dele: `SELECT change_event.old_resource`
+        # pede o `old_resource.campaign.resource_name` junto (revisao 05/10, I1).
+        c = caminho.lower()
+        return pedidos is None or any(c == p or c.startswith(p + ".") for p in pedidos)
+
     def _desce(no: dict[str, Any], prefixo: str) -> None:
         for k, v in no.items():
             caminho = f"{prefixo}{k}"
-            if isinstance(v, dict):
+            if isinstance(v, dict) and v:
                 _desce(v, f"{caminho}.")
                 continue
-            if k == "resource_name" and pedidos is not None and caminho.lower() not in pedidos:
+            if isinstance(v, dict) and not _pedido(caminho):
+                continue  # mensagem vazia que ninguem pediu
+            if k == "resource_name" and not _pedido(caminho):
                 continue
             plana[caminho] = v
 
diff --git a/src/google_ads/negativas.py b/src/google_ads/negativas.py
index 5149c98..7a222cd 100644
--- a/src/google_ads/negativas.py
+++ b/src/google_ads/negativas.py
@@ -25,8 +25,12 @@ def sem_acento(texto: str) -> str | None:
 
 
 def chave(texto: str) -> str:
-    """Chave de comparação: minúsculas e espaços colapsados — o acento fica."""
-    return " ".join(texto.lower().split())
+    """Chave de comparação: NFC, minúsculas e espaços colapsados — o acento fica.
+
+    NFC porque o mesmo `ç` chega composto ou decomposto (NFD), e os dois são a mesma
+    negativa para o Google.
+    """
+    return " ".join(unicodedata.normalize("NFC", texto).lower().split())
 
 
 def classificar(
@@ -37,13 +41,13 @@ def classificar(
     `nova` e cada existente têm `text` e `match_type`. Repetida vence coberta.
     """
     alvo = chave(nova["text"])
-    amplitude = AMPLITUDE[nova["match_type"]]
+    amplitude = AMPLITUDE[nova["match_type"]]  # o schema restringe ao enum
     cobre: dict[str, Any] | None = None
     for e in existentes:
         if chave(e["text"]) != alvo:
             continue
         if e["match_type"] == nova["match_type"]:
             return "repetida", e
-        if cobre is None and AMPLITUDE[e["match_type"]] > amplitude:
+        if cobre is None and AMPLITUDE.get(e["match_type"], -1) > amplitude:
             cobre = e
     return ("coberta", cobre) if cobre is not None else ("nova", None)
diff --git a/src/mcp/tools/add_negative_keywords.py b/src/mcp/tools/add_negative_keywords.py
index af40cc4..2905e53 100644
--- a/src/mcp/tools/add_negative_keywords.py
+++ b/src/mcp/tools/add_negative_keywords.py
@@ -15,7 +15,7 @@ import structlog
 from src.google_ads.access import AccountAccessDeniedError
 from src.google_ads.errors import GoogleAdsFriendlyError
 from src.google_ads.mutations import run_mutation
-from src.google_ads.negativas import classificar, sem_acento
+from src.google_ads.negativas import chave, classificar, sem_acento
 from src.google_ads.queries.tactical import campaign_negative_keywords_query
 from src.google_ads.reports import run_report
 from src.governance.blast_radius import classify
@@ -89,13 +89,22 @@ def _planejar(
     for kw in pedidas:
         estado, existente = classificar(kw, conhecidas)
         if estado == "repetida":
-            ja_existia.append({**kw, "existente": existente})
+            origem = "campanha" if any(existente is e for e in existentes) else "pedido"
+            ja_existia.append({**kw, "existente": existente, "origem": origem})
             continue
-        if estado == "coberta":
-            avisos.append({"tipo": "coberta", **kw, "coberta_por": existente})
         lote.append(kw)
         conhecidas.append(kw)
+    # Cobertura DEPOIS do lote montado: contra a campanha e o resto do pedido, em qualquer
+    # ordem — `[PHRASE x, BROAD x]` e `[BROAD x, PHRASE x]` dizem o mesmo.
+    for kw in lote:
+        estado, existente = classificar(kw, [c for c in conhecidas if c is not kw])
+        if estado == "coberta":
+            avisos.append({"tipo": "coberta", **kw, "coberta_por": existente})
+    vistas: set[tuple[str, str]] = set()
     for kw in pedidas:
+        if (chave(kw["text"]), kw["match_type"]) in vistas:
+            continue
+        vistas.add((chave(kw["text"]), kw["match_type"]))
         texto = sem_acento(kw["text"])
         if texto is None:
             continue
@@ -156,7 +165,9 @@ async def _negativas_da_campanha(
         " PHRASE e EXACT; PHRASE cobre EXACT) e gravada e vem em `avisos`. A acentuada sem a"
         " grafia sem acento vem em `avisos` com a `sugestao`; com"
         " `incluir_variante_sem_acento: true` o par e gravado e listado em"
-        " `variantes_incluidas`. Plural e erro de digitacao NAO sao tratados."
+        " `variantes_incluidas` — o opt-in pode dobrar o lote (ate 1000 operacoes por"
+        " chamada). `ja_existia[].origem` diz se a repetida ja estava na `campanha` ou"
+        " veio duas vezes no `pedido`. Plural e erro de digitacao NAO sao tratados."
         " `cobertura_verificada: false` (com `cobertura_motivo`) diz que a leitura previa"
         " falhou e a tool gravou sem conferir. Nada a gravar responde `status: no_changes`."
     ),
diff --git a/src/mcp/tools/add_negatives_from_search_terms.py b/src/mcp/tools/add_negatives_from_search_terms.py
index abbec5d..1ae8845 100644
--- a/src/mcp/tools/add_negatives_from_search_terms.py
+++ b/src/mcp/tools/add_negatives_from_search_terms.py
@@ -3,15 +3,16 @@
 
 Workflow: gestor calls get_search_terms_report -> picks bad terms -> passes them
 here with scope (campaign / ad_group / shared_set) for each. Auto-applies
-(negatives are safe per spec §7.1). Up to 500 per call. Returns per-row status
-including 'already_exists' for terms that were already negatives (idempotent).
+(negatives are safe per spec §7.1). Up to 500 per call. Returns per-row status;
+'already_exists' only when Google reports the duplicate — it usually drops it
+silently and the row comes back 'added' (catalogo A1, revisao 05/10).
 """
 
 from collections import Counter
 from typing import Any
 
 from src.google_ads.mutations import run_mutation
-from src.google_ads.negativas import classificar, sem_acento
+from src.google_ads.negativas import chave, classificar, sem_acento
 from src.governance.blast_radius import classify
 from src.mcp.context import get_current
 from src.mcp.tools._common import classify_partial
@@ -94,11 +95,16 @@ def _variantes_sem_acento(
         )
     variantes: list[dict[str, Any]] = []
     avisos: list[dict[str, Any]] = []
+    vistos: set[tuple[str, str, str, str]] = set()
     for n in negatives:
+        mt = n.get("match_type", "EXACT")
+        visto = (n["scope"], n["scope_id"], chave(n["search_term"]), mt)
+        if visto in vistos:
+            continue
+        vistos.add(visto)
         texto = sem_acento(n["search_term"])
         if texto is None:
             continue
-        mt = n.get("match_type", "EXACT")
         conhecidas = escopos[(n["scope"], n["scope_id"])]
         if classificar({"text": texto, "match_type": mt}, conhecidas)[0] != "nova":
             continue
@@ -132,13 +138,15 @@ def _variantes_sem_acento(
     description=(
         "[DEFER] Adiciona negativas derivadas do search_terms_report em batch. Aceita "
         "ate 500 termos com scope campaign|ad_group|shared_set. Sempre auto-aplica "
-        "(spec §7.1) — idempotente: termos ja existentes retornam status "
-        "'already_exists' sem falha. Use apos get_search_terms_report pra picar "
-        "termos performando mal e exclui-los do leilao."
+        "(spec §7.1). Termo que ja e negativa: o Google normalmente o descarta em silencio "
+        "(catalogo A1) e ele volta como 'added', nao 'already_exists' — 'already_exists' "
+        "so aparece quando o Google reporta a duplicata. Use apos get_search_terms_report "
+        "pra picar termos performando mal e exclui-los do leilao."
         " O Google NAO aplica variante proxima em negativa: termo acentuado sem a grafia"
         " sem acento no mesmo pedido e escopo vem em `avisos` com a `sugestao`; com"
         " `incluir_variante_sem_acento: true` o par e gravado e sai em `added` com"
-        " `variante_de`. A tool nao le as negativas existentes: o par so e conferido"
+        " `variante_de` — o opt-in pode dobrar o lote (ate 1000 operacoes por chamada)."
+        " A tool nao le as negativas existentes: o par so e conferido"
         " dentro do proprio pedido. Plural e erro de digitacao NAO sao tratados."
     ),
     input_schema=_SCHEMA,
@@ -209,7 +217,9 @@ async def add_negatives_from_search_terms(args: dict[str, Any]) -> dict[str, Any
     return applied_envelope(
         "add_negatives_from_search_terms",
         customer_id,
-        f"Adicionar {target_count} negativa(s) derivada(s) do search_terms_report: "
+        f"Adicionar {target_count - len(variantes)} negativa(s) derivada(s) do "
+        f"search_terms_report"
+        f"{f' + {len(variantes)} variante(s) sem acento' if variantes else ''}: "
         f"{result['applied_count']} aceita(s) pelo Google, {ja_existiam} ja existia(m), "
         f"{recusadas} recusada(s).",
         applied_count=result["applied_count"],
diff --git a/src/mcp/tools/run_gaql.py b/src/mcp/tools/run_gaql.py
index 4c4dd3f..af717db 100644
--- a/src/mcp/tools/run_gaql.py
+++ b/src/mcp/tools/run_gaql.py
@@ -78,7 +78,7 @@ _MAX_RAW_ROWS_FOR_AGGREGATE = 10_000
         "(overlap/position-above/outranking share) não existem na GAQL."
         ' `compact: true` devolve linhas planas (`{"campaign.id": ..., "metrics.clicks":'
         " ...}`) sem os `resource_name` que o Google manda em todo objeto da linha mesmo"
-        " fora do SELECT (o pedido no SELECT fica): -39% medido em 05/10 numa consulta de"
+        " fora do SELECT (o pedido no SELECT fica, com tudo o que mora dentro dele): -39% medido em 05/10 numa amostra de linhas de"
         " campaign_criterion — o ganho depende da consulta (linha cheia de metricas ganha"
         " menos). Use quando a resposta estoura o limite do cliente."
     ),
diff --git a/tests/unit/test_add_negative_keywords_cobertura.py b/tests/unit/test_add_negative_keywords_cobertura.py
index 73f9072..b79ae3d 100644
--- a/tests/unit/test_add_negative_keywords_cobertura.py
+++ b/tests/unit/test_add_negative_keywords_cobertura.py
@@ -106,7 +106,9 @@ async def test_repetida_sai_do_lote_e_vem_em_ja_existia() -> None:
         [e], [{"text": "patrol", "match_type": "BROAD"}, {"text": "brita", "match_type": "BROAD"}]
     )
     assert _lote(rm) == [{"text": "brita", "match_type": "BROAD"}]
-    assert out["ja_existia"] == [{"text": "patrol", "match_type": "BROAD", "existente": e}]
+    assert out["ja_existia"] == [
+        {"text": "patrol", "match_type": "BROAD", "existente": e, "origem": "campanha"}
+    ]
     assert out["cobertura_verificada"] is True
     assert out["status"] == "applied"
 
diff --git a/tests/unit/test_negativas_rodada_revisao.py b/tests/unit/test_negativas_rodada_revisao.py
new file mode 100644
index 0000000..483eb25
--- /dev/null
+++ b/tests/unit/test_negativas_rodada_revisao.py
@@ -0,0 +1,214 @@
+"""Rodada da revisão final da frente negativas + `run_gaql` compacto (05/10).
+
+Cada teste nomeia o achado (I1, M1...) do `revisao-final.md` da frente.
+"""
+
+from __future__ import annotations
+
+import unicodedata
+from collections.abc import Iterator
+from typing import Any
+from unittest.mock import AsyncMock, patch
+from uuid import uuid4
+
+import pytest
+from google.protobuf.json_format import MessageToDict
+
+from src.mcp.context import McpRequestContext, clear_current, set_current
+
+# --- negativas.py --------------------------------------------------------------------------
+
+
+def test_m1_chave_iguala_nfd_e_nfc() -> None:
+    from src.google_ads.negativas import chave, classificar
+
+    nfd = unicodedata.normalize("NFD", "construção")
+    assert nfd != "construção"
+    assert chave(nfd) == chave("construção")
+    existente = {"text": "construção", "match_type": "BROAD"}
+    assert classificar({"text": nfd, "match_type": "BROAD"}, [existente])[0] == "repetida"
+
+
+def test_m6_match_type_desconhecido_nao_derruba() -> None:
+    from src.google_ads.negativas import classificar
+
+    existente = {"text": "x", "match_type": "UNKNOWN"}
+    assert classificar({"text": "x", "match_type": "PHRASE"}, [existente]) == ("nova", None)
+
+
+# --- add_negative_keywords -----------------------------------------------------------------
+
+_MOD = "src.mcp.tools.add_negative_keywords"
+
+
+@pytest.fixture
+def _ctx() -> Iterator[None]:
+    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
+    yield
+    clear_current()
+
+
+async def _ank(
+    existentes: list[dict[str, Any]] | Exception, keywords: list[dict[str, str]], **extra: Any
+) -> tuple[dict[str, Any], AsyncMock]:
+    from src.mcp.tools.add_negative_keywords import add_negative_keywords
+
+    rr = AsyncMock()
+    if isinstance(existentes, Exception):
+        rr.side_effect = existentes
+    else:
+        rr.return_value = existentes
+    with (
+        patch(f"{_MOD}.run_report", rr),
+        patch(f"{_MOD}.run_mutation", new_callable=AsyncMock) as rm,
+    ):
+        rm.return_value = {"applied_count": 1, "provider_request_id": "r", "resource_names": []}
+        out = await add_negative_keywords(
+            {"customer_id": "7862230676", "campaign_id": "1", "keywords": keywords, **extra}
+        )
+    return out, rm
+
+
+@pytest.mark.usefixtures("_ctx")
+@pytest.mark.parametrize("ordem", [("PHRASE", "BROAD"), ("BROAD", "PHRASE")])
+async def test_m3_cobertura_no_pedido_nao_depende_da_ordem(ordem: tuple[str, str]) -> None:
+    out, _ = await _ank([], [{"text": "x", "match_type": t} for t in ordem])
+    cobertas = [a for a in out["avisos"] if a["tipo"] == "coberta"]
+    assert [(a["match_type"], a["coberta_por"]["match_type"]) for a in cobertas] == [
+        ("PHRASE", "BROAD")
+    ]
+
+
+@pytest.mark.usefixtures("_ctx")
+async def test_m4_aviso_de_acento_nao_duplica() -> None:
+    kw = {"text": "construção", "match_type": "BROAD"}
+    out, _ = await _ank([], [kw, dict(kw)])
+    assert len([a for a in out["avisos"] if a["tipo"] == "sem_variante_sem_acento"]) == 1
+
+
+@pytest.mark.usefixtures("_ctx")
+async def test_m5_ja_existia_diz_a_origem() -> None:
+    e = {"criterion_id": "9", "text": "brita", "match_type": "BROAD"}
+    out, _ = await _ank(
+        [e],
+        [
+            {"text": "brita", "match_type": "BROAD"},
+            {"text": "areia", "match_type": "BROAD"},
+            {"text": "areia", "match_type": "BROAD"},
+        ],
+    )
+    assert [(j["text"], j["origem"]) for j in out["ja_existia"]] == [
+        ("brita", "campanha"),
+        ("areia", "pedido"),
+    ]
+
+
+@pytest.mark.usefixtures("_ctx")
+async def test_m7_erro_amigavel_do_google_grava_com_a_mensagem() -> None:
+    from src.google_ads.errors import GoogleAdsFriendlyError
+
+    out, rm = await _ank(
+        GoogleAdsFriendlyError("Conta sem permissao de leitura no Google."),
+        [{"text": "brita", "match_type": "BROAD"}],
+    )
+    rm.assert_awaited_once()
+    assert out["cobertura_verificada"] is False
+    assert "Conta sem permissao de leitura no Google." in out["cobertura_motivo"]
+
+
+def test_m2_description_diz_que_o_opt_in_pode_dobrar_o_lote() -> None:
+    from src.mcp.tools._registry import get_tool, import_all_tools
+
+    import_all_tools()
+    for nome in ("add_negative_keywords", "add_negatives_from_search_terms"):
+        t = get_tool(nome)
+        assert t is not None
+        assert "pode dobrar o lote" in t.description, nome
+
+
+# --- add_negatives_from_search_terms -------------------------------------------------------
+
+_MOD_ST = "src.mcp.tools.add_negatives_from_search_terms"
+
+
+async def _st(negatives: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
+    from src.mcp.tools.add_negatives_from_search_terms import add_negatives_from_search_terms
+
+    with patch(f"{_MOD_ST}.run_mutation", new_callable=AsyncMock) as rm:
+        rm.return_value = {"applied_count": 2, "provider_request_id": "r", "partial_failures": []}
+        return await add_negatives_from_search_terms(
+            {"customer_id": "7862230676", "negatives": negatives, **extra}
+        )
+
+
+def _n(termo: str) -> dict[str, str]:
+    return {"search_term": termo, "match_type": "PHRASE", "scope": "campaign", "scope_id": "1"}
+
+
+@pytest.mark.usefixtures("_ctx")
+async def test_m4_search_terms_aviso_nao_duplica() -> None:
+    out = await _st([_n("construção"), _n("construção")])
+    assert len(out["avisos"]) == 1
+
+
+@pytest.mark.usefixtures("_ctx")
+async def test_m10_blast_summary_separa_as_variantes() -> None:
+    out = await _st([_n("construção")], incluir_variante_sem_acento=True)
+    assert "1 negativa(s) derivada(s) do search_terms_report" in out["blast_summary"]
+    assert "1 variante(s) sem acento" in out["blast_summary"]
+
+
+def test_i2_description_nao_promete_already_exists() -> None:
+    from src.mcp.tools._registry import get_tool, import_all_tools
+
+    import_all_tools()
+    t = get_tool("add_negatives_from_search_terms")
+    assert t is not None
+    assert "descarta em silencio" in t.description
+    assert "termos ja existentes retornam status" not in t.description
+
+
+# --- run_gaql compact ----------------------------------------------------------------------
+
+
+def _change_event(vazio: bool = False) -> dict[str, Any]:
+    from google.ads.googleads.v24.resources.types.campaign import Campaign
+    from google.ads.googleads.v24.resources.types.change_event import ChangeEvent
+    from google.ads.googleads.v24.services.types.google_ads_service import GoogleAdsRow
+
+    antigo = (
+        ChangeEvent.ChangedResource()
+        if vazio
+        else ChangeEvent.ChangedResource(
+            campaign=Campaign(resource_name="customers/1/campaigns/2", id=2)
+        )
+    )
+    row = GoogleAdsRow(
+        change_event=ChangeEvent(resource_name="customers/1/changeEvents/x", old_resource=antigo)
+    )
+    return MessageToDict(row._pb, preserving_proto_field_name=True)  # type: ignore[no-any-return]
+
+
+def test_i1_resource_name_dentro_de_campo_pedido_fica() -> None:
+    from src.google_ads.gaql_compacto import campos_do_select, linha_compacta
+
+    pedidos = campos_do_select("SELECT change_event.old_resource FROM change_event")
+    plana = linha_compacta(_change_event(), pedidos)
+    assert plana["change_event.old_resource.campaign.resource_name"] == "customers/1/campaigns/2"
+    assert "change_event.resource_name" not in plana
+
+
+def test_m8_campo_mensagem_vazio_pedido_fica() -> None:
+    from src.google_ads.gaql_compacto import campos_do_select, linha_compacta
+
+    pedidos = campos_do_select("SELECT change_event.old_resource FROM change_event")
+    assert linha_compacta(_change_event(vazio=True), pedidos) == {"change_event.old_resource": {}}
+
+
+def test_m9_description_diz_amostra_de_linhas() -> None:
+    from src.mcp.tools._registry import get_tool, import_all_tools
+
+    import_all_tools()
+    t = get_tool("run_gaql")
+    assert t is not None
+    assert "numa amostra de linhas de campaign_criterion" in t.description
```

### Task 7: fix(mcp): re-revisao - cobertura depois das variantes do opt-in, guard do prefixo do compact

- N1: a passada de cobertura roda depois das variantes: a BROAD sem acento gravada
  pelo opt-in cobre a EXACT pedida, e o aviso sai.
- N2: teste do limite do prefixo (campaign pedido nao casa campaign_budget).

26 sabotagens de copia caem sobre o codigo final.

**Arquivos:**

```text
M	src/mcp/tools/add_negative_keywords.py
M	tests/unit/test_negativas_rodada_revisao.py
```

- [ ] Aplicar o bloco, rodar o gate, commitar com a mensagem acima.

```diff
diff --git a/src/mcp/tools/add_negative_keywords.py b/src/mcp/tools/add_negative_keywords.py
index 2905e53..00439c7 100644
--- a/src/mcp/tools/add_negative_keywords.py
+++ b/src/mcp/tools/add_negative_keywords.py
@@ -94,12 +94,6 @@ def _planejar(
             continue
         lote.append(kw)
         conhecidas.append(kw)
-    # Cobertura DEPOIS do lote montado: contra a campanha e o resto do pedido, em qualquer
-    # ordem — `[PHRASE x, BROAD x]` e `[BROAD x, PHRASE x]` dizem o mesmo.
-    for kw in lote:
-        estado, existente = classificar(kw, [c for c in conhecidas if c is not kw])
-        if estado == "coberta":
-            avisos.append({"tipo": "coberta", **kw, "coberta_por": existente})
     vistas: set[tuple[str, str]] = set()
     for kw in pedidas:
         if (chave(kw["text"]), kw["match_type"]) in vistas:
@@ -117,6 +111,13 @@ def _planejar(
             variantes.append({**par, "variante_de": kw["text"]})
         else:
             avisos.append({"tipo": "sem_variante_sem_acento", **kw, "sugestao": texto})
+    # Cobertura DEPOIS do lote completo, variantes do opt-in inclusive: contra a campanha e o
+    # resto do lote, em qualquer ordem — `[PHRASE x, BROAD x]` e `[BROAD x, PHRASE x]` dizem o
+    # mesmo, e a BROAD sem acento gravada pelo opt-in cobre a EXACT pedida (re-revisao 05/10).
+    for kw in lote:
+        estado, existente = classificar(kw, [c for c in conhecidas if c is not kw])
+        if estado == "coberta":
+            avisos.append({"tipo": "coberta", **kw, "coberta_por": existente})
     return {
         "lote": lote,
         "ja_existia": ja_existia,
diff --git a/tests/unit/test_negativas_rodada_revisao.py b/tests/unit/test_negativas_rodada_revisao.py
index 483eb25..90fb7e0 100644
--- a/tests/unit/test_negativas_rodada_revisao.py
+++ b/tests/unit/test_negativas_rodada_revisao.py
@@ -212,3 +212,27 @@ def test_m9_description_diz_amostra_de_linhas() -> None:
     t = get_tool("run_gaql")
     assert t is not None
     assert "numa amostra de linhas de campaign_criterion" in t.description
+
+
+# --- re-revisão da rodada (05/10) ----------------------------------------------------------
+
+
+@pytest.mark.usefixtures("_ctx")
+async def test_n1_variante_do_opt_in_entra_na_cobertura() -> None:
+    out, _ = await _ank(
+        [],
+        [
+            {"text": "construcao", "match_type": "EXACT"},
+            {"text": "construção", "match_type": "BROAD"},
+        ],
+        incluir_variante_sem_acento=True,
+    )
+    cobertas = [(a["text"], a["match_type"]) for a in out["avisos"] if a["tipo"] == "coberta"]
+    assert cobertas == [("construcao", "EXACT")]
+
+
+def test_n2_prefixo_do_campo_pedido_nao_casa_vizinho_de_nome() -> None:
+    from src.google_ads.gaql_compacto import linha_compacta
+
+    linha = {"campaign": {"resource_name": "c"}, "campaign_budget": {"resource_name": "b"}}
+    assert linha_compacta(linha, {"campaign"}) == {"campaign.resource_name": "c"}
```
