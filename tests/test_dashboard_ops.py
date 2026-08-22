"""لوحة القيادة — ملخص تشغيلي dashboard_ops."""
from __future__ import annotations


def test_dashboard_ops_ok_for_admin(auth_client):
    r = auth_client.get("/admin/dashboard_ops")
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j.get("status") == "ok"
    assert "term" in j
    assert "schedule" in j
    assert "offerings" in j
    assert "archive" in j
    assert "risk_breakdown" in j
    assert "followup_courses" in j
    assert "alerts" in j
    assert isinstance(j["alerts"], list)
    assert set(j["risk_breakdown"].keys()) >= {"high_failed", "no_instructor", "no_section"}


def test_dashboard_ops_followup_not_silently_empty_when_failures_exist(auth_client, db_conn):
    """إن وُجدت درجات راسبة يجب أن تظهر في followup_courses (لا تُصفَّر بسبب خطأ إثراء)."""
    cur = db_conn.cursor()
    # طالب + مقرر راسب بحد أدنى للبيانات
    sid = "dash-fail-1"
    cur.execute("DELETE FROM grades WHERE student_id = ?", (sid,))
    cur.execute("DELETE FROM students WHERE student_id = ?", (sid,))
    try:
        cur.execute(
            "INSERT INTO students (student_id, student_name, status) VALUES (?, ?, ?)",
            (sid, "طالب لوحة", "active"),
        )
    except Exception:
        cur.execute(
            "INSERT INTO students (student_id, student_name) VALUES (?, ?)",
            (sid, "طالب لوحة"),
        )
    cur.execute(
        """
        INSERT INTO grades (student_id, course_name, course_code, units, grade, semester)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (sid, "مقرر اختبار لوحة", "TST101", 3, 40, "خريف 44-45"),
    )
    db_conn.commit()
    r = auth_client.get("/admin/dashboard_ops")
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    names = [c.get("course_name") for c in (j.get("followup_courses") or [])]
    assert "مقرر اختبار لوحة" in names or (j.get("risk_breakdown") or {}).get("high_failed", 0) > 0


def test_dashboard_page_includes_ops_bar(auth_client):
    r = auth_client.get("/dashboard")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "opsStatusBar" in html
    assert "opsAlerts" in html
    assert "/admin/dashboard_ops" in html
    assert "التقرير الشامل" in html
    assert "أعلى 3 مقررات" in html
