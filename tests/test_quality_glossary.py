"""اختبارات قاموس المصطلحات."""

from backend.core.quality_glossary import (
    get_term,
    glossary_by_category,
    glossary_json_for_client,
    user_visible_glossary,
    write_static_glossary_json,
)


def test_user_glossary_includes_core_symbols():
    ids = {t["id"] for t in user_visible_glossary()}
    assert "ig" in ids
    assert "glo" in ids
    assert "plo" in ids
    assert "clo" in ids
    assert "kpi" in ids
    assert "so" in ids
    assert "manual_binding" in ids
    assert "hybrid_indicator" not in ids
    assert "auto_indicator" not in ids


def test_glossary_terms_have_symbol_column():
    for term in user_visible_glossary():
        assert "symbol" in term
        assert term.get("title_ar")
        assert term.get("definition_ar")


def test_glossary_no_internal_codes_in_titles():
    data = glossary_json_for_client()
    terms = data.get("terms") or {}
    assert data.get("version") == 2
    for tid, term in terms.items():
        assert "GV-" not in (term.get("title_ar") or "")
        assert term.get("id") == tid


def test_get_term_ig_definition():
    t = get_term("ig")
    assert t is not None
    assert t["symbol"] == "IG"
    assert "استراتيجية" in t["title_ar"]
    assert t["definition_ar"]


def test_glossary_by_category_groups():
    groups = glossary_by_category()
    assert groups
    assert groups[0]["category_ar"] == "رموز التخطيط والمخرجات"
    assert all("category_ar" in g and "terms" in g for g in groups)
    first_row = groups[0]["terms"][0]
    assert "symbol" in first_row


def test_static_json_synced():
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "frontend" / "static" / "data" / "quality_glossary.json"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    expected = glossary_json_for_client()
    assert on_disk == expected
    assert on_disk.get("groups")
    assert on_disk["groups"][0]["terms"][0].get("symbol")


def test_glossary_api_route(app):
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        r = c.get("/academic_quality/api/glossary")
        assert r.status_code == 200
        data = r.get_json()
        assert "terms" in data
        assert "ig" in data["terms"]
        assert data["terms"]["ig"].get("symbol") == "IG"
        assert data.get("groups")

        r2 = c.get("/academic_quality/glossary")
        assert r2.status_code == 200
        html = r2.get_data(as_text=True) or ""
        assert "glossaryRoot" in html
        assert "glossary-symbol" in html
        assert "الرمز / الاختصار" in html
