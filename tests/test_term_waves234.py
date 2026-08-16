"""الموجات 2–4: سياسة المواعيد، السلة، لوحة التشغيل."""
from __future__ import annotations

import datetime

from backend.services.term_engine import (
    OP_ADD_COURSE,
    WINDOW_SCHEDULED,
    assert_term_operation,
    ensure_term_engine_tables,
    upsert_term_master,
)
from backend.services.term_policy import (
    EFFECT_CALENDAR_ONLY,
    EFFECT_EXTEND,
    EFFECT_IMMEDIATE_CLOSE,
    EFFECT_REJECT,
    EFFECT_REOPEN,
    apply_calendar_amendment,
    apply_window_dates,
    classify_window_change,
    preview_calendar_amendment,
)
from backend.services.term_basket import (
    CODE_BASKET_BLOCKED,
    BasketSwitchBlocked,
    archive_live_basket,
    assert_current_term_switch_allowed,
    unmigrated_students,
)


def test_classify_extend_open():
    today = datetime.date(2026, 8, 16)
    assert (
        classify_window_change(
            old_starts="2026-08-01",
            old_ends="2026-08-20",
            new_starts="2026-08-01",
            new_ends="2026-08-27",
            today=today,
            stage_closed=False,
            later_started=False,
        )
        == EFFECT_EXTEND
    )


def test_classify_locked_stage_is_calendar_only():
    today = datetime.date(2026, 8, 16)
    assert (
        classify_window_change(
            old_starts="2026-08-01",
            old_ends="2026-08-10",
            new_starts="2026-08-01",
            new_ends="2026-08-27",
            today=today,
            stage_closed=True,
            later_started=False,
        )
        == EFFECT_CALENDAR_ONLY
    )


def test_classify_reopen_after_later_stage_rejected():
    today = datetime.date(2026, 8, 16)
    assert (
        classify_window_change(
            old_starts=None,
            old_ends="2026-08-01",
            new_starts=None,
            new_ends="2026-08-31",
            today=today,
            stage_closed=False,
            later_started=True,
            old_status=WINDOW_SCHEDULED,
        )
        == EFFECT_REJECT
    )


def test_classify_immediate_close():
    today = datetime.date(2026, 8, 16)
    assert (
        classify_window_change(
            old_starts=None,
            old_ends="2026-08-31",
            new_starts=None,
            new_ends="2026-08-15",
            today=today,
            stage_closed=False,
            later_started=False,
            old_status=WINDOW_SCHEDULED,
        )
        == EFFECT_IMMEDIATE_CLOSE
    )


def test_classify_reopen_when_stage_open(db_conn):
    today = datetime.date(2026, 8, 16)
    assert (
        classify_window_change(
            old_starts=None,
            old_ends="2026-08-01",
            new_starts=None,
            new_ends="2026-08-31",
            today=today,
            stage_closed=False,
            later_started=False,
            old_status=WINDOW_SCHEDULED,
        )
        == EFFECT_REOPEN
    )


def test_locked_stage_save_does_not_reopen_window(db_conn):
    from backend.services.term_closure import close_term_stage

    ensure_term_engine_tables(db_conn)
    master = upsert_term_master(db_conn, season="fall", academic_year="2041/2042")
    apply_window_dates(
        db_conn,
        term_key=master["term_key"],
        window_key="registration_renewal",
        starts_at="2026-08-01",
        ends_at="2026-08-07",
    )
    close_term_stage(
        db_conn,
        stage="registrations",
        semester="خريف 2041/2042",
        department_id=None,
        actor="pytest",
        build_archive=False,
    )
    items = [
        {
            "item_no": 1,
            "title": "تجديد القيد وتسجيل المقررات الدراسية (لمدة أسبوع)",
            "event_date": "2026-08-28",
            "is_deleted": 0,
        }
    ]
    preview = preview_calendar_amendment(
        db_conn,
        academic_year="2041/2042",
        season="fall",
        items=items,
        now=datetime.date(2026, 8, 16),
    )
    assert preview["has_calendar_only"] is True
    applied = apply_calendar_amendment(
        db_conn,
        academic_year="2041/2042",
        season="fall",
        items=items,
        actor="pytest",
        reason="تأجيل وزاري بعد الإغلاق",
        confirm=True,
        now=datetime.date(2026, 8, 16),
        notify=False,
    )
    assert any(c["effect"] == EFFECT_CALENDAR_ONLY for c in applied["applied"])
    row = db_conn.execute(
        "SELECT ends_at FROM term_windows WHERE term_key=? AND window_key='registration_renewal'",
        (master["term_key"],),
    ).fetchone()
    assert str(row[0] if not hasattr(row, "keys") else row["ends_at"]) == "2026-08-07"


def test_grace_allows_write_after_immediate_close(db_conn):

    ensure_term_engine_tables(db_conn)
    master = upsert_term_master(db_conn, season="fall", academic_year="2042/2043")
    apply_window_dates(
        db_conn,
        term_key=master["term_key"],
        window_key="add_courses",
        starts_at=None,
        ends_at="2020-01-01",
        grace_until=(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)).isoformat(),
        source="policy",
    )
    assert_term_operation(
        db_conn,
        operation=OP_ADD_COURSE,
        semester="خريف 42-43",
        now=datetime.date(2026, 8, 16),
    )


def test_basket_blocks_term_switch(db_conn):
    ensure_term_engine_tables(db_conn)
    db_conn.execute(
        "INSERT INTO registrations (student_id, course_name, semester) VALUES ('S001', 'رياضيات 1', 'خريف 44-45')"
    )
    db_conn.commit()
    leftover = unmigrated_students(db_conn, "ربيع 45-46")
    assert leftover and leftover[0]["student_id"] == "S001"
    try:
        assert_current_term_switch_allowed(
            db_conn, term_name="ربيع", term_year="45-46"
        )
        assert False, "expected BasketSwitchBlocked"
    except BasketSwitchBlocked as exc:
        assert exc.code == CODE_BASKET_BLOCKED
        assert exc.payload["unmigrated_count"] >= 1


def test_archive_then_switch(db_conn):
    ensure_term_engine_tables(db_conn)
    db_conn.execute("DELETE FROM registrations")
    db_conn.execute(
        "INSERT INTO registrations (student_id, course_name, semester) VALUES ('S001', 'فيزياء 1', 'خريف 44-45')"
    )
    db_conn.commit()
    out = archive_live_basket(db_conn, actor="pytest", reason="إغلاق السلة قبل الربيع")
    assert out["archived_rows"] == 1
    n = db_conn.execute("SELECT COUNT(*) FROM registrations").fetchone()[0]
    assert int(n) == 0
    arch = db_conn.execute("SELECT COUNT(*) FROM term_registration_archives").fetchone()[0]
    assert int(arch) >= 1
    assert_current_term_switch_allowed(db_conn, term_name="ربيع", term_year="45-46")


def test_ops_dashboard_http(auth_client):
    r = auth_client.get("/term_ops/dashboard")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert "windows" in body
    assert "basket" in body
    assert "closure" in body
    assert "stored_calendars" in body


def test_ops_dashboard_hydrates_alias_year(auth_client, db_conn):
    db_conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', 'ربيع')")
    db_conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', '51-52')")
    db_conn.execute(
        """
        INSERT INTO academic_calendar (academic_year, term, item_no, title, event_date, is_deleted, updated_at)
        VALUES ('51-52', 'spring', 1, 'تجديد القيد وتسجيل المقررات الدراسية (لمدة أسبوع)', '2052-02-08', 0, '2052-01-01T00:00:00Z')
        """
    )
    db_conn.commit()
    r = auth_client.get("/term_ops/dashboard")
    assert r.status_code == 200
    body = r.get_json()
    assert body["term_key"] == "spring:2051/2052"
    renewal = next(w for w in body["windows"] if w["window_key"] == "registration_renewal")
    assert renewal["ends_at"] == "2052-02-08"
    assert renewal["status"] == "scheduled"
    new_reg = next(w for w in body["windows"] if w["window_key"] == "registration_new")
    assert new_reg.get("mapped") is True
    assert new_reg["date_kind"] == "range"
    assert body["term_master"].get("term_key") == "spring:2051/2052"
    db_conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', 'خريف')")
    db_conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', '44-45')")
    db_conn.commit()


def test_ops_dashboard_notice_when_other_year_has_dates(auth_client, db_conn):
    db_conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', 'ربيع')")
    db_conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', '52-53')")
    db_conn.execute(
        """
        INSERT INTO academic_calendar (academic_year, term, item_no, title, event_date, is_deleted, updated_at)
        VALUES ('2040/2041', 'spring', 1, 'تجديد القيد', '2041-02-10', 0, '2041-01-01T00:00:00Z')
        """
    )
    db_conn.commit()
    r = auth_client.get("/term_ops/dashboard")
    assert r.status_code == 200
    body = r.get_json()
    renewal = next(w for w in body["windows"] if w["window_key"] == "registration_renewal")
    assert not renewal.get("starts_at")
    assert body["notice_ar"]
    assert any(s["canonical_year"] == "2040/2041" for s in body["stored_calendars"])
    db_conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', 'خريف')")
    db_conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', '44-45')")
    db_conn.commit()


def test_calendar_preview_only_does_not_write(auth_client, db_conn):
    r = auth_client.post(
        "/academic_calendar/items",
        json={
            "academic_year": "2043/2044",
            "term": "fall",
            "preview_only": True,
            "items": [
                {"item_no": 1, "title": "تجديد القيد", "event_date": "2026-09-07", "is_deleted": 0}
            ],
        },
    )
    assert r.status_code == 200
    n = db_conn.execute(
        "SELECT COUNT(*) FROM academic_calendar WHERE academic_year='2043/2044'"
    ).fetchone()[0]
    assert int(n) == 0


def test_exception_bypasses_closed_window_not_stage(auth_client, db_conn):

    ensure_term_engine_tables(db_conn)
    master = upsert_term_master(db_conn, season="fall", academic_year="2046/2047")
    apply_window_dates(
        db_conn,
        term_key=master["term_key"],
        window_key="add_courses",
        starts_at=None,
        ends_at="2020-01-01",
        source="test",
    )
    r = auth_client.post(
        "/term_ops/exceptions",
        json={
            "student_id": "S001",
            "operation": OP_ADD_COURSE,
            "reason": "حالة إنسانية موثقة",
            "term_key": master["term_key"],
        },
    )
    assert r.status_code == 200
    eid = r.get_json()["id"]
    r2 = auth_client.post(f"/term_ops/exceptions/{eid}/approve", json={"days": 3})
    assert r2.status_code == 200
    assert_term_operation(
        db_conn,
        operation=OP_ADD_COURSE,
        semester="خريف 46-47",
        student_id="S001",
        now=datetime.date(2026, 8, 16),
    )
