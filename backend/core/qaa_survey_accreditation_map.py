"""ربط استبيانات المنظومة بمؤشرات QAA الرسمية (إصدار المركز 2023.4)."""

from __future__ import annotations

from typing import Any

QAA_INST_CATALOG = "QAA-2023.4-INST"
QAA_PROG_UG_CATALOG = "QAA-2023.4-PROG-UG"

QAA_CATALOG_VERSIONS: tuple[str, ...] = (QAA_INST_CATALOG, QAA_PROG_UG_CATALOG)

# template_code → قائمة روابط (لكل كتالوج QAA)
QAA_SURVEY_ACCREDITATION_MAP: dict[str, list[dict[str, str]]] = {
    "student_course": [
        {
            "catalog_version": QAA_INST_CATALOG,
            "indicator_code": "INST-09-15",
            "link_type": "evidence",
            "usage_ar": "شاهد اختياري — استطلاع آراء الطلاب (ربط يدوي من واجهة إدارة).",
        },
        {
            "catalog_version": QAA_INST_CATALOG,
            "indicator_code": "INST-05-19",
            "link_type": "evidence",
            "usage_ar": "استطلاع آراء الطلاب في جوانب محددة من العملية التعليمية.",
        },
        {
            "catalog_version": QAA_INST_CATALOG,
            "indicator_code": "INST-05-20",
            "link_type": "evidence",
            "usage_ar": "الاستفادة من استطلاع آراء الطلاب.",
        },
        {
            "catalog_version": QAA_PROG_UG_CATALOG,
            "indicator_code": "PROG-UG-02-20",
            "link_type": "evidence",
            "usage_ar": "استطلاع آراء منتسبي البرنامج في تطويره.",
        },
        {
            "catalog_version": QAA_PROG_UG_CATALOG,
            "indicator_code": "PROG-UG-02-21",
            "link_type": "evidence",
            "usage_ar": "الاستفادة من التغذية الراجعة من استطلاعات منتسبي البرنامج.",
        },
        {
            "catalog_version": QAA_PROG_UG_CATALOG,
            "indicator_code": "PROG-UG-08-08",
            "link_type": "evidence",
            "usage_ar": "شاهد اختياري — نتائج تقييم المقرر (ربط يدوي).",
        },
    ],
    "student_services": [
        {
            "catalog_version": QAA_INST_CATALOG,
            "indicator_code": "INST-05-19",
            "link_type": "evidence",
            "usage_ar": "رضا الطلبة — خدمات الشؤون والتسجيل.",
        },
        {
            "catalog_version": QAA_INST_CATALOG,
            "indicator_code": "INST-05-20",
            "link_type": "evidence",
            "usage_ar": "الاستفادة من آراء الطلاب في خدمات الشؤون.",
        },
        {
            "catalog_version": QAA_PROG_UG_CATALOG,
            "indicator_code": "PROG-UG-02-20",
            "link_type": "evidence",
            "usage_ar": "استطلاع منتسبي البرنامج — خدمات الطالب.",
        },
    ],
    "student_facilities": [
        {
            "catalog_version": QAA_INST_CATALOG,
            "indicator_code": "INST-06-20",
            "link_type": "hybrid",
            "usage_ar": "تقييم المرافق — يُكمّل الإدخال اليدوي للبنية التحتية.",
        },
        {
            "catalog_version": QAA_PROG_UG_CATALOG,
            "indicator_code": "PROG-UG-05-10",
            "link_type": "hybrid",
            "usage_ar": "مرافق البرنامج — استبيان رضا الطلاب عن المرافق.",
        },
    ],
    "faculty_hod": [
        {
            "catalog_version": QAA_INST_CATALOG,
            "indicator_code": "INST-02-06",
            "link_type": "evidence",
            "usage_ar": "قياس رضا منتسبي المؤسسة عن قيادة المؤسسة — منظور الأستاذ.",
        },
        {
            "catalog_version": QAA_PROG_UG_CATALOG,
            "indicator_code": "PROG-UG-03-06",
            "link_type": "evidence",
            "usage_ar": "قياس رضا أعضاء هيئة التدريس — تقييم رئيس القسم.",
        },
    ],
    "faculty_dean": [
        {
            "catalog_version": QAA_INST_CATALOG,
            "indicator_code": "INST-02-01",
            "link_type": "evidence",
            "usage_ar": "الحوكمة والسياسات — منظور هيئة التدريس.",
        },
        {
            "catalog_version": QAA_INST_CATALOG,
            "indicator_code": "INST-02-06",
            "link_type": "evidence",
            "usage_ar": "رضا المنتسبين عن القيادة والإدارة.",
        },
        {
            "catalog_version": QAA_PROG_UG_CATALOG,
            "indicator_code": "PROG-UG-03-07",
            "link_type": "evidence",
            "usage_ar": "الاستفادة من نتائج قياس رضا هيئة التدريس.",
        },
    ],
    "faculty_educational_process": [
        {
            "catalog_version": QAA_INST_CATALOG,
            "indicator_code": "INST-04-20",
            "link_type": "evidence",
            "usage_ar": "الاستفادة من تقارير/تقييمات المقررات — منظور الأستاذ.",
        },
        {
            "catalog_version": QAA_PROG_UG_CATALOG,
            "indicator_code": "PROG-UG-08-08",
            "link_type": "evidence",
            "usage_ar": "مراجعة طرق تقييم أداء الطلاب.",
        },
        {
            "catalog_version": QAA_PROG_UG_CATALOG,
            "indicator_code": "PROG-UG-08-11",
            "link_type": "evidence",
            "usage_ar": "مراجعة اللوائح والأنظمة في العملية التعليمية.",
        },
    ],
    "supervisor_advising": [
        {
            "catalog_version": QAA_INST_CATALOG,
            "indicator_code": "INST-05-21",
            "link_type": "evidence",
            "usage_ar": "مشاركة الطلاب — جودة الإرشاد والمتابعة.",
        },
        {
            "catalog_version": QAA_PROG_UG_CATALOG,
            "indicator_code": "PROG-UG-03-08",
            "link_type": "evidence",
            "usage_ar": "الإرشاد الأكاديمي — منظور المشرف.",
        },
    ],
    "supervisor_coordination": [
        {
            "catalog_version": QAA_INST_CATALOG,
            "indicator_code": "INST-09-15",
            "link_type": "evidence",
            "usage_ar": "تنسيق المشرف مع القسم — شاهد نوعي.",
        },
        {
            "catalog_version": QAA_PROG_UG_CATALOG,
            "indicator_code": "PROG-UG-08-07",
            "link_type": "evidence",
            "usage_ar": "مشاركة وحدة الجودة في تقييم العملية التعليمية.",
        },
    ],
    "staff_workplace": [
        {
            "catalog_version": QAA_INST_CATALOG,
            "indicator_code": "INST-03-06",
            "link_type": "evidence",
            "usage_ar": "تقييم أعضاء هيئة التدريس — بيئة عمل الموظف.",
        },
        {
            "catalog_version": QAA_PROG_UG_CATALOG,
            "indicator_code": "PROG-UG-03-06",
            "link_type": "evidence",
            "usage_ar": "رضا الكوادر المساندة.",
        },
    ],
    "staff_student_services": [
        {
            "catalog_version": QAA_INST_CATALOG,
            "indicator_code": "INST-05-19",
            "link_type": "evidence",
            "usage_ar": "منظور الموظف لجودة خدمة الطالب.",
        },
        {
            "catalog_version": QAA_PROG_UG_CATALOG,
            "indicator_code": "PROG-UG-02-20",
            "link_type": "evidence",
            "usage_ar": "خدمات الطالب — منظور الموظف.",
        },
    ],
    "employer_strategic": [
        {
            "catalog_version": QAA_INST_CATALOG,
            "indicator_code": "INST-08-07",
            "link_type": "evidence",
            "usage_ar": "استطلاع رأي المجتمع وقطاع العمل.",
        },
        {
            "catalog_version": QAA_INST_CATALOG,
            "indicator_code": "INST-05-23",
            "link_type": "evidence",
            "usage_ar": "متابعة الخريجين والاستفادة من آراء أصحاب المصلحة.",
        },
        {
            "catalog_version": QAA_PROG_UG_CATALOG,
            "indicator_code": "PROG-UG-08-13",
            "link_type": "evidence",
            "usage_ar": "الاستفادة من آراء الخريجين وأرباب العمل.",
        },
    ],
    "alumni": [
        {
            "catalog_version": QAA_INST_CATALOG,
            "indicator_code": "INST-05-23",
            "link_type": "evidence",
            "usage_ar": "متابعة الخريجين والاستفادة من آرائهم.",
        },
        {
            "catalog_version": QAA_PROG_UG_CATALOG,
            "indicator_code": "PROG-UG-08-12",
            "link_type": "evidence",
            "usage_ar": "متابعة أداء الخريجين.",
        },
        {
            "catalog_version": QAA_PROG_UG_CATALOG,
            "indicator_code": "PROG-UG-08-13",
            "link_type": "evidence",
            "usage_ar": "الاستفادة من آراء الخريجين في التحسين.",
        },
    ],
}


def qaa_links_for_template(
    template_code: str,
    *,
    catalog_version: str | None = None,
) -> list[dict[str, Any]]:
    """روابط QAA لقالب استبيان (اختياري: فلترة بكتالوج واحد)."""
    tpl = (template_code or "").strip()
    links = list(QAA_SURVEY_ACCREDITATION_MAP.get(tpl) or [])
    if catalog_version:
        cat = catalog_version.strip()
        links = [lk for lk in links if (lk.get("catalog_version") or "") == cat]
    return [{**lk, "template_code": tpl} for lk in links]


def all_qaa_survey_template_codes() -> list[str]:
    return sorted(QAA_SURVEY_ACCREDITATION_MAP.keys())
