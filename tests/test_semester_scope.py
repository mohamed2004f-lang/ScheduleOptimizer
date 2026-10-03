"""اختبارات تصنيف فصل كشف الدرجات (اتجاه عام / قسم + شعبة)."""

from __future__ import annotations

import uuid

from backend.services.grades import (
    _semester_scope_badge,
    _suggest_semester_scope,
    _upsert_semester_scope,
)


def test_semester_scope_badge_labels():
    assert _semester_scope_badge({"scope_kind": "college_general"}) == "اتجاه عام"
    assert "مدني" in _semester_scope_badge(
        {"scope_kind": "department", "department_label": "مدني", "group_code": "أ"}
    )
    assert "شعبة" in _semester_scope_badge(
        {"scope_kind": "department", "department_label": "مدني", "group_code": "أ"}
    )


def test_upsert_and_suggest_semester_scope(app, db_conn):
    uid = uuid.uuid4().hex[:8]
    sid = f"S{uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"D{uid}"[:12], "قسم اختبار", "Test"),
    )
    dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (f"D{uid}"[:12],)).fetchone()[0]
    cur.execute(
        "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
        (sid, "طالب", dept_id),
    )
    db_conn.commit()

    saved = _upsert_semester_scope(
        db_conn,
        sid,
        "خريف 2024/2025",
        {
            "scope_kind": "department",
            "department_id": dept_id,
            "group_code": "ب",
            "department_label": "قسم اختبار",
        },
        actor="tester",
    )
    assert saved is not None
    assert saved["scope_kind"] == "department"
    assert saved["group_code"] == "ب"
    db_conn.commit()

    suggested = _suggest_semester_scope(db_conn, sid, "خريف 2024/2025")
    assert suggested.get("source") == "saved"
    assert suggested.get("group_code") == "ب"
    assert "قسم اختبار" in (suggested.get("badge") or "")
