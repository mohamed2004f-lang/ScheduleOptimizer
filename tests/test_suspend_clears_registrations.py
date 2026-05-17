"""عند إيقاف القيد تُفرَّغ التسجيلات الفعلية (سياسة: كأنه غير مسجّل بالمقررات)."""


def test_suspend_enrollment_clears_registrations(db_conn):
    from backend.core.services import StudentService

    cur = db_conn.cursor()
    cur.execute("DELETE FROM registrations WHERE student_id = 'S001'")
    cur.execute(
        "INSERT INTO registrations (student_id, course_name) VALUES ('S001', 'رياضيات 1')"
    )
    db_conn.commit()

    out = StudentService.update_enrollment_status(
        "S001",
        "suspended",
        reason="اختبار",
        status_changed_term="خريف",
        status_changed_year="44-45",
    )
    assert out.get("status") == "ok"
    assert out.get("enrollment_status") == "suspended"
    assert int(out.get("suspension_cleared_registration_rows") or 0) >= 1

    n = cur.execute(
        "SELECT COUNT(*) FROM registrations WHERE student_id = ?",
        ("S001",),
    ).fetchone()[0]
    assert int(n) == 0
    es = cur.execute(
        "SELECT enrollment_status FROM students WHERE student_id = ?",
        ("S001",),
    ).fetchone()[0]
    assert (es or "").strip().lower() == "suspended"

    # إعادة الحالة لعدم كسر اختبارات أخرى تفترض S001 نشطاً
    cur.execute(
        "UPDATE students SET enrollment_status = 'active', status_changed_term = NULL, "
        "status_changed_year = NULL, status_reason = '', status_changed_at = NULL WHERE student_id = 'S001'"
    )
    db_conn.commit()
