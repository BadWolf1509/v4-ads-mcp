"""Unit tests for upload_customer_match_list tool — schema + Layer 2 (Sprint 3b.28).

Integration tests (Layer 3 mocking, dispatcher routing) live em
tests/integration/test_upload_customer_match_list.py.
"""

from src.mcp.tools.upload_customer_match_list import (
    _SCHEMA,
    _hash_members,
    _validate_payload_shape,
)


def test_schema_has_no_composition_keywords():
    import json

    schema_str = json.dumps(_SCHEMA)
    assert '"oneOf"' not in schema_str
    assert '"allOf"' not in schema_str
    assert '"anyOf"' not in schema_str


def test_schema_explicit_types():
    def _walk(obj):
        if isinstance(obj, dict):
            if "properties" in obj:
                for prop_name, prop_schema in obj["properties"].items():
                    assert "type" in prop_schema, f"property '{prop_name}' missing type"
                    _walk(prop_schema)
            if "items" in obj:
                _walk(obj["items"])
            for v in obj.values():
                if isinstance(v, dict | list):
                    _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(_SCHEMA)


def test_validate_payload_shape_accepts_well_formed_input():
    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [
            {"email": "user1@example.com"},
            {"phone_number": "+5511987654321"},
            {"email": "user2@example.com", "phone_number": "11987654322"},
        ],
    }
    assert _validate_payload_shape(args) is None


def test_validate_payload_shape_rejects_member_without_identifier():
    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [{}],
    }
    err = _validate_payload_shape(args)
    assert err is not None
    assert "sem identificador" in err or "identifier" in err.lower()


def test_validate_payload_shape_rejects_already_hashed_email():
    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [{"email": "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"}],
    }
    err = _validate_payload_shape(args)
    assert err is not None
    assert "SHA-256" in err or "já parece" in err
    assert "plaintext" in err


def test_validate_payload_shape_rejects_invalid_email_format():
    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [{"email": "not-an-email"}],
    }
    err = _validate_payload_shape(args)
    assert err is not None
    assert "inválido" in err.lower() or "invalid" in err.lower()


def test_validate_payload_shape_rejects_duplicate_email_after_normalize():
    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [
            {"email": "User@Example.COM"},
            {"email": "user@example.com"},
        ],
    }
    err = _validate_payload_shape(args)
    assert err is not None
    assert "duplicados" in err


def test_validate_payload_shape_rejects_duplicate_phone_after_normalize():
    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [
            {"phone_number": "(11) 9 8765-4321"},
            {"phone_number": "+5511987654321"},
        ],
    }
    err = _validate_payload_shape(args)
    assert err is not None
    assert "duplicados" in err


def test_hash_members_returns_hashed_email():
    members = [{"email": "user@example.com"}]
    result = _hash_members(members)
    assert len(result) == 1
    assert "hashed_email" in result[0]
    assert "hashed_phone_number" not in result[0]
    assert len(result[0]["hashed_email"]) == 64


def test_hash_members_handles_email_and_phone_per_member():
    members = [{"email": "user@example.com", "phone_number": "+5511987654321"}]
    result = _hash_members(members)
    assert "hashed_email" in result[0]
    assert "hashed_phone_number" in result[0]


def test_hash_members_strips_plaintext_keys():
    """Hashed output não deve carrear plaintext email/phone."""
    members = [{"email": "user@example.com", "phone_number": "+5511987654321"}]
    result = _hash_members(members)
    assert "email" not in result[0]
    assert "phone_number" not in result[0]
