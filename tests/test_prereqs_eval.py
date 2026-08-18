"""اختبارات تقييم المتطلبات الموحّد."""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.prereg_helpers import (
    evaluate_prereqs_for_student,
    format_unmet_prereqs_student_ar,
    prereq_ack_required,
)


def _mk_db():
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE grades (student_id TEXT, course_name TEXT, course_code TEXT, grade REAL)")
    cur.execute(
        "CREATE TABLE prereqs (course_name TEXT NOT NULL, required_course_name TEXT NOT NULL)"
    )
    cur.execute("CREATE TABLE registrations (student_id TEXT, course_name TEXT)")
    cur.execute(
        "CREATE TABLE courses (course_name TEXT PRIMARY KEY, course_code TEXT, units INTEGER DEFAULT 3)"
    )
    cur.execute(
        "CREATE TABLE students (student_id TEXT PRIMARY KEY, department_id INTEGER)"
    )
    cur.execute(
        """
        CREATE TABLE course_equivalence_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_key TEXT UNIQUE NOT NULL,
            title TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE course_equivalence_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            department_id INTEGER NOT NULL,
            course_name TEXT NOT NULL,
            course_code TEXT,
            program_course_id INTEGER,
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            UNIQUE(group_id, department_id, course_name)
        )
        """
    )
    return conn, cur


def test_missing_prereq_legacy_blocked():
    conn, cur = _mk_db()
    cur.execute("INSERT INTO prereqs VALUES ('B', 'A')")
    r = evaluate_prereqs_for_student(
        cur, "S1", ["B"], proposed_courses=["B"], old_registered=set()
    )
    assert r["blocked"].get("B") == ["A"]
    assert r["summary"]["has_blocking"] is True
    b_req = r["courses"]["B"]["requirements"][0]
    assert b_req["status"] == "missing"


def test_coregister_no_block():
    conn, cur = _mk_db()
    cur.execute("INSERT INTO prereqs VALUES ('B', 'A')")
    r = evaluate_prereqs_for_student(
        cur, "S1", ["A", "B"], proposed_courses=["A", "B"], old_registered=set()
    )
    assert r["blocked"] == {}
    assert r["coregister_pairs"]


def test_failed_warning_when_not_retaking():
    conn, cur = _mk_db()
    cur.execute("INSERT INTO prereqs VALUES ('B', 'A')")
    cur.execute("INSERT INTO grades VALUES ('S1', 'A', '', 40)")
    r = evaluate_prereqs_for_student(
        cur, "S1", ["B"], proposed_courses=["B"], old_registered=set()
    )
    assert r["blocked"] == {}
    assert len(r["warnings"]) >= 1


def test_passed_clean():
    conn, cur = _mk_db()
    cur.execute("INSERT INTO prereqs VALUES ('B', 'A')")
    cur.execute("INSERT INTO grades VALUES ('S1', 'A', '', 80)")
    r = evaluate_prereqs_for_student(
        cur, "S1", ["B"], proposed_courses=["B"], old_registered=set()
    )
    assert r["summary"]["courses_with_unmet_count"] == 0


def test_in_progress_registered():
    conn, cur = _mk_db()
    cur.execute("INSERT INTO prereqs VALUES ('B', 'A')")
    cur.execute("INSERT INTO registrations VALUES ('S1', 'A')")
    r = evaluate_prereqs_for_student(
        cur, "S1", ["B"], proposed_courses=["B"], old_registered=set()
    )
    st = r["courses"]["B"]["requirements"][0]["status"]
    assert st == "in_progress"


def test_student_unmet_text_lists_course_and_prereq():
    conn, cur = _mk_db()
    cur.execute("INSERT INTO prereqs VALUES ('B', 'A')")
    r = evaluate_prereqs_for_student(
        cur, "S1", ["B"], proposed_courses=["B"], old_registered=set()
    )
    text = format_unmet_prereqs_student_ar(r)
    assert "B" in text
    assert "A" in text
    assert prereq_ack_required(r) is True


def test_coregister_does_not_require_ack():
    conn, cur = _mk_db()
    cur.execute("INSERT INTO prereqs VALUES ('B', 'A')")
    r = evaluate_prereqs_for_student(
        cur, "S1", ["A", "B"], proposed_courses=["A", "B"], old_registered=set()
    )
    assert prereq_ack_required(r) is False
    assert format_unmet_prereqs_student_ar(r) == ""


def test_passed_via_course_code_when_name_differs():
    """درجة مسجّلة باسم مختلف لكن بنفس رمز دليل المقرر."""
    conn, cur = _mk_db()
    cur.execute("INSERT INTO prereqs VALUES ('B', 'ميكانيكا هندسية I')")
    cur.execute(
        "INSERT INTO courses VALUES ('ميكانيكا هندسية I', 'ME101', 3)"
    )
    cur.execute(
        "INSERT INTO grades VALUES ('S1', 'ميكانيك هندسي I', 'ME101', 75)"
    )
    r = evaluate_prereqs_for_student(
        cur, "S1", ["B"], proposed_courses=["B"], old_registered=set()
    )
    assert r["summary"]["courses_with_unmet_count"] == 0
    req = r["courses"]["B"]["requirements"][0]
    assert req["status"] == "passed"
    assert req.get("matched_course") == "ميكانيك هندسي I"


def test_passed_via_equivalence_group():
    conn, cur = _mk_db()
    cur.execute("INSERT INTO students VALUES ('S1', 10)")
    cur.execute("INSERT INTO prereqs VALUES ('B', 'فيزياء II')")
    cur.execute("INSERT INTO courses VALUES ('فيزياء II', 'PHY201', 3)")
    cur.execute(
        "INSERT INTO course_equivalence_groups (group_key, title, is_active) VALUES ('phys2', 'فيز2', 1)"
    )
    gid = cur.execute("SELECT id FROM course_equivalence_groups LIMIT 1").fetchone()[0]
    cur.execute(
        """
        INSERT INTO course_equivalence_items (group_id, department_id, course_name, course_code, is_active)
        VALUES (?, 10, 'فيزياء II', 'PHY201', 1)
        """,
        (gid,),
    )
    cur.execute(
        """
        INSERT INTO course_equivalence_items (group_id, department_id, course_name, course_code, is_active)
        VALUES (?, 10, 'Physics II', 'PHY201', 1)
        """,
        (gid,),
    )
    cur.execute(
        "INSERT INTO grades VALUES ('S1', 'Physics II', 'PHY201', 68)"
    )
    r = evaluate_prereqs_for_student(
        cur, "S1", ["B"], proposed_courses=["B"], old_registered=set()
    )
    assert r["summary"]["courses_with_unmet_count"] == 0
    assert r["courses"]["B"]["requirements"][0]["status"] == "passed"


def test_passed_via_normalized_name():
    conn, cur = _mk_db()
    cur.execute("INSERT INTO prereqs VALUES ('B', 'ميكانيكا هندسية I')")
    cur.execute(
        "INSERT INTO grades VALUES ('S1', 'ميكانيكا-هندسية I', NULL, 80)"
    )
    r = evaluate_prereqs_for_student(
        cur, "S1", ["B"], proposed_courses=["B"], old_registered=set()
    )
    assert r["courses"]["B"]["requirements"][0]["status"] == "passed"


if __name__ == "__main__":
    test_missing_prereq_legacy_blocked()
    test_coregister_no_block()
    test_failed_warning_when_not_retaking()
    test_passed_clean()
    test_in_progress_registered()
    test_student_unmet_text_lists_course_and_prereq()
    test_coregister_does_not_require_ack()
    test_passed_via_course_code_when_name_differs()
    test_passed_via_equivalence_group()
    test_passed_via_normalized_name()
    print("test_prereqs_eval: ok")
