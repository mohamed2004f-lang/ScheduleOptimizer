"""تقرير المقررات الاختيارية — يجب إرجاع student_name (PostgreSQL alias)."""
import pytest


def _seed_electives_gap_student(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO students (student_id, student_name) VALUES (?, ?)",
        ("21026", "طالب تجريبي للتقرير"),
    )
    for i in range(35):
        cname = f"مقرر_إجباري_{i}"
        cur.execute(
            "INSERT OR IGNORE INTO courses (course_name, course_code, units, category) VALUES (?, ?, 3, 'required')",
            (cname, f"REQ{i:03d}"),
        )
        cur.execute(
            """
            INSERT OR REPLACE INTO grades (student_id, semester, course_name, course_code, units, grade)
            VALUES (?, 'ف1', ?, ?, 3, 60)
            """,
            ("21026", cname, f"REQ{i:03d}"),
        )
    for j in range(2):
        cname = f"اختياري_{j}"
        cur.execute(
            "INSERT OR IGNORE INTO courses (course_name, course_code, units, category) VALUES (?, ?, 3, 'elective_major')",
            (cname, f"EL{j}"),
        )
        cur.execute(
            """
            INSERT OR REPLACE INTO grades (student_id, semester, course_name, course_code, units, grade)
            VALUES (?, 'ف1', ?, ?, 3, 70)
            """,
            ("21026", cname, f"EL{j}"),
        )
    db_conn.commit()


class TestElectivesReport:
    def test_report_includes_student_name(self, auth_client, db_conn):
        _seed_electives_gap_student(db_conn)
        resp = auth_client.get("/students/electives_report")
        assert resp.status_code == 200
        items = resp.get_json().get("items") or []
        match = [it for it in items if it.get("student_id") == "21026"]
        assert match, "expected student 21026 in electives report"
        assert match[0].get("student_name") == "طالب تجريبي للتقرير"
