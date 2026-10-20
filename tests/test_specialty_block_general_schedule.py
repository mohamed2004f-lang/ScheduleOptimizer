# -*- coding: utf-8 -*-
"""منع الأقسام التخصصية من إضافة مقررات الاتجاه العام للجدول."""

from __future__ import annotations

import uuid

from backend.services import schedule as schedule_svc


def test_specialty_blocked_helper(db_conn, monkeypatch):
    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    row = cur.execute(
        "SELECT id FROM departments WHERE UPPER(COALESCE(code,'')) IN ('GENERAL','GEN','GS') LIMIT 1"
    ).fetchone()
    if row:
        gen_id = int(row[0])
    else:
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES ('GENERAL', 'اتجاه عام', 'General', 1)"
        )
        gen_id = int(cur.execute("SELECT id FROM departments WHERE code='GENERAL' LIMIT 1").fetchone()[0])
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"ME{uid}".upper()[:12], f"ميكانيكا {uid}", "Mech"),
    )
    mech_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (f"ME{uid}".upper()[:12],)).fetchone()[0])
    course = f"رياضيات عامة {uid}"
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (course, f"GS{uid}"[:8], gen_id),
    )
    db_conn.commit()

    monkeypatch.setattr(
        schedule_svc,
        "_effective_schedule_department_scope_id",
        lambda conn: mech_id,
    )
    monkeypatch.setattr(
        schedule_svc,
        "_normalize_role",
        lambda r: "head_of_department",
    )
    monkeypatch.setattr(schedule_svc, "session", {"user_role": "head_of_department", "user": "hod"})

    msg = schedule_svc._specialty_blocked_from_general_course(db_conn, course)
    assert msg and "الاتجاه العام" in msg

    # قسم GENERAL مسموح
    monkeypatch.setattr(
        schedule_svc,
        "_effective_schedule_department_scope_id",
        lambda conn: gen_id,
    )
    assert schedule_svc._specialty_blocked_from_general_course(db_conn, course) is None
