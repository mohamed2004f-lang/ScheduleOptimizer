import sys
import os
from collections import defaultdict, OrderedDict
import datetime
import io
import math
import pandas as pd

# ensure parent package is importable when running modules directly in some environments
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask import Blueprint, request, jsonify, Response, send_file
from models.models import Grade
from .utilities import get_connection, df_from_query, excel_response_from_df, pdf_response_from_html


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
            return jsonify({"status": "ok", "message": "تم حفظ الدرجات وتسجيل التعديلات"}), 200
        except Exception as e:
            conn.rollback()
            return jsonify({"status": "error", "message": str(e)}), 500



@grades_bp.route("/migrate_registrations_to_transcript", methods=["POST"])
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
        student_row = cur.execute(
            "SELECT COALESCE(student_name, '') AS student_name FROM students WHERE student_id = ?",
            (student_id,),
        ).fetchone()
        student_name = student_row["student_name"] if student_row else ""

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
        total_units = sum(max(u, 0) for _, u in lst)
        semester_gpas[sem] = round(
            sum(grade * (max(units, 0)) for grade, units in lst) / total_units, 2
        ) if total_units else 0.0

    total_points = 0.0
    total_units = 0.0
    for info in best_map.values():
        units = max(info["units"] or 0, 0)
        total_units += units
        total_points += (info["best_grade"] * units)
    cumulative_gpa = round(total_points / total_units, 2) if total_units else 0.0

    ordered_semesters = list(transcript.keys())

    return {
        "student_id": student_id,
        "student_name": student_name,
        "transcript": transcript,
        "ordered_semesters": ordered_semesters,
        "semester_gpas": semester_gpas,
        "cumulative_gpa": cumulative_gpa,
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
                        sem,
                        cname,
                        ccode,
                        units,
                        float(grade_val) if grade_val is not None else None,
                    ),
                )
                inserted_total += 1

        conn.commit()

    sem_list = [sem for sem, _ in normalized_semesters]
    return jsonify({"status": "ok", "message": f"تم استيراد {inserted_total} درجة", "student_id": student_id, "semesters": sem_list}), 200


@grades_bp.route("/update", methods=["POST"])
def update_grade():
    data = request.get_json(force=True)
    sid = data.get("student_id")
    semester = data.get("semester")
    course = data.get("course_name")
    new_grade_raw = data.get("grade")
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
            "SELECT course_code, units, grade FROM grades WHERE student_id=? AND semester=? AND course_name=?", (sid, semester, course)
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
        else:
            # try to fetch course defaults from courses table
            course_row = cur.execute("SELECT course_code, units FROM courses WHERE course_name = ? LIMIT 1", (course,)).fetchone()
            if course_row:
                try:
                    course_code_to_use = course_row[0] if len(course_row) > 0 else (course_row['course_code'] if 'course_code' in course_row.keys() else "")
                except Exception:
                    course_code_to_use = course_row['course_code'] if 'course_code' in course_row.keys() else ""
                try:
                    units_to_use = int(course_row[1]) if len(course_row) > 1 and course_row[1] is not None else (int(course_row['units']) if 'units' in course_row.keys() and course_row['units'] is not None else 0)
                except Exception:
                    try:
                        units_to_use = int(course_row['units']) if 'units' in course_row.keys() and course_row['units'] is not None else 0
                    except Exception:
                        units_to_use = 0

        cur.execute(
            "INSERT INTO grade_audit (student_id, semester, course_name, old_grade, new_grade, changed_by, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, semester, course, old_grade, (float(new_grade) if new_grade is not None else None),
             changed_by, datetime.datetime.utcnow().isoformat())
        )

        cur.execute(
            "INSERT OR REPLACE INTO grades (student_id, semester, course_name, course_code, units, grade) VALUES (?, ?, ?, ?, ?, ?)",
            (sid, semester, course, course_code_to_use or "", int(units_to_use or 0), (float(new_grade) if new_grade is not None else None))
        )
        conn.commit()

    return jsonify({"status": "ok", "message": "تم تعديل الدرجة"}), 200


@grades_bp.route("/transcript/<student_id>")
def get_transcript(student_id):
    data = _load_transcript_data(student_id)
    return jsonify({
        "student_id": data["student_id"],
        "student_name": data.get("student_name", ""),
        "transcript": data["transcript"],
        "semester_gpas": data["semester_gpas"],
        "cumulative_gpa": data["cumulative_gpa"],
        "ordered_semesters": data.get("ordered_semesters", []),
    })


def _export_transcript_excel(data):
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
        row += 2

        transcript = data.get("transcript", {})
        semester_gpas = data.get("semester_gpas", {})
        ordered_semesters = data.get("ordered_semesters", [])

        if not ordered_semesters:
            worksheet.write(row, 0, "لا توجد بيانات درجات متاحة", bold)
        else:
            for sem in ordered_semesters:
                worksheet.write(row, 0, f"الفصل: {sem}", bold)
                worksheet.write(row, 4, "المعدل الفصلي", bold)
                worksheet.write(row, 5, semester_gpas.get(sem, 0.0), number_fmt)
                row += 1

                headers = ["المقرر", "الرمز", "الوحدات", "الدرجة"]
                for col, title in enumerate(headers):
                    worksheet.write(row, col, title, header_fmt)
                row += 1

                for course in transcript.get(sem, []):
                    worksheet.write(row, 0, course.get("course_name") or "")
                    worksheet.write(row, 1, course.get("course_code") or "")
                    worksheet.write(row, 2, course.get("units") or 0)
                    grade = course.get("grade")
                    if grade is None:
                        worksheet.write(row, 3, "-")
                    else:
                        worksheet.write(row, 3, float(grade), number_fmt)
                    row += 1

                row += 1

        worksheet.set_column(0, 0, 32)
        worksheet.set_column(1, 1, 16)
        worksheet.set_column(2, 3, 12)
        worksheet.set_column(4, 5, 18)

    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )


@grades_bp.route("/export/<student_id>")
def export_transcript(student_id):
    fmt = (request.args.get("format") or "excel").lower()
    data = _load_transcript_data(student_id)
    if fmt in ("excel", "xlsx"):
        return _export_transcript_excel(data)
    if fmt in ("text", "txt"):
        return Response(str(data), mimetype="text/plain")
    return jsonify({"status": "error", "message": "صيغة تصدير غير مدعومة"}), 400


@grades_bp.route("/delete/semester", methods=["POST"])
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

