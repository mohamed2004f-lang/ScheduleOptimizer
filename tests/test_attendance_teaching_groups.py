"""حضور مجموعات التدريس أ/ب — تصفية الكشف مع بقاء السجل على مستوى المقرر."""
from __future__ import annotations

import uuid

from backend.services import teaching_groups as tg
from backend.services.attendance_export_core import (
    expand_attendance_course_options,
    format_attendance_course_option,
    merge_course_group_filters,
    parse_attendance_course_option,
)
from backend.services.attendance_registration import (
    set_attendance_term_weeks,
)
from tests.test_attendance_registration import _ensure_attendance_table


def _set_current_term(cur, semester: str = "خريف 44-45") -> str:
    parts = semester.rsplit(" ", 1)
    tname = parts[0] if len(parts) == 2 else semester
    tyear = parts[1] if len(parts) == 2 else ""
    cur.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', ?)",
        (tname,),
    )
    cur.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', ?)",
        (tyear,),
    )
    return semester


def test_parse_format_attendance_option_key():
    assert parse_attendance_course_option("رياضيات 1") == ("رياضيات 1", None)
    assert parse_attendance_course_option("رياضيات 1||") == ("رياضيات 1", None)
    assert parse_attendance_course_option("رياضيات 1||42") == ("رياضيات 1", 42)
    assert format_attendance_course_option("رياضيات 1", None).endswith("||")
    assert format_attendance_course_option("رياضيات 1", 7) == "رياضيات 1||7"
    merged = merge_course_group_filters(
        [("مقرر", 1), ("مقرر", 2), ("مقرر", None), ("آخر", 9)]
    )
    assert merged["مقرر"] is None
    assert merged["آخر"] == {9}


def test_hod_roster_filters_by_teaching_group(app, db_conn):
    _ensure_attendance_table(db_conn)
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    sem = _set_current_term(cur)
    code = f"AH{uid}"[:12].upper()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (code, "ميكانيكا", "Mech"),
    )
    dept_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (code,)).fetchone()[0])
    course = f"ديناميكا-{uid}"
    cur.execute(
        "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (course, f"DY{uid[:4]}", dept_id),
    )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"أ-{uid}", dept_id),
    )
    inst_a = int(cur.lastrowid)
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"ب-{uid}", dept_id),
    )
    inst_b = int(cur.lastrowid)
    s_a, s_b = f"SA{uid}", f"SB{uid}"
    for sid, name in ((s_a, "طالب أ"), (s_b, "طالب ب")):
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id, enrollment_status) "
            "VALUES (?, ?, ?, 'active')",
            (sid, name, dept_id),
        )
        cur.execute(
            "INSERT INTO registrations (student_id, course_name, semester) VALUES (?, ?, ?)",
            (sid, course, sem),
        )
    section_ids = []
    for day in ("الأحد", "الإثنين"):
        cur.execute(
            """
            INSERT INTO schedule (course_name, day, time, room, instructor_id, semester, department_id)
            VALUES (?, ?, '08:00-10:00', '1', ?, ?, ?)
            """,
            (course, day, inst_a if day == "الأحد" else inst_b, sem, dept_id),
        )
        section_ids.append(int(cur.lastrowid))
    db_conn.commit()
    tg.setup_course_offering(
        db_conn,
        course_name=course,
        semester=sem,
        department_id=dept_id,
        group_kind="split",
        groups=[
            {"group_code": "A", "instructor_id": inst_a, "section_ids": [section_ids[0]]},
            {"group_code": "B", "instructor_id": inst_b, "section_ids": [section_ids[1]]},
        ],
    )
    groups = tg.list_teaching_groups(
        db_conn, semester=sem, department_id=dept_id, course_name=course
    )
    g_a = next(g for g in groups if g.get("group_code") == "A")
    g_b = next(g for g in groups if g.get("group_code") == "B")
    tg.assign_students_to_teaching_group(
        db_conn, teaching_group_id=int(g_a["id"]), student_ids=[s_a], action="assign"
    )
    tg.assign_students_to_teaching_group(
        db_conn, teaching_group_id=int(g_b["id"]), student_ids=[s_b], action="assign"
    )

    opts = expand_attendance_course_options(
        db_conn,
        [{"course_name": course, "course_code": "X", "units": 3}],
        semester=sem,
        role_bucket="head_of_department",
    )
    labels = {o.get("group_label") for o in opts}
    assert "الكل" in labels
    assert "A" in labels
    assert "B" in labels

    pw = cur.execute(
        "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
    ).fetchone()[0]
    head_user = f"head_att_tg_{uid}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) "
        "VALUES (?, ?, 'head_of_department', ?)",
        (head_user, pw, dept_id),
    )
    set_attendance_term_weeks(db_conn, 16)
    db_conn.commit()

    with app.test_client() as c:
        assert c.post(
            "/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"}
        ).status_code == 200
        allowed = c.get("/students/attendance_allowed_courses")
        assert allowed.status_code == 200
        names = {
            (x.get("course_name"), x.get("group_label") or "")
            for x in (allowed.get_json() or {}).get("courses") or []
        }
        assert (course, "الكل") in names
        assert (course, "A") in names
        assert (course, "B") in names

        all_roster = c.get(
            f"/students/attendance/register/roster?course={course}&week=1"
        )
        assert all_roster.status_code == 200
        all_ids = {s["student_id"] for s in all_roster.get_json()["students"]}
        assert all_ids == {s_a, s_b}

        a_roster = c.get(
            f"/students/attendance/register/roster?course={course}&week=1"
            f"&teaching_group_id={int(g_a['id'])}"
        )
        assert a_roster.status_code == 200
        a_body = a_roster.get_json()
        assert {s["student_id"] for s in a_body["students"]} == {s_a}
        assert a_body.get("group_label") == "A"

        save = c.post(
            "/students/attendance/register/save",
            json={
                "course_name": course,
                "week_number": 1,
                "teaching_group_id": int(g_a["id"]),
                "marks": [
                    {"student_id": s_a, "status": "present"},
                    {"student_id": s_b, "status": "absent"},
                ],
            },
        )
        assert save.status_code == 200, save.get_data(as_text=True)
        # s_b خارج المجموعة — يُتجاهل
        assert save.get_json()["saved"] == 1


def test_instructor_sees_only_own_teaching_group(app, db_conn):
    _ensure_attendance_table(db_conn)
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    sem = _set_current_term(cur)
    code = f"AI{uid}"[:12].upper()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (code, "كهرباء", "Elec"),
    )
    dept_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (code,)).fetchone()[0])
    course = f"دوائر-{uid}"
    cur.execute(
        "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (course, f"CK{uid[:4]}", dept_id),
    )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"م1-{uid}", dept_id),
    )
    inst_a = int(cur.lastrowid)
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"م2-{uid}", dept_id),
    )
    inst_b = int(cur.lastrowid)
    s_a, s_b = f"IA{uid}", f"IB{uid}"
    for sid, name in ((s_a, "أ"), (s_b, "ب")):
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id, enrollment_status) "
            "VALUES (?, ?, ?, 'active')",
            (sid, name, dept_id),
        )
        cur.execute(
            "INSERT INTO registrations (student_id, course_name, semester) VALUES (?, ?, ?)",
            (sid, course, sem),
        )
    section_ids = []
    for day, iid in (("الأحد", inst_a), ("الإثنين", inst_b)):
        cur.execute(
            """
            INSERT INTO schedule
              (course_name, day, time, room, instructor, instructor_id, semester, department_id)
            VALUES (?, ?, '08:00-10:00', '1', ?, ?, ?, ?)
            """,
            (course, day, f"م-{iid}", iid, sem, dept_id),
        )
        section_ids.append(int(cur.lastrowid))
    db_conn.commit()
    tg.setup_course_offering(
        db_conn,
        course_name=course,
        semester=sem,
        department_id=dept_id,
        group_kind="split",
        groups=[
            {"group_code": "A", "instructor_id": inst_a, "section_ids": [section_ids[0]]},
            {"group_code": "B", "instructor_id": inst_b, "section_ids": [section_ids[1]]},
        ],
    )
    groups = tg.list_teaching_groups(
        db_conn, semester=sem, department_id=dept_id, course_name=course
    )
    g_a = next(g for g in groups if g.get("group_code") == "A")
    g_b = next(g for g in groups if g.get("group_code") == "B")
    tg.assign_students_to_teaching_group(
        db_conn, teaching_group_id=int(g_a["id"]), student_ids=[s_a], action="assign"
    )
    tg.assign_students_to_teaching_group(
        db_conn, teaching_group_id=int(g_b["id"]), student_ids=[s_b], action="assign"
    )

    pw = cur.execute(
        "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
    ).fetchone()[0]
    user_a = f"inst_att_a_{uid}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, instructor_id, department_id) "
        "VALUES (?, ?, 'instructor', ?, ?)",
        (user_a, pw, inst_a, dept_id),
    )
    set_attendance_term_weeks(db_conn, 16)
    db_conn.commit()

    with app.test_client() as c:
        assert c.post(
            "/auth/login", json={"username": user_a, "password": "TestP@ssw0rd!"}
        ).status_code == 200
        allowed = c.get("/students/attendance_allowed_courses")
        assert allowed.status_code == 200
        courses = (allowed.get_json() or {}).get("courses") or []
        mine = [x for x in courses if x.get("course_name") == course]
        assert mine
        assert all(x.get("teaching_group_id") == int(g_a["id"]) for x in mine)
        assert all(x.get("group_label") == "A" for x in mine)

        roster = c.get(
            f"/students/attendance/register/roster?course={course}&week=1"
            f"&teaching_group_id={int(g_a['id'])}"
        )
        assert roster.status_code == 200
        assert {s["student_id"] for s in roster.get_json()["students"]} == {s_a}

        # محاولة طلب مجموعة المدرّس الآخر → لا طلبة (أو مقرر غير متاح)
        foreign = c.get(
            f"/students/attendance/register/roster?course={course}&week=1"
            f"&teaching_group_id={int(g_b['id'])}"
        )
        # إما 403/404 أو قائمة فارغة بعد تقاطع المجموعات
        if foreign.status_code == 200:
            assert foreign.get_json().get("students") == []
        else:
            assert foreign.status_code in (403, 404)
