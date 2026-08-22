"""أرشيف نسخ الجدول: لقطة v2، تطبيع أوقات، حذف غير الصالح، وتصدير PDF."""
from __future__ import annotations

import json

from backend.services.schedule import (
    SCHEDULE_SNAPSHOT_SCHEMA_VERSION,
    _build_schedule_version_view,
    _canonical_time_slot_label,
    _create_schedule_version,
    _ensure_schedule_version_tables,
    _snapshot_rows_look_corrupted,
    _snapshot_usability,
)


def _seed_schedule_row(db_conn, *, course="ميكانيكا", day="الأحد", time="09:00-11:00"):
    cur = db_conn.cursor()
    _ensure_schedule_version_tables(cur)
    cur.execute("DELETE FROM schedule")
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, instructor_id, semester)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (course, day, time, "101", "د. أحمد", 42, "خريف 44-45"),
    )
    db_conn.commit()


def test_canonical_time_slot_swaps_reversed_range():
    assert _canonical_time_slot_label("13:00-09:00") == "09:00-13:00"
    assert _canonical_time_slot_label("09:00-13:00") == "09:00-13:00"
    assert _canonical_time_slot_label("15:00-13:00") == "13:00-15:00"


def test_create_schedule_version_snapshot_v2(app, db_conn):
    _seed_schedule_row(db_conn)
    with app.test_request_context():
        ver = _create_schedule_version(db_conn, event_type="manual", note="unit test")
    assert ver.get("id")
    row = db_conn.execute(
        "SELECT snapshot_json FROM schedule_versions WHERE id = ?",
        (int(ver["id"]),),
    ).fetchone()
    snap = json.loads(row[0])
    assert snap["schema_version"] == SCHEDULE_SNAPSHOT_SCHEMA_VERSION
    assert isinstance(snap.get("time_slots"), list) and snap["time_slots"]
    assert snap.get("term_key")
    first = snap["rows"][0]
    assert first["instructor_id"] == 42
    assert first["course_name"] == "ميكانيكا"
    assert first["day"] == "الأحد"
    assert first["time"] == "09:00-11:00"
    assert first["course_name"] != first["semester"]


def test_create_version_normalizes_reversed_times(app, db_conn):
    _seed_schedule_row(db_conn, course="انتقال", time="13:00-09:00")
    with app.test_request_context():
        ver = _create_schedule_version(db_conn, event_type="manual", note="normalize")
    row = db_conn.execute(
        "SELECT snapshot_json FROM schedule_versions WHERE id = ?",
        (int(ver["id"]),),
    ).fetchone()
    snap = json.loads(row[0])
    assert snap["rows"][0]["time"] == "09:00-13:00"
    assert "09:00-13:00" in snap["time_slots"]
    live = db_conn.execute("SELECT time FROM schedule LIMIT 1").fetchone()
    assert (live[0] if not hasattr(live, "keys") else live["time"]) == "09:00-13:00"


def test_snapshot_rows_look_corrupted_detects_pg_coalesce_bug():
    rows = [
        {
            "course_name": "ربيع 25-26",
            "day": "ربيع 25-26",
            "time": "ربيع 25-26",
            "instructor": "ربيع 25-26",
            "semester": "ربيع 25-26",
        }
    ] * 5
    assert _snapshot_rows_look_corrupted(rows)
    assert _snapshot_usability({"rows": rows, "semester": "ربيع 25-26"})["usable"] is False


def test_build_schedule_version_view_filters_bad_time(db_conn):
    snap = {
        "schema_version": 2,
        "semester": "خريف 44-45",
        "time_slots": ["09:00-11:00", "11:00-12:00"],
        "rows": [
            {
                "course_name": "صحيح",
                "day": "الأحد",
                "time": "09:00-11:00",
                "room": "101",
                "instructor": "د. أ",
                "semester": "خريف 44-45",
            },
            {
                "course_name": "اسم فصل كوقت",
                "day": "الإثنين",
                "time": "خريف 44-45",
                "room": "102",
                "instructor": "د. ب",
                "semester": "خريف 44-45",
            },
        ],
    }
    built = _build_schedule_version_view(db_conn, snap)
    assert len(built["list_rows"]) == 2
    assert built["list_rows"][1]["time"] == ""
    assert len(built["matrix"]["الأحد"]["09:00-11:00"]) == 1
    assert built["matrix_row_count"] == 1
    assert "09:00-11:00" in built["columns"]
    assert built["usable"] is True


def test_archive_view_does_not_need_current_settings(db_conn):
    """معاينة الأرشيف تعتمد على اللقطة فقط وليس إعدادات الفصل الحالية."""
    snap = {
        "schema_version": 1,
        "semester": "ربيع 25-26",
        "rows": [
            {
                "course_name": "كيمياء",
                "day": "السبت",
                "time": "13:00-09:00",
                "room": "5",
                "instructor": "أ. حمد",
                "semester": "ربيع 25-26",
            }
        ],
    }
    built = _build_schedule_version_view(db_conn, snap)
    assert built["usable"] is True
    assert "09:00-13:00" in built["columns"]
    assert built["matrix"]["السبت"]["09:00-13:00"][0]["course_name"] == "كيمياء"


def test_schedule_version_preview_html_grid(auth_client, db_conn):
    _seed_schedule_row(db_conn, course="ديناميكا")
    with auth_client.application.test_request_context():
        ver = _create_schedule_version(db_conn, event_type="manual", note="preview test")
    vid = int(ver["id"])
    resp = auth_client.get(f"/schedule/versions/{vid}")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    html = resp.get_data(as_text=True)
    assert "timetable--cols3" in html
    assert "ديناميكا" in html
    assert "tab-list" in html
    assert "د. أحمد" in html


def test_schedule_version_pdf_route(auth_client, db_conn):
    _seed_schedule_row(db_conn, course="موائع")
    with auth_client.application.test_request_context():
        ver = _create_schedule_version(db_conn, event_type="manual", note="pdf test")
    vid = int(ver["id"])
    resp = auth_client.get(f"/schedule/versions/{vid}/pdf")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.mimetype in ("application/pdf", "application/octet-stream")
    assert len(resp.data) > 500


def test_delete_and_purge_unusable_versions(auth_client, db_conn):
    _ensure_schedule_version_tables(db_conn.cursor())
    # نسخة صالحة
    _seed_schedule_row(db_conn, course="صالحة")
    with auth_client.application.test_request_context():
        good = _create_schedule_version(db_conn, event_type="manual", note="good")
    # نسخة تالفة يدوياً
    bad_snap = {
        "semester": "خريف 44-45",
        "rows": [
            {
                "course_name": "خريف 44-45",
                "day": "خريف 44-45",
                "time": "خريف 44-45",
                "instructor": "خريف 44-45",
                "semester": "خريف 44-45",
            }
        ]
        * 4,
    }
    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT INTO schedule_versions
        (semester, version_no, snapshot_json, generated_at, generated_by, note, is_published)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("خريف 44-45", 99001, json.dumps(bad_snap, ensure_ascii=False), "2026-01-01", "t", "bad", 0),
    )
    db_conn.commit()
    bad_id = int(cur.lastrowid or 0)
    if not bad_id:
        row = cur.execute(
            "SELECT id FROM schedule_versions WHERE version_no = 99001 LIMIT 1"
        ).fetchone()
        bad_id = int(row[0])

    # حذف واحد
    empty_id_row = cur.execute(
        """
        INSERT INTO schedule_versions
        (semester, version_no, snapshot_json, generated_at, generated_by, note, is_published)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "خريف 44-45",
            99002,
            json.dumps({"semester": "خريف 44-45", "rows": [{"course_name": "x", "day": "السبت", "time": "", "instructor": ""}]}, ensure_ascii=False),
            "2026-01-02",
            "t",
            "empty",
            0,
        ),
    )
    db_conn.commit()
    empty_id = int(cur.lastrowid or 0)
    if not empty_id:
        empty_id = int(
            cur.execute("SELECT id FROM schedule_versions WHERE version_no = 99002").fetchone()[0]
        )

    r_del = auth_client.delete(f"/schedule/versions/{empty_id}")
    assert r_del.status_code == 200, r_del.get_data(as_text=True)
    assert (
        cur.execute("SELECT COUNT(*) FROM schedule_versions WHERE id = ?", (empty_id,)).fetchone()[0]
        == 0
    )

    r_purge = auth_client.post(
        "/schedule/versions/purge_unusable",
        json={"semester": "خريف 44-45"},
    )
    assert r_purge.status_code == 200, r_purge.get_data(as_text=True)
    body = r_purge.get_json()
    assert body["deleted_count"] >= 1
    assert (
        cur.execute("SELECT COUNT(*) FROM schedule_versions WHERE id = ?", (bad_id,)).fetchone()[0]
        == 0
    )
    # الصالحة تبقى
    assert (
        cur.execute(
            "SELECT COUNT(*) FROM schedule_versions WHERE id = ?", (int(good["id"]),)
        ).fetchone()[0]
        == 1
    )

    lst = auth_client.get("/schedule/versions?semester=خريف 44-45")
    assert lst.status_code == 200
    items = lst.get_json().get("items") or []
    assert any(int(it["id"]) == int(good["id"]) and it.get("usable") for it in items)
