"""تنبيهات عرض المقررات: طلبات القسم العام والتسجيلات اليتيمة.

قاعدة التشغيل:
- تحديد رئيس قسم تخصصي لمقرر عام = طلب تخطيط، لا يفتح تسجيلاً.
- الطلبة لا يُنبَّهون إلا إذا سُجّلوا فعلاً في مقرر خرج من القوائم المعتمدة.
- لا اعتماد ثانٍ من العميد أو الوكيل في أي من المسارين.
"""
from __future__ import annotations

import datetime
import logging

from backend.core.department_scope_policy import resolve_college_general_department_id
from backend.database.database import fetch_table_columns, table_exists
from backend.database.introspection import sql_notifications_user_col
from backend.services.term_offerings import (
    COLLEGE_LIST_DEPT_ID,
    KIND_GENERAL,
    STATE_PUBLISHED,
    STATUS_OFFERED,
    _general_catalog_keys,
    _shared_catalog_keys,
    get_offering_state,
    published_offered_course_names,
)

logger = logging.getLogger(__name__)

REASON_GENERAL_DROPPED = "general_not_approved"
REASON_DEPT_DROPPED = "dept_not_approved"


def _now() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat()


def _expiry(days: int) -> str:
    at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=max(int(days or 1), 1))
    return at.replace(microsecond=0).isoformat()


def _department_names(conn) -> dict[int, str]:
    if not table_exists(conn, "departments"):
        return {}
    cols = {str(c).strip().lower() for c in (fetch_table_columns(conn, "departments") or [])}
    parts = [name for name in ("name_ar", "name_en", "name", "code") if name in cols]
    expr = f"COALESCE({', '.join(parts)}, '')" if parts else "''"
    rows = conn.cursor().execute(f"SELECT id, {expr} FROM departments").fetchall()
    out: dict[int, str] = {}
    for r in rows or []:
        try:
            out[int(r[0])] = str(r[1] or "").strip()
        except (TypeError, ValueError):
            continue
    return out


def _offering_department_ids(conn, term_key: str) -> list[int]:
    if not term_key or not table_exists(conn, "term_course_offerings"):
        return []
    rows = conn.cursor().execute(
        """
        SELECT DISTINCT department_id FROM term_course_offerings
        WHERE term_key = ? AND status = ?
        """,
        (term_key, STATUS_OFFERED),
    ).fetchall()
    out = []
    for r in rows or []:
        try:
            out.append(int(r[0]))
        except (TypeError, ValueError):
            continue
    return sorted(out)


def _dept_offered_names(conn, term_key: str, department_id: int) -> list[str]:
    rows = conn.cursor().execute(
        """
        SELECT course_name FROM term_course_offerings
        WHERE term_key = ? AND department_id = ? AND status = ?
        ORDER BY course_name
        """,
        (term_key, int(department_id), STATUS_OFFERED),
    ).fetchall()
    return [str(r[0] or "").strip() for r in rows or [] if r and str(r[0] or "").strip()]


def _is_published(conn, term_key: str, department_id: int) -> bool:
    return (get_offering_state(conn, term_key, int(department_id)).get("status") or "") == STATE_PUBLISHED


def general_requests_summary(conn, *, term_key: str) -> dict:
    """ما طلبته الأقسام التخصصية من مقررات القسم العام مقابل قائمة العام."""
    gen_id = resolve_college_general_department_id(conn)
    payload = {
        "term_key": term_key or "",
        "general_department_id": gen_id,
        "general_published": False,
        "rows": [],
        "missing_count": 0,
        "requested_count": 0,
    }
    if not term_key or gen_id is None:
        return payload
    general_names, _gcodes = _general_catalog_keys(conn)
    shared_names, _scodes = _shared_catalog_keys(conn)
    general_published = _is_published(conn, term_key, int(gen_id))
    approved = {n.lower() for n in _dept_offered_names(conn, term_key, int(gen_id))}
    dept_names = _department_names(conn)
    rows = []
    for did in _offering_department_ids(conn, term_key):
        if did == int(gen_id) or did == COLLEGE_LIST_DEPT_ID:
            continue
        dept_published = _is_published(conn, term_key, did)
        for name in _dept_offered_names(conn, term_key, did):
            nl = name.lower()
            if nl in shared_names or nl not in general_names:
                continue
            rows.append(
                {
                    "department_id": did,
                    "department_name": dept_names.get(did, ""),
                    "course_name": name,
                    "department_published": dept_published,
                    "on_general_list": nl in approved,
                }
            )
    payload["general_published"] = general_published
    payload["rows"] = rows
    payload["requested_count"] = len(rows)
    payload["missing_count"] = sum(1 for r in rows if not r["on_general_list"])
    return payload


def _current_label(conn) -> str:
    try:
        from backend.services.term_basket import current_ops_label

        return (current_ops_label(conn) or "").strip()
    except Exception:
        return ""


def _live_registrations(conn) -> list[tuple[str, str]]:
    if not table_exists(conn, "registrations"):
        return []
    cols = {str(c).strip().lower() for c in (fetch_table_columns(conn, "registrations") or [])}
    label = _current_label(conn) if "semester" in cols else ""
    if label:
        rows = conn.cursor().execute(
            """
            SELECT student_id, course_name FROM registrations
            WHERE COALESCE(TRIM(semester), '') IN ('', ?)
            """,
            (label,),
        ).fetchall()
    else:
        rows = conn.cursor().execute(
            "SELECT student_id, course_name FROM registrations"
        ).fetchall()
    out = []
    for r in rows or []:
        sid = str(r[0] or "").strip()
        cname = str(r[1] or "").strip()
        if sid and cname:
            out.append((sid, cname))
    return out


def _students_index(conn) -> dict[str, dict]:
    if not table_exists(conn, "students"):
        return {}
    cols = {str(c).strip().lower() for c in (fetch_table_columns(conn, "students") or [])}
    name_col = "student_name" if "student_name" in cols else "student_id"
    dept_col = "department_id" if "department_id" in cols else "NULL"
    rows = conn.cursor().execute(
        f"SELECT student_id, {name_col}, {dept_col} FROM students"
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows or []:
        sid = str(r[0] or "").strip()
        if not sid:
            continue
        try:
            did = int(r[2]) if r[2] not in (None, "") else None
        except (TypeError, ValueError):
            did = None
        out[sid] = {"student_name": str(r[1] or "").strip(), "department_id": did}
    return out


def orphan_registrations(conn, *, term_key: str, department_id: int | None = None) -> dict:
    """تسجيلات قائمة لمقررات لم تعد ضمن القوائم المعتمدة للطالب."""
    payload = {"term_key": term_key or "", "rows": [], "students": 0, "checked_departments": []}
    if not term_key:
        return payload
    gen_id = resolve_college_general_department_id(conn)
    general_names, _gcodes = _general_catalog_keys(conn)
    shared_names, _scodes = _shared_catalog_keys(conn)
    students = _students_index(conn)
    eligible_cache: dict[int, set[str] | None] = {}
    dept_names = _department_names(conn)

    def _eligible(did: int) -> set[str] | None:
        if did not in eligible_cache:
            names, published = published_offered_course_names(
                conn, term_key=term_key, department_id=did
            )
            eligible_cache[did] = {n.lower() for n in names} if published else None
        return eligible_cache[did]

    rows = []
    affected: set[str] = set()
    for sid, cname in _live_registrations(conn):
        info = students.get(sid)
        if not info:
            continue
        did = info.get("department_id")
        if did is None:
            continue
        if department_id is not None and int(did) != int(department_id):
            continue
        allowed = _eligible(int(did))
        if allowed is None:
            continue
        nl = cname.lower()
        if nl in allowed:
            continue
        is_general = nl in general_names and nl not in shared_names
        rows.append(
            {
                "student_id": sid,
                "student_name": info.get("student_name") or "",
                "department_id": int(did),
                "department_name": dept_names.get(int(did), ""),
                "course_name": cname,
                "reason": REASON_GENERAL_DROPPED if is_general else REASON_DEPT_DROPPED,
            }
        )
        affected.add(sid)
    payload["rows"] = sorted(rows, key=lambda r: (r["department_name"], r["student_id"], r["course_name"]))
    payload["students"] = len(affected)
    payload["checked_departments"] = sorted(
        did for did, allowed in eligible_cache.items() if allowed is not None
    )
    payload["general_department_id"] = gen_id
    return payload


def _usernames_for_students(conn, student_ids: set[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not student_ids or not table_exists(conn, "users"):
        return out
    cols = {str(c).strip().lower() for c in (fetch_table_columns(conn, "users") or [])}
    if "student_id" not in cols:
        return out
    ids = sorted(student_ids)
    chunk = 400
    cur = conn.cursor()
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        ph = ",".join("?" * len(part))
        rows = cur.execute(
            f"SELECT username, student_id FROM users WHERE student_id IN ({ph})",
            tuple(part),
        ).fetchall()
        for r in rows or []:
            uname = str(r[0] or "").strip()
            sid = str(r[1] or "").strip()
            if uname and sid:
                out.setdefault(sid, []).append(uname)
    return out


def _hod_usernames(conn, department_ids: set[int]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    if not department_ids or not table_exists(conn, "users"):
        return out
    cols = {str(c).strip().lower() for c in (fetch_table_columns(conn, "users") or [])}
    if "department_id" not in cols:
        return out
    active = " AND COALESCE(is_active, 1) = 1" if "is_active" in cols else ""
    ids = sorted(department_ids)
    ph = ",".join("?" * len(ids))
    rows = conn.cursor().execute(
        f"""
        SELECT username, department_id FROM users
        WHERE role = 'head_of_department' AND department_id IN ({ph}){active}
        """,
        tuple(ids),
    ).fetchall()
    for r in rows or []:
        uname = str(r[0] or "").strip()
        try:
            did = int(r[1])
        except (TypeError, ValueError):
            continue
        if uname:
            out.setdefault(did, []).append(uname)
    return out


def _notify(conn, user: str, title: str, body: str) -> bool:
    if not user or not table_exists(conn, "notifications"):
        return False
    try:
        conn.cursor().execute(
            f"INSERT INTO notifications ({sql_notifications_user_col()}, title, body, is_read, created_at)"
            " VALUES (?, ?, ?, 0, ?)",
            (user, title, body, _now()),
        )
        return True
    except Exception:
        logger.exception("orphan notification insert failed")
        return False


def _grant_exception(conn, *, student_id: str, term_key: str, operation: str, reason: str, actor: str, days: int) -> bool:
    if not table_exists(conn, "term_operation_exceptions"):
        return False
    cur = conn.cursor()
    now = _now()
    existing = cur.execute(
        """
        SELECT id FROM term_operation_exceptions
        WHERE student_id = ? AND term_key = ? AND operation = ? AND status = 'approved'
        LIMIT 1
        """,
        (student_id, term_key, operation),
    ).fetchone()
    expires = _expiry(days)
    if existing:
        cur.execute(
            """
            UPDATE term_operation_exceptions
            SET expires_at = ?, updated_at = ?, approved_by = ?, reason = ?
            WHERE id = ?
            """,
            (expires, now, actor, reason, existing[0]),
        )
        return False
    cur.execute(
        """
        INSERT INTO term_operation_exceptions (
            student_id, term_key, operation, status, reason,
            proposed_by, approved_by, expires_at, created_at, updated_at
        ) VALUES (?, ?, ?, 'approved', ?, ?, ?, ?, ?, ?)
        """,
        (student_id, term_key, operation, reason, actor, actor, expires, now, now),
    )
    return True


def notify_orphan_registrations(
    conn,
    *,
    term_key: str,
    actor: str,
    department_id: int | None = None,
    days: int = 7,
    open_window: bool = True,
) -> dict:
    """ينبّه الطلبة المتأثرين ورؤساء أقسامهم، ويفتح إسقاط/إضافة محدوداً لهم فقط."""
    from backend.services.term_engine import OP_ADD_COURSE, OP_DROP_COURSE

    found = orphan_registrations(conn, term_key=term_key, department_id=department_id)
    rows = found.get("rows") or []
    result = {
        "term_key": term_key,
        "students": found.get("students") or 0,
        "rows": len(rows),
        "notified_students": 0,
        "notified_heads": 0,
        "exceptions": 0,
        "expires_days": int(days),
        "window_opened": bool(open_window),
    }
    if not rows:
        return result
    by_student: dict[str, list[dict]] = {}
    for r in rows:
        by_student.setdefault(r["student_id"], []).append(r)
    gen_id = found.get("general_department_id")
    dept_ids = {int(r["department_id"]) for r in rows}
    if gen_id is not None:
        dept_ids.add(int(gen_id))
    user_map = _usernames_for_students(conn, set(by_student.keys()))
    head_map = _hod_usernames(conn, dept_ids)
    reason = "مقرر خرج من القوائم المعتمدة بعد التسجيل"

    for sid, items in by_student.items():
        names = "، ".join(sorted({i["course_name"] for i in items}))
        body = (
            f"المقررات التالية لم تعد ضمن العرض المعتمد لهذا الفصل: {names}. "
            "أسقطها وأضف بديلاً متاحاً إن وُجد."
        )
        for uname in user_map.get(sid, []):
            if _notify(conn, uname, "مقرر مسجَّل لم يعد معتمداً", body):
                result["notified_students"] += 1
        if open_window:
            for op in (OP_DROP_COURSE, OP_ADD_COURSE):
                if _grant_exception(
                    conn,
                    student_id=sid,
                    term_key=term_key,
                    operation=op,
                    reason=reason,
                    actor=actor or "system",
                    days=days,
                ):
                    result["exceptions"] += 1

    per_dept: dict[int, list[dict]] = {}
    for r in rows:
        per_dept.setdefault(int(r["department_id"]), []).append(r)
    for did, items in per_dept.items():
        students_n = len({i["student_id"] for i in items})
        names = "، ".join(sorted({i["course_name"] for i in items}))
        body = f"{students_n} طالباً مسجَّلون في مقررات لم تعد معتمدة: {names}."
        for uname in head_map.get(did, []):
            if _notify(conn, uname, "تسجيلات متأثرة بمقررات غير معتمدة", body):
                result["notified_heads"] += 1
    general_rows = [r for r in rows if r["reason"] == REASON_GENERAL_DROPPED]
    if general_rows and gen_id is not None:
        names = "، ".join(sorted({r["course_name"] for r in general_rows}))
        body = f"مقررات عامة مسجَّل بها طلبة وليست ضمن قائمتك المعتمدة: {names}."
        for uname in head_map.get(int(gen_id), []):
            if _notify(conn, uname, "مقررات عامة مسجَّلة خارج القائمة المعتمدة", body):
                result["notified_heads"] += 1
    conn.commit()
    return result
