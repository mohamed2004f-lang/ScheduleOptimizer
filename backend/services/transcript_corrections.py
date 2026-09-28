"""طلبات تصحيح كشف الدرجات من المشرف الأكاديمي لاعتماد رئيس القسم."""
from __future__ import annotations

import datetime
import json
from typing import Any

from flask import Blueprint, current_app, jsonify, request, session

from backend.core.auth import current_supervisor_effective, login_required, role_required
from backend.core.department_scope_policy import (
    assert_student_in_actor_scope,
    courses_department_scope_filter,
)
from backend.database.database import fetch_table_columns, is_postgresql
from backend.services.course_workflow import notify_department_hods, notify_instructor
from backend.services.grades import (
    _audit_changed_by,
    _current_user_name,
    _require_post_publish_reason,
    _session_role,
    apply_grades_batch,
)
from backend.services.utilities import (
    get_connection,
    get_current_term,
    log_activity,
    schedule_semester_matches_current_term,
)

transcript_corrections_bp = Blueprint("transcript_corrections", __name__)


def _now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _ensure_table(conn) -> None:
    """إنشاء الجدول في SQLite للاختبارات؛ على PostgreSQL يعتمد Alembic."""
    if is_postgresql():
        return
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS transcript_correction_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            semester TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'pending',
            reason TEXT NOT NULL DEFAULT '',
            hod_note TEXT NOT NULL DEFAULT '',
            submitted_by TEXT NOT NULL DEFAULT '',
            instructor_id INTEGER,
            department_id INTEGER,
            created_at TEXT,
            submitted_at TEXT,
            reviewed_at TEXT,
            reviewed_by TEXT NOT NULL DEFAULT ''
        )
        """
    )


def _session_instructor_id() -> int | None:
    try:
        raw = session.get("instructor_id")
        if raw in (None, ""):
            return None
        return int(raw)
    except (TypeError, ValueError, RuntimeError):
        return None


def _is_supervisor_actor() -> bool:
    return bool(current_supervisor_effective())


def _assert_advisee(conn, student_id: str, instructor_id: int) -> None:
    row = conn.cursor().execute(
        "SELECT 1 FROM student_supervisor WHERE student_id = ? AND instructor_id = ? LIMIT 1",
        (student_id, instructor_id),
    ).fetchone()
    if not row:
        raise PermissionError("الطالب غير مسند إليك كمشرف أكاديمي")


def _assert_previous_term(conn, semester: str) -> None:
    term_name, term_year = get_current_term(conn=conn)
    current_label = f"{(term_name or '').strip()} {(term_year or '').strip()}".strip()
    if not current_label:
        return
    if schedule_semester_matches_current_term(semester, current_label):
        raise ValueError(
            "يُسمح للمشرف بطلب تصحيح فصول سابقة فقط — الفصل الحالي عبر مسودات الدرجات/الأستاذ."
        )


def _student_department_id(conn, student_id: str) -> int | None:
    row = conn.cursor().execute(
        "SELECT department_id FROM students WHERE student_id = ? LIMIT 1",
        (student_id,),
    ).fetchone()
    if not row or row[0] in (None, ""):
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def _normalize_grades_payload(grades: list) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for g in grades or []:
        if not isinstance(g, dict):
            continue
        cname = (g.get("course_name") or "").strip()
        if not cname:
            continue
        item = {
            "course_name": cname,
            "course_code": (g.get("course_code") or "").strip(),
            "grade": g.get("grade", None),
            "units": g.get("units"),
        }
        if "is_equated" in g:
            item["is_equated"] = bool(g.get("is_equated"))
        out.append(item)
    if not out:
        raise ValueError("قائمة المقررات/الدرجات فارغة")
    return out


def _parse_correction_payload(raw: Any) -> tuple[list, bool, dict | None]:
    """يدعم الحمولة القديمة (قائمة) والجديدة (كائن مع وسم معادلة)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except Exception:
            raw = []
    if isinstance(raw, list):
        return raw, False, None
    if isinstance(raw, dict):
        grades = raw.get("grades") if isinstance(raw.get("grades"), list) else []
        transfer = raw.get("transfer") if isinstance(raw.get("transfer"), dict) else None
        return grades, bool(raw.get("is_equated_semester") or raw.get("is_equated")), transfer
    return [], False, None


def _row_to_dict(row) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        d = {k: row[k] for k in row.keys()}
    else:
        # positional fallback — callers should use named queries
        d = {}
    return d


def _fetch_request(conn, req_id: int) -> dict[str, Any] | None:
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT id, student_id, semester, payload_json, status, reason, hod_note,
               submitted_by, instructor_id, department_id,
               created_at, submitted_at, reviewed_at, reviewed_by
        FROM transcript_correction_requests
        WHERE id = ?
        LIMIT 1
        """,
        (req_id,),
    ).fetchone()
    if not row:
        return None
    if hasattr(row, "keys"):
        d = {k: row[k] for k in row.keys()}
    else:
        keys = [
            "id", "student_id", "semester", "payload_json", "status", "reason", "hod_note",
            "submitted_by", "instructor_id", "department_id",
            "created_at", "submitted_at", "reviewed_at", "reviewed_by",
        ]
        d = dict(zip(keys, row))
    try:
        d["grades"], d["is_equated_semester"], d["transfer"] = _parse_correction_payload(
            d.get("payload_json") or "[]"
        )
    except Exception:
        d["grades"] = []
        d["is_equated_semester"] = False
        d["transfer"] = None
    return d


@transcript_corrections_bp.route("/transcript_corrections/meta", methods=["GET"])
@login_required
def transcript_corrections_meta():
    with get_connection() as conn:
        n, y = get_current_term(conn=conn)
        label = f"{(n or '').strip()} {(y or '').strip()}".strip()
    return jsonify({"status": "ok", "current_term": label}), 200


@transcript_corrections_bp.route("/courses_for_student", methods=["GET"])
@login_required
def courses_for_student():
    """
    مقررات قابلة للإدخال في كشف طالب محدد:
    قسم الطالب + الاتجاه العام + المشترك — بدون مقررات أقسام أخرى.
    """
    sid = str(request.args.get("student_id") or "").strip()
    if not sid:
        return jsonify({"status": "error", "message": "student_id مطلوب"}), 400

    role = (_session_role() or "").strip()
    is_sup = _is_supervisor_actor()
    can_manage = role in ("admin", "admin_main", "head_of_department")
    if not is_sup and not can_manage:
        return jsonify({"status": "error", "message": "غير مصرح"}), 403

    with get_connection() as conn:
        try:
            if is_sup and not can_manage:
                iid = _session_instructor_id()
                if not iid:
                    return jsonify({"status": "error", "message": "رقم عضو هيئة التدريس غير مرتبط بالحساب"}), 403
                _assert_advisee(conn, sid, iid)
            else:
                assert_student_in_actor_scope(conn, sid, _current_user_name())

            dept_id = _student_department_id(conn, sid)
            try:
                cols = fetch_table_columns(conn, "courses")
            except Exception:
                cols = []
            has_archived = "is_archived" in cols
            has_owning = "owning_department_id" in cols
            sel = "SELECT DISTINCT course_name, course_code, units FROM courses WHERE COALESCE(course_name,'') <> ''"
            params: list[Any] = []
            if has_archived:
                sel += " AND COALESCE(is_archived,0) = 0"
            if dept_id is not None and has_owning:
                scope_sql, scope_params = courses_department_scope_filter(conn, int(dept_id))
                sel += scope_sql
                params.extend(scope_params)
            sel += " ORDER BY course_name"
            rows = conn.cursor().execute(sel, tuple(params)).fetchall()
            seen: set[str] = set()
            out: list[dict[str, Any]] = []
            for r in rows or []:
                cname = (r[0] or "").strip() if r else ""
                if not cname:
                    continue
                key = cname.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "course_name": cname,
                        "course_code": (r[1] or "") if r else "",
                        "units": r[2] if r and len(r) > 2 else 0,
                    }
                )
            return jsonify(out), 200
        except PermissionError as e:
            return jsonify({"status": "error", "message": str(e)}), 403
        except Exception as e:
            current_app.logger.exception("courses_for_student failed")
            return jsonify({"status": "error", "message": str(e)}), 500


@transcript_corrections_bp.route("/transcript_corrections", methods=["POST"])
@login_required
def create_transcript_correction():
    """مشرف: إرسال طلب تصحيح كشف لفصل سابق (طلبة مسندون فقط)."""
    if not _is_supervisor_actor():
        return jsonify({"status": "error", "message": "متاح للمشرف الأكاديمي فقط"}), 403
    iid = _session_instructor_id()
    if not iid:
        return jsonify({"status": "error", "message": "رقم عضو هيئة التدريس غير مرتبط بالحساب"}), 403

    data = request.get_json(force=True) or {}
    sid = str(data.get("student_id") or "").strip()
    semester = str(data.get("semester") or "").strip()
    reason_raw = data.get("reason")
    is_equated = bool(data.get("is_equated_semester") or data.get("is_equated"))
    transfer = data.get("transfer") if isinstance(data.get("transfer"), dict) else None
    try:
        grades = _normalize_grades_payload(data.get("grades") or [])
        reason = _require_post_publish_reason(reason_raw, required=True)
        if is_equated:
            for g in grades:
                g["is_equated"] = True
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    if not sid or not semester:
        return jsonify({"status": "error", "message": "student_id و semester مطلوبة"}), 400

    with get_connection() as conn:
        try:
            _ensure_table(conn)
            _assert_advisee(conn, sid, iid)
            _assert_previous_term(conn, semester)
            dept_id = _student_department_id(conn, sid)
            actor = _current_user_name()
            now = _now_iso()
            payload = json.dumps(
                {
                    "grades": grades,
                    "is_equated_semester": is_equated,
                    "transfer": transfer,
                },
                ensure_ascii=False,
            )
            cur = conn.cursor()
            # إلغاء طلب معلق سابق لنفس الطالب/الفصل من نفس المشرف
            cur.execute(
                """
                UPDATE transcript_correction_requests
                SET status = 'rejected', hod_note = ?, reviewed_at = ?, reviewed_by = ?
                WHERE student_id = ? AND semester = ? AND instructor_id = ? AND status = 'pending'
                """,
                ("استُبدل بطلب أحدث من المشرف", now, actor, sid, semester, iid),
            )
            if is_postgresql():
                row_ins = cur.execute(
                    """
                    INSERT INTO transcript_correction_requests (
                        student_id, semester, payload_json, status, reason,
                        submitted_by, instructor_id, department_id,
                        created_at, submitted_at
                    ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (sid, semester, payload, reason, actor, iid, dept_id, now, now),
                ).fetchone()
                req_id = int(row_ins[0]) if row_ins else None
            else:
                cur.execute(
                    """
                    INSERT INTO transcript_correction_requests (
                        student_id, semester, payload_json, status, reason,
                        submitted_by, instructor_id, department_id,
                        created_at, submitted_at
                    ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
                    """,
                    (sid, semester, payload, reason, actor, iid, dept_id, now, now),
                )
                req_id = int(cur.lastrowid or 0) or None
            conn.commit()
            try:
                notify_department_hods(
                    conn,
                    dept_id,
                    title="طلب تصحيح كشف درجات",
                    body=f"المشرف {actor} أرسل تصحيحاً للطالب {sid} — فصل {semester}",
                )
            except Exception:
                current_app.logger.exception("notify hods for transcript correction failed")
            try:
                log_activity(
                    action="transcript_correction_submit",
                    details=f"id={req_id}; student_id={sid}; semester={semester}",
                )
            except Exception:
                pass
            return jsonify(
                {
                    "status": "ok",
                    "message": "تم إرسال طلب التصحيح لاعتماد رئيس القسم",
                    "id": req_id,
                }
            ), 200
        except PermissionError as e:
            conn.rollback()
            return jsonify({"status": "error", "message": str(e)}), 403
        except ValueError as e:
            conn.rollback()
            return jsonify({"status": "error", "message": str(e)}), 400
        except Exception as e:
            conn.rollback()
            current_app.logger.exception("create_transcript_correction failed")
            return jsonify({"status": "error", "message": str(e)}), 500


@transcript_corrections_bp.route("/transcript_corrections", methods=["GET"])
@login_required
def list_transcript_corrections():
    """قائمة الطلبات: مشرف (طلباته) أو رئيس قسم (قسمه)."""
    status = (request.args.get("status") or "pending").strip().lower()
    if status not in ("pending", "approved", "rejected", "all"):
        status = "pending"
    role = _session_role()
    iid = _session_instructor_id()
    actor = _current_user_name()

    with get_connection() as conn:
        try:
            _ensure_table(conn)
            cur = conn.cursor()
            params: list[Any] = []
            where = ["1=1"]
            if status != "all":
                where.append("status = ?")
                params.append(status)

            if role == "head_of_department":
                from backend.core.department_scope_policy import resolve_users_list_scope

                mode, dep_id = resolve_users_list_scope(conn, actor)
                if mode == "empty" or (mode != "none" and dep_id is None):
                    return jsonify({"status": "ok", "items": []}), 200
                if mode != "none" and dep_id is not None:
                    where.append("(department_id = ? OR department_id IS NULL)")
                    params.append(int(dep_id))
            elif _is_supervisor_actor() and iid:
                where.append("instructor_id = ?")
                params.append(int(iid))
            elif role in ("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean"):
                pass
            else:
                return jsonify({"status": "error", "message": "غير مصرح"}), 403

            sql = (
                "SELECT id, student_id, semester, payload_json, status, reason, hod_note, "
                "submitted_by, instructor_id, department_id, created_at, submitted_at, "
                "reviewed_at, reviewed_by "
                "FROM transcript_correction_requests WHERE "
                + " AND ".join(where)
                + " ORDER BY COALESCE(submitted_at, created_at) DESC, id DESC LIMIT 200"
            )
            rows = cur.execute(sql, tuple(params)).fetchall()
            items = []
            for row in rows:
                if hasattr(row, "keys"):
                    d = {k: row[k] for k in row.keys()}
                else:
                    keys = [
                        "id", "student_id", "semester", "payload_json", "status", "reason", "hod_note",
                        "submitted_by", "instructor_id", "department_id",
                        "created_at", "submitted_at", "reviewed_at", "reviewed_by",
                    ]
                    d = dict(zip(keys, row))
                if role == "head_of_department" and d.get("department_id") is None:
                    try:
                        assert_student_in_actor_scope(conn, str(d.get("student_id") or ""), actor)
                    except Exception:
                        continue
                try:
                    d["grades"] = json.loads(d.get("payload_json") or "[]")
                except Exception:
                    d["grades"] = []
                d.pop("payload_json", None)
                items.append(d)
            return jsonify({"status": "ok", "items": items}), 200
        except Exception as e:
            current_app.logger.exception("list_transcript_corrections failed")
            return jsonify({"status": "error", "message": f"تعذر تحميل الطلبات: {e}"}), 500


@transcript_corrections_bp.route("/transcript_corrections/<int:req_id>/approve", methods=["POST"])
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def approve_transcript_correction(req_id: int):
    actor = _current_user_name()
    with get_connection() as conn:
        try:
            _ensure_table(conn)
            req = _fetch_request(conn, req_id)
            if not req:
                return jsonify({"status": "error", "message": "الطلب غير موجود"}), 404
            if (req.get("status") or "") != "pending":
                return jsonify({"status": "error", "message": "الطلب ليس معلقاً"}), 400
            sid = str(req.get("student_id") or "").strip()
            semester = str(req.get("semester") or "").strip()
            if _session_role() == "head_of_department":
                assert_student_in_actor_scope(conn, sid, actor)
            grades = req.get("grades") or []
            reason = (req.get("reason") or "").strip()
            changed_by = _audit_changed_by(
                reason=f"اعتماد طلب#{req_id}: {reason}"[:400],
                kind="transcript_correction",
            )
            n = apply_grades_batch(
                conn,
                sid,
                semester,
                grades,
                changed_by,
                is_equated=bool(req.get("is_equated_semester")),
                transfer=req.get("transfer") if isinstance(req.get("transfer"), dict) else None,
            )
            now = _now_iso()
            conn.cursor().execute(
                """
                UPDATE transcript_correction_requests
                SET status = 'approved', reviewed_at = ?, reviewed_by = ?, hod_note = COALESCE(hod_note, '')
                WHERE id = ?
                """,
                (now, actor, req_id),
            )
            conn.commit()
            try:
                notify_instructor(
                    conn,
                    req.get("instructor_id"),
                    title="اعتماد تصحيح كشف درجات",
                    body=f"اعتمد رئيس القسم طلبك للطالب {sid} — فصل {semester}",
                )
            except Exception:
                pass
            try:
                log_activity(
                    action="transcript_correction_approve",
                    details=f"id={req_id}; student_id={sid}; count={n}",
                )
            except Exception:
                pass
            return jsonify({"status": "ok", "message": f"تم الاعتماد وتطبيق {n} سجل", "applied": n}), 200
        except Exception as e:
            conn.rollback()
            current_app.logger.exception("approve_transcript_correction failed")
            msg = str(e)
            code = 403 if "نطاق" in msg or "scope" in msg.lower() or "غير" in msg[:20] else 400
            return jsonify({"status": "error", "message": msg}), 400 if code == 400 else code


@transcript_corrections_bp.route("/transcript_corrections/<int:req_id>/reject", methods=["POST"])
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def reject_transcript_correction(req_id: int):
    actor = _current_user_name()
    data = request.get_json(force=True) or {}
    note = (data.get("hod_note") or data.get("reason") or "").strip()
    if len(note) < 3:
        return jsonify({"status": "error", "message": "ملاحظة الرفض مطلوبة"}), 400
    with get_connection() as conn:
        try:
            _ensure_table(conn)
            req = _fetch_request(conn, req_id)
            if not req:
                return jsonify({"status": "error", "message": "الطلب غير موجود"}), 404
            if (req.get("status") or "") != "pending":
                return jsonify({"status": "error", "message": "الطلب ليس معلقاً"}), 400
            sid = str(req.get("student_id") or "").strip()
            if _session_role() == "head_of_department":
                assert_student_in_actor_scope(conn, sid, actor)
            now = _now_iso()
            conn.cursor().execute(
                """
                UPDATE transcript_correction_requests
                SET status = 'rejected', hod_note = ?, reviewed_at = ?, reviewed_by = ?
                WHERE id = ?
                """,
                (note, now, actor, req_id),
            )
            conn.commit()
            try:
                notify_instructor(
                    conn,
                    req.get("instructor_id"),
                    title="رفض تصحيح كشف درجات",
                    body=f"رُفض طلب الطالب {sid} — {note}",
                )
            except Exception:
                pass
            return jsonify({"status": "ok", "message": "تم رفض الطلب"}), 200
        except Exception as e:
            conn.rollback()
            return jsonify({"status": "error", "message": str(e)}), 400


# أيضاً متاح عبر grades_bp aliases إن لزم — التسجيل من app.py على /grades
