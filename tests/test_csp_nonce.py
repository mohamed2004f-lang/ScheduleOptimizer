"""رمز CSP على سكربتات HTML وسياسة الإنتاج."""
import re
from pathlib import Path

from backend.core.security import _csp_header_value, inject_script_nonces

ROOT = Path(__file__).resolve().parents[1]


def test_inject_script_nonces_adds_missing_only():
    html = '<script src="/static/js/common.js"></script><script nonce="keep">ok()</script><script>inline()</script>'
    out = inject_script_nonces(html, "abc123")
    assert '<script nonce="abc123" src="/static/js/common.js">' in out
    assert '<script nonce="keep">' in out
    assert '<script nonce="abc123">' in out
    assert out.count('nonce="abc123"') == 2


def test_csp_header_production_uses_nonce(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("ENABLE_CSP", "1")
    monkeypatch.delenv("ENABLE_CSP_LEGACY", raising=False)
    header = _csp_header_value("nOnceVal")
    assert header is not None
    assert "'nonce-nOnceVal'" in header
    assert "unsafe-eval" not in header
    assert "unsafe-inline" not in header.split("style-src")[0]
    assert "'unsafe-inline'" in header.split("style-src", 1)[1]


def test_csp_header_skipped_outside_production(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("ENABLE_CSP", "1")
    assert _csp_header_value("x") is None


def test_csp_legacy_restores_unsafe_inline(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("ENABLE_CSP", "1")
    monkeypatch.setenv("ENABLE_CSP_LEGACY", "1")
    header = _csp_header_value("nOnceVal")
    assert header is not None
    assert "unsafe-inline" in header
    assert "unsafe-eval" in header
    assert "nonce-nOnceVal" not in header


def test_base_nav_scripts_are_external_with_nonce():
    nav = (ROOT / "frontend" / "templates" / "base_nav.html").read_text(encoding="utf-8")
    assert "/static/js/nav-auth.js" in nav
    assert "/static/js/nav-shell.js" in nav
    assert "/static/js/nav-shell-pending.js" in nav
    assert 'nonce="{{ csp_nonce }}"' in nav
    inlines = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", nav, flags=re.I)
    assert inlines == []


def test_docker_compose_disables_csp_legacy():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "ENABLE_CSP=1" in compose
    assert "ENABLE_CSP_LEGACY=0" in compose
    assert "ENABLE_CSP_LEGACY=1" not in compose


def test_dashboard_production_csp_script_src_has_nonce(auth_client, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("ENABLE_CSP", "1")
    monkeypatch.delenv("ENABLE_CSP_LEGACY", raising=False)
    resp = auth_client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "/static/js/nav-auth.js" in html
    for path in (
        "/static/js/nav-auth.js",
        "/static/js/nav-shell.js",
        "/static/js/nav-shell-pending.js",
    ):
        asset = auth_client.get(path)
        assert asset.status_code == 200, path
    csp = resp.headers.get("Content-Security-Policy") or ""
    assert "'nonce-" in csp
    assert "unsafe-eval" not in csp
    assert "unsafe-inline" not in csp.split("style-src")[0]
    assert "'unsafe-inline'" in csp.split("style-src", 1)[1]
