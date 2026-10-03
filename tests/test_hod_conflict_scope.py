# -*- coding: utf-8 -*-
"""عزل تعارضات الجدول حسب نطاق رئيس القسم."""


def test_filter_flat_conflicts_hod_sees_own_students_only(app, db_conn):
    from backend.core.auth import SESSION_ACTIVE_MODE
    from backend.services.students import (
        _filter_flat_student_conflicts_for_actor,
        normalize_sid,
    )

    cur = db_conn.cursor()
    uid = "99001"
    # قسمان
    cur.execute(
        "INSERT OR IGNORE INTO departments (id, code, name_ar) VALUES (?, ?, ?)",
        (9901, "RE9901", "طاقات اختبار"),
    )
    cur.execute(
        "INSERT OR IGNORE INTO departments (id, code, name_ar) VALUES (?, ?, ?)",
        (9902, "ME9902", "ميكانيكا اختبار"),
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO users (username, password_hash, role, department_id)
        VALUES (?, ?, 'head_of_department', ?)
        """,
        (f"hod_re_{uid}", "x", 9901),
    )
    cur.execute(
        "INSERT OR IGNORE INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
        ("SRE9901", "طالب طاقات", 9901),
    )
    cur.execute(
        "INSERT OR IGNORE INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
        ("SME9902", "طالب ميكانيكا", 9902),
    )
    db_conn.commit()

    flat = [
        {
            "student_id": "SME9902",
            "day": "الأحد",
            "time": "09:00-13:00",
            "conflicting_sections": "قياسات هندسية، مقاومة المواد 1",
        },
        {
            "student_id": "SRE9901",
            "day": "الإثنين",
            "time": "09:00-11:00",
            "conflicting_sections": "طاقة شمسية",
        },
    ]

    with app.test_request_context("/"):
        from flask import session

        session["user"] = f"hod_re_{uid}"
        session["username"] = f"hod_re_{uid}"
        session["user_role"] = "head_of_department"
        session[SESSION_ACTIVE_MODE] = "head"
        filtered = _filter_flat_student_conflicts_for_actor(db_conn, flat)

    sids = {normalize_sid(r["student_id"]) for r in filtered}
    assert "SRE9901" in sids
    assert "SME9902" not in sids
