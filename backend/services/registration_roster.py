"""
قوائم التسجيل الفعلي (مقررات + طلبة) — مصدر مشترك لتقرير التسجيل والحضور.
"""
from __future__ import annotations

from typing import Any

from backend.core.department_scope_policy import (
    resolve_registration_course_scope_sql,
    resolve_scope_sql_for_aliased_student,
)
from backend.database.database import fetch_table_columns, table_exists
from backend.services.attendance_export_core import (
    _SQL_REG_ACTIVE_STUDENT,
    _attendance_course_key,
    build_schedule_semester_match,
    course_rows_with_meta,
)


def _active_student_join(alias: str = "s") -> str:
    return (
        f"INNER JOIN students {alias} ON {alias}.student_id = r.student_id "
        f"AND COALESCE({alias}.enrollment_status, 'active') = 'active'"
    )


def _scope_clauses(conn, actor_username: str, student_alias: str = "s") -> tuple[str, str, tuple]:
    """(student_and, course_and, params) — فلاتر نطاق الطالب والمقرر."""
    scope_sql, scope_params = resolve_scope_sql_for_aliased_student(
        conn, actor_username, student_alias
    )
    course_scope_sql, course_scope_params = resolve_registration_course_scope_sql(
        conn, actor_username
    )
    student_and = f" AND ({scope_sql})" if scope_sql else ""
    course_and = course_scope_sql or ""
    params = tuple(scope_params or ()) + tuple(course_scope_params or ())
    return student_and, course_and, params


def registration_course_count_rows(conn, actor_username: str) -> list[dict[str, Any]]:
    """صف لكل مقرر: عدد الطلبة المسجّلين فعلياً."""
    cur = conn.cursor()
    student_and, course_and, params = _scope_clauses(conn, actor_username, "s")
    q = f"""
        SELECT r.course_name,
               COALESCE(c.course_code, '') AS course_code,
               COALESCE(c.units, 0) AS units,
               COUNT(DISTINCT r.student_id) AS student_count
        FROM registrations r
        {_active_student_join('s')}
        LEFT JOIN courses c ON c.course_name = r.course_name
        WHERE COALESCE(r.course_name, '') <> ''
          {student_and}
          {course_and}
        GROUP BY r.course_name, c.course_code, c.units
        ORDER BY r.course_name
    """
    rows = cur.execute(q, params).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows or []:
        d = dict(row)
        items.append({
            "course_name": (d.get("course_name") or "").strip(),
            "course_code": (d.get("course_code") or "").strip(),
            "units": int(d.get("units") or 0),
            "student_count": int(d.get("student_count") or 0),
        })
    return items


def registration_course_roster(
    conn,
    course_name: str,
    actor_username: str,
) -> list[dict[str, Any]] | None:
    """
    طلبة مقرر واحد من التسجيل الفعلي.
    يُرجع None إذا المقرر خارج نطاق الفاعل.
    """
    cname = (course_name or "").strip()
    if not cname:
        return None
    allowed = {r["course_name"].lower() for r in registration_course_count_rows(conn, actor_username)}
    if cname.lower() not in allowed:
        return None
    cur = conn.cursor()
    cols = fetch_table_columns(conn, "students")
    has_uni = "university_number" in cols
    uni_sel = ", COALESCE(s.university_number, '') AS university_number" if has_uni else ", '' AS university_number"
    student_and, course_and, params = _scope_clauses(conn, actor_username, "s")
    q = f"""
        SELECT DISTINCT r.student_id,
               COALESCE(s.student_name, '') AS student_name
               {uni_sel}
        FROM registrations r
        {_active_student_join('s')}
        LEFT JOIN courses c ON c.course_name = r.course_name
        WHERE LOWER(TRIM(COALESCE(r.course_name, ''))) = LOWER(TRIM(?))
          {student_and}
          {course_and}
        ORDER BY COALESCE(s.student_name, ''), r.student_id
    """
    rows = cur.execute(q, (cname,) + params).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows or []:
        d = dict(row)
        sid = (d.get("student_id") or "").strip()
        if not sid:
            continue
        out.append({
            "student_id": sid,
            "student_name": (d.get("student_name") or "").strip(),
            "university_number": (d.get("university_number") or "").strip(),
        })
    return out


def _schedule_course_keys(
    cur,
    term_name: str | None,
    term_year: str | None,
    *,
    instructor_name: str | None = None,
) -> set[str]:
    sem_sql, sem_bind = build_schedule_semester_match("s.semester", term_name, term_year)
    extra = ""
    params: list = list(sem_bind)
    if instructor_name:
        extra = " AND TRIM(COALESCE(s.instructor, '')) = TRIM(?)"
        params.append(instructor_name)
    try:
        rows = cur.execute(
            f"""
            SELECT DISTINCT TRIM(COALESCE(s.course_name, ''))
            FROM schedule s
            WHERE TRIM(COALESCE(s.course_name, '')) <> ''
              AND ({sem_sql})
              {extra}
            """,
            tuple(params),
        ).fetchall()
    except Exception:
        return set()
    return {_attendance_course_key(r[0]) for r in rows if r and r[0]}


def _teaching_group_course_keys(
    conn,
    cur,
    term_name: str | None,
    term_year: str | None,
    instructor_id: int | None,
) -> set[str]:
    if not instructor_id or not table_exists(conn, "teaching_groups"):
        return set()
    sem = f"{(term_name or '').strip()} {(term_year or '').strip()}".strip()
    if not sem:
        return set()
    try:
        rows = cur.execute(
            """
            SELECT DISTINCT TRIM(COALESCE(course_name, ''))
            FROM teaching_groups
            WHERE TRIM(COALESCE(course_name, '')) <> ''
              AND COALESCE(is_active, 1) = 1
              AND instructor_id = ?
              AND TRIM(COALESCE(semester, '')) = TRIM(?)
            """,
            (int(instructor_id), sem),
        ).fetchall()
    except Exception:
        return set()
    return {_attendance_course_key(r[0]) for r in rows if r and r[0]}


def registration_attendance_course_rows(
    conn,
    cur,
    term_name: str | None,
    term_year: str | None,
    actor_username: str,
    *,
    dept_scope_id: int | None = None,
    role_bucket: str = "",
    instructor_id: int | None = None,
    instructor_name: str | None = None,
    supervisor_instructor_id: int | None = None,
    student_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    مقررات الحضور من التسجيل الفعلي (بدون اشتراط وجود صف جدول).
    in_schedule: هل المقرر له صف في جدول الفصل الحالي.
  registration_only: ليس في الجدول بعد.
    """
    student_and, course_and, scope_params = _scope_clauses(conn, actor_username, "st")
    extra_where = ""
    extra_params: list = []
    rb = (role_bucket or "").strip()

    if supervisor_instructor_id is not None:
        extra_where += " AND r.student_id IN (SELECT student_id FROM student_supervisor WHERE instructor_id = ?)"
        extra_params.append(int(supervisor_instructor_id))
    elif student_id:
        extra_where += " AND r.student_id = ?"
        extra_params.append(str(student_id).strip())
    elif rb == "instructor" and instructor_id is not None:
        sched_keys = _schedule_course_keys(
            cur, term_name, term_year, instructor_name=instructor_name
        )
        tg_keys = _teaching_group_course_keys(
            conn, cur, term_name, term_year, instructor_id
        )
        allowed_keys = sched_keys | tg_keys
        if not allowed_keys:
            return []
        # فلترة لاحقة بعد الجلب

    dept_join = ""
    dept_and = ""
    dept_params: tuple = ()
    if dept_scope_id is not None:
        try:
            scols = fetch_table_columns(conn, "schedule")
            ccols = fetch_table_columns(conn, "courses")
        except Exception:
            scols, ccols = [], []
        if "department_id" in scols:
            dept_and = " AND COALESCE(c.owning_department_id, -987654321) = ? "
            dept_params = (int(dept_scope_id),)
        elif "owning_department_id" in (ccols or []):
            dept_and = " AND COALESCE(c.owning_department_id, -987654321) = ? "
            dept_params = (int(dept_scope_id),)

    q = f"""
        SELECT DISTINCT r.course_name,
               COALESCE(c.course_code, '') AS course_code,
               COALESCE(c.units, 0) AS units
        FROM registrations r
        {_SQL_REG_ACTIVE_STUDENT}
        LEFT JOIN courses c
          ON LOWER(TRIM(COALESCE(c.course_name, ''))) = LOWER(TRIM(COALESCE(r.course_name, '')))
        WHERE COALESCE(r.course_name, '') <> ''
          {student_and}
          {course_and}
          {extra_where}
          {dept_and}
        ORDER BY r.course_name
    """
    params = scope_params + tuple(extra_params) + dept_params
    try:
        rows = cur.execute(q, params).fetchall()
    except Exception:
        rows = []

    sched_all = _schedule_course_keys(cur, term_name, term_year)
    if rb == "instructor" and instructor_id is not None:
        sched_keys = _schedule_course_keys(
            cur, term_name, term_year, instructor_name=instructor_name
        )
        tg_keys = _teaching_group_course_keys(
            conn, cur, term_name, term_year, instructor_id
        )
        allowed_keys = sched_keys | tg_keys
    else:
        allowed_keys = None

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows or []:
        d = dict(row)
        cname = (d.get("course_name") or "").strip()
        if not cname:
            continue
        key = cname.lower()
        if key in seen:
            continue
        ck = _attendance_course_key(cname)
        if allowed_keys is not None and ck not in allowed_keys:
            continue
        seen.add(key)
        in_sched = ck in sched_all
        out.append({
            "course_name": cname,
            "course_code": (d.get("course_code") or "").strip(),
            "units": int(d.get("units") or 0),
            "in_schedule": in_sched,
            "registration_only": not in_sched,
        })
    return out


def registration_attendance_course_tuples(
    conn,
    cur,
    term_name: str | None,
    term_year: str | None,
    actor_username: str,
    **kwargs,
) -> list[tuple]:
    """توافق مع course_rows_with_meta: (course_name, course_code, units)."""
    rows = registration_attendance_course_rows(
        conn, cur, term_name, term_year, actor_username, **kwargs
    )
    if rows:
        return [(r["course_name"], r["course_code"], r["units"]) for r in rows]
    return []
