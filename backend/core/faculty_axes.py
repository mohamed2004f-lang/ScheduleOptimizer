"""
محاور دور عضو هيئة التدريس (المقررات المكلَّف بها) + تطبيع أسماء للمطابقة مع الجدول.
"""
from __future__ import annotations

import re
from typing import Any

_WS = re.compile(r"\s+")

# مفاتيح ثابتة للتخزين وواجهة API
FACULTY_AXIS_KEYS: tuple[str, ...] = (
    "course_mgmt",
    "teaching_content",
    "assessment",
    "communication_supervision",
    "documentation_quality",
    "extra_service",
)

FACULTY_AXIS_LABELS_AR: dict[str, str] = {
    "course_mgmt": "إعداد المقرر",
    "teaching_content": "تنفيذ المحتوى التعليمي",
    "assessment": "الدرجات والاختبارات",
    "communication_supervision": "التواصل مع الطلاب",
    "documentation_quality": "التوثيق والجودة والتطوير الأكاديمي",
    "extra_service": "أنشطة إضافية",
}

FACULTY_AXIS_HINTS_AR: dict[str, str] = {
    "course_mgmt": "يُحدَّث تلقائياً: قائمة مفردات معتمدة + خطة أسبوعية",
    "teaching_content": "يُحدَّث تلقائياً من تقرير الجزئي والنهائي",
    "assessment": "يُحدَّث تلقائياً من تقرير التنفيذ ومسودات الجزئي/النهائي",
    "communication_supervision": "إعلانات ومتابعة الطلاب",
    "documentation_quality": "يُحدَّث تلقائياً من تقرير تنفيذ المقرر (مفردات + جزئي + نهائي)",
    "extra_service": "نشاط أو مهمة خدمية — أو اختر «لا ينطبق»",
}

VALID_AXIS_STATUS = frozenset({"pending", "done", "na"})

# 8.7.2: محاور تُشتق تلقائياً من بيانات النظام (لا تُحدَّث يدوياً)
AUTO_DERIVED_AXIS_KEYS: frozenset[str] = frozenset({
    "course_mgmt",
    "teaching_content",
    "assessment",
    "documentation_quality",
})

# 8.7: محور التوثيق اليدوي — يُستبدل بتقرير تنفيذ المقرر (baseline + جزئي/نهائي)
FACULTY_AXIS_HIDDEN_KEYS: frozenset[str] = frozenset({"documentation_quality"})


def visible_axis_keys() -> tuple[str, ...]:
    """محاور تظهر في مقرراتي."""
    return tuple(k for k in FACULTY_AXIS_KEYS if k not in FACULTY_AXIS_HIDDEN_KEYS)


def is_editable_axis_key(axis_key: str) -> bool:
    return axis_key in visible_axis_keys() and axis_key not in AUTO_DERIVED_AXIS_KEYS


def normalize_instructor_name(s: Any) -> str:
    """إزالة الفراغات الزائدة والمحارف غير القابلة للرؤية الشائعة."""
    if s is None:
        return ""
    t = str(s).replace("\u00a0", " ").replace("\u200f", "").replace("\u200e", "").strip()
    return _WS.sub(" ", t).strip()


def is_auto_derived_axis_key(axis_key: str) -> bool:
    return axis_key in AUTO_DERIVED_AXIS_KEYS


def axis_labels_for_api() -> list[dict[str, str]]:
    """قائمة {key, label_ar, hint_ar, auto_derived} للواجهات (بدون محاور مخفية)."""
    return [
        {
            "key": k,
            "label_ar": FACULTY_AXIS_LABELS_AR[k],
            "hint_ar": FACULTY_AXIS_HINTS_AR.get(k, ""),
            "auto_derived": k in AUTO_DERIVED_AXIS_KEYS,
        }
        for k in visible_axis_keys()
    ]
