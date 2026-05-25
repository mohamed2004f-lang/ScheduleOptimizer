"""تقييم المخرجات: بنود CLO، درجات الطلاب، إتقان، لوحات الطالب ورئيس القسم."""

from __future__ import annotations

import datetime
from typing import Any

from backend.core.outcome_assessment_schema import ensure_outcome_assessment_schema
from backend.core.plo_glo import (
    DOMAIN_COLORS,
    DOMAIN_LABELS_AR,
    DOMAIN_ORDER,
    normalize_outcome_domain,
)
from backend.core.plo_schema import ensure_plo_enhancement_schema
from backend.database.database import conn_is_postgresql, is_postgresql, schedule_pk_column


def _row_dict(row, keys: list[str] | None = None) -> dict:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return dict(row)
    if keys:
        return {k: row[i] for i, k in enumerate(keys)}
    return {}


def _section_context(cur, section_id: int, conn=None) -> dict | None:
    pk = "id"
    if conn is not None:
        try:
            from backend.services.schedule import _sync_schedule_pk_col

            _sync_schedule_pk_col(conn)
            pk = schedule_pk_column(conn)
        except Exception:
            pk = "id"
    row = cur.execute(
        f"""
        SELECT {pk} AS section_id, COALESCE(program_course_id, 0) AS program_course_id,
               COALESCE(course_name, '') AS course_name, COALESCE(department_id, 0) AS department_id
        FROM schedule WHERE {pk} = ? LIMIT 1
        """,
        (int(section_id),),
    ).fetchone()
    if not row:
        return None
    return _row_dict(row, ["section_id", "program_course_id", "course_name", "department_id"])


def list_clos_for_program_course(cur, program_course_id: int, pg: bool = False) -> list[dict]:
    if not program_course_id:
        return []
    agg_plo = "STRING_AGG(DISTINCT o.code, ',')" if pg else "GROUP_CONCAT(DISTINCT o.code)"
    agg_glo = "STRING_AGG(DISTINCT o.parent_glo_code, ',')" if pg else "GROUP_CONCAT(DISTINCT o.parent_glo_code)"
    rows = cur.execute(
        f"""
        SELECT c.id, c.code, c.title_ar, c.bloom_level, c.sort_order,
               {agg_plo} AS plo_codes,
               {agg_glo} AS glo_codes
        FROM course_learning_outcomes c
        LEFT JOIN clo_plo_links l ON l.clo_id = c.id
        LEFT JOIN program_learning_outcomes o ON o.id = l.outcome_id
        WHERE c.program_course_id = ? AND COALESCE(c.is_active, 1) = 1
        GROUP BY c.id, c.code, c.title_ar, c.bloom_level, c.sort_order
        ORDER BY c.sort_order, c.code
        """,
        (int(program_course_id),),
    ).fetchall()
    out = []
    for r in rows or []:
        d = _row_dict(r) if hasattr(r, "keys") else {
            "id": r[0], "code": r[1], "title_ar": r[2], "bloom_level": r[3],
            "sort_order": r[4], "plo_codes": r[5], "glo_codes": r[6],
        }
        d["plo_codes"] = (d.get("plo_codes") or "").split(",") if d.get("plo_codes") else []
        d["glo_codes"] = [x for x in (d.get("glo_codes") or "").split(",") if x]
        out.append(d)
    return out


def list_clos_for_section(cur, section_id: int, conn=None) -> list[dict]:
    ctx = _section_context(cur, section_id, conn)
    if not ctx:
        return []
    pcid = int(ctx.get("program_course_id") or 0)
    pg = conn_is_postgresql(conn) if conn else False
    return list_clos_for_program_course(cur, pcid, pg)


def list_assessment_items(cur, section_id: int, semester: str) -> list[dict]:
    rows = cur.execute(
        """
        SELECT i.id, i.section_id, i.semester, i.clo_id, i.label, i.assessment_type,
               i.max_score, i.weight_percent, i.sort_order, i.is_active,
               c.code AS clo_code, c.title_ar AS clo_title_ar
        FROM section_assessment_items i
        JOIN course_learning_outcomes c ON c.id = i.clo_id
        WHERE i.section_id = ? AND i.semester = ? AND COALESCE(i.is_active, 1) = 1
        ORDER BY i.sort_order, i.id
        """,
        (int(section_id), semester),
    ).fetchall()
    return [_row_dict(r) for r in rows or []]


def save_assessment_items(
    cur,
    section_id: int,
    semester: str,
    items: list[dict],
) -> list[int]:
    """يستبدل بنود الشعبة النشطة بقائمة جديدة (حذف منطقي للقديم غير المذكور)."""
    now = datetime.datetime.utcnow().isoformat()
    keep_ids: list[int] = []
    for it in items or []:
        try:
            clo_id = int(it.get("clo_id"))
        except (TypeError, ValueError):
            continue
        label = (it.get("label") or "").strip()
        if not label:
            continue
        atype = (it.get("assessment_type") or "other").strip() or "other"
        try:
            max_score = float(it.get("max_score") or 100)
        except (TypeError, ValueError):
            max_score = 100.0
        try:
            weight = float(it.get("weight_percent") or 0)
        except (TypeError, ValueError):
            weight = 0.0
        try:
            sort_order = int(it.get("sort_order") or 0)
        except (TypeError, ValueError):
            sort_order = 0
        item_id = it.get("id")
        if item_id:
            try:
                iid = int(item_id)
            except (TypeError, ValueError):
                iid = 0
            if iid:
                cur.execute(
                    """
                    UPDATE section_assessment_items
                    SET clo_id=?, label=?, assessment_type=?, max_score=?, weight_percent=?,
                        sort_order=?, is_active=1
                    WHERE id=? AND section_id=? AND semester=?
                    """,
                    (clo_id, label, atype, max_score, weight, sort_order, iid, section_id, semester),
                )
                keep_ids.append(iid)
                continue
        if is_postgresql():
            row = cur.execute(
                """
                INSERT INTO section_assessment_items
                    (section_id, semester, clo_id, label, assessment_type, max_score, weight_percent, sort_order, is_active, created_at)
                VALUES (?,?,?,?,?,?,?,?,1,?)
                RETURNING id
                """,
                (section_id, semester, clo_id, label, atype, max_score, weight, sort_order, now),
            ).fetchone()
            keep_ids.append(int(row[0]))
        else:
            cur.execute(
                """
                INSERT INTO section_assessment_items
                    (section_id, semester, clo_id, label, assessment_type, max_score, weight_percent, sort_order, is_active, created_at)
                VALUES (?,?,?,?,?,?,?,?,1,?)
                """,
                (section_id, semester, clo_id, label, atype, max_score, weight, sort_order, now),
            )
            keep_ids.append(int(cur.lastrowid or 0))
    if keep_ids:
        ph = ",".join("?" * len(keep_ids))
        cur.execute(
            f"""
            UPDATE section_assessment_items SET is_active = 0
            WHERE section_id = ? AND semester = ? AND id NOT IN ({ph})
            """,
            (section_id, semester, *keep_ids),
        )
    else:
        cur.execute(
            "UPDATE section_assessment_items SET is_active = 0 WHERE section_id = ? AND semester = ?",
            (section_id, semester),
        )
    return keep_ids


def save_student_scores(cur, scores: list[dict]) -> int:
    now = datetime.datetime.utcnow().isoformat()
    saved = 0
    for sc in scores or []:
        try:
            item_id = int(sc.get("assessment_item_id"))
        except (TypeError, ValueError):
            continue
        sid = str((sc.get("student_id") or "")).strip()
        if not sid:
            continue
        absent = 1 if bool(sc.get("is_absent")) else 0
        raw = sc.get("score")
        score = None if raw is None or raw == "" else float(raw)
        if absent:
            score = 0.0
        if is_postgresql():
            cur.execute(
                """
                INSERT INTO student_assessment_scores (assessment_item_id, student_id, score, is_absent, updated_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT (assessment_item_id, student_id)
                DO UPDATE SET score=excluded.score, is_absent=excluded.is_absent, updated_at=excluded.updated_at
                """,
                (item_id, sid, score, absent, now),
            )
        else:
            cur.execute(
                """
                INSERT INTO student_assessment_scores (assessment_item_id, student_id, score, is_absent, updated_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(assessment_item_id, student_id)
                DO UPDATE SET score=excluded.score, is_absent=excluded.is_absent, updated_at=excluded.updated_at
                """,
                (item_id, sid, score, absent, now),
            )
        saved += 1
    return saved


def get_scores_matrix(cur, section_id: int, semester: str) -> dict[str, Any]:
    items = list_assessment_items(cur, section_id, semester)
    if not items:
        return {"items": [], "scores": []}
    ids = [int(i["id"]) for i in items]
    ph = ",".join("?" * len(ids))
    rows = cur.execute(
        f"""
        SELECT assessment_item_id, student_id, score, is_absent
        FROM student_assessment_scores
        WHERE assessment_item_id IN ({ph})
        """,
        tuple(ids),
    ).fetchall()
    scores = [_row_dict(r) for r in rows or []]
    return {"items": items, "scores": scores}


def recompute_clo_mastery(cur, section_id: int, semester: str) -> int:
    """يحسب إتقان كل طالب لكل CLO من بنود التقييم."""
    items = list_assessment_items(cur, section_id, semester)
    if not items:
        return 0
    by_clo: dict[int, list[dict]] = {}
    for it in items:
        by_clo.setdefault(int(it["clo_id"]), []).append(it)
    item_ids = [int(i["id"]) for i in items]
    ph = ",".join("?" * len(item_ids))
    rows = cur.execute(
        f"""
        SELECT assessment_item_id, student_id, score, is_absent
        FROM student_assessment_scores WHERE assessment_item_id IN ({ph})
        """,
        tuple(item_ids),
    ).fetchall()
    score_map: dict[tuple[int, str], float | None] = {}
    for r in rows or []:
        d = _row_dict(r)
        key = (int(d["assessment_item_id"]), str(d["student_id"]))
        if int(d.get("is_absent") or 0):
            score_map[key] = 0.0
        elif d.get("score") is not None:
            score_map[key] = float(d["score"])
        else:
            score_map[key] = None
    students = sorted({k[1] for k in score_map})
    if not students:
        pk = "id"
        rows2 = cur.execute(
            """
            SELECT DISTINCT r.student_id FROM registrations r
            WHERE r.course_name IN (
                SELECT course_name FROM schedule WHERE id = ?
            )
            """,
            (section_id,),
        ).fetchall()
        students = [str(r[0] if not hasattr(r, "keys") else r["student_id"]) for r in rows2 or []]
    now = datetime.datetime.utcnow().isoformat()
    updated = 0
    for sid in students:
        for clo_id, clo_items in by_clo.items():
            weighted_sum = 0.0
            weight_total = 0.0
            simple_sum = 0.0
            simple_n = 0
            for it in clo_items:
                iid = int(it["id"])
                mx = float(it.get("max_score") or 100) or 100.0
                w = float(it.get("weight_percent") or 0)
                sc = score_map.get((iid, sid))
                if sc is None:
                    continue
                pct = min(100.0, max(0.0, 100.0 * sc / mx))
                if w > 0:
                    weighted_sum += pct * w
                    weight_total += w
                simple_sum += pct
                simple_n += 1
            if weight_total > 0:
                mastery = round(weighted_sum / weight_total, 1)
            elif simple_n > 0:
                mastery = round(simple_sum / simple_n, 1)
            else:
                continue
            if is_postgresql():
                cur.execute(
                    """
                    INSERT INTO student_clo_mastery
                        (student_id, section_id, semester, clo_id, mastery_percent, source, updated_at)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT (student_id, section_id, semester, clo_id)
                    DO UPDATE SET mastery_percent=excluded.mastery_percent,
                                  source=excluded.source, updated_at=excluded.updated_at
                    """,
                    (sid, section_id, semester, clo_id, mastery, "computed", now),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO student_clo_mastery
                        (student_id, section_id, semester, clo_id, mastery_percent, source, updated_at)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(student_id, section_id, semester, clo_id)
                    DO UPDATE SET mastery_percent=excluded.mastery_percent,
                                  source=excluded.source, updated_at=excluded.updated_at
                    """,
                    (sid, section_id, semester, clo_id, mastery, "computed", now),
                )
            updated += 1
    return updated


def list_section_clo_assessments(
    cur, section_id: int, instructor_id: int, semester: str, conn=None
) -> list[dict]:
    pk = schedule_pk_column(conn) if conn else "id"
    rows = cur.execute(
        f"""
        SELECT c.id AS clo_id, c.code, c.title_ar,
               a.achievement_percent, COALESCE(a.notes,'') AS notes
        FROM course_learning_outcomes c
        JOIN schedule sch ON sch.program_course_id = c.program_course_id
        LEFT JOIN section_clo_assessments a
            ON a.clo_id = c.id AND a.section_id = ? AND a.instructor_id = ? AND a.semester = ?
        WHERE sch.{pk} = ? AND COALESCE(c.is_active, 1) = 1
        ORDER BY c.sort_order, c.code
        """,
        (section_id, instructor_id, semester, section_id),
    ).fetchall()
    return [_row_dict(r) for r in rows or []]


def save_section_clo_assessments(
    cur, section_id: int, instructor_id: int, semester: str, items: list[dict]
) -> None:
    now = datetime.datetime.utcnow().isoformat()
    for it in items or []:
        try:
            clo_id = int(it.get("clo_id"))
            pct = int(it.get("achievement_percent"))
        except (TypeError, ValueError):
            continue
        if pct < 0 or pct > 100:
            continue
        notes = (it.get("notes") or "").strip()
        if is_postgresql():
            cur.execute(
                """
                INSERT INTO section_clo_assessments
                    (section_id, instructor_id, semester, clo_id, achievement_percent, notes, updated_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT (section_id, instructor_id, semester, clo_id)
                DO UPDATE SET achievement_percent=excluded.achievement_percent,
                              notes=excluded.notes, updated_at=excluded.updated_at
                """,
                (section_id, instructor_id, semester, clo_id, pct, notes, now),
            )
        else:
            cur.execute(
                """
                INSERT INTO section_clo_assessments
                    (section_id, instructor_id, semester, clo_id, achievement_percent, notes, updated_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(section_id, instructor_id, semester, clo_id)
                DO UPDATE SET achievement_percent=excluded.achievement_percent,
                              notes=excluded.notes, updated_at=excluded.updated_at
                """,
                (section_id, instructor_id, semester, clo_id, pct, notes, now),
            )


def student_learning_outcomes_payload(conn, student_id: str) -> dict[str, Any]:
    ensure_plo_enhancement_schema(conn)
    ensure_outcome_assessment_schema(conn)
    cur = conn.cursor()
    pk = schedule_pk_column(conn)
    rows = cur.execute(
        f"""
        SELECT DISTINCT sc.{pk} AS section_id, sc.course_name, sc.semester,
               COALESCE(sc.program_course_id, 0) AS program_course_id
        FROM registrations r
        JOIN schedule sc ON sc.course_name = r.course_name
        WHERE r.student_id = ?
        ORDER BY sc.semester DESC, sc.course_name
        LIMIT 50
        """,
        (student_id,),
    ).fetchall()
    courses: list[dict] = []
    glo_agg: dict[str, list[float]] = {}
    for r in rows or []:
        d = _row_dict(r, ["section_id", "course_name", "semester", "program_course_id"])
        sid = int(d["section_id"])
        sem = (d.get("semester") or "").strip()
        pcid = int(d.get("program_course_id") or 0)
        clos = list_clos_for_program_course(cur, pcid, conn_is_postgresql(conn)) if pcid else []
        mastery_rows = cur.execute(
            """
            SELECT m.clo_id, m.mastery_percent, c.code, c.title_ar
            FROM student_clo_mastery m
            JOIN course_learning_outcomes c ON c.id = m.clo_id
            WHERE m.student_id = ? AND m.section_id = ? AND m.semester = ?
            """,
            (student_id, sid, sem),
        ).fetchall()
        mastery_by_clo = {int(x["clo_id"] if hasattr(x, "keys") else x[0]): x for x in mastery_rows or []}
        clo_items = []
        for c in clos:
            cid = int(c["id"])
            mrow = mastery_by_clo.get(cid)
            mp = None
            if mrow:
                mp = float(mrow["mastery_percent"] if hasattr(mrow, "keys") else mrow[1])
            glo_codes = c.get("glo_codes") or []
            for gc in glo_codes:
                if mp is not None:
                    glo_agg.setdefault(gc, []).append(mp)
            clo_items.append({
                "clo_id": cid,
                "code": c.get("code"),
                "title_ar": c.get("title_ar"),
                "mastery_percent": mp,
                "glo_codes": glo_codes,
                "plo_codes": c.get("plo_codes") or [],
            })
        courses.append({
            "section_id": sid,
            "course_name": d.get("course_name"),
            "semester": sem,
            "clos": clo_items,
        })
    glo_summary = []
    for code, vals in sorted(glo_agg.items()):
        avg = round(sum(vals) / len(vals), 1) if vals else None
        achieved = avg is not None and avg >= 70
        glo_summary.append({
            "glo_code": code,
            "average_mastery_percent": avg,
            "sample_count": len(vals),
            "achieved": achieved,
        })
    return {
        "student_id": student_id,
        "courses": courses,
        "glo_summary": glo_summary,
    }


def department_outcomes_dashboard(conn, department_id: int) -> dict[str, Any]:
    ensure_plo_enhancement_schema(conn)
    ensure_outcome_assessment_schema(conn)
    cur = conn.cursor()
    pk = schedule_pk_column(conn)
    programs = cur.execute(
        """
        SELECT id, COALESCE(name_ar, name_en, code, '') AS name
        FROM programs
        WHERE department_id = ? AND COALESCE(is_active, 1) = 1
        ORDER BY name_ar, code
        """,
        (int(department_id),),
    ).fetchall()
    program_ids = [int(p[0] if not hasattr(p, "keys") else p["id"]) for p in programs or []]
    domain_heatmap: list[dict] = []
    glo_rates: list[dict] = []
    if program_ids:
        ph = ",".join("?" * len(program_ids))
        dom_rows = cur.execute(
            f"""
            SELECT COALESCE(o.domain, '') AS domain,
                   AVG(COALESCE(m.mastery_percent, a.achievement_percent, silo.achievement_percent)) AS avg_pct,
                   COUNT(DISTINCT o.id) AS plo_count,
                   COUNT(*) AS sample_n
            FROM program_learning_outcomes o
            LEFT JOIN clo_plo_links l ON l.outcome_id = o.id
            LEFT JOIN course_learning_outcomes c ON c.id = l.clo_id
            LEFT JOIN student_clo_mastery m ON m.clo_id = c.id
            LEFT JOIN section_clo_assessments a ON a.clo_id = c.id
            LEFT JOIN section_ilo_assessments silo ON silo.outcome_id = o.id
            WHERE o.program_id IN ({ph}) AND COALESCE(o.is_active, 1) = 1
            GROUP BY COALESCE(o.domain, '')
            """,
            tuple(program_ids),
        ).fetchall()
        dom_by_key: dict[str, dict] = {}
        for r in dom_rows or []:
            d = _row_dict(r)
            raw_dom = (d.get("domain") or "").strip()
            dom = normalize_outcome_domain(raw_dom)
            avg = d.get("avg_pct")
            entry = {
                "domain": dom,
                "domain_label": DOMAIN_LABELS_AR.get(dom, dom),
                "achievement_percent": round(float(avg), 1) if avg is not None else None,
                "plo_count": int(d.get("plo_count") or 0),
                "sample_count": int(d.get("sample_n") or 0),
            }
            dom_by_key[dom] = entry
        for dom in DOMAIN_ORDER:
            domain_heatmap.append(
                dom_by_key.get(dom)
                or {
                    "domain": dom,
                    "domain_label": DOMAIN_LABELS_AR.get(dom, dom),
                    "achievement_percent": None,
                    "plo_count": 0,
                    "sample_count": 0,
                }
            )
        rows = cur.execute(
            f"""
            SELECT UPPER(TRIM(COALESCE(o.parent_glo_code,''))) AS glo_code,
                   AVG(COALESCE(m.mastery_percent, a.achievement_percent)) AS avg_pct,
                   COUNT(*) AS n
            FROM program_learning_outcomes o
            LEFT JOIN clo_plo_links l ON l.outcome_id = o.id
            LEFT JOIN course_learning_outcomes c ON c.id = l.clo_id
            LEFT JOIN student_clo_mastery m ON m.clo_id = c.id
            LEFT JOIN section_clo_assessments a ON a.clo_id = c.id
            WHERE o.program_id IN ({ph})
              AND COALESCE(o.parent_glo_code,'') <> ''
              AND COALESCE(o.is_active,1)=1
            GROUP BY UPPER(TRIM(COALESCE(o.parent_glo_code,'')))
            HAVING UPPER(TRIM(COALESCE(o.parent_glo_code,''))) <> ''
            ORDER BY 1
            """,
            tuple(program_ids),
        ).fetchall()
        for r in rows or []:
            d = _row_dict(r)
            glo_rates.append({
                "glo_code": d.get("glo_code"),
                "achievement_percent": round(float(d["avg_pct"]), 1) if d.get("avg_pct") is not None else None,
                "sample_count": int(d.get("n") or 0),
            })
    weak_list_raw = []
    if program_ids:
        weak_courses = cur.execute(
            f"""
            SELECT sc.course_name, sc.{pk} AS section_id, sc.semester,
                   AVG(COALESCE(m.mastery_percent, a.achievement_percent)) AS avg_mastery,
                   COUNT(DISTINCT m.student_id) AS students_n
            FROM schedule sc
            JOIN program_courses pc ON pc.id = sc.program_course_id
            LEFT JOIN student_clo_mastery m ON m.section_id = sc.{pk}
            LEFT JOIN section_clo_assessments a ON a.section_id = sc.{pk}
            WHERE pc.program_id IN ({",".join("?" * len(program_ids))})
            GROUP BY sc.{pk}, sc.course_name, sc.semester
            HAVING AVG(COALESCE(m.mastery_percent, a.achievement_percent)) IS NOT NULL
               AND AVG(COALESCE(m.mastery_percent, a.achievement_percent)) < 70
            ORDER BY 3 ASC
            LIMIT 15
            """,
            tuple(program_ids),
        ).fetchall()
        weak_list_raw = weak_courses or []
    weak_list = []
    for r in weak_list_raw:
        d = _row_dict(r)
        avg_m = float(d["avg_mastery"]) if d.get("avg_mastery") is not None else None
        weak_list.append({
            "course_name": d.get("course_name"),
            "section_id": d.get("section_id"),
            "semester": d.get("semester"),
            "avg_mastery_percent": round(avg_m, 1) if avg_m is not None else None,
            "students_count": int(d.get("students_n") or 0),
        })
    recommendations: list[dict] = []
    for dh in domain_heatmap:
        pct = dh.get("achievement_percent")
        label = dh.get("domain_label") or dh.get("domain")
        if pct is not None and pct < 70:
            recommendations.append({
                "type": "domain_low",
                "priority": "high",
                "domain": dh.get("domain"),
                "domain_label": label,
                "message_ar": (
                    f"مجال «{label}»: متوسط التحقق {pct}% — راجع مصفوفة التغطية (I/R/M) "
                    f"والمقررات التي تُقيّم هذا المجال."
                ),
            })
        elif pct is None and int(dh.get("plo_count") or 0) > 0:
            recommendations.append({
                "type": "domain_no_data",
                "priority": "medium",
                "domain": dh.get("domain"),
                "domain_label": label,
                "message_ar": (
                    f"مجال «{label}»: لا بيانات تقييم بعد — فعّلوا إدخال CLO في مسودات الدرجات "
                    f"أو تقييم الشعبة في مقرراتي."
                ),
            })
    for g in glo_rates:
        pct = g.get("achievement_percent")
        if pct is not None and pct < 70:
            recommendations.append({
                "type": "glo_low",
                "priority": "medium",
                "message_ar": f"مخرج كلية {g['glo_code']}: متوسط التحقق {pct}% (عبر PLO المرتبطة).",
                "glo_code": g["glo_code"],
            })
    for wc in weak_list[:8]:
        recommendations.append({
            "type": "weak_course",
            "priority": "medium",
            "message_ar": f"مقرر {wc['course_name']} (شعبة {wc['section_id']}): متوسط إتقان CLO {wc['avg_mastery_percent']}%.",
            "section_id": wc.get("section_id"),
            "course_name": wc.get("course_name"),
        })
    return {
        "department_id": int(department_id),
        "programs": [_row_dict(p, ["id", "name"]) if not hasattr(p, "keys") else dict(p) for p in programs or []],
        "domain_heatmap": domain_heatmap,
        "domain_labels": dict(DOMAIN_LABELS_AR),
        "domain_colors": dict(DOMAIN_COLORS),
        "glo_achievement": glo_rates,
        "weak_courses": weak_list,
        "recommendations": recommendations,
    }
