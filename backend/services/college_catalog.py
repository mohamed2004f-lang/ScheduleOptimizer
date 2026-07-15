"""
المرحلة 1 — إدارة الكتالوج: أقسام، برامج، محتوى مقررات، مقررات الخطة، شُعَب التنفيذ.
الصلاحية:
- admin / admin_main: إدارة كاملة.
- head_of_department: مقررات الخطة فقط (مع قراءة برامج قسمه).
"""

from __future__ import annotations

import re

from flask import Blueprint, jsonify, request, session

from backend.core.academic_pathway import (
    COLLEGE_GENERAL_COMPONENT_LABELS,
    REQUIREMENT_SCOPE_LABELS,
    ensure_program_course_plan_schema,
    normalize_college_general_component,
    normalize_requirement_scope,
)
from backend.core.program_tracks import (
    BUILTIN_TRACK_GROUPS,
    CANONICAL_BASE_PROGRAM_CODE,
    TRACK_GROUP_LABELS,
    base_program_template,
    builtin_track_groups_for_department,
    catalog_rules,
    department_has_track_catalog,
    department_tracks_note_ar,
    ensure_department_track_programs,
    is_custom_track_from_rules,
    merge_catalog_rules,
    names_customized_from_rules,
    program_role_label,
    track_group_label,
    track_template_presets,
)
from backend.core.auth import role_required
from backend.core.course_master_catalog import (
    LIFECYCLE_LABELS_AR,
    LIFECYCLE_SHARED,
    LIFECYCLE_STANDARD,
    LIFECYCLE_TRANSITIONAL,
    apply_transitional_title_tag,
    ensure_course_master_catalog_schema,
    normalize_catalog_lifecycle,
    title_suggests_transitional,
)
from backend.core.department_scope_policy import resolve_effective_department_scope_id
from backend.core.feature_flags import registration_program_course_mode
from backend.database.database import fetch_table_columns, is_postgresql
from backend.services.utilities import excel_response_from_frames, get_connection

college_catalog_bp = Blueprint("college_catalog", __name__, url_prefix="/college/catalog")

_ADMIN_FULL = ("admin", "admin_main", "system_admin", "college_dean")
_PLAN_EDITOR = ("admin", "admin_main", "system_admin", "college_dean", "head_of_department")


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
    uname = (session.get("user") or session.get("username") or "").strip()
    return resolve_effective_department_scope_id(conn, uname)


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


def _program_department_id(cur, program_id: int) -> tuple[int | None, str | None]:
    row = cur.execute(
        """
        SELECT p.department_id, d.code AS department_code
        FROM programs p
        LEFT JOIN departments d ON d.id = p.department_id
        WHERE p.id = ?
        LIMIT 1
        """,
        (int(program_id),),
    ).fetchone()
    if not row:
        return None, None
    if hasattr(row, "keys"):
        return row["department_id"], row["department_code"]
    return row[0], row[1]


def _find_or_create_course_master(
    cur,
    title_ar: str,
    units: int = 0,
    assessment_type: str = "theoretical",
) -> int:
    title_ar = (title_ar or "").strip()
    if not title_ar:
        raise ValueError("title_ar required")
    existing = cur.execute(
        """
        SELECT id FROM course_master
        WHERE lower(trim(COALESCE(title_ar,''))) = lower(trim(?))
        LIMIT 1
        """,
        (title_ar,),
    ).fetchone()
    if existing:
        return _row_id(existing)
    at = _assessment(assessment_type)
    u = max(0, int(units or 0))
    if is_postgresql():
        cur.execute(
            """
            INSERT INTO course_master (title_ar, default_units, grading_mode, assessment_type)
            VALUES (?, ?, 'partial_final', ?)
            RETURNING id
            """,
            (title_ar, u, at),
        )
        return _row_id(cur.fetchone())
    cur.execute(
        """
        INSERT INTO course_master (title_ar, default_units, grading_mode, assessment_type)
        VALUES (?, ?, 'partial_final', ?)
        """,
        (title_ar, u, at),
    )
    return int(
        getattr(cur, "lastrowid", None)
        or cur.execute("SELECT last_insert_rowid()").fetchone()[0]
    )


def _link_operational_course_to_master(
    conn, cur, course_name: str, department_id: int | None
) -> int | None:
    """ربط مقرر من جدول courses بـ course_master (إنشاء عند الحاجة)."""
    cname = (course_name or "").strip()
    if not cname:
        return None
    cols = set()
    try:
        cols = set(fetch_table_columns(conn, "courses"))
    except Exception:
        pass
    has_owning = "owning_department_id" in cols
    has_assessment = "assessment_type" in cols
    q = "SELECT course_name, course_code, course_master_id, units"
    if has_assessment:
        q += ", assessment_type"
    q += " FROM courses WHERE course_name = ?"
    params: tuple = (cname,)
    if has_owning and department_id is not None:
        q += " AND (owning_department_id IS NULL OR owning_department_id = ?)"
        params = (cname, int(department_id))
    row = cur.execute(q, params).fetchone()
    if not row:
        return None
    if hasattr(row, "keys"):
        d = {k: row[k] for k in row.keys()}
    else:
        keys = ["course_name", "course_code", "course_master_id", "units"]
        if has_assessment:
            keys.append("assessment_type")
        d = {keys[i]: row[i] for i in range(len(row))}
    cmid = d.get("course_master_id")
    if cmid not in (None, ""):
        try:
            return int(cmid)
        except (TypeError, ValueError):
            pass
    title = (d.get("course_name") or cname).strip()
    units = int(d.get("units") or 0)
    at = d.get("assessment_type") if has_assessment else "theoretical"
    mid = _find_or_create_course_master(cur, title, units, str(at or "theoretical"))
    if "course_master_id" in cols:
        cur.execute(
            "UPDATE courses SET course_master_id = ? WHERE course_name = ?",
            (mid, cname),
        )
    return mid


def _phase(v: str) -> str:
    x = (v or "major").strip().lower()
    return x if x in ("general", "major") else "major"


# ---------------------------------------------------------------------------
@college_catalog_bp.route("/pathway_meta", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def pathway_meta():
    """تسميات مسار الطالب ونطاق المتطلب (للواجهة)."""
    from backend.core.academic_pathway import (
        COLLEGE_GENERAL_PROGRAM_CODE,
        PATHWAY_STAGE_LABELS,
        PATHWAY_STAGES,
        college_pathway_cohort_cutoff,
    )

    cohort_year = None
    with get_connection() as conn:
        cur = conn.cursor()
        cohort_year = college_pathway_cohort_cutoff(cur, None)

    return jsonify(
        {
            "status": "ok",
            "requirement_scopes": [
                {"value": k, "label": REQUIREMENT_SCOPE_LABELS.get(k, k)}
                for k in ("college_general", "pre_track", "track", "elective", "dept_common")
            ],
            "pathway_stages": [
                {"value": k, "label": PATHWAY_STAGE_LABELS.get(k, k)} for k in PATHWAY_STAGES
            ],
            "operating_modes": [
                {
                    "value": "dept_only",
                    "label": "قسم فقط (طلاب حاليون بعد الاتجاه العام)",
                },
                {
                    "value": "college_and_dept",
                    "label": "كلية + قسم (دفعات جديدة في PROG_U1)",
                },
            ],
            "operating_mode": "dept_only",
            "college_pathway_cohort_from_join_year": cohort_year,
            "college_general_program_code": COLLEGE_GENERAL_PROGRAM_CODE,
            "operating_mode_note_ar": (
                "وحدات التخرج تختلف حسب القسم (شاملة اتجاه عام 36 — ليست +36). "
                "عرّف بنود كل قسم في تبويب لائحة المسار ثم زامِن البرامج. "
                "150/155 انتقالي لميكانيكا فقط (سجل الطالب)."
            ),
        }
    ), 200


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
    all_depts = (request.args.get("all") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    scope_applied = None
    with get_connection() as conn:
        if dept_id is None and not all_depts:
            scoped = _catalog_scope_department_id(conn)
            if scoped is not None:
                dept_id = scoped
                scope_applied = scoped
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
    for r in rows:
        tg = (r.get("track_group") or "").strip()
        code = (r.get("code") or "").strip()
        rules = r.get("rules_json")
        dept_code = (r.get("department_code") or "").strip().upper()
        base_tpl = base_program_template(dept_code) if dept_code else None
        base_codes = {CANONICAL_BASE_PROGRAM_CODE, "PROG_MAJOR"}
        if base_tpl:
            base_codes.add((base_tpl.program_code or "").strip().upper())
        dept_builtin = (
            builtin_track_groups_for_department(dept_code) if dept_code else frozenset()
        )
        builtin = dept_builtin if dept_builtin else BUILTIN_TRACK_GROUPS
        r["track_group_label"] = track_group_label(
            tg, rules_json=rules, name_ar=r.get("name_ar")
        )
        r["program_role"] = program_role_label(
            tg, code, rules_json=rules, name_ar=r.get("name_ar")
        )
        r["is_base_program"] = (not tg) or code.upper() in base_codes
        r["names_customized"] = names_customized_from_rules(rules)
        r["is_custom_track"] = is_custom_track_from_rules(rules) or (
            bool(tg) and tg.upper() not in builtin
        )
    return jsonify(
        {
            "status": "ok",
            "items": rows,
            "filtered_all_departments": bool(all_depts),
            "scope_department_id": scope_applied,
        }
    ), 200


@college_catalog_bp.route("/department_program_tracks", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def department_program_tracks():
    """كتالوج برامج الشعب لقسم (قوالب + برامج موجودة)."""
    dept_code = (request.args.get("department_code") or "MECH").strip().upper()
    ensure = (request.args.get("ensure") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    with get_connection() as conn:
        if ensure:
            ensure_department_track_programs(conn, dept_code)
        cur = conn.cursor()
        dept_row = cur.execute(
            "SELECT id, code, name_ar FROM departments WHERE UPPER(TRIM(code)) = ? LIMIT 1",
            (dept_code,),
        ).fetchone()
        if not dept_row:
            return jsonify({"status": "error", "message": "قسم غير موجود"}), 404
        dept_id = dept_row[0] if not hasattr(dept_row, "keys") else dept_row["id"]
        programs = _rows(
            cur,
            """
            SELECT p.id, p.code, p.name_ar, p.name_en, p.track_group, p.min_total_units,
                   COALESCE(p.is_active, 1) AS is_active
            FROM programs p
            WHERE p.department_id = ?
            ORDER BY
              CASE WHEN COALESCE(p.track_group, '') = '' THEN 0 ELSE 1 END,
              p.code
            """,
            (int(dept_id),),
        )
    dept_builtin = builtin_track_groups_for_department(dept_code)
    base_tpl = base_program_template(dept_code)
    base_codes = {CANONICAL_BASE_PROGRAM_CODE, "PROG_MAJOR"}
    if base_tpl:
        base_codes.add((base_tpl.program_code or "").strip().upper())
    base_list = []
    track_list = []
    for p in programs:
        tg = (p.get("track_group") or "").strip()
        code = (p.get("code") or "").strip()
        rules = p.get("rules_json")
        p["track_group_label"] = track_group_label(
            tg, rules_json=rules, name_ar=p.get("name_ar")
        )
        p["program_role"] = program_role_label(
            tg, code, rules_json=rules, name_ar=p.get("name_ar")
        )
        p["is_base_program"] = not tg or code.upper() in base_codes
        p["names_customized"] = names_customized_from_rules(rules)
        builtin = dept_builtin if dept_builtin else BUILTIN_TRACK_GROUPS
        p["is_custom_track"] = is_custom_track_from_rules(rules) or (
            bool(tg) and tg.upper() not in builtin
        )
        if p["is_base_program"] and not tg:
            base_list.append(p)
        else:
            track_list.append(p)
    bp = base_tpl.program_code if base_tpl else dept_code
    return jsonify(
        {
            "status": "ok",
            "department_code": dept_code,
            "department_id": dept_id,
            "track_group_labels": TRACK_GROUP_LABELS,
            "base_programs": base_list,
            "track_programs": track_list,
            "items": programs,
            "track_templates": track_template_presets(dept_code),
            "base_program_code": bp,
            "builtin_track_groups": sorted(dept_builtin) if dept_builtin else [],
            "has_track_catalog": department_has_track_catalog(dept_code),
            "note_ar": department_tracks_note_ar(dept_code),
        }
    ), 200


@college_catalog_bp.route("/department_program_tracks/ensure", methods=["POST"])
@role_required(*_PLAN_EDITOR)
def department_program_tracks_ensure():
    """إنشاء/تحديث قوالب برامج الشعب لقسم."""
    b = _body()
    dept_code = (b.get("department_code") or "MECH").strip().upper()
    from backend.core.program_tracks import graduation_units_for_department_code

    grad = _i(b.get("min_total_units"))
    if grad is None:
        grad = graduation_units_for_department_code(dept_code)
    grad = int(grad or 0) or graduation_units_for_department_code(dept_code)
    with get_connection() as conn:
        scope_dep = _catalog_scope_department_id(conn)
        if scope_dep is not None:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT code FROM departments WHERE id = ? LIMIT 1",
                (int(scope_dep),),
            ).fetchone()
            if not row:
                return jsonify({"status": "error", "message": "قسم غير معرّف"}), 403
            allowed = (
                row["code"] if hasattr(row, "keys") else row[0]
            ) or ""
            if (allowed or "").strip().upper() != dept_code:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "لا يمكن تهيئة شعب قسم آخر",
                        }
                    ),
                    403,
                )
        result = ensure_department_track_programs(
            conn, dept_code, graduation_units=int(grad)
        )
    if result.get("status") == "error":
        return jsonify(result), 400
    return jsonify(result), 200


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
    mark_custom_names = _ibool(b.get("names_customized"), 0)
    custom_track = _ibool(b.get("custom_track"), 0)
    track_label_ar = str(b.get("track_label_ar") or "").strip()
    if department_id is None or not code or not name_ar:
        return jsonify({"status": "error", "message": "department_id ورمز البرنامج والاسم بالعربية مطلوبون"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        pg = is_postgresql()
        existing_rules = ""
        if pid:
            row_r = cur.execute(
                "SELECT rules_json FROM programs WHERE id = ? LIMIT 1",
                (pid,),
            ).fetchone()
            if row_r:
                existing_rules = (
                    row_r["rules_json"]
                    if hasattr(row_r, "keys")
                    else (row_r[0] or "")
                ) or ""
        if mark_custom_names or custom_track or track_label_ar:
            rules_json = merge_catalog_rules(
                existing_rules or rules_json,
                names_customized=True if mark_custom_names else None,
                custom_track=True if custom_track else None,
                track_label_ar=track_label_ar or None,
            )
        elif pid and not rules_json:
            rules_json = existing_rules
        if track_group and track_group.upper() not in BUILTIN_TRACK_GROUPS:
            rules_json = merge_catalog_rules(
                rules_json or existing_rules,
                custom_track=True,
                track_label_ar=track_label_ar or name_ar,
            )
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


def _course_master_usage_map(cur) -> dict[int, dict]:
    """عدد البرامج والأقسام وبنود الخطة لكل course_master."""
    out: dict[int, dict] = {}

    def _merge_rows(rows: list[dict], fields: dict[str, str]) -> None:
        for r in rows:
            mid = _i(r.get("mid"))
            if mid is None:
                continue
            slot = out.setdefault(
                mid,
                {"program_count": 0, "department_count": 0, "plan_row_count": 0},
            )
            for key, src in fields.items():
                slot[key] = int(r.get(src) or 0)

    try:
        _merge_rows(
            _rows(
                cur,
                """
                SELECT pc.course_master_id AS mid,
                       COUNT(DISTINCT pc.program_id) AS program_count,
                       COUNT(DISTINCT p.department_id) AS department_count,
                       COUNT(*) AS plan_row_count
                FROM program_courses pc
                INNER JOIN programs p ON p.id = pc.program_id
                GROUP BY pc.course_master_id
                """,
            ),
            {
                "program_count": "program_count",
                "department_count": "department_count",
                "plan_row_count": "plan_row_count",
            },
        )
    except Exception:
        pass
    try:
        _merge_rows(
            _rows(
                cur,
                """
                SELECT course_master_id AS mid, COUNT(*) AS operational_count
                FROM courses
                WHERE course_master_id IS NOT NULL
                GROUP BY course_master_id
                """,
            ),
            {"operational_count": "operational_count"},
        )
    except Exception:
        pass
    try:
        _merge_rows(
            _rows(
                cur,
                """
                SELECT course_master_id AS mid, COUNT(*) AS plo_link_count
                FROM plo_course_master_links
                GROUP BY course_master_id
                """,
            ),
            {"plo_link_count": "plo_link_count"},
        )
    except Exception:
        pass
    return out


def _sql_count(cur, sql: str, params: tuple) -> int:
    r = cur.execute(sql, params).fetchone()
    if not r:
        return 0
    try:
        return int(r[0])
    except (TypeError, IndexError, KeyError):
        pass
    if hasattr(r, "keys"):
        keys = list(r.keys())
        if keys:
            return int(r[keys[0]])
    return 0


def _course_master_delete_blockers(cur, master_id: int) -> dict[str, int]:
    blockers: dict[str, int] = {}
    pc = _sql_count(
        cur,
        "SELECT COUNT(*) FROM program_courses WHERE course_master_id = ?",
        (master_id,),
    )
    if pc:
        blockers["program_courses"] = pc
    pr = _sql_count(
        cur,
        """
        SELECT COUNT(*) FROM program_course_prereqs
        WHERE required_course_master_id = ?
        """,
        (master_id,),
    )
    if pr:
        blockers["program_course_prereqs"] = pr
    try:
        pl = _sql_count(
            cur,
            """
            SELECT COUNT(*) FROM plo_course_master_links
            WHERE course_master_id = ?
            """,
            (master_id,),
        )
        if pl:
            blockers["plo_course_master_links"] = pl
    except Exception:
        pass
    return blockers


def _attach_course_master_usage(row: dict, usage: dict[int, dict], cur) -> None:
    mid = _i(row.get("id"))
    lc = normalize_catalog_lifecycle(row.get("catalog_lifecycle"))
    if lc == LIFECYCLE_STANDARD and title_suggests_transitional(row.get("title_ar")):
        lc = LIFECYCLE_TRANSITIONAL
    row["catalog_lifecycle"] = lc
    row["catalog_lifecycle_label"] = LIFECYCLE_LABELS_AR.get(lc, lc)
    row["catalog_note"] = str(row.get("catalog_note") or "").strip()
    row["review_after"] = str(row.get("review_after") or "").strip()
    u = usage.get(mid or -1, {})
    row["program_count"] = int(u.get("program_count") or 0)
    row["department_count"] = int(u.get("department_count") or 0)
    row["plan_row_count"] = int(u.get("plan_row_count") or 0)
    row["operational_count"] = int(u.get("operational_count") or 0)
    row["plo_link_count"] = int(u.get("plo_link_count") or 0)
    row["is_in_use"] = bool(
        row["program_count"]
        or row["plan_row_count"]
        or row["operational_count"]
        or row["plo_link_count"]
    )
    row["can_delete"] = not bool(_course_master_delete_blockers(cur, mid or 0))
    row["allow_cross_dept_link"] = lc in (LIFECYCLE_STANDARD, LIFECYCLE_SHARED)


# ---------------------------------------------------------------------------
@college_catalog_bp.route("/course_masters", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def list_course_masters():
    lifecycle_raw = (request.args.get("lifecycle") or "all").strip().lower()
    lifecycle_filter = (
        None if lifecycle_raw in ("", "all") else normalize_catalog_lifecycle(lifecycle_raw)
    )
    with get_connection() as conn:
        ensure_course_master_catalog_schema(conn)
        cur = conn.cursor()
        if is_postgresql():
            rows = _rows(cur, "SELECT * FROM course_master ORDER BY title_ar ASC")
        else:
            rows = _rows(cur, "SELECT * FROM course_master ORDER BY title_ar COLLATE NOCASE ASC")
        usage = _course_master_usage_map(cur)
        for row in rows:
            _attach_course_master_usage(row, usage, cur)
        if lifecycle_filter:
            rows = [r for r in rows if r.get("catalog_lifecycle") == lifecycle_filter]
    return jsonify({"status": "ok", "items": rows}), 200


@college_catalog_bp.route("/course_master/<int:master_id>/usage", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def course_master_usage(master_id: int):
    with get_connection() as conn:
        ensure_course_master_catalog_schema(conn)
        cur = conn.cursor()
        exists = cur.execute(
            "SELECT id, title_ar FROM course_master WHERE id = ?",
            (master_id,),
        ).fetchone()
        if not exists:
            return jsonify({"status": "error", "message": "المحتوى غير موجود"}), 404
        title_ar = (
            exists["title_ar"]
            if hasattr(exists, "keys")
            else exists[1]
        )
        plan_rows = _rows(
            cur,
            """
            SELECT d.code AS department_code,
                   d.name_ar AS department_name_ar,
                   p.id AS program_id,
                   p.code AS program_code,
                   p.name_ar AS program_name_ar,
                   pc.id AS program_course_id,
                   pc.course_code,
                   pc.level_no,
                   COALESCE(pc.requirement_scope, 'dept_common') AS requirement_scope
            FROM program_courses pc
            INNER JOIN programs p ON p.id = pc.program_id
            INNER JOIN departments d ON d.id = p.department_id
            WHERE pc.course_master_id = ?
            ORDER BY d.code, p.code, pc.course_code
            """,
            (master_id,),
        )
        operational = _rows(
            cur,
            """
            SELECT course_name, course_code, units
            FROM courses
            WHERE course_master_id = ?
            ORDER BY course_name
            """,
            (master_id,),
        )
        plo_links: list[dict] = []
        try:
            plo_links = _rows(
                cur,
                """
                SELECT p.code AS program_code,
                       d.code AS department_code,
                       o.code AS outcome_code,
                       o.title_ar AS outcome_title_ar
                FROM plo_course_master_links m
                INNER JOIN programs p ON p.id = m.program_id
                INNER JOIN departments d ON d.id = p.department_id
                INNER JOIN program_learning_outcomes o ON o.id = m.outcome_id
                WHERE m.course_master_id = ?
                ORDER BY d.code, p.code, o.code
                """,
                (master_id,),
            )
        except Exception:
            plo_links = []
        blockers = _course_master_delete_blockers(cur, master_id)
        lc_row = cur.execute(
            "SELECT catalog_lifecycle, title_ar FROM course_master WHERE id = ?",
            (master_id,),
        ).fetchone()
        lc = LIFECYCLE_STANDARD
        if lc_row:
            lc = normalize_catalog_lifecycle(
                lc_row["catalog_lifecycle"] if hasattr(lc_row, "keys") else None
            )
            title_chk = (
                lc_row["title_ar"] if hasattr(lc_row, "keys") else lc_row[1]
            )
            if lc == LIFECYCLE_STANDARD and title_suggests_transitional(title_chk):
                lc = LIFECYCLE_TRANSITIONAL
    dept_codes = sorted({r.get("department_code") for r in plan_rows if r.get("department_code")})
    return jsonify(
        {
            "status": "ok",
            "course_master_id": master_id,
            "title_ar": title_ar,
            "catalog_lifecycle": lc,
            "catalog_lifecycle_label": LIFECYCLE_LABELS_AR.get(lc, lc),
            "allow_cross_dept_link": lc in (LIFECYCLE_STANDARD, LIFECYCLE_SHARED),
            "program_count": len({r.get("program_id") for r in plan_rows}),
            "department_count": len(dept_codes),
            "plan_row_count": len(plan_rows),
            "operational_count": len(operational),
            "plo_link_count": len(plo_links),
            "can_delete": not blockers,
            "delete_blockers": blockers,
            "plan_rows": plan_rows,
            "operational_courses": operational,
            "plo_links": plo_links,
        }
    ), 200


@college_catalog_bp.route("/course_master/delete", methods=["POST"])
@role_required(*_ADMIN_FULL)
def delete_course_master():
    b = _body()
    mid = _i(b.get("id"))
    if not mid:
        return jsonify({"status": "error", "message": "id مطلوب"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        ensure_course_master_catalog_schema(conn)
        exists = cur.execute(
            "SELECT id, title_ar, catalog_lifecycle FROM course_master WHERE id = ?",
            (mid,),
        ).fetchone()
        if not exists:
            return jsonify({"status": "error", "message": "المحتوى غير موجود"}), 404
        blockers = _course_master_delete_blockers(cur, mid)
        if blockers:
            lc = LIFECYCLE_STANDARD
            try:
                if hasattr(exists, "keys"):
                    lc = normalize_catalog_lifecycle(exists["catalog_lifecycle"])
            except Exception:
                pass
            msg = (
                "لا يمكن حذف محتوى انتقالي ما زال مربوطاً بخطط أو مخرجات. "
                "أزل الربط من مقررات الخطة أولاً (لا تغيّر أسماء المقررات في التسجيل/الدرجات)."
                if lc == LIFECYCLE_TRANSITIONAL
                else "لا يمكن الحذف: المحتوى مربوط بخطط أو مخرجات. افتح «أين يُستخدم؟» ثم أزل الربط من مقررات الخطة أولاً."
            )
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": msg,
                        "delete_blockers": blockers,
                    }
                ),
                409,
            )
        cur.execute("DELETE FROM course_master WHERE id = ?", (mid,))
        conn.commit()
    return jsonify({"status": "ok", "id": mid}), 200


@college_catalog_bp.route("/course_master/implementation_meta", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def course_master_implementation_meta():
    """إرشادات المرحلة أ/ب وضمانات ما قبل التنفيذ (كتالوج فقط)."""
    reg_mode = registration_program_course_mode()
    return jsonify(
        {
            "status": "ok",
            "reg_program_course_mode": reg_mode,
            "reg_mode_ok": reg_mode in ("off", "warn"),
            "safeguards": [
                "العمل في كتالوج الكلية فقط — لا تعديل على قائمة المقررات/التسجيل/خطة التسجيل/كشف الدرجات من هنا.",
                "لا حذف محتوى يظهر مستخدماً في «أين يُستخدم؟».",
                "لا تغيير course_name في courses أو grades للمقررات الانتقالية.",
                "يُفضّل REG_PROGRAM_COURSE_MODE=warn أو off أثناء الانتقال (الحالي: "
                + reg_mode
                + ").",
            ],
            "phase_a_steps": [
                "وسم المحتوى المؤقت: حالة «انتقالي» + ملاحظة + تاريخ مراجعة.",
                "جرد عبر «أين يُستخدم؟» — لا دمج لسجلات متشابهة الاسم.",
                "تقرير الجرد الانتقالي (زر أدناه) لمعرفة ما يُحذف لاحقاً.",
            ],
            "phase_b_steps": [
                "المقررات المشتركة بين الأقسام (GS / رموز متعددة / subset): أدِرها من «سجل المقررات المشتركة» — تُزامَن تلقائياً إلى هنا.",
                "هذا القسم (course_master) للعرض والتدقيق والمحتوى القسمي والانتقالي فقط — لا إنشاء يدوي للمشترك.",
                "لا تربط برامج جديدة بمحتوى «انتقالي».",
                "بعد انتهاء الدفعة القديمة: حذف غير المستخدم فقط.",
            ],
        }
    ), 200


@college_catalog_bp.route("/course_masters/transition_audit", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def course_masters_transition_audit():
    """تقرير جرد المحتوى الانتقالي والمعياري (مرحلة أ)."""
    with get_connection() as conn:
        ensure_course_master_catalog_schema(conn)
        cur = conn.cursor()
        if is_postgresql():
            rows = _rows(cur, "SELECT * FROM course_master ORDER BY title_ar ASC")
        else:
            rows = _rows(cur, "SELECT * FROM course_master ORDER BY title_ar COLLATE NOCASE ASC")
        usage = _course_master_usage_map(cur)
        items = []
        summary = {
            "total": 0,
            "transitional": 0,
            "shared": 0,
            "standard": 0,
            "transitional_in_use": 0,
            "unused_transitional": 0,
        }
        for row in rows:
            _attach_course_master_usage(row, usage, cur)
            summary["total"] += 1
            lc = row.get("catalog_lifecycle") or LIFECYCLE_STANDARD
            summary[lc] = summary.get(lc, 0) + 1
            if lc == LIFECYCLE_TRANSITIONAL:
                if row.get("is_in_use"):
                    summary["transitional_in_use"] += 1
                else:
                    summary["unused_transitional"] += 1
            items.append(
                {
                    "id": row.get("id"),
                    "title_ar": row.get("title_ar"),
                    "catalog_lifecycle": lc,
                    "catalog_lifecycle_label": row.get("catalog_lifecycle_label"),
                    "catalog_note": row.get("catalog_note"),
                    "review_after": row.get("review_after"),
                    "program_count": row.get("program_count"),
                    "department_count": row.get("department_count"),
                    "plan_row_count": row.get("plan_row_count"),
                    "is_in_use": row.get("is_in_use"),
                    "can_delete": row.get("can_delete"),
                }
            )
    return jsonify({"status": "ok", "summary": summary, "items": items}), 200


@college_catalog_bp.route("/course_master/mark_lifecycle", methods=["POST"])
@role_required(*_ADMIN_FULL)
def course_master_mark_lifecycle():
    """وسم دفعة من سجلات المحتوى (مرحلة أ)."""
    b = _body()
    ids = b.get("ids") or []
    if not isinstance(ids, list) or not ids:
        mid = _i(b.get("id"))
        ids = [mid] if mid else []
    lifecycle = normalize_catalog_lifecycle(b.get("catalog_lifecycle"))
    note = str(b.get("catalog_note") or "").strip()
    review_after = str(b.get("review_after") or "").strip()
    sync_title = _ibool(b.get("sync_title_tag"), 0)
    updated = 0
    with get_connection() as conn:
        ensure_course_master_catalog_schema(conn)
        cur = conn.cursor()
        for raw_id in ids:
            mid = _i(raw_id)
            if not mid:
                continue
            row = cur.execute(
                "SELECT title_ar FROM course_master WHERE id = ?",
                (mid,),
            ).fetchone()
            if not row:
                continue
            title_ar = row["title_ar"] if hasattr(row, "keys") else row[0]
            if sync_title and lifecycle == LIFECYCLE_TRANSITIONAL:
                title_ar = apply_transitional_title_tag(title_ar, True)
            elif sync_title and lifecycle == LIFECYCLE_STANDARD:
                title_ar = apply_transitional_title_tag(title_ar, False)
            cur.execute(
                """
                UPDATE course_master
                SET catalog_lifecycle = ?, catalog_note = ?, review_after = ?, title_ar = ?
                WHERE id = ?
                """,
                (lifecycle, note, review_after, title_ar, mid),
            )
            updated += 1
        conn.commit()
    return jsonify({"status": "ok", "updated": updated, "catalog_lifecycle": lifecycle}), 200


@college_catalog_bp.route("/course_master/<int:master_id>/link_suggestions", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def course_master_link_suggestions(master_id: int):
    """برامج لا تملك بعد بنداً لهذا المحتوى (مرحلة ب)."""
    with get_connection() as conn:
        ensure_course_master_catalog_schema(conn)
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id, title_ar, catalog_lifecycle FROM course_master WHERE id = ?",
            (master_id,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "المحتوى غير موجود"}), 404
        lc = normalize_catalog_lifecycle(
            row["catalog_lifecycle"] if hasattr(row, "keys") else LIFECYCLE_STANDARD
        )
        if lc == LIFECYCLE_TRANSITIONAL:
            return jsonify(
                {
                    "status": "error",
                    "message": "محتوى انتقالي — لا يُربط ببرامج جديدة. أنشئ نسخة معيارية أو مشتركة.",
                    "catalog_lifecycle": lc,
                }
            ), 400
        scope = _catalog_scope_department_id(conn)
        sql = """
            SELECT p.id AS program_id, p.code AS program_code, p.name_ar AS program_name_ar,
                   d.code AS department_code, d.name_ar AS department_name_ar
            FROM programs p
            INNER JOIN departments d ON d.id = p.department_id
            WHERE COALESCE(p.is_active, 1) = 1
              AND NOT EXISTS (
                SELECT 1 FROM program_courses pc
                WHERE pc.program_id = p.id AND pc.course_master_id = ?
              )
        """
        params: list = [master_id]
        if scope is not None:
            sql += " AND p.department_id = ?"
            params.append(int(scope))
        sql += " ORDER BY d.code, p.code"
        programs = _rows(cur, sql, tuple(params))
    return jsonify(
        {
            "status": "ok",
            "course_master_id": master_id,
            "items": programs,
        }
    ), 200


@college_catalog_bp.route("/course_master/<int:master_id>/link_to_program", methods=["POST"])
@role_required(*_PLAN_EDITOR)
def course_master_link_to_program(master_id: int):
    """إضافة بند خطة لبرنامج آخر بنفس المحتوى (مرحلة ب)."""
    b = _body()
    program_id = _i(b.get("program_id"))
    course_code = str(b.get("course_code") or "").strip()
    level_no = max(0, _i(b.get("level_no"), 0) or 0)
    req_scope = normalize_requirement_scope(
        b.get("requirement_scope") or suggest_requirement_scope_for_level(level_no)
    )
    units_ov = b.get("units_override")
    if program_id is None or not course_code:
        return jsonify(
            {"status": "error", "message": "program_id ورمز المقرر في الخطة مطلوبان"}
        ), 400
    with get_connection() as conn:
        ensure_course_master_catalog_schema(conn)
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id, catalog_lifecycle, default_units FROM course_master WHERE id = ?",
            (master_id,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "المحتوى غير موجود"}), 404
        lc = normalize_catalog_lifecycle(
            row["catalog_lifecycle"] if hasattr(row, "keys") else LIFECYCLE_STANDARD
        )
        if lc == LIFECYCLE_TRANSITIONAL:
            return jsonify(
                {
                    "status": "error",
                    "message": "لا يُربط المحتوى الانتقالي ببرامج جديدة.",
                }
            ), 400
        if not _program_belongs_to_scope(conn, int(program_id)):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        default_u = int(
            row["default_units"] if hasattr(row, "keys") else (row[2] or 0)
        )
        units_ov_int = (
            _i(units_ov, default_u) if units_ov not in (None, "") else default_u
        )
        if lc == LIFECYCLE_STANDARD and _i(b.get("mark_shared"), 0):
            cur.execute(
                "UPDATE course_master SET catalog_lifecycle = ? WHERE id = ?",
                (LIFECYCLE_SHARED, master_id),
            )
        pg = is_postgresql()
        if pg:
            cur.execute(
                """
                INSERT INTO program_courses
                (program_id, course_master_id, course_code, course_name_override,
                 plan_applicability, requirement_scope, level_no, units_override,
                 category, is_required, is_active)
                VALUES (?, ?, ?, '', 'both', ?, ?, ?, 'required', 1, 1)
                ON CONFLICT (program_id, course_code) DO UPDATE SET
                  course_master_id = EXCLUDED.course_master_id,
                  requirement_scope = EXCLUDED.requirement_scope,
                  level_no = EXCLUDED.level_no,
                  units_override = EXCLUDED.units_override,
                  is_active = 1
                RETURNING id
                """,
                (
                    program_id,
                    master_id,
                    course_code,
                    req_scope,
                    level_no,
                    units_ov_int,
                ),
            )
            pcid = _row_id(cur.fetchone())
        else:
            cur.execute(
                """
                INSERT INTO program_courses
                (program_id, course_master_id, course_code, course_name_override,
                 plan_applicability, requirement_scope, level_no, units_override,
                 category, is_required, is_active)
                VALUES (?, ?, ?, '', 'both', ?, ?, ?, 'required', 1, 1)
                ON CONFLICT (program_id, course_code) DO UPDATE SET
                  course_master_id = excluded.course_master_id,
                  requirement_scope = excluded.requirement_scope,
                  level_no = excluded.level_no,
                  units_override = excluded.units_override,
                  is_active = 1
                """,
                (
                    program_id,
                    master_id,
                    course_code,
                    req_scope,
                    level_no,
                    units_ov_int,
                ),
            )
            pcid = int(
                cur.execute(
                    "SELECT id FROM program_courses WHERE program_id = ? AND course_code = ?",
                    (program_id, course_code),
                ).fetchone()[0]
            )
        conn.commit()
    return jsonify(
        {
            "status": "ok",
            "program_course_id": pcid,
            "course_master_id": master_id,
            "program_id": program_id,
            "course_code": course_code,
        }
    ), 200


def _scope_for_level(level_no: int) -> str:
    """اقتراح نطاق المتطلب من level_no (1 اتجاه عام، 2–4 قبل الشعبة، 5+ شعبة)."""
    lv = max(0, int(level_no or 0))
    if lv <= 1:
        return "college_general"
    if lv <= 4:
        return "pre_track"
    return "track"


def infer_level_from_course_code(course_code: str | None) -> int:
    """
    استنتاج المستوى من أول رقم في الجزء الرقمي لرمز المقرر.
    GE 102 → 1، ME201 → 2، PL-150 → 1
    """
    code = (course_code or "").strip().upper()
    if not code:
        return 0
    m = re.search(r"\d+", code)
    if not m:
        return 0
    digits = m.group(0)
    return int(digits[0]) if digits else 0


def suggest_requirement_scope_for_level(level_no: int) -> str:
    return _scope_for_level(level_no)


def _infer_college_general_component(course_code: str, title_ar: str) -> str:
    """تصنيف تلقائي لمقرر الاتجاه العام إلى جامعة/كلية."""
    code = (course_code or "").strip().upper()
    title = (title_ar or "").strip()
    if code.startswith(("UR", "UNI", "UNV", "U-")):
        return "university"
    if code.startswith(("CR", "COL", "C-")):
        return "college"
    if "جامعة" in title:
        return "university"
    if "كلية" in title:
        return "college"
    return "college"


def resolve_college_general_component(
    explicit: str | None,
    course_code: str,
    title_ar: str,
) -> str:
    """يُفضَّل القيمة الصريحة من الخطة، وإلا التصنيف التلقائي."""
    comp = normalize_college_general_component(explicit)
    if comp in ("university", "college"):
        return comp
    return _infer_college_general_component(course_code, title_ar)


def _college_general_component_for_scope(
    requirement_scope: str, raw_component: str | None
) -> str:
    if normalize_requirement_scope(requirement_scope) != "college_general":
        return ""
    return normalize_college_general_component(raw_component)


def _catalog_item_fields(**kwargs) -> dict:
    code = (kwargs.get("course_code") or "").strip()
    lv = infer_level_from_course_code(code)
    item = dict(kwargs)
    item["inferred_level"] = lv
    item["suggested_scope"] = suggest_requirement_scope_for_level(lv)
    return item


@college_catalog_bp.route("/department_course_catalog", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def department_course_catalog():
    """
    كتالوج مقررات القسم للاختيار في الخطة:
    - مقررات مسجّلة (جدول courses)
    - مقررات من خطط جميع برامج/تخصصات القسم (program_courses)
    """
    program_id = _i(request.args.get("program_id"))
    if program_id is None:
        return jsonify({"status": "error", "message": "program_id مطلوب"}), 400
    with get_connection() as conn:
        if not _program_belongs_to_scope(conn, int(program_id)):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        dept_id, dept_code = _program_department_id(cur, int(program_id))
        if dept_id is None:
            return jsonify(
                {"status": "error", "message": "البرنامج غير مرتبط بقسم"}
            ), 400
        cols = set()
        try:
            cols = set(fetch_table_columns(conn, "courses"))
        except Exception:
            pass
        has_owning = "owning_department_id" in cols
        has_archived = "is_archived" in cols

        by_key: dict[str, dict] = {}

        def _merge(item: dict) -> None:
            key = item.get("dedupe_key") or ""
            if not key:
                return
            prev = by_key.get(key)
            if prev is None:
                by_key[key] = item
                return
            if not prev.get("course_code") and item.get("course_code"):
                prev["course_code"] = item["course_code"]
            if not prev.get("course_master_id") and item.get("course_master_id"):
                prev["course_master_id"] = item["course_master_id"]
            if not prev.get("units") and item.get("units"):
                prev["units"] = item["units"]
            plans = prev.setdefault("plan_refs", [])
            ref = {
                "program_code": item.get("program_code"),
                "track_group": item.get("track_group"),
                "course_code": item.get("course_code"),
            }
            if ref not in plans:
                plans.append(ref)

        if has_owning:
            sel = """
                SELECT c.course_name, c.course_code, c.course_master_id, c.units,
                       cm.title_ar AS master_title_ar
                FROM courses c
                LEFT JOIN course_master cm ON cm.id = c.course_master_id
                WHERE c.owning_department_id = ?
            """
            params: tuple = (int(dept_id),)
            if has_archived:
                sel += " AND COALESCE(c.is_archived, 0) = 0"
            sel += " ORDER BY c.course_name"
            for r in _rows(cur, sel, params):
                cname = (r.get("course_name") or "").strip()
                if not cname:
                    continue
                cmid = r.get("course_master_id")
                title = (r.get("master_title_ar") or cname).strip()
                code = (r.get("course_code") or "").strip()
                units = int(r.get("units") or 0)
                key = f"cm:{cmid}" if cmid not in (None, "") else f"op:{cname}"
                label = title
                if code:
                    label += f" — {code}"
                _merge(
                    _catalog_item_fields(
                        dedupe_key=key,
                        source="courses",
                        course_master_id=int(cmid) if cmid not in (None, "") else None,
                        operational_course_name=cname if cmid in (None, "") else None,
                        title_ar=title,
                        course_code=code,
                        units=units,
                        program_code=None,
                        track_group=None,
                        label=label,
                    )
                )

        plan_rows = _rows(
            cur,
            """
            SELECT cm.id AS course_master_id,
                   COALESCE(NULLIF(trim(cm.title_ar), ''), pc.course_code) AS title_ar,
                   pc.course_code,
                   COALESCE(pc.units_override, cm.default_units, 0) AS units,
                   p.code AS program_code,
                   COALESCE(p.track_group, '') AS track_group
            FROM program_courses pc
            INNER JOIN programs p ON p.id = pc.program_id
            INNER JOIN course_master cm ON cm.id = pc.course_master_id
            WHERE p.department_id = ? AND COALESCE(pc.is_active, 1) = 1
            ORDER BY cm.title_ar, pc.course_code, p.code
            """,
            (int(dept_id),),
        )
        for r in plan_rows:
            cmid = r.get("course_master_id")
            if cmid in (None, ""):
                continue
            code = (r.get("course_code") or "").strip()
            title = (r.get("title_ar") or code).strip()
            pcode = (r.get("program_code") or "").strip()
            track = (r.get("track_group") or "").strip()
            key = f"cm:{cmid}"
            label = title
            if code:
                label += f" — {code}"
            if pcode or track:
                tg_label = track_group_label(track)
                label += f" [{pcode}{(' — ' + tg_label) if track else ''}]"
            _merge(
                _catalog_item_fields(
                    dedupe_key=key,
                    source="plan",
                    course_master_id=int(cmid),
                    operational_course_name=None,
                    title_ar=title,
                    course_code=code,
                    units=int(r.get("units") or 0),
                    program_code=pcode or None,
                    track_group=track or None,
                    label=label,
                )
            )

        registered = []
        from_plans = []
        for item in sorted(by_key.values(), key=lambda x: (x.get("title_ar") or "").lower()):
            item.pop("dedupe_key", None)
            if item.get("source") == "courses":
                registered.append(item)
            else:
                from_plans.append(item)
        reg_cm_ids = {
            int(x["course_master_id"])
            for x in registered
            if x.get("course_master_id") not in (None, "")
        }
        from_plans = [
            p
            for p in from_plans
            if p.get("course_master_id") in (None, "")
            or int(p["course_master_id"]) not in reg_cm_ids
        ]

    return jsonify(
        {
            "status": "ok",
            "program_id": program_id,
            "department_id": dept_id,
            "department_code": dept_code,
            "items": registered + from_plans,
            "groups": {
                "courses": registered,
                "plan": from_plans,
            },
        }
    ), 200


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
    lifecycle = normalize_catalog_lifecycle(b.get("catalog_lifecycle"))
    catalog_note = str(b.get("catalog_note") or "").strip()
    review_after = str(b.get("review_after") or "").strip()
    sync_title = _ibool(b.get("sync_title_tag"), 0)
    if sync_title and lifecycle == LIFECYCLE_TRANSITIONAL:
        title_ar = apply_transitional_title_tag(title_ar, True)
    elif sync_title and lifecycle == LIFECYCLE_STANDARD:
        title_ar = apply_transitional_title_tag(title_ar, False)
    if not title_ar:
        return jsonify({"status": "error", "message": "عنوان المقرر بالعربية مطلوب"}), 400
    with get_connection() as conn:
        ensure_course_master_catalog_schema(conn)
        cur = conn.cursor()
        pg = is_postgresql()
        if mid:
            cur.execute(
                """
                UPDATE course_master SET title_ar = ?, title_en = ?, description = ?, default_units = ?,
                  grading_mode = ?, assessment_type = ?,
                  catalog_lifecycle = ?, catalog_note = ?, review_after = ?
                WHERE id = ?
                """,
                (
                    title_ar,
                    title_en,
                    description,
                    units,
                    gm,
                    at,
                    lifecycle,
                    catalog_note,
                    review_after,
                    mid,
                ),
            )
        elif pg:
            cur.execute(
                """
                INSERT INTO course_master
                  (title_ar, title_en, description, default_units, grading_mode, assessment_type,
                   catalog_lifecycle, catalog_note, review_after)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (
                    title_ar,
                    title_en,
                    description,
                    units,
                    gm,
                    at,
                    lifecycle,
                    catalog_note,
                    review_after,
                ),
            )
            mid = _row_id(cur.fetchone())
        else:
            cur.execute(
                """
                INSERT INTO course_master
                  (title_ar, title_en, description, default_units, grading_mode, assessment_type,
                   catalog_lifecycle, catalog_note, review_after)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title_ar,
                    title_en,
                    description,
                    units,
                    gm,
                    at,
                    lifecycle,
                    catalog_note,
                    review_after,
                ),
            )
            mid = int(getattr(cur, "lastrowid", None) or cur.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.commit()
    return jsonify({"status": "ok", "id": mid, "catalog_lifecycle": lifecycle}), 200


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
        try:
            from backend.core.college_shared_catalog import ensure_college_shared_catalog_schema

            ensure_college_shared_catalog_schema(conn)
        except Exception:
            pass
        cur = conn.cursor()
        rows = _rows(
            cur,
            """
            SELECT pc.*, cm.title_ar AS master_title_ar,
                   COALESCE(pc.requirement_scope, 'dept_common') AS requirement_scope,
                   COALESCE(pc.college_general_component, '') AS college_general_component,
                   CASE WHEN csd.id IS NOT NULL THEN 1 ELSE 0 END AS from_shared_catalog,
                   csc.share_type AS shared_catalog_share_type,
                   csc.canonical_course_name AS shared_catalog_name
            FROM program_courses pc
            INNER JOIN course_master cm ON cm.id = pc.course_master_id
            LEFT JOIN college_shared_catalog_depts csd
              ON csd.program_course_id = pc.id AND COALESCE(csd.is_active, 1) = 1
            LEFT JOIN college_shared_catalog csc
              ON csc.id = csd.catalog_id AND COALESCE(csc.is_active, 1) = 1
            WHERE pc.program_id = ?
            ORDER BY pc.level_no, pc.course_code
            """,
            (program_id,),
        )
    return jsonify({"status": "ok", "items": rows}), 200


@college_catalog_bp.route("/program_courses/classification_summary", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def program_courses_classification_summary():
    program_id = _i(request.args.get("program_id"))
    if not program_id:
        return jsonify({"status": "error", "message": "program_id مطلوب"}), 400
    with get_connection() as conn:
        if not _program_belongs_to_scope(conn, int(program_id)):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT COALESCE(pc.requirement_scope, 'dept_common') AS requirement_scope,
                   COUNT(*) AS cnt,
                   SUM(COALESCE(pc.units_override, cm.default_units, 0)) AS units_sum
            FROM program_courses pc
            INNER JOIN course_master cm ON cm.id = pc.course_master_id
            WHERE pc.program_id = ? AND COALESCE(pc.is_active, 1) = 1
            GROUP BY COALESCE(pc.requirement_scope, 'dept_common')
            """,
            (int(program_id),),
        ).fetchall()
        by_scope: dict[str, int] = {}
        units_by_scope: dict[str, int] = {}
        total = 0
        plan_units_total = 0
        for r in rows or []:
            if hasattr(r, "keys"):
                sc = r["requirement_scope"]
                cnt = int(r["cnt"])
                u = int(r["units_sum"] or 0)
            else:
                sc, cnt, u = r[0], int(r[1]), int(r[2] or 0)
            key = str(sc or "dept_common")
            by_scope[key] = cnt
            units_by_scope[key] = u
            total += cnt
            plan_units_total += u
        prog = cur.execute(
            """
            SELECT p.id, p.code, p.name_ar, p.min_total_units, p.department_id, d.code AS department_code
            FROM programs p
            LEFT JOIN departments d ON d.id = p.department_id
            WHERE p.id = ?
            """,
            (int(program_id),),
        ).fetchone()
        prog_d = {}
        if prog:
            if hasattr(prog, "keys"):
                prog_d = {k: prog[k] for k in prog.keys()}
            else:
                prog_d = {
                    "id": prog[0],
                    "code": prog[1],
                    "name_ar": prog[2],
                    "min_total_units": prog[3],
                    "department_id": prog[4],
                    "department_code": prog[5],
                }
        reg_units = None
        reg_general_units = None
        if prog_d.get("department_id"):
            from backend.services.pathway_regulations import get_pathway_regulation_value

            reg_units = get_pathway_regulation_value(
                cur, int(prog_d["department_id"]), "dept_graduation_min_units", default=None
            )
        gen_row = cur.execute(
            "SELECT id FROM departments WHERE UPPER(TRIM(code)) = 'GENERAL' LIMIT 1"
        ).fetchone()
        if gen_row:
            gid = int(gen_row[0] if not hasattr(gen_row, "keys") else gen_row["id"])
            from backend.services.pathway_regulations import get_pathway_regulation_value

            reg_general_units = get_pathway_regulation_value(
                cur, gid, "college_general_total_units", default=None
            )
            reg_general_university_units = get_pathway_regulation_value(
                cur, gid, "college_general_university_units", default=None
            )
            reg_general_college_units = get_pathway_regulation_value(
                cur, gid, "college_general_college_units", default=None
            )
        else:
            reg_general_university_units = None
            reg_general_college_units = None
        ensure_program_course_plan_schema(conn)
        cg_rows = _rows(
            cur,
            """
            SELECT COALESCE(pc.course_code, '') AS course_code,
                   COALESCE(cm.title_ar, '') AS title_ar,
                   COALESCE(pc.college_general_component, '') AS college_general_component,
                   COALESCE(pc.units_override, cm.default_units, 0) AS units
            FROM program_courses pc
            INNER JOIN course_master cm ON cm.id = pc.course_master_id
            WHERE pc.program_id = ?
              AND COALESCE(pc.is_active, 1) = 1
              AND COALESCE(pc.requirement_scope, 'dept_common') = 'college_general'
            """,
            (int(program_id),),
        )
        college_general_units = int(units_by_scope.get("college_general", 0))
        university_general_units = 0
        college_general_only_units = 0
        for r in cg_rows:
            units = int(r.get("units") or 0)
            bucket = resolve_college_general_component(
                str(r.get("college_general_component") or ""),
                str(r.get("course_code") or ""),
                str(r.get("title_ar") or ""),
            )
            if bucket == "university":
                university_general_units += units
            else:
                college_general_only_units += units
    return jsonify(
        {
            "status": "ok",
            "program_id": program_id,
            "total": total,
            "by_scope": by_scope,
            "units_by_scope": units_by_scope,
            "plan_units_total": plan_units_total,
            "college_general_units_in_plan": college_general_units,
            "college_general_university_units_in_plan": university_general_units,
            "college_general_college_units_in_plan": college_general_only_units,
            "regulation_college_general_units": (
                int(reg_general_units) if reg_general_units is not None else None
            ),
            "regulation_college_general_university_units": (
                int(reg_general_university_units)
                if reg_general_university_units is not None
                else None
            ),
            "regulation_college_general_college_units": (
                int(reg_general_college_units)
                if reg_general_college_units is not None
                else None
            ),
            "college_general_units_ok": (
                reg_general_units is None
                or college_general_units == int(reg_general_units)
            ),
            "college_general_university_units_ok": (
                reg_general_university_units is None
                or university_general_units == int(reg_general_university_units)
            ),
            "college_general_college_units_ok": (
                reg_general_college_units is None
                or college_general_only_units == int(reg_general_college_units)
            ),
            "scope_labels": REQUIREMENT_SCOPE_LABELS,
            "program": prog_d,
            "regulation_graduation_units": reg_units,
            "units_in_sync": (
                reg_units is None
                or int(prog_d.get("min_total_units") or 0) == int(reg_units)
            ),
            "plan_units_vs_graduation_ok": (
                reg_units is None or plan_units_total == int(reg_units)
            ),
        }
    ), 200


@college_catalog_bp.route("/student_pathway_progress", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def catalog_student_pathway_progress():
    """نفس حاسبة المسار — من كتالوج الخطة (رئيس قسم)."""
    from backend.core.pathway_progress import compute_pathway_progress

    sid = (request.args.get("student_id") or "").strip()
    if not sid:
        return jsonify({"status": "error", "message": "student_id مطلوب"}), 400
    with get_connection() as conn:
        from backend.services.students import normalize_sid as _ns
        from backend.services.students import _get_allowed_student_ids_for_role

        sid = _ns(sid)
        cur = conn.cursor()
        allowed = _get_allowed_student_ids_for_role(conn, session.get("user_role"))
        if allowed is not None and sid not in allowed:
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
        result = compute_pathway_progress(cur, sid)
    if result.get("status") == "error":
        return jsonify(result), 404
    return jsonify(result), 200


@college_catalog_bp.route("/program_courses/grid", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def program_courses_grid():
    from backend.core.pathway_plan_grid import build_program_plan_grid

    program_id = _i(request.args.get("program_id"))
    if not program_id:
        return jsonify({"status": "error", "message": "program_id مطلوب"}), 400
    with get_connection() as conn:
        if not _program_belongs_to_scope(conn, int(program_id)):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        grid = build_program_plan_grid(cur, int(program_id))
    return jsonify({"status": "ok", **grid}), 200


@college_catalog_bp.route("/program_course_prereqs", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def list_program_course_prereqs():
    from backend.core.pathway_plan_grid import load_prereq_edges

    program_id = _i(request.args.get("program_id"))
    if not program_id:
        return jsonify({"status": "error", "message": "program_id مطلوب"}), 400
    with get_connection() as conn:
        if not _program_belongs_to_scope(conn, int(program_id)):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        items = load_prereq_edges(cur, int(program_id))
    return jsonify({"status": "ok", "items": items}), 200


@college_catalog_bp.route("/program_course_prereq/save", methods=["POST"])
@role_required(*_PLAN_EDITOR)
def save_program_course_prereq():
    b = _body()
    pc_id = _i(b.get("program_course_id"))
    req_pc = _i(b.get("required_program_course_id"))
    note = (b.get("note") or "").strip()[:200]
    if not pc_id or not req_pc:
        return jsonify({"status": "error", "message": "program_course_id و required_program_course_id مطلوبان"}), 400
    if pc_id == req_pc:
        return jsonify({"status": "error", "message": "لا يمكن ربط المقرر بنفسه"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT program_id FROM program_courses WHERE id = ? LIMIT 1",
            (int(pc_id),),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "بند الخطة غير موجود"}), 404
        prog_id = int(row[0] if not hasattr(row, "keys") else row["program_id"])
        if not _program_belongs_to_scope(conn, prog_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        req_row = cur.execute(
            "SELECT program_id FROM program_courses WHERE id = ? LIMIT 1",
            (int(req_pc),),
        ).fetchone()
        if not req_row or int(req_row[0] if not hasattr(req_row, "keys") else req_row["program_id"]) != prog_id:
            return jsonify({"status": "error", "message": "المتطلب السابق يجب أن يكون من نفس البرنامج"}), 400
        cur.execute(
            """
            INSERT INTO program_course_prereqs (
                program_course_id, required_program_course_id, note
            ) VALUES (?, ?, ?)
            """,
            (int(pc_id), int(req_pc), note),
        )
        conn.commit()
        rid = int(getattr(cur, "lastrowid", None) or cur.execute("SELECT last_insert_rowid()").fetchone()[0])
    return jsonify({"status": "ok", "id": rid}), 200


@college_catalog_bp.route("/program_course_prereq/delete", methods=["POST"])
@role_required(*_PLAN_EDITOR)
def delete_program_course_prereq():
    b = _body()
    rid = _i(b.get("id"))
    if not rid:
        return jsonify({"status": "error", "message": "id مطلوب"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT pc.program_id FROM program_course_prereqs pr
            INNER JOIN program_courses pc ON pc.id = pr.program_course_id
            WHERE pr.id = ?
            """,
            (int(rid),),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        prog_id = int(row[0] if not hasattr(row, "keys") else row["program_id"])
        if not _program_belongs_to_scope(conn, prog_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur.execute("DELETE FROM program_course_prereqs WHERE id = ?", (int(rid),))
        conn.commit()
    return jsonify({"status": "ok"}), 200


@college_catalog_bp.route("/program_plan/export", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def export_program_plan_excel():
    from backend.core.pathway_export import frames_for_program_plan_export

    program_id = _i(request.args.get("program_id"))
    if not program_id:
        return jsonify({"status": "error", "message": "program_id مطلوب"}), 400
    with get_connection() as conn:
        if not _program_belongs_to_scope(conn, int(program_id)):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        prow = cur.execute(
            "SELECT code FROM programs WHERE id = ? LIMIT 1",
            (int(program_id),),
        ).fetchone()
        if prow and hasattr(prow, "keys"):
            pcode = str(prow["code"] or program_id)
        elif prow:
            pcode = str(prow[0] or program_id)
        else:
            pcode = str(program_id)
        frames = frames_for_program_plan_export(cur, int(program_id), pcode)
    return excel_response_from_frames(frames, filename_prefix=f"plan_{pcode}")


@college_catalog_bp.route("/pathway_progress/export", methods=["GET"])
@role_required(*_PLAN_EDITOR)
def export_catalog_pathway_progress_excel():
    from backend.core.pathway_export import frames_for_pathway_progress_export
    from backend.core.pathway_progress import compute_pathway_progress
    from backend.services.students import normalize_sid as _ns
    from backend.services.students import _get_allowed_student_ids_for_role

    sid = _ns((request.args.get("student_id") or "").strip())
    if not sid:
        return jsonify({"status": "error", "message": "student_id مطلوب"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        allowed = _get_allowed_student_ids_for_role(conn, session.get("user_role"))
        if allowed is not None and sid not in allowed:
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
        result = compute_pathway_progress(cur, sid)
    if result.get("status") == "error":
        return jsonify(result), 404
    frames = frames_for_pathway_progress_export(result)
    return excel_response_from_frames(frames, filename_prefix=f"pathway_{sid}")


@college_catalog_bp.route("/program_courses/bulk_requirement_scope", methods=["POST"])
@role_required(*_PLAN_EDITOR)
def bulk_requirement_scope():
    b = _body()
    program_id = _i(b.get("program_id"))
    scope = normalize_requirement_scope(b.get("requirement_scope"))
    ids = [int(x) for x in (b.get("program_course_ids") or [])]
    only_level = b.get("only_level")
    try:
        only_level_i = int(only_level) if only_level not in (None, "") else None
    except (TypeError, ValueError):
        only_level_i = None
    if program_id is None:
        return jsonify({"status": "error", "message": "program_id مطلوب"}), 400
    with get_connection() as conn:
        if not _program_belongs_to_scope(conn, int(program_id)):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        if ids:
            ph = ",".join("?" * len(ids))
            cur.execute(
                f"""
                UPDATE program_courses SET requirement_scope = ?
                WHERE program_id = ? AND id IN ({ph})
                """,
                (scope, int(program_id), *ids),
            )
        elif only_level_i is not None:
            cur.execute(
                """
                UPDATE program_courses SET requirement_scope = ?
                WHERE program_id = ? AND level_no = ? AND COALESCE(is_active, 1) = 1
                """,
                (scope, int(program_id), only_level_i),
            )
        else:
            cur.execute(
                """
                UPDATE program_courses SET requirement_scope = ?
                WHERE program_id = ? AND COALESCE(is_active, 1) = 1
                """,
                (scope, int(program_id)),
            )
        updated = int(getattr(cur, "rowcount", -1) or 0)
        conn.commit()
    return jsonify({"status": "ok", "updated": updated, "requirement_scope": scope}), 200


@college_catalog_bp.route("/program_courses/apply_suggested_scope", methods=["POST"])
@role_required(*_PLAN_EDITOR)
def apply_suggested_scope():
    """اقتراح نطاق المتطلب من level_no (0–2 مشترك، 3–4 ما قبل الشعبة، 5+ شعبة)."""
    b = _body()
    program_id = _i(b.get("program_id"))
    ids = [int(x) for x in (b.get("program_course_ids") or [])]
    if program_id is None:
        return jsonify({"status": "error", "message": "program_id مطلوب"}), 400
    with get_connection() as conn:
        if not _program_belongs_to_scope(conn, int(program_id)):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        if ids:
            ph = ",".join("?" * len(ids))
            rows = cur.execute(
                f"""
                SELECT id, level_no FROM program_courses
                WHERE program_id = ? AND id IN ({ph}) AND COALESCE(is_active, 1) = 1
                """,
                (int(program_id), *ids),
            ).fetchall()
        else:
            rows = cur.execute(
                """
                SELECT id, level_no FROM program_courses
                WHERE program_id = ? AND COALESCE(is_active, 1) = 1
                """,
                (int(program_id),),
            ).fetchall()
        n = 0
        for r in rows or []:
            rid = int(r[0] if not hasattr(r, "keys") else r["id"])
            lv = int(r[1] if not hasattr(r, "keys") else r["level_no"] or 0)
            sc = _scope_for_level(lv)
            cur.execute(
                "UPDATE program_courses SET requirement_scope = ? WHERE id = ?",
                (sc, rid),
            )
            n += 1
        conn.commit()
    return jsonify({"status": "ok", "updated": n}), 200


@college_catalog_bp.route("/program_course/set_requirement_scope", methods=["POST"])
@role_required(*_PLAN_EDITOR)
def set_program_course_requirement_scope():
    b = _body()
    pcid = _i(b.get("id"))
    scope = normalize_requirement_scope(b.get("requirement_scope"))
    if pcid is None:
        return jsonify({"status": "error", "message": "id مطلوب"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT program_id FROM program_courses WHERE id = ?",
            (pcid,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "بند غير موجود"}), 404
        pid = int(row[0] if not hasattr(row, "keys") else row["program_id"])
        if not _program_belongs_to_scope(conn, pid):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        if scope != "college_general":
            cur.execute(
                """
                UPDATE program_courses
                SET requirement_scope = ?, college_general_component = ''
                WHERE id = ?
                """,
                (scope, pcid),
            )
        else:
            cur.execute(
                "UPDATE program_courses SET requirement_scope = ? WHERE id = ?",
                (scope, pcid),
            )
        conn.commit()
    return jsonify({"status": "ok", "id": pcid, "requirement_scope": scope}), 200


@college_catalog_bp.route("/program_course/set_college_general_component", methods=["POST"])
@role_required(*_PLAN_EDITOR)
def set_program_course_college_general_component():
    b = _body()
    pcid = _i(b.get("id"))
    comp = normalize_college_general_component(b.get("college_general_component"))
    if pcid is None:
        return jsonify({"status": "error", "message": "id مطلوب"}), 400
    with get_connection() as conn:
        ensure_program_course_plan_schema(conn)
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT program_id, COALESCE(requirement_scope, 'dept_common') AS requirement_scope
            FROM program_courses WHERE id = ?
            """,
            (pcid,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "بند غير موجود"}), 404
        if hasattr(row, "keys"):
            pid = int(row["program_id"])
            scope = normalize_requirement_scope(row["requirement_scope"])
        else:
            pid = int(row[0])
            scope = normalize_requirement_scope(row[1])
        if scope != "college_general":
            return jsonify(
                {
                    "status": "error",
                    "message": "نوع الاتجاه العام يُضبط فقط لمقررات نطاق «اتجاه عام»",
                }
            ), 400
        if not _program_belongs_to_scope(conn, pid):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur.execute(
            "UPDATE program_courses SET college_general_component = ? WHERE id = ?",
            (comp, pcid),
        )
        conn.commit()
    return jsonify(
        {
            "status": "ok",
            "id": pcid,
            "college_general_component": comp,
            "college_general_component_label": COLLEGE_GENERAL_COMPONENT_LABELS.get(
                comp or "auto", comp
            ),
        }
    ), 200


@college_catalog_bp.route("/program/sync_graduation_units", methods=["POST"])
@role_required(*_PLAN_EDITOR)
def sync_program_graduation_units():
    """مزامنة min_total_units للبرنامج من بند لائحة dept_graduation_min_units."""
    b = _body()
    program_id = _i(b.get("program_id"))
    if program_id is None:
        return jsonify({"status": "error", "message": "program_id مطلوب"}), 400
    with get_connection() as conn:
        if not _program_belongs_to_scope(conn, int(program_id)):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        row = cur.execute(
            "SELECT department_id, min_total_units FROM programs WHERE id = ?",
            (int(program_id),),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "برنامج غير موجود"}), 404
        dept_id = row[0] if not hasattr(row, "keys") else row["department_id"]
        old_units = int(row[1] if not hasattr(row, "keys") else row["min_total_units"] or 0)
        if dept_id is None:
            return jsonify({"status": "error", "message": "البرنامج بلا قسم"}), 400
        from backend.services.pathway_regulations import get_pathway_regulation_value

        reg = get_pathway_regulation_value(
            cur, int(dept_id), "dept_graduation_min_units", default=None
        )
        if reg is None:
            return jsonify(
                {"status": "error", "message": "بند وحدات التخرج غير معرّف في لائحة القسم"}
            ), 400
        new_units = int(reg)
        cur.execute(
            "UPDATE programs SET min_total_units = ? WHERE id = ?",
            (new_units, int(program_id)),
        )
        conn.commit()
    return jsonify(
        {
            "status": "ok",
            "program_id": program_id,
            "min_total_units": new_units,
            "previous_min_total_units": old_units,
        }
    ), 200


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
    operational_course_name = str(b.get("operational_course_name") or "").strip()
    course_master_title_ar = str(b.get("course_master_title_ar") or "").strip()
    course_code = str(b.get("course_code") or "").strip()
    name_ov = str(b.get("course_name_override") or "").strip()
    level_no = max(0, _i(b.get("level_no"), 0) or 0)
    term_hint = str(b.get("term_hint") or "").strip()
    units_ov = b.get("units_override")
    units_ov_int = None if units_ov in (None, "") else _i(units_ov, 0)
    req_scope = normalize_requirement_scope(b.get("requirement_scope"))
    cg_comp = _college_general_component_for_scope(
        req_scope, b.get("college_general_component")
    )
    plan_app = "both"  # 150/155 متوقف — لا يُستخدم في الخطة الجديدة
    category = str(b.get("category") or "required").strip() or "required"
    reqd = _ibool(b.get("is_required"), 1)
    is_act = _ibool(b.get("is_active"), 1)
    if program_id is None or not course_code:
        return jsonify(
            {"status": "error", "message": "program_id ورمز المقرر في الخطة مطلوبة"}
        ), 400
    with get_connection() as conn:
        ensure_program_course_plan_schema(conn)
        if not _program_belongs_to_scope(conn, int(program_id)):
            return jsonify({"status": "error", "message": "FORBIDDEN_PROGRAM_SCOPE"}), 403
        cur = conn.cursor()
        dept_id, _dept_code = _program_department_id(cur, int(program_id))
        if course_master_id is None and operational_course_name:
            linked = _link_operational_course_to_master(
                conn, cur, operational_course_name, dept_id
            )
            if linked is not None:
                course_master_id = linked
            else:
                return jsonify(
                    {
                        "status": "error",
                        "message": "المقرر المسجّل غير موجود في قائمة قسم البرنامج",
                    }
                ), 400
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
                  course_name_override = ?, plan_applicability = ?, requirement_scope = ?,
                  college_general_component = ?,
                  level_no = ?, term_hint = ?, units_override = ?,
                  category = ?, is_required = ?, is_active = ?
                WHERE id = ?
                """,
                (
                    program_id,
                    course_master_id,
                    course_code,
                    name_ov,
                    plan_app,
                    req_scope,
                    cg_comp,
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
                 plan_applicability, requirement_scope, college_general_component,
                 level_no, term_hint, units_override,
                 category, is_required, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (program_id, course_code) DO UPDATE SET
                  course_master_id = EXCLUDED.course_master_id,
                  course_name_override = EXCLUDED.course_name_override,
                  plan_applicability = EXCLUDED.plan_applicability,
                  requirement_scope = EXCLUDED.requirement_scope,
                  college_general_component = EXCLUDED.college_general_component,
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
                    req_scope,
                    cg_comp,
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
                 plan_applicability, requirement_scope, college_general_component,
                 level_no, term_hint, units_override,
                 category, is_required, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (program_id, course_code) DO UPDATE SET
                  course_master_id = excluded.course_master_id,
                  course_name_override = excluded.course_name_override,
                  plan_applicability = excluded.plan_applicability,
                  requirement_scope = excluded.requirement_scope,
                  college_general_component = excluded.college_general_component,
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
                    req_scope,
                    cg_comp,
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


# program_course_sections — أُلغيت (2026-03): الشعب التشغيلية عبر teaching_groups.
# المسارات /sections و/section/* محذوفة؛ استخدم /schedule_teaching_groups.
