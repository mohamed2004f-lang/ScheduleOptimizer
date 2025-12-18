import sys
import os
from collections import defaultdict, OrderedDict
import datetime
import io
import math
import pandas as pd

# ensure parent package is importable when running as package
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


@grades_bp.route("/import/transcript", methods=["POST"])
def import_transcript_excel():
    file = request.files.get("file")
    if not file:
        return jsonify({"status": "error", "message": "ملف Excel مفقود"}), 400
    try:
        raw_bytes = file.read()
    except Exception:
        return jsonify({"status": "error", "message": "تعذر قراءة الملف"}), 400
    if not raw_bytes:
        return jsonify({"status": "error", "message": "الملف فارغ"}), 400

    try:
        df_export = pd.read_excel(io.BytesIO(raw_bytes), header=None)
    except Exception as exc:
        return jsonify({"status": "error", "message": f"فشل قراءة ملف Excel: {exc}"}), 400

    # form values
    student_id_form = _normalize_student_id(request.form.get("student_id"))
    semester_label = (request.form.get("semester") or "").strip()
    academic_year = (request.form.get("year") or "").strip()
    student_name = (request.form.get("student_name") or "").strip()
    changed_by = (request.form.get("changed_by") or "import").strip() or "import"

    provided_semester = semester_label.strip()
    if academic_year:
        provided_semester = f"{provided_semester} {academic_year}".strip()

    # try export-style parse first
    parsed_export = _parse_export_style_single_student(df_export)
    if parsed_export.get("ok"):
        return _import_export_style_single_student(
            parsed_export,
            student_id_form,
            student_name,
            provided_semester,
            changed_by,
        )

    # fallback simple 4-column
    if not student_id_form:
        return jsonify({"status": "error", "message": "student_id مطلوب"}), 400
    if not provided_semester:
        return jsonify({"status": "error", "message": "يرجى إدخال اسم الفصل أو السنة"}), 400

    try:
        df_simple = pd.read_excel(io.BytesIO(raw_bytes))
    except Exception as exc:
        return jsonify({"status": "error", "message": f"فشل قراءة ملف Excel: {exc}"}), 400

    if df_simple.empty:
        return jsonify({"status": "error", "message": "الملف لا يحتوي على بيانات"}), 400
    if df_simple.shape[1] < 4:
        return jsonify({"status": "error", "message": "يجب أن يحتوي الملف على أربعة أعمدة على الأقل"}), 400

    df_simple = df_simple.iloc[:, :4].copy()
    df_simple.columns = ["course_name", "course_code", "units", "grade"]
    df_simple["course_name"] = df_simple["course_name"].astype(str).str.strip()
    df_simple["course_code"] = df_simple["course_code"].astype(str).str.strip()
    df_simple["units"] = pd.to_numeric(df_simple["units"], errors="coerce").fillna(0).astype(int)
    df_simple["grade"] = pd.to_numeric(df_simple["grade"], errors="coerce")
    df_simple = df_simple[df_simple["course_name"].astype(bool)]

    if df_simple.empty:
        return jsonify({"status": "error", "message": "لم يتم العثور على مقررات صالحة في الملف"}), 400

    rows = df_simple.to_dict(orient="records")
    semester = provided_semester

    with get_connection() as conn:
        cur = conn.cursor()

        if student_name:
            cur.execute(
                """
                INSERT INTO students (student_id, student_name)
                VALUES (?, ?)
                ON CONFLICT(student_id) DO UPDATE SET student_name = excluded.student_name
                """,
                (student_id_form, student_name),
            )
        else:
            cur.execute(
                """
                INSERT OR IGNORE INTO students (student_id, student_name)
                VALUES (?, COALESCE((SELECT student_name FROM students WHERE student_id = ?), ''))
                """,
                (student_id_form, student_id_form),
            )

        inserted = 0
        now_iso = datetime.datetime.utcnow().isoformat()
        for row in rows:
            cname = row["course_name"]
            ccode = row["course_code"] or ""
            units = int(row["units"] or 0)
            grade = row["grade"]

            if grade is not None and (grade < 0 or grade > 100):
                conn.rollback()
                return jsonify({"status": "error", "message": f"الدرجة للمقرر {cname} يجب أن تكون بين 0 و 100"}), 400

            cur.execute(
                """
                INSERT INTO grade_audit (student_id, semester, course_name, old_grade, new_grade, changed_by, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    student_id_form,
                    semester,
                    cname,
                    None,
                    float(grade) if grade is not None else None,
                    changed_by,
                    now_iso,
                ),
            )

            cur.execute(
                """
                INSERT INTO grades (student_id, semester, course_name, course_code, units, grade)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    student_id_form,
                    semester,
                    cname,
                    ccode,
                    units,
                    float(grade) if grade is not None else None,
                ),
            )
            inserted += 1

        conn.commit()

    return jsonify({
        "status": "ok",
        "message": f"تم استيراد {inserted} مقرر للفصل {semester}",
        "student_id": student_id_form,
        "semester": semester,
    }), 200


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
        regs = cur.execute(
            "SELECT course_name, course_code, units FROM registrations WHERE student_id = ?",
            (student_id,)
        ).fetchall()
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
