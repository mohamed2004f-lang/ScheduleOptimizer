"""حقول دورة حياة محتوى المقرر (انتقالي / معياري / مشترك بين أقسام)."""

from __future__ import annotations

import re

from backend.database.database import fetch_table_columns, is_postgresql

LIFECYCLE_STANDARD = "standard"
LIFECYCLE_TRANSITIONAL = "transitional"
LIFECYCLE_SHARED = "shared"

LIFECYCLE_LABELS_AR = {
    LIFECYCLE_STANDARD: "معياري (خطة القسم)",
    LIFECYCLE_TRANSITIONAL: "انتقالي (قديم)",
    LIFECYCLE_SHARED: "مشترك بين أقسام",
}

_TRANSITIONAL_TAG = "[انتقالي]"


def ensure_course_master_catalog_schema(conn) -> None:
    cols = set(fetch_table_columns(conn, "course_master") or [])
    cur = conn.cursor()
    if "catalog_lifecycle" not in cols:
        if is_postgresql():
            cur.execute(
                """
                ALTER TABLE course_master
                ADD COLUMN IF NOT EXISTS catalog_lifecycle TEXT NOT NULL DEFAULT 'standard'
                """
            )
        else:
            cur.execute(
                """
                ALTER TABLE course_master
                ADD COLUMN catalog_lifecycle TEXT NOT NULL DEFAULT 'standard'
                """
            )
    if "catalog_note" not in cols:
        if is_postgresql():
            cur.execute(
                "ALTER TABLE course_master ADD COLUMN IF NOT EXISTS catalog_note TEXT DEFAULT ''"
            )
        else:
            cur.execute(
                "ALTER TABLE course_master ADD COLUMN catalog_note TEXT DEFAULT ''"
            )
    if "review_after" not in cols:
        if is_postgresql():
            cur.execute(
                "ALTER TABLE course_master ADD COLUMN IF NOT EXISTS review_after TEXT DEFAULT ''"
            )
        else:
            cur.execute(
                "ALTER TABLE course_master ADD COLUMN review_after TEXT DEFAULT ''"
            )


def normalize_catalog_lifecycle(raw: str | None) -> str:
    v = (raw or "").strip().lower()
    if v in (LIFECYCLE_TRANSITIONAL, LIFECYCLE_SHARED, LIFECYCLE_STANDARD):
        return v
    return LIFECYCLE_STANDARD


def title_suggests_transitional(title_ar: str | None) -> bool:
    t = (title_ar or "").strip()
    if not t:
        return False
    if _TRANSITIONAL_TAG in t:
        return True
    return bool(re.search(r"\[انتقال", t, re.IGNORECASE))


def apply_transitional_title_tag(title_ar: str, add: bool) -> str:
    t = (title_ar or "").strip()
    if not t:
        return t
    if add:
        if title_suggests_transitional(t):
            return t
        return f"{t} {_TRANSITIONAL_TAG}".strip()
    return re.sub(r"\s*\[انتقال[^\]]*\]\s*", " ", t, flags=re.IGNORECASE).strip()
