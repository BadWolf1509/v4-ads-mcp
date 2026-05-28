from src.auth.oauth import _error_page, _success_page


def test_error_page_escapes_html():
    resp = _error_page("<script>alert(1)</script>", status=400)
    body = resp.body.decode()
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_success_page_escapes_email():
    resp = _success_page("a@b.com<script>")
    assert "<script>" not in resp.body.decode()
