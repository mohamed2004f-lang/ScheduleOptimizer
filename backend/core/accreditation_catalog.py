"""
كتالوج معايير الاعتماد المؤسسي (هـ-1) — محاور، معايير، مؤشرات.
يُعبَّى تدريجياً؛ التقييمات تُخزَّن في accreditation_assessments.
"""

from __future__ import annotations

from typing import Any

from backend.database.database import is_postgresql

CATALOG_VERSION = "2026.1"  # أرشيف فقط — ليس طبقة تشغيل يومية
INTERNAL_CATALOG_VERSION = CATALOG_VERSION
QAA_INST_CATALOG_VERSION = "QAA-2023.4-INST"
QAA_PROG_UG_CATALOG_VERSION = "QAA-2023.4-PROG-UG"

DOMAIN_LABELS = {
    "vision_strategy": "الرؤية والرسالة والتخطيط",
    "governance": "الحوكمة والإدارة",
    "human_resources": "الموارد البشرية",
    "facilities_finance": "المرافق والموارد المالية",
    "quality_assurance": "ضمان الجودة وتحسين الأداء",
    "student_services": "الطلبة والخدمات الطلابية",
    "community_research": "المجتمع والبحث",
    # دليل المركز الوطني — إصدار 4 (2023)
    "qaa_mq": "جودة الإدارة (معايير المركز)",
    "qaa_inst": "الاعتماد المؤسسي (معايير المركز)",
    "qaa_prog_ug": "الاعتماد البرامجي — بكالوريوس (معايير المركز)",
}

CATALOG_VERSION_LABELS = {
    CATALOG_VERSION: "كتالوج داخلي (أرشيف — متوقف)",
    QAA_INST_CATALOG_VERSION: "معايير المركز — اعتماد مؤسسي (إصدار 4، 2023)",
    QAA_PROG_UG_CATALOG_VERSION: "معايير المركز — اعتماد برامجي بكالوريوس (إصدار 4، 2023)",
}

# تبويبات التشغيل اليومية — مؤسسي + برامجي فقط (الخيار ب)
ACCREDITATION_MAP_SCOPES: list[dict[str, str]] = [
    {
        "key": "inst",
        "catalog_version": QAA_INST_CATALOG_VERSION,
        "title_ar": "اعتماد مؤسسي",
        "page_title_ar": "خريطة امتثال — اعتماد مؤسسي",
        "nav_label_ar": "امتثال مؤسسي",
        "indicator_hint_ar": "202 مؤشر",
        "org_level": "college",
    },
    {
        "key": "prog",
        "catalog_version": QAA_PROG_UG_CATALOG_VERSION,
        "title_ar": "اعتماد برامجي — بكالوريوس",
        "page_title_ar": "خريطة امتثال — اعتماد برامجي",
        "nav_label_ar": "امتثال برامجي",
        "indicator_hint_ar": "139 مؤشر",
        "org_level": "program",
    },
]

# محفوظ للقراءة الصريحة فقط (لا يظهر في التبويبات)
INTERNAL_MAP_SCOPE: dict[str, str] = {
    "key": "internal",
    "catalog_version": INTERNAL_CATALOG_VERSION,
    "title_ar": "كتالوج داخلي (أرشيف)",
    "page_title_ar": "خريطة امتثال — كتالوج داخلي (أرشيف)",
    "nav_label_ar": "امتثال (أرشيف)",
    "indicator_hint_ar": "15 مؤشر",
    "org_level": "archive",
}


def resolve_map_catalog_scope(
    conn,
    *,
    scope: str | None = None,
    catalog_version: str | None = None,
) -> tuple[str, str]:
    """يُرجع (catalog_version, scope_key) لصفحة خريطة الامتثال."""
    explicit = (catalog_version or "").strip()
    if explicit:
        for item in ACCREDITATION_MAP_SCOPES:
            if item["catalog_version"] == explicit:
                return explicit, item["key"]
        if explicit == INTERNAL_MAP_SCOPE["catalog_version"]:
            return explicit, "internal"
        return explicit, "custom"
    sk = (scope or "").strip().lower()
    for item in ACCREDITATION_MAP_SCOPES:
        if item["key"] == sk:
            return item["catalog_version"], item["key"]
    if sk == "internal":
        return INTERNAL_MAP_SCOPE["catalog_version"], "internal"
    return QAA_INST_CATALOG_VERSION, "inst"


def map_scope_meta(scope_key: str) -> dict[str, str]:
    for item in ACCREDITATION_MAP_SCOPES:
        if item["key"] == scope_key:
            return dict(item)
    if scope_key == "internal":
        return dict(INTERNAL_MAP_SCOPE)
    return dict(ACCREDITATION_MAP_SCOPES[0])


def catalog_scope_label(
    catalog_version: str,
    department_id: int | None = None,
    *,
    program_name_ar: str | None = None,
    org_label_ar: str | None = None,
) -> str:
    """وصف نطاق الكتالوج للواجهة."""
    if org_label_ar:
        ver_label = CATALOG_VERSION_LABELS.get(catalog_version, catalog_version)
        return f"{ver_label} · {org_label_ar}"
    ver_label = CATALOG_VERSION_LABELS.get(catalog_version, catalog_version)
    if catalog_version.startswith("QAA-2023.4-PROG"):
        if program_name_ar:
            scope = f"برنامجي ({program_name_ar})"
        elif department_id is not None:
            scope = f"برنامجي (قسم #{department_id})"
        else:
            scope = "برنامجي (برنامج أكاديمي)"
    elif catalog_version.startswith("QAA-2023.4-INST"):
        scope = "مؤسسي (كلية — جميع الأقسام)"
    elif catalog_version == INTERNAL_CATALOG_VERSION:
        scope = "أرشيف داخلي"
    else:
        scope = "مؤسسي (كلية)" if department_id is None else f"قسم #{department_id}"
    return f"{ver_label} · {scope}"

SOURCE_TYPE_LABELS = {
    "auto": "حساب من النظام",
    "manual": "إدخال يدوي",
    "hybrid": "مختلط (حساب من النظام + مراجعة)",
    "document": "وثيقة / دليل",
    "qaa_center": "مركز ضمان الجودة الليبي",
}

# محاور دليل المركز — للفلترة عبر المؤسسي والبرامجي
QAA_AXIS_OPTIONS: list[dict[str, str]] = [
    {
        "catalog_version": "QAA-2023.4-INST",
        "domain_code": "qaa_mq",
        "label": DOMAIN_LABELS["qaa_mq"],
    },
    {
        "catalog_version": "QAA-2023.4-INST",
        "domain_code": "qaa_inst",
        "label": DOMAIN_LABELS["qaa_inst"],
    },
    {
        "catalog_version": "QAA-2023.4-PROG-UG",
        "domain_code": "qaa_prog_ug",
        "label": DOMAIN_LABELS["qaa_prog_ug"],
    },
]

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
    """إصدارات موجودة في القاعدة (قد تشمل الأرشيف الداخلي)."""
    try:
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT DISTINCT catalog_version FROM accreditation_standards
            WHERE COALESCE(is_active, 1) = 1
            ORDER BY catalog_version
            """
        ).fetchall()
        out = []
        for r in rows or []:
            if hasattr(r, "keys"):
                try:
                    v = r["catalog_version"]
                except (KeyError, IndexError, TypeError):
                    v = r[0] if len(r) else None
            else:
                v = r[0]
            if v:
                out.append(str(v).strip())
        return out
    except Exception:
        return [QAA_INST_CATALOG_VERSION]


def list_operational_catalog_versions(conn) -> list[str]:
    """إصدارات التشغيل فقط — بدون الكتالوج الداخلي 2026.1."""
    preferred = (QAA_INST_CATALOG_VERSION, QAA_PROG_UG_CATALOG_VERSION)
    active = list_active_catalog_versions(conn)
    out = [v for v in preferred if v in active]
    for v in active:
        if v == INTERNAL_CATALOG_VERSION:
            continue
        if v not in out:
            out.append(v)
    if not out:
        out = list(preferred)
    return out


def resolve_catalog_version(conn, explicit: str | None = None) -> str:
    """إصدار الكتالوج النشط — صريح، أو مؤسسي QAA، ثم برامجي، دون تفضيل الأرشيف الداخلي."""
    if (explicit or "").strip():
        return explicit.strip()
    cur = conn.cursor()
    for preferred in (QAA_INST_CATALOG_VERSION, QAA_PROG_UG_CATALOG_VERSION):
        row = cur.execute(
            """
            SELECT 1 FROM accreditation_standards
            WHERE catalog_version = ? AND COALESCE(is_active, 1) = 1
            LIMIT 1
            """,
            (preferred,),
        ).fetchone()
        if row:
            return preferred
    row = cur.execute(
        """
        SELECT catalog_version FROM accreditation_standards
        WHERE COALESCE(is_active, 1) = 1
          AND catalog_version <> ?
        ORDER BY catalog_version DESC
        LIMIT 1
        """,
        (INTERNAL_CATALOG_VERSION,),
    ).fetchone()
    if row:
        try:
            return str(row[0] if not hasattr(row, "keys") else row["catalog_version"])
        except (KeyError, TypeError, IndexError):
            pass
    return QAA_INST_CATALOG_VERSION


def seed_internal_accreditation_catalog(conn) -> dict[str, int]:
    """بذر أرشيفي لكتالوج 2026.1 — للاختبارات أو الاسترجاع الصريح فقط."""
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


def ensure_accreditation_catalog(
    conn,
    *,
    seed_internal: bool = False,
) -> dict[str, int]:
    """
    يضمن كتالوجات التشغيل (QAA مؤسسي + برامجي).
    الخيار ب: لا يُبذر الكتالوج الداخلي افتراضياً (بياناته تبقى إن وُجدت).
    """
    internal_stats: dict[str, int] = {
        "catalog_version": CATALOG_VERSION,
        "standards": 0,
        "indicators": 0,
    }
    if seed_internal:
        internal_stats = seed_internal_accreditation_catalog(conn)

    qaa_stats: dict[str, int] = {}
    try:
        from backend.core.qaa_catalog_seed import ensure_qaa_catalog

        qaa_stats = ensure_qaa_catalog(conn)
    except Exception:
        import logging

        logging.getLogger(__name__).exception("ensure_qaa_catalog failed")

    return {
        "catalog_version": QAA_INST_CATALOG_VERSION,
        "standards": int(internal_stats.get("standards") or 0),
        "indicators": int(internal_stats.get("indicators") or 0),
        "internal_seeded": bool(seed_internal),
        "qaa_catalog": qaa_stats,
    }
