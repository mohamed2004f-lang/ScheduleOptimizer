"""اختبارات ميزات المساعد المتقدمة (6–13)."""

from backend.services.quality_assistant import run_quality_assistant
from backend.services.quality_assistant_advanced import (
    build_committee_summary,
    build_style_training_export,
    committee_summary_docx_bytes,
    llm_config,
    log_usage_event,
    proofread_quality_text,
    proactive_term_alerts,
    suggest_archive_links,
    usage_analytics_summary,
)


def _dept(db_conn) -> int:
    cur = db_conn.cursor()
    row = cur.execute("SELECT id FROM departments WHERE code = ?", ("QAADV",)).fetchone()
    if row:
        return int(row[0] if not hasattr(row, "keys") else row["id"])
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        ("QAADV", "قسم متقدم للاختبار", "Adv"),
    )
    db_conn.commit()
    return int(cur.execute("SELECT id FROM departments WHERE code = ?", ("QAADV",)).fetchone()[0])


def test_committee_summary_and_docx(db_conn):
    dept_id = _dept(db_conn)
    summary = build_committee_summary(
        db_conn,
        mode="quality_committee",
        semester="اختبار-لجنة",
        department_id=dept_id,
        notes="ناقشنا فجوات PROG والأرشيف",
        history=[{"role": "user", "text": "ما أولويات الجلسة؟"}],
    )
    assert summary["status"] == "ok"
    assert "ملخص" in (summary.get("markdown") or "")
    docx = committee_summary_docx_bytes(summary)
    assert docx[:2] == b"PK"


def test_archive_suggest_and_proofread_and_alerts(db_conn):
    dept_id = _dept(db_conn)
    sug = suggest_archive_links(
        db_conn,
        mode="head_of_department",
        semester="اختبار-أرشيف",
        department_id=dept_id,
        notes="نحتاج محضر لجنة للجودة",
    )
    assert sug["suggestions"]
    assert sug["suggestion_only"] is True

    pr = proofread_quality_text(
        text="الطالب يفهم المادة بشكل ممتاز وعلى أعلى مستوى",
        kind="clo",
        use_llm=False,
    )
    assert pr["issues"]
    assert pr.get("improved_ar")

    al = proactive_term_alerts(
        db_conn, mode="head_of_department", semester="اختبار-تنبيه", department_id=dept_id
    )
    assert al["alerts"]
    assert any("إغلاق الفصل" in (a.get("title_ar") or "") for a in al["alerts"])


def test_usage_and_style_pack(db_conn):
    log_usage_event(db_conn, mode="instructor", intent="discuss", channel="assistant", actor="u1")
    log_usage_event(db_conn, mode="instructor", intent="discuss", channel="fab", actor="u2")
    log_usage_event(db_conn, mode="head_of_department", intent="proofread", actor="u1")
    stats = usage_analytics_summary(db_conn)
    assert stats["total_events"] >= 3
    assert stats["top"]

    z = build_style_training_export(db_conn)
    assert z[:2] == b"PK"
    cfg = llm_config()
    assert "enabled" in cfg


def test_assistant_intents_advanced(db_conn):
    dept_id = _dept(db_conn)
    r = run_quality_assistant(
        db_conn,
        mode="quality_committee",
        intent="committee_summary",
        department_id=dept_id,
        semester="اختبار-م6",
        notes="جلسة متابعة شواهد",
    )
    assert r["status"] == "ok"
    assert r.get("committee_summary") or r.get("draft_text")

    r2 = run_quality_assistant(
        db_conn,
        mode="instructor",
        intent="proofread",
        semester="اختبار-م8",
        notes="يصمم الطالب منظومة ميكانيكية بسيطة وفق متطلبات المقرر",
        topic="clo",
    )
    assert r2["status"] == "ok"
    assert r2.get("proofread") or any("صياغة" in str(b) for b in (r2.get("bullets") or []))

    r3 = run_quality_assistant(
        db_conn,
        mode="head_of_department",
        intent="archive_link_suggest",
        department_id=dept_id,
        semester="اختبار-م7",
    )
    assert r3["status"] == "ok"
