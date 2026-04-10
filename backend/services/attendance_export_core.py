"""
منطق مشترك لتصدير/طباعة الحضور والغياب (صلاحيات + جلب البيانات).
"""
from __future__ import annotations

from typing import Any, Callable

from flask import jsonify, request, session


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
        semester_label = None
        allowed_course_set = None
        allowed_student_filter_sql = None
        allowed_student_filter_params: list = []

        if user_role in ("student", "supervisor", "instructor"):
            term_name, term_year = get_current_term(conn=conn)
            semester_label = f"{(term_name or '').strip()} {(term_year or '').strip()}".strip()
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
                    """
                    SELECT DISTINCT s.course_name
                    FROM schedule s
                    JOIN registrations r ON r.course_name = s.course_name
                    WHERE s.semester = ?
                      AND r.student_id = ?
                      AND COALESCE(s.course_name,'') <> ''
                    """,
                    (semester_label, sid_session),
                ).fetchall()
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
                    """
                    SELECT DISTINCT s.course_name
                    FROM schedule s
                    JOIN registrations r ON r.course_name = s.course_name
                    WHERE s.semester = ?
                      AND r.student_id IN (
                          SELECT student_id FROM student_supervisor WHERE instructor_id = ?
                      )
                      AND COALESCE(s.course_name,'') <> ''
                    """,
                    (semester_label, instructor_id),
                ).fetchall()
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
                    """
                    SELECT DISTINCT course_name
                    FROM schedule
                    WHERE semester = ?
                      AND instructor = ?
                      AND COALESCE(course_name,'') <> ''
                    """,
                    (semester_label, instructor_name),
                ).fetchall()
            )

        if semester_label is None:
            term_name, term_year = get_current_term(conn=conn)
            semester_label = f"{(term_name or '').strip()} {(term_year or '').strip()}".strip()

        def _fetch_all_courses():
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
        normalized_map = {c.lower(): c for c in all_courses}

        if not selected_courses:
            reg_rows = cur.execute(
                "SELECT DISTINCT course_name FROM registrations WHERE COALESCE(course_name,'') <> '' ORDER BY course_name"
            ).fetchall()
            auto_courses = [r[0] for r in reg_rows if r[0]]
            if not auto_courses:
                auto_courses = all_courses
            selected_courses = auto_courses
        else:
            resolved = []
            for val in selected_courses:
                match = normalized_map.get(val.lower())
                if match:
                    resolved.append(match)
                else:
                    resolved.append(val)
                    missing_courses.append(val)
            seen_rc = set()
            filtered = []
            for c in resolved:
                key = c.lower()
                if key in seen_rc:
                    continue
                seen_rc.add(key)
                filtered.append(c)
            selected_courses = filtered

        if allowed_course_set is not None:
            allowed_by_lower = {c.lower(): c for c in allowed_course_set if c}
            selected_courses = [
                allowed_by_lower.get(c.lower())
                for c in selected_courses
                if c and c.lower() in allowed_by_lower
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
            SELECT r.course_name, r.student_id, COALESCE(s.student_name, '') AS student_name
            FROM registrations r
            LEFT JOIN students s ON s.student_id = r.student_id
            {where_clause}
            ORDER BY r.course_name, COALESCE(s.student_name,''), r.student_id
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
