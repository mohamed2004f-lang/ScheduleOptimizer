"""أرشيف ضمان جودة القسم — CRUD ورفع ملفات واقتراحات ربط يدوي."""

from __future__ import annotations

import datetime
import hashlib
import os
import re
from typing import Any

from backend.core.department_archive_catalog import (
    ARCHIVE_RECORD_TYPES,
    ARCHIVE_TYPE_CODES,
    FOLLOW_UP_STATUSES,
    GUIDE_SECTIONS,
    NAMING_EXAMPLES,
    NAMING_PATTERN_AR,
    suggestions_for_type,
)
from backend.database.database import is_postgresql, table_exists
from backend.services.quality_metrics import _row_val, term_label_from_conn

ALLOWED_EXTENSIONS = frozenset(
    {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".png", ".jpg", ".jpeg", ".webp", ".txt"}
)
MAX_FILE_BYTES = 15 * 1024 * 1024

_TABLE_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS department_archive_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL,
    program_id INTEGER,
    record_type TEXT NOT NULL,
    title_ar TEXT NOT NULL DEFAULT '',
    ref_number TEXT DEFAULT '',
    doc_date TEXT DEFAULT '',
    semester TEXT DEFAULT '',
    party_ar TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    body_text TEXT DEFAULT '',
    follow_up_status TEXT DEFAULT 'na',
    original_name TEXT DEFAULT '',
    stored_path TEXT DEFAULT '',
    mime_type TEXT DEFAULT '',
    file_size INTEGER DEFAULT 0,
    sha256 TEXT DEFAULT '',
    created_by TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT DEFAULT '',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (department_id) REFERENCES departments(id)
)
"""


def archive_upload_dir() -> str:
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "uploads", "department_archive")
    )
    os.makedirs(base, exist_ok=True)
    return base


def ensure_department_archive_table(conn) -> None:
    if table_exists(conn, "department_archive_items"):
        return
    cur = conn.cursor()
    if is_postgresql():
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS department_archive_items (
                id BIGSERIAL PRIMARY KEY,
                department_id BIGINT NOT NULL,
                program_id BIGINT,
                record_type TEXT NOT NULL,
                title_ar TEXT NOT NULL DEFAULT '',
                ref_number TEXT DEFAULT '',
                doc_date TEXT DEFAULT '',
                semester TEXT DEFAULT '',
                party_ar TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                body_text TEXT DEFAULT '',
                follow_up_status TEXT DEFAULT 'na',
                original_name TEXT DEFAULT '',
                stored_path TEXT DEFAULT '',
                mime_type TEXT DEFAULT '',
                file_size BIGINT DEFAULT 0,
                sha256 TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_by TEXT DEFAULT '',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
    else:
        cur.execute(_TABLE_DDL_SQLITE)
    try:
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_dept_archive_dept_sem "
            "ON department_archive_items(department_id, semester, record_type)"
        )
    except Exception:
        pass
    conn.commit()


def _now() -> str:
    return datetime.datetime.utcnow().isoformat()


def _row_dict(row) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    return {}


def _normalize_type(record_type: str) -> str:
    t = (record_type or "").strip().lower()
    if t not in ARCHIVE_RECORD_TYPES:
        raise ValueError("نوع السجل غير معروف")
    return t


def catalog_payload() -> dict[str, Any]:
    return {
        "record_types": list(ARCHIVE_RECORD_TYPES.values()),
        "follow_up_statuses": [{"code": c, "label_ar": lbl} for c, lbl in FOLLOW_UP_STATUSES],
        "naming_pattern_ar": NAMING_PATTERN_AR,
        "naming_examples": NAMING_EXAMPLES,
        "guide_sections": GUIDE_SECTIONS,
    }


def list_archive_items(
    conn,
    *,
    department_id: int,
    semester: str | None = None,
    record_type: str | None = None,
    q: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    ensure_department_archive_table(conn)
    cur = conn.cursor()
    sql = """
        SELECT id, department_id, program_id, record_type, title_ar, ref_number, doc_date,
               semester, party_ar, tags, body_text, follow_up_status,
               original_name, stored_path, mime_type, file_size, sha256,
               created_by, created_at, updated_by, updated_at, is_active
        FROM department_archive_items
        WHERE department_id = ? AND COALESCE(is_active, 1) = 1
    """
    params: list[Any] = [int(department_id)]
    if (semester or "").strip():
        sql += " AND semester = ?"
        params.append(semester.strip())
    if (record_type or "").strip():
        sql += " AND record_type = ?"
        params.append(_normalize_type(record_type))
    if (q or "").strip():
        like = f"%{q.strip()}%"
        sql += (
            " AND (title_ar LIKE ? OR ref_number LIKE ? OR party_ar LIKE ? "
            "OR tags LIKE ? OR body_text LIKE ? OR original_name LIKE ?)"
        )
        params.extend([like, like, like, like, like, like])
    sql += " ORDER BY COALESCE(doc_date, '') DESC, id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    rows = cur.execute(sql, tuple(params)).fetchall() or []
    out = []
    for r in rows:
        d = _row_dict(r)
        if not d and r is not None:
            keys = [
                "id", "department_id", "program_id", "record_type", "title_ar", "ref_number",
                "doc_date", "semester", "party_ar", "tags", "body_text", "follow_up_status",
                "original_name", "stored_path", "mime_type", "file_size", "sha256",
                "created_by", "created_at", "updated_by", "updated_at", "is_active",
            ]
            d = {keys[i]: r[i] for i in range(min(len(keys), len(r)))}
        meta = ARCHIVE_RECORD_TYPES.get(d.get("record_type") or "", {})
        d["record_type_label_ar"] = meta.get("title_ar") or d.get("record_type")
        d["has_file"] = bool((d.get("stored_path") or "").strip())
        d["qaa_suggestions"] = suggestions_for_type(str(d.get("record_type") or ""))
        out.append(d)
    return out


def get_archive_item(conn, item_id: int) -> dict[str, Any] | None:
    ensure_department_archive_table(conn)
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT id, department_id, program_id, record_type, title_ar, ref_number, doc_date,
               semester, party_ar, tags, body_text, follow_up_status,
               original_name, stored_path, mime_type, file_size, sha256,
               created_by, created_at, updated_by, updated_at, is_active
        FROM department_archive_items
        WHERE id = ? AND COALESCE(is_active, 1) = 1
        """,
        (int(item_id),),
    ).fetchone()
    if not row:
        return None
    d = _row_dict(row)
    if not d:
        keys = [
            "id", "department_id", "program_id", "record_type", "title_ar", "ref_number",
            "doc_date", "semester", "party_ar", "tags", "body_text", "follow_up_status",
            "original_name", "stored_path", "mime_type", "file_size", "sha256",
            "created_by", "created_at", "updated_by", "updated_at", "is_active",
        ]
        d = {keys[i]: row[i] for i in range(min(len(keys), len(row)))}
    meta = ARCHIVE_RECORD_TYPES.get(d.get("record_type") or "", {})
    d["record_type_label_ar"] = meta.get("title_ar") or d.get("record_type")
    d["has_file"] = bool((d.get("stored_path") or "").strip())
    d["qaa_suggestions"] = suggestions_for_type(str(d.get("record_type") or ""))
    return d


def create_archive_item(
    conn,
    *,
    department_id: int,
    record_type: str,
    title_ar: str,
    actor: str,
    program_id: int | None = None,
    ref_number: str = "",
    doc_date: str = "",
    semester: str | None = None,
    party_ar: str = "",
    tags: str = "",
    body_text: str = "",
    follow_up_status: str = "na",
    raw: bytes | None = None,
    original_name: str = "",
    mime_type: str = "",
) -> dict[str, Any]:
    ensure_department_archive_table(conn)
    rtype = _normalize_type(record_type)
    title = (title_ar or "").strip()
    if not title:
        raise ValueError("عنوان السجل مطلوب")
    sem = (semester or term_label_from_conn(conn) or "").strip()
    status = (follow_up_status or "na").strip() or "na"
    allowed_status = {c for c, _ in FOLLOW_UP_STATUSES}
    if status not in allowed_status:
        status = "na"

    stored_path = ""
    sha = ""
    fsize = 0
    oname = (original_name or "").strip()
    mime = (mime_type or "").strip()
    if raw:
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError("حجم الملف يتجاوز 15MB")
        ext = os.path.splitext(oname or "document.bin")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError("صيغة غير مسموحة")
        sha = hashlib.sha256(raw).hexdigest()
        safe_sem = re.sub(r"[^\w\-]+", "_", sem)[:40] or "sem"
        stored_name = f"dept{int(department_id)}__{rtype}__{safe_sem}__{sha[:16]}{ext}"
        stored_path = os.path.join(archive_upload_dir(), stored_name)
        with open(stored_path, "wb") as out:
            out.write(raw)
        fsize = len(raw)

    now = _now()
    cur = conn.cursor()
    if is_postgresql():
        cur.execute(
            """
            INSERT INTO department_archive_items (
                department_id, program_id, record_type, title_ar, ref_number, doc_date,
                semester, party_ar, tags, body_text, follow_up_status,
                original_name, stored_path, mime_type, file_size, sha256,
                created_by, created_at, updated_by, updated_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            RETURNING id
            """,
            (
                int(department_id),
                int(program_id) if program_id is not None else None,
                rtype,
                title[:300],
                (ref_number or "")[:120],
                (doc_date or "")[:40],
                sem[:80],
                (party_ar or "")[:300],
                (tags or "")[:300],
                (body_text or "")[:8000],
                status[:32],
                oname[:260],
                stored_path,
                mime[:120],
                fsize,
                sha,
                (actor or "")[:120],
                now,
                (actor or "")[:120],
                now,
            ),
        )
        item_id = int(_row_val(cur.fetchone(), 0, "id") or 0)
    else:
        cur.execute(
            """
            INSERT INTO department_archive_items (
                department_id, program_id, record_type, title_ar, ref_number, doc_date,
                semester, party_ar, tags, body_text, follow_up_status,
                original_name, stored_path, mime_type, file_size, sha256,
                created_by, created_at, updated_by, updated_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                int(department_id),
                int(program_id) if program_id is not None else None,
                rtype,
                title[:300],
                (ref_number or "")[:120],
                (doc_date or "")[:40],
                sem[:80],
                (party_ar or "")[:300],
                (tags or "")[:300],
                (body_text or "")[:8000],
                status[:32],
                oname[:260],
                stored_path,
                mime[:120],
                fsize,
                sha,
                (actor or "")[:120],
                now,
                (actor or "")[:120],
                now,
            ),
        )
        item_id = int(getattr(cur, "lastrowid", None) or cur.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.commit()
    item = get_archive_item(conn, item_id)
    return item or {"id": item_id, "status": "ok"}


def soft_delete_archive_item(conn, item_id: int, *, actor: str = "") -> bool:
    ensure_department_archive_table(conn)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE department_archive_items
        SET is_active = 0, updated_at = ?, updated_by = ?
        WHERE id = ? AND COALESCE(is_active, 1) = 1
        """,
        (_now(), (actor or "")[:120], int(item_id)),
    )
    conn.commit()
    return cur.rowcount > 0


def archive_checklist(conn, *, department_id: int, semester: str) -> dict[str, Any]:
    ensure_department_archive_table(conn)
    sem = (semester or "").strip()
    items = list_archive_items(conn, department_id=department_id, semester=sem, limit=500)
    by_type: dict[str, int] = {c: 0 for c in ARCHIVE_TYPE_CODES}
    open_notes = 0
    for it in items:
        rt = it.get("record_type") or ""
        if rt in by_type:
            by_type[rt] += 1
        if rt == "notes" and (it.get("follow_up_status") or "") in ("open", "in_progress"):
            open_notes += 1
    rows = []
    for code in ARCHIVE_TYPE_CODES:
        meta = ARCHIVE_RECORD_TYPES[code]
        count = by_type[code]
        ok = count >= 1 if code != "notes" else True
        if code == "notes":
            hint = "اختياري — أغلق الملاحظات المفتوحة أو وثّق حالتها"
            ok = open_notes == 0 or count >= 1
        else:
            hint = "يُفضّل سند واحد على الأقل هذا الفصل" if not ok else "مكتمل"
        rows.append(
            {
                "record_type": code,
                "title_ar": meta["title_ar"],
                "count": count,
                "ok": bool(ok),
                "hint_ar": hint,
            }
        )
    complete = all(r["ok"] for r in rows if r["record_type"] != "notes") and open_notes == 0
    return {
        "status": "ok",
        "department_id": int(department_id),
        "semester": sem,
        "rows": rows,
        "open_notes": open_notes,
        "complete": complete,
        "summary_ar": (
            "قائمة التحقق الفصلية مكتملة" if complete else "توجد نواقص في أرشيف هذا الفصل"
        ),
    }


def suggest_qaa_for_item(conn, item_id: int) -> dict[str, Any]:
    item = get_archive_item(conn, item_id)
    if not item:
        raise ValueError("السجل غير موجود")
    suggestions = list(item.get("qaa_suggestions") or [])
    # enrich titles from catalog when possible
    cur = conn.cursor()
    enriched = []
    for s in suggestions:
        code = (s.get("indicator_code") or "").strip()
        cat = (s.get("catalog_version") or "").strip()
        title = ""
        if code and table_exists(conn, "accreditation_indicators"):
            row = cur.execute(
                """
                SELECT i.title_ar FROM accreditation_indicators i
                INNER JOIN accreditation_standards st ON st.id = i.standard_id
                WHERE i.code = ? AND st.catalog_version = ?
                LIMIT 1
                """,
                (code, cat),
            ).fetchone()
            if row:
                title = str(_row_val(row, 0, "title_ar") or "")
        enriched.append({**s, "indicator_title_ar": title, "suggestion_only": True})
    return {
        "status": "ok",
        "item": item,
        "suggestions": enriched,
        "policy_ar": "اقتراح فقط — يجب تأكيد الربط يدوياً. لا تُحدَّث حالة الامتثال تلقائياً.",
    }


def link_archive_item_to_evidence(
    conn,
    *,
    item_id: int,
    indicator_code: str,
    catalog_version: str,
    actor: str,
    semester: str | None = None,
) -> dict[str, Any]:
    """ترشيح سجل الأرشيف كشاهد اعتماد بعد اختيار يدوي لمؤشر."""
    from backend.core.accreditation_catalog import ensure_accreditation_catalog
    from backend.services.accreditation_evidence import save_file_evidence
    from backend.services.survey_accreditation import resolve_indicator_id

    item = get_archive_item(conn, item_id)
    if not item:
        raise ValueError("السجل غير موجود")
    ensure_accreditation_catalog(conn)
    code = (indicator_code or "").strip()
    cat = (catalog_version or "").strip()
    if not code or not cat:
        raise ValueError("indicator_code و catalog_version مطلوبان")
    iid = resolve_indicator_id(conn, code, catalog_version=cat)
    if not iid:
        # try without catalog helper signature
        try:
            iid = resolve_indicator_id(conn, code)
        except TypeError:
            iid = None
    if not iid:
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT i.id FROM accreditation_indicators i
            INNER JOIN accreditation_standards s ON s.id = i.standard_id
            WHERE i.code = ? AND s.catalog_version = ?
            LIMIT 1
            """,
            (code, cat),
        ).fetchone()
        iid = int(_row_val(row, 0, "id") or 0) if row else None
    if not iid:
        raise ValueError(f"المؤشر {code} غير موجود في {cat}")

    sem = (semester or item.get("semester") or term_label_from_conn(conn) or "").strip()
    dept_id = int(item["department_id"])
    title = f"[أرشيف] {item.get('record_type_label_ar') or item.get('record_type')}: {item.get('title_ar')}"
    desc = (
        f"ربط يدوي من أرشيف القسم. رقم: {item.get('ref_number') or '—'} · "
        f"تاريخ: {item.get('doc_date') or '—'} · سجل #{item.get('id')}"
    )

    stored = (item.get("stored_path") or "").strip()
    if stored and os.path.isfile(stored):
        with open(stored, "rb") as fh:
            raw = fh.read()
        result = save_file_evidence(
            conn,
            semester=sem,
            department_id=dept_id,
            raw=raw,
            original_name=item.get("original_name") or os.path.basename(stored),
            mime_type=item.get("mime_type") or "application/octet-stream",
            uploaded_by=actor or "archive",
            indicator_id=int(iid),
            title_ar=title[:300],
            description=desc[:2000],
        )
    else:
        # رابط/سجل نصي بدون ملف — احفظ كدليل رابط وصفي عبر جدول الأدلة إن أمكن
        from backend.services.accreditation_evidence import save_link_evidence

        result = save_link_evidence(
            conn,
            semester=sem,
            department_id=dept_id,
            external_url=f"archive://item/{int(item_id)}",
            uploaded_by=actor or "archive",
            indicator_id=int(iid),
            title_ar=title[:300],
            description=(desc + "\n\n" + (item.get("body_text") or ""))[:2000],
        )
    return {
        "status": "ok",
        "policy_ar": "تم الربط يدوياً كشاهد — حالة الامتثال لم تُغيَّر تلقائياً.",
        "evidence": result,
        "indicator_id": int(iid),
        "indicator_code": code,
        "catalog_version": cat,
        "archive_item_id": int(item_id),
    }
