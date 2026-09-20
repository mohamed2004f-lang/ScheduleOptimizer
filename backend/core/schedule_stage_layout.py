"""تصنيف مقررات الجدول لعرض المراحل (عرض فقط — لا يغيّر صفوف schedule)."""

from __future__ import annotations

from typing import Any

# كتل العرض في مصفوفة المراحل
BUCKET_GENERAL_OR_Y1 = "general_or_y1"  # اتجاه عام + مستوى 2 (ومستوى 0/1 غير العام)
BUCKET_Y3 = "y3"
BUCKET_Y4Y5 = "y4y5"

STAGE_BUCKETS = (BUCKET_GENERAL_OR_Y1, BUCKET_Y3, BUCKET_Y4Y5)

STAGE_BUCKET_LABELS = {
    BUCKET_GENERAL_OR_Y1: "اتجاه عام + السنة الأولى بالقسم",
    BUCKET_Y3: "المرحلة الثالثة",
    BUCKET_Y4Y5: "الرابعة + الخامسة",
}

LAYOUT_STAGE_MATRIX = "stage_matrix"
LAYOUT_PERSONAL_WEEKLY = "personal_weekly"


def classify_stage_bucket(
    *,
    course_code: str | None = None,
    is_college_general: bool = False,
) -> str:
    """
    تصنيف مقرر لعمود المرحلة.
    الاتجاه العام دائماً في الكتلة الأولى حتى لو رمزه GS 201.
    وإلا: أول رقم في الجزء الرقمي (ME 205→2، ME 301→3، ME 401/501→4/5).
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
) -> str:
    """
    stage_matrix: قسم تخصصي (نطاق قسم ≠ GENERAL).
    personal_weekly: رئيس الاتجاه العام، أو بلا نطاق قسم (أدمن بدون فلتر).
    """
    from backend.core.department_scope_policy import (
        actor_manages_college_general_scope,
        resolve_effective_department_scope_id,
    )

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
    # دفعات لتفادي استعلام ضخم جداً
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


def build_display_layout_payload(conn, actor_username: str | None = None) -> dict[str, Any]:
    """حمولة واجهة: هل مصفوفة المراحل مفعّلة وما وضع العرض."""
    from backend.core.feature_flags import is_schedule_stage_grid_enabled

    enabled = is_schedule_stage_grid_enabled()
    mode = resolve_schedule_layout_mode(conn, actor_username) if enabled else LAYOUT_PERSONAL_WEEKLY
    if not enabled:
        mode = LAYOUT_PERSONAL_WEEKLY
    return {
        "stage_grid_enabled": enabled,
        "layout_mode": mode,
        "use_stage_matrix": bool(enabled and mode == LAYOUT_STAGE_MATRIX),
        "buckets": [
            {"id": b, "label": STAGE_BUCKET_LABELS[b]} for b in STAGE_BUCKETS
        ],
    }
