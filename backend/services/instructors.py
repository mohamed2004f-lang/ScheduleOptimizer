from flask import Blueprint, request, jsonify, session

from backend.core.auth import admin_required, login_required
from .utilities import get_connection

instructors_bp = Blueprint("instructors", __name__)


@instructors_bp.route("/list")
@login_required
def list_instructors():
    """
    إرجاع قائمة أعضاء هيئة التدريس.
    الحقول: id, name, type, email, is_active
    """
    with get_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT id, name, type, email, is_active FROM instructors ORDER BY name"
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
                }
            )
    return jsonify({"instructors": items})


@instructors_bp.route("/save", methods=["POST"])
@admin_required
def save_instructor():
    """
    إضافة / تعديل عضو هيئة تدريس.
    body:
      - id (اختياري: عند الإرسال يتم التعديل، وإلا يُنشأ سجل جديد)
      - name (نصي إجباري)
      - type: internal | external
      - email (اختياري)
      - is_active (اختياري: 1/0 أو true/false)
    """
    data = request.get_json(force=True) or {}
    inst_id = data.get("id")
    name = (data.get("name") or "").strip()
    inst_type = (data.get("type") or "internal").strip() or "internal"
    email = (data.get("email") or "").strip() or None
    is_active_raw = data.get("is_active", 1)

    if not name:
        return (
            jsonify({"status": "error", "message": "name مطلوب"}),
            400,
        )

    # تطبيع is_active إلى 0/1
    is_active = 1
    if isinstance(is_active_raw, str):
        is_active = 0 if is_active_raw.strip().lower() in ("0", "false", "no") else 1
    elif isinstance(is_active_raw, (int, bool)):
        is_active = 1 if bool(is_active_raw) else 0

    with get_connection() as conn:
        cur = conn.cursor()
        if inst_id:
            cur.execute(
                """
                UPDATE instructors
                SET name = ?, type = ?, email = ?, is_active = ?
                WHERE id = ?
                """,
                (name, inst_type, email, is_active, inst_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO instructors (name, type, email, is_active)
                VALUES (?,?,?,?)
                """,
                (name, inst_type, email, is_active),
            )
        conn.commit()

    return jsonify({"status": "ok"})


@instructors_bp.route("/delete", methods=["POST"])
@admin_required
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

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM instructors WHERE id = ?", (inst_id,))
        conn.commit()

    return jsonify({"status": "ok"})


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

    if user_role == "supervisor" or (user_role == "instructor" and int(session.get("is_supervisor") or 0) == 1):
        instructor_id = session.get("instructor_id")
    else:
        instructor_id = request.args.get("instructor_id", type=int)

    if not instructor_id:
        return jsonify({"status": "error", "message": "instructor_id مطلوب"}), 400

    active_only = request.args.get("active_only", "").lower() in ("1", "true", "yes")

    with get_connection() as conn:
        cur = conn.cursor()
        cols = [row[1] for row in cur.execute("PRAGMA table_info(students)").fetchall()]
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
                INSERT OR IGNORE INTO student_supervisor (student_id, instructor_id)
                VALUES (?, ?)
                """,
                (sid, instructor_id),
            )
        conn.commit()

    return jsonify(
        {"status": "ok", "assigned_count": len(cleaned_ids), "instructor_id": instructor_id}
    )

