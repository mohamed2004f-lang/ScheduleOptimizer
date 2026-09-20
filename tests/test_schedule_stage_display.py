"""اختبارات إثراء صفوف الجدول ومسارات العرض/الأوقات."""

from __future__ import annotations

import json


def test_list_schedule_rows_includes_stage_fields(auth_client, db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO courses (course_name, course_code, units) VALUES (?, ?, 3)",
        ("مقرر مرحلة اختبار", "ME 205"),
    )
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, semester)
        VALUES (?, 'السبت', '09:00-11:00', '101', 'أ', ?)
        """,
        ("مقرر مرحلة اختبار", "خريف 1447"),
    )
    db_conn.commit()

    r = auth_client.get("/schedule/list_schedule_rows")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, list)
    # إن وُجد الصف ضمن نطاق الفصل الحالي يجب أن يحمل حقول المرحلة
    for row in data:
        assert "section_id" in row
        assert "course_name" in row
        assert "day" in row
        assert "time" in row
        if "stage_bucket" in row:
            assert row["stage_bucket"] in ("general_or_y1", "y3", "y4y5")
            assert "is_college_general" in row
            assert "course_code" in row
    hit = [x for x in data if x.get("course_name") == "مقرر مرحلة اختبار"]
    if hit:
        assert hit[0].get("stage_bucket") == "general_or_y1"
        assert "ME" in str(hit[0].get("course_code") or "").upper() or hit[0].get("course_code") == "ME 205"


def test_display_layout_endpoint(auth_client):
    r = auth_client.get("/schedule/display_layout")
    assert r.status_code == 200
    j = r.get_json()
    assert j.get("status") == "ok"
    assert "stage_grid_enabled" in j
    assert "layout_mode" in j
    assert "use_stage_matrix" in j
    assert isinstance(j.get("buckets"), list)


def test_time_slots_by_day_roundtrip(auth_client):
    payload = {
        "by_day": {
            "السبت": ["08:00-10:00", "10:00-12:00"],
            "الأحد": ["08:00-10:00"],
        }
    }
    r = auth_client.post(
        "/schedule/time_slots",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert r.status_code == 200
    j = r.get_json()
    assert j.get("status") == "ok"
    assert isinstance(j.get("slots"), list)
    assert "08:00-10:00" in j["slots"]
    assert "10:00-12:00" in j["slots"]
    by_day = j.get("by_day") or {}
    assert "السبت" in by_day
    assert "08:00-10:00" in by_day["السبت"]

    g = auth_client.get("/schedule/time_slots")
    assert g.status_code == 200
    gj = g.get_json()
    assert isinstance(gj.get("slots"), list)
    assert isinstance(gj.get("by_day"), dict)


def test_print_preview_ok(auth_client):
    r = auth_client.get("/schedule/print_preview")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "معاينة" in body or "الجدول" in body


def test_results_page_uses_stage_grid_contract(auth_client):
    """مرحلة 8: صفحة النتائج تعرض الجدول عبر الراسمات المشتركة وليس زر تعارض وحده."""
    r = auth_client.get("/results")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "buildStageMatrixTimetableHtml" in body or "buildPersonalWeeklyTimetableHtml" in body
    assert "paintScheduleConflictActions" in body
    assert "/schedule/print_preview" in body
    assert "optResultsStudentConflicts" in body
    assert "optResultsConflictsOnly" in body
    # لا نعيد شبكة «يوجد تعارض» القديمة كالعرض الأساسي
    assert "يوجد تعارض (" not in body
