"""اختبارات تسجيل الحضور ونسبة الغياب (مقام ثابت 16)."""

from backend.services.attendance_registration import (
    ATTENDANCE_TERM_WEEKS_KEY,
    DEFAULT_TERM_WEEKS,
    compute_absence_stats,
    get_attendance_term_weeks,
    set_attendance_term_weeks,
)


_ATTENDANCE_DDL = """
CREATE TABLE IF NOT EXISTS attendance_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    course_name TEXT NOT NULL,
    week_number INTEGER NOT NULL,
    status TEXT CHECK (status IN ('present', 'absent', 'late', 'excused')),
    note TEXT,
    recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (student_id, course_name, week_number)
);
"""


def _ensure_attendance_table(conn):
    conn.executescript(_ATTENDANCE_DDL)
    conn.commit()


def _seed_attendance_course(conn):
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO students (student_id, student_name, enrollment_status) VALUES ('S001', 'طالب أول', 'active')"
    )
    cur.execute(
        "INSERT OR IGNORE INTO students (student_id, student_name, enrollment_status) VALUES ('S002', 'طالب ثاني', 'active')"
    )
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES ('رياضيات 1', 'MATH101', 3)"
    )
    cur.execute(
        "INSERT OR IGNORE INTO registrations (student_id, course_name) VALUES ('S001', 'رياضيات 1')"
    )
    cur.execute(
        "INSERT OR IGNORE INTO registrations (student_id, course_name) VALUES ('S002', 'رياضيات 1')"
    )
    cur.execute(
        """INSERT OR IGNORE INTO schedule (course_name, day, time, room, instructor, semester)
           VALUES ('رياضيات 1', 'الأحد', '08:00', 'ق1', 'أستاذ تجريبي', 'خريف 44-45')"""
    )
    conn.commit()


def test_compute_absence_stats_fixed_denominator_16():
    """أسابيع غير المسجلة لا تُحسب غياباً؛ المقام ثابت 16."""
    stats = compute_absence_stats(
        {1: "present", 2: "absent", 3: "absent"},
        term_weeks=16,
    )
    assert stats["absent_weeks"] == 2
    assert stats["recorded_weeks"] == 3
    assert stats["term_weeks"] == 16
    assert stats["absence_percent"] == 12.5
    assert stats["absence_label"] == "2/16"


def test_compute_absence_stats_ignores_unrecorded_weeks():
    stats = compute_absence_stats({5: "absent"}, term_weeks=16)
    assert stats["absent_weeks"] == 1
    assert stats["absence_percent"] == 6.2


def test_get_set_attendance_term_weeks(db_conn):
    _ensure_attendance_table(db_conn)
    assert get_attendance_term_weeks(db_conn) == DEFAULT_TERM_WEEKS
    saved = set_attendance_term_weeks(db_conn, 20)
    db_conn.commit()
    assert saved == 20
    assert get_attendance_term_weeks(db_conn) == 20
    row = db_conn.execute(
        "SELECT value FROM system_settings WHERE key = ?",
        (ATTENDANCE_TERM_WEEKS_KEY,),
    ).fetchone()
    assert row[0] == "20"


def test_attendance_register_routes(app, db_conn):
    _ensure_attendance_table(db_conn)
    _seed_attendance_course(db_conn)
    set_attendance_term_weeks(db_conn, 16)
    db_conn.commit()

    with app.test_client() as c:
        assert c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"}).status_code == 200

        cfg = c.get("/students/attendance/register/config")
        assert cfg.status_code == 200
        assert cfg.get_json()["term_weeks"] == 16

        roster = c.get("/students/attendance/register/roster?course=رياضيات%201&week=1")
        assert roster.status_code == 200
        data = roster.get_json()
        assert data["status"] == "ok"
        assert data["course_name"] == "رياضيات 1"
        assert len(data["students"]) == 2
        for st in data["students"]:
            assert st["absence_percent"] == 0.0

        save = c.post(
            "/students/attendance/register/save",
            json={
                "course_name": "رياضيات 1",
                "week_number": 1,
                "marks": [
                    {"student_id": "S001", "status": "present"},
                    {"student_id": "S002", "status": "absent"},
                ],
            },
        )
        assert save.status_code == 200
        saved = save.get_json()
        assert saved["saved"] == 2

        save2 = c.post(
            "/students/attendance/register/save",
            json={
                "course_name": "رياضيات 1",
                "week_number": 2,
                "marks": [{"student_id": "S002", "status": "absent"}],
            },
        )
        assert save2.status_code == 200

        roster2 = c.get("/students/attendance/register/roster?course=رياضيات%201&week=2")
        s002 = next(s for s in roster2.get_json()["students"] if s["student_id"] == "S002")
        assert s002["absent_weeks"] == 2
        assert s002["absence_percent"] == 12.5


def test_admin_attendance_term_weeks_setting(app, db_conn):
    with app.test_client() as c:
        assert c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"}).status_code == 200
        resp = c.post("/admin/settings/attendance_term_weeks", json={"term_weeks": 18})
        assert resp.status_code == 200
        assert resp.get_json()["term_weeks"] == 18
        got = c.get("/admin/settings/attendance_term_weeks")
        assert got.get_json()["term_weeks"] == 18