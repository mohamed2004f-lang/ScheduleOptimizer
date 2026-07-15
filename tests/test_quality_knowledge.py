"""اختبارات مكتبة معرفة مساعد الجودة (رفع، اعتماد، استرجاع، تصدير)."""

from backend.core.quality_knowledge_catalog import LIBRARY_POLICY_AR, catalog_payload
from backend.core.quality_assistant_catalog import APPROVED_GLOBAL_REFERENCES
from backend.services.quality_knowledge import (
    can_approve_knowledge,
    can_upload_knowledge,
    create_knowledge_doc,
    ensure_quality_knowledge_tables,
    export_approved_knowledge_zip,
    library_bootstrap,
    list_knowledge_docs,
    retrieve_knowledge,
    seed_approved_global_refs_into_knowledge,
    seed_specialty_packs_into_knowledge,
    set_knowledge_status,
)
from backend.services.quality_assistant import run_quality_assistant


def _dept(db_conn) -> int:
    cur = db_conn.cursor()
    row = cur.execute("SELECT id FROM departments WHERE code = ?", ("QKLIB",)).fetchone()
    if row:
        return int(row[0] if not hasattr(row, "keys") else row["id"])
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        ("QKLIB", "قسم الميكانيك للاختبار", "MECH Test"),
    )
    db_conn.commit()
    return int(cur.execute("SELECT id FROM departments WHERE code = ?", ("QKLIB",)).fetchone()[0])


def test_catalog_and_roles():
    cat = catalog_payload()
    assert cat["suggestion_only"] is True
    assert LIBRARY_POLICY_AR in cat["policy_ar"] or cat["policy_ar"]
    assert can_upload_knowledge("head_of_department")
    assert not can_approve_knowledge("head_of_department")
    assert can_approve_knowledge("college_dean")
    assert can_approve_knowledge("instructor", is_college_quality_lead=True)


def test_create_approve_retrieve_export(db_conn):
    dept_id = _dept(db_conn)
    draft = create_knowledge_doc(
        db_conn,
        title_ar="ملخص OBE داخلي",
        actor="hod1",
        category="outcomes_obe",
        department_id=dept_id,
        body_text=(
            "مخرجات التعلم CLO يجب أن تكون قابلة للقياس. "
            "اربط التقييم بالمخرجات وراجع أدلة الشواهد بعد كل فصل. "
            "ABET ومخرجات البرنامج للنقاش فقط مع الالتزام بـ QAA المحلي."
        ),
        status="draft",
    )
    assert draft["id"]
    assert draft["status"] == "draft"
    assert draft["suggestion_only"] is True

    # المسودة لا تظهر في الاسترجاع المعتمد
    empty = retrieve_knowledge(
        db_conn,
        query="مخرجات التعلم CLO قابلة للقياس",
        department_id=dept_id,
        approved_only=True,
    )
    assert empty["hits_count"] == 0

    approved = set_knowledge_status(db_conn, int(draft["id"]), status="approved", actor="dean1")
    assert approved["status"] == "approved"

    hits = retrieve_knowledge(
        db_conn,
        query="مخرجات التعلم CLO قابلة للقياس ABET",
        department_id=dept_id,
        approved_only=True,
        top_k=3,
    )
    assert hits["hits_count"] >= 1
    assert any("CLO" in (h.get("excerpt") or "") or "مخرجات" in (h.get("excerpt") or "") for h in hits["hits"])

    z = export_approved_knowledge_zip(db_conn, department_id=dept_id)
    assert z[:2] == b"PK"


def test_seed_and_discuss_uses_library(db_conn):
    ensure_quality_knowledge_tables(db_conn)
    # وثيقة معتمدة مباشرة حتى لا نعتمد على فراغ المكتبة المشتركة في الاختبارات
    create_knowledge_doc(
        db_conn,
        title_ar="بطاقة مراجع مخرجات ورسالة",
        actor="system",
        category="global_summary",
        body_text=(
            "صياغة رسالة البرنامج يجب أن تربط سوق العمل بمخرجات التعلم. "
            "راجع أسئلة اللجنة حول قابلية القياس والشواهد. "
            "المراجع العالمية للنقاش وليست بديلاً عن QAA."
        ),
        status="approved",
    )

    seeded_once = seed_specialty_packs_into_knowledge(db_conn, actor="tester")
    # المكتبة غير فارغة: قد تُستكمل بطاقات عالمية ناقصة، لكن لا تُعاد حزم التخصص
    assert int(seeded_once.get("packs_seeded") or 0) == 0
    # إعادة التشغيل لا تضاعف البطاقات
    again = seed_specialty_packs_into_knowledge(db_conn, actor="tester")
    assert int(again.get("refs_seeded") or 0) == 0

    boot = library_bootstrap(
        db_conn,
        role="college_dean",
        department_id=None,
        seed_if_empty=False,
    )
    assert boot["can_approve"] is True
    assert len(boot["docs"]) >= 1

    dept_id = _dept(db_conn)
    d = run_quality_assistant(
        db_conn,
        mode="head_of_department",
        intent="discuss",
        department_id=dept_id,
        semester="اختبار-معرفة",
        notes="ما نصائح صياغة مخرجات التعلم والرسالة وفق المراجع؟",
    )
    assert d["status"] == "ok"
    assert d["suggestion_only"] is True
    links = d.get("links") or []
    assert any("knowledge" in str(l.get("href") or "") for l in links)
    assert d.get("knowledge_hits") is not None


def test_list_filters(db_conn):
    dept_id = _dept(db_conn)
    create_knowledge_doc(
        db_conn,
        title_ar="سياسة داخلية للاختبار",
        actor="dean",
        category="committee_notes",
        department_id=dept_id,
        body_text="سياسة لجنة الجودة للاختبار فقط",
        status="approved",
    )
    docs = list_knowledge_docs(
        db_conn, department_id=dept_id, category="committee_notes", status="approved"
    )
    assert any(d.get("title_ar") == "سياسة داخلية للاختبار" for d in docs)


def test_seed_when_library_empty(db_conn):
    ensure_quality_knowledge_tables(db_conn)
    cur = db_conn.cursor()
    cur.execute("DELETE FROM quality_knowledge_chunks")
    cur.execute("DELETE FROM quality_knowledge_docs")
    db_conn.commit()
    seeded = seed_specialty_packs_into_knowledge(db_conn, actor="tester")
    assert seeded["seeded"] >= 1
    assert int(seeded.get("refs_seeded") or 0) >= len(APPROVED_GLOBAL_REFERENCES)
    z = export_approved_knowledge_zip(db_conn)
    assert z[:2] == b"PK"


def test_seed_global_refs_idempotent(db_conn):
    ensure_quality_knowledge_tables(db_conn)
    a = seed_approved_global_refs_into_knowledge(db_conn, actor="tester")
    b = seed_approved_global_refs_into_knowledge(db_conn, actor="tester")
    assert int(a.get("seeded") or 0) + int(a.get("skipped") or 0) >= len(
        APPROVED_GLOBAL_REFERENCES
    )
    assert int(b.get("seeded") or 0) == 0
    hits = retrieve_knowledge(
        db_conn, query="ABET مخرجات طالب هندسية تصميم", approved_only=True, top_k=3
    )
    assert hits["hits_count"] >= 1
    assert hits.get("retrieval") == "keyword+hashed_embed"


def test_retrieve_prefers_department_scope(db_conn):
    ensure_quality_knowledge_tables(db_conn)
    from backend.services.quality_knowledge import create_knowledge_doc

    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        ("RAGMECH", "ميكانيكا RAG", "RAG MECH"),
    )
    db_conn.commit()
    dept_id = int(cur.execute("SELECT id FROM departments WHERE code=?", ("RAGMECH",)).fetchone()[0])

    create_knowledge_doc(
        db_conn,
        title_ar="وثيقة كلية عامة عن الجودة",
        actor="t",
        category="global_summary",
        department_id=None,
        body_text="الجودة الأكاديمية العامة للكلية ومؤشرات التشغيل فقط.",
        status="approved",
    )
    create_knowledge_doc(
        db_conn,
        title_ar="وثيقة ميكانيكا مخرجات تصميم",
        actor="t",
        category="outcomes_obe",
        department_id=dept_id,
        body_text="مخرجات التصميم الميكانيكي والتجريب والقياس في معامل الورش.",
        status="approved",
    )
    hits = retrieve_knowledge(
        db_conn,
        query="مخرجات التصميم الميكانيكي والتجريب",
        department_id=dept_id,
        prefer_department=True,
        top_k=3,
    )
    assert hits["hits_count"] >= 1
    assert hits["hits"][0]["title_ar"] == "وثيقة ميكانيكا مخرجات تصميم"
