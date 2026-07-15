"""اختبارات إغلاق الفصل الموحّد (مراحل 0–6)."""

import os

from backend.services.term_closure import (
    TermClosedError,
    assert_term_writable,
    close_term_stage,
    ensure_term_closure_tables,
    get_term_closure_status,
    is_stage_closed,
    reopen_term_stage,
)


def test_ensure_tables_and_status(db_conn):
    ensure_term_closure_tables(db_conn)
    status = get_term_closure_status(db_conn, semester="خريف-اختبار-1", department_id=None)
    assert status["status"] == "ok"
    assert status["semester"] == "خريف-اختبار-1"
    assert status["scope_key"] == "college"
    assert status["operational_complete"] is False
    stages = {s["stage"]: s for s in status["stage_board"]}
    assert "registrations" in stages
    assert "grades" in stages
    assert stages["grades"]["optional"] is True
    assert status["grades_policy"]["excluded_from_first_wave"] is True


def test_close_registrations_locks_writes(db_conn):
    sem = "خريف-قفل-reg"
    close_term_stage(
        db_conn,
        stage="registrations",
        semester=sem,
        department_id=None,
        actor="pytest",
        build_archive=False,
    )
    assert is_stage_closed(db_conn, sem, "registrations", None)
    try:
        assert_term_writable(db_conn, stage="registrations", semester=sem)
        assert False, "expected TermClosedError"
    except TermClosedError as exc:
        assert "مغلق" in str(exc)


def test_dept_scope_does_not_block_other_dept(db_conn):
    sem = "خريف-قفل-dept"
    close_term_stage(
        db_conn,
        stage="schedule",
        semester=sem,
        department_id=1,
        actor="pytest",
        build_archive=False,
    )
    assert is_stage_closed(db_conn, sem, "schedule", 1)
    # قسم آخر غير مقفل (ما لم يُغلق على مستوى الكلية)
    assert not is_stage_closed(
        db_conn, sem, "schedule", 2, include_college=True
    )
    assert_term_writable(
        db_conn, stage="schedule", semester=sem, department_id=2
    )


def test_college_lock_blocks_department(db_conn):
    sem = "خريف-قفل-college"
    close_term_stage(
        db_conn,
        stage="exams",
        semester=sem,
        department_id=None,
        actor="pytest",
        build_archive=False,
    )
    assert is_stage_closed(db_conn, sem, "exams", 5, include_college=True)
    try:
        assert_term_writable(
            db_conn, stage="exams", semester=sem, department_id=5
        )
        assert False, "expected TermClosedError"
    except TermClosedError:
        pass


def test_reopen_requires_reason(db_conn):
    sem = "خريف-إعادة-فتح"
    close_term_stage(
        db_conn,
        stage="registrations",
        semester=sem,
        department_id=None,
        actor="pytest",
        build_archive=False,
    )
    try:
        reopen_term_stage(
            db_conn,
            stage="registrations",
            semester=sem,
            department_id=None,
            actor="admin",
            reason="ابد",
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "سبب" in str(exc)

    status = reopen_term_stage(
        db_conn,
        stage="registrations",
        semester=sem,
        department_id=None,
        actor="admin",
        reason="تصحيح بيانات التسجيلات بعد خطأ",
    )
    assert status["stages"]["registrations"]["closed"] is False
    assert_term_writable(db_conn, stage="registrations", semester=sem)


def test_archive_after_operational_stages(db_conn, monkeypatch):
    sem = "خريف-أرشيف-zip"

    # لا نستدعي close_semester_and_snapshot الحقيقي للاستبيانات
    def _fake_survey_close(conn, **kwargs):
        return {
            "status": "ok",
            "snapshot_count": 0,
            "archive_filename": "",
            "archive_url": "",
        }

    monkeypatch.setattr(
        "backend.services.term_closure.close_semester_and_snapshot",
        _fake_survey_close,
    )

    for stage in ("registrations", "schedule", "exams", "surveys"):
        status = close_term_stage(
            db_conn,
            stage=stage,
            semester=sem,
            department_id=None,
            actor="pytest",
            build_archive=True,
        )
    assert status["operational_complete"] is True
    assert status.get("archive_filename")
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "backend",
        "uploads",
        "term_archives",
        status["archive_filename"],
    )
    # المسار عبر term_archive_dir
    from backend.services.term_closure import term_archive_dir

    full = os.path.join(term_archive_dir(), status["archive_filename"])
    assert os.path.isfile(full)


def test_new_semester_writable_while_old_locked(db_conn):
    """المرحلة 5: قفل الفصل يعتمد على ملصق الفصل — فصل جديد يبقى مفتوحاً."""
    old = "خريف-قديم-مغلق"
    new = "ربيع-جديد-مفتوح"
    close_term_stage(
        db_conn,
        stage="registrations",
        semester=old,
        department_id=None,
        actor="pytest",
        build_archive=False,
    )
    try:
        assert_term_writable(db_conn, stage="registrations", semester=old)
        assert False, "expected lock on old"
    except TermClosedError:
        pass
    assert_term_writable(db_conn, stage="registrations", semester=new)


def test_grades_stage_optional_not_required_for_archive(db_conn, monkeypatch):
    monkeypatch.setattr(
        "backend.services.term_closure.close_semester_and_snapshot",
        lambda *a, **k: {"status": "ok", "snapshot_count": 0, "archive_filename": ""},
    )
    sem = "خريف-بدون-درجات"
    for stage in ("registrations", "schedule", "exams", "surveys"):
        st = close_term_stage(
            db_conn,
            stage=stage,
            semester=sem,
            department_id=None,
            actor="pytest",
            build_archive=True,
        )
    assert st["operational_complete"] is True
    assert st["stages"]["grades"]["closed"] is False
    # الدرجات لا تُقفل تلقائياً
    assert_term_writable(db_conn, stage="grades", semester=sem)
