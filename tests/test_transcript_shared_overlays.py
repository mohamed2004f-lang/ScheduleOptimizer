"""رموز/وحدات المقررات المشتركة في كشف الدرجات حسب قسم الطالب."""
from __future__ import annotations

import uuid


def _setup_fluids_shared(db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) "
        "VALUES ('GENERAL', 'عام', 'Gen', 1)"
    )
    mcode = f"MH{uid}"[:12].upper()
    ccode = f"CV{uid}"[:12].upper()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (mcode, "ميكانيك", "Mech"),
    )
    mech_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (mcode,)).fetchone()[0])
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (ccode, "مدني", "Civ"),
    )
    civil_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (ccode,)).fetchone()[0])

    cname = f"ميكانيكا الموائع I-{uid}"
    mech_course_code = f"ME{uid[:4].upper()}"
    civil_course_code = f"CI{uid[:4].upper()}"
    cur.execute(
        "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
        (cname, mech_course_code, 3, mech_id),
    )
    from backend.core.college_shared_catalog import save_catalog_entry

    save_catalog_entry(
        db_conn,
        {
            "catalog_key": f"fluids_{uid}",
            "share_type": "multi_code",
            "canonical_course_name": cname,
            "canonical_course_code": mech_course_code,
            "units": 3,
            "requirement_scope": "major",
            "departments": [
                {"department_id": mech_id, "plan_course_code": mech_course_code, "units_override": 3},
                {"department_id": civil_id, "plan_course_code": civil_course_code, "units_override": 4},
            ],
        },
    )
    db_conn.commit()
    return {
        "uid": uid,
        "cname": cname,
        "mech_id": mech_id,
        "civil_id": civil_id,
        "mcode": mcode,
        "ccode": ccode,
        "mech_course_code": mech_course_code,
        "civil_course_code": civil_course_code,
    }


def _insert_student(db_conn, student_id: str, department_id: int, name: str = "طالب"):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
        (student_id, name, department_id),
    )
    db_conn.commit()


def test_resolve_course_for_department_overlays(db_conn):
    from backend.core.college_shared_catalog import resolve_course_for_department

    ctx = _setup_fluids_shared(db_conn)
    civil = resolve_course_for_department(
        db_conn, ctx["cname"], ctx["civil_id"], base_code=ctx["mech_course_code"], base_units=3
    )
    assert civil["course_code"] == ctx["civil_course_code"]
    assert civil["units"] == 4

    mech = resolve_course_for_department(
        db_conn, ctx["cname"], ctx["mech_id"], base_code=ctx["mech_course_code"], base_units=3
    )
    assert mech["course_code"] == ctx["mech_course_code"]
    assert mech["units"] == 3


def test_unified_gs_unchanged_by_overlay(db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) "
        "VALUES ('GENERAL', 'عام', 'Gen', 1)"
    )
    gen_id = int(cur.execute("SELECT id FROM departments WHERE code='GENERAL'").fetchone()[0])
    dcode = f"D{uid}"[:12].upper()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (dcode, "قسم", "Dept"),
    )
    dept_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (dcode,)).fetchone()[0])
    cname = f"رياضيات-{uid}"
    from backend.core.college_shared_catalog import resolve_course_for_department, save_catalog_entry

    save_catalog_entry(
        db_conn,
        {
            "catalog_key": f"gs_{uid}",
            "share_type": "unified",
            "canonical_course_name": cname,
            "canonical_course_code": "GS101",
            "units": 3,
            "requirement_scope": "pre_track",
        },
    )
    db_conn.commit()
    resolved = resolve_course_for_department(
        db_conn, cname, dept_id, base_code="GS101", base_units=3
    )
    assert resolved["course_code"] == "GS101"
    assert resolved["units"] == 3
    # owning remains general path; overlay helpers return canonical for unified without dept row
    assert gen_id is not None


def test_apply_grades_batch_uses_student_department_overlay(db_conn):
    from backend.services.grades import apply_grades_batch

    ctx = _setup_fluids_shared(db_conn)
    sid = f"S{ctx['uid']}"
    _insert_student(db_conn, sid, ctx["civil_id"], "مدني")
    apply_grades_batch(
        db_conn,
        sid,
        "خريف 2026/2027",
        [{"course_name": ctx["cname"], "course_code": ctx["mech_course_code"], "grade": 70}],
        "test",
    )
    db_conn.commit()
    row = db_conn.cursor().execute(
        "SELECT course_code, units FROM grades WHERE student_id=? AND course_name=?",
        (sid, ctx["cname"]),
    ).fetchone()
    assert row is not None
    assert (row[0] if not hasattr(row, "keys") else row["course_code"]) == ctx["civil_course_code"]
    assert int(row[1] if not hasattr(row, "keys") else row["units"]) == 4


def test_apply_grades_batch_accepts_plan_code_and_mech_student(db_conn):
    from backend.services.grades import apply_grades_batch

    ctx = _setup_fluids_shared(db_conn)
    sid = f"M{ctx['uid']}"
    _insert_student(db_conn, sid, ctx["mech_id"], "ميكانيك")
    apply_grades_batch(
        db_conn,
        sid,
        "خريف 2026/2027",
        [{"course_name": ctx["cname"], "course_code": ctx["civil_course_code"], "grade": 65}],
        "test",
    )
    db_conn.commit()
    row = db_conn.cursor().execute(
        "SELECT course_code, units FROM grades WHERE student_id=? AND course_name=?",
        (sid, ctx["cname"]),
    ).fetchone()
    assert row is not None
    # طالب ميكانيكا: حتى لو أُرسل رمز المدني، الحفظ يطبّق overlay قسم الطالب
    assert (row[0] if not hasattr(row, "keys") else row["course_code"]) == ctx["mech_course_code"]
    assert int(row[1] if not hasattr(row, "keys") else row["units"]) == 3


def test_update_grade_keeps_civil_overlay(app, db_conn):
    """تصحيح درجة واحدة لا يعيد الرمز المرجعي للميكانيكا."""
    ctx = _setup_fluids_shared(db_conn)
    sid = f"U{ctx['uid']}"
    _insert_student(db_conn, sid, ctx["civil_id"], "مدني")
    from backend.services.grades import apply_grades_batch

    apply_grades_batch(
        db_conn,
        sid,
        "خريف 2023/2024",
        [{"course_name": ctx["cname"], "course_code": ctx["civil_course_code"], "grade": 38}],
        "seed",
    )
    db_conn.commit()
    cur = db_conn.cursor()
    pw = cur.execute(
        "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
    ).fetchone()[0]
    head = f"head_up_{ctx['uid']}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
        (head, pw, ctx["civil_id"]),
    )
    db_conn.commit()
    with app.test_client() as client:
        assert client.post("/auth/login", json={"username": head, "password": "TestP@ssw0rd!"}).status_code == 200
        r = client.post(
            "/grades/update",
            json={
                "student_id": sid,
                "semester": "خريف 2023/2024",
                "course_name": ctx["cname"],
                "course_code": ctx["mech_course_code"],
                "grade": 42,
                "reason": "تصحيح درجة بعد النشر للتحقق",
            },
        )
        assert r.status_code == 200, r.get_json()
    row = db_conn.cursor().execute(
        "SELECT course_code, units, grade FROM grades WHERE student_id=? AND semester=? AND course_name=?",
        (sid, "خريف 2023/2024", ctx["cname"]),
    ).fetchone()
    assert (row[0] if not hasattr(row, "keys") else row["course_code"]) == ctx["civil_course_code"]
    assert int(row[1] if not hasattr(row, "keys") else row["units"]) == 4
    assert float(row[2] if not hasattr(row, "keys") else row["grade"]) == 42.0


def test_resolve_accepts_plan_code_despite_asterisk_duplicate(db_conn):
    """رمز CIEN في صف مكرر (* ) لا يمنع حفظ الاسم الرسمي من سجل المشترك."""
    from backend.services.grades import _resolve_catalog_course

    ctx = _setup_fluids_shared(db_conn)
    cur = db_conn.cursor()
    # صف مكرر كما في الإنتاج: اسم بنجمة ورمز بلا مسافة
    dup_name = ctx["cname"] + "*"
    cur.execute(
        "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
        (dup_name, ctx["civil_course_code"].replace(" ", ""), 4, ctx["civil_id"]),
    )
    db_conn.commit()
    cur = db_conn.cursor()
    resolved = _resolve_catalog_course(
        cur,
        course_name=ctx["cname"],
        course_code=ctx["civil_course_code"],
        department_id=ctx["civil_id"],
        conn=db_conn,
    )
    assert resolved["course_name"] == ctx["cname"]
    assert resolved["course_code"] == ctx["civil_course_code"]
    assert int(resolved["units"]) == 4


def test_courses_for_student_returns_civil_overlay(app, db_conn):
    ctx = _setup_fluids_shared(db_conn)
    sid = f"C{ctx['uid']}"
    _insert_student(db_conn, sid, ctx["civil_id"], "مدني")
    cur = db_conn.cursor()
    pw = cur.execute(
        "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
    ).fetchone()[0]
    head = f"head_fl_{ctx['uid']}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
        (head, pw, ctx["civil_id"]),
    )
    db_conn.commit()

    with app.test_client() as client:
        assert client.post("/auth/login", json={"username": head, "password": "TestP@ssw0rd!"}).status_code == 200
        r = client.get(f"/grades/courses_for_student?student_id={sid}")
        assert r.status_code == 200
        rows = r.get_json() or []
        hit = next((x for x in rows if x.get("course_name") == ctx["cname"]), None)
        assert hit is not None
        assert hit.get("course_code") == ctx["civil_course_code"]
        assert int(hit.get("units") or 0) == 4
