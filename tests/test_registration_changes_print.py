"""اختبارات طباعة/إخفاء سجل الإضافة والإسقاط."""
from __future__ import annotations


def _seed_change(
    conn,
    *,
    student_id="S001",
    student_name="طالب أول",
    action="add",
    course="رياضيات 1",
    code="MATH101",
    hidden=0,
    reason="",
    action_time="2025-09-10 10:00:00",
):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO registration_changes_log
          (student_id, student_name, term, course_name, course_code, units,
           action, action_phase, action_time, performed_by, reason, notes, is_hidden)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            student_id,
            student_name,
            "2025-Fall",
            course,
            code,
            3,
            action,
            "add_drop",
            action_time,
            "admin-test",
            reason,
            "",
            hidden,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def test_registration_changes_hides_by_default(auth_client, db_conn):
    visible_id = _seed_change(db_conn, course="رياضيات 1", reason="visible-row", hidden=0)
    hidden_id = _seed_change(db_conn, course="فيزياء 1", action="drop", reason="hidden-row", hidden=1)

    r = auth_client.get("/students/registration_changes_report")
    assert r.status_code == 200
    items = r.get_json()["items"]
    ids = {it["id"] for it in items}
    assert visible_id in ids
    assert hidden_id not in ids

    r2 = auth_client.get("/students/registration_changes_report?include_hidden=1")
    assert r2.status_code == 200
    ids2 = {it["id"] for it in r2.get_json()["items"]}
    assert visible_id in ids2
    assert hidden_id in ids2


def test_registration_changes_hide_and_delete_selected(auth_client, db_conn):
    id_a = _seed_change(db_conn, course="رياضيات 1", reason="to-hide")
    id_b = _seed_change(db_conn, course="فيزياء 1", action="drop", reason="to-delete")

    r = auth_client.post(
        "/students/registration_changes_report/hide",
        json={"ids": [id_a], "hidden": True},
    )
    assert r.status_code == 200
    assert r.get_json()["updated"] >= 1

    listed = auth_client.get("/students/registration_changes_report").get_json()["items"]
    assert id_a not in {it["id"] for it in listed}

    r_del = auth_client.post(
        "/students/registration_changes_report/delete",
        json={"ids": [id_b]},
    )
    assert r_del.status_code == 200
    assert r_del.get_json()["deleted"] >= 1


def test_print_form_requires_single_student(auth_client, db_conn):
    id_add = _seed_change(db_conn, course="رياضيات 1", action="add", reason="PRINT-ADD-ONLY")
    r = auth_client.post(
        "/students/registration_changes_report/print_form",
        json={"ids": [id_add], "form_type": "add"},
    )
    assert r.status_code == 400


def test_print_add_form_selected_only(auth_client, db_conn):
    id_add = _seed_change(db_conn, course="رياضيات 1", action="add", reason="PRINT-ADD-ONLY")
    id_drop = _seed_change(db_conn, course="فيزياء 1", action="drop", reason="PRINT-DROP-ONLY")
    _seed_change(db_conn, course="كيمياء 1", code="CHEM101", action="add", reason="PRINT-EXCLUDED")

    r = auth_client.post(
        "/students/registration_changes_report/print_form",
        json={
            "student_id": "S001",
            "form_type": "add",
            "ids": [id_add, id_drop],
        },
    )
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "نموذج إضافة مقررات" in html
    assert "PRINT-ADD-ONLY" in html
    assert "PRINT-DROP-ONLY" not in html
    assert "PRINT-EXCLUDED" not in html
    assert "طالب أول" in html


def test_print_final_hides_technical_notes_and_formats_time(auth_client, db_conn):
    id_add = _seed_change(
        db_conn,
        course="رياضيات 1",
        action="add",
        reason="bulk_save",
        action_time="2026-04-25T07:37:56.010235",
    )
    id_drop = _seed_change(
        db_conn,
        course="فيزياء 1",
        action="drop",
        reason="سبب رسمي للطباعة",
    )

    r = auth_client.post(
        "/students/registration_changes_report/print_form",
        json={
            "student_id": "S001",
            "form_type": "final",
            "ids": [id_add, id_drop],
        },
    )
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "نموذج نهائي" in html
    assert "bulk_save" not in html
    assert "سبب رسمي للطباعة" in html
    assert "2026-04-25 07:37" in html
    assert "07:37:56" not in html


def test_print_visible_for_student_without_ids(auth_client, db_conn):
    _seed_change(db_conn, course="رياضيات 1", action="add", reason="VIS-ADD")
    _seed_change(db_conn, course="فيزياء 1", action="drop", reason="VIS-DROP")

    r = auth_client.post(
        "/students/registration_changes_report/print_form",
        json={"student_id": "S001", "form_type": "drop"},
    )
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "نموذج إسقاط مقررات" in html
    assert "VIS-DROP" in html
    assert "VIS-ADD" not in html
