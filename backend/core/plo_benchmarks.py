"""قوالب مخرجات جاهزة — كلية الهندسة (ABET/EAC) حسب القسم والشعبة."""

from __future__ import annotations

from typing import Any

# (template_code, name_ar, framework, department_codes, track_groups, outcomes)
# track_groups: فارغ = كل الشعب؛ أو ["PWR","MFG"] إلخ

def _mech_sos_2026() -> list[dict[str, Any]]:
    """مخرجات طالب برنامج ميكانيك — 6 SO (وثيقة القسم)."""
    from backend.core.program_goals import MECH_STUDENT_OUTCOMES

    return list(MECH_STUDENT_OUTCOMES)


def _abet7() -> list[dict[str, Any]]:
    """ABET Student Outcomes — الإصدار السبعة (مرجع لكل أقسام الهندسة)."""
    return [
        {
            "code": "PLO1",
            "title_ar": "حل المشكلات الهندسية المعقدة",
            "title_en": "Engineering Problem Solving",
            "domain": "skills",
            "bloom_level": "analyze",
            "accreditation_tag": "ABET-1",
            "parent_glo_code": "GLO2",
            "description": "تحديد وصياغة وحل مشكلات هندسية معقدة بتطبيق مبادئ الهندسة والرياضيات وعلوم الطبيعة.",
            "performance_indicator": "يحل ≥80% من مسائل التصميم/التحليل المعيارية للمستوى المستهدف.",
        },
        {
            "code": "PLO2",
            "title_ar": "التصميم الهندسي",
            "title_en": "Engineering Design",
            "domain": "skills",
            "bloom_level": "create",
            "accreditation_tag": "ABET-2",
            "parent_glo_code": "GLO3",
            "description": "تطبيق إجراءات التصميم الهندسي لإنتاج حلول تلبي احتياجات محددة مع مراعاة الصحة والسلامة والرفاه.",
            "performance_indicator": "يُنجز مشروع تصميم متكامل يحقق المتطلبات الوظيفية والاقتصادية والبيئية.",
        },
        {
            "code": "PLO3",
            "title_ar": "التواصل الفعّال",
            "title_en": "Effective Communication",
            "domain": "professional",
            "bloom_level": "apply",
            "accreditation_tag": "ABET-3",
            "parent_glo_code": "GLO6",
            "description": "التواصل الفعّال مع مجموعات متنوعة كتابةً وشفهياً في سياقات هندسية.",
            "performance_indicator": "يقدّم تقارير فنية وعروضاً واضحة وفق معايير المهنة.",
        },
        {
            "code": "PLO4",
            "title_ar": "المسؤولية الأخلاقية والمهنية",
            "title_en": "Ethics & Professional Responsibility",
            "domain": "values",
            "bloom_level": "evaluate",
            "accreditation_tag": "ABET-4",
            "parent_glo_code": "GLO8",
            "description": "إدراك المسؤوليات الأخلاقية والمهنية وآثار الحلول الهندسية في السياق العالمي والاجتماعي.",
            "performance_indicator": "يُظهر التزاماً بقواعد السلوك المهني في سيناريوهات عمل جماعية.",
        },
        {
            "code": "PLO5",
            "title_ar": "العمل ضمن فرق",
            "title_en": "Teamwork",
            "domain": "professional",
            "bloom_level": "apply",
            "accreditation_tag": "ABET-5",
            "parent_glo_code": "GLO5",
            "description": "العمل بفعالية ضمن فرق ذات قيادة مشتركة وبيئات تعاونية وهيكلية.",
            "performance_indicator": "يساهم في أدوار الفريق ويُنجز مخرجات مشتركة في مشروع متعدد التخصصات.",
        },
        {
            "code": "PLO6",
            "title_ar": "التجريب وتحليل البيانات",
            "title_en": "Experimentation & Data Analysis",
            "domain": "skills",
            "bloom_level": "analyze",
            "accreditation_tag": "ABET-6",
            "parent_glo_code": "GLO4",
            "description": "تطوير وإجراء تجارب مناسبة وتحليل وتفسير البيانات واستخدام الحكم الهندسي لاستخلاص النتائج.",
            "performance_indicator": "يصمم تجربة ويحلل بياناتها ضمن هامش خطأ مقبول.",
        },
        {
            "code": "PLO7",
            "title_ar": "التعلم مدى الحياة",
            "title_en": "Lifelong Learning",
            "domain": "knowledge",
            "bloom_level": "apply",
            "accreditation_tag": "ABET-7",
            "parent_glo_code": "GLO1",
            "description": "اكتساب المعرفة وتطبيقها حسب الحاجة باستخدام استراتيجيات تعلم مناسبة.",
            "performance_indicator": "يُحدّث معارفه بأدوات/تقنيات جديدة ذات صلة بالتخصص.",
        },
    ]


def _mech_pwr_supplement() -> list[dict[str, Any]]:
    return [
        {
            "code": "PLO8",
            "title_ar": "أنظمة الطاقة والموائع",
            "title_en": "Energy & Fluid Power Systems",
            "domain": "skills",
            "bloom_level": "apply",
            "accreditation_tag": "MECH-PWR",
            "parent_glo_code": "GLO3",
            "description": "تحليل وتصميم أنظمة الطاقة الحرارية والهيدروليكية والضواغط في التطبيقات الميكانيكية.",
            "performance_indicator": "يُقيّم أداء نظام طاقة/موائع ضمن مواصفات تشغيلية.",
        },
    ]


def _mech_mfg_supplement() -> list[dict[str, Any]]:
    return [
        {
            "code": "PLO8",
            "title_ar": "التصنيع وإدارة العمليات",
            "title_en": "Manufacturing & Operations",
            "domain": "skills",
            "bloom_level": "apply",
            "accreditation_tag": "MECH-MFG",
            "parent_glo_code": "GLO3",
            "description": "تطبيق مبادئ التصنيع وتحسين العمليات والجودة في الإنتاج.",
            "performance_indicator": "يُقترح عملية تصنيع/تخطيط إنتاج تلبي معايير الجودة والتكلفة.",
        },
    ]


def _mech_des_supplement() -> list[dict[str, Any]]:
    return [
        {
            "code": "PLO8",
            "title_ar": "التصميم الميكانيكي المتقدم",
            "title_en": "Advanced Mechanical Design",
            "domain": "skills",
            "bloom_level": "create",
            "accreditation_tag": "MECH-DES",
            "parent_glo_code": "GLO3",
            "description": "استخدام CAD/FEA والتحليل الميكانيكي في تصميم مكونات وآلات.",
            "performance_indicator": "يُنجز نموذج تصميم محاكى يحقق معايير الإجهاد/الانحراف.",
        },
    ]


def _civil_supplement() -> list[dict[str, Any]]:
    return [
        {
            "code": "PLO8",
            "title_ar": "البنية التحتية والإنشاءات",
            "title_en": "Infrastructure & Structures",
            "domain": "skills",
            "bloom_level": "apply",
            "accreditation_tag": "CIVIL-8",
            "parent_glo_code": "GLO3",
            "description": "تصميم وتحليل عناصر إنشائية ومرافق بنية تحتية وفق أكواد ومعايير معتمدة.",
            "performance_indicator": "يُحقق متطلبات السلامة الهيكلية في مشروع إنشائي نموذجي.",
        },
    ]


def _elec_supplement() -> list[dict[str, Any]]:
    return [
        {
            "code": "PLO8",
            "title_ar": "الأنظمة الكهربائية والإلكترونية",
            "title_en": "Electrical & Electronic Systems",
            "domain": "skills",
            "bloom_level": "apply",
            "accreditation_tag": "ELEC-8",
            "parent_glo_code": "GLO3",
            "description": "تحليل وتصميم دوائر وأنظمة كهربائية/إلكترونية وقوى وتحكم.",
            "performance_indicator": "يُصمم نظاماً كهربائياً يحقق مواصفات الأداء والسلامة.",
        },
    ]


def _civil_str_supplement() -> list[dict[str, Any]]:
    return [
        {
            "code": "PLO8",
            "title_ar": "التحليل والتصميم الإنشائي",
            "title_en": "Structural Analysis & Design",
            "domain": "skills",
            "bloom_level": "create",
            "accreditation_tag": "CIVIL-STR",
            "parent_glo_code": "GLO3",
            "description": "تحليل وتصميم العناصر والمنشآت الإنشائية وفق الأكواد.",
            "performance_indicator": "يُصمم عنصراً إنشائياً يحقق معايير السلامة والخدمة.",
        },
    ]


def _civil_geo_supplement() -> list[dict[str, Any]]:
    return [
        {
            "code": "PLO8",
            "title_ar": "الجيوتقنية والأساسات",
            "title_en": "Geotechnical & Foundations",
            "domain": "skills",
            "bloom_level": "analyze",
            "accreditation_tag": "CIVIL-GEO",
            "parent_glo_code": "GLO2",
            "description": "تقييم خواص التربة وتصميم الأساسات والمنحدرات.",
            "performance_indicator": "يُحلل مسألة استقرار/حمل تربة نموذجية.",
        },
    ]


def _civil_wtr_supplement() -> list[dict[str, Any]]:
    return [
        {
            "code": "PLO8",
            "title_ar": "الموارد المائية والبيئة",
            "title_en": "Water Resources & Environment",
            "domain": "skills",
            "bloom_level": "apply",
            "accreditation_tag": "CIVIL-WTR",
            "parent_glo_code": "GLO7",
            "description": "تخطيط وإدارة موارد مائية وشبكات صرف ومشاريع بيئية.",
            "performance_indicator": "يُقترح حلاً هيدروليكياً/بيئياً لمشروع مائي.",
        },
    ]


def _elec_pwr_track_supplement() -> list[dict[str, Any]]:
    return [
        {
            "code": "PLO8",
            "title_ar": "أنظمة القدرة والطاقة الكهربائية",
            "title_en": "Electric Power Systems",
            "domain": "skills",
            "bloom_level": "apply",
            "accreditation_tag": "ELEC-PWR",
            "parent_glo_code": "GLO3",
            "description": "تحليل وتصميم أنظمة توليد ونقل وتوزيع القدرة.",
            "performance_indicator": "يُقيّم أداء محطة/شبكة قدرة نموذجية.",
        },
    ]


def _elec_com_supplement() -> list[dict[str, Any]]:
    return [
        {
            "code": "PLO8",
            "title_ar": "الاتصالات والإشارات",
            "title_en": "Communications & Signals",
            "domain": "skills",
            "bloom_level": "analyze",
            "accreditation_tag": "ELEC-COM",
            "parent_glo_code": "GLO5",
            "description": "تحليل وتصميم أنظمة اتصالات رقمية وإشارات.",
            "performance_indicator": "يُحاكي/يُحلل قناة اتصال أو ترميزاً أساسياً.",
        },
    ]


def _elec_ctl_supplement() -> list[dict[str, Any]]:
    return [
        {
            "code": "PLO8",
            "title_ar": "التحكم الآلي والأتمتة",
            "title_en": "Control & Automation",
            "domain": "skills",
            "bloom_level": "apply",
            "accreditation_tag": "ELEC-CTL",
            "parent_glo_code": "GLO3",
            "description": "نمذجة وتحليل وتصميم أنظمة تحكم خطية وغير خطية.",
            "performance_indicator": "يُصمم منظومة تحكم تلبي مواصفات الاستقرار.",
        },
    ]


def _renew_sol_supplement() -> list[dict[str, Any]]:
    return [
        {
            "code": "PLO8",
            "title_ar": "أنظمة الطاقة الشمسية",
            "title_en": "Solar Energy Systems",
            "domain": "skills",
            "bloom_level": "apply",
            "accreditation_tag": "RENEW-SOL",
            "parent_glo_code": "GLO7",
            "description": "تحليل وتصميم منظومات PV/حرارية شمسية.",
            "performance_indicator": "يُقدّر إنتاج طاقة منظومة شمسية لموقع محدد.",
        },
    ]


def _renew_wnd_supplement() -> list[dict[str, Any]]:
    return [
        {
            "code": "PLO8",
            "title_ar": "أنظمة طاقة الرياح",
            "title_en": "Wind Energy Systems",
            "domain": "skills",
            "bloom_level": "apply",
            "accreditation_tag": "RENEW-WND",
            "parent_glo_code": "GLO7",
            "description": "تحليل موارد الرياح وتصميم توربينات ومنظومات رياح.",
            "performance_indicator": "يُقارن خيارات توليد رياح لموقع محدد.",
        },
    ]


def _renew_supplement() -> list[dict[str, Any]]:
    return [
        {
            "code": "PLO8",
            "title_ar": "أنظمة الطاقة المتجددة",
            "title_en": "Renewable Energy Systems",
            "domain": "skills",
            "bloom_level": "apply",
            "accreditation_tag": "RENEW-8",
            "parent_glo_code": "GLO7",
            "description": "تحليل وتصميم أنظمة طاقة متجددة وتقييم كفاءتها واستدامتها.",
            "performance_indicator": "يُقارن حلول طاقة متجددة اقتصادياً وفنياً لمشروع محدد.",
        },
    ]


def _general_foundation() -> list[dict[str, Any]]:
    """القسم العام — تهيئة قبل التنسيب (EAC foundation)."""
    return [
        {
            "code": "PLO1",
            "title_ar": "الرياضيات والعلوم الأساسية",
            "title_en": "Math & Basic Sciences",
            "domain": "knowledge",
            "bloom_level": "apply",
            "accreditation_tag": "EAC-G1",
            "parent_glo_code": "GLO1",
            "description": "تطبيق مفاهيم الرياضيات والفيزياء والكيمياء في مسائل هندسية تمهيدية.",
            "performance_indicator": "يحل مسائل معيارية في حساب التفاضل والجبر والفيزياء.",
        },
        {
            "code": "PLO2",
            "title_ar": "مقدمة في الهندسة والتصميم",
            "title_en": "Intro to Engineering & Design",
            "domain": "skills",
            "bloom_level": "apply",
            "accreditation_tag": "EAC-G2",
            "parent_glo_code": "GLO3",
            "description": "فهم منهجية حل المشكلات والتصميم الهندسي الأولي والرسومات.",
            "performance_indicator": "يُنجز مشروع تصميم تمهيدي ضمن فريق.",
        },
        {
            "code": "PLO3",
            "title_ar": "مهارات الحاسوب والتواصل",
            "title_en": "Computing & Communication",
            "domain": "skills",
            "bloom_level": "apply",
            "accreditation_tag": "EAC-G3",
            "parent_glo_code": "GLO5",
            "description": "استخدام أدوات الحاسوب والبرمجة التمهيدية والتواصل الفني.",
            "performance_indicator": "يُعد تقريراً فنياً ويستخدم أداة حاسوبية مناسبة.",
        },
        {
            "code": "PLO4",
            "title_ar": "الوعي المهني والأخلاقيات",
            "title_en": "Professional Awareness",
            "domain": "values",
            "bloom_level": "understand",
            "accreditation_tag": "EAC-G4",
            "parent_glo_code": "GLO8",
            "description": "إدراك أخلاقيات المهنة ومسارات التخصصات الهندسية.",
            "performance_indicator": "يُظهر فهماً لقواعد السلوك المهني في أنشطة صفية.",
        },
    ]


BENCHMARK_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "code": "mech_sos_2026",
        "name_ar": "ميكانيك — أهداف البرنامج + 6 مخرجات (SO)",
        "name_en": "MECH Program Goals + 6 Student Outcomes",
        "framework": "MECH",
        "department_codes": ["MECH"],
        "track_groups": [],
        "outcomes": _mech_sos_2026(),
    },
    {
        "code": "abet_v7",
        "name_ar": "ABET — مخرجات الطالب (7) — أساس كل الأقسام",
        "name_en": "ABET Student Outcomes (7)",
        "framework": "ABET",
        "department_codes": ["MECH", "CIVIL", "ELEC", "RENEW"],
        "track_groups": [],
        "outcomes": _abet7(),
    },
    {
        "code": "mech_pwr",
        "name_ar": "ميكانيك — شعبة القوى (إضافة PLO8)",
        "name_en": "MECH Power Track Supplement",
        "framework": "ABET+Track",
        "department_codes": ["MECH"],
        "track_groups": ["PWR"],
        "requires_base": "abet_v7",
        "outcomes": _mech_pwr_supplement(),
    },
    {
        "code": "mech_mfg",
        "name_ar": "ميكانيك — شعبة الإنتاج (إضافة PLO8)",
        "name_en": "MECH Manufacturing Track Supplement",
        "framework": "ABET+Track",
        "department_codes": ["MECH"],
        "track_groups": ["MFG"],
        "requires_base": "abet_v7",
        "outcomes": _mech_mfg_supplement(),
    },
    {
        "code": "mech_des",
        "name_ar": "ميكانيك — شعبة التصميم (إضافة PLO8)",
        "name_en": "MECH Design Track Supplement",
        "framework": "ABET+Track",
        "department_codes": ["MECH"],
        "track_groups": ["DES"],
        "requires_base": "abet_v7",
        "outcomes": _mech_des_supplement(),
    },
    {
        "code": "civil_abet",
        "name_ar": "مدني — ABET (7) + تخصص إنشاءات",
        "name_en": "Civil ABET + Infrastructure",
        "framework": "ABET",
        "department_codes": ["CIVIL"],
        "track_groups": [],
        "outcomes": _abet7() + _civil_supplement(),
    },
    {
        "code": "elec_abet",
        "name_ar": "كهربائي — ABET (7) + أنظمة كهربائية",
        "name_en": "Electrical ABET + Systems",
        "framework": "ABET",
        "department_codes": ["ELEC"],
        "track_groups": [],
        "outcomes": _abet7() + _elec_supplement(),
    },
    {
        "code": "renew_abet",
        "name_ar": "طاقات متجددة — ABET (7) + استدامة",
        "name_en": "Renewable ABET + Sustainability",
        "framework": "ABET",
        "department_codes": ["RENEW"],
        "track_groups": [],
        "outcomes": _abet7() + _renew_supplement(),
    },
    {
        "code": "general_foundation",
        "name_ar": "القسم العام — مخرجات تأسيسية (EAC)",
        "name_en": "General Year Foundation Outcomes",
        "framework": "EAC",
        "department_codes": ["GENERAL"],
        "track_groups": [],
        "outcomes": _general_foundation(),
    },
    {
        "code": "civil_str",
        "name_ar": "مدني — شعبة إنشائي (PLO8)",
        "name_en": "Civil Structures Track",
        "framework": "ABET+Track",
        "department_codes": ["CIVIL"],
        "track_groups": ["STR"],
        "requires_base": "abet_v7",
        "outcomes": _civil_str_supplement(),
    },
    {
        "code": "civil_geo",
        "name_ar": "مدني — شعبة جيوتقنية (PLO8)",
        "name_en": "Civil Geotechnical Track",
        "framework": "ABET+Track",
        "department_codes": ["CIVIL"],
        "track_groups": ["GEO"],
        "requires_base": "abet_v7",
        "outcomes": _civil_geo_supplement(),
    },
    {
        "code": "civil_wtr",
        "name_ar": "مدني — شعبة مياه/بيئة (PLO8)",
        "name_en": "Civil Water & Environment Track",
        "framework": "ABET+Track",
        "department_codes": ["CIVIL"],
        "track_groups": ["WTR"],
        "requires_base": "abet_v7",
        "outcomes": _civil_wtr_supplement(),
    },
    {
        "code": "elec_pwr_track",
        "name_ar": "كهربائي — شعبة قوى (PLO8)",
        "name_en": "Electrical Power Track",
        "framework": "ABET+Track",
        "department_codes": ["ELEC"],
        "track_groups": ["PWR"],
        "requires_base": "abet_v7",
        "outcomes": _elec_pwr_track_supplement(),
    },
    {
        "code": "elec_com",
        "name_ar": "كهربائي — شعبة اتصالات (PLO8)",
        "name_en": "Electrical Communications Track",
        "framework": "ABET+Track",
        "department_codes": ["ELEC"],
        "track_groups": ["COM"],
        "requires_base": "abet_v7",
        "outcomes": _elec_com_supplement(),
    },
    {
        "code": "elec_ctl",
        "name_ar": "كهربائي — شعبة تحكم (PLO8)",
        "name_en": "Electrical Control Track",
        "framework": "ABET+Track",
        "department_codes": ["ELEC"],
        "track_groups": ["CTL"],
        "requires_base": "abet_v7",
        "outcomes": _elec_ctl_supplement(),
    },
    {
        "code": "renew_sol",
        "name_ar": "طاقات متجددة — شعبة شمسية (PLO8)",
        "name_en": "Renewable Solar Track",
        "framework": "ABET+Track",
        "department_codes": ["RENEW"],
        "track_groups": ["SOL"],
        "requires_base": "abet_v7",
        "outcomes": _renew_sol_supplement(),
    },
    {
        "code": "renew_wnd",
        "name_ar": "طاقات متجددة — شعبة رياح (PLO8)",
        "name_en": "Renewable Wind Track",
        "framework": "ABET+Track",
        "department_codes": ["RENEW"],
        "track_groups": ["WND"],
        "requires_base": "abet_v7",
        "outcomes": _renew_wnd_supplement(),
    },
)

TEMPLATES_BY_CODE = {t["code"]: t for t in BENCHMARK_TEMPLATES}


def _program_context(cur, program_id: int) -> dict[str, Any] | None:
    row = cur.execute(
        """
        SELECT p.id, p.code AS program_code, COALESCE(p.track_group,'') AS track_group,
               UPPER(TRIM(d.code)) AS department_code
        FROM programs p
        JOIN departments d ON d.id = p.department_id
        WHERE p.id = ?
        """,
        (int(program_id),),
    ).fetchone()
    if not row:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    return {
        "id": row[0],
        "program_code": row[1],
        "track_group": row[2] or "",
        "department_code": row[3] or "",
    }


def templates_for_program(cur, program_id: int) -> list[dict[str, Any]]:
    ctx = _program_context(cur, program_id)
    if not ctx:
        return []
    dept = (ctx.get("department_code") or "").upper()
    tg = (ctx.get("track_group") or "").strip().upper()
    out: list[dict[str, Any]] = []
    for tpl in BENCHMARK_TEMPLATES:
        depts = [x.upper() for x in tpl.get("department_codes") or []]
        if dept not in depts:
            continue
        tgroups = [x.upper() for x in tpl.get("track_groups") or []]
        if tgroups and tg not in tgroups:
            continue
        item = {
            "code": tpl["code"],
            "name_ar": tpl["name_ar"],
            "name_en": tpl.get("name_en", ""),
            "framework": tpl.get("framework", ""),
            "outcome_count": len(tpl.get("outcomes") or []),
            "requires_base": tpl.get("requires_base"),
            "recommended": tpl["code"] == "mech_sos_2026"
            and dept == "MECH"
            and not tg,
        }
        if dept == "MECH" and tg == "PWR" and tpl["code"] == "mech_pwr":
            item["recommended"] = True
        if dept == "MECH" and tg == "MFG" and tpl["code"] == "mech_mfg":
            item["recommended"] = True
        if dept == "MECH" and tg == "DES" and tpl["code"] == "mech_des":
            item["recommended"] = True
        if dept == "CIVIL" and tpl["code"] == "civil_abet":
            item["recommended"] = True
        if dept == "ELEC" and tpl["code"] == "elec_abet":
            item["recommended"] = True
        if dept == "RENEW" and tpl["code"] == "renew_abet":
            item["recommended"] = True
        if dept == "GENERAL" and tpl["code"] == "general_foundation":
            item["recommended"] = True
        track_map = {
            ("CIVIL", "STR"): "civil_str",
            ("CIVIL", "GEO"): "civil_geo",
            ("CIVIL", "WTR"): "civil_wtr",
            ("ELEC", "PWR"): "elec_pwr_track",
            ("ELEC", "COM"): "elec_com",
            ("ELEC", "CTL"): "elec_ctl",
            ("RENEW", "SOL"): "renew_sol",
            ("RENEW", "WND"): "renew_wnd",
        }
        if track_map.get((dept, tg)) == tpl["code"]:
            item["recommended"] = True
        out.append(item)
    return out


def import_template(
    cur,
    program_id: int,
    template_code: str,
    *,
    merge: bool = True,
    actor: str = "",
) -> dict[str, Any]:
    tpl = TEMPLATES_BY_CODE.get((template_code or "").strip())
    if not tpl:
        return {"status": "error", "message": "قالب غير معروف"}
    requires = tpl.get("requires_base")
    if requires:
        cnt = cur.execute(
            """
            SELECT COUNT(*) FROM program_learning_outcomes
            WHERE program_id = ? AND code LIKE 'PLO%'
            """,
            (int(program_id),),
        ).fetchone()
        n = int(cnt[0] if not hasattr(cnt, "keys") else list(cnt.values())[0])
        if n < 7:
            return {
                "status": "error",
                "message": f"استورد القالب الأساسي ({requires}) أولاً قبل شعبة التخصص.",
            }
    inserted = 0
    skipped = 0
    for i, oc in enumerate(tpl.get("outcomes") or []):
        code = (oc.get("code") or "").strip()
        if not code:
            continue
        exists = cur.execute(
            "SELECT id FROM program_learning_outcomes WHERE program_id = ? AND code = ?",
            (int(program_id), code),
        ).fetchone()
        if exists:
            if not merge:
                skipped += 1
                continue
            skipped += 1
            continue
        cur.execute(
            """
            INSERT INTO program_learning_outcomes (
                program_id, code, title_ar, title_en, description,
                domain, bloom_level, performance_indicator, accreditation_tag,
                parent_glo_code, sort_order, governance_status, version, effective_from
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', 1, '')
            """,
            (
                int(program_id),
                code,
                oc.get("title_ar") or code,
                oc.get("title_en") or "",
                oc.get("description") or "",
                oc.get("domain") or "skills",
                oc.get("bloom_level") or "",
                oc.get("performance_indicator") or "",
                oc.get("accreditation_tag") or tpl.get("framework", ""),
                oc.get("parent_glo_code") or "",
                (i + 1) * 10,
            ),
        )
        inserted += 1
    return {
        "status": "ok",
        "inserted": inserted,
        "skipped": skipped,
        "template": template_code,
        "actor": actor,
    }
