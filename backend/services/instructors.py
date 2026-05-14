from flask import Blueprint, request, jsonify, session

from backend.core.auth import admin_required, current_supervisor_effective, login_required, role_required
from backend.core.department_scope_policy import (
    actor_can_manage_existing_instructor,
    finalize_instructor_department_id_for_write,
    proposed_department_allowed_for_scope,
    resolve_users_list_scope,
)
from backend.core.feature_flags import is_multi_dept_instructor_enabled
from backend.database.database import fetch_table_columns
from backend.repositories.instructor_assignments_repo import (
    assignments_table_ready,
    list_assignment_department_details,
    list_assignments_for_instructor,
    replace_user_assignments_from_payload,
)
from backend.repositories.instructor_students_repo import (
    instructor_linked_to_department,
    students_for_instructor_department,
)
from .utilities import get_connection

instructors_bp = Blueprint("instructors", __name__)

_MANAGE_ROLES = ("admin_main", "head_of_department")
_EXTERNAL_SCOPE_ALLOWED = {"within_college", "outside_college", "outside_university"}


def _current_actor_username() -> str:
    return (session.get("user") or session.get("username") or "").strip()


def _normalize_role_local(raw: str | None) -> str:
    try:
        from backend.core.auth import _normalize_role

        return _normalize_role((raw or "").strip())
    except Exception:
        return (raw or "").strip()


def _can_access_instructor_admin_endpoint(conn, actor_username: str, instructor_db_id: int) -> bool:
    """صلاحية الوصول لمسارات إدارة الأستاذ (حسب الدور ونطاق القسم)."""
    role = _normalize_role_local(session.get("user_role"))
    if role in ("admin_main", "admin"):
        return actor_can_manage_existing_instructor(conn, actor_username, int(instructor_db_id))
    if role == "head_of_department":
        return actor_can_manage_existing_instructor(conn, actor_username, int(instructor_db_id))
    if role == "instructor":
        try:
            return int(session.get("instructor_id") or 0) == int(instructor_db_id)
        except (TypeError, ValueError):
            return False
    return False


def _can_bypass_scope_for_cross_department_assignments() -> bool:
    """
    السماح للمسؤول الرئيسي بإدارة الأقسام المتعاونة عبر الأقسام
    حتى عند تفعيل نطاق عرض مؤقت في الجلسة.
    """
    role = _normalize_role_local(session.get("user_role"))
    return role in ("admin_main", "admin")


@instructors_bp.route("/list")
@login_required
def list_instructors():
    """
    إرجاع قائمة أعضاء هيئة التدريس.

    لمسؤول رئيسي / رئيس قسم: تصفية حسب نطاق القسم في الجلسة أو قسم رئيس القسم.
    لبقية الأدوار: القائمة الكاملة لاستخدام القوائم المنسدلة في النماذج الأخرى.
    """
    actor = _current_actor_username()
    with get_connection() as conn:
        cur = conn.cursor()
        icols = fetch_table_columns(conn, "instructors")
        has_dept = "department_id" in icols
        has_external_scope = "external_scope" in icols
        mode, dep_id = resolve_users_list_scope(conn, actor)

        if mode == "empty":
            return jsonify({"instructors": []})

        if has_dept:
            if has_external_scope:
                sel = (
                    "SELECT i.id, i.name, i.type, i.email, i.is_active, "
                    "i.department_id, d.code, d.name_ar, i.external_scope "
                    "FROM instructors i "
                    "LEFT JOIN departments d ON d.id = i.department_id "
                )
            else:
                sel = (
                    "SELECT i.id, i.name, i.type, i.email, i.is_active, "
                    "i.department_id, d.code, d.name_ar "
                    "FROM instructors i "
                    "LEFT JOIN departments d ON d.id = i.department_id "
                )
            if mode == "department" and dep_id is not None:
                if assignments_table_ready(conn) and is_multi_dept_instructor_enabled():
                    rows = cur.execute(
                        sel
                        + """ WHERE (
                            i.department_id = ? OR EXISTS (
                                SELECT 1 FROM instructor_department_assignments a
                                WHERE a.instructor_id = i.id AND a.department_id = ? AND a.is_active = 1
                            )
                        ) ORDER BY i.name""",
                        (int(dep_id), int(dep_id)),
                    ).fetchall()
                else:
                    rows = cur.execute(sel + " WHERE i.department_id = ? ORDER BY i.name", (int(dep_id),)).fetchall()
            else:
                rows = cur.execute(sel + " ORDER BY i.name").fetchall()
            items = []
            for r in rows:
                di = r[5] if len(r) > 5 else None
                dept_id_out = None
                if di not in (None, ""):
                    try:
                        dept_id_out = int(di)
                    except (TypeError, ValueError):
                        dept_id_out = None
                items.append(
                    {
                        "id": r[0],
                        "name": r[1],
                        "type": r[2],
                        "email": r[3],
                        "is_active": bool(r[4]),
                        "department_id": dept_id_out,
                        "department_code": r[6] if len(r) > 6 else None,
                        "department_name_ar": r[7] if len(r) > 7 else None,
                        "external_scope": r[8] if has_external_scope and len(r) > 8 else "within_college",
                    }
                )
        else:
            rows = cur.execute(
                (
                    "SELECT id, name, type, email, is_active, external_scope FROM instructors ORDER BY name"
                    if has_external_scope
                    else "SELECT id, name, type, email, is_active FROM instructors ORDER BY name"
                )
            ).fetchall()
            items = []
            for r in rows:
                items.append(
                    {
                        "id": r[0],
                        "name": r[1],
                        "type": r[2],
                        "email": r[3],
                        "is_active": bool(r[4]),
                        "department_id": None,
                        "department_code": None,
                        "department_name_ar": None,
                        "external_scope": r[5] if has_external_scope and len(r) > 5 else "within_college",
                    }
                )

        enrich_ids = [it["id"] for it in items]
        dept_multi: dict = {}
        if is_multi_dept_instructor_enabled() and assignments_table_ready(conn) and enrich_ids:
            dept_multi = list_assignment_department_details(conn, enrich_ids)
        for it in items:
            # الأقسام المتعاونة المعروضة يجب أن تستبعد القسم الرئيسي وتزيل التكرار.
            primary_id = it.get("department_id")
            raw_rows = dept_multi.get(it["id"], [])
            uniq: list[dict] = []
            seen_ids: set[int] = set()
            for d in raw_rows:
                try:
                    did = int(d.get("department_id"))
                except (TypeError, ValueError, AttributeError):
                    continue
                if primary_id not in (None, ""):
                    try:
                        if int(primary_id) == did:
                            continue
                    except (TypeError, ValueError):
                        pass
                if did in seen_ids:
                    continue
                seen_ids.add(did)
                uniq.append(
                    {
                        "department_id": did,
                        "department_code": d.get("department_code"),
                        "department_name_ar": d.get("department_name_ar"),
                    }
                )
            it["departments"] = uniq

    return jsonify({"instructors": items})


@instructors_bp.route("/save", methods=["POST"])
@role_required(*_MANAGE_ROLES)
def save_instructor():
    """
    إضافة / تعديل عضو هيئة تدريس.
    body:
      - id (اختياري)
      - name (إجباري)
      - type: internal | external
      - email (اختياري)
      - is_active (اختياري)
      - department_id (اختياري؛ للمسؤول بلا نطاق قسم)
      - department_assignments (اختياري): قائمة إسنادات أقسام إضافية عند تفعيل ENABLE_MULTI_DEPT_INSTRUCTOR
    """
    data = request.get_json(force=True) or {}
    inst_id_raw = data.get("id")
    name = (data.get("name") or "").strip()
    inst_type = (data.get("type") or "internal").strip() or "internal"
    email = (data.get("email") or "").strip() or None
    is_active_raw = data.get("is_active", 1)
    body_dept = data.get("department_id")
    external_scope_raw = (data.get("external_scope") or "").strip()

    if not name:
        return (
            jsonify({"status": "error", "message": "name مطلوب"}),
            400,
        )

    is_active = 1
    if isinstance(is_active_raw, str):
        is_active = 0 if is_active_raw.strip().lower() in ("0", "false", "no") else 1
    elif isinstance(is_active_raw, (int, bool)):
        is_active = 1 if bool(is_active_raw) else 0

    inst_id = None
    if inst_id_raw not in (None, ""):
        try:
            inst_id = int(inst_id_raw)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "رقم عضو هيئة التدريس يجب أن يكون رقمًا صحيحًا"}), 400

    actor = _current_actor_username()
    actor_role = _normalize_role_local(session.get("user_role"))

    with get_connection() as conn:
        cur = conn.cursor()
        icols = fetch_table_columns(conn, "instructors")
        has_dept = "department_id" in icols
        has_external_scope = "external_scope" in icols

        final_dept, fd_err = finalize_instructor_department_id_for_write(
            conn, actor_username=actor, body_department_id=body_dept
        )
        if not fd_err[0]:
            return jsonify({"status": "error", "message": fd_err[1]}), 400

        # admin_main/admin: اسمح بتعديل القسم الرئيسي صراحةً حتى مع وجود نطاق عرض مفعّل في الجلسة.
        if actor_role in ("admin_main", "admin") and "department_id" in data:
            if body_dept in (None, ""):
                final_dept = None
            else:
                try:
                    final_dept = int(body_dept)
                except (TypeError, ValueError):
                    return jsonify({"status": "error", "message": "department_id غير صالح."}), 400

        if actor_role not in ("admin_main", "admin"):
            ok_prop, msg_prop = proposed_department_allowed_for_scope(conn, actor, final_dept)
            if not ok_prop:
                return jsonify({"status": "error", "message": msg_prop}), 400

        # قواعد القسم الرئيسي/نطاق التعاون:
        # - internal: القسم الرئيسي إلزامي
        # - external: external_scope إلزامي إذا العمود متاح
        if inst_type == "internal" and final_dept is None:
            return jsonify({"status": "error", "message": "القسم الرئيسي إلزامي للأستاذ من داخل القسم."}), 400
        external_scope = external_scope_raw or "within_college"
        if has_external_scope and inst_type == "external" and external_scope not in _EXTERNAL_SCOPE_ALLOWED:
            return jsonify({"status": "error", "message": "external_scope غير صالح."}), 400
        if has_external_scope and inst_type == "internal":
            # للأساتذة الداخليين لا نحتاج تمييز خارجي؛ نخزن قيمة افتراضية متسقة
            external_scope = "within_college"

        if inst_id is not None and not actor_can_manage_existing_instructor(conn, actor, inst_id):
            return jsonify({"status": "error", "message": "لا يمكن تعديل هذا السجل خارج نطاق قسمك."}), 403

        try:
            if inst_id is not None:
                exists = cur.execute("SELECT 1 FROM instructors WHERE id = ? LIMIT 1", (inst_id,)).fetchone()
                if exists:
                    if has_dept:
                        if has_external_scope:
                            cur.execute(
                                """
                                UPDATE instructors
                                SET name = ?, type = ?, email = ?, is_active = ?, department_id = ?, external_scope = ?
                                WHERE id = ?
                                """,
                                (name, inst_type, email, is_active, final_dept, external_scope, inst_id),
                            )
                        else:
                            cur.execute(
                                """
                                UPDATE instructors
                                SET name = ?, type = ?, email = ?, is_active = ?, department_id = ?
                                WHERE id = ?
                                """,
                                (name, inst_type, email, is_active, final_dept, inst_id),
                            )
                    else:
                        cur.execute(
                            """
                            UPDATE instructors
                            SET name = ?, type = ?, email = ?, is_active = ?
                            WHERE id = ?
                            """,
                            (name, inst_type, email, is_active, inst_id),
                        )
                else:
                    if has_dept:
                        if has_external_scope:
                            cur.execute(
                                """
                                INSERT INTO instructors (id, name, type, email, is_active, department_id, external_scope)
                                VALUES (?,?,?,?,?,?,?)
                                """,
                                (inst_id, name, inst_type, email, is_active, final_dept, external_scope),
                            )
                        else:
                            cur.execute(
                                """
                                INSERT INTO instructors (id, name, type, email, is_active, department_id)
                                VALUES (?,?,?,?,?,?)
                                """,
                                (inst_id, name, inst_type, email, is_active, final_dept),
                            )
                    else:
                        cur.execute(
                            """
                            INSERT INTO instructors (id, name, type, email, is_active)
                            VALUES (?,?,?,?,?)
                            """,
                            (inst_id, name, inst_type, email, is_active),
                        )
            else:
                if has_dept:
                    if has_external_scope:
                        cur.execute(
                            """
                            INSERT INTO instructors (name, type, email, is_active, department_id, external_scope)
                            VALUES (?,?,?,?,?,?)
                            """,
                            (name, inst_type, email, is_active, final_dept, external_scope),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO instructors (name, type, email, is_active, department_id)
                            VALUES (?,?,?,?,?)
                            """,
                            (name, inst_type, email, is_active, final_dept),
                        )
                else:
                    cur.execute(
                        """
                        INSERT INTO instructors (name, type, email, is_active)
                        VALUES (?,?,?,?)
                        """,
                        (name, inst_type, email, is_active),
                    )
        except Exception as e:
            msg = str(e).lower()
            if "duplicate" in msg or "unique" in msg:
                return jsonify({"status": "error", "message": "رقم عضو هيئة التدريس مستخدم بالفعل"}), 409
            raise

        resolved_id = inst_id if inst_id is not None else int(cur.lastrowid or 0)
        if (
            resolved_id
            and is_multi_dept_instructor_enabled()
            and assignments_table_ready(conn)
            and isinstance(data.get("department_assignments"), list)
            and actor_can_manage_existing_instructor(conn, actor, int(resolved_id))
        ):
            for a in data.get("department_assignments") or []:
                try:
                    pd = int(a.get("department_id"))
                except (TypeError, ValueError):
                    continue
                if not _can_bypass_scope_for_cross_department_assignments():
                    ok_pd, msg_pd = proposed_department_allowed_for_scope(conn, actor, pd)
                    if not ok_pd:
                        conn.rollback()
                        return jsonify({"status": "error", "message": msg_pd}), 400
            replace_user_assignments_from_payload(
                conn, int(resolved_id), data.get("department_assignments") or []
            )

        conn.commit()

    return jsonify({"status": "ok"})


@instructors_bp.route("/delete", methods=["POST"])
@role_required(*_MANAGE_ROLES)
def delete_instructor():
    """
    حذف عضو هيئة تدريس.
    body:
      - id
    """
    data = request.get_json(force=True) or {}
    inst_id = data.get("id")
    if not inst_id:
        return (
            jsonify({"status": "error", "message": "id مطلوب"}),
            400,
        )

    try:
        inst_id = int(inst_id)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "id غير صالح"}), 400

    actor = _current_actor_username()

    with get_connection() as conn:
        if not actor_can_manage_existing_instructor(conn, actor, inst_id):
            return jsonify({"status": "error", "message": "لا يمكن حذف هذا السجل خارج نطاق قسمك."}), 403
        cur = conn.cursor()
        cur.execute("DELETE FROM instructors WHERE id = ?", (inst_id,))
        conn.commit()

    return jsonify({"status": "ok"})


@instructors_bp.route("/<int:instructor_id>/department_assignments", methods=["GET"])
@login_required
def get_instructor_department_assignments(instructor_id: int):
    """قائمة إسنادات الأستاذ للأقسام (جدول instructor_department_assignments)."""
    actor = _current_actor_username()
    with get_connection() as conn:
        if not _can_access_instructor_admin_endpoint(conn, actor, instructor_id):
            return jsonify({"status": "error", "message": "غير مصرّح"}), 403
        if not is_multi_dept_instructor_enabled():
            return jsonify({"status": "ok", "assignments": [], "feature_disabled": True})
        rows = list_assignments_for_instructor(conn, instructor_id)
        return jsonify({"status": "ok", "assignments": rows})


@instructors_bp.route("/<int:instructor_id>/department_assignments/save", methods=["POST"])
@login_required
def save_instructor_department_assignments(instructor_id: int):
    """
    حفظ إسنادات المستخدم فقط (لا يمس سجلات الترحيل schedule_backfill / home_backfill).
    body: { \"assignments\": [ { department_id, schedule_section_id?, semester?, is_primary? }, ... ] }
    """
    actor = _current_actor_username()
    data = request.get_json(force=True) or {}
    assignments = data.get("assignments")
    if not isinstance(assignments, list):
        return jsonify({"status": "error", "message": "assignments يجب أن تكون قائمة"}), 400
    with get_connection() as conn:
        if not _can_access_instructor_admin_endpoint(conn, actor, instructor_id):
            return jsonify({"status": "error", "message": "غير مصرّح"}), 403
        if not is_multi_dept_instructor_enabled() or not assignments_table_ready(conn):
            return jsonify({"status": "error", "message": "الميزة غير مفعّلة"}), 400
        if not actor_can_manage_existing_instructor(conn, actor, instructor_id):
            return jsonify({"status": "error", "message": "لا يمكن التعديل خارج نطاق قسمك."}), 403
        for a in assignments:
            try:
                pd = int(a.get("department_id"))
            except (TypeError, ValueError):
                continue
            if not _can_bypass_scope_for_cross_department_assignments():
                ok_pd, msg_pd = proposed_department_allowed_for_scope(conn, actor, pd)
                if not ok_pd:
                    return jsonify({"status": "error", "message": msg_pd}), 400
        replace_user_assignments_from_payload(conn, instructor_id, assignments)
        conn.commit()
    return jsonify({"status": "ok"})


@instructors_bp.route("/<int:instructor_id>/students_by_department", methods=["GET"])
@login_required
def instructor_students_by_department(instructor_id: int):
    """
    طلاب القسم المسجّلون في مقررات يدرّسها الأستاذ في ذلك القسم (مع توسعة التكافؤ).
    Query: department_id (إجباري)، semester (اختياري لتصفية صفوف الجدول).
    """
    actor = _current_actor_username()
    dept_raw = request.args.get("department_id")
    try:
        dept_id = int(dept_raw)
    except (TypeError, ValueError):
        dept_id = None
    if not dept_id:
        return jsonify({"status": "error", "message": "department_id مطلوب"}), 400
    semester = request.args.get("semester")
    sem = str(semester).strip() if semester not in (None, "") else None

    with get_connection() as conn:
        if not _can_access_instructor_admin_endpoint(conn, actor, instructor_id):
            return jsonify({"status": "error", "message": "غير مصرّح"}), 403
        if not instructor_linked_to_department(conn, instructor_id, dept_id):
            return jsonify({"status": "error", "message": "الأستاذ غير مرتبط بهذا القسم"}), 400
        students, courses = students_for_instructor_department(conn, instructor_id, dept_id, sem)
        return jsonify(
            {
                "status": "ok",
                "instructor_id": instructor_id,
                "department_id": dept_id,
                "semester": sem,
                "students": students,
                "course_names_resolved": courses,
            }
        )


@instructors_bp.route("/supervised_students")
@login_required
def supervised_students():
    """
    إرجاع الطلبة المسندين إلى مشرف معيّن.
    - إذا كان المستخدم أدمن: يمرر instructor_id في query string.
    - إذا كان المستخدم مشرفاً: يستخدم instructor_id من الجلسة ويتجاهل أي قيمة أخرى.
    """
    user_role = session.get("user_role")
    instructor_id = None

    if current_supervisor_effective():
        instructor_id = session.get("instructor_id")
    else:
        instructor_id = request.args.get("instructor_id", type=int)

    if not instructor_id:
        return jsonify({"status": "error", "message": "instructor_id مطلوب"}), 400

    active_only = request.args.get("active_only", "").lower() in ("1", "true", "yes")

    with get_connection() as conn:
        cur = conn.cursor()
        cols = fetch_table_columns(conn, "students")
        has_enrollment_status = "enrollment_status" in cols
        has_join = "join_term" in cols and "join_year" in cols
        extra_sel = ", COALESCE(s.join_term, '') AS join_term, COALESCE(s.join_year, '') AS join_year" if has_join else ""
        if has_enrollment_status and active_only:
            rows = cur.execute(
                """
                SELECT ss.student_id,
                       COALESCE(s.student_name, '') AS student_name
                """ + extra_sel + """
                FROM student_supervisor ss
                LEFT JOIN students s ON s.student_id = ss.student_id
                WHERE ss.instructor_id = ?
                  AND COALESCE(s.enrollment_status, 'active') = 'active'
                ORDER BY ss.student_id
                """,
                (instructor_id,),
            ).fetchall()
        else:
            rows = cur.execute(
                """
                SELECT ss.student_id,
                       COALESCE(s.student_name, '') AS student_name
                """ + extra_sel + """
                FROM student_supervisor ss
                LEFT JOIN students s ON s.student_id = ss.student_id
                WHERE ss.instructor_id = ?
                ORDER BY ss.student_id
                """,
                (instructor_id,),
            ).fetchall()
        if has_join:
            students = [
                {"student_id": r[0], "student_name": r[1], "join_term": (r[2] or "").strip(), "join_year": (r[3] or "").strip()}
                for r in rows
            ]
        else:
            students = [
                {"student_id": r[0], "student_name": r[1], "join_term": "", "join_year": ""} for r in rows
            ]
    return jsonify(
        {"status": "ok", "instructor_id": instructor_id, "students": students}
    )


@instructors_bp.route("/available_students")
@admin_required
def available_students():
    """
    إرجاع جميع الطلبة مع معلومة إن كان لديهم أي مشرف.
    يستخدمها الأدمن في شاشة إسناد الطلبة للمشرفين.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT s.student_id,
                   COALESCE(s.student_name, '') AS student_name,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM student_supervisor ss
                       WHERE ss.student_id = s.student_id
                   ) THEN 1 ELSE 0 END AS has_supervisor
            FROM students s
            ORDER BY s.student_id
            """
        ).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "student_id": r[0],
                    "student_name": r[1],
                    "has_supervisor": bool(r[2]),
                }
            )
    return jsonify({"status": "ok", "students": out})


@instructors_bp.route("/assign_students", methods=["POST"])
@admin_required
def assign_students():
    """
    إسناد مجموعة من الطلبة إلى مشرف معيّن.
    body:
      - instructor_id (إجباري)
      - student_ids: قائمة أرقام الطلبة (إجباري)
    المنطق:
      - حذف كل السجلات السابقة لهذا المشرف.
      - إدخال الإسنادات الجديدة.
    """
    data = request.get_json(force=True) or {}
    instructor_id = data.get("instructor_id")
    student_ids = data.get("student_ids") or []

    try:
        instructor_id = int(instructor_id)
    except (TypeError, ValueError):
        instructor_id = None

    if not instructor_id:
        return (
            jsonify({"status": "error", "message": "instructor_id مطلوب"}),
            400,
        )
    if not isinstance(student_ids, list):
        return (
            jsonify({"status": "error", "message": "student_ids يجب أن تكون قائمة"}),
            400,
        )

    # إزالة التكرار وتطبيع الأرقام
    cleaned_ids = []
    seen = set()
    for sid in student_ids:
        if sid is None:
            continue
        s = str(sid).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        cleaned_ids.append(s)

    with get_connection() as conn:
        cur = conn.cursor()
        # تأكد من أن المشرف موجود
        inst_row = cur.execute(
            "SELECT id FROM instructors WHERE id = ?", (instructor_id,)
        ).fetchone()
        if not inst_row:
            return (
                jsonify({"status": "error", "message": "المشرف غير موجود"}),
                404,
            )

        # حذف الإسنادات السابقة
        cur.execute(
            "DELETE FROM student_supervisor WHERE instructor_id = ?",
            (instructor_id,),
        )

        # إدخال الإسنادات الجديدة
        for sid in cleaned_ids:
            cur.execute(
                """
                INSERT INTO student_supervisor (student_id, instructor_id)
                VALUES (?, ?)
                ON CONFLICT (student_id, instructor_id) DO NOTHING
                """,
                (sid, instructor_id),
            )
        conn.commit()

    return jsonify(
        {"status": "ok", "assigned_count": len(cleaned_ids), "instructor_id": instructor_id}
    )

