"""اختبارات مجموعات التدريس — المرحلة 1."""
import uuid

from backend.services import teaching_groups as tg


def _seed_dept_course_schedule(db_conn, *, course="ميكانيكا II", semester="خريف 44-45", slots=None):
    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"TG{uid}".upper()[:12], f"قسم {uid}", "TG"),
    )
    dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (f"TG{uid}".upper()[:12],)).fetchone()[0]
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (course, f"C{uid}"[:8], dept_id),
    )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"د. {uid}", dept_id),
    )
    inst_id = int(cur.lastrowid)
    slots = slots or [
        ("الأحد", "08:00-10:00", "101"),
        ("الأربعاء", "10:00-12:00", "102"),
    ]
    section_ids = []
    for day, time, room in slots:
        cur.execute(
            """
            INSERT INTO schedule (course_name, day, time, room, instructor, instructor_id, semester, department_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (course, day, time, room, f"د. {uid}", inst_id, semester, dept_id),
        )
        section_ids.append(int(cur.lastrowid))
    try:
        cur.execute("UPDATE schedule SET id = rowid WHERE id IS NULL")
    except Exception:
        pass
    db_conn.commit()
    return {"dept_id": dept_id, "inst_id": inst_id, "section_ids": section_ids, "course": course, "semester": semester}


class TestTeachingGroupsService:
    def test_backfill_single_group_links_all_lectures(self, db_conn):
        seed = _seed_dept_course_schedule(db_conn)
        stats = tg.backfill_teaching_groups_for_semester(
            db_conn, semester=seed["semester"], department_id=seed["dept_id"]
        )
        assert stats["created"] >= 1
        assert stats["linked"] >= 2

        groups = tg.list_teaching_groups(db_conn, semester=seed["semester"], department_id=seed["dept_id"])
        assert len(groups) == 1
        assert groups[0]["group_kind"] == "single"
        assert groups[0]["group_code_label"] == "الكل"

        linked = tg.list_linked_section_ids(db_conn, int(groups[0]["id"]))
        assert len(linked) == 2

        cur = db_conn.cursor()
        for sid in seed["section_ids"]:
            row = cur.execute(
                "SELECT teaching_group_id FROM schedule WHERE rowid = ? OR id = ?",
                (sid, sid),
            ).fetchone()
            assert int(row[0]) == int(groups[0]["id"])

    def test_setup_split_creates_two_groups(self, db_conn):
        seed = _seed_dept_course_schedule(db_conn)
        sids = seed["section_ids"]
        saved = tg.setup_course_offering(
            db_conn,
            course_name=seed["course"],
            semester=seed["semester"],
            department_id=seed["dept_id"],
            group_kind="split",
            groups=[
                {"group_code": "A", "instructor_id": seed["inst_id"], "section_ids": [sids[0]]},
                {"group_code": "B", "instructor_id": seed["inst_id"], "section_ids": [sids[1]]},
            ],
        )
        assert len(saved) == 2
        codes = sorted(g.get("group_code") for g in saved)
        assert codes == ["A", "B"]

    def test_audit_reports_unlinked_before_backfill(self, db_conn):
        seed = _seed_dept_course_schedule(db_conn)
        audit = tg.audit_teaching_groups(db_conn, semester=seed["semester"], department_id=seed["dept_id"])
        assert audit["unlinked_count"] == 2
        tg.backfill_teaching_groups_for_semester(db_conn, semester=seed["semester"], department_id=seed["dept_id"])
        audit2 = tg.audit_teaching_groups(db_conn, semester=seed["semester"], department_id=seed["dept_id"])
        assert audit2["unlinked_count"] == 0


class TestTeachingGroupsApi:
    def test_setup_page_requires_auth(self, app):
        with app.test_client() as c:
            r = c.get("/schedule_teaching_groups")
            assert r.status_code in (302, 401, 403)

    def test_backfill_api(self, auth_client, db_conn):
        seed = _seed_dept_course_schedule(db_conn)
        r = auth_client.post(
            "/schedule/teaching_groups/backfill",
            json={"semester": seed["semester"]},
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200
        j = r.get_json()
        assert j["status"] == "ok"
        assert j["stats"]["created"] >= 1

    def test_list_schedule_rows_includes_teaching_group_label(self, auth_client, db_conn):
        seed = _seed_dept_course_schedule(db_conn)
        tg.backfill_teaching_groups_for_semester(db_conn, semester=seed["semester"], department_id=seed["dept_id"])
        r = auth_client.get("/schedule/list_schedule_rows")
        assert r.status_code == 200
        rows = r.get_json()
        mine = [x for x in rows if x.get("course_name") == seed["course"]]
        assert mine
        assert mine[0].get("teaching_group_id")
        assert mine[0].get("teaching_group_label")

    def test_setup_list_api(self, auth_client, db_conn):
        seed = _seed_dept_course_schedule(db_conn)
        r = auth_client.get(f"/schedule/teaching_groups/setup?semester={seed['semester']}")
        assert r.status_code == 200
        j = r.get_json()
        assert j["status"] == "ok"
        names = [o["course_name"] for o in j.get("offerings") or []]
        assert seed["course"] in names
