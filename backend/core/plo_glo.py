"""مخرجات الخريج على مستوى كلية الهندسة (GLO) — مرجع EAC/ABET."""

from __future__ import annotations

from typing import Any

# كلية الهندسة — صفات الخريج (8) تُربط عبر parent_glo_code في PLO
ENGINEERING_COLLEGE_GLO: tuple[dict[str, Any], ...] = (
    {
        "code": "GLO1",
        "title_ar": "المعرفة الهندسية",
        "title_en": "Engineering Knowledge",
        "domain": "knowledge",
        "description": "تطبيق المعرفة الرياضية والعلوم الأساسية والهندسية في حل المشكلات الهندسية.",
    },
    {
        "code": "GLO2",
        "title_ar": "تحليل المشكلات",
        "title_en": "Problem Analysis",
        "domain": "skills",
        "description": "تحديد وصياغة وتحليل المشكلات الهندسية المعقدة باستخدام مبادئ الهندسة والرياضيات.",
    },
    {
        "code": "GLO3",
        "title_ar": "التصميم والتطوير",
        "title_en": "Design & Development",
        "domain": "skills",
        "description": "تصميم مكونات أو أنظمة أو عمليات لتلبية متطلبات محددة مع مراعاة القيود.",
    },
    {
        "code": "GLO4",
        "title_ar": "التحقيق والتجريب",
        "title_en": "Investigation",
        "domain": "skills",
        "description": "تصميم وتنفيذ تجارب وتحليل البيانات وتفسير النتائج لاستخلاص استنتاجات صالحة.",
    },
    {
        "code": "GLO5",
        "title_ar": "الأدوات الحديثة",
        "title_en": "Modern Tools",
        "domain": "skills",
        "description": "استخدام تقنيات وأدوات ومهارات حديثة — بما فيها الحوسبة — في الممارسة الهندسية.",
    },
    {
        "code": "GLO6",
        "title_ar": "المهندس والمجتمع",
        "title_en": "Engineer & Society",
        "domain": "professional",
        "description": "تقييم الآثار الاجتماعية والصحية والأمنية والثقافية والبيئية للحلول الهندسية.",
    },
    {
        "code": "GLO7",
        "title_ar": "البيئة والاستدامة",
        "title_en": "Environment & Sustainability",
        "domain": "values",
        "description": "فهم تأثير الحلول الهندسية في السياقات البيئية والاجتماعية والاقتصادية المستدامة.",
    },
    {
        "code": "GLO8",
        "title_ar": "الأخلاقيات والمسؤولية المهنية",
        "title_en": "Ethics & Professionalism",
        "domain": "values",
        "description": "الالتزام بأخلاقيات المهنة ومسؤوليات الممارسة الهندسية ومعايير الجودة.",
    },
)

GLO_BY_CODE = {g["code"]: g for g in ENGINEERING_COLLEGE_GLO}

DOMAIN_LABELS_AR = {
    "knowledge": "معرفة",
    "skills": "مهارات",
    "values": "قيم ومسؤولية",
    "professional": "مهنية",
}

BLOOM_LABELS_AR = {
    "remember": "تذكر",
    "understand": "فهم",
    "apply": "تطبيق",
    "analyze": "تحليل",
    "evaluate": "تقييم",
    "create": "إبداع",
}

GOVERNANCE_LABELS_AR = {
    "draft": "مسودة",
    "approved": "معتمد",
    "retired": "موقوف",
}

COVERAGE_LABELS_AR = {
    "": "—",
    "I": "تقديم (I)",
    "R": "تعميق (R)",
    "M": "إتقان/تقييم (M)",
}

COVERAGE_CYCLE = ("", "I", "R", "M")


def next_coverage_level(current: str | None) -> str:
    cur = (current or "").strip().upper()
    if cur not in COVERAGE_CYCLE:
        return "I"
    idx = COVERAGE_CYCLE.index(cur)
    return COVERAGE_CYCLE[(idx + 1) % len(COVERAGE_CYCLE)]


def glo_list() -> list[dict[str, Any]]:
    return [dict(g) for g in ENGINEERING_COLLEGE_GLO]
