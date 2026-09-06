"""Verify all registered MCP tools have valid JSON Schema and consistent shape."""

import jsonschema
import pytest

from src.mcp.tools._registry import all_tools, import_all_tools
from src.mcp.tools.update_ad_group_bid import _SCHEMA as AD_GROUP_BID_SCHEMA
from src.mcp.tools.update_keyword_bid import _SCHEMA as KEYWORD_BID_SCHEMA
from tests.unit import _guard_harness as h


@pytest.fixture(scope="module", autouse=True)
def _load_tools():
    import_all_tools()


def test_every_tool_has_valid_schema():
    for tool in all_tools():
        # Will raise if invalid schema
        jsonschema.Draft202012Validator.check_schema(tool.input_schema)


def test_no_composition_keywords_in_any_schema():
    """Anthropic Messages API rejects oneOf/allOf/anyOf in tool input_schema.

    Empirical finding Sprint 3b.19B.1: the API error message says "at the top
    level" but rejects these keywords at ANY nesting level (top-level of root
    AND top-level of subschemas inside `items`/`properties.*`). Two tools
    shipped with violations broke the entire Claude session via 400 error:
    - Sprint 3b.18 update_rsa: anyOf in properties.updates.items
    - Sprint 3b.19B create_conversion_value_rule_set: allOf at root + in items

    Walks every registered tool's schema recursively. Express runtime-only
    constraints (cross-field, conditional requireds) inside the tool body
    instead — both above were ported to pre-flight checks.
    """
    forbidden = {"oneOf", "allOf", "anyOf"}
    offenders: list[tuple[str, str]] = []

    def walk(tool_name: str, node: object, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in forbidden:
                    offenders.append((tool_name, f"{path}.{key}"))
                walk(tool_name, value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(tool_name, item, f"{path}[{i}]")

    for tool in all_tools():
        walk(tool.name, tool.input_schema, "input_schema")

    assert not offenders, (
        "Schemas with oneOf/allOf/anyOf rejected by Anthropic API "
        "(see Sprint 3b.19B.1 lesson):\n"
        + "\n".join(f"  {name}: {path}" for name, path in offenders)
    )


def test_builder_tests_use_capture_client_not_magicmock():
    """Builder tests DEVEM usar fixtures/proto_capture.make_capture_client, nunca
    um MagicMock client cru.

    MagicMock aceita qualquer atribuição de campo proto silenciosamente — mascara
    bugs de campo errado/ausente (F16/F42/F44 + A4: negative=True virou False sem
    ser detectado). make_capture_client captura os assignments pra asserção real.

    Offender = test_*_builder.py que referencia MagicMock SEM importar
    make_capture_client (rolou o próprio mock em vez da fixture). Arquivos que
    usam make_capture_client e ainda importam MagicMock pra uso ancilar (ex:
    override pontual de path helper) são legítimos e ficam de fora.

    Escopo via `h.testes_py(unit_dir)` (recursivo — pega builder test que
    algum dia mude de subpasta), mas o filtro MANTÉM o sufixo `_builder.py`
    de propósito, em vez de só `startswith("test_")` como o resto da Task 4:
    a regra "MagicMock cru no client mascara bug de proto field" só faz
    sentido pra teste QUE EXERCITA UM BUILDER.

    Dois números, medidos e conferidos por dois caminhos independentes cada
    (revisão de Task 4, 2026-09-06 — a versão anterior deste docstring dizia
    "39" e não citava o segundo número abaixo; os dois estavam errados, e
    docstring com número errado é pior que sem número, porque quem confia não
    remede):

    - **21** arquivos `test_*_builder.py` hoje em `tests/unit/` (diretos,
      nenhum aninhado) — a população que o filtro de sufixo abaixo preserva;
      nenhum deles é offender hoje (por isso este guard passa). Reproduza com
      `len(list(unit_dir.glob("test_*_builder.py")))` (glob puro,
      não-recursivo) — bate com `len([p for p in h.testes_py(unit_dir) if
      p.name.startswith("test_") and p.name.endswith("_builder.py")])`
      (harness, recursivo).
    - **42** arquivos que este guard passaria a acusar se o filtro abaixo
      soltasse o sufixo (só `startswith("test_")`, sem o `endswith`) —
      test_backup, test_session_is_active, test_logging_context, etc. — que
      usam MagicMock pra mockar pool/conexão/job e nunca tocam
      `_BUILDERS`/`register_builder`; zero desses 42 é builder test sem o
      nome certo, é o guard perguntando a arquivo errado uma pergunta que não
      se aplica a ele. Reproduza tirando o `and path.name.endswith(...)` da
      condição abaixo — bate trocando `h.testes_py(unit_dir)` por
      `unit_dir.rglob("*.py")` cru (mesmos `_IGNORADOS` de
      `_guard_harness.py`).
    """
    import pathlib

    unit_dir = pathlib.Path(__file__).resolve().parent
    offenders: list[str] = []
    for path in h.testes_py(unit_dir):
        if not (path.name.startswith("test_") and path.name.endswith("_builder.py")):
            continue
        src = path.read_text(encoding="utf-8")
        if "MagicMock" in src and "make_capture_client" not in src:
            offenders.append(path.name)

    assert not offenders, (
        "Builder tests com MagicMock client cru em vez de make_capture_client "
        "(bugs de proto field mascarados — F16/F42/F44):\n" + "\n".join(f"  {n}" for n in offenders)
    )


def test_registered_tool_count_matches_files_on_disk():
    """Regression for Sprints 3b.12-3b.14 bug: manual import list lagged behind
    actual files, leaving 3 tools dead in production despite tests passing
    (pytest import side effects masked the registry gap).

    With pkgutil auto-discovery in import_all_tools(), this should be
    structurally impossible. Defense-in-depth: verify 1:1 count match.
    """
    import pathlib

    registered_count = len(all_tools())
    tools_dir = pathlib.Path(__file__).resolve().parent.parent.parent / "src" / "mcp" / "tools"
    file_count = sum(1 for f in tools_dir.glob("*.py") if not f.stem.startswith("_"))

    assert registered_count == file_count, (
        f"Tool count mismatch: {registered_count} registered, {file_count} files in tools/. "
        f"Likely cause: a tool file exists but its module wasn't imported by import_all_tools(). "
        f"With pkgutil auto-discovery this should be impossible — check _registry.py."
    )


def test_customer_id_pattern_is_consistent():
    """Every tool that has a customer_id field must use the same pattern."""
    for tool in all_tools():
        props = tool.input_schema.get("properties", {})
        if "customer_id" in props:
            cid = props["customer_id"]
            assert cid.get("pattern") == "^[0-9]{10}$", (
                f"{tool.name} has wrong customer_id pattern: {cid.get('pattern')}"
            )


def test_all_phase_2_tools_registered():
    """All 31 tools (20 Phase 2 + 3 campaign mutations + 2 ad group mutations + 2 keyword mutations + 1 negatives + 2 recommendations + 1 create_ad_group) registered."""
    expected = {
        "add_keywords",
        "audit_competitor_keywords",
        "audit_goal_attribution",  # Sprint 3b.35
        "audit_orphan_smart_actions",  # Sprint 3b.37
        "audit_quality_score",
        "audit_zombie_keywords",  # Sprint 3b.36
        "create_ad_group",
        "add_negative_keywords",
        "add_negatives_from_search_terms",
        "apply_audience",
        "apply_change",
        "apply_recommendation",
        "bulk_pause_by_query",
        "detect_drift",  # Sprint 3b.33
        "dismiss_recommendation",
        "list_my_accounts",
        # visao geral
        "get_account_overview",
        "get_budget_pacing",
        "get_recommendations",
        # performance
        "get_campaign_performance",
        "get_change_history",
        "get_ad_group_performance",
        "get_device_performance",
        "get_geo_performance",
        "get_hourly_performance",
        # tactical
        "get_keyword_performance",
        "get_search_terms_report",
        "get_negative_keywords_audit",
        "get_ad_performance",
        "get_audience_performance",
        "get_conversion_actions",
        # client report
        "get_funnel_metrics",
        "get_top_keywords_creatives",
        # utilities
        "run_gaql",
        "validate_gaql",
        "list_gaql_resources",
        # campaign mutations
        "update_campaign_bidding",
        "update_campaign_budget",
        "update_campaign_status",
        # ad group mutations
        "update_ad_group_bid",
        "update_ad_group_status",
        # ad mutations
        "update_ad_status",
        # keyword mutations
        "update_keyword_bid",
        "update_keyword_status",
        # audience mutations
        "remove_audience",
        # utilities
        "get_my_rate_limit_status",
        "get_my_audit_log",
        # create patterns
        "create_rsa",
        "create_conversion_action",
        "create_conversion_value_rule_set",
        "create_campaign",  # Sprint 3b.24
        "create_and_link_assets",  # Sprint 3b.25
        "import_offline_conversions",  # Sprint 3b.26
        "upload_customer_match_list",  # Sprint 3b.28
        # update patterns
        "update_rsa",
        "update_conversion_action",  # Sprint 3b.27
        "get_performance_breakdown",  # Fase 2A Task 5
    }
    actual = {t.name for t in all_tools()}
    missing = expected - actual
    assert not missing, f"Missing tools: {missing}"


def test_no_unexpected_tools():
    """Catch accidental new tool registrations not in the expected set."""
    expected = {
        "add_keywords",
        "audit_competitor_keywords",
        "audit_goal_attribution",  # Sprint 3b.35
        "audit_orphan_smart_actions",  # Sprint 3b.37
        "audit_quality_score",
        "audit_zombie_keywords",  # Sprint 3b.36
        "create_ad_group",
        "add_negative_keywords",
        "add_negatives_from_search_terms",
        "apply_audience",
        "apply_change",
        "apply_recommendation",
        "bulk_pause_by_query",
        "detect_drift",  # Sprint 3b.33
        "dismiss_recommendation",
        "remove_audience",
        "remove_negative_keywords",
        "list_my_accounts",
        "get_account_overview",
        "get_budget_pacing",
        "get_recommendations",
        "get_campaign_performance",
        "get_change_history",
        "get_ad_group_performance",
        "get_device_performance",
        "get_geo_performance",
        "get_hourly_performance",
        "get_keyword_performance",
        "get_search_terms_report",
        "get_negative_keywords_audit",
        "get_ad_performance",
        "get_audience_performance",
        "get_conversion_actions",
        "get_funnel_metrics",
        "get_top_keywords_creatives",
        "run_gaql",
        "validate_gaql",
        "list_gaql_resources",
        "update_campaign_bidding",
        "update_campaign_budget",
        "update_campaign_status",
        "update_ad_group_bid",
        "update_ad_group_status",
        "update_ad_status",
        "update_keyword_bid",
        "update_keyword_status",
        "get_my_rate_limit_status",
        "get_my_audit_log",
        "create_rsa",
        "create_conversion_action",
        "create_conversion_value_rule_set",
        "create_campaign",  # Sprint 3b.24
        "create_and_link_assets",  # Sprint 3b.25
        "import_offline_conversions",  # Sprint 3b.26
        "upload_customer_match_list",  # Sprint 3b.28
        "update_rsa",
        "update_conversion_action",  # Sprint 3b.27
        "meta_list_my_ad_accounts",  # Sprint M.2a Task 9
        "meta_get_account_overview",  # Sprint M.2b Task C
        "meta_get_campaign_performance",  # Sprint M.3 Task 3
        "meta_get_ad_set_performance",  # Sprint M.3 Task 4
        "meta_get_ad_performance",  # Sprint M.3 Task 5
        "meta_get_performance_breakdown",  # Sprint M.4
        "get_performance_breakdown",  # Fase 2A Task 5
        "get_assets",  # F134 Task 3
        "remove_asset_link",  # F134 Task 5
        "get_ad_schedule",  # ad_schedule Task 5
        "update_ad_schedule",  # ad_schedule Task 7
    }
    actual = {t.name for t in all_tools()}
    unexpected = actual - expected
    assert not unexpected, f"Unexpected tools: {unexpected}"


def test_date_range_schemas_are_explicit():
    """Schemas with `date_range` MUST declare type: "string" + enum of presets.

    Sprint 3b.20: missing `type` field caused Claude to serialize dict-as-string,
    breaking parse_date_range. Defense-in-depth — fails CI if a regression
    reintroduces a loose `date_range` schema.

    For tools that need custom periods, add `start_date` + `end_date` as separate
    string properties with pattern YYYY-MM-DD (see resolve_date_window helper).
    """
    offenders: list[tuple[str, str]] = []

    for tool in all_tools():
        props = tool.input_schema.get("properties", {})
        dr = props.get("date_range")
        if dr is None:
            continue
        if dr.get("type") != "string":
            offenders.append((tool.name, f"date_range.type={dr.get('type')!r}"))
        elif "enum" not in dr:
            offenders.append((tool.name, "date_range missing enum"))

    assert not offenders, (
        "date_range schemas without explicit type+enum (Sprint 3b.20 regression):\n"
        + "\n".join(f"  {name}: {reason}" for name, reason in offenders)
    )


def test_every_tool_has_description():
    for tool in all_tools():
        assert tool.description, f"{tool.name} has no description"
        assert len(tool.description) >= 30, (
            f"{tool.name} description too short: {tool.description!r}"
        )


def test_every_tool_input_schema_disallows_extra_properties():
    """Tools should set additionalProperties: false to catch typos."""
    for tool in all_tools():
        if tool.input_schema.get("type") == "object":
            assert tool.input_schema.get("additionalProperties") is False, (
                f"{tool.name} doesn't have additionalProperties: false"
            )


def test_update_keyword_bid_accepts_zero_bid():
    """Keyword bid schema should accept new_cpc_bid_brl: 0 to allow inheriting from parent."""
    valid_input = {
        "customer_id": "1234567890",
        "bids": [
            {
                "ad_group_id": "1",
                "criterion_id": "2",
                "new_cpc_bid_brl": 0,
            }
        ],
    }
    # Should not raise ValidationError
    jsonschema.validate(valid_input, KEYWORD_BID_SCHEMA)


def test_update_keyword_bid_rejects_negative_bid():
    """Keyword bid schema should reject new_cpc_bid_brl: -1."""
    invalid_input = {
        "customer_id": "1234567890",
        "bids": [
            {
                "ad_group_id": "1",
                "criterion_id": "2",
                "new_cpc_bid_brl": -1,
            }
        ],
    }
    with pytest.raises(jsonschema.exceptions.ValidationError):
        jsonschema.validate(invalid_input, KEYWORD_BID_SCHEMA)


def test_update_ad_group_bid_accepts_zero_bid():
    """Ad group bid schema should accept new_cpc_bid_brl: 0 to allow inheriting from parent."""
    valid_input = {
        "customer_id": "1234567890",
        "bids": [
            {
                "ad_group_id": "1",
                "new_cpc_bid_brl": 0,
            }
        ],
    }
    # Should not raise ValidationError
    jsonschema.validate(valid_input, AD_GROUP_BID_SCHEMA)


def test_update_ad_group_bid_rejects_negative_bid():
    """Ad group bid schema should reject new_cpc_bid_brl: -1."""
    invalid_input = {
        "customer_id": "1234567890",
        "bids": [
            {
                "ad_group_id": "1",
                "new_cpc_bid_brl": -1,
            }
        ],
    }
    with pytest.raises(jsonschema.exceptions.ValidationError):
        jsonschema.validate(invalid_input, AD_GROUP_BID_SCHEMA)


def test_get_account_overview_accepts_custom_period():
    """Verify Sprint 3b.20 pattern works on canonical tool."""
    from src.mcp.tools.get_account_overview import _SCHEMA

    valid_custom = {
        "customer_id": "1234567890",
        "start_date": "2026-05-08",
        "end_date": "2026-05-14",
    }
    jsonschema.validate(valid_custom, _SCHEMA)

    valid_preset = {"customer_id": "1234567890", "date_range": "LAST_7_DAYS"}
    jsonschema.validate(valid_preset, _SCHEMA)


def test_get_account_overview_rejects_invalid_date_format():
    from src.mcp.tools.get_account_overview import _SCHEMA

    invalid = {"customer_id": "1234567890", "start_date": "08/05/2026", "end_date": "2026-05-14"}
    with pytest.raises(jsonschema.exceptions.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)


def test_every_mutate_builder_has_a_builder_test():
    """Todo @register_builder DEVE ter um test_*_builder.py que importa/referencia
    sua função. Anti-reincidência F50/F51 (Onda 2): os 10 builders update_*/negative
    shiparam sem teste de execução — um campo proto / FieldMask / oneof errado passava
    a suíte e só falhava quando um gestor confirmava a mutação em produção.

    Complementa test_builder_tests_use_capture_client_not_magicmock (que garante a
    QUALIDADE do teste) com a EXISTÊNCIA do teste.

    Escopo via `h.testes_py(unit_dir)` filtrado só por `startswith("test_")` —
    SEM o sufixo `_builder.py`: o guard passa a ver todo teste (recursivo) que
    mencione o nome do builder ou da op, não só quem lembrou de nomear o
    arquivo `_builder.py`. Ao contrário do guard de MagicMock acima, alargar
    aqui não introduz ruído — o pior caso é uma referência incidental ao nome
    em outro teste contando como cobertura, nunca um builder real cobrado sem
    motivo. `p.name.startswith("test_")` também é o que mantém
    `tests/unit/fixtures_guards/**/modulo.py` (árvore sintética do harness)
    fora do corpo lido — nenhum arquivo lá começa com `test_`.
    """
    import pathlib

    from src.google_ads.mutates._common import _BUILDERS, import_all_builders

    import_all_builders()

    unit_dir = pathlib.Path(__file__).resolve().parent
    all_content = "\n".join(
        p.read_text(encoding="utf-8") for p in h.testes_py(unit_dir) if p.name.startswith("test_")
    )

    missing = sorted(
        op
        for op, fn in _BUILDERS.items()
        if fn.__name__ not in all_content and op not in all_content
    )

    assert not missing, (
        "Builders de mutate sem test_*_builder.py (classe F50/F51 — código de mutação "
        "sem teste de execução):\n" + "\n".join(f"  {op}" for op in missing)
    )
