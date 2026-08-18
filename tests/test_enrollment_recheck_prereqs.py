"""اختبارات إعادة فحص متطلبات خطة التسجيل المعلّقة."""
import json


def _ensure_enrollment_tables(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS enrollment_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            semester TEXT NOT NULL,
            status TEXT NOT NULL,
            rejection_reason TEXT,
            created_at TEXT,
            updated_at TEXT,
            prereq_validation_json TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS enrollment_plan_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            course_name TEXT NOT NULL
        )
        """
    )


def _insert_pending_plan_with_stale_validation(db_conn, *, student_id="S001", semester="خريف 36-37"):
    cur = db_conn.cursor()
    _ensure_enrollment_tables(cur)
    stale = {
        "version": 1,
        "semester": semester,
        "summary": {"courses_with_unmet_count": 1, "has_blocking": True},
        "courses": {
            "مقرر متقدم": {
                "requirements": [
                    {"prereq": "ميكانيكا هندسية I", "status": "missing"},
                ]
            }
        },
    }
    cur.execute(
        """
        INSERT INTO enrollment_plans
            (student_id, semester, status, created_at, updated_at, prereq_validation_json)
        VALUES (?, ?, 'Pending', '2026-01-01', '2026-01-01', ?)
        """,
        (student_id, semester, json.dumps(stale, ensure_ascii=False)),
    )
    plan_id = int(cur.lastrowid)
    cur.execute(
        "INSERT INTO enrollment_plan_items (plan_id, course_name) VALUES (?, 'مقرر متقدم')",
        (plan_id,),
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO courses (course_name, course_code, units)
        VALUES ('ميكانيكا هندسية I', 'ME101', 3)
        """
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO courses (course_name, course_code, units)
        VALUES ('ميكانيك هندسي I', 'ME101', 3)
        """
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO prereqs (course_name, required_course_name)
        VALUES ('مقرر متقدم', 'ميكانيكا هندسية I')
        """
    )
    db_conn.commit()
    return plan_id


def test_recheck_prereqs_updates_snapshot_when_grade_matches_by_code(auth_client, db_conn):
    plan_id = _insert_pending_plan_with_stale_validation(db_conn)
    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO grades (student_id, semester, course_name, course_code, units, grade)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("S001", "خريف 36-37", "ميكانيك هندسي I", "ME101", 3, 75),
    )
    db_conn.commit()

    r = auth_client.post(f"/enrollment/plans/{plan_id}/recheck_prereqs")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["unmet_count"] == 0
    pv = body.get("prereq_validation") or {}
    req = pv["courses"]["مقرر متقدم"]["requirements"][0]
    assert req["status"] == "passed"

    row = cur.execute(
        "SELECT prereq_validation_json FROM enrollment_plans WHERE id = ?",
        (plan_id,),
    ).fetchone()
    stored = json.loads(row[0])
    assert stored["summary"]["courses_with_unmet_count"] == 0

    status_row = cur.execute(
        "SELECT status FROM enrollment_plans WHERE id = ?",
        (plan_id,),
    ).fetchone()
    assert status_row[0] == "Pending"


def test_recheck_prereqs_rejects_non_pending(auth_client, db_conn):
    plan_id = _insert_pending_plan_with_stale_validation(db_conn)
    cur = db_conn.cursor()
    cur.execute(
        "UPDATE enrollment_plans SET status = 'Approved' WHERE id = ?",
        (plan_id,),
    )
    db_conn.commit()

    r = auth_client.post(f"/enrollment/plans/{plan_id}/recheck_prereqs")
    assert r.status_code == 400
    assert "معلّقة" in (r.get_json().get("message") or "")
