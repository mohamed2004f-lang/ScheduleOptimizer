"""
كتالوج معايير الاعتماد المؤسسي (هـ-1) — محاور، معايير، مؤشرات.
يُعبَّى تدريجياً؛ التقييمات تُخزَّن في accreditation_assessments.
"""

from __future__ import annotations

from typing import Any

from backend.database.database import is_postgresql

CATALOG_VERSION = "2026.1"

DOMAIN_LABELS = {
    "vision_strategy": "الرؤية والرسالة والتخطيط",
    "governance": "الحوكمة والإدارة",
    "human_resources": "الموارد البشرية",
    "facilities_finance": "المرافق والموارد المالية",
    "quality_assurance": "ضمان الجودة وتحسين الأداء",
    "student_services": "الطلبة والخدمات الطلابية",
    "community_research": "المجتمع والبحث",
}

SOURCE_TYPE_LABELS = {
    "auto": "آلي من النظام",
    "manual": "إدخال يدوي",
    "hybrid": "مختلط (آلي + مراجعة)",
    "document": "وثيقة / دليل",
}

COMPLIANCE_STATUS_LABELS = {
    "not_started": "لم يبدأ",
    "in_progress": "قيد التنفيذ",
    "partial": "جزئي",
    "met": "متحقق",
    "gap": "فجوة",
}

# (domain, standard_code, standard_title, standard_desc, weight, indicator_code, indicator_title, source_type, target_hint)
DEFAULT_ACCREDITATION_SEED: list[tuple] = [
    (
        "vision_strategy",
        "VS-01",
        "وضوح الرؤية والرسالة",
        "وجود رؤية ورسالة معتمدة ومنشورة للكلية.",
        8,
        "VS-01-1",
        "اعتماد وثيقة الرؤية والرسالة",
        "document",
        "وثيقة معتمدة خلال آخر 3 سنوات",
    ),
    (
        "vision_strategy",
        "VS-02",
        "الخطة الاستراتيجية",
        "خطة استراتيجية للكلية مع مؤشرات متابعة.",
        7,
        "VS-02-1",
        "خطة استراتيجية سارية",
        "document",
        "خطة معتمدة + مؤشرات قابلة للقياس",
    ),
    (
        "governance",
        "GV-01",
        "هياكل الحوكمة",
        "وضوح لجان الحوكمة ومهامها.",
        10,
        "GV-01-1",
        "لجان الحوكمة النشطة",
        "manual",
        "محاضر اجتماعات ربع سنوية على الأقل",
    ),
    (
        "governance",
        "GV-02",
        "سياسات الأقسام",
        "سياسات معتمدة وقابلة للتدقيق.",
        8,
        "GV-02-1",
        "نسبة السياسات المعتمدة",
        "hybrid",
        "سياسات department_policies المعتمدة",
    ),
    (
        "human_resources",
        "HR-01",
        "مؤهلات هيئة التدريس",
        "نسبة أعضاء هيئة التدريس ذوي المؤهلات العليا.",
        12,
        "HR-01-1",
        "نسبة المؤهلات العليا",
        "auto",
        "من بيانات instructors — هدف ≥ 70%",
    ),
    (
        "human_resources",
        "HR-02",
        "الحمل التدريسي",
        "توازن نسبة الطلبة إلى أعضاء هيئة التدريس.",
        8,
        "HR-02-1",
        "نسبة طالب : أستاذ",
        "auto",
        "من students و instructors النشطين",
    ),
    (
        "facilities_finance",
        "FF-01",
        "البنية التحتية",
        "ملاءمة المرافق والمختبرات.",
        10,
        "FF-01-1",
        "تقييم البنية التحتية",
        "manual",
        "إدخال دوري في لوحة الجودة (%)",
    ),
    (
        "facilities_finance",
        "FF-02",
        "الموارد المالية",
        "شفافية تخصيص موارد التعليم.",
        7,
        "FF-02-1",
        "خطة مالية للتعليم",
        "document",
        "تقرير مالي سنوي معتمد",
    ),
    (
        "quality_assurance",
        "QA-01",
        "نظام ضمان الجودة",
        "وجود نظام فعال لمراقبة الجودة.",
        15,
        "QA-01-1",
        "لقطات مؤشرات الجودة",
        "auto",
        "quality_metrics_snapshots دورية",
    ),
    (
        "quality_assurance",
        "QA-02",
        "تقارير إقفال المقررات",
        "اكتمال تقارير الإقفال للشعب.",
        10,
        "QA-02-1",
        "نسبة اكتمال تقارير الإقفال",
        "auto",
        "من course_closure_reports",
    ),
    (
        "quality_assurance",
        "QA-03",
        "مخرجات التعلم",
        "ربط المقررات بمخرجات البرنامج وتقييمها.",
        10,
        "QA-03-1",
        "متوسط تحقق مخرجات التعلم",
        "auto",
        "من section_ilo_assessments / إقفال",
    ),
    (
        "student_services",
        "SS-01",
        "رضا الطلبة",
        "قياس رضا الطلبة عن التعليم.",
        8,
        "SS-01-1",
        "رضا الطلبة (استبيان المقرر)",
        "auto",
        "من course_evaluations",
    ),
    (
        "student_services",
        "SS-02",
        "الاحتفاظ والتخرج",
        "مؤشرات الاحتفاظ والتقدم الأكاديمي.",
        7,
        "SS-02-1",
        "معدل التخرج التقريبي",
        "auto",
        "من enrollment_status للطلاب",
    ),
    (
        "community_research",
        "CR-01",
        "الشراكة المجتمعية",
        "أنشطة خدمة المجتمع والشراكات.",
        5,
        "CR-01-1",
        "عدد الأنشطة المجتمعية",
        "manual",
        "سجل أنشطة سنوي",
    ),
    (
        "community_research",
        "CR-02",
        "البحث العلمي",
        "مخرجات بحثية لأعضاء هيئة التدريس.",
        5,
        "CR-02-1",
        "عدد المخرجات البحثية",
        "manual",
        "قائمة منشورات/مشاريع سنوية",
    ),
]


def _row_id(row: Any) -> int | None:
    if row is None:
        return None
    try:
        return int(row[0])
    except (TypeError, IndexError, KeyError):
        pass
    if hasattr(row, "keys"):
        v = row.get("id")
        return int(v) if v is not None else None
    return None


def list_active_catalog_versions(conn) -> list[str]:
    """إصدارات الكتالوج النشطة (للقائمة المنسدلة)."""
    cur = conn.cursor()
    try:
        rows = cur.execute(
            """
            SELECT DISTINCT catalog_version FROM accreditation_standards
            WHERE COALESCE(is_active, 1) = 1
            ORDER BY catalog_version DESC
            """
        ).fetchall()
        out = []
        for r in rows or []:
            v = r[0] if not hasattr(r, "keys") else r.get("catalog_version")
            if v:
                out.append(str(v).strip())
        return out
    except Exception:
        return [CATALOG_VERSION]


def resolve_catalog_version(conn, explicit: str | None = None) -> str:
    """إصدار الكتالوج النشط — صريح، أو الإصدار الافتراضي إن كان نشطاً، وإلا الأحدث."""
    if (explicit or "").strip():
        return explicit.strip()
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT 1 FROM accreditation_standards
        WHERE catalog_version = ? AND COALESCE(is_active, 1) = 1
        LIMIT 1
        """,
        (CATALOG_VERSION,),
    ).fetchone()
    if row:
        return CATALOG_VERSION
    row = cur.execute(
        """
        SELECT catalog_version FROM accreditation_standards
        WHERE COALESCE(is_active, 1) = 1
        ORDER BY catalog_version DESC
        LIMIT 1
        """
    ).fetchone()
    if row:
        try:
            return str(row[0] if not hasattr(row, "keys") else row["catalog_version"])
        except (KeyError, TypeError, IndexError):
            pass
    return CATALOG_VERSION


def ensure_accreditation_catalog(conn) -> dict[str, int]:
    """إدراج المعايير والمؤشرات الافتراضية إن لم تكن موجودة."""
    cur = conn.cursor()
    standards_upserted = 0
    indicators_upserted = 0
    pg = is_postgresql()

    for (
        domain,
        std_code,
        std_title,
        std_desc,
        weight,
        ind_code,
        ind_title,
        source_type,
        target_hint,
    ) in DEFAULT_ACCREDITATION_SEED:
        if pg:
            cur.execute(
                """
                INSERT INTO accreditation_standards
                (catalog_version, domain_code, code, title_ar, description, weight_percent, sort_order, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 0, 1)
                ON CONFLICT (catalog_version, code) DO UPDATE SET
                    title_ar = EXCLUDED.title_ar,
                    description = EXCLUDED.description,
                    weight_percent = EXCLUDED.weight_percent,
                    domain_code = EXCLUDED.domain_code
                RETURNING id
                """,
                (CATALOG_VERSION, domain, std_code, std_title, std_desc, float(weight)),
            )
            row = cur.fetchone()
            std_id = _row_id(row)
            if std_id is None:
                cur.execute(
                    "SELECT id FROM accreditation_standards WHERE catalog_version = ? AND code = ?",
                    (CATALOG_VERSION, std_code),
                )
                std_id = _row_id(cur.fetchone())
        else:
            cur.execute(
                """
                INSERT OR IGNORE INTO accreditation_standards
                (catalog_version, domain_code, code, title_ar, description, weight_percent, sort_order, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 0, 1)
                """,
                (CATALOG_VERSION, domain, std_code, std_title, std_desc, float(weight)),
            )
            cur.execute(
                "SELECT id FROM accreditation_standards WHERE catalog_version = ? AND code = ?",
                (CATALOG_VERSION, std_code),
            )
            std_id = _row_id(cur.fetchone())
        if not std_id:
            continue
        standards_upserted += 1

        if pg:
            cur.execute(
                """
                INSERT INTO accreditation_indicators
                (standard_id, code, title_ar, source_type, target_hint_ar, sort_order, is_active)
                VALUES (?, ?, ?, ?, ?, 0, 1)
                ON CONFLICT (standard_id, code) DO UPDATE SET
                    title_ar = EXCLUDED.title_ar,
                    source_type = EXCLUDED.source_type,
                    target_hint_ar = EXCLUDED.target_hint_ar
                """,
                (int(std_id), ind_code, ind_title, source_type, target_hint),
            )
        else:
            cur.execute(
                """
                INSERT OR IGNORE INTO accreditation_indicators
                (standard_id, code, title_ar, source_type, target_hint_ar, sort_order, is_active)
                VALUES (?, ?, ?, ?, ?, 0, 1)
                """,
                (int(std_id), ind_code, ind_title, source_type, target_hint),
            )
        indicators_upserted += 1

    conn.commit()
    return {
        "catalog_version": CATALOG_VERSION,
        "standards": standards_upserted,
        "indicators": indicators_upserted,
    }
