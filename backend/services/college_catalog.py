"""
المرحلة 1 — إدارة الكتالوج: أقسام، برامج، محتوى مقررات، مقررات الخطة، شُعَب التنفيذ.
الصلاحية:
- admin / admin_main: إدارة كاملة.
- head_of_department: مقررات الخطة فقط (مع قراءة برامج قسمه).
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from backend.core.auth import get_admin_department_scope_id, role_required
from backend.core.department_scope_policy import head_home_department_id
from backend.database.database import is_postgresql
from backend.services.utilities import get_connection

college_catalog_bp = Blueprint("college_catalog", __name__, url_prefix="/college/catalog")

_ADMIN_FULL = ("admin", "admin_main")
_PLAN_EDITOR = ("admin", "admin_main", "head_of_department")


def _body() -> dict:
    return request.get_json(force=True, silent=True) or {}


def _i(v, default=None):
    if v in (None, ""):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _ibool(v, default=1) -> int:
    if v is None:
        return default
    if isinstance(v, bool):
        return 1 if v else 0
    s = str(v).strip().lower()
    if s in ("1", "true", "yes"):
        return 1
    if s in ("0", "false", "no"):
        return 0
    return default


def _row_id(row) -> int:
    if hasattr(row, "__getitem__"):
        try:
            return int(row["id"])
        except Exception:
            return int(row[0])
    raise TypeError(row)


def _rows(cur, sql: str, params=()):
    cur.execute(sql, params)
    rows = cur.fetchall() or []
    desc = cur.description or ()
    keys = [d[0] for d in desc]
    out = []
    for r in rows:
        if hasattr(r, "keys"):
            try:
                out.append({k: r[k] for k in r.keys()})
                continue
            except Exception:
                pass
        out.append({keys[i]: r[i] for i in range(min(len(keys), len(r)))})
    return out


def _catalog_scope_department_id(conn) -> int | None:
    role = (session.get("user_role") or "").strip().lower()
    if role == "head_of_department":
        uname = (session.get("user") or session.get("username") or "").strip()
        dep = head_home_department_id(conn, uname)
        return int(dep) if dep is not None else None
    scoped = get_admin_department_scope_id()
    return int(scoped) if scoped is not None else None


def _program_belongs_to_scope(conn, program_id: int | None) -> bool:
    if program_id is None:
        return False
    scope_dep = _catalog_scope_department_id(conn)
    if scope_dep is None:
        return True
    cur = conn.cursor()
    row = cur.execute(
        "SELECT department_id FROM programs WHERE id = ? LIMIT 1",
        (int(program_id),),
    ).fetchone()
    if not row:
        return False
    dep_id = row["department_id"] if hasattr(row, "keys") else row[0]
    try:
        return int(dep_id or 0) == int(scope_dep)
    except Exception:
        return False


def _grading_mode(v: str) -> str:
    x = (v or "partial_final").strip().lower()
    return x if x in ("partial_final", "final_total_only") else "partial_final"


def _assessment(v: str) -> str:
    x = (v or "theoretical").strip().lower()
    if x in ("theoretical", "practical", "training"):
        return x
    return "theoretical"


def _phase(v: str) -> str:
    x = (v or "major").strip().lower()
    return x if x in ("general", "major") else "major"


# ---------------------------------------------------------------------------
@college_catalog_bp.route("/departments", methods=["GET"])
@role_required(*_ADMIN_FULL)
def list_departments():
    with get_connection() as conn:
        cur = conn.cursor()
        if is_postgresql():
            rows = _rows(cur, "SELECT * FROM departments ORDER BY code ASC")
        else:
            rows = _rows(cur, "SELECT * FROM departments ORDER BY code COLLATE NOCASE ASC")
    return jsonify({"status": "ok", "items": rows}), 200


@college_catalog_bp.route("/department/save", methods=["POST"])
@role_required(*_ADMIN_FULL)
def save_department():
    b = _body()
    dept_id = _i(b.get("id"))
    code = str(b.get("code") or "").strip()
    name_ar = str(b.get("name_ar") or "").strip()
    name_en = str(b.get("name_en") or "").strip()
    is_act = _ibool(b.get("is_active"), 1)
    if not code or not name_ar:
        return jsonify({"status": "error", "message": "رمز القسم والاسم بالعربية مطلوبان"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        pg = is_postgresql()
        if dept_id:
            cur.execute(
                """
                UPDATE departments SET code = ?, name_ar = ?, name_en = ?, is_active = ?
                WHERE id = ?
                """,
                (code, name_ar, name_en, is_act, dept_id),
            )
        elif pg:
            cur.execute(
                """
                INSERT INTO departments (code, name_ar, name_en, is_active)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (code) DO UPDATE
                SET name_ar = EXCLUDED.name_ar,
                    name_en = EXCLUDED.name_en,
                    is_active = EXCLUDED.is_active
                RETURNING id
                """,
                (code, name_ar, name_en, is_act),
            )
            dept_id = _row_id(cur.fetchone())
        else:
            cur.execute(
                "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, ?)",
                (code, name_ar, name_en, is_act),
            )
            cur.execute("SELECT id FROM departments WHERE code = ?", (code,))
            dept_id = _row_id(cur.fetchone())
            cur.execute(
                "UPDATE departments SET name_ar = ?, name_en = ?, is_active = ? WHERE id = ?",
                (name_ar, name_en, is_act, dept_id),
            )
        conn.commit()
    return jsonify({"status": "ok", "id": dept_id}), 200


# ---------------------------------------------------------------------------
@college_catalog_bp.route("/programs", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def list_programs():
    dept_id = _i(request.args.get("department_id"))
    with get_connection() as conn:
        if dept_id is None:
            scoped = _catalog_scope_department_id(conn)
            if scoped is not None:
                dept_id = scoped
        base = """
            SELECT p.*, d.code AS department_code
            FROM programs p
            LEFT JOIN departments d ON d.id = p.department_id
        """
        order = " ORDER BY COALESCE(d.code, ''), p.code "
        params = ()
        if dept_id:
            sql = base + " WHERE p.department_id = ?" + order
            params = (dept_id,)
        else:
            sql = base + order
        cur = conn.cursor()
        rows = _rows(cur, sql, params)
    return jsonify({"status": "ok", "items": rows}), 200


@college_catalog_bp.route("/program/save", methods=["POST"])
@role_required(*_ADMIN_FULL)
def save_program():
    b = _body()
    pid = _i(b.get("id"))
    department_id = _i(b.get("department_id"))
    code = str(b.get("code") or "").strip()
    name_ar = str(b.get("name_ar") or "").strip()
    name_en = str(b.get("name_en") or "").strip()
    phase = _phase(b.get("phase"))
    track_group = str(b.get("track_group") or "").strip()
    min_u = max(0, _i(b.get("min_total_units"), 0) or 0)
    rules_json = str(b.get("rules_json") or "").strip()
    is_act = _ibool(b.get("is_active"), 1)
    if department_id is None or not code or not name_ar:
        return jsonify({"status": "error", "message": "department_id ورمز البرنامج والاسم بالعربية مطلوبون"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        pg = is_postgresql()
        if pid:
            cur.execute(
                """
                UPDATE programs SET department_id = ?, code = ?, name_ar = ?, name_en = ?, phase = ?,
                    track_group = ?, min_total_units = ?, rules_json = ?, is_active = ?
                WHERE id = ?
                """,
                (
                    department_id,
                    code,
                    name_ar,
                    name_en,
                    phase,
                    track_group,
                    min_u,
                    rules_json or None,
                    is_act,
                    pid,
                ),
            )
        elif pg:
            cur.execute(
                """
                INSERT INTO programs
                (department_id, code, name_ar, name_en, phase, track_group,
                 min_total_units, rules_json, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULLIF(?, ''), ?)
                ON CONFLICT (department_id, code) DO UPDATE SET
                    name_ar = EXCLUDED.name_ar,
                    name_en = EXCLUDED.name_en,
                    phase = EXCLUDED.phase,
                    track_group = EXCLUDED.track_group,
                    min_total_units = EXCLUDED.min_total_units,
                    rules_json = EXCLUDED.rules_json,
                    is_active = EXCLUDED.is_active
                RETURNING id
                """,
                (
                    department_id,
                    code,
                    name_ar,
                    name_en,
                    phase,
                    track_group,
                    min_u,
                    rules_json or "",
                    is_act,
                ),
            )
            pid = _row_id(cur.fetchone())
        else:
            cur.execute(
                """
                INSERT OR IGNORE INTO programs
                (department_id, code, name_ar, name_en, phase, track_group,
                 min_total_units, rules_json, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    department_id,
                    code,
                    name_ar,
                    name_en,
                    phase,
                    track_group,
                    min_u,
                    rules_json or None,
                    is_act,
                ),
            )
            cur.execute(
                "SELECT id FROM programs WHERE department_id = ? AND code = ?",
                (department_id, code),
            )
            pid = _row_id(cur.fetchone())
            cur.execute(
                """
                UPDATE programs SET name_ar = ?, name_en = ?, phase = ?, track_group = ?,
                  min_total_units = ?, rules_json = ?, is_active = ?
                WHERE id = ?
                """,
                (name_ar, name_en, phase, track_group, min_u, rules_json or None, is_act, pid),
            )
        conn.commit()
    return jsonify({"status": "ok", "id": pid}), 200


# ---------------------------------------------------------------------------
@college_catalog_bp.route("/course_masters", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def list_course_masters():
    with get_connection() as conn:
        cur = conn.cursor()
        if is_postgresql():
            rows = _rows(cur, "SELECT * FROM course_master ORDER BY title_ar ASC")
        else:
            rows = _rows(cur, "SELECT * FROM course_master ORDER BY title_ar COLLATE NOCASE ASC")
    return jsonify({"status": "ok", "items": rows}), 200


@college_catalog_bp.route("/course_master/save", methods=["POST"])
@role_required(*_ADMIN_FULL)
def save_course_master():
    b = _body()
    mid = _i(b.get("id"))
    title_ar = str(b.get("title_ar") or "").strip()
    title_en = str(b.get("title_en") or "").strip()
    description = str(b.get("description") or "").strip()
    units = max(0, _i(b.get("default_units"), 0) or 0)
    gm = _grading_mode(b.get("grading_mode"))
    at = _assessment(b.get("assessment_type"))
    if not title_ar:
        return jsonify({"status": "error", "message": "عنوان المقرر بالعربية مطلوب"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        pg = is_postgresql()
        if mid:
            cur.execute(
                """
                UPDATE course_master SET title_ar = ?, title_en = ?, description = ?, default_units = ?,
                  grading_mode = ?, assessment_type = ?
                WHERE id = ?
                """,
                (title_ar, title_en, description, units, gm, at, mid),
            )
        elif pg:
            cur.execute(
                """
                INSERT INTO course_master
                  (title_ar, title_en, description, default_units, grading_mode, assessment_type)
                VALUES (?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (title_ar, title_en, description, units, gm, at),
            )
            mid = _row_id(cur.fetchone())
        else:
            cur.execute(
                """
                INSERT INTO course_master
                  (title_ar, title_en, description, default_units, grading_mode, assessment_type)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (title_ar, title_en, description, units, gm, at),
            )
            mid = int(getattr(cur, "lastrowid", None) or cur.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.commit()
    return jsonify({"status": "ok", "id": mid}), 200


# ---------------------------------------------------------------------------
@college_catalog_bp.route("/program_courses", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def list_program_courses():
    program_id = _i(request.args.get("program_id"))
    if not program_id:
        return jsonify({"status": "error", "message": "program_id مطلوب"}), 400
    with get_connection() as conn:
        if not _program_belongs_to_scope(conn, int(program_id)):
            return jsonify({"status": "error", "message": "FORBIDDEN_PROGRAM_SCOPE"}), 403
        cur = conn.cursor()
        rows = _rows(
            cur,
            """
            SELECT pc.*, cm.title_ar AS master_title_ar
            FROM program_courses pc
            INNER JOIN course_master cm ON cm.id = pc.course_master_id
            WHERE pc.program_id = ?
            ORDER BY pc.level_no, pc.course_code
            """,
            (program_id,),
        )
    return jsonify({"status": "ok", "items": rows}), 200


@college_catalog_bp.route("/program_courses/browse", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def browse_program_courses():
    lim = max(1, min(_i(request.args.get("limit"), 400), 800))
    order_lim = """
            ORDER BY COALESCE(d.code, ''), p.code, pc.level_no, pc.course_code
            LIMIT ?
            """
    base_sel = """
            SELECT pc.id,
                   pc.program_id,
                   pc.course_master_id,
                   pc.course_code,
                   COALESCE(pc.plan_applicability, 'both') AS plan_applicability,
                   pc.level_no,
                   d.code AS department_code,
                   p.code AS program_code,
                   p.phase AS program_phase,
                   cm.title_ar AS master_title_ar
            FROM program_courses pc
            INNER JOIN programs p ON p.id = pc.program_id
            LEFT JOIN departments d ON d.id = p.department_id
            INNER JOIN course_master cm ON cm.id = pc.course_master_id
            """
    with get_connection() as conn:
        scope = _catalog_scope_department_id(conn)
        cur = conn.cursor()
        if scope is not None:
            sql = base_sel + " WHERE p.department_id = ? " + order_lim
            params = (scope, lim)
        else:
            sql = base_sel + order_lim
            params = (lim,)
        rows = _rows(cur, sql, params)
    for r in rows:
        dept = str(r.get("department_code") or "")
        pcode = str(r.get("program_code") or "")
        cc = str(r.get("course_code") or "")
        r["label"] = f"{dept} / {pcode} / {cc}" if dept or pcode else cc
    return jsonify({"status": "ok", "items": rows}), 200


@college_catalog_bp.route("/program_course/save", methods=["POST"])
@role_required(*_PLAN_EDITOR)
def save_program_course():
    b = _body()
    pcid = _i(b.get("id"))
    program_id = _i(b.get("program_id"))
    course_master_id = _i(b.get("course_master_id"))
    course_master_title_ar = str(b.get("course_master_title_ar") or "").strip()
    course_code = str(b.get("course_code") or "").strip()
    name_ov = str(b.get("course_name_override") or "").strip()
    level_no = max(0, _i(b.get("level_no"), 0) or 0)
    term_hint = str(b.get("term_hint") or "").strip()
    units_ov = b.get("units_override")
    units_ov_int = None if units_ov in (None, "") else _i(units_ov, 0)
    plan_app = str(b.get("plan_applicability") or "both").strip().lower()
    if plan_app not in ("150", "155", "both"):
        plan_app = "both"
    category = str(b.get("category") or "required").strip() or "required"
    reqd = _ibool(b.get("is_required"), 1)
    is_act = _ibool(b.get("is_active"), 1)
    if program_id is None or not course_code:
        return jsonify(
            {"status": "error", "message": "program_id ورمز المقرر في الخطة مطلوبة"}
        ), 400
    with get_connection() as conn:
        if not _program_belongs_to_scope(conn, int(program_id)):
            return jsonify({"status": "error", "message": "FORBIDDEN_PROGRAM_SCOPE"}), 403
        cur = conn.cursor()
        if course_master_id is None:
            if not course_master_title_ar:
                return jsonify(
                    {"status": "error", "message": "اختر مقررًا من القائمة أو أدخل اسم مقرر جديد"}
                ), 400
            existing = cur.execute(
                """
                SELECT id
                FROM course_master
                WHERE lower(trim(COALESCE(title_ar,''))) = lower(trim(?))
                LIMIT 1
                """,
                (course_master_title_ar,),
            ).fetchone()
            if existing:
                course_master_id = _row_id(existing)
            else:
                if is_postgresql():
                    cur.execute(
                        """
                        INSERT INTO course_master (title_ar, default_units, grading_mode, assessment_type)
                        VALUES (?, ?, 'partial_final', 'theoretical')
                        RETURNING id
                        """,
                        (course_master_title_ar, int(units_ov_int or 0)),
                    )
                    course_master_id = _row_id(cur.fetchone())
                else:
                    cur.execute(
                        """
                        INSERT INTO course_master (title_ar, default_units, grading_mode, assessment_type)
                        VALUES (?, ?, 'partial_final', 'theoretical')
                        """,
                        (course_master_title_ar, int(units_ov_int or 0)),
                    )
                    course_master_id = int(
                        getattr(cur, "lastrowid", None)
                        or cur.execute("SELECT last_insert_rowid()").fetchone()[0]
                    )
        pg = is_postgresql()
        if pcid:
            cur.execute(
                """
                UPDATE program_courses SET program_id = ?, course_master_id = ?, course_code = ?,
                  course_name_override = ?, plan_applicability = ?, level_no = ?, term_hint = ?, units_override = ?,
                  category = ?, is_required = ?, is_active = ?
                WHERE id = ?
                """,
                (
                    program_id,
                    course_master_id,
                    course_code,
                    name_ov,
                    plan_app,
                    level_no,
                    term_hint,
                    units_ov_int,
                    category,
                    reqd,
                    is_act,
                    pcid,
                ),
            )
        elif pg:
            cur.execute(
                """
                INSERT INTO program_courses
                (program_id, course_master_id, course_code, course_name_override,
                 plan_applicability, level_no, term_hint, units_override, category, is_required, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (program_id, course_code) DO UPDATE SET
                  course_master_id = EXCLUDED.course_master_id,
                  course_name_override = EXCLUDED.course_name_override,
                  plan_applicability = EXCLUDED.plan_applicability,
                  level_no = EXCLUDED.level_no,
                  term_hint = EXCLUDED.term_hint,
                  units_override = EXCLUDED.units_override,
                  category = EXCLUDED.category,
                  is_required = EXCLUDED.is_required,
                  is_active = EXCLUDED.is_active
                RETURNING id
                """,
                (
                    program_id,
                    course_master_id,
                    course_code,
                    name_ov,
                    plan_app,
                    level_no,
                    term_hint,
                    units_ov_int,
                    category,
                    reqd,
                    is_act,
                ),
            )
            pcid = _row_id(cur.fetchone())
        else:
            cur.execute(
                """
                INSERT INTO program_courses
                (program_id, course_master_id, course_code, course_name_override,
                 plan_applicability, level_no, term_hint, units_override, category, is_required, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (program_id, course_code) DO UPDATE SET
                  course_master_id = excluded.course_master_id,
                  course_name_override = excluded.course_name_override,
                  plan_applicability = excluded.plan_applicability,
                  level_no = excluded.level_no,
                  term_hint = excluded.term_hint,
                  units_override = excluded.units_override,
                  category = excluded.category,
                  is_required = excluded.is_required,
                  is_active = excluded.is_active
                """,
                (
                    program_id,
                    course_master_id,
                    course_code,
                    name_ov,
                    plan_app,
                    level_no,
                    term_hint,
                    units_ov_int,
                    category,
                    reqd,
                    is_act,
                ),
            )
            cur.execute(
                "SELECT id FROM program_courses WHERE program_id = ? AND course_code = ?",
                (program_id, course_code),
            )
            pcid = _row_id(cur.fetchone())
        conn.commit()
    return jsonify({"status": "ok", "id": pcid}), 200


@college_catalog_bp.route("/program_course/delete", methods=["POST"])
@role_required(*_PLAN_EDITOR)
def delete_program_course():
    pcid = _i(_body().get("id"))
    if pcid is None:
        return jsonify({"status": "error", "message": "id مطلوب"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute("SELECT program_id FROM program_courses WHERE id = ? LIMIT 1", (pcid,)).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        prog_id = row["program_id"] if hasattr(row, "keys") else row[0]
        if not _program_belongs_to_scope(conn, _i(prog_id)):
            return jsonify({"status": "error", "message": "FORBIDDEN_PROGRAM_SCOPE"}), 403
        cur = conn.cursor()
        cur.execute("DELETE FROM program_courses WHERE id = ?", (pcid,))
        conn.commit()
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
@college_catalog_bp.route("/sections", methods=["GET"])
@role_required(*_ADMIN_FULL)
def list_sections():
    program_course_id = _i(request.args.get("program_course_id"))
    if not program_course_id:
        return jsonify({"status": "error", "message": "program_course_id مطلوب"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        if is_postgresql():
            sql = """
                SELECT * FROM program_course_sections
                WHERE program_course_id = ?
                ORDER BY section_code ASC
            """
        else:
            sql = """
                SELECT * FROM program_course_sections
                WHERE program_course_id = ?
                ORDER BY section_code COLLATE NOCASE ASC
            """
        rows = _rows(cur, sql, (program_course_id,))
    return jsonify({"status": "ok", "items": rows}), 200


@college_catalog_bp.route("/section/save", methods=["POST"])
@role_required(*_ADMIN_FULL)
def save_section():
    b = _body()
    sid = _i(b.get("id"))
    program_course_id = _i(b.get("program_course_id"))
    section_code = str(b.get("section_code") or "").strip()
    cap_raw = b.get("capacity_max")
    cap = None if cap_raw in (None, "") else _i(cap_raw, None)
    semester = str(b.get("semester") or "").strip()
    note = str(b.get("note") or "").strip()
    is_act = _ibool(b.get("is_active"), 1)
    if program_course_id is None or not section_code:
        return jsonify({"status": "error", "message": "program_course_id و section_code مطلوبان"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        pg = is_postgresql()
        if sid:
            cur.execute(
                """
                UPDATE program_course_sections SET program_course_id = ?, section_code = ?,
                  capacity_max = ?, semester = ?, note = ?, is_active = ?
                WHERE id = ?
                """,
                (program_course_id, section_code, cap, semester, note, is_act, sid),
            )
        elif pg:
            cur.execute(
                """
                INSERT INTO program_course_sections
                  (program_course_id, section_code, capacity_max, semester, note, is_active)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (program_course_id, section_code) DO UPDATE SET
                  capacity_max = EXCLUDED.capacity_max,
                  semester = EXCLUDED.semester,
                  note = EXCLUDED.note,
                  is_active = EXCLUDED.is_active
                RETURNING id
                """,
                (program_course_id, section_code, cap, semester, note, is_act),
            )
            sid = _row_id(cur.fetchone())
        else:
            cur.execute(
                """
                INSERT INTO program_course_sections
                  (program_course_id, section_code, capacity_max, semester, note, is_active)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (program_course_id, section_code) DO UPDATE SET
                  capacity_max = excluded.capacity_max,
                  semester = excluded.semester,
                  note = excluded.note,
                  is_active = excluded.is_active
                """,
                (program_course_id, section_code, cap, semester, note, is_act),
            )
            cur.execute(
                """
                SELECT id FROM program_course_sections
                WHERE program_course_id = ? AND section_code = ?
                """,
                (program_course_id, section_code),
            )
            sid = _row_id(cur.fetchone())
        conn.commit()
    return jsonify({"status": "ok", "id": sid}), 200


@college_catalog_bp.route("/section/delete", methods=["POST"])
@role_required(*_ADMIN_FULL)
def delete_section():
    sid = _i(_body().get("id"))
    if sid is None:
        return jsonify({"status": "error", "message": "id مطلوب"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM program_course_sections WHERE id = ?", (sid,))
        conn.commit()
    return jsonify({"status": "ok"}), 200
