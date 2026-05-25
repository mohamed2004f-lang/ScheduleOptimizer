"""اختبارات مجالات المخرجات (7 مجالات — عمود domain واحد)."""

from backend.core.plo_glo import (
    DEFAULT_OUTCOME_DOMAIN,
    DOMAIN_ORDER,
    migrate_outcome_domains,
    normalize_outcome_domain,
    seed_college_glo_defaults,
)
from backend.core.plo_schema import ensure_plo_enhancement_schema


def test_normalize_legacy_and_glo_mapping():
    assert normalize_outcome_domain("skills") == "technical_skills"
    assert normalize_outcome_domain("knowledge") == "program_knowledge"
    assert normalize_outcome_domain("values") == "ethical_values"
    assert normalize_outcome_domain("professional") == "social_responsibility"
    assert normalize_outcome_domain("", glo_code="GLO7") == "environmental_values"
    assert normalize_outcome_domain("bogus") == DEFAULT_OUTCOME_DOMAIN
    assert len(DOMAIN_ORDER) == 7


def test_migrate_outcome_domains(db_conn):
    ensure_plo_enhancement_schema(db_conn)
    seed_college_glo_defaults(db_conn)
    cur = db_conn.cursor()
    cur.execute(
        "UPDATE college_graduate_outcomes SET domain = 'skills' WHERE code = 'GLO2'"
    )
    cur.execute(
        """
        INSERT INTO program_learning_outcomes
        (program_id, code, title_ar, domain, parent_glo_code, is_active)
        VALUES (1, 'PLO_MIG', 'اختبار ترحيل', 'knowledge', 'GLO1', 1)
        """
    )
    db_conn.commit()
    stats = migrate_outcome_domains(db_conn)
    row = cur.execute(
        "SELECT domain FROM college_graduate_outcomes WHERE code = 'GLO2'"
    ).fetchone()
    dom = row[0] if not hasattr(row, "keys") else row["domain"]
    assert dom == "technical_skills"
    prow = cur.execute(
        "SELECT domain FROM program_learning_outcomes WHERE code = 'PLO_MIG'"
    ).fetchone()
    pdom = prow[0] if not hasattr(prow, "keys") else prow["domain"]
    assert pdom == "program_knowledge"
    assert stats["glo"] >= 1 or stats["plo"] >= 1
