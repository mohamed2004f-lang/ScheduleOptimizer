"""كتالوج مساعد الجودة الذكي — أدوار، نوايا، معرفة مرجعية، ملفات تخصصية."""

from __future__ import annotations

from typing import Any

# أوضاع المساعد (persona)
ASSISTANT_MODES: dict[str, dict[str, Any]] = {
    "instructor": {
        "code": "instructor",
        "title_ar": "مساعد الأستاذ",
        "subtitle_ar": "المقرر · CLO · الإغلاق · استبيان المقرر",
        "lens_ar": "تدريسي يومي",
        "session_roles": ("instructor",),
        "also_flags": (),
        "phase": 1,
    },
    "head_of_department": {
        "code": "head_of_department",
        "title_ar": "مساعد رئيس القسم",
        "subtitle_ar": "البرنامج · الأرشيف · PROG · استبيانات القسم",
        "lens_ar": "تشغيلي برامجي",
        "session_roles": ("head_of_department",),
        "also_flags": ("is_dept_quality_coordinator",),
        "phase": 1,
    },
    "academic_vice_dean": {
        "code": "academic_vice_dean",
        "title_ar": "مساعد وكيل الشؤون العلمية",
        "subtitle_ar": "متابعة فصلية عابرة للأقسام · اكتمال أكاديمي",
        "lens_ar": "تشغيل أكاديمي للكلية",
        "session_roles": ("academic_vice_dean", "admin_main", "system_admin"),
        "also_flags": (),
        "phase": 2,
    },
    "quality_committee": {
        "code": "quality_committee",
        "title_ar": "مساعد لجنة الجودة العلمية",
        "subtitle_ar": "مناقشة · مراجع عالمية · مسودة محضر · شواهد مقترحة",
        "lens_ar": "معياري ونقاشي",
        "session_roles": (
            "admin_main",
            "system_admin",
            "college_dean",
            "academic_vice_dean",
            "head_of_department",
        ),
        "also_flags": ("is_college_quality_lead", "is_dept_quality_coordinator"),
        "phase": 3,
    },
    "college_dean": {
        "code": "college_dean",
        "title_ar": "مساعد العميد",
        "subtitle_ar": "موجز تنفيذي · مخاطر · جاهزية تشغيلية",
        "lens_ar": "حوكمة الكلية",
        "session_roles": ("college_dean", "admin_main", "system_admin"),
        "also_flags": (),
        "phase": 4,
    },
}

# مواضيع مشتركة + حسب الوضع (كان يُسمّى سابقاً «نية» في الواجهة)
COMMON_INTENTS: list[dict[str, str]] = [
    {"code": "help", "label_ar": "ماذا يستطيع المساعد؟"},
    {"code": "system_help", "label_ar": "مساعدة استخدام المنظومة"},
    {"code": "discuss", "label_ar": "دردشة جودة (اكتب سؤالك)"},
    {"code": "global_tips", "label_ar": "مبادئ عالمية (رسالة/مخرجات/جودة)"},
    {"code": "proofread", "label_ar": "مدقق صياغة (رسالة/CLO)"},
    {"code": "proactive_alerts", "label_ar": "تنبيهات قبل إغلاق الفصل"},
    {"code": "archive_link_suggest", "label_ar": "اقتراح ربط أرشيف للفجوات"},
    {"code": "committee_summary", "label_ar": "ملخص لجنة للتصدير"},
]

# مواضيع مساعدة استخدام المنظومة (دليل تشغيلي مختصر + روابط)
SYSTEM_USAGE_TOPICS: list[dict[str, Any]] = [
    {
        "code": "assistant_chat",
        "label_ar": "الدردشة مع المساعد الذكي",
        "keywords": ("دردشة", "مساعد", "شات", "chat", "موضوع", "نية"),
        "steps_ar": [
            "اختر وضعك (أستاذ / رئيس قسم / …) ثم تبويب الدردشة.",
            "اكتب سؤالك أو اختر «موضوعاً سريعاً» من الأزرار.",
            "للجودة والصياغة استخدم تبويب «دردشة الجودة»؛ للاستخدام اليومي استخدم «مساعدة المنظومة».",
            "المساعد يقترح فقط ولا يعتمد امتثالاً تلقائياً.",
        ],
        "links": [
            {"href": "/academic_quality/assistant", "label_ar": "المساعد الذكي"},
            {"href": "/academic_quality/assistant/knowledge", "label_ar": "مكتبة المعرفة"},
        ],
    },
    {
        "code": "knowledge_library",
        "label_ar": "مكتبة معرفة المساعد",
        "keywords": ("مكتبة", "معرفة", "رفع وثيقة", "rag", "مرجع عالمي", "اعتماد وثيقة"),
        "steps_ar": [
            "افتح مكتبة المعرفة من المساعد أو القائمة.",
            "ارفع ملفاً/نصاً تملك الكلية حقه، ثم أرسل للاعتماد.",
            "بعد الاعتماد يسترجع المساعد مقاطعها في الدردشة.",
            "صدّر المعتمد ZIP للنسخ الاحتياطي.",
        ],
        "links": [
            {"href": "/academic_quality/assistant/knowledge", "label_ar": "مكتبة المعرفة"},
        ],
    },
    {
        "code": "quality_dashboard",
        "label_ar": "لوحة الجودة الأكاديمية",
        "keywords": ("لوحة الجودة", "مؤشر", "اعتماد", "dashboard", "تشغيلية"),
        "steps_ar": [
            "من قائمة الجودة افتح لوحة الجودة الأكاديمية.",
            "راجع المؤشرات التشغيلية والفجوات — ليست حكماً نهائياً بالامتثال.",
            "انتقل لخريطة الاعتماد أو الأرشيف حسب الفجوة الظاهرة.",
        ],
        "links": [
            {"href": "/academic_quality/dashboard", "label_ar": "لوحة الجودة"},
            {"href": "/academic_quality/accreditation/map?scope=inst", "label_ar": "خريطة الاعتماد المؤسسي"},
        ],
    },
    {
        "code": "accreditation_map",
        "label_ar": "خريطة الاعتماد والشواهد",
        "keywords": ("خريطة", "شاهد", "شواهد", "ربط", "inst", "prog", "امتثال"),
        "steps_ar": [
            "افتح خريطة الاعتماد واختر الكتالوج INST أو PROG.",
            "راجع حالة المؤشر واربط الشاهد يدوياً بعد التأكد البشري.",
            "الاستبيانات تساند ولا تُغلق المعيار وحدها.",
        ],
        "links": [
            {"href": "/academic_quality/accreditation/map?scope=inst", "label_ar": "اعتماد مؤسسي"},
            {"href": "/academic_quality/accreditation/map?scope=prog", "label_ar": "اعتماد برامجي"},
            {"href": "/academic_quality/glossary", "label_ar": "دليل المصطلحات"},
        ],
    },
    {
        "code": "department_archive",
        "label_ar": "أرشيف القسم",
        "keywords": ("أرشيف", "محضر", "قرار", "مراسلات", "ملاحظات قسم"),
        "steps_ar": [
            "افتح أرشيف القسم واختر الفصل والقسم.",
            "أضف محاضر/قرارات/مراسلات/ملاحظات حسب النوع.",
            "استخدم اقتراحات المساعد كنقاط مراجعة فقط.",
        ],
        "links": [
            {"href": "/academic_quality/archive", "label_ar": "أرشيف القسم"},
        ],
    },
    {
        "code": "surveys",
        "label_ar": "الاستبيانات ومنصة التقييم",
        "keywords": ("استبيان", "تقييم", "دعوة", "خريج", "رضا", "survey"),
        "steps_ar": [
            "إدارة القوالب والدورة من إدارة الاستبيانات.",
            "راجع النتائج والتحليل من مركز الاستبيانات أو صفحة النتائج.",
            "للاعتماد: اربط الشاهد يدوياً بعد مراجعة اللجنة.",
        ],
        "links": [
            {"href": "/academic_quality/survey_admin", "label_ar": "إدارة الاستبيانات"},
            {"href": "/academic_quality/surveys", "label_ar": "مركز الاستبيانات"},
        ],
    },
    {
        "code": "course_quality_reports",
        "label_ar": "تقارير جودة المقررات (تنفيذ المفردات)",
        "keywords": (
            "تقرير مقرر",
            "مفردات",
            "نسب إنجاز",
            "تنفيذ المقرر",
            "طباعة تقرير",
            "معاينة تقرير",
            "course report",
            "syllabus",
        ),
        "steps_ar": [
            "الأستاذ يعبّئ التقرير من مقرراتي أو تعبئة الاستبيانات (نسب، فجوات أقل من 50٪، خارج المقرر، مراجع، تقويم).",
            "للمعاينة/الطباعة: افتح «تقارير جودة المقررات» ثم معاينة المقرر أو PDF.",
            "للحزمة الإجمالية (قسم/كلية): استخدم «معاينة الحزمة» أو PDF إجمالي.",
            "للاعتماد: المساعد يقترح الشاهد course_delivery_quality_report — الربط النهائي يدوي في خريطة الاعتماد.",
        ],
        "links": [
            {"href": "/academic_quality/course_reports", "label_ar": "فهرس تقارير المقررات"},
            {"href": "/academic_quality/course_reports/package", "label_ar": "حزمة التقارير (معاينة)"},
            {"href": "/course_delivery_page", "label_ar": "تعبئة تقرير مقرر"},
            {"href": "/academic_quality/accreditation/map?scope=prog", "label_ar": "خريطة الاعتماد البرامجي"},
        ],
    },
    {
        "code": "outcomes_clo",
        "label_ar": "مخرجات التعلم وإغلاق المقرر",
        "keywords": ("clo", "plo", "glo", "مخرجات", "إغلاق", "تقرير إقفال", "مصفوفة"),
        "steps_ar": [
            "الأستاذ يقيّم CLO من مقرراتي ويربطها بـ PLO.",
            "أكمل تقرير إغلاق المقرر عند نهاية الفصل.",
            "رئيس القسم يراجع الاعتماد من لوحة مخرجات القسم.",
        ],
        "links": [
            {"href": "/my_courses", "label_ar": "مقرراتي"},
            {"href": "/academic_quality/ilo/department/dashboard", "label_ar": "لوحة مخرجات القسم"},
        ],
    },
    {
        "code": "grades",
        "label_ar": "مسودات الدرجات والنشر",
        "keywords": ("درجات", "مسودة", "نشر", "كنترول", "نتائج"),
        "steps_ar": [
            "أدخل المسودات من صفحة مسودات الدرجات للمقرر.",
            "اتبع مسار المراجعة (أستاذ → قسم → كنترول/عمادة حسب صلاحياتكم).",
            "لا تُعتبر الدرجات نهائية قبل الاعتماد/النشر الرسمي.",
        ],
        "links": [
            {"href": "/grade_drafts", "label_ar": "مسودات الدرجات"},
        ],
    },
    {
        "code": "glossary",
        "label_ar": "دليل المصطلحات",
        "keywords": ("مصطلح", "glossary", "qaa", "glo", "plo", "تعريف"),
        "steps_ar": [
            "افتح دليل المصطلحات لفهم اختصارات الجودة والاعتماد.",
            "ارجع للمساعد إذا أردت صياغة عملية بعد فهم التعريف.",
        ],
        "links": [
            {"href": "/academic_quality/glossary", "label_ar": "دليل المصطلحات"},
        ],
    },
    {
        "code": "college_profile",
        "label_ar": "ملف الكلية والهرم الاستراتيجي",
        "keywords": ("هرم", "رسالة", "رؤية", "ملف الكلية", "أهداف", "profile"),
        "steps_ar": [
            "حدّث رسالة/رؤية/أهداف الكلية من ملف الكلية.",
            "اربط أهداف البرامج (PG) بمخرجات البرامج (PLO) حسب هيكلتهكم.",
            "استخدم المساعد لمناقشة الصياغة ثم اعتمد التغيير بشرياً.",
        ],
        "links": [
            {"href": "/academic_quality/college", "label_ar": "هوية الكلية"},
            {"href": "/academic_quality/assistant", "label_ar": "مناقشة الصياغة"},
        ],
    },
]


def match_system_usage_topic(query: str = "") -> dict[str, Any] | None:
    """مطابقة سؤال المستخدم بموضوع مساعدة استخدام المنظومة."""
    q = (query or "").strip().lower()
    if not q:
        return None
    best: dict[str, Any] | None = None
    best_score = 0
    for topic in SYSTEM_USAGE_TOPICS:
        score = 0
        for kw in topic.get("keywords") or ():
            k = str(kw).lower()
            if k and k in q:
                score += 2 if len(k) > 3 else 1
        label = (topic.get("label_ar") or "").lower()
        if label and any(p in q for p in label.split() if len(p) > 2):
            score += 1
        if score > best_score:
            best_score = score
            best = topic
    return best if best_score > 0 else None


def list_system_usage_topics() -> list[dict[str, Any]]:
    return [
        {
            "code": t["code"],
            "label_ar": t["label_ar"],
            "links": list(t.get("links") or []),
        }
        for t in SYSTEM_USAGE_TOPICS
    ]

# كيف يناقش كل دور المساعد (نص إرشادي للواجهة)
ROLE_DISCUSSION_GUIDE: dict[str, dict[str, Any]] = {
    "instructor": {
        "how_ar": [
            "اكتب سؤالك في الدردشة ثم اضغط إرسال، أو اختر موضوعاً سريعاً.",
            "اسأل عن صياغة CLO، ربطها بـ PLO، أو تفسير بند استبيان ضعيف.",
            "إن احتجت تصعيداً: استخدم موضوع «مسودة رفع لرئيس القسم».",
        ],
        "example_prompts_ar": [
            "كيف أصوغ CLO لقياس مهارة التصميم في مقرري؟",
            "بند «وضوح التقييم» ضعيف — ماذا أقترح لتحسينه؟",
        ],
    },
    "head_of_department": {
        "how_ar": [
            "اختر قسمك ثم ناقش فجوات PROG أو صياغة رسالة البرنامج.",
            "حمّل حزمة مراجع قسمك واستخدمها أثناء النقاش مع اللجنة.",
            "اطلب موجزاً للجلسة أو صفّد لوكيل الشؤون / اللجنة.",
        ],
        "example_prompts_ar": [
            "هل رسالة برنامج الميكانيكا واضحة بما يكفي للمقارنة مع ABET؟",
            "ما أهم 3 نواقص أرشيف يجب معالجتها قبل إغلاق الفصل؟",
        ],
    },
    "academic_vice_dean": {
        "how_ar": [
            "اسأل عن المتابعة عبر الأقسام: إغلاق، استبيانات، تنبيهات أرشيف.",
            "اطلب موجزاً تنفيذياً للعميد أو بنوداً لأجندة اللجنة.",
        ],
        "example_prompts_ar": [
            "أي أقسام تحتاج تدخل تشغيلي هذا الفصل؟",
            "صِغ فقرة موجزة للعميد عن مخاطر الجودة الحالية.",
        ],
    },
    "quality_committee": {
        "how_ar": [
            "استخدم المناقشة لطرح أسئلة معيارية (رسالة، مخرجات، شواهد).",
            "اربط النقاش بحزمة المراجع العالمية للقسم المختار.",
            "اطلب مسودة محضر أو خطة تحسين بعد الاتفاق البشري.",
        ],
        "example_prompts_ar": [
            "ناقش نقاط القوة والضعف في مخرجات التصميم للقسم المدني.",
            "ما الأسئلة التي نطرحها على رئيس القسم قبل اعتماد التوصية؟",
        ],
    },
    "college_dean": {
        "how_ar": [
            "اطلب موجزاً تنفيذياً ومخاطر دون الغرق في تفاصيل CLO.",
            "اسأل: ماذا أطلب من اللجنة قبل اتخاذ قرار موارد؟",
        ],
        "example_prompts_ar": [
            "لخّص جاهزية الكلية التشغيلية هذا الفصل في 5 نقاط.",
            "ما البنود التي تستحق قرار عمادة الآن؟",
        ],
    },
}

MODE_INTENTS: dict[str, list[dict[str, str]]] = {
    "instructor": [
        {"code": "clo_tips", "label_ar": "اقتراح صياغة CLO"},
        {"code": "closure_checklist", "label_ar": "قائمة إغلاق المقرر"},
        {"code": "survey_explain", "label_ar": "تفسير نتائج استبيان المقرر"},
        {"code": "course_report_mine", "label_ar": "معاينة تقرير مقرري (جودة)"},
        {"code": "escalate_hod", "label_ar": "مسودة رفع لرئيس القسم"},
    ],
    "head_of_department": [
        {"code": "dept_snapshot", "label_ar": "موجز القسم لهذا الفصل"},
        {"code": "archive_gaps", "label_ar": "نواقص أرشيف القسم"},
        {"code": "archive_link_suggest", "label_ar": "اقتراح ربط أرشيف للفجوات"},
        {"code": "prog_gaps", "label_ar": "فجوات الامتثال البرامجي"},
        {"code": "survey_weak", "label_ar": "ضعاف استبيانات القسم"},
        {"code": "course_report_gaps", "label_ar": "فجوات تقارير المقررات"},
        {"code": "brief_for_committee", "label_ar": "موجز لجلسة لجنة الجودة"},
        {"code": "committee_summary", "label_ar": "ملخص لجنة للتصدير"},
        {"code": "proactive_alerts", "label_ar": "تنبيهات قبل إغلاق الفصل"},
        {"code": "specialty_pack", "label_ar": "مراجع عالمية للقسم"},
        {"code": "escalate_vice", "label_ar": "مسودة رفع لوكيل الشؤون العلمية"},
        {"code": "escalate_committee", "label_ar": "مسودة إدراج لأجندة اللجنة"},
    ],
    "academic_vice_dean": [
        {"code": "college_ops", "label_ar": "متابعة تشغيلية عبر الأقسام"},
        {"code": "closure_coverage", "label_ar": "اكتمال تقومات/إغلاقات (ملخص)"},
        {"code": "survey_coverage", "label_ar": "تغطية الاستبيانات الكلية"},
        {"code": "course_report_coverage", "label_ar": "تغطية تقارير المقررات (الكلية)"},
        {"code": "escalate_committee", "label_ar": "بنود لمتابعة اللجنة"},
        {"code": "escalate_dean", "label_ar": "موجز تنفيذي للعميد"},
    ],
    "quality_committee": [
        {"code": "session_agenda", "label_ar": "أجندة جلسة مقترحة"},
        {"code": "discuss_mission", "label_ar": "مناقشة رسالة/رؤية/أهداف"},
        {"code": "discuss_outcomes", "label_ar": "مناقشة مخرجات التعلم (OBE)"},
        {"code": "evidence_gaps", "label_ar": "فجوات شواهد INST/PROG"},
        {"code": "minutes_draft", "label_ar": "مسودة محضر لجنة"},
        {"code": "improvement_draft", "label_ar": "مسودة خطة تحسين"},
        {"code": "committee_summary", "label_ar": "ملخص لجنة للتصدير"},
        {"code": "archive_link_suggest", "label_ar": "اقتراح ربط أرشيف"},
        {"code": "specialty_pack", "label_ar": "مرجع تخصصي للقسم"},
        {"code": "usage_insights", "label_ar": "أكثر المواضيع استخداماً"},
    ],
    "college_dean": [
        {"code": "exec_brief", "label_ar": "موجز تنفيذي للكلية"},
        {"code": "risk_flags", "label_ar": "أبرز المخاطر التشغيلية"},
        {"code": "inst_progress", "label_ar": "تقدم الامتثال المؤسسي"},
        {"code": "course_report_coverage", "label_ar": "تغطية تقارير المقررات (الكلية)"},
        {"code": "ask_committee", "label_ar": "أسئلة للجنة قبل القرار"},
        {"code": "proactive_alerts", "label_ar": "تنبيهات قبل إغلاق الفصل"},
        {"code": "usage_insights", "label_ar": "أكثر المواضيع استخداماً"},
    ],
}

# بطاقات مراجع عالمية معتمدة في المنظومة (روابط رسمية + ملخص نقاش داخلي — ليست نصوص معايير محمية)
APPROVED_GLOBAL_REFERENCES: list[dict[str, Any]] = [
    {
        "code": "qaa_ly",
        "label_ar": "المركز الوطني لضمان جودة واعتماد المؤسسات التعليمية (ليبيا)",
        "label_en": "Libyan QAA (qaa.ly)",
        "official_url": "https://qaa.ly/",
        "scope_ar": "معايير الاعتماد المؤسسي والبرامجي المحلية الملزمة",
        "packs": ("*", "MECH", "CIVIL", "ELEC", "RENEW", "GENERAL"),
        "use_for_ar": [
            "الامتثال اليومي INST/PROG",
            "ربط الشواهد يدوياً بالمؤشرات",
            "مرجع أي خلاف مع أطر عالمية",
        ],
        "discussion_summary_ar": (
            "المرجع الملزم عندكم هو كتالوج المنظومة QAA-2023.4-INST و QAA-2023.4-PROG-UG. "
            "أي مرجع عالمي يُستخدم للصياغة والمناقشة فقط، ثم يُعاد ربط النتيجة بمؤشر محلي وشاهد بشري."
        ),
        "not_a_substitute_ar": "هذا هو المرجع الملزم — لا يُستبدل بمراجع خارجية.",
    },
    {
        "code": "abet_eac",
        "label_ar": "ABET — اعتماد البرامج الهندسية (EAC)",
        "label_en": "ABET Engineering Accreditation Criteria",
        "official_url": "https://www.abet.org/accreditation/accreditation-criteria/",
        "scope_ar": "مخرجات الطالب، التصميم، التجريب، الأخلاقيات، فرق العمل، التعلم المستمر",
        "packs": ("*", "MECH", "CIVIL", "ELEC", "RENEW", "GENERAL", "engineering"),
        "use_for_ar": [
            "صياغة/مراجعة PLO هندسية",
            "مناقشة تغطية التصميم والتجريب",
            "أسئلة لجنة حول مستوى Mastery",
        ],
        "discussion_summary_ar": (
            "ABET مفيد كعدسة لمخرجات الطالب الهندسي (معرفة، تطبيق، تصميم، تجارب، فريق، تواصل، أخلاق، تعلم مستمر). "
            "استخدمه لمقارنة تغطية برنامجكم ثم طابقوا الفجوات مع مؤشرات PROG المحلية وليس كقائمة امتثال بحد ذاتها."
        ),
        "not_a_substitute_ar": "ليس بديلاً عن QAA المحلي ولا يُعتبر اعتماداً تلقائياً في المنظومة.",
    },
    {
        "code": "washington_accord",
        "label_ar": "اتفاق واشنطن / خصائص خرّيج IEA",
        "label_en": "Washington Accord / IEA Graduate Attributes",
        "official_url": "https://www.ieagreements.org/",
        "scope_ar": "خصائص خرّيج هندسي معترف بها دولياً ومستويات الكفاءة",
        "packs": ("*", "MECH", "CIVIL", "ELEC", "RENEW", "engineering"),
        "use_for_ar": [
            "نقاش مستوى الخرّيج مقابل الممارسة المهنية",
            "مقارنة أهداف البرنامج بخصائص دولية",
        ],
        "discussion_summary_ar": (
            "خصائص الخرّيج (Graduate Attributes) تساعد اللجنة على سؤال: هل خرّيج البرنامج يملك المعرفة والمهارة "
            "والمسؤولية المهنية المتوقعة دولياً؟ الصيغة النهائية تبقى وفق لوائح الكلية وQAA."
        ),
        "not_a_substitute_ar": "عضوية الاتفاق أو معادلتها قرار خارجي — لا تُستنتج من المسح الداخلي.",
    },
    {
        "code": "eur_ace",
        "label_ar": "EUR-ACE — إطار اعتماد هندسي أوروبي",
        "label_en": "EUR-ACE Framework",
        "official_url": "https://www.enaee.eu/eur-ace-system/",
        "scope_ar": "نتائج تعلم برامج هندسية على مستوى البكالوريوس/الماجستير في السياق الأوروبي",
        "packs": ("*", "MECH", "CIVIL", "ELEC", "RENEW", "engineering"),
        "use_for_ar": [
            "مقارنة مخرجات البرنامج بصياغات أوروبية شائعة",
            "نقاش المعرفة/المهارات/الكفاءة",
        ],
        "discussion_summary_ar": (
            "EUR-ACE يوفّر لغة مشتركة لمخرجات الهندسة (معرفة، مهارات هندسية، مهارات عرضية). "
            "مفيد عند صياغة PLO أو تقارير اللجنة؛ القرار المحلي يبقى عند مؤشر PROG الليبي."
        ),
        "not_a_substitute_ar": "ليست شهادة اعتماد لبرامجكم ما لم تُمنح من جهة معتمدة رسمياً.",
    },
    {
        "code": "cdio",
        "label_ar": "CDIO — تصور·تصميم·تنفيذ·تشغيل",
        "label_en": "CDIO Initiative",
        "official_url": "http://www.cdio.org/",
        "scope_ar": "ربط المنهج بالمشاريع ومسار المنتج الهندسي الكامل",
        "packs": ("*", "MECH", "CIVIL", "ELEC", "RENEW", "GENERAL", "engineering"),
        "use_for_ar": [
            "تصميم مسار مشاريع عبر السنوات",
            "ربط CLO بمراحل Conceive–Design–Implement–Operate",
        ],
        "discussion_summary_ar": (
            "CDIO يقترح بناء المنهج حول دورة المنتج: تصوّر الحاجة، التصميم، التنفيذ، التشغيل. "
            "استخدمه لفحص هل المشاريع والمعامل تغطي الدورة كاملة أم تبقى نظرية فقط."
        ),
        "not_a_substitute_ar": "إطار تعليمي للنقاش — ليس مؤشر اعتماد QAA.",
    },
    {
        "code": "asce_bok",
        "label_ar": "ASCE — جسم معرفة المهندس المدني",
        "label_en": "ASCE Body of Knowledge",
        "official_url": "https://www.asce.org/",
        "scope_ar": "معرفة ومهارات المهندس المدني عبر المسار الأكاديمي والمهني",
        "packs": ("CIVIL",),
        "use_for_ar": [
            "صياغة رسالة/أهداف مدنية",
            "مراجعة تغطية السلامة والإنشاء والاستدامة",
        ],
        "discussion_summary_ar": (
            "ASCE BOK يساعد قسم المدني على تسمية مجالات المعرفة (تحليل، مواد، إدارة مشاريع، أخلاق، استدامة) "
            "ومستويات الإتقان. طابقوا النقاش مع خطة البرنامج المحلية وشواهد الميدان."
        ),
        "not_a_substitute_ar": "مرجع مهني للنقاش وليس معيار اعتماد برامجي ليبي.",
    },
    {
        "code": "ieee_ethics",
        "label_ar": "IEEE — أخلاقيات المهنة (مفهوم)",
        "label_en": "IEEE Code of Ethics",
        "official_url": "https://www.ieee.org/about/corporate/governance/p7-8.html",
        "scope_ar": "أخلاقيات السلامة والمسؤولية في الأنظمة الكهربائية والإلكترونية",
        "packs": ("ELEC",),
        "use_for_ar": [
            "صياغة CLO/PLO للأخلاقيات والسلامة",
            "أسئلة لجنة حول سلامة المعامل",
        ],
        "discussion_summary_ar": (
            "ميثاق IEEE يدعم نقاش المسؤولية المهنية، السلامة العامة، والصدق في التقارير الفنية. "
            "اربطوه بإجراءات سلامة معامل الكهرباء ومحاضر التدريب الداخلي."
        ),
        "not_a_substitute_ar": "مفهوم للنقاش — ليس استبدالاً لسياسات السلامة المحلية.",
    },
    {
        "code": "asme_imeche",
        "label_ar": "ASME / IMechE — ممارسة ميكانيكية مهنية",
        "label_en": "ASME / IMechE professional practice",
        "official_url": "https://www.asme.org/",
        "scope_ar": "سلامة وأنظمة ميكانيكية وأخلاقيات المهنة",
        "packs": ("MECH",),
        "use_for_ar": [
            "نقاش سلامة الورش والمختبرات",
            "صياغة مخرجات مرتبطة بالتصميم الميكانيكي",
        ],
        "discussion_summary_ar": (
            "الجمعيات المهنية الميكانيكية توفر لغة حول السلامة، المعايير الصناعية، والمسؤولية المهنية. "
            "استخدمها لأسئلة اللجنة ثم وثّقوا إجراءات الورش محلياً كشواهد محتملة."
        ),
        "not_a_substitute_ar": "ليست شهادة اعتماد لبرنامجكم.",
    },
    {
        "code": "irena",
        "label_ar": "IRENA — معرفة انتقال الطاقة المتجددة",
        "label_en": "IRENA knowledge hub",
        "official_url": "https://www.irena.org/",
        "scope_ar": "سياق تقني وسياسات الطاقة المتجددة عالمياً",
        "packs": ("RENEW",),
        "use_for_ar": [
            "إثراء رسالة البرنامج ورؤية الاستدامة",
            "سياق مشاريع التخرج في الطاقة",
        ],
        "discussion_summary_ar": (
            "IRENA مصدر لسياق انتقال الطاقة والتقنيات (شمس، رياح، كفاءة). مفيد لصياغة الرؤية "
            "وربط الخدمة المجتمعية؛ الامتثال يبقى عبر مؤشرات QAA."
        ),
        "not_a_substitute_ar": "معرفة سياق — ليس معيار اعتماد برامجي.",
    },
    {
        "code": "iso_21001",
        "label_ar": "ISO 21001 — أنظمة إدارة المنظمات التعليمية (مفاهيم)",
        "label_en": "ISO 21001 Educational organizations management",
        "official_url": "https://www.iso.org/standard/66266.html",
        "scope_ar": "مفاهيم إدارة جودة التعليم المتمحورة حول المتعلم",
        "packs": ("*", "GENERAL", "business"),
        "use_for_ar": [
            "نقاش سياسات تحسين الخدمة التعليمية",
            "مقارنة PDCA الداخلي",
        ],
        "discussion_summary_ar": (
            "ISO 21001 يوفّر مفاهيم لإدارة منظمة تعليمية (احتياجات المتعلمين، التحسين المستمر، الشفافية). "
            "استخدمه لأسئلة تشغيلية، دون الخلط بين شهادة ISO واعتماد QAA البرامجي."
        ),
        "not_a_substitute_ar": "شهادة/مفهوم إداري منفصل عن اعتماد المركز الوطني.",
    },
    {
        "code": "esg_ehea",
        "label_ar": "ESG / منطقة التعليم العالي الأوروبية (مفاهيم)",
        "label_en": "ESG / EHEA quality concepts",
        "official_url": "https://www.ehea.info/",
        "scope_ar": "ضمان جودة داخلي وخارجي وتتابع المستويات في السياق الأوروبي",
        "packs": ("*", "GENERAL"),
        "use_for_ar": [
            "نقاش ضمان الجودة الداخلي",
            "تتابع المستوى التأسيسي→التخصصي",
        ],
        "discussion_summary_ar": (
            "معايير ESG تلهم نقاش دور الوحدة الداخلية للجودة واستقلالية التقييم الخارجي. "
            "المرحلة العامة تستفيد من فكرة التتابع الواضح قبل التخصص."
        ),
        "not_a_substitute_ar": "مفاهيم للنقاش — التنظيم المحلي ولوائح الكلية هما المرجع التشغيلي.",
    },
    {
        "code": "iso_50001",
        "label_ar": "ISO 50001 — إدارة الطاقة (مفهوم)",
        "label_en": "ISO 50001 Energy management",
        "official_url": "https://www.iso.org/iso-50001-energy-management.html",
        "scope_ar": "مفاهيم كفاءة الطاقة والتحسين المستمر لاستهلاك الطاقة",
        "packs": ("RENEW", "MECH"),
        "use_for_ar": [
            "صياغة مخرجات كفاءة الطاقة",
            "ربط مشاريع قياس الاستهلاك",
        ],
        "discussion_summary_ar": (
            "ISO 50001 يقدّم دورة تخطيط–تشغيل–مراجعة لكفاءة الطاقة. مفيد لمشاريع التخرج والمعامل "
            "في الطاقات المتجددة/الميكانيكا — دون اعتباره معيار اعتماد برامجي."
        ),
        "not_a_substitute_ar": "مفهوم إداري تقني — ليس مؤشر PROG.",
    },
]


def approved_global_refs_for_pack(pack_code: str | None = None) -> list[dict[str, Any]]:
    """مراجع معتمدة للكلية (*) أو لحزمة قسم محددة."""
    code = (pack_code or "*").strip().upper()
    if code == "GENERAL":
        code = "GENERAL"
    out = []
    for ref in APPROVED_GLOBAL_REFERENCES:
        packs = {str(p).upper() for p in (ref.get("packs") or ())}
        if "*" in packs or code == "*" or code in packs:
            out.append(ref)
    return out


def approved_global_ref_to_markdown(ref: dict[str, Any]) -> str:
    lines = [
        f"# مرجع عالمي معتمد — {ref.get('label_ar')}",
        "",
        f"> {_REF_DISCLAIMER_AR}",
        "",
        f"**الرمز الداخلي:** `{ref.get('code')}`",
        f"**English:** {ref.get('label_en') or '—'}",
        f"**الرابط الرسمي:** {ref.get('official_url') or '—'}",
        f"**النطاق:** {ref.get('scope_ar') or '—'}",
        "",
        "## ملخص للنقاش (صياغة داخلية)",
        ref.get("discussion_summary_ar") or "",
        "",
        "## استخدام مقترح في المساعد",
    ]
    for u in ref.get("use_for_ar") or []:
        lines.append(f"- {u}")
    lines.extend(
        [
            "",
            "## تنبيه",
            ref.get("not_a_substitute_ar") or _REF_DISCLAIMER_AR,
            "",
            f"الحزم المرتبطة: {', '.join(str(p) for p in (ref.get('packs') or ()))}",
            "",
        ]
    )
    return "\n".join(lines)


def knowledge_doc_title_for_global_ref(ref: dict[str, Any]) -> str:
    return f"مرجع عالمي معتمد — {ref.get('label_ar')}"


# معرفة عالمية معتمدة (مختصرة — للنصوص والاقتراح؛ ليست بديلاً عن QAA المحلي)
GLOBAL_REFERENCE_TIPS: list[dict[str, str]] = [
    {
        "topic_ar": "الرسالة والرؤية",
        "tip_ar": (
            "الرسالة تصف الغرض والجمهور والنتيجة الآن؛ الرؤية طموح زمني واضح. "
            "تجنّب العبارات الفضفاضة بدون مؤشرات يمكن التحقق منها."
        ),
        "source_tag": "مرجع عالمي",
    },
    {
        "topic_ar": "الأهداف الاستراتيجية",
        "tip_ar": (
            "الأهداف (IG/PG) تُصاغ قابلة للقياس والربط بمؤشرات أداء. كل هدف برنامج يفضّل "
            "ربطه بهدف كلية واحد على الأقل."
        ),
        "source_tag": "مرجع عالمي",
    },
    {
        "topic_ar": "مخرجات التعلم (OBE)",
        "tip_ar": (
            "هرم سليم: رسالة → أهداف → GLO/PLO → CLO → قياس. المخرج يبدأ بفعل قابل للملاحظة "
            "(يصمم، يحلّل، يطبّق) ويُغطى بمقرر ومستوى I/R/M واضح."
        ),
        "source_tag": "مرجع عالمي",
    },
    {
        "topic_ar": "دورة الجودة PDCA",
        "tip_ar": (
            "خطط (فجوات) → نفّذ (تحسين + شواهد) → افحص (خريطة/استبيانات) → عدّل. "
            "الاستبيان وحده لا يُغلق المعيار دون مراجعة بشرية."
        ),
        "source_tag": "مرجع عالمي",
    },
    {
        "topic_ar": "الاعتماد المحلي أولاً",
        "tip_ar": (
            "المرجع الملزم عندكم هو المركز الوطني لضمان الجودة (qaa.ly) — كتالوج "
            "QAA-2023.4-INST و PROG-UG. المراجع العالمية للمساعدة في الصياغة والمناقشة فقط."
        ),
        "source_tag": "منظومة + مركز",
    },
]

# تنبيه ثابت: المرجع الملزم محلي؛ العالمي للصياغة والمناقشة فقط
_REF_DISCLAIMER_AR = (
    "هذه المراجع عالمية للمناقشة وتحسين الصياغة فقط. المرجع الملزم للاعتماد عندكم هو "
    "المركز الوطني لضمان الجودة (qaa.ly) — QAA-2023.4-INST / PROG-UG — مع تأكيد بشري للشواهد."
)

_COMMON_ENG_FRAMEWORKS = [
    {
        "name": "ABET EAC (Engineering)",
        "role_ar": "مخرجات طالب وهندسة التصميم والأخلاق والفرق والتجريب",
        "note_ar": "مفيد لمواءمة PLO مع معايير هندسية شائعة؛ لا يُستبدل به QAA الليبي.",
    },
    {
        "name": "Washington Accord / IEA Graduate Attributes",
        "role_ar": "خصائص خرّيج هندسي معترف بها دولياً",
        "note_ar": "مرجع لمناقشة مستوى الخرّيج والكفاءة المهنية.",
    },
    {
        "name": "EUR-ACE",
        "role_ar": "إطار اعتماد هندسي أوروبي لنتائج التعلم",
        "note_ar": "للمقارنة والصياغة؛ الامتثال يبقى عبر PROG المحلي.",
    },
    {
        "name": "CDIO",
        "role_ar": "Conceive–Design–Implement–Operate",
        "note_ar": "يدعم ربط المناهج بالمشاريع والتصميم عبر المراحل.",
    },
]

# حزم مراجع حسب رمز القسم في المنظومة (+ فئات احتياطية)
SPECIALTY_PACKS: dict[str, dict[str, Any]] = {
    "MECH": {
        "title_ar": "الهندسة الميكانيكية",
        "title_en": "Mechanical Engineering",
        "department_codes": ("MECH",),
        "keywords": ("ميكان", "mechanical", "MECH"),
        "frameworks": _COMMON_ENG_FRAMEWORKS
        + [
            {
                "name": "ASME / IMechE (مهني)",
                "role_ar": "ممارسات مهنية وسلامة وأنظمة ميكانيكية",
                "note_ar": "لأسئلة اللجنة حول الأخلاقيات والسلامة الصناعية.",
            },
        ],
        "mission_vision_tips_ar": [
            "اربط رسالة البرنامج بالطاقة، التصميم الميكانيكي، التصنيع أو الأنظمة الحرارية بوضوح الجمهور (صناعة محلية/إقليمية).",
            "تجنّب رسالة عامة لكل الهندسة بدون تخصّص ميكانيكي ظاهر.",
        ],
        "outcomes_tips_ar": [
            "غطِّ تصميم أنظمة ميكانيكية وتحليل الإجهاد/السوائل/الحرارة ضمن PLO قابلة للقياس.",
            "اجعل مشروع التخرج أو معمل التصميم مستوى M لمخرج التصميم.",
            "وثّق سلامة الورش والمختبرات كشواهد محتملة لمؤشرات QAA ذات الصلة.",
        ],
        "review_questions_ar": [
            "هل توجد PLO للتصميم الميكانيكي والتجريب والقياس؟",
            "هل شعب الطاقة/التصنيع/التصميم (إن وجدت) واضحة في المصفوفة؟",
            "هل محاضر لجنة المشاريع وأمن الورش مؤرشفة لهذا الفصل؟",
        ],
        "evidence_hints_ar": [
            "تقارير مشاريع، عينات من تقارير معامل، محاضر سلامة، استبيان مقرر التصميم.",
            "تقرير مقرر دراسي (تنفيذ المفردات) PDF من /academic_quality/course_reports — شاهد مقترح يُربط يدوياً.",
        ],
        "global_refs": [
            {
                "label_ar": "ABET — Engineering Accreditation",
                "cite": "https://www.abet.org/accreditation/accreditation-criteria/",
                "use_ar": "مراجعة صياغة مخرجات الطالب الهندسية.",
            },
            {
                "label_ar": "IEA Graduate Attributes / Washington Accord",
                "cite": "https://www.ieagreements.org/",
                "use_ar": "مناقشة خصائص الخرّيج الهندسي.",
            },
            {
                "label_ar": "EUR-ACE Framework",
                "cite": "https://www.enaee.eu/eur-ace-system/",
                "use_ar": "مقارنة مخرجات هندسية بالصياغات الأوروبية.",
            },
            {
                "label_ar": "CDIO Syllabus",
                "cite": "http://www.cdio.org/",
                "use_ar": "ربط مراحل التصميم والتنفيذ بالمقررات.",
            },
            {
                "label_ar": "ASME (ممارسة مهنية)",
                "cite": "https://www.asme.org/",
                "use_ar": "سلامة وأنظمة ميكانيكية للنقاش.",
            },
        ],
        "tips_ar": [
            "استخدم قوالب PLO الميكانيكية من كتالوج المخرجات (ABET/وثيقة القسم) كنقطة انطلاق ثم راجعها محلياً.",
        ],
    },
    "CIVIL": {
        "title_ar": "الهندسة المدنية",
        "title_en": "Civil Engineering",
        "department_codes": ("CIVIL",),
        "keywords": ("مدني", "civil", "CIVIL", "إنشاء"),
        "frameworks": _COMMON_ENG_FRAMEWORKS
        + [
            {
                "name": "ASCE Body of Knowledge",
                "role_ar": "معرفة ومهارات المهندس المدني عبر المسار المهني",
                "note_ar": "مكمّل لصياغة أهداف البرنامج والمستويات.",
            },
        ],
        "mission_vision_tips_ar": [
            "أكّد البنية التحتية، السلامة الإنشائية، والاستدامة في الرسالة إن كانت جزءاً من هوية البرنامج.",
        ],
        "outcomes_tips_ar": [
            "اربط PLO بالتحليل الإنشائي، مواد البناء، المساحة/الجيوماتكس، وإدارة المشاريع حسب الخطة.",
            "اجعل التدريب الميداني أو مشروع التخرج شاهداً محتملاً بعد التوثيق اليدوي.",
        ],
        "review_questions_ar": [
            "هل السلامة الإنشائية والاستدامة ظاهرة في المخرجات؟",
            "هل الميدان/الزيارات موثّقة في الأرشيف؟",
            "هل استبيانات جهات العمل أو التدريب مفعّلة؟",
        ],
        "evidence_hints_ar": [
            "تقارير تربة/إنشاء طلابية (نماذج)، محاضر تدريب، تقييم مشرف ميداني.",
        ],
        "global_refs": [
            {
                "label_ar": "ABET EAC Criteria",
                "cite": "https://www.abet.org/accreditation/accreditation-criteria/",
                "use_ar": "مخرجات هندسية عامة + تصميم.",
            },
            {
                "label_ar": "EUR-ACE Framework",
                "cite": "https://www.enaee.eu/eur-ace-system/",
                "use_ar": "مقارنة مخرجات برامجية أوروبية.",
            },
            {
                "label_ar": "ASCE — Civil Engineering Body of Knowledge",
                "cite": "https://www.asce.org/",
                "use_ar": "مناقشة نطاق معرفة المهندس المدني.",
            },
            {
                "label_ar": "ISO 14001 (مفهوم استدامة)",
                "cite": "https://www.iso.org/iso-14001-environmental-management.html",
                "use_ar": "إطار مفاهيمي لبعد البيئة — ليس معيار اعتماد برامجي.",
            },
        ],
        "tips_ar": [
            "عند مناقشة اللجنة: فرّق بين «معيار مهني عالمي» و«مؤشر QAA مطلوب محلياً».",
        ],
    },
    "ELEC": {
        "title_ar": "الهندسة الكهربائية",
        "title_en": "Electrical Engineering",
        "department_codes": ("ELEC",),
        "keywords": ("كهرب", "electrical", "ELEC", "إلكترون", "اتصالات"),
        "frameworks": _COMMON_ENG_FRAMEWORKS
        + [
            {
                "name": "IEEE / IEC (مفاهيم مهنية)",
                "role_ar": "أخلاقيات ومعايير أنظمة كهربائية واتصالات",
                "note_ar": "لدعم صياغة CLO للمختبرات والسلامة الكهربائية.",
            },
        ],
        "mission_vision_tips_ar": [
            "حدد إن كان التركيز قدرات، إلكترونيات، تحكم، أو اتصالات — وضوح الهوية يسهّل مواءمة PG/PLO.",
        ],
        "outcomes_tips_ar": [
            "غطِّ تحليل الدوائر/الأنظمة، التجريب المخبري، والتصميم الكهربائي في مستويات I/R/M.",
            "اربط معامل السلامة الكهربائية والبرمجيات الهندسية بشواهد أرشيفية عند الحاجة.",
        ],
        "review_questions_ar": [
            "هل معامل الجهد العالي/الإلكترونيات لديها إجراءات سلامة موثّقة؟",
            "هل مشاريع التحكم/الطاقة ظاهرة كمخرجات Mastery؟",
            "هل ضعاف استبيان المختبرات تُناقش في اللجنة؟",
        ],
        "evidence_hints_ar": [
            "تقارير مختبر، مشاريع تخرج كهربائية، محاضر صيانة المعامل.",
        ],
        "global_refs": [
            {
                "label_ar": "ABET EAC Criteria",
                "cite": "https://www.abet.org/accreditation/accreditation-criteria/",
                "use_ar": "مخرجات الطالب والتصميم.",
            },
            {
                "label_ar": "EUR-ACE Framework",
                "cite": "https://www.enaee.eu/eur-ace-system/",
                "use_ar": "مقارنة مخرجات هندسية أوروبية.",
            },
            {
                "label_ar": "IEEE — Code of Ethics (مفهوم)",
                "cite": "https://www.ieee.org/about/corporate/governance/p7-8.html",
                "use_ar": "مناقشة البعد الأخلاقي المهني.",
            },
            {
                "label_ar": "CDIO",
                "cite": "http://www.cdio.org/",
                "use_ar": "مسار التصميم→التنفيذ للمشاريع الكهربائية.",
            },
        ],
        "tips_ar": [
            "استعن بقوالب المخرجات الكهربائية في المنظومة ثم طابقها مع خطة المقررات المحلية.",
        ],
    },
    "RENEW": {
        "title_ar": "هندسة الطاقات المتجددة",
        "title_en": "Renewable Energy Engineering",
        "department_codes": ("RENEW",),
        "keywords": ("طاقات", "متجدد", "renewable", "RENEW", "شمس", "رياح"),
        "frameworks": _COMMON_ENG_FRAMEWORKS
        + [
            {
                "name": "IRENA / مفاهيم انتقال الطاقة",
                "role_ar": "سياق الاستدامة وسوق الطاقة المتجددة",
                "note_ar": "للإثراء المعرفي في الرسالة والخدمة المجتمعية — ليس معيار اعتماد.",
            },
        ],
        "mission_vision_tips_ar": [
            "اجعل الاستدامة وكفاءة الطاقة وثيقة الصلة برسالة البرنامج ورؤية الكلية.",
        ],
        "outcomes_tips_ar": [
            "غطِّ أنظمة شمسية/رياح/تخزين أو كفاءة طاقة بحسب الخطة، مع قياس مخبري أو مشروعي.",
            "اربط مشاريع التخرج ببيانات أداء حقيقية أو محاكاة موثّقة.",
        ],
        "review_questions_ar": [
            "هل الاستدامة مخرج صريح أم مضمّن فقط؟",
            "هل توجد شواهد تدريب/زيارات محطات؟",
            "هل استبيانات المجتمع/أرباب العمل تغطي جدوى الطاقة؟",
        ],
        "evidence_hints_ar": [
            "تقارير أداء منظومات، محاضر زيارات ميدانية، مشاريع تخرج متعلقة بالطاقة.",
        ],
        "global_refs": [
            {
                "label_ar": "ABET EAC Criteria",
                "cite": "https://www.abet.org/accreditation/accreditation-criteria/",
                "use_ar": "إطار مخرجات هندسية.",
            },
            {
                "label_ar": "IRENA — Knowledge hub",
                "cite": "https://www.irena.org/",
                "use_ar": "سياق سياسات وتقنيات الطاقة المتجددة للنقاش.",
            },
            {
                "label_ar": "ISO 50001 (مفهوم إدارة الطاقة)",
                "cite": "https://www.iso.org/iso-50001-energy-management.html",
                "use_ar": "مفاهيم كفاءة الطاقة — ليس بديلاً عن QAA.",
            },
        ],
        "tips_ar": [
            "في اللجنة: استخدم المراجع العالمية لصياغة الرؤية، ثم اسند الامتثال لمؤشرات PROG المحلية.",
        ],
    },
    "GENERAL": {
        "title_ar": "القسم العام / المرحلة التأسيسية",
        "title_en": "General / Foundation Year",
        "department_codes": ("GENERAL", "GEN", "GS"),
        "keywords": ("عام", "تأسيس", "GENERAL", "سنة عامة"),
        "frameworks": [
            {
                "name": "ABET / EAC foundation concepts",
                "role_ar": "رياضيات وعلوم ومهارات تمهيدية للهندسة",
                "note_ar": "المرحلة العامة تُمهّد لـ PLO التخصص لاحقاً.",
            },
            {
                "name": "ESG / Bologna-inspired progression (مفاهيم)",
                "role_ar": "تتابع التعلم والانتقال للبرنامج التخصصي",
                "note_ar": "للمناقشة فقط — التدرج المحلي حسب لوائح الكلية.",
            },
        ],
        "mission_vision_tips_ar": [
            "رسالة المرحلة العامة: تهيئة معرفية ومهارية قبل التنسيب — ليست رسالة برنامج تخصصي كامل.",
        ],
        "outcomes_tips_ar": [
            "ركّز على مخرجات تأسيسية (رياضيات، فيزياء، مهارات تعلم، لغة تقنية) قابلة للقياس.",
            "وضّح قواعد الانتقال للتخصص واربطها بلوائح الكلية لا بمراجع خارجية وحدها.",
        ],
        "review_questions_ar": [
            "هل مخرجات التأسيس مربوطة بـ GLO الكلية؟",
            "هل مسار التنسيب موثّق في الأرشيف/السياسات؟",
            "هل استبيانات الطلبة تقيس جاهزية الانتقال للتخصص؟",
        ],
        "evidence_hints_ar": [
            "سياسات التنسيب، إحصاءات الانتقال، نماذج إرشاد أكاديمي.",
        ],
        "global_refs": [
            {
                "label_ar": "ABET — إلى مفاهيم التأسيس العلمي",
                "cite": "https://www.abet.org/accreditation/accreditation-criteria/",
                "use_ar": "ما المهارات العلمية الأساسية المتوقعة قبل التخصص.",
            },
            {
                "label_ar": "Tuning / ESG (مفاهيم أوروبية للتعلم)",
                "cite": "https://www.ehea.info/",
                "use_ar": "نقاش تتابع المستويات — مع الالتزام بالتنظيم المحلي.",
            },
        ],
        "tips_ar": [
            "لا تفرض PLO تخصصية ثقيلة على المرحلة العامة؛ حافظ على تمهيد واضح.",
        ],
    },
    # فئات احتياطية إن لم يُطابق رمز القسم
    "engineering": {
        "title_ar": "برنامج هندسي عام (احتياطي)",
        "title_en": "Generic Engineering",
        "department_codes": (),
        "keywords": ("هندس", "engineering", "تقنية"),
        "frameworks": _COMMON_ENG_FRAMEWORKS,
        "mission_vision_tips_ar": [
            "حدّد تخصصاً أو مجالاً تطبيقياً في الرسالة حتى تسهل المواءمة.",
        ],
        "outcomes_tips_ar": [
            "اعتمد مخرجات ABET السبعة كنقطة نقاش ثم طابقها مع QAA PROG-UG.",
        ],
        "review_questions_ar": [
            "هل التصميم والتجريب والأخلاق ظاهرة في المخرجات؟",
            "هل المشروع الختامي مستوى M؟",
        ],
        "evidence_hints_ar": ["مشاريع، معامل، محاضر لجان."],
        "global_refs": [
            {
                "label_ar": "ABET EAC",
                "cite": "https://www.abet.org/accreditation/accreditation-criteria/",
                "use_ar": "مرجع صياغة مخرجات هندسية.",
            },
            {
                "label_ar": "Washington Accord / IEA",
                "cite": "https://www.ieagreements.org/",
                "use_ar": "خصائص خرّيج هندسي.",
            },
        ],
        "tips_ar": [
            "بعد تحديد القسم بدقة، اختر الحزمة المتخصصة (MECH/CIVIL/ELEC/RENEW).",
        ],
    },
    "business": {
        "title_ar": "إدارة / أعمال (احتياطي)",
        "title_en": "Business / Management",
        "department_codes": (),
        "keywords": ("إدارة", "محاسب", "أعمال", "مال", "اقتصاد", "تسويق"),
        "frameworks": [
            {
                "name": "AACSB / EFMD (مفاهيم)",
                "role_ar": "جودة برامج الأعمال عالمياً",
                "note_ar": "للمناقشة إن وُجد برنامج إداري — ليس بديلاً عن QAA.",
            },
        ],
        "mission_vision_tips_ar": [
            "اربط الرسالة بسوق العمل المحلي والأخلاقيات المهنية.",
        ],
        "outcomes_tips_ar": [
            "أدرج التحليل الكمي، الاتصال، والأخلاقيات في PLO.",
        ],
        "review_questions_ar": [
            "هل استبيانات الخريجين/جهات العمل نشطة؟",
            "هل دراسات الحالة تقيس مهارات القرار؟",
        ],
        "evidence_hints_ar": ["تقارير تدريب، استبيانات قطاع."],
        "global_refs": [
            {
                "label_ar": "AACSB (مفاهيم)",
                "cite": "https://www.aacsb.edu/",
                "use_ar": "نقاش جودة برامج الأعمال.",
            },
        ],
        "tips_ar": [
            "في كلية الهندسة نادراً ما تُستخدم هذه الحزمة — راجع رمز القسم.",
        ],
    },
    "general": {
        "title_ar": "حزمة عامة (كل البرامج)",
        "title_en": "Generic QA pack",
        "department_codes": (),
        "keywords": (),
        "frameworks": [
            {
                "name": "OBE / PDCA",
                "role_ar": "رسالة→أهداف→مخرجات→قياس→تحسين",
                "note_ar": "إطار عالمي مشترك للنقاش.",
            },
            {
                "name": "QAA Libya (محلي ملزم)",
                "role_ar": "معايير المركز — INST/PROG",
                "note_ar": "مرجع الامتثال اليومي في المنظومة.",
            },
        ],
        "mission_vision_tips_ar": [
            "رسالة واضحة، رؤية زمنية، أهداف قابلة للقياس.",
        ],
        "outcomes_tips_ar": [
            "CLO → PLO → GLO مترابطة؛ كل مخرج له قياس.",
        ],
        "review_questions_ar": [
            "هل رسالة البرنامج منسجمة مع رسالة الكلية؟",
            "هل كل GLO له PLO؟",
            "هل الأرشيف الفصلي مكتمل؟",
        ],
        "evidence_hints_ar": [
            "شواهد من الأرشيف والاستبيانات بعد ربط يدوي.",
        ],
        "global_refs": [
            {
                "label_ar": "المركز الوطني لضمان الجودة (ليبيا)",
                "cite": "https://qaa.ly/",
                "use_ar": "المرجع الملزم محلياً.",
            },
        ],
        "tips_ar": [
            "ابدأ بالفجوات في المنظومة ثم استخدم المراجع العالمية للصياغة فقط.",
        ],
    },
}

ESCALATION_TARGETS: dict[str, dict[str, str]] = {
    "head_of_department": {
        "label_ar": "رئيس القسم",
        "mode": "head_of_department",
    },
    "academic_vice_dean": {
        "label_ar": "وكيل الشؤون العلمية",
        "mode": "academic_vice_dean",
    },
    "quality_committee": {
        "label_ar": "لجنة الجودة العلمية",
        "mode": "quality_committee",
    },
    "college_dean": {
        "label_ar": "عميد الكلية",
        "mode": "college_dean",
    },
}

POLICY_BANNER_AR = (
    "المساعد يقترح ويناقش ويصوغ مسودات فقط. لا يعتمد امتثالاً ولا يربط شواهد نهائياً "
    "ولا يغيّر بيانات الاعتماد دون تأكيد بشري."
)


def intents_for_mode(mode: str) -> list[dict[str, str]]:
    out = list(COMMON_INTENTS)
    out.extend(MODE_INTENTS.get(mode) or [])
    return out


def catalog_for_client() -> dict[str, Any]:
    modes = []
    for code, meta in ASSISTANT_MODES.items():
        modes.append(
            {
                "code": code,
                "title_ar": meta["title_ar"],
                "subtitle_ar": meta["subtitle_ar"],
                "lens_ar": meta["lens_ar"],
                "phase": meta["phase"],
                "intents": intents_for_mode(code),
            }
        )
    refs = [
        {
            "code": r["code"],
            "label_ar": r["label_ar"],
            "label_en": r.get("label_en") or "",
            "official_url": r.get("official_url") or "",
            "scope_ar": r.get("scope_ar") or "",
            "use_for_ar": list(r.get("use_for_ar") or []),
            "packs": list(r.get("packs") or ()),
        }
        for r in APPROVED_GLOBAL_REFERENCES
    ]
    return {
        "modes": modes,
        "policy_ar": POLICY_BANNER_AR,
        "escalation_targets": [
            {"code": k, "label_ar": v["label_ar"]} for k, v in ESCALATION_TARGETS.items()
        ],
        "approved_global_references": refs,
        "system_usage_topics": list_system_usage_topics(),
        "reference_disclaimer_ar": _REF_DISCLAIMER_AR,
        "suggestion_only": True,
        "topic_label_ar": "موضوع",
        "version": 3,
    }


def match_specialty_pack(department_name_ar: str = "", department_code: str = "") -> dict[str, Any]:
    """مطابقة حزمة مراجع: رمز القسم أولاً، ثم الكلمات المفتاحية، ثم احتياطي."""
    code_u = (department_code or "").strip().upper()
    blob = f"{department_name_ar} {department_code}".strip()
    blob_l = blob.lower()

    # 1) مطابقة رمز القسم المباشرة أو ضمن department_codes
    if code_u and code_u in SPECIALTY_PACKS:
        pack = SPECIALTY_PACKS[code_u]
        return {"code": code_u, "disclaimer_ar": _REF_DISCLAIMER_AR, **pack}
    for key, pack in SPECIALTY_PACKS.items():
        codes = {str(c).upper() for c in (pack.get("department_codes") or ())}
        if code_u and code_u in codes:
            return {"code": key, "disclaimer_ar": _REF_DISCLAIMER_AR, **pack}

    # 2) كلمات مفتاحية (تجاهل الحزم العامة جداً أولاً)
    for key, pack in SPECIALTY_PACKS.items():
        if key in ("general", "engineering", "business"):
            continue
        for kw in pack.get("keywords") or ():
            if not kw:
                continue
            if kw.lower() in blob_l or kw in blob:
                return {"code": key, "disclaimer_ar": _REF_DISCLAIMER_AR, **pack}

    for key in ("engineering", "business"):
        pack = SPECIALTY_PACKS[key]
        for kw in pack.get("keywords") or ():
            if kw and (kw.lower() in blob_l or kw in blob):
                return {"code": key, "disclaimer_ar": _REF_DISCLAIMER_AR, **pack}

    return {
        "code": "general",
        "disclaimer_ar": _REF_DISCLAIMER_AR,
        **SPECIALTY_PACKS["general"],
    }


def list_specialty_packs_summary() -> list[dict[str, Any]]:
    """ملخص للحزم المعرّفة (للواجهة/الاختبارات)."""
    out = []
    for key, pack in SPECIALTY_PACKS.items():
        out.append(
            {
                "code": key,
                "title_ar": pack.get("title_ar"),
                "department_codes": list(pack.get("department_codes") or ()),
                "refs_count": len(pack.get("global_refs") or []),
            }
        )
    return out


def exportable_specialty_packs(*, primary_only: bool = True) -> dict[str, Any]:
    """
    حزم قابلة للتحميل: الروابط والنصائح المعتمدة في المنظومة.
    ملاحظة: لا نحمّل محتويات مواقع خارجية كاملة — فقط بطاقات مراجعنا المعتمدة + الروابط.
    """
    primary_keys = ("MECH", "CIVIL", "ELEC", "RENEW", "GENERAL")
    keys = primary_keys if primary_only else tuple(SPECIALTY_PACKS.keys())
    packs = []
    for key in keys:
        pack = SPECIALTY_PACKS.get(key)
        if not pack:
            continue
        packs.append(
            {
                "code": key,
                "title_ar": pack.get("title_ar"),
                "title_en": pack.get("title_en"),
                "department_codes": list(pack.get("department_codes") or ()),
                "disclaimer_ar": _REF_DISCLAIMER_AR,
                "frameworks": list(pack.get("frameworks") or []),
                "mission_vision_tips_ar": list(pack.get("mission_vision_tips_ar") or []),
                "outcomes_tips_ar": list(pack.get("outcomes_tips_ar") or []),
                "review_questions_ar": list(pack.get("review_questions_ar") or []),
                "evidence_hints_ar": list(pack.get("evidence_hints_ar") or []),
                "global_refs": list(pack.get("global_refs") or []),
                "tips_ar": list(pack.get("tips_ar") or []),
            }
        )
    return {
        "status": "ok",
        "title_ar": "حزم المراجع العالمية المعتمدة في مساعد الجودة",
        "disclaimer_ar": _REF_DISCLAIMER_AR,
        "note_ar": (
            "الملف يحتوي بطاقات المراجع والروابط الرسمية للاطلاع. "
            "لا يتضمن تنزيلاً آلياً لنصوص مواقع خارجية بالكامل."
        ),
        "approved_global_references": [
            {
                "code": r["code"],
                "label_ar": r["label_ar"],
                "label_en": r.get("label_en") or "",
                "official_url": r.get("official_url") or "",
                "scope_ar": r.get("scope_ar") or "",
                "discussion_summary_ar": r.get("discussion_summary_ar") or "",
                "use_for_ar": list(r.get("use_for_ar") or []),
                "packs": list(r.get("packs") or ()),
            }
            for r in APPROVED_GLOBAL_REFERENCES
        ],
        "packs": packs,
        "version": 2,
        "suggestion_only": True,
    }


def specialty_pack_to_markdown(pack: dict[str, Any]) -> str:
    lines = [
        f"# {pack.get('title_ar') or pack.get('code')}",
        "",
        f"**الرمز:** `{pack.get('code')}`",
        "",
        f"> {pack.get('disclaimer_ar') or _REF_DISCLAIMER_AR}",
        "",
        "## أطر للنقاش",
    ]
    for f in pack.get("frameworks") or []:
        lines.append(f"- **{f.get('name')}** — {f.get('role_ar')}: {f.get('note_ar')}")
    lines.extend(["", "## رسالة / رؤية"])
    for t in pack.get("mission_vision_tips_ar") or []:
        lines.append(f"- {t}")
    lines.extend(["", "## مخرجات التعلم"])
    for t in pack.get("outcomes_tips_ar") or pack.get("tips_ar") or []:
        lines.append(f"- {t}")
    lines.extend(["", "## أسئلة مراجعة"])
    for q in pack.get("review_questions_ar") or []:
        lines.append(f"- {q}")
    lines.extend(["", "## شواهد محتملة (ربط يدوي)"])
    for e in pack.get("evidence_hints_ar") or []:
        lines.append(f"- {e}")
    lines.extend(["", "## مراجع وروابط اطّلاع"])
    for r in pack.get("global_refs") or []:
        lines.append(f"- [{r.get('label_ar')}]({r.get('cite')}) — {r.get('use_ar')}")
    lines.append("")
    return "\n".join(lines)
