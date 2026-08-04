"""
حزم دليل الجودة الموحّدة — مصدر واحد للدليل والمساعد وخريطة الجودة الشخصية.

كل حزمة تُعرض فقط إن تطابقت جمهوريتها مع دور المستخدم / الوضع / الأعلام / الصلاحيات.
"""

from __future__ import annotations

from typing import Any

# أدوار قيادة الجودة الرئيسية (حزم مفصّلة)
PRIMARY_QUALITY_ROLES = frozenset(
    {
        "admin_main",
        "system_admin",
        "college_dean",
        "academic_vice_dean",
        "head_of_department",
        "instructor",
        "supervisor",
    }
)

# حزم الدليل/الخريطة — مرتبة للعرض
QUALITY_CONTENT_PACKS: list[dict[str, Any]] = [
    {
        "id": "identity_story_read",
        "tier": "primary",
        "title_ar": "هوية الكلية وبرنامجك (قراءة)",
        "summary_ar": "قصة تعريفية: الرؤية والرسالة والأهداف الجذرية ومخرجات البرنامج — بدون KPI.",
        "href": "/academic_quality/ilo/outcomes-map",
        "page_guide_key": "college_identity_story",
        "roles": (),
        "also_flags": (),
        "active_modes": (),
        "required_any_caps": (
            "nav_instructor_quality_hub",
            "nav_supervisor_portal_menu",
            "nav_academic_quality_dashboard",
            "nav_surveys_results",
            "nav_ilo_catalog",
            "is_instructor_or_supervisor_nav",
        ),
        "deny_caps": (),
        "audience_kind": "primary",
    },
    {
        "id": "identity_workshop_edit",
        "tier": "primary",
        "title_ar": "ورشة تحرير هوية الكلية",
        "summary_ar": "تحرير الرسالة/الرؤية/القيم وشجرة الأهداف وKPI — للعميد والأدمن الرئيسي.",
        "href": "/academic_quality/college",
        "page_guide_key": "college_profile",
        "roles": ("college_dean", "admin_main", "system_admin"),
        "also_flags": (),
        "active_modes": (),
        "required_any_caps": ("can_edit_college_identity", "nav_college_profile"),
        "deny_caps": (),
        "audience_kind": "primary",
    },
    {
        "id": "instructor_quality_hub",
        "tier": "primary",
        "title_ar": "بوابة جودة الأستاذ",
        "summary_ar": "تعبئة استبياناتك، قصة الهوية، وروابط CLO دون قائمة ضمان الجودة الإدارية.",
        "href": "/academic_quality/instructor/quality-hub",
        "page_guide_key": "instructor_quality_hub",
        "roles": ("instructor", "head_of_department", "college_dean", "academic_vice_dean"),
        "also_flags": (),
        "active_modes": ("instructor",),
        "required_any_caps": ("nav_instructor_quality_hub", "nav_instructor_portal_menu"),
        "deny_caps": (),
        "audience_kind": "primary",
    },
    {
        "id": "supervisor_quality_slim",
        "tier": "primary",
        "title_ar": "جودة وضع المشرف",
        "summary_ar": "لوحة إشراف + تعبئة استبيانات دورية + هوية الكلية قراءة — بلا قائمة جودة إدارية.",
        "href": "/academic_quality/supervisor/quality-hub",
        "page_guide_key": "supervisor_quality_slim",
        "roles": ("supervisor", "instructor", "head_of_department", "college_dean", "academic_vice_dean"),
        "also_flags": (),
        "active_modes": ("supervisor",),
        "required_any_caps": ("nav_supervisor_portal_menu", "nav_supervisor_dashboard"),
        "deny_caps": (),
        "audience_kind": "primary",
    },
    {
        "id": "surveys_fill",
        "tier": "primary",
        "title_ar": "تعبئة الاستبيانات",
        "summary_ar": "الاستبيانات المطلوبة حسب وضعك الحالي (طالب / أستاذ / مشرف / موظف).",
        "href": "/academic_quality/surveys",
        "page_guide_key": "survey_hub",
        "roles": (),
        "also_flags": (),
        "active_modes": (),
        "required_any_caps": ("nav_surveys_hub",),
        "deny_caps": (),
        "audience_kind": "primary",
    },
    {
        "id": "surveys_results",
        "tier": "primary",
        "title_ar": "نتائج الاستبيانات",
        "summary_ar": "نتائج داخلية وخارجية. الخارجي حسب القسم لرئيس القسم، وفلتر للكلية للقيادة.",
        "href": "/academic_quality/surveys/results",
        "page_guide_key": "survey_results",
        "roles": (
            "admin",
            "admin_main",
            "system_admin",
            "college_dean",
            "academic_vice_dean",
            "head_of_department",
        ),
        "also_flags": ("is_college_quality_lead",),
        "active_modes": (),
        "required_any_caps": ("nav_surveys_results",),
        "deny_caps": (),
        "audience_kind": "primary",
    },
    {
        "id": "surveys_external_invites",
        "tier": "primary",
        "title_ar": "دعوات الاستبيانات الخارجية",
        "summary_ar": "إنشاء روابط الحملات للخريجين وجهات العمل — عميد وأدمن رئيسي فقط.",
        "href": "/academic_quality/surveys/invites",
        "page_guide_key": "survey_invites",
        "roles": ("admin_main", "system_admin", "college_dean"),
        "also_flags": (),
        "active_modes": (),
        "required_any_caps": ("can_manage_survey_invites", "nav_surveys_invites"),
        "deny_caps": (),
        "audience_kind": "primary",
    },
    {
        "id": "quality_dashboard",
        "tier": "primary",
        "title_ar": "لوحة الجودة",
        "summary_ar": "مؤشرات تشغيلية ومسارات العمل — ليست درجة اعتماد رسمية.",
        "href": "/academic_quality/dashboard",
        "page_guide_key": "academic_quality_dashboard",
        "roles": (
            "admin",
            "admin_main",
            "system_admin",
            "college_dean",
            "academic_vice_dean",
            "head_of_department",
        ),
        "also_flags": ("is_college_quality_lead",),
        "active_modes": (),
        "required_any_caps": ("nav_academic_quality_dashboard",),
        "deny_caps": (),
        "audience_kind": "primary",
    },
    {
        "id": "accreditation_inst",
        "tier": "primary",
        "title_ar": "امتثال مؤسسي",
        "summary_ar": "خريطة QAA-INST والشواهد — ربط يدوي بعد الاقتراح.",
        "href": "/academic_quality/accreditation/map?scope=inst",
        "page_guide_key": "accreditation_map",
        "roles": (
            "admin_main",
            "system_admin",
            "college_dean",
            "academic_vice_dean",
            "head_of_department",
        ),
        "also_flags": ("is_college_quality_lead",),
        "active_modes": (),
        "required_any_caps": ("nav_academic_quality_dashboard", "can_edit_accreditation_catalog"),
        "deny_caps": (),
        "audience_kind": "primary",
    },
    {
        "id": "accreditation_prog",
        "tier": "primary",
        "title_ar": "امتثال برامجي",
        "summary_ar": "خريطة PROG-UG لقسمك/برنامجك مع الشواهد.",
        "href": "/academic_quality/accreditation/map?scope=prog",
        "page_guide_key": "accreditation_map",
        "roles": (
            "admin_main",
            "system_admin",
            "college_dean",
            "academic_vice_dean",
            "head_of_department",
        ),
        "also_flags": ("is_college_quality_lead", "is_dept_quality_coordinator"),
        "active_modes": (),
        "required_any_caps": ("nav_academic_quality_dashboard",),
        "deny_caps": (),
        "audience_kind": "primary",
    },
    {
        "id": "department_archive",
        "tier": "primary",
        "title_ar": "أرشيف القسم",
        "summary_ar": "محاضر وقرارات ومراسلات كشواهد تشغيلية.",
        "href": "/academic_quality/archive",
        "page_guide_key": "department_archive",
        "roles": (
            "admin_main",
            "system_admin",
            "college_dean",
            "academic_vice_dean",
            "head_of_department",
        ),
        "also_flags": ("is_dept_quality_coordinator", "is_college_quality_lead"),
        "active_modes": (),
        "required_any_caps": ("nav_academic_quality_dashboard",),
        "deny_caps": (),
        "audience_kind": "primary",
    },
    {
        "id": "college_archive",
        "tier": "primary",
        "title_ar": "أرشيف الكلية",
        "summary_ar": "خزائن العميد والوكيل ورئيس قسم جودة بالكلية + السجل المشترك والمشاركة.",
        "href": "/academic_quality/college-archive",
        "page_guide_key": "college_archive",
        "roles": (
            "admin_main",
            "system_admin",
            "college_dean",
            "academic_vice_dean",
        ),
        "also_flags": ("is_college_quality_lead",),
        "active_modes": (),
        "required_any_caps": ("nav_college_archive",),
        "deny_caps": (),
        "audience_kind": "primary",
    },
    {
        "id": "quality_assistant",
        "tier": "supporting",
        "title_ar": "المساعد الذكي",
        "summary_ar": "اقتراحات حسب دورك وقسمك — لا يعتمد امتثالاً تلقائياً.",
        "href": "/academic_quality/assistant",
        "page_guide_key": "quality_assistant",
        "roles": (),
        "also_flags": (),
        "active_modes": (),
        "required_any_caps": ("nav_quality_assistant",),
        "deny_caps": (),
        "audience_kind": "supporting",
    },
    {
        "id": "dept_quality_coordinator",
        "tier": "supporting",
        "title_ar": "منسق جودة القسم",
        "summary_ar": "مسارك المختصر: أرشيف القسم + PROG + نتائج قسمك.",
        "href": "/academic_quality/archive",
        "page_guide_key": "department_archive",
        "roles": (),
        "also_flags": ("is_dept_quality_coordinator",),
        "active_modes": (),
        "required_any_caps": (),
        "deny_caps": (),
        "audience_kind": "supporting",
    },
    {
        "id": "college_quality_lead",
        "tier": "supporting",
        "title_ar": "رئيس ضمان الجودة بالكلية",
        "summary_ar": "مسار تشغيلي: نتائج، امتثال، معرفة — بدون إنشاء دعوات خارجية ما لم تُمنح صلاحية.",
        "href": "/academic_quality/dashboard",
        "page_guide_key": "academic_quality_dashboard",
        "roles": (),
        "also_flags": ("is_college_quality_lead",),
        "active_modes": (),
        "required_any_caps": (),
        "deny_caps": (),
        "audience_kind": "supporting",
    },
]


def _truthy_cap(caps: dict[str, Any] | None, key: str) -> bool:
    if not caps:
        return False
    return bool(caps.get(key))


def pack_matches_audience(
    pack: dict[str, Any],
    *,
    role: str,
    active_mode: str | None,
    caps: dict[str, Any] | None,
    is_college_quality_lead: bool = False,
    is_dept_quality_coordinator: bool = False,
) -> bool:
    """هل تُعرض الحزمة لهذا المستخدم؟"""
    role_n = (role or "").strip().lower()
    am = (active_mode or "").strip().lower()
    roles = tuple(pack.get("roles") or ())
    flags = tuple(pack.get("also_flags") or ())
    modes = tuple(pack.get("active_modes") or ())
    req_any = tuple(pack.get("required_any_caps") or ())
    deny = tuple(pack.get("deny_caps") or ())

    for d in deny:
        if _truthy_cap(caps, d):
            return False

    role_ok = (not roles) or (role_n in roles)
    flag_ok = False
    if "is_college_quality_lead" in flags and is_college_quality_lead:
        flag_ok = True
    if "is_dept_quality_coordinator" in flags and is_dept_quality_coordinator:
        flag_ok = True
    if not roles and not flags:
        audience_ok = True
    else:
        audience_ok = role_ok or flag_ok

    if not audience_ok:
        return False

    if modes and am and am not in modes:
        # إن وُجدت أوضاع مطلوبة ولم يطابق الوضع النشط — استثنِ إلا إن الدور الأصلي هو المشرف للحزمة
        if pack.get("id") == "supervisor_quality_slim" and role_n == "supervisor":
            pass
        elif pack.get("id") == "instructor_quality_hub" and role_n == "instructor" and am != "supervisor":
            pass
        else:
            return False

    if req_any:
        if not any(_truthy_cap(caps, k) for k in req_any):
            # أعلام الجودة قد تمنح نتائج/لوحة دون قدرات كاملة في caps للـ staff
            if pack.get("id") in ("surveys_results", "quality_dashboard", "college_quality_lead") and is_college_quality_lead:
                return True
            if pack.get("id") in ("dept_quality_coordinator", "accreditation_prog", "department_archive") and is_dept_quality_coordinator:
                return True
            return False

    return True


def filter_packs_for_user(
    *,
    role: str,
    active_mode: str | None = None,
    caps: dict[str, Any] | None = None,
    is_college_quality_lead: bool = False,
    is_dept_quality_coordinator: bool = False,
    packs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    src = packs if packs is not None else QUALITY_CONTENT_PACKS
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in src:
        if not pack_matches_audience(
            p,
            role=role,
            active_mode=active_mode,
            caps=caps,
            is_college_quality_lead=is_college_quality_lead,
            is_dept_quality_coordinator=is_dept_quality_coordinator,
        ):
            continue
        pid = str(p.get("id") or "")
        if pid in seen:
            continue
        seen.add(pid)
        out.append(
            {
                "id": pid,
                "tier": p.get("tier") or "primary",
                "audience_kind": p.get("audience_kind") or "primary",
                "title_ar": p.get("title_ar"),
                "summary_ar": p.get("summary_ar"),
                "href": p.get("href"),
                "page_guide_key": p.get("page_guide_key"),
            }
        )
    return out


def guide_audience_payload(
    *,
    role: str,
    active_mode: str | None = None,
    caps: dict[str, Any] | None = None,
    is_college_quality_lead: bool = False,
    is_dept_quality_coordinator: bool = False,
    department_label: str | None = None,
    department_id: int | None = None,
    dept_scope_locked: bool = False,
) -> dict[str, Any]:
    """حمولة جاهزة لمحرّك الدليل + خريطة الجودة الشخصية."""
    packs = filter_packs_for_user(
        role=role,
        active_mode=active_mode,
        caps=caps,
        is_college_quality_lead=is_college_quality_lead,
        is_dept_quality_coordinator=is_dept_quality_coordinator,
    )
    primary = [p for p in packs if p.get("audience_kind") != "supporting"]
    supporting = [p for p in packs if p.get("audience_kind") == "supporting"]
    guide_keys = sorted(
        {str(p.get("page_guide_key") or "") for p in packs if p.get("page_guide_key")}
    )
    is_primary_role = (role or "").strip().lower() in PRIMARY_QUALITY_ROLES or is_college_quality_lead
    return {
        "v": 1,
        "role": (role or "").strip().lower(),
        "active_mode": (active_mode or "").strip().lower() or None,
        "is_college_quality_lead": bool(is_college_quality_lead),
        "is_dept_quality_coordinator": bool(is_dept_quality_coordinator),
        "is_primary_quality_audience": bool(is_primary_role),
        "department_id": int(department_id) if department_id is not None else None,
        "department_label": department_label,
        "dept_scope_locked": bool(dept_scope_locked),
        "capabilities": {
            k: bool(v)
            for k, v in (caps or {}).items()
            if isinstance(k, str) and (k.startswith("nav_") or k.startswith("can_") or k.startswith("is_"))
        },
        "packs": packs,
        "primary_packs": primary,
        "supporting_packs": supporting,
        "allowed_guide_keys": guide_keys,
        "maintenance_note_ar": (
            "بعد أي تغيير في حوكمة الجودة: حدّث QUALITY_CONTENT_PACKS "
            "وجولات guide-catalog المرتبطة ثم أعد اختبار جمهور كل دور."
        ),
    }


def system_usage_topics_with_guide_keys() -> list[dict[str, Any]]:
    """مواضيع مساعدة المنظومة مع ربط اختياري لمفتاح PageGuide."""
    from backend.core.quality_assistant_catalog import SYSTEM_USAGE_TOPICS

    key_by_code = {
        "assistant_chat": "quality_assistant",
        "knowledge_library": "quality_knowledge",
        "quality_dashboard": "academic_quality_dashboard",
        "accreditation_map": "accreditation_map",
        "department_archive": "department_archive",
        "college_archive": "college_archive",
        "surveys": "survey_hub",
        "outcomes_clo": "ilo_catalog",
    }
    out: list[dict[str, Any]] = []
    for t in SYSTEM_USAGE_TOPICS:
        item = dict(t)
        code = str(item.get("code") or "")
        if "page_guide_key" not in item and code in key_by_code:
            item["page_guide_key"] = key_by_code[code]
        # تحديث نص الاستبيانات ليعكس فصل الدعوات
        if code == "surveys":
            item["steps_ar"] = [
                "تعبئة الاستبيانات من مركز التعبئة حسب وضعك الحالي.",
                "النتائج المجمّعة لقيادة الكلية/القسم ورئيس جودة الكلية.",
                "إنشاء دعوات خارجية (خريجون/قطاع) للعميد والأدمن الرئيسي فقط.",
                "للاعتماد: اربط الشاهد يدوياً بعد مراجعة اللجنة.",
            ]
            item["links"] = [
                {"href": "/academic_quality/surveys", "label_ar": "تعبئة الاستبيانات"},
                {"href": "/academic_quality/surveys/results", "label_ar": "نتائج مجمّعة"},
                {"href": "/academic_quality/surveys/invites", "label_ar": "دعوات خارجية (مخوّلون)"},
            ]
        out.append(item)
    return out
