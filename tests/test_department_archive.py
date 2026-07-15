"""اختبارات أرشيف القسم + الاقتراحات + المساعد."""

from backend.core.accreditation_catalog import ensure_accreditation_catalog
from backend.core.department_archive_catalog import ARCHIVE_TYPE_CODES
from backend.services.department_archive import (
    archive_checklist,
    create_archive_item,
    ensure_department_archive_table,
    link_archive_item_to_evidence,
    list_archive_items,
    suggest_qaa_for_item,
)
from backend.services.department_archive_assistant import (
    classify_archive_text,
    draft_archive_document,
    run_assistant,
)


def _dept(db_conn) -> int:
    cur = db_conn.cursor()
    row = cur.execute("SELECT id FROM departments WHERE code = ?", ("ARCH",)).fetchone()
    if row:
        return int(row[0] if not hasattr(row, "keys") else row["id"])
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        ("ARCH", "قسم الأرشيف", "Archive Dept"),
    )
    db_conn.commit()
    return int(cur.execute("SELECT id FROM departments WHERE code = ?", ("ARCH",)).fetchone()[0])


def test_create_list_archive_and_checklist(db_conn):
    dept_id = _dept(db_conn)
    ensure_department_archive_table(db_conn)
    item = create_archive_item(
        db_conn,
        department_id=dept_id,
        record_type="minutes",
        title_ar="محضر لجنة الجودة",
        actor="tester",
        semester="أرشيف-1",
        doc_date="2026-07-14",
        ref_number="M-1",
        body_text="اجتماع ضمان الجودة",
    )
    assert item["id"]
    assert item["record_type"] == "minutes"
    items = list_archive_items(db_conn, department_id=dept_id, semester="أرشيف-1")
    assert len(items) == 1
    check = archive_checklist(db_conn, department_id=dept_id, semester="أرشيف-1")
    assert check["status"] == "ok"
    minutes_row = next(r for r in check["rows"] if r["record_type"] == "minutes")
    assert minutes_row["count"] == 1
    assert minutes_row["ok"] is True


def test_classify_and_draft_assistant():
    cls = classify_archive_text(title_ar="محضر اجتماع مجلس القسم", body_text="جدول أعمال وحضور")
    assert cls["suggested_type"] == "minutes"
    assert cls["suggestion_only"] is True
    draft = draft_archive_document(
        record_type="decision",
        fields={"title_ar": "اعتماد سياسة", "ref_number": "D-9", "doc_date": "2026-07-14"},
        department_name_ar="الهندسة",
    )
    assert "قرار" in draft["draft_text"]
    assert draft["suggestion_only"] is True


def test_suggest_qaa_and_manual_link(db_conn):
    ensure_accreditation_catalog(db_conn)
    dept_id = _dept(db_conn)
    item = create_archive_item(
        db_conn,
        department_id=dept_id,
        record_type="minutes",
        title_ar="محضر جودة",
        actor="tester",
        semester="أرشيف-2",
        body_text="لجنة الجودة",
        raw=b"%PDF-1.4 archive test",
        original_name="minutes.pdf",
        mime_type="application/pdf",
    )
    sug = suggest_qaa_for_item(db_conn, int(item["id"]))
    assert sug["suggestions"]
    assert sug["policy_ar"]
    first = sug["suggestions"][0]
    linked = link_archive_item_to_evidence(
        db_conn,
        item_id=int(item["id"]),
        indicator_code=first["indicator_code"],
        catalog_version=first["catalog_version"],
        actor="tester",
        semester="أرشيف-2",
    )
    assert linked["status"] == "ok"
    assert "يدوي" in linked["policy_ar"]


def test_assistant_gaps_and_help(db_conn):
    dept_id = _dept(db_conn)
    help_msg = run_assistant(db_conn, intent="help")
    assert "suggest" in str(help_msg.get("intents")) or help_msg.get("message_ar")
    gaps = run_assistant(db_conn, intent="gaps", department_id=dept_id, semester="أرشيف-3")
    assert gaps.get("rows")
    assert len(ARCHIVE_TYPE_CODES) == 5


def test_archive_pages(app, auth_client, db_conn):
    _dept(db_conn)
    page = auth_client.get("/academic_quality/archive")
    assert page.status_code == 200
    assert "أرشيف القسم".encode("utf-8") in page.data
    guide = auth_client.get("/academic_quality/archive/guide")
    assert guide.status_code == 200
    assert "دليل".encode("utf-8") in guide.data
