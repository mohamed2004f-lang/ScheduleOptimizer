#!/usr/bin/env python3
"""ترحيل مجموعات التدريس — حصص الجدول، التسجيلات، والتقييمات."""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.services import teaching_groups as tg  # noqa: E402
from backend.services.utilities import get_connection, get_current_term  # noqa: E402


def _term_label(conn, semester: str | None) -> str:
    sem = (semester or "").strip()
    if sem:
        return sem
    tname, tyear = get_current_term(conn=conn)
    return f"{(tname or '').strip()} {(tyear or '').strip()}".strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill teaching groups pipeline")
    parser.add_argument("--semester", help="مثل: خريف 44-45")
    parser.add_argument("--department-id", type=int, default=None)
    parser.add_argument("--skip-schedule", action="store_true")
    parser.add_argument("--skip-registrations", action="store_true")
    parser.add_argument("--skip-evaluations", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()

    with get_connection() as conn:
        sem = _term_label(conn, args.semester)
        dept = args.department_id
        print(f"الفصل: {sem or '—'}")
        if args.audit_only:
            sched = tg.audit_teaching_groups(conn, semester=sem, department_id=dept)
            regs = tg.registration_teaching_groups_audit(conn, semester=sem, department_id=dept)
            evals = tg.teaching_groups_without_evaluation_audit(
                conn, semester=sem, department_id=dept
            )
            print("تدقيق الجدول:", sched)
            print("تدقيق التسجيلات:", {"unlinked": regs.get("unlinked_count")})
            print("مجموعات بلا تقييم:", evals.get("missing_groups"))
            return 0

        if not args.skip_schedule:
            stats = tg.backfill_teaching_groups_for_semester(
                conn, semester=sem, department_id=dept
            )
            print("ترحيل حصص → مجموعات:", stats)
        if not args.skip_registrations:
            stats = tg.backfill_registrations_teaching_groups(
                conn, semester=sem, department_id=dept
            )
            print("ترحيل تسجيلات:", stats)
        if not args.skip_evaluations:
            stats = tg.backfill_course_evaluations_teaching_groups(conn, semester=sem)
            print("ترحيل تقييمات:", stats)

        sched = tg.audit_teaching_groups(conn, semester=sem, department_id=dept)
        regs = tg.registration_teaching_groups_audit(conn, semester=sem, department_id=dept)
        evals = tg.teaching_groups_without_evaluation_audit(
            conn, semester=sem, department_id=dept
        )
        print("— بعد الترحيل —")
        print("حصص غير مربوطة:", len(sched.get("unlinked_slots") or []))
        print("تسجيلات بلا مجموعة:", regs.get("unlinked_count"))
        print("مجموعات بلا تقييم:", evals.get("missing_groups"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
