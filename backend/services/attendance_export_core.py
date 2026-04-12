"""
منطق مشترك لتصدير/طباعة الحضور والغياب (صلاحيات + جلب البيانات).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable

from flask import jsonify, request, session


def _attendance_course_key(name: str) -> str:
    """مفتاح مطابقة أسماء المقررات: تطبيع Unicode، دمج المسافات، ثم lower (مثل قائمة الجدول مقابل باراميتر الرابط)."""
    if not name:
        return ""
    t = unicodedata.normalize("NFKC", str(name).strip())
    t = re.sub(r"\s+", " ", t)
    return t.lower()


def _dedupe_course_list(names: list) -> list:
    seen = set()
    ordered = []
    for item in names:
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
    return ordered


def _collapse_ws(s: str) -> str:
    if not s:
        return ""
    t = unicodedata.normalize("NFKC", str(s).strip())
    return re.sub(r"\s+", " ", t).strip()


def _sqlite_norm_semester_expr(col: str) -> str:
    """طمس مسافات متعددة داخل حقل الفصل في SQL (SQLite/PostgreSQL REPLACE)."""
    t = f"TRIM(COALESCE({col}, ''))"
    for _ in range(8):
        t = f"REPLACE({t}, '  ', ' ')"
    return t


def build_schedule_semester_match(column: str, term_name: str | None, term_year: str | None) -> tuple[str, list]:
    """
    شرط AND لمطابقة schedule.<semester> مع إعدادات الفصل الحالي.
    يدعم: النص المدمج، الاسم أو السنة منفردين، ونصاً في الجدول يحتوي الاسم والسنة (LIKE).
    """
    n = _collapse_ws(str(term_name or ""))
    y = _collapse_ws(str(term_year or ""))
    f = _collapse_ws(f"{n} {y}")
    candidates: list[str] = []
    for c in (f, n, y):
        if c and c not in candidates:
            candidates.append(c)
    if not candidates:
        return ("0=1", [])
    norm = _sqlite_norm_semester_expr(column)
    in_ph = ",".join("?" * len(candidates))
    parts: list[str] = [f"{norm} IN ({in_ph})"]
    bind: list = list(candidates)
    if n and y and len(n) >= 2 and len(y) >= 2:
        # %% لـ psycopg: النسبة المئوية الحرفية في LIKE (لا تُخلط مع %s)
        parts.append(f"({norm} LIKE '%%' || ? || '%%' AND {norm} LIKE '%%' || ? || '%%')")
        bind.extend([n, y])
    return ("(" + " OR ".join(parts) + ")", bind)


def semester_matches_term_settings(
    schedule_semester: str,
    term_name: str | None,
    term_year: str | None,
) -> bool:
    """
    مطابقة نص semester في الجدول مع إعدادات الفصل الحالي.
    يبدأ بما يعادل شرط SQL، ثم يخفّف لمقارنة أرقام السنة (25-26 مقابل 2025-2026) عند تطابق اسم الفصل إن وُجد.
    """
    ss = _collapse_ws(schedule_semester)
    n = _collapse_ws(str(term_name or ""))
    y = _collapse_ws(str(term_year or ""))
    # صف جدول بلا نص فصل: نعتمد وجود المقرر في الجدول مع التسجيل (لا نستبعد لغياب عمود الفصل).
    if not ss:
        return True

    f = _collapse_ws(f"{n} {y}")
    candidates: list[str] = []
    for c in (f, n, y):
        if c and c not in candidates:
            candidates.append(c)
    if candidates:
        if ss in candidates:
            return True
        if n and y and len(n) >= 2 and len(y) >= 2 and n in ss and y in ss:
            return True

    if n and n not in ss:
        return False
    if not y:
        return True
    if y in ss:
        return True
    for part in re.findall(r"\d{2,4}", y):
        if len(part) >= 2 and part in ss:
            return True
    if len(y) >= 4 and y.startswith("20"):
        if y[2:4] in ss:
            return True
        if y[:4] in ss.replace(" ", ""):
            return True
    m_ss = re.search(r"(\d{2})\s*[-–/]\s*(\d{2})", ss)
    if m_ss:
        a, b = m_ss.group(1), m_ss.group(2)
        if a in y or b in y or f"20{a}" in y or f"20{b}" in y:
            return True
    return False


def _collapse_ws_equal(a: str, b: str) -> bool:
    return _collapse_ws(a) == _collapse_ws(b)


def fallback_distinct_attendance_courses(
    cur,
    term_name: str | None,
    term_year: str | None,
    *,
    student_id: str | None = None,
    supervisor_instructor_id: int | None = None,
    instructor_name: str | None = None,
) -> list[str]:
    """
    عند فشل JOIN SQL بين التسجيل والجدول (اختلاف صيغة الفصل/الاسم): مطابقة المقرر بمفتاح موحّد + فصل مرن + اختياري مدرّس الجدول.
    """
    where_extra = ""
    params: list = []
    if student_id:
        where_extra = " AND r.student_id = ?"
        params.append(student_id)
    if supervisor_instructor_id is not None:
        where_extra += " AND r.student_id IN (SELECT student_id FROM student_supervisor WHERE instructor_id = ?)"
        params.append(supervisor_instructor_id)

    try:
        reg_rows = cur.execute(
            f"""
            SELECT DISTINCT TRIM(COALESCE(r.course_name, ''))
            FROM registrations r
            {_SQL_REG_ACTIVE_STUDENT}
            WHERE TRIM(COALESCE(r.course_name, '')) <> ''
            {where_extra}
            """,
            tuple(params),
        ).fetchall()
    except Exception:
        reg_rows = []

    try:
        sch_rows = cur.execute(
            """
            SELECT TRIM(COALESCE(course_name, '')),
                   TRIM(COALESCE(semester, '')),
                   TRIM(COALESCE(instructor, ''))
            FROM schedule
            WHERE TRIM(COALESCE(course_name, '')) <> ''
            """
        ).fetchall()
    except Exception:
        sch_rows = []

    by_key: dict[str, list[tuple[str, str]]] = {}
    for cn, sem, inst in sch_rows:
        if not cn:
            continue
        k = _attendance_course_key(cn)
        if k not in by_key:
            by_key[k] = []
        by_key[k].append((sem, inst))

    matched: list[str] = []
    seen: set[str] = set()
    for (rname,) in reg_rows:
        if not rname:
            continue
        rk = _attendance_course_key(rname)
        for sem, inst in by_key.get(rk, []):
            if not semester_matches_term_settings(sem, term_name, term_year):
                continue
            if instructor_name is not None:
                if not _collapse_ws_equal(inst, instructor_name):
                    continue
            if rname.lower() not in seen:
                seen.add(rname.lower())
                matched.append(rname)
            break

    return sorted(matched, key=lambda x: (x or "").lower())


def course_rows_with_meta(cur, course_names: list[str]) -> list[tuple]:
    """(course_name, course_code, units) لكل اسم مقرر."""
    rows: list[tuple] = []
    for name in course_names:
        try:
            r = cur.execute(
                """
                SELECT COALESCE(c.course_code,''), COALESCE(c.units,0)
                FROM courses c
                WHERE LOWER(TRIM(COALESCE(c.course_name,''))) = LOWER(TRIM(?))
                LIMIT 1
                """,
                (name,),
            ).fetchone()
        except Exception:
            r = None
        if r:
            rows.append((name, r[0], int(r[1] or 0)))
        else:
            rows.append((name, "", 0))
    return rows


# طالب نشط فقط — لا تُعرض مقررات من تسجيلات قديمة لطلبة غير مسجّلين أو منسحبين
_SQL_REG_ACTIVE_STUDENT = (
    "INNER JOIN students st ON st.student_id = r.student_id "
    "AND COALESCE(st.enrollment_status, 'active') = 'active'"
)


def collect_attendance_export_state(
    get_connection: Callable,
    get_current_term: Callable,
    normalize_sid: Callable,
    course_name_lock: str | None = None,
) -> dict[str, Any]:
    """
    يُرجع أحد:
 - {"kind": "http", "response": (response, status)}
    - {"kind": "empty_excel", "summaries": list, "weeks": int}
    - {"kind": "ok", ...} بيانات الجداول والأسابيع
    """
    if course_name_lock:
        raw_courses = [course_name_lock.strip()]
    else:
        raw_courses = request.args.getlist("course") or request.args.getlist("courses")
        if not raw_courses:
            single_courses = request.args.get("courses") or request.args.get("course")
            if single_courses:
                raw_courses = [single_courses]

    def _normalize_courses(values):
        out = []
        for val in values or []:
            if not val:
                continue
            parts = [p.strip() for p in str(val).split(",") if p.strip()]
            out.extend(parts if len(parts) > 1 else [parts[0]] if parts else [])
        seen = set()
        ordered = []
        for item in out:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(item)
        return ordered

    selected_courses = _normalize_courses(raw_courses)

    MAX_WEEKS = 30
    DEFAULT_WEEKS = 14
    try:
        weeks = int(str(request.args.get("weeks", DEFAULT_WEEKS)).strip())
    except (TypeError, ValueError):
        weeks = DEFAULT_WEEKS
    if weeks < 1:
        weeks = 1
    if weeks > MAX_WEEKS:
        weeks = MAX_WEEKS

    summaries: list = []
    missing_courses: list = []

    with get_connection() as conn:
        cur = conn.cursor()

        user_role = session.get("user_role")
        term_name, term_year = get_current_term(conn=conn)
        semester_label = f"{(term_name or '').strip()} {(term_year or '').strip()}".strip()
        sem_match_sql, sem_match_params = build_schedule_semester_match("s.semester", term_name, term_year)
        # صفوف بلا فصل في schedule تُقبل أيضاً (كثير من النشرات لا تملأ semester)
        sched_sem_and = f" AND (({sem_match_sql}) OR TRIM(COALESCE(s.semester, '')) = '')"
        allowed_course_set = None
        allowed_student_filter_sql = None
        allowed_student_filter_params: list = []

        if user_role in ("student", "supervisor", "instructor"):
            if not semester_label:
                return {
                    "kind": "http",
                    "response": (
                        jsonify(
                            {
                                "status": "error",
                                "message": "لا يمكن تحديد الفصل الحالي",
                                "code": "FORBIDDEN",
                            }
                        ),
                        403,
                    ),
                }

        if user_role == "student":
            sid_session = normalize_sid(session.get("student_id") or session.get("user"))
            if not sid_session:
                return {
                    "kind": "http",
                    "response": (
                        jsonify(
                            {
                                "status": "error",
                                "message": "لا يوجد ربط بين حسابك والطالب",
                                "code": "FORBIDDEN",
                            }
                        ),
                        403,
                    ),
                }

            allowed_student_filter_sql = "r.student_id = ?"
            allowed_student_filter_params = [sid_session]
            allowed_course_set = set(
                c[0]
                for c in cur.execute(
                    f"""
                    SELECT DISTINCT r.course_name
                    FROM registrations r
                    {_SQL_REG_ACTIVE_STUDENT}
                    INNER JOIN schedule s
                      ON LOWER(TRIM(COALESCE(r.course_name, ''))) = LOWER(TRIM(COALESCE(s.course_name, '')))
                    {sched_sem_and}
                    WHERE r.student_id = ?
                      AND COALESCE(r.course_name, '') <> ''
                    """,
                    tuple(sem_match_params) + (sid_session,),
                ).fetchall()
                if c and c[0]
            )
            if not allowed_course_set:
                allowed_course_set = set(
                    fallback_distinct_attendance_courses(
                        cur, term_name, term_year, student_id=sid_session
                    )
                )

        elif user_role == "supervisor" or (
            user_role == "instructor" and int(session.get("is_supervisor") or 0) == 1
        ):
            instructor_id = session.get("instructor_id")
            if not instructor_id:
                return {
                    "kind": "http",
                    "response": (
                        jsonify(
                            {
                                "status": "error",
                                "message": "لا يوجد ربط بين حسابك وعضو هيئة تدريس",
                                "code": "FORBIDDEN",
                            }
                        ),
                        403,
                    ),
                }

            allowed_student_filter_sql = "r.student_id IN (SELECT student_id FROM student_supervisor WHERE instructor_id = ?)"
            allowed_student_filter_params = [instructor_id]
            allowed_course_set = set(
                c[0]
                for c in cur.execute(
                    f"""
                    SELECT DISTINCT r.course_name
                    FROM registrations r
                    {_SQL_REG_ACTIVE_STUDENT}
                    INNER JOIN schedule s
                      ON LOWER(TRIM(COALESCE(r.course_name, ''))) = LOWER(TRIM(COALESCE(s.course_name, '')))
                    {sched_sem_and}
                    WHERE r.student_id IN (
                          SELECT student_id FROM student_supervisor WHERE instructor_id = ?
                      )
                      AND COALESCE(r.course_name, '') <> ''
                    """,
                    tuple(sem_match_params) + (instructor_id,),
                ).fetchall()
                if c and c[0]
            )
            if not allowed_course_set:
                allowed_course_set = set(
                    fallback_distinct_attendance_courses(
                        cur, term_name, term_year, supervisor_instructor_id=int(instructor_id)
                    )
                )

        elif user_role == "instructor":
            instructor_id = session.get("instructor_id")
            if not instructor_id:
                return {
                    "kind": "http",
                    "response": (
                        jsonify(
                            {
                                "status": "error",
                                "message": "لا يوجد ربط بين حسابك وعضو هيئة تدريس",
                                "code": "FORBIDDEN",
                            }
                        ),
                        403,
                    ),
                }

            instr_row = cur.execute(
                "SELECT name FROM instructors WHERE id = ? LIMIT 1",
                (instructor_id,),
            ).fetchone()
            if not instr_row:
                return {
                    "kind": "http",
                    "response": (
                        jsonify(
                            {
                                "status": "error",
                                "message": "لا يمكن تحديد المدرّس المرتبط بحسابك",
                                "code": "FORBIDDEN",
                            }
                        ),
                        403,
                    ),
                }
            instructor_name = instr_row[0]

            allowed_course_set = set(
                c[0]
                for c in cur.execute(
                    f"""
                    SELECT DISTINCT r.course_name
                    FROM registrations r
                    {_SQL_REG_ACTIVE_STUDENT}
                    INNER JOIN schedule s
                      ON LOWER(TRIM(COALESCE(r.course_name, ''))) = LOWER(TRIM(COALESCE(s.course_name, '')))
                    {sched_sem_and}
                     AND TRIM(COALESCE(s.instructor, '')) = TRIM(?)
                    WHERE COALESCE(r.course_name, '') <> ''
                    """,
                    tuple(sem_match_params) + (instructor_name,),
                ).fetchall()
                if c and c[0]
            )
            if not allowed_course_set:
                allowed_course_set = set(
                    fallback_distinct_attendance_courses(
                        cur, term_name, term_year, instructor_name=instructor_name
                    )
                )

        def _fetch_all_courses():
            """مقررات يوجد لها طالب نشط مسجّل + صف جدول للفصل الحالي (لا احتياط بلا فصل)."""
            sem = (semester_label or "").strip()
            if sem:
                names: list = []
                try:
                    rows = cur.execute(
                        f"""
                        SELECT DISTINCT r.course_name
                        FROM registrations r
                        {_SQL_REG_ACTIVE_STUDENT}
                        INNER JOIN schedule s
                          ON LOWER(TRIM(COALESCE(r.course_name, ''))) = LOWER(TRIM(COALESCE(s.course_name, '')))
                        {sched_sem_and}
                        WHERE COALESCE(r.course_name, '') <> ''
                        ORDER BY r.course_name
                        """,
                        tuple(sem_match_params),
                    ).fetchall()
                    names = [r[0] for r in rows if r[0]]
                except Exception:
                    names = []
                if not names:
                    names = fallback_distinct_attendance_courses(cur, term_name, term_year)
                return _dedupe_course_list(names)
            names = []
            try:
                rows = cur.execute(
                    "SELECT DISTINCT course_name FROM courses WHERE COALESCE(course_name,'') <> '' ORDER BY course_name"
                ).fetchall()
                names = [r[0] for r in rows if r[0]]
            except Exception:
                names = []
            if not names:
                try:
                    rows = cur.execute(
                        "SELECT DISTINCT course_name FROM schedule WHERE COALESCE(course_name,'') <> '' ORDER BY course_name"
                    ).fetchall()
                    names = [r[0] for r in rows if r[0]]
                except Exception:
                    names = []
            seen = set()
            ordered = []
            for item in names:
                key = item.lower()
                if key in seen:
                    continue
                seen.add(key)
                ordered.append(item)
            return ordered

        all_courses = _fetch_all_courses()
        normalized_map: dict[str, str] = {}
        for c in all_courses:
            k = _attendance_course_key(c)
            if k and k not in normalized_map:
                normalized_map[k] = c

        # تقييد الإدارة بمجموعة المقررات المستخرجة من التسجيلات + الجدول (all_courses)
        if user_role in ("admin", "admin_main", "head_of_department") and (semester_label or "").strip():
            allowed_course_set = set(all_courses)

        if not selected_courses:
            sem = (semester_label or "").strip()
            if sem:
                try:
                    reg_rows = cur.execute(
                        f"""
                        SELECT DISTINCT r.course_name
                        FROM registrations r
                        {_SQL_REG_ACTIVE_STUDENT}
                        INNER JOIN schedule s
                          ON LOWER(TRIM(COALESCE(r.course_name, ''))) = LOWER(TRIM(COALESCE(s.course_name, '')))
                        {sched_sem_and}
                        WHERE COALESCE(r.course_name, '') <> ''
                        ORDER BY r.course_name
                        """,
                        tuple(sem_match_params),
                    ).fetchall()
                except Exception:
                    reg_rows = []
            else:
                reg_rows = []
            auto_courses = [r[0] for r in reg_rows if r[0]]
            if not auto_courses and sem:
                auto_courses = fallback_distinct_attendance_courses(cur, term_name, term_year)
            if not auto_courses:
                auto_courses = all_courses
            selected_courses = auto_courses
        else:
            resolved = []
            for val in selected_courses:
                match = normalized_map.get(_attendance_course_key(val))
                if match:
                    resolved.append(match)
                else:
                    resolved.append(val)
                    missing_courses.append(val)
            seen_rc = set()
            filtered = []
            for c in resolved:
                key = _attendance_course_key(c)
                if key in seen_rc:
                    continue
                seen_rc.add(key)
                filtered.append(c)
            selected_courses = filtered

        if allowed_course_set is not None:
            allowed_by_key: dict[str, str] = {}
            for c in allowed_course_set:
                if not c:
                    continue
                k = _attendance_course_key(c)
                if k and k not in allowed_by_key:
                    allowed_by_key[k] = c
            selected_courses = [
                allowed_by_key.get(_attendance_course_key(c))
                for c in selected_courses
                if c and _attendance_course_key(c) in allowed_by_key
            ]

        if not selected_courses:
            summaries.append(
                {
                    "المقرر": "لا توجد مقررات",
                    "عدد الطلبة": 0,
                    "عدد الأسابيع": weeks,
                    "ملاحظات": "لا توجد بيانات تسجيل متاحة",
                }
            )
            return {"kind": "empty_excel", "summaries": summaries, "weeks": weeks}

        course_students = {c: [] for c in selected_courses}
        course_seen = {c: set() for c in selected_courses}

        where_clauses = []
        params = []
        if selected_courses:
            placeholders = ",".join("?" for _ in selected_courses)
            where_clauses.append(f"r.course_name IN ({placeholders})")
            params.extend(selected_courses)
        if allowed_student_filter_sql:
            where_clauses.append(allowed_student_filter_sql)
            params.extend(allowed_student_filter_params)

        where_clause = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        reg_query = f"""
            SELECT r.course_name, r.student_id, COALESCE(st.student_name, '') AS student_name
            FROM registrations r
            {_SQL_REG_ACTIVE_STUDENT}
            {where_clause}
            ORDER BY r.course_name, COALESCE(st.student_name,''), r.student_id
        """
        reg_rows = cur.execute(reg_query, params).fetchall()
        for row in reg_rows:
            cname = row[0]
            sid = normalize_sid(row[1])
            if not cname or not sid:
                continue
            if cname not in course_students:
                course_students[cname] = []
                course_seen[cname] = set()
            if sid in course_seen[cname]:
                continue
            course_seen[cname].add(sid)
            course_students[cname].append({"student_id": sid, "student_name": row[2] or ""})

        attendance_map: dict = {}
        if selected_courses:
            att_placeholders = ",".join("?" for _ in selected_courses)
            att_query = f"""
                SELECT course_name, student_id, week_number, COALESCE(status, '') AS status
                FROM attendance_records
                WHERE week_number BETWEEN 1 AND ?
                {'AND course_name IN (' + att_placeholders + ')' if selected_courses else ''}
            """
            att_params = [weeks] + (selected_courses if selected_courses else [])
            try:
                att_rows = cur.execute(att_query, att_params).fetchall()
            except Exception:
                att_rows = []
            for row in att_rows:
                cname, sid, week_no, status = row
                if not cname or not sid:
                    continue
                try:
                    week_idx = int(week_no)
                except (TypeError, ValueError):
                    continue
                if week_idx < 1 or week_idx > weeks:
                    continue
                key = (cname, normalize_sid(sid))
                attendance_map.setdefault(key, {})[week_idx] = status

        return {
            "kind": "ok",
            "weeks": weeks,
            "selected_courses": selected_courses,
            "course_students": course_students,
            "attendance_map": attendance_map,
            "missing_courses": missing_courses,
            "semester_label": semester_label or "",
        }
