"""Diagnose auto-axis status for a course (one-off)."""
from __future__ import annotations

import sys

from backend.services.course_delivery import (
    apply_auto_axes_to_portal_row,
    derive_assessment_axis,
    derive_course_mgmt_axis,
    derive_teaching_content_axis,
    delivery_summary_for_ui,
    ensure_course_delivery_schema,
    get_active_baseline,
)
from backend.services.teaching_groups import list_linked_section_ids
from backend.services.utilities import get_connection, get_current_term

COURSE = sys.argv[1] if len(sys.argv) > 1 else "مقاومة المواد II"


def main() -> None:
    with get_connection() as conn:
        ensure_course_delivery_schema(conn)
        cur = conn.cursor()
        tname, tyear = get_current_term(conn=conn)
        sem = f"{(tname or '').strip()} {(tyear or '').strip()}".strip()
        print("semester:", sem)
        bl = get_active_baseline(conn, COURSE)
        print("baseline approved:", bool(bl), "topics:", len((bl or {}).get("topics") or []))

        cur.execute("SELECT id, name FROM instructors")
        instructors = cur.fetchall()
        print("instructors count:", len(instructors))

        cur.execute(
            "SELECT id, course_name, group_code, semester FROM teaching_groups WHERE course_name ILIKE %s",
            (f"%{COURSE.split()[0]}%",),
        )
        print("teaching_groups:", cur.fetchall())

        cur.execute(
            """
            SELECT DISTINCT s.instructor, s.teaching_group_id, s.course_name
            FROM schedule s
            WHERE s.course_name ILIKE %s
            """,
            (f"%{COURSE.split()[0]}%",),
        )
        sched = cur.fetchall()
        print("schedule rows:", sched)

        for inst_name, tgid, cn in sched or []:
            cur.execute(
                "SELECT id FROM instructors WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s)) LIMIT 1",
                (inst_name,),
            )
            irow = cur.fetchone()
            if not irow:
                print("no instructor id for", inst_name)
                continue
            iid = int(irow[0])
            sids = list_linked_section_ids(conn, int(tgid or 0)) or []
            cn = (cn or COURSE).strip()
            print("\n===", cn, "tgid=", tgid, "instructor=", inst_name, "iid=", iid, "sections=", sids)
            ds = delivery_summary_for_ui(conn, teaching_group_id=tgid, course_name=cn, semester=sem)
            print("delivery baseline_ok:", ds.get("baseline_ok"), "checkpoints:", ds.get("checkpoints_done"))
            for fn, out in [
                ("course_mgmt", derive_course_mgmt_axis(conn, course_name=cn, instructor_id=iid, section_ids=sids)),
                ("teaching_content", derive_teaching_content_axis(conn, teaching_group_id=tgid, course_name=cn, semester=sem)),
                ("assessment", derive_assessment_axis(conn, teaching_group_id=tgid, course_name=cn, semester=sem, instructor_id=iid)),
            ]:
                print(f"  {fn}: status={out.get('status')} detail={out.get('detail_ar')}")
            row = {
                "section_id": sids[0] if sids else 0,
                "section_ids": sids,
                "teaching_group_id": int(tgid or 0) or None,
                "course_name": cn,
                "axes": {k: "pending" for k in ("course_mgmt", "teaching_content", "assessment", "communication_supervision", "extra_service")},
            }
            apply_auto_axes_to_portal_row(conn, row, semester=sem, instructor_id=iid)
            print("  merged axes:", row.get("axes"))
            print("  axes_meta:", {k: v.get("detail_ar") for k, v in (row.get("axes_meta") or {}).items()})
            stale = cur.execute(
                """
                SELECT section_id, axis_key, status FROM faculty_section_axis_status
                WHERE instructor_id = ? AND axis_key IN ('course_mgmt','teaching_content','assessment')
                """,
                (iid,),
            ).fetchall()
            print("  stale manual:", stale)


if __name__ == "__main__":
    main()
