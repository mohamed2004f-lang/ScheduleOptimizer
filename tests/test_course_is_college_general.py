# -*- coding: utf-8 -*-
"""regression: course_is_college_general يجب ألا يوسّم كل المقررات بسبب title_ar."""
from __future__ import annotations

import uuid

from backend.core.department_scope_policy import course_is_college_general


def test_specialty_course_not_false_general_via_title_tautology(db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) "
        "VALUES ('GENERAL', 'الاتجاه العام', 'General', 1)"
    )
    gen_id = int(cur.execute("SELECT id FROM departments WHERE code='GENERAL'").fetchone()[0])
    ccode = f"ME{uid}"[:12].upper()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (ccode, "ميكانيكا", "Mech"),
    )
    dep_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (ccode,)).fetchone()[0])

    # مقرر اتجاه عام حقيقي
    cur.execute(
        "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (f"GenMath-{uid}", f"G{uid[:4]}", gen_id),
    )
    # مقرر تخصص مع course_master
    spec_name = f"رياضيات III-{uid}"
    try:
        cur.execute(
            "INSERT INTO course_master (title_ar, default_units, grading_mode, assessment_type) "
            "VALUES (?, 3, 'partial_final', 'theoretical')",
            (spec_name,),
        )
        mid = int(cur.execute("SELECT id FROM course_master WHERE title_ar=?", (spec_name,)).fetchone()[0])
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id, course_master_id) "
            "VALUES (?, ?, 3, ?, ?)",
            (spec_name, f"GS{uid[:3]}", dep_id, mid),
        )
    except Exception:
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
            (spec_name, f"GS{uid[:3]}", dep_id),
        )

    # صف college_general غير مرتبط بهذا المقرر (لكشف التوتولوجيا القديمة)
    prog = cur.execute("SELECT id FROM programs LIMIT 1").fetchone()
    if prog:
        pid = int(prog[0] if not hasattr(prog, "keys") else prog["id"])
        try:
            cur.execute(
                "INSERT INTO course_master (title_ar, default_units, grading_mode, assessment_type) "
                "VALUES (?, 3, 'partial_final', 'theoretical')",
                (f"OtherGen-{uid}",),
            )
            omid = int(
                cur.execute(
                    "SELECT id FROM course_master WHERE title_ar=?", (f"OtherGen-{uid}",)
                ).fetchone()[0]
            )
            cur.execute(
                """
                INSERT INTO program_courses
                (program_id, course_master_id, course_code, requirement_scope, is_active)
                VALUES (?, ?, ?, 'college_general', 1)
                """,
                (pid, omid, f"OG{uid[:3]}"),
            )
        except Exception:
            pass

    db_conn.commit()
    assert course_is_college_general(db_conn, f"GenMath-{uid}") is True
    assert course_is_college_general(db_conn, spec_name) is False
