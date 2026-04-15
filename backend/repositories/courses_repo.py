"""استعلامات جدول المقررات — تكرار الاسم/الرمز وغيرها."""
from __future__ import annotations

from typing import Any, Optional


def find_course_name_duplicate_ci(conn, course_name: str) -> Optional[Any]:
    """إن وُجد مقرر بنفس الاسم (بعد تطبيع المسافات وحالة الأحرف) يُعاد صف يحوي course_name."""
    cname = (course_name or "").strip()
    if not cname:
        return None
    cur = conn.cursor()
    return cur.execute(
        "SELECT course_name FROM courses WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))",
        (cname,),
    ).fetchone()


def find_course_code_duplicate_ci(conn, course_code: str) -> Optional[Any]:
    """إن وُجد مقرر بنفس الرمز (غير فارغ) يُعاد صف يحوي course_name."""
    code = (course_code or "").strip()
    if not code:
        return None
    cur = conn.cursor()
    return cur.execute(
        "SELECT course_name FROM courses WHERE COALESCE(course_code,'') <> '' AND LOWER(TRIM(course_code)) = LOWER(TRIM(?))",
        (code,),
    ).fetchone()
