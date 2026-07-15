"""
حساب مؤشرات الاعتماد المؤسسي آلياً من بيانات ScheduleOptimizer (هـ-2).

مرجع المعايير: المركز الوطني لضمان الجودة واعتماد المؤسسات التعليمية والتدريبية — ليبيا
https://qaa.ly/%d8%a7%d9%84%d8%aa%d8%b9%d9%84%d9%8a%d9%85-%d8%a7%d9%84%d8%ac%d8%a7%d9%85%d8%b9%d9%8a/
"""

from __future__ import annotations

import datetime
from typing import Any

from backend.database.database import table_exists
from backend.services.quality_metrics import (
    _avg_eval_score,
    _avg_ilo,
    _faculty_qualifications,
    _graduation_proxy,
    _reports_completion,
    _row_val,
    _student_faculty_ratio,
    compute_quality_metrics,
    term_label_from_conn,
)

QAA_HIGHER_ED_URL = (
    "https://qaa.ly/%d8%a7%d9%84%d8%aa%d8%b9%d9%84%d9%8a%d9%85-%d8%a7%d9%84%d8%ac%d8%a7%d9%85%d8%b9%d9%8a/"
)

# أدوار التنسيق (تشغيلياً: رئيس القسم أو من يكلفه — غير مفعلة كصلاحيات منفصلة بعد)
ACCREDITATION_COORDINATOR_ROLES = (
    {
        "key": "qa_coordinator",
        "title_ar": "منسق ضمان الجودة بالقسم",
        "holder_ar": "عضو هيئة التدريس (يُكلف من رئيس القسم)",
        "active_in_system": True,
    },
    {
        "key": "community_coordinator",
        "title_ar": "منسق خدمة المجتمع والبيئة",
        "holder_ar": "رئيس القسم أو من يكلفه (الدور غير مفعّل في النظام)",
        "active_in_system": False,
    },
    {
        "key": "research_coordinator",
        "title_ar": "منسق البحث العلمي بالقسم",
        "holder_ar": "رئيس القسم أو من يكلفه (الدور غير مفعّل في النظام)",
        "active_in_system": False,
    },
)

AUTO_INDICATOR_CODES = frozenset(
    {
        "HR-01-1",
        "HR-02-1",
        "GV-02-1",
        "QA-01-1",
        "QA-02-1",
        "QA-03-1",
        "SS-01-1",
        "SS-02-1",
        "FF-01-1",
    }
)

THRESHOLDS = {
    "HR-01-1": {"met": 70.0, "partial": 50.0},
    "QA-02-1": {"met": 80.0, "partial": 60.0},
    "QA-03-1": {"met": 70.0, "partial": 50.0},
    "SS-01-1": {"met": 75.0, "partial": 60.0},
    "SS-02-1": {"met": 70.0, "partial": 50.0},
    "GV-02-1": {"met": 80.0, "partial": 50.0},
    "FF-01-1": {"met": 75.0, "partial": 50.0},
}


def suggest_compliance_status(score_percent: float | None, *, met: float = 70.0, partial: float = 50.0) -> str:
    if score_percent is None:
        return "in_progress"
    s = float(score_percent)
    if s >= met:
        return "met"
    if s >= partial:
        return "partial"
    if s > 0:
        return "gap"
    return "in_progress"


def _ratio_to_score(ratio: float | None) -> float | None:
    """كلما انخفضت نسبة طالب:أستاذ كانت النتيجة أفضل."""
    if ratio is None:
        return None
    r = float(ratio)
    if r <= 15:
        return 100.0
    if r <= 20:
        return 90.0
    if r <= 25:
        return 75.0
    if r <= 35:
        return 55.0
    if r <= 45:
        return 35.0
    return 20.0


def _policy_approval_score(cur, department_id: int | None) -> tuple[float | None, str]:
    if department_id is None:
        return None, "يتطلب نطاق قسم — غير متاح على مستوى الكلية"
    if not table_exists(cur.connection, "department_graduation_policies"):
        return None, "جدول سياسات التخرج غير موجود"
    row = cur.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) AS approved
        FROM department_graduation_policies
        WHERE department_id = ?
        """,
        (int(department_id),),
    ).fetchone()
    total = int(_row_val(row, 0, "total") or _row_val(row, 0) or 0)
    approved = int(_row_val(row, 1, "approved") or _row_val(row, 1) or 0)
    if total <= 0:
        return 0.0, "لا توجد سياسات مقترحة للقسم بعد"
    pct = min(100.0, (approved / total) * 100.0)
    return pct, f"سياسات معتمدة: {approved} من {total}"


def _snapshot_score(cur, semester: str, department_id: int | None) -> tuple[float | None, str]:
    if not table_exists(cur.connection, "quality_metrics_snapshots"):
        return None, "جدول لقطات الجودة غير موجود"
    dept_clause = "department_id IS NULL" if department_id is None else "department_id = ?"
    params: list[Any] = [semester]
    if department_id is not None:
        params.append(int(department_id))
    cnt_row = cur.execute(
        f"""
        SELECT COUNT(*), MAX(overall_accreditation_score)
        FROM quality_metrics_snapshots
        WHERE semester = ? AND {dept_clause}
        """,
        tuple(params),
    ).fetchone()
    cnt = int(_row_val(cnt_row, 0) or 0)
    latest = _row_val(cnt_row, 1)
    if cnt <= 0:
        return 0.0, "لا توجد لقطة محفوظة لهذا الفصل — يُنصح بحفظ لقطة من لوحة الجودة"
    score = float(latest) if latest is not None else 100.0
    return min(100.0, score), f"لقطات محفوظة: {cnt} — آخر درجة {score:.1f}"


def compute_indicator_auto(
    conn,
    indicator_code: str,
    *,
    semester: str,
    department_id: int | None = None,
) -> dict[str, Any]:
    """حساب مؤشر واحد من النظام."""
    code = (indicator_code or "").strip().upper()
    cur = conn.cursor()
    sem = (semester or term_label_from_conn(conn)).strip()

    if code not in AUTO_INDICATOR_CODES:
        return {
            "indicator_code": code,
            "computable": False,
            "message_ar": "المؤشر ليس آلياً أو مختلطاً في الكتالوج الحالي",
        }

    score: float | None = None
    detail = ""
    th = THRESHOLDS.get(code, {"met": 70.0, "partial": 50.0})

    if code == "HR-01-1":
        score = _faculty_qualifications(cur, department_id, sem)
        detail = f"نسبة المؤهلات العليا: {score:.1f}%"
    elif code == "HR-02-1":
        ratio = _student_faculty_ratio(cur, department_id)
        score = _ratio_to_score(ratio)
        if ratio is not None:
            detail = f"نسبة طالب:أستاذ ≈ 1:{ratio}"
        else:
            detail = "لا يوجد أعضاء هيئة تدريس نشطون في النطاق"
    elif code == "GV-02-1":
        score, detail = _policy_approval_score(cur, department_id)
    elif code == "QA-01-1":
        score, detail = _snapshot_score(cur, sem, department_id)
        if score is not None and score <= 0:
            metrics = compute_quality_metrics(conn, semester=sem, department_id=department_id)
            score = float(metrics.get("overall_accreditation_score") or 0)
            detail += f" — درجة لوحة الجودة الحالية: {score:.1f}"
    elif code == "QA-02-1":
        score = _reports_completion(conn, cur, sem, department_id)
        detail = f"اكتمال تقارير إقفال المقررات: {score:.1f}%"
        try:
            from backend.services.survey_accreditation import survey_supplementary_notes

            extra = survey_supplementary_notes(
                conn, semester=sem, department_id=department_id, indicator_code=code
            )
            if extra:
                detail += f" — استبيانات داعمة: {extra}"
        except Exception:
            pass
    elif code == "QA-03-1":
        score = _avg_ilo(conn, cur, sem, department_id)
        detail = f"متوسط تحقق مخرجات التعلم: {score:.1f}%"
        try:
            from backend.services.survey_accreditation import survey_supplementary_notes

            extra = survey_supplementary_notes(
                conn, semester=sem, department_id=department_id, indicator_code=code
            )
            if extra:
                detail += f" — استبيانات داعمة: {extra}"
        except Exception:
            pass
    elif code == "SS-01-1":
        score = _avg_eval_score(conn, cur, sem, department_id)
        detail = f"رضا الطلبة (استبيان المقرر): {score:.1f}%"
        try:
            from backend.services.survey_accreditation import survey_supplementary_notes

            extra = survey_supplementary_notes(
                conn, semester=sem, department_id=department_id, indicator_code=code
            )
            if extra:
                detail += f" — استبيانات داعمة: {extra}"
        except Exception:
            pass
    elif code == "SS-02-1":
        score = _graduation_proxy(cur, department_id)
        detail = f"مؤشر التقدم الأكاديمي (تقريبي): {score:.1f}%"
        try:
            from backend.services.survey_accreditation import survey_supplementary_notes

            extra = survey_supplementary_notes(
                conn, semester=sem, department_id=department_id, indicator_code=code
            )
            if extra:
                detail += f" — استبيانات داعمة: {extra}"
        except Exception:
            pass
    elif code == "FF-01-1":
        from backend.services.survey_accreditation import compute_hybrid_infrastructure_rating

        score, detail = compute_hybrid_infrastructure_rating(
            conn, semester=sem, department_id=department_id
        )

    status = suggest_compliance_status(
        score, met=th["met"], partial=th["partial"]
    )
    notes = f"[آلي من النظام] {detail}".strip()
    if code == "GV-02-1" and department_id is None:
        status = "in_progress"
        notes += " — يُقيَّم على مستوى القسم عند تسجيل دخول رئيس القسم."

    return {
        "indicator_code": code,
        "computable": score is not None or code in ("QA-01-1", "GV-02-1"),
        "score_percent": round(score, 1) if score is not None else None,
        "compliance_status": status,
        "notes_ar": notes,
        "detail_ar": detail,
        "qaa_reference_url": QAA_HIGHER_ED_URL,
    }


def list_auto_indicator_rows(cur, catalog_version: str) -> list[dict[str, Any]]:
    rows = cur.execute(
        """
        SELECT i.id, i.code, i.source_type, s.code AS standard_code
        FROM accreditation_indicators i
        INNER JOIN accreditation_standards s ON s.id = i.standard_id
        WHERE s.catalog_version = ?
          AND COALESCE(i.is_active, 1) = 1
          AND i.source_type IN ('auto', 'hybrid')
        ORDER BY i.id
        """,
        (catalog_version,),
    ).fetchall()
    out = []
    for r in rows or []:
        if hasattr(r, "keys"):
            out.append({k: r[k] for k in r.keys()})
        else:
            out.append(
                {
                    "id": r[0],
                    "code": r[1],
                    "source_type": r[2],
                    "standard_code": r[3],
                }
            )
    return out


def _upsert_auto_assessment(
    cur,
    *,
    semester: str,
    department_id: int | None,
    indicator_id: int,
    score_percent: float | None,
    compliance_status: str,
    notes: str,
    actor: str,
) -> None:
    now = datetime.datetime.utcnow().isoformat()
    if department_id is None:
        cur.execute(
            """
            DELETE FROM accreditation_assessments
            WHERE semester = ? AND indicator_id = ? AND department_id IS NULL
            """,
            (semester, int(indicator_id)),
        )
        cur.execute(
            """
            INSERT INTO accreditation_assessments
            (semester, department_id, indicator_id, score_percent, compliance_status,
             notes, updated_at, updated_by)
            VALUES (?, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (semester, int(indicator_id), score_percent, compliance_status, notes, now, actor),
        )
    else:
        cur.execute(
            """
            INSERT INTO accreditation_assessments
            (semester, department_id, indicator_id, score_percent, compliance_status,
             notes, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (semester, department_id, indicator_id) DO UPDATE SET
                score_percent = excluded.score_percent,
                compliance_status = excluded.compliance_status,
                notes = excluded.notes,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            (
                semester,
                int(department_id),
                int(indicator_id),
                score_percent,
                compliance_status,
                notes,
                now,
                actor,
            ),
        )


def apply_auto_assessments(
    conn,
    *,
    semester: str | None = None,
    department_id: int | None = None,
    actor: str = "",
    catalog_version: str | None = None,
    only_not_started: bool = True,
    indicator_codes: list[str] | None = None,
) -> dict[str, Any]:
    """
    يحسب ويحفظ تقييمات المؤشرات الآلية/المختلطة.
    only_not_started: لا يستبدل تقييماً يدوياً (ملاحظات لا تبدأ بـ [آلي])
    """
    from backend.core.accreditation_catalog import (
        QAA_INST_CATALOG_VERSION,
        ensure_accreditation_catalog,
        resolve_catalog_version,
    )
    from backend.services.institutional_accreditation import _ensure_accreditation_tables

    _ensure_accreditation_tables(conn)
    ensure_accreditation_catalog(conn)
    cur = conn.cursor()
    sem = (semester or term_label_from_conn(conn)).strip()
    cat_ver = resolve_catalog_version(conn, catalog_version or QAA_INST_CATALOG_VERSION)

    existing = {}
    dept_clause = "department_id IS NULL" if department_id is None else "department_id = ?"
    params: list[Any] = [sem]
    if department_id is not None:
        params.append(int(department_id))
    for row in cur.execute(
        f"""
        SELECT indicator_id, compliance_status, notes
        FROM accreditation_assessments
        WHERE semester = ? AND {dept_clause}
        """,
        tuple(params),
    ).fetchall():
        iid = int(_row_val(row, 0, "indicator_id") or row[0])
        notes = str(_row_val(row, 2, "notes") or row[2] if len(row) > 2 else "")
        existing[iid] = {
            "status": _row_val(row, 1, "compliance_status") or row[1],
            "notes": notes,
        }

    codes_filter = {c.strip().upper() for c in (indicator_codes or []) if c}
    results: list[dict[str, Any]] = []
    updated = 0
    skipped = 0

    for row in list_auto_indicator_rows(cur, cat_ver):
        code = str(row.get("code") or "").strip().upper()
        if codes_filter and code not in codes_filter:
            continue
        if code not in AUTO_INDICATOR_CODES:
            skipped += 1
            results.append({"indicator_code": code, "action": "skipped", "reason": "not_auto"})
            continue

        iid = int(row["id"])
        prev = existing.get(iid)
        if only_not_started and prev:
            n = (prev.get("notes") or "").strip()
            st = prev.get("status") or "not_started"
            if st != "not_started" and not n.startswith("[آلي"):
                skipped += 1
                results.append({"indicator_code": code, "action": "skipped", "reason": "manual_keep"})
                continue

        computed = compute_indicator_auto(
            conn, code, semester=sem, department_id=department_id
        )
        if not computed.get("computable") and computed.get("score_percent") is None:
            skipped += 1
            results.append(
                {
                    "indicator_code": code,
                    "action": "skipped",
                    "reason": computed.get("notes_ar") or "not_computable",
                }
            )
            continue

        _upsert_auto_assessment(
            cur,
            semester=sem,
            department_id=department_id,
            indicator_id=iid,
            score_percent=computed.get("score_percent"),
            compliance_status=computed.get("compliance_status") or "in_progress",
            notes=computed.get("notes_ar") or "",
            actor=actor,
        )
        updated += 1
        results.append({**computed, "action": "updated", "indicator_id": iid})

    conn.commit()
    return {
        "status": "ok",
        "semester": sem,
        "department_id": department_id,
        "updated_count": updated,
        "skipped_count": skipped,
        "results": results,
        "qaa_reference_url": QAA_HIGHER_ED_URL,
        "coordinator_roles": ACCREDITATION_COORDINATOR_ROLES,
    }
