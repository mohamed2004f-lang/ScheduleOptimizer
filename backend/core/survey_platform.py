"""منصة الاستبيانات متعددة الفئات (و-0 → و-5)."""

from __future__ import annotations

from typing import Any

# مراجع إطارية: SERU/SET (تجربة الطالب)، IDEA (تقييم التدريس)، ECP/QM (ضمان الجودة)،
# NASPA (شؤون الطلبة)، أدبيات قيادة الأقسام في التعليم العالي (360).

SURVEY_QUESTIONS_TARGET_COUNT = 10

RESPONDENT_ROLE_LABELS: dict[str, str] = {
    "student": "الطالب",
    "instructor": "عضو هيئة التدريس",
    "supervisor": "المشرف الأكاديمي",
    "staff": "الموظف الإداري",
    "alumni": "الخريج",
    "employer": "جهة العمل / القطاع",
    "partner": "الشريك المجتمعي",
}

EXTERNAL_SURVEY_CODES: frozenset[str] = frozenset({
    "employer_strategic",
    "alumni",
})

EMPLOYER_ORG_TYPES: tuple[tuple[str, str], ...] = (
    ("government", "قطاع حكومي"),
    ("private", "شركة خاصة"),
    ("state_owned", "شركة عامة (مملوكة للدولة)"),
    ("mixed", "قطاع مختلط"),
    ("nonprofit", "منظمة غير ربحية"),
    ("other", "أخرى"),
)

EMPLOYER_HIRE_DEPARTMENTS_LABEL = "من أي أقسام توظّفون (أو تحتاجون) خريجين الكلية؟"
EMPLOYER_HIRE_DEPARTMENTS_HINT = (
    "يمكن اختيار أكثر من قسم. تحت كل قسم ستظهر خانة لكتابة التخصص أو الشعبة/المسار المطلوب."
)
EMPLOYER_HIRE_NEEDS_FIELD_LABEL = "التخصص / الشعبة أو المسار المطلوب من هذا القسم"
EMPLOYER_HIRE_NEEDS_FIELD_HINT = (
    "اكتب بحرية ما تحتاجونه — مثال: «طاقة»، «تصنيع»، «اتصالات»، أو «أي تخصص في القسم»."
)

ALUMNI_OPEN_COMMENT_LABEL = (
    "بناءً على خبرتك، ما التوصية التي تقدمها للكلية لضمان توظيف الخريجين في مسميات وظيفية معتمدة؟ (اختياري)"
)
EMPLOYER_OPEN_COMMENT_LABEL = "أهم ثلاث توصيات لتحسين الخطة الاستراتيجية أو مخرجات التعلم (اختياري)"

ALUMNI_INTRO_AR = (
    "تسعى الكلية لمراجعة البرامج الأكاديمية لضمان مواءمة مخرجاتها مع سوق العمل. "
    "حدّد أولاً قسمك وتخصصك الدقيق في الحقول أدناه — فجميع أسئلة الاستبيان التالية "
    "تخص ذلك البرنامج الذي درسته وليس الكلية عموماً. "
    "المدة التقريبية: ٨–١٠ دقائق. جميع الإجابات مجمّعة ولا تُنشر بأسماء الأفراد."
)

ALUMNI_PROGRAM_TERMINOLOGY_AR = (
    "للتوضيح: «البرنامج» في هذا الاستبيان = التخصص الذي درسته (القسم + الشعبة/المسار إن وُجد). "
    "«القسم» هو تخصصك الرئيسي (مثل: الهندسة الميكانيكية). "
    "«الشعبة/المسار» هو التخصص الدقيق داخل القسم (مثل: طاقة، تصنيع) — اختر «لا ينطبق» إن لم تكن ضمن شعبة."
)

ALUMNI_PROGRAM_SCOPE_HINT_AR = (
    "الأسئلة التالية عن البرنامج الذي حدّدته أعلاه (قسمك ومسارك إن وُجد)، وليس عن الكلية بأكملها."
)

ALUMNI_DEPARTMENT_FIELD_LABEL = "قسمك / التخصص الرئيسي"
ALUMNI_DEPARTMENT_FIELD_HINT = "مثال: الهندسة الميكانيكية، الهندسة الكهربائية — هذا هو «برنامجك» بمعناه العام."
ALUMNI_TRACK_FIELD_LABEL = "الشعبة أو المسار الدقيق (إن وُجد)"
ALUMNI_TRACK_FIELD_HINT = "مثال: طاقة، تصنيع. إن لم تكن في شعبة محددة اختر «لا ينطبق». إن كان مسارك غير مدرج (برنامج قديم/موقوف) اختر «مسار غير مدرج» واكتب اسمه."
ALUMNI_TRACK_CUSTOM_OPTION_LABEL = "مسار/شعبة غير مدرج (برنامج قديم أو موقوف)"
ALUMNI_TRACK_CUSTOM_FIELD_LABEL = "اسم المسار أو الشعبة التي تخرّجت منها"
ALUMNI_TAIL_PROGRAM_HINT_AR = (
    "الإجابات التالية تخص البرنامج الذي حدّدته أعلاه (قسمك ومسارك)، وليس الكلية بأكملها."
)

ALUMNI_EMPLOYMENT_STATUSES: tuple[tuple[str, str], ...] = (
    ("in_specialty", "أعمل في مجال تخصصي"),
    ("other_engineering", "أعمل في مجال هندسي آخر"),
    ("non_engineering", "أعمل في مجال غير هندسي"),
    ("self_employed", "أعمل لحسابي / مشروع خاص"),
    ("job_seeking", "أبحث عن عمل"),
    ("postgrad", "أكمل الدراسات العليا"),
    ("not_working", "لا أعمل حالياً"),
)

ALUMNI_EMPLOYED_STATUSES: frozenset[str] = frozenset({
    "in_specialty",
    "other_engineering",
    "non_engineering",
    "self_employed",
})

ALUMNI_ENGINEERING_QUAL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("yes", "نعم"),
    ("no", "لا"),
    ("partial", "جزئياً"),
    ("na", "لا ينطبق"),
)

ALUMNI_PROGRAM_DEVELOPMENT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("merge_dept", "دمج مع قسم آخر"),
    ("freeze_conditions", "تجميد حتى تتغير ظروف الحالية"),
    ("replace_program", "استبدال ببرنامج آخر أكثر طلباً في سوق العمل"),
)

ALUMNI_PROGRAM_FREEZE_SUPPORT_QUESTION_AR = (
    "هل تؤيد تجميد البرنامج الذي قيّمته أعلاه في ظل الظروف الحالية؟"
)

ALUMNI_PROGRAM_FREEZE_QUESTION_AR = (
    "في حال قررت الكلية تجميد البرنامج، ما مقترحك؟"
)

# تسميات قديمة لعرض الردود السابقة في التقارير
ALUMNI_LEGACY_PROGRAM_DEVELOPMENT_LABELS: dict[str, str] = {
    "curriculum": "تعديل الخطة الدراسية",
    "rename": "تغيير اسم التخصص",
    "merge": "دمج البرنامج مع تخصص آخر",
    "new_tracks": "استحداث شعب جديدة داخل القسم",
    "freeze": "تجميد البرنامج",
    "no_change": "لا تغيير جوهري",
}

ALUMNI_PROFILE_FIELD_LABELS: tuple[str, ...] = (
    "الاسم الثلاثي (اختياري)",
    "سنة التخرج *",
    f"{ALUMNI_DEPARTMENT_FIELD_LABEL} *",
    ALUMNI_TRACK_FIELD_LABEL,
    "ملخص البرنامج المُقيَّم (يتحدّث تلقائياً)",
    "الحالة المهنية الحالية *",
    "مسمى وظيفتك الحالي (حسب الحالة)",
    "هل تتطلب وظيفتك مؤهلاً هندسياً؟ (حسب الحالة)",
    "هل واجهت رفضاً عند التقديم على وظائف؟ (حسب الحالة)",
    "رقم الهاتف (اختياري)",
)

ALUMNI_TAIL_FIXED_FIELDS: tuple[dict[str, Any], ...] = (
    {"label_ar": "هل تنصح الطلاب الجدد بالالتحاق بهذا التخصص (البرنامج الذي حدّدته أعلاه) في ظل الظروف الحالية؟", "field_type": "select", "options": ("نعم", "لا")},
    {"label_ar": "لماذا؟", "field_type": "text", "optional": True},
    {"label_ar": ALUMNI_PROGRAM_FREEZE_SUPPORT_QUESTION_AR, "field_type": "select", "options": ("نعم", "لا")},
    {
        "label_ar": ALUMNI_PROGRAM_FREEZE_QUESTION_AR,
        "field_type": "select",
        "options": tuple(lbl for _, lbl in ALUMNI_PROGRAM_DEVELOPMENT_OPTIONS),
        "conditional": True,
    },
    {"label_ar": "ما أبرز صعوبة واجهتها عند بدء العمل؟", "field_type": "text", "optional": True},
    {"label_ar": "ما المهارة التقنية أو البرمجية التي تمنيت التركيز عليها أكثر؟", "field_type": "text", "optional": True},
    {"label_ar": "ما التقنيات أو الأدوات التي يتطلبها عملك ولم يغطّها البرنامج؟", "field_type": "text", "optional": True},
    {"label_ar": ALUMNI_OPEN_COMMENT_LABEL, "field_type": "textarea", "optional": True},
)

ALUMNI_QUESTION_SECTIONS: list[tuple[int, str]] = [
    (10, "ثانياً — جودة المخرجات والجاهزية المهنية"),
    (80, "ثالثاً — الفجوة مع متطلبات السوق"),
    (90, "رابعاً — التقييم العام"),
]

ALUMNI_V2_MARKER_PREFIX = "إلى أي مدى كان البرنامج متوازناً"


def build_alumni_admin_outline(questions: list[dict]) -> list[dict[str, Any]]:
    """هيكل النموذج الكامل كما يظهر للخريج — لصفحة إدارة البنود."""
    sections = list(ALUMNI_QUESTION_SECTIONS)
    next_section = 0
    items: list[dict[str, Any]] = [
        {"kind": "section", "title_ar": "أولاً — معلومات الخريج والواقع المهني", "fixed_block": True},
    ]
    for lbl in ALUMNI_PROFILE_FIELD_LABELS:
        items.append({"kind": "fixed", "label_ar": lbl, "fixed_block": True, "field_type": "profile"})
    for q in questions:
        sort_order = int(q.get("sort_order") or 0)
        while next_section < len(sections) and sort_order >= int(sections[next_section][0]):
            items.append({"kind": "section", "title_ar": sections[next_section][1]})
            next_section += 1
        items.append({"kind": "question", **q})
    items.append(
        {"kind": "section", "title_ar": "خامساً — التوصيات ومستقبل البرنامج", "fixed_block": True}
    )
    for fx in ALUMNI_TAIL_FIXED_FIELDS:
        items.append({"kind": "fixed", "fixed_block": True, **fx})
    return items


def program_development_label(choice_key: str) -> str:
    """تسمية عربية لخيار تجميد/تطوير البرنامج (حالية أو قديمة)."""
    key = (choice_key or "").strip()
    if not key:
        return ""
    for k, lbl in ALUMNI_PROGRAM_DEVELOPMENT_OPTIONS:
        if k == key:
            return lbl
    return ALUMNI_LEGACY_PROGRAM_DEVELOPMENT_LABELS.get(key, key)

# ما يُفترض أن يملأه كل دور في صفحة «تعبئة الاستبيانات»
SURVEY_METRIC_LABELS: dict[str, str] = {
    "student_services": "رضا الطالب — خدمات الشؤون",
    "student_facilities": "رضا الطالب — المرافق",
    "faculty_hod": "رأي الأستاذ — رئيس القسم",
    "faculty_dean": "رأي الأستاذ — قيادة الكلية وسياساتها",
    "faculty_educational_process": "تقييم العملية التعليمية في القسم",
    "faculty_external_collaborator": "المتعاون الخارجي — تجربة التدريس والتنسيق",
    "supervisor_advising": "المشرف — جودة الإرشاد والمتابعة",
    "supervisor_coordination": "المشرف — التنسيق مع القسم والخدمات",
    "staff_workplace": "رضا الموظف — بيئة العمل",
    "staff_student_services": "جودة خدمة الطالب (موظف)",
}

# مقدّمات واجهة التعبئة — استبيانات عضو هيئة التدريس
SURVEY_TEMPLATE_INTRO: dict[str, dict[str, str]] = {
    "faculty_hod": {
        "subtitle_ar": "رأيك في قيادة رئيس قسمك هذا الفصل",
        "about_ar": (
            "قيّم تجربتك المباشرة مع رئيس القسم: التوجيه، العدالة، التواصل، ودعم التطوير المهني. "
            "لا تُعرض إجابتك باسمك؛ تُجمَّع مع زملائك في القسم (٣ أعضاء على الأقل)."
        ),
        "duration_hint": "٣–٥ دقائق · ١٠ بنود",
        "icon": "fa-user-tie",
    },
    "faculty_dean": {
        "subtitle_ar": "رأيك في أداء إدارة الكلية ووضوح سياساتها (ضمن صلاحياتها)",
        "about_ar": (
            "قيّم وضوح قرارات الكلية، دعم التعليم والجودة، والتواصل مع هيئة التدريس. "
            "الاستبيان سري ويُجمَّع مع بقية أعضاء هيئة التدريس."
        ),
        "duration_hint": "٣–٥ دقائق · ١٠ بنود",
        "icon": "fa-building-columns",
    },
    "faculty_educational_process": {
        "subtitle_ar": "رأيك في إجراءات التدريس والتقويم داخل قسمك",
        "about_ar": (
            "قيّم وضوح إقفال المقررات، سياسات الامتحانات والدرجات، الربط بمخرجات البرنامج، "
            "وجودة إجراءات ضمان الجودة في قسمك."
        ),
        "duration_hint": "٣–٥ دقائق · ١٠ بنود",
        "icon": "fa-chalkboard",
    },
    "faculty_external_collaborator": {
        "subtitle_ar": "تجربتك في التعاون التدريسي مع القسم (متعاون خارجي)",
        "about_ar": (
            "يُخصَّص لمن يُكلف بتدريس مقرر أو أكثر دون انتماء دائم للقسم. "
            "قيّم وضوح التكليف، التنسيق، والدعم المتاح — دون أسئلة عن اجتماعات أو سياسات داخلية لا تشارك فيها."
        ),
        "duration_hint": "٢–٣ دقائق · ٦ بنود",
        "icon": "fa-handshake",
    },
}

# عناوين أقسام داخل نموذج التعبئة (حسب sort_order)
SURVEY_QUESTION_SECTIONS: dict[str, list[tuple[int, str]]] = {
    "faculty_hod": [
        (10, "أولاً — القيادة والتوجيه"),
        (50, "ثانياً — العدالة والتواصل"),
        (90, "ثالثاً — التقييم الإجمالي"),
    ],
    "faculty_dean": [
        (10, "أولاً — السياسات وموارد الكلية"),
        (50, "ثانياً — التواصل والحوكمة"),
        (90, "ثالثاً — التقييم الإجمالي"),
    ],
    "faculty_educational_process": [
        (10, "أولاً — التقويم والإقفال"),
        (50, "ثانياً — الجودة والتنسيق"),
        (90, "ثالثاً — التقييم الإجمالي"),
    ],
}


def survey_template_intro(template_code: str) -> dict[str, str]:
    return dict(SURVEY_TEMPLATE_INTRO.get((template_code or "").strip(), {}))


def survey_question_section_title(template_code: str, sort_order: int) -> str | None:
    sections = SURVEY_QUESTION_SECTIONS.get((template_code or "").strip(), [])
    title = None
    for threshold, label in sections:
        if int(sort_order) >= int(threshold):
            title = label
    return title


# ربط كل استبيان بمعايير الاعتماد (شاهد / آلي / هجين)
SURVEY_ACCREDITATION_MAP: dict[str, list[dict[str, str]]] = {
    "student_course": [
        {
            "standard_code": "SS-01",
            "indicator_code": "SS-01-1",
            "indicator_title_ar": "رضا الطلبة (استبيان المقرر)",
            "link_type": "evidence",
            "usage_ar": "شاهد اختياري — يُربط يدوياً من واجهة إدارة الامتثال.",
        },
    ],
    "student_services": [
        {
            "standard_code": "SS-01",
            "indicator_code": "SS-01-1",
            "indicator_title_ar": "رضا الطلبة",
            "link_type": "evidence",
            "usage_ar": "شاهد داعم على جودة خدمات الشؤون والتسجيل.",
        },
        {
            "standard_code": "SS-02",
            "indicator_code": "SS-02-1",
            "indicator_title_ar": "معدل التخرج التقريبي",
            "link_type": "evidence",
            "usage_ar": "شاهد على تجربة الطالب وخدمات الدعم الأكاديمي.",
        },
    ],
    "student_facilities": [
        {
            "standard_code": "FF-01",
            "indicator_code": "FF-01-1",
            "indicator_title_ar": "تقييم البنية التحتية",
            "link_type": "hybrid",
            "usage_ar": "يُكمّل أو يستبدل الإدخال اليدوي لـ FF-01-1 (مقترح).",
        },
    ],
    "faculty_hod": [
        {
            "standard_code": "GV-02",
            "indicator_code": "GV-02-1",
            "indicator_title_ar": "اعتماد السياسات الأكاديمية",
            "link_type": "evidence",
            "usage_ar": "دليل على قيادة القسم والمشاركة في صنع القرار.",
        },
    ],
    "faculty_dean": [
        {
            "standard_code": "GV-01",
            "indicator_code": "GV-01-1",
            "indicator_title_ar": "هيكل الحوكمة",
            "link_type": "evidence",
            "usage_ar": "دليل على وضوح السياسات والحوكمة على مستوى الكلية.",
        },
        {
            "standard_code": "FF-02",
            "indicator_code": "FF-02-1",
            "indicator_title_ar": "خطة مالية للتعليم",
            "link_type": "evidence",
            "usage_ar": "شاهد على متابعة الكلية لاحتياجات الأقسام لدى الجامعة.",
        },
    ],
    "faculty_educational_process": [
        {
            "standard_code": "QA-02",
            "indicator_code": "QA-02-1",
            "indicator_title_ar": "نسبة اكتمال تقارير الإقفال",
            "link_type": "evidence",
            "usage_ar": "شاهد مكمّل على رضا الأساتذة عن إجراءات الإقفال.",
        },
        {
            "standard_code": "QA-03",
            "indicator_code": "QA-03-1",
            "indicator_title_ar": "متوسط تحقق مخرجات التعلم",
            "link_type": "evidence",
            "usage_ar": "شاهد على وضوح التقويم والربط بمخرجات البرنامج.",
        },
    ],
    "supervisor_advising": [
        {
            "standard_code": "SS-02",
            "indicator_code": "SS-02-1",
            "indicator_title_ar": "معدل التخرج التقريبي",
            "link_type": "evidence",
            "usage_ar": "شاهد على جودة الإرشاد الأكاديمي والمتابعة.",
        },
    ],
    "supervisor_coordination": [
        {
            "standard_code": "SS-01",
            "indicator_code": "SS-01-1",
            "indicator_title_ar": "رضا الطلبة",
            "link_type": "evidence",
            "usage_ar": "شاهد على تنسيق المشرف مع القسم وشؤون الطلبة.",
        },
        {
            "standard_code": "QA-01",
            "indicator_code": "QA-01-1",
            "indicator_title_ar": "لقطات مؤشرات الجودة",
            "link_type": "evidence",
            "usage_ar": "يُرفع ضمن ملف ضمان الجودة كشاهد نوعي.",
        },
    ],
    "staff_workplace": [
        {
            "standard_code": "HR-01",
            "indicator_code": "HR-01-1",
            "indicator_title_ar": "نسبة المؤهلات العليا",
            "link_type": "evidence",
            "usage_ar": "شاهد على بيئة العمل ودعم الموظفين.",
        },
        {
            "standard_code": "HR-02",
            "indicator_code": "HR-02-1",
            "indicator_title_ar": "نسبة طالب : أستاذ",
            "link_type": "evidence",
            "usage_ar": "شاهد مكمّل على كفاءة الخدمات الإدارية.",
        },
    ],
    "staff_student_services": [
        {
            "standard_code": "SS-01",
            "indicator_code": "SS-01-1",
            "indicator_title_ar": "رضا الطلبة",
            "link_type": "evidence",
            "usage_ar": "منظور الموظف لجودة خدمة الطالب.",
        },
    ],
    "employer_strategic": [
        {
            "standard_code": "GV-01",
            "indicator_code": "GV-01-1",
            "indicator_title_ar": "هيكل الحوكمة",
            "link_type": "evidence",
            "usage_ar": "استشارة القطاع في الرؤية والخطة الاستراتيجية.",
        },
        {
            "standard_code": "QA-03",
            "indicator_code": "QA-03-1",
            "indicator_title_ar": "متوسط تحقق مخرجات التعلم",
            "link_type": "evidence",
            "usage_ar": "رأي القطاع في مخرجات تعلم الخريج على مستوى الكلية.",
        },
        {
            "standard_code": "CR",
            "indicator_code": "CR-01",
            "indicator_title_ar": "الشراكات المجتمعية",
            "link_type": "evidence",
            "usage_ar": "استعداد القطاع للشراكة مع الكلية.",
        },
    ],
    "alumni": [
        {
            "standard_code": "QA-03",
            "indicator_code": "QA-03-1",
            "indicator_title_ar": "متوسط تحقق مخرجات التعلم",
            "link_type": "evidence",
            "usage_ar": "رضا الخريج عن جودة التعليم والجاهزية المهنية.",
        },
        {
            "standard_code": "SS-02",
            "indicator_code": "SS-02-1",
            "indicator_title_ar": "معدل التخرج التقريبي",
            "link_type": "evidence",
            "usage_ar": "شاهد على تجربة الخريج طويلة المدى.",
        },
    ],
}

LINK_TYPE_LABELS_AR: dict[str, str] = {
    "auto": "آلي",
    "hybrid": "هجين",
    "evidence": "شاهد",
    "manual": "يدوي",
}

ROLE_SURVEY_FILL_GUIDE: dict[str, str] = {
    "student": "تقييم كل مقرر مسجّل به، ثم استبيانات الخدمات والمرافق.",
    "instructor": (
        "ثلاثة استبيانات قصيرة (وضع الأستاذ فقط): "
        "١) رئيس قسمك، ٢) قيادة الكلية وسياساتها، ٣) إجراءات التدريس والإقفال في قسمك. "
        "كل استبيان ~٣–٥ دقائق، إجاباتك مجهولة."
    ),
    "head_of_department": "كعضو هيئة تدريس: نفس استبيانات الأستاذ (يُنصح بوضع «أستاذ» من شريط الأدوار إن وُجد).",
    "college_dean": "كعضو هيئة تدريس: نفس استبيانات الأستاذ — في وضع القيادة أو «أستاذ» من شريط الأدوار.",
    "academic_vice_dean": "كعضو هيئة تدريس: نفس استبيانات الأستاذ — في وضع الوكيل أو «أستاذ» من شريط الأدوار.",
    "supervisor": "استبيانان للمشرف (إرشاد ومتابعة + تنسيق مع القسم)، وتقرير إرشاد كمي منفصل.",
    "staff": "استبيان بيئة العمل وجودة خدمة الطالب من منظور الموظف.",
    "admin_main": "هذه الصفحة لمن يملأ استبياناً بصفته (طالب/أستاذ/موظف). للمتابعة: «نتائج الاستبيانات» أو «إعداد بنود الاستبيانات».",
    "admin": "هذه الصفحة لمن يملأ استبياناً بصفته. للمتابعة: «نتائج الاستبيانات» أو «إعداد بنود الاستبيانات».",
}

SURVEY_TEMPLATE_SEED: list[dict[str, Any]] = [
    {
        "code": "student_course",
        "title_ar": "تقييم المقرر والأستاذ (طالب)",
        "respondent_role": "student",
        "subject_type": "course_section",
        "is_anonymous": 1,
        "min_aggregate": 5,
        "department_scoped": 0,
        "legacy_course_eval": 1,
    },
    {
        "code": "student_services",
        "title_ar": "رضا الطالب عن خدمات الشؤون والتسجيل",
        "respondent_role": "student",
        "subject_type": "student_services",
        "is_anonymous": 1,
        "min_aggregate": 10,
        "department_scoped": 0,
    },
    {
        "code": "student_facilities",
        "title_ar": "رضا الطالب عن المرافق والبيئة التعليمية",
        "respondent_role": "student",
        "subject_type": "facilities",
        "is_anonymous": 1,
        "min_aggregate": 10,
        "department_scoped": 0,
    },
    {
        "code": "faculty_hod",
        "title_ar": "١ — رأيي في قيادة رئيس القسم",
        "respondent_role": "instructor",
        "subject_type": "department_head",
        "is_anonymous": 1,
        "min_aggregate": 3,
        "department_scoped": 1,
    },
    {
        "code": "faculty_dean",
        "title_ar": "٢ — رأيي في قيادة الكلية وسياساتها الأكاديمية",
        "respondent_role": "instructor",
        "subject_type": "dean",
        "is_anonymous": 1,
        "min_aggregate": 3,
        "department_scoped": 0,
    },
    {
        "code": "faculty_educational_process",
        "title_ar": "٣ — رأيي في العملية التعليمية داخل القسم",
        "respondent_role": "instructor",
        "subject_type": "educational_process",
        "is_anonymous": 1,
        "min_aggregate": 3,
        "department_scoped": 1,
    },
    {
        "code": "faculty_external_collaborator",
        "title_ar": "استبيان المتعاون الخارجي — تجربة التدريس والتنسيق",
        "respondent_role": "instructor",
        "subject_type": "external_teaching",
        "is_anonymous": 1,
        "min_aggregate": 1,
        "department_scoped": 0,
    },
    {
        "code": "supervisor_advising",
        "title_ar": "استبيان المشرف الأكاديمي — جودة الإرشاد والمتابعة",
        "respondent_role": "supervisor",
        "subject_type": "supervision",
        "is_anonymous": 1,
        "min_aggregate": 1,
        "department_scoped": 1,
    },
    {
        "code": "supervisor_coordination",
        "title_ar": "استبيان المشرف — التنسيق مع القسم وشؤون الطلبة",
        "respondent_role": "supervisor",
        "subject_type": "supervision_coordination",
        "is_anonymous": 1,
        "min_aggregate": 1,
        "department_scoped": 1,
    },
    {
        "code": "staff_workplace",
        "title_ar": "رضا الموظف عن بيئة العمل والأدوات",
        "respondent_role": "staff",
        "subject_type": "workplace",
        "is_anonymous": 1,
        "min_aggregate": 3,
        "department_scoped": 0,
    },
    {
        "code": "staff_student_services",
        "title_ar": "تقييم الموظف لجودة خدمة الطالب",
        "respondent_role": "staff",
        "subject_type": "student_services",
        "is_anonymous": 1,
        "min_aggregate": 3,
        "department_scoped": 0,
    },
    {
        "code": "employer_strategic",
        "title_ar": "استشارة القطاع — الرؤية والخطة والمخرجات",
        "respondent_role": "employer",
        "subject_type": "sector_consultation",
        "is_anonymous": 1,
        "min_aggregate": 5,
        "department_scoped": 0,
    },
    {
        "code": "alumni",
        "title_ar": "استبيان الخريج — تقييم البرنامج الأكاديمي",
        "respondent_role": "alumni",
        "subject_type": "alumni_feedback",
        "is_anonymous": 1,
        "min_aggregate": 5,
        "department_scoped": 0,
    },
]

# (label_ar, sort_order) — 10 بنود لكل قالب
QUESTION_SEED: dict[str, list[tuple[str, int]]] = {
    "student_services": [
        ("أستطيع معرفة الإجراء المطلوب لكل طلب (تسجيل، إسقاط، اعتراض…)", 10),
        ("أجد المعلومات الأكاديمية التي أحتاجها دون صعوبة", 20),
        ("تُنجَز معاملاتي في السجل (تسجيل، كشف، شهادات) بدقة", 30),
        ("أتلقى رداً على استفساري خلال مدة معقولة", 40),
        ("يعاملني موظفو الشؤون باحترام ومهنية", 50),
        ("تُطبَّق اللوائح على الجميع بنفس المعايير", 60),
        ("قنوات التواصل الرسمية (بوابة، بريد، مكتب) فعّالة", 70),
        ("تُعالَج حالتي الخاصة (صعوبات، ظروف استثنائية) بشكل مناسب", 80),
        ("الرسوم والمواعيد والجداول الرسمية معلنة بوضوح", 90),
        ("بشكل عام، أنا راضٍ عن خدمات الشؤون والتسجيل", 100),
    ],
    "student_facilities": [
        ("القاعات الدراسية نظيفة وصالحة للاستخدام", 10),
        ("المختبرات والورش تلبي احتياجات التعلم التطبيقي", 20),
        ("أستطيع استخدام الحاسوب والشبكة عند الحاجة للدراسة", 30),
        ("المكتبة والمصادر الإلكترونية تدعم دراستي", 40),
        ("أشعر بالأمن والسلامة داخل الحرم", 50),
        ("المرافق مناسبة لذوي الإعاقة والوصول السهل", 60),
        ("البيئة داخل القاعة تساعدني على التركيز والتعلم", 70),
        ("خدمات الرعاية والدعم الطلابي متوفرة في الحرم", 80),
        ("تتوفر مساحات مناسبة للعمل الجماعي والأنشطة", 90),
        ("بشكل عام، أنا راضٍ عن البنية التحتية والمرافق", 100),
    ],
    "faculty_hod": [
        ("رئيس القسم يوضّح لي أولويات القسم وقراراته الأكاديمية", 10),
        ("توزيع الأعباء التدريسية والإدارية عادل بين أعضاء القسم", 20),
        ("رئيس القسم يدعم تطويري المهني (تدريب، لجان، فرص بحثية)", 30),
        ("اجتماعات القسم مفيدة ويُشرَك فيها الأعضاء في القرار", 40),
        ("رئيس القسم يستمع لملاحظاتي ويتواصل بشفافية", 50),
        ("الاعتراضات والنزاعات تُعالَج بعدالة ودون تحيّز", 60),
        ("رئيس القسم يتابع جودة التدريس ويساعد في تحسين المقررات", 70),
        ("رئيس القسم يمثّل مصالح القسم أمام إدارة الكلية بفعالية", 80),
        ("رئيس القسم يلتزم بمعايير ضمان الجودة والاعتماد", 90),
        ("تقييمي الإجمالي لأداء رئيس القسم هذا الفصل", 100),
    ],
    "faculty_dean": [
        ("سياسات الكلية واستراتيجيتها الأكاديمية واضحة لي", 10),
        ("الكلية تتابع احتياجات الأقسام (تعيينات، مرافق، ميزانيات) لدى الجامعة بفعالية", 20),
        ("إدارة الكلية تدعم نشاطي البحثي (منح داخلية، تنسيق مشاريع، تسهيلات نشر) ضمن إمكانياتها", 30),
        ("إدارة الكلية تدعم مبادرات الاعتماد وضمان الجودة", 40),
        ("التواصل بين إدارة الكلية وأعضاء هيئة التدريس فعّال", 50),
        ("اتخاذ القرار في الكلية شفاف ومبني على بيانات", 60),
        ("الكلية تتابع تطوير البرامج ومراجعتها ومواءمتها مع سوق العمل (بالتنسيق مع الأقسام)", 70),
        ("بيئة العمل في الكلية محترمة ومحفّزة", 80),
        ("إدارة الكلية تمثّل الكلية أمام الجامعة والشركاء بفعالية", 90),
        ("تقييمي الإجمالي لأداء إدارة الكلية ووضوح سياساتها هذا الفصل", 100),
    ],
    "faculty_educational_process": [
        ("معايير إقفال المقررات وتقارير الإقفال واضحة لي", 10),
        ("سياسات الامتحانات والدرجات في القسم عادلة وشفافة", 20),
        ("التقويم ومفردات المقررات متوافقة مع مخرجات البرنامج", 30),
        ("متابعة تحقق مخرجات التعلم في الشعب فعّالة في قسمي", 40),
        ("الجدول الدراسي يلبّي متطلبات المقررات والمعامل", 50),
        ("إجراءات ضمان الجودة والتدقيق الداخلي في القسم فعّالة", 60),
        ("أعرف كيف أطلب الاستثناءات الأكاديمية وكيف تُعالَج", 70),
        ("أدلة التعلم والمنصات الإلكترونية مدعومة ومتاحة", 80),
        ("التدريس والاختبارات والإرشاد الأكاديمي متكاملون في القسم", 90),
        ("تقييمي الإجمالي للعملية التعليمية في قسمي هذا الفصل", 100),
    ],
    "faculty_external_collaborator": [
        ("كان التكليف التدريسي والمهام المتفق عليها واضحة لي منذ البداية", 10),
        ("حصلت على تنسيق كافٍ مع القسم أو منسق المقرر خلال الفصل", 20),
        ("توفرت لي المعلومات اللازمة (جدول، شعب، منصة، قنوات تواصل)", 30),
        ("تلقيت دعماً إدارياً وفنياً مناسباً عند الحاجة", 40),
        ("أستطيع إنجاز مهام التدريس المتفق عليها ضمن الإطار المعطى", 50),
        ("بشكل عام، تجربة التعاون التدريسي مع القسم هذا الفصل كانت مرضية", 60),
    ],
    "staff_workplace": [
        ("وضوح الأدوار والمسؤوليات الوظيفية", 10),
        ("توفر الأنظمة والأدوات اللازمة لإنجاز العمل", 20),
        ("التعاون والتنسيق بين الوحدات الإدارية", 30),
        ("بيئة عمل آمنة ومحترمة وخالية من التمييز", 40),
        ("فرص التطوير المهني والتدريب المستمر", 50),
        ("عدالة سياسات الأداء الوظيفي والحوافز", 60),
        ("توازن معقول بين الأعباء والموارد البشرية", 70),
        ("جودة القيادة الإدارية المباشرة والدعم", 80),
        ("شفافية القرارات الإدارية ذات الصلة بالموظف", 90),
        ("بشكل عام، أنا راضٍ عن بيئة العمل", 100),
    ],
    "supervisor_advising": [
        ("أتابع الطلاب المتعثرين بانتظام خلال الفصل", 10),
        ("أوثّق إجراءات الإرشاد وتواصلي مع الطالب أو ولي الأمر", 20),
        ("لدي خطة تدخل واضحة لكل حالة متعثرة", 30),
        ("أُحيل الحالات المناسبة لشؤون الطلبة أو الدعم النفسي", 40),
        ("أتابع تنفيذ خطط التحسين بعد الرسوب أو الإنذار", 50),
        ("أستخدم بيانات السجل والدرجات في قرارات الإرشاد", 60),
        ("أتعامل بعدالة مع جميع الطلاب المشرف عليهم", 70),
        ("ألتزم بمواعيد لقاءات الإرشاد الفصلي", 80),
        ("أربط الإرشاد بمتطلبات التخرج والخطة الدراسية", 90),
        ("بشكل عام، ممارسات الإرشاد لديّ فعّالة هذا الفصل", 100),
    ],
    "supervisor_coordination": [
        ("أحصل على قرارات واضحة من رئيس القسم في الحالات الأكاديمية", 10),
        ("أعرف إلى من أُصعِّد المشكلة داخل القسم والكلية", 20),
        ("تتعاون شؤون الطلبة معي في الإضافة والإسقاط والاستثناءات", 30),
        ("أشارك تقارير الإرشاد مع لجان الجودة عند الطلب", 40),
        ("أستطيع تطبيق سياسات الحضور والغياب والإنذارات بوضوح", 50),
        ("أتواصل مع أساتذة المقررات عند الحاجة دون تأخير", 60),
        ("أتابع جداول الامتحانات لاتخاذ التدخل في الوقت المناسب", 70),
        ("ألمّ بلوائح الانتقال والمسارات والبرامج ذات الصلة", 80),
        ("أساهم في تحسين مؤشرات نجاح الطلبة في القسم", 90),
        ("بشكل عام، التنسيق المؤسسي للإشراف فعّال هذا الفصل", 100),
    ],
    "employer_strategic": [
        ("وضوح رسالة الكلية وهويتها المهنية لدى قطاعكم", 10),
        ("ملاءمة رؤية الكلية لاحتياجات سوق العمل والتنمية", 20),
        ("ملاءمة الأهداف الاستراتيجية للكلية لأولويات قطاعكم", 30),
        ("ملاءمة مخرجات تعلم الخريج لمتطلبات العمل الفعلية", 40),
        ("أرى أن أولويات الخطة الاستراتيجية للكلية واضحة من منظورنا", 50),
        ("نحن مستعدون للشراكة مع الكلية (تدريب، مشاريع، لقاءات)", 60),
    ],
    "alumni": [
        ("إلى أي مدى كان البرنامج متوازناً بين الجانب النظري والتطبيقي (معامل، مشاريع، تدريب)؟", 10),
        ("إلى أي مدى ساعدتك مشاريع التخرج والمشاريع الدراسية على فهم مسؤوليات العمل الهندسي؟", 20),
        ("عند التخرج، شعرت بجاهزية كافية في المهارات الناعمة (التواصل، العمل الجماعي، إدارة الوقت)", 30),
        ("إلى أي مدى وفرت الكلية إرشاداً كافياً للبحث عن عمل (سيرة ذاتية، مهارات مقابلة)؟", 40),
        ("إلى أي مدى تعكس مخرجات البرنامج التطورات التكنولوجية المطلوبة في سوق العمل؟", 50),
        ("إلى أي مدى طوّر البرنامج قدرتك على حل مشكلات هندسية معقدة؟", 60),
        ("إلى أي مدى عزّز البرنامج التعلم الذاتي لمواكبة التحديثات في تخصصك؟", 70),
        ("إلى أي مدى لاحظت فجوة بين ما تعلمته في البرنامج ومتطلبات وظيفتك الفعلية؟", 80),
        ("لو عاد بك الزمن، إلى أي مدى ستختار دراسة هذا التخصص مرة أخرى؟", 90),
        ("بشكل عام، ما مدى رضاك عن تجربتك الدراسية في الكلية؟", 100),
    ],
    "staff_student_services": [
        ("لدي إجراءات مكتوبة وواضحة لخدمة كل نوع طلب", 10),
        ("بيانات السجل الأكاديمي في النظام دقيقة ومحدّثة", 20),
        ("أستطيع إنجاز المعاملة المعتادة ضمن الوقت المحدد", 30),
        ("لدي الصلاحيات والأدوات لخدمة الطالب دون عوائق", 40),
        ("التنسيق مع الأقسام والكلية سلس عند الحاجة", 50),
        ("معايير الخدمة موحّدة بين موظفي الوحدة", 60),
        ("أستطيع معالجة الحالات الاستثنائية وفق لائحة واضحة", 70),
        ("أعرف إلى من أُصعِّد المشكلة عند التعثر", 80),
        ("أتلقى ملاحظات كافية لتحسين الخدمة", 90),
        ("بشكل عام، أستطيع تقديم خدمة جيدة للطالب", 100),
    ],
}
