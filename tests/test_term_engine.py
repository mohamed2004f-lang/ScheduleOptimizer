"""الموجة 0–1 لمحرّك الفصل: مفتاح موحّد، نوافذ، نسخ تقويم، وحارس الكتابة."""
from __future__ import annotations

from backend.database.database import TABLES_SCHEMA
from backend.services.term_engine import (
    VERSION_AMENDED,
    VERSION_PUBLISHED,
    WINDOW_CATALOG,
    canonical_term_key,
    ensure_term_engine_tables,
    normalize_academic_year,
    on_calendar_saved,
    parse_ops_term,
    snapshot_calendar_version,
    sync_current_term_from_settings,
    sync_windows_from_calendar_items,
    upsert_term_master,
)


def test_schema_includes_term_engine_tables():
    for name in (
        "term_master",
        "term_windows",
        "academic_calendar_versions",
        "term_course_offerings",
        "term_offering_state",
    ):
        assert name in TABLES_SCHEMA


def test_term_engine_guard_lives_beside_closure():
    import backend.services.term_engine as mod

    assert not hasattr(mod, "assert_term_writable")
    assert hasattr(mod, "assert_term_operation")


def test_normalize_year_and_ops_label():
    assert normalize_academic_year("25-26") == "2025/2026"
    assert normalize_academic_year("2025/2026") == "2025/2026"
    assert normalize_academic_year("44-45") == "2044/2045"
    parsed = parse_ops_term("خريف", "25-26")
    assert parsed["term_key"] == "fall:2025/2026"
    assert parsed["ops_label"] == "خريف 25-26"
    assert canonical_term_key("fall", "2025/2026") == "fall:2025/2026"


def test_sync_current_term_sets_is_current(db_conn):
    ensure_term_engine_tables(db_conn)
    row = sync_current_term_from_settings(db_conn, term_name="خريف", term_year="44-45")
    assert row["term_key"] == "fall:2044/2045"
    assert int(row["is_current"]) == 1
    assert row["ops_label"] == "خريف 44-45"
    other = upsert_term_master(
        db_conn,
        season="spring",
        academic_year="2044/2045",
        make_current=True,
    )
    assert other["term_key"] == "spring:2044/2045"
    assert int(other["is_current"]) == 1
    prev = db_conn.execute(
        "SELECT is_current FROM term_master WHERE term_key = ?",
        ("fall:2044/2045",),
    ).fetchone()
    assert int(prev[0] if not hasattr(prev, "keys") else prev["is_current"]) == 0


def test_windows_map_fall_item_numbers_and_duration(db_conn):
    ensure_term_engine_tables(db_conn)
    master = upsert_term_master(db_conn, season="fall", academic_year="2025/2026")
    items = [
        {"item_no": 1, "title": "تجديد القيد وتسجيل المقررات الدراسية (لمدة أسبوع)", "event_date": "2025-09-07"},
        {"item_no": 2, "title": "تسجيل الطلبة المستجدين (لمدة أسبوع)", "event_date": "2025-09-14"},
        {"item_no": 4, "title": "آخر موعد لإضافة المقررات الدراسية", "event_date": "2025-09-21"},
        {"item_no": 5, "title": "بداية الامتحانات الجزئية (التصفية)", "event_date": "2025-11-01"},
        {"item_no": 6, "title": "نهاية الامتحانات الجزئية (التصفية)", "event_date": "2025-11-12"},
        {"item_no": 7, "title": "آخر موعد لإسقاط المواد", "event_date": "2025-12-01"},
    ]
    sync_windows_from_calendar_items(
        db_conn, term_key=master["term_key"], season="fall", items=items
    )
    rows = {
        r["window_key"] if hasattr(r, "keys") else r[0]: r
        for r in db_conn.execute(
            "SELECT window_key, starts_at, ends_at, status, kind FROM term_windows WHERE term_key = ?",
            (master["term_key"],),
        ).fetchall()
    }

    def _val(row, key, idx):
        return row[key] if hasattr(row, "keys") else row[idx]

    renewal = rows["registration_renewal"]
    assert _val(renewal, "ends_at", 2) == "2025-09-07"
    assert _val(renewal, "starts_at", 1) == "2025-09-01"
    assert _val(renewal, "status", 3) == "scheduled"
    add = rows["add_courses"]
    assert _val(add, "ends_at", 2) == "2025-09-21"
    assert _val(add, "starts_at", 1) in (None, "")
    mid = rows["midterm_exams"]
    assert _val(mid, "starts_at", 1) == "2025-11-01"
    assert _val(mid, "ends_at", 2) == "2025-11-12"
    freeze = rows["schedule_freeze"]
    assert _val(freeze, "status", 3) == "unset"
    assert "registration_new" in rows
    catalog_keys = {s.window_key for s in WINDOW_CATALOG}
    assert "surveys" in catalog_keys


def test_spring_titles_include_new_students():
    from backend.services.academic_calendar import SPRING_TITLES

    assert SPRING_TITLES[1] == "تسجيل الطلبة المستجدين (لمدة أسبوع)"
    assert SPRING_TITLES[2] == "بداية الدراسة"


def test_migrate_spring_shifts_start_of_study(db_conn):
    from backend.services.term_engine import migrate_spring_new_students_item

    db_conn.execute(
        """
        INSERT INTO academic_calendar (academic_year, term, item_no, title, event_date, is_deleted, updated_at)
        VALUES
          ('2055/2056', 'spring', 1, 'تجديد القيد وتسجيل المقررات الدراسية (لمدة أسبوع)', '2056-03-10', 0, '2056-01-01T00:00:00Z'),
          ('2055/2056', 'spring', 2, 'بداية الدراسة', '2056-03-10', 0, '2056-01-01T00:00:00Z')
        """
    )
    db_conn.commit()
    assert migrate_spring_new_students_item(db_conn) == 1
    assert migrate_spring_new_students_item(db_conn) == 0
    row = db_conn.execute(
        "SELECT item_no, title FROM academic_calendar WHERE academic_year='2055/2056' AND term='spring' AND title LIKE '%بداية الدراسة%'"
    ).fetchone()
    no = row[0] if not hasattr(row, "keys") else row["item_no"]
    assert int(no) == 3


def test_windows_map_spring_new_students_duration(db_conn):
    ensure_term_engine_tables(db_conn)
    master = upsert_term_master(db_conn, season="spring", academic_year="2056/2057")
    items = [
        {"item_no": 1, "title": "تجديد القيد", "event_date": "2057-03-10"},
        {"item_no": 2, "title": "تسجيل الطلبة المستجدين (لمدة أسبوع)", "event_date": "2057-03-17"},
        {"item_no": 3, "title": "بداية الدراسة", "event_date": "2057-03-18"},
        {"item_no": 5, "title": "بداية الامتحانات الجزئية", "event_date": "2057-04-09"},
        {"item_no": 6, "title": "نهاية الامتحانات الجزئية", "event_date": "2057-05-09"},
    ]
    sync_windows_from_calendar_items(
        db_conn, term_key=master["term_key"], season="spring", items=items
    )
    row = db_conn.execute(
        "SELECT starts_at, ends_at FROM term_windows WHERE term_key = ? AND window_key = 'registration_new'",
        (master["term_key"],),
    ).fetchone()
    starts = row[0] if not hasattr(row, "keys") else row["starts_at"]
    ends = row[1] if not hasattr(row, "keys") else row["ends_at"]
    assert str(ends)[:10] == "2057-03-17"
    assert str(starts)[:10] == "2057-03-11"
    mid = db_conn.execute(
        "SELECT starts_at, ends_at FROM term_windows WHERE term_key = ? AND window_key = 'midterm_exams'",
        (master["term_key"],),
    ).fetchone()
    assert (mid[0] if not hasattr(mid, "keys") else mid["starts_at"]) == "2057-04-09"
    assert (mid[1] if not hasattr(mid, "keys") else mid["ends_at"]) == "2057-05-09"


def test_spring_includes_new_student_window(db_conn):
    ensure_term_engine_tables(db_conn)
    master = upsert_term_master(db_conn, season="spring", academic_year="2025/2026")
    sync_windows_from_calendar_items(
        db_conn,
        term_key=master["term_key"],
        season="spring",
        items=[{"item_no": 1, "title": "تجديد القيد", "event_date": "2026-02-01"}],
    )
    row = db_conn.execute(
        "SELECT status, starts_at, ends_at FROM term_windows WHERE term_key = ? AND window_key = 'registration_new'",
        (master["term_key"],),
    ).fetchone()
    assert row is not None
    status = row[0] if not hasattr(row, "keys") else row["status"]
    assert status == "unset"


def test_calendar_save_versions_published_then_amended(db_conn):
    ensure_term_engine_tables(db_conn)
    db_conn.execute(
        """
        INSERT INTO academic_calendar (academic_year, term, item_no, title, event_date, is_deleted, updated_at)
        VALUES ('2025/2026', 'fall', 1, 'تجديد القيد', '2025-09-07', 0, '2025-01-01T00:00:00Z')
        """
    )
    db_conn.commit()
    first = on_calendar_saved(db_conn, academic_year="2025/2026", season="fall", actor="admin-test")
    assert first["term_key"] == "fall:2025/2026"
    assert first["calendar_version"]["status"] == VERSION_PUBLISHED
    assert first["calendar_version"]["version_no"] == 1
    db_conn.execute(
        "UPDATE academic_calendar SET event_date = '2025-09-14' WHERE academic_year = '2025/2026' AND term = 'fall' AND item_no = 1"
    )
    db_conn.commit()
    second = on_calendar_saved(db_conn, academic_year="2025/2026", season="fall", actor="admin-test")
    assert second["calendar_version"]["status"] == VERSION_AMENDED
    assert second["calendar_version"]["version_no"] == 2
    n = db_conn.execute(
        "SELECT COUNT(*) FROM academic_calendar_versions WHERE term_key = 'fall:2025/2026'"
    ).fetchone()[0]
    assert int(n) == 2


def test_draft_version_is_updated_in_place(db_conn):
    ensure_term_engine_tables(db_conn)
    upsert_term_master(db_conn, season="fall", academic_year="2026/2027")
    snapshot_calendar_version(
        db_conn,
        term_key="fall:2026/2027",
        items=[{"item_no": 1, "title": "أ"}],
        actor="u",
        reason="seed",
    )
    db_conn.execute(
        "UPDATE academic_calendar_versions SET status = 'draft' WHERE term_key = 'fall:2026/2027'"
    )
    db_conn.commit()
    again = snapshot_calendar_version(
        db_conn,
        term_key="fall:2026/2027",
        items=[{"item_no": 1, "title": "ب"}],
        actor="u",
    )
    assert again["version_no"] == 1
    assert again["status"] == "draft"
    n = db_conn.execute(
        "SELECT COUNT(*) FROM academic_calendar_versions WHERE term_key = 'fall:2026/2027'"
    ).fetchone()[0]
    assert int(n) == 1


def test_calendar_get_payload_unchanged(auth_client):
    r = auth_client.get("/academic_calendar/items?academic_year=2025/2026&term=fall")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["academic_year"] == "2025/2026"
    assert body["term"] == "fall"
    assert "items" in body
    first = body["items"][0]
    assert {"item_no", "title", "event_date", "is_deleted", "updated_at", "is_custom"} <= set(first.keys())
    assert first["item_no"] == 1
    assert "تجديد القيد" in first["title"]


def test_duration_range_survives_edited_title():
    from backend.services.academic_calendar import assemble_calendar_items

    items = assemble_calendar_items(
        academic_year="2026/2027",
        term="fall",
        existing={
            1: {
                "title": "تجديد القيد وتسجيل المقررات الدراسية",
                "event_date": "2026-09-10",
                "event_date_start": "2026-09-01",
                "is_deleted": 0,
            },
            3: {"title": "بداية الدراسة", "event_date": "2026-09-12", "is_deleted": 0},
        },
    )
    by_no = {int(it["item_no"]): it for it in items}
    assert by_no[1]["needs_range"] is True
    assert by_no[1]["event_date_start"] == "2026-09-01"
    assert by_no[3]["needs_range"] is False
    assert by_no[3]["event_date"] == "2026-09-12"


def test_calendar_post_persists_dashed_year_and_reloads_slash(auth_client, db_conn):
    """حفظ بـ 2061-2062 يجب أن يظهر عند التحميل بـ 2061/2062."""
    r = auth_client.post(
        "/academic_calendar/items",
        json={
            "academic_year": "2061-2062",
            "term": "fall",
            "items": [
                {
                    "item_no": 1,
                    "title": "تجديد القيد وتسجيل المقررات الدراسية (لمدة أسبوع)",
                    "event_date": "2061-09-14",
                    "event_date_start": "2061-09-08",
                    "is_deleted": 0,
                },
                {
                    "item_no": 3,
                    "title": "بداية الدراسة",
                    "event_date": "2061-09-15",
                    "is_deleted": 0,
                },
            ],
        },
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["academic_year"] == "2061/2062"
    assert body["written"] >= 2
    posted = {int(it["item_no"]): it for it in body["items"]}
    assert posted[1]["event_date"] == "2061-09-14"
    assert posted[1].get("event_date_start") in (None, "2061-09-08") or str(
        posted[1].get("event_date_start") or ""
    ).startswith("2061-09-08")
    assert posted[3]["event_date"] == "2061-09-15"

    row = db_conn.execute(
        "SELECT event_date FROM academic_calendar WHERE academic_year='2061/2062' AND term='fall' AND item_no=1"
    ).fetchone()
    assert row is not None
    stored = row["event_date"] if hasattr(row, "keys") else row[0]
    assert str(stored)[:10] == "2061-09-14"

    g = auth_client.get("/academic_calendar/items?academic_year=2061/2062&term=fall")
    assert g.status_code == 200
    first = next(i for i in g.get_json()["items"] if i["item_no"] == 1)
    assert first["event_date"] == "2061-09-14"
    start = auth_client.get("/academic_calendar/items?academic_year=2061-2062&term=خريف")
    assert start.status_code == 200
    first2 = next(i for i in start.get_json()["items"] if i["item_no"] == 1)
    assert first2["event_date"] == "2061-09-14"


def test_calendar_post_does_not_require_preview_confirm(auth_client):
    r = auth_client.post(
        "/academic_calendar/items",
        json={
            "academic_year": "2063/2064",
            "term": "spring",
            "items": [
                {"item_no": 1, "title": "تجديد القيد", "event_date": "2064-02-10", "is_deleted": 0}
            ],
        },
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    first = next(i for i in r.get_json()["items"] if i["item_no"] == 1)
    assert first["event_date"] == "2064-02-10"


def test_calendar_rows_survive_ops_sync_rollback(auth_client, db_conn, monkeypatch):
    """حفظ الإعلان يُثبَّت حتى لو مزامنة التشغيل ألغت المعاملة."""

    def _boom(conn, **kwargs):
        conn.rollback()
        return None

    monkeypatch.setattr("backend.services.term_engine.on_calendar_saved", _boom)
    r = auth_client.post(
        "/academic_calendar/items",
        json={
            "academic_year": "2071/2072",
            "term": "fall",
            "items": [
                {
                    "item_no": 1,
                    "title": "تجديد القيد وتسجيل المقررات الدراسية (لمدة أسبوع)",
                    "event_date": "2071-09-10",
                    "event_date_start": "2071-09-01",
                    "is_deleted": 0,
                }
            ],
        },
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["status"] == "ok"
    first = next(i for i in body["items"] if i["item_no"] == 1)
    assert first["event_date"] == "2071-09-10"
    row = db_conn.execute(
        "SELECT event_date FROM academic_calendar WHERE academic_year='2071/2072' AND term='fall' AND item_no=1"
    ).fetchone()
    assert row is not None
    stored = row["event_date"] if hasattr(row, "keys") else row[0]
    assert str(stored)[:10] == "2071-09-10"
    g = auth_client.get("/academic_calendar/items?academic_year=2071/2072&term=fall")
    loaded = next(i for i in g.get_json()["items"] if i["item_no"] == 1)
    assert loaded["event_date"] == "2071-09-10"


def test_year_aliases_include_short_and_long():
    from backend.services.term_engine import academic_year_aliases

    aliases = academic_year_aliases("25-26")
    assert "25-26" in aliases
    assert "2025/2026" in aliases
    assert academic_year_aliases("2025/2026")[0] == "2025/2026"


def test_parse_slash_date():
    from backend.services.term_engine import _parse_date

    assert _parse_date("15/02/2026").isoformat() == "2026-02-15"
    assert _parse_date("2026-02-15").isoformat() == "2026-02-15"


def test_load_calendar_rows_by_year_alias(db_conn):
    from backend.services.term_engine import load_calendar_item_rows

    db_conn.execute(
        """
        INSERT INTO academic_calendar (academic_year, term, item_no, title, event_date, is_deleted, updated_at)
        VALUES ('48-49', 'spring', 1, 'تجديد القيد', '2049-02-08', 0, '2049-01-01T00:00:00Z')
        """
    )
    db_conn.commit()
    rows = load_calendar_item_rows(db_conn, "2048/2049", "spring")
    assert 1 in rows
    assert rows[1]["event_date"] == "2049-02-08"


def test_load_prefers_dated_alias_over_empty_canonical(db_conn):
    from backend.services.term_engine import load_calendar_item_rows

    db_conn.execute(
        """
        INSERT INTO academic_calendar (academic_year, term, item_no, title, event_date, is_deleted, updated_at)
        VALUES
          ('2058/2059', 'fall', 1, 'تجديد القيد', NULL, 0, '2058-01-01T00:00:00Z'),
          ('2058-2059', 'fall', 1, 'تجديد القيد', '2058-09-07', 0, '2058-01-02T00:00:00Z')
        """
    )
    db_conn.commit()
    rows = load_calendar_item_rows(db_conn, "2058/2059", "fall")
    assert str(rows[1]["event_date"])[:10] == "2058-09-07"


def test_calendar_get_normalizes_dashed_year(auth_client, db_conn):
    db_conn.execute(
        """
        INSERT INTO academic_calendar (academic_year, term, item_no, title, event_date, is_deleted, updated_at)
        VALUES ('2059-2060', 'fall', 1, 'تجديد القيد وتسجيل المقررات الدراسية (لمدة أسبوع)', '2059-09-14', 0, '2059-01-01T00:00:00Z')
        """
    )
    db_conn.commit()
    r = auth_client.get("/academic_calendar/items?academic_year=2059-2060&term=fall")
    assert r.status_code == 200
    body = r.get_json()
    assert body["academic_year"] == "2059/2060"
    first = next(it for it in body["items"] if it["item_no"] == 1)
    assert str(first["event_date"])[:10] == "2059-09-14"


def test_window_uses_explicit_start_date(db_conn):
    ensure_term_engine_tables(db_conn)
    master = upsert_term_master(db_conn, season="fall", academic_year="2060/2061")
    items = [
        {
            "item_no": 1,
            "title": "تجديد القيد وتسجيل المقررات الدراسية (لمدة أسبوع)",
            "event_date_start": "2060-09-01",
            "event_date": "2060-09-10",
        }
    ]
    sync_windows_from_calendar_items(
        db_conn, term_key=master["term_key"], season="fall", items=items
    )
    row = db_conn.execute(
        "SELECT starts_at, ends_at FROM term_windows WHERE term_key = ? AND window_key = 'registration_renewal'",
        (master["term_key"],),
    ).fetchone()
    starts = row[0] if not hasattr(row, "keys") else row["starts_at"]
    ends = row[1] if not hasattr(row, "keys") else row["ends_at"]
    assert str(starts)[:10] == "2060-09-01"
    assert str(ends)[:10] == "2060-09-10"


def test_hydrate_windows_from_short_year_calendar(db_conn):
    from backend.services.term_engine import hydrate_term_windows_from_calendar

    ensure_term_engine_tables(db_conn)
    db_conn.execute(
        """
        INSERT INTO academic_calendar (academic_year, term, item_no, title, event_date, is_deleted, updated_at)
        VALUES ('49-50', 'ربيع', 1, 'تجديد القيد وتسجيل المقررات الدراسية (لمدة أسبوع)', '2050-02-08', 0, '2050-01-01T00:00:00Z')
        """
    )
    db_conn.commit()
    out = hydrate_term_windows_from_calendar(
        db_conn,
        academic_year="2049/2050",
        season="spring",
        ops_label="ربيع 49-50",
        ops_year_label="49-50",
    )
    assert out["hydrated"] is True
    assert out["filled"] >= 1
    row = db_conn.execute(
        "SELECT starts_at, ends_at, status FROM term_windows WHERE term_key = 'spring:2049/2050' AND window_key = 'registration_renewal'"
    ).fetchone()
    assert row is not None
    ends = row["ends_at"] if hasattr(row, "keys") else row[1]
    assert str(ends)[:10] == "2050-02-08"


def test_calendar_get_finds_short_year_via_alias(auth_client, db_conn):
    db_conn.execute(
        """
        INSERT INTO academic_calendar (academic_year, term, item_no, title, event_date, is_deleted, updated_at)
        VALUES ('50-51', 'spring', 1, 'تجديد القيد', '2051-02-08', 0, '2051-01-01T00:00:00Z')
        """
    )
    db_conn.commit()
    r = auth_client.get("/academic_calendar/items?academic_year=2050/2051&term=spring")
    assert r.status_code == 200
    items = r.get_json()["items"]
    first = next(it for it in items if it["item_no"] == 1)
    assert first["event_date"] == "2051-02-08"


def _seed_op_window(conn, *, year: str, window_key: str, starts: str | None, ends: str | None):
    from backend.services.term_engine import WINDOW_SCHEDULED, WINDOW_UNSET

    master = upsert_term_master(conn, season="fall", academic_year=year)
    key = master["term_key"]
    status = WINDOW_SCHEDULED if (starts or ends) else WINDOW_UNSET
    conn.execute(
        "DELETE FROM term_windows WHERE term_key = ? AND window_key = ?",
        (key, window_key),
    )
    conn.execute(
        """
        INSERT INTO term_windows (
            term_key, window_key, kind, label_ar, closure_stage,
            starts_at, ends_at, status, source, updated_at
        ) VALUES (?, ?, 'window', ?, 'registrations', ?, ?, ?, 'test', '2026-01-01T00:00:00Z')
        """,
        (key, window_key, window_key, starts, ends, status),
    )
    conn.commit()
    return key


def test_guard_allows_when_windows_unset(db_conn):
    from backend.services.term_engine import OP_REGISTRATION_WRITE, assert_term_operation

    upsert_term_master(db_conn, season="fall", academic_year="2031/2032")
    assert_term_operation(
        db_conn,
        operation=OP_REGISTRATION_WRITE,
        semester="خريف 31-32",
        now=__import__("datetime").date(2026, 8, 16),
    )


def test_guard_blocks_past_window_not_stage(db_conn):
    import datetime

    import pytest

    from backend.services.term_engine import (
        CODE_WINDOW_CLOSED,
        OP_ADD_COURSE,
        TermOperationError,
        assert_term_operation,
    )

    _seed_op_window(
        db_conn,
        year="2032/2033",
        window_key="add_courses",
        starts=None,
        ends="2026-08-01",
    )
    with pytest.raises(TermOperationError) as excinfo:
        assert_term_operation(
            db_conn,
            operation=OP_ADD_COURSE,
            semester="خريف 32-33",
            now=datetime.date(2026, 8, 16),
        )
    assert excinfo.value.code == CODE_WINDOW_CLOSED
    assert excinfo.value.window_key == "add_courses"


def test_guard_allows_open_deadline_window(db_conn):
    import datetime

    from backend.services.term_engine import OP_ADD_COURSE, assert_term_operation

    _seed_op_window(
        db_conn,
        year="2033/2034",
        window_key="add_courses",
        starts=None,
        ends="2026-08-20",
    )
    assert_term_operation(
        db_conn,
        operation=OP_ADD_COURSE,
        semester="خريف 33-34",
        now=datetime.date(2026, 8, 16),
    )


def test_guard_stage_lock_beats_open_window(db_conn):
    import datetime

    import pytest

    from backend.services.term_closure import TermClosedError, close_term_stage
    from backend.services.term_engine import OP_REGISTRATION_WRITE, assert_term_operation

    _seed_op_window(
        db_conn,
        year="2034/2035",
        window_key="registration_renewal",
        starts="2026-08-01",
        ends="2026-08-31",
    )
    close_term_stage(
        db_conn,
        stage="registrations",
        semester="خريف 34-35",
        department_id=None,
        actor="pytest",
        build_archive=False,
    )
    with pytest.raises(TermClosedError):
        assert_term_operation(
            db_conn,
            operation=OP_REGISTRATION_WRITE,
            semester="خريف 34-35",
            now=datetime.date(2026, 8, 16),
        )


def test_guard_unparseable_semester_skips_windows(db_conn):
    from backend.services.term_engine import OP_ADD_COURSE, assert_term_operation

    assert_term_operation(
        db_conn,
        operation=OP_ADD_COURSE,
        semester="اختبار",
        now=__import__("datetime").date(2026, 8, 16),
    )


def test_add_request_http_423_when_window_closed(student_auth_client, db_conn):
    import datetime

    from backend.services.term_engine import (
        OP_ADD_COURSE,
        assert_term_operation,
    )

    _seed_op_window(
        db_conn,
        year="2035/2036",
        window_key="add_courses",
        starts=None,
        ends="2020-01-01",
    )
    r = student_auth_client.post(
        "/registration_requests/create",
        json={
            "student_id": "S001",
            "term": "خريف 35-36",
            "course_name": "رياضيات 1",
            "action": "add",
            "reason": "wave1",
        },
    )
    assert r.status_code == 423
    body = r.get_json()
    assert body["code"] == "term_window_closed"
    assert body["operation"] == OP_ADD_COURSE
    import pytest
    from backend.services.term_engine import TermOperationError

    with pytest.raises(TermOperationError):
        assert_term_operation(
            db_conn,
            operation=OP_ADD_COURSE,
            semester="خريف 35-36",
            now=datetime.date(2026, 8, 16),
        )


def test_guard_or_windows_any_open_allows(db_conn):
    import datetime

    from backend.services.term_engine import OP_ADD_COURSE, assert_term_operation

    _seed_op_window(
        db_conn,
        year="2038/2039",
        window_key="add_courses",
        starts=None,
        ends="2020-01-01",
    )
    _seed_op_window(
        db_conn,
        year="2038/2039",
        window_key="registration_renewal",
        starts="2026-08-01",
        ends="2026-08-31",
    )
    assert_term_operation(
        db_conn,
        operation=OP_ADD_COURSE,
        semester="خريف 38-39",
        now=datetime.date(2026, 8, 16),
    )


def test_guard_closed_term_master_blocks(db_conn):
    import pytest

    from backend.services.term_engine import (
        CODE_TERM_CLOSED,
        OP_REGISTRATION_WRITE,
        TermOperationError,
        assert_term_operation,
    )

    master = upsert_term_master(db_conn, season="fall", academic_year="2039/2040")
    db_conn.execute(
        "UPDATE term_master SET status = 'closed' WHERE term_key = ?",
        (master["term_key"],),
    )
    db_conn.commit()
    with pytest.raises(TermOperationError) as excinfo:
        assert_term_operation(
            db_conn,
            operation=OP_REGISTRATION_WRITE,
            semester="خريف 39-40",
        )
    assert excinfo.value.code == CODE_TERM_CLOSED


def test_save_registrations_http_423_when_stage_closed(auth_client, db_conn):
    from backend.services.term_closure import close_term_stage, reopen_term_stage

    sem = "خريف 44-45"
    close_term_stage(
        db_conn,
        stage="registrations",
        semester=sem,
        department_id=None,
        actor="pytest",
        build_archive=False,
    )
    try:
        r = auth_client.post(
            "/students/save_registrations",
            json={
                "student_id": "S001",
                "courses": ["رياضيات 1", "فيزياء 1", "كيمياء 1"],
                "override_reason": "wave1-lock",
            },
        )
        assert r.status_code == 423
        body = r.get_json()
        assert body["code"] == "term_closed"
    finally:
        reopen_term_stage(
            db_conn,
            stage="registrations",
            semester=sem,
            department_id=None,
            actor="pytest",
            reason="إعادة فتح بعد اختبار الموجة 1",
        )


def test_approve_plan_http_423_when_stage_closed(auth_client, db_conn):
    from backend.services.term_closure import close_term_stage

    cur = db_conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS enrollment_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            semester TEXT NOT NULL,
            status TEXT NOT NULL,
            rejection_reason TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS enrollment_plan_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            course_name TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        INSERT INTO enrollment_plans (student_id, semester, status, created_at, updated_at)
        VALUES ('S001', 'خريف 36-37', 'Pending', '2026-01-01', '2026-01-01')
        """
    )
    plan_id = int(cur.lastrowid)
    cur.execute(
        "INSERT INTO enrollment_plan_items (plan_id, course_name) VALUES (?, 'رياضيات 1')",
        (plan_id,),
    )
    db_conn.commit()
    close_term_stage(
        db_conn,
        stage="registrations",
        semester="خريف 36-37",
        department_id=None,
        actor="pytest",
        build_archive=False,
    )
    r = auth_client.post(f"/enrollment/plans/{plan_id}/approve")
    assert r.status_code == 423
    body = r.get_json()
    assert body["code"] == "term_closed"
    assert "مغلق" in (body.get("message") or "")
