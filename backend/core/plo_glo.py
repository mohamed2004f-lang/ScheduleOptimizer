"""مخرجات الخريج على مستوى الكلية (GLO) — قاعدة بيانات + بذرة افتراضية."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# بذرة افتراضية — تُستورد إلى college_graduate_outcomes عند أول تشغيل
ENGINEERING_COLLEGE_GLO: tuple[dict[str, Any], ...] = (
    {
        "code": "GLO1",
        "title_ar": "المعرفة الهندسية",
        "title_en": "Engineering Knowledge",
        "domain": "program_knowledge",
        "description": "تطبيق المعرفة الرياضية والعلوم الأساسية والهندسية في حل المشكلات الهندسية.",
    },
    {
        "code": "GLO2",
        "title_ar": "تحليل المشكلات",
        "title_en": "Problem Analysis",
        "domain": "technical_skills",
        "description": "تحديد وصياغة وتحليل المشكلات الهندسية المعقدة باستخدام مبادئ الهندسة والرياضيات.",
    },
    {
        "code": "GLO3",
        "title_ar": "التصميم والتطوير",
        "title_en": "Design & Development",
        "domain": "technical_skills",
        "description": "تصميم مكونات أو أنظمة أو عمليات لتلبية متطلبات محددة مع مراعاة القيود.",
    },
    {
        "code": "GLO4",
        "title_ar": "التحقيق والتجريب",
        "title_en": "Investigation",
        "domain": "technical_skills",
        "description": "تصميم وتنفيذ تجارب وتحليل البيانات وتفسير النتائج لاستخلاص استنتاجات صالحة.",
    },
    {
        "code": "GLO5",
        "title_ar": "الأدوات الحديثة",
        "title_en": "Modern Tools",
        "domain": "technical_skills",
        "description": "استخدام تقنيات وأدوات ومهارات حديثة — بما فيها الحوسبة — في الممارسة الهندسية.",
    },
    {
        "code": "GLO6",
        "title_ar": "المهندس والمجتمع",
        "title_en": "Engineer & Society",
        "domain": "social_responsibility",
        "description": "تقييم الآثار الاجتماعية والصحية والأمنية والثقافية للحلول الهندسية.",
    },
    {
        "code": "GLO7",
        "title_ar": "البيئة والاستدامة",
        "title_en": "Environment & Sustainability",
        "domain": "environmental_values",
        "description": "فهم تأثير الحلول الهندسية في السياقات البيئية والاجتماعية والاقتصادية المستدامة.",
    },
    {
        "code": "GLO8",
        "title_ar": "الأخلاقيات والمسؤولية المهنية",
        "title_en": "Ethics & Professionalism",
        "domain": "ethical_values",
        "description": "الالتزام بأخلاقيات المهنة ومسؤوليات الممارسة الهندسية ومعايير الجودة.",
    },
)

# مجالات مخرجات الخريج (GLO) ومخرجات البرنامج (PLO) — عمود domain واحد
DOMAIN_LABELS_AR: dict[str, str] = {
    "program_knowledge": "معرفة البرنامج",
    "technical_skills": "مهارات تقنية",
    "general_skills": "مهارات عامة",
    "values_orientation": "قيم / اتجاهات",
    "ethical_values": "قيم أخلاقية",
    "social_responsibility": "مسؤولية اجتماعية",
    "environmental_values": "قيم بيئية",
}

DOMAIN_ORDER: tuple[str, ...] = tuple(DOMAIN_LABELS_AR.keys())

DOMAIN_COLORS: dict[str, str] = {
    "program_knowledge": "#6f42c1",
    "technical_skills": "#0d6efd",
    "general_skills": "#20c997",
    "values_orientation": "#fd7e14",
    "ethical_values": "#dc3545",
    "social_responsibility": "#d63384",
    "environmental_values": "#198754",
}

LEGACY_DOMAIN_MAP: dict[str, str] = {
    "knowledge": "program_knowledge",
    "skills": "technical_skills",
    "professional": "social_responsibility",
    "values": "ethical_values",
}

GLO_CODE_DOMAIN: dict[str, str] = {
    "GLO1": "program_knowledge",
    "GLO2": "technical_skills",
    "GLO3": "technical_skills",
    "GLO4": "technical_skills",
    "GLO5": "technical_skills",
    "GLO6": "social_responsibility",
    "GLO7": "environmental_values",
    "GLO8": "ethical_values",
    "GLO9": "general_skills",
    "GLO10": "general_skills",
}

VALID_GLO_DOMAINS = frozenset(DOMAIN_LABELS_AR.keys())
VALID_PLO_DOMAINS = VALID_GLO_DOMAINS
DEFAULT_OUTCOME_DOMAIN = "technical_skills"


def normalize_outcome_domain(raw: str | None, *, glo_code: str | None = None) -> str:
    """توحيد domain القديمة إلى المجالات السبعة (بدون ربط CLO↔GLO مباشر)."""
    key = (raw or "").strip().lower()
    if glo_code:
        gc = (glo_code or "").strip().upper()
        mapped = GLO_CODE_DOMAIN.get(gc)
        if mapped:
            return mapped
    if key in VALID_GLO_DOMAINS:
        return key
    if key in LEGACY_DOMAIN_MAP:
        return LEGACY_DOMAIN_MAP[key]
    return DEFAULT_OUTCOME_DOMAIN


def outcome_domains_payload() -> dict[str, Any]:
    return {
        "labels": dict(DOMAIN_LABELS_AR),
        "order": list(DOMAIN_ORDER),
        "colors": dict(DOMAIN_COLORS),
        "default": DEFAULT_OUTCOME_DOMAIN,
    }


def migrate_outcome_domains(conn) -> dict[str, int]:
    """ترحيل domain في GLO و PLO من التصنيف القديم (4 مجالات) إلى السبعة."""
    cur = conn.cursor()
    stats = {"glo": 0, "plo": 0}
    try:
        rows = cur.execute(
            "SELECT id, code, COALESCE(domain,'') AS domain FROM college_graduate_outcomes"
        ).fetchall()
        for r in rows or []:
            rid = int(r[0] if not hasattr(r, "keys") else r["id"])
            code = r[1] if not hasattr(r, "keys") else r["code"]
            old = r[2] if not hasattr(r, "keys") else r["domain"]
            new = normalize_outcome_domain(old, glo_code=str(code or ""))
            expected = GLO_CODE_DOMAIN.get(str(code or "").strip().upper())
            if expected and new != expected:
                new = expected
            if new != (old or "").strip().lower():
                cur.execute(
                    "UPDATE college_graduate_outcomes SET domain = ? WHERE id = ?",
                    (new, rid),
                )
                stats["glo"] += 1
    except Exception as e:
        logger.debug("migrate glo domains: %s", e)
    try:
        rows = cur.execute(
            """
            SELECT id, COALESCE(domain,'') AS domain,
                   COALESCE(parent_glo_code,'') AS parent_glo_code
            FROM program_learning_outcomes
            """
        ).fetchall()
        for r in rows or []:
            if hasattr(r, "keys"):
                rid = int(r["id"])
                old = r["domain"]
                pglo = r["parent_glo_code"]
            else:
                rid, old, pglo = int(r[0]), r[1], r[2]
            new = normalize_outcome_domain(old, glo_code=pglo)
            if new != (old or "").strip().lower():
                cur.execute(
                    "UPDATE program_learning_outcomes SET domain = ? WHERE id = ?",
                    (new, rid),
                )
                stats["plo"] += 1
    except Exception as e:
        logger.debug("migrate plo domains: %s", e)
    try:
        conn.commit()
    except Exception:
        pass
    return stats

BLOOM_LABELS_AR = {
    "remember": "تذكر",
    "understand": "فهم",
    "apply": "تطبيق",
    "analyze": "تحليل",
    "evaluate": "تقييم",
    "create": "إبداع",
}

GOVERNANCE_LABELS_AR = {
    "draft": "مسودة",
    "approved": "معتمد",
    "retired": "موقوف",
}

COVERAGE_LABELS_AR = {
    "": "—",
    "I": "تقديم (I)",
    "R": "تعميق (R)",
    "M": "إتقان/تقييم (M)",
}

COVERAGE_CYCLE = ("", "I", "R", "M")


def next_coverage_level(current: str | None) -> str:
    cur = (current or "").strip().upper()
    if cur not in COVERAGE_CYCLE:
        return "I"
    idx = COVERAGE_CYCLE.index(cur)
    return COVERAGE_CYCLE[(idx + 1) % len(COVERAGE_CYCLE)]


def _row_to_glo(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return dict(row)
    return {
        "id": row[0],
        "code": row[1],
        "title_ar": row[2],
        "title_en": row[3],
        "description": row[4],
        "domain": row[5],
        "sort_order": row[6],
        "governance_status": row[7],
        "is_active": row[8],
    }


GLO_SELECT = """
    id, code, title_ar, COALESCE(title_en,'') AS title_en,
    COALESCE(description,'') AS description,
    COALESCE(domain,'skills') AS domain,
    sort_order, COALESCE(governance_status,'approved') AS governance_status,
    is_active
"""


def seed_college_glo_defaults(conn) -> int:
    """إدخال GLO الافتراضية إذا كان الجدول فارغاً."""
    cur = conn.cursor()
    try:
        row = cur.execute(
            "SELECT COUNT(*) FROM college_graduate_outcomes"
        ).fetchone()
        if row is None:
            n = 0
        elif hasattr(row, "__getitem__"):
            n = int(row[0])
        else:
            n = 0
    except Exception:
        return 0
    if n > 0:
        return 0
    inserted = 0
    for i, g in enumerate(ENGINEERING_COLLEGE_GLO):
        code = (g.get("code") or "").strip()
        if not code:
            continue
        cur.execute(
            """
            INSERT INTO college_graduate_outcomes (
                code, title_ar, title_en, description, domain,
                sort_order, governance_status, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, 'approved', 1)
            """,
            (
                code,
                g.get("title_ar") or code,
                g.get("title_en") or "",
                g.get("description") or "",
                normalize_outcome_domain(g.get("domain"), glo_code=code),
                (i + 1) * 10,
            ),
        )
        inserted += 1
    return inserted


def _fetch_glo_rows(conn, *, active_only: bool) -> list[dict[str, Any]]:
    cur = conn.cursor()
    sql = f"""
        SELECT {GLO_SELECT}
        FROM college_graduate_outcomes
        WHERE 1=1
    """
    if active_only:
        sql += " AND COALESCE(is_active, 1) = 1"
    sql += " ORDER BY sort_order, code"
    try:
        rows = cur.execute(sql).fetchall()
    except Exception:
        return []
    out = []
    for r in rows or []:
        if hasattr(r, "keys"):
            out.append(dict(r))
        else:
            out.append(_row_to_glo(r))
    return out


def glo_list_from_db(conn, *, active_only: bool = True) -> list[dict[str, Any]]:
    out = _fetch_glo_rows(conn, active_only=active_only)
    if not out:
        inserted = seed_college_glo_defaults(conn)
        if inserted:
            try:
                conn.commit()
            except Exception:
                pass
        out = _fetch_glo_rows(conn, active_only=active_only)
    if not out and active_only:
        out = _fetch_glo_rows(conn, active_only=False)
    return out


def glo_list(conn=None, *, active_only: bool = True) -> list[dict[str, Any]]:
    """قائمة GLO من قاعدة البيانات (مع بذرة تلقائية)."""
    if conn is not None:
        from backend.core.plo_schema import ensure_plo_enhancement_schema

        ensure_plo_enhancement_schema(conn)
        return glo_list_from_db(conn, active_only=active_only)
    from backend.services.utilities import get_connection

    with get_connection() as c:
        from backend.core.plo_schema import ensure_plo_enhancement_schema

        ensure_plo_enhancement_schema(c)
        return glo_list_from_db(c, active_only=active_only)


def glo_by_code(conn, code: str) -> dict[str, Any] | None:
    c = (code or "").strip().upper()
    if not c:
        return None
    cur = conn.cursor()
    row = cur.execute(
        f"""
        SELECT {GLO_SELECT}
        FROM college_graduate_outcomes
        WHERE UPPER(TRIM(code)) = ?
        LIMIT 1
        """,
        (c,),
    ).fetchone()
    if not row:
        fallback = {g["code"].upper(): g for g in ENGINEERING_COLLEGE_GLO}
        fg = fallback.get(c)
        return dict(fg) if fg else None
    if hasattr(row, "keys"):
        return dict(row)
    return _row_to_glo(row)


def glo_referenced_by_plo(cur, code: str) -> int:
    c = (code or "").strip().upper()
    row = cur.execute(
        """
        SELECT COUNT(*) FROM program_learning_outcomes
        WHERE UPPER(TRIM(COALESCE(parent_glo_code,''))) = ?
          AND COALESCE(is_active, 1) = 1
        """,
        (c,),
    ).fetchone()
    return int(row[0]) if row else 0


# توافق قديم
GLO_BY_CODE = {g["code"]: g for g in ENGINEERING_COLLEGE_GLO}
