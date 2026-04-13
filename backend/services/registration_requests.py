import datetime
from flask import Blueprint, request, jsonify, session

from backend.services.utilities import get_connection
from backend.core.auth import login_required, role_required


registration_requests_bp = Blueprint("registration_requests", __name__)


def _current_user() -> str:
    return session.get("user") or session.get("username") or ""


@registration_requests_bp.route("/registration_requests/create", methods=["POST"])
@login_required
def create_request():
    data = request.get_json(force=True) or {}
    student_id = (data.get("student_id") or "").strip()
    term = (data.get("term") or "").strip()
    course_name = (data.get("course_name") or "").strip()
    action = (data.get("action") or "").strip()
    reason = (data.get("reason") or "").strip()

    if action not in ("add", "drop"):
        return jsonify({"status": "error", "message": "action غير صالح"}), 400
    if not student_id or not course_name:
        return jsonify({"status": "error", "message": "student_id و course_name مطلوبة"}), 400

    # الطالب فقط يمكنه إنشاء طلب، ولـنفسه فقط
    user_role = session.get("user_role")
    if user_role != "student":
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403

    sid_session = session.get("student_id") or session.get("user")
    if sid_session != student_id:
        return jsonify({"status": "error", "message": "لا يمكنك إنشاء طلب لطالب آخر"}), 403

    requested_by = _current_user()

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO registration_requests
            (student_id, term, course_name, action, status, requested_by, request_reason)
            VALUES (?,?,?,?, 'pending', ?, ?)
            """,
            (student_id, term, course_name, action, requested_by, reason or None),
        )
        conn.commit()
        req_id = cur.lastrowid

    return jsonify({"status": "ok", "id": req_id, "message": "تم إرسال الطلب للمراجعة"}), 200


@registration_requests_bp.route("/registration_requests/list", methods=["GET"])
@role_required("admin", "supervisor")
def list_requests():
    raw_role = session.get("user_role") or ""
    is_supervisor = (raw_role == "supervisor") or (raw_role == "instructor" and int(session.get("is_supervisor") or 0) == 1)
    # منع الأستاذ غير المشرف من هذا المسار
    if raw_role == "instructor" and not is_supervisor:
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403

    student_id = (request.args.get("student_id") or "").strip()
    term = (request.args.get("term") or "").strip()
    action = (request.args.get("action") or "").strip()
    status = (request.args.get("status") or "").strip()

    q = """
        SELECT id, student_id, term, course_name, action, status,
               requested_by, reviewed_by, request_reason, review_note,
               created_at, updated_at
        FROM registration_requests
        WHERE 1=1
    """
    params = []

    # Scope للـ supervisor: فقط طلبات طلابه
    if is_supervisor:
        instructor_id = session.get("instructor_id")
        if not instructor_id:
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
        q += """
            AND student_id IN (
                SELECT student_id
                FROM student_supervisor
                WHERE instructor_id = ?
            )
        """
        params.append(instructor_id)
    if student_id:
        q += " AND student_id = ?"
        params.append(student_id)
    if term:
        q += " AND term = ?"
        params.append(term)
    if action in ("add", "drop"):
        q += " AND action = ?"
        params.append(action)
    if status in ("pending", "approved", "rejected", "executed"):
        q += " AND status = ?"
        params.append(status)
    q += " ORDER BY created_at DESC, id DESC"

    with get_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute(q, params).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "student_id": r["student_id"],
                    "term": r["term"],
                    "course_name": r["course_name"],
                    "action": r["action"],
                    "status": r["status"],
                    "requested_by": r["requested_by"],
                    "reviewed_by": r["reviewed_by"],
                    "request_reason": r["request_reason"],
                    "review_note": r["review_note"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                }
            )
    return jsonify({"status": "ok", "items": out})


def _execute_registration_change(conn, student_id: str, course_name: str, action: str):
    """
    تنفيذ الإضافة/الإسقاط فعلياً على جدول registrations مع تسجيل العملية في سجل التغييرات.
    """
    from backend.services.students import normalize_sid

    sid = normalize_sid(student_id)
    cur = conn.cursor()

    rows = cur.execute(
        "SELECT course_name FROM registrations WHERE student_id = ?",
        (sid,),
    ).fetchall()
    current = {r[0] for r in rows}

    # حد الوحدات 12-19 (إلزامي). المشرف لا يمكنه التجاوز، الأدمن يمكنه بشرط ملاحظة الموافقة.
    role = session.get("user_role") or ""
    # حساب الوحدات بعد التغيير المقترح
    proposed = set(current)
    if action == "add":
        proposed.add(course_name)
    elif action == "drop" and course_name in proposed:
        proposed.remove(course_name)
    # جلب وحدات ورموز المقررات دفعة واحدة (يشمل المقرر المُنفَّذ حتى لو خرج من مجموعة proposed بعد الإسقاط)
    meta_names = proposed | {course_name}
    course_lookup: dict[str, tuple[str, int]] = {}
    try:
        if meta_names:
            lst = list(meta_names)
            placeholders = ",".join("?" for _ in lst)
            rows_u = cur.execute(
                f"""
                SELECT course_name, COALESCE(course_code,'') AS course_code,
                       COALESCE(units,0) AS units
                FROM courses
                WHERE course_name IN ({placeholders})
                """,
                lst,
            ).fetchall()
            for r in rows_u:
                course_lookup[r[0]] = ((r[1] or "").strip(), int(r[2] or 0))
    except Exception:
        course_lookup = {}

    total_units = 0
    try:
        total_units = sum(course_lookup.get(c, ("", 0))[1] for c in proposed)
    except Exception:
        total_units = 0
    if total_units and (total_units < 12 or total_units > 19):
        if role != "admin":
            raise ValueError(f"UNITS_LIMIT: إجمالي الوحدات ({total_units}) خارج 12-19 ولا يمكن تنفيذه بواسطة {role or 'user'}.")

    if action == "add":
        if course_name in current:
            return
        cur.execute(
            "INSERT OR IGNORE INTO registrations (student_id, course_name) VALUES (?,?)",
            (sid, course_name),
        )
    elif action == "drop":
        if course_name not in current:
            return
        cur.execute(
            "DELETE FROM registrations WHERE student_id = ? AND course_name = ?",
            (sid, course_name),
        )
    else:
        return

    # تسجيل في سجل التغييرات
    try:
        student_row = cur.execute(
            "SELECT COALESCE(student_name,'') FROM students WHERE student_id = ?",
            (sid,),
        ).fetchone()
        student_name = student_row[0] if student_row else ""
    except Exception:
        student_name = ""

    course_code, units = course_lookup.get(course_name, ("", 0))
    performed_by = _current_user()
    # نحاول ربط السجل بالفصل الحالي
    try:
        from backend.services.utilities import get_current_term
        term_name, term_year = get_current_term(conn=conn)
        term_label = f"{term_name} {term_year}".strip()
    except Exception:
        term_label = ""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    prev_state = '{"registered": false}'
    new_state = '{"registered": true}'
    if action == "drop":
        prev_state, new_state = new_state, prev_state

    try:
        cur.execute(
            """
            INSERT INTO registration_changes_log
            (student_id, student_name, term, course_name, course_code, units,
             action, action_phase, action_time, performed_by, reason, notes,
             prev_state, new_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sid,
                student_name,
                term_label,
                course_name,
                course_code,
                units,
                action,
                "manual",
                now_iso,
                performed_by,
                None,
                "request_execute",
                prev_state,
                new_state,
            ),
        )
    except Exception:
        # إذا لم يكن جدول السجل موجوداً بعد، لا نفشل العملية الأساسية
        pass


@registration_requests_bp.route("/registration_requests/approve", methods=["POST"])
@role_required("admin", "supervisor")
def approve_request():
    raw_role = session.get("user_role") or ""
    is_supervisor = (raw_role == "supervisor") or (raw_role == "instructor" and int(session.get("is_supervisor") or 0) == 1)
    if raw_role == "instructor" and not is_supervisor:
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403

    data = request.get_json(force=True) or {}
    req_id = data.get("id")
    execute_now = bool(data.get("execute_now", True))
    note = (data.get("note") or "").strip()
    if not req_id:
        return jsonify({"status": "error", "message": "id مطلوب"}), 400

    reviewer = _current_user()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id, student_id, term, course_name, action, status FROM registration_requests WHERE id = ?",
            (req_id,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "الطلب غير موجود"}), 404

        # Scope للـ supervisor: فقط اعتماد طلبات طلابه
        if is_supervisor:
            instructor_id = session.get("instructor_id")
            if not instructor_id:
                return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
            allowed = cur.execute(
                """
                SELECT 1
                FROM student_supervisor
                WHERE student_id = ? AND instructor_id = ?
                LIMIT 1
                """,
                (row["student_id"], instructor_id),
            ).fetchone()
            if not allowed:
                return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
        if row["status"] not in ("pending", "approved"):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"لا يمكن اعتماد طلب حالته الحالية: {row['status']}",
                    }
                ),
                400,
            )

        status = "approved"
        if execute_now:
            # إذا كانت العملية ستؤدي لتجاوز حد الوحدات، الأدمن فقط يسمح وبشرط ملاحظة
            try:
                _execute_registration_change(conn, row["student_id"], row["course_name"], row["action"])
            except ValueError as ve:
                msg = str(ve)
                if msg.startswith("UNITS_LIMIT"):
                    # إذا الأدمن: نطلب note كسبب إلزامي
                    role = session.get("user_role") or ""
                    if role == "admin":
                        if not note:
                            return jsonify({"status": "error", "code": "UNITS_OVERRIDE_REQUIRED", "message": "يتطلب سبب/ملاحظة لاعتماد وتنفيذ طلب يؤدي لتجاوز حد الوحدات."}), 400
                        # نعيد التنفيذ بعد توفر note (التجاوز مسموح للأدمن)
                        _execute_registration_change(conn, row["student_id"], row["course_name"], row["action"])
                    else:
                        return jsonify({"status": "error", "code": "UNITS_LIMIT", "message": "لا يمكن تنفيذ الطلب لأن التغيير يؤدي لتجاوز حد الوحدات 12-19."}), 400
                else:
                    raise
            status = "executed"

        cur.execute(
            """
            UPDATE registration_requests
            SET status = ?, reviewed_by = ?, review_note = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, reviewer, note or None, now_iso, req_id),
        )
        conn.commit()

    return jsonify(
        {
            "status": "ok",
            "message": "تم اعتماد الطلب" + (" وتم التنفيذ" if execute_now else ""),
        }
    ), 200


@registration_requests_bp.route("/registration_requests/reject", methods=["POST"])
@role_required("admin", "supervisor")
def reject_request():
    raw_role = session.get("user_role") or ""
    is_supervisor = (raw_role == "supervisor") or (raw_role == "instructor" and int(session.get("is_supervisor") or 0) == 1)
    if raw_role == "instructor" and not is_supervisor:
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403

    data = request.get_json(force=True) or {}
    req_id = data.get("id")
    note = (data.get("note") or "").strip()
    if not req_id:
        return jsonify({"status": "error", "message": "id مطلوب"}), 400

    reviewer = _current_user()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id, student_id, status FROM registration_requests WHERE id = ?",
            (req_id,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "الطلب غير موجود"}), 404

        # Scope للـ supervisor: فقط رفض طلبات طلابه
        if is_supervisor:
            instructor_id = session.get("instructor_id")
            if not instructor_id:
                return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
            allowed = cur.execute(
                """
                SELECT 1
                FROM student_supervisor
                WHERE student_id = ? AND instructor_id = ?
                LIMIT 1
                """,
                (row["student_id"], instructor_id),
            ).fetchone()
            if not allowed:
                return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
        if row["status"] not in ("pending",):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"لا يمكن رفض طلب حالته الحالية: {row['status']}",
                    }
                ),
                400,
            )

        cur.execute(
            """
            UPDATE registration_requests
            SET status = 'rejected', reviewed_by = ?, review_note = ?, updated_at = ?
            WHERE id = ?
            """,
            (reviewer, note or None, now_iso, req_id),
        )
        conn.commit()

    return jsonify({"status": "ok", "message": "تم رفض الطلب"}), 200

