# -*- coding: utf-8 -*-
"""
إصلاح ميكانيكا الموائع I/II: ترقية لمشترك multi_code
مع رموز الميكانيك (ME) والمدني (CIEN) من لقطة الاستيراد.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass
os.environ.setdefault("ADMIN_PASSWORD", "x")
os.environ.setdefault("SECRET_KEY", "x")

PAIRS = [
    ("ميكانيكا الموائع I", "ME 307", "CIEN 319", 3, 4),
    ("ميكانيكا الموائع II", "ME 310", "CIEN 324", 3, 4),
]


def main() -> None:
    from backend.core.college_shared_catalog import (
        find_shared_catalog_id_by_course_name,
        get_department_plan_course_code,
        save_catalog_entry,
        set_department_plan_course_code,
    )
    from backend.database.database import close_pool, get_connection

    with get_connection() as conn:
        cur = conn.cursor()
        mech = cur.execute(
            "SELECT id FROM departments WHERE UPPER(TRIM(code)) = 'MECH' LIMIT 1"
        ).fetchone()
        civil = cur.execute(
            "SELECT id FROM departments WHERE UPPER(TRIM(code)) = 'CIVIL' LIMIT 1"
        ).fetchone()
        if not mech or not civil:
            raise SystemExit("MECH/CIVIL departments missing")
        mech_id = int(mech[0] if not hasattr(mech, "keys") else mech["id"])
        civil_id = int(civil[0] if not hasattr(civil, "keys") else civil["id"])

        for cname, mech_code, civil_code, mech_units, civil_units in PAIRS:
            row = cur.execute(
                """
                SELECT course_name, course_code, units, owning_department_id
                FROM courses WHERE LOWER(TRIM(course_name)) = LOWER(TRIM(?))
                """,
                (cname,),
            ).fetchone()
            if row is None:
                print("missing course", cname)
                continue
            current_code = (row["course_code"] if hasattr(row, "keys") else row[1]) or ""
            current_units = int((row["units"] if hasattr(row, "keys") else row[2]) or 0)
            # إن استُبدل الرمز بـ CIEN سابقاً، نعيد رمز الميكانيك من الثوابت/الدرجات
            owner_code = mech_code
            if str(current_code).strip().upper().startswith("ME"):
                owner_code = str(current_code).strip()
            catalog_units = current_units if current_units > 0 else mech_units

            cid = find_shared_catalog_id_by_course_name(conn, cname)
            if cid is None:
                save_catalog_entry(
                    conn,
                    {
                        "canonical_course_name": cname,
                        "canonical_course_code": owner_code,
                        "share_type": "multi_code",
                        "units": catalog_units,
                        "notes": "إصلاح بعد استيراد المدني (اسم مشترك مع الميكانيك)",
                        "departments": [
                            {
                                "department_id": mech_id,
                                "plan_course_code": owner_code,
                                "units_override": mech_units,
                            },
                            {
                                "department_id": civil_id,
                                "plan_course_code": civil_code,
                                "units_override": civil_units,
                            },
                        ],
                    },
                )
                print("promoted", cname, owner_code, "+", civil_code)
            else:
                set_department_plan_course_code(
                    conn, cname, mech_id, owner_code, units=mech_units
                )
                set_department_plan_course_code(
                    conn, cname, civil_id, civil_code, units=civil_units
                )
                print("linked", cname, owner_code, "+", civil_code)

            print(
                "  plans",
                get_department_plan_course_code(conn, cname, mech_id),
                get_department_plan_course_code(conn, cname, civil_id),
            )

        conn.commit()
        try:
            from backend.core.cache_setup import invalidate_list_prefix

            invalidate_list_prefix("courses")
        except Exception:
            pass
    close_pool()
    print("done")


if __name__ == "__main__":
    main()
