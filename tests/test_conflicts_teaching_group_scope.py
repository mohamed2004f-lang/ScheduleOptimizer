# -*- coding: utf-8 -*-
"""تضارب الطالب يُحسب على حصص مجموعته فقط وليس كل شعب المقرر."""

from __future__ import annotations

import uuid

from backend.services import teaching_groups as tg
from backend.services.students import compute_per_student_conflicts


def test_conflict_uses_only_assigned_teaching_group_slots(db_conn):
    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"CF{uid}".upper()[:12], f"قسم {uid}", "CF"),
    )
    dept = int(
        cur.execute(
            "SELECT id FROM departments WHERE code = ?", (f"CF{uid}".upper()[:12],)
        ).fetchone()[0]
    )
    sem = f"خريف {uid}"
    course_a = f"إحصاء {uid}"
    course_b = f"فيزياء {uid}"
    for name, code in ((course_a, f"ST{uid}"[:8]), (course_b, f"PH{uid}"[:8])):
        cur.execute(
            "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
            (name, code, dept),
        )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"د. {uid}", dept),
    )
    iid = int(cur.lastrowid)
    sid = f"S{uid}"
    cur.execute(
        "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
        (sid, "طالب تضارب", dept),
    )
    # مقرر الإحصاء: شعبتان في نفس الوقت (A و B)
    section_ids = []
    for gcode, day in (("A", "الثلاثاء"), ("B", "الأربعاء")):
        cur.execute(
            """
            INSERT INTO schedule (course_name, day, time, room, instructor_id, semester, department_id)
            VALUES (?, ?, '09:00-12:00', '1', ?, ?, ?)
            """,
            (course_a, day, iid, sem, dept),
        )
        section_ids.append(int(cur.lastrowid))
    # مقرر آخر يتعارض مع أربعاء فقط
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor_id, semester, department_id)
        VALUES (?, 'الأربعاء', '09:00-12:00', '2', ?, ?, ?)
        """,
        (course_b, iid, sem, dept),
    )
    cur.execute(
        "INSERT INTO registrations (student_id, course_name, semester) VALUES (?, ?, ?)",
        (sid, course_a, sem),
    )
    cur.execute(
        "INSERT INTO registrations (student_id, course_name, semester) VALUES (?, ?, ?)",
        (sid, course_b, sem),
    )
    db_conn.commit()

    tg.setup_course_offering(
        db_conn,
        course_name=course_a,
        semester=sem,
        department_id=dept,
        group_kind="split",
        groups=[
            {"group_code": "A", "instructor_id": iid, "section_ids": [section_ids[0]]},
            {"group_code": "B", "instructor_id": iid, "section_ids": [section_ids[1]]},
        ],
    )
    groups = tg.list_teaching_groups(
        db_conn, semester=sem, department_id=dept, course_name=course_a
    )
    g_a = next(g for g in groups if g.get("group_code") == "A")
    g_b = next(g for g in groups if g.get("group_code") == "B")

    # موزَّع على A فقط → لا تعارض مع فيزياء (أربعاء)
    tg.assign_students_to_teaching_group(
        db_conn, teaching_group_id=int(g_a["id"]), student_ids=[sid], action="assign"
    )
    conflicts_a = compute_per_student_conflicts(db_conn, prefer_schedule=True)
    mine_a = [c for c in conflicts_a if c.get("student_id") == sid]
    assert mine_a == [], mine_a

    # نقل إلى B → يتعارض مع فيزياء الأربعاء
    tg.assign_students_to_teaching_group(
        db_conn, teaching_group_id=int(g_b["id"]), student_ids=[sid], action="assign"
    )
    conflicts_b = compute_per_student_conflicts(db_conn, prefer_schedule=True)
    mine_b = [c for c in conflicts_b if c.get("student_id") == sid]
    assert len(mine_b) >= 1, mine_b
    assert any(course_a in (c.get("conflicting_sections") or "") for c in mine_b)
