import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from models.models import Course
from flask import Blueprint, request, jsonify, Response, current_app, session, send_file
from backend.core.auth import (
    login_required,
    role_required,
    _normalize_role,
    students_registry_view_only,
)
from backend.core.department_scope_policy import (
    assert_course_writable_by_actor,
    courses_department_scope_filter,
    courses_export_sql_and_params,
    course_is_college_general,
    course_is_college_shared_catalog,
    resolve_effective_department_scope_id,
    resolve_import_owning_department_id,
)
from collections import defaultdict
from .utilities import get_connection, excel_response_from_df, pdf_response_from_html
from backend.database.database import fetch_table_columns, is_postgresql
from backend.repositories import courses_repo
import io
import base64
import pandas as pd
from datetime import datetime

courses_bp = Blueprint("courses", __name__)


def _is_instructor_or_supervisor_view_only() -> bool:
    role = (session.get("user_role") or "").strip()
    if role in ("supervisor", "instructor"):
        return True
    return students_registry_view_only()


def _effective_department_scope_id(conn) -> int | None:
    uname = (session.get("user") or session.get("username") or "").strip()
    return resolve_effective_department_scope_id(conn, uname)


def _actor_username() -> str:
    return (session.get("user") or session.get("username") or "").strip()


def _forbid_course_write(conn, course_name: str):
    """يرفع ValueError إن لم يُسمح بتعديل المقرر؛ يُحوَّل إلى 403 في المسارات."""
    assert_course_writable_by_actor(conn, course_name, _actor_username())


def _courses_export_dataframe(conn) -> pd.DataFrame:
    """DataFrame لتصدير المقررات (SQLite أو PostgreSQL)."""
    sql, params = courses_export_sql_and_params(conn)
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cols = [d[0] for d in (cur.description or [])] or ["course_name", "course_code", "units"]
    return pd.DataFrame(rows, columns=cols)


def _normalize_assessment_type(raw: str) -> str:
    v = (raw or "").strip().lower()
    if v in ("theoretical", "practical", "training"):
        return v
    if v in ("نظري",):
        return "theoretical"
    if v in ("عملي",):
        return "practical"
    if v in ("تدريب",):
        return "training"
    return "theoretical"


def _safe_weight(raw, fallback: float | None = None):
    if raw in (None, ""):
        return fallback
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return fallback
    if v < 0 or v > 100:
        return fallback
    return v


def _annotate_courses_edit_meta(conn, courses: list) -> None:
    """وسم مقررات الاتجاه العام/المشترك وصلاحية التعديل لكل صف في قائمة المقررات."""
    from backend.core.college_shared_catalog import (
        get_department_plan_course_code,
        get_department_plan_units,
    )
    from backend.core.department_scope_policy import (
        course_code_editable_by_actor,
        course_is_college_general,
        course_is_college_shared_catalog,
        course_writable_by_actor,
        resolve_effective_department_scope_id,
    )

    actor = _actor_username()
    scope_dep = resolve_effective_department_scope_id(conn, actor)
    for c in courses or []:
        name = getattr(c, "course_name", None) or ""
        try:
            can_edit = bool(course_writable_by_actor(conn, name, actor))
        except Exception:
            can_edit = False
        try:
            can_edit_code = bool(course_code_editable_by_actor(conn, name, actor))
        except Exception:
            can_edit_code = can_edit
        try:
            is_general = bool(course_is_college_general(conn, name))
        except Exception:
            is_general = False
        try:
            is_shared = bool(
                course_is_college_shared_catalog(
                    conn, name, department_id=int(scope_dep) if scope_dep is not None else None
                )
            )
        except Exception:
            is_shared = False
        if is_general:
            kind, kind_ar = "college_general", "اتجاه عام"
        elif is_shared:
            kind, kind_ar = "shared", "مشترك كلية"
        else:
            kind, kind_ar = "department", "قسم"
        display_code = getattr(c, "course_code", None) or ""
        display_units = getattr(c, "units", None)
        if is_shared and scope_dep is not None:
            try:
                dept_code = get_department_plan_course_code(conn, name, int(scope_dep))
                if dept_code:
                    display_code = dept_code
            except Exception:
                pass
            try:
                dept_units = get_department_plan_units(conn, name, int(scope_dep))
                if dept_units is not None:
                    display_units = dept_units
            except Exception:
                pass
        setattr(c, "can_edit", can_edit)
        setattr(c, "can_edit_code", can_edit_code)
        setattr(c, "course_kind", kind)
        setattr(c, "course_kind_ar", kind_ar)
        setattr(c, "display_code", display_code)
        setattr(c, "display_units", display_units)
        setattr(c, "dept_plan_code", display_code if is_shared else "")
        if is_shared and display_units is not None:
            setattr(c, "units", display_units)


@courses_bp.route("/list")
@login_required
def list_courses():
    # يرجع جدول courses، وإذا غير موجود يرجع من schedule
    try:
        from backend.core.cache_setup import cache, list_cache_key

        if cache:
            _ck = list_cache_key("courses")
            _hit = cache.get(_ck)
            if _hit is not None:
                return _hit
    except Exception:
        pass

    role_n = _normalize_role((session.get("user_role") or "").strip())
    with get_connection() as conn:
        scope_dep = _effective_department_scope_id(conn)
        admin_scoped = scope_dep is not None and role_n in (
            "admin",
            "admin_main",
            "head_of_department",
        )
        cur = conn.cursor()
        try:
            try:
                cols = fetch_table_columns(conn, "courses")
            except Exception:
                cols = []
            has_cat = "category" in cols
            has_archived = "is_archived" in cols
            has_assessment_type = "assessment_type" in cols
            has_cw_weight = "coursework_weight" in cols
            has_mid_weight = "midterm_weight" in cols
            has_final_weight = "final_exam_weight" in cols
            has_owning_dept = "owning_department_id" in cols
            sel = "SELECT DISTINCT course_name, course_code, units"
            if has_cat:
                sel += ", COALESCE(category,'required') AS category"
            if has_archived:
                sel += ", COALESCE(is_archived,0) AS is_archived"
            if has_assessment_type:
                sel += ", COALESCE(assessment_type,'theoretical') AS assessment_type"
            if has_cw_weight:
                sel += ", coursework_weight"
            if has_mid_weight:
                sel += ", midterm_weight"
            if has_final_weight:
                sel += ", final_exam_weight"
            sel += " FROM courses WHERE COALESCE(course_name,'') <> ''"
            if has_archived:
                sel += " AND COALESCE(is_archived,0) = 0"
            q_params: tuple = ()
            if scope_dep is not None and has_owning_dept:
                scope_sql, scope_params = courses_department_scope_filter(conn, int(scope_dep))
                sel += scope_sql
                q_params = scope_params
            sel += " ORDER BY course_name"
            rows = cur.execute(sel, q_params).fetchall()
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
                try:
                    archived_idx = 4 if has_cat else 3
                    setattr(c, "is_archived", int(r[archived_idx] or 0) if has_archived else 0)
                except Exception:
                    setattr(c, "is_archived", 0)
                idx = 5 if has_cat else 4
                if not has_archived:
                    idx -= 1
                try:
                    setattr(c, "assessment_type", _normalize_assessment_type(r[idx] if has_assessment_type else "theoretical"))
                except Exception:
                    setattr(c, "assessment_type", "theoretical")
                idx += 1 if has_assessment_type else 0
                try:
                    setattr(c, "coursework_weight", r[idx] if has_cw_weight else None)
                except Exception:
                    setattr(c, "coursework_weight", None)
                idx += 1 if has_cw_weight else 0
                try:
                    setattr(c, "midterm_weight", r[idx] if has_mid_weight else None)
                except Exception:
                    setattr(c, "midterm_weight", None)
                idx += 1 if has_mid_weight else 0
                try:
                    setattr(c, "final_exam_weight", r[idx] if has_final_weight else None)
                except Exception:
                    setattr(c, "final_exam_weight", None)
                courses.append(c)
            # إن كان جدول courses فارغاً لكن الجدول الدراسي يحوي مقررات، نعرضها (مثل بيئة بعد ترحيل أو بيانات جزئية)
            # عند تصفية المسؤول حسب قسم: لا نستخدم schedule لأن المقررات هناك غالباً بلا قسم مالك فيزداد التداخل بين الأقسام
            if not courses and not admin_scoped:
                rows = cur.execute(
                    "SELECT DISTINCT course_name FROM schedule WHERE COALESCE(course_name,'') <> '' ORDER BY course_name"
                ).fetchall()
                seen = set()
                for r in rows:
                    cname = r[0]
                    key = cname.strip().lower() if cname else ""
                    if not cname or key in seen:
                        continue
                    seen.add(key)
                    c = Course(cname, "", 0)
                    setattr(c, "category", "required")
                    setattr(c, "is_archived", 0)
                    setattr(c, "assessment_type", "theoretical")
                    setattr(c, "coursework_weight", None)
                    setattr(c, "midterm_weight", None)
                    setattr(c, "final_exam_weight", None)
                    courses.append(c)
        except Exception:
            if admin_scoped:
                rows = []
            else:
                rows = cur.execute(
                    "SELECT DISTINCT course_name FROM schedule WHERE COALESCE(course_name,'') <> '' ORDER BY course_name"
                ).fetchall()
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
                setattr(c, "assessment_type", "theoretical")
                setattr(c, "coursework_weight", None)
                setattr(c, "midterm_weight", None)
                setattr(c, "final_exam_weight", None)
                courses.append(c)
        _annotate_courses_edit_meta(conn, courses)
    resp = jsonify([c.__dict__ for c in courses])
    try:
        from backend.core.cache_setup import cache, list_cache_key

        if cache:
            cache.set(list_cache_key("courses"), resp)
    except Exception:
        pass
    return resp

@courses_bp.route("/add", methods=["POST"])
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def add_course():
    data = request.get_json(force=True)
    # حماية: مقررات الخطة (150/155) يجب إدارتها عبر college_catalog/program_courses
    # وليس عبر شاشة courses العامة، حتى لا تختلط نسخ الخطة بالمقرر العام.
    if any(k in data for k in ("program_id", "current_program_id", "graduation_plan", "plan_code")):
        return jsonify(
            {
                "status": "error",
                "code": "USE_PROGRAM_COURSES",
                "message": "إدارة مقررات الخطط (150/155) تتم من صفحة دليل الكلية/مقررات البرنامج، وليس من شاشة المقررات العامة.",
            }
        ), 400
    cname = (data.get("course_name") or "").strip()
    code = (data.get("course_code") or "").strip()
    try:
        units = int(data.get("units", 0) or 0)
    except (TypeError, ValueError):
        units = 0
    category = (data.get("category") or "required").strip() or "required"
    if category not in ("required", "elective_major", "elective_free"):
        category = "required"
    assessment_type = _normalize_assessment_type(data.get("assessment_type") or "theoretical")
    coursework_weight = _safe_weight(data.get("coursework_weight"), None)
    midterm_weight = _safe_weight(data.get("midterm_weight"), None)
    final_exam_weight = _safe_weight(data.get("final_exam_weight"), None)
    if not cname:
        return jsonify({"status": "error", "message": "اسم المقرر (course_name) مطلوب"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        # الجداول تُنشأ عند التشغيل عبر ensure_tables في database.py — لا CREATE في المسار
        from backend.core.department_scope_policy import (
            course_is_college_general,
            course_is_college_shared_catalog,
        )

        existing = courses_repo.find_course_name_row_ci(conn, cname)
        existing_archived = False
        if existing is not None:
            try:
                existing_archived = int(
                    existing["is_archived"] if hasattr(existing, "keys") else existing[3] or 0
                ) == 1
            except Exception:
                existing_archived = False
            if not existing_archived:
                if course_is_college_general(conn, cname, course_code=code) or course_is_college_shared_catalog(
                    conn, cname
                ):
                    return jsonify(
                        {
                            "status": "error",
                            "code": "COLLEGE_SHARED_COURSE",
                            "message": (
                                "هذا المقرر مُعرَّف في سجل المقررات المشتركة/الكلية — "
                                "متاح لقسمك تلقائياً في القائمة والجدول والتسجيل. "
                                "راجع «سجل المقررات المشتركة» أو حدّث الصفحة."
                            ),
                        }
                    ), 409
                return jsonify(
                    {
                        "status": "error",
                        "message": "يوجد مقرر آخر بنفس الاسم. استخدم زر \"تحرير\" لتعديله.",
                    }
                ), 400

        # منع تكرار الرمز إذا تم إدخاله (يشمل المؤرشف بسبب فهرس الرمز الفريد)
        if code:
            row = courses_repo.find_course_code_duplicate_ci(
                conn, code, exclude_course_name=cname if existing_archived else None
            )
            if row:
                other = _course_row_name(row)
                return jsonify(
                    {
                        "status": "error",
                        "message": f"يوجد مقرر آخر بنفس الرمز ({other}). الرجاء اختيار رمز مختلف.",
                    }
                ), 400

        # تأكد من وجود عمود category (قواعد قديمة / توافق SQLite وPostgreSQL)
        try:
            cols = fetch_table_columns(conn, "courses")
        except Exception:
            cols = []
        has_owning_dept = "owning_department_id" in cols
        has_archived = "is_archived" in cols
        scope_dep = _effective_department_scope_id(conn)
        owning_id = (
            resolve_import_owning_department_id(conn, cname, scope_dep, course_code=code)
            if has_owning_dept
            else None
        )

        if existing_archived:
            # استعادة السجل المؤرشف بدل INSERT (الاسم مفتاح أساسي ولا يُحرَّر بالأرشفة)
            sets = ["course_code = ?", "units = ?"]
            params: list = [code, units]
            if "category" in cols:
                sets.append("category = ?")
                params.append(category)
            has_assessment_cols = all(
                k in cols
                for k in ("assessment_type", "coursework_weight", "midterm_weight", "final_exam_weight")
            )
            if has_assessment_cols:
                sets.extend(
                    [
                        "assessment_type = ?",
                        "coursework_weight = ?",
                        "midterm_weight = ?",
                        "final_exam_weight = ?",
                    ]
                )
                params.extend(
                    [assessment_type, coursework_weight, midterm_weight, final_exam_weight]
                )
            if has_owning_dept and owning_id is not None:
                sets.append("owning_department_id = COALESCE(owning_department_id, ?)")
                params.append(int(owning_id))
            if has_archived:
                sets.append("is_archived = 0")
            params.append(cname)
            cur.execute(
                f"UPDATE courses SET {', '.join(sets)} WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))",
                tuple(params),
            )
            try:
                from backend.services.college_catalog import _link_operational_course_to_master

                _link_operational_course_to_master(
                    conn, cur, cname, int(owning_id) if owning_id is not None else None
                )
            except Exception:
                pass
            conn.commit()
            try:
                from backend.core.cache_setup import invalidate_list_prefix

                invalidate_list_prefix("courses")
            except Exception:
                pass
            return jsonify(
                {
                    "status": "ok",
                    "restored": True,
                    "message": "تم استعادة المقرر من الأرشيف وتحديث بياناته",
                }
            ), 200

        if "category" in cols:
            has_assessment_cols = all(k in cols for k in ("assessment_type", "coursework_weight", "midterm_weight", "final_exam_weight"))
            if has_assessment_cols:
                if has_owning_dept:
                    cur.execute(
                        """
                        INSERT INTO courses
                        (course_name, course_code, units, category, assessment_type, coursework_weight, midterm_weight, final_exam_weight, owning_department_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            cname,
                            code,
                            units,
                            category,
                            assessment_type,
                            coursework_weight,
                            midterm_weight,
                            final_exam_weight,
                            (int(owning_id) if owning_id is not None else None),
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO courses
                        (course_name, course_code, units, category, assessment_type, coursework_weight, midterm_weight, final_exam_weight)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (cname, code, units, category, assessment_type, coursework_weight, midterm_weight, final_exam_weight),
                    )
            else:
                if has_owning_dept:
                    cur.execute(
                        "INSERT INTO courses (course_name, course_code, units, category, owning_department_id) VALUES (?, ?, ?, ?, ?)",
                        (cname, code, units, category, (int(owning_id) if owning_id is not None else None)),
                    )
                else:
                    cur.execute(
                        "INSERT INTO courses (course_name, course_code, units, category) VALUES (?, ?, ?, ?)",
                        (cname, code, units, category),
                    )
        else:
            if has_owning_dept:
                cur.execute(
                    "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
                    (cname, code, units, (int(owning_id) if owning_id is not None else None)),
                )
            else:
                cur.execute(
                    "INSERT INTO courses (course_name, course_code, units) VALUES (?, ?, ?)",
                    (cname, code, units),
                )
        try:
            from backend.services.college_catalog import _link_operational_course_to_master

            _link_operational_course_to_master(
                conn, cur, cname, int(owning_id) if owning_id is not None else None
            )
        except Exception:
            pass
        conn.commit()
    try:
        from backend.core.cache_setup import invalidate_list_prefix

        invalidate_list_prefix("courses")
    except Exception:
        pass
    return jsonify({"status": "ok", "message": "تم إضافة المقرر"}), 200

@courses_bp.route("/update", methods=["POST"])
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def update_course():
    data = request.get_json(force=True)
    old_name = (data.get("old_course_name") or "").strip()
    new_name = (data.get("new_course_name") or "").strip()
    new_units = data.get("units")
    new_code = (data.get("course_code") or "").strip()
    category = (data.get("category") or "").strip()
    assessment_type = _normalize_assessment_type(data.get("assessment_type") or "theoretical")
    coursework_weight = _safe_weight(data.get("coursework_weight"), None)
    midterm_weight = _safe_weight(data.get("midterm_weight"), None)
    final_exam_weight = _safe_weight(data.get("final_exam_weight"), None)
    code_only = bool(data.get("code_only"))
    if not old_name or not new_name:
        return jsonify({"status": "error", "message": "old_course_name و new_course_name مطلوبة"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        from backend.core.department_scope_policy import (
            course_code_editable_by_actor,
            course_writable_by_actor,
        )

        full_ok = course_writable_by_actor(conn, old_name, _actor_username())
        code_ok = course_code_editable_by_actor(conn, old_name, _actor_username())

        # رئيس تخصص على مقرر مشترك: رمز ووحدات خطة القسم — دون الاسم الرسمي
        if (code_only or not full_ok) and code_ok and not full_ok:
            if new_name != old_name:
                return jsonify(
                    {
                        "status": "error",
                        "message": "لا يمكن تغيير اسم المقرر المشترك من نطاق قسمك — عدّل الرمز/الوحدات فقط.",
                    }
                ), 403
            if not new_code:
                return jsonify({"status": "error", "message": "رمز المقرر مطلوب."}), 400
            units_override = None
            if new_units is not None and str(new_units).strip() != "":
                try:
                    units_override = int(new_units)
                except (TypeError, ValueError):
                    return jsonify({"status": "error", "message": "عدد الوحدات غير صالح."}), 400
                if units_override < 0:
                    return jsonify({"status": "error", "message": "عدد الوحدات يجب أن يكون >= 0."}), 400
            scope_dep = _effective_department_scope_id(conn)
            if scope_dep is None:
                return jsonify({"status": "error", "message": "لا يوجد نطاق قسم لتحديث الخطة."}), 400
            try:
                from backend.core.college_shared_catalog import set_department_plan_course_code

                info = set_department_plan_course_code(
                    conn,
                    old_name,
                    int(scope_dep),
                    new_code,
                    units=units_override,
                )
                conn.commit()
            except ValueError as e:
                return jsonify({"status": "error", "message": str(e)}), 400
            try:
                from backend.core.cache_setup import invalidate_list_prefix

                invalidate_list_prefix("courses")
            except Exception:
                pass
            return jsonify(
                {
                    "status": "ok",
                    "message": "تم حفظ رمز/وحدات المقرر لخطة قسمك (المقرر المشترك).",
                    "code_only": True,
                    "plan_course_code": info.get("plan_course_code"),
                    "units_override": info.get("units_override"),
                    "effective_units": info.get("units"),
                    "canonical_course_code": info.get("canonical_course_code"),
                }
            ), 200

        try:
            _forbid_course_write(conn, old_name)
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 403
        # منع تكرار الاسم الجديد (باستثناء نفس المقرر)
        row = cur.execute(
            """
            SELECT course_name
            FROM courses
            WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))
              AND LOWER(TRIM(course_name)) <> LOWER(TRIM(?))
            """,
            (new_name, old_name),
        ).fetchone()
        if row:
            return jsonify({"status": "error", "message": "لا يمكن تغيير الاسم لأنه مستخدم لمقرر آخر."}), 400

        # منع تكرار الرمز الجديد إن وجد
        if new_code:
            row = cur.execute(
                """
                SELECT course_name
                FROM courses
                WHERE COALESCE(course_code,'') <> ''
                  AND LOWER(TRIM(course_code)) = LOWER(TRIM(?))
                  AND LOWER(TRIM(course_name)) <> LOWER(TRIM(?))
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

        # تأكد من وجود عمود category (قواعد قديمة / توافق SQLite وPostgreSQL)
        try:
            cols = fetch_table_columns(conn, "courses")
        except Exception:
            cols = []
        has_cat = "category" in cols
        has_assessment_cols = all(k in cols for k in ("assessment_type", "coursework_weight", "midterm_weight", "final_exam_weight"))
        cat_value = category if category in ("required", "elective_major", "elective_free") else None
        updated_rows = 0
        if has_cat:
            if cat_value is None:
                if has_assessment_cols:
                    res = cur.execute(
                        """
                        UPDATE courses
                        SET course_name=?, course_code=?, units=?,
                            assessment_type=?, coursework_weight=?, midterm_weight=?, final_exam_weight=?
                        WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))
                        """,
                        (
                            new_name, new_code or "", (int(new_units) if new_units is not None else None),
                            assessment_type, coursework_weight, midterm_weight, final_exam_weight,
                            old_name,
                        ),
                    )
                    updated_rows = int(res.rowcount or 0)
                else:
                    res = cur.execute(
                        "UPDATE courses SET course_name=?, course_code=?, units=? WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))",
                        (new_name, new_code or "", (int(new_units) if new_units is not None else None), old_name),
                    )
                    updated_rows = int(res.rowcount or 0)
            else:
                if has_assessment_cols:
                    res = cur.execute(
                        """
                        UPDATE courses
                        SET course_name=?, course_code=?, units=?, category=?,
                            assessment_type=?, coursework_weight=?, midterm_weight=?, final_exam_weight=?
                        WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))
                        """,
                        (
                            new_name, new_code or "", (int(new_units) if new_units is not None else None), cat_value,
                            assessment_type, coursework_weight, midterm_weight, final_exam_weight,
                            old_name,
                        ),
                    )
                    updated_rows = int(res.rowcount or 0)
                else:
                    res = cur.execute(
                        "UPDATE courses SET course_name=?, course_code=?, units=?, category=? WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))",
                        (new_name, new_code or "", (int(new_units) if new_units is not None else None), cat_value, old_name),
                    )
                    updated_rows = int(res.rowcount or 0)
        else:
            res = cur.execute(
                "UPDATE courses SET course_name=?, course_code=?, units=? WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))",
                (new_name, new_code or "", (int(new_units) if new_units is not None else None), old_name),
            )
            updated_rows = int(res.rowcount or 0)

        if updated_rows <= 0:
            return jsonify({"status": "error", "message": "لم يتم العثور على المقرر المطلوب لتحديثه."}), 404

        # تحديث جميع الجداول التي تعتمد على اسم المقرر
        for tbl in ("grades", "schedule", "registrations", "enrollment_plan_items", "exams"):
            try:
                cur.execute(
                    f"UPDATE {tbl} SET course_name=? WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))",
                    (new_name, old_name),
                )
            except Exception:
                pass

        cur.execute(
            "UPDATE prereqs SET course_name=? WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))",
            (new_name, old_name),
        )
        cur.execute(
            "UPDATE prereqs SET required_course_name=? WHERE LOWER(TRIM(required_course_name)) = LOWER(TRIM(?))",
            (new_name, old_name),
        )

        if new_units is not None or new_code is not None:
            try:
                if new_units is not None:
                    cur.execute(
                        "UPDATE grades SET units=? WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))",
                        (int(new_units), new_name),
                    )
                if new_code is not None:
                    cur.execute(
                        "UPDATE grades SET course_code=? WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))",
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

def _ensure_courses_archived_column(conn, cur) -> None:
    try:
        cols = fetch_table_columns(conn, "courses")
    except Exception:
        cols = []
    if "is_archived" not in cols and not is_postgresql():
        try:
            cur.execute("ALTER TABLE courses ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass


def _course_link_counts(cur, cname: str) -> dict:
    links = {}
    for tbl in ("grades", "registrations", "schedule", "enrollment_plan_items", "exams", "prereqs"):
        try:
            if tbl == "prereqs":
                row = cur.execute(
                    "SELECT COUNT(*) FROM prereqs WHERE course_name = ? OR required_course_name = ?",
                    (cname, cname),
                ).fetchone()
            else:
                row = cur.execute(
                    f"SELECT COUNT(*) FROM {tbl} WHERE course_name = ?",
                    (cname,),
                ).fetchone()
            links[tbl] = int(row[0] or 0) if row else 0
        except Exception:
            links[tbl] = 0
    return links


def _delete_or_archive_course(conn, cur, cname: str) -> dict:
    """
    حذف صلب إن لم توجد ارتباطات؛ وإلا أرشفة.
    يفترض أن الصلاحية فُحصت مسبقاً عبر _forbid_course_write.
    """
    name = (cname or "").strip()
    if not name:
        return {"course_name": cname, "status": "skipped", "reason": "empty"}
    _ensure_courses_archived_column(conn, cur)
    links = _course_link_counts(cur, name)
    if any(v > 0 for v in links.values()):
        cur.execute("UPDATE courses SET is_archived = 1 WHERE course_name = ?", (name,))
        return {
            "course_name": name,
            "status": "archived",
            "archived": True,
            "links": links,
        }
    cur.execute("DELETE FROM courses WHERE course_name = ?", (name,))
    cur.execute(
        "DELETE FROM prereqs WHERE course_name = ? OR required_course_name = ?",
        (name, name),
    )
    return {
        "course_name": name,
        "status": "deleted",
        "archived": False,
        "links": links,
    }


def _invalidate_courses_list_cache() -> None:
    try:
        from backend.core.cache_setup import invalidate_list_prefix

        invalidate_list_prefix("courses")
    except Exception:
        pass


def _scoped_active_course_names(conn, cur, *, dept_scope_id: int | None) -> list[str]:
    """
    أسماء المقررات غير المؤرشفة ضمن نطاق العرض للقسم،
    ثم تُصفّى إلى ما يحق للفاعل تعديله/حذفه فقط
    (لا تشمل اتجاه عام/مشترك لرئيس تخصص).
    """
    from backend.core.department_scope_policy import course_writable_by_actor

    try:
        cols = fetch_table_columns(conn, "courses")
    except Exception:
        cols = []
    has_archived = "is_archived" in cols
    has_owning = "owning_department_id" in cols
    sql = "SELECT DISTINCT course_name FROM courses WHERE COALESCE(TRIM(course_name),'') <> ''"
    params: tuple = ()
    if has_archived:
        sql += " AND COALESCE(is_archived,0) = 0"
    if dept_scope_id is not None and has_owning:
        scope_sql, scope_params = courses_department_scope_filter(conn, int(dept_scope_id))
        sql += scope_sql
        params = scope_params
    sql += " ORDER BY course_name"
    rows = cur.execute(sql, params).fetchall()
    out = []
    seen = set()
    actor = _actor_username()
    for r in rows or []:
        name = (r[0] if not hasattr(r, "keys") else r["course_name"]) or ""
        name = str(name).strip()
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        try:
            if not course_writable_by_actor(conn, name, actor):
                continue
        except Exception:
            continue
        out.append(name)
    return out


@courses_bp.route("/delete", methods=["POST"])
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def delete_course():
    data = request.get_json(force=True)
    cname = data.get("course_name")
    if not cname:
        return jsonify({"status": "error", "message": "course_name مطلوب"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            _forbid_course_write(conn, cname)
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 403
        result = _delete_or_archive_course(conn, cur, cname)
        if result.get("status") == "archived":
            try:
                cur.execute("DELETE FROM optimized_schedule")
            except Exception:
                pass
            try:
                cur.execute("DELETE FROM conflict_report")
            except Exception:
                pass
            conn.commit()
            _invalidate_courses_list_cache()
            return jsonify({
                "status": "ok",
                "archived": True,
                "message": "تمت أرشفة المقرر بدلاً من الحذف لأنه مرتبط ببيانات أكاديمية تاريخية.",
                "links": result.get("links") or {},
            }), 200

        try:
            cur.execute("DELETE FROM optimized_schedule")
        except Exception:
            pass
        try:
            cur.execute("DELETE FROM conflict_report")
        except Exception:
            pass
        conn.commit()
    _invalidate_courses_list_cache()
    return jsonify({"status": "ok", "archived": False, "message": "تم حذف المقرر (لا توجد له ارتباطات)."}), 200


@courses_bp.route("/bulk_delete", methods=["POST"])
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def bulk_delete_courses():
    """
    حذف/أرشفة دفعة مقررات.
    body:
      - course_names: [..]  (اختياري إن all_in_scope)
      - all_in_scope: true   → كل مقررات نطاق القسم الظاهرة (غير مؤرشفة)
      - confirm_phrase: يجب أن يساوي «تأكيد» عند all_in_scope أو عند أكثر من 20 مقرراً
    """
    data = request.get_json(silent=True) or {}
    all_in_scope = bool(data.get("all_in_scope"))
    raw_names = data.get("course_names") or data.get("names") or []
    if not isinstance(raw_names, list):
        raw_names = []
    confirm_phrase = str(data.get("confirm_phrase") or data.get("confirm") or "").strip()

    with get_connection() as conn:
        cur = conn.cursor()
        scope_dep = _effective_department_scope_id(conn)

        if all_in_scope:
            if scope_dep is None:
                return jsonify(
                    {
                        "status": "error",
                        "message": "حذف كل مقررات القسم متاح لحساب مرتبط بقسم (رئيس قسم / نطاق قسم).",
                        "code": "scope_required",
                    }
                ), 400
            if confirm_phrase != "تأكيد":
                return jsonify(
                    {
                        "status": "error",
                        "message": "للتأكيد اكتب كلمة: تأكيد",
                        "code": "confirm_required",
                    }
                ), 400
            names = _scoped_active_course_names(conn, cur, dept_scope_id=int(scope_dep))
        else:
            names = []
            seen = set()
            for n in raw_names:
                name = str(n or "").strip()
                key = name.lower()
                if not name or key in seen:
                    continue
                seen.add(key)
                names.append(name)
            if len(names) > 20 and confirm_phrase != "تأكيد":
                return jsonify(
                    {
                        "status": "error",
                        "message": "لحذف أكثر من 20 مقرراً اكتب كلمة التأكيد: تأكيد",
                        "code": "confirm_required",
                    }
                ), 400

        if not names:
            return jsonify({"status": "error", "message": "لا توجد مقررات للحذف."}), 400
        if len(names) > 800:
            return jsonify({"status": "error", "message": "الحد الأقصى 800 مقرراً في الطلب."}), 400

        deleted = 0
        archived = 0
        forbidden = 0
        errors: list[dict] = []
        details: list[dict] = []

        for name in names:
            try:
                _forbid_course_write(conn, name)
            except ValueError as e:
                forbidden += 1
                errors.append({"course_name": name, "message": str(e)})
                continue
            try:
                result = _delete_or_archive_course(conn, cur, name)
            except Exception as exc:
                errors.append({"course_name": name, "message": str(exc)})
                continue
            st = result.get("status")
            if st == "archived":
                archived += 1
            elif st == "deleted":
                deleted += 1
            details.append(result)

        try:
            cur.execute("DELETE FROM optimized_schedule")
        except Exception:
            pass
        try:
            cur.execute("DELETE FROM conflict_report")
        except Exception:
            pass
        conn.commit()

    _invalidate_courses_list_cache()
    return jsonify(
        {
            "status": "ok",
            "message": (
                f"اكتمل: حُذف {deleted} وأُرشف {archived}"
                + (f" وتُخطّي {forbidden} بلا صلاحية" if forbidden else "")
            ),
            "deleted": deleted,
            "archived": archived,
            "forbidden": forbidden,
            "requested": len(names),
            "errors": errors[:50],
            "all_in_scope": all_in_scope,
        }
    ), 200


# المتطلبات (Prereqs) - يدعم زوج واحد أو دفعة items[]
@courses_bp.route("/prereqs/add", methods=["POST"])
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
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
        # جدول prereqs يُنشأ عند التشغيل عبر ensure_tables — لا CREATE في المسار
        # collect known courses and build tolerant maps
        try:
            rows = cur.execute(
                "SELECT course_name, COALESCE(course_code, '') FROM courses"
            ).fetchall()
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

                try:
                    _forbid_course_write(conn, real_course)
                except ValueError as e:
                    errors.append({"course": real_course, "required": real_req, "reason": str(e)})
                    continue

                cur.execute(
                    "INSERT INTO prereqs (course_name, required_course_name) VALUES (?,?) ON CONFLICT (course_name, required_course_name) DO NOTHING",
                    (real_course, real_req),
                )
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
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def delete_prereq():
    data = request.get_json(force=True)
    course = data.get("course_name")
    req = data.get("required_course_name")
    if not course or not req:
        return jsonify({"status": "error", "message": "course_name و required_course_name مطلوبة"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            _forbid_course_write(conn, course)
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 403
        cur.execute("DELETE FROM prereqs WHERE course_name = ? AND required_course_name = ?", (course, req))
        conn.commit()
    return jsonify({"status": "ok", "message": "تم حذف المتطلب"}), 200

@courses_bp.route("/prereqs/list")
@login_required
def list_prereqs():
    """نفس مصدر خريطة المتطلبات حتى لا تختفي الصفوف عند نطاق القسم."""
    with get_connection() as conn:
        _courses, prereqs = _load_courses_and_prereqs(conn)
        prereqs_sorted = sorted(
            prereqs,
            key=lambda r: (
                (r.get("course_name") or ""),
                (r.get("required_course_name") or ""),
            ),
        )
        return jsonify(
            [
                {
                    "course_name": r.get("course_name"),
                    "required_course_name": r.get("required_course_name"),
                }
                for r in prereqs_sorted
            ]
        )

@courses_bp.route("/prereqs/status")
@login_required
def prereq_status():
    student_id = request.args.get("student_id")
    if not student_id:
        return jsonify({"status": "error", "message": "student_id مطلوب"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        scope_dep = _effective_department_scope_id(conn)
        try:
            if scope_dep is None:
                rows_c = cur.execute("SELECT course_name FROM courses").fetchall()
            else:
                scope_sql, scope_params = courses_department_scope_filter(conn, int(scope_dep))
                rows_c = cur.execute(
                    f"SELECT course_name FROM courses WHERE 1=1{scope_sql}",
                    scope_params,
                ).fetchall()
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


def _load_courses_and_prereqs(conn):
    cur = conn.cursor()
    role_n = _normalize_role((session.get("user_role") or "").strip())
    scope_dep = _effective_department_scope_id(conn)
    admin_scoped = scope_dep is not None and role_n in ("admin", "admin_main", "head_of_department")

    courses = []
    try:
        cols = fetch_table_columns(conn, "courses")
        has_owning = "owning_department_id" in cols
        q = (
            "SELECT course_name, COALESCE(course_code,'') AS course_code FROM courses "
            "WHERE COALESCE(course_name,'') <> ''"
        )
        qp: tuple = ()
        if admin_scoped and has_owning:
            scope_sql, scope_params = courses_department_scope_filter(conn, int(scope_dep))
            q += scope_sql
            qp = scope_params
        rows_c = cur.execute(q, qp).fetchall()
        courses = [{"course_name": r[0], "course_code": (r[1] or "")} for r in (rows_c or []) if r and r[0]]
        if admin_scoped and not courses and has_owning:
            courses = []
        elif admin_scoped and not has_owning:
            cols_sch = fetch_table_columns(conn, "schedule")
            if "department_id" in cols_sch:
                rows_sch = cur.execute(
                    """
                    SELECT DISTINCT course_name FROM schedule
                    WHERE COALESCE(course_name,'') <> '' AND COALESCE(department_id,-1) = ?
                    ORDER BY course_name
                    """,
                    (int(scope_dep),),
                ).fetchall()
                courses = [{"course_name": r[0], "course_code": ""} for r in (rows_sch or []) if r and r[0]]
            else:
                courses = []
    except Exception:
        try:
            if admin_scoped:
                cols_sch = fetch_table_columns(conn, "schedule")
                if "department_id" in cols_sch:
                    rows_s = cur.execute(
                        """
                        SELECT DISTINCT course_name FROM schedule
                        WHERE COALESCE(course_name,'') <> '' AND COALESCE(department_id,-1) = ?
                        ORDER BY course_name
                        """,
                        (int(scope_dep),),
                    ).fetchall()
                else:
                    rows_s = []
            else:
                rows_s = cur.execute(
                    "SELECT DISTINCT course_name FROM schedule WHERE COALESCE(course_name,'') <> '' ORDER BY course_name"
                ).fetchall()
            courses = [{"course_name": r[0], "course_code": ""} for r in (rows_s or []) if r and r[0]]
        except Exception:
            if admin_scoped:
                courses = []
            else:
                rows_s = cur.execute(
                    "SELECT DISTINCT course_name FROM schedule WHERE COALESCE(course_name,'') <> '' ORDER BY course_name"
                ).fetchall()
                courses = [{"course_name": r[0], "course_code": ""} for r in (rows_s or []) if r and r[0]]

    try:
        rows_p = cur.execute("SELECT course_name, required_course_name FROM prereqs").fetchall()
        prereqs = [{"course_name": r[0], "required_course_name": r[1]} for r in (rows_p or []) if r and r[0] and r[1]]
    except Exception:
        prereqs = []

    # normalize + dedupe
    seen = set()
    out_courses = []
    for c in courses:
        key = (c.get("course_name") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out_courses.append(c)
    allowed_lower = {(c.get("course_name") or "").strip().lower() for c in out_courses}

    seen_p = set()
    out_pr = []
    for p in prereqs:
        a = (p.get("required_course_name") or "").strip()
        b = (p.get("course_name") or "").strip()
        if not a or not b:
            continue
        if admin_scoped:
            if b.lower() not in allowed_lower or a.lower() not in allowed_lower:
                continue
        k = (b.lower(), a.lower())
        if k in seen_p:
            continue
        seen_p.add(k)
        out_pr.append({"course_name": b, "required_course_name": a})
    return out_courses, out_pr


def _subgraph_for_course(prereqs_rows, focus_course: str, direction: str, depth: int):
    focus = (focus_course or "").strip()
    if not focus:
        return prereqs_rows
    direction = (direction or "both").strip().lower()
    if direction not in ("both", "prereqs", "dependents"):
        direction = "both"
    try:
        depth = int(depth or 2)
    except Exception:
        depth = 2
    depth = max(1, min(depth, 10))

    # Build adjacency
    prereq_to_course = defaultdict(set)  # req -> {course}
    course_to_prereq = defaultdict(set)  # course -> {req}
    for row in prereqs_rows:
        c = (row.get("course_name") or "").strip()
        r = (row.get("required_course_name") or "").strip()
        if not c or not r:
            continue
        prereq_to_course[r].add(c)
        course_to_prereq[c].add(r)

    included_courses = {focus}

    def walk_prereqs():
        frontier = {focus}
        for _ in range(depth):
            nxt = set()
            for c in frontier:
                for r in course_to_prereq.get(c, set()):
                    if r not in included_courses:
                        included_courses.add(r)
                        nxt.add(r)
            frontier = nxt
            if not frontier:
                break

    def walk_dependents():
        frontier = {focus}
        for _ in range(depth):
            nxt = set()
            for r in frontier:
                for c in prereq_to_course.get(r, set()):
                    if c not in included_courses:
                        included_courses.add(c)
                        nxt.add(c)
            frontier = nxt
            if not frontier:
                break

    if direction in ("both", "prereqs"):
        walk_prereqs()
    if direction in ("both", "dependents"):
        walk_dependents()

    out = []
    for row in prereqs_rows:
        c = (row.get("course_name") or "").strip()
        r = (row.get("required_course_name") or "").strip()
        if c in included_courses and r in included_courses:
            out.append(row)
    return out


def _render_prereq_flow_png(courses, prereqs_rows, focus_course: str = "", direction: str = "both", depth: int = 2):
    # Import matplotlib lazily so the app runs without it until used.
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        raise RuntimeError(
            "ميزة خريطة المتطلبات تحتاج تثبيت مكتبة matplotlib. "
            "نفّذ: pip install -r requirements.txt ثم أعد تشغيل السيرفر."
        ) from e

    # Arabic shaping + bidi so Arabic renders correctly in matplotlib
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        def _rtl_text(s: str) -> str:
            txt = str(s or "")
            if not txt:
                return ""
            return get_display(arabic_reshaper.reshape(txt))
    except Exception:
        def _rtl_text(s: str) -> str:
            return str(s or "")

    # Optionally reduce to a focused subgraph
    filtered_pr = _subgraph_for_course(prereqs_rows, focus_course=focus_course, direction=direction, depth=depth)

    # Build nodes set (from edges + courses list)
    nodes = set()
    for p in filtered_pr:
        nodes.add((p.get("course_name") or "").strip())
        nodes.add((p.get("required_course_name") or "").strip())
    nodes = {n for n in nodes if n}
    if not nodes:
        # fallback: show an "empty" image
        fig = plt.figure(figsize=(10, 4), dpi=160)
        ax = fig.add_subplot(111)
        ax.axis("off")
        ax.text(
            0.5, 0.5, _rtl_text("لا توجد متطلبات لعرضها"),
            ha="center", va="center", fontsize=16, fontfamily="DejaVu Sans"
        )
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    # adjacency: prereq -> course
    succ = defaultdict(list)
    indeg = defaultdict(int)
    for n in nodes:
        indeg[n] = 0
    for row in filtered_pr:
        c = (row.get("course_name") or "").strip()
        r = (row.get("required_course_name") or "").strip()
        if not c or not r:
            continue
        if c not in nodes or r not in nodes:
            continue
        succ[r].append(c)
        indeg[c] += 1

    # Layering: Kahn + level propagation (best-effort even with cycles)
    level = {n: 0 for n in nodes}
    q = [n for n in nodes if indeg.get(n, 0) == 0]
    processed = 0
    while q:
        n = q.pop(0)
        processed += 1
        for v in succ.get(n, []):
            level[v] = max(level.get(v, 0), level.get(n, 0) + 1)
            indeg[v] = max(0, indeg.get(v, 0) - 1)
            if indeg[v] == 0:
                q.append(v)
    # cycles: keep existing level=0..N, but still plot

    max_level = max(level.values()) if level else 0
    layers = defaultdict(list)
    for n, lv in level.items():
        layers[lv].append(n)
    for lv in layers:
        layers[lv].sort(key=lambda x: x)

    # Reduce edge crossings: reorder each layer by predecessor barycenter.
    preds = defaultdict(list)  # course -> [prereq]
    for row in filtered_pr:
        c = (row.get("course_name") or "").strip()
        r = (row.get("required_course_name") or "").strip()
        if c and r:
            preds[c].append(r)
    for lv in range(1, max_level + 1):
        prev_order = {n: i for i, n in enumerate(layers.get(lv - 1, []))}
        def _bary(n):
            ps = [prev_order[p] for p in preds.get(n, []) if p in prev_order]
            if not ps:
                return 10**9
            return sum(ps) / max(1, len(ps))
        layers[lv].sort(key=lambda n: (_bary(n), n))

    # coordinates
    pos = {}
    x_scale = 1.45  # more horizontal separation between levels
    for lv in range(0, max_level + 1):
        layer_nodes = layers.get(lv, [])
        for i, n in enumerate(layer_nodes):
            # x increases with level; y decreases with index for top-down
            pos[n] = (lv * x_scale, -i)

    # Figure size scaling
    max_layer_size = max((len(v) for v in layers.values()), default=1)
    width = max(10, 2.5 + (max_level + 1) * 2.8)
    height = max(4.5, 1.6 + max_layer_size * 0.9)

    fig = plt.figure(figsize=(width, height), dpi=160)
    ax = fig.add_subplot(111)
    ax.axis("off")

    # Build display labels with code if available
    code_map = {}
    for c in courses or []:
        name = (c.get("course_name") or "").strip()
        if not name:
            continue
        code_map[name] = (c.get("course_code") or "").strip()

    def label_for(name: str) -> str:
        code = (code_map.get(name) or "").strip()
        raw = f"{name}\n({code})" if code else name
        return _rtl_text(raw)

    # Draw edges first
    is_full_plan = not (focus_course or "").strip()
    edge_palette = ["#0f766e", "#1d4ed8", "#7c3aed", "#b45309", "#be123c", "#0f766e"]
    for row in filtered_pr:
        c = (row.get("course_name") or "").strip()
        r = (row.get("required_course_name") or "").strip()
        if c not in pos or r not in pos:
            continue
        x1, y1 = pos[r]
        x2, y2 = pos[c]
        src_level = int(level.get(r, 0) or 0)
        color = edge_palette[src_level % len(edge_palette)]
        # "core" edges are adjacent levels; others are lighter/dashed.
        level_gap = abs(int(level.get(c, 0) or 0) - src_level)
        core_edge = (level_gap <= 1)
        lw = 1.8 if core_edge else 1.1
        alpha = 0.72 if core_edge else 0.38
        linestyle = "-" if core_edge else "--"
        # In focused mode keep stronger edges for readability.
        if not is_full_plan:
            lw = 1.9 if core_edge else 1.4
            alpha = 0.82 if core_edge else 0.55
            linestyle = "-"
        ax.annotate(
            "",
            xy=(x2, y2),
            xytext=(x1, y1),
            arrowprops=dict(
                arrowstyle="-|>",
                color=color,
                lw=lw,
                linestyle=linestyle,
                alpha=alpha,
                mutation_scale=9,
                shrinkA=12,
                shrinkB=12,
            ),
            zorder=1,
        )

    # Draw nodes
    for n, (x, y) in pos.items():
        is_focus = (focus_course or "").strip() and n == (focus_course or "").strip()
        fc = "#e2e8f0" if not is_focus else "#fde68a"
        ec = "#94a3b8" if not is_focus else "#f59e0b"
        ax.text(
            x, y,
            label_for(n),
            ha="center",
            va="center",
            fontsize=10,
            color="#0f172a",
            bbox=dict(boxstyle="round,pad=0.35", fc=fc, ec=ec, lw=1.2),
            fontfamily="DejaVu Sans",
            zorder=2,
        )

    # Title
    title = "خريطة المتطلبات بين المقررات"
    if (focus_course or "").strip():
        title += f" — ({focus_course})"
    ax.text(
        0, 1.02, _rtl_text(title),
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=14,
        fontweight="bold",
        fontfamily="DejaVu Sans",
    )

    # Tight bounds with padding
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    ax.set_xlim(min(xs) - 1.0, max(xs) + 1.0)
    ax.set_ylim(min(ys) - 1.0, max(ys) + 1.0)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


@courses_bp.route("/prereqs/flowchart/png")
@login_required
def prereqs_flowchart_png():
    course = (request.args.get("course") or "").strip()
    direction = (request.args.get("direction") or "both").strip()
    depth = request.args.get("depth") or 2
    with get_connection() as conn:
        courses, prereqs_rows = _load_courses_and_prereqs(conn)
    try:
        png = _render_prereq_flow_png(courses, prereqs_rows, focus_course=course, direction=direction, depth=depth)
        return send_file(io.BytesIO(png), mimetype="image/png", as_attachment=False, download_name="prereqs_flowchart.png")
    except Exception as e:
        current_app.logger.exception("flowchart png failed")
        return jsonify({"status": "error", "message": str(e)}), 500


@courses_bp.route("/prereqs/flowchart/pdf")
@role_required("admin", "admin_main", "head_of_department", "supervisor", "instructor", "student")
def prereqs_flowchart_pdf():
    course = (request.args.get("course") or "").strip()
    direction = (request.args.get("direction") or "both").strip()
    depth = request.args.get("depth") or 2
    with get_connection() as conn:
        courses, prereqs_rows = _load_courses_and_prereqs(conn)
    try:
        png = _render_prereq_flow_png(courses, prereqs_rows, focus_course=course, direction=direction, depth=depth)
    except Exception as e:
        current_app.logger.exception("flowchart render failed")
        return jsonify({"status": "error", "message": str(e)}), 500
    b64 = base64.b64encode(png).decode("ascii")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""
    <!doctype html>
    <html lang="ar" dir="rtl">
      <head>
        <meta charset="utf-8"/>
        <title>خريطة المتطلبات</title>
        <style>
          body {{ font-family: DejaVu Sans, Arial, Tahoma; direction: rtl; }}
          .meta {{ color:#475569; font-size: 12px; margin-bottom: 8px; }}
          .imgwrap {{ width: 100%; text-align: center; }}
          img {{ max-width: 100%; height: auto; }}
        </style>
      </head>
      <body>
        <h3 style="margin:0 0 6px 0;">خريطة المتطلبات بين المقررات</h3>
        <div class="meta">التاريخ: {now}{(' — مقرر: ' + course) if course else ''}</div>
        <div class="imgwrap">
          <img src="data:image/png;base64,{b64}" alt="Prereqs Flowchart"/>
        </div>
      </body>
    </html>
    """
    return pdf_response_from_html(html, filename_prefix="prereqs_flowchart")


@courses_bp.route("/prereqs/flowchart/pptx")
@role_required("admin", "admin_main", "head_of_department", "supervisor", "instructor", "student")
def prereqs_flowchart_pptx():
    course = (request.args.get("course") or "").strip()
    direction = (request.args.get("direction") or "both").strip()
    depth = request.args.get("depth") or 2
    with get_connection() as conn:
        courses, prereqs_rows = _load_courses_and_prereqs(conn)
    try:
        png = _render_prereq_flow_png(courses, prereqs_rows, focus_course=course, direction=direction, depth=depth)
    except Exception as e:
        current_app.logger.exception("flowchart render failed")
        return jsonify({"status": "error", "message": str(e)}), 500

    # Lazy import so app doesn't crash if dependency missing until used
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
    except Exception:
        current_app.logger.exception("pptx dependency missing")
        return jsonify({
            "status": "error",
            "message": "تصدير PowerPoint يحتاج تثبيت python-pptx. نفّذ: pip install -r requirements.txt ثم أعد تشغيل السيرفر."
        }), 500

    prs = Presentation()
    # Use a blank layout if possible
    layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[0]
    slide = prs.slides.add_slide(layout)

    # Title (textbox)
    title = "خريطة المتطلبات بين المقررات"
    if course:
        title += f" — {course}"
    tx = slide.shapes.add_textbox(Inches(0.5), Inches(0.2), Inches(12.5), Inches(0.6))
    tf = tx.text_frame
    tf.clear()
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = title
    run.font.size = Pt(24)
    run.font.bold = True

    # Image
    img_stream = io.BytesIO(png)
    img_stream.seek(0)
    slide.shapes.add_picture(img_stream, Inches(0.5), Inches(1.0), width=Inches(12.5))

    out = io.BytesIO()
    prs.save(out)
    out.seek(0)
    return send_file(
        out,
        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        as_attachment=True,
        download_name="prereqs_flowchart.pptx",
    )

# -----------------------
# Import / Export endpoints
# -----------------------

def _bind_imported_courses_department(
    conn,
    course_names: list[str],
    dept_id: int,
) -> int:
    """تعيين قسم المالك للمقررات المستوردة دون الكتابة فوق تعيين سابق (باستثناء الاتجاه العام)."""
    if not course_names:
        return 0
    cols = fetch_table_columns(conn, "courses")
    if "owning_department_id" not in cols:
        return 0
    bound_names = [
        n
        for n in course_names
        if n and not course_is_college_general(conn, n)
    ]
    if not bound_names:
        return 0
    placeholders = ",".join("?" for _ in bound_names)
    cur = conn.cursor()
    cur.execute(
        f"""
        UPDATE courses
        SET owning_department_id = COALESCE(owning_department_id, ?)
        WHERE course_name IN ({placeholders})
        """,
        (int(dept_id), *bound_names),
    )
    return int(cur.rowcount or 0)


def _course_row_name(row) -> str:
    if row is None:
        return ""
    if hasattr(row, "keys"):
        return str(row["course_name"] or "").strip()
    return str(row[0] or "").strip()


@courses_bp.route("/import/excel", methods=["POST"])
@login_required
def courses_import_excel():
    if _is_instructor_or_supervisor_view_only():
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
    f = request.files.get("file")
    if not f:
        return jsonify({"status": "error", "message": "file required"}), 400
    try:
        df = pd.read_excel(f)
        df.columns = [str(c).lower().strip() for c in df.columns]
        if "course_name" not in df.columns:
            return jsonify({"status": "error", "message": "Columns required: course_name"}), 400
        rows = df.to_dict(orient="records")
        imported_names: list[str] = []
        created: list[str] = []
        updated: list[dict] = []
        ignored: list[dict] = []
        with get_connection() as conn:
            cur = conn.cursor()
            cols = fetch_table_columns(conn, "courses")
            has_cat = "category" in cols
            has_owning = "owning_department_id" in cols
            has_archived = "is_archived" in cols
            archive_clear_sql = ", is_archived = 0" if has_archived else ""
            dept_id = _effective_department_scope_id(conn)
            from backend.core.department_scope_policy import course_writable_by_actor

            actor = _actor_username()
            for r in rows:
                cname = (r.get("course_name") or "").strip()
                if not cname:
                    continue
                code = (r.get("course_code") or "").strip()
                try:
                    units = int(r.get("units", 0) or 0)
                except (TypeError, ValueError):
                    units = 0
                category = (r.get("category") or "required").strip() or "required"
                if category not in ("required", "elective_major", "elective_free"):
                    category = "required"

                # رمز مستخدم لمقرر باسم آخر (مثل GS 201 للكلية) — تجاهل دون إيقاف الاستيراد
                if code:
                    code_hit = courses_repo.find_course_code_duplicate_ci(
                        conn, code, exclude_course_name=cname
                    )
                    existing_name = _course_row_name(code_hit)
                    if existing_name and existing_name.casefold() != cname.casefold():
                        reason = "course_code_exists"
                        if course_is_college_general(
                            conn, existing_name, course_code=code
                        ) or course_is_college_shared_catalog(conn, existing_name):
                            reason = "college_shared_or_general"
                        ignored.append(
                            {
                                "course_name": cname,
                                "course_code": code,
                                "existing_course_name": existing_name,
                                "reason": reason,
                                "message": (
                                    f"الرمز {code} مستخدم مسبقاً للمقرر «{existing_name}» "
                                    "— لم يُنشأ صف جديد (مقرر كلية/موجود)."
                                ),
                            }
                        )
                        continue

                name_row = courses_repo.find_course_name_row_ci(conn, cname)
                name_exists = bool(name_row)
                name_archived = False
                if name_row is not None:
                    try:
                        name_archived = int(
                            name_row["is_archived"]
                            if hasattr(name_row, "keys")
                            else name_row[3] or 0
                        ) == 1
                    except Exception:
                        name_archived = False
                # نشط فقط يمنع التحديث لقفل الكلية؛ المؤرشف يُستعاد عبر ON CONFLICT
                if name_exists and not name_archived:
                    # اتجاه عام / مشترك: لا يحدّثه رئيس تخصص — تنبيه وتجاوز
                    is_locked = course_is_college_general(conn, cname) or course_is_college_shared_catalog(
                        conn, cname, department_id=int(dept_id) if dept_id is not None else None
                    )
                    if is_locked and not course_writable_by_actor(conn, cname, actor):
                        ignored.append(
                            {
                                "course_name": cname,
                                "course_code": code,
                                "existing_course_name": cname,
                                "reason": "name_exists_college",
                                "message": (
                                    f"الاسم «{cname}» موجود ضمن الاتجاه العام/المشترك — "
                                    "تُجاهل دون تعديل، ويُستكمل باقي الملف."
                                ),
                            }
                        )
                        continue

                owning_id = (
                    resolve_import_owning_department_id(conn, cname, dept_id, course_code=code)
                    if has_owning
                    else None
                )
                if has_cat and has_owning and owning_id is not None:
                    cur.execute(
                        f"""
                        INSERT INTO courses (course_name, course_code, units, category, owning_department_id)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(course_name) DO UPDATE SET
                          course_code = excluded.course_code,
                          units = excluded.units,
                          category = excluded.category,
                          owning_department_id = COALESCE(courses.owning_department_id, excluded.owning_department_id)
                          {archive_clear_sql}
                        """,
                        (cname, code, units, category, int(owning_id)),
                    )
                elif has_cat and has_owning:
                    cur.execute(
                        f"""
                        INSERT INTO courses (course_name, course_code, units, category, owning_department_id)
                        VALUES (?, ?, ?, ?, NULL)
                        ON CONFLICT(course_name) DO UPDATE SET
                          course_code = excluded.course_code,
                          units = excluded.units,
                          category = excluded.category
                          {archive_clear_sql}
                        """,
                        (cname, code, units, category),
                    )
                elif has_cat:
                    cur.execute(
                        f"""
                        INSERT INTO courses (course_name, course_code, units, category)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(course_name) DO UPDATE SET
                          course_code = excluded.course_code,
                          units = excluded.units,
                          category = excluded.category
                          {archive_clear_sql}
                        """,
                        (cname, code, units, category),
                    )
                elif has_owning and owning_id is not None:
                    cur.execute(
                        f"""
                        INSERT INTO courses (course_name, course_code, units, owning_department_id)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(course_name) DO UPDATE SET
                          course_code = excluded.course_code,
                          units = excluded.units,
                          owning_department_id = COALESCE(courses.owning_department_id, excluded.owning_department_id)
                          {archive_clear_sql}
                        """,
                        (cname, code, units, int(owning_id)),
                    )
                else:
                    cur.execute(
                        f"""
                        INSERT INTO courses (course_name, course_code, units)
                        VALUES (?, ?, ?)
                        ON CONFLICT(course_name) DO UPDATE SET
                          course_code = excluded.course_code,
                          units = excluded.units
                          {archive_clear_sql}
                        """,
                        (cname, code, units),
                    )
                imported_names.append(cname)
                if name_exists:
                    updated.append(
                        {
                            "course_name": cname,
                            "course_code": code,
                            "reason": "name_exists_restored" if name_archived else "name_exists_updated",
                            "message": (
                                f"الاسم «{cname}» كان مؤرشفاً — تم استعادته وتحديث الرمز/الوحدات."
                                if name_archived
                                else (
                                    f"الاسم «{cname}» موجود مسبقاً — تم تحديث الرمز/الوحدات "
                                    "واستُكمل استيراد باقي المقررات."
                                )
                            ),
                        }
                    )
                else:
                    created.append(cname)
            department_bound = 0
            if dept_id is not None and imported_names and has_owning:
                department_bound = _bind_imported_courses_department(
                    conn, imported_names, int(dept_id)
                )
                from backend.core.department_scope_policy import backfill_courses_owning_department_from_schedule

                backfill_courses_owning_department_from_schedule(conn, department_id=int(dept_id))
            conn.commit()
            try:
                from backend.core.cache_setup import invalidate_list_prefix
                invalidate_list_prefix("courses")
            except Exception:
                pass
        payload: dict = {
            "status": "ok",
            "imported": len(imported_names),
            "created": len(created),
            "updated": len(updated),
            "updated_items": updated,
            "ignored": ignored,
            "ignored_count": len(ignored),
            "warnings_count": len(updated) + len(ignored),
        }
        if dept_id is not None:
            payload["department_id"] = int(dept_id)
            payload["department_bound"] = department_bound
        return jsonify(payload), 200
    except Exception as e:
        current_app.logger.exception("courses_import_excel failed")
        return jsonify({"status": "error", "message": str(e)}), 500


# -----------------------
# Export endpoints
# -----------------------

@courses_bp.route("/export/excel")
@login_required
def export_courses_excel():
    """
    Export courses table as Excel, scoped to the actor's department when applicable.
    """
    if _is_instructor_or_supervisor_view_only():
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
    try:
        with get_connection() as conn:
            df = _courses_export_dataframe(conn)
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
    Export courses list as PDF, scoped to the actor's department when applicable.
    """
    if _is_instructor_or_supervisor_view_only():
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
    try:
        with get_connection() as conn:
            df = _courses_export_dataframe(conn)
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
