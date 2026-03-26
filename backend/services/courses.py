import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from models.models import Course
from flask import Blueprint, request, jsonify, Response, current_app, session
from backend.core.auth import login_required, role_required
from collections import defaultdict
from .utilities import get_connection, table_to_dicts, df_from_query, excel_response_from_df, pdf_response_from_html

courses_bp = Blueprint("courses", __name__)


def _is_instructor_or_supervisor_view_only() -> bool:
    role = (session.get("user_role") or "").strip()
    return role == "supervisor" or (role == "instructor") or (role == "instructor" and int(session.get("is_supervisor") or 0) == 1)

@courses_bp.route("/list")
@login_required
def list_courses():
    # يرجع جدول courses، وإذا غير موجود يرجع من schedule
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            try:
                cols = [r[1] for r in cur.execute("PRAGMA table_info(courses)").fetchall()]
            except Exception:
                cols = []
            has_cat = "category" in cols
            sel = "SELECT DISTINCT course_name, course_code, units"
            if has_cat:
                sel += ", COALESCE(category,'required') AS category"
            sel += " FROM courses WHERE COALESCE(course_name,'') <> '' ORDER BY course_name"
            rows = cur.execute(sel).fetchall()
            # إزالة التكرار البرمجيًا أيضًا (احتياطي)
            seen = set()
            courses = []
            for r in rows:
                cname = r[0]
                key = cname.strip().lower() if cname else ""
                if not cname or key in seen:
                    continue
                seen.add(key)
                c = Course(r[0], r[1], r[2])
                try:
                    setattr(c, "category", (r[3] if has_cat else "required") or "required")
                except Exception:
                    setattr(c, "category", "required")
                courses.append(c)
        except Exception:
            rows = cur.execute("SELECT DISTINCT course_name FROM schedule WHERE COALESCE(course_name,'') <> '' ORDER BY course_name").fetchall()
            seen = set()
            courses = []
            for r in rows:
                cname = r[0]
                key = cname.strip().lower() if cname else ""
                if not cname or key in seen:
                    continue
                seen.add(key)
                c = Course(r[0], "", 0)
                setattr(c, "category", "required")
                courses.append(c)
    return jsonify([c.__dict__ for c in courses])

@courses_bp.route("/add", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def add_course():
    data = request.get_json(force=True)
    cname = (data.get("course_name") or "").strip()
    code = (data.get("course_code") or "").strip()
    try:
        units = int(data.get("units", 0) or 0)
    except (TypeError, ValueError):
        units = 0
    category = (data.get("category") or "required").strip() or "required"
    if category not in ("required", "elective_major", "elective_free"):
        category = "required"
    if not cname:
        return jsonify({"status": "error", "message": "اسم المقرر (course_name) مطلوب"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS courses (
                course_name TEXT PRIMARY KEY,
                course_code TEXT,
                units INTEGER
            )
        """)
        # منع تكرار الاسم (تطبيع بسيط lower/strip)
        row = cur.execute(
            "SELECT course_name FROM courses WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))",
            (cname,),
        ).fetchone()
        if row:
            return jsonify({"status": "error", "message": "يوجد مقرر آخر بنفس الاسم. استخدم زر \"تحرير\" لتعديله."}), 400

        # منع تكرار الرمز إذا تم إدخاله
        if code:
            row = cur.execute(
                "SELECT course_name FROM courses WHERE COALESCE(course_code,'') <> '' AND LOWER(TRIM(course_code)) = LOWER(TRIM(?))",
                (code,),
            ).fetchone()
            if row:
                return jsonify(
                    {
                        "status": "error",
                        "message": f"يوجد مقرر آخر بنفس الرمز ({row['course_name']}). الرجاء اختيار رمز مختلف.",
                    }
                ), 400

        # تأكد من وجود عمود category (قواعد قديمة)
        try:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(courses)").fetchall()]
        except Exception:
            cols = []
        if "category" in cols:
            cur.execute(
                "INSERT INTO courses (course_name, course_code, units, category) VALUES (?, ?, ?, ?)",
                (cname, code, units, category),
            )
        else:
            cur.execute(
                "INSERT INTO courses (course_name, course_code, units) VALUES (?, ?, ?)",
                (cname, code, units),
            )
        conn.commit()
    return jsonify({"status": "ok", "message": "تم إضافة المقرر"}), 200

@courses_bp.route("/update", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def update_course():
    data = request.get_json(force=True)
    old_name = (data.get("old_course_name") or "").strip()
    new_name = (data.get("new_course_name") or "").strip()
    new_units = data.get("units")
    new_code = (data.get("course_code") or "").strip()
    category = (data.get("category") or "").strip()
    if not old_name or not new_name:
        return jsonify({"status": "error", "message": "old_course_name و new_course_name مطلوبة"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        # منع تكرار الاسم الجديد (باستثناء نفس المقرر)
        row = cur.execute(
            "SELECT course_name FROM courses WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?)) AND course_name <> ?",
            (new_name, old_name),
        ).fetchone()
        if row:
            return jsonify({"status": "error", "message": "لا يمكن تغيير الاسم لأنه مستخدم لمقرر آخر."}), 400

        # منع تكرار الرمز الجديد إن وجد
        if new_code:
            row = cur.execute(
                """
                SELECT course_name FROM courses
                WHERE COALESCE(course_code,'') <> ''
                  AND LOWER(TRIM(course_code)) = LOWER(TRIM(?))
                  AND course_name <> ?
                """,
                (new_code, old_name),
            ).fetchone()
            if row:
                return jsonify(
                    {
                        "status": "error",
                        "message": f"الرمز مستخدم لمقرر آخر ({row['course_name']}). اختر رمزاً مختلفاً.",
                    }
                ), 400

        # تأكد من وجود عمود category (قواعد قديمة)
        try:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(courses)").fetchall()]
        except Exception:
            cols = []
        has_cat = "category" in cols
        cat_value = category if category in ("required", "elective_major", "elective_free") else None
        if has_cat:
            if cat_value is None:
                cur.execute(
                    "UPDATE courses SET course_name=?, course_code=?, units=? WHERE course_name=?",
                    (new_name, new_code or "", (int(new_units) if new_units is not None else None), old_name),
                )
            else:
                cur.execute(
                    "UPDATE courses SET course_name=?, course_code=?, units=?, category=? WHERE course_name=?",
                    (new_name, new_code or "", (int(new_units) if new_units is not None else None), cat_value, old_name),
                )
        else:
            cur.execute(
                "UPDATE courses SET course_name=?, course_code=?, units=? WHERE course_name=?",
                (new_name, new_code or "", (int(new_units) if new_units is not None else None), old_name),
            )

        # تحديث جميع الجداول التي تعتمد على اسم المقرر
        for tbl in ("grades", "schedule", "registrations", "enrollment_plan_items", "exams"):
            try:
                cur.execute(f"UPDATE {tbl} SET course_name=? WHERE course_name=?", (new_name, old_name))
            except Exception:
                pass

        cur.execute("UPDATE prereqs SET course_name=? WHERE course_name=?", (new_name, old_name))
        cur.execute("UPDATE prereqs SET required_course_name=? WHERE required_course_name=?", (new_name, old_name))

        if new_units is not None or new_code is not None:
            try:
                if new_units is not None:
                    cur.execute("UPDATE grades SET units=? WHERE course_name=?", (int(new_units), new_name))
                if new_code is not None:
                    cur.execute(
                        "UPDATE grades SET course_code=? WHERE course_name=?",
                        (new_code or "", new_name),
                    )
            except Exception:
                pass

        # أي تعديل على المقررات (الاسم/الرمز/الوحدات) يجعل نتائج التحسين الحالية قديمة
        try:
            cur.execute("DELETE FROM optimized_schedule")
        except Exception:
            pass
        try:
            cur.execute("DELETE FROM conflict_report")
        except Exception:
            pass

        conn.commit()
    return jsonify({"status": "ok", "message": "تم تعديل بيانات المقرر"}), 200

@courses_bp.route("/delete", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def delete_course():
    data = request.get_json(force=True)
    cname = data.get("course_name")
    if not cname:
        return jsonify({"status": "error", "message": "course_name مطلوب"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM courses WHERE course_name = ?", (cname,))
        except Exception:
            pass
        for tbl in ("schedule", "registrations", "grades"):
            try:
                cur.execute(f"DELETE FROM {tbl} WHERE course_name = ?", (cname,))
            except Exception:
                pass
        cur.execute("DELETE FROM prereqs WHERE course_name = ? OR required_course_name = ?", (cname, cname))

        # حذف مقرر يؤثر على الجدول النهائي وتقرير التعارضات
        try:
            cur.execute("DELETE FROM optimized_schedule")
        except Exception:
            pass
        try:
            cur.execute("DELETE FROM conflict_report")
        except Exception:
            pass

        conn.commit()
    return jsonify({"status": "ok", "message": "تم حذف المقرر وجميع صوره"}), 200

# المتطلبات (Prereqs) - يدعم زوج واحد أو دفعة items[]
@courses_bp.route("/prereqs/add", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def add_prereq():
    """
    Accepts:
    - single object: {"course_name":"A","required_course_name":"B"}
    - or batch: {"items":[{"course_name":"A","required_course_name":"B"}, ...]}

    Response contains lists: added, ignored (duplicates), missing, errors
    """
    data = request.get_json(force=True) or {}

    # normalize incoming items into a list of pairs
    items = []
    if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
        for it in data["items"]:
            c = (it.get("course_name") or "").strip()
            r = (it.get("required_course_name") or "").strip()
            if c and r:
                items.append((c, r))
    else:
        # allow single pair payload
        c = (data.get("course_name") or "").strip()
        r = (data.get("required_course_name") or "").strip()
        if c and r:
            items.append((c, r))

    if not items:
        return jsonify({"status":"error","message":"يرجى تمرير course_name و required_course_name أو مصفوفة items"}), 400

    added = []
    ignored = []
    missing = []
    errors = []

    with get_connection() as conn:
        cur = conn.cursor()
        # Ensure prereqs table exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS prereqs (
                course_name TEXT,
                required_course_name TEXT,
                PRIMARY KEY (course_name, required_course_name)
            )
        """)
        # collect known courses and build tolerant maps
        try:
            rows = cur.execute("SELECT course_name, IFNULL(course_code, '') FROM courses").fetchall()
            known = set()
            name_map = {}   # normalized -> actual name
            code_map = {}   # normalized code -> actual name
            for name, code in rows:
                if not name:
                    continue
                known.add(name)
                nclean = name.strip()
                nkey = nclean.lower()
                name_map[nkey] = nclean
                if code:
                    code_map[code.strip().lower()] = nclean
        except Exception:
            # fallback: try schedule table
            try:
                rows = cur.execute("SELECT DISTINCT course_name FROM schedule").fetchall()
                known = {r[0] for r in rows}
                name_map = { (r[0].strip().lower()): r[0] for r in rows if r[0] }
                code_map = {}
            except Exception:
                known = set()
                name_map = {}
                code_map = {}

        # helper to resolve incoming label to an actual known course name if possible
        def resolve_course_label(label):
            if not label:
                return None
            lab = label.strip()
            lnorm = lab.lower()
            # exact match (case sensitive stored name)
            if lab in known:
                return lab
            # normalized name match
            if lnorm in name_map:
                return name_map[lnorm]
            # code match
            if lnorm in code_map:
                return code_map[lnorm]
            # forgiving contains/prefix match against stored names
            for knorm, real in name_map.items():
                if lnorm == knorm or lnorm in knorm or knorm in lnorm:
                    return real
            return None

        for course, req in items:
            try:
                real_course = resolve_course_label(course)
                real_req = resolve_course_label(req)

                if real_course is None or real_req is None:
                    missing_pair = []
                    if real_course is None:
                        missing_pair.append(f"المقرر غير موجود: {course}")
                    if real_req is None:
                        missing_pair.append(f"المقرر المطلوب غير موجود: {req}")
                    missing.append({"course":course,"required":req,"reason":"; ".join(missing_pair)})
                    continue

                if real_course == real_req:
                    errors.append({"course":course,"required":req,"reason":"المقرر لا يمكن أن يكون متطلباً لنفسه"})
                    continue

                cur.execute("INSERT OR IGNORE INTO prereqs (course_name, required_course_name) VALUES (?,?)", (real_course, real_req))
                if cur.rowcount == 0:
                    ignored.append({"course":real_course,"required":real_req})
                else:
                    added.append({"course":real_course,"required":real_req})
            except Exception as e:
                current_app.logger.exception("add_prereq item failed")
                errors.append({"course":course,"required":req,"reason":str(e)})
        conn.commit()

    return jsonify({
        "status":"ok",
        "added": added,
        "ignored": ignored,
        "missing": missing,
        "errors": errors,
        "message": f"تمت المعالجة: تمت الإضافة {len(added)}؛ تجاهل التكرار {len(ignored)}؛ ناقصة {len(missing)}؛ أخطاء {len(errors)}"
    }), 200

@courses_bp.route("/prereqs/delete", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def delete_prereq():
    data = request.get_json(force=True)
    course = data.get("course_name")
    req = data.get("required_course_name")
    if not course or not req:
        return jsonify({"status": "error", "message": "course_name و required_course_name مطلوبة"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM prereqs WHERE course_name = ? AND required_course_name = ?", (course, req))
        conn.commit()
    return jsonify({"status": "ok", "message": "تم حذف المتطلب"}), 200

@courses_bp.route("/prereqs/list")
@login_required
def list_prereqs():
    with get_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute("SELECT course_name, required_course_name FROM prereqs ORDER BY course_name, required_course_name").fetchall()
        return jsonify([{"course_name": r[0], "required_course_name": r[1]} for r in rows])

@courses_bp.route("/prereqs/status")
@login_required
def prereq_status():
    student_id = request.args.get("student_id")
    if not student_id:
        return jsonify({"status": "error", "message": "student_id مطلوب"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        try:
            rows_c = cur.execute("SELECT course_name FROM courses").fetchall()
            courses = [r[0] for r in rows_c]
        except Exception:
            try:
                rows_s = cur.execute("SELECT DISTINCT course_name FROM schedule").fetchall()
                courses = [r[0] for r in rows_s]
            except Exception:
                courses = []

        rows_p = cur.execute("SELECT course_name, required_course_name FROM prereqs").fetchall()
        prereq_map = defaultdict(list)
        for c, req in rows_p:
            prereq_map[c].append(req)

        taken_rows = cur.execute(
            "SELECT DISTINCT course_name FROM grades WHERE student_id = ? AND grade IS NOT NULL", (student_id,)
        ).fetchall()
        taken = {r[0] for r in taken_rows}

        allowed = []
        blocked = {}
        for c in courses:
            reqs = prereq_map.get(c, [])
            missing = [req for req in reqs if req not in taken]
            if missing:
                blocked[c] = missing
            else:
                allowed.append(c)

    return jsonify({"status": "ok", "allowed": allowed, "blocked": blocked, "prereqs": prereq_map})

# -----------------------
# Export endpoints
# -----------------------

@courses_bp.route("/export/excel")
@login_required
def export_courses_excel():
    """
    Export full courses table as an Excel file using utilities.excel_response_from_df.
    """
    if _is_instructor_or_supervisor_view_only():
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
    try:
        df = df_from_query("SELECT course_name, course_code, units FROM courses")
    except Exception:
        # If table doesn't exist or query fails, return empty CSV-like response
        from io import StringIO
        sio = StringIO()
        sio.write("course_name,course_code,units\n")
        sio.seek(0)
        return Response(sio.getvalue(), mimetype="text/csv")
    return excel_response_from_df(df, filename_prefix="courses")

@courses_bp.route("/export/pdf")
@login_required
def export_courses_pdf():
    """
    Export courses list as PDF. If pdf generation is not available, the underlying utility
    will return a JSON error response explaining the issue.
    """
    if _is_instructor_or_supervisor_view_only():
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
    try:
        df = df_from_query("SELECT course_name, course_code, units FROM courses")
    except Exception:
        df = None

    if df is None or df.empty:
        html = "<html><head><meta charset='utf-8'><title>المقررات</title></head><body><h3>لا توجد مقررات للتصدير</h3></body></html>"
        return pdf_response_from_html(html, filename_prefix="courses")

    # توليد HTML بسيط من DataFrame (مأمون لمعظم البيانات الصغيرة)
    table_html = df.to_html(index=False, classes="table table-bordered table-sm", border=0, justify="left")
    html = f"""
    <!doctype html>
    <html lang="ar" dir="rtl">
      <head>
        <meta charset="utf-8"/>
        <title>قائمة المقررات</title>
        <style>
          body {{ font-family: DejaVu Sans, Arial, Tahoma; direction: rtl; }}
          table {{ border-collapse: collapse; width: 100%; }}
          table th, table td {{ border: 1px solid #ccc; padding: 6px; text-align: left; }}
          th {{ background: #f0f0f0; }}
        </style>
      </head>
      <body>
        <h3>قائمة المقررات</h3>
        {table_html}
      </body>
    </html>
    """
    return pdf_response_from_html(html, filename_prefix="courses")
