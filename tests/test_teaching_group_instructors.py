# -*- coding: utf-8 -*-
"""فريق التدريس: رئيسي + مساعدون على teaching_groups."""
import uuid

from backend.services import teaching_groups as tg


def _seed_group(db_conn):
    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"TI{uid}".upper()[:12], f"قسم {uid}", "TI"),
    )
    dept_id = cur.execute(
        "SELECT id FROM departments WHERE code = ?", (f"TI{uid}".upper()[:12],)
    ).fetchone()[0]
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (f"مقرر فريق {uid}", f"T{uid}"[:8], dept_id),
    )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"رئيسي {uid}", dept_id),
    )
    primary_id = int(cur.lastrowid)
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"مساعد {uid}", dept_id),
    )
    asst_id = int(cur.lastrowid)
    db_conn.commit()
    rec = tg.create_teaching_group(
        db_conn,
        course_name=f"مقرر فريق {uid}",
        semester="خريف 44-45",
        department_id=dept_id,
        instructor_id=primary_id,
    )
    return {
        "group_id": int(rec["id"]),
        "primary_id": primary_id,
        "asst_id": asst_id,
        "course": f"مقرر فريق {uid}",
        "dept_id": dept_id,
        "uid": uid,
    }


def test_set_group_instructors_primary_and_assistant(db_conn):
    seed = _seed_group(db_conn)
    team = tg.set_group_instructors(
        db_conn,
        seed["group_id"],
        primary_instructor_id=seed["primary_id"],
        assistant_ids=[seed["asst_id"]],
    )
    assert len(team) == 2
    roles = {m["role"] for m in team}
    assert roles == {"primary", "assistant"}
    g = tg.get_teaching_group(db_conn, seed["group_id"])
    assert int(g["instructor_id"]) == seed["primary_id"]
    assert seed["asst_id"] in (g.get("assistant_instructor_ids") or [])
    assert "مساعد" in (g.get("instructors_display") or "")


def test_assistant_sees_assigned_group(db_conn):
    seed = _seed_group(db_conn)
    tg.set_group_instructors(
        db_conn,
        seed["group_id"],
        primary_instructor_id=seed["primary_id"],
        assistant_ids=[seed["asst_id"]],
    )
    rows = tg.list_instructor_assigned_groups(db_conn, seed["asst_id"], "خريف 44-45")
    assert any(int(r.get("teaching_group_id") or 0) == seed["group_id"] for r in rows)
    mine = next(r for r in rows if int(r.get("teaching_group_id") or 0) == seed["group_id"])
    assert mine.get("instructor_role") == "assistant"


def test_format_instructors_display():
    assert tg.format_instructors_display("أحمد", ["سارة"]) == "أحمد + مساعد: سارة"
    assert tg.format_instructors_display("أحمد", []) == "أحمد"


def test_enrich_schedule_rows_instructor_team(db_conn):
    seed = _seed_group(db_conn)
    tg.set_group_instructors(
        db_conn,
        seed["group_id"],
        primary_instructor_id=seed["primary_id"],
        assistant_ids=[seed["asst_id"]],
    )
    rows = [
        {
            "teaching_group_id": seed["group_id"],
            "instructor": "قديم",
            "course_name": "x",
        }
    ]
    tg.enrich_schedule_rows_instructor_team(db_conn, rows)
    assert rows[0]["instructor_primary"]
    assert len(rows[0].get("assistant_names") or []) == 1
    assert " + مساعد:" not in (rows[0].get("instructor") or "")
    assert "مساعد" in (rows[0].get("instructor_display") or "")


def test_instructors_api(auth_client, db_conn):
    seed = _seed_group(db_conn)
    r = auth_client.put(
        f"/schedule/teaching_groups/{seed['group_id']}/instructors",
        json={
            "primary_instructor_id": seed["primary_id"],
            "assistant_ids": [seed["asst_id"]],
        },
    )
    assert r.status_code == 200, r.data
    body = r.get_json()
    assert body.get("status") == "ok"
    assert len(body.get("instructors") or []) == 2
    g = auth_client.get(f"/schedule/teaching_groups/{seed['group_id']}/instructors")
    assert g.status_code == 200
    assert len((g.get_json() or {}).get("instructors") or []) == 2
