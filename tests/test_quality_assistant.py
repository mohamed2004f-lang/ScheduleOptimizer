"""اختبارات المساعد الذكي للجودة (أدوار + تصعيد)."""

from backend.core.quality_assistant_catalog import (
    APPROVED_GLOBAL_REFERENCES,
    ASSISTANT_MODES,
    catalog_for_client,
    exportable_specialty_packs,
    match_specialty_pack,
)
from backend.services.quality_assistant import (
    build_references_zip_bytes,
    build_welcome_brief,
    ensure_quality_assistant_tables,
    list_escalations,
    normalize_chat_history,
    resolve_assistant_mode,
    run_quality_assistant,
    save_assistant_feedback,
)


def _dept(db_conn) -> int:
    cur = db_conn.cursor()
    row = cur.execute("SELECT id FROM departments WHERE code = ?", ("QAASST",)).fetchone()
    if row:
        return int(row[0] if not hasattr(row, "keys") else row["id"])
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        ("QAASST", "قسم هندسة الحاسوب", "CS Eng"),
    )
    db_conn.commit()
    return int(cur.execute("SELECT id FROM departments WHERE code = ?", ("QAASST",)).fetchone()[0])


def test_catalog_has_five_modes():
    cat = catalog_for_client()
    codes = {m["code"] for m in cat["modes"]}
    assert codes == set(ASSISTANT_MODES.keys())
    assert cat["suggestion_only"] is True
    assert len(cat.get("approved_global_references") or []) >= 8
    assert {r["code"] for r in APPROVED_GLOBAL_REFERENCES} >= {
        "abet_eac",
        "washington_accord",
        "eur_ace",
        "cdio",
        "qaa_ly",
    }
    payload = exportable_specialty_packs(primary_only=True)
    assert len(payload.get("approved_global_references") or []) >= 8


def test_resolve_modes_by_role():
    assert resolve_assistant_mode(role="instructor") == "instructor"
    assert resolve_assistant_mode(role="head_of_department") == "head_of_department"
    assert resolve_assistant_mode(role="academic_vice_dean") in (
        "academic_vice_dean",
        "quality_committee",
        "college_dean",
    )
    assert resolve_assistant_mode(role="college_dean") in ("college_dean", "quality_committee")
    assert (
        resolve_assistant_mode(
            role="instructor",
            requested="quality_committee",
            is_dept_quality_coordinator=True,
        )
        == "quality_committee"
    )


def test_specialty_pack_by_department_code():
    mech = match_specialty_pack("الهندسة الميكانيكية", "MECH")
    assert mech["code"] == "MECH"
    assert mech.get("global_refs")
    assert "ABET" in str(mech.get("frameworks"))

    renew = match_specialty_pack("", "RENEW")
    assert renew["code"] == "RENEW"
    assert renew.get("disclaimer_ar")

    general = match_specialty_pack("القسم العام", "GENERAL")
    assert general["code"] == "GENERAL"


def test_instructor_and_hod_intents(db_conn):
    dept_id = _dept(db_conn)
    ensure_quality_assistant_tables(db_conn)
    r1 = run_quality_assistant(
        db_conn, mode="instructor", intent="clo_tips", department_id=dept_id, semester="اختبار-مساعد-1"
    )
    assert r1["status"] == "ok"
    assert r1["suggestion_only"] is True
    assert r1.get("bullets")

    r2 = run_quality_assistant(
        db_conn,
        mode="head_of_department",
        intent="dept_snapshot",
        department_id=dept_id,
        semester="اختبار-مساعد-1",
    )
    assert r2["status"] == "ok"
    assert "موجز" in (r2.get("message_ar") or "")


def test_escalation_chain(db_conn):
    dept_id = _dept(db_conn)
    ensure_quality_assistant_tables(db_conn)
    esc = run_quality_assistant(
        db_conn,
        mode="instructor",
        intent="escalate_hod",
        department_id=dept_id,
        semester="اختبار-مساعد-2",
        topic="CLO ناقص",
        notes="يرجى المراجعة",
        actor="tester",
    )
    assert esc["status"] == "ok"
    assert esc.get("escalation", {}).get("to_mode") == "head_of_department"
    items = list_escalations(db_conn, to_mode="head_of_department", department_id=dept_id)
    assert any(i["id"] == esc["escalation"]["id"] for i in items)


def test_committee_and_dean_intents(db_conn):
    dept_id = _dept(db_conn)
    ensure_quality_assistant_tables(db_conn)
    c = run_quality_assistant(
        db_conn,
        mode="quality_committee",
        intent="session_agenda",
        department_id=dept_id,
        semester="اختبار-مساعد-3",
    )
    assert c["status"] == "ok"
    assert c.get("bullets")

    d = run_quality_assistant(
        db_conn,
        mode="college_dean",
        intent="exec_brief",
        department_id=dept_id,
        semester="اختبار-مساعد-3",
    )
    assert d["status"] == "ok"
    assert "تنفيذي" in (d.get("message_ar") or "")


def test_vice_dean_ops(db_conn):
    _dept(db_conn)
    ensure_quality_assistant_tables(db_conn)
    v = run_quality_assistant(
        db_conn,
        mode="academic_vice_dean",
        intent="college_ops",
        semester="اختبار-مساعد-4",
    )
    assert v["status"] == "ok"
    assert "تشغيلية" in (v.get("message_ar") or "")


def test_discuss_and_references_export(db_conn):
    dept_id = _dept(db_conn)
    d = run_quality_assistant(
        db_conn,
        mode="head_of_department",
        intent="discuss",
        department_id=dept_id,
        semester="اختبار-مناقشة",
        notes="كيف أحسّن رسالة البرنامج مقارنة بـ ABET؟",
    )
    assert d["status"] == "ok"
    assert d["suggestion_only"] is True
    assert any("رسالة" in str(b) or "ABET" in str(b) or "حزمة" in str(b) for b in (d.get("bullets") or []))

    payload = exportable_specialty_packs(primary_only=True)
    codes = {p["code"] for p in payload["packs"]}
    assert {"MECH", "CIVIL", "ELEC", "RENEW", "GENERAL"} <= codes
    z = build_references_zip_bytes(primary_only=True)
    assert z[:2] == b"PK"


def test_system_help_chat(db_conn):
    cat = catalog_for_client()
    assert cat.get("topic_label_ar") == "موضوع"
    assert any(t["code"] == "system_help" for t in cat["modes"][0]["intents"])
    assert len(cat.get("system_usage_topics") or []) >= 5

    r = run_quality_assistant(
        db_conn,
        mode="instructor",
        intent="system_help",
        semester="اختبار-استخدام",
        notes="كيف أفتح أرشيف القسم؟",
    )
    assert r["status"] == "ok"
    assert r.get("matched_topic") == "department_archive" or any(
        "أرشيف" in str(b) for b in (r.get("bullets") or [])
    )
    assert r.get("links")
    assert r.get("reply_id")
    assert r.get("actions")

    r2 = run_quality_assistant(
        db_conn,
        mode="head_of_department",
        intent="system_help",
        semester="اختبار-استخدام",
        topic="knowledge_library",
    )
    assert r2["status"] == "ok"
    assert r2.get("matched_topic") == "knowledge_library"


def test_history_welcome_feedback_actions(db_conn):
    dept_id = _dept(db_conn)
    ensure_quality_assistant_tables(db_conn)
    hist = normalize_chat_history(
        [
            {"role": "user", "text": "نتحدث عن رسالة البرنامج"},
            {"role": "assistant", "text": "حسناً، ركّز على الجمهور والمؤشرات."},
            {"role": "user", "text": "وماذا عن الربط مع ABET؟"},
        ]
    )
    assert len(hist) == 3

    d = run_quality_assistant(
        db_conn,
        mode="head_of_department",
        intent="discuss",
        department_id=dept_id,
        semester="اختبار-ذاكرة",
        notes="أعد تلخيص النقطة السابقة باختصار",
        history=hist,
    )
    assert d["status"] == "ok"
    assert d.get("history_used", 0) >= 1
    assert d.get("reply_id")
    assert any(a.get("type") == "copy_text" for a in (d.get("actions") or []))
    assert any(a.get("type") == "escalate" for a in (d.get("actions") or []))

    w = build_welcome_brief(
        db_conn, mode="head_of_department", semester="اختبار-ترحيب", department_id=dept_id
    )
    assert w.get("greeting_ar")
    assert len(w.get("tasks") or []) >= 1

    fb = save_assistant_feedback(
        db_conn,
        reply_id=d["reply_id"],
        rating="up",
        reason_ar="واضح",
        mode="head_of_department",
        intent="discuss",
        actor="tester",
        department_id=dept_id,
    )
    assert fb["status"] == "ok"
    assert fb["rating"] == "up"
