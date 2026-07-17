"""اختبارات أساسية لصفحة المقرر والمكتبة والقفل."""
from __future__ import annotations

import json

import pytest

from backend.services.course_pages import (
    STATUS_DRAFT,
    STATUS_EMPTY,
    STATUS_LOCKED,
    _apply_field_save,
    _get_or_create_catalog,
    ensure_course_pages_schema,
)


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    import sqlite3

    db = tmp_path / "cp.db"
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
    ensure_course_pages_schema(c)
    yield c
    c.close()


def test_catalog_create_and_lock_objectives(conn, monkeypatch):
    monkeypatch.setattr("backend.services.course_pages._username", lambda: "prof1")
    monkeypatch.setattr("backend.services.course_pages._session_instructor_id", lambda: 1)
    monkeypatch.setattr(
        "backend.services.course_pages._instructor_assigned_to_course",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr("backend.services.course_pages._is_hod_or_admin", lambda: False)

    cat = _get_or_create_catalog(conn, "برمجة 1")
    assert cat["field_status"]["objectives"] == STATUS_EMPTY

    items = [{"title": "فهم أساسيات البرمجة"}, {"title": "كتابة برامج بسيطة"}]
    updated = _apply_field_save(conn, cat, "objectives", items, finalize=False)
    assert updated["field_status"]["objectives"] == STATUS_DRAFT
    assert len(updated["objectives"]) == 2

    updated2 = _apply_field_save(conn, updated, "objectives", items, finalize=True)
    assert updated2["field_status"]["objectives"] == STATUS_LOCKED

    with pytest.raises(PermissionError):
        _apply_field_save(conn, updated2, "objectives", [{"title": "تغيير"}], finalize=True)


def test_assessment_catalog_seed_and_parse_refs(conn):
    from backend.services.assessment_plan import (
        assessment_plan_total,
        assessment_plan_to_methods,
        validate_assessment_plan,
    )
    from backend.services.course_pages import parse_references_text

    plan = {
        "midterm": 20,
        "practical": 20,
        "final": 40,
        "coursework": {
            "quiz": 5,
            "assignment": 5,
            "report": 5,
            "participation": 2,
            "presentation": 2,
            "worksheet": 1,
            "other": 0,
            "other_label": "",
        },
    }
    assert assessment_plan_total(plan) == 100
    ok, msg = validate_assessment_plan(plan)
    assert ok, msg
    methods = assessment_plan_to_methods(plan)
    assert any(m["code"] == "coursework" for m in methods)
    bad = dict(plan)
    bad["final"] = 41
    ok2, msg2 = validate_assessment_plan(bad)
    assert not ok2 and "100" in msg2
    refs = parse_references_text("كتاب أ\nhttps://example.com\n\nكتاب ب")
    assert len(refs) == 3
    assert refs[1]["ref_type"] == "website"


def test_validate_submit_requires_recommendations():
    from backend.services.course_delivery import validate_quality_report_for_submit

    rep = {
        "items": [{"topic_id": 1, "completion_pct": 80, "incomplete_reason": ""}],
        "extra_topics": [],
        "references": [
            {"ref_type": "book", "title": "A", "publication_date": "2020"},
            {"ref_type": "book", "title": "B", "publication_date": "2021"},
        ],
        "assessment_methods": [{"method_label": "نهائي"}],
        "instructor_recommendations": "",
    }
    err = validate_quality_report_for_submit(
        rep, require_books=True, require_assessments=True, require_recommendations=True
    )
    assert err and "توصيات" in err
    rep["instructor_recommendations"] = "يُفضّل زيادة ساعات المشروع العملي"
    assert (
        validate_quality_report_for_submit(
            rep, require_books=True, require_assessments=True, require_recommendations=True
        )
        is None
    )


def test_hod_can_edit_locked(conn, monkeypatch):
    monkeypatch.setattr("backend.services.course_pages._username", lambda: "hod1")
    monkeypatch.setattr("backend.services.course_pages._session_instructor_id", lambda: None)
    monkeypatch.setattr("backend.services.course_pages._is_hod_or_admin", lambda: True)
    monkeypatch.setattr(
        "backend.services.course_pages.assert_hod_for_course_operation",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "backend.services.course_pages.hod_may_operate_on_course",
        lambda *_a, **_k: True,
    )

    cat = _get_or_create_catalog(conn, "رياضيات")
    # seed locked
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE course_catalog_pages
        SET objectives_json=?, objectives_status=?
        WHERE id=?
        """,
        (json.dumps([{"title": "قديم"}], ensure_ascii=False), STATUS_LOCKED, int(cat["id"])),
    )
    conn.commit()
    cat = _get_or_create_catalog(conn, "رياضيات")
    updated = _apply_field_save(
        conn, cat, "objectives", [{"title": "جديد من الرئيس"}], finalize=True
    )
    assert updated["objectives"][0]["title"] == "جديد من الرئيس"
    assert updated["field_status"]["objectives"] == STATUS_LOCKED


def test_course_page_readiness_snapshot(conn):
    from backend.services.course_pages import course_page_readiness_snapshot

    snap = course_page_readiness_snapshot(
        conn,
        course_name="مقرر اختبار",
        instructor_id=9,
        section_id=1,
    )
    assert snap["ready"] is False
    assert snap["assessment_ok"] is False
    assert snap["materials_published"] == 0
    assert snap["pct"] == 0
    assert any("أهداف" in b or "مفردات" in b or "تقييم" in b for b in snap["blockers"])
    assert "course_page" in snap["course_page_url"]


def test_outcome_links_and_weekly_normalize(conn, monkeypatch):
    from backend.services.course_pages import (
        _normalize_outcome_links,
        _normalize_weeks,
        ensure_course_pages_schema,
        save_weekly_plan,
        get_weekly_plan_bundle,
    )

    monkeypatch.setattr("backend.services.course_pages._username", lambda: "tester")
    ensure_course_pages_schema(conn)
    links = _normalize_outcome_links(
        [{"clo_code": "CLO1", "objective_indexes": [0, 0, 1], "plo_ids": ["3"]}],
        [{"code": "CLO1"}, {"code": "CLO2"}],
    )
    assert links[0]["objective_indexes"] == [0, 1]
    assert links[0]["plo_ids"] == [3]
    assert any(x["clo_code"] == "CLO2" for x in links)
    weeks = _normalize_weeks([{"week_no": 2, "week_topic": "باب 1", "lecture_status": "done", "linked_clo": "CLO1"}])
    assert weeks[0]["lecture_status"] == "done"
    bundle = save_weekly_plan(
        conn,
        course_name="مقرر خطة",
        instructor_id=5,
        weeks=weeks,
        semester="خريف 1446",
    )
    assert bundle["my_plan"] and len(bundle["my_plan"]["weeks"]) == 1
    again = get_weekly_plan_bundle(conn, course_name="مقرر خطة", instructor_id=5, semester="خريف 1446")
    assert again["my_plan"]["weeks"][0]["week_topic"] == "باب 1"
