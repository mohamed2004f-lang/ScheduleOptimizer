"""تطبيع أدوار المستخدم."""
from __future__ import annotations

# مرادفات قديمة/يدوية لدور رئيس القسم في قاعدة البيانات
_HEAD_ROLE_ALIASES = frozenset(
    (
        "head",
        "hod",
        "head_of_dept",
        "head_dept",
        "department_head",
        "dept_head",
        "head_of_department_ar",
        "head-of-department",
        "head of department",
        "dept chairman",
        "chairman",
        "رئيس قسم",
        "رئيس_قسم",
        "رئيس-قسم",
    )
)


def _normalize_role(role: str) -> str:
    """تطبيع الأدوار لتوافق الإصدارات السابقة (حالة الأحرف، admin → admin_main، مرادفات رئيس القسم)."""
    r = (role or "").strip()
    if not r:
        return r
    k = r.lower()
    # طبّع الفواصل الشائعة حتى تعمل القيم مثل "head-of-department" و"head of department"
    k_norm = k.replace("-", "_").replace(" ", "_")
    while "__" in k_norm:
        k_norm = k_norm.replace("__", "_")
    if k == "admin":
        return "admin_main"
    if k_norm == "admin":
        return "admin_main"
    if k == "head_of_department" or k_norm == "head_of_department" or k in _HEAD_ROLE_ALIASES or k_norm in _HEAD_ROLE_ALIASES:
        return "head_of_department"
    if k in (
        "instructor", "student", "supervisor", "admin_main", "staff",
        "system_admin", "college_dean", "academic_vice_dean",
    ):
        return k
    if k_norm in (
        "instructor", "student", "supervisor", "admin_main", "staff",
        "system_admin", "college_dean", "academic_vice_dean",
    ):
        return k_norm
    return r
