"""اعتماد عرض مقررات الفصل — مستقل عن نشر الجدول الزمني."""
from __future__ import annotations

import datetime
import logging

from flask import Blueprint, jsonify, render_template, request, session

from backend.core.auth import _normalize_role, login_required, role_required
from backend.core.department_scope_policy import (
    resolve_college_general_department_id,
    resolve_effective_department_scope_id,
)
from backend.database.database import fetch_table_columns, table_exists
from backend.services.term_engine import (
    ensure_term_engine_tables,
    parse_ops_term,
    season_name_ar,
)
from backend.services.utilities import (
    excel_response_from_frames,
    get_connection,
    get_current_term,
    log_activity,
    pdf_response_from_html,
)
logger = logging.getLogger(__name__)

term_offerings_bp = Blueprint("term_offerings", __name__)

_EDIT_ROLES = (
    "admin",
    "admin_main",
    "system_admin",
    "college_dean",
    "academic_vice_dean",
    "head_of_department",
)
_ADMIN_ROLES = ("admin", "admin_main", "system_admin")
_WRITE_ROLES = _ADMIN_ROLES + ("head_of_department",)
_PUBLISH_ROLES = _WRITE_ROLES
COLLEGE_LIST_DEPT_ID = 0

KIND_GENERAL = "college_general"
KIND_SHARED = "shared"
KIND_DEPT = "department"
GROUP_GENERAL_LABEL = "القسم العام"
GROUP_SHARED_LABEL = "مقررات مشتركة"
STATUS_OFFERED = "offered"
STATUS_CANCELLED = "cancelled"
STATE_DRAFT = "draft"
STATE_PUBLISHED = "published"


def _actor() -> str:
    return (session.get("user") or session.get("username") or "").strip()


def _role() -> str:
    return _normalize_role((session.get("user_role") or "").strip())


def _can_publish_role(role: str | None = None) -> bool:
    return (role or _role()) in _PUBLISH_ROLES


def _can_write_offerings(role: str | None, scope) -> bool:
    r = role or _role()
    if r in _ADMIN_ROLES:
        return True
    return r == "head_of_department" and scope is not None


def _list_department_id(scope) -> int:
    if scope is None:
        return COLLEGE_LIST_DEPT_ID
    return int(scope)


def _now() -> str:
    return datetime.datetime.utcnow().isoformat()


def _current_parsed(conn) -> dict | None:
    name, year = get_current_term(conn=conn)
    return parse_ops_term(name, year)


def _ensure_offerings_schema(conn) -> None:
    try:
        ensure_term_engine_tables(conn)
        conn.commit()
    except Exception:
        logger.exception("ensure_term_engine_tables failed in term offerings")
        try:
            conn.rollback()
        except Exception:
            pass


def _state_payload(
    *,
    parsed: dict,
    state: dict,
    courses: list[dict],
    scope,
    role: str,
    previous: dict | None,
    catalog_warning: str = "",
    gen_id: int | None = None,
    general_gaps: list | None = None,
    general_published: bool = False,
    writer: bool = False,
    instructors: list[dict] | None = None,
) -> dict:
    published = (state.get("status") or "") == STATE_PUBLISHED
    can_publish = bool(writer)
    college_writer = writer and scope is None
    general_hod = (
        scope is not None
        and gen_id is not None
        and int(scope) == int(gen_id)
    )
    for c in courses:
        kind = (c.get("kind") or KIND_DEPT).strip() or KIND_DEPT
        mode = "full" if writer else "readonly"
        c["kind"] = kind
        c["edit_mode"] = mode
        c["locked"] = mode == "readonly"
    scope_note = ""
    if not writer:
        scope_note = (
            "اعتماد عرض المقررات والجداول من رئيس القسم فقط. "
            "العميد ووكيل الشؤون العلمية يطّلعان دون اعتماد."
        )
    elif general_hod:
        scope_note = (
            "تعتمد قائمة القسم العام أنت. الأقسام التخصصية تُنبَّه إن حددت مقرراً عاماً "
            "غير موجود في قائمتك بعد الاعتماد."
        )
    elif scope is not None:
        scope_note = (
            "تعتمد قائمة قسمك أنت. المقررات المشتركة ضمن نطاقك وتُحفظ مع قسمك "
            "(لتوزيع المجموعات والأعداد). مقررات القسم العام يعتمدها الاتجاه العام؛ "
            "إن حددت منها ما لم يعتمده ظهر تنبيه بعد اعتماده."
        )
    selected_general = [
        c.get("course_name")
        for c in courses
        if c.get("offered") and (c.get("kind") or "") == KIND_GENERAL
    ]
    general_pending = (
        bool(selected_general)
        and not general_hod
        and not general_published
        and scope is not None
    )
    return {
        "status": "ok",
        "term_key": parsed["term_key"],
        "ops_label": parsed.get("ops_label") or "",
        "offerings_status": state.get("status") or STATE_DRAFT,
        "published": published,
        "published_at": state.get("published_at"),
        "published_by": state.get("published_by") or "",
        "department_id": scope if scope is not None else (COLLEGE_LIST_DEPT_ID if writer else None),
        "can_publish": can_publish,
        "can_edit": can_publish,
        "college_writer": college_writer,
        "general_hod": general_hod,
        "scope_note": scope_note,
        "general_published": general_published,
        "general_pending": general_pending,
        "general_gaps": general_gaps or [],
        "courses": courses,
        "groups": _group_courses(courses),
        "instructors": instructors or [],
        "offered_count": sum(1 for c in courses if c.get("offered")),
        "previous_term": previous,
        "catalog_warning": catalog_warning,
    }


def _error_with_term(message: str, code: str, status: int = 400, **extra):
    name, year = get_current_term()
    parsed = parse_ops_term(name, year)
    payload = {
        "status": "error",
        "message": message,
        "code": code,
        "ops_label": (parsed or {}).get("ops_label") or f"{name} {year}".strip(),
        "term_name": name,
        "term_year": year,
    }
    payload.update(extra)
    return jsonify(payload), status


def _named(row, names: tuple[str, ...]) -> dict:
    if row is None:
        return {}
    out = {}
    keys_l = {}
    if hasattr(row, "keys"):
        try:
            keys_l = {str(k).lower(): k for k in row.keys()}
        except Exception:
            keys_l = {}
    for i, name in enumerate(names):
        val = None
        src = keys_l.get(name.lower())
        if src is not None:
            try:
                val = row[src]
            except Exception:
                val = None
        if val is None:
            try:
                val = row[i]
            except Exception:
                val = None
        out[name] = val
    return out


def get_offering_state(conn, term_key: str, department_id: int = COLLEGE_LIST_DEPT_ID) -> dict:
    empty = {
        "term_key": term_key or "",
        "department_id": int(department_id or 0),
        "status": STATE_DRAFT,
        "published_at": None,
        "published_by": "",
    }
    if not term_key or not table_exists(conn, "term_offering_state"):
        return empty
    row = conn.cursor().execute(
        """
        SELECT term_key, department_id, status, published_at, published_by, updated_at, updated_by
        FROM term_offering_state
        WHERE term_key = ? AND department_id = ?
        LIMIT 1
        """,
        (term_key, int(department_id or 0)),
    ).fetchone()
    data = _named(
        row,
        ("term_key", "department_id", "status", "published_at", "published_by", "updated_at", "updated_by"),
    )
    if not data.get("term_key"):
        return empty
    data["status"] = (data.get("status") or STATE_DRAFT).strip() or STATE_DRAFT
    data["department_id"] = _as_int(data.get("department_id"), int(department_id or 0))
    return data


def _offered_names_for_dept(conn, term_key: str, department_id: int) -> set[str]:
    if not term_key or not table_exists(conn, "term_course_offerings"):
        return set()
    rows = conn.cursor().execute(
        """
        SELECT course_name FROM term_course_offerings
        WHERE term_key = ? AND department_id = ? AND status = ?
        """,
        (term_key, int(department_id), STATUS_OFFERED),
    ).fetchall()
    return {str(r[0] or "").strip() for r in rows if r and str(r[0] or "").strip()}


def _published_department_ids(conn, term_key: str) -> set[int]:
    if not term_key or not table_exists(conn, "term_offering_state"):
        return set()
    rows = conn.cursor().execute(
        """
        SELECT department_id FROM term_offering_state
        WHERE term_key = ? AND status = ?
        """,
        (term_key, STATE_PUBLISHED),
    ).fetchall()
    out = set()
    for r in rows or []:
        out.add(_as_int(r[0] if not hasattr(r, "keys") else r["department_id"], COLLEGE_LIST_DEPT_ID))
    return out


def _name_is_general_request(name: str, *, general_names: set[str], shared_names: set[str]) -> bool:
    nl = (name or "").strip().lower()
    if not nl:
        return False
    if nl in shared_names:
        return False
    return nl in general_names


def published_offered_course_names(
    conn,
    *,
    term_key: str,
    department_id: int | None = None,
) -> tuple[set[str], bool]:
    """أسماء المقررات المعتمدة للتسجيل.

    قسم تخصص: قائمة القسم المعتمدة بلا مقررات العام (تبقى طلباً) ∪ قائمة القسم العام المعتمدة.
    بلا قسم (اختبارات/مسار إداري): اتحاد كل القوائم المعتمدة.
    """
    if not term_key or not table_exists(conn, "term_offering_state"):
        return set(), False
    gen_id = resolve_college_general_department_id(conn)
    if department_id is None:
        published_depts = _published_department_ids(conn, term_key)
        if not published_depts:
            return set(), False
        names: set[str] = set()
        for did in published_depts:
            names |= _offered_names_for_dept(conn, term_key, did)
        return names, True
    home = int(department_id)
    home_pub = (get_offering_state(conn, term_key, home).get("status") or "") == STATE_PUBLISHED
    if not home_pub:
        return set(), False
    home_names = _offered_names_for_dept(conn, term_key, home)
    if gen_id is not None and home == int(gen_id):
        return home_names, True
    general_names, _gcodes = _general_catalog_keys(conn)
    shared_names, _scodes = _shared_catalog_keys(conn)
    eligible = {
        n
        for n in home_names
        if not _name_is_general_request(n, general_names=general_names, shared_names=shared_names)
    }
    if gen_id is not None:
        gen_pub = (get_offering_state(conn, term_key, int(gen_id)).get("status") or "") == STATE_PUBLISHED
        if gen_pub:
            eligible |= _offered_names_for_dept(conn, term_key, int(gen_id))
    return eligible, True


def _as_int(val, default: int = 0) -> int:
    if val in (None, "", False):
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return default


def _as_optional_int(val) -> int | None:
    if val in (None, ""):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return None


def _is_archived_flag(val) -> bool:
    if val in (None, "", 0, False):
        return False
    if val is True:
        return True
    s = str(val).strip().lower()
    return s in ("1", "true", "t", "yes")


def _label_for_term_key(term_key: str) -> str:
    raw = (term_key or "").strip()
    if ":" not in raw:
        return raw
    season, year = raw.split(":", 1)
    try:
        return f"{season_name_ar(season.strip())} {year.strip()}".strip()
    except Exception:
        return raw


def _dept_name_sql(conn) -> str:
    cols = {str(c).strip().lower() for c in (fetch_table_columns(conn, "departments") or [])}
    parts = [f"d.{name}" for name in ("name_ar", "name_en", "name", "code") if name in cols]
    if not parts:
        return "''"
    return f"COALESCE({', '.join(parts)}, '')"


def _name_code_sets_from_rows(rows) -> tuple[set[str], set[str]]:
    names: set[str] = set()
    codes: set[str] = set()
    for r in rows or []:
        n = str(r[0] or "").strip().lower()
        c = str(r[1] or "").strip().lower()
        if n:
            names.add(n)
        if c:
            codes.add(c)
    return names, codes


def _shared_catalog_keys(conn) -> tuple[set[str], set[str]]:
    names: set[str] = set()
    codes: set[str] = set()
    if not table_exists(conn, "college_shared_catalog"):
        return names, codes
    try:
        from backend.core.college_shared_catalog import ensure_college_shared_catalog_schema

        ensure_college_shared_catalog_schema(conn)
    except Exception:
        pass
    cur = conn.cursor()
    n1, c1 = _name_code_sets_from_rows(
        cur.execute(
            """
            SELECT canonical_course_name, canonical_course_code
            FROM college_shared_catalog
            WHERE COALESCE(is_active, 1) = 1
            """
        ).fetchall()
    )
    names |= n1
    codes |= c1
    if table_exists(conn, "college_shared_catalog_depts"):
        n2, c2 = _name_code_sets_from_rows(
            cur.execute(
                """
                SELECT plan_course_name_override, plan_course_code
                FROM college_shared_catalog_depts
                WHERE COALESCE(is_active, 1) = 1
                """
            ).fetchall()
        )
        names |= n2
        codes |= c2
    return names, codes


def _general_catalog_keys(conn) -> tuple[set[str], set[str]]:
    names: set[str] = set()
    codes: set[str] = set()
    gen_id = resolve_college_general_department_id(conn)
    cur = conn.cursor()
    if gen_id is not None and table_exists(conn, "courses"):
        n1, c1 = _name_code_sets_from_rows(
            cur.execute(
                """
                SELECT course_name, COALESCE(course_code, '')
                FROM courses
                WHERE owning_department_id = ?
                """,
                (int(gen_id),),
            ).fetchall()
        )
        names |= n1
        codes |= c1
    if not table_exists(conn, "program_courses"):
        return names, codes
    pc_cols = {str(c).strip() for c in (fetch_table_columns(conn, "program_courses") or [])}
    if "requirement_scope" not in pc_cols:
        return names, codes
    n2, c2 = _name_code_sets_from_rows(
        cur.execute(
            """
            SELECT COALESCE(course_name_override, ''), COALESCE(course_code, '')
            FROM program_courses
            WHERE COALESCE(requirement_scope, 'dept_common') = 'college_general'
              AND COALESCE(is_active, 1) = 1
            """
        ).fetchall()
    )
    names |= n2
    codes |= c2
    if table_exists(conn, "course_master"):
        n3, c3 = _name_code_sets_from_rows(
            cur.execute(
                """
                SELECT COALESCE(cm.title_ar, ''), COALESCE(pc.course_code, '')
                FROM program_courses pc
                LEFT JOIN course_master cm ON cm.id = pc.course_master_id
                WHERE COALESCE(pc.requirement_scope, 'dept_common') = 'college_general'
                  AND COALESCE(pc.is_active, 1) = 1
                """
            ).fetchall()
        )
        names |= n3
        codes |= c3
    return names, codes


def _annotate_offering_kinds(conn, courses: list[dict]) -> list[dict]:
    try:
        shared_names, shared_codes = _shared_catalog_keys(conn)
        general_names, general_codes = _general_catalog_keys(conn)
        gen_id = resolve_college_general_department_id(conn)
    except Exception:
        logger.exception("term offerings kind classification failed")
        for c in courses:
            c.setdefault("kind", KIND_DEPT)
        return courses
    for c in courses:
        name_l = (c.get("course_name") or "").strip().lower()
        code_l = (c.get("course_code") or "").strip().lower()
        owned_general = gen_id is not None and c.get("department_id") == int(gen_id)
        is_shared = name_l in shared_names or (code_l and code_l in shared_codes)
        is_general = (
            owned_general
            or name_l in general_names
            or (code_l and code_l in general_codes)
        )
        if is_shared:
            c["kind"] = KIND_SHARED
        elif is_general:
            c["kind"] = KIND_GENERAL
        else:
            c["kind"] = KIND_DEPT
    return courses


def _catalog_courses(conn, *, department_id: int | None = None) -> list[dict]:
    """قائمة الكتالوج. أسماء الأعمدة إلزامية: dict_row في PostgreSQL يدمج COALESCE بلا AS."""
    if not table_exists(conn, "courses"):
        return []
    cols = {str(c).strip() for c in (fetch_table_columns(conn, "courses") or [])}
    has_archived = "is_archived" in cols
    has_owning = "owning_department_id" in cols
    has_code = "course_code" in cols
    has_units = "units" in cols
    has_dept_table = table_exists(conn, "departments")
    join = ""
    dept_name_expr = "''"
    order_expr = "c.course_name"
    if has_owning and has_dept_table:
        join = " LEFT JOIN departments d ON d.id = c.owning_department_id "
        dept_name_expr = _dept_name_sql(conn)
        order_expr = f"{dept_name_expr}, c.course_name"
    select = [
        "c.course_name AS course_name",
        (f"c.course_code AS course_code" if has_code else "NULL AS course_code"),
        (f"c.units AS units" if has_units else "NULL AS units"),
        (f"c.owning_department_id AS department_id" if has_owning else "NULL AS department_id"),
        f"{dept_name_expr} AS department_name",
        (f"c.is_archived AS is_archived" if has_archived else "NULL AS is_archived"),
    ]
    where = ["COALESCE(c.course_name,'') <> ''"]
    bind: list = []
    extra_sql = ""
    if department_id is not None and has_owning:
        gen_id = resolve_college_general_department_id(conn)
        if gen_id is None:
            where.append("c.owning_department_id = ?")
            bind.append(int(department_id))
        else:
            where.append(
                """
                (
                  COALESCE(c.owning_department_id, -1) IN (?, ?)
                  OR c.owning_department_id IS NULL
                  OR EXISTS (
                    SELECT 1 FROM college_shared_catalog csc
                    WHERE COALESCE(csc.is_active, 1) = 1
                      AND lower(trim(csc.canonical_course_name)) = lower(trim(c.course_name))
                  )
                )
                """
            )
            bind.extend([int(department_id), int(gen_id)])
    sql = (
        f"SELECT {', '.join(select)} FROM courses c{join}"
        f" WHERE {' AND '.join(where)}{extra_sql} ORDER BY {order_expr}"
    )
    try:
        rows = conn.cursor().execute(sql, tuple(bind)).fetchall()
    except Exception:
        logger.exception("term offerings catalog query failed; retrying without join")
        try:
            conn.rollback()
        except Exception:
            pass
        rows = conn.cursor().execute(
            """
            SELECT course_name AS course_name,
                   NULL AS course_code,
                   NULL AS units,
                   NULL AS department_id,
                   '' AS department_name,
                   NULL AS is_archived
            FROM courses
            WHERE COALESCE(course_name,'') <> ''
            ORDER BY course_name
            """
        ).fetchall()
    out = []
    names = ("course_name", "course_code", "units", "department_id", "department_name", "is_archived")
    for r in rows:
        data = _named(r, names)
        name = str(data.get("course_name") or "").strip()
        if not name:
            continue
        if _is_archived_flag(data.get("is_archived")):
            continue
        out.append(
            {
                "course_name": name,
                "course_code": str(data.get("course_code") or "").strip(),
                "units": _as_int(data.get("units"), 0),
                "department_id": _as_optional_int(data.get("department_id")),
                "department_name": str(data.get("department_name") or "").strip(),
            }
        )
    return _annotate_offering_kinds(conn, out)


def _group_courses(courses: list[dict]) -> list[dict]:
    buckets: dict[str, dict] = {}
    order: list[str] = []

    def _ensure(key: str, *, kind: str, department_id, department_name: str) -> dict:
        if key not in buckets:
            buckets[key] = {
                "key": key,
                "kind": kind,
                "department_id": department_id,
                "department_name": department_name,
                "pinned": kind in (KIND_GENERAL, KIND_SHARED),
                "courses": [],
                "offered_count": 0,
                "total": 0,
            }
            order.append(key)
        return buckets[key]

    _ensure("college_general", kind=KIND_GENERAL, department_id=None, department_name=GROUP_GENERAL_LABEL)
    _ensure("shared", kind=KIND_SHARED, department_id=None, department_name=GROUP_SHARED_LABEL)
    for c in courses:
        kind = (c.get("kind") or KIND_DEPT).strip() or KIND_DEPT
        if kind == KIND_GENERAL:
            bucket = buckets["college_general"]
        elif kind == KIND_SHARED:
            bucket = buckets["shared"]
        else:
            did = c.get("department_id")
            key = f"dept:{did}" if did is not None else "dept:none"
            label = (c.get("department_name") or "").strip() or "مقررات القسم"
            bucket = _ensure(key, kind=KIND_DEPT, department_id=did, department_name=label)
        bucket["courses"].append(c)
        bucket["total"] += 1
        if c.get("offered"):
            bucket["offered_count"] += 1
    return [buckets[k] for k in order if buckets[k]["total"] > 0]


def previous_offering_snapshot(
    conn, current_term_key: str, department_id: int | None = None
) -> dict | None:
    if not current_term_key or not table_exists(conn, "term_course_offerings"):
        return None
    if department_id is None:
        rows = conn.cursor().execute(
            """
            SELECT term_key, COUNT(*) FROM term_course_offerings
            WHERE term_key <> ? AND status = ?
            GROUP BY term_key
            """,
            (current_term_key, STATUS_OFFERED),
        ).fetchall()
    else:
        rows = conn.cursor().execute(
            """
            SELECT term_key, COUNT(*) FROM term_course_offerings
            WHERE term_key <> ? AND status = ? AND department_id = ?
            GROUP BY term_key
            """,
            (current_term_key, STATUS_OFFERED, int(department_id)),
        ).fetchall()
    candidates = []
    for r in rows or []:
        key = str(r[0] or "").strip()
        n = _as_int(r[1], 0)
        if key and n > 0:
            candidates.append((key, n))
    if not candidates:
        return None
    published: set[str] = set()
    if table_exists(conn, "term_offering_state"):
        if department_id is None:
            st = conn.cursor().execute(
                "SELECT term_key FROM term_offering_state WHERE status = ?",
                (STATE_PUBLISHED,),
            ).fetchall()
        else:
            st = conn.cursor().execute(
                """
                SELECT term_key FROM term_offering_state
                WHERE status = ? AND department_id = ?
                """,
                (STATE_PUBLISHED, int(department_id)),
            ).fetchall()
        published = {str(x[0] or "").strip() for x in st if x}
    candidates.sort(key=lambda item: (1 if item[0] in published else 0, item[0]), reverse=True)
    key, n = candidates[0]
    return {
        "term_key": key,
        "ops_label": _label_for_term_key(key),
        "offered_count": n,
        "published": key in published,
    }


def _offered_map(
    conn, term_key: str, department_id: int | None = None, *, any_department: bool = False
) -> dict[str, dict]:
    if not term_key or not table_exists(conn, "term_course_offerings"):
        return {}
    cols = {c.lower() for c in (fetch_table_columns(conn, "term_course_offerings") or [])}
    has_proposed = "proposed_instructor_id" in cols
    proposed_sel = ", proposed_instructor_id" if has_proposed else ""
    if any_department or department_id is None:
        rows = conn.cursor().execute(
            f"""
            SELECT course_name, department_id, status{proposed_sel}
            FROM term_course_offerings WHERE term_key = ?
            """,
            (term_key,),
        ).fetchall()
    else:
        rows = conn.cursor().execute(
            f"""
            SELECT course_name, department_id, status{proposed_sel}
            FROM term_course_offerings
            WHERE term_key = ? AND department_id = ?
            """,
            (term_key, int(department_id)),
        ).fetchall()
    out = {}
    for r in rows:
        name = str(r[0] or "").strip()
        if not name:
            continue
        proposed_id = None
        if has_proposed:
            proposed_id = _as_optional_int(r[3] if len(r) > 3 else None)
        out[name] = {
            "department_id": _as_optional_int(r[1]),
            "status": str(r[2] or STATUS_OFFERED).strip() or STATUS_OFFERED,
            "proposed_instructor_id": proposed_id,
        }
    return out


def _list_offering_instructors(conn, department_id: int | None) -> list[dict]:
    """أساتذة نشطون لاختيار المقترح (نطاق القسم إن وُجد، وإلا الكل)."""
    if not table_exists(conn, "instructors"):
        return []
    cols = {c.lower() for c in (fetch_table_columns(conn, "instructors") or [])}
    if "id" not in cols or "name" not in cols:
        return []
    active_sql = "COALESCE(is_active, 1) = 1" if "is_active" in cols else "1=1"
    params: list = []
    dept_sql = ""
    if department_id is not None and int(department_id) != COLLEGE_LIST_DEPT_ID and "department_id" in cols:
        dept_sql = " AND department_id = ?"
        params.append(int(department_id))
    rows = conn.cursor().execute(
        f"""
        SELECT id, COALESCE(TRIM(name), '') AS name
        FROM instructors
        WHERE {active_sql}{dept_sql}
        ORDER BY name, id
        """,
        tuple(params),
    ).fetchall()
    out = []
    for row in rows or []:
        d = dict(row) if hasattr(row, "keys") else {"id": row[0], "name": row[1]}
        iid = int(d.get("id") or 0)
        if iid <= 0:
            continue
        name = (d.get("name") or "").strip() or f"أستاذ #{iid}"
        out.append({"id": iid, "name": name})
    return out


def _instructor_names_by_id(conn, instructor_ids: list[int] | set[int]) -> dict[int, str]:
    ids = sorted({int(i) for i in (instructor_ids or []) if i and int(i) > 0})
    if not ids or not table_exists(conn, "instructors"):
        return {}
    ph = ",".join("?" for _ in ids)
    rows = conn.cursor().execute(
        f"""
        SELECT id, COALESCE(TRIM(name), '') AS name
        FROM instructors WHERE id IN ({ph})
        """,
        tuple(ids),
    ).fetchall()
    out: dict[int, str] = {}
    for row in rows or []:
        d = dict(row) if hasattr(row, "keys") else {"id": row[0], "name": row[1]}
        iid = int(d.get("id") or 0)
        if iid <= 0:
            continue
        out[iid] = (d.get("name") or "").strip() or f"أستاذ #{iid}"
    return out


def _normalize_proposed_instructors(
    raw: object,
    *,
    course_names: list[str],
) -> dict[str, int | None]:
    """خريطة اسم مقرر → معرف أستاذ مقترح (أو None لمسح الاختيار)."""
    allowed = {(n or "").strip().lower(): (n or "").strip() for n in course_names if (n or "").strip()}
    out: dict[str, int | None] = {}
    if isinstance(raw, dict):
        items = raw.items()
    elif isinstance(raw, list):
        items = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            cname = (entry.get("course_name") or "").strip()
            items.append((cname, entry.get("proposed_instructor_id")))
    else:
        return out
    for key, val in items:
        cname = (str(key) if key is not None else "").strip()
        canon = allowed.get(cname.lower())
        if not canon:
            continue
        if val in (None, "", 0, "0"):
            out[canon] = None
            continue
        try:
            iid = int(val)
        except (TypeError, ValueError):
            continue
        out[canon] = iid if iid > 0 else None
    return out


def _upsert_state(
    conn, term_key: str, department_id: int, *, status: str, actor: str, published: bool
) -> None:
    now = _now()
    did = int(department_id)
    cur = conn.cursor()
    existing = cur.execute(
        """
        SELECT term_key FROM term_offering_state
        WHERE term_key = ? AND department_id = ?
        LIMIT 1
        """,
        (term_key, did),
    ).fetchone()
    pub_at = now if published else None
    pub_by = actor if published else ""
    if existing:
        if published:
            cur.execute(
                """
                UPDATE term_offering_state
                SET status = ?, published_at = ?, published_by = ?, updated_at = ?, updated_by = ?
                WHERE term_key = ? AND department_id = ?
                """,
                (status, pub_at, pub_by, now, actor, term_key, did),
            )
        else:
            cur.execute(
                """
                UPDATE term_offering_state
                SET status = ?, published_at = NULL, published_by = '', updated_at = ?, updated_by = ?
                WHERE term_key = ? AND department_id = ?
                """,
                (status, now, actor, term_key, did),
            )
        return
    cur.execute(
        """
        INSERT INTO term_offering_state
            (term_key, department_id, status, published_at, published_by, updated_at, updated_by)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (term_key, did, status, pub_at, pub_by, now, actor),
    )


def save_offered_courses(
    conn,
    *,
    term_key: str,
    course_names: list[str],
    actor: str,
    department_id: int | None,
    proposed_instructors: dict[str, int | None] | None = None,
) -> dict:
    """يستبدل قائمة القسم بالكامل. المشترك والعام المحددان يُحفظان تحت department_id للقائمة."""
    names = []
    seen = set()
    for raw in course_names:
        n = str(raw or "").strip()
        if not n or n.lower() in seen:
            continue
        seen.add(n.lower())
        names.append(n)
    catalog = {c["course_name"]: c for c in _catalog_courses(conn)}
    catalog_l = {k.lower(): k for k in catalog}
    resolved = []
    for n in names:
        key = catalog_l.get(n.lower())
        if not key:
            continue
        resolved.append(catalog[key])
    owner_id = _list_department_id(department_id)
    cur = conn.cursor()
    now = _now()
    cols = {c.lower() for c in (fetch_table_columns(conn, "term_course_offerings") or [])}
    has_proposed = "proposed_instructor_id" in cols
    proposals = _normalize_proposed_instructors(
        proposed_instructors or {},
        course_names=[r["course_name"] for r in resolved],
    )
    cur.execute(
        "DELETE FROM term_course_offerings WHERE term_key = ? AND department_id = ?",
        (term_key, owner_id),
    )
    for rec in resolved:
        cname = rec["course_name"]
        proposed_id = proposals.get(cname)
        if has_proposed:
            cur.execute(
                """
                INSERT INTO term_course_offerings
                    (term_key, course_name, department_id, status, proposed_instructor_id,
                     created_at, created_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    term_key,
                    cname,
                    owner_id,
                    STATUS_OFFERED,
                    int(proposed_id) if proposed_id else None,
                    now,
                    actor,
                    now,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO term_course_offerings
                    (term_key, course_name, department_id, status, created_at, created_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    term_key,
                    cname,
                    owner_id,
                    STATUS_OFFERED,
                    now,
                    actor,
                    now,
                ),
            )
    state = get_offering_state(conn, term_key, owner_id)
    if (state.get("status") or STATE_DRAFT) != STATE_PUBLISHED:
        _upsert_state(conn, term_key, owner_id, status=STATE_DRAFT, actor=actor, published=False)
    else:
        _upsert_state(
            conn,
            term_key,
            owner_id,
            status=STATE_PUBLISHED,
            actor=state.get("published_by") or actor,
            published=True,
        )
        cur.execute(
            """
            UPDATE term_offering_state
            SET updated_at = ?, updated_by = ?
            WHERE term_key = ? AND department_id = ?
            """,
            (now, actor, term_key, owner_id),
        )
    conn.commit()
    return {
        "saved": len(resolved),
        "saved_department": len(resolved),
        "added_college": 0,
        "department_id": owner_id,
    }


def _write_forbidden():
    return jsonify(
        {
            "status": "error",
            "message": "اعتماد عرض المقررات من رئيس القسم فقط. العميد والوكيل يطّلعان دون اعتماد.",
            "code": "OFFERINGS_WRITE_FORBIDDEN",
        }
    ), 403


def _general_alignment(conn, term_key: str, courses: list[dict], scope, gen_id) -> tuple[list[str], bool]:
    if gen_id is None:
        return [], False
    gen_pub = (get_offering_state(conn, term_key, int(gen_id)).get("status") or "") == STATE_PUBLISHED
    gen_names = _offered_names_for_dept(conn, term_key, int(gen_id)) if gen_pub else set()
    gen_l = {n.lower() for n in gen_names}
    for c in courses:
        if (c.get("kind") or "") != KIND_GENERAL:
            c["on_general_list"] = False
            continue
        c["on_general_list"] = (c.get("course_name") or "").strip().lower() in gen_l
    gaps = []
    if (
        gen_pub
        and scope is not None
        and int(scope) != int(gen_id)
    ):
        for c in courses:
            if not c.get("offered"):
                continue
            if (c.get("kind") or "") != KIND_GENERAL:
                continue
            if not c.get("on_general_list"):
                n = (c.get("course_name") or "").strip()
                if n:
                    gaps.append(n)
    return gaps, gen_pub


@term_offerings_bp.route("/term_offerings")
@login_required
@role_required(*_EDIT_ROLES)
def term_offerings_page():
    return render_template("term_offerings.html", active_page="term_offerings")


def _preview_filter_department_id():
    raw = (request.args.get("department_id") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@term_offerings_bp.route("/term_offerings/preview")
@login_required
@role_required(*_EDIT_ROLES)
def term_offerings_preview():
    """معاينة HTML لعرض مقررات الفصل — طباعة من المتصفح."""
    with get_connection() as conn:
        ctx = prepare_term_offerings_preview_context(
            conn, filter_department_id=_preview_filter_department_id()
        )
    if not ctx.get("ok"):
        return (
            render_template(
                "term_offerings_preview.html",
                for_pdf=False,
                ok=False,
                error=ctx.get("error") or "تعذر تحميل المعاينة.",
                title="عرض مقررات الفصل",
                preview_banner_title="معاينة عرض مقررات الفصل",
                preview_hide_names_toggle=True,
                pdf_download_url="",
                rows=[],
            ),
            400,
        )
    return render_template("term_offerings_preview.html", for_pdf=False, **ctx)


@term_offerings_bp.route("/term_offerings/preview.pdf")
@login_required
@role_required(*_EDIT_ROLES)
def term_offerings_preview_pdf():
    with get_connection() as conn:
        ctx = prepare_term_offerings_preview_context(
            conn, filter_department_id=_preview_filter_department_id()
        )
    if not ctx.get("ok"):
        return jsonify({"status": "error", "message": ctx.get("error") or "تعذر التصدير"}), 400
    html = render_template("term_offerings_preview.html", for_pdf=True, **ctx)
    slug = (ctx.get("ops_label") or "offerings").replace(" ", "_")[:40]
    return pdf_response_from_html(html, filename_prefix=f"term_offerings_{slug}")


@term_offerings_bp.route("/term_offerings/preview.xlsx")
@login_required
@role_required(*_EDIT_ROLES)
def term_offerings_preview_xlsx():
    with get_connection() as conn:
        ctx = prepare_term_offerings_preview_context(
            conn, filter_department_id=_preview_filter_department_id()
        )
    if not ctx.get("ok"):
        return jsonify({"status": "error", "message": ctx.get("error") or "تعذر التصدير"}), 400
    frames = term_offerings_preview_excel_frames(ctx)
    slug = (ctx.get("ops_label") or "offerings").replace(" ", "_")[:40]
    return excel_response_from_frames(frames, filename_prefix=f"term_offerings_{slug}")


@term_offerings_bp.route("/term_offerings/state", methods=["GET"])
@login_required
@role_required(*_EDIT_ROLES)
def term_offerings_state():
    try:
        with get_connection() as conn:
            _ensure_offerings_schema(conn)
            parsed = _current_parsed(conn)
            if not parsed:
                return _error_with_term(
                    "عيّن الفصل الحالي أولاً من تشغيل الفصل.",
                    "CURRENT_TERM_UNSET",
                )
            actor = _actor()
            role = _role()
            scope = resolve_effective_department_scope_id(conn, actor)
            writer = _can_write_offerings(role, scope)
            term_key = parsed["term_key"]
            list_dept = _list_department_id(scope) if writer else None
            if writer:
                state = get_offering_state(conn, term_key, list_dept)
                offered = _offered_map(conn, term_key, list_dept)
                previous = previous_offering_snapshot(conn, term_key, list_dept)
            else:
                published_depts = _published_department_ids(conn, term_key)
                any_pub = bool(published_depts)
                sample = None
                if any_pub:
                    sample = get_offering_state(conn, term_key, next(iter(published_depts)))
                state = sample or {
                    "term_key": term_key,
                    "status": STATE_DRAFT,
                    "published_at": None,
                    "published_by": "",
                }
                if not any_pub:
                    state["status"] = STATE_DRAFT
                offered = _offered_map(conn, term_key, any_department=True)
                previous = previous_offering_snapshot(conn, term_key)
            catalog_warning = ""
            try:
                courses = _catalog_courses(conn, department_id=scope)
            except Exception:
                logger.exception("term offerings catalog failed")
                try:
                    conn.rollback()
                except Exception:
                    pass
                courses = []
                catalog_warning = (
                    "تعذر قراءة كتالوج المقررات. تحقق من ترحيل القاعدة (0009) ثم حدّث الصفحة."
                )
            for c in courses:
                rec = offered.get(c["course_name"]) or {}
                c["offered"] = (rec.get("status") or "") == STATUS_OFFERED
                pid = rec.get("proposed_instructor_id")
                c["proposed_instructor_id"] = int(pid) if pid else None
            name_map = _instructor_names_by_id(
                conn,
                [c.get("proposed_instructor_id") for c in courses if c.get("proposed_instructor_id")],
            )
            for c in courses:
                pid = c.get("proposed_instructor_id")
                c["proposed_instructor_name"] = name_map.get(int(pid), "") if pid else ""
            instructors = _list_offering_instructors(
                conn, list_dept if writer else (scope if scope is not None else None)
            )
            gen_id = resolve_college_general_department_id(conn)
            general_gaps, general_published = _general_alignment(
                conn, term_key, courses, scope, gen_id
            )
            return jsonify(
                _state_payload(
                    parsed=parsed,
                    state=state,
                    courses=courses,
                    scope=scope,
                    role=role,
                    previous=previous,
                    catalog_warning=catalog_warning,
                    gen_id=gen_id,
                    general_gaps=general_gaps,
                    general_published=general_published,
                    writer=writer,
                    instructors=instructors,
                )
            )
    except Exception:
        logger.exception("term_offerings_state failed")
        return _error_with_term(
            "تعذر تحميل عرض المقررات. إن استمر الخطأ نفّذ alembic upgrade head (0009) ثم أعد المحاولة.",
            "OFFERINGS_STATE_FAILED",
            500,
        )


@term_offerings_bp.route("/term_offerings/proposed_instructors", methods=["GET"])
@login_required
@role_required(*_EDIT_ROLES)
def term_offerings_proposed_instructors():
    """
    خريطة المقرر → أستاذ مقترح من عرض الفصل الحالي (استرشادي للجدول).
    غير إلزامي — للتمييز في قائمة اختيار الأستاذ فقط.
    """
    with get_connection() as conn:
        _ensure_offerings_schema(conn)
        parsed = _current_parsed(conn)
        if not parsed:
            return jsonify(
                {
                    "status": "ok",
                    "term_key": "",
                    "ops_label": "",
                    "by_course": {},
                }
            )
        actor = _actor()
        role = _role()
        scope = resolve_effective_department_scope_id(conn, actor)
        writer = _can_write_offerings(role, scope)
        term_key = parsed["term_key"]
        if writer:
            offered = _offered_map(conn, term_key, _list_department_id(scope))
        elif role in _ADMIN_ROLES or role in ("college_dean", "academic_vice_dean"):
            offered = _offered_map(conn, term_key, any_department=True)
        elif scope is not None:
            offered = _offered_map(conn, term_key, int(scope))
        else:
            offered = _offered_map(conn, term_key, any_department=True)
        by_course: dict[str, dict] = {}
        ids: list[int] = []
        for name, rec in (offered or {}).items():
            if (rec.get("status") or "") != STATUS_OFFERED:
                continue
            pid = rec.get("proposed_instructor_id")
            if not pid:
                continue
            try:
                iid = int(pid)
            except (TypeError, ValueError):
                continue
            if iid <= 0:
                continue
            by_course[name] = {"instructor_id": iid, "instructor_name": ""}
            ids.append(iid)
        names = _instructor_names_by_id(conn, ids)
        for payload in by_course.values():
            payload["instructor_name"] = names.get(int(payload["instructor_id"]), "") or ""
        return jsonify(
            {
                "status": "ok",
                "term_key": term_key,
                "ops_label": parsed.get("ops_label") or "",
                "by_course": by_course,
            }
        )


@term_offerings_bp.route("/term_offerings/save", methods=["POST"])
@login_required
@role_required(*_WRITE_ROLES)
def term_offerings_save():
    data = request.get_json(silent=True) or {}
    names = data.get("course_names") or data.get("offered") or []
    if not isinstance(names, list):
        return jsonify({"status": "error", "message": "course_names يجب أن تكون قائمة."}), 400
    offerings_payload = data.get("offerings")
    proposed_raw = data.get("proposed_instructors")
    if isinstance(offerings_payload, list) and not proposed_raw:
        proposed_raw = offerings_payload
        if not names:
            names = [
                (e.get("course_name") if isinstance(e, dict) else None)
                for e in offerings_payload
            ]
    with get_connection() as conn:
        _ensure_offerings_schema(conn)
        parsed = _current_parsed(conn)
        if not parsed:
            return _error_with_term("عيّن الفصل الحالي أولاً.", "CURRENT_TERM_UNSET")
        actor = _actor()
        role = _role()
        scope = resolve_effective_department_scope_id(conn, actor)
        if not _can_write_offerings(role, scope):
            return _write_forbidden()
        term_key = parsed["term_key"]
        list_dept = _list_department_id(scope)
        state = get_offering_state(conn, term_key, list_dept)
        published = (state.get("status") or "") == STATE_PUBLISHED
        course_names = [str(x) for x in names if x is not None]
        proposals = _normalize_proposed_instructors(proposed_raw, course_names=course_names)
        result = save_offered_courses(
            conn,
            term_key=term_key,
            course_names=course_names,
            actor=actor or "system",
            department_id=scope,
            proposed_instructors=proposals,
        )
        try:
            log_activity(
                action="term_offerings_save",
                details=f"term={term_key}, dept={list_dept}, count={result.get('saved')}",
            )
        except Exception:
            pass
        return jsonify(
            {
                "status": "ok",
                "saved": result.get("saved") or 0,
                "saved_department": result.get("saved_department") or 0,
                "added_college": result.get("added_college") or 0,
                "term_key": term_key,
                "ops_label": parsed.get("ops_label") or "",
                "published": published,
                "department_id": list_dept,
            }
        )


@term_offerings_bp.route("/term_offerings/publish", methods=["POST"])
@login_required
@role_required(*_PUBLISH_ROLES)
def term_offerings_publish():
    with get_connection() as conn:
        _ensure_offerings_schema(conn)
        parsed = _current_parsed(conn)
        if not parsed:
            return _error_with_term("عيّن الفصل الحالي أولاً.", "CURRENT_TERM_UNSET")
        actor = _actor() or "system"
        role = _role()
        scope = resolve_effective_department_scope_id(conn, actor)
        if not _can_write_offerings(role, scope):
            return _write_forbidden()
        term_key = parsed["term_key"]
        list_dept = _list_department_id(scope)
        offered, _ok = _count_offered(conn, term_key, list_dept)
        if offered < 1:
            return jsonify({"status": "error", "message": "اختر مقرراً واحداً على الأقل قبل اعتماد العرض."}), 400
        _upsert_state(conn, term_key, list_dept, status=STATE_PUBLISHED, actor=actor, published=True)
        conn.commit()
        try:
            log_activity(
                action="term_offerings_publish",
                details=f"term={term_key}, dept={list_dept}, offered={offered}",
            )
        except Exception:
            pass
        return jsonify(
            {
                "status": "ok",
                "published": True,
                "offered_count": offered,
                "term_key": term_key,
                "ops_label": parsed.get("ops_label") or "",
                "department_id": list_dept,
            }
        )


@term_offerings_bp.route("/term_offerings/unpublish", methods=["POST"])
@login_required
@role_required(*_PUBLISH_ROLES)
def term_offerings_unpublish():
    with get_connection() as conn:
        _ensure_offerings_schema(conn)
        parsed = _current_parsed(conn)
        if not parsed:
            return _error_with_term("عيّن الفصل الحالي أولاً.", "CURRENT_TERM_UNSET")
        actor = _actor() or "system"
        role = _role()
        scope = resolve_effective_department_scope_id(conn, actor)
        if not _can_write_offerings(role, scope):
            return _write_forbidden()
        term_key = parsed["term_key"]
        list_dept = _list_department_id(scope)
        _upsert_state(conn, term_key, list_dept, status=STATE_DRAFT, actor=actor, published=False)
        conn.commit()
        try:
            log_activity(
                action="term_offerings_unpublish",
                details=f"term={term_key}, dept={list_dept}",
            )
        except Exception:
            pass
        return jsonify(
            {
                "status": "ok",
                "published": False,
                "term_key": term_key,
                "ops_label": parsed.get("ops_label") or "",
                "department_id": list_dept,
            }
        )


@term_offerings_bp.route("/term_offerings/copy_previous", methods=["POST"])
@login_required
@role_required(*_WRITE_ROLES)
def term_offerings_copy_previous():
    with get_connection() as conn:
        _ensure_offerings_schema(conn)
        parsed = _current_parsed(conn)
        if not parsed:
            return _error_with_term("عيّن الفصل الحالي أولاً.", "CURRENT_TERM_UNSET")
        actor = _actor()
        role = _role()
        scope = resolve_effective_department_scope_id(conn, actor)
        if not _can_write_offerings(role, scope):
            return _write_forbidden()
        term_key = parsed["term_key"]
        list_dept = _list_department_id(scope)
        prev = previous_offering_snapshot(conn, term_key, list_dept)
        if not prev:
            return jsonify(
                {
                    "status": "error",
                    "message": "لا يوجد عرض سابق لنسخه.",
                    "code": "NO_PREVIOUS_OFFERING",
                }
            ), 404
        names_rows = conn.cursor().execute(
            """
            SELECT course_name, proposed_instructor_id FROM term_course_offerings
            WHERE term_key = ? AND status = ? AND department_id = ?
            """,
            (prev["term_key"], STATUS_OFFERED, list_dept),
        ).fetchall()
        names = []
        proposals: dict[str, int | None] = {}
        for r in names_rows or []:
            cname = str(r[0] or "").strip()
            if not cname:
                continue
            names.append(cname)
            try:
                pid = int(r[1]) if r[1] is not None else None
            except (TypeError, ValueError):
                pid = None
            proposals[cname] = pid if pid and pid > 0 else None
        result = save_offered_courses(
            conn,
            term_key=term_key,
            course_names=names,
            actor=actor or "system",
            department_id=scope,
            proposed_instructors=proposals,
        )
        try:
            log_activity(
                action="term_offerings_copy_previous",
                details=f"term={term_key}, dept={list_dept}, from={prev['term_key']}, count={result.get('saved')}",
            )
        except Exception:
            pass
        return jsonify(
            {
                "status": "ok",
                "saved": result.get("saved") or 0,
                "saved_department": result.get("saved_department") or 0,
                "added_college": result.get("added_college") or 0,
                "term_key": term_key,
                "ops_label": parsed.get("ops_label") or "",
                "source": prev,
                "department_id": list_dept,
            }
        )


@term_offerings_bp.route("/term_offerings/general_requests", methods=["GET"])
@login_required
@role_required(*_EDIT_ROLES)
def term_offerings_general_requests():
    """ما طلبته الأقسام من مقررات القسم العام — قراءة فقط، بلا اعتماد ثانٍ."""
    from backend.services.term_offering_alerts import general_requests_summary

    with get_connection() as conn:
        _ensure_offerings_schema(conn)
        parsed = _current_parsed(conn)
        if not parsed:
            return _error_with_term("عيّن الفصل الحالي أولاً.", "CURRENT_TERM_UNSET")
        actor = _actor()
        role = _role()
        scope = resolve_effective_department_scope_id(conn, actor)
        gen_id = resolve_college_general_department_id(conn)
        is_general_hod = (
            scope is not None and gen_id is not None and int(scope) == int(gen_id)
        )
        if not (is_general_hod or role in _ADMIN_ROLES or role in ("college_dean", "academic_vice_dean")):
            return jsonify(
                {
                    "status": "error",
                    "message": "هذه اللوحة لرئيس الاتجاه العام.",
                    "code": "GENERAL_SCOPE_ONLY",
                }
            ), 403
        payload = general_requests_summary(conn, term_key=parsed["term_key"])
        payload["status"] = "ok"
        payload["ops_label"] = parsed.get("ops_label") or ""
        payload["general_hod"] = is_general_hod
        return jsonify(payload)


@term_offerings_bp.route("/term_offerings/orphans", methods=["GET"])
@login_required
@role_required(*_EDIT_ROLES)
def term_offerings_orphans():
    """تسجيلات قائمة لمقررات خرجت من القوائم المعتمدة."""
    from backend.services.term_offering_alerts import orphan_registrations

    with get_connection() as conn:
        _ensure_offerings_schema(conn)
        parsed = _current_parsed(conn)
        if not parsed:
            return _error_with_term("عيّن الفصل الحالي أولاً.", "CURRENT_TERM_UNSET")
        scope = resolve_effective_department_scope_id(conn, _actor())
        payload = orphan_registrations(
            conn, term_key=parsed["term_key"], department_id=scope
        )
        payload["status"] = "ok"
        payload["ops_label"] = parsed.get("ops_label") or ""
        payload["department_id"] = scope
        return jsonify(payload)


@term_offerings_bp.route("/term_offerings/orphans/notify", methods=["POST"])
@login_required
@role_required(*_WRITE_ROLES)
def term_offerings_orphans_notify():
    """ينبّه المتأثرين ويفتح لهم إسقاط/إضافة محدوداً — لا يفتح التسجيل للكل."""
    from backend.services.term_offering_alerts import notify_orphan_registrations

    data = request.get_json(silent=True) or {}
    try:
        days = int(data.get("days") or 7)
    except (TypeError, ValueError):
        days = 7
    open_window = data.get("open_window")
    with get_connection() as conn:
        _ensure_offerings_schema(conn)
        parsed = _current_parsed(conn)
        if not parsed:
            return _error_with_term("عيّن الفصل الحالي أولاً.", "CURRENT_TERM_UNSET")
        actor = _actor()
        role = _role()
        scope = resolve_effective_department_scope_id(conn, actor)
        if not _can_write_offerings(role, scope):
            return _write_forbidden()
        result = notify_orphan_registrations(
            conn,
            term_key=parsed["term_key"],
            actor=actor or "system",
            department_id=scope,
            days=max(1, min(days, 30)),
            open_window=True if open_window is None else bool(open_window),
        )
        try:
            log_activity(
                action="term_offerings_orphans_notify",
                details=(
                    f"term={parsed['term_key']}, dept={scope}, "
                    f"students={result.get('students')}, exceptions={result.get('exceptions')}"
                ),
            )
        except Exception:
            pass
        result["status"] = "ok"
        result["ops_label"] = parsed.get("ops_label") or ""
        return jsonify(result)


def _count_offered(conn, term_key: str, department_id: int) -> tuple[int, bool]:
    if not table_exists(conn, "term_course_offerings"):
        return 0, False
    row = conn.cursor().execute(
        """
        SELECT COUNT(*) FROM term_course_offerings
        WHERE term_key = ? AND department_id = ? AND status = ?
        """,
        (term_key, int(department_id), STATUS_OFFERED),
    ).fetchone()
    n = _as_int(row[0] if row else 0, 0)
    return n, True


def _kind_label_ar(kind: str) -> str:
    k = (kind or "").strip()
    if k == KIND_GENERAL:
        return "قسم عام"
    if k == KIND_SHARED:
        return "مشترك"
    return "قسم"


def _department_label(conn, department_id: int | None) -> str:
    if department_id is None or int(department_id) == COLLEGE_LIST_DEPT_ID:
        return "الكلية / كل الأقسام"
    if not table_exists(conn, "departments"):
        return f"قسم #{int(department_id)}"
    cols = {str(c).strip().lower() for c in (fetch_table_columns(conn, "departments") or [])}
    parts = [name for name in ("name_ar", "name_en", "name", "code") if name in cols]
    if not parts:
        return f"قسم #{int(department_id)}"
    expr = "COALESCE(" + ", ".join(
        f"NULLIF(TRIM(CAST({p} AS TEXT)), '')" for p in parts
    ) + f", 'قسم #{int(department_id)}')"
    row = conn.cursor().execute(
        f"SELECT {expr} FROM departments WHERE id = ? LIMIT 1",
        (int(department_id),),
    ).fetchone()
    if not row:
        return f"قسم #{int(department_id)}"
    return str(row[0] or f"قسم #{int(department_id)}")


def _offering_enrollment_counts(
    conn,
    *,
    course_names: list[str],
    semester: str,
) -> dict[str, int]:
    """
    عدد المسجّلين الأحياء لكل مقرر معروض في الفصل الحالي.
    يفضّل مجموعات التدريس إن وُجدت للفصل، وإلا العدّ باسم المقرر.
    طلبة نشطون فقط عند توفر enrollment_status. المقررات بلا تسجيل → 0.
    """
    names = sorted({(n or "").strip() for n in (course_names or []) if (n or "").strip()})
    if not names or not table_exists(conn, "registrations"):
        return {n: 0 for n in names}

    sem = (semester or "").strip()
    reg_cols = {c.lower() for c in (fetch_table_columns(conn, "registrations") or [])}
    stu_cols = (
        {c.lower() for c in (fetch_table_columns(conn, "students") or [])}
        if table_exists(conn, "students")
        else set()
    )
    active_only = "enrollment_status" in stu_cols
    active_sql = (
        " AND COALESCE(s.enrollment_status, 'active') = 'active'"
        if active_only
        else " AND COALESCE(r.student_id, '') <> ''"
    )
    join_stu = " LEFT JOIN students s ON s.student_id = r.student_id "

    sem_sql = ""
    sem_params: list = []
    if sem and "semester" in reg_cols:
        sem_sql = """
          AND (
            lower(trim(COALESCE(r.semester, ''))) = lower(trim(?))
            OR trim(COALESCE(r.semester, '')) = ''
          )
        """
        sem_params.append(sem)

    out: dict[str, int] = {n: 0 for n in names}
    name_key = {n.lower(): n for n in names}
    placeholders = ",".join("?" for _ in names)
    lower_names = [n.lower() for n in names]
    cur = conn.cursor()

    use_tg = (
        sem
        and "teaching_group_id" in reg_cols
        and table_exists(conn, "teaching_groups")
    )
    courses_with_tg: set[str] = set()
    if use_tg:
        tg_rows = cur.execute(
            f"""
            SELECT id, course_name FROM teaching_groups
            WHERE is_active = 1
              AND lower(trim(COALESCE(semester, ''))) = lower(trim(?))
              AND lower(trim(course_name)) IN ({placeholders})
            """,
            (sem, *lower_names),
        ).fetchall()
        all_tg_ids: list[int] = []
        for row in tg_rows or []:
            d = dict(row) if hasattr(row, "keys") else {"id": row[0], "course_name": row[1]}
            cname = (d.get("course_name") or "").strip()
            key = cname.lower()
            if key not in name_key:
                continue
            tid = int(d.get("id") or 0)
            if tid <= 0:
                continue
            courses_with_tg.add(key)
            all_tg_ids.append(tid)

        if all_tg_ids:
            tg_ph = ",".join("?" for _ in all_tg_ids)
            rows = cur.execute(
                f"""
                SELECT lower(trim(tg.course_name)) AS ckey,
                       COUNT(DISTINCT r.student_id) AS student_count
                FROM registrations r
                JOIN teaching_groups tg ON tg.id = r.teaching_group_id
                {join_stu}
                WHERE r.teaching_group_id IN ({tg_ph})
                  {active_sql}
                  {sem_sql}
                GROUP BY lower(trim(tg.course_name))
                """,
                tuple(all_tg_ids) + tuple(sem_params),
            ).fetchall()
            for row in rows or []:
                d = dict(row) if hasattr(row, "keys") else {"ckey": row[0], "student_count": row[1]}
                key = (d.get("ckey") or "").strip().lower()
                canon = name_key.get(key)
                if canon:
                    out[canon] = int(d.get("student_count") or 0)

    fallback_names = [name_key[k] for k in name_key if k not in courses_with_tg]
    if fallback_names:
        fb_lower = [n.lower() for n in fallback_names]
        fb_ph = ",".join("?" for _ in fallback_names)
        rows = cur.execute(
            f"""
            SELECT lower(trim(r.course_name)) AS ckey,
                   COUNT(DISTINCT r.student_id) AS student_count
            FROM registrations r
            {join_stu}
            WHERE lower(trim(r.course_name)) IN ({fb_ph})
              {active_sql}
              {sem_sql}
            GROUP BY lower(trim(r.course_name))
            """,
            tuple(fb_lower) + tuple(sem_params),
        ).fetchall()
        for row in rows or []:
            d = dict(row) if hasattr(row, "keys") else {"ckey": row[0], "student_count": row[1]}
            key = (d.get("ckey") or "").strip().lower()
            canon = name_key.get(key)
            if canon:
                out[canon] = int(d.get("student_count") or 0)

    return out


def prepare_term_offerings_preview_context(
    conn,
    *,
    filter_department_id: int | None = None,
    actor: str | None = None,
    role: str | None = None,
) -> dict:
    """
    سياق معاينة/طباعة عرض مقررات الفصل الحالي.
    يعرض المقررات المختارة في قائمة القسم؛ يميّز المعتمد عن المسودة.
    """
    from backend.core.arabic_export import pdf_arabic_extra_css

    _ensure_offerings_schema(conn)
    parsed = _current_parsed(conn)
    if not parsed:
        return {
            "ok": False,
            "error": "عيّن الفصل الحالي أولاً من تشغيل الفصل.",
            "error_code": "CURRENT_TERM_UNSET",
        }

    try:
        actor_name = (actor if actor is not None else _actor()).strip()
    except RuntimeError:
        actor_name = (actor or "").strip()
    try:
        role_name = _normalize_role((role if role is not None else _role()) or "")
    except RuntimeError:
        role_name = _normalize_role((role or "").strip())
    scope = resolve_effective_department_scope_id(conn, actor_name)
    writer = _can_write_offerings(role_name, scope)
    can_pick = role_name in _ADMIN_ROLES or role_name in ("college_dean", "academic_vice_dean")
    term_key = parsed["term_key"]
    ops_label = parsed.get("ops_label") or term_key

    if writer:
        list_dept = _list_department_id(scope)
    elif can_pick and filter_department_id is not None:
        list_dept = int(filter_department_id)
    elif can_pick:
        list_dept = None
    elif scope is not None:
        list_dept = int(scope)
    else:
        list_dept = COLLEGE_LIST_DEPT_ID

    rows: list[dict] = []
    states: list[dict] = []
    if list_dept is not None:
        state = get_offering_state(conn, term_key, list_dept)
        states.append(state)
        offered = _offered_map(conn, term_key, list_dept)
        catalog_scope = None if int(list_dept) == COLLEGE_LIST_DEPT_ID else int(list_dept)
        catalog = _annotate_offering_kinds(
            conn, _catalog_courses(conn, department_id=catalog_scope)
        )
        by_name = {c["course_name"]: c for c in catalog}
        for name, rec in sorted(offered.items(), key=lambda x: x[0]):
            if (rec.get("status") or "") != STATUS_OFFERED:
                continue
            c = by_name.get(name) or {
                "course_name": name,
                "course_code": "",
                "units": None,
                "kind": KIND_DEPT,
                "department_name": "",
            }
            kind = (c.get("kind") or KIND_DEPT).strip() or KIND_DEPT
            rows.append(
                {
                    "course_name": name,
                    "course_code": (c.get("course_code") or "") or "—",
                    "units": c.get("units") if c.get("units") is not None else "—",
                    "kind": kind,
                    "kind_label": _kind_label_ar(kind),
                    "department_name": (c.get("department_name") or "").strip() or "—",
                    "proposed_instructor_id": rec.get("proposed_instructor_id"),
                    "proposed_instructor_name": "",
                }
            )
        department_label = _department_label(conn, list_dept)
        is_published = (state.get("status") or "") == STATE_PUBLISHED
        published_at = state.get("published_at") or ""
        published_by = state.get("published_by") or ""
    else:
        published_depts = sorted(_published_department_ids(conn, term_key))
        catalog = _annotate_offering_kinds(conn, _catalog_courses(conn, department_id=None))
        by_name = {c["course_name"]: c for c in catalog}
        seen: set[str] = set()
        for did in published_depts:
            st = get_offering_state(conn, term_key, did)
            states.append(st)
            offered = _offered_map(conn, term_key, did)
            for name, rec in offered.items():
                if (rec.get("status") or "") != STATUS_OFFERED:
                    continue
                if name in seen:
                    continue
                seen.add(name)
                c = by_name.get(name) or {
                    "course_name": name,
                    "course_code": "",
                    "units": None,
                    "kind": KIND_DEPT,
                    "department_name": "",
                }
                kind = (c.get("kind") or KIND_DEPT).strip() or KIND_DEPT
                rows.append(
                    {
                        "course_name": name,
                        "course_code": (c.get("course_code") or "") or "—",
                        "units": c.get("units") if c.get("units") is not None else "—",
                        "kind": kind,
                        "kind_label": _kind_label_ar(kind),
                        "department_name": (c.get("department_name") or "").strip()
                        or _department_label(conn, did),
                        "proposed_instructor_id": rec.get("proposed_instructor_id"),
                        "proposed_instructor_name": "",
                    }
                )
        rows.sort(key=lambda r: ((r.get("department_name") or ""), r.get("course_name") or ""))
        department_label = "كل الأقسام المعتمدة"
        is_published = bool(published_depts)
        published_at = next((s.get("published_at") for s in states if s.get("published_at")), "") or ""
        published_by = next((s.get("published_by") for s in states if s.get("published_by")), "") or ""

    proposed_name_map = _instructor_names_by_id(
        conn,
        [r.get("proposed_instructor_id") for r in rows if r.get("proposed_instructor_id")],
    )
    for r in rows:
        pid = r.get("proposed_instructor_id")
        r["proposed_instructor_name"] = (
            proposed_name_map.get(int(pid), "") if pid else ""
        ) or "—"

    enroll_map = _offering_enrollment_counts(
        conn,
        course_names=[r.get("course_name") or "" for r in rows],
        semester=ops_label,
    )
    total_enrolled = 0
    for r in rows:
        n = int(enroll_map.get(r.get("course_name") or "", 0) or 0)
        r["enrolled_count"] = n
        total_enrolled += n

    status_ar = "معتمد" if is_published else "مسودة (غير معتمد)"
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    qs = f"?department_id={int(list_dept)}" if list_dept is not None else ""
    base_footer = (
        "قائمة معتمدة للتسجيل — ليست جدولاً زمنياً. "
        "عمود الأستاذ المقترح استرشادي فقط وليس تعييناً نهائياً."
        if is_published
        else "مسودة غير معتمدة — لا تُستخدم وثيقة رسمية للتسجيل حتى يتم الاعتماد. "
        "عمود الأستاذ المقترح استرشادي فقط."
    )
    return {
        "ok": True,
        "title": "عرض مقررات الفصل المعتمد",
        "term_key": term_key,
        "ops_label": ops_label,
        "department_id": list_dept,
        "department_label": department_label,
        "is_published": is_published,
        "status_ar": status_ar,
        "published_at": published_at or "—",
        "published_by": published_by or "—",
        "rows": rows,
        "course_count": len(rows),
        "total_enrolled": total_enrolled,
        "export_date": now,
        "generated_at": now,
        "preview_banner_title": "معاينة عرض مقررات الفصل",
        "preview_hide_names_toggle": True,
        "pdf_download_url": f"/term_offerings/preview.pdf{qs}",
        "pdf_arabic_css": pdf_arabic_extra_css(for_pdf=False),
        "pdf_arabic_css_print": pdf_arabic_extra_css(for_pdf=True),
        "can_pick_department": can_pick,
        "footer_note": (
            f"{base_footer} "
            f"إجمالي المسجّلين (مجموع الصفوف): {total_enrolled} — تاريخ الطباعة: {now}."
        ),
    }


def term_offerings_preview_excel_frames(ctx: dict) -> list[tuple[str, object]]:
    import pandas as pd

    rows = ctx.get("rows") or []
    df = pd.DataFrame(
        [
            {
                "الرمز": r.get("course_code") or "",
                "المقرر": r.get("course_name") or "",
                "الوحدات": r.get("units") if r.get("units") is not None else "",
                "التصنيف": r.get("kind_label") or "",
                "القسم": r.get("department_name") or "",
                "أستاذ مقترح": (
                    r.get("proposed_instructor_name")
                    if (r.get("proposed_instructor_name") or "") not in ("", "—")
                    else ""
                ),
                "عدد المسجّلين": int(r.get("enrolled_count") or 0),
            }
            for r in rows
        ]
    )
    meta = pd.DataFrame(
        [
            {"البند": "الفصل", "القيمة": ctx.get("ops_label") or ""},
            {"البند": "النطاق", "القيمة": ctx.get("department_label") or ""},
            {"البند": "الحالة", "القيمة": ctx.get("status_ar") or ""},
            {"البند": "تاريخ الاعتماد", "القيمة": ctx.get("published_at") or ""},
            {"البند": "اعتمد بواسطة", "القيمة": ctx.get("published_by") or ""},
            {"البند": "عدد المقررات", "القيمة": ctx.get("course_count") or 0},
            {"البند": "إجمالي المسجّلين", "القيمة": ctx.get("total_enrolled") or 0},
            {"البند": "تاريخ التصدير", "القيمة": ctx.get("export_date") or ""},
        ]
    )
    return [("الغلاف", meta), ("المقررات", df)]
