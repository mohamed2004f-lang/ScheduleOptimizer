"""تقرير تغطية تعبئة الاستبيانات — أعداد مجمّعة + قائمة المتأخرين فقط (للتذكير)."""

from __future__ import annotations

import logging
from typing import Any

from backend.core.department_scope_policy import head_home_department_id
from backend.core.survey_platform import RESPONDENT_ROLE_LABELS
from backend.database.database import fetch_table_columns, table_exists
from backend.services.course_evaluations import list_pending_course_evaluations
from backend.services.multi_surveys import (
    ensure_survey_templates_seeded,
    list_pending_for_respondent_role,
    list_templates,
)
from backend.services.quality_metrics import term_label_from_conn

logger = logging.getLogger(__name__)


ROLE_KEYS = ("student", "instructor", "supervisor", "staff")

SCOPE_ADMIN_ROLES = frozenset(
    {"admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean"}
)


def _row_val(row, idx: int = 0, key: str | None = None):
    if row is None:
        return None
    if key and hasattr(row, "keys"):
        try:
            return row[key]
        except (KeyError, TypeError):
            pass
    try:
        return row[idx]
    except (IndexError, TypeError):
        return None


def _department_label(conn, department_id: int | None) -> str:
    if department_id is None:
        return "كل الكلية"
    cur = conn.cursor()
    row = cur.execute(
        "SELECT COALESCE(name_ar, code, '') FROM departments WHERE id = ? LIMIT 1",
        (int(department_id),),
    ).fetchone()
    label = str(_row_val(row, 0) or "").strip()
    return label or f"قسم #{department_id}"


def _table_cols(conn, table: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    return {c.lower() for c in fetch_table_columns(conn, table)}


def _active_predicate(cols: set[str], alias: str) -> str:
    if "is_active" in cols:
        return f"COALESCE({alias}.is_active, 1) = 1"
    return "1=1"


def _safe_student_dept_sql(conn, alias: str, dept_id: int) -> tuple[str, tuple[Any, ...]]:
    """فلتر قسم للطالب — يتكيّف مع الأعمدة المتوفرة في قاعدة الإنتاج."""
    st_cols = _table_cols(conn, "students")
    parts: list[str] = []
    params: list[Any] = []
    if "department_id" in st_cols:
        parts.append(f"{alias}.department_id = ?")
        params.append(int(dept_id))
    if table_exists(conn, "programs"):
        if "current_program_id" in st_cols:
            parts.append(
                f"{alias}.current_program_id IN (SELECT id FROM programs WHERE department_id = ?)"
            )
            params.append(int(dept_id))
        if "admission_program_id" in st_cols:
            parts.append(
                f"{alias}.admission_program_id IN (SELECT id FROM programs WHERE department_id = ?)"
            )
            params.append(int(dept_id))
    if not parts:
        return "", ()
    return "(" + " OR ".join(parts) + ")", tuple(params)


def resolve_completion_department_id(
    conn,
    *,
    role: str,
    username: str | None,
    requested_department_id: int | None = None,
    session_scope_id: int | None = None,
) -> tuple[int | None, bool]:
    """
    يُرجع (department_id, can_pick_department).
    None = كل الكلية. رئيس القسم مقيّد بقسمه دائماً.
    """
    role = (role or "").strip()
    if role == "head_of_department":
        hid = head_home_department_id(conn, username)
        return (int(hid) if hid is not None else None, False)
    if role in SCOPE_ADMIN_ROLES:
        if requested_department_id is not None:
            return int(requested_department_id), True
        if session_scope_id is not None:
            return int(session_scope_id), True
        return None, True
    return None, False


def list_departments_for_completion(conn) -> list[dict[str, Any]]:
    if not table_exists(conn, "departments"):
        return []
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, COALESCE(name_ar, code, '') AS label
        FROM departments
        ORDER BY COALESCE(name_ar, code, '')
        """
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({"id": int(_row_val(r, 0)), "label": str(_row_val(r, 1) or "")})
    return out


def _missing_platform(
    conn,
    *,
    respondent_role: str,
    respondent_id: str,
    semester: str,
    department_id: int | None,
    session_data: dict,
) -> list[str]:
    pending = list_pending_for_respondent_role(
        conn,
        respondent_role=respondent_role,
        session_data=session_data,
        semester=semester,
        department_id=department_id,
    )
    missing = [str(p.get("title_ar") or p.get("code") or "استبيان") for p in pending]
    if respondent_role in ("instructor", "supervisor") and department_id is None:
        scoped = [
            t
            for t in list_templates(conn)
            if (t.get("respondent_role") or "") == respondent_role
            and int(t.get("department_scoped") or 0)
            and not int(t.get("legacy_course_eval") or 0)
        ]
        if scoped:
            missing.append("استبيانات القسم (يتطلب ربط قسم بالحساب)")
    return missing


def _list_students_in_scope(conn, *, department_id: int | None) -> list[dict[str, Any]]:
    if not table_exists(conn, "students") or not table_exists(conn, "registrations"):
        return []
    st_cols = _table_cols(conn, "students")
    cur = conn.cursor()
    active_sql = (
        " AND COALESCE(s.enrollment_status, 'active') = 'active'"
        if "enrollment_status" in st_cols
        else ""
    )
    dept_sql = ""
    dept_params: tuple[Any, ...] = ()
    if department_id is not None:
        frag, dept_params = _safe_student_dept_sql(conn, "s", int(department_id))
        if frag:
            dept_sql = f" AND {frag}"
        else:
            dept_sql = " AND s.department_id = ?"
            dept_params = (int(department_id),)
    uni_sel = (
        "COALESCE(NULLIF(TRIM(s.university_number), ''), s.student_id)"
        if "university_number" in st_cols
        else "s.student_id"
    )
    sql = f"""
        SELECT DISTINCT s.student_id,
               COALESCE(s.student_name, '') AS name,
               {uni_sel} AS display_id
        FROM students s
        INNER JOIN registrations r ON r.student_id = s.student_id
        WHERE COALESCE(s.student_id, '') <> '' {active_sql}{dept_sql}
        ORDER BY name, display_id
    """
    rows = cur.execute(sql, dept_params).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        sid = str(_row_val(row, 0, "student_id") or "").strip()
        if not sid:
            continue
        display_id = str(_row_val(row, 2, "display_id") or sid).strip() or sid
        out.append(
            {
                "respondent_id": sid,
                "display_id": display_id,
                "name": str(_row_val(row, 1, "name") or "").strip() or sid,
            }
        )
    return out


def _list_instructors_in_scope(conn, *, department_id: int | None) -> list[dict[str, Any]]:
    if not table_exists(conn, "instructors"):
        return []
    ins_cols = _table_cols(conn, "instructors")
    usr_cols = _table_cols(conn, "users")
    ins_active = _active_predicate(ins_cols, "i")
    usr_active = _active_predicate(usr_cols, "u") if usr_cols else "1=1"
    user_sub = ""
    if table_exists(conn, "users"):
        user_sub = f"""
               (
                   SELECT u.username FROM users u
                   WHERE u.instructor_id = i.id AND {usr_active}
                   LIMIT 1
               ) AS username
        """
    else:
        user_sub = "NULL AS username"
    cur = conn.cursor()
    sql = f"""
        SELECT i.id,
               COALESCE(i.name, '') AS name,
               i.department_id,
               {user_sub}
        FROM instructors i
        WHERE {ins_active}
    """
    params: list[Any] = []
    if department_id is not None and "department_id" in ins_cols:
        sql += " AND i.department_id = ?"
        params.append(int(department_id))
    sql += " ORDER BY name, id"
    rows = cur.execute(sql, tuple(params)).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        iid = int(_row_val(row, 0, "id") or 0)
        if not iid:
            continue
        out.append(
            {
                "respondent_id": str(iid),
                "display_id": str(iid),
                "name": str(_row_val(row, 1, "name") or "").strip() or f"أستاذ #{iid}",
                "department_id": _row_val(row, 2, "department_id"),
                "username": str(_row_val(row, 3, "username") or "").strip(),
            }
        )
    return out


def _list_supervisors_in_scope(conn, *, department_id: int | None) -> list[dict[str, Any]]:
    if not table_exists(conn, "users") or not table_exists(conn, "instructors"):
        return []
    ins_cols = _table_cols(conn, "instructors")
    usr_cols = _table_cols(conn, "users")
    ins_active = _active_predicate(ins_cols, "i")
    usr_active = _active_predicate(usr_cols, "u")
    sup_pred = "u.role = 'supervisor'"
    if "is_supervisor" in usr_cols:
        sup_pred = f"({sup_pred} OR COALESCE(u.is_supervisor, 0) = 1)"
    cur = conn.cursor()
    sql = f"""
        SELECT DISTINCT i.id,
               COALESCE(i.name, '') AS name,
               i.department_id,
               (
                   SELECT u2.username FROM users u2
                   WHERE u2.instructor_id = i.id AND {_active_predicate(usr_cols, "u2")}
                   LIMIT 1
               ) AS username
        FROM users u
        INNER JOIN instructors i ON i.id = u.instructor_id
        WHERE {usr_active}
          AND {ins_active}
          AND u.instructor_id IS NOT NULL
          AND {sup_pred}
    """
    params: list[Any] = []
    if department_id is not None and "department_id" in ins_cols:
        sql += " AND i.department_id = ?"
        params.append(int(department_id))
    sql += " ORDER BY name, id"
    rows = cur.execute(sql, tuple(params)).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        iid = int(_row_val(row, 0, "id") or 0)
        if not iid:
            continue
        out.append(
            {
                "respondent_id": str(iid),
                "display_id": str(iid),
                "name": str(_row_val(row, 1, "name") or "").strip() or f"مشرف #{iid}",
                "department_id": _row_val(row, 2, "department_id"),
                "username": str(_row_val(row, 3, "username") or "").strip(),
            }
        )
    return out


def _list_staff_in_scope(conn, *, department_id: int | None) -> list[dict[str, Any]]:
    if not table_exists(conn, "users"):
        return []
    usr_cols = _table_cols(conn, "users")
    usr_active = _active_predicate(usr_cols, "u")
    dept_sel = "COALESCE(u.department_id, 0) AS department_id" if "department_id" in usr_cols else "0 AS department_id"
    cur = conn.cursor()
    sql = f"""
        SELECT u.username, {dept_sel}
        FROM users u
        WHERE u.role = 'staff' AND {usr_active}
    """
    params: list[Any] = []
    if department_id is not None and "department_id" in usr_cols:
        sql += " AND u.department_id = ?"
        params.append(int(department_id))
    sql += " ORDER BY u.username"
    rows = cur.execute(sql, tuple(params)).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        uname = str(_row_val(row, 0, "username") or "").strip()
        if not uname:
            continue
        out.append(
            {
                "respondent_id": uname,
                "display_id": uname,
                "name": uname,
                "department_id": _row_val(row, 1, "department_id"),
                "username": uname,
            }
        )
    return out


def _student_missing_items(
    conn,
    *,
    student_id: str,
    semester: str,
) -> list[str]:
    sid = (student_id or "").strip()
    if not sid:
        return []
    missing: list[str] = []
    for p in list_pending_course_evaluations(conn, sid, semester=semester):
        missing.append(str(p.get("title_ar") or p.get("course_name") or "تقييم مقرر"))
    session_data = {"student_id": sid, "user": sid}
    for title in _missing_platform(
        conn,
        respondent_role="student",
        respondent_id=sid,
        semester=semester,
        department_id=None,
        session_data=session_data,
    ):
        if title not in missing:
            missing.append(title)
    return missing


def _person_missing_items(
    conn,
    *,
    role_key: str,
    person: dict[str, Any],
    semester: str,
) -> list[str]:
    if role_key == "student":
        return _student_missing_items(conn, student_id=person["respondent_id"], semester=semester)
    dept_raw = person.get("department_id")
    dept_id: int | None
    try:
        dept_id = int(dept_raw) if dept_raw not in (None, "", 0) else None
    except (TypeError, ValueError):
        dept_id = None
    rid = person["respondent_id"]
    if role_key == "instructor":
        try:
            iid = int(rid)
        except (TypeError, ValueError):
            return ["معرّف أستاذ غير صالح"]
        session_data = {
            "instructor_id": iid,
            "user": person.get("username") or rid,
        }
        return _missing_platform(
            conn,
            respondent_role="instructor",
            respondent_id=str(rid),
            semester=semester,
            department_id=dept_id,
            session_data=session_data,
        )
    if role_key == "supervisor":
        try:
            iid = int(rid)
        except (TypeError, ValueError):
            return ["معرّف مشرف غير صالح"]
        session_data = {
            "instructor_id": iid,
            "user": person.get("username") or rid,
        }
        return _missing_platform(
            conn,
            respondent_role="supervisor",
            respondent_id=str(rid),
            semester=semester,
            department_id=dept_id,
            session_data=session_data,
        )
    if role_key == "staff":
        session_data = {"user": rid}
        return _missing_platform(
            conn,
            respondent_role="staff",
            respondent_id=str(rid),
            semester=semester,
            department_id=None,
            session_data=session_data,
        )
    return []


def _has_any_survey_submission(
    conn,
    *,
    respondent_role: str,
    respondent_id: str,
    semester: str,
) -> bool:
    if not table_exists(conn, "survey_responses"):
        return False
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT 1 FROM survey_responses
        WHERE respondent_role = ? AND respondent_id = ? AND semester = ?
          AND status = 'submitted'
        LIMIT 1
        """,
        (respondent_role, str(respondent_id), semester),
    ).fetchone()
    return row is not None


def _student_has_any_submission(conn, student_id: str, semester: str) -> bool:
    sid = (student_id or "").strip()
    if not sid:
        return False
    if table_exists(conn, "course_evaluations"):
        cur = conn.cursor()
        row = cur.execute(
            "SELECT 1 FROM course_evaluations WHERE student_id = ? AND semester = ? LIMIT 1",
            (sid, semester),
        ).fetchone()
        if row is not None:
            return True
    return _has_any_survey_submission(
        conn, respondent_role="student", respondent_id=sid, semester=semester
    )


def _classify_pending_status(
    conn,
    *,
    role_key: str,
    person: dict[str, Any],
    semester: str,
    missing: list[str],
) -> str:
    rid = person["respondent_id"]
    if role_key == "student":
        return "partial" if _student_has_any_submission(conn, rid, semester) else "not_started"
    resp_role = role_key if role_key in ("instructor", "supervisor", "staff") else role_key
    if _has_any_survey_submission(conn, respondent_role=resp_role, respondent_id=rid, semester=semester):
        return "partial"
    return "not_started"


def _role_universe(conn, role_key: str, department_id: int | None) -> list[dict[str, Any]]:
    if role_key == "student":
        return _list_students_in_scope(conn, department_id=department_id)
    if role_key == "instructor":
        return _list_instructors_in_scope(conn, department_id=department_id)
    if role_key == "supervisor":
        return _list_supervisors_in_scope(conn, department_id=department_id)
    if role_key == "staff":
        return _list_staff_in_scope(conn, department_id=department_id)
    return []


def build_role_completion(
    conn,
    *,
    role_key: str,
    semester: str,
    department_id: int | None,
) -> dict[str, Any]:
    universe = _role_universe(conn, role_key, department_id)
    pending_rows: list[dict[str, Any]] = []
    complete_count = 0
    partial_count = 0
    not_started_count = 0

    for person in universe:
        try:
            missing = _person_missing_items(
                conn, role_key=role_key, person=person, semester=semester
            )
        except Exception as exc:
            logger.warning(
                "survey completion check failed role=%s id=%s: %s",
                role_key,
                person.get("respondent_id"),
                exc,
            )
            missing = ["تعذّر التحقق — راجع بيانات الحساب أو التسجيلات"]
        if not missing:
            complete_count += 1
            continue
        status = _classify_pending_status(
            conn, role_key=role_key, person=person, semester=semester, missing=missing
        )
        if status == "not_started":
            not_started_count += 1
        else:
            partial_count += 1

        pending_rows.append(
            {
                "respondent_id": person["respondent_id"],
                "display_id": person.get("display_id") or person["respondent_id"],
                "name": person.get("name") or person["respondent_id"],
                "status": status,
                "missing_items": missing,
                "missing_summary": "؛ ".join(missing[:4])
                + ("…" if len(missing) > 4 else ""),
            }
        )

    total = len(universe)
    pending_total = len(pending_rows)
    pct = round((complete_count / total) * 100, 1) if total else 0.0
    return {
        "role": role_key,
        "role_label": RESPONDENT_ROLE_LABELS.get(role_key, role_key),
        "total": total,
        "completed": complete_count,
        "partial": partial_count,
        "not_started": not_started_count,
        "pending": pending_total,
        "completion_percent": pct,
        "pending_people": pending_rows,
    }


def build_survey_completion_report(
    conn,
    *,
    semester: str | None = None,
    department_id: int | None = None,
) -> dict[str, Any]:
    ensure_survey_templates_seeded(conn)
    sem = (semester or "").strip() or term_label_from_conn(conn)
    roles = [build_role_completion(conn, role_key=rk, semester=sem, department_id=department_id) for rk in ROLE_KEYS]
    summary_completed = sum(int(b.get("completed") or 0) for b in roles)
    summary_total = sum(int(b.get("total") or 0) for b in roles)
    return {
        "semester": sem,
        "department_id": department_id,
        "department_label": _department_label(conn, department_id),
        "roles": roles,
        "summary_completed": summary_completed,
        "summary_total": summary_total,
        "generated_at": __import__("datetime").datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


def export_pending_completion_xlsx(report: dict[str, Any]) -> bytes:
    import io

    import pandas as pd

    rows: list[dict[str, Any]] = []
    for block in report.get("roles") or []:
        role_label = block.get("role_label") or block.get("role")
        for p in block.get("pending_people") or []:
            rows.append(
                {
                    "الفئة": role_label,
                    "الاسم": p.get("name"),
                    "المعرّف": p.get("display_id"),
                    "الحالة": "لم يبدأ" if p.get("status") == "not_started" else "جزئي",
                    "المتبقي": "؛ ".join(p.get("missing_items") or []),
                }
            )
    df = pd.DataFrame(rows or [{"ملاحظة": "لا يوجد متأخرون في النطاق المحدد"}])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="متأخرون")
    return buf.getvalue()
