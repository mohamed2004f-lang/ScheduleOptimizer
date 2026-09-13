"""نافذة ملء استبيانات الطلبة: بعد الإسقاط وقبل بداية الفصل التالي."""
from __future__ import annotations

import datetime

import pytest

from backend.services.student_survey_window import (
    MSG_AFTER_CLOSE,
    MSG_BEFORE_OPEN,
    MSG_NO_DROP,
    next_ops_term,
    student_survey_fill_gate,
)
from backend.services.term_engine import WINDOW_SCHEDULED, WINDOW_UNSET, upsert_term_master


@pytest.fixture(autouse=True)
def _isolate_gate(monkeypatch):
    """لا hydration من التقويم؛ الفصل الجاري الافتراضي = نفس فصل الاستبيان (لا إغلاق احتياطي)."""
    monkeypatch.setattr(
        "backend.services.student_survey_window.hydrate_term_windows_from_calendar",
        lambda *a, **k: {"hydrated": False, "reason": "test"},
    )


def _put_window(conn, term_key: str, window_key: str, *, starts=None, ends=None, status=WINDOW_SCHEDULED):
    conn.execute(
        "DELETE FROM term_windows WHERE term_key = ? AND window_key = ?",
        (term_key, window_key),
    )
    conn.execute(
        """
        INSERT INTO term_windows (
            term_key, window_key, kind, label_ar, closure_stage,
            starts_at, ends_at, status, source, updated_at
        ) VALUES (?, ?, 'window', ?, 'registrations', ?, ?, ?, 'test', '2026-01-01T00:00:00Z')
        """,
        (term_key, window_key, window_key, starts, ends, status),
    )
    conn.commit()


def _pin_current_term(monkeypatch, name: str, year: str):
    monkeypatch.setattr(
        "backend.services.utilities.get_current_term",
        lambda conn=None: (name, year),
    )


def test_next_ops_term_fall_to_spring():
    nxt = next_ops_term("fall", "2025/2026")
    assert nxt is not None
    assert nxt["season"] == "spring"
    assert nxt["academic_year"] == "2025/2026"
    assert nxt["term_key"] == "spring:2025/2026"


def test_next_ops_term_spring_to_fall():
    nxt = next_ops_term("spring", "2025/2026")
    assert nxt is not None
    assert nxt["season"] == "fall"
    assert nxt["academic_year"] == "2026/2027"
    assert nxt["term_key"] == "fall:2026/2027"


def test_gate_before_drop_deadline(db_conn, monkeypatch):
    year = "2031/2032"
    _pin_current_term(monkeypatch, "خريف", year)
    master = upsert_term_master(db_conn, season="fall", academic_year=year)
    nxt = upsert_term_master(db_conn, season="spring", academic_year=year)
    _put_window(db_conn, master["term_key"], "drop_courses", ends="2031-11-10")
    # بداية الفصل التالي بعيدة حتى لا يتداخل الإغلاق
    _put_window(db_conn, nxt["term_key"], "instruction_start", starts="2032-02-15")
    gate = student_survey_fill_gate(
        db_conn,
        f"خريف {year}",
        today=datetime.date(2031, 11, 10),
    )
    assert gate["open"] is False
    assert gate["reason"] == "before_drop_deadline"
    assert gate["message_ar"] == MSG_BEFORE_OPEN


def test_gate_opens_day_after_drop(db_conn, monkeypatch):
    year = "2032/2033"
    _pin_current_term(monkeypatch, "خريف", year)
    master = upsert_term_master(db_conn, season="fall", academic_year=year)
    nxt = upsert_term_master(db_conn, season="spring", academic_year=year)
    _put_window(db_conn, master["term_key"], "drop_courses", ends="2032-11-10")
    _put_window(db_conn, nxt["term_key"], "instruction_start", starts="2033-02-15")
    gate = student_survey_fill_gate(
        db_conn,
        f"خريف {year}",
        today=datetime.date(2032, 11, 11),
    )
    assert gate["open"] is True
    assert gate["reason"] == "open"
    assert gate["drop_ends_at"] == "2032-11-10"
    assert gate["closes_at"] == "2033-02-15"


def test_gate_closes_when_next_instruction_starts(db_conn, monkeypatch):
    year = "2033/2034"
    _pin_current_term(monkeypatch, "خريف", year)
    master = upsert_term_master(db_conn, season="fall", academic_year=year)
    nxt = upsert_term_master(db_conn, season="spring", academic_year=year)
    _put_window(db_conn, master["term_key"], "drop_courses", ends="2033-11-10")
    _put_window(db_conn, nxt["term_key"], "instruction_start", starts="2034-02-15")
    gate = student_survey_fill_gate(
        db_conn,
        f"خريف {year}",
        today=datetime.date(2034, 2, 15),
    )
    assert gate["open"] is False
    assert gate["reason"] == "closed_new_term_started"
    assert gate["message_ar"] == MSG_AFTER_CLOSE


def test_gate_fail_closed_when_drop_unset(db_conn, monkeypatch):
    year = "2034/2035"
    _pin_current_term(monkeypatch, "خريف", year)
    master = upsert_term_master(db_conn, season="fall", academic_year=year)
    nxt = upsert_term_master(db_conn, season="spring", academic_year=year)
    conn = db_conn
    conn.execute(
        "DELETE FROM term_windows WHERE term_key IN (?, ?)",
        (master["term_key"], nxt["term_key"]),
    )
    conn.commit()
    gate = student_survey_fill_gate(
        db_conn,
        f"خريف {year}",
        today=datetime.date(2034, 12, 1),
    )
    assert gate["open"] is False
    assert gate["reason"] == "drop_deadline_unset"
    assert gate["message_ar"] == MSG_NO_DROP


def test_gate_fail_closed_when_drop_status_unset(db_conn, monkeypatch):
    year = "2035/2036"
    _pin_current_term(monkeypatch, "خريف", year)
    master = upsert_term_master(db_conn, season="fall", academic_year=year)
    nxt = upsert_term_master(db_conn, season="spring", academic_year=year)
    _put_window(
        db_conn,
        master["term_key"],
        "drop_courses",
        ends="2035-11-10",
        status=WINDOW_UNSET,
    )
    _put_window(db_conn, nxt["term_key"], "instruction_start", starts="2036-02-15")
    gate = student_survey_fill_gate(
        db_conn,
        f"خريف {year}",
        today=datetime.date(2035, 12, 1),
    )
    assert gate["open"] is False
    assert gate["reason"] == "drop_deadline_unset"


def test_gate_closes_when_current_term_advanced(db_conn, monkeypatch):
    year = "2036/2037"
    master = upsert_term_master(db_conn, season="fall", academic_year=year)
    nxt = upsert_term_master(db_conn, season="spring", academic_year=year)
    _put_window(db_conn, master["term_key"], "drop_courses", ends="2036-11-10")
    # لا بداية دراسة للفصل التالي
    db_conn.execute(
        "DELETE FROM term_windows WHERE term_key = ? AND window_key = 'instruction_start'",
        (nxt["term_key"],),
    )
    db_conn.commit()
    _pin_current_term(monkeypatch, "ربيع", year)
    gate = student_survey_fill_gate(
        db_conn,
        f"خريف {year}",
        today=datetime.date(2037, 1, 20),
    )
    assert gate["open"] is False
    assert gate["reason"] == "closed_current_term_advanced"
    assert gate["message_ar"] == MSG_AFTER_CLOSE
