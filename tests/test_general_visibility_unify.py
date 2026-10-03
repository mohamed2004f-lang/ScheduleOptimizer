# -*- coding: utf-8 -*-
"""ظهور مقررات الاتجاه العام للتخصص دون اشتراط بنود program_courses."""
import uuid


def test_specialty_sees_general_owned_without_plan_link(app, db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        ("GENERAL", "الاتجاه العام", "General"),
    )
    gen_dept = int(cur.execute("SELECT id FROM departments WHERE code = 'GENERAL'").fetchone()[0])
    code = f"RN{uid}"[:12].upper()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (code, "طاقات", "Renew"),
    )
    dep = int(cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0])
    gen_course = f"MathGen-{uid}"
    cur.execute(
        "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
        (gen_course, f"GS{uid[:4]}", 3, gen_dept),
    )
    # لا نضيف program_courses عمداً
    pw = cur.execute("SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1").fetchone()[0]
    head = f"head_vis_{uid}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
        (head, pw, dep),
    )
    db_conn.commit()

    with app.test_client() as c:
        assert c.post("/auth/login", json={"username": head, "password": "TestP@ssw0rd!"}).status_code == 200
        r = c.get("/courses/list")
        assert r.status_code == 200, r.data
        names = {x.get("course_name") for x in (r.get_json() or [])}
        assert gen_course in names


def test_ensure_college_general_copies_to_empty_program(db_conn):
    from backend.services.college_catalog import ensure_college_general_plan_items

    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS enrollment_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT, semester TEXT, status TEXT,
            created_at TEXT, updated_at TEXT
        )
        """
    )
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        ("GENERAL", "الاتجاه العام", "General"),
    )
    gen_dept = int(cur.execute("SELECT id FROM departments WHERE code = 'GENERAL'").fetchone()[0])
    src_code = f"MS{uid}"[:12].upper()
    dst_code = f"CS{uid}"[:12].upper()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (src_code, "مصدر", "Src"),
    )
    src_dep = int(cur.execute("SELECT id FROM departments WHERE code = ?", (src_code,)).fetchone()[0])
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (dst_code, "هدف", "Dst"),
    )
    dst_dep = int(cur.execute("SELECT id FROM departments WHERE code = ?", (dst_code,)).fetchone()[0])
    cur.execute(
        "INSERT INTO programs (code, name_ar, department_id, is_active) VALUES (?, ?, ?, 1)",
        (f"PROG_SRC_{uid}", "مصدر", src_dep),
    )
    src_prog = int(cur.execute("SELECT id FROM programs WHERE code = ?", (f"PROG_SRC_{uid}",)).fetchone()[0])
    cur.execute(
        "INSERT INTO programs (code, name_ar, department_id, is_active) VALUES (?, ?, ?, 1)",
        (f"PROG_DST_{uid}", "هدف", dst_dep),
    )
    dst_prog = int(cur.execute("SELECT id FROM programs WHERE code = ?", (f"PROG_DST_{uid}",)).fetchone()[0])
    cur.execute(
        "INSERT INTO course_master (title_ar, default_units, assessment_type) VALUES (?, ?, 'theoretical')",
        (f"GenTitle-{uid}", 3),
    )
    mid = int(cur.execute("SELECT id FROM course_master WHERE title_ar = ?", (f"GenTitle-{uid}",)).fetchone()[0])
    cur.execute(
        """
        INSERT INTO program_courses
        (program_id, course_master_id, course_code, requirement_scope, level_no, units_override, is_active, is_required)
        VALUES (?, ?, ?, 'college_general', 1, 3, 1, 1)
        """,
        (src_prog, mid, f"GS {uid[:3]}"),
    )
    db_conn.commit()
    n = ensure_college_general_plan_items(db_conn, dst_prog)
    assert n >= 1
    cnt = cur.execute(
        """
        SELECT COUNT(*) FROM program_courses
        WHERE program_id = ? AND requirement_scope = 'college_general'
        """,
        (dst_prog,),
    ).fetchone()[0]
    assert int(cnt) >= 1
