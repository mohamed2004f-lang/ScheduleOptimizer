"""
تحقق مركزي من المدخلات الشائعة في المنظومة.
"""
from __future__ import annotations

import re
from typing import Any, Optional, Tuple

_TIME_SLOT_RE = re.compile(
    r"^\s*(\d{1,2}):(\d{2})\s*[-–—/\\]\s*(\d{1,2}):(\d{2})\s*$"
)
_DAY_NAMES = frozenset(
    {"السبت", "الأحد", "الإثنين", "الثلاثاء", "الأربعاء", "الخميس"}
)


def _ok(msg: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    return (True, None) if msg is None else (False, msg)


def validate_student_id(sid: Any) -> Tuple[bool, Optional[str]]:
    s = (str(sid).strip() if sid is not None else "")
    if not s:
        return False, "رقم الطالب مطلوب"
    if len(s) > 50:
        return False, "رقم الطالب طويل جداً"
    return True, None


def validate_course_name(name: Any) -> Tuple[bool, Optional[str]]:
    s = (str(name).strip() if name is not None else "")
    if not s:
        return False, "اسم المقرر مطلوب"
    if len(s) > 200:
        return False, "اسم المقرر طويل جداً"
    return True, None


def validate_grade(grade: Any) -> Tuple[bool, Optional[str]]:
    if grade is None or grade == "":
        return True, None
    try:
        g = float(grade)
    except (TypeError, ValueError):
        return False, "الدرجة يجب أن تكون رقماً"
    if g < 0 or g > 100:
        return False, "الدرجة يجب أن تكون بين 0 و 100"
    return True, None


def validate_time_slot(time_str: Any) -> Tuple[bool, Optional[str]]:
    s = (str(time_str).strip() if time_str is not None else "")
    if not s:
        return False, "التوقيت مطلوب"
    if not _TIME_SLOT_RE.match(s):
        return False, "تنسيق التوقيت غير صحيح. استخدم: HH:MM-HH:MM"
    m = _TIME_SLOT_RE.match(s)
    if not m:
        return False, "تنسيق التوقيت غير صحيح"
    for hh, mm in ((int(m.group(1)), int(m.group(2))), (int(m.group(3)), int(m.group(4)))):
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return False, "ساعة أو دقيقة غير صالحة في التوقيت"
    return True, None


def validate_schedule_day(day: Any) -> Tuple[bool, Optional[str]]:
    s = (str(day).strip() if day is not None else "")
    if not s:
        return False, "اليوم مطلوب"
    if s not in _DAY_NAMES:
        return False, f"يوم غير معروف: {s}"
    return True, None


def validate_optimize_params(data: dict | None) -> Tuple[bool, Optional[str], dict]:
    """يرجع (صالح، رسالة خطأ، معاملات منظّفة)."""
    data = data if isinstance(data, dict) else {}
    try:
        max_alt = int(data.get("max_alternatives_per_section") or 3)
    except (TypeError, ValueError):
        return False, "max_alternatives_per_section يجب أن يكون رقماً", {}
    try:
        move_cost = float(data.get("move_cost") or 1.0)
    except (TypeError, ValueError):
        return False, "move_cost يجب أن يكون رقماً", {}
    if max_alt < 1 or max_alt > 10:
        return False, "max_alternatives_per_section يجب أن يكون بين 1 و 10", {}
    if move_cost < 0:
        return False, "move_cost يجب أن يكون >= 0", {}
    cleaned = {
        "max_alternatives_per_section": max_alt,
        "move_cost": move_cost,
        "add_room_conflict": bool(data.get("add_room_conflict", True)),
        "add_instructor_conflict": bool(data.get("add_instructor_conflict", True)),
    }
    return True, None, cleaned


def validate_schedule_row_dict(row: dict) -> Tuple[bool, Optional[str]]:
    if not isinstance(row, dict):
        return False, "صف الجدول يجب أن يكون كائناً"
    ok, msg = validate_course_name(row.get("course_name"))
    if not ok:
        return ok, msg
    ok, msg = validate_schedule_day(row.get("day"))
    if not ok:
        return ok, msg
    ok, msg = validate_time_slot(row.get("time"))
    if not ok:
        return ok, msg
    return True, None
