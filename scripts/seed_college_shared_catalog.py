#!/usr/bin/env python3
"""تعبئة أولية لسجل المقررات المشتركة (قابل للتشغيل المتكرر)."""
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("ADMIN_PASSWORD", "seed-local")
os.environ.setdefault("SECRET_KEY", "seed-local")

INITIAL_ENTRIES = [
    {
        "catalog_key": "math_iii",
        "share_type": "unified",
        "canonical_course_name": "رياضيات III",
        "canonical_course_code": "GS 201",
        "units": 3,
        "requirement_scope": "pre_track",
    },
    {
        "catalog_key": "math_iv",
        "share_type": "unified",
        "canonical_course_name": "رياضيات IV",
        "canonical_course_code": "GS 202",
        "units": 3,
        "requirement_scope": "pre_track",
    },
    {
        "catalog_key": "eng_academic",
        "share_type": "unified",
        "canonical_course_name": "لغة انجليزية أكاديمية",
        "canonical_course_code": "GS 212",
        "units": 3,
        "requirement_scope": "pre_track",
    },
    {
        "catalog_key": "workshop_tech",
        "share_type": "unified",
        "canonical_course_name": "تقنية ورش",
        "canonical_course_code": "GS 203",
        "units": 2,
        "requirement_scope": "pre_track",
        "notes": "غيّر إلى multi_code من الواجهة إن اختلف الاسم بين الأقسام",
    },
    {
        "catalog_key": "mech_eng_ii",
        "share_type": "multi_code",
        "canonical_course_name": "ميكانيكا هندسية II",
        "canonical_course_code": "ME 205",
        "units": 3,
        "requirement_scope": "pre_track",
        "department_codes": {"MECH": "ME 205"},
    },
    {
        "catalog_key": "engineering_survey",
        "share_type": "multi_code",
        "canonical_course_name": "قياسات هندسية",
        "canonical_course_code": "ME 209",
        "units": 3,
        "requirement_scope": "pre_track",
        "department_codes": {"MECH": "ME 209"},
    },
    {
        "catalog_key": "tech_report_writing",
        "share_type": "multi_code",
        "canonical_course_name": "كتابة تقارير فنية",
        "canonical_course_code": "ME 401",
        "units": 2,
        "requirement_scope": "pre_track",
        "department_codes": {"MECH": "ME 401"},
    },
    {
        "catalog_key": "numerical_analysis",
        "share_type": "multi_code",
        "canonical_course_name": "تحليلات عددية",
        "canonical_course_code": "ME 301",
        "units": 3,
        "requirement_scope": "pre_track",
        "department_codes": {"MECH": "ME 301"},
    },
]


def main() -> int:
    from backend.database.database import close_pool, get_connection
    from backend.core.college_shared_catalog import list_catalog_entries, save_catalog_entry

    try:
        with get_connection() as conn:
            existing = {e.get("catalog_key"): e for e in list_catalog_entries(conn, include_inactive=True)}
            n = 0
            for item in INITIAL_ENTRIES:
                key = item["catalog_key"]
                payload = {k: v for k, v in item.items() if k != "department_codes"}
                if key in existing:
                    payload["id"] = existing[key]["id"]
                dept_codes = item.get("department_codes") or {}
                if dept_codes:
                    cur = conn.cursor()
                    departments = []
                    for code, pcode in dept_codes.items():
                        row = cur.execute(
                            "SELECT id FROM departments WHERE UPPER(TRIM(code)) = ? LIMIT 1",
                            (code.strip().upper(),),
                        ).fetchone()
                        if not row:
                            print(f"Skip dept {code} for {key} — not found")
                            continue
                        did = int(row[0] if not hasattr(row, "keys") else row["id"])
                        departments.append(
                            {
                                "department_id": did,
                                "plan_course_code": pcode,
                                "plan_course_name_override": "",
                                "is_active": True,
                            }
                        )
                    payload["departments"] = departments
                save_catalog_entry(conn, payload)
                n += 1
                print(f"OK: {key} — {payload['canonical_course_name']}")
            conn.commit()
            print(f"Seeded/updated {n} shared catalog entries.")
        return 0
    finally:
        close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
