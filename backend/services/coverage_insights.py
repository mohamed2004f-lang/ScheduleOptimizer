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


_COVERAGE_SCOPE_LABELS_AR = {
    "current_term": "مقررات الجدول الدراسي للفصل الحالي فقط",
    "current_semester_or_blank": "مقررات الجدول الدراسي للفصل الحالي فقط",
    "current_term_empty": "لا توجد مقررات في الجدول الدراسي للفصل الحالي (قد توجد صفوف لفصول أخرى)",
    "none": "لا توجد مقررات في جدول schedule",
    "scoped_no_schedule_course_department_columns": (
        "لا يمكن حصر مقررات الجدولة حسب القسم (أعمدة القسم غير متوفرة في الجدولة/المقررات)"
    ),
    # توافق قديم — لم يعد يُستخدم بعد إيقاف الرجوع لكل الجدولة
    "all_schedule": "كل المقررات الظاهرة في جدول المقررات (لم يُعثر على بيانات للفصل الحالي)",
    "all_schedule_scoped": "كل مقررات الجدولة المطابقة للفصل (ضمن مقررات قسم نطاقك)",
}


def coverage_scope_label_ar(scope: str) -> str:
    return _COVERAGE_SCOPE_LABELS_AR.get(scope, scope or "")


def _schedule_dept_sql_parts(conn, dept_scope_id: int | None):
    """أجزاء JOIN/WHERE لقيد القسم على schedule؛ أو (None, None, None) عند تعذّر القيد."""
    if dept_scope_id is None:
        return "", "", ()
    scols = fetch_table_columns(conn, "schedule")
    try:
        ccols = fetch_table_columns(conn, "courses")
    except Exception:
        ccols = []
    sched_has_dept = "department_id" in scols
    courses_have_owning = "owning_department_id" in ccols
    if sched_has_dept:
        return (
            "",
            " AND COALESCE(s.department_id, -987654321) = ? ",
            (int(dept_scope_id),),
        )
    if courses_have_owning:
        join_owner = """
            INNER JOIN courses ccov_dep
              ON lower(trim(ccov_dep.course_name)) = lower(trim(s.course_name))
             AND COALESCE(ccov_dep.owning_department_id, -1) = ?
        """
        return join_owner, "", (int(dept_scope_id),)
    return None, None, None


def _fetch_schedule_name_semester_rows(conn, cur, *, dept_scope_id: int | None):
    """
    صفوف (course_name, semester) من schedule مع قيد القسم الاختياري.
    يُرجع (rows, error_scope) حيث error_scope عند تعذّر قيد القسم.
    """
    parts = _schedule_dept_sql_parts(conn, dept_scope_id)
    if parts[0] is None:
        return [], "scoped_no_schedule_course_department_columns"
    join_owner, dept_sql_frag, dept_params = parts
    try:
        rows = cur.execute(
            f"""
            SELECT TRIM(s.course_name) AS course_name,
                   COALESCE(TRIM(s.semester), '') AS semester
            FROM schedule s
            {join_owner}
            WHERE COALESCE(TRIM(s.course_name), '') <> ''
              {dept_sql_frag}
            """,
            dept_params,
        ).fetchall()
    except Exception:
        return [], "none"
    out = []
    for r in rows or []:
        if hasattr(r, "keys"):
            name = (r["course_name"] or "").strip()
            sem = (r["semester"] or "").strip()
        else:
            name = (r[0] or "").strip()
            sem = (r[1] or "").strip() if len(r) > 1 else ""
        if name:
            out.append((name, sem))
    return out, ""


def schedule_other_term_leftover_summary(
    conn,
    cur,
    *,
    dept_scope_id: int | None = None,
) -> dict:
    """
    صفوف الجدولة التي لا تطابق الفصل الحالي (بما فيها بلا فصل).
    لا تُحسب في مقارنة تغطية الفصل الحالي بعد إيقاف الرجوع لـ all_schedule.
    """
    from backend.services.term_engine import (
        current_term_match_context,
        schedule_semester_matches_term_context,
    )

    empty = {
        "row_count": 0,
        "distinct_courses": 0,
        "semesters": [],
        "warning_ar": "",
    }
    rows, err = _fetch_schedule_name_semester_rows(conn, cur, dept_scope_id=dept_scope_id)
    if err == "scoped_no_schedule_course_department_columns":
        return empty
    ctx = current_term_match_context(conn)
    leftover_names: set[str] = set()
    leftover_sems: dict[str, int] = {}
    row_count = 0
    for name, sem in rows:
        if ctx and schedule_semester_matches_term_context(sem, ctx):
            continue
        row_count += 1
        leftover_names.add(normalize_coverage_course_key(name))
        label = sem.strip() if sem.strip() else "(بلا فصل)"
        leftover_sems[label] = leftover_sems.get(label, 0) + 1
    if row_count <= 0:
        return empty
    semesters = sorted(leftover_sems.keys(), key=lambda s: (-leftover_sems[s], s))
    sem_txt = "، ".join(semesters[:6])
    if len(semesters) > 6:
        sem_txt += "…"
    warning_ar = (
        f"تنبيه: يوجد {row_count} صفاً ({len(leftover_names)} مقرراً) في الجدولة "
        f"لفصول أخرى أو بلا فصل ({sem_txt}). "
        "لا تُحسب في مقارنة الفصل الحالي بعد التفريغ."
    )
    return {
        "row_count": row_count,
        "distinct_courses": len(leftover_names),
        "semesters": semesters,
        "warning_ar": warning_ar,
    }


def schedule_distinct_course_names_for_coverage(
    conn,
    cur,
    term_label: str,
    *,
    dept_scope_id: int | None = None,
) -> tuple[list[str], str]:
    """
    أسماء المقررات الفريدة من schedule للفصل الحالي فقط.
    لا رجوع إلى كل الجدولة عند فراغ الفصل (تجنّب عدّ بقايا فصول أخرى بعد التفريغ).
    المطابقة عبر term_engine (مثل لوحة الجدول وتفريغ الفصل).
    عند dept_scope_id يُقيَّد القسم عبر schedule.department_id أو courses.owning_department_id.
    """
    from backend.services.term_engine import (
        current_term_match_context,
        schedule_semester_matches_term_context,
    )

    tl = (term_label or "").strip()
    rows, err = _fetch_schedule_name_semester_rows(conn, cur, dept_scope_id=dept_scope_id)
    if err:
        return [], err

    ctx = current_term_match_context(conn)
    by_key: dict[str, str] = {}
    any_rows = False
    for name, sem in rows:
        any_rows = True
        matched = False
        if ctx:
            matched = schedule_semester_matches_term_context(sem, ctx)
        elif tl:
            matched = (sem or "").strip().lower() == tl.lower()
        if not matched:
            continue
        ck = normalize_coverage_course_key(name)
        if ck and ck not in by_key:
            by_key[ck] = name

    names = sorted(by_key.values(), key=lambda x: x.lower())
    if names:
        return names, "current_term"
    if any_rows:
        return [], "current_term_empty"
    return [], "none"


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
    لا رجوع لصفوف فصول أخرى عند فراغ الفصل الحالي.
    """
    from collections import defaultdict

    from backend.services.term_engine import (
        current_term_match_context,
        schedule_semester_matches_term_context,
    )

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
    ctx = current_term_match_context(conn)

    try:
        raw_rows = cur.execute(
            f"""
            SELECT TRIM(s.course_name),
                   {iid_expr},
                   TRIM(COALESCE(s.instructor, '')),
                   TRIM(COALESCE(s.room, '')),
                   COALESCE(TRIM(s.semester), '')
            FROM schedule s
            {join_owner}
            WHERE COALESCE(TRIM(s.course_name), '') <> ''
              {dept_sql_frag}
            """,
            dept_params,
        ).fetchall()
    except Exception:
        raw_rows = []

    rows = []
    for r in raw_rows or []:
        sem = (r[4] or "").strip() if len(r) > 4 else ""
        if ctx:
            if not schedule_semester_matches_term_context(sem, ctx):
                continue
        elif tl and sem.lower() != tl.lower():
            continue
        rows.append(r)

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
