import sys
import os
from collections import defaultdict, OrderedDict
import datetime
import io
import math
import pandas as pd

# ensure parent package is importable when running modules directly in some environments
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask import Blueprint, request, jsonify, Response, send_file, session
from backend.core.auth import login_required, role_required
from models.models import Grade
from .utilities import get_connection, df_from_query, excel_response_from_df, pdf_response_from_html, log_activity

PASSING_GRADE = 50

grades_bp = Blueprint("grades", __name__)


def validate_grade_value(g):
    if g is None:
        return True, None
    try:
        v = float(g)
    except (TypeError, ValueError):
        return False, "grade must be numeric or null"
    if v < 0 or v > 100:
        return False, "grade must be between 0 and 100"
    return True, v


@grades_bp.route("/save", methods=["POST"])
@role_required("admin")
def save_grades():
    data = request.get_json(force=True)
    sid = data.get("student_id")
    semester = data.get("semester")
    grades = data.get("grades", [])
    changed_by = data.get("changed_by", "system")
    if not sid or not semester:
        return jsonify({"status": "error", "message": "student_id و semester مطلوبة"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        try:
            for g in grades:
                course = g.get("course_name")
                new_grade_raw = g.get("grade", None)
                ok, val_or_msg = validate_grade_value(new_grade_raw)
                if not ok:
                    raise ValueError(f"القيمة للمقرر {course} غير صحيحة: {val_or_msg}")
                new_grade = val_or_msg

                old = cur.execute(
                    "SELECT grade FROM grades WHERE student_id = ? AND semester = ? AND course_name = ?",
                    (sid, semester, course)
                ).fetchone()
                old_grade = old[0] if old else None

                cur.execute(
                    "INSERT INTO grade_audit (student_id, semester, course_name, old_grade, new_grade, changed_by, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (sid, semester, course, old_grade, (float(new_grade) if new_grade is not None else None),
                     changed_by, datetime.datetime.utcnow().isoformat())
                )

                cur.execute(
                    "INSERT OR REPLACE INTO grades (student_id, semester, course_name, course_code, units, grade) VALUES (?, ?, ?, ?, ?, ?)",
                    (sid, semester, course, g.get("course_code", ""), int(g.get("units", 0) or 0),
                     (float(new_grade) if new_grade is not None else None))
                )
            conn.commit()
            # تسجيل النشاط (عدد الدرجات التي تم تعديلها)
            try:
                log_activity(
                    action="save_grades",
                    details=f"student_id={sid}, semester={semester}, count={len(grades)}",
                )
            except Exception:
                pass
            return jsonify({"status": "ok", "message": "تم حفظ الدرجات وتسجيل التعديلات"}), 200
        except Exception as e:
            conn.rollback()
            return jsonify({"status": "error", "message": str(e)}), 500

@grades_bp.route("/template/transcript", methods=["GET"])
@login_required
def download_transcript_template():
    """
    تنزيل قالب Excel فارغ لاستخدامه في استيراد كشف درجات طالب واحد (تنسيق التصدير).
    يحتوي على الأعمدة/الشكل المتوقعين من منطق الاستيراد الحالي.
    """
    # الأعمدة الأساسية في الصف الأول: اسم المقرر، الرمز، الوحدات
    # الصف الثاني: مثال لقيمة الوحدات
    # باقي الصفوف: فارغة ليتم تعبئتها.
    import xlsxwriter

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    ws = workbook.add_worksheet("TranscriptTemplate")

    header_fmt = workbook.add_format({"bold": True, "bg_color": "#f0f0f0"})

    headers = ["اسم المقرر", "رمز المقرر", "الوحدات", "الدرجة"]
    for col, title in enumerate(headers):
        ws.write(0, col, title, header_fmt)

    # صف مثال بسيط
    ws.write(1, 0, "رياضيات هندسية I")
    ws.write(1, 1, "MATH101")
    ws.write(1, 2, 4)
    ws.write(1, 3, 85)

    workbook.close()
    output.seek(0)

    now_str = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"transcript_template_{now_str}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@grades_bp.route("/template/semester", methods=["GET"])
@login_required
def download_semester_template():
    """
    تنزيل قالب Excel فارغ لاستخدامه في استيراد نتيجة فصل كاملة.
    الصف الأول: أسماء المقررات، الصف الثاني: الوحدات، ثم صفوف الطلبة.
    """
    import xlsxwriter

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    ws = workbook.add_worksheet("SemesterTemplate")

    header_fmt = workbook.add_format({"bold": True, "bg_color": "#f0f0f0"})

    # الصف الأول: عناوين الأعمدة الثابتة + مثال لمادتين
    ws.write(0, 0, "الاسم الرباعي", header_fmt)
    ws.write(0, 1, "الرقم الدراسي", header_fmt)
    ws.write(0, 2, "رياضيات هندسية I", header_fmt)
    ws.write(0, 3, "فيزياء I", header_fmt)

    # الصف الثاني: وحدات المواد
    ws.write(1, 0, "")
    ws.write(1, 1, "")
    ws.write(1, 2, 4)  # وحدات الرياضيات
    ws.write(1, 3, 3)  # وحدات الفيزياء

    # صف مثال لطالب واحد
    ws.write(2, 0, "أحمد خالد الطشاني")
    ws.write(2, 1, "24379")
    ws.write(2, 2, 90)  # درجة الرياضيات
    ws.write(2, 3, 85)  # درجة الفيزياء

    workbook.close()
    output.seek(0)

    now_str = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"semester_template_{now_str}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@grades_bp.route("/import/semester", methods=["POST"])
@role_required("admin")
def import_semester_excel():
    """
    استيراد نتيجة فصل كاملة من ملف Excel.
    يدعم نمطين:
      - preview: عندما يحتوي النموذج على preview=1 (أو true)، يتم فقط تحليل الملف
        وإرجاع ملخص بعدد الطلبة/المقررات/السجلات بدون أي كتابة في قاعدة البيانات.
      - apply: الاستيراد الفعلي عند عدم وجود preview، مع نفس منطق إدراج الدرجات السابق.
    صيغة الملف:
      - الصف الأول: أسماء المقررات، مع أول عمودين للـ (الاسم الرباعي، الرقم الدراسي)
      - الصف الثاني: وحدات كل مقرر
      - باقي الصفوف: بيانات الطلبة (الاسم، الرقم، الدرجات لكل مقرر)
    """
    semester_label = (request.form.get("semester") or "").strip()
    academic_year = (request.form.get("year") or "").strip()
    changed_by = (request.form.get("changed_by") or "semester-import").strip() or "semester-import"
    preview_flag = (request.form.get("preview") or "").strip().lower() in ("1", "true", "yes", "preview")
    file = request.files.get("file")

    if not semester_label and not academic_year:
        return (
            jsonify({"status": "error", "message": "يرجى إدخال الفصل أو السنة"}),
            400,
        )
    if not file:
        return jsonify({"status": "error", "message": "ملف Excel مفقود"}), 400

    semester = semester_label
    if academic_year:
        semester = f"{semester} {academic_year}".strip()
    if not semester:
        return jsonify({"status": "error", "message": "تعذر تحديد اسم الفصل"}), 400

    try:
        df = pd.read_excel(file, header=None)
    except Exception as exc:
        return (
            jsonify({"status": "error", "message": f"فشل قراءة ملف Excel: {exc}"}),
            400,
        )

    if df.shape[0] < 3 or df.shape[1] < 3:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "ملف الاستيراد يجب أن يحتوي على عناوين ووحدات وبيانات طلبة",
                }
            ),
            400,
        )

    header_row = df.iloc[0].tolist()
    units_row = df.iloc[1].tolist()

    course_columns = []
    for idx, name in enumerate(header_row):
        if idx < 2:
            continue
        if name is None or (isinstance(name, float) and math.isnan(name)):
            continue
        cname = str(name).strip()
        if not cname:
            continue
        units = _parse_units(units_row[idx] if idx < len(units_row) else None)
        course_columns.append((idx, cname, units))

    if not course_columns:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "لم يتم العثور على عناوين مقررات في الصف الأول",
                }
            ),
            400,
        )

    student_rows = df.iloc[2:]
    if student_rows.empty:
        return (
            jsonify({"status": "error", "message": "لا توجد سجلات طلبة للاستيراد"}),
            400,
        )

    students_data = []
    invalid_grades = []
    for _, row in student_rows.iterrows():
        name_raw = row.iloc[0] if len(row) > 0 else None
        sid_raw = row.iloc[1] if len(row) > 1 else None
        student_name = str(name_raw).strip() if name_raw is not None else ""
        student_id = _normalize_student_id(sid_raw)
        if not student_id and not student_name:
            continue
        if not student_id:
            continue

        grades = []
        for col_idx, cname, units in course_columns:
            value = row.iloc[col_idx] if col_idx < len(row) else None
            grade_val = _parse_grade_value(value)
            grades.append((cname, units, grade_val))

            if grade_val is not None and (grade_val < 0 or grade_val > 100):
                invalid_grades.append(
                    {
                        "student_id": student_id,
                        "student_name": student_name,
                        "course_name": cname,
                        "grade": grade_val,
                    }
                )

        students_data.append((student_id, student_name, grades))

    if not students_data:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "لم يتم العثور على طلبة صالحين في الملف",
                }
            ),
            400,
        )

    # في نمط المعاينة: لا نكتب شيئاً في قاعدة البيانات، نعيد فقط ملخصاً
    if preview_flag:
        total_students = len(students_data)
        total_courses = len(course_columns)
        total_records = sum(len(grades) for _, _, grades in students_data)
        return jsonify(
            {
                "status": "ok",
                "mode": "preview",
                "semester": semester,
                "students": total_students,
                "courses": total_courses,
                "records": total_records,
                "invalid_grades": invalid_grades,
            }
        )

    # تطبيق الاستيراد الفعلي (منطق قريب من النسخة الأصلية)
    with get_connection() as conn:
        cur = conn.cursor()

        existing_rows = cur.execute(
            "SELECT student_id, course_name, grade FROM grades WHERE semester = ?",
            (semester,),
        ).fetchall()
        existing_map = {
            (row["student_id"], row["course_name"]): row["grade"] for row in existing_rows
        }

        # التأكد من وجود المقررات في جدول courses وتحديث الوحدات
        for _, cname, units in course_columns:
            try:
                cur.execute(
                    """
                    INSERT INTO courses (course_name, course_code, units)
                    VALUES (?, '', ?)
                    ON CONFLICT(course_name) DO UPDATE SET
                        units = CASE
                            WHEN excluded.units IS NOT NULL AND excluded.units > 0 THEN excluded.units
                            ELSE units
                        END
                    """,
                    (cname, units),
                )
            except Exception:
                pass

        inserted_records = 0
        affected_students = set()

        now_iso = datetime.datetime.utcnow().isoformat()
        for student_id, student_name, grades in students_data:
            affected_students.add(student_id)
            if student_name:
                cur.execute(
                    """
                    INSERT INTO students (student_id, student_name)
                    VALUES (?, ?)
                    ON CONFLICT(student_id) DO UPDATE SET student_name = excluded.student_name
                    """,
                    (student_id, student_name),
                )
            else:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO students (student_id, student_name)
                    VALUES (?, COALESCE((SELECT student_name FROM students WHERE student_id = ?), ''))
                    """,
                    (student_id, student_id),
                )

            for cname, units, grade_val in grades:
                if grade_val is not None and (grade_val < 0 or grade_val > 100):
                    conn.rollback()
                    return (
                        jsonify(
                            {
                                "status": "error",
                                "message": f"الدرجة للمقرر {cname} للطالب {student_id} يجب أن تكون بين 0 و 100",
                            }
                        ),
                        400,
                    )

                key = (student_id, cname)
                old_grade = existing_map.get(key)

                cur.execute(
                    """
                    INSERT INTO grade_audit (student_id, semester, course_name, old_grade, new_grade, changed_by, ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        student_id,
                        semester,
                        cname,
                        float(old_grade) if old_grade is not None else None,
                        float(grade_val) if grade_val is not None else None,
                        changed_by,
                        now_iso,
                    ),
                )

                cur.execute(
                    """
                    INSERT OR REPLACE INTO grades (student_id, semester, course_name, course_code, units, grade)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        student_id,
                        semester,
                        cname,
                        "",
                        units,
                        float(grade_val) if grade_val is not None else None,
                    ),
                )
                inserted_records += 1

        conn.commit()

    return (
        jsonify(
            {
                "status": "ok",
                "message": f"تم استيراد نتيجة الفصل {semester} لعدد {len(affected_students)} طالب/ة",
                "semester": semester,
                "students": len(affected_students),
                "courses": len(course_columns),
                "records": inserted_records,
            }
        ),
        200,
    )


@grades_bp.route("/migrate_registrations_to_transcript", methods=["POST"])
@role_required("admin")
def migrate_registrations_to_transcript():
    data = request.get_json(force=True)
    student_id = data.get("student_id")
    semester = data.get("semester")
    year = data.get("year")
    changed_by = data.get("changed_by", "migrate-ui")
    if not student_id or not semester or not year:
        return jsonify({"status": "error", "message": "student_id، الفصل، السنة مطلوبة"}), 400
    semester_label = f"{semester} {year}".strip()
    with get_connection() as conn:
        cur = conn.cursor()
        # registrations table schema may vary across installs. Try to select course_code/units
        # if present; otherwise select only course_name and look up code/units from `courses`.
        regs = None
        try:
            cols = [r[1] for r in cur.execute("PRAGMA table_info('registrations')").fetchall()]
        except Exception:
            cols = []

        if 'course_code' in cols and 'units' in cols:
            regs = cur.execute(
                "SELECT course_name, course_code, units FROM registrations WHERE student_id = ?",
                (student_id,)
            ).fetchall()
        else:
            # fetch only course_name and enrich from courses table when possible
            simple = cur.execute(
                "SELECT course_name FROM registrations WHERE student_id = ?",
                (student_id,)
            ).fetchall()
            regs = []
            for row in simple:
                # row may be a tuple like (course_name,) or a Row; handle both
                cname = row[0] if isinstance(row, (list, tuple)) else row['course_name'] if 'course_name' in row.keys() else None
                if not cname:
                    continue
                course_row = cur.execute(
                    "SELECT course_code, units FROM courses WHERE course_name = ? LIMIT 1",
                    (cname,)
                ).fetchone()
                if course_row:
                    ccode = course_row[0] if isinstance(course_row, (list, tuple)) else course_row['course_code']
                    units = course_row[1] if isinstance(course_row, (list, tuple)) else course_row['units']
                else:
                    ccode = ""
                    units = 0
                regs.append((cname, ccode or "", int(units or 0)))
        if not regs:
            return jsonify({"status": "error", "message": "لا توجد مقررات مسجلة لهذا الطالب"}), 404

        existing = cur.execute(
            "SELECT course_name FROM grades WHERE student_id = ? AND semester = ?",
            (student_id, semester_label)
        ).fetchall()
        existing_courses = set(row[0] for row in existing)
        inserted = 0
        now_iso = datetime.datetime.utcnow().isoformat()
        for reg in regs:
            cname, ccode, units = reg
            if cname in existing_courses:
                continue
            cur.execute(
                "INSERT INTO grades (student_id, semester, course_name, course_code, units, grade) VALUES (?, ?, ?, ?, ?, NULL)",
                (student_id, semester_label, cname, ccode or "", int(units or 0))
            )
            cur.execute(
                "INSERT INTO grade_audit (student_id, semester, course_name, old_grade, new_grade, changed_by, ts) VALUES (?, ?, ?, NULL, NULL, ?, ?)",
                (student_id, semester_label, cname, changed_by, now_iso)
            )
            inserted += 1
        conn.commit()
    return jsonify({"status": "ok", "message": f"تم ترحيل {inserted} مقرر للفصل {semester_label}", "semester": semester_label, "inserted": inserted}), 200


def _load_transcript_data(student_id: str):
    with get_connection() as conn:
        cur = conn.cursor()
        cols = [row[1] for row in cur.execute("PRAGMA table_info(students)").fetchall()]
        has_plan = "graduation_plan" in cols
        sel = "SELECT COALESCE(student_name, '') AS student_name"
        if has_plan:
            sel += ", COALESCE(graduation_plan, '') AS graduation_plan"
        sel += " FROM students WHERE student_id = ?"
        student_row = cur.execute(sel, (student_id,)).fetchone()
        student_name = student_row["student_name"] if student_row else ""
        graduation_plan = (student_row.get("graduation_plan") or "").strip() if student_row and has_plan else ""

        grade_rows = cur.execute(
            """
            SELECT semester, course_name, course_code, units, grade
            FROM grades
            WHERE student_id = ?
            ORDER BY semester, course_name
            """,
            (student_id,),
        ).fetchall()

    transcript = OrderedDict()
    gpa_by_semester = defaultdict(list)
    best_map = {}

    for row in grade_rows:
        sem = row["semester"] or ""
        course_name = row["course_name"] or ""
        course_code = row["course_code"] or ""
        units = row["units"] or 0
        grade = row["grade"]

        transcript.setdefault(sem, []).append(
            {
                "course_name": course_name,
                "course_code": course_code,
                "units": units,
                "grade": grade,
            }
        )

        if grade is not None:
            gpa_by_semester[sem].append((grade, units))

        if grade is not None:
            if course_name not in best_map or grade > best_map[course_name]["best_grade"]:
                best_map[course_name] = {"best_grade": grade, "units": units}
            else:
                if units and (not best_map[course_name]["units"] or units > best_map[course_name]["units"]):
                    best_map[course_name]["units"] = units

    semester_gpas = {}
    for sem, lst in gpa_by_semester.items():
        total_units_sem = sum(max(u, 0) for _, u in lst)
        semester_gpas[sem] = (
            round(
                sum(grade * (max(units, 0)) for grade, units in lst) / total_units_sem,
                2,
            )
            if total_units_sem
            else 0.0
        )

    # استكمال الوحدات من جدول المقررات إذا كانت مسجلة 0 أو فارغة في الدرجات
    course_units_from_db = {}
    if best_map:
        with get_connection() as conn2:
            cur2 = conn2.cursor()
            for course_name in best_map.keys():
                row = cur2.execute(
                    "SELECT COALESCE(units, 0) AS u FROM courses WHERE course_name = ?",
                    (course_name,),
                ).fetchone()
                if row and (row["u"] or 0) > 0:
                    course_units_from_db[course_name] = int(row["u"])

    total_points = 0.0
    total_units = 0.0
    completed_units = 0
    completed_units_breakdown = []  # لمراجعة الوحدات المنجزة: قائمة (مقرر، درجة، وحدات، ناجح؟)
    for course_name, info in best_map.items():
        units = max(info["units"] or 0, 0)
        if units <= 0 and course_name in course_units_from_db:
            units = course_units_from_db[course_name]
        grade_best = info["best_grade"]
        passed = grade_best is not None and grade_best >= PASSING_GRADE
        total_units += units
        total_points += (grade_best * units) if grade_best is not None else 0.0
        if passed:
            completed_units += units
        completed_units_breakdown.append({
            "course_name": course_name,
            "best_grade": grade_best,
            "units_used": units,
            "passed": passed,
        })
    cumulative_gpa = round(total_points / total_units, 2) if total_units else 0.0
    completed_units = int(completed_units)

    ordered_semesters = list(transcript.keys())

    return {
        "student_id": student_id,
        "student_name": student_name,
        "graduation_plan": graduation_plan,
        "transcript": transcript,
        "ordered_semesters": ordered_semesters,
        "semester_gpas": semester_gpas,
        "cumulative_gpa": cumulative_gpa,
        "completed_units": completed_units,
        "completed_units_breakdown": completed_units_breakdown,
    }


def _normalize_student_id(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _parse_units(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 0
    try:
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return 0
            return max(int(round(float(cleaned.replace(",", ".")))), 0)
        return max(int(round(float(value))), 0)
    except Exception:
        return 0


def _parse_grade_value(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, str):
        trimmed = value.strip()
        if not trimmed:
            return None
        if all(ch in {"/", "\\", "-"} for ch in trimmed):
            return None
        trimmed = trimmed.replace(",", ".")
        try:
            return float(trimmed)
        except ValueError:
            return None
    try:
        return float(value)
    except Exception:
        return None


def _cell_to_str(value):
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def _parse_export_style_single_student(df):
    matrix = df.where(pd.notnull(df), None).values.tolist()
    if not matrix or not matrix[0]:
        return {"ok": False}

    first_label = _cell_to_str(matrix[0][0])
    if first_label != "اسم الطالب":
        return {"ok": False}

    student_name = _cell_to_str(matrix[0][1]) if len(matrix[0]) > 1 else ""
    student_id = ""
    if len(matrix) > 1 and len(matrix[1]) > 1 and _cell_to_str(matrix[1][0]) == "الرقم الدراسي":
        student_id = _normalize_student_id(matrix[1][1])

    semesters = []
    idx = 0
    total_rows = len(matrix)
    while idx < total_rows:
        row = matrix[idx]
        first = _cell_to_str(row[0]) if row else ""
        if first.startswith("الفصل"):
            sem = first.split(":", 1)[1].strip() if ":" in first else first.replace("الفصل", "", 1).strip()
            idx += 1

            # find header row
            while idx < total_rows:
                header_row = matrix[idx]
                header_label = _cell_to_str(header_row[0]) if header_row else ""
                if header_label == "المقرر":
                    idx += 1
                    break
                idx += 1

            courses = []
            while idx < total_rows:
                course_row = matrix[idx]
                if not course_row or not any(cell is not None for cell in course_row):
                    idx += 1
                    break
                course_name = _cell_to_str(course_row[0])
                if not course_name:
                    idx += 1
                    break
                course_code = _cell_to_str(course_row[1]) if len(course_row) > 1 else ""
                units = _parse_units(course_row[2]) if len(course_row) > 2 else 0
                grade_val = _parse_grade_value(course_row[3]) if len(course_row) > 3 else None
                courses.append({"course_name": course_name, "course_code": course_code, "units": units, "grade": grade_val})
                idx += 1

            semesters.append((sem, courses))
            continue
        idx += 1

    return {"ok": True, "student_name": student_name, "student_id": student_id, "semesters": semesters}


@grades_bp.route("/import/single", methods=["POST"])
@role_required("admin")
def import_single_student():
    # expects form with file (excel) and optional student_id/semester/year/changed_by
    file = request.files.get("file")
    sid = request.form.get("student_id")
    semester = request.form.get("semester") or ""
    year = request.form.get("year") or ""
    changed_by = request.form.get("changed_by") or "importer"

    if not file:
        return jsonify({"status": "error", "message": "ملف مفقود"}), 400
    try:
        df = pd.read_excel(file, header=None)
    except Exception as exc:
        return jsonify({"status": "error", "message": f"فشل قراءة ملف Excel: {exc}"}), 400

    parsed = _parse_export_style_single_student(df)
    if not parsed.get("ok"):
        return jsonify({"status": "error", "message": "تنسيق الملف غير مدعوم"}), 400

    sem_label = semester
    if year:
        sem_label = f"{semester} {year}".strip()

    return _import_export_style_single_student(parsed, sid, None, sem_label, changed_by)


@grades_bp.route("/import/transcript", methods=["POST"])
@role_required("admin")
def import_transcript():
    """
    Alias لمسار استيراد كشف درجات طالب واحد باستخدام نفس منطق /import/single
    حتى يتوافق مع واجهة transcript.html التي تستدعي /grades/import/transcript.
    """
    return import_single_student()


def _import_export_style_single_student(parsed, student_id_override, student_name_override, provided_semester, changed_by):
    student_id_file = parsed.get("student_id") or ""
    student_name_file = parsed.get("student_name") or ""
    semesters = parsed.get("semesters") or []

    if not semesters:
        return jsonify({"status": "error", "message": "الملف لا يحتوي على فصول دراسية صالحة"}), 400

    if student_id_override and student_id_file and student_id_override != student_id_file:
        return jsonify({"status": "error", "message": "رقم الطالب في الملف لا يطابق الرقم المحدد"}), 400

    student_id = student_id_override or student_id_file
    if not student_id:
        return jsonify({"status": "error", "message": "تعذر تحديد رقم الطالب من الملف أو الحقول"}), 400

    student_name = student_name_override or student_name_file

    normalized_semesters = []
    default_semester = (provided_semester or "").strip()
    for sem_name, courses in semesters:
        sem = (sem_name or "").strip()
        if not sem:
            sem = default_semester
        if not sem:
            return jsonify({"status": "error", "message": "أحد الفصول في الملف يفتقد للاسم ولا يوجد فصل بديل محدد"}), 400
        filtered_courses = [c for c in courses if c.get("course_name")]
        if filtered_courses:
            normalized_semesters.append((sem, filtered_courses))

    if not normalized_semesters:
        return jsonify({"status": "error", "message": "لا توجد مقررات صالحة للاستيراد"}), 400

    with get_connection() as conn:
        cur = conn.cursor()

        if student_name:
            cur.execute(
                """
                INSERT INTO students (student_id, student_name)
                VALUES (?, ?)
                ON CONFLICT(student_id) DO UPDATE SET student_name = excluded.student_name
                """,
                (student_id, student_name),
            )
        else:
            cur.execute(
                """
                INSERT OR IGNORE INTO students (student_id, student_name)
                VALUES (?, COALESCE((SELECT student_name FROM students WHERE student_id = ?), ''))
                """,
                (student_id, student_id),
            )

        inserted_total = 0
        now_iso = datetime.datetime.utcnow().isoformat()

        for sem, courses in normalized_semesters:
            existing_rows = cur.execute(
                "SELECT course_name, grade FROM grades WHERE student_id = ? AND semester = ?",
                (student_id, sem),
            ).fetchall()
            existing_map = {row[0]: row[1] for row in existing_rows}

            for course in courses:
                cname = course.get("course_name") or ""
                if not cname:
                    continue
                ccode = course.get("course_code") or ""
                units = int(course.get("units") or 0)
                grade_val = course.get("grade")

                if grade_val is not None and (grade_val < 0 or grade_val > 100):
                    conn.rollback()
                    return jsonify({"status": "error", "message": f"الدرجة للمقرر {cname} في الفصل {sem} يجب أن تكون بين 0 و 100"}), 400

                old_grade = existing_map.get(cname)
                new_grade_float = float(grade_val) if grade_val is not None else None
                # إذا كان السجل موجوداً بنفس الدرجة لنفس الطالب/الفصل/المقرر فلا نكرر ولا نحدّث
                if old_grade is not None and new_grade_float is not None:
                    if abs(float(old_grade) - new_grade_float) < 1e-6:
                        continue
                elif old_grade is None and new_grade_float is None:
                    continue

                # إذا لم يُرسل رمز للمقرر، نحاول جلبه من جدول courses بالاعتماد على اسم المقرر
                if not ccode:
                    course_row = cur.execute(
                        "SELECT course_code FROM courses WHERE course_name = ? LIMIT 1",
                        (cname,),
                    ).fetchone()
                    if course_row:
                        try:
                            ccode = (
                                course_row[0]
                                if len(course_row) > 0
                                else (course_row["course_code"] if "course_code" in course_row.keys() else "")
                            )
                        except Exception:
                            ccode = course_row["course_code"] if "course_code" in course_row.keys() else ""

                cur.execute(
                    """
                    INSERT INTO grade_audit (student_id, semester, course_name, old_grade, new_grade, changed_by, ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        student_id,
                        sem,
                        cname,
                        float(old_grade) if old_grade is not None else None,
                        new_grade_float,
                        changed_by,
                        now_iso,
                    ),
                )

                cur.execute(
                    """
                    INSERT OR REPLACE INTO grades (student_id, semester, course_name, course_code, units, grade)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        student_id,
                        sem,
                        cname,
                        ccode,
                        units,
                        new_grade_float,
                    ),
                )
                inserted_total += 1

        conn.commit()

    sem_list = [sem for sem, _ in normalized_semesters]
    return jsonify({"status": "ok", "message": f"تم استيراد {inserted_total} درجة", "student_id": student_id, "semesters": sem_list}), 200


@grades_bp.route("/update", methods=["POST"])
@role_required("admin")
def update_grade():
    data = request.get_json(force=True)
    sid = data.get("student_id")
    semester = data.get("semester")
    course = data.get("course_name")  # الاسم الحالي في جدول grades (لتعريف السطر)
    new_course_name = (data.get("new_course_name") or "").strip()  # الاسم الجديد عند اختيار مقرر من القائمة
    new_grade_raw = data.get("grade")
    new_course_code = (data.get("course_code") or "").strip()
    changed_by = data.get("changed_by", "admin")

    if not sid or not semester or not course:
        return jsonify({"status": "error", "message": "student_id و semester و course_name مطلوبة"}), 400

    ok, val_or_msg = validate_grade_value(new_grade_raw)
    if not ok:
        return jsonify({"status": "error", "message": val_or_msg}), 400
    new_grade = val_or_msg

    with get_connection() as conn:
        cur = conn.cursor()
        # fetch existing grade row to preserve course_code and units if present
        existing = cur.execute(
            "SELECT course_code, units, grade FROM grades WHERE student_id=? AND semester=? AND course_name=?",
            (sid, semester, course),
        ).fetchone()

        old_grade = None
        course_code_to_use = ""
        units_to_use = 0

        if existing:
            try:
                # sqlite Row supports mapping access
                old_grade = existing[2] if len(existing) > 2 else existing['grade']
            except Exception:
                old_grade = (existing['grade'] if 'grade' in existing.keys() else None)

            try:
                course_code_to_use = existing[0] if len(existing) > 0 else (existing['course_code'] if 'course_code' in existing.keys() else "")
            except Exception:
                course_code_to_use = existing['course_code'] if 'course_code' in existing.keys() else ""

            try:
                units_to_use = int(existing[1]) if len(existing) > 1 and existing[1] is not None else (int(existing['units']) if 'units' in existing.keys() and existing['units'] is not None else 0)
            except Exception:
                try:
                    units_to_use = int(existing['units']) if 'units' in existing.keys() and existing['units'] is not None else 0
                except Exception:
                    units_to_use = 0
        # اسم المقرر الذي سنحفظ به بعد التصحيح (قد يختلف عن الاسم القادم من الواجهة)
        course_name_final = course

        # إذا اختار المستخدم مقرراً جديداً من قائمة المقررات، نعتمد الاسم والرمز والوحدات من جدول المقررات
        if new_course_name:
            course_name_final = new_course_name
            course_row = cur.execute(
                "SELECT course_code, units FROM courses WHERE course_name = ? LIMIT 1",
                (new_course_name,),
            ).fetchone()
            if course_row:
                try:
                    course_code_to_use = (course_row[0] if course_row[0] is not None else "") or course_code_to_use
                except Exception:
                    pass
                try:
                    if len(course_row) > 1 and course_row[1] is not None:
                        units_to_use = int(course_row[1])
                except Exception:
                    pass

        # في حال أدخل المستخدم رمزاً جديداً، نبحث عنه في جدول المقررات ونصحح الاسم/الوحدات
        if new_course_code:
            # أولاً نحاول المطابقة على رمز المقرر
            course_row = cur.execute(
                "SELECT course_name, course_code, units FROM courses WHERE course_code = ? LIMIT 1",
                (new_course_code,),
            ).fetchone()
            if course_row:
                # اعتماد الاسم والرمز والوحدات الرسمية من جدول المقررات
                try:
                    course_name_final = course_row[0]
                except Exception:
                    course_name_final = course_row["course_name"]
                try:
                    course_code_to_use = course_row[1]
                except Exception:
                    course_code_to_use = course_row["course_code"]
                try:
                    units_to_use = int(course_row[2]) if course_row[2] is not None else units_to_use
                except Exception:
                    units_to_use = units_to_use
            else:
                # لم نجد الرمز في جدول المقررات، نستخدمه كما هو فقط
                course_code_to_use = new_course_code

        # إذا لم يوجد لدينا رمز حتى الآن، نحاول جلبه بالاعتماد على اسم المقرر (كما في السابق)
        if not course_code_to_use:
            course_row = cur.execute(
                "SELECT course_code, units FROM courses WHERE course_name = ? LIMIT 1",
                (course_name_final,),
            ).fetchone()
            if course_row:
                try:
                    course_code_to_use = (
                        course_row[0]
                        if len(course_row) > 0
                        else (course_row["course_code"] if "course_code" in course_row.keys() else "")
                    )
                except Exception:
                    course_code_to_use = (
                        course_row["course_code"] if "course_code" in course_row.keys() else ""
                    )
                try:
                    units_to_use = (
                        int(course_row[1])
                        if len(course_row) > 1 and course_row[1] is not None
                        else (
                            int(course_row["units"])
                            if "units" in course_row.keys() and course_row["units"] is not None
                            else units_to_use
                        )
                    )
                except Exception:
                    try:
                        units_to_use = (
                            int(course_row["units"])
                            if "units" in course_row.keys() and course_row["units"] is not None
                            else units_to_use
                        )
                    except Exception:
                        pass

        # إذا تغير اسم المقرر النهائي عن الاسم المسجل حالياً، نحذف السطر القديم لتفادي ازدواجية (اسم قديم + اسم صحيح)
        if course_name_final != course:
            cur.execute(
                "DELETE FROM grades WHERE student_id=? AND semester=? AND course_name=?",
                (sid, semester, course),
            )

        cur.execute(
            "INSERT INTO grade_audit (student_id, semester, course_name, old_grade, new_grade, changed_by, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                sid,
                semester,
                course_name_final,
                old_grade,
                (float(new_grade) if new_grade is not None else None),
                changed_by,
                datetime.datetime.utcnow().isoformat(),
            ),
        )

        cur.execute(
            "INSERT OR REPLACE INTO grades (student_id, semester, course_name, course_code, units, grade) VALUES (?, ?, ?, ?, ?, ?)",
            (
                sid,
                semester,
                course_name_final,
                course_code_to_use or "",
                int(units_to_use or 0),
                (float(new_grade) if new_grade is not None else None),
            ),
        )
        conn.commit()

    return jsonify({"status": "ok", "message": "تم تعديل الدرجة"}), 200


@grades_bp.route("/transcript/<student_id>")
@login_required
def get_transcript(student_id):
    # الطالب لا يمكنه عرض إلا سجله الخاص
    user_role = session.get("user_role")
    if user_role == "student":
        sid_session = session.get("student_id") or session.get("user")
        if sid_session != student_id:
            return jsonify({
                "status": "error",
                "message": "لا يمكنك عرض سجل طالب آخر",
                "code": "FORBIDDEN"
            }), 403
    # المشرف يمكنه عرض سجلات الطلبة المسندين إليه فقط
    if user_role == "supervisor":
        from backend.services.utilities import get_connection
        instructor_id = session.get("instructor_id")
        if not instructor_id:
            return jsonify({
                "status": "error",
                "message": "لا يوجد ربط بين حسابك وعضو هيئة تدريس",
                "code": "FORBIDDEN"
            }), 403
        with get_connection() as conn:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT 1 FROM student_supervisor WHERE student_id = ? AND instructor_id = ? LIMIT 1",
                (student_id, instructor_id),
            ).fetchone()
            if not row:
                return jsonify({
                    "status": "error",
                    "message": "لا يمكنك عرض سجل طالب غير مُسند إليك",
                    "code": "FORBIDDEN"
                }), 403
    data = _load_transcript_data(student_id)
    return jsonify({
        "student_id": data["student_id"],
        "student_name": data.get("student_name", ""),
        "graduation_plan": data.get("graduation_plan", ""),
        "transcript": data["transcript"],
        "semester_gpas": data["semester_gpas"],
        "cumulative_gpa": data["cumulative_gpa"],
        "completed_units": data.get("completed_units", 0),
        "ordered_semesters": data.get("ordered_semesters", []),
    })


def _compute_academic_status(student_id: str, data: dict):
    """
    حساب ملاحظة أكاديمية مختصرة (إنذارات/احتمال فصل) + فرصة استثنائية إن وُجدت.
    منطق منسجم مع الدالة الموجودة في performance.py حتى يظهر في التصدير الرسمي.
    """
    ordered = data.get("ordered_semesters", []) or []
    sem_gpas = data.get("semester_gpas", {}) or {}
    cumulative_gpa = data.get("cumulative_gpa", 0.0)

    from .utilities import get_connection  # استيراد محلي لتفادي الحلقات
    from backend.services.performance import _load_rule_number  # إعادة استخدام نفس الدالة

    if not ordered:
        label = "لا توجد بيانات درجات"
    else:
        # قراءة الحدود من academic_rules
        with get_connection() as conn:
            warning_threshold = _load_rule_number(conn, "warning_semester_threshold", 50.0)
            dismissal_cgpa_threshold = _load_rule_number(conn, "dismissal_cgpa_threshold", 35.0)
            dismissal_min_semesters = int(_load_rule_number(conn, "dismissal_min_semesters", 2.0))

        lows = []
        for idx, sem in enumerate(ordered):
            g = sem_gpas.get(sem, 0.0)
            if idx == 0:
                lows.append(False)
            else:
                lows.append((g or 0) < warning_threshold)

        consecutive_lows = 0
        for idx in range(len(lows) - 1, -1, -1):
            if not lows[idx]:
                break
            if idx == 0:
                break
            consecutive_lows += 1

        if consecutive_lows == 0:
            label = "طالب في وضع أكاديمي سليم"
        elif consecutive_lows == 1:
            label = f"إنذار أكاديمي أول (معدل فصلي أقل من {warning_threshold:.0f}%)"
        elif consecutive_lows == 2:
            label = "إنذار أكاديمي ثانٍ (فصلان متتاليان دون إزالة الإنذار)"
        else:
            label = "أكثر من إنذارين متتاليين (يستدعي دراسة حالة للفصل المحتمل)"

        try:
            cgpa = float(cumulative_gpa or 0.0)
        except Exception:
            cgpa = 0.0

        semesters_count = len(ordered)
        if semesters_count and cgpa < dismissal_cgpa_threshold:
            if semesters_count < dismissal_min_semesters:
                label += (
                    f" — المعدل التراكمي أقل من {dismissal_cgpa_threshold:.0f}% في هذه المرحلة المبكرة من الدراسة؛ "
                    f"يُنصح الطالب بتحسين أدائه لتفادي الوصول إلى حد الفصل وفق اللائحة."
                )
            else:
                label += (
                    f" — المعدل التراكمي أقل من {dismissal_cgpa_threshold:.0f}% بعد {semesters_count} فصل/فصول دراسية منذ الالتحاق؛ "
                    f"وفق المادة 40 أو ما يعادلها قد يُعرض الطالب للفصل، مع إمكانية منحه فرصة استثنائية واحدة حسب اللوائح."
                )

    extra_chance = False
    extra_note = ""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            row = cur.execute(
                """
                SELECT id, type, note, is_active
                FROM student_exceptions
                WHERE student_id = ? AND type = 'extra_chance'
                ORDER BY id DESC
                LIMIT 1
                """,
                (student_id,),
            ).fetchone()
            if row and row[3]:
                extra_chance = True
                extra_note = row[2] or ""
    except Exception:
        extra_chance = False
        extra_note = ""

    return {
        "label": label,
        "extra_chance": extra_chance,
        "extra_note": extra_note,
    }


def _export_transcript_excel(data, academic_status=None):
    buf = io.BytesIO()
    now = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"transcript_{data['student_id']}_{now}.xlsx"

    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        workbook = writer.book
        worksheet = workbook.add_worksheet("Transcript")
        writer.sheets["Transcript"] = worksheet

        bold = workbook.add_format({"bold": True})
        header_fmt = workbook.add_format({"bold": True, "bg_color": "#f0f0f0"})
        number_fmt = workbook.add_format({"num_format": "0.00"})

        row = 0
        worksheet.write(row, 0, "اسم الطالب", bold)
        worksheet.write(row, 1, data.get("student_name") or "")
        row += 1
        worksheet.write(row, 0, "الرقم الدراسي", bold)
        worksheet.write(row, 1, data.get("student_id") or "")
        row += 1
        worksheet.write(row, 0, "المعدل التراكمي", bold)
        worksheet.write(row, 1, data.get("cumulative_gpa") or 0, number_fmt)
        row += 1
        worksheet.write(row, 0, "الوحدات المنجزة", bold)
        worksheet.write(row, 1, data.get("completed_units") or 0)
        row += 2

        transcript = data.get("transcript", {})
        semester_gpas = data.get("semester_gpas", {})
        ordered_semesters = data.get("ordered_semesters", [])

        if not ordered_semesters:
            worksheet.write(row, 0, "لا توجد بيانات درجات متاحة", bold)
            row += 2
        else:
            for sem in ordered_semesters:
                worksheet.write(row, 0, f"الفصل: {sem}", bold)
                worksheet.write(row, 4, "المعدل الفصلي", bold)
                worksheet.write(row, 5, semester_gpas.get(sem, 0.0), number_fmt)

                # مجاميع وحدات ودرجات الفصل
                sem_courses = transcript.get(sem, []) or []
                sem_units = 0
                sem_points = 0.0
                for course in sem_courses:
                    u = int(course.get("units") or 0)
                    g = course.get("grade")
                    sem_units += u
                    if g is not None:
                        try:
                            sem_points += float(g) * u
                        except Exception:
                            pass
                worksheet.write(row, 6, "مجموع وحدات الفصل", bold)
                worksheet.write(row, 7, sem_units)
                worksheet.write(row, 8, "مجموع الدرجات", bold)
                worksheet.write(row, 9, sem_points, number_fmt)
                row += 1

                headers = ["المقرر", "الرمز", "الوحدات", "الدرجة"]
                for col, title in enumerate(headers):
                    worksheet.write(row, col, title, header_fmt)
                row += 1

        # ملاحظات أكاديمية في نهاية الكشف
        if academic_status:
            note = academic_status.get("label") or ""
            if academic_status.get("extra_chance"):
                note += (" — " if note else "") + "فرصة استثنائية"
                extra = academic_status.get("extra_note") or ""
                if extra:
                    note += f" ({extra})"
            worksheet.write(row, 0, "ملاحظات أكاديمية", bold)
            worksheet.write(row, 1, note)
            row += 1

        # ملاحظة رسمية عامة
        formal_note = (
            "هذا الكشف لغرض المتابعة الداخلية فقط، ولا يُعتد به لأي إجراءات رسمية مثل النقل أو التسجيل الخارجي. "
            "الإجراء الأكاديمي والمالي الرسمي يتم حصراً عن طريق مكتب المسجّل ومكتب الدراسة والامتحانات بالكلية."
        )
        worksheet.write(row, 0, "تنبيه رسمي", bold)
        worksheet.write(row, 1, formal_note)
        worksheet.set_column(0, 0, 32)
        worksheet.set_column(1, 1, 16)
        worksheet.set_column(2, 3, 12)
        worksheet.set_column(4, 5, 18)
        worksheet.set_column(6, 9, 18)

    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )


@grades_bp.route("/export/<student_id>")
@login_required
def export_transcript(student_id):
    fmt = (request.args.get("format") or "excel").lower()
    mode = (request.args.get("mode") or "detailed").lower()
    semester_filter = (request.args.get("semester") or "").strip()

    data = _load_transcript_data(student_id)

    # في حال تم تحديد فصل لفلترة التصدير، نقتصر على هذا الفصل فقط
    if semester_filter:
        sem = semester_filter
        original_transcript = data.get("transcript", {})
        if sem in original_transcript:
            data = {
                **data,
                "transcript": {sem: original_transcript.get(sem, [])},
                "ordered_semesters": [sem],
                "semester_gpas": {
                    sem: data.get("semester_gpas", {}).get(sem, 0.0),
                },
            }
    academic_status = _compute_academic_status(student_id, data)

    if fmt in ("excel", "xlsx"):
        if mode == "summary":
            # تصدير ملخّص: وحدات منجزة + معدل تراكمي فقط
            summary = {
                "student_id": [data.get("student_id", "")],
                "student_name": [data.get("student_name", "")],
                "completed_units": [data.get("completed_units", 0)],
                "cumulative_gpa": [data.get("cumulative_gpa", 0.0)],
            }
            df = pd.DataFrame(summary)
            return excel_response_from_df(df, filename_prefix="transcript_summary")
        return _export_transcript_excel(data, academic_status=academic_status)
    if fmt in ("text", "txt"):
        return Response(str(data), mimetype="text/plain")
    if fmt in ("pdf",):
        # استخدام قالب HTML رسمي لكشف الدرجات وتحويله إلى PDF جاهز للطباعة
        from flask import render_template

        # احسب مجاميع وحدات/درجات كل فصل للتقارير
        semester_totals = {}
        for sem, courses in data.get("transcript", {}).items():
            sem_units = 0
            sem_points = 0.0
            for course in courses or []:
                u = int(course.get("units") or 0)
                g = course.get("grade")
                sem_units += u
                if g is not None:
                    try:
                        sem_points += float(g) * u
                    except Exception:
                        pass
            semester_totals[sem] = {"units": sem_units, "points": sem_points}

        html = render_template(
            "export_transcript.html",
            student_id=data["student_id"],
            student_name=data.get("student_name", ""),
            transcript=data.get("transcript", {}),
            ordered_semesters=data.get("ordered_semesters", []),
            semester_gpas=data.get("semester_gpas", {}),
            cumulative_gpa=data.get("cumulative_gpa", 0.0),
            completed_units=data.get("completed_units", 0),
            semester_totals=semester_totals,
            academic_status=academic_status,
        )
        return pdf_response_from_html(html, filename_prefix=f"transcript_{student_id}")
    return jsonify({"status": "error", "message": "صيغة تصدير غير مدعومة"}), 400


@grades_bp.route("/delete/semester", methods=["POST"])
@role_required("admin")
def delete_semester():
    """Delete all grades for a student in a semester. Records audit rows for each deleted course."""
    data = request.get_json(force=True)
    student_id = data.get("student_id")
    semester = data.get("semester")
    changed_by = data.get("changed_by", "admin")

    if not student_id or not semester:
        return jsonify({"status": "error", "message": "student_id و semester مطلوبة"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT course_name, grade FROM grades WHERE student_id = ? AND semester = ?",
            (student_id, semester),
        ).fetchall()

        if not rows:
            return jsonify({"status": "ok", "message": "لا توجد درجات للحذف", "deleted": 0}), 200

        now_iso = datetime.datetime.utcnow().isoformat()
        deleted = 0
        for r in rows:
            # r can be Row or tuple
            if hasattr(r, "keys"):
                cname = r["course_name"]
                oldg = r["grade"]
            else:
                cname = r[0]
                oldg = r[1] if len(r) > 1 else None

            cur.execute(
                "INSERT INTO grade_audit (student_id, semester, course_name, old_grade, new_grade, changed_by, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (student_id, semester, cname, (float(oldg) if oldg is not None else None), None, changed_by, now_iso),
            )
            deleted += 1

        cur.execute(
            "DELETE FROM grades WHERE student_id = ? AND semester = ?",
            (student_id, semester),
        )
        conn.commit()

    return jsonify({"status": "ok", "message": f"تم حذف {deleted} سجل(سجلات) للفصل {semester}", "deleted": deleted}), 200


@grades_bp.route("/delete/course", methods=["POST"])
@role_required("admin")
def delete_course():
    """Delete a single course result for a student in a semester. Records an audit row."""
    data = request.get_json(force=True)
    student_id = data.get("student_id")
    semester = data.get("semester")
    course_name = data.get("course_name")
    changed_by = data.get("changed_by", "admin")

    if not student_id or not semester or not course_name:
        return jsonify({"status": "error", "message": "student_id و semester و course_name مطلوبة"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT grade FROM grades WHERE student_id = ? AND semester = ? AND course_name = ?",
            (student_id, semester, course_name),
        ).fetchone()

        if not row:
            return jsonify({"status": "ok", "message": "لا يوجد سجل لهذه المادة", "deleted": 0}), 200

        old_grade = row[0] if not hasattr(row, "keys") else row["grade"]
        now_iso = datetime.datetime.utcnow().isoformat()

        cur.execute(
            "INSERT INTO grade_audit (student_id, semester, course_name, old_grade, new_grade, changed_by, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (student_id, semester, course_name, (float(old_grade) if old_grade is not None else None), None, changed_by, now_iso),
        )

        cur.execute(
            "DELETE FROM grades WHERE student_id = ? AND semester = ? AND course_name = ?",
            (student_id, semester, course_name),
        )
        conn.commit()

    return jsonify({"status": "ok", "message": f"تم حذف سجل المقرر {course_name}", "deleted": 1}), 200

