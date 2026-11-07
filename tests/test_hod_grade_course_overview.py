"""معاينة درجات المقرر لكل المجموعات + تصفية حسب الأستاذ لرئيس القسم."""
from __future__ import annotations

import uuid

from backend.services import teaching_groups as tg


def _set_term(cur, semester: str = "خريف 44-45") -> str:
    parts = semester.rsplit(" ", 1)
    tname = parts[0] if len(parts) == 2 else semester
    tyear = parts[1] if len(parts) == 2 else ""
    cur.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', ?)",
        (tname,),
    )
    cur.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', ?)",
        (tyear,),
    )
    return semester


def test_hod_course_overview_merges_groups_and_instructor_filter(app, db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    sem = _set_term(cur)
    code = f"GO{uid}"[:12].upper()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (code, "قسم درجات", "Grades"),
    )
    dept_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (code,)).fetchone()[0])
    course = f"مقرر-نظرة-{uid}"
    cur.execute(
        "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (course, f"GO{uid[:4]}", dept_id),
    )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"أستاذ أ {uid}", dept_id),
    )
    inst_a = int(cur.lastrowid)
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"أستاذ ب {uid}", dept_id),
    )
    inst_b = int(cur.lastrowid)
    s_a, s_b = f"GA{uid}", f"GB{uid}"
    for sid, name in ((s_a, "طالب أ"), (s_b, "طالب ب")):
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id, enrollment_status) "
            "VALUES (?, ?, ?, 'active')",
            (sid, name, dept_id),
        )
        cur.execute(
            "INSERT INTO registrations (student_id, course_name, semester) VALUES (?, ?, ?)",
            (sid, course, sem),
        )
    section_ids = []
    for day, iid in (("الأحد", inst_a), ("الإثنين", inst_b)):
        cur.execute(
            """
            INSERT INTO schedule
              (course_name, day, time, room, instructor_id, semester, department_id)
            VALUES (?, ?, '08:00-10:00', '1', ?, ?, ?)
            """,
            (course, day, iid, sem, dept_id),
        )
        section_ids.append(int(cur.lastrowid))
    db_conn.commit()
    tg.setup_course_offering(
        db_conn,
        course_name=course,
        semester=sem,
        department_id=dept_id,
        group_kind="split",
        groups=[
            {"group_code": "A", "instructor_id": inst_a, "section_ids": [section_ids[0]]},
            {"group_code": "B", "instructor_id": inst_b, "section_ids": [section_ids[1]]},
        ],
    )
    groups = tg.list_teaching_groups(
        db_conn, semester=sem, department_id=dept_id, course_name=course
    )
    g_a = next(g for g in groups if g.get("group_code") == "A")
    g_b = next(g for g in groups if g.get("group_code") == "B")
    tg.assign_students_to_teaching_group(
        db_conn, teaching_group_id=int(g_a["id"]), student_ids=[s_a], action="assign"
    )
    tg.assign_students_to_teaching_group(
        db_conn, teaching_group_id=int(g_b["id"]), student_ids=[s_b], action="assign"
    )

    # مسودتان مرسلتان
    for tgid, iid, sid, cw, md, sec in (
        (int(g_a["id"]), inst_a, s_a, 8, 25, section_ids[0]),
        (int(g_b["id"]), inst_b, s_b, 9, 27, section_ids[1]),
    ):
        cur.execute(
            """
            INSERT INTO grade_drafts
              (semester, course_name, section_id, teaching_group_id, instructor_id,
               draft_phase, status, submitted_at)
            VALUES (?, ?, ?, ?, ?, 'partial', 'Submitted', datetime('now'))
            """,
            (sem, course, sec, tgid, iid),
        )
        did = int(
            cur.execute(
                "SELECT id FROM grade_drafts WHERE course_name=? AND teaching_group_id=? ORDER BY id DESC LIMIT 1",
                (course, tgid),
            ).fetchone()[0]
        )
        cur.execute(
            """
            INSERT INTO grade_draft_items
              (draft_id, student_id, coursework, midterm, computed_total)
            VALUES (?, ?, ?, ?, ?)
            """,
            (did, sid, cw, md, float(cw) + float(md)),
        )
    pw = cur.execute(
        "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
    ).fetchone()[0]
    head = f"head_go_{uid}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) "
        "VALUES (?, ?, 'head_of_department', ?)",
        (head, pw, dept_id),
    )
    db_conn.commit()

    with app.test_client() as c:
        assert c.post(
            "/auth/login", json={"username": head, "password": "TestP@ssw0rd!"}
        ).status_code == 200

        pending_all = c.get("/grades/drafts/pending")
        assert pending_all.status_code == 200
        pend = (pending_all.get_json() or {}).get("pending") or []
        mine = [p for p in pend if p.get("course_name") == course]
        assert len(mine) >= 2

        pending_a = c.get(f"/grades/drafts/pending?instructor_id={inst_a}")
        assert pending_a.status_code == 200
        only_a = [
            p for p in (pending_a.get_json() or {}).get("pending") or []
            if p.get("course_name") == course
        ]
        assert only_a
        assert all(int(p.get("instructor_id") or 0) == inst_a for p in only_a)

        ov = c.get(f"/grades/drafts/course_overview?course_name={course}")
        assert ov.status_code == 200, ov.get_data(as_text=True)
        body = ov.get_json() or {}
        assert body.get("draft_count") >= 2
        sids = {s.get("student_id") for s in body.get("students") or []}
        assert s_a in sids and s_b in sids
        instructors = {s.get("instructor_name") for s in body.get("students") or []}
        assert any("أستاذ أ" in (n or "") for n in instructors)
        assert any("أستاذ ب" in (n or "") for n in instructors)
