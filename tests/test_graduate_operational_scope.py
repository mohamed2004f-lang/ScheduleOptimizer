"""خريج = سجل مقفول: يُستبعد من القوائم التشغيلية ويُجمَّد تسجيله الفصلي."""
from backend.core.auth_guards import student_alumni_path_allowed, student_portal_path_allowed
from backend.core.enrollment_status_policy import apply_alumni_student_caps, is_alumni_enrollment
from backend.core.services import StudentService


def _reset_s001(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "UPDATE students SET enrollment_status = 'active', status_changed_term = NULL, "
        "status_changed_year = NULL, status_reason = '', status_changed_at = NULL WHERE student_id = 'S001'"
    )
    db_conn.commit()


def test_alumni_paths_keep_transcript_block_registration():
    assert student_portal_path_allowed("/my_registrations") is True
    assert student_alumni_path_allowed("/my_transcript") is True
    assert student_alumni_path_allowed("/my_portal") is True
    assert student_alumni_path_allowed("/academic_quality/student/progress") is True
    assert student_alumni_path_allowed("/my_registrations") is False
    assert student_alumni_path_allowed("/enrollment/plans") is False
    assert student_alumni_path_allowed("/my_requests") is False


def test_apply_alumni_caps_hides_operational_nav():
    caps = apply_alumni_student_caps({"v": 1, "nav_student_registrations": True})
    assert caps["alumni_mode"] is True
    assert caps["nav_student_registrations"] is False
    assert caps["nav_student_portal"] is True
    assert caps["nav_transcript_nav"] is True
    assert is_alumni_enrollment("graduated") is True


def test_default_students_list_excludes_graduates(auth_client, db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO students (student_id, student_name, enrollment_status) VALUES (?, ?, 'graduated')",
        ("GR-SCOPE-1", "خريج اختبار"),
    )
    db_conn.commit()
    try:
        operational = auth_client.get("/students/list")
        assert operational.status_code == 200
        ids = {s.get("student_id") for s in (operational.get_json() or [])}
        assert "GR-SCOPE-1" not in ids

        archive = auth_client.get("/students/list?include_inactive=1")
        archive_ids = {s.get("student_id") for s in (archive.get_json() or [])}
        assert "GR-SCOPE-1" in archive_ids

        only_grad = auth_client.get("/students/list?enrollment_status=graduated")
        grad_ids = {s.get("student_id") for s in (only_grad.get_json() or [])}
        assert "GR-SCOPE-1" in grad_ids
    finally:
        cur.execute("DELETE FROM students WHERE student_id = 'GR-SCOPE-1'")
        db_conn.commit()


def test_graduate_clears_registrations_and_archives_plans(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS enrollment_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            semester TEXT NOT NULL,
            status TEXT NOT NULL,
            rejection_reason TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    cur.execute("DELETE FROM registrations WHERE student_id = 'S001'")
    cur.execute("DELETE FROM enrollment_plans WHERE student_id = 'S001'")
    cur.execute(
        "INSERT INTO registrations (student_id, course_name) VALUES ('S001', 'رياضيات 1')"
    )
    cur.execute(
        """
        INSERT INTO enrollment_plans (student_id, semester, status, created_at, updated_at)
        VALUES ('S001', 'خريف 36-37', 'Pending', '2026-01-01', '2026-01-01')
        """
    )
    db_conn.commit()
    try:
        out = StudentService.update_enrollment_status("S001", "graduated", reason="اختبار تخرج")
        assert out.get("status") == "ok"
        assert out.get("enrollment_status") == "graduated"
        assert int(out.get("cleared_registration_rows") or 0) >= 1
        n = cur.execute(
            "SELECT COUNT(*) FROM registrations WHERE student_id = ?",
            ("S001",),
        ).fetchone()[0]
        assert int(n) == 0
        st = cur.execute(
            "SELECT status FROM enrollment_plans WHERE student_id = 'S001' LIMIT 1"
        ).fetchone()
        assert st and st[0] == "Archived"
    finally:
        cur.execute("DELETE FROM enrollment_plans WHERE student_id = 'S001'")
        _reset_s001(db_conn)
