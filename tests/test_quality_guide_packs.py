"""اختبارات حزم دليل الجودة وجمهور المستخدمين."""

from __future__ import annotations

from backend.core.auth import compute_capabilities
from backend.core.quality_guide_packs import (
    QUALITY_CONTENT_PACKS,
    filter_packs_for_user,
    guide_audience_payload,
    pack_matches_audience,
    system_usage_topics_with_guide_keys,
)
from backend.core.quality_assistant_catalog import catalog_for_client, list_system_usage_topics


def test_packs_catalog_non_empty():
    assert len(QUALITY_CONTENT_PACKS) >= 10
    ids = {p["id"] for p in QUALITY_CONTENT_PACKS}
    assert "identity_workshop_edit" in ids
    assert "surveys_external_invites" in ids
    assert "supervisor_quality_slim" in ids


def test_dean_gets_invites_and_workshop():
    caps = compute_capabilities("college_dean", 0, "dean")
    packs = filter_packs_for_user(role="college_dean", active_mode="dean", caps=caps)
    ids = {p["id"] for p in packs}
    assert "surveys_external_invites" in ids
    assert "identity_workshop_edit" in ids or "identity_story_read" in ids


def test_hod_no_invites_has_results():
    caps = compute_capabilities("head_of_department", 0, "head")
    packs = filter_packs_for_user(role="head_of_department", active_mode="head", caps=caps)
    ids = {p["id"] for p in packs}
    assert "surveys_external_invites" not in ids
    assert "surveys_results" in ids or pack_matches_audience(
        next(p for p in QUALITY_CONTENT_PACKS if p["id"] == "surveys_results"),
        role="head_of_department",
        active_mode="head",
        caps=caps,
    )


def test_instructor_mode_hub_not_supervisor_menu():
    caps = compute_capabilities("instructor", 1, "instructor")
    packs = filter_packs_for_user(role="instructor", active_mode="instructor", caps=caps)
    ids = {p["id"] for p in packs}
    assert "instructor_quality_hub" in ids or "surveys_fill" in ids
    assert "surveys_external_invites" not in ids


def test_supervisor_mode_slim_pack():
    caps = compute_capabilities("instructor", 1, "supervisor")
    packs = filter_packs_for_user(role="instructor", active_mode="supervisor", caps=caps)
    ids = {p["id"] for p in packs}
    assert "supervisor_quality_slim" in ids
    assert "surveys_external_invites" not in ids


def test_quality_lead_flag_gets_results_supporting():
    caps = {"nav_surveys_results": True, "nav_academic_quality_dashboard": True}
    packs = filter_packs_for_user(
        role="staff",
        active_mode=None,
        caps=caps,
        is_college_quality_lead=True,
    )
    ids = {p["id"] for p in packs}
    assert "college_quality_lead" in ids or "surveys_results" in ids


def test_audience_payload_structure():
    caps = compute_capabilities("college_dean", 0, "dean")
    payload = guide_audience_payload(
        role="college_dean",
        active_mode="dean",
        caps=caps,
        department_label="كلية",
    )
    assert payload["v"] == 1
    assert "packs" in payload
    assert "allowed_guide_keys" in payload
    assert "maintenance_note_ar" in payload
    assert payload["is_primary_quality_audience"] is True


def test_system_usage_topics_have_guide_keys():
    topics = system_usage_topics_with_guide_keys()
    by_code = {t["code"]: t for t in topics}
    assert by_code["quality_dashboard"].get("page_guide_key") == "academic_quality_dashboard"
    surveys = by_code["surveys"]
    assert "عميد" in " ".join(surveys.get("steps_ar") or []) or any(
        "دعوات" in (x.get("label_ar") or "") for x in (surveys.get("links") or [])
    )
    listed = list_system_usage_topics()
    assert any(t.get("page_guide_key") for t in listed)
    cat = catalog_for_client()
    assert any(t.get("page_guide_key") for t in (cat.get("system_usage_topics") or []))


def test_guide_catalog_js_has_new_keys():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "frontend" / "static" / "js" / "guide-catalog.js").read_text(
        encoding="utf-8"
    )
    for key in (
        "college_identity_story",
        "instructor_quality_hub",
        "supervisor_quality_slim",
        "survey_invites",
        "survey_results",
    ):
        assert f'"{key}"' in text


def test_page_guide_js_filters_caps():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "frontend" / "static" / "js" / "page-guide.js").read_text(
        encoding="utf-8"
    )
    assert "forCaps" in text
    assert "forFlags" in text
    assert "forModes" in text
    assert "/academic_quality/api/guide/audience" in text
