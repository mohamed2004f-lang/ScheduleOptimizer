"""كتالوج أرشيف الكلية — خزائن الأدوار + أنواع السجلات (طابع كلي)."""

from __future__ import annotations

from typing import Any

from backend.core.department_archive_catalog import (
    ARCHIVE_RECORD_TYPES as _DEPT_TYPES,
    ARCHIVE_TYPE_CODES,
    FOLLOW_UP_STATUSES,
)

# خزائن أرشيف الكلية
COLLEGE_CABINETS: dict[str, dict[str, Any]] = {
    "dean": {
        "code": "dean",
        "title_ar": "أرشيف العميد",
        "owner_role": "college_dean",
        "short_ar": "عميد",
        "examples_ar": "قرارات العمادة، مراسلات العميد، متابعات خاصة",
    },
    "vice_dean": {
        "code": "vice_dean",
        "title_ar": "أرشيف الوكيل العلمي",
        "owner_role": "academic_vice_dean",
        "short_ar": "وكيل",
        "examples_ar": "قرارات الوكالة، محاضر ولجان الوكيل، مراسلات علمية",
    },
    "college_quality_dept": {
        "code": "college_quality_dept",
        "title_ar": "أرشيف رئيس قسم جودة بالكلية",
        "owner_role": "college_quality_lead",
        "short_ar": "جودة الكلية",
        "examples_ar": "محاضر الجودة المركزية، فجوات INST، أدلة مؤسسية قيد التجهيز",
    },
    "shared": {
        "code": "shared",
        "title_ar": "السجل المشترك للكلية",
        "owner_role": None,
        "short_ar": "مشترك",
        "examples_ar": "مجلس الكلية، قرارات عامة باسم الكلية، مخاطبات رسمية مشتركة",
    },
}

CABINET_CODES: tuple[str, ...] = tuple(COLLEGE_CABINETS.keys())
PRIVATE_CABINET_CODES: tuple[str, ...] = ("dean", "vice_dean", "college_quality_dept")

# أنواع السجلات — نفس رموز القسم بأمثلة كلية
ARCHIVE_RECORD_TYPES: dict[str, dict[str, Any]] = {}
for _code, _meta in _DEPT_TYPES.items():
    m = dict(_meta)
    if _code == "minutes":
        m["examples_ar"] = "مجلس الكلية، لجنة الجودة المركزية، لجان الاعتماد المؤسسي"
    elif _code == "decision":
        m["examples_ar"] = "قرارات العميد أو الوكيل أو رئيس قسم جودة بالكلية"
    elif _code == "corr_out":
        m["examples_ar"] = "كتب رسمية صادرة من العمادة أو وكالة الكلية"
    elif _code == "corr_in":
        m["examples_ar"] = "كتب واردة للكلية مع إحالة على القيادة"
    elif _code == "notes":
        m["examples_ar"] = "ملاحظات متابعة فجوات INST على مستوى الكلية"
    ARCHIVE_RECORD_TYPES[_code] = m

NAMING_PATTERN_AR = "{CABINET}_{TYPE}_{YYYYMMDD}_{موضوع مختصر}"
NAMING_EXAMPLES: dict[str, str] = {
    "minutes": "SHARED_محضر_20260803_مجلس_الكلية.pdf",
    "decision": "DEAN_قرار_20260803_اعتماد_سياسة.pdf",
    "corr_out": "VICE_صادر_20260803_مخاطبة_وزارة.pdf",
    "corr_in": "QUALITY_وارد_20260801_من_الجامعة.pdf",
    "notes": "QUALITY_ملاحظة_20260803_فجوة_INST.docx",
}

# اقتراحات INST للربط اليدوي
COLLEGE_QAA_SUGGESTIONS: dict[str, list[dict[str, str]]] = {
    "minutes": [
        {
            "catalog_version": "QAA-2023.4-INST",
            "indicator_code": "INST-02-01",
            "reason_ar": "محضر مجلس/لجنة جودة على مستوى الكلية",
        },
    ],
    "decision": [
        {
            "catalog_version": "QAA-2023.4-INST",
            "indicator_code": "INST-01-02",
            "reason_ar": "قرار قيادة كلية يدعم الحوكمة المؤسسية",
        },
    ],
    "corr_out": [
        {
            "catalog_version": "QAA-2023.4-INST",
            "indicator_code": "INST-03-01",
            "reason_ar": "مراسلة صادرة باسم الكلية",
        },
    ],
    "corr_in": [
        {
            "catalog_version": "QAA-2023.4-INST",
            "indicator_code": "INST-03-01",
            "reason_ar": "مراسلة واردة ومتابعة مؤسسية",
        },
    ],
    "notes": [
        {
            "catalog_version": "QAA-2023.4-INST",
            "indicator_code": "INST-04-01",
            "reason_ar": "متابعة فجوات وتحسين مستمر",
        },
    ],
}


def cabinet_title(code: str) -> str:
    return str((COLLEGE_CABINETS.get(code) or {}).get("title_ar") or code)


def suggestions_for_college_type(record_type: str) -> list[dict[str, str]]:
    return list(COLLEGE_QAA_SUGGESTIONS.get((record_type or "").strip().lower()) or [])


def catalog_payload() -> dict[str, Any]:
    return {
        "cabinets": list(COLLEGE_CABINETS.values()),
        "record_types": list(ARCHIVE_RECORD_TYPES.values()),
        "follow_up_statuses": [{"code": c, "label_ar": lbl} for c, lbl in FOLLOW_UP_STATUSES],
        "naming_pattern_ar": NAMING_PATTERN_AR,
        "naming_examples": NAMING_EXAMPLES,
        "type_codes": list(ARCHIVE_TYPE_CODES),
    }
