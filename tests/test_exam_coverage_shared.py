"""تغطية جدول الامتحانات: إلزامي / مشترك اختياري / مستثنى + إضافة مشتركة."""

import uuid

from backend.services.coverage_insights import (
    classify_registration_exam_gaps,
    is_exam_exempt_course,
)


def test_is_exam_exempt_graduation_project():
    assert is_exam_exempt_course("مشروع تخرج جزء أول")
    assert is_exam_exempt_course("مشروع تخرج جزء ثاني")
    assert not is_exam_exempt_course("ميكانيكا هندسية II")


def test_classify_registration_exam_gaps_dept_owned_vs_shared(db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    code = f"CLF{uid}".upper()[:12]
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (code, "قسم تصنيف", "Classify"),
    )
    dep = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
    owned = f"OwnedCourse{uid}"
    shared = f"SharedCourse{uid}"
    grad = f"مشروع تخرج جزء أول {uid}"
    other_dep_code = f"OTH{uid}".upper()[:12]
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (other_dep_code, "قسم آخر", "Other"),
    )
    other_dep = cur.execute("SELECT id FROM departments WHERE code = ?", (other_dep_code,)).fetchone()[0]
    cur.execute(
        """
        INSERT OR REPLACE INTO courses
        (course_name, course_code, units, category, owning_department_id)
        VALUES (?, ?, 3, 'required', ?)
        """,
        (owned, f"O{uid[:4]}", dep),
    )
    cur.execute(
        """
        INSERT OR REPLACE INTO courses
        (course_name, course_code, units, category, owning_department_id)
        VALUES (?, ?, 3, 'required', ?)
        """,
        (shared, f"S{uid[:4]}", other_dep),
    )
    cur.execute(
        """
        INSERT OR REPLACE INTO courses
        (course_name, course_code, units, category, owning_department_id)
        VALUES (?, ?, 3, 'required', ?)
        """,
        (grad, f"G{uid[:4]}", dep),
    )
    db_conn.commit()
    classified = classify_registration_exam_gaps(
        db_conn,
        [owned, shared, grad],
        department_id=int(dep),
    )
    assert owned in classified["required"]
    assert shared in classified["optional_shared"]
    assert grad in classified["exempt"]
    assert owned not in classified["optional_shared"]
    assert shared not in classified["required"]


def test_head_coverage_splits_required_optional_exempt(app, db_conn):
    uid = uuid.uuid4().hex[:8]
    code = f"HCV{uid}".upper()[:12]
    cur = db_conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_type TEXT NOT NULL,
            exam_id INTEGER,
            course_name TEXT NOT NULL,
            exam_date TEXT,
            exam_time TEXT,
            room TEXT,
            instructor TEXT
        )
        """
    )
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (code, "قسم تغطية", "Coverage"),
    )
    dep = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
    other_code = f"HCO{uid}".upper()[:12]
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (other_code, "قسم ملكية مشتركة", "SharedOwner"),
    )
    other_dep = cur.execute("SELECT id FROM departments WHERE code = ?", (other_code,)).fetchone()[0]

    owned = f"DeptOwned{uid}"
    shared = f"SharedMech{uid}"
    grad = "مشروع تخرج جزء أول"
    for name, owner, code_sfx in (
        (owned, dep, "D"),
        (shared, other_dep, "S"),
        (grad, dep, "P"),
    ):
        cur.execute(
            """
            INSERT OR REPLACE INTO courses
            (course_name, course_code, units, category, owning_department_id)
            VALUES (?, ?, 3, 'required', ?)
            """,
            (name, f"{code_sfx}{uid[:4]}", owner),
        )

    sid = f"HCVS{uid}"
    cur.execute(
        "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
        (sid, "طالب تغطية", dep),
    )
    for cname in (owned, shared, grad):
        cur.execute("INSERT INTO registrations (student_id, course_name) VALUES (?, ?)", (sid, cname))

    pw = cur.execute("SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1").fetchone()[0]
    head_user = f"head_hcv_{uid}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
        (head_user, pw, dep),
    )
    db_conn.commit()

    headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
    with app.test_client() as c:
        assert c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"}).status_code == 200
        r = c.get("/exams/midterm/schedule_coverage", headers=headers)
        assert r.status_code == 200
        cov = r.get_json() or {}
        base = cov.get("registration_baseline") or {}
        required = base.get("missing_required") or []
        optional = base.get("missing_optional_shared") or []
        exempt = base.get("missing_exempt") or []
        assert owned in required
        assert shared in optional
        assert any("مشروع تخرج" in x for x in exempt)
        assert shared not in (base.get("missing_in_exam") or [])
        assert owned in (base.get("missing_in_exam") or [])


def test_head_can_add_shared_course_with_registration(app, db_conn):
    uid = uuid.uuid4().hex[:8]
    code = f"HAD{uid}".upper()[:12]
    cur = db_conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_type TEXT NOT NULL,
            exam_id INTEGER,
            course_name TEXT NOT NULL,
            exam_date TEXT,
            exam_time TEXT,
            room TEXT,
            instructor TEXT
        )
        """
    )
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (code, "قسم إضافة", "AddDept"),
    )
    dep = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
    other_code = f"HAO{uid}".upper()[:12]
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (other_code, "مالك مشترك", "SharedOwner2"),
    )
    other_dep = cur.execute("SELECT id FROM departments WHERE code = ?", (other_code,)).fetchone()[0]
    shared = f"AddShared{uid}"
    cur.execute(
        """
        INSERT OR REPLACE INTO courses
        (course_name, course_code, units, category, owning_department_id)
        VALUES (?, ?, 3, 'required', ?)
        """,
        (shared, f"A{uid[:4]}", other_dep),
    )
    sid = f"HADS{uid}"
    cur.execute(
        "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
        (sid, "طالب إضافة", dep),
    )
    cur.execute("INSERT INTO registrations (student_id, course_name) VALUES (?, ?)", (sid, shared))
    pw = cur.execute("SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1").fetchone()[0]
    head_user = f"head_had_{uid}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
        (head_user, pw, dep),
    )
    db_conn.commit()

    headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
    with app.test_client() as c:
        assert c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"}).status_code == 200
        r = c.post(
            "/exams/midterm/add_row",
            json={
                "course_name": shared,
                "exam_date": "2026-05-10",
                "exam_time": "09:00-11:00",
                "room": "A1",
                "instructor": "T",
            },
            headers=headers,
        )
        assert r.status_code == 200, r.get_json()
        assert (r.get_json() or {}).get("status") == "ok"
        rows = c.get("/exams/midterm/rows", headers=headers).get_json() or []
        names = {str(x.get("course_name") or "").strip() for x in rows}
        assert shared in names
