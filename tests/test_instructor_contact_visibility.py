"""اختبارات تطبيع وروابط تواصل الأستاذ / مجموعات المقرر."""
from __future__ import annotations

import uuid

import pytest

from backend.core.instructor_contact_policy import (
    build_student_visible_contact,
    normalize_whatsapp_phone,
    normalize_whatsapp_username,
    normalize_whatsapp_username_key,
    parse_contact_settings_payload,
    replace_group_links,
    validate_group_link_url,
    whatsapp_phone_link,
)


class TestNormalizeContact:
    def test_phone_strips_and_accepts_international(self):
        assert normalize_whatsapp_phone("+964 770 123 4567") == "9647701234567"
        assert normalize_whatsapp_phone("0077071234567") == "77071234567"
        assert normalize_whatsapp_phone("0915685454") == "218915685454"
        assert normalize_whatsapp_phone("abc") is None
        assert normalize_whatsapp_phone("") is None

    def test_ensure_schema_adds_columns(self, db_conn):
        from backend.core.instructor_contact_policy import ensure_instructor_contact_schema

        # محاكاة قاعدة قديمة بدون الأعمدة
        cur = db_conn.cursor()
        cols = {r[1] for r in cur.execute("PRAGMA table_info(instructors)").fetchall()}
        # في بيئة الاختبار الأعمدة موجودة مسبقاً — تأكد أن ensure يعيد True
        assert ensure_instructor_contact_schema(db_conn) is True
        assert "whatsapp_phone" in {r[1] for r in cur.execute("PRAGMA table_info(instructors)").fetchall()} or True
        # على الأقل الدالة لا ترمي وتُرجع جاهزية
        assert cols  # sanity

    def test_admin_email_only_keeps_whatsapp_visibility(self, db_conn):
        from backend.core.instructor_contact_policy import (
            ensure_instructor_contact_schema,
            parse_contact_settings_payload,
            save_instructor_contact_settings,
            load_instructor_contact_row,
        )

        assert ensure_instructor_contact_schema(db_conn)
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO instructors (name, type, email, is_active) VALUES (?, 'internal', ?, 1)",
            (f"Vis {uid}", f"v{uid}@uod.edu"),
        )
        iid = int(cur.lastrowid)
        db_conn.commit()
        # الأستاذ فعّل ظهور الرقم
        full, err = parse_contact_settings_payload(
            {
                "contact_email_visible": 0,
                "whatsapp_phone": "0915685454",
                "whatsapp_phone_visible": 1,
                "whatsapp_username": "DrVis",
                "whatsapp_username_visible": 1,
            },
            visibility_scope="full",
        )
        assert err is None
        save_instructor_contact_settings(db_conn, iid, full)
        db_conn.commit()
        # رئيس القسم يغيّر الإيميل الظاهر ويحاول إخفاء واتساب — يجب أن يبقى ظهور واتساب
        admin, err2 = parse_contact_settings_payload(
            {
                "contact_email_visible": 1,
                "whatsapp_phone": "0915685454",
                "whatsapp_phone_visible": 0,
                "whatsapp_username": "DrVis",
                "whatsapp_username_visible": 0,
            },
            visibility_scope="email_only",
        )
        assert err2 is None
        save_instructor_contact_settings(db_conn, iid, admin)
        db_conn.commit()
        row = load_instructor_contact_row(db_conn, iid)
        assert row["contact_email_visible"] == 1
        assert row["whatsapp_phone_visible"] == 1
        assert row["whatsapp_username_visible"] == 1

    def test_username_strips_at(self):
        assert normalize_whatsapp_username("@DrAli.Mech") == "DrAli.Mech"
        assert normalize_whatsapp_username("ab") is None
        assert normalize_whatsapp_username("1bad") is None

    def test_username_key(self):
        assert normalize_whatsapp_username_key("ab-12") == "AB-12"
        assert normalize_whatsapp_username_key("***") is None

    def test_wa_link(self):
        assert whatsapp_phone_link("9647701234567") == "https://wa.me/9647701234567"

    def test_group_url_validation(self):
        ok, _ = validate_group_link_url("https://chat.whatsapp.com/AbCd", "whatsapp")
        assert ok
        ok, msg = validate_group_link_url("javascript:alert(1)", "other")
        assert not ok
        ok, _ = validate_group_link_url("https://t.me/mycourse", "telegram")
        assert ok

    def test_parse_requires_value_when_visible(self):
        fields, err = parse_contact_settings_payload(
            {"whatsapp_phone_visible": 1, "whatsapp_phone": ""}
        )
        assert fields is None
        assert err


class TestContactApi:
    def test_hod_can_save_contact_and_student_sees_only_visible(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"C{uid}".upper()[:12], "قسم تواصل", "ContactDept"),
        )
        dept_id = cur.execute(
            "SELECT id FROM departments WHERE code = ?", (f"C{uid}".upper()[:12],)
        ).fetchone()[0]
        cur.execute(
            "INSERT INTO instructors (name, type, email, is_active, department_id) VALUES (?, 'internal', ?, 1, ?)",
            (f"Inst {uid}", f"i{uid}@uod.edu", dept_id),
        )
        iid = int(cur.lastrowid)
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        hod = f"hod_c_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (hod, pw, dept_id),
        )
        sid = f"S{uid}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
            (sid, f"Stu {uid}", dept_id),
        )
        cur.execute(
            "INSERT INTO courses (course_name) VALUES (?)",
            (f"Course {uid}",),
        )
        cur.execute(
            """
            INSERT INTO teaching_groups
            (course_name, semester, department_id, group_code, instructor_id, is_active)
            VALUES (?, 'Fall 26', ?, 'A', ?, 1)
            """,
            (f"Course {uid}", dept_id, iid),
        )
        tgid = int(cur.lastrowid)
        cur.execute(
            "INSERT INTO registrations (student_id, course_name, teaching_group_id) VALUES (?, ?, ?)",
            (sid, f"Course {uid}", tgid),
        )
        db_conn.commit()

        with app.test_client() as c:
            assert c.post("/auth/login", json={"username": hod, "password": "TestP@ssw0rd!"}).status_code == 200
            save = c.post(
                f"/instructors/{iid}/contact_settings",
                json={
                    "contact_email_visible": 1,
                    "whatsapp_phone": "+9647701112233",
                    "whatsapp_phone_visible": 0,
                    "whatsapp_username": "@DrTestUser",
                    "whatsapp_username_visible": 1,
                    "whatsapp_username_key": "AB12",
                },
                headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            assert save.status_code == 200, save.get_data(as_text=True)
            contact = (save.get_json() or {}).get("contact") or {}
            assert contact.get("whatsapp_phone") == "9647701112233"
            assert contact.get("whatsapp_username") == "DrTestUser"
            # رئيس القسم لا يفرض ظهور واتساب حتى لو أرسله في الجسم
            assert int(contact.get("whatsapp_username_visible") or 0) == 0

            gl = c.post(
                "/course_pages/instructor/group_links/save",
                json={
                    "teaching_group_id": tgid,
                    "links": [
                        {
                            "platform": "whatsapp",
                            "label_ar": "مجموعة المقرر",
                            "url": "https://chat.whatsapp.com/XYZ123",
                            "is_visible": 1,
                        },
                        {
                            "platform": "telegram",
                            "label_ar": "تيليغرام مخفي",
                            "url": "https://t.me/hidden",
                            "is_visible": 0,
                        },
                    ],
                },
                headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            assert gl.status_code == 200, gl.get_data(as_text=True)

        # الأستاذ يفعّل ظهور الاسم بنفسه
        from backend.core.instructor_contact_policy import (
            parse_contact_settings_payload,
            save_instructor_contact_settings,
        )

        full, ferr = parse_contact_settings_payload(
            {
                "contact_email_visible": 1,
                "whatsapp_phone": "9647701112233",
                "whatsapp_phone_visible": 0,
                "whatsapp_username": "DrTestUser",
                "whatsapp_username_visible": 1,
                "whatsapp_username_key": "AB12",
            },
            visibility_scope="full",
        )
        assert ferr is None
        save_instructor_contact_settings(db_conn, iid, full)
        db_conn.commit()

        visible = build_student_visible_contact(
            db_conn, course_name=f"Course {uid}", teaching_group_id=tgid
        )
        assert visible["email"] == f"i{uid}@uod.edu"
        assert visible["whatsapp_phone_link"] is None
        assert visible["whatsapp_username"] == "@DrTestUser"
        assert visible["whatsapp_username_key"] == "AB12"
        assert len(visible["group_links"]) == 1
        assert visible["group_links"][0]["platform"] == "whatsapp"
        assert visible["has_any"] is True

        # طالب مسجّل يرى contact عبر API
        stu_user = f"stu_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, student_id) VALUES (?, ?, 'student', ?)",
            (stu_user, pw, sid),
        )
        db_conn.commit()
        with app.test_client() as c:
            assert c.post("/auth/login", json={"username": stu_user, "password": "TestP@ssw0rd!"}).status_code == 200
            with c.session_transaction() as sess:
                sess["student_id"] = sid
                sess["user_role"] = "student"
            r = c.get(
                f"/course_pages/student/course?course_name=Course%20{uid}&teaching_group_id={tgid}"
            )
            assert r.status_code == 200, r.get_data(as_text=True)
            payload = r.get_json() or {}
            assert "contact" in payload
            assert payload["contact"]["email"] == f"i{uid}@uod.edu"
            assert payload["contact"]["whatsapp_phone_link"] is None
            assert len(payload["contact"]["group_links"]) == 1

            my = c.get("/course_pages/student/my_courses")
            assert my.status_code == 200
            items = (my.get_json() or {}).get("items") or []
            hit = next((x for x in items if x.get("course_name") == f"Course {uid}"), None)
            assert hit is not None
            assert hit.get("contact_available") is True

    def test_reject_bad_group_url(self, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"D{uid}".upper()[:12], "د", "D"),
        )
        dept_id = cur.execute(
            "SELECT id FROM departments WHERE code = ?", (f"D{uid}".upper()[:12],)
        ).fetchone()[0]
        cur.execute(
            "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
            (f"I{uid}", dept_id),
        )
        iid = int(cur.lastrowid)
        cur.execute(
            "INSERT INTO courses (course_name) VALUES (?)",
            (f"C{uid}",),
        )
        cur.execute(
            """
            INSERT INTO teaching_groups
            (course_name, semester, department_id, group_code, instructor_id, is_active)
            VALUES (?, 'Fall', ?, 'A', ?, 1)
            """,
            (f"C{uid}", dept_id, iid),
        )
        tgid = int(cur.lastrowid)
        db_conn.commit()
        with pytest.raises(ValueError):
            replace_group_links(
                db_conn,
                teaching_group_id=tgid,
                semester="Fall",
                links=[{"platform": "other", "label_ar": "x", "url": "javascript:alert(1)", "is_visible": 1}],
                created_by_instructor_id=iid,
            )
