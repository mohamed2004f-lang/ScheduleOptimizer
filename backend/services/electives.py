from __future__ import annotations

from typing import Dict, Any
from backend.database.database import fetch_table_columns


ELECTIVE_CATEGORIES = ("elective_major", "elective_free")


def check_electives_requirement(cur, student_id: str, *, required_electives: int = 3) -> Dict[str, Any]:
    """
    شرط: بعد إكمال 100 وحدة منجزة (ناجح فقط) يجب إكمال عدد محدد من المقررات الاختيارية.
    - يعتمد على grades للوحدات/الدرجات
    - يعتمد على courses.category لتحديد اختياري/إجباري
    - يدعم استثناء من student_exceptions: type='electives_waive' و is_active=1
    """
    sid = (str(student_id or "")).strip()
    if not sid:
        return {
            "completed_units": 0,
            "required_electives": required_electives,
            "electives_completed": 0,
            "active": False,
            "ok": True,
            "waived": False,
        }

    # مجموع الوحدات المكتملة (ناجح فقط)
    try:
        row = cur.execute(
            """
            SELECT COALESCE(SUM(COALESCE(units,0)),0) AS cu
            FROM grades
            WHERE student_id = ?
              AND grade IS NOT NULL
              AND grade >= 50
            """,
            (sid,),
        ).fetchone()
        completed_units = int((row[0] if row else 0) or 0)
    except Exception:
        completed_units = 0

    if completed_units < 100:
        return {
            "completed_units": completed_units,
            "required_electives": required_electives,
            "electives_completed": 0,
            "active": False,
            "ok": True,
            "waived": False,
        }

    # استثناء
    try:
        exc = cur.execute(
            """
            SELECT 1 FROM student_exceptions
            WHERE student_id = ? AND type = 'electives_waive' AND is_active = 1
            LIMIT 1
            """,
            (sid,),
        ).fetchone()
        if exc:
            return {
                "completed_units": completed_units,
                "required_electives": required_electives,
                "electives_completed": 0,
                "active": True,
                "ok": True,
                "waived": True,
            }
    except Exception:
        pass

    # وجود category في courses (قواعد قديمة)
    try:
        cols = fetch_table_columns(cur.connection, "courses")
    except Exception:
        cols = []
    has_cat = "category" in cols
    if not has_cat:
        # لا يمكن حساب الاختياريات بدقة بدون التصنيف
        return {
            "completed_units": completed_units,
            "required_electives": required_electives,
            "electives_completed": 0,
            "active": True,
            "ok": False,
            "waived": False,
            "message": "تعذر حساب المقررات الاختيارية لأن تصنيف المقررات غير متوفر بعد.",
        }

    try:
        placeholders = ",".join("?" for _ in ELECTIVE_CATEGORIES)
        row = cur.execute(
            f"""
            SELECT COUNT(*) FROM grades g
            JOIN courses c ON c.course_name = g.course_name
            WHERE g.student_id = ?
              AND g.grade IS NOT NULL
              AND g.grade >= 50
              AND COALESCE(c.category,'required') IN ({placeholders})
            """,
            (sid, *ELECTIVE_CATEGORIES),
        ).fetchone()
        electives_completed = int((row[0] if row else 0) or 0)
    except Exception:
        electives_completed = 0

    ok = electives_completed >= int(required_electives or 0)
    return {
        "completed_units": completed_units,
        "required_electives": int(required_electives or 0),
        "electives_completed": electives_completed,
        "active": True,
        "ok": ok,
        "waived": False,
    }

