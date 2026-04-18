import sys
import os
from collections import defaultdict, OrderedDict
import datetime
import io
import math
import pandas as pd

# ensure parent package is importable when running modules directly in some environments
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask import Blueprint, request, jsonify, Response, send_file, session, current_app
from backend.core.auth import login_required, role_required, current_supervisor_effective
from backend.database.database import is_postgresql, schedule_pk_column, fetch_table_columns
from .utilities import (
    get_connection,
    get_current_term,
    schedule_semester_matches_current_term,
    excel_response_from_df,
    pdf_response_from_html,
    log_activity,
)

PASSING_GRADE = 50
DEFAULT_COURSEWORK_WEIGHT = 10.0
DEFAULT_MIDTERM_WEIGHT = 30.0
DEFAULT_FINAL_EXAM_WEIGHT = 60.0

grades_bp = Blueprint("grades", __name__)
SCHEDULE_PK_COL = "id"


def _sync_schedule_pk_col(conn) -> str:
    global SCHEDULE_PK_COL
    try:
        SCHEDULE_PK_COL = schedule_pk_column(conn)
    except Exception:
        pass
    return SCHEDULE_PK_COL


def _now_iso_z() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _current_user_name() -> str:
    return (session.get("user") or session.get("username") or "").strip()


def _is_supervisor_role() -> bool:
    return current_supervisor_effective()


def _current_semester_label(conn) -> str:
    term_name, term_year = get_current_term(conn=conn)
    return f"{(term_name or '').strip()} {(term_year or '').strip()}".strip()


def _faculty_cycle_lock_key(term_label: str) -> str:
    return f"faculty_cycle_lock::{(term_label or '').strip()}"


def _is_faculty_cycle_locked(conn, term_label: str) -> bool:
    row = conn.cursor().execute(
        "SELECT COALESCE(value_json,'false') FROM app_settings WHERE key = ? LIMIT 1",
        (_faculty_cycle_lock_key(term_label),),
    ).fetchone()
    raw = (row[0] if row else "false") or "false"
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _instructor_name_for_session(conn) -> str:
    instructor_id = session.get("instructor_id")
    if not instructor_id:
        return ""
    cur = conn.cursor()
    row = cur.execute(
        "SELECT name FROM instructors WHERE id = ? LIMIT 1",
        (int(instructor_id),),
    ).fetchone()
    return (row[0] if row else "") or ""


def _allowed_courses_for_instructor_current_term(conn) -> list:
    """
    يرجع قائمة أسماء المقررات المسندة للأستاذ في الفصل الحالي من جدول schedule.
    """
    sections = _allowed_sections_for_instructor_current_term(conn)
    return sorted({(x.get("course_name") or "").strip() for x in sections if (x.get("course_name") or "").strip()})


def _allowed_sections_for_instructor_current_term(conn) -> list[dict]:
    """
    الشعب المسندة للأستاذ في الفصل الحالي مع section_id/course_name.
    يطابق منطق جدول الأستاذ الأسبوعي (تطبيع الاسم + instructor_id) ثم يحصر الفصل الحالي.
    """
    instructor_id = session.get("instructor_id")
    if not instructor_id:
        return []
    instructor_name = _instructor_name_for_session(conn)
    semester_label = _current_semester_label(conn)
    if not semester_label or not (instructor_name or "").strip():
        return []
    try:
        iid = int(instructor_id)
    except (TypeError, ValueError):
        return []

    from backend.core.faculty_axes import normalize_instructor_name
    from backend.services.schedule import _assigned_section_rows

    cur = conn.cursor()
    canon = normalize_instructor_name(instructor_name)
    tuples = _assigned_section_rows(cur, iid, canon)
    out = []
    for t in tuples:
        sid, cn, _day, _tim, _room, _inst_txt, sem = t
        if not schedule_semester_matches_current_term(sem, semester_label):
            continue
        out.append({"section_id": int(sid), "course_name": (cn or "")})
    out.sort(key=lambda x: (x["course_name"], x["section_id"]))
    return out


def _resolve_assigned_section_for_course(conn, course_name: str, section_id: int | None = None):
    sections = _allowed_sections_for_instructor_current_term(conn)
    if not sections:
        return None
    if section_id is not None:
        for s in sections:
            if int(s["section_id"]) == int(section_id):
                if str(s["course_name"] or "").strip() != str(course_name or "").strip():
                    return None
                return s
        return None
    for s in sections:
        if str(s["course_name"] or "").strip() == str(course_name or "").strip():
            return s
    return None


def _instructor_can_access_draft(conn, draft_row) -> bool:
    """Own draft: session instructor_id must match draft; allowed for instructor or staff rows linked to same faculty id."""
    role = (session.get("user_role") or "").strip()
    if _is_supervisor_role():
        return False
    if role not in ("instructor", "head_of_department", "admin_main", "admin"):
        return False
    if not session.get("instructor_id"):
        return False
    if int(draft_row["instructor_id"] or 0) != int(session.get("instructor_id") or 0):
        return False
    sid = draft_row["section_id"] if hasattr(draft_row, "keys") else draft_row[3]
    course_name = draft_row["course_name"] if hasattr(draft_row, "keys") else draft_row[2]
    try:
        sid_int = int(sid) if sid not in (None, "") else None
    except (TypeError, ValueError):
        sid_int = None
    return _resolve_assigned_section_for_course(conn, course_name, sid_int) is not None


def _can_delete_grade_draft(conn, draft_row) -> bool:
    """
    سياسة الحذف:
    - instructor: يمكن حذف Draft فقط لمسودته.
    - admin/admin_main: يمكن حذف Draft أو Rejected.
    - لا حذف بعد Submitted/Approved.
    """
    status = str((draft_row["status"] if hasattr(draft_row, "keys") else "") or "").strip()
    role = (session.get("user_role") or "").strip()
    if role == "instructor":
        return status == "Draft" and _instructor_can_access_draft(conn, draft_row)
    if role in ("admin", "admin_main"):
        return status in ("Draft", "Rejected")
    return False


def _course_grading_mode(conn, course_name: str) -> str:
    cur = conn.cursor()
    cols = fetch_table_columns(conn, "courses")
    if "grading_mode" not in cols:
        return "partial_final"
    row = cur.execute(
        "SELECT COALESCE(grading_mode,'partial_final') FROM courses WHERE course_name = ? LIMIT 1",
        (course_name,),
    ).fetchone()
    m = (row[0] if row else "partial_final") or "partial_final"
    m = str(m).strip().lower()
    return m if m in ("partial_final", "final_total_only") else "partial_final"


def _normalize_assessment_type(raw: str) -> str:
    v = str(raw or "").strip().lower()
    arabic_map = {
        "نظري": "theoretical",
        "عملي": "practical",
        "تدريب": "training",
    }
    if v in arabic_map:
        return arabic_map[v]
    if v in ("theoretical", "practical", "training"):
        return v
    return "theoretical"


def _assessment_weights_for_type(assessment_type: str) -> tuple[float, float, float]:
    """
    أوزان استرشادية افتراضية:
    - النظري: 10/30/60
    - العملي: 20/20/60
    - التدريب: 40/0/60
    """
    t = _normalize_assessment_type(assessment_type)
    if t == "practical":
        return (20.0, 20.0, 60.0)
    if t == "training":
        return (40.0, 0.0, 60.0)
    return (DEFAULT_COURSEWORK_WEIGHT, DEFAULT_MIDTERM_WEIGHT, DEFAULT_FINAL_EXAM_WEIGHT)


def _safe_weight(v, fallback: float) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return float(fallback)
    if n < 0 or n > 100:
        return float(fallback)
    return float(n)


def _course_assessment_profile(conn, course_name: str) -> dict:
    """
    ملف تقييم المقرر (استرشادي غير إلزامي):
    - assessment_type: theoretical/practical/training
    - weights: coursework/midterm/final_exam
    """
    cur = conn.cursor()
    try:
        row = cur.execute(
            """
            SELECT
              COALESCE(assessment_type, 'theoretical') AS assessment_type,
              coursework_weight, midterm_weight, final_exam_weight
            FROM courses
            WHERE course_name = ?
            LIMIT 1
            """,
            (course_name,),
        ).fetchone()
    except Exception:
        row = None
    atype = _normalize_assessment_type((row["assessment_type"] if row and hasattr(row, "keys") else "theoretical") if row else "theoretical")
    def_cw, def_md, def_fe = _assessment_weights_for_type(atype)
    cw_raw = (row["coursework_weight"] if row and hasattr(row, "keys") else None) if row else None
    md_raw = (row["midterm_weight"] if row and hasattr(row, "keys") else None) if row else None
    fe_raw = (row["final_exam_weight"] if row and hasattr(row, "keys") else None) if row else None
    return {
        "assessment_type": atype,
        "weights": {
            "coursework": _safe_weight(cw_raw, def_cw),
            "midterm": _safe_weight(md_raw, def_md),
            "final_exam": _safe_weight(fe_raw, def_fe),
        },
        "advisory_only": True,
    }


def _compute_total_for_mode(mode: str, partial, final, total):
    """
    - partial_final: instructor can send partial+final OR total; we compute best available.
    - final_total_only: use total only (100-only course).
    """
    if mode == "final_total_only":
        return total
    # partial_final
    if total is not None:
        return total
    if partial is None and final is None:
        return None
    p = float(partial or 0)
    f = float(final or 0)
    return p + f


def _compute_total_from_components(coursework, midterm, final_exam, fallback_partial, fallback_final, fallback_total):
    """أولوية الحساب: أعمال+جزئي+نهائي، ثم fallback القديم."""
    if coursework is not None or midterm is not None or final_exam is not None:
        c = float(coursework or 0)
        m = float(midterm or 0)
        fe = float(final_exam or 0)
        return c + m + fe
    return _compute_total_for_mode("partial_final", fallback_partial, fallback_final, fallback_total)


def _validate_component_value(label: str, value, max_value: float):
    if value is None:
        return True, None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False, f"{label} يجب أن تكون رقمية"
    if v < 0 or v > max_value:
        return False, f"{label} يجب أن تكون بين 0 و {int(max_value)}"
    return True, v


def _resolve_catalog_course(cur, course_name: str = "", course_code: str = ""):
    """
    Resolve course by code/name from catalog with strict consistency.
    Returns dict {course_name, course_code, units} or raises ValueError.
    """
    cname = (course_name or "").strip()
    ccode = (course_code or "").strip()

    row_by_code = None
    row_by_name = None
    if ccode:
        row_by_code = cur.execute(
            "SELECT course_name, COALESCE(course_code,'') AS course_code, COALESCE(units,0) AS units FROM courses WHERE course_code = ? LIMIT 1",
            (ccode,),
        ).fetchone()
        if not row_by_code:
            raise ValueError(f"رمز المقرر غير موجود في دليل المقررات: {ccode}")
    def _norm_name(s: str) -> str:
        s = str(s or "").strip().lower()
        # normalize common Arabic variants and separators
        s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
        s = s.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
        s = s.replace("ـ", "")
        for ch in ("-", "_", "/", "\\", "(", ")", "[", "]", "{", "}", "،", ",", ".", ":", ";"):
            s = s.replace(ch, " ")
        s = " ".join(s.split())
        return s

    if cname:
        row_by_name = cur.execute(
            "SELECT course_name, COALESCE(course_code,'') AS course_code, COALESCE(units,0) AS units FROM courses WHERE course_name = ? LIMIT 1",
            (cname,),
        ).fetchone()
        # fallback: normalized-name match to handle minor writing variants
        if not row_by_name:
            target_norm = _norm_name(cname)
            all_rows = cur.execute(
                "SELECT course_name, COALESCE(course_code,'') AS course_code, COALESCE(units,0) AS units FROM courses"
            ).fetchall()
            for rr in all_rows or []:
                rr_name = (rr[0] if isinstance(rr, (list, tuple)) else rr["course_name"]) or ""
                if _norm_name(rr_name) == target_norm and target_norm:
                    row_by_name = rr
                    break
        if not row_by_name and not row_by_code:
            raise ValueError(f"اسم المقرر غير موجود في دليل المقررات: {cname}")

    # if both provided, ensure they point to same catalog row
    if row_by_code and row_by_name:
        name_code = row_by_code[0] if isinstance(row_by_code, (list, tuple)) else row_by_code["course_name"]
        name_name = row_by_name[0] if isinstance(row_by_name, (list, tuple)) else row_by_name["course_name"]
        if str(name_code).strip() != str(name_name).strip():
            raise ValueError(f"عدم تطابق بين اسم المقرر ({cname}) ورمزه ({ccode})")

    row = row_by_code or row_by_name
    if not row:
        raise ValueError("يجب توفير اسم مقرر أو رمز مقرر صحيح")
    out_name = (row[0] if isinstance(row, (list, tuple)) else row["course_name"]) or ""
    out_code = (row[1] if isinstance(row, (list, tuple)) else row["course_code"]) or ""
    out_units = (row[2] if isinstance(row, (list, tuple)) else row["units"]) or 0
    if not str(out_code).strip():
        raise ValueError(f"المقرر '{out_name}' لا يملك رمزاً معتمداً في دليل المقررات")
    return {"course_name": str(out_name).strip(), "course_code": str(out_code).strip(), "units": int(out_units or 0)}


_GRADE_DRAFT_SELF_SERVICE_ROLES = ("instructor", "head_of_department", "admin_main", "admin")


@grades_bp.route("/drafts/courses", methods=["GET"])
@role_required(*_GRADE_DRAFT_SELF_SERVICE_ROLES)
def draft_courses_current_term():
    """
    قائمة مقررات الأستاذ في الفصل الحالي (لإنشاء مسودة).
    """
    with get_connection() as conn:
        sections = _allowed_sections_for_instructor_current_term(conn)
    courses = sorted({(x.get("course_name") or "").strip() for x in sections if (x.get("course_name") or "").strip()})
    return jsonify({"status": "ok", "courses": courses, "sections": sections}), 200


@grades_bp.route("/drafts/mine", methods=["GET"])
@role_required(*_GRADE_DRAFT_SELF_SERVICE_ROLES)
def list_my_grade_drafts():
    """مسودات الأستاذ للفصل الحالي (سجل واحد لكل مقرر حسب القيد الفريد)."""
    if _is_supervisor_role():
        return jsonify({"status": "ok", "drafts": [], "semester": ""}), 200
    instructor_id = session.get("instructor_id")
    if not instructor_id:
        return jsonify({"status": "error", "message": "لا يوجد ربط بين حسابك وعضو هيئة تدريس"}), 403
    with get_connection() as conn:
        semester_label = _current_semester_label(conn)
        if not semester_label:
            return jsonify({"status": "ok", "drafts": [], "semester": ""}), 200
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT id, semester, course_name, section_id, grading_mode, status,
                   created_at, updated_at, submitted_at, approved_at, approved_by, instructor_id, note
            FROM grade_drafts
            WHERE instructor_id = ? AND semester = ?
            ORDER BY course_name, section_id
            """,
            (int(instructor_id), semester_label),
        ).fetchall()
    drafts = []
    for r in rows or []:
        row_dict = dict(r)
        row_dict["can_delete"] = bool(_can_delete_grade_draft(conn, r))
        drafts.append(row_dict)
    return jsonify({"status": "ok", "drafts": drafts, "semester": semester_label}), 200


@grades_bp.route("/drafts/roster", methods=["GET"])
@role_required(*_GRADE_DRAFT_SELF_SERVICE_ROLES)
def draft_roster_for_course():
    """الطلاب المسجلون في المقرر (من جدول registrations) بعد التحقق من إسناد المقرر للأستاذ."""
    if _is_supervisor_role():
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
    course_name = (request.args.get("course_name") or "").strip()
    section_id = request.args.get("section_id", type=int)
    if not course_name:
        return jsonify({"status": "error", "message": "course_name مطلوب"}), 400
    with get_connection() as conn:
        _sync_schedule_pk_col(conn)
        section_row = _resolve_assigned_section_for_course(conn, course_name, section_id)
        if not section_row:
            return jsonify({"status": "error", "message": "المقرر غير مسند لك في الفصل الحالي"}), 403
        section_id = int(section_row["section_id"])
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT DISTINCT r.student_id, COALESCE(s.student_name, '') AS student_name
            FROM registrations r
            JOIN schedule sc ON sc.course_name = r.course_name
            LEFT JOIN students s ON s.student_id = r.student_id
            WHERE r.course_name = ?
              AND sc.{SCHEDULE_PK_COL} = ?
            ORDER BY student_name, r.student_id
            """,
            (course_name, section_id),
        ).fetchall()
    roster = [{"student_id": r[0], "student_name": r[1] or ""} for r in rows] if rows else []
    return jsonify({"status": "ok", "roster": roster}), 200


@grades_bp.route("/drafts/pending", methods=["GET"])
@role_required("admin_main", "head_of_department")
def list_pending_grade_drafts():
    """مسودات بانتظار الاعتماد للفصل الحالي."""
    with get_connection() as conn:
        semester_label = _current_semester_label(conn)
        cur = conn.cursor()
        if not semester_label:
            return jsonify({"status": "ok", "pending": [], "semester": ""}), 200
        rows = cur.execute(
            """
            SELECT d.id, d.semester, d.course_name, d.section_id, d.grading_mode, d.status,
                   d.created_at, d.updated_at, d.submitted_at,
                   d.instructor_id, COALESCE(i.name, '') AS instructor_name
            FROM grade_drafts d
            LEFT JOIN instructors i ON i.id = d.instructor_id
            WHERE d.semester = ? AND d.status = 'Submitted'
            ORDER BY d.submitted_at DESC, d.course_name, d.section_id
            """,
            (semester_label,),
        ).fetchall()
    pending = [dict(r) for r in rows] if rows else []
    return jsonify({"status": "ok", "pending": pending, "semester": semester_label}), 200


@grades_bp.route("/drafts/deletable", methods=["GET"])
@role_required("admin", "admin_main")
def list_deletable_grade_drafts():
    """مسودات قابلة للحذف للأدمن في الفصل الحالي (Draft/Rejected)."""
    with get_connection() as conn:
        semester_label = _current_semester_label(conn)
        cur = conn.cursor()
        if not semester_label:
            return jsonify({"status": "ok", "drafts": [], "semester": ""}), 200
        rows = cur.execute(
            """
            SELECT d.id, d.semester, d.course_name, d.section_id, d.grading_mode, d.status,
                   d.created_at, d.updated_at, d.submitted_at,
                   d.instructor_id, COALESCE(i.name, '') AS instructor_name
            FROM grade_drafts d
            LEFT JOIN instructors i ON i.id = d.instructor_id
            WHERE d.semester = ? AND d.status IN ('Draft','Rejected')
            ORDER BY d.updated_at DESC, d.course_name, d.section_id
            """,
            (semester_label,),
        ).fetchall()
        drafts = []
        for r in rows or []:
            item = dict(r)
            item["can_delete"] = bool(_can_delete_grade_draft(conn, r))
            drafts.append(item)
    return jsonify({"status": "ok", "drafts": drafts, "semester": semester_label}), 200


@grades_bp.route("/drafts", methods=["POST"])
@role_required(*_GRADE_DRAFT_SELF_SERVICE_ROLES)
def create_grade_draft():
    """
    إنشاء مسودة درجات لمقرر واحد في الفصل الحالي.
    body:
      - course_name
      - section_id
    """
    if _is_supervisor_role():
        # المشرف لا يستخدم مسار مسودات الأستاذ (لتفادي الالتباس)
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403

    data = request.get_json(force=True) or {}
    course_name = (data.get("course_name") or "").strip()
    section_id_raw = data.get("section_id")
    section_id = None
    if section_id_raw not in (None, ""):
        try:
            section_id = int(section_id_raw)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "section_id غير صالح"}), 400
    if not course_name:
        return jsonify({"status": "error", "message": "course_name مطلوب"}), 400

    with get_connection() as conn:
        _sync_schedule_pk_col(conn)
        cur = conn.cursor()
        semester_label = _current_semester_label(conn)
        if _is_faculty_cycle_locked(conn, semester_label):
            return jsonify({"status": "error", "message": "تم إغلاق دورة أعضاء هيئة التدريس لهذا الفصل"}), 423
        section_row = _resolve_assigned_section_for_course(conn, course_name, section_id)
        if not section_row:
            return jsonify({"status": "error", "message": "المقرر غير مسند لك في الفصل الحالي"}), 403
        section_id = int(section_row["section_id"])
        if not semester_label:
            return jsonify({"status": "error", "message": "لا يمكن تحديد الفصل الحالي"}), 400

        instructor_id = session.get("instructor_id")
        if not instructor_id:
            return jsonify({"status": "error", "message": "لا يوجد ربط بين حسابك وعضو هيئة تدريس"}), 403

        # منع أكثر من مسودة مفتوحة في نفس الوقت للأستاذ (مقرر واحد فقط في كل مرة)
        row_open = cur.execute(
            """
            SELECT id FROM grade_drafts
            WHERE instructor_id = ?
              AND semester = ?
              AND status IN ('Draft','Submitted')
            LIMIT 1
            """,
            (int(instructor_id), semester_label),
        ).fetchone()
        if row_open:
            return jsonify({"status": "error", "message": "لديك مسودة مفتوحة بالفعل لهذا الفصل"}), 400

        # قيد فريد في قاعدة البيانات على (semester, course_name, instructor_id)
        # لذلك نتحقق مسبقاً ونُرجع رسالة واضحة بدل 500.
        row_same_course = cur.execute(
            """
            SELECT id, status, COALESCE(section_id,0) AS section_id
            FROM grade_drafts
            WHERE instructor_id = ?
              AND semester = ?
              AND course_name = ?
            LIMIT 1
            """,
            (int(instructor_id), semester_label, course_name),
        ).fetchone()
        if row_same_course:
            existing_id = int(row_same_course["id"] if hasattr(row_same_course, "keys") else row_same_course[0])
            existing_status = str((row_same_course["status"] if hasattr(row_same_course, "keys") else row_same_course[1]) or "").strip()
            existing_section = int(row_same_course["section_id"] if hasattr(row_same_course, "keys") else (row_same_course[2] or 0))
            if existing_status == "Approved":
                return jsonify({
                    "status": "error",
                    "message": "توجد مسودة معتمدة لهذا المقرر في الفصل الحالي ولا يمكن إنشاء مسودة جديدة له",
                    "draft_id": existing_id,
                    "existing_status": existing_status,
                    "section_id": existing_section or None,
                }), 400
            return jsonify({
                "status": "ok",
                "draft_id": existing_id,
                "grading_mode": _course_grading_mode(conn, course_name),
                "section_id": existing_section or section_id,
                "existing": True,
                "existing_status": existing_status,
            }), 200

        grading_mode = _course_grading_mode(conn, course_name)
        now = _now_iso_z()
        if is_postgresql():
            row_new = cur.execute(
                """
                INSERT INTO grade_drafts
                (semester, course_name, section_id, instructor_id, grading_mode, status, created_at, updated_at)
                VALUES (?,?,?,?,?, 'Draft', ?, ?)
                RETURNING id
                """,
                (semester_label, course_name, section_id, int(instructor_id), grading_mode, now, now),
            ).fetchone()
            draft_id = int(row_new[0]) if row_new else 0
        else:
            cur.execute(
                """
                INSERT INTO grade_drafts
                (semester, course_name, section_id, instructor_id, grading_mode, status, created_at, updated_at)
                VALUES (?,?,?,?,?, 'Draft', ?, ?)
                """,
                (semester_label, course_name, section_id, int(instructor_id), grading_mode, now, now),
            )
            draft_id = int(cur.lastrowid or 0)
        conn.commit()

    return jsonify({"status": "ok", "draft_id": int(draft_id), "grading_mode": grading_mode, "section_id": section_id}), 200


@grades_bp.route("/drafts/<int:draft_id>", methods=["GET"])
@role_required("instructor", "head_of_department", "admin_main", "admin")
def get_grade_draft(draft_id: int):
    with get_connection() as conn:
        cur = conn.cursor()
        d = cur.execute(
            "SELECT * FROM grade_drafts WHERE id = ?",
            (int(draft_id),),
        ).fetchone()
        if not d:
            return jsonify({"status": "error", "message": "draft not found"}), 404

        # Scope: instructor (non-supervisor) sees own drafts only; HoD/admin may preview any for approval.
        role = (session.get("user_role") or "").strip()
        if role == "instructor" and not _is_supervisor_role():
            if not _instructor_can_access_draft(conn, d):
                return jsonify({"status": "error", "message": "FORBIDDEN"}), 403

        items = cur.execute(
            """
            SELECT student_id, coursework, midterm, final_exam, absent_midterm, absent_final_exam,
                   partial, final, total, computed_total, updated_at
            FROM grade_draft_items
            WHERE draft_id = ?
            ORDER BY student_id
            """,
            (int(draft_id),),
        ).fetchall()
        out_items = [dict(r) for r in items] if items else []
        can_delete = bool(_can_delete_grade_draft(conn, d))
        assessment_profile = _course_assessment_profile(conn, (d["course_name"] or "").strip())

    draft_dict = dict(d)
    draft_dict["can_delete"] = can_delete
    draft_dict["assessment_profile"] = assessment_profile
    return jsonify({"status": "ok", "draft": draft_dict, "items": out_items}), 200


@grades_bp.route("/drafts/<int:draft_id>", methods=["DELETE"])
@role_required(*_GRADE_DRAFT_SELF_SERVICE_ROLES)
def delete_grade_draft(draft_id: int):
    """حذف مسودة درجات وفق صلاحيات محددة (للتجارب قبل الاعتماد)."""
    with get_connection() as conn:
        cur = conn.cursor()
        d = cur.execute("SELECT * FROM grade_drafts WHERE id = ?", (int(draft_id),)).fetchone()
        if not d:
            return jsonify({"status": "error", "message": "draft not found"}), 404
        if not _can_delete_grade_draft(conn, d):
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
        cur.execute("DELETE FROM grade_draft_items WHERE draft_id = ?", (int(draft_id),))
        cur.execute("DELETE FROM grade_drafts WHERE id = ?", (int(draft_id),))
        conn.commit()
    return jsonify({"status": "ok", "deleted": True, "draft_id": int(draft_id)}), 200


@grades_bp.route("/drafts/<int:draft_id>/items", methods=["POST"])
@role_required(*_GRADE_DRAFT_SELF_SERVICE_ROLES)
def save_grade_draft_items(draft_id: int):
    if _is_supervisor_role():
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403

    data = request.get_json(force=True) or {}
    items = data.get("items") or []
    if not isinstance(items, list):
        return jsonify({"status": "error", "message": "items must be list"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        d = cur.execute(
            "SELECT * FROM grade_drafts WHERE id = ?",
            (int(draft_id),),
        ).fetchone()
        if not d:
            return jsonify({"status": "error", "message": "draft not found"}), 404
        if not _instructor_can_access_draft(conn, d):
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
        if _is_faculty_cycle_locked(conn, (d["semester"] or "").strip()):
            return jsonify({"status": "error", "message": "تم إغلاق دورة أعضاء هيئة التدريس لهذا الفصل"}), 423
        if (d["status"] or "") not in ("Draft", "Rejected"):
            return jsonify({"status": "error", "message": "لا يمكن تعديل مسودة ليست Draft/Rejected"}), 400

        now = _now_iso_z()

        saved = 0
        for it in items:
            sid = str((it or {}).get("student_id") or "").strip()
            if not sid:
                continue
            coursework = it.get("coursework", None)
            midterm = it.get("midterm", None)
            final_exam = it.get("final_exam", None)
            absent_midterm = 1 if bool(it.get("absent_midterm", False)) else 0
            absent_final_exam = 1 if bool(it.get("absent_final_exam", False)) else 0
            partial = it.get("partial", None)  # دعم قديم
            final = it.get("final", None)      # دعم قديم
            total = it.get("total", None)      # دعم قديم

            # الطالب الغائب في الاختبار تُقيّد درجته بصفر تلقائياً.
            if absent_midterm:
                midterm = 0
            if absent_final_exam:
                final_exam = 0

            # validate
            ok, cv = _validate_component_value("درجة الأعمال", coursework, 100.0)
            if not ok:
                return jsonify({"status": "error", "message": f"{sid}: {cv}"}), 400
            ok, mv = _validate_component_value("درجة الجزئي", midterm, 100.0)
            if not ok:
                return jsonify({"status": "error", "message": f"{sid}: {mv}"}), 400
            ok, fv2 = _validate_component_value("درجة النهائي", final_exam, 100.0)
            if not ok:
                return jsonify({"status": "error", "message": f"{sid}: {fv2}"}), 400
            ok, pv = validate_grade_value(partial)
            if not ok:
                return jsonify({"status": "error", "message": f"partial invalid for {sid}: {pv}"}), 400
            ok, fv = validate_grade_value(final)
            if not ok:
                return jsonify({"status": "error", "message": f"final invalid for {sid}: {fv}"}), 400
            ok, tv = validate_grade_value(total)
            if not ok:
                return jsonify({"status": "error", "message": f"total invalid for {sid}: {tv}"}), 400

            computed = _compute_total_from_components(cv, mv, fv2, pv, fv, tv)
            ok, computed_checked = validate_grade_value(computed)
            if not ok:
                return jsonify({"status": "error", "message": f"المجموع غير صالح للطالب {sid}"}), 400
            # upsert
            cur.execute(
                """
                INSERT INTO grade_draft_items
                    (draft_id, student_id, coursework, midterm, final_exam, absent_midterm, absent_final_exam, partial, final, total, computed_total, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(draft_id, student_id) DO UPDATE SET
                  coursework=excluded.coursework,
                  midterm=excluded.midterm,
                  final_exam=excluded.final_exam,
                  absent_midterm=excluded.absent_midterm,
                  absent_final_exam=excluded.absent_final_exam,
                  partial=excluded.partial,
                  final=excluded.final,
                  total=excluded.total,
                  computed_total=excluded.computed_total,
                  updated_at=excluded.updated_at
                """,
                (int(draft_id), sid, cv, mv, fv2, absent_midterm, absent_final_exam, pv, fv, tv, computed_checked, now),
            )
            saved += 1

        cur.execute("UPDATE grade_drafts SET updated_at = ? WHERE id = ?", (now, int(draft_id)))
        conn.commit()

    return jsonify({"status": "ok", "saved": int(saved)}), 200


@grades_bp.route("/drafts/<int:draft_id>/submit", methods=["POST"])
@role_required(*_GRADE_DRAFT_SELF_SERVICE_ROLES)
def submit_grade_draft(draft_id: int):
    if _is_supervisor_role():
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
    with get_connection() as conn:
        cur = conn.cursor()
        d = cur.execute("SELECT * FROM grade_drafts WHERE id = ?", (int(draft_id),)).fetchone()
        if not d:
            return jsonify({"status": "error", "message": "draft not found"}), 404
        if not _instructor_can_access_draft(conn, d):
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
        if _is_faculty_cycle_locked(conn, (d["semester"] or "").strip()):
            return jsonify({"status": "error", "message": "تم إغلاق دورة أعضاء هيئة التدريس لهذا الفصل"}), 423
        if (d["status"] or "") not in ("Draft", "Rejected"):
            return jsonify({"status": "error", "message": "لا يمكن الإرسال إلا من Draft/Rejected"}), 400
        now = _now_iso_z()
        cur.execute(
            "UPDATE grade_drafts SET status='Submitted', submitted_at=?, updated_at=? WHERE id=?",
            (now, now, int(draft_id)),
        )
        conn.commit()
    return jsonify({"status": "ok"}), 200


@grades_bp.route("/drafts/<int:draft_id>/approve", methods=["POST"])
@role_required("admin_main", "head_of_department")
def approve_grade_draft(draft_id: int):
    """
    اعتماد المسودة ونشرها في جدول grades.
    """
    actor = _current_user_name() or "system"
    now = _now_iso_z()
    with get_connection() as conn:
        cur = conn.cursor()
        d = cur.execute("SELECT * FROM grade_drafts WHERE id = ?", (int(draft_id),)).fetchone()
        if not d:
            return jsonify({"status": "error", "message": "draft not found"}), 404
        if (d["status"] or "") not in ("Submitted",):
            return jsonify({"status": "error", "message": "لا يمكن الاعتماد إلا لمسودة Submitted"}), 400

        semester = d["semester"]
        course_name = d["course_name"]
        # نشر الدرجات
        items = cur.execute(
            "SELECT student_id, computed_total FROM grade_draft_items WHERE draft_id = ?",
            (int(draft_id),),
        ).fetchall()
        published = 0
        for it in items or []:
            sid = (it["student_id"] if hasattr(it, "keys") else it[0]) or ""
            grade_val = (it["computed_total"] if hasattr(it, "keys") else it[1])
            # نسمح بـ NULL (لم يُدخل)
            old = cur.execute(
                "SELECT grade FROM grades WHERE student_id=? AND semester=? AND course_name=?",
                (sid, semester, course_name),
            ).fetchone()
            old_grade = old[0] if old else None

            cur.execute(
                """
                INSERT INTO grades (student_id, semester, course_name, grade, updated_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(student_id, semester, course_name) DO UPDATE SET
                  grade=excluded.grade,
                  updated_at=excluded.updated_at
                """,
                (sid, semester, course_name, grade_val, now),
            )
            try:
                cur.execute(
                    "INSERT INTO grade_audit (student_id, semester, course_name, old_grade, new_grade, changed_by, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (sid, semester, course_name, old_grade, grade_val, actor, now),
                )
            except Exception:
                pass
            published += 1

        cur.execute(
            "UPDATE grade_drafts SET status='Approved', approved_at=?, approved_by=?, updated_at=? WHERE id=?",
            (now, actor, now, int(draft_id)),
        )
        conn.commit()

    return jsonify({"status": "ok", "published": int(published)}), 200


@grades_bp.route("/drafts/<int:draft_id>/reject", methods=["POST"])
@role_required("admin_main", "head_of_department")
def reject_grade_draft(draft_id: int):
    """إرجاع المسودة للأستاذ لتصحيحها (تغيير الحالة إلى Rejected مع ملاحظة)."""
    data = request.get_json(force=True) or {}
    note = (data.get("note") or "").strip()
    actor = _current_user_name() or "system"
    now = _now_iso_z()
    with get_connection() as conn:
        cur = conn.cursor()
        d = cur.execute("SELECT * FROM grade_drafts WHERE id = ?", (int(draft_id),)).fetchone()
        if not d:
            return jsonify({"status": "error", "message": "draft not found"}), 404
        if (d["status"] or "") not in ("Submitted",):
            return jsonify({"status": "error", "message": "لا يمكن الإرجاع إلا لمسودة Submitted"}), 400
        new_note = note or f"Returned by {actor}"
        cur.execute(
            "UPDATE grade_drafts SET status='Rejected', note=?, updated_at=? WHERE id=?",
            (new_note, now, int(draft_id)),
        )
        conn.commit()
    return jsonify({"status": "ok", "draft_id": int(draft_id), "returned": True}), 200


@grades_bp.route("/drafts/<int:draft_id>/correction_request", methods=["POST"])
@role_required(*_GRADE_DRAFT_SELF_SERVICE_ROLES)
def request_grade_draft_correction(draft_id: int):
    """
    طلب تصحيح رسمي بعد الاعتماد:
    - يُسمح للأستاذ (غير مشرف) لمسودته المعتمدة فقط.
    - يُسجّل كطلب pending بانتظار قرار رئيس القسم/الإدارة.
    """
    if _is_supervisor_role():
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
    data = request.get_json(force=True) or {}
    reason = (data.get("reason") or "").strip()
    if len(reason) < 5:
        return jsonify({"status": "error", "message": "يرجى إدخال سبب واضح لا يقل عن 5 أحرف"}), 400
    actor = _current_user_name() or "system"
    now = _now_iso_z()
    with get_connection() as conn:
        cur = conn.cursor()
        d = cur.execute("SELECT * FROM grade_drafts WHERE id = ?", (int(draft_id),)).fetchone()
        if not d:
            return jsonify({"status": "error", "message": "draft not found"}), 404
        if not _instructor_can_access_draft(conn, d):
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
        if str((d["status"] or "")).strip() != "Approved":
            return jsonify({"status": "error", "message": "طلب التصحيح متاح فقط بعد الاعتماد"}), 400
        pending = cur.execute(
            "SELECT id FROM grade_correction_requests WHERE draft_id = ? AND status = 'pending' LIMIT 1",
            (int(draft_id),),
        ).fetchone()
        if pending:
            req_id = int(pending["id"] if hasattr(pending, "keys") else pending[0])
            return jsonify({"status": "ok", "request_id": req_id, "existing": True}), 200
        if is_postgresql():
            row_new = cur.execute(
                """
                INSERT INTO grade_correction_requests
                (semester, draft_id, course_name, section_id, instructor_id, requested_by, reason, status, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,'pending',?,?)
                RETURNING id
                """,
                (
                    (d["semester"] or "").strip(),
                    int(draft_id),
                    (d["course_name"] or "").strip(),
                    d["section_id"],
                    int(d["instructor_id"] or 0),
                    actor,
                    reason,
                    now,
                    now,
                ),
            ).fetchone()
            req_id = int(row_new[0]) if row_new else 0
        else:
            cur.execute(
                """
                INSERT INTO grade_correction_requests
                (semester, draft_id, course_name, section_id, instructor_id, requested_by, reason, status, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,'pending',?,?)
                """,
                (
                    (d["semester"] or "").strip(),
                    int(draft_id),
                    (d["course_name"] or "").strip(),
                    d["section_id"],
                    int(d["instructor_id"] or 0),
                    actor,
                    reason,
                    now,
                    now,
                ),
            )
            req_id = int(cur.lastrowid or 0)
        conn.commit()
    try:
        log_activity(action="grade_correction_request_create", details=f"draft_id={draft_id}, request_id={req_id}")
    except Exception:
        pass
    return jsonify({"status": "ok", "request_id": req_id, "created": True}), 200


@grades_bp.route("/drafts/correction_requests", methods=["GET"])
@role_required("admin_main", "head_of_department")
def list_grade_correction_requests():
    """طلبات التصحيح الرسمية بعد الاعتماد (للمعتمدين)."""
    status = (request.args.get("status") or "pending").strip().lower()
    allowed_statuses = {"pending", "approved", "rejected", "all"}
    if status not in allowed_statuses:
        status = "pending"
    with get_connection() as conn:
        cur = conn.cursor()
        params = []
        q = """
            SELECT r.id, r.semester, r.draft_id, r.course_name, r.section_id, r.instructor_id,
                   r.requested_by, r.reason, r.status, r.review_note, r.reviewed_by, r.reviewed_at,
                   r.created_at, r.updated_at,
                   COALESCE(i.name, '') AS instructor_name
            FROM grade_correction_requests r
            LEFT JOIN instructors i ON i.id = r.instructor_id
            WHERE 1=1
        """
        if status != "all":
            q += " AND r.status = ?"
            params.append(status)
        q += " ORDER BY CASE WHEN r.status = 'pending' THEN 0 ELSE 1 END, r.created_at DESC"
        rows = cur.execute(q, tuple(params)).fetchall()
    items = [dict(r) for r in (rows or [])]
    return jsonify({"status": "ok", "items": items}), 200


@grades_bp.route("/drafts/correction_requests/<int:req_id>/review", methods=["POST"])
@role_required("admin_main", "head_of_department")
def review_grade_correction_request(req_id: int):
    """
    مراجعة طلب التصحيح:
    - approved: إعادة المسودة المعتمدة إلى Rejected لتعديلها ثم إعادة إرسالها.
    - rejected: إبقاء المسودة المعتمدة كما هي.
    """
    data = request.get_json(force=True) or {}
    new_status = (data.get("status") or "").strip().lower()
    if new_status not in ("approved", "rejected"):
        return jsonify({"status": "error", "message": "status يجب أن يكون approved أو rejected"}), 400
    review_note = (data.get("review_note") or "").strip()
    actor = _current_user_name() or "system"
    now = _now_iso_z()
    with get_connection() as conn:
        cur = conn.cursor()
        req = cur.execute(
            "SELECT * FROM grade_correction_requests WHERE id = ? LIMIT 1",
            (int(req_id),),
        ).fetchone()
        if not req:
            return jsonify({"status": "error", "message": "request not found"}), 404
        if (req["status"] or "") != "pending":
            return jsonify({"status": "error", "message": "تمت مراجعة هذا الطلب مسبقاً"}), 400

        draft_id = int(req["draft_id"] or 0)
        d = cur.execute("SELECT * FROM grade_drafts WHERE id = ? LIMIT 1", (draft_id,)).fetchone()
        if not d:
            return jsonify({"status": "error", "message": "draft not found"}), 404

        cur.execute(
            """
            UPDATE grade_correction_requests
            SET status = ?, review_note = ?, reviewed_by = ?, reviewed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_status, review_note, actor, now, now, int(req_id)),
        )
        reopened = False
        if new_status == "approved":
            merged_note = (f"[تصحيح بعد الاعتماد] طلب #{req_id} تمت الموافقة عليه"
                           + (f" — {review_note}" if review_note else ""))
            cur.execute(
                "UPDATE grade_drafts SET status='Rejected', note=?, updated_at=? WHERE id=?",
                (merged_note, now, draft_id),
            )
            reopened = True
        conn.commit()
    try:
        log_activity(action="grade_correction_request_review", details=f"request_id={req_id}, status={new_status}")
    except Exception:
        pass
    return jsonify({"status": "ok", "request_id": int(req_id), "reviewed": True, "reopened": reopened}), 200


@grades_bp.route("/special_cases", methods=["GET"])
@login_required
def list_grade_special_cases():
    role = (session.get("user_role") or "").strip()
    if role not in ("instructor", "admin", "admin_main", "head_of_department"):
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
    section_id = request.args.get("section_id", type=int)
    status = (request.args.get("status") or "").strip().lower()
    with get_connection() as conn:
        cur = conn.cursor()
        params = []
        q = """
            SELECT id, semester, section_id, course_name, instructor_id, student_id, case_type, reason,
                   status, created_at, created_by, reviewed_at, reviewed_by, review_note
            FROM grade_special_cases
            WHERE 1=1
        """
        instructor_only = (request.args.get("instructor_only") or "").strip().lower() in ("1", "true", "yes")
        if role == "instructor" and not _is_supervisor_role():
            params.append(int(session.get("instructor_id") or 0))
            q += " AND instructor_id = ?"
        elif (
            instructor_only
            and role in ("head_of_department", "admin_main", "admin")
            and session.get("instructor_id")
        ):
            params.append(int(session.get("instructor_id") or 0))
            q += " AND instructor_id = ?"
        if section_id:
            params.append(int(section_id))
            q += " AND section_id = ?"
        if status in ("submitted", "approved", "rejected"):
            params.append(status)
            q += " AND status = ?"
        q += " ORDER BY id DESC"
        rows = cur.execute(q, tuple(params)).fetchall()
    items = [dict(r) for r in (rows or [])]
    return jsonify({"status": "ok", "items": items}), 200


@grades_bp.route("/special_cases", methods=["POST"])
@role_required(*_GRADE_DRAFT_SELF_SERVICE_ROLES)
def create_grade_special_case():
    if _is_supervisor_role():
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
    data = request.get_json(force=True) or {}
    course_name = (data.get("course_name") or "").strip()
    student_id = (data.get("student_id") or "").strip()
    reason = (data.get("reason") or "").strip()
    case_type = (data.get("case_type") or "").strip().lower()
    section_id_raw = data.get("section_id")
    if not course_name or not student_id or not reason:
        return jsonify({"status": "error", "message": "course_name/student_id/reason مطلوبة"}), 400
    if case_type not in ("postponed", "deprivation", "cheating"):
        return jsonify({"status": "error", "message": "case_type غير صالح"}), 400
    try:
        section_id = int(section_id_raw)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "section_id غير صالح"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        semester = _current_semester_label(conn)
        if _is_faculty_cycle_locked(conn, semester):
            return jsonify({"status": "error", "message": "تم إغلاق دورة أعضاء هيئة التدريس لهذا الفصل"}), 423
        section_row = _resolve_assigned_section_for_course(conn, course_name, section_id)
        if not section_row:
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
        # الطالب يجب أن يكون مسجلاً في نفس الشعبة.
        row = cur.execute(
            f"""
            SELECT 1
            FROM registrations r
            JOIN schedule s ON s.course_name = r.course_name
            WHERE r.student_id = ? AND r.course_name = ? AND s.{SCHEDULE_PK_COL} = ?
            LIMIT 1
            """,
            (student_id, course_name, int(section_id)),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "الطالب غير مسجل في هذه الشعبة"}), 400
        actor = _current_user_name() or "system"
        now = _now_iso_z()
        if is_postgresql():
            row_new = cur.execute(
                """
                INSERT INTO grade_special_cases
                    (semester, section_id, course_name, instructor_id, student_id, case_type, reason, status, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'submitted', ?, ?)
                RETURNING id
                """,
                (
                    semester,
                    int(section_id),
                    course_name,
                    int(session.get("instructor_id") or 0),
                    student_id,
                    case_type,
                    reason,
                    now,
                    actor,
                ),
            ).fetchone()
            case_id = int(row_new[0]) if row_new else 0
        else:
            cur.execute(
                """
                INSERT INTO grade_special_cases
                    (semester, section_id, course_name, instructor_id, student_id, case_type, reason, status, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'submitted', ?, ?)
                """,
                (
                    semester,
                    int(section_id),
                    course_name,
                    int(session.get("instructor_id") or 0),
                    student_id,
                    case_type,
                    reason,
                    now,
                    actor,
                ),
            )
            case_id = int(cur.lastrowid or 0)
        conn.commit()
    return jsonify({"status": "ok", "case_id": case_id}), 200


@grades_bp.route("/special_cases/<int:case_id>/review", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def review_grade_special_case(case_id: int):
    data = request.get_json(force=True) or {}
    status = (data.get("status") or "").strip().lower()
    review_note = (data.get("review_note") or "").strip()
    if status not in ("approved", "rejected"):
        return jsonify({"status": "error", "message": "status يجب أن يكون approved أو rejected"}), 400
    actor = _current_user_name() or "system"
    now = _now_iso_z()
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute("SELECT id FROM grade_special_cases WHERE id = ? LIMIT 1", (int(case_id),)).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "case not found"}), 404
        cur.execute(
            """
            UPDATE grade_special_cases
            SET status = ?, review_note = ?, reviewed_at = ?, reviewed_by = ?
            WHERE id = ?
            """,
            (status, review_note, now, actor, int(case_id)),
        )
        conn.commit()
    return jsonify({"status": "ok", "case_id": int(case_id), "reviewed_status": status}), 200


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
@role_required("admin", "admin_main", "head_of_department")
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
                course = (g.get("course_name") or "").strip()
                course_code_in = (g.get("course_code") or "").strip()
                resolved = _resolve_catalog_course(cur, course_name=course, course_code=course_code_in)
                course = resolved["course_name"]
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
                    """
                    INSERT INTO grades (student_id, semester, course_name, course_code, units, grade)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (student_id, semester, course_name) DO UPDATE SET
                        course_code = EXCLUDED.course_code,
                        units = EXCLUDED.units,
                        grade = EXCLUDED.grade
                    """,
                    (sid, semester, course, resolved["course_code"], int(resolved["units"] or 0),
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
@role_required("admin", "admin_main", "head_of_department")
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

        # تشديد الربط: المقرر يجب أن يكون موجوداً في الدليل وبرمز معتمد
        for _, cname, _units in course_columns:
            _resolve_catalog_course(cur, course_name=cname, course_code="")

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
                    INSERT INTO students (student_id, student_name)
                    VALUES (?, COALESCE((SELECT student_name FROM students WHERE student_id = ?), ''))
                    ON CONFLICT (student_id) DO NOTHING
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

                resolved = _resolve_catalog_course(cur, course_name=cname, course_code="")
                cname_final = resolved["course_name"]
                ccode_final = resolved["course_code"]
                units_final = int(resolved["units"] or units or 0)

                key = (student_id, cname_final)
                old_grade = existing_map.get(key)

                cur.execute(
                    """
                    INSERT INTO grade_audit (student_id, semester, course_name, old_grade, new_grade, changed_by, ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        student_id,
                        semester,
                        cname_final,
                        float(old_grade) if old_grade is not None else None,
                        float(grade_val) if grade_val is not None else None,
                        changed_by,
                        now_iso,
                    ),
                )

                cur.execute(
                    """
                    INSERT INTO grades (student_id, semester, course_name, course_code, units, grade)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (student_id, semester, course_name) DO UPDATE SET
                        course_code = EXCLUDED.course_code,
                        units = EXCLUDED.units,
                        grade = EXCLUDED.grade
                    """,
                    (
                        student_id,
                        semester,
                        cname_final,
                        ccode_final,
                        units_final,
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
@role_required("admin", "admin_main", "head_of_department")
def migrate_registrations_to_transcript():
    data = request.get_json(force=True)
    student_id = data.get("student_id")
    semester = (data.get("semester") or "").strip()
    year = (data.get("year") or "").strip()
    changed_by = data.get("changed_by", "migrate-ui")
    if not student_id:
        return jsonify({"status": "error", "message": "student_id مطلوب"}), 400
    with get_connection() as conn:
        # إذا لم يُمرّر الفصل أو السنة، نستخدم الفصل الحالي من الإعدادات
        if not semester or not year:
            def_term_name, def_term_year = get_current_term(conn=conn)
            if not semester:
                semester = def_term_name
            if not year:
                year = def_term_year
        semester_label = f"{semester} {year}".strip()
        if not semester_label:
            return jsonify({"status": "error", "message": "الفصل والسنة مطلوبان (أدخلهما أو اضبط الفصل الحالي في الصفحة)"}), 400
        cur = conn.cursor()
        # registrations table schema may vary across installs. Try to select course_code/units
        # if present; otherwise select only course_name and look up code/units from `courses`.
        regs = None
        try:
            cols = fetch_table_columns(conn, "registrations")
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

        # بعد الترحيل الناجح إلى جدول grades، نحذف تسجيلات الطالب الفعلية من جدول registrations
        # حتى لا تبقى مكررة بين التسجيلات الحالية وكشف الدرجات.
        cur.execute(
            "DELETE FROM registrations WHERE student_id = ?",
            (student_id,),
        )

        # اختيارياً: أرشفة خطة التسجيل المعتمدة لهذا الفصل إن وجدت (لا يؤثر إذا لم توجد).
        try:
            cur.execute(
                """
                UPDATE enrollment_plans
                SET status = 'Archived', updated_at = ?
                WHERE student_id = ? AND semester = ? AND status = 'Approved'
                """,
                (now_iso, student_id, semester_label),
            )
        except Exception:
            # في حال اختلاف المخطط أو غياب الجدول، نتجاهل الخطأ بصمت حتى لا نفشل عملية الترحيل.
            pass

        conn.commit()
    return jsonify({"status": "ok", "message": f"تم ترحيل {inserted} مقرر للفصل {semester_label}", "semester": semester_label, "inserted": inserted}), 200


def _load_transcript_data(student_id: str):
    with get_connection() as conn:
        cur = conn.cursor()
        cols = fetch_table_columns(conn, "students")
        has_plan = "graduation_plan" in cols
        has_join = "join_term" in cols and "join_year" in cols
        sel = "SELECT COALESCE(student_name, '') AS student_name"
        if has_plan:
            sel += ", COALESCE(graduation_plan, '') AS graduation_plan"
        if has_join:
            sel += ", COALESCE(join_term, '') AS join_term, COALESCE(join_year, '') AS join_year"
        sel += " FROM students WHERE student_id = ?"
        student_row = cur.execute(sel, (student_id,)).fetchone()
        student_name = student_row["student_name"] if student_row else ""
        graduation_plan = ""
        join_term = ""
        join_year = ""
        if student_row and has_plan:
            try:
                graduation_plan = (student_row["graduation_plan"] or "").strip()
            except (KeyError, IndexError, TypeError):
                pass
        if student_row and has_join:
            try:
                join_term = (student_row["join_term"] or "").strip()
                join_year = (student_row["join_year"] or "").strip()
            except (KeyError, IndexError, TypeError):
                pass

        grade_rows = cur.execute(
            """
            SELECT semester, course_name, course_code, units, grade
            FROM grades
            WHERE student_id = ?
            ORDER BY semester, course_name
            """,
            (student_id,),
        ).fetchall()

        # حالة المقررات الاختيارية بعد 100 وحدة
        try:
            from backend.services.electives import check_electives_requirement
            electives_status = check_electives_requirement(cur, student_id, required_electives=3)
        except Exception:
            electives_status = {"active": False, "ok": True, "waived": False}

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

    # الوحدات المنجزة لكل فصل دراسي (مقررات ناجحة فقط، درجة >= حد النجاح)
    semester_completed_units = {}
    for sem, courses_list in transcript.items():
        sem_completed = 0
        for c in courses_list:
            units = max(c.get("units") or 0, 0)
            if units <= 0 and (c.get("course_name") or "") in course_units_from_db:
                units = course_units_from_db[c["course_name"]]
            grade = c.get("grade")
            if grade is not None and float(grade) >= PASSING_GRADE:
                sem_completed += max(0, units)
        semester_completed_units[sem] = int(sem_completed)

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
        "join_term": join_term,
        "join_year": join_year,
        "transcript": transcript,
        "ordered_semesters": ordered_semesters,
        "semester_gpas": semester_gpas,
        "semester_completed_units": semester_completed_units,
        "cumulative_gpa": cumulative_gpa,
        "completed_units": completed_units,
        "completed_units_breakdown": completed_units_breakdown,
        "electives_status": electives_status,
    }


def _load_all_transcripts_bulk(student_ids: list[str] | None = None) -> dict:
    """
    جلب بيانات كشوف الدرجات لجميع الطلاب (أو مجموعة محددة) دفعة واحدة.
    تُرجع dict مفتاحه student_id وقيمته نفس الهيكل الذي تُرجعه _load_transcript_data.
    تحل مشكلة N+1 Queries عند الحاجة لبيانات عدد كبير من الطلاب.
    """
    result: dict = {}

    with get_connection() as conn:
        cur = conn.cursor()

        # --- 1) جلب بيانات الطلاب الأساسية ---
        cols = fetch_table_columns(conn, "students")
        has_plan = "graduation_plan" in cols
        has_join = "join_term" in cols and "join_year" in cols

        sel_parts = ["student_id", "COALESCE(student_name, '') AS student_name"]
        if has_plan:
            sel_parts.append("COALESCE(graduation_plan, '') AS graduation_plan")
        if has_join:
            sel_parts.append("COALESCE(join_term, '') AS join_term")
            sel_parts.append("COALESCE(join_year, '') AS join_year")

        if student_ids is not None:
            if len(student_ids) == 0:
                return result
            placeholders = ",".join("?" for _ in student_ids)
            sql = "SELECT " + ", ".join(sel_parts) + f" FROM students WHERE student_id IN ({placeholders})"
            student_rows = cur.execute(sql, tuple(student_ids)).fetchall()
        else:
            sql = "SELECT " + ", ".join(sel_parts) + " FROM students"
            student_rows = cur.execute(sql).fetchall()

        students_map: dict = {}
        for sr in student_rows:
            sid = sr["student_id"]
            students_map[sid] = {
                "student_name": (sr["student_name"] or ""),
                "graduation_plan": ((sr["graduation_plan"] or "").strip() if has_plan else ""),
                "join_term": ((sr["join_term"] or "").strip() if has_join else ""),
                "join_year": ((sr["join_year"] or "").strip() if has_join else ""),
            }

        if not students_map:
            return result

        all_sids = list(students_map.keys())

        # --- 2) جلب جميع الدرجات دفعة واحدة ---
        placeholders = ",".join("?" for _ in all_sids)
        grade_rows = cur.execute(
            f"""
            SELECT student_id, semester, course_name, course_code, units, grade
            FROM grades
            WHERE student_id IN ({placeholders})
            ORDER BY student_id, semester, course_name
            """,
            tuple(all_sids),
        ).fetchall()

        # تجميع الدرجات حسب الطالب
        grades_by_student: dict = defaultdict(list)
        for gr in grade_rows:
            grades_by_student[gr["student_id"]].append(gr)

        # --- 3) جلب وحدات المقررات من جدول courses (دفعة واحدة) ---
        all_course_names: set = set()
        for gr in grade_rows:
            cname = gr["course_name"] or ""
            if cname:
                all_course_names.add(cname)

        course_units_from_db: dict = {}
        if all_course_names:
            cnames_list = list(all_course_names)
            placeholders_c = ",".join("?" for _ in cnames_list)
            course_rows = cur.execute(
                f"SELECT course_name, COALESCE(units, 0) AS u FROM courses WHERE course_name IN ({placeholders_c})",
                tuple(cnames_list),
            ).fetchall()
            for cr in course_rows:
                u = int(cr["u"] or 0)
                if u > 0:
                    course_units_from_db[cr["course_name"]] = u

        # --- 4) معالجة بيانات كل طالب ---
        for sid, sinfo in students_map.items():
            student_grade_rows = grades_by_student.get(sid, [])

            transcript = OrderedDict()
            gpa_by_semester: dict = defaultdict(list)
            best_map: dict = {}

            for row in student_grade_rows:
                sem = row["semester"] or ""
                course_name = row["course_name"] or ""
                course_code = row["course_code"] or ""
                units = row["units"] or 0
                grade = row["grade"]

                transcript.setdefault(sem, []).append({
                    "course_name": course_name,
                    "course_code": course_code,
                    "units": units,
                    "grade": grade,
                })

                if grade is not None:
                    gpa_by_semester[sem].append((grade, units))

                if grade is not None:
                    if course_name not in best_map or grade > best_map[course_name]["best_grade"]:
                        best_map[course_name] = {"best_grade": grade, "units": units}
                    else:
                        if units and (not best_map[course_name]["units"] or units > best_map[course_name]["units"]):
                            best_map[course_name]["units"] = units

            semester_gpas: dict = {}
            for sem, lst in gpa_by_semester.items():
                total_units_sem = sum(max(u, 0) for _, u in lst)
                semester_gpas[sem] = (
                    round(
                        sum(g * max(u, 0) for g, u in lst) / total_units_sem,
                        2,
                    )
                    if total_units_sem
                    else 0.0
                )

            # الوحدات المنجزة لكل فصل دراسي
            semester_completed_units: dict = {}
            for sem, courses_list in transcript.items():
                sem_completed = 0
                for c in courses_list:
                    u = max(c.get("units") or 0, 0)
                    if u <= 0 and (c.get("course_name") or "") in course_units_from_db:
                        u = course_units_from_db[c["course_name"]]
                    g = c.get("grade")
                    if g is not None and float(g) >= PASSING_GRADE:
                        sem_completed += max(0, u)
                semester_completed_units[sem] = int(sem_completed)

            total_points = 0.0
            total_units = 0.0
            completed_units = 0
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
            cumulative_gpa = round(total_points / total_units, 2) if total_units else 0.0
            completed_units = int(completed_units)

            ordered_semesters = list(transcript.keys())

            result[sid] = {
                "student_id": sid,
                "student_name": sinfo["student_name"],
                "graduation_plan": sinfo["graduation_plan"],
                "join_term": sinfo["join_term"],
                "join_year": sinfo["join_year"],
                "transcript": transcript,
                "ordered_semesters": ordered_semesters,
                "semester_gpas": semester_gpas,
                "semester_completed_units": semester_completed_units,
                "cumulative_gpa": cumulative_gpa,
                "completed_units": completed_units,
            }

    return result


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
@role_required("admin", "admin_main", "head_of_department")
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
@role_required("admin", "admin_main", "head_of_department")
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
                INSERT INTO students (student_id, student_name)
                VALUES (?, COALESCE((SELECT student_name FROM students WHERE student_id = ?), ''))
                ON CONFLICT (student_id) DO NOTHING
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
                ccode_in = (course.get("course_code") or "").strip()
                resolved = _resolve_catalog_course(cur, course_name=cname, course_code=ccode_in)
                cname = resolved["course_name"]
                ccode = resolved["course_code"]
                units = int(resolved["units"] or 0)
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
                    INSERT INTO grades (student_id, semester, course_name, course_code, units, grade)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (student_id, semester, course_name) DO UPDATE SET
                        course_code = EXCLUDED.course_code,
                        units = EXCLUDED.units,
                        grade = EXCLUDED.grade
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
@role_required("admin", "admin_main", "head_of_department")
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
                    code_val = course_row["course_code"] if "course_code" in course_row.keys() else (course_row[0] if len(course_row) > 0 else "")
                    course_code_to_use = (code_val or "") or course_code_to_use
                except Exception:
                    try:
                        course_code_to_use = (course_row[0] or "") or course_code_to_use
                    except Exception:
                        pass
                try:
                    u_val = course_row["units"] if "units" in course_row.keys() else (course_row[1] if len(course_row) > 1 else None)
                    if u_val is not None:
                        units_to_use = int(u_val)
                except Exception:
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
                # تشديد الربط: لا نقبل رمزاً غير موجود في الدليل
                return jsonify({"status": "error", "message": f"رمز المقرر غير موجود في دليل المقررات: {new_course_code}"}), 400

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
            """
            INSERT INTO grades (student_id, semester, course_name, course_code, units, grade)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (student_id, semester, course_name) DO UPDATE SET
                course_code = EXCLUDED.course_code,
                units = EXCLUDED.units,
                grade = EXCLUDED.grade
            """,
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


@grades_bp.route("/course_mapping_issues", methods=["GET"])
@role_required("admin", "admin_main", "head_of_department")
def course_mapping_issues():
    """
    يعرض سجلات grades غير المطابقة مع دليل المقررات.
    الحالات:
      - missing_code: لا يوجد رمز مقرر في السجل
      - invalid_code: الرمز غير موجود في دليل المقررات
      - name_code_mismatch: الرمز صحيح لكن الاسم لا يطابق اسم المقرر في الدليل
    """
    semester = (request.args.get("semester") or "").strip()
    sid = (request.args.get("student_id") or "").strip()
    with get_connection() as conn:
        cur = conn.cursor()
        sql = """
        SELECT g.student_id,
               COALESCE(s.student_name,'') AS student_name,
               g.semester,
               g.course_name,
               COALESCE(g.course_code,'') AS course_code,
               COALESCE(g.units,0) AS units,
               g.grade,
               cc.course_name AS code_course_name,
               COALESCE(cc.course_code,'') AS code_course_code,
               COALESCE(cc.units,0) AS code_units,
               cn.course_name AS name_course_name,
               COALESCE(cn.course_code,'') AS name_course_code,
               COALESCE(cn.units,0) AS name_units
        FROM grades g
        LEFT JOIN students s ON s.student_id = g.student_id
        LEFT JOIN courses cc
          ON LOWER(TRIM(COALESCE(g.course_code,''))) <> ''
         AND LOWER(TRIM(cc.course_code)) = LOWER(TRIM(g.course_code))
        LEFT JOIN courses cn
          ON LOWER(TRIM(cn.course_name)) = LOWER(TRIM(g.course_name))
        WHERE 1=1
        """
        params = []
        if semester:
            sql += " AND g.semester = ?"
            params.append(semester)
        if sid:
            sql += " AND g.student_id = ?"
            params.append(sid)
        sql += " ORDER BY g.semester DESC, g.student_id, g.course_name"
        rows = cur.execute(sql, params).fetchall()

    items = []
    stats = {"missing_code": 0, "invalid_code": 0, "name_code_mismatch": 0, "total_issues": 0}
    for r in rows or []:
        d = dict(r)
        code = (d.get("course_code") or "").strip()
        g_name = (d.get("course_name") or "").strip()
        code_name = (d.get("code_course_name") or "").strip()
        issue = None
        if not code:
            issue = "missing_code"
        elif not code_name:
            issue = "invalid_code"
        elif code_name != g_name:
            issue = "name_code_mismatch"
        if not issue:
            continue

        suggested_name = ""
        suggested_code = ""
        suggested_units = 0
        if issue == "missing_code":
            # إن وجد المقرر بالاسم في الدليل، اقترحه
            suggested_name = (d.get("name_course_name") or "").strip()
            suggested_code = (d.get("name_course_code") or "").strip()
            suggested_units = int(d.get("name_units") or 0)
        else:
            suggested_name = code_name
            suggested_code = (d.get("code_course_code") or "").strip()
            suggested_units = int(d.get("code_units") or 0)

        stats[issue] += 1
        stats["total_issues"] += 1
        items.append({
            "student_id": d.get("student_id"),
            "student_name": d.get("student_name") or "",
            "semester": d.get("semester") or "",
            "course_name": g_name,
            "course_code": code,
            "units": int(d.get("units") or 0),
            "grade": d.get("grade"),
            "issue_type": issue,
            "suggested_course_name": suggested_name,
            "suggested_course_code": suggested_code,
            "suggested_units": suggested_units,
        })

    return jsonify({"status": "ok", "items": items, "stats": stats}), 200


@grades_bp.route("/course_mapping_fix", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def course_mapping_fix():
    """
    تصحيح ربط مقرر في grades عبر اختيار مقرر معتمد من دليل المقررات.
    body:
      - student_id, semester, current_course_name
      - target_course_name (مطلوب)
      - changed_by (اختياري)
    """
    try:
        data = request.get_json(force=True) or {}
        sid = (data.get("student_id") or "").strip()
        semester = (data.get("semester") or "").strip()
        current_name = (data.get("current_course_name") or "").strip()
        target_name = (data.get("target_course_name") or "").strip()
        changed_by = (data.get("changed_by") or session.get("user") or "mapping-fix").strip()
        if not sid or not semester or not current_name or not target_name:
            return jsonify({"status": "error", "message": "student_id و semester و current_course_name و target_course_name مطلوبة"}), 400

        with get_connection() as conn:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT grade FROM grades WHERE student_id=? AND semester=? AND course_name=? LIMIT 1",
                (sid, semester, current_name),
            ).fetchone()
            if not row:
                return jsonify({"status": "error", "message": "سجل الدرجة الحالي غير موجود"}), 404
            grade_val = row[0] if isinstance(row, (list, tuple)) else row["grade"]

            resolved = _resolve_catalog_course(cur, course_name=target_name, course_code="")
            target_name_final = resolved["course_name"]
            target_code = resolved["course_code"]
            target_units = int(resolved["units"] or 0)

            if target_name_final != current_name:
                conflict = cur.execute(
                    "SELECT 1 FROM grades WHERE student_id=? AND semester=? AND course_name=? LIMIT 1",
                    (sid, semester, target_name_final),
                ).fetchone()
                if conflict:
                    return jsonify({"status": "error", "message": "يوجد سجل آخر بنفس المقرر الهدف لهذا الطالب/الفصل. يرجى دمجه يدوياً أولاً."}), 409

            cur.execute(
                """
                UPDATE grades
                   SET course_name = ?, course_code = ?, units = ?
                 WHERE student_id = ? AND semester = ? AND course_name = ?
                """,
                (target_name_final, target_code, target_units, sid, semester, current_name),
            )

            def _to_float_or_none(v):
                if v is None:
                    return None
                try:
                    return float(v)
                except Exception:
                    return None

            cur.execute(
                "INSERT INTO grade_audit (student_id, semester, course_name, old_grade, new_grade, changed_by, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    sid,
                    semester,
                    target_name_final,
                    _to_float_or_none(grade_val),
                    _to_float_or_none(grade_val),
                    changed_by,
                    datetime.datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()

        return jsonify({"status": "ok", "message": "تم تصحيح ربط المقرر بنجاح"}), 200
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception as exc:
        try:
            current_app.logger.exception("course_mapping_fix failed")
        except Exception:
            pass
        return jsonify({"status": "error", "message": f"فشل التصحيح: {exc}"}), 500


@grades_bp.route("/rename_semester", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def rename_semester():
    """
    تعديل اسم فصل (مثلاً من \"خريف 24-25\" إلى \"خريف 25-26\").
    التعديل يؤثر على جميع الدرجات في جدول grades (و grade_audit) التي تحمل هذا الاسم.
    مخصص للأدمن فقط.
    """
    data = request.get_json(force=True) or {}
    old_sem = (data.get("old_semester") or "").strip()
    new_sem = (data.get("new_semester") or "").strip()
    if not old_sem or not new_sem:
        return jsonify({"status": "error", "message": "old_semester و new_semester مطلوبة"}), 400
    if old_sem == new_sem:
        return jsonify({"status": "error", "message": "لا يوجد تغيير في اسم الفصل"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        cnt_row = cur.execute("SELECT COUNT(*) FROM grades WHERE semester = ?", (old_sem,)).fetchone()
        count = cnt_row[0] if cnt_row else 0
        if count == 0:
            return jsonify({"status": "error", "message": "لا توجد درجات تحمل هذا الفصل"}), 404

        cur.execute("UPDATE grades SET semester = ? WHERE semester = ?", (new_sem, old_sem))
        try:
            cur.execute("UPDATE grade_audit SET semester = ? WHERE semester = ?", (new_sem, old_sem))
        except Exception:
            pass
        conn.commit()

        try:
            log_activity(
                action="rename_semester",
                details=f"old={old_sem}, new={new_sem}, rows={count}",
            )
        except Exception:
            pass

    return jsonify({"status": "ok", "message": f"تم تحديث اسم الفصل إلى '{new_sem}' لعدد {count} سجل/سجلات."}), 200


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
    sup_eff = current_supervisor_effective()
    if sup_eff:
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
    # الأستاذ (غير المشرف) يمكنه عرض سجلات الطلاب المرتبطين بمقرراته في الفصل الحالي فقط
    if user_role == "instructor" and not sup_eff:
        instructor_id = session.get("instructor_id")
        if not instructor_id:
            return jsonify({
                "status": "error",
                "message": "لا يوجد ربط بين حسابك وعضو هيئة تدريس",
                "code": "FORBIDDEN"
            }), 403
        with get_connection() as conn:
            cur = conn.cursor()
            instr_row = cur.execute(
                "SELECT name FROM instructors WHERE id = ? LIMIT 1",
                (instructor_id,),
            ).fetchone()
            if not instr_row:
                return jsonify({
                    "status": "error",
                    "message": "لا يمكن تحديد المدرّس المرتبط بحسابك",
                    "code": "FORBIDDEN"
                }), 403
            instructor_name = instr_row[0]

            term_name, term_year = get_current_term(conn=conn)
            semester_label = f"{(term_name or '').strip()} {(term_year or '').strip()}".strip()
            if not semester_label:
                return jsonify({
                    "status": "error",
                    "message": "لا يمكن تحديد الفصل الحالي",
                    "code": "FORBIDDEN"
                }), 403

            allowed = cur.execute(
                """
                SELECT 1
                FROM registrations r
                JOIN schedule s ON r.course_name = s.course_name
                WHERE r.student_id = ?
                  AND s.semester = ?
                  AND s.instructor = ?
                LIMIT 1
                """,
                (student_id, semester_label, instructor_name),
            ).fetchone()
            if not allowed:
                return jsonify({
                    "status": "error",
                    "message": "لا يمكنك عرض سجل طالب غير مسند إلى مقرراتك في الفصل الحالي",
                    "code": "FORBIDDEN"
                }), 403
    data = _load_transcript_data(student_id)
    return jsonify({
        "student_id": data["student_id"],
        "student_name": data.get("student_name", ""),
        "graduation_plan": data.get("graduation_plan", ""),
        "join_term": data.get("join_term", ""),
        "join_year": data.get("join_year", ""),
        "transcript": data["transcript"],
        "semester_completed_units": data.get("semester_completed_units", {}),
        "semester_gpas": data["semester_gpas"],
        "cumulative_gpa": data["cumulative_gpa"],
        "completed_units": data.get("completed_units", 0),
        "ordered_semesters": data.get("ordered_semesters", []),
        "completed_units_breakdown": data.get("completed_units_breakdown", []),
        "electives_status": data.get("electives_status", {}),
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

    # تقييد التصدير حسب الدور (منع التلاعب عبر استدعاء endpoint مباشرة)
    user_role = session.get("user_role")
    if user_role == "student":
        sid_session = session.get("student_id") or session.get("user")
        if sid_session != student_id:
            return jsonify({
                "status": "error",
                "message": "لا يمكنك تصدير سجل طالب آخر",
                "code": "FORBIDDEN"
            }), 403

    sup_eff = current_supervisor_effective()
    if sup_eff:
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
                    "message": "لا يمكنك تصدير سجل طالب غير مُسند إليك",
                    "code": "FORBIDDEN"
                }), 403

    if user_role == "instructor" and not sup_eff:
        instructor_id = session.get("instructor_id")
        if not instructor_id:
            return jsonify({
                "status": "error",
                "message": "لا يوجد ربط بين حسابك وعضو هيئة تدريس",
                "code": "FORBIDDEN"
            }), 403
        with get_connection() as conn:
            cur = conn.cursor()
            instr_row = cur.execute(
                "SELECT name FROM instructors WHERE id = ? LIMIT 1",
                (instructor_id,),
            ).fetchone()
            if not instr_row:
                return jsonify({
                    "status": "error",
                    "message": "لا يمكن تحديد المدرّس المرتبط بحسابك",
                    "code": "FORBIDDEN"
                }), 403
            instructor_name = instr_row[0]

            term_name, term_year = get_current_term(conn=conn)
            semester_label = f"{(term_name or '').strip()} {(term_year or '').strip()}".strip()
            if not semester_label:
                return jsonify({
                    "status": "error",
                    "message": "لا يمكن تحديد الفصل الحالي",
                    "code": "FORBIDDEN"
                }), 403

            allowed = cur.execute(
                """
                SELECT 1
                FROM registrations r
                JOIN schedule s ON r.course_name = s.course_name
                WHERE r.student_id = ?
                  AND s.semester = ?
                  AND s.instructor = ?
                LIMIT 1
                """,
                (student_id, semester_label, instructor_name),
            ).fetchone()
            if not allowed:
                return jsonify({
                    "status": "error",
                    "message": "لا يمكنك تصدير سجل طالب غير مسند إلى مقرراتك في الفصل الحالي",
                    "code": "FORBIDDEN"
                }), 403

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
@role_required("admin", "admin_main", "head_of_department")
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
@role_required("admin", "admin_main", "head_of_department")
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

