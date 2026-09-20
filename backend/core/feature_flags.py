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


def is_schedule_assignment_upsert_enabled() -> bool:
    """
    عند حفظ/تحديث صف جدول بأستاذ من قسم آخر: إنشاء/تفعيل تعيين متعاون للقسم.
    يتطلب ENABLE_MULTI_DEPT_INSTRUCTOR. عطّل بـ ENABLE_SCHEDULE_ASSIGNMENT_UPSERT=0.
    """
    if not is_multi_dept_instructor_enabled():
        return False
    v = (os.environ.get("ENABLE_SCHEDULE_ASSIGNMENT_UPSERT") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def is_schedule_stage_grid_enabled() -> bool:
    """
    عرض محرر الجدول بمصفوفة المراحل (يوم|وقت|كتل المستويات) للأقسام التخصصية.
    الافتراضي: مفعّل. عطّل بـ SCHEDULE_STAGE_GRID=0 للرجوع للشبكة الأسبوعية الحالية.
    """
    v = (os.environ.get("SCHEDULE_STAGE_GRID") or "1").strip().lower()
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
