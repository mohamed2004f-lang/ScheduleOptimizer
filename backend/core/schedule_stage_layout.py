"""تصنيف وعرض مصفوفة الجدول (عرض فقط — لا يغيّر صفوف schedule).

أعمدة الشبكة الثلاثة = مسارات تعبئة متوازنة (ليس محتوى سنة دراسية).
stage_bucket الأكاديمي يبقى للشارات فقط.
"""

from __future__ import annotations

import re
from typing import Any

# شارات/توافق قديم — لا تُستخدم لتعيين عمود العرض
BUCKET_GENERAL_OR_Y1 = "general_or_y1"
BUCKET_Y3 = "y3"
BUCKET_Y4Y5 = "y4y5"

STAGE_BUCKETS = (BUCKET_GENERAL_OR_Y1, BUCKET_Y3, BUCKET_Y4Y5)

STAGE_BUCKET_LABELS = {
    BUCKET_GENERAL_OR_Y1: "اتجاه عام + السنة الأولى بالقسم",
    BUCKET_Y3: "المرحلة الثالثة",
    BUCKET_Y4Y5: "الرابعة + الخامسة",
}

# أعمدة التعبئة البصرية في مصفوفة الأقسام العلمية
PACK_COL_1 = "pack_1"
PACK_COL_2 = "pack_2"
PACK_COL_3 = "pack_3"
PACK_COLUMNS = (PACK_COL_1, PACK_COL_2, PACK_COL_3)
PACK_COLUMN_LABEL = "مقررات دراسية"
PACK_COLUMN_LABELS = {c: PACK_COLUMN_LABEL for c in PACK_COLUMNS}

LAYOUT_STAGE_MATRIX = "stage_matrix"
LAYOUT_PERSONAL_WEEKLY = "personal_weekly"


def classify_stage_bucket(
    *,
    course_code: str | None = None,
    is_college_general: bool = False,
) -> str:
    """
    تصنيف أكاديمي للشارة فقط (لا يحدد عمود العرض).
    الاتجاه العام → general_or_y1؛ وإلا حسب أول رقم في الرمز.
    """
    if is_college_general:
        return BUCKET_GENERAL_OR_Y1
    from backend.services.college_catalog import infer_level_from_course_code

    level = int(infer_level_from_course_code(course_code) or 0)
    if level <= 2:
        return BUCKET_GENERAL_OR_Y1
    if level == 3:
        return BUCKET_Y3
    return BUCKET_Y4Y5


def course_pack_sort_key(row: dict[str, Any] | None) -> tuple:
    """اتجاه عام أولاً، ثم أقل رمز رقمي، ثم الرمز، ثم الاسم."""
    item = row or {}
    is_gen = 0 if item.get("is_college_general") else 1
    code = str(item.get("course_code") or "").strip().upper()
    m = re.search(r"\d+", code)
    num = int(m.group(0)) if m else 10**9
    name = str(item.get("course_name") or "").strip().lower()
    return (is_gen, num, code, name)


def assign_pack_display_columns(
    courses: list[dict[str, Any]] | None,
    *,
    column_count: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """
    توزيع مقررات نفس اليوم/الوقت على أعمدة التعبئة:
    ترتيب (عام ثم أقل رمز) → العمود الأقل ازدحاماً (تعادل → عمود أصغر رقماً).
    """
    n = max(1, int(column_count or 3))
    ids = tuple(f"pack_{i}" for i in range(1, n + 1))
    cols: dict[str, list[dict[str, Any]]] = {cid: [] for cid in ids}
    ordered = sorted(list(courses or []), key=course_pack_sort_key)
    for row in ordered:
        best = min(range(1, n + 1), key=lambda i: (len(cols[f"pack_{i}"]), i))
        cols[f"pack_{best}"].append(row)
    return cols


def stage_badge_for_row(
    *,
    course_code: str | None = None,
    is_college_general: bool = False,
) -> str:
    """شارة صغيرة داخل الكتلة الأولى: عام | قسم 2 | غير مصنّف."""
    if is_college_general:
        return "عام"
    from backend.services.college_catalog import infer_level_from_course_code

    level = int(infer_level_from_course_code(course_code) or 0)
    if level == 2:
        return "قسم 2"
    if level <= 0:
        return "غير مصنّف"
    if level == 1:
        return "مستوى 1"
    return ""


def resolve_schedule_layout_mode(
    conn,
    actor_username: str | None = None,
    *,
    department_id: int | None = None,
) -> str:
    """
    stage_matrix: قسم تخصصي (نطاق قسم ≠ GENERAL).
    personal_weekly: رئيس الاتجاه العام، أو بلا نطاق قسم (أدمن بدون فلتر).
    department_id: تجاوز اختياري لنطاق الجلسة (فلتر صفحة التعارضات).
    """
    from backend.core.department_scope_policy import (
        actor_manages_college_general_scope,
        resolve_effective_department_scope_id,
    )
    from backend.database.database import table_exists

    if department_id is not None:
        dep = int(department_id)
        if dep <= 0:
            return LAYOUT_PERSONAL_WEEKLY
        if table_exists(conn, "departments"):
            row = conn.cursor().execute(
                "SELECT COALESCE(code, ''), COALESCE(name_en, '') FROM departments WHERE id = ? LIMIT 1",
                (dep,),
            ).fetchone()
            if row:
                code = str(row[0] or "").strip().upper()
                name_en = str(row[1] or "").strip().upper()
                if code in ("GENERAL", "GEN", "GS") or "GENERAL" in name_en:
                    return LAYOUT_PERSONAL_WEEKLY
        return LAYOUT_STAGE_MATRIX

    if actor_manages_college_general_scope(conn, actor_username):
        return LAYOUT_PERSONAL_WEEKLY
    dep = resolve_effective_department_scope_id(conn, actor_username)
    if dep is None:
        return LAYOUT_PERSONAL_WEEKLY
    return LAYOUT_STAGE_MATRIX


def enrich_schedule_row_stage_fields(
    conn,
    item: dict[str, Any],
    *,
    course_code_by_name: dict[str, str] | None = None,
) -> dict[str, Any]:
    """يضيف course_code / is_college_general / stage_bucket / stage_badge دون حذف المفاتيح القديمة."""
    from backend.core.department_scope_policy import course_is_college_general

    name = str(item.get("course_name") or "").strip()
    code = str(item.get("course_code") or "").strip()
    if not code and course_code_by_name is not None:
        code = str(course_code_by_name.get(name.lower()) or "").strip()
    is_gen = False
    try:
        is_gen = bool(course_is_college_general(conn, name, course_code=code or None))
    except Exception:
        is_gen = False
    bucket = classify_stage_bucket(course_code=code or None, is_college_general=is_gen)
    badge = stage_badge_for_row(course_code=code or None, is_college_general=is_gen)
    item["course_code"] = code
    item["is_college_general"] = is_gen
    item["stage_bucket"] = bucket
    item["stage_badge"] = badge
    return item


def load_course_codes_by_name(conn, course_names: list[str]) -> dict[str, str]:
    """خريطة lower(name) → course_code من جدول courses."""
    names = sorted({(n or "").strip() for n in course_names if (n or "").strip()})
    if not names:
        return {}
    from backend.database.database import fetch_table_columns

    cols = fetch_table_columns(conn, "courses") or []
    if "course_code" not in cols:
        return {}
    cur = conn.cursor()
    out: dict[str, str] = {}
    chunk = 200
    for i in range(0, len(names), chunk):
        part = names[i : i + chunk]
        placeholders = ",".join("?" for _ in part)
        rows = cur.execute(
            f"""
            SELECT course_name, COALESCE(course_code, '') AS course_code
            FROM courses
            WHERE lower(trim(course_name)) IN ({placeholders})
            """,
            tuple(n.lower() for n in part),
        ).fetchall() or []
        for r in rows:
            if hasattr(r, "keys"):
                nm = str(r["course_name"] or "").strip().lower()
                cd = str(r["course_code"] or "").strip()
            else:
                nm = str(r[0] or "").strip().lower()
                cd = str(r[1] or "").strip()
            if nm and nm not in out:
                out[nm] = cd
    return out


def build_display_layout_payload(
    conn,
    actor_username: str | None = None,
    *,
    department_id: int | None = None,
    semester: str | None = None,
) -> dict[str, Any]:
    """حمولة واجهة: هل مصفوفة المراحل مفعّلة وما وضع العرض."""
    from backend.core.feature_flags import is_schedule_stage_grid_enabled
    from backend.core.department_scope_policy import (
        actor_manages_college_general_scope,
        resolve_college_general_department_id,
        resolve_effective_department_scope_id,
    )
    from backend.services import schedule_display_tracks as sdt

    enabled = is_schedule_stage_grid_enabled()
    mode = (
        resolve_schedule_layout_mode(conn, actor_username, department_id=department_id)
        if enabled
        else LAYOUT_PERSONAL_WEEKLY
    )
    if not enabled:
        mode = LAYOUT_PERSONAL_WEEKLY
    use_stage = bool(enabled and mode == LAYOUT_STAGE_MATRIX)

    display_tracks: list[dict[str, Any]] = []
    use_display_tracks = False
    tracks_dept = department_id
    if tracks_dept is None:
        if actor_manages_college_general_scope(conn, actor_username):
            tracks_dept = resolve_college_general_department_id(conn)
        else:
            tracks_dept = resolve_effective_department_scope_id(conn, actor_username)
    # أعمدة العرض لجدول الاتجاه العام فقط (ليس مصفوفة المراحل)
    if not use_stage and tracks_dept:
        gen_id = resolve_college_general_department_id(conn)
        if gen_id and int(tracks_dept) == int(gen_id):
            display_tracks = sdt.list_display_tracks(
                conn, semester=semester, department_id=int(tracks_dept)
            )
            use_display_tracks = len(display_tracks) >= 1

    return {
        "stage_grid_enabled": enabled,
        "layout_mode": mode,
        "use_stage_matrix": use_stage,
        "use_display_tracks": use_display_tracks,
        "display_tracks": display_tracks,
        "buckets": [
            {"id": c, "label": PACK_COLUMN_LABELS[c]} for c in PACK_COLUMNS
        ],
    }
