from src.mcp.session import extract_bearer_token


def test_extracts_bearer_from_header():
    token = extract_bearer_token("Bearer mcp_abc123")
    assert token == "mcp_abc123"


def test_returns_none_for_missing_header():
    assert extract_bearer_token(None) is None


def test_returns_none_for_wrong_scheme():
    assert extract_bearer_token("Basic dXNlcjpwYXNz") is None


def test_returns_none_for_empty_token():
    assert extract_bearer_token("Bearer ") is None
