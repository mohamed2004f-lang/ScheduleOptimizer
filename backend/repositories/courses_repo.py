"""استعلامات جدول المقررات — تكرار الاسم/الرمز وغيرها."""
from __future__ import annotations

from typing import Any, Optional


def _has_archived_column(conn) -> bool:
    try:
        from backend.database.database import fetch_table_columns

        return "is_archived" in fetch_table_columns(conn, "courses")
    except Exception:
        return False


def find_course_name_row_ci(conn, course_name: str) -> Optional[Any]:
    """صف المقرر بنفس الاسم (أي حالة أرشفة) إن وُجد."""
    cname = (course_name or "").strip()
    if not cname:
        return None
    cur = conn.cursor()
    if _has_archived_column(conn):
        return cur.execute(
            """
            SELECT course_name, course_code, units, COALESCE(is_archived, 0) AS is_archived
            FROM courses
            WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))
            """,
            (cname,),
        ).fetchone()
    return cur.execute(
        """
        SELECT course_name, course_code, units, 0 AS is_archived
        FROM courses
        WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))
        """,
        (cname,),
    ).fetchone()


def find_course_name_duplicate_ci(
    conn, course_name: str, *, include_archived: bool = False
) -> Optional[Any]:
    """إن وُجد مقرر بنفس الاسم (بعد تطبيع المسافات وحالة الأحرف) يُعاد صف يحوي course_name.

    افتراضياً تُتجاهل المقررات المؤرشفة منطقياً حتى يمكن استعادتها عبر الإضافة/الاستيراد.
    """
    cname = (course_name or "").strip()
    if not cname:
        return None
    cur = conn.cursor()
    if include_archived or not _has_archived_column(conn):
        return cur.execute(
            "SELECT course_name FROM courses WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))",
            (cname,),
        ).fetchone()
    return cur.execute(
        """
        SELECT course_name FROM courses
        WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))
          AND COALESCE(is_archived, 0) = 0
        """,
        (cname,),
    ).fetchone()


def find_course_code_duplicate_ci(
    conn,
    course_code: str,
    *,
    include_archived: bool = True,
    exclude_course_name: str | None = None,
) -> Optional[Any]:
    """إن وُجد مقرر بنفس الرمز (غير فارغ) يُعاد صف يحوي course_name.

    افتراضياً يشمل المؤرشف لأن فهرس الرمز الفريد في قاعدة البيانات يغطي كل الصفوف.
    يمكن استثناء اسم مقرر عند الاستعادة/التحديث.
    """
    code = (course_code or "").strip()
    if not code:
        return None
    cur = conn.cursor()
    sql = (
        "SELECT course_name FROM courses "
        "WHERE COALESCE(course_code,'') <> '' "
        "AND LOWER(TRIM(course_code)) = LOWER(TRIM(?))"
    )
    params: list[Any] = [code]
    if not include_archived and _has_archived_column(conn):
        sql += " AND COALESCE(is_archived, 0) = 0"
    excl = (exclude_course_name or "").strip()
    if excl:
        sql += " AND LOWER(TRIM(course_name)) <> LOWER(TRIM(?))"
        params.append(excl)
    return cur.execute(sql, tuple(params)).fetchone()
