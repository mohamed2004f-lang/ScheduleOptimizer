"""قاموس مصطلحات ضمان الجودة — عربي أولاً مع عمود رموز للمرجع في دليل المصطلحات."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# audience: user = يظهر في القاموس والتلميحات | internal = لا يُعرض
# symbol: يُعرض في جدول دليل المصطلحات (قد يكون فارغاً لمصطلحات بلا اختصار)
QUALITY_GLOSSARY: dict[str, dict[str, Any]] = {
    # ——— رموز التخطيط والمخرجات ———
    "ig": {
        "symbol": "IG",
        "title_ar": "الأهداف الاستراتيجية للكلية",
        "definition_ar": (
            "أهداف قابلة للقياس على مستوى الكلية (مثل IG1–IG8) تُربط بالخطة الاستراتيجية "
            "وبأهداف البرامج؛ تُعرض في هوية الكلية واستشارات القطاع."
        ),
        "audience": "user",
        "category_ar": "رموز التخطيط والمخرجات",
    },
    "glo": {
        "symbol": "GLO",
        "title_ar": "مخرجات تعلم الخريج على مستوى الكلية",
        "definition_ar": (
            "قدرات ومعارف ومهارات وقيم يُتوقع من كل خريج — بغض النظر عن التخصص "
            "(GLO1–GLO10 في النظام). تُربط بها مخرجات البرامج (PLO/SO) لا مخرجات المقرر مباشرة."
        ),
        "audience": "user",
        "category_ar": "رموز التخطيط والمخرجات",
    },
    "plo": {
        "symbol": "PLO",
        "title_ar": "مخرجات تعلم البرنامج الأكاديمي",
        "definition_ar": (
            "مخرجات خاصة ببرنامج دراسي (PLO1، PLO2…) تُربط بمخرج خريج واحد أو أكثر (GLO) "
            "وتُغطى عبر المقررات (CLO) في مصفوفة التغطية."
        ),
        "audience": "user",
        "category_ar": "رموز التخطيط والمخرجات",
    },
    "so": {
        "symbol": "SO",
        "title_ar": "مخرجات الطالب (Student Outcomes)",
        "definition_ar": (
            "تسمية بديلة لمخرجات البرنامج في بعض القوالب (SO1–SO6)، خاصة برامج الهندسة؛ "
            "تؤدي نفس دور PLO وتُربط بـ GLO."
        ),
        "audience": "user",
        "category_ar": "رموز التخطيط والمخرجات",
    },
    "clo": {
        "symbol": "CLO",
        "title_ar": "مخرجات تعلم المقرر الدراسي",
        "definition_ar": (
            "ما يُفترض أن يتعلمه الطالب في مقرر محدد (CLO1…)؛ تُربط بـ PLO/SO في مصفوفة "
            "التغطية ولا تُربط مباشرة بـ GLO."
        ),
        "audience": "user",
        "category_ar": "رموز التخطيط والمخرجات",
    },
    "pg": {
        "symbol": "PG",
        "title_ar": "أهداف البرنامج الأكاديمي",
        "definition_ar": (
            "أهداف تخص برنامجاً دراسياً (PG1…) وتُربط بالأهداف الاستراتيجية للكلية (IG) "
            "في ملف البرنامج."
        ),
        "audience": "user",
        "category_ar": "رموز التخطيط والمخرجات",
    },
    "kpi": {
        "symbol": "KPI",
        "title_ar": "مؤشرات قياس الأداء",
        "definition_ar": (
            "مقاييس رقمية أو نوعية تُتابع تحقق الأهداف الاستراتيجية ومخرجات التعلم، "
            "مع أهداف زمنية ومسؤول عن المتابعة في لوحة الجودة."
        ),
        "audience": "user",
        "category_ar": "رموز التخطيط والمخرجات",
    },
    # ——— مجالات مخرجات التعلم (عمود domain) ———
    "domain_program_knowledge": {
        "symbol": "program_knowledge",
        "title_ar": "مجال: معرفة البرنامج",
        "definition_ar": "تصنيف لمخرجات GLO/PLO المتعلقة بالمعرفة الأساسية للتخصص.",
        "audience": "user",
        "category_ar": "مجالات مخرجات التعلم",
    },
    "domain_technical_skills": {
        "symbol": "technical_skills",
        "title_ar": "مجال: مهارات تقنية",
        "definition_ar": "تحليل، تصميم، تجريب، وأدوات حديثة — أغلب GLO2–GLO5.",
        "audience": "user",
        "category_ar": "مجالات مخرجات التعلم",
    },
    "domain_general_skills": {
        "symbol": "general_skills",
        "title_ar": "مجال: مهارات عامة",
        "definition_ar": "تواصل، عمل جماعي، وتعلم مستمر — غالباً GLO9–GLO10.",
        "audience": "user",
        "category_ar": "مجالات مخرجات التعلم",
    },
    "domain_ethical_values": {
        "symbol": "ethical_values",
        "title_ar": "مجال: قيم أخلاقية",
        "definition_ar": "أخلاقيات المهنة والمسؤولية المهنية — GLO8.",
        "audience": "user",
        "category_ar": "مجالات مخرجات التعلم",
    },
    "domain_social_responsibility": {
        "symbol": "social_responsibility",
        "title_ar": "مجال: مسؤولية اجتماعية",
        "definition_ar": "أثر الحلول على المجتمع والصحة والأمن — GLO6.",
        "audience": "user",
        "category_ar": "مجالات مخرجات التعلم",
    },
    "domain_environmental_values": {
        "symbol": "environmental_values",
        "title_ar": "مجال: قيم بيئية",
        "definition_ar": "استدامة والأثر البيئي للحلول الهندسية — GLO7.",
        "audience": "user",
        "category_ar": "مجالات مخرجات التعلم",
    },
    "domain_values_orientation": {
        "symbol": "values_orientation",
        "title_ar": "مجال: قيم / اتجاهات",
        "definition_ar": "توجهات قيمية عامة لمخرجات البرنامج عند الحاجة.",
        "audience": "user",
        "category_ar": "مجالات مخرجات التعلم",
    },
    # ——— الاعتماد والشواهد ———
    "compliance_map": {
        "symbol": "—",
        "title_ar": "خريطة امتثال الاعتماد",
        "definition_ar": (
            "لوحة تعرض معايير ومؤشرات الاعتماد (مؤسسي / برامجي / داخلي) وحالة التحقق "
            "والشواهد والربط اليدوي لكل فصل."
        ),
        "audience": "user",
        "category_ar": "الاعتماد والشواهد",
    },
    "evidence": {
        "symbol": "شاهد",
        "title_ar": "شاهد الاعتماد",
        "definition_ar": (
            "ملف أو تقرير أو لقطة أرشيف يُرفع لإثبات تحقق مؤشر؛ الربط بالاستبيانات "
            "يُجرى يدوياً من خريطة الامتثال (لا ربط إلزامي عند الإغلاق)."
        ),
        "audience": "user",
        "category_ar": "الاعتماد والشواهد",
    },
    "manual_binding": {
        "symbol": "ربط يدوي",
        "title_ar": "ربط مصدر بالمؤشر (يدوي)",
        "definition_ar": (
            "ربط اختياري بين استبيان أو ملف ومؤشر في خريطة الامتثال؛ "
            "لا يُنشأ تلقائياً من خرائط ثابتة أو عند إغلاق الفصل."
        ),
        "audience": "user",
        "category_ar": "الاعتماد والشواهد",
    },
    "source_auto": {
        "symbol": "auto",
        "title_ar": "مؤشر — آلي من النظام",
        "definition_ar": (
            "درجة المؤشر تُحسب من بيانات النظام (تقييمات، سجلات، استبيانات مجمّعة) "
            "عبر «احسب من النظام» في خريطة الامتثال — منفصل عن ربط الشواهد."
        ),
        "audience": "user",
        "category_ar": "الاعتماد والشواهد",
    },
    "source_manual": {
        "symbol": "manual",
        "title_ar": "مؤشر — إدخال يدوي",
        "definition_ar": "درجة المؤشر أو حالة الامتثال تُسجَّل يدوياً من لجنة الجودة بعد المراجعة.",
        "audience": "user",
        "category_ar": "الاعتماد والشواهد",
    },
    "source_hybrid": {
        "symbol": "hybrid",
        "title_ar": "مؤشر — مختلط (آلي + مراجعة)",
        "definition_ar": (
            "مزيج بين إدخال يدوي وبيانات استبيان أو نظام (مثل مؤشر المرافق FF-01-1)؛ "
            "لا يعني ربطاً آلياً للشواهد."
        ),
        "audience": "user",
        "category_ar": "الاعتماد والشواهد",
    },
    "source_document": {
        "symbol": "document",
        "title_ar": "مؤشر — وثيقة / دليل",
        "definition_ar": "يُثبت بالوثائق والسياسات المرفوعة كشواهد لا بدرجة رقمية آلية.",
        "audience": "user",
        "category_ar": "الاعتماد والشواهد",
    },
    "indicator_inst": {
        "symbol": "INST-XX-YY",
        "title_ar": "رمز مؤشر — اعتماد مؤسسي (QAA)",
        "definition_ar": (
            "تنسيق مؤشرات كتالوج المركز للاعتماد المؤسسي (202 مؤشر في QAA-2023.4-INST)، "
            "مثل INST-05-19."
        ),
        "audience": "user",
        "category_ar": "معايير المركز (QAA)",
    },
    "indicator_prog": {
        "symbol": "PROG-UG-XX-YY",
        "title_ar": "رمز مؤشر — اعتماد برامجي بكالوريوس (QAA)",
        "definition_ar": (
            "تنسيق مؤشرات الاعتماد البرامجي للبكالوريوس (139 مؤشر في QAA-2023.4-PROG-UG)."
        ),
        "audience": "user",
        "category_ar": "معايير المركز (QAA)",
    },
    "qaa_axis_mq": {
        "symbol": "qaa_mq",
        "title_ar": "محور: جودة الإدارة (معايير المركز)",
        "definition_ar": "محور في دليل معايير QAA يضم معايير إدارة الجودة على مستوى المؤسسة.",
        "audience": "user",
        "category_ar": "معايير المركز (QAA)",
    },
    "qaa_axis_inst": {
        "symbol": "qaa_inst",
        "title_ar": "محور: الاعتماد المؤسسي (معايير المركز)",
        "definition_ar": "محور معايير الاعتماد المؤسسي في دليل المركز الوطني.",
        "audience": "user",
        "category_ar": "معايير المركز (QAA)",
    },
    "qaa_axis_prog": {
        "symbol": "qaa_prog_ug",
        "title_ar": "محور: الاعتماد البرامجي — بكالوريوس",
        "definition_ar": "محور معايير اعتماد البرامج الأكاديمية (مرحلة البكالوريوس).",
        "audience": "user",
        "category_ar": "معايير المركز (QAA)",
    },
    # ——— الاستبيانات والأرشفة ———
    "surveys_hub": {
        "symbol": "—",
        "title_ar": "مركز تعبئة الاستبيانات",
        "definition_ar": (
            "صفحة موحّدة للطلاب والأساتذة والموظفين: استبيانات الفصل + تقييم المقرر "
            "في قائمة واحدة (/academic_quality/surveys)."
        ),
        "audience": "user",
        "category_ar": "الاستبيانات والأرشفة",
    },
    "semester_snapshot": {
        "symbol": "لقطة فصل",
        "title_ar": "لقطة الفصل الدراسي",
        "definition_ar": (
            "أرشيف ثابت لنتائج استبيانات الفصل عند الإغلاق؛ لا يتغيّر لاحقاً "
            "ويُستخدم للمقارنة والاتجاهات."
        ),
        "audience": "user",
        "category_ar": "الاستبيانات والأرشفة",
    },
    "cycle_snapshot": {
        "symbol": "لقطة دورة",
        "title_ar": "لقطة دورة الاستبيانات الخارجية",
        "definition_ar": "أرشيف ثابت لنتائج حملة دعوة (خريجون أو قطاع) عند إغلاق الدورة.",
        "audience": "user",
        "category_ar": "الاستبيانات والأرشفة",
    },
    "external_cycle": {
        "symbol": "cycle_label",
        "title_ar": "دورة الحملة الخارجية",
        "definition_ar": (
            "تسمية فترة جمع إجابات عبر روابط دعوة (مثل «استشارة قطاع 2026»)؛ "
            "منفصلة عن semester للاستبيانات الداخلية."
        ),
        "audience": "user",
        "category_ar": "الاستبيانات والأرشفة",
    },
    "min_aggregate": {
        "symbol": "min_aggregate",
        "title_ar": "الحد الأدنى للتجميع",
        "definition_ar": (
            "أقل عدد من الإجابات قبل عرض النسبة المجمّعة علناً؛ يحفظ خصوصية المستجيبين "
            "(افتراضياً 3 للمقرر و5 للاستبيانات العامة)."
        ),
        "audience": "user",
        "category_ar": "الاستبيانات والأرشفة",
    },
    # ——— الكتالوج الداخلي (2026.1) ———
    "domain_vision_strategy": {
        "symbol": "vision_strategy",
        "title_ar": "محور داخلي: الرؤية والرسالة والتخطيط",
        "definition_ar": "محور في الكتالوج الداخلي التجريبي (2026.1) — تبويب «امتثال داخلي».",
        "audience": "user",
        "category_ar": "محاور الكتالوج الداخلي",
    },
    "domain_governance": {
        "symbol": "governance",
        "title_ar": "محور داخلي: الحوكمة والإدارة",
        "definition_ar": "سياسات، لجان، وإدارة — في الكتالوج المختصر الداخلي.",
        "audience": "user",
        "category_ar": "محاور الكتالوج الداخلي",
    },
    "domain_human_resources": {
        "symbol": "human_resources",
        "title_ar": "محور داخلي: الموارد البشرية",
        "definition_ar": "مؤهلات هيئة التدريس وتوزيع الأعباء في الكتالوج الداخلي.",
        "audience": "user",
        "category_ar": "محاور الكتالوج الداخلي",
    },
    "domain_facilities_finance": {
        "symbol": "facilities_finance",
        "title_ar": "محور داخلي: المرافق والموارد المالية",
        "definition_ar": "بنية تحتية وميزانية — الكتالوج الداخلي.",
        "audience": "user",
        "category_ar": "محاور الكتالوج الداخلي",
    },
    "domain_quality_assurance": {
        "symbol": "quality_assurance",
        "title_ar": "محور داخلي: ضمان الجودة",
        "definition_ar": "تحسين الأداء ومراجعات البرامج — الكتالوج الداخلي.",
        "audience": "user",
        "category_ar": "محاور الكتالوج الداخلي",
    },
    "domain_student_services": {
        "symbol": "student_services",
        "title_ar": "محور داخلي: الطلبة والخدمات",
        "definition_ar": "رضا الطلبة وخدمات الدعم — الكتالوج الداخلي.",
        "audience": "user",
        "category_ar": "محاور الكتالوج الداخلي",
    },
    "domain_community_research": {
        "symbol": "community_research",
        "title_ar": "محور داخلي: المجتمع والبحث",
        "definition_ar": "شراكات مجتمعية وبحث — الكتالوج الداخلي.",
        "audience": "user",
        "category_ar": "محاور الكتالوج الداخلي",
    },
}

# ترتيب عرض الفئات في دليل المصطلحات
GLOSSARY_CATEGORY_ORDER: tuple[str, ...] = (
    "رموز التخطيط والمخرجات",
    "مجالات مخرجات التعلم",
    "الاعتماد والشواهد",
    "معايير المركز (QAA)",
    "الاستبيانات والأرشفة",
    "محاور الكتالوج الداخلي",
)


def _term_public(key: str, entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": key,
        "symbol": (entry.get("symbol") or "").strip() or "—",
        "title_ar": entry.get("title_ar") or "",
        "definition_ar": entry.get("definition_ar") or "",
        "category_ar": entry.get("category_ar") or "عام",
    }


def user_visible_glossary() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, entry in QUALITY_GLOSSARY.items():
        if entry.get("audience") != "user":
            continue
        out.append(_term_public(key, entry))
    order = {c: i for i, c in enumerate(GLOSSARY_CATEGORY_ORDER)}
    return sorted(
        out,
        key=lambda x: (
            order.get(x.get("category_ar") or "", 99),
            x.get("symbol") or "",
            x.get("title_ar") or "",
        ),
    )


def glossary_by_category() -> list[dict[str, Any]]:
    items = user_visible_glossary()
    cats: dict[str, list] = {}
    for item in items:
        cat = item.get("category_ar") or "عام"
        cats.setdefault(cat, []).append(item)
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cat in GLOSSARY_CATEGORY_ORDER:
        if cat in cats:
            ordered.append({"category_ar": cat, "terms": cats[cat]})
            seen.add(cat)
    for cat in sorted(cats.keys()):
        if cat not in seen:
            ordered.append({"category_ar": cat, "terms": cats[cat]})
    return ordered


def get_term(term_id: str) -> dict[str, Any] | None:
    key = (term_id or "").strip().lower()
    entry = QUALITY_GLOSSARY.get(key)
    if not entry or entry.get("audience") != "user":
        return None
    return _term_public(key, entry)


def glossary_json_for_client() -> dict[str, Any]:
    groups = glossary_by_category()
    terms = {t["id"]: t for t in user_visible_glossary()}
    return {
        "terms": terms,
        "groups": groups,
        "category_order": list(GLOSSARY_CATEGORY_ORDER),
        "version": 2,
    }


def write_static_glossary_json(
    path: Path | None = None,
) -> Path:
    """كتابة JSON الثابت للتلميحات — يُستدعى من الاختبارات أو سكربت صيانة."""
    target = path or (
        Path(__file__).resolve().parents[2] / "frontend" / "static" / "data" / "quality_glossary.json"
    )
    payload = glossary_json_for_client()
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
