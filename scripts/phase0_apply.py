"""
تطبيق المرحلة 0 على قاعدة البيانات:
  1) ضمان وجود جداول الأقسام/البرامج (مع ensure_tables)
  2) إدراج أو تحديث كتالوج الأقسام والبرامج المرجعي (بدون مقررات تجريبية)
  3) تعبئة department_id و current_program_id للطلاب غير المعيَّنين
     — افتراضي: قسم MECH وبرنامج PROG_MAJOR (قابل للتغيير)

الاستخدام (PostgreSQL):
  python scripts/phase0_apply.py
  python scripts/phase0_apply.py --legacy-dept MECH
  python scripts/phase0_apply.py --dry-run
  python scripts/phase0_apply.py --attach-operational
      يربط أيضاً المقررات (owning_department_id) وهيئة التدريس والمستخدمين التشغيليين
      بقسم التراث نفسه — للبيانات المخزّنة قبل تعدد الأقسام.
  python scripts/phase0_apply.py --me-monolith
      يفرض ربط **كل** الطلاب والمقررات والجدول (schedule) والهيئة والمستخدمين التشغيليين
      بقسم --legacy-dept (افتراضي MECH). للبيانات القديمة «كتلة ميكانيك» فقط.

ملاحظة: الطلبة المعيَّنوا مسبقاً لا يُعادوا كتابتهم بفضل COALESCE.
لا يتم تعديل admission_program_id (مناسب لمن أنهوا مرحلة العام خارج هذا النموذج).
"""

from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.boot.phase0 import (  # noqa: E402
    backfill_legacy_operational_data,
    backfill_legacy_students,
    count_legacy_students,
    ensure_phase0_catalog,
)
from backend.database.database import close_pool, ensure_tables, get_connection  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="مرحلة 0: كتالوج أقسام/برامج + تعبئة طلاب قدامى")
    parser.add_argument(
        "--legacy-dept",
        default="MECH",
        help="رمز القسم المرجعي للطلاب بلا تعيين (افتراضي: MECH = ميكانيكي)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="احسب عدد الصفوف دون تنفيذ UPDATE",
    )
    parser.add_argument(
        "--attach-operational",
        action="store_true",
        help="ربط المقررات وأعضاء هيئة التدريس ومستخدمي التدريس/الإدارة بقسم الترحيل (بلا قسم فقط)",
    )
    parser.add_argument(
        "--skip-students",
        action="store_true",
        help="مع --attach-operational أو --me-monolith: لا تعبئة طلاب (مقررات/هيئة/جدول/مستخدمون فقط)",
    )
    parser.add_argument(
        "--me-monolith",
        action="store_true",
        help="فرض ربط كل البيانات التشغيلية الحالية بقسم legacy-dept (كتلة واحدة؛ يتجاهل --attach-operational)",
    )
    args = parser.parse_args()

    try:
        return _main_after_args(args)
    finally:
        close_pool()


def _main_after_args(args: argparse.Namespace) -> int:
    if not os.environ.get("DATABASE_URL"):
        print("تنبيه: DATABASE_URL غير مضبوط — ستُستخدم config/.env", file=sys.stderr)

    ensure_tables()
    dept_code = str(args.legacy_dept).strip().upper()
    if not dept_code:
        print("خطأ: --legacy-dept فارغ.", file=sys.stderr)
        return 2

    with get_connection() as conn:
        before = count_legacy_students(conn)
        print(f"طلاب بدون تعيين قسم/برنامج (قبل): {before}")

        cat = ensure_phase0_catalog(conn)
        print("[ok] كتالوج الأقسام/البرامج جاهز، مثلاً GENERAL ->", cat["department_ids_by_code"].get("GENERAL"))
        if dept_code not in cat["department_ids_by_code"]:
            print(f"خطأ: قسم غير موجود في الكتالوج: {dept_code}", file=sys.stderr)
            return 2
        prog_key = f"{dept_code}/PROG_MAJOR"
        if prog_key not in cat["program_ids"]:
            print(f"خطأ: برنامج غير موجود: {prog_key}", file=sys.stderr)
            return 2

        if args.me_monolith:
            if args.attach_operational:
                print(
                    "تنبيه: --me-monolith يستبدل --attach-operational (تشغيل كتلة واحدة فقط).",
                    file=sys.stderr,
                )
            op_out = backfill_legacy_operational_data(
                conn,
                legacy_dept_code=dept_code,
                dry_run=args.dry_run,
                include_students=not args.skip_students,
                include_courses=True,
                include_instructors=True,
                include_staff_users=True,
                monolith_exclusive=True,
            )
            rem_raw = op_out.get("remaining_unassigned")
            if rem_raw is None:
                rem = count_legacy_students(conn)
            else:
                rem = int(rem_raw)
            out = {
                "pending_student_rows_before": before,
                "pending_student_rows": rem,
                "updated_rows": op_out.get("students_all_rows_updated", op_out.get("would_update_students", 0)),
                "remaining_unassigned": rem,
            }
        elif args.attach_operational:
            op_out = backfill_legacy_operational_data(
                conn,
                legacy_dept_code=dept_code,
                dry_run=args.dry_run,
                include_students=not args.skip_students,
                include_courses=True,
                include_instructors=True,
                include_staff_users=True,
                monolith_exclusive=False,
            )
            if not args.skip_students and "students" in op_out:
                out = op_out["students"]
            else:
                rem = count_legacy_students(conn)
                out = {
                    "pending_student_rows_before": before,
                    "pending_student_rows": rem,
                    "updated_rows": 0,
                    "remaining_unassigned": rem,
                }
        else:
            op_out = None
            out = backfill_legacy_students(conn, legacy_dept_code=dept_code, dry_run=args.dry_run)
        conn.commit()

    if args.dry_run:
        pend = out.get("pending_student_rows")
        if pend is None:
            pend = out.get("pending_student_rows_before")
        print("[dry-run] لم يُنفَّذ UPDATE — pending:", pend)
        if op_out:
            print("[dry-run] attach-operational:", {k: v for k, v in op_out.items() if k != "students"})
        return 0

    print(
        "[ok] تم التحديث: pending_before="
        f"{out.get('pending_student_rows_before')} updated_rows="
        f"{out.get('updated_rows')} remaining_unassigned={out.get('remaining_unassigned')}"
    )
    if op_out:
        brief = {k: v for k, v in op_out.items() if k != "students"}
        st = op_out.get("students")
        if isinstance(st, dict):
            brief["students_summary"] = {
                k: st.get(k)
                for k in (
                    "pending_student_rows_before",
                    "updated_rows",
                    "remaining_unassigned",
                )
                if k in st
            }
        print("[ok] attach-operational:", brief)
    if int(out.get("remaining_unassigned") or 0) > 0:
        print("تحذير: ما زال هناك طلاب بدون تعيين (تحقق من صحة أكواد الأقسام/الصفوف).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
