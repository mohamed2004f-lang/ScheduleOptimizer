# -*- coding: utf-8 -*-
"""إخراج مقرر قياسات هندسية من سجل المشترك وإبقاؤه لملكية الميكانيكا فقط."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

# تحميل .env إن وُجد
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

os.environ.setdefault("ADMIN_PASSWORD", "diag")
os.environ.setdefault("SECRET_KEY", "diag")

TARGET_NAMES = ("قياسات هندسية",)
TARGET_KEYS = ("engineering_survey",)


def main() -> int:
    from backend.database.database import close_pool, get_connection
    from backend.core.college_shared_catalog import (
        delete_catalog_entry,
        ensure_college_shared_catalog_schema,
        list_catalog_entries,
    )
    from backend.core.department_scope_policy import resolve_college_general_department_id

    with get_connection() as conn:
        ensure_college_shared_catalog_schema(conn)
        cur = conn.cursor()
        mech = cur.execute(
            "SELECT id FROM departments WHERE UPPER(TRIM(code)) = 'MECH' LIMIT 1"
        ).fetchone()
        if not mech:
            print("MECH department not found")
            return 1
        mech_id = int(mech[0] if not hasattr(mech, "keys") else mech["id"])
        gen_id = resolve_college_general_department_id(conn)

        removed = 0
        for it in list_catalog_entries(conn, include_inactive=True):
            name = (it.get("canonical_course_name") or "").strip()
            key = (it.get("catalog_key") or "").strip()
            if name in TARGET_NAMES or key in TARGET_KEYS or "قياسات هندس" in name:
                cid = int(it["id"])
                print("removing catalog", cid, key, name, it.get("share_type"))
                try:
                    delete_catalog_entry(conn, cid, force=True)
                    removed += 1
                except Exception as e:
                    print(" delete failed, deactivating:", e)
                    cur.execute(
                        "UPDATE college_shared_catalog SET is_active = 0 WHERE id = ?",
                        (cid,),
                    )
                    removed += 1

        # ملكية المقرر التشغيلية للميكانيكا
        for name in TARGET_NAMES:
            row = cur.execute(
                "SELECT owning_department_id, course_code FROM courses WHERE course_name = ?",
                (name,),
            ).fetchone()
            if not row:
                print("course row missing:", name)
                continue
            own = row[0] if not hasattr(row, "keys") else row["owning_department_id"]
            code = row[1] if not hasattr(row, "keys") else row["course_code"]
            print("course before", name, "owning", own, "code", code)
            if gen_id is not None and own is not None and int(own) == int(gen_id):
                cur.execute(
                    "UPDATE courses SET owning_department_id = ? WHERE course_name = ?",
                    (mech_id, name),
                )
                print(" set owning -> MECH", mech_id)
            elif own is None or int(own) != mech_id:
                cur.execute(
                    "UPDATE courses SET owning_department_id = ? WHERE course_name = ?",
                    (mech_id, name),
                )
                print(" set owning -> MECH", mech_id)

        conn.commit()
        print("done removed_catalog_entries", removed)

        # verify
        left = [
            it
            for it in list_catalog_entries(conn, include_inactive=True)
            if (it.get("canonical_course_name") or "") in TARGET_NAMES
            or (it.get("catalog_key") or "") in TARGET_KEYS
        ]
        print("remaining catalog hits", left)
        for name in TARGET_NAMES:
            r = cur.execute(
                "SELECT owning_department_id FROM courses WHERE course_name = ?",
                (name,),
            ).fetchone()
            print("owning now", name, r[0] if r else None)

    close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
