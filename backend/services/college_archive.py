"""أرشيف الكلية — خزائن خاصة + سجل مشترك."""

from __future__ import annotations

import datetime
import hashlib
import os
import re
from typing import Any

from backend.core.college_archive_catalog import (
    ARCHIVE_RECORD_TYPES,
    ARCHIVE_TYPE_CODES,
    CABINET_CODES,
    COLLEGE_CABINETS,
    PRIVATE_CABINET_CODES,
    cabinet_title,
    catalog_payload,
    suggestions_for_college_type,
)
from backend.core.department_archive_catalog import FOLLOW_UP_STATUSES
from backend.database.database import is_postgresql, table_exists
from backend.services.archive_shares import SOURCE_COLLEGE, user_can_read_shared_item
from backend.services.quality_metrics import _row_val, term_label_from_conn

ALLOWED_EXTENSIONS = frozenset(
    {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".png", ".jpg", ".jpeg", ".webp", ".txt"}
)
MAX_FILE_BYTES = 15 * 1024 * 1024


def archive_upload_dir(cabinet: str = "") -> str:
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "uploads", "college_archive")
    )
    if cabinet:
        base = os.path.join(base, re.sub(r"[^\w\-]+", "_", cabinet)[:40])
    os.makedirs(base, exist_ok=True)
    return base


def ensure_college_archive_table(conn) -> None:
    if table_exists(conn, "college_archive_items"):
        return
    cur = conn.cursor()
    if is_postgresql():
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS college_archive_items (
                id BIGSERIAL PRIMARY KEY,
                cabinet_code TEXT NOT NULL,
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
                created_by_role TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_by TEXT DEFAULT '',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
    else:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS college_archive_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cabinet_code TEXT NOT NULL,
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
                created_by_role TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_by TEXT DEFAULT '',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
    try:
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_college_archive_cab "
            "ON college_archive_items(cabinet_code, semester, record_type)"
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


def _normalize_cabinet(cabinet: str) -> str:
    c = (cabinet or "").strip().lower()
    if c not in COLLEGE_CABINETS:
        raise ValueError("خزينة غير معروفة")
    return c


def session_cabinet_owner(role: str, *, is_college_quality_lead: bool = False) -> str | None:
    """خزينة المالك الافتراضية للمستخدم."""
    r = (role or "").strip().lower()
    if r == "college_dean":
        return "dean"
    if r == "academic_vice_dean":
        return "vice_dean"
    if is_college_quality_lead or r in ("college_quality_head", "college_quality_lead"):
        return "college_quality_dept"
    return None


def is_college_archive_admin(role: str) -> bool:
    return (role or "").strip().lower() in ("admin", "admin_main", "system_admin")


def can_access_college_archive_portal(role: str, *, is_college_quality_lead: bool = False) -> bool:
    r = (role or "").strip().lower()
    if is_college_archive_admin(r):
        return True
    if r in ("college_dean", "academic_vice_dean"):
        return True
    if is_college_quality_lead:
        return True
    return False


def can_write_cabinet(
    cabinet: str,
    role: str,
    *,
    is_college_quality_lead: bool = False,
) -> bool:
    cab = _normalize_cabinet(cabinet)
    if is_college_archive_admin(role):
        return True
    if cab == "shared":
        return bool(session_cabinet_owner(role, is_college_quality_lead=is_college_quality_lead))
    owner = session_cabinet_owner(role, is_college_quality_lead=is_college_quality_lead)
    return owner == cab


def can_read_cabinet(
    cabinet: str,
    role: str,
    *,
    is_college_quality_lead: bool = False,
) -> bool:
    cab = _normalize_cabinet(cabinet)
    if is_college_archive_admin(role):
        return True
    if cab == "shared":
        return can_access_college_archive_portal(role, is_college_quality_lead=is_college_quality_lead)
    owner = session_cabinet_owner(role, is_college_quality_lead=is_college_quality_lead)
    return owner == cab


def can_read_college_item(
    conn,
    item: dict[str, Any],
    *,
    username: str,
    role: str,
    is_college_quality_lead: bool = False,
    home_department_id: int | None = None,
) -> bool:
    if not item:
        return False
    cab = str(item.get("cabinet_code") or "")
    if can_read_cabinet(cab, role, is_college_quality_lead=is_college_quality_lead):
        return True
    return user_can_read_shared_item(
        conn,
        source=SOURCE_COLLEGE,
        item_id=int(item["id"]),
        username=username,
        user_role=role,
        is_college_quality_lead=is_college_quality_lead,
        home_department_id=home_department_id,
    )


def _enrich_item(d: dict[str, Any]) -> dict[str, Any]:
    meta = ARCHIVE_RECORD_TYPES.get(d.get("record_type") or "", {})
    d["record_type_label_ar"] = meta.get("title_ar") or d.get("record_type")
    d["cabinet_title_ar"] = cabinet_title(str(d.get("cabinet_code") or ""))
    d["has_file"] = bool((d.get("stored_path") or "").strip())
    d["qaa_suggestions"] = suggestions_for_college_type(str(d.get("record_type") or ""))
    return d


_ITEM_COLS = (
    "id, cabinet_code, record_type, title_ar, ref_number, doc_date, semester, party_ar, tags, "
    "body_text, follow_up_status, original_name, stored_path, mime_type, file_size, sha256, "
    "created_by, created_by_role, created_at, updated_by, updated_at, is_active"
)


def list_college_archive_items(
    conn,
    *,
    cabinet: str,
    semester: str | None = None,
    record_type: str | None = None,
    q: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    ensure_college_archive_table(conn)
    cab = _normalize_cabinet(cabinet)
    cur = conn.cursor()
    sql = f"""
        SELECT {_ITEM_COLS}
        FROM college_archive_items
        WHERE cabinet_code = ? AND COALESCE(is_active, 1) = 1
    """
    params: list[Any] = [cab]
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
            keys = [c.strip() for c in _ITEM_COLS.split(",")]
            d = {keys[i]: r[i] for i in range(min(len(keys), len(r)))}
        out.append(_enrich_item(d))
    return out


def get_college_archive_item(conn, item_id: int) -> dict[str, Any] | None:
    ensure_college_archive_table(conn)
    cur = conn.cursor()
    row = cur.execute(
        f"SELECT {_ITEM_COLS} FROM college_archive_items WHERE id = ? AND COALESCE(is_active, 1) = 1",
        (int(item_id),),
    ).fetchone()
    if not row:
        return None
    d = _row_dict(row)
    if not d:
        keys = [c.strip() for c in _ITEM_COLS.split(",")]
        d = {keys[i]: row[i] for i in range(min(len(keys), len(row)))}
    return _enrich_item(d)


def create_college_archive_item(
    conn,
    *,
    cabinet: str,
    record_type: str,
    title_ar: str,
    actor: str,
    actor_role: str = "",
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
    ensure_college_archive_table(conn)
    cab = _normalize_cabinet(cabinet)
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
        from backend.core.security import assert_upload_magic

        assert_upload_magic(raw, oname)
        sha = hashlib.sha256(raw).hexdigest()
        safe_sem = re.sub(r"[^\w\-]+", "_", sem)[:40] or "sem"
        stored_name = f"{cab}__{rtype}__{safe_sem}__{sha[:16]}{ext}"
        stored_path = os.path.join(archive_upload_dir(cab), stored_name)
        with open(stored_path, "wb") as out:
            out.write(raw)
        fsize = len(raw)

    now = _now()
    cur = conn.cursor()
    vals = (
        cab,
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
        (actor_role or "")[:64],
        now,
        (actor or "")[:120],
        now,
    )
    if is_postgresql():
        cur.execute(
            """
            INSERT INTO college_archive_items (
                cabinet_code, record_type, title_ar, ref_number, doc_date, semester,
                party_ar, tags, body_text, follow_up_status,
                original_name, stored_path, mime_type, file_size, sha256,
                created_by, created_by_role, created_at, updated_by, updated_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            RETURNING id
            """,
            vals,
        )
        item_id = int(_row_val(cur.fetchone(), 0, "id") or 0)
    else:
        cur.execute(
            """
            INSERT INTO college_archive_items (
                cabinet_code, record_type, title_ar, ref_number, doc_date, semester,
                party_ar, tags, body_text, follow_up_status,
                original_name, stored_path, mime_type, file_size, sha256,
                created_by, created_by_role, created_at, updated_by, updated_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            vals,
        )
        item_id = int(
            getattr(cur, "lastrowid", None)
            or cur.execute("SELECT last_insert_rowid()").fetchone()[0]
        )
    conn.commit()
    return get_college_archive_item(conn, item_id) or {"id": item_id, "status": "ok"}


def soft_delete_college_archive_item(conn, item_id: int, *, actor: str = "") -> bool:
    ensure_college_archive_table(conn)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE college_archive_items
        SET is_active = 0, updated_at = ?, updated_by = ?
        WHERE id = ? AND COALESCE(is_active, 1) = 1
        """,
        (_now(), (actor or "")[:120], int(item_id)),
    )
    conn.commit()
    return cur.rowcount > 0


def list_items_by_ids(conn, item_ids: list[int]) -> list[dict[str, Any]]:
    ensure_college_archive_table(conn)
    if not item_ids:
        return []
    cur = conn.cursor()
    out = []
    for iid in item_ids:
        row = cur.execute(
            f"SELECT {_ITEM_COLS} FROM college_archive_items WHERE id = ? AND COALESCE(is_active, 1) = 1",
            (int(iid),),
        ).fetchone()
        if not row:
            continue
        d = _row_dict(row)
        if not d:
            keys = [c.strip() for c in _ITEM_COLS.split(",")]
            d = {keys[i]: row[i] for i in range(min(len(keys), len(row)))}
        out.append(_enrich_item(d))
    return out


def visible_cabinets_for_user(role: str, *, is_college_quality_lead: bool = False) -> list[dict[str, Any]]:
    out = []
    for code in CABINET_CODES:
        if can_read_cabinet(code, role, is_college_quality_lead=is_college_quality_lead):
            meta = dict(COLLEGE_CABINETS[code])
            meta["can_write"] = can_write_cabinet(
                code, role, is_college_quality_lead=is_college_quality_lead
            )
            out.append(meta)
    return out
