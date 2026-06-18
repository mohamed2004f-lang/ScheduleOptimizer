"""
إعادة ضبط تجربة «تقرير تنفيذ المقرر» لمقرر واحد (قائمة مفردات + تقارير + مسودات مرتبطة).

الاستخدام:
  python scripts/reset_course_delivery_trial.py --course "مقاومة المواد II"
  python scripts/reset_course_delivery_trial.py --course "مقاومة المواد II" --teaching-group-id 19
  python scripts/reset_course_delivery_trial.py --course "مقاومة المواد II" --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import get_connection  # noqa: E402


def _count(cur, sql: str, params: tuple) -> int:
    row = cur.execute(sql, params).fetchone()
    if not row:
        return 0
    try:
        return int(row[0])
    except (TypeError, KeyError, IndexError):
        d = dict(row) if hasattr(row, "keys") else {}
        return int(next(iter(d.values()), 0))


def reset_course_delivery_trial(
    *,
    course_name: str,
    teaching_group_id: int | None = None,
    dry_run: bool = False,
) -> dict:
    course_name = (course_name or "").strip()
    if not course_name:
        raise ValueError("course_name مطلوب")

    stats: dict[str, int] = {}

    with get_connection() as conn:
        cur = conn.cursor()

        baseline_ids = [
            int(r[0] if not hasattr(r, "keys") else r["id"])
            for r in cur.execute(
                "SELECT id FROM course_syllabus_baselines WHERE course_name = ?",
                (course_name,),
            ).fetchall()
            or []
        ]

        report_sql = "SELECT id FROM course_delivery_reports WHERE course_name = ?"
        report_params: list = [course_name]
        if teaching_group_id:
            report_sql += " AND teaching_group_id = ?"
            report_params.append(int(teaching_group_id))
        report_ids = [
            int(r[0] if not hasattr(r, "keys") else r["id"])
            for r in cur.execute(report_sql, tuple(report_params)).fetchall()
            or []
        ]

        draft_sql = "SELECT id FROM grade_drafts WHERE course_name = ?"
        draft_params: list = [course_name]
        if teaching_group_id:
            draft_sql += " AND (teaching_group_id = ? OR teaching_group_id IS NULL)"
            draft_params.append(int(teaching_group_id))
        draft_ids = [
            int(r[0] if not hasattr(r, "keys") else r["id"])
            for r in cur.execute(draft_sql, tuple(draft_params)).fetchall()
            or []
        ]

        if dry_run:
            stats["baselines"] = len(baseline_ids)
            stats["topics"] = sum(
                _count(cur, "SELECT COUNT(*) FROM course_syllabus_topics WHERE baseline_id = ?", (bid,))
                for bid in baseline_ids
            )
            stats["reports"] = len(report_ids)
            stats["report_items"] = sum(
                _count(cur, "SELECT COUNT(*) FROM course_delivery_report_items WHERE report_id = ?", (rid,))
                for rid in report_ids
            )
            stats["grade_drafts"] = len(draft_ids)
            stats["draft_items"] = sum(
                _count(cur, "SELECT COUNT(*) FROM grade_draft_items WHERE draft_id = ?", (did,))
                for did in draft_ids
            )
            return stats

        for did in draft_ids:
            cur.execute("DELETE FROM grade_draft_items WHERE draft_id = ?", (did,))
            stats["draft_items"] = stats.get("draft_items", 0) + cur.rowcount
            cur.execute("DELETE FROM grade_drafts WHERE id = ?", (did,))
            stats["grade_drafts"] = stats.get("grade_drafts", 0) + cur.rowcount

        for rid in report_ids:
            cur.execute("DELETE FROM course_delivery_report_items WHERE report_id = ?", (rid,))
            stats["report_items"] = stats.get("report_items", 0) + cur.rowcount
            cur.execute("DELETE FROM course_delivery_extra_topics WHERE report_id = ?", (rid,))
            cur.execute("DELETE FROM course_delivery_reports WHERE id = ?", (rid,))
            stats["reports"] = stats.get("reports", 0) + cur.rowcount

        for bid in baseline_ids:
            cur.execute("DELETE FROM course_syllabus_topics WHERE baseline_id = ?", (bid,))
            stats["topics"] = stats.get("topics", 0) + cur.rowcount
            cur.execute("DELETE FROM course_syllabus_baselines WHERE id = ?", (bid,))
            stats["baselines"] = stats.get("baselines", 0) + cur.rowcount

        conn.commit()

    return stats


def main() -> int:
    p = argparse.ArgumentParser(description="إعادة ضبط تجربة تقرير تنفيذ المقرر لمقرر واحد")
    p.add_argument("--course", required=True, help="اسم المقرر بالعربية كما في النظام")
    p.add_argument("--teaching-group-id", type=int, default=None, help="تقييد المسودات/التقارير بمجموعة تدريس")
    p.add_argument("--dry-run", action="store_true", help="عرض ما سيُحذف دون تنفيذ")
    args = p.parse_args()

    stats = reset_course_delivery_trial(
        course_name=args.course,
        teaching_group_id=args.teaching_group_id,
        dry_run=args.dry_run,
    )
    mode = "معاينة (dry-run)" if args.dry_run else "تم الحذف"
    print(f"{mode} — {args.course}")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
