"""
مقاطع مقارنة التغطية الموحّدة: الجدولة ↔ التسجيل الفعلي ↔ جدول الامتحانات.
مصادر واحدة لتفادي ازدواج SQL وتباين النتائج بين الواجهات.
"""

from __future__ import annotations

from flask import session

from backend.core import department_scope_policy as dept_scope_policy
from backend.core.faculty_axes import normalize_instructor_name
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


def _resolve_schedule_instructor(cur, instructor_id, instructor_text: str) -> tuple[int | None, str]:
    """ربط instructor_id / النص في schedule بسجل instructors."""
    iid: int | None = None
    try:
        if instructor_id is not None:
            iid = int(instructor_id)
    except (TypeError, ValueError):
        iid = None
    if iid:
        row = cur.execute(
            "SELECT id, COALESCE(TRIM(name), '') FROM instructors WHERE id = ? LIMIT 1",
            (iid,),
        ).fetchone()
        if row:
            return int(row[0]), (row[1] or "").strip() or (instructor_text or "").strip()
    name = normalize_instructor_name(instructor_text)
    if not name:
        return None, (instructor_text or "").strip()
    try:
        rows = cur.execute(
            "SELECT id, COALESCE(TRIM(name), '') FROM instructors WHERE COALESCE(TRIM(name), '') <> ''"
        ).fetchall()
    except Exception:
        return None, name
    for rid, rname in rows:
        if normalize_instructor_name(rname) == name:
            return int(rid), (rname or "").strip()
    for rid, rname in rows:
        rn = normalize_instructor_name(rname)
        if name in rn or rn in name:
            return int(rid), (rname or "").strip()
    return None, name


def schedule_course_primary_assignments(
    conn,
    cur,
    term_label: str,
    *,
    dept_scope_id: int | None = None,
) -> dict[str, dict]:
    """
    لكل مقرر في الجدول الدراسي (الفصل الحالي): الأستاذ والقاعة الأكثر تكراراً في schedule.
    المفتاح: اسم المقرر كما يظهر في القائمة (course_name).
    """
    from collections import defaultdict

    tl = (term_label or "").strip()
    dept = dept_scope_id
    scols = fetch_table_columns(conn, "schedule")
    try:
        ccols = fetch_table_columns(conn, "courses")
    except Exception:
        ccols = []
    sched_has_dept = "department_id" in scols
    courses_have_owning = "owning_department_id" in ccols
    has_iid = "instructor_id" in scols

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
            return {}

    iid_expr = "s.instructor_id" if has_iid else "NULL"

    def _fetch_rows(use_term: bool) -> list:
        term_frag = ""
        params: tuple = dept_params
        if use_term and tl:
            term_frag = """
              AND (
                  COALESCE(TRIM(s.semester), '') = ''
                  OR LOWER(TRIM(COALESCE(s.semester,''))) = LOWER(TRIM(?))
              )
            """
            params = (tl,) + dept_params
        try:
            return cur.execute(
                f"""
                SELECT TRIM(s.course_name),
                       {iid_expr},
                       TRIM(COALESCE(s.instructor, '')),
                       TRIM(COALESCE(s.room, ''))
                FROM schedule s
                {join_owner}
                WHERE COALESCE(TRIM(s.course_name), '') <> ''
                  {term_frag}
                  {dept_sql_frag}
                """,
                params,
            ).fetchall()
        except Exception:
            return []

    rows = _fetch_rows(bool(tl))
    if not rows and tl:
        rows = _fetch_rows(False)

    sig_counts: dict[str, dict[tuple, int]] = defaultdict(lambda: defaultdict(int))
    display_names: dict[str, str] = {}

    for r in rows:
        cname = (r[0] or "").strip()
        if not cname:
            continue
        ck = normalize_coverage_course_key(cname)
        try:
            iid = int(r[1]) if r[1] is not None else None
        except (TypeError, ValueError):
            iid = None
        inst = (r[2] or "").strip()
        room = (r[3] or "").strip()
        sig = (iid, inst, room)
        sig_counts[ck][sig] += 1
        if ck not in display_names:
            display_names[ck] = cname

    out: dict[str, dict] = {}
    for ck, counts in sig_counts.items():
        best = max(
            counts.keys(),
            key=lambda s: (
                counts[s],
                1 if (s[0] or (s[1] or "").strip()) else 0,
                1 if s[0] else 0,
                len((s[1] or "").strip()),
            ),
        )
        iid, inst, room = best
        resolved_id, resolved_name = _resolve_schedule_instructor(cur, iid, inst)
        display = display_names.get(ck, ck)
        out[display] = {
            "instructor_id": resolved_id,
            "instructor": resolved_name or inst,
            "room": room,
        }
        out[ck] = out[display]
    return out


def is_exam_exempt_course(course_name: str) -> bool:
    """مقررات بلا امتحان تقليدي (مشروع تخرج …)."""
    n = normalize_coverage_course_key(course_name)
    if not n:
        return False
    markers = (
        "مشروع تخرج",
        "مشروع التخرج",
        "graduation project",
        "capstone",
    )
    return any(m in n for m in markers)


def course_owning_department_id(conn, course_name: str) -> int | None:
    cname = (course_name or "").strip()
    if not cname:
        return None
    try:
        cols = fetch_table_columns(conn, "courses")
    except Exception:
        cols = []
    if "owning_department_id" not in {str(c).strip().lower() for c in (cols or [])}:
        return None
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT owning_department_id FROM courses
        WHERE lower(trim(course_name)) = lower(trim(?))
        LIMIT 1
        """,
        (cname,),
    ).fetchone()
    if not row or row[0] is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def course_is_optional_shared_for_exam(
    conn,
    course_name: str,
    *,
    department_id: int | None,
) -> bool:
    """
    مقرر مشترك/كلية عامة بالنسبة لقسم ما:
    ليس مملوكاً للقسم، أو في كتالوج المشتركة / اتجاه عام الكلية.
    """
    from backend.core.department_scope_policy import (
        course_is_college_general,
        course_is_college_shared_catalog,
    )

    cname = (course_name or "").strip()
    if not cname:
        return False
    if is_exam_exempt_course(cname):
        return False
    own = course_owning_department_id(conn, cname)
    if department_id is not None and own is not None and int(own) == int(department_id):
        return False
    if course_is_college_shared_catalog(conn, cname, department_id=department_id):
        return True
    if course_is_college_general(conn, cname):
        return True
    if department_id is not None and (own is None or int(own) != int(department_id)):
        return True
    return False


def classify_registration_exam_gaps(
    conn,
    missing_course_names: list[str],
    *,
    department_id: int | None,
) -> dict[str, list[str]]:
    """
    تصنيف مقررات مسجّلة بلا امتحان:
    - required: مقررات القسم (يلزم إجراء)
    - optional_shared: مشتركة/عامة (اختيارية حسب الفصل والقسم)
    - exempt: بلا امتحان تقليدي
    """
    required: list[str] = []
    optional_shared: list[str] = []
    exempt: list[str] = []
    for name in missing_course_names or []:
        display = (name or "").strip()
        if not display:
            continue
        if is_exam_exempt_course(display):
            exempt.append(display)
            continue
        if course_is_optional_shared_for_exam(conn, display, department_id=department_id):
            optional_shared.append(display)
        else:
            required.append(display)
    return {
        "required": required,
        "optional_shared": optional_shared,
        "exempt": exempt,
    }


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
