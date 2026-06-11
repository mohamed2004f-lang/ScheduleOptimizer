"""اختبارات المرحلة 2 — ربط التسجيلات بمجموعات التدريس."""
import uuid

import pytest

from backend.services import teaching_groups as tg


def _set_current_term(cur, semester="خريف 44-45"):
    parts = semester.split()
    tname = parts[0] if parts else "خريف"
    tyear = parts[1] if len(parts) > 1 else "44-45"
    cur.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', ?)", (tname,))
    cur.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', ?)", (tyear,))


def _seed_split_offering(db_conn, *, course="فيزياء II", semester="خريف 44-45"):
    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"R2{uid}".upper()[:12], f"قسم {uid}", "R2"),
    )
    dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (f"R2{uid}".upper()[:12],)).fetchone()[0]
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (course, f"P{uid}"[:8], dept_id),
    )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"د. {uid}", dept_id),
    )
    inst_id = int(cur.lastrowid)
    cur.execute(
        "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
        (f"ST{uid}", "طالب تجربة", dept_id),
    )
    sid = f"ST{uid}"
    section_ids = []
    for day, time in [("الأحد", "08:00-10:00"), ("الثلاثاء", "10:00-12:00")]:
        cur.execute(
            """
            INSERT INTO schedule (course_name, day, time, room, instructor_id, semester, department_id)
            VALUES (?, ?, ?, '101', ?, ?, ?)
            """,
            (course, day, time, inst_id, semester, dept_id),
        )
        section_ids.append(int(cur.lastrowid))
    db_conn.commit()
    _set_current_term(cur, semester)
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
    groups = tg.list_teaching_groups(db_conn, semester=semester, department_id=dept_id, course_name=course)
    g_a = next(g for g in groups if g.get("group_code") == "A")
    g_b = next(g for g in groups if g.get("group_code") == "B")
    return {
        "student_id": sid,
        "dept_id": dept_id,
        "course": course,
        "semester": semester,
        "group_a": int(g_a["id"]),
        "group_b": int(g_b["id"]),
    }


class TestRegistrationTeachingGroupsService:
    def test_resolve_and_backfill_single(self, db_conn):
        uid = uuid.uuid4().hex[:6]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"BF{uid}".upper()[:12], "قسم", "BF"),
        )
        dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (f"BF{uid}".upper()[:12],)).fetchone()[0]
        course = "كيمياء II"
        semester = "خريف 44-45"
        cur.execute(
            "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 2, ?)",
            (course, "CH2", dept_id),
        )
        cur.execute(
            "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
            ("أستاذ", dept_id),
        )
        inst_id = int(cur.lastrowid)
        sid = f"S{uid}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
            (sid, "طالب", dept_id),
        )
        cur.execute(
            "INSERT INTO schedule (course_name, day, time, room, instructor_id, semester, department_id) VALUES (?, 'الأحد', '08:00', '1', ?, ?, ?)",
            (course, inst_id, semester, dept_id),
        )
        cur.execute("INSERT INTO registrations (student_id, course_name) VALUES (?, ?)", (sid, course))
        db_conn.commit()
        _set_current_term(cur, semester)
        tg.backfill_teaching_groups_for_semester(db_conn, semester=semester, department_id=dept_id)
        stats = tg.backfill_registrations_teaching_groups(db_conn, semester=semester, department_id=dept_id)
        assert stats["linked"] >= 1
        gid = tg.resolve_teaching_group_for_registration(
            db_conn, student_id=sid, course_name=course, semester=semester
        )
        assert gid is not None
        assert tg.count_registrations_for_teaching_group(db_conn, int(gid)) == 1

    def test_split_requires_choice(self, db_conn):
        seed = _seed_split_offering(db_conn)
        with pytest.raises(ValueError):
            tg.resolve_teaching_group_for_registration(
                db_conn,
                student_id=seed["student_id"],
                course_name=seed["course"],
                semester=seed["semester"],
            )
        gid = tg.resolve_teaching_group_for_registration(
            db_conn,
            student_id=seed["student_id"],
            course_name=seed["course"],
            semester=seed["semester"],
            teaching_group_id=seed["group_a"],
        )
        assert gid == seed["group_a"]

    def test_count_per_teaching_group(self, db_conn):
        seed = _seed_split_offering(db_conn)
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO registrations (student_id, course_name, teaching_group_id) VALUES (?, ?, ?)",
            (seed["student_id"], seed["course"], seed["group_a"]),
        )
        db_conn.commit()
        assert tg.count_registrations_for_teaching_group(db_conn, seed["group_a"]) == 1
        assert tg.count_registrations_for_teaching_group(db_conn, seed["group_b"]) == 0


class TestRegistrationTeachingGroupsApi:
    def test_save_with_teaching_group(self, auth_client, db_conn):
        seed = _seed_split_offering(db_conn)
        r = auth_client.post(
            "/students/save_registrations",
            json={
                "student_id": seed["student_id"],
                "registration_items": [
                    {"course_name": seed["course"], "teaching_group_id": seed["group_a"]}
                ],
                "override_reason": "اختبار",
            },
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200
        row = db_conn.execute(
            "SELECT teaching_group_id FROM registrations WHERE student_id = ?",
            (seed["student_id"],),
        ).fetchone()
        assert int(row[0]) == seed["group_a"]

    def test_save_split_without_group_fails(self, auth_client, db_conn):
        seed = _seed_split_offering(db_conn)
        r = auth_client.post(
            "/students/save_registrations",
            json={
                "student_id": seed["student_id"],
                "registration_items": [{"course_name": seed["course"], "teaching_group_id": None}],
                "override_reason": "اختبار",
            },
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400
        assert r.get_json().get("code") == "TEACHING_GROUP_REQUIRED"

    def test_registration_options_api(self, auth_client, db_conn):
        seed = _seed_split_offering(db_conn)
        r = auth_client.get(
            f"/schedule/teaching_groups/registration_options?student_id={seed['student_id']}&course_name={seed['course']}"
        )
        assert r.status_code == 200
        assert len(r.get_json().get("options") or []) == 2

    def test_registrations_backfill_api(self, auth_client, db_conn):
        uid = uuid.uuid4().hex[:6]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"API{uid}".upper()[:12], "قسم", "API"),
        )
        dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (f"API{uid}".upper()[:12],)).fetchone()[0]
        course = "أحياء"
        semester = "خريف 44-45"
        cur.execute(
            "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 2, ?)",
            (course, "BIO", dept_id),
        )
        cur.execute(
            "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
            ("أستاذ", dept_id),
        )
        inst_id = int(cur.lastrowid)
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
            (f"SA{uid}", "طالب", dept_id),
        )
        cur.execute(
            "INSERT INTO schedule (course_name, day, time, room, instructor_id, semester, department_id) VALUES (?, 'الأحد', '08:00', '1', ?, ?, ?)",
            (course, inst_id, semester, dept_id),
        )
        cur.execute("INSERT INTO registrations (student_id, course_name) VALUES (?, ?)", (f"SA{uid}", course))
        db_conn.commit()
        _set_current_term(cur, semester)
        tg.backfill_teaching_groups_for_semester(db_conn, semester=semester, department_id=dept_id)
        r = auth_client.post("/schedule/teaching_groups/registrations/backfill", json={"semester": semester})
        assert r.status_code == 200
        assert r.get_json()["stats"]["linked"] >= 1
