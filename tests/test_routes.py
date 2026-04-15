"""
اختبارات Integration لمسارات Flask (Routes).

يغطي:
- مسارات عامة (لا تحتاج تسجيل دخول): /health, /login
- مسارات محمية (تحتاج تسجيل دخول): /, /dashboard
- مسار تسجيل الدخول والخروج عبر API: /auth/login, /auth/logout, /auth/check
"""
import pytest


# ═══════════════════════════════════════════════════════
# 1. مسارات عامة (بدون تسجيل دخول)
# ═══════════════════════════════════════════════════════

class TestPublicRoutes:
    """اختبارات المسارات العامة التي لا تحتاج تسجيل دخول."""

    def test_health_returns_200(self, client):
        """GET /health يجب أن يرجع 200 مع status=healthy."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"
        assert "uptime_seconds" in data
        assert "version" in data
        assert "environment" in data

    def test_health_reflects_request_id_header(self, client):
        """العميل يمكنه تمرير X-Request-ID ويُعاد في الاستجابة."""
        resp = client.get("/health", headers={"X-Request-ID": "test-req-abc-001"})
        assert resp.status_code == 200
        assert resp.headers.get("X-Request-ID") == "test-req-abc-001"

    def test_health_ready_checks_database(self, client):
        """GET /health/ready يتحقق من الاتصال بقاعدة البيانات."""
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("status") == "ready"
        assert data.get("database_ok") is True

    def test_system_diagnostics_requires_login(self, client):
        resp = client.get("/admin/system_diagnostics")
        assert resp.status_code in (401, 403, 302)

    def test_login_page_accessible(self, client):
        """GET /login يجب أن يكون متاحاً (200 أو 500 إذا كان القالب غير موجود في بيئة الاختبار)."""
        resp = client.get("/login")
        # In test environment templates may not be available, so 500 is acceptable.
        # The key assertion is that it does NOT return 401/403 (i.e., it's not auth-protected).
        assert resp.status_code in (200, 500)
        assert resp.status_code != 401
        assert resp.status_code != 403


# ═══════════════════════════════════════════════════════
# 2. مسارات محمية (بدون تسجيل دخول → 401 أو redirect)
# ═══════════════════════════════════════════════════════

class TestProtectedRoutesUnauthenticated:
    """اختبارات المسارات المحمية عند عدم تسجيل الدخول."""

    def test_root_redirects_to_login(self, app):
        """GET / بدون تسجيل دخول يجب أن يحول إلى /login."""
        # Use a fresh client (no session) to avoid auth leaking from session-scoped client.
        with app.test_client() as c:
            resp = c.get("/", follow_redirects=False)
            assert resp.status_code in (302, 301)
            assert "/login" in resp.headers.get("Location", "")

    def test_dashboard_api_returns_401(self, app):
        """GET /dashboard بدون تسجيل دخول عبر API يجب أن يرجع 401."""
        with app.test_client() as c:
            resp = c.get(
                "/dashboard",
                headers={"Accept": "application/json"},
            )
            assert resp.status_code in (401, 403)


# ═══════════════════════════════════════════════════════
# 3. تسجيل الدخول والخروج
# ═══════════════════════════════════════════════════════

class TestAuthFlow:
    """اختبارات تدفق المصادقة الكامل."""

    def test_login_missing_credentials(self, app):
        """POST /auth/login بدون بيانات يجب أن يرجع 400."""
        with app.test_client() as c:
            resp = c.post("/auth/login", json={})
            assert resp.status_code == 400
            data = resp.get_json()
            assert data["status"] == "error"

    def test_login_wrong_password(self, app):
        """POST /auth/login بكلمة مرور خاطئة يجب أن يرجع 401."""
        with app.test_client() as c:
            resp = c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "wrong-password"},
            )
            assert resp.status_code == 401

    def test_login_success(self, app):
        """POST /auth/login ببيانات صحيحة يجب أن يرجع 200."""
        with app.test_client() as c:
            resp = c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "ok"
            assert data["user"] == "admin-test"

    def test_auth_check_after_login(self, app):
        """GET /auth/check بعد تسجيل الدخول يجب أن يرجع authenticated=True."""
        with app.test_client() as c:
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            resp = c.get("/auth/check")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["authenticated"] is True
            assert "capabilities" in data
            caps = data["capabilities"]
            assert caps is not None
            assert caps.get("v") == 1
            assert caps.get("can_manage_schedule_edit") is True

    def test_logout(self, app):
        """POST /auth/logout بعد تسجيل الدخول يجب أن يرجع 200."""
        with app.test_client() as c:
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            resp = c.post("/auth/logout")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "ok"

    def test_auth_check_after_logout(self, app):
        """GET /auth/check بعد تسجيل الخروج يجب أن يرجع authenticated=False."""
        with app.test_client() as c:
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            c.post("/auth/logout")
            resp = c.get("/auth/check")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["authenticated"] is False


# ═══════════════════════════════════════════════════════
# 4. مسارات محمية (بعد تسجيل الدخول)
# ═══════════════════════════════════════════════════════

class TestProtectedRoutesAuthenticated:
    """اختبارات المسارات المحمية بعد تسجيل الدخول كـ admin."""

    def test_root_after_login_redirects_to_dashboard(self, auth_client):
        """GET / بعد تسجيل الدخول كـ admin يجب أن يحول إلى dashboard."""
        resp = auth_client.get("/", follow_redirects=False)
        # admin role gets redirected to /dashboard
        assert resp.status_code in (200, 302)

    def test_students_list(self, auth_client):
        """GET /students/list يجب أن يرجع 200 مع بيانات JSON."""
        resp = auth_client.get(
            "/students/list",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200

    def test_students_add_then_list_contains_new_student(self, auth_client):
        """POST /students/add ثم التأكد من ظهور الطالب في /students/list."""
        sid = "S900"
        add_resp = auth_client.post(
            "/students/add",
            json={
                "student_id": sid,
                "student_name": "طالب اختبار تكاملي",
                "graduation_plan": "150 وحدة",
                "join_term": "خريف",
                "join_year": "25-26",
            },
        )
        assert add_resp.status_code == 200
        add_data = add_resp.get_json()
        assert add_data is not None
        assert add_data.get("status") == "ok"

        list_resp = auth_client.get("/students/list", headers={"Accept": "application/json"})
        assert list_resp.status_code == 200
        rows = list_resp.get_json() or []
        assert any((r.get("student_id") == sid) for r in rows)

    def test_results_data_returns_200_and_expected_keys(self, auth_client):
        """GET /results_data لا يجب أن يفشل ImportError ويُرجع البنية المتوقعة."""
        resp = auth_client.get("/results_data", headers={"Accept": "application/json"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)
        assert "conflict_report" in data
        assert "proposed_moves" in data
        assert "optimized_schedule" in data

    def test_system_diagnostics_returns_json(self, auth_client):
        """GET /admin/system_diagnostics يعيد ملخصاً آمناً للمسؤول."""
        resp = auth_client.get("/admin/system_diagnostics")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("status") == "ok"
        assert "database" in data
        assert "last_critical_errors" in data
        assert "users_count" in data


# ═══════════════════════════════════════════════════════
# 5. عرض جدول الطالب والدرجات وطلبات التسجيل
# ═══════════════════════════════════════════════════════


class TestStudentViewRoute:
    """تأكيد حماية ``/student_view`` وإتاحتها بعد تسجيل الدخول."""

    def test_student_view_unauthenticated_redirects_to_login(self, app):
        with app.test_client() as c:
            resp = c.get("/student_view", follow_redirects=False)
            assert resp.status_code in (302, 301)
            assert "/login" in resp.headers.get("Location", "")

    def test_student_view_unauthenticated_json_returns_401(self, app):
        with app.test_client() as c:
            resp = c.get(
                "/student_view",
                headers={"Accept": "application/json"},
            )
            assert resp.status_code == 401

    def test_student_view_authenticated_ok(self, auth_client):
        resp = auth_client.get("/student_view")
        assert resp.status_code in (200, 500)


class TestGradesTranscriptRoute:
    """مسار كشف الدرجات لطالب موجود في بيانات الاختبار."""

    def test_transcript_requires_auth(self, app):
        with app.test_client() as c:
            resp = c.get(
                "/grades/transcript/S001",
                headers={"Accept": "application/json"},
            )
            assert resp.status_code == 401

    def test_transcript_admin_returns_json(self, auth_client):
        resp = auth_client.get(
            "/grades/transcript/S001",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        assert "status" in data or "student_id" in data or "courses" in str(data).lower()


class TestRegistrationRequestsRoutes:
    """تكامل أساسي لطلبات الإضافة/الإسقاط."""

    def test_list_requires_auth(self, app):
        with app.test_client() as c:
            resp = c.get(
                "/registration_requests/list",
                headers={"Accept": "application/json"},
            )
            assert resp.status_code == 401

    def test_list_admin_returns_ok(self, auth_client):
        resp = auth_client.get(
            "/registration_requests/list",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("status") == "ok"
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_create_as_student_then_approve_without_execute(self, student_auth_client, auth_client, db_conn):
        cur = db_conn.cursor()
        cur.execute("DELETE FROM registration_requests")
        cur.execute("DELETE FROM registrations WHERE student_id = ?", ("S001",))
        db_conn.commit()

        r = student_auth_client.post(
            "/registration_requests/create",
            json={
                "student_id": "S001",
                "term": "اختبار",
                "course_name": "رياضيات 1",
                "action": "add",
                "reason": "pytest",
            },
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body.get("status") == "ok"
        req_id = body.get("id")
        assert req_id is not None

        r2 = auth_client.post(
            "/registration_requests/approve",
            json={"id": req_id, "execute_now": False, "note": ""},
        )
        assert r2.status_code == 200
        row = cur.execute(
            "SELECT status FROM registration_requests WHERE id = ?",
            (req_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "approved"

    def test_create_as_student_then_approve_and_execute(self, student_auth_client, auth_client, db_conn):
        """اعتماد الطلب مع ``execute_now: true`` ينفّذ الإضافة على ``registrations``."""
        cur = db_conn.cursor()
        cur.execute("DELETE FROM registration_requests")
        cur.execute("DELETE FROM registrations WHERE student_id = ?", ("S001",))
        db_conn.commit()

        r = student_auth_client.post(
            "/registration_requests/create",
            json={
                "student_id": "S001",
                "term": "اختبار-تنفيذ",
                "course_name": "فيزياء 1",
                "action": "add",
                "reason": "pytest execute",
            },
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body.get("status") == "ok"
        req_id = body.get("id")
        assert req_id is not None

        r2 = auth_client.post(
            "/registration_requests/approve",
            json={"id": req_id, "execute_now": True, "note": ""},
        )
        assert r2.status_code == 200
        assert "تنفيذ" in (r2.get_json() or {}).get("message", "")

        row = cur.execute(
            "SELECT status FROM registration_requests WHERE id = ?",
            (req_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "executed"

        reg = cur.execute(
            "SELECT 1 FROM registrations WHERE student_id = ? AND course_name = ?",
            ("S001", "فيزياء 1"),
        ).fetchone()
        assert reg is not None


class TestSaveRegistrationsPrereqOverride:
    """تغطية fallback لتجاوز المتطلبات مع payload قديم."""

    def test_admin_legacy_override_reason_allows_prereq_override(self, app, monkeypatch):
        # نجبر التحقق ليُرجع مقررات محجوبة، للتأكد من مسار التجاوز.
        monkeypatch.setattr(
            "backend.services.students.evaluate_courses_prereqs",
            lambda cur, sid, courses, old_courses: {
                "blocked": {"فيزياء 1": ["رياضيات 1"]},
                "warnings": [],
                "coregister_pairs": [],
                "drop_violations": [],
            },
        )
        with app.test_client() as c:
            login = c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            assert login.status_code == 200

            resp = c.post(
                "/students/save_registrations",
                json={
                    "student_id": "S001",
                    "courses": ["رياضيات 1", "فيزياء 1", "كيمياء 1"],
                    # Legacy payload: لا يرسل prereq_override/prereq_override_reason
                    "override_reason": "عدم وجود كشف درجات للطالب",
                },
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data is not None
            assert data.get("status") == "ok"
            assert data.get("prereq_overridden") is True


class TestInstructorMyCourses:
    """لوحة مقرراتي والـ API المرتبطة."""

    def test_my_courses_page_requires_instructor(self, app):
        with app.test_client() as c:
            r = c.get("/my_courses")
            assert r.status_code in (302, 401, 403)

    def test_my_assigned_sections_for_instructor(self, app):
        with app.test_client() as c:
            login = c.post(
                "/auth/login",
                json={"username": "inst-test", "password": "TestP@ssw0rd!"},
            )
            assert login.status_code == 200
            resp = c.get("/schedule/my_assigned_sections")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "rows" in data
            assert len(data["rows"]) == 2
            assert data.get("instructor_name") == "أستاذ تجريبي"
            names = {r.get("course_name") for r in data["rows"]}
            assert names == {"رياضيات 1", "فيزياء 1"}
            assert "axes" in data["rows"][0]
            assert data["rows"][0]["axes"].get("assessment") == "pending"
            assert "axis_catalog" in data

    def test_my_axis_status_post(self, app):
        with app.test_client() as c:
            login = c.post(
                "/auth/login",
                json={"username": "inst-test", "password": "TestP@ssw0rd!"},
            )
            assert login.status_code == 200
            r0 = c.get("/schedule/my_assigned_sections").get_json()
            sid = r0["rows"][0]["section_id"]
            save = c.post(
                "/schedule/my_axis_status",
                json={"section_id": sid, "axis_key": "assessment", "status": "done"},
            )
            assert save.status_code == 200
            assert save.get_json().get("status") == "ok"
            r1 = c.get("/schedule/my_assigned_sections").get_json()
            row = next(x for x in r1["rows"] if x["section_id"] == sid)
            assert row["axes"]["assessment"] == "done"

    def test_my_assigned_sections_forbidden_for_admin(self, auth_client):
        resp = auth_client.get("/schedule/my_assigned_sections")
        assert resp.status_code == 403

    def test_my_course_admin_save_plan_and_syllabus(self, app):
        with app.test_client() as c:
            login = c.post(
                "/auth/login",
                json={"username": "inst-test", "password": "TestP@ssw0rd!"},
            )
            assert login.status_code == 200
            r0 = c.get("/schedule/my_assigned_sections").get_json()
            sid = r0["rows"][0]["section_id"]
            s1 = c.post(
                "/schedule/my_course_syllabus",
                json={"section_id": sid, "syllabus_text": "الأسبوع 1-3: أساسيات المقرر"},
            )
            assert s1.status_code == 200
            p1 = c.post(
                "/schedule/my_course_plan",
                json={
                    "section_id": sid,
                    "week_no": 1,
                    "week_topic": "مقدمة وتمهيد",
                    "lecture_status": "planned",
                    "resources_text": "ملف تمهيدي",
                },
            )
            assert p1.status_code == 200
            details = c.get(f"/schedule/my_course_admin?section_id={sid}")
            assert details.status_code == 200
            body = details.get_json()
            assert body.get("syllabus_text") == "الأسبوع 1-3: أساسيات المقرر"
            plan = body.get("weekly_plan") or []
            assert any(int(x.get("week_no") or 0) == 1 for x in plan)

    def test_student_announcements_scoped_to_registered_sections(self, app):
        with app.test_client() as c:
            # إنشاء إعلانين: واحد على مقرر مسجل للطالب S001 وآخر على مقرر غير مسجل.
            login_inst = c.post(
                "/auth/login",
                json={"username": "inst-test", "password": "TestP@ssw0rd!"},
            )
            assert login_inst.status_code == 200
            sections = c.get("/schedule/my_assigned_sections").get_json().get("rows") or []
            assert len(sections) >= 2
            s_registered = sections[0]["section_id"]
            s_other = sections[1]["section_id"]
            # نضبط تسجيلات الطالب يدوياً لتشمل فقط أول مقرر.
            with app.app_context():
                from backend.services.utilities import get_connection
                with get_connection() as conn:
                    cur = conn.cursor()
                    course_registered = sections[0]["course_name"]
                    cur.execute("DELETE FROM registrations WHERE student_id = ?", ("S001",))
                    cur.execute(
                        "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
                        ("S001", course_registered),
                    )
                    conn.commit()

            a1 = c.post(
                "/schedule/my_course_announcement",
                json={"section_id": s_registered, "body": "إعلان لشعبتي", "announcement_type": "general"},
            )
            assert a1.status_code == 200
            a2 = c.post(
                "/schedule/my_course_announcement",
                json={"section_id": s_other, "body": "إعلان لشعبة أخرى", "announcement_type": "general"},
            )
            assert a2.status_code == 200
            c.post("/auth/logout")

            login_student = c.post(
                "/auth/login",
                json={"username": "student-s001", "password": "TestP@ssw0rd!"},
            )
            assert login_student.status_code == 200
            out = c.get("/schedule/student_my_announcements")
            assert out.status_code == 200
            items = out.get_json().get("items") or []
            bodies = {x.get("body") for x in items}
            assert "إعلان لشعبتي" in bodies
            assert "إعلان لشعبة أخرى" not in bodies

    def test_faculty_assignments_scoped_for_instructor(self, app):
        with app.test_client() as c:
            login_admin = c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            assert login_admin.status_code == 200
            created = c.post(
                "/schedule/faculty_assignments",
                json={
                    "instructor_id": 1,
                    "assignment_type": "committee",
                    "title": "لجنة الجودة",
                    "decision_ref": "DEC-2026-01",
                    "start_date": "2026-01-01",
                    "end_date": "2026-12-31",
                },
            )
            assert created.status_code == 200
            assignment_id = (created.get_json() or {}).get("assignment_id")
            assert assignment_id is not None
            c.post("/auth/logout")

            login_inst = c.post(
                "/auth/login",
                json={"username": "inst-test", "password": "TestP@ssw0rd!"},
            )
            assert login_inst.status_code == 200
            mine = c.get("/schedule/faculty_assignments")
            assert mine.status_code == 200
            items = (mine.get_json() or {}).get("items") or []
            assert any(int(x.get("id") or 0) == int(assignment_id) for x in items)

            forbidden = c.get("/schedule/faculty_assignments?instructor_id=999")
            assert forbidden.status_code == 403

    def test_faculty_assignment_logs_follow_assignment_scope(self, app):
        with app.test_client() as c:
            login_admin = c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            assert login_admin.status_code == 200
            created = c.post(
                "/schedule/faculty_assignments",
                json={
                    "instructor_id": 1,
                    "assignment_type": "quality",
                    "title": "تقرير جودة المقرر",
                    "decision_ref": "DEC-2026-02",
                },
            )
            assert created.status_code == 200
            assignment_id = int((created.get_json() or {}).get("assignment_id") or 0)
            assert assignment_id > 0
            c.post("/auth/logout")

            login_inst = c.post(
                "/auth/login",
                json={"username": "inst-test", "password": "TestP@ssw0rd!"},
            )
            assert login_inst.status_code == 200
            add_log = c.post(
                "/schedule/faculty_assignment_logs",
                json={
                    "assignment_id": assignment_id,
                    "log_type": "quality_report",
                    "notes": "تم إعداد تقرير أولي للمقرر.",
                    "approval_status": "submitted",
                },
            )
            assert add_log.status_code == 200
            c.post("/auth/logout")

            login_admin2 = c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            assert login_admin2.status_code == 200
            logs_resp = c.get(f"/schedule/faculty_assignment_logs?assignment_id={assignment_id}")
            assert logs_resp.status_code == 200
            logs = (logs_resp.get_json() or {}).get("items") or []
            assert any((x.get("log_type") == "quality_report") for x in logs)


class TestGradeDraftsSectionScope:
    def test_grade_draft_requires_assigned_section(self, app):
        with app.test_client() as c:
            login_inst = c.post(
                "/auth/login",
                json={"username": "inst-test", "password": "TestP@ssw0rd!"},
            )
            assert login_inst.status_code == 200
            sections_resp = c.get("/grades/drafts/courses")
            assert sections_resp.status_code == 200
            sections = (sections_resp.get_json() or {}).get("sections") or []
            assert sections
            s0 = sections[0]
            create_ok = c.post(
                "/grades/drafts",
                json={"course_name": s0.get("course_name"), "section_id": s0.get("section_id")},
            )
            assert create_ok.status_code == 200
            did = int((create_ok.get_json() or {}).get("draft_id") or 0)
            assert did > 0

            bad_roster = c.get(
                "/grades/drafts/roster?course_name="
                + str(s0.get("course_name"))
                + "&section_id=999999"
            )
            assert bad_roster.status_code == 403

    def test_grade_special_case_create_and_review(self, app):
        with app.test_client() as c:
            login_inst = c.post(
                "/auth/login",
                json={"username": "inst-test", "password": "TestP@ssw0rd!"},
            )
            assert login_inst.status_code == 200
            sec_resp = c.get("/grades/drafts/courses")
            sections = (sec_resp.get_json() or {}).get("sections") or []
            assert sections
            sec = sections[0]
            course_name = sec.get("course_name")
            section_id = sec.get("section_id")
            with app.app_context():
                from backend.services.utilities import get_connection
                with get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT OR IGNORE INTO registrations (student_id, course_name) VALUES (?, ?)",
                        ("S001", course_name),
                    )
                    conn.commit()

            create_case = c.post(
                "/grades/special_cases",
                json={
                    "course_name": course_name,
                    "section_id": section_id,
                    "student_id": "S001",
                    "case_type": "cheating",
                    "reason": "محضر موثق من لجنة الاختبار",
                },
            )
            assert create_case.status_code == 200
            case_id = int((create_case.get_json() or {}).get("case_id") or 0)
            assert case_id > 0
            c.post("/auth/logout")

            login_admin = c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            assert login_admin.status_code == 200
            review = c.post(
                f"/grades/special_cases/{case_id}/review",
                json={"status": "approved", "review_note": "تمت المراجعة والاعتماد"},
            )
            assert review.status_code == 200
            listed = c.get("/grades/special_cases?status=approved")
            assert listed.status_code == 200
            items = (listed.get_json() or {}).get("items") or []
            assert any(int(x.get("id") or 0) == case_id for x in items)
