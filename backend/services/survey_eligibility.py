"""سياسة أهلية تعبئة استبيانات أعضاء هيئة التدريس."""

from __future__ import annotations

from backend.database.database import fetch_table_columns, table_exists

# استبيانات الأستاذ الداخلية (غير مطلوبة من المتعاون خارج الكلية/الجامعة).
STANDARD_INTERNAL_INSTRUCTOR_TEMPLATES = frozenset(
    {
        "faculty_hod",
        "faculty_dean",
        "faculty_educational_process",
    }
)

# الاستبيان الوحيد المطلوب من المتعاون خارج الكلية/الجامعة.
FACULTY_EXTERNAL_COLLABORATOR_TEMPLATE = "faculty_external_collaborator"

_EXTERNAL_COLLABORATOR_SCOPES = frozenset({"outside_college", "outside_university"})


def _row_val(row, idx: int = 0, key: str | None = None):
    if row is None:
        return None
    if key and hasattr(row, "keys"):
        try:
            return row[key]
        except (KeyError, TypeError):
            pass
    try:
        return row[idx]
    except (IndexError, TypeError):
        return None


def instructor_survey_profile(conn, instructor_id: int) -> dict:
    """ملخص أهلية أستاذ للاستبيانات الداخلية."""
    iid = int(instructor_id)
    profile = {
        "instructor_id": iid,
        "department_id": None,
        "instructor_type": "internal",
        "external_scope": "within_college",
        "is_department_head": False,
        "head_department_id": None,
        "is_external_collaborator": False,
    }
    if not table_exists(conn, "instructors"):
        return profile

    cols = {c.lower() for c in fetch_table_columns(conn, "instructors")}
    select_cols = ["department_id"]
    if "type" in cols:
        select_cols.append("type")
    if "external_scope" in cols:
        select_cols.append("external_scope")
    cur = conn.cursor()
    row = cur.execute(
        f"SELECT {', '.join(select_cols)} FROM instructors WHERE id = ? LIMIT 1",
        (iid,),
    ).fetchone()
    if row:
        profile["department_id"] = _row_val(row, 0, "department_id")
        offset = 1
        if "type" in cols:
            profile["instructor_type"] = (
                str(_row_val(row, offset, "type") or "internal").strip().lower() or "internal"
            )
            offset += 1
        if "external_scope" in cols:
            profile["external_scope"] = (
                str(_row_val(row, offset, "external_scope") or "within_college").strip().lower()
                or "within_college"
            )

    inst_type = profile["instructor_type"]
    ext_scope = profile["external_scope"]
    profile["is_external_collaborator"] = (
        inst_type == "external" and ext_scope in _EXTERNAL_COLLABORATOR_SCOPES
    )

    if table_exists(conn, "users"):
        usr_cols = {c.lower() for c in fetch_table_columns(conn, "users")}
        active_sql = "1=1"
        if "is_active" in usr_cols:
            active_sql = "COALESCE(u.is_active, 1) = 1"
        head_row = cur.execute(
            f"""
            SELECT COALESCE(u.department_id, i.department_id) AS head_dept
            FROM users u
            LEFT JOIN instructors i ON i.id = u.instructor_id
            WHERE u.instructor_id = ?
              AND lower(trim(COALESCE(u.role, ''))) = 'head_of_department'
              AND {active_sql}
            LIMIT 1
            """,
            (iid,),
        ).fetchone()
        if head_row:
            head_dept = _row_val(head_row, 0, "head_dept")
            if head_dept not in (None, ""):
                try:
                    profile["head_department_id"] = int(head_dept)
                    profile["is_department_head"] = True
                except (TypeError, ValueError):
                    profile["is_department_head"] = True

    return profile


def is_instructor_template_required(
    conn,
    *,
    template_code: str,
    instructor_id: int,
    department_id: int | None,
) -> bool:
    """
    هل يُطلب هذا الاستبيان من الأستاذ؟

    - المتعاون خارج الكلية/الجامعة: يُطلب منه faculty_external_collaborator فقط.
    - رئيس القسم: لا يُطلب منه faculty_hod لقسمه.
    """
    code = (template_code or "").strip()
    if not code:
        return True

    profile = instructor_survey_profile(conn, int(instructor_id))

    if profile["is_external_collaborator"]:
        return code == FACULTY_EXTERNAL_COLLABORATOR_TEMPLATE

    if code == FACULTY_EXTERNAL_COLLABORATOR_TEMPLATE:
        return False

    if code == "faculty_hod" and profile["is_department_head"]:
        scope_dept = department_id
        if scope_dept is None:
            scope_dept = profile.get("head_department_id") or profile.get("department_id")
        head_dept = profile.get("head_department_id") or profile.get("department_id")
        if head_dept is None or scope_dept is None or int(head_dept) == int(scope_dept):
            return False

    return True
