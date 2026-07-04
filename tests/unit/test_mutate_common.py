"""Unit tests for src/mcp/tools/_mutate_common.py envelope helpers.

Task 3.2 — dedup dos 22 mutate tools: error_envelope/applied_envelope/
preview_envelope centralizam o bloco "risk -> AUTO-apply / dry-run / error"
que estava copiado em cada tool. Cobre shape, DEFAULT_TTL_MINUTES usado
(não o literal 10 hardcoded), confirmation_reason opcional, e **extra
passando por-tool fields sem colidir com os campos canônicos.
"""

from src.governance.dry_run import DEFAULT_TTL_MINUTES
from src.mcp.tools._mutate_common import applied_envelope, error_envelope, preview_envelope

# ---------------------------------------------------------------------------
# error_envelope
# ---------------------------------------------------------------------------


def test_error_envelope_minimal_shape():
    result = error_envelope("update_keyword_bid", "algo deu errado")
    assert result == {
        "status": "error",
        "error_message": "algo deu errado",
        "operation": "update_keyword_bid",
    }


def test_error_envelope_includes_customer_id_when_given():
    result = error_envelope("create_campaign", "geo invalido", customer_id="1234567890")
    assert result["customer_id"] == "1234567890"
    assert result["status"] == "error"
    assert result["error_message"] == "geo invalido"
    assert result["operation"] == "create_campaign"


def test_error_envelope_omits_customer_id_when_not_given():
    result = error_envelope("update_campaign_budget", "campanha nao encontrada")
    assert "customer_id" not in result


def test_error_envelope_extra_fields_pass_through():
    """**extra carrega campos de pré-flight (missing_ids, negative_ids_blocked, etc)."""
    result = error_envelope(
        "update_conversion_action",
        "999 nao existe",
        customer_id="1163862076",
        missing_ids=["999"],
    )
    assert result["missing_ids"] == ["999"]
    assert result["error_message"] == "999 nao existe"


def test_error_envelope_never_has_error_key():
    """Regression guard: chave legada 'error' não deve reaparecer no envelope canônico."""
    result = error_envelope("bulk_pause_by_query", "filtro invalido", target_type="keyword")
    assert "error" not in result
    assert result["error_message"] == "filtro invalido"


# ---------------------------------------------------------------------------
# applied_envelope
# ---------------------------------------------------------------------------


def test_applied_envelope_minimal_shape():
    result = applied_envelope(
        "update_ad_group_status",
        "1234567890",
        "Mudar status de 3 grupo(s) para PAUSED.",
        applied_count=3,
        provider_request_id="req-abc",
        auto_applied_reason="update_ad_group_status: bulk pequeno (3 entities <= 5) — auto",
    )
    assert result == {
        "status": "applied",
        "operation": "update_ad_group_status",
        "customer_id": "1234567890",
        "blast_summary": "Mudar status de 3 grupo(s) para PAUSED.",
        "applied_count": 3,
        "provider_request_id": "req-abc",
        "auto_applied_reason": "update_ad_group_status: bulk pequeno (3 entities <= 5) — auto",
    }


def test_applied_envelope_extra_fields_pass_through():
    """**extra carrega campos por-tool (changes[], added[], resource_names, etc)."""
    changes = [{"ad_group_id": "1", "delta_pct": 5.0}]
    result = applied_envelope(
        "update_keyword_bid",
        "1234567890",
        "Atualizar CPC de 1 keyword(s).",
        applied_count=1,
        provider_request_id="req-xyz",
        auto_applied_reason="auto",
        changes=changes,
        max_delta_pct=5.0,
    )
    assert result["changes"] == changes
    assert result["max_delta_pct"] == 5.0


# ---------------------------------------------------------------------------
# preview_envelope
# ---------------------------------------------------------------------------


def test_preview_envelope_minimal_shape():
    result = preview_envelope(
        "update_campaign_status",
        "1234567890",
        "Mudar status de 6 campanha(s) para PAUSED.",
        "ABC12345",
    )
    assert result["status"] == "dry_run"
    assert result["operation"] == "update_campaign_status"
    assert result["customer_id"] == "1234567890"
    assert result["blast_summary"] == "Mudar status de 6 campanha(s) para PAUSED."
    assert result["confirmation_token"] == "ABC12345"
    assert result["to_apply"] == "Chame apply_change(confirmation_token=<token>) para aplicar."
    assert "confirmation_reason" not in result


def test_preview_envelope_uses_default_ttl_minutes_not_hardcoded_literal():
    """expires_in_minutes deve vir de DEFAULT_TTL_MINUTES (src/governance/dry_run.py),
    não de um literal 10 hardcoded no helper — regression guard contra o bug
    original (10 hardcoded 22x nos tools)."""
    result = preview_envelope(
        "update_keyword_status",
        "1234567890",
        "Mudar status de 6 palavra(s)-chave para PAUSED.",
        "TOKEN001",
    )
    assert result["expires_in_minutes"] == DEFAULT_TTL_MINUTES


def test_preview_envelope_confirmation_reason_included_when_given():
    result = preview_envelope(
        "update_keyword_bid",
        "1234567890",
        "Atualizar CPC de 6 keyword(s).",
        "TOKEN002",
        confirmation_reason="update_keyword_bid: more than 5 entities (6) — confirmar",
    )
    assert (
        result["confirmation_reason"] == "update_keyword_bid: more than 5 entities (6) — confirmar"
    )


def test_preview_envelope_confirmation_reason_omitted_when_none():
    """bulk_pause_by_query nao chama blast_radius.classify — omite confirmation_reason
    por design (não um bug de omissão acidental)."""
    result = preview_envelope(
        "bulk_pause_by_query",
        "1234567890",
        "Pausar 2 keyword(s).",
        "TOK01234",
        preview={"target_type": "keyword", "matched_count": 2},
    )
    assert "confirmation_reason" not in result
    assert result["preview"] == {"target_type": "keyword", "matched_count": 2}


def test_preview_envelope_extra_fields_pass_through():
    """**extra carrega campos por-tool (changes[], *_preview[], sample_keywords, etc)."""
    preview = [{"ad_group_id": "1", "name": "AG1"}]
    result = preview_envelope(
        "create_ad_group",
        "1234567890",
        "Criar 1 ad_group(s) em 1 campaign(s).",
        "TOKENAG",
        confirmation_reason="create_ad_group: criacao de entidade(s) — sempre CONFIRM (spec §7.1)",
        ad_groups_preview=preview,
    )
    assert result["ad_groups_preview"] == preview


def test_preview_envelope_extra_does_not_override_canonical_fields_order():
    """Canonical fields (status/operation/customer_id/blast_summary/token/ttl/to_apply)
    are always present regardless of extra kwargs ordering."""
    result = preview_envelope(
        "apply_audience",
        "1234567890",
        "Apply 2 audience(s).",
        "TOKAUD01",
        target_type="ad_group",
        mode="observation",
    )
    assert result["target_type"] == "ad_group"
    assert result["mode"] == "observation"
    for key in (
        "status",
        "operation",
        "customer_id",
        "blast_summary",
        "confirmation_token",
        "expires_in_minutes",
        "to_apply",
    ):
        assert key in result
