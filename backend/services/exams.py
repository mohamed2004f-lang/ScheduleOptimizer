from flask import Blueprint, request, jsonify, send_file, session, render_template
from backend.core.auth import login_required, role_required, SESSION_ACTIVE_MODE, _normalize_role
from backend.core import department_scope_policy as dept_scope_policy
from backend.core.department_scope_policy import resolve_effective_department_scope_id

from backend.services.coverage_insights import (
    classify_registration_exam_gaps,
    normalize_coverage_course_key,
    registered_distinct_course_names,
    registration_course_student_counts,
    schedule_course_primary_assignments,
    schedule_distinct_course_names_for_coverage,
)
from backend.database.database import is_postgresql, fetch_table_columns
from .utilities import (
    get_connection,
    excel_response_from_df,
    pdf_response_from_html,
    log_activity,
    SEMESTER_LABEL,
    get_current_term,
    get_exam_schedule_published_at,
    set_exam_schedule_published_at,
    get_exam_schedule_updated_at,
    touch_exam_schedule_updated_at,
)
import json
import logging
from datetime import datetime

exams_bp = Blueprint("exams", __name__)
logger = logging.getLogger(__name__)

VALID_TYPES = {"midterm", "final"}


def _course_names_agg_sql(expr: str = "e.course_name") -> str:
    """Cross-db aggregation for comma-separated course names."""
    if is_postgresql():
        return f"STRING_AGG({expr}, ',')"
    return f"GROUP_CONCAT({expr})"


def _should_snapshot_exam_export():
    role = (session.get("user_role") or "").strip()
    return role in ("admin", "admin_main", "head_of_department")


def _ensure_exam_schedule_version_tables(cur):
    if is_postgresql():
        return
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS exam_schedule_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_type TEXT NOT NULL CHECK (exam_type IN ('midterm', 'final')),
            semester TEXT NOT NULL,
            version_no INTEGER NOT NULL DEFAULT 1,
            snapshot_json TEXT DEFAULT '',
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            generated_by TEXT DEFAULT '',
            note TEXT DEFAULT '',
            is_published INTEGER NOT NULL DEFAULT 0,
            UNIQUE (exam_type, semester, version_no)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS exam_schedule_version_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_schedule_version_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            event_time TEXT DEFAULT CURRENT_TIMESTAMP,
            actor TEXT DEFAULT '',
            details TEXT DEFAULT ''
        )
        """
    )
    try:
        cur.execute(
            "ALTER TABLE exam_schedule_versions ADD COLUMN is_published INTEGER NOT NULL DEFAULT 0"
        )
    except Exception:
        pass


def _role_may_edit_exam_schedule():
    role = _normalize_role((session.get("user_role") or "").strip())
    if role in ("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean"):
        return True
    if role == "head_of_department":
        mode = (session.get(SESSION_ACTIVE_MODE) or "head").strip().lower()
        return mode in ("", "head", "hod", "department_head")
    return False


def _effective_department_scope_id(conn) -> int | None:
    uname = (session.get("user") or session.get("username") or "").strip()
    return resolve_effective_department_scope_id(conn, uname)


def _course_in_scope(conn, course_name: str) -> bool:
    """
    مقرر ضمن نطاق محرّر الجدول:
    - بلا نطاق قسم → الكل
    - مملوك للقسم، أو عليه تسجيل نشط ضمن نطاق القسم، أو في الكتالوج المشترك/العام المرتبط بالقسم
    """
    dep = _effective_department_scope_id(conn)
    if dep is None:
        return True
    cname = (course_name or "").strip()
    if not cname:
        return False
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT 1
        FROM courses
        WHERE lower(trim(course_name)) = lower(trim(?))
          AND COALESCE(owning_department_id,-1) = ?
        LIMIT 1
        """,
        (cname, int(dep)),
    ).fetchone()
    if row:
        return True
    if dept_scope_policy.course_is_college_shared_catalog(conn, cname, department_id=int(dep)):
        return True
    if dept_scope_policy.course_is_college_general(conn, cname):
        actor_u = (session.get("user") or session.get("username") or "").strip()
        registered = registered_distinct_course_names(cur, conn, actor_username=actor_u)
        reg_keys = {_norm_exam_course_key(n) for n in registered if _norm_exam_course_key(n)}
        return _norm_exam_course_key(cname) in reg_keys
    actor_u = (session.get("user") or session.get("username") or "").strip()
    registered = registered_distinct_course_names(cur, conn, actor_username=actor_u)
    reg_keys = {_norm_exam_course_key(n) for n in registered if _norm_exam_course_key(n)}
    return _norm_exam_course_key(cname) in reg_keys


def _dept_visible_exam_course_keys(conn, cur, *, dep_id: int) -> set[str]:
    """مفاتيح مقررات يظهر امتحانها لرئيس القسم: ملكية القسم + مقررات عليها تسجيل في النطاق."""
    owned: set[str] = set()
    try:
        rows = cur.execute(
            """
            SELECT course_name FROM courses
            WHERE COALESCE(owning_department_id, -1) = ?
            """,
            (int(dep_id),),
        ).fetchall()
        for r in rows or []:
            k = _norm_exam_course_key(r[0] if not hasattr(r, "keys") else r["course_name"])
            if k:
                owned.add(k)
    except Exception:
        pass
    actor_u = (session.get("user") or session.get("username") or "").strip()
    registered = registered_distinct_course_names(cur, conn, actor_username=actor_u)
    reg_keys = {_norm_exam_course_key(n) for n in registered if _norm_exam_course_key(n)}
    return owned | reg_keys


def _fetch_scoped_exam_rows(conn, cur, exam_type: str, *, dep_id: int | None):
    """صفوف امتحانات للنوع؛ عند نطاق القسم تشمل الملكية + مقررات التسجيل في القسم."""
    if dep_id is None:
        return cur.execute(
            """
            SELECT id AS exam_id, COALESCE(course_name,'') AS course_name,
                   COALESCE(exam_date,'') AS exam_date
            FROM exams WHERE exam_type = ?
            ORDER BY exam_date, course_name, id
            """,
            (exam_type,),
        ).fetchall()
    visible = _dept_visible_exam_course_keys(conn, cur, dep_id=int(dep_id))
    rows = cur.execute(
        """
        SELECT id AS exam_id, COALESCE(course_name,'') AS course_name,
               COALESCE(exam_date,'') AS exam_date
        FROM exams WHERE exam_type = ?
        ORDER BY exam_date, course_name, id
        """,
        (exam_type,),
    ).fetchall()
    out = []
    for r in rows or []:
        cname = r[1] if not hasattr(r, "keys") else r["course_name"]
        if _norm_exam_course_key(cname) in visible:
            out.append(r)
    return out


def _exam_has_any_rows(conn, exam_type: str) -> bool:
    cur = conn.cursor()
    row = cur.execute(
        "SELECT 1 FROM exams WHERE exam_type = ? LIMIT 1",
        (exam_type,),
    ).fetchone()
    return bool(row)


def _is_educational_viewer_role() -> bool:
    """طالب / أستاذ / مشرف / رئيس قسم في وضع التدريس أو الإشراف."""
    role = _normalize_role((session.get("user_role") or "").strip())
    if role in ("student", "instructor", "supervisor"):
        return True
    if role == "head_of_department":
        mode = (session.get(SESSION_ACTIVE_MODE) or "head").strip().lower()
        return mode in ("instructor", "supervisor")
    return False


def _user_can_view_exam_rows(exam_type: str) -> bool:
    """
    من يمكنه رؤية جدول الامتحانات:
    - محرّرو الجدول (إدارة / رئيس قسم في وضع الرئيس) دائماً.
    - باقي الأدوار: بعد «اعتماد/نشر»، أو (للأدوار التعليمية) عند وجود صفوف فعلية.
    """
    if _role_may_edit_exam_schedule():
        return True
    with get_connection() as conn:
        if get_exam_schedule_published_at(exam_type, conn=conn) is not None:
            return True
        if _is_educational_viewer_role() and _exam_has_any_rows(conn, exam_type):
            return True
    return False


def _user_can_view_exam_coverage(exam_type: str) -> bool:
    """مقارنة التسجيل/الجدولة الدراسية — للإدارة ورئيس القسم (وضع الرئيس) فقط."""
    return _role_may_edit_exam_schedule()


def _empty_schedule_coverage_payload(exam_type: str, *, coverage_available: bool = False) -> dict:
    return {
        "exam_type": exam_type,
        "coverage_available": coverage_available,
        "term_label": "",
        "schedule_scope": "",
        "schedule_scope_ar": "",
        "duplicate_courses": [],
        "missing_from_exams": [],
        "extras_in_exams_not_in_schedule": [],
        "registration_baseline": {
            "missing_in_exam": [],
            "missing_required": [],
            "missing_optional_shared": [],
            "missing_exempt": [],
            "extra_in_exam": [],
        },
        "counts": {},
    }


def _create_exam_schedule_version(
    conn, exam_type: str, event_type: str, note: str = "", is_published: bool = False
):
    if exam_type not in VALID_TYPES:
        return None
    cur = conn.cursor()
    _ensure_exam_schedule_version_tables(cur)
    try:
        tname, tyear = get_current_term(conn=conn)
        semester = f"{(tname or '').strip()} {(tyear or '').strip()}".strip() or SEMESTER_LABEL
    except Exception:
        semester = SEMESTER_LABEL

    rows = cur.execute(
        """
        SELECT id, COALESCE(course_name,''), COALESCE(exam_date,''), COALESCE(exam_time,''),
               COALESCE(room,''), COALESCE(instructor,''), exam_id
        FROM exams
        WHERE exam_type = ?
        ORDER BY exam_date, exam_time, course_name, id
        """,
        (exam_type,),
    ).fetchall()
    items = []
    for r in rows:
        items.append(
            {
                "exam_id": int(r[0]),
                "course_name": r[1],
                "exam_date": r[2],
                "exam_time": r[3],
                "room": r[4],
                "instructor": r[5],
                "legacy_exam_id": r[6],
            }
        )

    actor = (session.get("user") or session.get("username") or "").strip() or "system"
    now = datetime.utcnow().isoformat()
    max_row = cur.execute(
        "SELECT COALESCE(MAX(version_no),0) FROM exam_schedule_versions WHERE exam_type = ? AND semester = ?",
        (exam_type, semester),
    ).fetchone()
    version_no = int((max_row[0] if max_row and max_row[0] is not None else 0) or 0) + 1
    snapshot = {
        "exam_type": exam_type,
        "semester": semester,
        "captured_at": now,
        "captured_by": actor,
        "row_count": len(items),
        "rows": items,
    }
    if is_postgresql():
        row_new = cur.execute(
            """
            INSERT INTO exam_schedule_versions
            (exam_type, semester, version_no, snapshot_json, generated_at, generated_by, note, is_published)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                exam_type,
                semester,
                version_no,
                json.dumps(snapshot, ensure_ascii=False),
                now,
                actor,
                (note or ""),
                1 if is_published else 0,
            ),
        ).fetchone()
        ver_id = int(row_new[0]) if row_new else 0
    else:
        cur.execute(
            """
            INSERT INTO exam_schedule_versions
            (exam_type, semester, version_no, snapshot_json, generated_at, generated_by, note, is_published)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exam_type,
                semester,
                version_no,
                json.dumps(snapshot, ensure_ascii=False),
                now,
                actor,
                (note or ""),
                1 if is_published else 0,
            ),
        )
        ver_id = int(cur.lastrowid or 0)
    cur.execute(
        """
        INSERT INTO exam_schedule_version_events
        (exam_schedule_version_id, event_type, event_time, actor, details)
        VALUES (?, ?, ?, ?, ?)
        """,
        (ver_id, (event_type or "manual"), now, actor, (note or "")),
    )
    conn.commit()
    return {
        "id": ver_id,
        "exam_type": exam_type,
        "semester": semester,
        "version_no": version_no,
        "generated_at": now,
        "is_published": bool(is_published),
    }


@exams_bp.route("/versions")
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def exam_schedule_versions_list():
    semester = (request.args.get("semester") or "").strip()
    exam_type = (request.args.get("exam_type") or "").strip()
    event_type = (request.args.get("event_type") or "").strip()
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            _ensure_exam_schedule_version_tables(cur)
            where = []
            params = []
            if semester:
                where.append("v.semester = ?")
                params.append(semester)
            if exam_type in VALID_TYPES:
                where.append("v.exam_type = ?")
                params.append(exam_type)
            if event_type:
                where.append("e.event_type = ?")
                params.append(event_type)
            wsql = ("WHERE " + " AND ".join(where)) if where else ""
            rows = cur.execute(
                f"""
                SELECT v.id, v.exam_type, v.semester, v.version_no, v.generated_at, v.generated_by, v.note,
                       v.is_published, e.event_type, e.event_time
                FROM exam_schedule_versions v
                LEFT JOIN exam_schedule_version_events e ON e.exam_schedule_version_id = v.id
                {wsql}
                ORDER BY v.generated_at DESC, v.id DESC
                """,
                params,
            ).fetchall()
            items = []
            for r in rows:
                items.append(
                    {
                        "id": int(r[0]),
                        "exam_type": r[1] or "",
                        "semester": r[2] or "",
                        "version_no": int(r[3] or 0),
                        "generated_at": r[4] or "",
                        "generated_by": r[5] or "",
                        "note": r[6] or "",
                        "is_published": bool(int(r[7] or 0)),
                        "event_type": r[8] or "",
                        "event_time": r[9] or "",
                    }
                )
            return jsonify({"status": "ok", "items": items})
    except Exception:
        logger.exception("exam_schedule_versions list failed")
        return jsonify({"status": "error", "message": "فشل تحميل أرشيف جداول الامتحانات"}), 500


@exams_bp.route("/versions/<int:version_id>")
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def exam_schedule_version_detail(version_id: int):
    download = str(request.args.get("download") or "").lower() in ("1", "true", "yes")
    format_json = str(request.args.get("format") or "").lower() == "json"
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            _ensure_exam_schedule_version_tables(cur)
            row = cur.execute(
                """
                SELECT id, exam_type, semester, version_no, snapshot_json, generated_at, generated_by, note, is_published
                FROM exam_schedule_versions
                WHERE id = ?
                LIMIT 1
                """,
                (int(version_id),),
            ).fetchone()
            if not row:
                return jsonify({"status": "error", "message": "النسخة غير موجودة"}), 404
            payload = {
                "id": int(row[0]),
                "exam_type": row[1] or "",
                "semester": row[2] or "",
                "version_no": int(row[3] or 0),
                "generated_at": row[5] or "",
                "generated_by": row[6] or "",
                "note": row[7] or "",
                "is_published": bool(int(row[8] or 0)),
                "snapshot": json.loads(row[4] or "{}"),
            }
            if download or format_json:
                return jsonify(payload)
            snap = payload["snapshot"] if isinstance(payload["snapshot"], dict) else {}
            rows = snap.get("rows") if isinstance(snap.get("rows"), list) else []
            payload["row_count"] = int(snap.get("row_count") or len(rows))
            return render_template(
                "exam_version_preview.html",
                item=payload,
                exam_rows=rows,
            )
    except Exception:
        logger.exception("exam_schedule_version_detail failed")
        return jsonify({"status": "error", "message": "فشل قراءة نسخة جدول الامتحانات"}), 500


@exams_bp.route("/versions/<int:version_id>/restore_draft", methods=["POST"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def exam_schedule_version_restore_draft(version_id: int):
    exam_type = ""
    semester = ""
    version_no = 0
    restored = 0
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            _ensure_exam_schedule_version_tables(cur)
            row = cur.execute(
                "SELECT exam_type, semester, version_no, snapshot_json FROM exam_schedule_versions WHERE id = ? LIMIT 1",
                (int(version_id),),
            ).fetchone()
            if not row:
                return jsonify({"status": "error", "message": "النسخة غير موجودة"}), 404

            exam_type = row[0] or ""
            semester = row[1] or ""
            version_no = int(row[2] or 0)
            if exam_type not in VALID_TYPES:
                return jsonify({"status": "error", "message": "نوع امتحان غير صالح"}), 400
            try:
                snap = json.loads(row[3] or "{}")
            except Exception:
                snap = {}
            rows = snap.get("rows") if isinstance(snap, dict) else []
            if not isinstance(rows, list):
                rows = []

            dep_r = _effective_department_scope_id(conn)
            dept_scoped_r = dep_r is not None
            _delete_exams_for_type_respecting_scope(
                cur, exam_type, int(dep_r) if dept_scoped_r else None, dept_scoped_r
            )
            restored = 0
            for it in rows:
                if not isinstance(it, dict):
                    continue
                course_name = (it.get("course_name") or "").strip()
                if not course_name:
                    continue
                if not _course_in_scope(conn, course_name):
                    continue
                exam_date = (it.get("exam_date") or "").strip()
                exam_time = (it.get("exam_time") or "").strip()
                room = (it.get("room") or "").strip()
                instructor = (it.get("instructor") or "").strip()
                leg_id = it.get("legacy_exam_id")
                cur.execute(
                    """
                    INSERT INTO exams (exam_type, exam_id, course_name, exam_date, exam_time, room, instructor)
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    (exam_type, leg_id, course_name, exam_date, exam_time, room, instructor),
                )
                restored += 1

            conn.commit()

        try:
            touch_exam_schedule_updated_at(exam_type)
        except Exception:
            pass

        try:
            persist_exam_conflicts(exam_type)
        except Exception:
            logger.exception("persist_exam_conflicts after exam restore")

        try:
            with get_connection() as conn2:
                _create_exam_schedule_version(
                    conn2,
                    exam_type,
                    "restore_draft",
                    note=f"restored from version_id={int(version_id)} (v{version_no})",
                )
        except Exception:
            logger.exception("failed to log exam restore_draft version event")

        try:
            log_activity(
                action="exam_schedule_restore_draft",
                details=f"version_id={int(version_id)}, exam_type={exam_type}, version_no={version_no}, restored_rows={restored}",
            )
        except Exception:
            pass

        return jsonify(
            {
                "status": "ok",
                "message": f"تمت استعادة نسخة #{version_no} ({exam_type}) كمسودة حالية ({restored} صف).",
                "restored_rows": restored,
                "version_no": version_no,
                "semester": semester,
                "exam_type": exam_type,
            }
        )
    except Exception:
        logger.exception("exam_schedule_version_restore_draft failed")
        return jsonify({"status": "error", "message": "فشل استعادة نسخة جدول الامتحانات"}), 500


@exams_bp.route("/<exam_type>/publish_status")
@login_required
def exam_schedule_publish_status(exam_type):
    if exam_type not in VALID_TYPES:
        return jsonify({"status": "error", "message": "invalid exam type"}), 400
    with get_connection() as conn:
        published_at = get_exam_schedule_published_at(exam_type, conn=conn)
        updated_at = get_exam_schedule_updated_at(exam_type, conn=conn)
    changed_since_publish = False
    if published_at and updated_at:
        changed_since_publish = updated_at > published_at
    return jsonify(
        {
            "status": "ok",
            "published": published_at is not None,
            "published_at": published_at,
            "updated_at": updated_at,
            "changed_since_publish": changed_since_publish,
        }
    )


@exams_bp.route("/<exam_type>/publish", methods=["POST"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def exam_schedule_publish(exam_type):
    if exam_type not in VALID_TYPES:
        return jsonify({"status": "error", "message": "invalid exam type"}), 400
    ver = None
    try:
        with get_connection() as conn:
            published_at = set_exam_schedule_published_at(exam_type, conn=conn)
            try:
                touch_exam_schedule_updated_at(exam_type, conn=conn)
            except Exception:
                logger.exception("touch exam updated at on publish")
            try:
                ver = _create_exam_schedule_version(
                    conn,
                    exam_type,
                    "publish",
                    note="exam schedule published",
                    is_published=True,
                )
            except Exception:
                logger.exception("failed to create exam schedule version on publish")
        try:
            log_activity(
                action="exam_schedule_publish",
                details=f"exam_type={exam_type}, published_at={published_at}",
            )
        except Exception:
            pass
        out = {
            "status": "ok",
            "message": "تم اعتماد ونشر جدول الامتحانات",
            "published_at": published_at,
        }
        if ver:
            out["version"] = {
                "id": ver.get("id"),
                "version_no": ver.get("version_no"),
                "semester": ver.get("semester"),
            }
        return jsonify(out), 200
    except Exception as e:
        logger.exception("exam_schedule_publish failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


def normalize_dates(dates):
    # expect list of date strings, normalize to ISO YYYY-MM-DD
    out = []
    for d in dates:
        if not d:
            continue
        try:
            dt = datetime.fromisoformat(d) if 'T' in d else datetime.strptime(d, "%Y-%m-%d")
            out.append(dt.date().isoformat())
        except Exception:
            # try common formats
            try:
                dt = datetime.strptime(d, "%d/%m/%Y")
                out.append(dt.date().isoformat())
            except Exception:
                continue
    return sorted(list(dict.fromkeys(out)))


def _norm_exam_course_key(name: str) -> str:
    return normalize_coverage_course_key(name)


def _delete_exams_for_type_respecting_scope(cur, exam_type: str, dep_id: int | None, dept_scoped: bool) -> None:
    """يحذف صفوف الامتحانات: كلياً لغير المنطقي، أو مقررات القسم فقط عند نطاق القسم."""
    if not dept_scoped or dep_id is None:
        cur.execute("DELETE FROM exams WHERE exam_type = ?", (exam_type,))
        return
    cur.execute(
        """
        DELETE FROM exams
        WHERE exam_type = ?
          AND EXISTS (
              SELECT 1 FROM courses c
              WHERE lower(trim(c.course_name)) = lower(trim(exams.course_name))
                AND COALESCE(c.owning_department_id, -1) = ?
          )
        """,
        (exam_type, int(dep_id)),
    )


def _fetch_exam_conflict_aggregate_rows(conn, exam_type: str):
    """
    مجموعات تعارض (طالب يوم واحد أكثر من امتحان): ضمن مقررات قسم المنطقي وطلاب المنطقي.
    """
    cur = conn.cursor()
    dep = _effective_department_scope_id(conn)
    dept_scoped = dep is not None
    uname = (session.get("user") or session.get("username") or "").strip()
    scope_sql, scope_params = dept_scope_policy.resolve_scope_sql_for_aliased_student(conn, uname, "st")
    if scope_sql == "1=0":
        return []

    dept_join = ""
    prefix_params: tuple = ()
    if dept_scoped and dep is not None:
        dept_join = """
            INNER JOIN courses __c_dep
              ON lower(trim(__c_dep.course_name)) = lower(trim(e.course_name))
             AND COALESCE(__c_dep.owning_department_id, -1) = ?
        """
        prefix_params = (int(dep),)

    stu_join = ""
    scope_where = ""
    scope_params_suffix: tuple = ()
    if scope_sql:
        stu_join = " INNER JOIN students st ON st.student_id = r.student_id "
        scope_where = f" AND ({scope_sql}) "
        scope_params_suffix = tuple(scope_params) if scope_params else ()

    q = f"""
        SELECT r.student_id AS student_id, e.exam_date AS exam_date,
               {_course_names_agg_sql("e.course_name")} AS conflicting_courses,
               COUNT(e.course_name) AS ccount
        FROM exams e
        {dept_join}
        JOIN registrations r ON LOWER(TRIM(r.course_name)) = LOWER(TRIM(e.course_name))
        {stu_join}
        WHERE e.exam_type = ?
        {scope_where}
        GROUP BY r.student_id, e.exam_date
        HAVING COUNT(e.course_name) > 1
    """
    params = prefix_params + (exam_type,) + scope_params_suffix
    return cur.execute(q, params).fetchall()


def _exam_dicts_for_export_or_results(conn, exam_type: str) -> list[dict]:
    """صفوف جدول exams حسب نطاق القسم (يتوافق مع list_exam_rows)."""
    cur = conn.cursor()
    dep = _effective_department_scope_id(conn)
    cur.execute(
        "SELECT * FROM exams WHERE exam_type = ? ORDER BY exam_date, exam_time, id",
        (exam_type,),
    )
    rows = cur.fetchall()
    cols = [d[0] for d in (cur.description or [])]
    visible: set[str] | None = None
    if dep is not None:
        visible = _dept_visible_exam_course_keys(conn, cur, dep_id=int(dep))
    out: list[dict] = []
    for r in rows or []:
        if hasattr(r, "keys"):
            item = dict(r)
        else:
            item = dict(zip(cols, r))
        if visible is not None:
            if _norm_exam_course_key(item.get("course_name") or "") not in visible:
                continue
        out.append(item)
    return out


@exams_bp.route('/<exam_type>/schedule_coverage')
@login_required
def exam_schedule_coverage(exam_type):
    """
    لمطابقة جدول المقررات الدراسي مع جدول الامتحانات:
    - مقررات مكررة (نفس الاسم أكثر من مرة؛ وتمييز التكرار في يوم واحد).
    - مقررات في الجدول الدراسي ولا يوجد لها امتحان (جزئي/نهائي حسب النوع).
    - مقررات مسجلة في الامتحانات ولا تظهر ضمن مجموعة الجدول الدراسي المستخدم للمقارنة.
    """
    if exam_type not in VALID_TYPES:
        return jsonify({"error": "invalid exam type"}), 400
    if not _user_can_view_exam_coverage(exam_type):
        with get_connection() as conn:
            tname, tyear = get_current_term(conn=conn)
            term_label = f"{(tname or '').strip()} {(tyear or '').strip()}".strip() or SEMESTER_LABEL
        payload = _empty_schedule_coverage_payload(exam_type, coverage_available=False)
        payload["term_label"] = term_label
        return jsonify(payload)
    if not _user_can_view_exam_rows(exam_type):
        return jsonify(_empty_schedule_coverage_payload(exam_type, coverage_available=False))
    try:
        with get_connection() as conn:
            tname, tyear = get_current_term(conn=conn)
            term_label = f"{(tname or '').strip()} {(tyear or '').strip()}".strip() or SEMESTER_LABEL
            cur = conn.cursor()
            dep = _effective_department_scope_id(conn)
            dept_scoped_user = dep is not None

            schedule_names, scope = schedule_distinct_course_names_for_coverage(
                conn,
                cur,
                term_label,
                dept_scope_id=int(dep) if dept_scoped_user else None,
            )
            actor_u = (session.get("user") or session.get("username") or "").strip()
            sched_keys = {_norm_exam_course_key(n) for n in schedule_names if _norm_exam_course_key(n)}
            registered_names = registered_distinct_course_names(cur, conn, actor_username=actor_u)
            reg_keys = {_norm_exam_course_key(n) for n in registered_names if _norm_exam_course_key(n)}

            rows = _fetch_scoped_exam_rows(
                conn, cur, exam_type, dep_id=int(dep) if dept_scoped_user else None
            )

            by_key: dict[str, list[dict]] = {}
            exam_keys: set[str] = set()
            for r in rows:
                if hasattr(r, "keys"):
                    cid, cname, ed = int(r["exam_id"]), r["course_name"] or "", r["exam_date"] or ""
                else:
                    cid, cname, ed = int(r[0]), r[1] or "", r[2] or ""
                k = _norm_exam_course_key(cname)
                if not k:
                    continue
                exam_keys.add(k)
                by_key.setdefault(k, []).append(
                    {"exam_id": cid, "course_name": cname.strip(), "exam_date": ed}
                )

            duplicate_courses: list[dict] = []
            for k, items in sorted(by_key.items(), key=lambda x: x[0]):
                if len(items) < 2:
                    continue
                dates = sorted({(it.get("exam_date") or "") for it in items})
                seen_per_date: dict[str, int] = {}
                for it in items:
                    d = (it.get("exam_date") or "").strip()
                    if d:
                        seen_per_date[d] = seen_per_date.get(d, 0) + 1
                same_day = any(v > 1 for v in seen_per_date.values())
                display = items[0].get("course_name") or k
                duplicate_courses.append(
                    {
                        "course_key": k,
                        "display_name": display,
                        "row_count": len(items),
                        "dates": dates,
                        "same_day_duplicate": same_day,
                    }
                )

            missing_from_exams = sorted(
                n for n in schedule_names if _norm_exam_course_key(n) and _norm_exam_course_key(n) not in exam_keys
            )
            extras_in_exams = sorted(
                {
                    v[0].get("course_name") or k
                    for k, v in by_key.items()
                    if k and k not in sched_keys
                }
            )
            missing_from_exams_vs_registrations = sorted(
                n
                for n in registered_names
                if _norm_exam_course_key(n) and _norm_exam_course_key(n) not in exam_keys
            )
            classified = classify_registration_exam_gaps(
                conn,
                missing_from_exams_vs_registrations,
                department_id=int(dep) if dept_scoped_user else None,
            )
            missing_required = classified.get("required") or []
            missing_optional = classified.get("optional_shared") or []
            missing_exempt = classified.get("exempt") or []
            extras_in_exams_vs_registrations = sorted(
                {
                    v[0].get("course_name") or k
                    for k, v in by_key.items()
                    if k and k not in reg_keys
                }
            )

            scope_labels = {
                "current_semester_or_blank": "مقررات الجدول الدراسي للفصل الحالي (أو صفوف بلا حقل فصل)",
                "all_schedule": "كل المقررات الظاهرة في جدول المقررات (لم يُعثر على بيانات للفصل الحالي)",
                "all_schedule_scoped": "كل مقررات الجدولة المطابقة للفصل (ضمن مقررات قسم نطاقك)",
                "none": "لا توجد مقررات في جدول schedule",
                "scoped_no_schedule_course_department_columns": "لا يمكن حصر مقررات الجدولة حسب القسم (أعمدة القسم غير متوفرة في الجدولة/المقررات)",
            }
            scope_ar = scope_labels.get(scope, scope)
            if dept_scoped_user:
                if scope == "scoped_no_schedule_course_department_columns":
                    scope_ar = (
                        scope_labels["scoped_no_schedule_course_department_columns"]
                        + " أضف department_id في الجدولة أو owning_department_id في المقررات لقياس الدقة داخل القسم."
                    )
                elif scope_ar:
                    scope_ar = scope_ar + " — الأعداد والقوائم أعلاه تخص مقررات قسم عملك وفق هذا النطاق."

            return jsonify(
                {
                    "exam_type": exam_type,
                    "coverage_available": True,
                    "term_label": term_label,
                    "schedule_scope": scope,
                    "schedule_scope_ar": scope_ar,
                    "duplicate_courses": duplicate_courses,
                    "missing_from_exams": missing_from_exams,
                    "extras_in_exams_not_in_schedule": extras_in_exams,
                    "registration_baseline": {
                        "missing_in_exam": missing_required,
                        "missing_required": missing_required,
                        "missing_optional_shared": missing_optional,
                        "missing_exempt": missing_exempt,
                        "extra_in_exam": extras_in_exams_vs_registrations,
                    },
                    "counts": {
                        "schedule_distinct": len(sched_keys),
                        "registrations_distinct": len(reg_keys),
                        "exam_distinct_courses": len(exam_keys),
                        "exam_rows": sum(len(v) for v in by_key.values()),
                        "required_missing": len(missing_required),
                        "optional_shared_missing": len(missing_optional),
                        "exempt_missing": len(missing_exempt),
                    },
                }
            )
    except Exception as e:
        logger.error("exam_schedule_coverage failed: %s", e, exc_info=True)
        return jsonify({"error": "internal"}), 500


@exams_bp.route('/<exam_type>/rows')
@login_required
def list_exam_rows(exam_type):
    if exam_type not in VALID_TYPES:
        return jsonify([])
    if not _user_can_view_exam_rows(exam_type):
        return jsonify([])
    role = _normalize_role((session.get("user_role") or "").strip())
    with get_connection() as conn:
        cur = conn.cursor()
        if role == "student":
            sid = (session.get("student_id") or session.get("user") or "").strip()
            if not sid:
                return jsonify([])
            rows = cur.execute(
                """
                SELECT e.id AS exam_id, e.course_name, e.exam_date, e.exam_time, e.room, e.instructor
                FROM exams e
                INNER JOIN registrations r
                    ON lower(trim(r.course_name)) = lower(trim(e.course_name))
                WHERE e.exam_type = ? AND r.student_id = ?
                ORDER BY e.exam_date, e.exam_time, e.course_name
                """,
                (exam_type, sid),
            ).fetchall()
            return jsonify([dict(r) for r in rows])
        dep = _effective_department_scope_id(conn)
        if dep is None:
            rows = cur.execute(
                "SELECT id AS exam_id, course_name, exam_date, exam_time, room, instructor FROM exams WHERE exam_type=? ORDER BY exam_date, exam_time",
                (exam_type,),
            ).fetchall()
            return jsonify([dict(r) for r in rows])
        visible = _dept_visible_exam_course_keys(conn, cur, dep_id=int(dep))
        rows = cur.execute(
            """
            SELECT id AS exam_id, course_name, exam_date, exam_time, room, instructor
            FROM exams WHERE exam_type=?
            ORDER BY exam_date, exam_time
            """,
            (exam_type,),
        ).fetchall()
        out = []
        for r in rows or []:
            item = dict(r)
            if _norm_exam_course_key(item.get("course_name") or "") in visible:
                out.append(item)
        return jsonify(out)

@exams_bp.route('/<exam_type>/check_conflicts', methods=['POST'])
@login_required
def check_exam_conflicts(exam_type):
    """
    التحقق من التعارضات قبل إضافة امتحان جديد
    Returns: قائمة بالتعارضات المحتملة
    """
    if exam_type not in VALID_TYPES:
        return jsonify({"status":"error","message":"invalid exam type"}), 400
    
    try:
        data = request.get_json(force=True) or {}
        course_name = data.get('course_name','').strip()
        exam_date = data.get('exam_date','').strip()
        
        if not course_name or not exam_date:
            return jsonify({
                "status": "error",
                "message": "course_name and exam_date required"
            }), 400
        
        # normalize date
        nd = normalize_dates([exam_date])
        if not nd:
            return jsonify({"status":"error","message":"invalid date format"}), 400
        exam_date = nd[0]
        
        # محاكاة إضافة الامتحان مؤقتاً للتحقق من التعارضات
        with get_connection() as conn:
            cur = conn.cursor()
            
            # إضافة مؤقتة للامتحان
            if is_postgresql():
                row_new = cur.execute(
                    "INSERT INTO exams (exam_type, exam_id, course_name, exam_date, exam_time, room, instructor) VALUES (?,?,?,?,?,?,?) RETURNING id",
                    (exam_type, None, course_name, exam_date, data.get('exam_time',''), data.get('room',''), data.get('instructor',''))
                ).fetchone()
                temp_rowid = int(row_new[0]) if row_new else 0
            else:
                cur.execute(
                    "INSERT INTO exams (exam_type, exam_id, course_name, exam_date, exam_time, room, instructor) VALUES (?,?,?,?,?,?,?)",
                    (exam_type, None, course_name, exam_date, data.get('exam_time',''), data.get('room',''), data.get('instructor',''))
                )
                temp_rowid = int(cur.lastrowid or 0)
            
            rows = _fetch_exam_conflict_aggregate_rows(conn, exam_type)
            
            # تصفية التعارضات المتعلقة بالامتحان الجديد
            def _norm_name(v: str) -> str:
                return (v or "").strip().lower()

            relevant_conflicts = []
            target_course = _norm_name(course_name)
            for r in rows:
                courses_raw = r[2] or ""
                parsed = [_norm_name(x) for x in str(courses_raw).split(",") if _norm_name(x)]
                if r[1] == exam_date and target_course in parsed:
                    relevant_conflicts.append({
                        'student_id': r[0] or '',
                        'exam_date': r[1] or '',
                        'conflicting_courses': courses_raw
                    })

            # إرفاق أسماء الطلبة لعرضها في نافذة التعارضات
            try:
                student_ids = sorted({(c.get("student_id") or "").strip() for c in relevant_conflicts if (c.get("student_id") or "").strip()})
                name_map = {}
                if student_ids:
                    rows2 = cur.execute(
                        "SELECT student_id, COALESCE(student_name,'') AS student_name FROM students WHERE student_id IN ({})".format(
                            ",".join("?" for _ in student_ids)
                        ),
                        student_ids,
                    ).fetchall()
                    name_map = {r[0]: (r[1] or "") for r in rows2}
                for c in relevant_conflicts:
                    sid = (c.get("student_id") or "").strip()
                    c["student_name"] = name_map.get(sid, "")
            except Exception:
                pass
            
            # حذف الإضافة المؤقتة
            cur.execute("DELETE FROM exams WHERE id = ?", (temp_rowid,))
            conn.commit()
            
            return jsonify({
                "status": "ok",
                "has_conflicts": len(relevant_conflicts) > 0,
                "conflicts": relevant_conflicts,
                "conflict_count": len(relevant_conflicts)
            }), 200
            
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error checking exam conflicts: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"خطأ في التحقق من التعارضات: {str(e)}"
        }), 500

@exams_bp.route('/<exam_type>/add_row', methods=['POST'])
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def add_exam_row(exam_type):
    if exam_type not in VALID_TYPES:
        return jsonify({"status":"error","message":"invalid exam type"}), 400
    if not _role_may_edit_exam_schedule():
        return jsonify({"status": "error", "message": "غير مصرح", "code": "FORBIDDEN"}), 403
    data = request.get_json(force=True) or {}
    course_name = data.get('course_name','')
    exam_date = data.get('exam_date','')
    exam_time = data.get('exam_time','09:00-12:00')  # الوقت الافتراضي
    room = data.get('room','')
    instructor = data.get('instructor','')
    if not course_name or not exam_date:
        return jsonify({"status":"error","message":"course_name and exam_date required"}), 400
    # normalize date
    nd = normalize_dates([exam_date])
    if not nd:
        return jsonify({"status":"error","message":"invalid date format"}), 400
    exam_date = nd[0]
    with get_connection() as conn:
        if not _course_in_scope(conn, course_name):
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
        try:
            from backend.core.department_scope_policy import resolve_effective_department_scope_id
            from backend.services.term_closure import TermClosedError, assert_term_writable

            actor = (session.get("user") or session.get("username") or "").strip()
            dept_id = resolve_effective_department_scope_id(conn, actor)
            assert_term_writable(conn, stage="exams", department_id=dept_id)
        except TermClosedError as exc:
            return jsonify({"status": "error", "message": str(exc), "code": "term_closed"}), 423
        cur = conn.cursor()
        cur.execute("INSERT INTO exams (exam_type, exam_id, course_name, exam_date, exam_time, room, instructor) VALUES (?,?,?,?,?,?,?)",
                    (exam_type, None, course_name, exam_date, exam_time, room, instructor))
        conn.commit()
    try:
        touch_exam_schedule_updated_at(exam_type)
    except Exception:
        pass
    # تحديث جدول تعارضات الامتحانات
    try:
        persist_exam_conflicts(exam_type)
        log_activity(
            action="add_exam_row",
            details=f"exam_type={exam_type}, course_name={course_name}, exam_date={exam_date}, exam_time={exam_time}",
        )
    except Exception:
        pass
    return jsonify({"status":"ok"})

@exams_bp.route('/<exam_type>/delete_row', methods=['POST'])
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def delete_exam_row(exam_type):
    if exam_type not in VALID_TYPES:
        return jsonify({"status":"error"}), 400
    if not _role_may_edit_exam_schedule():
        return jsonify({"status": "error", "message": "غير مصرح", "code": "FORBIDDEN"}), 403
    data = request.get_json(force=True) or {}
    exam_id = data.get('exam_id')
    if not exam_id:
        return jsonify({"status":"error","message":"exam_id required"}), 400
    with get_connection() as conn:
        try:
            from backend.core.department_scope_policy import resolve_effective_department_scope_id
            from backend.services.term_closure import TermClosedError, assert_term_writable

            actor = (session.get("user") or session.get("username") or "").strip()
            dept_id = resolve_effective_department_scope_id(conn, actor)
            assert_term_writable(conn, stage="exams", department_id=dept_id)
        except TermClosedError as exc:
            return jsonify({"status": "error", "message": str(exc), "code": "term_closed"}), 423
        cur = conn.cursor()
        row_c = cur.execute("SELECT course_name FROM exams WHERE id = ? AND exam_type = ? LIMIT 1", (exam_id, exam_type)).fetchone()
        if row_c and not _course_in_scope(conn, row_c[0]):
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
        cur.execute('DELETE FROM exams WHERE id = ? AND exam_type = ?', (exam_id, exam_type))
        conn.commit()
    try:
        touch_exam_schedule_updated_at(exam_type)
    except Exception:
        pass
    try:
        persist_exam_conflicts(exam_type)
        log_activity(
            action="delete_exam_row",
            details=f"exam_type={exam_type}, exam_id={exam_id}",
        )
    except Exception:
        pass
    return jsonify({"status":"ok"})

@exams_bp.route('/<exam_type>/distribute', methods=['POST'])
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def distribute_exams(exam_type):
    """
    Body: { dates: ["YYYY-MM-DD", ...], method: "round_robin" }
    Distribute all courses found in schedule (or courses table) over given dates.
    Enforce max span <= 31 days.
    """
    if exam_type not in VALID_TYPES:
        return jsonify({"status":"error","message":"invalid exam type"}), 400
    data = request.get_json(force=True) or {}
    dates = data.get('dates') or []
    method = data.get('method','round_robin')
    dates = normalize_dates(dates)
    if not dates:
        return jsonify({"status":"error","message":"no valid dates provided"}), 400
    # enforce max span <= 31 days
    try:
        d0 = datetime.fromisoformat(dates[0]).date()
        d1 = datetime.fromisoformat(dates[-1]).date()
        span = (d1 - d0).days
        if span > 31:
            return jsonify({"status":"error","message":"date span exceeds 31 days"}), 400
    except Exception:
        pass

    with get_connection() as conn:
        cur = conn.cursor()
        dep = _effective_department_scope_id(conn)
        dept_scoped_user = dep is not None
        try:
            tname, tyear = get_current_term(conn=conn)
            term_label = f"{(tname or '').strip()} {(tyear or '').strip()}".strip() or SEMESTER_LABEL
        except Exception:
            term_label = SEMESTER_LABEL
        courses, _cov = schedule_distinct_course_names_for_coverage(
            conn,
            cur,
            term_label,
            dept_scope_id=int(dep) if dept_scoped_user else None,
        )
        if not courses:
            try:
                join_owner = ""
                dept_par: tuple = ()
                if dept_scoped_user and dep is not None:
                    try:
                        ccols = fetch_table_columns(conn, "courses")
                    except Exception:
                        ccols = []
                    if "owning_department_id" in ccols:
                        join_owner = """
                            INNER JOIN courses ccov_dep
                              ON lower(trim(ccov_dep.course_name)) = lower(trim(s.course_name))
                             AND COALESCE(ccov_dep.owning_department_id, -1) = ?
                        """
                        dept_par = (int(dep),)
                rows_fb = cur.execute(
                    f"""
                    SELECT MIN(TRIM(s.course_name)) AS course_name
                    FROM schedule s
                    {join_owner}
                    WHERE COALESCE(TRIM(s.course_name), '') <> ''
                    GROUP BY LOWER(TRIM(s.course_name))
                    ORDER BY MIN(TRIM(s.course_name))
                    """,
                    dept_par,
                ).fetchall()
                courses = [(r[0] or "").strip() for r in rows_fb if r and (r[0] or "").strip()]
            except Exception:
                courses = []
        if not courses:
            try:
                if dept_scoped_user and dep is not None:
                    rows_fb2 = cur.execute(
                        """
                        SELECT MIN(TRIM(course_name)) AS course_name
                        FROM courses
                        WHERE COALESCE(TRIM(course_name), '') <> ''
                          AND COALESCE(owning_department_id, -1) = ?
                        GROUP BY LOWER(TRIM(course_name))
                        ORDER BY MIN(TRIM(course_name))
                        """,
                        (int(dep),),
                    ).fetchall()
                else:
                    rows_fb2 = cur.execute(
                        """
                        SELECT MIN(TRIM(course_name)) AS course_name
                        FROM courses
                        WHERE COALESCE(TRIM(course_name), '') <> ''
                        GROUP BY LOWER(TRIM(course_name))
                        ORDER BY MIN(TRIM(course_name))
                        """
                    ).fetchall()
                courses = [(r[0] or "").strip() for r in rows_fb2 if r and (r[0] or "").strip()]
            except Exception:
                courses = []

        if not courses:
            return jsonify({"status":"error","message":"no courses found to schedule"}), 400

        _delete_exams_for_type_respecting_scope(
            cur, exam_type, int(dep) if dept_scoped_user else None, dept_scoped_user
        )

        # assign courses to dates
        if method == 'round_robin':
            di = 0
            for c in courses:
                ed = dates[di % len(dates)]
                cur.execute('INSERT INTO exams (exam_type, exam_id, course_name, exam_date, exam_time, room, instructor) VALUES (?,?,?,?,?,?,?)',
                            (exam_type, None, c, ed, '', '', ''))
                di += 1
        elif method in ('balanced', 'smart'):
            # توزيع يعتمد على عدد الطلبة المسجلين لتقليل احتمال التعارض
            actor_u = (session.get("user") or session.get("username") or "").strip()
            try:
                counts = registration_course_student_counts(cur, conn, actor_username=actor_u)
            except Exception:
                counts = {}
            # رتب المقررات تنازلياً حسب عدد الطلبة
            sorted_courses = sorted(
                courses, key=lambda c: counts.get((c or "").strip().lower(), 0), reverse=True
            )
            date_load = {d: 0 for d in dates}
            for c in sorted_courses:
                # اختر التاريخ ذو أقل حمل حالي
                target_date = min(date_load, key=lambda d: date_load[d])
                cur.execute(
                    'INSERT INTO exams (exam_type, exam_id, course_name, exam_date, exam_time, room, instructor) VALUES (?,?,?,?,?,?,?)',
                    (exam_type, None, c, target_date, '', '', ''),
                )
                date_load[target_date] += counts.get(c, 0)
        else:
            # default same as round_robin
            di = 0
            for c in courses:
                ed = dates[di % len(dates)]
                cur.execute('INSERT INTO exams (exam_type, exam_id, course_name, exam_date, exam_time, room, instructor) VALUES (?,?,?,?,?,?,?)',
                            (exam_type, None, c, ed, '', '', ''))
                di += 1
        conn.commit()
        try:
            touch_exam_schedule_updated_at(exam_type, conn=conn)
        except Exception:
            pass
        try:
            _create_exam_schedule_version(
                conn,
                exam_type,
                "distribute",
                note=f"method={method}, dates={','.join(dates)}",
            )
        except Exception:
            logger.exception("failed to create exam schedule version on distribute")
    try:
        persist_exam_conflicts(exam_type)
        log_activity(
            action="distribute_exams",
            details=f"exam_type={exam_type}, method={method}, dates={','.join(dates)}",
        )
    except Exception:
        pass
    return jsonify({"status":"ok","scheduled": len(courses)})


@exams_bp.route('/available_courses')
@login_required
def available_courses():
    """Return distinct course names from schedule (for populating selects)."""
    with get_connection() as conn:
        cur = conn.cursor()
        dep = _effective_department_scope_id(conn)
        dept_scoped_user = dep is not None
        try:
            tname, tyear = get_current_term(conn=conn)
            term_label = f"{(tname or '').strip()} {(tyear or '').strip()}".strip() or SEMESTER_LABEL
        except Exception:
            term_label = SEMESTER_LABEL
        courses, _ = schedule_distinct_course_names_for_coverage(
            conn,
            cur,
            term_label,
            dept_scope_id=int(dep) if dept_scoped_user else None,
        )
        if not courses:
            try:
                join_owner = ""
                dept_par: tuple = ()
                if dept_scoped_user and dep is not None:
                    try:
                        ccols = fetch_table_columns(conn, "courses")
                    except Exception:
                        ccols = []
                    if "owning_department_id" in ccols:
                        join_owner = """
                            INNER JOIN courses ccov_dep
                              ON lower(trim(ccov_dep.course_name)) = lower(trim(s.course_name))
                             AND COALESCE(ccov_dep.owning_department_id, -1) = ?
                        """
                        dept_par = (int(dep),)
                rows = cur.execute(
                    f"""
                    SELECT MIN(TRIM(s.course_name)) AS course_name
                    FROM schedule s
                    {join_owner}
                    WHERE COALESCE(TRIM(s.course_name), '') <> ''
                    GROUP BY LOWER(TRIM(s.course_name))
                    ORDER BY MIN(TRIM(s.course_name))
                    """,
                    dept_par,
                ).fetchall()
                courses = [r[0] for r in rows]
            except Exception:
                courses = []
        if not courses:
            try:
                if dept_scoped_user and dep is not None:
                    rows = cur.execute(
                        """
                        SELECT MIN(TRIM(course_name)) AS course_name
                        FROM courses
                        WHERE COALESCE(TRIM(course_name), '') <> ''
                          AND COALESCE(owning_department_id, -1) = ?
                        GROUP BY LOWER(TRIM(course_name))
                        ORDER BY MIN(TRIM(course_name))
                        """,
                        (int(dep),),
                    ).fetchall()
                else:
                    rows = cur.execute(
                        """
                        SELECT MIN(TRIM(course_name)) AS course_name
                        FROM courses
                        WHERE COALESCE(TRIM(course_name), '') <> ''
                        GROUP BY LOWER(TRIM(course_name))
                        ORDER BY MIN(TRIM(course_name))
                        """
                    ).fetchall()
                courses = [r[0] for r in rows]
            except Exception:
                courses = []
        assignments = schedule_course_primary_assignments(
            conn,
            cur,
            term_label,
            dept_scope_id=int(dep) if dept_scoped_user else None,
        )
    return jsonify({"courses": courses, "assignments": assignments})


@exams_bp.route('/<exam_type>/export')
@login_required
def export_exams(exam_type):
    """Export exam rows in format=txt|xlsx|pdf (query param format)."""
    fmt = (request.args.get('format') or 'txt').lower()
    if exam_type not in VALID_TYPES:
        return jsonify({"status": "error", "message": "invalid exam type"}), 400
    if not _user_can_view_exam_rows(exam_type):
        return jsonify({"status": "error", "message": "جدول الامتحانات غير معتمد/منشور بعد"}), 403
    ver_info = None
    if _should_snapshot_exam_export():
        ev_map = {"txt": "export_txt", "xlsx": "export_xlsx", "xls": "export_xlsx", "pdf": "export_pdf"}
        ev = ev_map.get(fmt, f"export_{fmt}")
        try:
            with get_connection() as conn:
                ver_info = _create_exam_schedule_version(
                    conn, exam_type, ev, note=f"exam export format={fmt}"
                )
        except Exception:
            logger.exception("failed to create exam schedule version on export")
    import io
    import pandas as pd

    with get_connection() as conn:
        exams = _exam_dicts_for_export_or_results(conn, exam_type)
    if fmt == 'txt':
        # tab-separated text
        df = pd.DataFrame(exams)
        buf = io.BytesIO()
        buf.write(df.to_csv(index=False, sep='\t', encoding='utf-8').encode('utf-8'))
        buf.seek(0)
        fname = f"exams_{exam_type}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
        return send_file(buf, mimetype='text/plain', as_attachment=True, download_name=fname)
    elif fmt in ('xlsx','xls'):
        df = pd.DataFrame(exams)
        return excel_response_from_df(df, filename_prefix=f"exams_{exam_type}")
    elif fmt == 'pdf':
        # build simple html
        rows_html = ''.join([f"<tr><td>{e.get('course_name','')}</td><td>{e.get('exam_date','')}</td><td>{e.get('exam_time','')}</td><td>{e.get('room','')}</td></tr>" for e in exams])
        meta_bits = ""
        if ver_info:
            meta_bits = f"<p style='font-size:11px;color:#444'>الفصل: {ver_info.get('semester') or '—'} | النسخة الأرشيفية: #{int(ver_info.get('version_no') or 0)}</p>"
        html = f"""
        <html><head><meta charset='utf-8'><style>table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #ccc;padding:6px}}</style></head>
        <body><h2>Exams - {exam_type}</h2>{meta_bits}<table><thead><tr><th>Course</th><th>Date</th><th>Time</th><th>Room</th></tr></thead><tbody>{rows_html}</tbody></table></body></html>
        """
        return pdf_response_from_html(html, filename_prefix=f"exams_{exam_type}")
    else:
        return jsonify({"status":"error","message":"unsupported format"}), 400


@exams_bp.route('/<exam_type>/conflicts/export')
@login_required
def export_conflicts(exam_type):
    fmt = (request.args.get('format') or 'txt').lower()
    if exam_type not in VALID_TYPES:
        return jsonify({"status": "error", "message": "invalid exam type"}), 400
    if not _user_can_view_exam_rows(exam_type):
        return jsonify({"status": "error", "message": "جدول الامتحانات غير معتمد/منشور بعد"}), 403
    import io
    import pandas as pd

    with get_connection() as conn:
        agg_rows = _fetch_exam_conflict_aggregate_rows(conn, exam_type)
        rows = pd.DataFrame(
            [
                {"student_id": r[0], "exam_date": r[1], "conflicting_courses": r[2], "ccount": r[3]}
                for r in agg_rows
            ]
        )
    if fmt == 'txt':
        buf = io.BytesIO()
        buf.write(rows.to_csv(index=False, sep="\t", encoding="utf-8").encode("utf-8"))
        buf.seek(0)
        fname = f"exam_conflicts_{exam_type}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
        return send_file(buf, mimetype='text/plain', as_attachment=True, download_name=fname)
    elif fmt in ('xlsx','xls'):
        return excel_response_from_df(rows, filename_prefix=f"exam_conflicts_{exam_type}")
    elif fmt == 'pdf':
        # build html table
        rows_html = "".join(
            [
                f"<tr><td>{r.student_id}</td><td>{r.exam_date}</td><td>{r.conflicting_courses}</td></tr>"
                for r in rows.itertuples()
            ]
        )
        html = f"""
        <html><head><meta charset='utf-8'><style>table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #ccc;padding:6px}}</style></head>
        <body><h2>Exam Conflicts - {exam_type}</h2><table><thead><tr><th>student_id</th><th>date</th><th>conflicting_courses</th></tr></thead><tbody>{rows_html}</tbody></table></body></html>
        """
        return pdf_response_from_html(html, filename_prefix=f"exam_conflicts_{exam_type}")
    else:
        return jsonify({"status":"error","message":"unsupported format"}), 400

@exams_bp.route('/<exam_type>/conflicts')
@login_required
def exam_conflicts(exam_type):
    if exam_type not in VALID_TYPES:
        return jsonify({"conflicts": []})
    if not _user_can_view_exam_rows(exam_type):
        return jsonify({"conflicts": []})
    role = _normalize_role((session.get("user_role") or "").strip())
    with get_connection() as conn:
        rows = _fetch_exam_conflict_aggregate_rows(conn, exam_type)
        out = []
        for r in rows:
            out.append({
                'student_id': r[0] or '',
                'exam_date': r[1] or '',
                'conflicting_courses': r[2] or ''
            })
        if role == "student":
            sid = (session.get("student_id") or session.get("user") or "").strip()
            out = [c for c in out if (c.get("student_id") or "").strip() == sid]
        return jsonify({'conflicts': out})

@exams_bp.route('/<exam_type>/results_data')
@login_required
def exam_results_data(exam_type):
    if exam_type not in VALID_TYPES:
        return jsonify({})
    if not _user_can_view_exam_rows(exam_type):
        return jsonify({"exams": [], "conflicts": []})
    with get_connection() as conn:
        exams = _exam_dicts_for_export_or_results(conn, exam_type)
        cur = conn.cursor()
        uname = (session.get("user") or session.get("username") or "").strip()
        stu_scope_sql, stu_scope_params = dept_scope_policy.resolve_scope_sql_for_students_table(
            conn, uname
        )
        if stu_scope_sql and stu_scope_sql != "1=0":
            cur.execute(
                f"""
                SELECT ec.student_id, ec.exam_date, ec.conflicting_courses
                FROM exam_conflicts ec
                WHERE ec.exam_type = ?
                  AND EXISTS (
                    SELECT 1 FROM students
                    WHERE students.student_id = ec.student_id
                      AND ({stu_scope_sql})
                  )
                """,
                (exam_type,) + tuple(stu_scope_params),
            )
        elif stu_scope_sql == "1=0":
            persisted = []
        else:
            cur.execute(
                "SELECT student_id, exam_date, conflicting_courses FROM exam_conflicts WHERE exam_type = ?",
                (exam_type,),
            )
        persisted = [dict(r) for r in cur.fetchall()] if stu_scope_sql != "1=0" else []
        if not persisted:
            agg = _fetch_exam_conflict_aggregate_rows(conn, exam_type)
            conflicts = [
                {"student_id": r[0] or "", "exam_date": r[1] or "", "conflicting_courses": r[2] or ""}
                for r in agg
            ]
        else:
            conflicts = persisted
    return jsonify({
        'exams': exams,
        'conflicts': conflicts
    })


@exams_bp.route('/<exam_type>/update_row', methods=['POST'])
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def update_exam_row(exam_type):
    if exam_type not in VALID_TYPES:
        return jsonify({"status":"error","message":"invalid exam type"}), 400
    data = request.get_json(force=True) or {}
    exam_id = data.get('exam_id')
    if not exam_id:
        return jsonify({"status":"error","message":"exam_id required"}), 400
    fields = {}
    for k in ('course_name','exam_date','exam_time','room','instructor'):
        if k in data:
            fields[k] = data[k]
    # توحيد صيغة التاريخ إذا تم تمريره
    if 'exam_date' in fields and fields['exam_date']:
        nd = normalize_dates([fields['exam_date']])
        if nd:
            fields['exam_date'] = nd[0]
    if not fields:
        return jsonify({"status":"error","message":"no fields to update"}), 400
    sets = ','.join([f"{k} = ?" for k in fields.keys()])
    params = list(fields.values()) + [exam_id, exam_type]
    q = f"UPDATE exams SET {sets} WHERE id = ? AND exam_type = ?"
    with get_connection() as conn:
        try:
            from backend.core.department_scope_policy import resolve_effective_department_scope_id
            from backend.services.term_closure import TermClosedError, assert_term_writable

            actor = (session.get("user") or session.get("username") or "").strip()
            dept_id = resolve_effective_department_scope_id(conn, actor)
            assert_term_writable(conn, stage="exams", department_id=dept_id)
        except TermClosedError as exc:
            return jsonify({"status": "error", "message": str(exc), "code": "term_closed"}), 423
        cur = conn.cursor()
        cur.execute(q, params)
        conn.commit()
    try:
        touch_exam_schedule_updated_at(exam_type)
    except Exception:
        pass
    try:
        persist_exam_conflicts(exam_type)
        log_activity(
            action="update_exam_row",
            details=f"exam_type={exam_type}, exam_id={exam_id}",
        )
    except Exception:
        pass
    return jsonify({"status":"ok"})


@exams_bp.route('/<exam_type>/bulk_update', methods=['POST'])
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def bulk_update_exam_rows(exam_type):
    if exam_type not in VALID_TYPES:
        return jsonify({"status":"error","message":"invalid exam type"}), 400
    data = request.get_json(force=True) or {}
    items = data.get('items') or []
    if not isinstance(items, list):
        return jsonify({"status":"error","message":"items must be a list"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        for it in items:
            exam_id = it.get('exam_id')
            if not exam_id:
                continue
            fields = {}
            for k in ('course_name','exam_date','exam_time','room','instructor'):
                if k in it:
                    fields[k] = it[k]
            # توحيد صيغة التاريخ إن وُجدت
            if 'exam_date' in fields and fields['exam_date']:
                nd = normalize_dates([fields['exam_date']])
                if nd:
                    fields['exam_date'] = nd[0]
            if not fields:
                continue
            sets = ','.join([f"{k} = ?" for k in fields.keys()])
            params = list(fields.values()) + [exam_id, exam_type]
            q = f"UPDATE exams SET {sets} WHERE id = ? AND exam_type = ?"
            try:
                cur.execute(q, params)
            except Exception:
                # skip individual failures
                continue
        conn.commit()
    try:
        touch_exam_schedule_updated_at(exam_type)
    except Exception:
        pass
    try:
        persist_exam_conflicts(exam_type)
        log_activity(
            action="bulk_update_exam_rows",
            details=f"exam_type={exam_type}, count={len(items)}",
        )
    except Exception:
        pass
    return jsonify({"status":"ok","updated": len(items)})


@exams_bp.route('/<exam_type>/student_rows')
@login_required
def student_exam_rows(exam_type):
    """
    إرجاع جدول امتحانات طالب معيّن:
    - الطالب: يستخدم student_id من الجلسة ولا يسمح بتمريره.
    - المشرف/الأدمن: يمكن تمرير ?student_id=...
    """
    if exam_type not in VALID_TYPES:
        return jsonify({"rows": []})
    if not _user_can_view_exam_rows(exam_type):
        return jsonify({"rows": []})
    user_role = session.get("user_role")
    if user_role == "student":
        sid = session.get("student_id") or session.get("user") or ""
    else:
        sid = (request.args.get("student_id") or "").strip()
    if not sid:
        return jsonify({"rows": []})

    with get_connection() as conn:
        cur = conn.cursor()
        q = """
        SELECT e.id AS exam_id,
               e.course_name,
               e.exam_date,
               e.exam_time,
               e.room,
               e.instructor
        FROM exams e
        JOIN registrations r ON LOWER(TRIM(r.course_name)) = LOWER(TRIM(e.course_name))
        WHERE e.exam_type = ? AND r.student_id = ?
        ORDER BY e.exam_date, e.exam_time, e.course_name
        """
        rows = cur.execute(q, (exam_type, sid)).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "exam_id": r[0],
                    "course_name": r[1],
                    "exam_date": r[2],
                    "exam_time": r[3],
                    "room": r[4],
                    "instructor": r[5],
                }
            )
    return jsonify({"rows": out})

# helper to persist conflicts (used if we want to write to exam_conflicts)
def persist_exam_conflicts(exam_type):
    if exam_type not in VALID_TYPES:
        return 0
    with get_connection() as conn:
        cur = conn.cursor()
        uname = (session.get("user") or session.get("username") or "").strip()
        stu_scope_sql, stu_scope_params = dept_scope_policy.resolve_scope_sql_for_students_table(
            conn, uname
        )
        if stu_scope_sql == "1=0":
            conn.commit()
            return 0
        if stu_scope_sql:
            cur.execute(
                f"""
                DELETE FROM exam_conflicts ec
                WHERE ec.exam_type = ?
                  AND EXISTS (
                    SELECT 1 FROM students
                    WHERE students.student_id = ec.student_id
                      AND ({stu_scope_sql})
                  )
                """,
                (exam_type,) + tuple(stu_scope_params),
            )
        else:
            cur.execute("DELETE FROM exam_conflicts WHERE exam_type = ?", (exam_type,))
        rows = _fetch_exam_conflict_aggregate_rows(conn, exam_type)
        for r in rows:
            cur.execute(
                "INSERT INTO exam_conflicts (exam_type, student_id, exam_date, conflicting_courses) VALUES (?,?,?,?)",
                (exam_type, r[0] or "", r[1] or "", r[2] or ""),
            )
        conn.commit()
        return len(rows)
