"""كتالوج أرشيف ضمان جودة القسم — أنواع، دليل، قوالب، اقتراحات ربط يدوي."""

from __future__ import annotations

from typing import Any

# أنواع السجلات التشغيلية لكل قسم
ARCHIVE_RECORD_TYPES: dict[str, dict[str, Any]] = {
    "minutes": {
        "code": "minutes",
        "title_ar": "محاضر الاجتماعات",
        "short_ar": "محضر",
        "icon": "fa-people-group",
        "examples_ar": "مجلس القسم، لجنة الجودة، لجان الامتحانات",
        "required_fields": ("title_ar", "doc_date"),
        "optional_fields": ("ref_number", "party_ar", "tags", "body_text"),
    },
    "decision": {
        "code": "decision",
        "title_ar": "القرارات",
        "short_ar": "قرار",
        "icon": "fa-gavel",
        "examples_ar": "قرارات رئيس القسم أو إحالات رسمية داخل الكلية",
        "required_fields": ("title_ar", "doc_date", "ref_number"),
        "optional_fields": ("party_ar", "tags", "body_text"),
    },
    "corr_out": {
        "code": "corr_out",
        "title_ar": "مراسلات صادرة",
        "short_ar": "صادر",
        "icon": "fa-paper-plane",
        "examples_ar": "كتب رسمية صادرة من القسم",
        "required_fields": ("title_ar", "doc_date", "ref_number", "party_ar"),
        "optional_fields": ("tags", "body_text"),
    },
    "corr_in": {
        "code": "corr_in",
        "title_ar": "مراسلات واردة",
        "short_ar": "وارد",
        "icon": "fa-envelope-open-text",
        "examples_ar": "كتب واردة للقسم مع إحالة",
        "required_fields": ("title_ar", "doc_date", "party_ar"),
        "optional_fields": ("ref_number", "tags", "body_text"),
    },
    "notes": {
        "code": "notes",
        "title_ar": "دفتر الملاحظات",
        "short_ar": "ملاحظة",
        "icon": "fa-book",
        "examples_ar": "ملاحظات تشغيل ومتابعة لإجراءات الجودة",
        "required_fields": ("title_ar", "doc_date"),
        "optional_fields": ("tags", "body_text", "follow_up_status"),
    },
}

ARCHIVE_TYPE_CODES: tuple[str, ...] = tuple(ARCHIVE_RECORD_TYPES.keys())

FOLLOW_UP_STATUSES: tuple[tuple[str, str], ...] = (
    ("open", "مفتوحة"),
    ("in_progress", "قيد المتابعة"),
    ("done", "مغلقة"),
    ("na", "لا ينطبق"),
)

# قواعد تسمية مقترحة
NAMING_PATTERN_AR = "{DEPT}_{TYPE}_{YYYYMMDD}_{موضوع مختصر}"
NAMING_EXAMPLES: dict[str, str] = {
    "minutes": "MECH_محضر_20260714_لجنة_الجودة.pdf",
    "decision": "MECH_قرار_20260714_اعتماد_سياسة.pdf",
    "corr_out": "MECH_صادر_20260714_مخاطبة_العمادة.pdf",
    "corr_in": "MECH_وارد_20260710_من_العمادة.pdf",
    "notes": "MECH_ملاحظة_20260714_متابعة_فجوات.docx",
}

# اقتراحات ربط يدوي: نوع سجل → مؤشرات QAA مرشّحة (تأكيد بشري إلزامي)
ARCHIVE_QAA_SUGGESTIONS: dict[str, list[dict[str, str]]] = {
    "minutes": [
        {
            "catalog_version": "QAA-2023.4-INST",
            "indicator_code": "INST-02-01",
            "usage_ar": "محاضر الحوكمة/الاجتماعات — شاهد مؤسسي مقترح.",
        },
        {
            "catalog_version": "QAA-2023.4-INST",
            "indicator_code": "INST-09-15",
            "usage_ar": "محاضر ضمان الجودة — شاهد مقترح.",
        },
        {
            "catalog_version": "QAA-2023.4-PROG-UG",
            "indicator_code": "PROG-UG-03-06",
            "usage_ar": "محاضر البرنامج/القسم — شاهد برامجي مقترح.",
        },
    ],
    "decision": [
        {
            "catalog_version": "QAA-2023.4-INST",
            "indicator_code": "INST-02-01",
            "usage_ar": "قرارات إدارية داعمة للحوكمة.",
        },
        {
            "catalog_version": "QAA-2023.4-PROG-UG",
            "indicator_code": "PROG-UG-08-11",
            "usage_ar": "قرارات مرتبطة بلوائح/عملية البرنامج.",
        },
    ],
    "corr_out": [
        {
            "catalog_version": "QAA-2023.4-INST",
            "indicator_code": "INST-08-07",
            "usage_ar": "مراسلات مع الجهات الخارجية/المجتمع.",
        },
        {
            "catalog_version": "QAA-2023.4-INST",
            "indicator_code": "INST-02-06",
            "usage_ar": "مراسلات داخلية داعمة للقيادة والإدارة.",
        },
    ],
    "corr_in": [
        {
            "catalog_version": "QAA-2023.4-INST",
            "indicator_code": "INST-02-06",
            "usage_ar": "مراسلات واردة ذات أثر تشغيلي/قيادي.",
        },
        {
            "catalog_version": "QAA-2023.4-PROG-UG",
            "indicator_code": "PROG-UG-08-13",
            "usage_ar": "وارد من أصحاب المصلحة/القطاع (إن انطبق).",
        },
    ],
    "notes": [
        {
            "catalog_version": "QAA-2023.4-INST",
            "indicator_code": "INST-09-15",
            "usage_ar": "ملاحظات متابعة الجودة — شاهد داعم بعد التوثيق.",
        },
        {
            "catalog_version": "QAA-2023.4-PROG-UG",
            "indicator_code": "PROG-UG-08-07",
            "usage_ar": "ملاحظات وحدة الجودة على البرنامج.",
        },
    ],
}

# كلمات مفتاحية لتصنيف المساعد
CLASSIFY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "minutes": ("محضر", "اجتماع", "مجلس", "لجنة", "حضور", "جدول أعمال"),
    "decision": ("قرار", "تعميم", "اعتماد", "يقرّ", "يقرر"),
    "corr_out": ("صادر", "كتابنا", "مخاطبة", "إلى السيد", "تحية طيبة وبعد"),
    "corr_in": ("وارد", "إليكم", "إشارة إلى كتابكم", "من العمادة", "من الكلية"),
    "notes": ("ملاحظة", "متابعة", "تذكير", "فجوة", "إجراء تصحيحي", "دفتر"),
}

DRAFT_TEMPLATES: dict[str, str] = {
    "minutes": """محضر اجتماع — {title_ar}

القسم: {department_name_ar}
التاريخ: {doc_date}
رقم المحضر: {ref_number}
الحضور: {party_ar}

أولاً — جدول الأعمال:
1.
2.

ثانياً — المناقشات:
-

ثالثاً — القرارات والتوصيات:
1.
2.

رابعاً — المتابعة:
-

التوقيع: ____________________    التاريخ: {doc_date}
""",
    "decision": """قرار رقم ({ref_number})

القسم: {department_name_ar}
التاريخ: {doc_date}
الموضوع: {title_ar}

بعد الاطلاع على {party_ar}، تقرّر ما يلي:
1.
2.

يُبلَّغ هذا القرار لمن يلزم لتنفيذه.

رئيس القسم: ____________________
""",
    "corr_out": """كتاب صادر رقم ({ref_number})

القسم: {department_name_ar}
التاريخ: {doc_date}
إلى: {party_ar}
الموضوع: {title_ar}

السلام عليكم ورحمة الله وبركاته،
تحية طيبة وبعد،

{body_text}

وتفضلوا بقبول فائق الاحترام،
رئيس القسم: ____________________
""",
    "corr_in": """سجل وارد

القسم: {department_name_ar}
تاريخ الاستلام: {doc_date}
رقم الوارد: {ref_number}
الجهة المرسلة: {party_ar}
الموضوع: {title_ar}

ملخص المحتوى:
{body_text}

الإحالة / الإجراء المطلوب:
-
المسؤول المتابع:
-
""",
    "notes": """ملاحظة جودة

القسم: {department_name_ar}
التاريخ: {doc_date}
الموضوع: {title_ar}
الحالة: {follow_up_status}

الوصف:
{body_text}

الإجراء المقترح:
-
الموعد المستهدف:
-
""",
}

GUIDE_SECTIONS: list[dict[str, Any]] = [
    {
        "title_ar": "الغرض",
        "body_ar": (
            "أرشيف القسم هو السجل التشغيلي لضمان الجودة: يحفظ المحاضر والقرارات "
            "والمراسلات والملاحظات بشكل منظم لكل قسم، ويمكن ترشيح أي وثيقة يدوياً "
            "كشاهد على مؤشر اعتماد مؤسسي أو برامجي."
        ),
    },
    {
        "title_ar": "سياسة الربط بالاعتماد",
        "body_ar": (
            "الربط بمؤشرات QAA اقتراح فقط. لا تُحدَّث حالة الامتثال تلقائياً. "
            "يختار منسق الجودة أو رئيس القسم المؤشر ثم يؤكد الربط."
        ),
    },
    {
        "title_ar": "قواعد التسمية",
        "body_ar": (
            f"الصيغة المقترحة: {NAMING_PATTERN_AR}. استخدم رمز القسم الإنجليزي "
            "وتاريخاً بصيغة YYYYMMDD وموضوعاً قصيراً بلا فراغات زائدة."
        ),
    },
    {
        "title_ar": "متى يُرفع الملف؟",
        "body_ar": (
            "ارفع النسخة النهائية الموقّعة (PDF مفضّل). المسودات تُحفظ في دفتر "
            "الملاحظات أو كمرفقات مؤقتة حتى الاعتماد."
        ),
    },
    {
        "title_ar": "قائمة التحقق الفصلية",
        "body_ar": (
            "قبل إغلاق الفصل: تحقق من وجود محضر جودة واحد على الأقل، قرار ذي صلة "
            "إن وُجد، قيد صادر/وارد رئيسي، وإغلاق ملاحظات المتابعة أو توثيق حالتها."
        ),
    },
]


def record_type_label(code: str) -> str:
    meta = ARCHIVE_RECORD_TYPES.get((code or "").strip())
    return (meta or {}).get("title_ar") or code or "—"


def suggestions_for_type(record_type: str) -> list[dict[str, str]]:
    return list(ARCHIVE_QAA_SUGGESTIONS.get((record_type or "").strip()) or [])
