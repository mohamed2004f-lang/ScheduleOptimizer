"""تصنيف وعرض مصفوفة الجدول (عرض فقط — لا يغيّر صفوف schedule).

أعمدة التعبئة: عمود مفضّل حسب المرحلة + Round-robin داخل اليوم لنفس المرحلة
+ تفريغ عند تعارض نفس الوقت. stage_bucket يبقى للشارات أيضاً.
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
    """يدوي أولاً، ثم مرحلة مفضّلة، ثم عام، ثم أقل رمز رقمي، ثم الرمز، ثم الاسم."""
    item = row or {}
    manual = 0 if manual_pack_prefer_index(item) is not None else 1
    prefer = stage_pack_prefer_index(item)
    is_gen = 0 if item.get("is_college_general") else 1
    code = str(item.get("course_code") or "").strip().upper()
    m = re.search(r"\d+", code)
    num = int(m.group(0)) if m else 10**9
    name = str(item.get("course_name") or "").strip().lower()
    return (manual, prefer, is_gen, num, code, name)


def manual_pack_prefer_index(
    row: dict[str, Any] | None,
    *,
    column_count: int = 3,
) -> int | None:
    """تجاوز يدوي من مجموعة التدريس: pack_display_column / display_column / tg_display_column."""
    item = row or {}
    n = max(1, int(column_count or 3))
    for key in ("pack_display_column", "display_column", "tg_display_column"):
        raw = item.get(key)
        if raw is None or raw == "":
            continue
        try:
            idx = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= idx <= n:
            return idx
    return None


def stage_pack_prefer_index(row: dict[str, Any] | None) -> int:
    """
    عمود مفضّل حسب المرحلة (أو التجاوز اليدوي إن وُجد):
    1 ← مرحلة 1 / اتجاه عام
    2 ← مرحلتا 2–3
    3 ← مرحلتا 4–5 (+ أعلى)
    """
    item = row or {}
    manual = manual_pack_prefer_index(item)
    if manual is not None:
        return manual
    if item.get("is_college_general"):
        return 1
    from backend.services.college_catalog import infer_level_from_course_code

    level = int(infer_level_from_course_code(item.get("course_code")) or 0)
    if level <= 1:
        return 1
    if level <= 3:
        return 2
    return 3


def course_pack_identity(row: dict[str, Any] | None) -> str:
    """مفتاح ثابت للمقرر عبر الأوقات (رمز|اسم|مجموعة) لتثبيت عمود العرض."""
    item = row or {}
    code = str(item.get("course_code") or "").strip().upper()
    name = str(item.get("course_name") or "").strip().lower()
    group = str(
        item.get("group_code")
        or item.get("group_code_label")
        or item.get("teaching_group_id")
        or ""
    ).strip().upper()
    if code or name:
        return f"{code}|{name}|{group}"
    sid = item.get("section_id") or item.get("id") or ""
    return f"sid:{sid}"


def sticky_pack_lookup_key(day: str | None, row: dict[str, Any] | None) -> str:
    """مفتاح التثبيت: يوم|هوية المقرر."""
    d = str(day or (row or {}).get("day") or "").strip()
    return f"{d}|{course_pack_identity(row)}"


def build_sticky_pack_map(
    rows: list[dict[str, Any]] | None,
    *,
    column_count: int = 3,
) -> dict[str, str]:
    """
    تثبيت عمود لكل مقرر داخل اليوم:
    - عمود البداية = مفضّل المرحلة (1 / 2–3 / 4–5)
    - مقررات نفس المرحلة في نفس اليوم → Round-robin من عمود البداية
    المفتاح: «يوم|هوية».
    """
    n = max(1, int(column_count or 3))
    by_day: dict[str, list[dict[str, Any]]] = {}
    for row in rows or []:
        day = str(row.get("day") or "").strip()
        by_day.setdefault(day, []).append(row)

    out: dict[str, str] = {}
    for day, day_rows in by_day.items():
        reps: dict[str, dict[str, Any]] = {}
        for row in day_rows:
            kid = course_pack_identity(row)
            if kid not in reps:
                reps[kid] = row
        # 1) تثبيت يدوي صريح
        auto_kids: list[str] = []
        for kid in sorted(reps.keys(), key=lambda k: course_pack_sort_key(reps[k])):
            manual = manual_pack_prefer_index(reps[kid], column_count=n)
            if manual is not None:
                out[f"{day}|{kid}"] = f"pack_{manual}"
            else:
                auto_kids.append(kid)
        # 2) الباقي: RR حسب المرحلة داخل اليوم
        by_rank: dict[int, list[str]] = {1: [], 2: [], 3: []}
        for kid in auto_kids:
            rank = stage_pack_prefer_index(reps[kid])
            by_rank.setdefault(rank, []).append(kid)
        for rank, kids in by_rank.items():
            start = ((int(rank) - 1) % n) + 1
            for i, kid in enumerate(kids):
                col = ((start - 1 + i) % n) + 1
                out[f"{day}|{kid}"] = f"pack_{col}"
    return out


def assign_pack_display_columns(
    courses: list[dict[str, Any]] | None,
    *,
    column_count: int = 3,
    sticky_map: dict[str, str] | None = None,
    day: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """
    توزيع مقررات نفس اليوم/الوقت على أعمدة التعبئة.

    1) عمود مفضّل من sticky اليوم (مرحلة + RR) أو من المرحلة مباشرة.
    2) إن كان المفضّل فارغاً في الصف → ضعه فيه.
    3) وإلا فرّغ لأقرب عمود فارغ (لفّ دائري).
    4) إن امتلأت الأعمدة → الأقل ازدحاماً (تعادل → أقرب للمفضّل ثم رقم أصغر).
    """
    n = max(1, int(column_count or 3))
    ids = tuple(f"pack_{i}" for i in range(1, n + 1))
    cols: dict[str, list[dict[str, Any]]] = {cid: [] for cid in ids}
    ordered = sorted(list(courses or []), key=course_pack_sort_key)
    sticky = sticky_map or {}

    def _prefer_index(row: dict[str, Any]) -> int:
        key = sticky_pack_lookup_key(day, row)
        pref = sticky.get(key) or sticky.get(course_pack_identity(row))
        if isinstance(pref, str) and pref.startswith("pack_"):
            try:
                idx = int(pref.split("_", 1)[1])
                if 1 <= idx <= n:
                    return idx
            except (TypeError, ValueError):
                pass
        return stage_pack_prefer_index(row)

    for row in ordered:
        prefer = _prefer_index(row)
        placed = False
        for offset in range(n):
            idx = ((prefer - 1 + offset) % n) + 1
            cid = f"pack_{idx}"
            if not cols[cid]:
                cols[cid].append(row)
                placed = True
                break
        if placed:
            continue
        best = min(
            range(1, n + 1),
            key=lambda i: (
                len(cols[f"pack_{i}"]),
                (i - prefer) % n,
                i,
            ),
        )
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
