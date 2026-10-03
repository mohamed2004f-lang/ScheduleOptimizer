"""اختبارات تصحيح كشف الدرجات (مشرف يعتمد فوراً + إشعار رئيس القسم)."""

from __future__ import annotations

import json
import uuid

import pytest


def _set_term(db_conn, name: str, year: str) -> None:
    cur = db_conn.cursor()
    for k, v in (("current_term_name", name), ("current_term_year", year)):
        try:
            cur.execute(
                "INSERT INTO system_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (k, v),
            )
        except Exception:
            cur.execute("DELETE FROM system_settings WHERE key = ?", (k,))
            cur.execute("INSERT INTO system_settings (key, value) VALUES (?, ?)", (k, v))
    db_conn.commit()


@pytest.fixture
def civil_dept_with_advisee(app, db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    code = f"CV{uid}".upper()[:12]
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (code, "مدني", "Civil"),
    )
    dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"مشرف-{uid}", dept_id),
    )
    iid = cur.execute(
        "SELECT id FROM instructors WHERE name = ?", (f"مشرف-{uid}",)
    ).fetchone()[0]
    sid = f"T{uid}"
    cur.execute(
        "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
        (sid, "طالب اختبار", dept_id),
    )
    cur.execute(
        "INSERT INTO student_supervisor (student_id, instructor_id) VALUES (?, ?)",
        (sid, iid),
    )
    cur.execute(
        "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
        (f"مقرر-{uid}", f"C{uid[:4]}".upper(), 3, dept_id),
    )
    # مقرر قسم آخر — يجب ألا يظهر في courses_for_student
    other_code = f"OT{uid}".upper()[:12]
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (other_code, "قسم آخر", "Other"),
    )
    other_dept = cur.execute("SELECT id FROM departments WHERE code = ?", (other_code,)).fetchone()[0]
    cur.execute(
        "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
        (f"أجنبي-{uid}", f"X{uid[:4]}".upper(), 2, other_dept),
    )
    pw = cur.execute(
        "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
    ).fetchone()[0]
    head_user = f"head_tx_{uid}"
    sup_user = f"sup_tx_{uid}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
        (head_user, pw, dept_id),
    )
    cur.execute(
        "INSERT INTO users (username, password_hash, role, instructor_id, is_supervisor, department_id) "
        "VALUES (?, ?, 'instructor', ?, 1, ?)",
        (sup_user, pw, iid, dept_id),
    )
    db_conn.commit()
    _set_term(db_conn, "خريف", "2026/2027")
    return {
        "dept_id": dept_id,
        "sid": sid,
        "iid": iid,
        "course": f"مقرر-{uid}",
        "head_user": head_user,
        "sup_user": sup_user,
        "password": "TestP@ssw0rd!",
    }


class TestTranscriptCorrections:
    def test_supervisor_cannot_save_grades_directly(self, app, civil_dept_with_advisee):
        ctx = civil_dept_with_advisee
        with app.test_client() as c:
            assert c.post(
                "/auth/login",
                json={"username": ctx["sup_user"], "password": ctx["password"]},
            ).status_code == 200
            # تفعيل وضع مشرف إن لزم
            c.post("/auth/active_mode", json={"mode": "supervisor"})
            resp = c.post(
                "/grades/save",
                json={
                    "student_id": ctx["sid"],
                    "semester": "ربيع 2025/2026",
                    "grades": [{"course_name": ctx["course"], "grade": 70}],
                    "reason": "محاولة مباشرة",
                },
            )
            assert resp.status_code in (403, 401), resp.get_data(as_text=True)

    def test_supervisor_finalize_applies_immediately(self, app, db_conn, civil_dept_with_advisee):
        ctx = civil_dept_with_advisee
        with app.test_client() as c:
            assert c.post(
                "/auth/login",
                json={"username": ctx["sup_user"], "password": ctx["password"]},
            ).status_code == 200
            c.post("/auth/active_mode", json={"mode": "supervisor"})
            # فصل حالي يجب أن يُرفض
            bad = c.post(
                "/grades/transcript_corrections",
                json={
                    "student_id": ctx["sid"],
                    "semester": "خريف 2026/2027",
                    "reason": "إدخال نتائج سابقة للاختبار",
                    "grades": [{"course_name": ctx["course"], "grade": 80}],
                },
            )
            assert bad.status_code == 400, bad.get_data(as_text=True)

            ok = c.post(
                "/grades/transcript_corrections",
                json={
                    "student_id": ctx["sid"],
                    "semester": "ربيع 2025/2026",
                    "reason": "إدخال نتائج سابقة للاختبار",
                    "grades": [{"course_name": ctx["course"], "grade": 88}],
                },
            )
            assert ok.status_code == 200, ok.get_data(as_text=True)
            body = ok.get_json() or {}
            req_id = body.get("id")
            assert req_id
            assert int(body.get("applied") or 0) >= 1

        # الدرجة مطبّقة فوراً بدون اعتماد رئيس القسم
        row = db_conn.execute(
            "SELECT grade FROM grades WHERE student_id = ? AND semester = ? AND course_name = ?",
            (ctx["sid"], "ربيع 2025/2026", ctx["course"]),
        ).fetchone()
        assert row is not None
        assert float(row[0]) == 88.0

        status_row = db_conn.execute(
            "SELECT status, reviewed_by FROM transcript_correction_requests WHERE id = ?",
            (req_id,),
        ).fetchone()
        assert status_row is not None
        assert (status_row[0] or "") == "approved"
        assert (status_row[1] or "") == ctx["sup_user"]

        # رئيس القسم يرى الاعتماد في قائمة المعتمد (اطلاع فقط)
        with app.test_client() as c2:
            assert c2.post(
                "/auth/login",
                json={"username": ctx["head_user"], "password": ctx["password"]},
            ).status_code == 200
            lst_pending = c2.get("/grades/transcript_corrections?status=pending")
            assert lst_pending.status_code == 200
            pending_items = (lst_pending.get_json() or {}).get("items") or []
            assert not any(int(x.get("id")) == int(req_id) for x in pending_items)

            lst = c2.get("/grades/transcript_corrections?status=approved")
            assert lst.status_code == 200
            items = (lst.get_json() or {}).get("items") or []
            assert any(int(x.get("id")) == int(req_id) for x in items)

    def test_transcript_includes_supervisor_audit_badge(self, app, db_conn, civil_dept_with_advisee):
        ctx = civil_dept_with_advisee
        with app.test_client() as c:
            c.post("/auth/login", json={"username": ctx["sup_user"], "password": ctx["password"]})
            c.post("/auth/active_mode", json={"mode": "supervisor"})
            ok = c.post(
                "/grades/transcript_corrections",
                json={
                    "student_id": ctx["sid"],
                    "semester": "خريف 2024/2025",
                    "reason": "توثيق شارة الاعتماد في الكشف",
                    "grades": [{"course_name": ctx["course"], "grade": 77}],
                },
            )
            assert ok.status_code == 200, ok.get_data(as_text=True)

        with app.test_client() as c2:
            c2.post("/auth/login", json={"username": ctx["head_user"], "password": ctx["password"]})
            r = c2.get(f"/grades/transcript/{ctx['sid']}")
            assert r.status_code == 200, r.get_data(as_text=True)
            data = r.get_json() or {}
            courses = (data.get("transcript") or {}).get("خريف 2024/2025") or []
            assert courses, data
            hit = next((x for x in courses if x.get("course_name") == ctx["course"]), None)
            assert hit is not None
            audit = hit.get("audit") or {}
            assert audit.get("supervisor_approved") is True
            assert (audit.get("supervisor_by") or audit.get("entered_by")) == ctx["sup_user"]
            assert audit.get("entered_by") == ctx["sup_user"]
            assert not audit.get("hod_approved")

    def test_legacy_hod_approve_attributes_enterer_to_supervisor(self, app, db_conn, civil_dept_with_advisee):
        """المسار القديم: المشرف يقدّم ورئيس القسم يعتمد — المدخل = المشرف وليس الرئيس."""
        from backend.services.transcript_corrections import _ensure_table

        ctx = civil_dept_with_advisee
        _ensure_table(db_conn)
        now = "2026-01-01T00:00:00Z"
        payload = json.dumps(
            {"grades": [{"course_name": ctx["course"], "grade": 66}], "is_equated_semester": False},
            ensure_ascii=False,
        )
        db_conn.execute(
            """
            INSERT INTO transcript_correction_requests (
                student_id, semester, payload_json, status, reason,
                submitted_by, instructor_id, department_id,
                created_at, submitted_at, reviewed_at, reviewed_by, hod_note
            ) VALUES (?, ?, ?, 'approved', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ctx["sid"],
                "ربيع 2023/2024",
                payload,
                "إدخال قديم",
                ctx["sup_user"],
                ctx["iid"],
                ctx["dept_id"],
                now,
                now,
                now,
                ctx["head_user"],
                "",
            ),
        )
        db_conn.execute(
            """
            INSERT INTO grades (student_id, semester, course_name, course_code, units, grade)
            VALUES (?, ?, ?, 'C1', 3, 66)
            """,
            (ctx["sid"], "ربيع 2023/2024", ctx["course"]),
        )
        # تدقيق قديم باسم رئيس القسم إن وُجد الجدول (يُتجاهل لصالح submitted_by)
        try:
            db_conn.execute(
                """
                INSERT INTO grade_audit (student_id, semester, course_name, old_grade, new_grade, changed_by, ts)
                VALUES (?, ?, ?, NULL, 66, ?, ?)
                """,
                (
                    ctx["sid"],
                    "ربيع 2023/2024",
                    ctx["course"],
                    f"{ctx['head_user']}|transcript_correction|اعتماد طلب",
                    now,
                ),
            )
        except Exception:
            pass
        db_conn.commit()

        with app.test_client() as c:
            c.post("/auth/login", json={"username": ctx["head_user"], "password": ctx["password"]})
            r = c.get(f"/grades/transcript/{ctx['sid']}")
            assert r.status_code == 200, r.get_data(as_text=True)
            courses = ((r.get_json() or {}).get("transcript") or {}).get("ربيع 2023/2024") or []
            hit = next((x for x in courses if x.get("course_name") == ctx["course"]), None)
            assert hit is not None
            audit = hit.get("audit") or {}
            assert audit.get("entered_by") == ctx["sup_user"]
            assert audit.get("hod_approved") is True
            assert audit.get("hod_by") == ctx["head_user"]
            assert not audit.get("supervisor_approved")

    def test_courses_for_student_scoped_to_dept(self, app, civil_dept_with_advisee):
        ctx = civil_dept_with_advisee
        with app.test_client() as c:
            assert c.post(
                "/auth/login",
                json={"username": ctx["sup_user"], "password": ctx["password"]},
            ).status_code == 200
            c.post("/auth/active_mode", json={"mode": "supervisor"})
            r = c.get(f"/grades/courses_for_student?student_id={ctx['sid']}")
            assert r.status_code == 200, r.get_data(as_text=True)
            items = r.get_json() or []
            names = {x.get("course_name") for x in items if isinstance(x, dict)}
            assert ctx["course"] in names
            foreign = [n for n in names if n and n.startswith("أجنبي-")]
            assert not foreign, f"ظهرت مقررات قسم آخر: {foreign}"
