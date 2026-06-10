"""إصلاح رموز مخرجات جميع برامج ميكانيك — تشغيل لمرة واحدة."""
from __future__ import annotations

from backend.core.outcome_symbol_audit import audit_all_programs, cleanup_mech_stray_outcomes
from backend.core.plo_schema import ensure_plo_enhancement_schema
from backend.core.program_goals import import_mech_program_profile
from backend.database.database import get_connection


def main() -> None:
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        cur = conn.cursor()
        before = audit_all_programs(cur)
        print(f"برامج بها ملاحظات قبل الإصلاح: {len(before)}")
        for rep in before:
            print(f"  program {rep['program_id']}: {[i['message_ar'] for i in rep['issues']]}")

        rows = cur.execute(
            """
            SELECT p.id FROM programs p
            JOIN departments d ON d.id = p.department_id
            WHERE UPPER(TRIM(d.code)) = 'MECH' AND COALESCE(p.is_active, 1) = 1
            ORDER BY p.id
            """
        ).fetchall()
        for r in rows or []:
            pid = int(r[0] if not hasattr(r, "keys") else r["id"])
            import_mech_program_profile(cur, pid, merge=True, sync_links=True, actor="fix_script")
            cleanup = cleanup_mech_stray_outcomes(cur, pid)
            retired = cleanup.get("retired_codes") or []
            if retired:
                print(f"program {pid}: retired {retired}")

        after = audit_all_programs(cur)
        print(f"برامج بها ملاحظات بعد الإصلاح: {len(after)}")
        for rep in after:
            print(f"  program {rep['program_id']}: {[i['message_ar'] for i in rep['issues']]}")


if __name__ == "__main__":
    main()
