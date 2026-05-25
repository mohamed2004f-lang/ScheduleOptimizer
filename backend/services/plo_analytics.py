"""تحليلات وتقارير مخرجات التعلم."""

from __future__ import annotations

import csv
import io
from typing import Any

from backend.core.plo_glo import DOMAIN_LABELS_AR, normalize_outcome_domain


def program_plo_analytics(cur, program_id: int) -> dict[str, Any]:
    outcomes = cur.execute(
        """
        SELECT id, code, title_ar, governance_status, parent_glo_code,
               COALESCE(domain,'') AS domain
        FROM program_learning_outcomes
        WHERE program_id = ? AND COALESCE(is_active, 1) = 1
        ORDER BY sort_order, code
        """,
        (int(program_id),),
    ).fetchall()
    outcome_rows = []
    for o in outcomes or []:
        if hasattr(o, "keys"):
            outcome_rows.append(dict(o))
        else:
            outcome_rows.append(
                {
                    "id": o[0],
                    "code": o[1],
                    "title_ar": o[2],
                    "governance_status": o[3],
                    "parent_glo_code": o[4],
                    "domain": o[5],
                }
            )
    for oc in outcome_rows:
        dom = normalize_outcome_domain(
            oc.get("domain"),
            glo_code=oc.get("parent_glo_code"),
        )
        oc["domain"] = dom
        oc["domain_label"] = DOMAIN_LABELS_AR.get(dom, dom)
    course_count = int(
        cur.execute(
            """
            SELECT COUNT(*) FROM program_courses
            WHERE program_id = ? AND COALESCE(is_active, 1) = 1
            """,
            (int(program_id),),
        ).fetchone()[0]
    )
    coverage_by_outcome: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for oc in outcome_rows:
        oid = int(oc["id"])
        levels = cur.execute(
            """
            SELECT COALESCE(m.coverage_level, '') AS lv
            FROM program_course_learning_outcomes m
            JOIN program_courses pc ON pc.id = m.program_course_id
            WHERE pc.program_id = ? AND m.outcome_id = ? AND COALESCE(pc.is_active, 1) = 1
            """,
            (int(program_id), oid),
        ).fetchall()
        i_cnt = r_cnt = m_cnt = 0
        for lv_row in levels or []:
            lv = (
                str(lv_row[0] if not hasattr(lv_row, "keys") else lv_row["lv"] or "")
                .strip()
                .upper()
            )
            if lv == "I":
                i_cnt += 1
            elif lv == "R":
                r_cnt += 1
            elif lv == "M":
                m_cnt += 1
        linked_courses = i_cnt + r_cnt + m_cnt
        assess_pct = round(100.0 * m_cnt / course_count, 1) if course_count else 0.0
        item = {
            "outcome_id": oid,
            "code": oc["code"],
            "title_ar": oc["title_ar"],
            "domain": oc.get("domain"),
            "domain_label": oc.get("domain_label"),
            "introduce_count": i_cnt,
            "reinforce_count": r_cnt,
            "assess_count": m_cnt,
            "linked_courses": linked_courses,
            "assess_coverage_percent": assess_pct,
        }
        coverage_by_outcome.append(item)
        if m_cnt < 3 and course_count >= 3:
            gaps.append(
                {
                    "code": oc["code"],
                    "domain": oc.get("domain"),
                    "domain_label": oc.get("domain_label"),
                    "reason": "أقل من 3 مقررات بمستوى إتقان/تقييم (M)",
                    "assess_count": m_cnt,
                }
            )
        ach = cur.execute(
            """
            SELECT AVG(achievement_percent) FROM section_ilo_assessments s
            JOIN schedule sch ON sch.id = s.section_id
            WHERE s.outcome_id = ?
            """,
            (oid,),
        ).fetchone()
        avg_ach = ach[0] if ach and ach[0] is not None else None
        if avg_ach is not None and float(avg_ach) < 70:
            gaps.append(
                {
                    "code": oc["code"],
                    "domain": oc.get("domain"),
                    "domain_label": oc.get("domain_label"),
                    "reason": f"متوسط تحقق الشعب {float(avg_ach):.0f}% أقل من 70%",
                    "assess_count": m_cnt,
                }
            )
    domain_stats: dict[str, dict[str, Any]] = {}
    for oc in outcome_rows:
        dom = oc.get("domain") or ""
        if not dom:
            continue
        bucket = domain_stats.setdefault(
            dom,
            {
                "domain": dom,
                "domain_label": oc.get("domain_label"),
                "plo_count": 0,
                "assess_m_total": 0,
                "low_achievement_count": 0,
            },
        )
        bucket["plo_count"] += 1
        cov = next((x for x in coverage_by_outcome if x["outcome_id"] == int(oc["id"])), None)
        if cov:
            bucket["assess_m_total"] += int(cov.get("assess_count") or 0)
    for g in gaps:
        dom = g.get("domain") or ""
        if dom in domain_stats:
            domain_stats[dom]["low_achievement_count"] = (
                int(domain_stats[dom].get("low_achievement_count") or 0) + 1
            )
    domain_summary = []
    for dom in sorted(domain_stats.keys(), key=lambda d: DOMAIN_LABELS_AR.get(d, d)):
        st = domain_stats[dom]
        domain_summary.append(
            {
                "domain": dom,
                "domain_label": st.get("domain_label"),
                "plo_count": st["plo_count"],
                "gap_count": int(st.get("low_achievement_count") or 0),
            }
        )
    clo_count = 0
    try:
        clo_count = int(
            cur.execute(
                """
                SELECT COUNT(*) FROM course_learning_outcomes clo
                JOIN program_courses pc ON pc.id = clo.program_course_id
                WHERE pc.program_id = ? AND COALESCE(clo.is_active, 1) = 1
                """,
                (int(program_id),),
            ).fetchone()[0]
        )
    except Exception:
        clo_count = 0
    approved = sum(
        1
        for oc in outcome_rows
        if (oc.get("governance_status") or "").strip() == "approved"
    )
    return {
        "outcomes_count": len(outcome_rows),
        "courses_count": course_count,
        "clo_count": clo_count,
        "approved_outcomes": approved,
        "coverage_by_outcome": coverage_by_outcome,
        "domain_summary": domain_summary,
        "gaps": gaps,
        "target_assess_courses_per_plo": 3,
    }


def export_plo_matrix_csv(
    outcomes: list[dict],
    columns: list[dict],
    cells: list[dict],
) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    header = ["PLO"] + [
        (c.get("course_code") or c.get("course_name") or c.get("col_key") or "")
        for c in columns
    ]
    w.writerow(header)
    cell_map = {(c["outcome_id"], c["col_key"]): c for c in cells}
    for o in outcomes:
        row = [o.get("code") or ""]
        for col in columns:
            key = (o.get("id"), col.get("col_key"))
            cell = cell_map.get(key) or {}
            if not cell.get("linked"):
                row.append("")
            else:
                row.append(cell.get("coverage_level") or "●")
        w.writerow(row)
    return buf.getvalue()
