"""الموجة 3: سلة التسجيلات الحية لا تُخلط بين فصلين."""
from __future__ import annotations

import logging
from typing import Any

from backend.database.database import fetch_table_columns, table_exists
from backend.services.term_engine import (
    _now_iso,
    ensure_term_engine_tables,
    parse_ops_term,
)

logger = logging.getLogger("backend.services.term_basket")

CODE_BASKET_BLOCKED = "basket_unmigrated"


class BasketSwitchBlocked(ValueError):
    def __init__(self, message: str, payload: dict[str, Any]):
        super().__init__(message)
        self.payload = payload
        self.code = CODE_BASKET_BLOCKED


def registrations_has_semester(conn) -> bool:
    try:
        return "semester" in (fetch_table_columns(conn, "registrations") or [])
    except Exception:
        return False


def current_ops_label(conn) -> str:
    from backend.services.utilities import get_current_term

    name, year = get_current_term(conn=conn)
    return f"{(name or '').strip()} {(year or '').strip()}".strip()


def stamp_registration_semester(cur, conn, student_id: str, course_name: str, semester: str | None = None) -> None:
    if not registrations_has_semester(conn):
        return
    label = (semester or "").strip() or current_ops_label(conn)
    if not label:
        return
    try:
        cur.execute(
            """
            UPDATE registrations
            SET semester = ?
            WHERE student_id = ? AND course_name = ?
              AND (semester IS NULL OR TRIM(semester) = '' OR semester = ?)
            """,
            (label, student_id, course_name, label),
        )
    except Exception:
        logger.exception("stamp registration semester failed")


def backfill_live_basket_semester(conn) -> int:
    if not registrations_has_semester(conn):
        return 0
    label = current_ops_label(conn)
    if not label:
        return 0
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE registrations
        SET semester = ?
        WHERE semester IS NULL OR TRIM(semester) = ''
        """,
        (label,),
    )
    n = int(cur.rowcount or 0)
    try:
        conn.commit()
    except Exception:
        pass
    return n


def live_basket_summary(conn) -> dict[str, Any]:
    cur = conn.cursor()
    n_rows = int(cur.execute("SELECT COUNT(*) FROM registrations").fetchone()[0] or 0)
    n_students = int(
        cur.execute("SELECT COUNT(DISTINCT student_id) FROM registrations").fetchone()[0] or 0
    )
    terms: list[str] = []
    if registrations_has_semester(conn):
        rows = cur.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(semester), ''), '') AS sem, COUNT(*)
            FROM registrations GROUP BY 1
            """
        ).fetchall()
        for r in rows:
            terms.append(str(r[0] if not hasattr(r, "keys") else r["sem"] or ""))
    pending = 0
    if table_exists(conn, "registration_requests"):
        try:
            pending = int(
                cur.execute(
                    "SELECT COUNT(*) FROM registration_requests WHERE status = 'pending'"
                ).fetchone()[0]
                or 0
            )
        except Exception:
            pending = 0
    return {
        "rows": n_rows,
        "students": n_students,
        "semesters": terms,
        "pending_requests": pending,
        "current_ops_label": current_ops_label(conn),
    }


def unmigrated_students(conn, new_ops_label: str, limit: int = 200) -> list[dict[str, Any]]:
    """طلبة السلة الحية الذين لا ينتمون للفصل الجديد."""
    new_label = (new_ops_label or "").strip()
    cur = conn.cursor()
    has_sem = registrations_has_semester(conn)
    if has_sem:
        rows = cur.execute(
            """
            SELECT r.student_id,
                   COALESCE(s.student_name, '') AS student_name,
                   COUNT(*) AS courses,
                   COALESCE(NULLIF(TRIM(r.semester), ''), '') AS semester
            FROM registrations r
            LEFT JOIN students s ON s.student_id = r.student_id
            WHERE COALESCE(NULLIF(TRIM(r.semester), ''), '') != ?
            GROUP BY r.student_id
            ORDER BY r.student_id
            LIMIT ?
            """,
            (new_label, int(limit)),
        ).fetchall()
    else:
        rows = cur.execute(
            """
            SELECT r.student_id,
                   COALESCE(s.student_name, '') AS student_name,
                   COUNT(*) AS courses,
                   '' AS semester
            FROM registrations r
            LEFT JOIN students s ON s.student_id = r.student_id
            GROUP BY r.student_id
            ORDER BY r.student_id
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    out = []
    for r in rows or []:
        if hasattr(r, "keys"):
            out.append(
                {
                    "student_id": r["student_id"],
                    "student_name": r["student_name"],
                    "courses": int(r["courses"] or 0),
                    "semester": r["semester"],
                }
            )
        else:
            out.append(
                {
                    "student_id": r[0],
                    "student_name": r[1],
                    "courses": int(r[2] or 0),
                    "semester": r[3],
                }
            )
    return out


def archive_live_basket(conn, *, actor: str = "", reason: str = "") -> dict[str, Any]:
    """ينسخ السلة الحية إلى الأرشيف ثم يفرّغها. الطلبات المعلّقة لا تُحذف."""
    ensure_term_engine_tables(conn)
    if not table_exists(conn, "term_registration_archives"):
        raise ValueError("جدول أرشيف السلة غير موجود")
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise ValueError("سبب الأرشفة مطلوب (٥ أحرف على الأقل).")
    label = current_ops_label(conn) or "unknown"
    now = _now_iso()
    cur = conn.cursor()
    cols = fetch_table_columns(conn, "registrations") or []
    has_pc = "program_course_id" in cols
    has_tg = "teaching_group_id" in cols
    has_sem = "semester" in cols
    select = "student_id, course_name"
    if has_pc:
        select += ", program_course_id"
    if has_tg:
        select += ", teaching_group_id"
    if has_sem:
        select += ", semester"
    rows = cur.execute(f"SELECT {select} FROM registrations").fetchall()
    n = 0
    for r in rows or []:
        if hasattr(r, "keys"):
            sid, cname = r["student_id"], r["course_name"]
            pcid = r["program_course_id"] if has_pc else None
            gid = r["teaching_group_id"] if has_tg else None
            sem = r["semester"] if has_sem else label
        else:
            sid, cname = r[0], r[1]
            idx = 2
            pcid = r[idx] if has_pc else None
            if has_pc:
                idx += 1
            gid = r[idx] if has_tg else None
            if has_tg:
                idx += 1
            sem = r[idx] if has_sem else label
        cur.execute(
            """
            INSERT INTO term_registration_archives (
                archived_term, student_id, course_name, program_course_id,
                teaching_group_id, semester, archived_at, archived_by, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (label, sid, cname, pcid, gid, sem or label, now, actor or "", reason),
        )
        n += 1
    cur.execute("DELETE FROM registrations")
    try:
        conn.commit()
    except Exception:
        pass
    return {
        "status": "ok",
        "archived_term": label,
        "archived_rows": n,
        "pending_requests_kept": True,
    }


def assert_current_term_switch_allowed(
    conn,
    *,
    term_name: str,
    term_year: str,
    archive: bool = False,
    actor: str = "",
    reason: str = "",
) -> dict[str, Any] | None:
    """يمنع تعيين فصل جديد وفي السلة طلبة غير مُرحَّلين ما لم تُطلب الأرشفة."""
    parsed = parse_ops_term(term_name, term_year)
    new_label = parsed["ops_label"] if parsed else f"{term_name} {term_year}".strip()
    old_label = current_ops_label(conn)
    if old_label and new_label == old_label:
        return None
    summary = live_basket_summary(conn)
    if int(summary.get("rows") or 0) == 0:
        return None
    leftover = unmigrated_students(conn, new_label, limit=500)
    if not leftover:
        return None
    if archive:
        archived = archive_live_basket(conn, actor=actor, reason=reason or "أرشفة إجبارية قبل تعيين فصل جديد")
        return {"archived": archived}
    raise BasketSwitchBlocked(
        "لا يمكن تعيين فصل حالي جديد وفي السلة طلبة غير مُرحَّلين. أرشف السلة أولاً أو رحّل التسجيلات.",
        {
            "code": CODE_BASKET_BLOCKED,
            "current_ops_label": old_label,
            "new_ops_label": new_label,
            "unmigrated_count": len(leftover),
            "unmigrated": leftover[:50],
            "pending_requests": summary.get("pending_requests") or 0,
        },
    )
