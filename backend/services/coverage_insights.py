"""
مقاطع مقارنة التغطية الموحّدة: الجدولة ↔ التسجيل الفعلي ↔ جدول الامتحانات.
مصادر واحدة لتفادي ازدواج SQL وتباين النتائج بين الواجهات.
"""

from __future__ import annotations

from flask import session

from backend.core import department_scope_policy as dept_scope_policy
from backend.database.database import fetch_table_columns


def normalize_coverage_course_key(name: str) -> str:
    return (name or "").strip().lower()


def schedule_distinct_course_names_for_coverage(
    conn,
    cur,
    term_label: str,
    *,
    dept_scope_id: int | None = None,
) -> tuple[list[str], str]:
    """
    أسماء المقررات الفريدة من schedule (الفصل الحالي أو كل الجدولة عند الحاجة).
    عند dept_scope_id يُقيَّد القسم عبر schedule.department_id أو courses.owning_department_id.
    """
    tl = (term_label or "").strip()
    rows: list = []
    used_filter = ""

    dept = dept_scope_id
    scols = fetch_table_columns(conn, "schedule")
    try:
        ccols = fetch_table_columns(conn, "courses")
    except Exception:
        ccols = []
    sched_has_dept = "department_id" in scols
    courses_have_owning = "owning_department_id" in ccols

    join_owner = ""
    dept_params: tuple = ()
    dept_sql_frag = ""

    if dept is not None:
        if sched_has_dept:
            dept_sql_frag = " AND COALESCE(s.department_id, -987654321) = ? "
            dept_params = (int(dept),)
        elif courses_have_owning:
            join_owner = """
                INNER JOIN courses ccov_dep
                  ON lower(trim(ccov_dep.course_name)) = lower(trim(s.course_name))
                 AND COALESCE(ccov_dep.owning_department_id, -1) = ?
            """
            dept_params = (int(dept),)
        else:
            return [], "scoped_no_schedule_course_department_columns"

    def _suffix():
        return join_owner, dept_sql_frag, dept_params

    try:
        if tl:
            jo, dfs, dp = _suffix()
            rows = cur.execute(
                f"""
                SELECT MIN(TRIM(s.course_name)) AS course_name
                FROM schedule s
                {jo}
                WHERE COALESCE(TRIM(s.course_name), '') <> ''
                  AND (
                      COALESCE(TRIM(s.semester), '') = ''
                      OR LOWER(TRIM(COALESCE(s.semester,''))) = LOWER(TRIM(?))
                  )
                  {dfs}
                GROUP BY LOWER(TRIM(s.course_name))
                ORDER BY MIN(TRIM(s.course_name))
                """,
                (tl,) + dp,
            ).fetchall()
            used_filter = "current_semester_or_blank"
    except Exception:
        rows = []

    names = [(r[0] or "").strip() for r in rows if r and (r[0] or "").strip()]
    if not names:
        try:
            jo, dfs, dp = _suffix()
            rows = cur.execute(
                f"""
                SELECT MIN(TRIM(s.course_name)) AS course_name
                FROM schedule s
                {jo}
                WHERE COALESCE(TRIM(s.course_name), '') <> ''
                  {dfs}
                GROUP BY LOWER(TRIM(s.course_name))
                ORDER BY MIN(TRIM(s.course_name))
                """,
                dp,
            ).fetchall()
            names = [(r[0] or "").strip() for r in rows if r and (r[0] or "").strip()]
            used_filter = "all_schedule" + ("_scoped" if dept is not None else "")
        except Exception:
            names = []
            used_filter = "none"

    return names, used_filter


def registered_distinct_course_names(cur, conn, *, actor_username: str | None = None) -> list[str]:
    """مقررات التسجيل الفعلي (طلاب نشطون) وفق نطاق المستخدم عند تنشيطه."""
    try:
        cols_stu = fetch_table_columns(conn, "students")
    except Exception:
        cols_stu = []
    active_only = "enrollment_status" in {str(c).strip().lower() for c in (cols_stu or [])}

    uname = (actor_username if actor_username is not None else "").strip()
    if not uname:
        try:
            uname = (session.get("user") or session.get("username") or "").strip()
        except Exception:
            uname = ""

    scope_sql, scope_params = dept_scope_policy.resolve_scope_sql_for_aliased_student(conn, uname, "s")

    if scope_sql == "1=0":
        return []

    join_kind = "LEFT JOIN students s ON s.student_id = r.student_id"
    scope_and = ""
    extra_params: tuple = ()
    if scope_sql:
        join_kind = "INNER JOIN students s ON s.student_id = r.student_id"
        scope_and = f" AND ({scope_sql})"
        extra_params = tuple(scope_params) if scope_params else ()

    if active_only:
        rows = cur.execute(
            f"""
            SELECT MIN(TRIM(r.course_name)) AS course_name
            FROM registrations r
            {join_kind}
            WHERE COALESCE(TRIM(r.course_name), '') <> ''
              AND COALESCE(s.enrollment_status, 'active') = 'active'
              {scope_and}
            GROUP BY LOWER(TRIM(r.course_name))
            ORDER BY MIN(TRIM(r.course_name))
            """,
            extra_params,
        ).fetchall()
    else:
        rows = cur.execute(
            f"""
            SELECT MIN(TRIM(r.course_name)) AS course_name
            FROM registrations r
            {join_kind}
            WHERE COALESCE(TRIM(r.course_name), '') <> ''
              {scope_and}
            GROUP BY LOWER(TRIM(r.course_name))
            ORDER BY MIN(TRIM(r.course_name))
            """,
            extra_params,
        ).fetchall()
    return [(r[0] or "").strip() for r in (rows or []) if r and (r[0] or "").strip()]


def registration_course_student_counts(cur, conn, *, actor_username: str | None = None) -> dict[str, int]:
    """
    عدد الطلاب المميزين لكل مقرر (مفتاح: lower(trim(course_name))).
    يُستخدم في توزيع الامتحانات المتوازن ضمن نطاق القسم.
    """
    try:
        cols_stu = fetch_table_columns(conn, "students")
    except Exception:
        cols_stu = []
    active_only = "enrollment_status" in {str(c).strip().lower() for c in (cols_stu or [])}

    uname = (actor_username if actor_username is not None else "").strip()
    if not uname:
        try:
            uname = (session.get("user") or session.get("username") or "").strip()
        except Exception:
            uname = ""

    scope_sql, scope_params = dept_scope_policy.resolve_scope_sql_for_aliased_student(conn, uname, "s")
    if scope_sql == "1=0":
        return {}

    join_kind = "LEFT JOIN students s ON s.student_id = r.student_id"
    scope_and = ""
    extra_params: tuple = ()
    if scope_sql:
        join_kind = "INNER JOIN students s ON s.student_id = r.student_id"
        scope_and = f" AND ({scope_sql})"
        extra_params = tuple(scope_params) if scope_params else ()

    act = "AND COALESCE(s.enrollment_status, 'active') = 'active'" if active_only else ""

    rows = cur.execute(
        f"""
        SELECT LOWER(TRIM(r.course_name)) AS course_key, COUNT(DISTINCT r.student_id) AS cnt
        FROM registrations r
        {join_kind}
        WHERE COALESCE(TRIM(r.course_name), '') <> ''
          {act}
          {scope_and}
        GROUP BY LOWER(TRIM(r.course_name))
        """,
        extra_params,
    ).fetchall()
    out: dict[str, int] = {}
    for r in rows or []:
        k = (r[0] or "").strip().lower()
        if k:
            out[k] = int(r[1] or 0)
    return out
