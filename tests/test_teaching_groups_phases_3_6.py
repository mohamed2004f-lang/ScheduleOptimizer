"""اختبارات المراحل 3–6 — تقييم، استبيانات، أستاذ، ترحيل."""
import uuid

from backend.services import teaching_groups as tg
from backend.services.course_evaluations import (
    _already_evaluated,
    _student_evaluable_sections,
    list_pending_course_evaluations,
)
from backend.services.evaluation_survey import insert_evaluation_with_answers, list_survey_questions
from backend.services.survey_analytics import (
    build_course_eval_missing_sections_audit,
    build_course_eval_section_report,
    section_enrolled_count,
)


def _set_current_term(cur, semester="خريف 44-45"):
    parts = semester.split()
    tname = parts[0] if parts else "خريف"
    tyear = parts[1] if len(parts) > 1 else "44-45"
    cur.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', ?)", (tname,))
    cur.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', ?)", (tyear,))


def _seed_single_with_students(db_conn, *, course="ميكانيكا II", semester="خريف 44-45", n_students=5):
    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"P3{uid}".upper()[:12], f"قسم {uid}", "P3"),
    )
    dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (f"P3{uid}".upper()[:12],)).fetchone()[0]
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (course, f"M{uid}"[:8], dept_id),
    )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"د. {uid}", dept_id),
    )
    inst_id = int(cur.lastrowid)
    section_ids = []
    for day, time in [("الأحد", "08:00-10:00"), ("الأربعاء", "10:00-12:00")]:
        cur.execute(
            """
            INSERT INTO schedule (course_name, day, time, room, instructor_id, semester, department_id)
            VALUES (?, ?, ?, '101', ?, ?, ?)
            """,
            (course, day, time, inst_id, semester, dept_id),
        )
        section_ids.append(int(cur.lastrowid))
    cur.execute("UPDATE schedule SET id = rowid WHERE id IS NULL")
    student_ids = []
    for i in range(n_students):
        sid = f"ST{uid}{i}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
            (sid, f"طالب {i}", dept_id),
        )
        student_ids.append(sid)
    db_conn.commit()
    _set_current_term(cur, semester)
    tg.backfill_teaching_groups_for_semester(db_conn, semester=semester, department_id=dept_id)
    tg.backfill_registrations_teaching_groups(db_conn, semester=semester, department_id=dept_id)
    groups = tg.list_teaching_groups(db_conn, semester=semester, department_id=dept_id, course_name=course)
    assert len(groups) == 1
    gid = int(groups[0]["id"])
    for sid in student_ids:
        cur.execute(
            "INSERT OR REPLACE INTO registrations (student_id, course_name, teaching_group_id) VALUES (?, ?, ?)",
            (sid, course, gid),
        )
    db_conn.commit()
    return {
        "course": course,
        "semester": semester,
        "dept_id": dept_id,
        "inst_id": inst_id,
        "group_id": gid,
        "student_ids": student_ids,
        "section_ids": section_ids,
    }


def _seed_split(db_conn, *, course="فيزياء II", semester="خريف 44-45"):
    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"SP{uid}".upper()[:12], f"قسم {uid}", "SP"),
    )
    dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (f"SP{uid}".upper()[:12],)).fetchone()[0]
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (course, f"P{uid}"[:8], dept_id),
    )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"د. {uid}", dept_id),
    )
    inst_id = int(cur.lastrowid)
    section_ids = []
    for day, time in [("الأحد", "08:00"), ("الثلاثاء", "10:00")]:
        cur.execute(
            """
            INSERT INTO schedule (course_name, day, time, room, instructor_id, semester, department_id)
            VALUES (?, ?, ?, '101', ?, ?, ?)
            """,
            (course, day, time, inst_id, semester, dept_id),
        )
        section_ids.append(int(cur.lastrowid))
    cur.execute("UPDATE schedule SET id = rowid WHERE id IS NULL")
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
    cur.execute(
        "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
        (f"SA{uid}", "طالب A", dept_id),
    )
    cur.execute(
        "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
        (f"SB{uid}", "طالب B", dept_id),
    )
    cur.execute(
        "INSERT INTO registrations (student_id, course_name, teaching_group_id) VALUES (?, ?, ?)",
        (f"SA{uid}", course, int(g_a["id"])),
    )
    cur.execute(
        "INSERT INTO registrations (student_id, course_name, teaching_group_id) VALUES (?, ?, ?)",
        (f"SB{uid}", course, int(g_b["id"])),
    )
    db_conn.commit()
    return {
        "course": course,
        "semester": semester,
        "dept_id": dept_id,
        "inst_id": inst_id,
        "group_a": int(g_a["id"]),
        "group_b": int(g_b["id"]),
        "student_a": f"SA{uid}",
        "student_b": f"SB{uid}",
    }


class TestPhase3Evaluations:
    def test_single_two_lectures_one_evaluable_group(self, db_conn):
        seed = _seed_single_with_students(db_conn, n_students=5)
        groups = tg.list_student_evaluable_groups(
            db_conn, seed["student_ids"][0], seed["semester"]
        )
        assert len(groups) == 1
        assert int(groups[0]["teaching_group_id"]) == seed["group_id"]
        assert len(groups[0].get("schedule_slots") or []) == 2

        all_secs = _student_evaluable_sections(db_conn, seed["student_ids"][0], seed["semester"])
        assert len(all_secs) == 1

    def test_enrolled_count_per_teaching_group(self, db_conn):
        seed = _seed_single_with_students(db_conn, n_students=5)
        enrolled = section_enrolled_count(
            db_conn,
            seed["course"],
            seed["semester"],
            teaching_group_id=seed["group_id"],
        )
        assert enrolled == 5

    def test_evaluation_once_per_teaching_group(self, db_conn):
        seed = _seed_single_with_students(db_conn, n_students=3)
        sid = seed["student_ids"][0]
        sem = seed["semester"]
        questions = list_survey_questions(db_conn, active_only=True)
        answers = {int(q["id"]): 5 for q in questions}
        sec_id = tg.primary_section_id_for_group(db_conn, seed["group_id"])
        insert_evaluation_with_answers(
            db_conn,
            student_id=sid,
            section_id=sec_id,
            teaching_group_id=seed["group_id"],
            course_name=seed["course"],
            instructor_id=seed["inst_id"],
            semester=sem,
            comments="",
            answers=answers,
            active_questions=questions,
        )
        db_conn.commit()
        cur = db_conn.cursor()
        assert _already_evaluated(
            db_conn, cur, sid, sem, teaching_group_id=seed["group_id"]
        )
        pending = list_pending_course_evaluations(db_conn, sid, semester=sem)
        assert len(pending) == 0

    def test_section_report_uses_group_enrollment(self, db_conn):
        seed = _seed_single_with_students(db_conn, n_students=5)
        questions = list_survey_questions(db_conn, active_only=True)
        answers = {int(q["id"]): 4 for q in questions}
        sec_id = tg.primary_section_id_for_group(db_conn, seed["group_id"])
        for i, stu in enumerate(seed["student_ids"][:3]):
            insert_evaluation_with_answers(
                db_conn,
                student_id=stu,
                section_id=sec_id,
                teaching_group_id=seed["group_id"],
                course_name=seed["course"],
                instructor_id=seed["inst_id"],
                semester=seed["semester"],
                comments="",
                answers=answers,
                active_questions=questions,
            )
        db_conn.commit()
        rep = build_course_eval_section_report(
            db_conn, sec_id, semester=seed["semester"], teaching_group_id=seed["group_id"]
        )
        assert rep is not None
        assert rep["enrolled_count"] == 5
        assert rep.get("teaching_group_id") == seed["group_id"]

    def test_missing_audit_uses_teaching_groups(self, db_conn):
        seed = _seed_single_with_students(db_conn, n_students=2)
        audit = build_course_eval_missing_sections_audit(
            db_conn, semester=seed["semester"], department_id=seed["dept_id"]
        )
        assert audit.get("audit_mode") == "teaching_groups"
        assert audit["missing_sections"] >= 1

    def test_backfill_evaluations_teaching_group(self, db_conn):
        seed = _seed_single_with_students(db_conn, n_students=1)
        questions = list_survey_questions(db_conn, active_only=True)
        answers = {int(q["id"]): 4 for q in questions}
        sec_id = tg.primary_section_id_for_group(db_conn, seed["group_id"])
        insert_evaluation_with_answers(
            db_conn,
            student_id=seed["student_ids"][0],
            section_id=sec_id,
            course_name=seed["course"],
            instructor_id=seed["inst_id"],
            semester=seed["semester"],
            comments="",
            answers=answers,
            active_questions=questions,
        )
        db_conn.commit()
        stats = tg.backfill_course_evaluations_teaching_groups(db_conn, semester=seed["semester"])
        assert stats["linked"] >= 1
        row = db_conn.execute(
            "SELECT teaching_group_id FROM course_evaluations WHERE student_id = ?",
            (seed["student_ids"][0],),
        ).fetchone()
        assert int(row[0]) == seed["group_id"]


class TestPhase4Instructor:
    def test_instructor_assigned_teaching_groups(self, db_conn):
        seed = _seed_single_with_students(db_conn)
        rows = tg.list_instructor_assigned_groups(db_conn, seed["inst_id"], seed["semester"])
        assert len(rows) == 1
        assert int(rows[0]["teaching_group_id"]) == seed["group_id"]
        assert rows[0]["student_count"] == 5
        assert len(rows[0].get("schedule_slots") or []) == 2


class TestPhase6Scenarios:
    def test_split_two_groups_separate_evaluable(self, db_conn):
        seed = _seed_split(db_conn)
        ga = tg.list_student_evaluable_groups(db_conn, seed["student_a"], seed["semester"])
        gb = tg.list_student_evaluable_groups(db_conn, seed["student_b"], seed["semester"])
        assert len(ga) == 1
        assert len(gb) == 1
        assert int(ga[0]["teaching_group_id"]) == seed["group_a"]
        assert int(gb[0]["teaching_group_id"]) == seed["group_b"]

    def test_split_instructor_sees_two_groups(self, db_conn):
        seed = _seed_split(db_conn)
        rows = tg.list_instructor_assigned_groups(db_conn, seed["inst_id"], seed["semester"])
        assert len(rows) == 2
        ids = {int(r["teaching_group_id"]) for r in rows}
        assert seed["group_a"] in ids
        assert seed["group_b"] in ids

    def test_groups_without_eval_audit_split(self, db_conn):
        seed = _seed_split(db_conn)
        audit = tg.teaching_groups_without_evaluation_audit(
            db_conn, semester=seed["semester"], department_id=seed["dept_id"]
        )
        assert audit["missing_groups"] == 2
        assert audit["total_teaching_groups"] == 2
