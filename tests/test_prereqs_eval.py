"""اختبارات تقييم المتطلبات الموحّد."""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.prereg_helpers import evaluate_prereqs_for_student


def _mk_db():
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE grades (student_id TEXT, course_name TEXT, grade REAL)")
    cur.execute(
        "CREATE TABLE prereqs (course_name TEXT NOT NULL, required_course_name TEXT NOT NULL)"
    )
    cur.execute("CREATE TABLE registrations (student_id TEXT, course_name TEXT)")
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
    cur.execute("INSERT INTO grades VALUES ('S1', 'A', 40)")
    r = evaluate_prereqs_for_student(
        cur, "S1", ["B"], proposed_courses=["B"], old_registered=set()
    )
    assert r["blocked"] == {}
    assert len(r["warnings"]) >= 1


def test_passed_clean():
    conn, cur = _mk_db()
    cur.execute("INSERT INTO prereqs VALUES ('B', 'A')")
    cur.execute("INSERT INTO grades VALUES ('S1', 'A', 80)")
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


if __name__ == "__main__":
    test_missing_prereq_legacy_blocked()
    test_coregister_no_block()
    test_failed_warning_when_not_retaking()
    test_passed_clean()
    test_in_progress_registered()
    print("test_prereqs_eval: ok")
