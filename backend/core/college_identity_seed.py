"""بذرة هوية الكلية وأهداف IG — بدون اعتماد دولي."""

from __future__ import annotations

import json
from typing import Any

DEFAULT_INTRO_AR = (
    "كلية الهندسة تضم عدداً من الأقسام والبرامج الأكاديمية، وتسعى لتخريج مهندسين "
    "وفق إطار موحّد من مخرجات الخريج (GLO) وأهداف استراتيجية (IG) مرتبطة ببرامجها. "
    "تُدار مخرجات التعلم والتقييم عبر منظومة ScheduleOptimizer لضمان الشفافية والقياس المستمر."
)

DEFAULT_MISSION_AR = (
    "تعليم وتدريب مهندسين متميزين قادرين على تطبيق المعرفة الهندسية والعلمية "
    "لحل المشكلات المعقدة، مع الالتزام بالقيم الأخلاقية والمسؤولية الاجتماعية "
    "والاستدامة البيئية، بما يخدم المجتمع والاقتصاد الوطني."
)

DEFAULT_VISION_AR = (
    "أن تكون كلية الهندسة مركزاً متميزاً وطنياً وإقليمياً للتعليم الهندسي والبحث التطبيقي، "
    "تخرج مهندسين مؤهلين قادرين على المساهمة في التنمية المستدامة والابتكار التكنولوجي "
    "وفق معايير الجودة الوطنية."
)

DEFAULT_STRATEGIC_PLAN_SUMMARY_AR = (
    "تركز الخطة الاستراتيجية للكلية على تحسين جودة التعليم الهندسي ومواءمة المناهج مع "
    "احتياجات سوق العمل، وتطوير مهارات الطلاب الشاملة، وتعزيز البحث والابتكار، وتطوير "
    "البنية التحتية والموارد، وبناء شراكات فعّالة مع القطاع الصناعي والمجتمع، مع التزام "
    "مؤسسي بضمان الجودة والمسؤولية الاجتماعية والاستدامة."
)

CORE_VALUES: list[dict[str, str]] = [
    {"code": "CV1", "title_ar": "التميز الأكاديمي", "description": "السعي لأعلى معايير الجودة في التعليم والبحث."},
    {"code": "CV2", "title_ar": "الابتكار والإبداع", "description": "تشجيع الفكر الناقد والابتكار في حل المشكلات."},
    {"code": "CV3", "title_ar": "الأمانة والنزاهة", "description": "الالتزام بالأخلاقيات والمسؤولية المهنية."},
    {"code": "CV4", "title_ar": "المسؤولية الاجتماعية", "description": "مراعاة أثر الحلول على المجتمع والبيئة."},
    {"code": "CV5", "title_ar": "التعاون والعمل الجماعي", "description": "تعزيز ثقافة الفريق بين الطلاب والأساتذة."},
    {"code": "CV6", "title_ar": "التعلم المستمر", "description": "مواكبة التطورات وتحديث المعارف."},
]

STRATEGIC_GOALS: tuple[dict[str, Any], ...] = (
    {"code": "IG1", "parent_code": "", "title_ar": "تحسين جودة التعليم الهندسي", "pillar": "education", "sort_order": 10,
     "description": "رفع فعالية التعليم عبر مناهج ومخرجات قابلة للقياس وضمان جودة أكاديمي."},
    {"code": "IG1.1", "parent_code": "IG1", "title_ar": "مواءمة المناهج مع مخرجات البرنامج والكلية", "pillar": "education", "sort_order": 11, "description": ""},
    {"code": "IG1.2", "parent_code": "IG1", "title_ar": "مخرجات ومقررات واضحة وقابلة للقياس (CLO/PLO)", "pillar": "education", "sort_order": 12, "description": ""},
    {"code": "IG1.3", "parent_code": "IG1", "title_ar": "نظام شامل لضمان الجودة الأكاديمية", "pillar": "education", "sort_order": 13, "description": ""},
    {"code": "IG1.4", "parent_code": "IG1", "title_ar": "تحسين النجاح في المقررات الحرجة", "pillar": "education", "sort_order": 14, "description": ""},
    {"code": "IG1.5", "parent_code": "IG1", "title_ar": "تقييم فعالية التدريس وتغذية راجعة", "pillar": "education", "sort_order": 15, "description": ""},
    {"code": "IG2", "parent_code": "", "title_ar": "تطوير مهارات الطلاب الشاملة", "pillar": "skills", "sort_order": 20, "description": ""},
    {"code": "IG2.1", "parent_code": "IG2", "title_ar": "المهارات التقنية (تحليل، تصميم، تجريب، أدوات)", "pillar": "skills", "sort_order": 21, "description": ""},
    {"code": "IG2.2", "parent_code": "IG2", "title_ar": "المهارات العامة (تواصل، عمل جماعي، قيادة)", "pillar": "skills", "sort_order": 22, "description": ""},
    {"code": "IG2.3", "parent_code": "IG2", "title_ar": "الفكر الناقد وحل المشكلات المعقدة", "pillar": "skills", "sort_order": 23, "description": ""},
    {"code": "IG2.4", "parent_code": "IG2", "title_ar": "مهارات البحث والابتكار", "pillar": "skills", "sort_order": 24, "description": ""},
    {"code": "IG2.5", "parent_code": "IG2", "title_ar": "الوعي بالمسؤولية الاجتماعية والبيئية", "pillar": "skills", "sort_order": 25, "description": ""},
    {"code": "IG3", "parent_code": "", "title_ar": "تعزيز البحث العلمي والابتكار", "pillar": "research", "sort_order": 30, "description": ""},
    {"code": "IG3.1", "parent_code": "IG3", "title_ar": "زيادة المشاريع البحثية والابتكارية", "pillar": "research", "sort_order": 31, "description": ""},
    {"code": "IG3.2", "parent_code": "IG3", "title_ar": "تشجيع النشر والمشاركة في المؤتمرات", "pillar": "research", "sort_order": 32, "description": ""},
    {"code": "IG3.3", "parent_code": "IG3", "title_ar": "شراكات بحثية أكاديمية وطنية", "pillar": "research", "sort_order": 33, "description": ""},
    {"code": "IG3.4", "parent_code": "IG3", "title_ar": "دعم مشاريع التخرج التطبيقية", "pillar": "research", "sort_order": 34, "description": ""},
    {"code": "IG3.5", "parent_code": "IG3", "title_ar": "حاضنات ابتكار ومختبرات متخصصة", "pillar": "research", "sort_order": 35, "description": ""},
    {"code": "IG4", "parent_code": "", "title_ar": "تطوير البنية التحتية والموارد", "pillar": "infrastructure", "sort_order": 40, "description": ""},
    {"code": "IG4.1", "parent_code": "IG4", "title_ar": "مختبرات حديثة مجهزة", "pillar": "infrastructure", "sort_order": 41, "description": ""},
    {"code": "IG4.2", "parent_code": "IG4", "title_ar": "مكتبة وموارد رقمية", "pillar": "infrastructure", "sort_order": 42, "description": ""},
    {"code": "IG4.3", "parent_code": "IG4", "title_ar": "منظومة تعلم إلكتروني فعّالة", "pillar": "infrastructure", "sort_order": 43, "description": ""},
    {"code": "IG4.4", "parent_code": "IG4", "title_ar": "بيئة تعليمية آمنة وصحية", "pillar": "infrastructure", "sort_order": 44, "description": ""},
    {"code": "IG4.5", "parent_code": "IG4", "title_ar": "استثمار في تقنيات حديثة", "pillar": "infrastructure", "sort_order": 45, "description": ""},
    {"code": "IG5", "parent_code": "", "title_ar": "تطوير الموارد البشرية", "pillar": "faculty", "sort_order": 50, "description": ""},
    {"code": "IG5.1", "parent_code": "IG5", "title_ar": "تطوير مهارات التدريس والتقييم", "pillar": "faculty", "sort_order": 51, "description": ""},
    {"code": "IG5.2", "parent_code": "IG5", "title_ar": "برامج تدريب وورش للأساتذة", "pillar": "faculty", "sort_order": 52, "description": ""},
    {"code": "IG5.3", "parent_code": "IG5", "title_ar": "فرص التطور الأكاديمي والمهني", "pillar": "faculty", "sort_order": 53, "description": ""},
    {"code": "IG5.4", "parent_code": "IG5", "title_ar": "تحسين بيئة العمل والحوافز", "pillar": "faculty", "sort_order": 54, "description": ""},
    {"code": "IG5.5", "parent_code": "IG5", "title_ar": "ثقافة التعلم المستمر", "pillar": "faculty", "sort_order": 55, "description": ""},
    {"code": "IG6", "parent_code": "", "title_ar": "تعزيز الشراكات والتعاون (وطني)", "pillar": "partnerships", "sort_order": 60, "description": ""},
    {"code": "IG6.1", "parent_code": "IG6", "title_ar": "شراكات مع جامعات ومؤسسات وطنية", "pillar": "partnerships", "sort_order": 61, "description": ""},
    {"code": "IG6.2", "parent_code": "IG6", "title_ar": "تعاون مع القطاع الصناعي المحلي", "pillar": "partnerships", "sort_order": 62, "description": ""},
    {"code": "IG6.3", "parent_code": "IG6", "title_ar": "مشاريع مجتمعية وخدمة مجتمع", "pillar": "partnerships", "sort_order": 63, "description": ""},
    {"code": "IG6.4", "parent_code": "IG6", "title_ar": "برامج تبادل أكاديمي (حسب الإمكانيات)", "pillar": "partnerships", "sort_order": 64, "description": ""},
    {"code": "IG6.5", "parent_code": "IG6", "title_ar": "الاستفادة من الخبرات في تطوير البرامج", "pillar": "partnerships", "sort_order": 65, "description": ""},
    {"code": "IG7", "parent_code": "", "title_ar": "ضمان الجودة الأكاديمي المؤسسي (وطني)", "pillar": "quality", "sort_order": 70,
     "description": "مراجعة ذاتية، توثيق، وتغطية مخرجات — دون اعتماد دولي في هذه المرحلة."},
    {"code": "IG7.1", "parent_code": "IG7", "title_ar": "خطة مراجعة ذاتية سنوية للبرامج", "pillar": "quality", "sort_order": 71, "description": ""},
    {"code": "IG7.2", "parent_code": "IG7", "title_ar": "توثيق قرارات الجودة والمجالس", "pillar": "quality", "sort_order": 72, "description": ""},
    {"code": "IG7.3", "parent_code": "IG7", "title_ar": "تغطية كافية لمخرجات البرامج (I/R/M)", "pillar": "quality", "sort_order": 73, "description": ""},
    {"code": "IG7.4", "parent_code": "IG7", "title_ar": "تقييم دوري وفجوات من تحليلات النظام", "pillar": "quality", "sort_order": 74, "description": ""},
    {"code": "IG7.5", "parent_code": "IG7", "title_ar": "أرشفة نسخ معتمدة من المناهج والمخرجات", "pillar": "quality", "sort_order": 75, "description": ""},
    {"code": "IG8", "parent_code": "", "title_ar": "المسؤولية الاجتماعية والاستدامة", "pillar": "sustainability", "sort_order": 80, "description": ""},
    {"code": "IG8.1", "parent_code": "IG8", "title_ar": "محتوى الاستدامة في المناهج", "pillar": "sustainability", "sort_order": 81, "description": ""},
    {"code": "IG8.2", "parent_code": "IG8", "title_ar": "مشاريع بحلول مستدامة", "pillar": "sustainability", "sort_order": 82, "description": ""},
    {"code": "IG8.3", "parent_code": "IG8", "title_ar": "تقليل البصمة البيئية للكلية", "pillar": "sustainability", "sort_order": 83, "description": ""},
    {"code": "IG8.4", "parent_code": "IG8", "title_ar": "مبادرات مجتمعية", "pillar": "sustainability", "sort_order": 84, "description": ""},
    {"code": "IG8.5", "parent_code": "IG8", "title_ar": "توعية بالاستدامة", "pillar": "sustainability", "sort_order": 85, "description": ""},
)

# goal_code -> list of glo codes
IG_GLO_LINKS: dict[str, list[str]] = {
    "IG1": ["GLO1", "GLO2", "GLO3", "GLO4", "GLO5"],
    "IG2": ["GLO2", "GLO3", "GLO4", "GLO5"],
    "IG3": ["GLO3", "GLO4", "GLO5"],
    "IG4": ["GLO5"],
    "IG6": ["GLO6"],
    "IG7": ["GLO1", "GLO2", "GLO3", "GLO4", "GLO5", "GLO6", "GLO7", "GLO8"],
    "IG8": ["GLO6", "GLO7", "GLO8"],
}

DEFAULT_KPIS: tuple[dict[str, Any], ...] = (
    {"goal_code": "IG1", "name_ar": "نسبة المقررات تحقق مخرجاتها ≥ 80%", "target_value": 80.0, "unit": "%", "data_source": "system", "frequency": "annual", "sort_order": 10},
    {"goal_code": "IG1", "name_ar": "معدل رضا الطلاب عن التعليم ≥ 4/5", "target_value": 4.0, "unit": "من 5", "data_source": "survey", "frequency": "semester", "sort_order": 11},
    {"goal_code": "IG2", "name_ar": "نسبة الطلاب تحقق مخرجات البرنامج ≥ 85%", "target_value": 85.0, "unit": "%", "data_source": "system", "frequency": "annual", "sort_order": 20},
    {"goal_code": "IG2", "name_ar": "نسبة الطلاب يمتلكون مهارات تواصل وعمل جماعي فعّالة", "target_value": 80.0, "unit": "%", "data_source": "survey", "frequency": "annual", "sort_order": 21},
    {"goal_code": "IG3", "name_ar": "عدد المشاريع البحثية المنجزة سنوياً", "target_value": 10.0, "unit": "مشروع", "data_source": "manual", "frequency": "annual", "sort_order": 30},
    {"goal_code": "IG3", "name_ar": "عدد الأوراق العلمية المنشورة", "target_value": 5.0, "unit": "ورقة", "data_source": "manual", "frequency": "annual", "sort_order": 31},
    {"goal_code": "IG4", "name_ar": "نسبة المختبرات المجهزة وفق المعايير", "target_value": 75.0, "unit": "%", "data_source": "manual", "frequency": "annual", "sort_order": 40},
    {"goal_code": "IG4", "name_ar": "معدل رضا الطلاب عن البنية التحتية", "target_value": 3.5, "unit": "من 5", "data_source": "survey", "frequency": "semester", "sort_order": 41},
    {"goal_code": "IG5", "name_ar": "عدد ورش التطوير المهني للأساتذة", "target_value": 6.0, "unit": "ورشة", "data_source": "manual", "frequency": "annual", "sort_order": 50},
    {"goal_code": "IG5", "name_ar": "نسبة الأساتذة المشاركين في برامج تدريب", "target_value": 70.0, "unit": "%", "data_source": "manual", "frequency": "annual", "sort_order": 51},
    {"goal_code": "IG6", "name_ar": "عدد اتفاقيات الشراكة الوطنية الفعّالة", "target_value": 3.0, "unit": "اتفاقية", "data_source": "manual", "frequency": "annual", "sort_order": 60},
    {"goal_code": "IG6", "name_ar": "عدد المشاريع المجتمعية المنفذة", "target_value": 4.0, "unit": "مشروع", "data_source": "manual", "frequency": "annual", "sort_order": 61},
    {"goal_code": "IG7", "name_ar": "نسبة PLO ذات تغطية M كافية (≥3 مقررات)", "target_value": 90.0, "unit": "%", "data_source": "system", "frequency": "annual", "sort_order": 70},
    {"goal_code": "IG7", "name_ar": "إتمام المراجعة الذاتية السنوية للبرامج", "target_value": 100.0, "unit": "%", "data_source": "manual", "frequency": "annual", "sort_order": 71},
    {"goal_code": "IG8", "name_ar": "نسبة مقررات بمحتوى استدامة/مسؤولية", "target_value": 60.0, "unit": "%", "data_source": "manual", "frequency": "annual", "sort_order": 80},
    {"goal_code": "IG8", "name_ar": "عدد المبادرات المجتمعية المنفذة", "target_value": 3.0, "unit": "مبادرة", "data_source": "manual", "frequency": "annual", "sort_order": 81},
)


def seed_college_identity_defaults(conn) -> dict[str, int]:
    cur = conn.cursor()
    stats = {"identity": 0, "goals": 0, "links": 0, "kpis": 0}
    try:
        n = cur.execute("SELECT COUNT(*) FROM college_identity").fetchone()
        cnt = int(n[0] if not hasattr(n, "keys") else list(n.values())[0])
    except Exception:
        cnt = 0
    if cnt == 0:
        cur.execute(
            """
            INSERT INTO college_identity (
                intro_ar, mission_ar, vision_ar, strategic_plan_summary_ar, values_json,
                effective_from, governance_status, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, 'approved', 1)
            """,
            (
                DEFAULT_INTRO_AR,
                DEFAULT_MISSION_AR,
                DEFAULT_VISION_AR,
                DEFAULT_STRATEGIC_PLAN_SUMMARY_AR,
                json.dumps(CORE_VALUES, ensure_ascii=False),
                "2025-2026",
            ),
        )
        stats["identity"] = 1
    try:
        gcnt = cur.execute("SELECT COUNT(*) FROM college_strategic_goals").fetchone()
        g_n = int(gcnt[0] if not hasattr(gcnt, "keys") else list(gcnt.values())[0])
    except Exception:
        g_n = 0
    if g_n == 0:
        for g in STRATEGIC_GOALS:
            cur.execute(
                """
                INSERT INTO college_strategic_goals (
                    code, parent_code, title_ar, title_en, description,
                    pillar, sort_order, governance_status, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'approved', 1)
                """,
                (
                    g["code"],
                    g.get("parent_code") or "",
                    g["title_ar"],
                    g.get("title_en") or "",
                    g.get("description") or "",
                    g.get("pillar") or "",
                    int(g.get("sort_order") or 0),
                ),
            )
            stats["goals"] += 1
    try:
        lcnt = cur.execute("SELECT COUNT(*) FROM college_goal_glo_links").fetchone()
        l_n = int(lcnt[0] if not hasattr(lcnt, "keys") else list(lcnt.values())[0])
    except Exception:
        l_n = 0
    if l_n == 0:
        for goal_code, glos in IG_GLO_LINKS.items():
            for glo in glos:
                try:
                    cur.execute(
                        """
                        INSERT INTO college_goal_glo_links (goal_code, glo_code, alignment)
                        VALUES (?, ?, 'primary')
                        """,
                        (goal_code, glo.upper()),
                    )
                    stats["links"] += 1
                except Exception:
                    pass
    try:
        kcnt = cur.execute("SELECT COUNT(*) FROM goal_kpi").fetchone()
        k_n = int(kcnt[0] if not hasattr(kcnt, "keys") else list(kcnt.values())[0])
    except Exception:
        k_n = 0
    if k_n == 0:
        for i, k in enumerate(DEFAULT_KPIS):
            cur.execute(
                """
                INSERT INTO goal_kpi (
                    goal_code, name_ar, target_value, unit, frequency,
                    data_source, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    k["goal_code"],
                    k["name_ar"],
                    k.get("target_value"),
                    k.get("unit") or "",
                    k.get("frequency") or "annual",
                    k.get("data_source") or "manual",
                    int(k.get("sort_order") or i * 10),
                ),
            )
            stats["kpis"] += 1
    _ensure_all_kpis_seeded(cur)
    try:
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    return stats


def _ensure_all_kpis_seeded(cur):
    """تُكمل KPIs الناقصة إذا أضيفت أهداف جديدة في DEFAULT_KPIS."""
    for k in DEFAULT_KPIS:
        try:
            exists = cur.execute(
                "SELECT 1 FROM goal_kpi WHERE goal_code = ? AND name_ar = ?",
                (k["goal_code"], k["name_ar"]),
            ).fetchone()
            if not exists:
                cur.execute(
                    """
                    INSERT INTO goal_kpi (
                        goal_code, name_ar, target_value, unit, frequency,
                        data_source, sort_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        k["goal_code"],
                        k["name_ar"],
                        k.get("target_value"),
                        k.get("unit") or "",
                        k.get("frequency") or "annual",
                        k.get("data_source") or "manual",
                        int(k.get("sort_order") or 0),
                    ),
                )
        except Exception:
            pass
