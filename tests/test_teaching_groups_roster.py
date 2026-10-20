"""تعيين طلبة لمجموعات التدريس من صفحة الإعداد."""

from __future__ import annotations

import uuid

from backend.services import teaching_groups as tg


def _seed(db_conn, *, semester="خريف 44-45"):
    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"RO{uid}".upper()[:12], f"قسم {uid}", "RO"),
    )
    dept_id = cur.execute(
        "SELECT id FROM departments WHERE code = ?", (f"RO{uid}".upper()[:12],)
    ).fetchone()[0]
    course = f"إحصاء {uid}"
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (course, f"ST{uid}"[:8], dept_id),
    )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"د. {uid}", dept_id),
    )
    inst_id = int(cur.lastrowid)
    students = []
    for i in range(3):
        sid = f"S{uid}{i}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
            (sid, f"طالب {i}", dept_id),
        )
        cur.execute(
            "INSERT INTO registrations (student_id, course_name, semester) VALUES (?, ?, ?)",
            (sid, course, semester),
        )
        students.append(sid)
    section_ids = []
    for day, time in [("الأحد", "09:00-12:00"), ("الإثنين", "09:00-12:00")]:
        cur.execute(
            """
            INSERT INTO schedule (course_name, day, time, room, instructor_id, semester, department_id)
            VALUES (?, ?, ?, '1', ?, ?, ?)
            """,
            (course, day, time, inst_id, semester, dept_id),
        )
        section_ids.append(int(cur.lastrowid))
    db_conn.commit()
    tg.setup_course_offering(
        db_conn,
        course_name=course,
        semester=semester,
        department_id=dept_id,
        group_kind="split",
        groups=[
            {"group_code": "A", "instructor_id": inst_id, "section_ids": [section_ids[0]]},
            {"group_code": "B", "instructor_id": inst_id, "section_ids": [section_ids[1]]},
        ],
    )
    groups = tg.list_teaching_groups(
        db_conn, semester=semester, department_id=dept_id, course_name=course
    )
    g_a = next(g for g in groups if g.get("group_code") == "A")
    g_b = next(g for g in groups if g.get("group_code") == "B")
    return {
        "course": course,
        "semester": semester,
        "dept_id": dept_id,
        "students": students,
        "group_a": int(g_a["id"]),
        "group_b": int(g_b["id"]),
    }


def test_roster_lists_unassigned_then_assign(db_conn):
    seed = _seed(db_conn)
    roster = tg.list_course_group_roster(
        db_conn,
        course_name=seed["course"],
        semester=seed["semester"],
        department_id=seed["dept_id"],
    )
    assert roster["totals"]["registered"] == 3
    assert roster["totals"]["unassigned"] == 3
    assert len(roster["unassigned"]) == 3
    assert isinstance(roster.get("sibling_meta"), dict)
    assert str(seed["group_a"]) in roster["sibling_meta"]
    assert roster["sibling_meta"][str(seed["group_a"])].get("badge")
    assert any(g.get("instructor_name") for g in roster["groups"])

    stats = tg.assign_students_to_teaching_group(
        db_conn,
        teaching_group_id=seed["group_a"],
        student_ids=seed["students"][:2],
        action="assign",
    )
    assert stats["updated"] >= 2
    assert stats.get("transferred_from", 0) == 0

    roster2 = tg.list_course_group_roster(
        db_conn,
        course_name=seed["course"],
        semester=seed["semester"],
        department_id=seed["dept_id"],
    )
    g_a = next(g for g in roster2["groups"] if g["teaching_group_id"] == seed["group_a"])
    assert g_a["member_count"] == 2
    assert roster2["totals"]["unassigned"] == 1

    # نقل إلى B
    stats_move = tg.assign_students_to_teaching_group(
        db_conn,
        teaching_group_id=seed["group_b"],
        student_ids=[seed["students"][0]],
        action="assign",
    )
    assert stats_move.get("transferred_from", 0) >= 1
    roster3 = tg.list_course_group_roster(
        db_conn,
        course_name=seed["course"],
        semester=seed["semester"],
        department_id=seed["dept_id"],
    )
    g_a = next(g for g in roster3["groups"] if g["teaching_group_id"] == seed["group_a"])
    g_b = next(g for g in roster3["groups"] if g["teaching_group_id"] == seed["group_b"])
    assert g_a["member_count"] == 1
    assert g_b["member_count"] == 1

    # إزالة
    tg.assign_students_to_teaching_group(
        db_conn,
        teaching_group_id=seed["group_b"],
        student_ids=[seed["students"][0]],
        action="unassign",
    )
    assert tg.count_registrations_for_teaching_group(db_conn, seed["group_b"]) == 0


def test_single_group_setup_assigns_all_registrations(db_conn):
    """مجموعة واحدة (محاضرات متعددة): كل المسجّلين يُربطون تلقائياً بالمجموعة."""
    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"SG{uid}".upper()[:12], f"قسم {uid}", "SG"),
    )
    dept_id = cur.execute(
        "SELECT id FROM departments WHERE code = ?", (f"SG{uid}".upper()[:12],)
    ).fetchone()[0]
    course = f"ورش {uid}"
    sem = "خريف 44-45"
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (course, f"WS{uid}"[:8], dept_id),
    )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"د. ورش {uid}", dept_id),
    )
    inst_id = int(cur.lastrowid)
    students = []
    for i in range(4):
        sid = f"W{uid}{i}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
            (sid, f"طالب ورش {i}", dept_id),
        )
        cur.execute(
            "INSERT INTO registrations (student_id, course_name, semester) VALUES (?, ?, ?)",
            (sid, course, sem),
        )
        students.append(sid)
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor_id, semester, department_id)
        VALUES (?, 'الأحد', '09:00-13:00', '1', ?, ?, ?)
        """,
        (course, inst_id, sem, dept_id),
    )
    section_id = int(cur.lastrowid)
    db_conn.commit()

    saved = tg.setup_course_offering(
        db_conn,
        course_name=course,
        semester=sem,
        department_id=dept_id,
        group_kind="single",
        groups=[{"instructor_id": inst_id, "section_ids": [section_id]}],
    )
    assert len(saved) == 1
    gid = int(saved[0]["id"])
    assert tg.count_registrations_for_teaching_group(db_conn, gid) == 4
    roster = tg.list_course_group_roster(
        db_conn, course_name=course, semester=sem, department_id=dept_id
    )
    assert roster["totals"]["unassigned"] == 0
    assert roster["totals"]["assigned"] == 4


def test_roster_includes_student_department_buckets(db_conn):
    """روستر يحمل قسم الطالب + تمييز الاتجاه العام عن الأقسام التخصصية."""
    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    # GENERAL
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
        (f"CV{uid}".upper()[:12], f"مدني {uid}", "Civil"),
    )
    civil_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (f"CV{uid}".upper()[:12],)).fetchone()[0])
    sem = f"خريف 44-{uid[:2]}"
    course = f"رياضيات عامة {uid}"
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (course, f"GS{uid}"[:8], gen_id),
    )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"د. عام {uid}", gen_id),
    )
    inst_id = int(cur.lastrowid)
    for code, day in (("A", "السبت"), ("B", "الأحد")):
        cur.execute(
            """
            INSERT INTO teaching_groups
                (course_name, semester, department_id, group_code, group_kind, instructor_id, is_active)
            VALUES (?, ?, ?, ?, 'split', ?, 1)
            """,
            (course, sem, gen_id, code, inst_id),
        )
        gid = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO schedule
                (course_name, day, time, room, instructor_id, semester, department_id, teaching_group_id)
            VALUES (?, ?, '09:00-11:00', 'G1', ?, ?, ?, ?)
            """,
            (course, day, inst_id, sem, gen_id, gid),
        )
    sid_gen = f"G{uid}"
    sid_cv = f"C{uid}"
    cur.execute(
        "INSERT INTO students (student_id, student_name, department_id, enrollment_status) VALUES (?, ?, ?, 'active')",
        (sid_gen, "طالب عام", gen_id),
    )
    cur.execute(
        "INSERT INTO students (student_id, student_name, department_id, enrollment_status) VALUES (?, ?, ?, 'active')",
        (sid_cv, "طالب مدني", civil_id),
    )
    groups = tg.list_teaching_groups(db_conn, semester=sem, department_id=gen_id, course_name=course)
    gid_a = int(next(g for g in groups if g.get("group_code") == "A")["id"])
    for sid in (sid_gen, sid_cv):
        cur.execute(
            "INSERT INTO registrations (student_id, course_name, semester, teaching_group_id) VALUES (?, ?, ?, ?)",
            (sid, course, sem, gid_a),
        )
    db_conn.commit()

    roster = tg.list_course_group_roster(
        db_conn, course_name=course, semester=sem, department_id=gen_id
    )
    assert roster.get("general_department_id") == gen_id
    g_a = next(g for g in roster["groups"] if g["teaching_group_id"] == gid_a)
    by_sid = {m["student_id"]: m for m in g_a["members"]}
    assert by_sid[sid_gen]["is_general_department"] is True
    assert by_sid[sid_cv]["is_general_department"] is False
    assert by_sid[sid_cv]["department_id"] == civil_id
    assert "مدني" in (by_sid[sid_cv].get("department_name") or "")


def test_roster_api(auth_client, db_conn):

    seed = _seed(db_conn)
    r = auth_client.get(
        f"/schedule/teaching_groups/roster?course_name={seed['course']}&semester={seed['semester']}&department_id={seed['dept_id']}"
    )
    assert r.status_code == 200
    j = r.get_json()
    assert j["status"] == "ok"
    assert j["totals"]["registered"] == 3

    r2 = auth_client.post(
        "/schedule/teaching_groups/roster/assign",
        json={
            "teaching_group_id": seed["group_a"],
            "student_ids": seed["students"][:1],
            "action": "assign",
        },
        headers={"Content-Type": "application/json"},
    )
    assert r2.status_code == 200
    j2 = r2.get_json()
    assert j2["status"] == "ok"
    assert j2["stats"]["updated"] >= 1
    g_a = next(
        g for g in (j2.get("roster") or {}).get("groups") or []
        if g["teaching_group_id"] == seed["group_a"]
    )
    assert g_a["member_count"] >= 1
