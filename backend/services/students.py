import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from models.models import Student
from flask import Blueprint, request, jsonify, render_template, current_app, send_file, session
from backend.core.auth import login_required, role_required
from collections import defaultdict
import sqlite3, pandas as pd, io
from .utilities import (
    get_connection,
    table_to_dicts,
    DB_FILE,
    df_from_query,
    excel_response_from_df,
    excel_response_from_frames,
    pdf_response_from_html,
    log_activity,
    get_schedule_published_at,
)

students_bp = Blueprint("students", __name__)

# -----------------------------
# مساعدة: تطبيع معرّف الطالب
# -----------------------------
def normalize_sid(sid):
    if sid is None:
        return ""
    return str(sid).strip()

# -----------------------------
# CRUD أساسي للطلاب
# -----------------------------
@students_bp.route("/list")
@login_required
def list_students():
    """جلب قائمة الطلاب - يستخدم Service Layer"""
    try:
        from backend.core.services import StudentService
        from backend.core.exceptions import AppException
        
        students = StudentService.get_all_students()
        # تحويل إلى كائنات Student للتوافق مع الكود القديم
        students_objects = [Student(s["student_id"], s["student_name"]) for s in students]
        return jsonify([s.__dict__ for s in students_objects])
    except AppException as e:
        raise
    except Exception as e:
        from backend.core.exceptions import DatabaseError
        raise DatabaseError(f"فشل جلب قائمة الطلاب: {str(e)}")

@students_bp.route("/add", methods=["POST"])
@login_required
def add_student():
    """إضافة طالب جديد - يستخدم Service Layer"""
    try:
        from backend.core.services import StudentService
        from backend.core.exceptions import AppException
        
        data = request.get_json(force=True) or {}
        sid = data.get("student_id")
        name = data.get("student_name", "") or ""
        
        result = StudentService.add_student(sid, name)
        return jsonify(result), 200
    except AppException as e:
        # يتم التعامل مع AppException تلقائياً من خلال error handlers
        raise
    except Exception as e:
        from backend.core.exceptions import DatabaseError
        raise DatabaseError(f"فشل إضافة الطالب: {str(e)}")

@students_bp.route("/delete", methods=["POST"])
@login_required
def delete_student():
    """حذف طالب - يستخدم Service Layer"""
    try:
        from backend.core.services import StudentService
        from backend.core.exceptions import AppException
        
        data = request.get_json(force=True) or {}
        sid = data.get("student_id")
        
        result = StudentService.delete_student(sid)
        # حذف البيانات المرتبطة (للتوافق مع الكود القديم)
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM registrations WHERE student_id = ?", (sid,))
                cur.execute("DELETE FROM grades WHERE student_id = ?", (sid,))
                cur.execute("DELETE FROM grade_audit WHERE student_id = ?", (sid,))
                conn.commit()
        except Exception:
            pass  # تجاهل الأخطاء في الحذف المرتبط
        
        return jsonify(result), 200
    except AppException as e:
        # يتم التعامل مع AppException تلقائياً من خلال error handlers
        raise
    except Exception as e:
        from backend.core.exceptions import DatabaseError
        raise DatabaseError(f"فشل حذف الطالب: {str(e)}")

# -----------------------------
# التسجيلات
# -----------------------------
@students_bp.route("/save_registrations", methods=["POST"])
@role_required("admin")
def save_registrations():
    data = request.get_json(force=True) or {}
    sid = normalize_sid(data.get("student_id"))
    courses = data.get("courses")
    if courses is None:
        courses = data.get("registrations", [])
    if courses is None:
        courses = []
    if not sid:
        return jsonify({"status": "error", "message": "student_id مطلوب"}), 400
    if not isinstance(courses, list):
        return jsonify({"status": "error", "message": "courses/registrations يجب أن تكون قائمة"}), 400

    # Deduplicate provided courses while preserving order to avoid inserting duplicates
    seen = set()
    deduped = []
    for c in courses:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    courses = deduped

    try:
        with get_connection() as conn:
            cur = conn.cursor()
            blocked = {}
            if courses:
                placeholders = ",".join("?" for _ in courses)
                q = f"SELECT course_name, required_course_name FROM prereqs WHERE course_name IN ({placeholders})"
                try:
                    rows = cur.execute(q, courses).fetchall()
                except Exception:
                    current_app.logger.exception("prereqs query failed")
                    rows = []
                prereq_map = defaultdict(list)
                for course_name, required in rows:
                    prereq_map[course_name].append(required)

                for course in courses:
                    reqs = prereq_map.get(course, [])
                    missing = []
                    for r in reqs:
                        old = cur.execute(
                            "SELECT grade FROM grades WHERE student_id = ? AND course_name = ? LIMIT 1",
                            (sid, r)
                        ).fetchone()
                        if old is None or old[0] is None:
                            missing.append(r)
                    if missing:
                        blocked[course] = missing

            if blocked:
                return jsonify({"status": "error", "message": "بعض المتطلبات غير مستوفاة", "blocked": blocked}), 400

            try:
                cur.execute("DELETE FROM registrations WHERE student_id = ?", (sid,))
                if courses:
                    cur.executemany(
                        "INSERT INTO registrations (student_id, course_name) VALUES (?,?)",
                        [(sid, c) for c in courses]
                    )
                conn.commit()

                # إعادة حساب التعارضات وتحديث جدول conflict_report
                try:
                    from backend.services.students import compute_per_student_conflicts
                    conflicts = compute_per_student_conflicts(conn)
                    # حذف تعارضات الطالب الحالي فقط
                    cur.execute("DELETE FROM conflict_report WHERE student_id = ?", (sid,))
                    # إضافة التعارضات الجديدة للطالب
                    for conf in conflicts:
                        if conf.get('student_id') == sid:
                            cur.execute(
                                "INSERT INTO conflict_report (student_id, day, time, conflicting_sections) VALUES (?,?,?,?)",
                                (conf.get('student_id',''), conf.get('day',''), conf.get('time',''), conf.get('conflicting_sections',''))
                            )
                    conn.commit()
                except Exception as e:
                    current_app.logger.exception("recompute conflict_report failed")

                # تسجيل العملية في سجل النشاط
                try:
                    log_activity(
                        action="save_registrations",
                        details=f"student_id={sid}, courses={','.join(courses)}",
                    )
                except Exception:
                    pass

                return jsonify({"status": "ok", "message": "تم حفظ التسجيلات"}), 200
            except Exception as e:
                conn.rollback()
                current_app.logger.exception("insert registrations failed")
                return jsonify({"status": "error", "message": str(e)}), 500
    except Exception as e:
        current_app.logger.exception("save_registrations outer failure")
        return jsonify({"status": "error", "message": str(e)}), 500

@students_bp.route("/get_registrations")
@login_required
def get_registrations():
    student_id = normalize_sid(request.args.get("student_id"))
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            # تقييد المشرف: لا يرى تسجيلات إلا لطلبته المسندين إليه
            user_role = session.get("user_role")
            if user_role == "supervisor":
                instructor_id = session.get("instructor_id")
                if not instructor_id:
                    return jsonify([]), 200
                if not student_id:
                    # منع إرجاع جميع التسجيلات للمشرف
                    return jsonify([]), 200
                ok = cur.execute(
                    "SELECT 1 FROM student_supervisor WHERE student_id = ? AND instructor_id = ? LIMIT 1",
                    (student_id, instructor_id),
                ).fetchone()
                if not ok:
                    return jsonify([]), 200
            if student_id:
                rows = cur.execute("SELECT course_name FROM registrations WHERE student_id = ?", (student_id,)).fetchall()
                return jsonify([r[0] for r in rows])
            else:
                rows = cur.execute("SELECT student_id, course_name FROM registrations").fetchall()
                return jsonify([{"student_id": r[0], "course_name": r[1]} for r in rows])
    except Exception:
        current_app.logger.exception("get_registrations failed")
        return jsonify([])

@students_bp.route("/delete_registrations", methods=["POST"])
@role_required("admin")
def delete_registrations():
    data = request.get_json(force=True) or {}
    sid = normalize_sid(data.get("student_id"))
    if not sid:
        return jsonify({"status":"error","message":"student_id مطلوب"}), 400
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM registrations WHERE student_id = ?", (sid,))
            conn.commit()
        return jsonify({"status":"ok","deleted_for": sid})
    except Exception as e:
        current_app.logger.exception("delete_registrations failed")
        return jsonify({"status":"error","message": str(e)}), 500

@students_bp.route("/import_registrations", methods=["POST"])
@login_required
def import_registrations():
    data = request.get_json(force=True) or {}
    items = data.get("items", []) or []
    added = 0
    with get_connection() as conn:
        cur = conn.cursor()
        cols = [r[1] for r in cur.execute("PRAGMA table_info(students)").fetchall()]
        has_uni = 'university_number' in cols

        for it in items:
            sid = normalize_sid(it.get("student_id"))
            name = it.get("name") or it.get("student_name") or ""
            uni = it.get("university_number") or ""
            regs = it.get("registrations", []) or it.get("courses", []) or []
            # dedupe registrations list for this imported record
            if regs:
                _seen = set()
                _dedup = []
                for c in regs:
                    if c not in _seen:
                        _seen.add(c)
                        _dedup.append(c)
                regs = _dedup
            if not sid:
                continue
            try:
                if has_uni:
                    cur.execute("INSERT OR IGNORE INTO students (student_id, student_name, university_number) VALUES (?,?,?)", (sid, name, uni))
                else:
                    cur.execute("INSERT OR IGNORE INTO students (student_id, student_name) VALUES (?,?)", (sid, name))
                cur.execute("DELETE FROM registrations WHERE student_id = ?", (sid,))
                for c in regs:
                    cur.execute("INSERT INTO registrations (student_id, course_name) VALUES (?,?)", (sid, c))
                added += 1
            except Exception:
                current_app.logger.exception("import_registrations failed for %s", sid)
        conn.commit()
    return jsonify({"status":"ok","imported": added})

# -----------------------------
# Export registrations
# -----------------------------
@students_bp.route("/export/registrations")
@login_required
def export_registrations_excel():
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cols = [r[1] for r in cur.execute("PRAGMA table_info(students)").fetchall()]
            has_uni = 'university_number' in cols

            if has_uni:
                rows = cur.execute("""
                    SELECT r.student_id,
                           COALESCE(s.student_name, '') AS student_name,
                           COALESCE(s.university_number, '') AS university_number,
                           r.course_name,
                           COALESCE(c.course_code, '') AS course_code,
                           COALESCE(c.units, 0) AS units
                    FROM registrations r
                    LEFT JOIN students s ON r.student_id = s.student_id
                    LEFT JOIN courses c ON r.course_name = c.course_name
                    ORDER BY r.student_id, r.course_name
                """).fetchall()
            else:
                rows = cur.execute("""
                    SELECT r.student_id,
                           COALESCE(s.student_name, '') AS student_name,
                           '' AS university_number,
                           r.course_name,
                           COALESCE(c.course_code, '') AS course_code,
                           COALESCE(c.units, 0) AS units
                    FROM registrations r
                    LEFT JOIN students s ON r.student_id = s.student_id
                    LEFT JOIN courses c ON r.course_name = c.course_name
                    ORDER BY r.student_id, r.course_name
                """).fetchall()

        data = []
        for r in rows:
            data.append({
                "student_id": r[0] or "",
                "student_name": r[1] or "",
                "university_number": r[2] or "",
                "course_name": r[3] or "",
                "course_code": r[4] or "",
                "units": int(r[5]) if r[5] is not None else 0
            })
        df = pd.DataFrame(data, columns=["student_id","student_name","university_number","course_name","course_code","units"])
        return excel_response_from_df(df, filename_prefix="registrations")
    except Exception:
        current_app.logger.exception("export_registrations_excel failed")
        return jsonify({"status":"error","message":"فشل التصدير"}), 500


@students_bp.route("/export/attendance")
@login_required
def export_attendance_excel():
    """
    تصدير سجلات الحضور/الغياب في ملف Excel متعدد الأوراق.
    يسمح بتحديد مقررات متعددة (?course=اسم1&course=اسم2) وتحديد عدد الأسابيع (?weeks=10).
    """
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
        # إزالة التكرار مع الحفاظ على الترتيب
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

    summaries = []
    frames = []
    missing_courses = []

    try:
        with get_connection() as conn:
            cur = conn.cursor()

            # احصل على جميع المقررات المعروفة
            def _fetch_all_courses():
                names = []
                try:
                    rows = cur.execute("SELECT DISTINCT course_name FROM courses WHERE COALESCE(course_name,'') <> '' ORDER BY course_name").fetchall()
                    names = [r[0] for r in rows if r[0]]
                except Exception:
                    names = []
                if not names:
                    try:
                        rows = cur.execute("SELECT DISTINCT course_name FROM schedule WHERE COALESCE(course_name,'') <> '' ORDER BY course_name").fetchall()
                        names = [r[0] for r in rows if r[0]]
                    except Exception:
                        names = []
                # إزالة التكرار مع الحفاظ على الترتيب (احتياطي)
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
                # لا توجد مقررات محددة: استخدم المقررات التي لديها تسجيلات أولاً
                reg_rows = cur.execute(
                    "SELECT DISTINCT course_name FROM registrations WHERE COALESCE(course_name,'') <> '' ORDER BY course_name"
                ).fetchall()
                auto_courses = [r[0] for r in reg_rows if r[0]]
                if not auto_courses:
                    auto_courses = all_courses
                selected_courses = auto_courses
            else:
                # حاول مطابقة المقررات المحددة مع قاعدة البيانات (مع الحفاظ على الأسماء غير المعروفة كما هي لإظهار ملاحظة)
                resolved = []
                for val in selected_courses:
                    match = normalized_map.get(val.lower())
                    if match:
                        resolved.append(match)
                    else:
                        resolved.append(val)
                        missing_courses.append(val)
                # إزالة التكرار مجدداً مع الحفاظ على الترتيب
                seen_rc = set()
                filtered = []
                for c in resolved:
                    key = c.lower()
                    if key in seen_rc:
                        continue
                    seen_rc.add(key)
                    filtered.append(c)
                selected_courses = filtered

            # إذا ما زالت القائمة فارغة فليس هناك بيانات
            if not selected_courses:
                summaries.append({
                    "المقرر": "لا توجد مقررات",
                    "عدد الطلبة": 0,
                    "عدد الأسابيع": weeks,
                    "ملاحظات": "لا توجد بيانات تسجيل متاحة"
                })
                frames.append(("ملخص", pd.DataFrame(summaries)))
                return excel_response_from_frames(frames, filename_prefix="attendance")

            # حضّر خريطة الطلبة لكل مقرر
            course_students = {c: [] for c in selected_courses}
            course_seen = {c: set() for c in selected_courses}

            placeholders = ",".join("?" for _ in selected_courses)
            reg_query = f"""
                SELECT r.course_name, r.student_id, COALESCE(s.student_name, '') AS student_name
                FROM registrations r
                LEFT JOIN students s ON s.student_id = r.student_id
                {'WHERE r.course_name IN (' + placeholders + ')' if selected_courses else ''}
                ORDER BY r.course_name, COALESCE(s.student_name,''), r.student_id
            """
            reg_params = selected_courses if selected_courses else []
            reg_rows = cur.execute(reg_query, reg_params).fetchall()
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
                course_students[cname].append({
                    "student_id": sid,
                    "student_name": row[2] or ""
                })

            # اجلب بيانات الحضور المخزنة إن وجدت
            attendance_map = {}
            if selected_courses:
                att_placeholders = ",".join("?" for _ in selected_courses)
                att_query = f"""
                    SELECT course_name, student_id, week_number, COALESCE(status, '') AS status
                    FROM attendance_records
                    WHERE week_number BETWEEN 1 AND ?
                    {'AND course_name IN (' + att_placeholders + ')' if selected_courses else ''}
                """
                params = [weeks] + (selected_courses if selected_courses else [])
                try:
                    att_rows = cur.execute(att_query, params).fetchall()
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

            # إعداد أوراق العمل
            week_columns = [f"الأسبوع {i}" for i in range(1, weeks + 1)]

            for course_name in selected_courses:
                students_list = course_students.get(course_name, [])
                notes = ""
                if not students_list:
                    notes = "لا توجد تسجيلات للمقرر"
                summaries.append({
                    "المقرر": course_name,
                    "عدد الطلبة": len(students_list),
                    "عدد الأسابيع": weeks,
                    "ملاحظات": notes
                })

                rows = []
                for student in students_list:
                    sid = student["student_id"]
                    row = {
                        "الرقم الدراسي": sid,
                        "اسم الطالب": student["student_name"]
                    }
                    week_statuses = attendance_map.get((course_name, sid), {})
                    for idx, col in enumerate(week_columns, start=1):
                        row[col] = week_statuses.get(idx, "")
                    rows.append(row)

                if rows:
                    df = pd.DataFrame(rows)
                else:
                    df = pd.DataFrame(columns=["الرقم الدراسي", "اسم الطالب", *week_columns])
                frames.append((course_name, df))

            # أضف المقررات المفقودة في الملاحظات
            seen_missing = set()
            for missing in missing_courses:
                mk = missing.lower()
                if mk in seen_missing:
                    continue
                seen_missing.add(mk)
                summaries.append({
                    "المقرر": missing,
                    "عدد الطلبة": 0,
                    "عدد الأسابيع": weeks,
                    "ملاحظات": "المقرر غير موجود في قاعدة البيانات"
                })

        # إضافة ورقة الملخص في البداية
        summary_df = pd.DataFrame(summaries)
        frames.insert(0, ("ملخص", summary_df))

        return excel_response_from_frames(frames, filename_prefix="attendance")
    except Exception:
        current_app.logger.exception("export_attendance_excel failed")
        return jsonify({"status": "error", "message": "فشل تصدير الحضور"}), 500
# -----------------------------
# Eligible courses for registration
# -----------------------------
@students_bp.route("/eligible_courses")
@login_required
def eligible_courses():
    """
    المقررات المتاحة للطالب ضمن خطته الدراسية: فقط المقررات الموجودة في الجدول الدراسي المعتمد.
    إذا لم يُنشر الجدول بعد، تُرجع eligible فارغة و schedule_published=False.
    """
    sid = normalize_sid(request.args.get("student_id"))
    if not sid:
        return jsonify({"eligible": [], "completed": [], "schedule_published": False})

    PASS_TEXT = {'p','pass','نجاح','مقبول','a','b','c'}
    PASS_NUM_THRESHOLD = 50.0

    try:
        with get_connection() as conn:
            cur = conn.cursor()
            published_at = get_schedule_published_at(conn)
            if published_at is None:
                try:
                    grade_rows = cur.execute(
                        "SELECT course_name, grade FROM grades WHERE student_id = ?", (sid,)
                    ).fetchall()
                except Exception:
                    grade_rows = []
                grade_map = {r[0]: r[1] for r in grade_rows}
                try:
                    all_rows = cur.execute(
                        "SELECT course_name, COALESCE(course_code, ''), COALESCE(units, 0) FROM courses"
                    ).fetchall()
                    all_courses = [{"course_name": r[0], "course_code": r[1], "units": r[2]} for r in all_rows]
                except Exception:
                    all_courses = []
                completed = []
                for c in all_courses:
                    g = grade_map.get(c["course_name"], None)
                    if g is None:
                        continue
                    passed = False
                    try:
                        if float(g) >= PASS_NUM_THRESHOLD:
                            passed = True
                    except Exception:
                        pass
                    if not passed and isinstance(g, str) and g.strip().lower() in PASS_TEXT:
                        passed = True
                    if passed:
                        completed.append({**c, "grade": g})
                return jsonify({"eligible": [], "completed": completed, "schedule_published": False})

            schedule_course_names = set(
                r[0] for r in cur.execute("SELECT DISTINCT course_name FROM schedule WHERE COALESCE(course_name,'') <> ''").fetchall()
            )
            try:
                all_rows = cur.execute("SELECT course_name, COALESCE(course_code, ''), COALESCE(units, 0) FROM courses").fetchall()
                all_courses = [{"course_name": r[0], "course_code": r[1], "units": r[2]} for r in all_rows]
            except Exception:
                all_rows = cur.execute("SELECT DISTINCT course_name FROM schedule").fetchall()
                all_courses = [{"course_name": r[0], "course_code": "", "units": 0} for r in all_rows]

            all_courses = [c for c in all_courses if c["course_name"] in schedule_course_names]

            try:
                grade_rows = cur.execute("""
                    SELECT course_name, grade FROM grades
                    WHERE student_id = ?
                    GROUP BY course_name
                """, (sid,)).fetchall()
            except Exception:
                grade_rows = cur.execute("SELECT course_name, grade FROM grades WHERE student_id = ?", (sid,)).fetchall()

            grade_map = {r[0]: r[1] for r in grade_rows}

            eligible = []
            completed = []
            for c in all_courses:
                cname = c["course_name"]
                g = grade_map.get(cname, None)
                if g is None:
                    eligible.append(c)
                    continue
                passed = False
                try:
                    gn = float(g)
                    if gn >= PASS_NUM_THRESHOLD:
                        passed = True
                except Exception:
                    pass
                if not passed:
                    if isinstance(g, str) and g.strip().lower() in PASS_TEXT:
                        passed = True
                if passed:
                    comp = c.copy()
                    comp["grade"] = g
                    completed.append(comp)
                else:
                    eligible.append(c)

        return jsonify({"eligible": eligible, "completed": completed, "schedule_published": True})
    except Exception:
        current_app.logger.exception("eligible_courses failed")
        return jsonify({"eligible": [], "completed": [], "schedule_published": False})

# -----------------------------
# Timetable conflicts (robust)
# -----------------------------
def parse_time_range(value):
    """
    Accept formats:
      - "08:00-10:00"
      - "08:00 - 10:00"
      - "08:00" (treated as start only)
      - "08:00/10:00" etc.
    Return tuple (start, end) where end may be '' if not available.
    """
    if not value:
        return ("", "")
    v = str(value).strip()
    # try common delimiters
    for sep in ['-', '–', '—', '/', '\\', ' to ']:
        if sep in v:
            parts = [p.strip() for p in v.split(sep) if p.strip()]
            if len(parts) >= 2:
                return (parts[0], parts[1])
    # single time
    return (v, '')

@students_bp.route("/timetable/conflicts")
@login_required
def timetable_conflicts():
    """
    Return conflicts grouped by (day, start, end, room).
    Tries to detect time columns named: start_time,end_time OR time OR timeslot OR time_range.
    If times are combined (e.g. "08:00-10:00") parse them.
    """
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # detect table
            tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            table_name = None
            for t in ("timetable", "schedule", "sessions"):
                if t in tables:
                    table_name = t
                    break
            if not table_name:
                table_name = tables[0] if tables else "timetable"

            # inspect columns
            cols_info = cur.execute(f"PRAGMA table_info({table_name})").fetchall()
            col_names = [c[1] for c in cols_info]

            # determine which time columns exist
            has_start = 'start_time' in col_names and 'end_time' in col_names
            has_time_single = 'time' in col_names or 'time_range' in col_names or 'timeslot' in col_names
            # build query selecting flexible columns (use COALESCE and aliases)
            select_cols = []
            # day
            if 'day' in col_names:
                select_cols.append("COALESCE(day, '') AS day")
            else:
                select_cols.append("COALESCE(weekday, '') AS day")
            # start/end or single time
            if has_start:
                select_cols.append("COALESCE(start_time, '') AS start_time")
                select_cols.append("COALESCE(end_time, '') AS end_time")
            elif 'time' in col_names:
                select_cols.append("COALESCE(time, '') AS time_single")
            elif 'time_range' in col_names:
                select_cols.append("COALESCE(time_range, '') AS time_single")
            elif 'timeslot' in col_names:
                select_cols.append("COALESCE(timeslot, '') AS time_single")
            else:
                # no time-related column detected — attempt to select a few common names
                select_cols.append("COALESCE(time, '') AS time_single")

            # other common columns
            for cname in ("room", "course_name", "student_id", "section", "note"):
                if cname in col_names:
                    select_cols.append(f"COALESCE({cname}, '') AS {cname}")
                else:
                    select_cols.append(f"'' AS {cname}")

            q = f"SELECT {', '.join(select_cols)} FROM {table_name}"
            try:
                rows = cur.execute(q).fetchall()
            except Exception:
                current_app.logger.exception("timetable/conflicts: query failed (check table/columns)")
                return jsonify({"conflicts": []})

            slots = {}
            for r in rows:
                rowd = dict(r)
                day = rowd.get("day", "") or ""
                # parse start/end depending on which columns present
                if "start_time" in rowd and "end_time" in rowd:
                    start = rowd.get("start_time","") or ""
                    end = rowd.get("end_time","") or ""
                else:
                    ts = rowd.get("time_single","") or ""
                    start, end = parse_time_range(ts)
                room = rowd.get("room","") or ""
                course = rowd.get("course_name","") or ""
                sid = rowd.get("student_id","") or ""
                section = rowd.get("section","") or ""
                note = rowd.get("note","") or ""

                key = f"{day}|{start}|{end}|{room}"
                slots.setdefault(key, {"day": day, "start_time": start, "end_time": end, "room": room, "entries": []})
                slots[key]["entries"].append({
                    "student_id": sid,
                    "student_name": "",
                    "course_name": course,
                    "section": section,
                    "note": note
                })

            # fetch student names for present student_ids
            student_ids = sorted({e["student_id"] for s in slots.values() for e in s["entries"] if e["student_id"]})
            name_map = {}
            if student_ids:
                try:
                    q2 = "SELECT student_id, COALESCE(student_name,'') as student_name FROM students WHERE student_id IN ({})".format(",".join("?" for _ in student_ids))
                    rows2 = cur.execute(q2, student_ids).fetchall()
                    name_map = {r["student_id"]: r["student_name"] for r in rows2}
                except Exception:
                    current_app.logger.exception("timetable/conflicts: failed fetching student names")

            conflicts = []
            for k, s in slots.items():
                entries = s["entries"]
                unique_students = {e["student_id"] for e in entries if e["student_id"]}
                unique_course_sections = {(e["course_name"], e.get("section","")) for e in entries}
                if len(entries) > 1 and (len(unique_students) > 1 or len(unique_course_sections) > 1):
                    for e in entries:
                        sid = e.get("student_id") or ""
                        e["student_name"] = name_map.get(sid, "")
                    s["key"] = k
                    conflicts.append(s)

            return jsonify({"conflicts": conflicts})
    except Exception:
        current_app.logger.exception("timetable_conflicts failed outer")
        return jsonify({"conflicts": []})

# -----------------------------
# استيراد / تصدير بيانات الطلاب (موجودة سابقاً)
# -----------------------------
@students_bp.route("/export/excel")
@login_required
def students_export_excel():
    try:
        df = df_from_query("SELECT student_id, student_name FROM students", db_file=DB_FILE)
        return excel_response_from_df(df, filename_prefix="students")
    except Exception:
        current_app.logger.exception("students_export_excel failed")
        return jsonify({"status": "error", "message": "فشل التصدير"}), 500

@students_bp.route("/export/pdf")
@login_required
def students_export_pdf():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            rows = cur.execute("SELECT student_id, student_name FROM students ORDER BY student_id").fetchall()
            students = [dict(r) for r in rows]
        html = render_template("export_students.html", students=students)
        return pdf_response_from_html(html, filename_prefix="students")
    except Exception:
        current_app.logger.exception("students_export_pdf failed")
        return jsonify({"status": "error", "message": "فشل التصدير إلى PDF"}), 500

@students_bp.route("/import/excel", methods=["POST"])
@login_required
def students_import_excel():
    f = request.files.get("file")
    if not f:
        return jsonify({"status":"error","message":"file required"}), 400
    try:
        df = pd.read_excel(f)
        df.columns = [c.lower() for c in df.columns]
        if not {"student_id","student_name"}.issubset(df.columns):
            return jsonify({"status":"error","message":"Columns required: student_id, student_name"}), 400
        rows = df.to_dict(orient="records")
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            for r in rows:
                sid = normalize_sid(r.get("student_id"))
                name = r.get("student_name") or ""
                cur.execute("INSERT OR REPLACE INTO students (student_id, student_name) VALUES (?,?)", (sid, name))
            conn.commit()
        return jsonify({"status":"ok","imported":len(rows)}), 200
    except Exception as e:
        current_app.logger.exception("students_import_excel failed")
        return jsonify({"status":"error","message":str(e)}), 500


def compute_timetable_conflicts(conn):
    """Compute conflicts given an open sqlite3 connection.
    Returns list of conflict dicts analogous to the /timetable/conflicts route (but without jsonify)."""
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # detect table
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    table_name = None
    for t in ("timetable", "schedule", "sessions"):
        if t in tables:
            table_name = t
            break
    if not table_name:
        table_name = tables[0] if tables else "timetable"

    cols_info = cur.execute(f"PRAGMA table_info({table_name})").fetchall()
    col_names = [c[1] for c in cols_info]

    has_start = 'start_time' in col_names and 'end_time' in col_names

    select_cols = []
    if 'day' in col_names:
        select_cols.append("COALESCE(day, '') AS day")
    else:
        select_cols.append("COALESCE(weekday, '') AS day")
    if has_start:
        select_cols.append("COALESCE(start_time, '') AS start_time")
        select_cols.append("COALESCE(end_time, '') AS end_time")
    elif 'time' in col_names:
        select_cols.append("COALESCE(time, '') AS time_single")
    elif 'time_range' in col_names:
        select_cols.append("COALESCE(time_range, '') AS time_single")
    elif 'timeslot' in col_names:
        select_cols.append("COALESCE(timeslot, '') AS time_single")
    else:
        select_cols.append("COALESCE(time, '') AS time_single")

    for cname in ("room", "course_name", "student_id", "section", "note"):
        if cname in col_names:
            select_cols.append(f"COALESCE({cname}, '') AS {cname}")
        else:
            select_cols.append(f"'' AS {cname}")

    q = f"SELECT {', '.join(select_cols)} FROM {table_name}"
    try:
        rows = cur.execute(q).fetchall()
    except Exception:
        return []

    slots = {}
    for r in rows:
        rowd = dict(r)
        day = rowd.get("day", "") or ""
        if "start_time" in rowd and "end_time" in rowd:
            start = rowd.get("start_time", "") or ""
            end = rowd.get("end_time", "") or ""
        else:
            ts = rowd.get("time_single", "") or ""
            start, end = parse_time_range(ts)
        room = rowd.get("room", "") or ""
        course = rowd.get("course_name", "") or ""
        sid = rowd.get("student_id", "") or ""
        section = rowd.get("section", "") or ""
        note = rowd.get("note", "") or ""

        key = f"{day}|{start}|{end}|{room}"
        slots.setdefault(key, {"day": day, "start_time": start, "end_time": end, "room": room, "entries": []})
        slots[key]["entries"].append({
            "student_id": sid,
            "student_name": "",
            "course_name": course,
            "section": section,
            "note": note
        })

    student_ids = sorted({e["student_id"] for s in slots.values() for e in s["entries"] if e["student_id"]})
    name_map = {}
    if student_ids:
        try:
            q2 = "SELECT student_id, COALESCE(student_name,'') as student_name FROM students WHERE student_id IN ({})".format(
                ",".join("?" for _ in student_ids)
            )
            rows2 = cur.execute(q2, student_ids).fetchall()
            name_map = {r["student_id"]: r["student_name"] for r in rows2}
        except Exception:
            name_map = {}

    conflicts = []
    for k, s in slots.items():
        entries = s["entries"]
        unique_students = {e["student_id"] for e in entries if e["student_id"]}
        unique_course_sections = {(e["course_name"], e.get("section", "")) for e in entries}
        if len(entries) > 1 and (len(unique_students) > 1 or len(unique_course_sections) > 1):
            for e in entries:
                sid = e.get("student_id") or ""
                e["student_name"] = name_map.get(sid, "")
            s["key"] = k
            conflicts.append(s)

    return conflicts


def compute_per_student_conflicts(conn):
    """
    Compute conflicts where a student has 2+ different courses at the same day/time.
    Returns list of dicts: { student_id, day, time, conflicting_sections, conflict_id }.
    This function ONLY checks courses that are in the schedule table.
    """
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get all courses from schedule table with their day and time
    try:
        schedule_rows = cur.execute("""
            SELECT DISTINCT course_name, day, time 
            FROM schedule 
            WHERE course_name IS NOT NULL 
            AND course_name != '' 
            AND day IS NOT NULL 
            AND day != '' 
            AND time IS NOT NULL 
            AND time != ''
        """).fetchall()
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error reading schedule table: {e}")
        return []

    # If no courses in schedule, return empty conflicts
    if not schedule_rows:
        return []

    # Build mapping: course_name -> list of (day, time) tuples
    course_schedule = defaultdict(list)
    for row in schedule_rows:
        course_name = (row['course_name'] or '').strip()
        day = (row['day'] or '').strip()
        time = (row['time'] or '').strip()
        if course_name and day and time:
            course_schedule[course_name].append((day, time))

    # Helper to convert time string to minutes
    def time_to_minutes(time_str):
        """Convert HH:MM to minutes since midnight"""
        try:
            parts = str(time_str).strip().split(':')
            if len(parts) >= 2:
                h = int(parts[0])
                m = int(parts[1])
                return h * 60 + m
        except Exception:
            pass
        return None

    def parse_time_range(time_str):
        """Parse time range like '09:00-11:00' or '11:00-09:00'"""
        if not time_str:
            return None, None
        time_str = str(time_str).strip()
        # Try different separators
        for sep in ['-', '–', '—', '/', ' to ']:
            if sep in time_str:
                parts = [p.strip() for p in time_str.split(sep, 1)]
                if len(parts) == 2:
                    start_min = time_to_minutes(parts[0])
                    end_min = time_to_minutes(parts[1])
                    if start_min is not None and end_min is not None:
                        # Handle reversed times like '13:00-09:00'
                        if end_min < start_min:
                            start_min, end_min = end_min, start_min
                        return start_min, end_min
        # Single time
        single_min = time_to_minutes(time_str)
        return single_min, single_min

    # Get all student registrations
    try:
        registrations = cur.execute("""
            SELECT DISTINCT student_id, course_name 
            FROM registrations 
            WHERE student_id IS NOT NULL 
            AND student_id != '' 
            AND course_name IS NOT NULL 
            AND course_name != ''
        """).fetchall()
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error reading registrations: {e}")
        return []

    # Build student schedule: student_id -> day -> list of courses with times
    student_schedule = defaultdict(lambda: defaultdict(list))
    for reg in registrations:
        student_id = (reg['student_id'] or '').strip()
        course_name = (reg['course_name'] or '').strip()
        
        # Only include courses that are in the schedule
        if course_name not in course_schedule:
            continue
        
        # Add all schedule entries for this course
        for day, time_str in course_schedule[course_name]:
            start_min, end_min = parse_time_range(time_str)
            student_schedule[student_id][day].append({
                'course_name': course_name,
                'time_str': time_str,
                'start_min': start_min,
                'end_min': end_min
            })

    # Find conflicts: for each student+day, check for overlapping courses
    conflicts = []
    conflict_id = 0
    for student_id, days_dict in student_schedule.items():
        for day, courses in days_dict.items():
            # Check all pairs of courses for time overlap
            n = len(courses)
            for i in range(n):
                for j in range(i + 1, n):
                    course1 = courses[i]
                    course2 = courses[j]
                    
                    # Skip if same course
                    if course1['course_name'] == course2['course_name']:
                        continue
                    
                    # Check for time overlap
                    has_overlap = False
                    if (course1['start_min'] is not None and course1['end_min'] is not None and
                        course2['start_min'] is not None and course2['end_min'] is not None):
                        # Check if time ranges overlap
                        latest_start = max(course1['start_min'], course2['start_min'])
                        earliest_end = min(course1['end_min'], course2['end_min'])
                        if latest_start < earliest_end:
                            has_overlap = True
                    elif course1['time_str'] == course2['time_str'] and course1['time_str']:
                        # Same time string
                        has_overlap = True
                    
                    if has_overlap:
                        conflict_id += 1
                        conflicting_courses = sorted([course1['course_name'], course2['course_name']])
                        conflicts.append({
                            'conflict_id': conflict_id,
                            'student_id': student_id,
                            'day': day,
                            'time': course1['time_str'] or course2['time_str'] or '',
                            'conflicting_sections': ', '.join(conflicting_courses)
                        })

    return conflicts


def compute_student_conflicts(conn):
    """Detect conflicts where a student has 2+ schedule entries at the same day/time.
    Uses registrations JOIN schedule to detect overlapping enrollments. Returns flat rows:
    [{ student_id, day, time, conflicting_sections }, ...]
    """
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # Build a flexible day/time expression covering common column names
    day_expr = "COALESCE(s.day, s.weekday, '')"
    time_expr = "COALESCE(s.start_time, s.time, s.time_range, s.timeslot, '')"

    q = f"""
        SELECT r.student_id as student_id,
               {day_expr} as day,
               {time_expr} as time,
               GROUP_CONCAT(s.course_name || CASE WHEN COALESCE(s.section,'')<>'' THEN '('||COALESCE(s.section,'')||')' ELSE '' END, ' | ') as conflicting_sections,
               COUNT(*) as cnt
        FROM registrations r
        JOIN schedule s ON r.course_name = s.course_name
        WHERE COALESCE(r.student_id, '') <> ''
        GROUP BY r.student_id, day, time
        HAVING COUNT(*) > 1
    """
    try:
        rows = cur.execute(q).fetchall()
    except Exception:
        return []

    out = []
    for r in rows:
        out.append({
            'student_id': r['student_id'] or '',
            'day': r['day'] or '',
            'time': r['time'] or '',
            'conflicting_sections': r['conflicting_sections'] or ''
        })
    return out
