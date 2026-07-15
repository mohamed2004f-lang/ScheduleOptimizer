"""اختبارات وحدات التخرج لكل قسم في لائحة المسار."""
from __future__ import annotations

import pytest


class TestDeptGraduationRegulations:
    def test_pathway_defaults_seeded_per_department(self, db_conn):
        from backend.services.pathway_regulations import (
            DEPT_GRADUATION_TARGETS,
            COLLEGE_GENERAL_UNITS_IN_GRAD,
            ensure_pathway_regulation_defaults,
            get_pathway_regulation_value,
        )

        cur = db_conn.cursor()
        codes = {}
        for code in DEPT_GRADUATION_TARGETS:
            cur.execute(
                "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
                (code, code, code),
            )
            row = cur.execute(
                "SELECT id FROM departments WHERE UPPER(TRIM(code)) = ? LIMIT 1", (code,)
            ).fetchone()
            codes[code] = int(row[0])

        cur.execute(
            "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES ('GENERAL', 'عام', 'Gen', 1)"
        )
        db_conn.commit()

        ensure_pathway_regulation_defaults(db_conn)

        for code, grad in DEPT_GRADUATION_TARGETS.items():
            did = codes[code]
            g = get_pathway_regulation_value(cur, did, "dept_graduation_min_units")
            p = get_pathway_regulation_value(cur, did, "dept_pre_track_min_units")
            assert int(g or 0) == int(grad)
            assert int(p or 0) == int(grad) - COLLEGE_GENERAL_UNITS_IN_GRAD

    def test_graduation_units_for_department_code(self):
        from backend.core.program_tracks import graduation_units_for_department_code

        assert graduation_units_for_department_code("CIVIL") == 161
        assert graduation_units_for_department_code("MECH") == 155
        assert graduation_units_for_department_code("UNKNOWN") == 155
