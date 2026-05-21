"""أدلة الاعتماد المؤسسي — رفع ملفات وروابط (هـ-3)."""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any

from backend.core.accreditation_evidence_catalog import INSTITUTIONAL_EVIDENCE_CHECKLIST
from backend.database.database import is_postgresql, table_exists
from backend.services.quality_metrics import _row_val

ALLOWED_EXTENSIONS = frozenset(
    {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".png", ".jpg", ".jpeg", ".webp"}
)
MAX_FILE_BYTES = 15 * 1024 * 1024


def evidence_upload_dir() -> str:
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "uploads", "accreditation_evidence")
    )
    os.makedirs(base, exist_ok=True)
    return base


def _ensure_evidence_table(conn) -> None:
    if table_exists(conn, "accreditation_evidence"):
        return
    from backend.database.database import SCHEMA

    ddl = SCHEMA.get("accreditation_evidence")
    if ddl and hasattr(conn, "executescript"):
        conn.executescript(ddl)
        conn.commit()


def _row_dict(row, keys: list[str] | None = None) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    if keys:
        return {keys[i]: row[i] for i in range(min(len(keys), len(row)))}
    return {}


def list_evidence(
    conn,
    *,
    semester: str,
    department_id: int | None = None,
    indicator_id: int | None = None,
    checklist_key: str | None = None,
) -> list[dict[str, Any]]:
    _ensure_evidence_table(conn)
    cur = conn.cursor()
    dept_clause = "department_id IS NULL" if department_id is None else "department_id = ?"
    params: list[Any] = [semester]
    if department_id is not None:
        params.append(int(department_id))
    extra = ""
    if indicator_id is not None:
        extra += " AND indicator_id = ?"
        params.append(int(indicator_id))
    if checklist_key:
        extra += " AND checklist_key = ?"
        params.append(checklist_key.strip())
    cur.execute(
        f"""
        SELECT id, semester, department_id, indicator_id, standard_id, checklist_key,
               title_ar, description, evidence_type, external_url,
               original_name, mime_type, file_size, uploaded_by, uploaded_at
        FROM accreditation_evidence
        WHERE semester = ? AND {dept_clause} AND COALESCE(is_active, 1) = 1 {extra}
        ORDER BY uploaded_at DESC, id DESC
        """,
        tuple(params),
    )
    rows = cur.fetchall() or []
    desc = cur.description or ()
    keys = [d[0] for d in desc]
    items = [_row_dict(r, keys) for r in rows]
    for it in items:
        it["download_url"] = (
            f"/academic_quality/api/accreditation/evidence/file/{it['id']}"
            if it.get("evidence_type") == "file" and it.get("id")
            else None
        )
    return items


def evidence_counts_by_indicator(
    conn, semester: str, department_id: int | None
) -> dict[int, int]:
    _ensure_evidence_table(conn)
    cur = conn.cursor()
    dept_clause = "department_id IS NULL" if department_id is None else "department_id = ?"
    params: list[Any] = [semester]
    if department_id is not None:
        params.append(int(department_id))
    cur.execute(
        f"""
        SELECT indicator_id, COUNT(*) FROM accreditation_evidence
        WHERE semester = ? AND {dept_clause}
          AND indicator_id IS NOT NULL
          AND COALESCE(is_active, 1) = 1
        GROUP BY indicator_id
        """,
        tuple(params),
    )
    out: dict[int, int] = {}
    for r in cur.fetchall() or []:
        iid = _row_val(r, 0, "indicator_id")
        cnt = _row_val(r, 1) or 0
        if iid is not None:
            out[int(iid)] = int(cnt)
    return out


def build_checklist_status(
    conn, semester: str, department_id: int | None
) -> list[dict[str, Any]]:
    all_items = list_evidence(conn, semester=semester, department_id=department_id)
    by_key: dict[str, int] = {}
    for it in all_items:
        k = (it.get("checklist_key") or "").strip()
        if k:
            by_key[k] = by_key.get(k, 0) + 1
    out = []
    for key, title, desc, hint in INSTITUTIONAL_EVIDENCE_CHECKLIST:
        cnt = by_key.get(key, 0)
        out.append(
            {
                "checklist_key": key,
                "title_ar": title,
                "description_ar": desc,
                "qaa_hint": hint,
                "attached_count": cnt,
                "has_evidence": cnt > 0,
            }
        )
    return out


def save_file_evidence(
    conn,
    *,
    semester: str,
    department_id: int | None,
    raw: bytes,
    original_name: str,
    mime_type: str,
    uploaded_by: str,
    indicator_id: int | None = None,
    standard_id: int | None = None,
    checklist_key: str | None = None,
    title_ar: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    _ensure_evidence_table(conn)
    if not raw:
        raise ValueError("ملف فارغ")
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("حجم الملف يتجاوز 15MB")

    filename = (original_name or "document").strip()
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("صيغة غير مسموحة")

    sha = hashlib.sha256(raw).hexdigest()
    safe_sem = re.sub(r"[^\w\-]+", "_", semester)[:40] or "sem"
    dept_part = "college" if department_id is None else f"dept{department_id}"
    stored_name = f"{dept_part}__{safe_sem}__{sha[:16]}{ext}"
    stored_path = os.path.join(evidence_upload_dir(), stored_name)
    with open(stored_path, "wb") as out:
        out.write(raw)

    import datetime

    now = datetime.datetime.utcnow().isoformat()
    cur = conn.cursor()
    title = (title_ar or filename).strip()[:300]
    desc = (description or "").strip()[:2000]
    ck = (checklist_key or "").strip()[:64] or None

    if is_postgresql():
        cur.execute(
            """
            INSERT INTO accreditation_evidence (
                semester, department_id, indicator_id, standard_id, checklist_key,
                title_ar, description, evidence_type, external_url,
                original_name, stored_path, mime_type, file_size, sha256,
                uploaded_by, uploaded_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'file', NULL, ?, ?, ?, ?, ?, ?, ?, 1)
            RETURNING id
            """,
            (
                semester,
                department_id,
                indicator_id,
                standard_id,
                ck,
                title,
                desc,
                filename,
                stored_path,
                mime_type,
                len(raw),
                sha,
                uploaded_by,
                now,
            ),
        )
        row = cur.fetchone()
        eid = int(_row_val(row, 0, "id") or 0)
    else:
        cur.execute(
            """
            INSERT INTO accreditation_evidence (
                semester, department_id, indicator_id, standard_id, checklist_key,
                title_ar, description, evidence_type, external_url,
                original_name, stored_path, mime_type, file_size, sha256,
                uploaded_by, uploaded_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'file', NULL, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                semester,
                department_id,
                indicator_id,
                standard_id,
                ck,
                title,
                desc,
                filename,
                stored_path,
                mime_type,
                len(raw),
                sha,
                uploaded_by,
                now,
            ),
        )
        eid = int(cur.lastrowid or 0)

    conn.commit()
    return {
        "id": eid,
        "title_ar": title,
        "download_url": f"/academic_quality/api/accreditation/evidence/file/{eid}",
    }


def save_link_evidence(
    conn,
    *,
    semester: str,
    department_id: int | None,
    external_url: str,
    uploaded_by: str,
    indicator_id: int | None = None,
    standard_id: int | None = None,
    checklist_key: str | None = None,
    title_ar: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    _ensure_evidence_table(conn)
    url = (external_url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("رابط غير صالح")

    import datetime

    now = datetime.datetime.utcnow().isoformat()
    cur = conn.cursor()
    title = (title_ar or url).strip()[:300]
    desc = (description or "").strip()[:2000]
    ck = (checklist_key or "").strip()[:64] or None

    params = (
        semester,
        department_id,
        indicator_id,
        standard_id,
        ck,
        title,
        desc,
        url,
        uploaded_by,
        now,
    )
    if is_postgresql():
        row = cur.execute(
            """
            INSERT INTO accreditation_evidence (
                semester, department_id, indicator_id, standard_id, checklist_key,
                title_ar, description, evidence_type, external_url,
                original_name, stored_path, mime_type, file_size, sha256,
                uploaded_by, uploaded_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'link', ?, '', NULL, NULL, 0, '', ?, ?, 1)
            RETURNING id
            """,
            params,
        ).fetchone()
        eid = int(_row_val(row, 0, "id") or 0)
    else:
        cur.execute(
            """
            INSERT INTO accreditation_evidence (
                semester, department_id, indicator_id, standard_id, checklist_key,
                title_ar, description, evidence_type, external_url,
                original_name, stored_path, mime_type, file_size, sha256,
                uploaded_by, uploaded_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'link', ?, '', NULL, NULL, 0, '', ?, ?, 1)
            """,
            params,
        )
        eid = int(cur.lastrowid or 0)
    conn.commit()
    return {"id": eid, "title_ar": title, "external_url": url}


def get_evidence_file(conn, evidence_id: int) -> dict[str, Any] | None:
    _ensure_evidence_table(conn)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT original_name, stored_path, mime_type, evidence_type
        FROM accreditation_evidence WHERE id = ? AND COALESCE(is_active, 1) = 1
        """,
        (int(evidence_id),),
    )
    row = cur.fetchone()
    if not row:
        return None
    if hasattr(row, "keys"):
        d = {k: row[k] for k in row.keys()}
    else:
        d = {
            "original_name": row[0],
            "stored_path": row[1],
            "mime_type": row[2],
            "evidence_type": row[3],
        }
    if d.get("evidence_type") != "file":
        return None
    return d


def soft_delete_evidence(conn, evidence_id: int) -> bool:
    _ensure_evidence_table(conn)
    cur = conn.cursor()
    cur.execute(
        "UPDATE accreditation_evidence SET is_active = 0 WHERE id = ?",
        (int(evidence_id),),
    )
    conn.commit()
    return cur.rowcount > 0
