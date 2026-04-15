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
    "course_mgmt": "إدارة المقرر",
    "teaching_content": "التدريس والمحتوى التعليمي",
    "assessment": "التقييم والاختبارات",
    "communication_supervision": "التواصل والإشراف",
    "documentation_quality": "التوثيق والجودة والتطوير الأكاديمي",
    "extra_service": "الأنشطة الإضافية والخدمية",
}

VALID_AXIS_STATUS = frozenset({"pending", "done", "na"})


def normalize_instructor_name(s: Any) -> str:
    """إزالة الفراغات الزائدة والمحارف غير القابلة للرؤية الشائعة."""
    if s is None:
        return ""
    t = str(s).replace("\u00a0", " ").replace("\u200f", "").replace("\u200e", "").strip()
    return _WS.sub(" ", t).strip()


def axis_labels_for_api() -> list[dict[str, str]]:
    """قائمة {key, label_ar} للواجهات."""
    return [{"key": k, "label_ar": FACULTY_AXIS_LABELS_AR[k]} for k in FACULTY_AXIS_KEYS]
