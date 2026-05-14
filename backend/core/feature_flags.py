"""ميزات اختيارية تُفعَّل عبر متغيرات البيئة."""

from __future__ import annotations

import os


def is_multi_dept_instructor_enabled() -> bool:
    """
    إسناد الأستاذ لأكثر من قسم + تكافؤ المقررات بين الأقسام.
    الافتراضي: مفعّل (1). عطّل بتعيين ENABLE_MULTI_DEPT_INSTRUCTOR=0.
    """
    v = (os.environ.get("ENABLE_MULTI_DEPT_INSTRUCTOR") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def registration_program_course_mode() -> str:
    """
    ربط التسجيلات بـ program_courses:
    - off: بدون تحقق
    - warn: إرجاع تحذيرات فقط (الافتراضي)
    - enforce: منع الحفظ/التنفيذ عند المخالفة
    """
    v = (os.environ.get("REG_PROGRAM_COURSE_MODE") or "warn").strip().lower()
    if v in ("off", "warn", "enforce"):
        return v
    return "warn"
