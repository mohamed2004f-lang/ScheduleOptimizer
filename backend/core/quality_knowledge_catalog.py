"""كتالوج مكتبة معرفة مساعد الجودة — تصنيفات وحالات وصلاحيات."""

from __future__ import annotations

from typing import Any

KNOWLEDGE_CATEGORIES: dict[str, dict[str, str]] = {
    "mission_vision": {
        "code": "mission_vision",
        "title_ar": "رسالة ورؤية وصياغة استراتيجية",
    },
    "outcomes_obe": {
        "code": "outcomes_obe",
        "title_ar": "مخرجات التعلم (OBE)",
    },
    "evidence_review": {
        "code": "evidence_review",
        "title_ar": "شواهد وأسئلة مراجعة",
    },
    "global_summary": {
        "code": "global_summary",
        "title_ar": "ملخصات مراجع عالمية",
    },
    "qaa_local": {
        "code": "qaa_local",
        "title_ar": "معايير QAA المحلية / أدلة المركز",
    },
    "committee_notes": {
        "code": "committee_notes",
        "title_ar": "ملاحظات لجنة / سياسات داخلية",
    },
    "other": {
        "code": "other",
        "title_ar": "أخرى",
    },
}

KNOWLEDGE_STATUSES: dict[str, str] = {
    "draft": "مسودة",
    "pending_review": "بانتظار الاعتماد",
    "approved": "معتمد للاستخدام في المساعد",
    "archived": "مؤرشف",
}

# من يرفع ومن يعتمد
UPLOAD_ROLES = (
    "admin",
    "admin_main",
    "system_admin",
    "college_dean",
    "academic_vice_dean",
    "head_of_department",
)

APPROVE_ROLES = (
    "admin",
    "admin_main",
    "system_admin",
    "college_dean",
    "academic_vice_dean",
)

READ_ROLES = UPLOAD_ROLES + ("instructor",)

ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".docx", ".json"}
MAX_FILE_BYTES = 20 * 1024 * 1024

LIBRARY_POLICY_AR = (
    "ارفع فقط وثائق تملك الكلية حق استخدامها. لا ترفع نصوص معايير محمية سُحبت من الإنترنت "
    "بدون ترخيص. المساعد يسترجع مقتطفات للاقتراح فقط ولا يعتمد امتثالاً."
)


def catalog_payload() -> dict[str, Any]:
    return {
        "categories": [
            {"code": c, "title_ar": m["title_ar"]} for c, m in KNOWLEDGE_CATEGORIES.items()
        ],
        "statuses": [{"code": k, "title_ar": v} for k, v in KNOWLEDGE_STATUSES.items()],
        "policy_ar": LIBRARY_POLICY_AR,
        "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
        "max_file_mb": MAX_FILE_BYTES // (1024 * 1024),
        "suggestion_only": True,
    }
