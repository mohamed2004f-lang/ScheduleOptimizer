"""دورة رفع الملفات: الصيغ المسموحة، الحجم، المسار، وصلاحية أرشيف الكلية."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.core.security import resolve_safe_upload_path
from backend.services.accreditation_evidence import (
    MAX_FILE_BYTES as EVIDENCE_MAX,
    save_file_evidence,
)
from backend.services.college_archive import (
    MAX_FILE_BYTES as COLLEGE_MAX,
    can_access_college_archive_portal,
    can_write_cabinet,
    create_college_archive_item,
    ensure_college_archive_table,
)
from backend.services.department_archive import (
    MAX_FILE_BYTES as DEPT_MAX,
    create_archive_item,
    ensure_department_archive_table,
)


def _dept(db_conn) -> int:
    cur = db_conn.cursor()
    row = cur.execute("SELECT id FROM departments WHERE code = ?", ("ULIF",)).fetchone()
    if row:
        return int(row[0] if not hasattr(row, "keys") else row["id"])
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        ("ULIF", "قسم رفع ملفات", "Upload Lifecycle Dept"),
    )
    db_conn.commit()
    return int(cur.execute("SELECT id FROM departments WHERE code = ?", ("ULIF",)).fetchone()[0])


def _unlink(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def test_evidence_rejects_exe_and_oversize(db_conn):
    with pytest.raises(ValueError, match="صيغة"):
        save_file_evidence(
            db_conn,
            semester="ul-sem",
            department_id=None,
            raw=b"MZ",
            original_name="payload.exe",
            mime_type="application/octet-stream",
            uploaded_by="tester",
        )
    with pytest.raises(ValueError, match="15MB"):
        save_file_evidence(
            db_conn,
            semester="ul-sem",
            department_id=None,
            raw=b"x" * (EVIDENCE_MAX + 1),
            original_name="huge.pdf",
            mime_type="application/pdf",
            uploaded_by="tester",
        )


def test_evidence_pdf_saved_under_uploads_and_downloadable(db_conn, auth_client):
    pdf = b"%PDF-1.4 lifecycle-ok"
    saved = save_file_evidence(
        db_conn,
        semester="ul-ok",
        department_id=None,
        raw=pdf,
        original_name="ok.pdf",
        mime_type="application/pdf",
        uploaded_by="tester",
        title_ar="دليل دورة الرفع",
    )
    assert saved["id"] > 0
    row = db_conn.execute(
        "SELECT stored_path FROM accreditation_evidence WHERE id=?",
        (saved["id"],),
    ).fetchone()
    stored = row[0] if not hasattr(row, "keys") else row["stored_path"]
    try:
        safe = resolve_safe_upload_path(stored)
        assert safe is not None
        assert "uploads" in str(safe).replace("\\", "/")
        assert "accreditation_evidence" in str(safe)
        assert safe.read_bytes() == pdf
        dl = auth_client.get(f"/academic_quality/api/accreditation/evidence/file/{saved['id']}")
        assert dl.status_code == 200
        assert dl.data == pdf
    finally:
        _unlink(stored)


def test_evidence_download_404_when_missing_on_disk(db_conn, auth_client):
    saved = save_file_evidence(
        db_conn,
        semester="ul-gone",
        department_id=None,
        raw=b"%PDF-1.4 gone",
        original_name="gone.pdf",
        mime_type="application/pdf",
        uploaded_by="tester",
    )
    row = db_conn.execute(
        "SELECT stored_path FROM accreditation_evidence WHERE id=?",
        (saved["id"],),
    ).fetchone()
    stored = row[0] if not hasattr(row, "keys") else row["stored_path"]
    _unlink(stored)
    dl = auth_client.get(f"/academic_quality/api/accreditation/evidence/file/{saved['id']}")
    assert dl.status_code == 404


def test_evidence_rejects_pdf_extension_with_wrong_content(db_conn):
    with pytest.raises(ValueError, match="لا يطابق"):
        save_file_evidence(
            db_conn,
            semester="ul-bad-magic",
            department_id=None,
            raw=b"MZ-this-is-not-a-pdf",
            original_name="malware.pdf",
            mime_type="application/pdf",
            uploaded_by="tester",
        )


def test_department_archive_rejects_exe_accepts_pdf(db_conn):
    dept_id = _dept(db_conn)
    ensure_department_archive_table(db_conn)
    with pytest.raises(ValueError, match="صيغة"):
        create_archive_item(
            db_conn,
            department_id=dept_id,
            record_type="minutes",
            title_ar="محضر خبيث",
            actor="tester",
            semester="ul-dept",
            raw=b"MZ",
            original_name="tool.exe",
            mime_type="application/octet-stream",
        )
    with pytest.raises(ValueError, match="15MB"):
        create_archive_item(
            db_conn,
            department_id=dept_id,
            record_type="minutes",
            title_ar="محضر ضخم",
            actor="tester",
            semester="ul-dept",
            raw=b"x" * (DEPT_MAX + 1),
            original_name="big.pdf",
            mime_type="application/pdf",
        )
    item = create_archive_item(
        db_conn,
        department_id=dept_id,
        record_type="minutes",
        title_ar="محضر PDF",
        actor="tester",
        semester="ul-dept",
        raw=b"%PDF-1.4 dept",
        original_name="minutes.pdf",
        mime_type="application/pdf",
    )
    stored = item.get("stored_path") or ""
    try:
        assert item["id"]
        safe = resolve_safe_upload_path(stored)
        assert safe is not None
        assert "department_archive" in str(safe).replace("\\", "/") or "uploads" in str(safe).replace("\\", "/")
    finally:
        _unlink(stored)


def test_college_archive_rejects_exe_and_traversal_name(db_conn):
    ensure_college_archive_table(db_conn)
    with pytest.raises(ValueError, match="صيغة"):
        create_college_archive_item(
            db_conn,
            cabinet="dean",
            record_type="decision",
            title_ar="قرار خبيث",
            actor="dean1",
            actor_role="college_dean",
            semester="ul-col",
            raw=b"MZ",
            original_name="../secret.exe",
            mime_type="application/octet-stream",
        )
    with pytest.raises(ValueError, match="15MB"):
        create_college_archive_item(
            db_conn,
            cabinet="dean",
            record_type="decision",
            title_ar="قرار ضخم",
            actor="dean1",
            actor_role="college_dean",
            semester="ul-col",
            raw=b"x" * (COLLEGE_MAX + 1),
            original_name="big.pdf",
            mime_type="application/pdf",
        )
    item = create_college_archive_item(
        db_conn,
        cabinet="dean",
        record_type="decision",
        title_ar="قرار PDF",
        actor="dean1",
        actor_role="college_dean",
        semester="ul-col",
        raw=b"%PDF-1.4 college",
        original_name="decision.pdf",
        mime_type="application/pdf",
    )
    stored = item.get("stored_path") or ""
    try:
        assert item["id"]
        safe = resolve_safe_upload_path(stored)
        assert safe is not None
        assert "college_archive" in str(safe).replace("\\", "/")
        assert ".." not in os.path.basename(stored)
    finally:
        _unlink(stored)


def test_instructor_and_student_cannot_write_dean_cabinet():
    assert can_write_cabinet("dean", "instructor") is False
    assert can_write_cabinet("dean", "student") is False
    assert can_write_cabinet("shared", "instructor") is False
    assert can_access_college_archive_portal("instructor") is False
    assert can_access_college_archive_portal("student") is False
    assert can_access_college_archive_portal("college_dean") is True


def test_instructor_http_cannot_create_college_archive(instructor_auth_client):
    resp = instructor_auth_client.post(
        "/academic_quality/api/college-archive/items",
        json={
            "cabinet": "dean",
            "record_type": "decision",
            "title_ar": "محاولة أستاذ",
        },
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 403


def test_student_http_cannot_create_college_archive(student_auth_client):
    resp = student_auth_client.post(
        "/academic_quality/api/college-archive/items",
        json={
            "cabinet": "dean",
            "record_type": "decision",
            "title_ar": "محاولة طالب",
        },
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 403


def test_instructor_cannot_download_accreditation_evidence(instructor_auth_client):
    resp = instructor_auth_client.get(
        "/academic_quality/api/accreditation/evidence/file/1",
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 403
