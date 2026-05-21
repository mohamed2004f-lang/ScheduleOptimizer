"""إدخالات يدوية موسّعة وخطط تحسين الاعتماد المؤسسي (هـ-4)."""

from __future__ import annotations

import datetime
from typing import Any

from backend.core.accreditation_catalog import resolve_catalog_version
from backend.database.database import is_postgresql, table_exists
from backend.services.accreditation_metrics import suggest_compliance_status
from backend.services.quality_metrics import _row_val

PLAN_STATUS_LABELS = {
    "planned": "مخطط",
    "in_progress": "قيد التنفيذ",
    "done": "منجز",
    "cancelled": "ملغى",
}

PLAN_PRIORITY_LABELS = {
    "low": "منخفض",
    "medium": "متوسط",
    "high": "عالي",
}

MANUAL_SECTIONS: list[dict[str, Any]] = [
    {
        "key": "facilities",
        "title_ar": "المرافق",
        "fields": [
            {"key": "classrooms_count", "label_ar": "عدد القاعات الدراسية", "type": "int"},
            {"key": "labs_count", "label_ar": "عدد المعامل", "type": "int"},
            {"key": "facilities_rating", "label_ar": "تقييم حالة المرافق (1–5)", "type": "float"},
            {"key": "facilities_notes", "label_ar": "ملاحظات", "type": "text"},
        ],
    },
    {
        "key": "finance",
        "title_ar": "الموارد المالية",
        "fields": [
            {"key": "annual_budget_million", "label_ar": "الميزانية السنوية (مليون)", "type": "float"},
            {"key": "budget_execution_percent", "label_ar": "نسبة تنفيذ الميزانية %", "type": "float"},
            {"key": "finance_notes", "label_ar": "ملاحظات", "type": "text"},
        ],
    },
    {
        "key": "governance",
        "title_ar": "الحوكمة",
        "fields": [
            {"key": "governance_meetings_count", "label_ar": "اجتماعات اللجان (الفصل)", "type": "int"},
            {"key": "policies_active_count", "label_ar": "سياسات نشطة معتمدة", "type": "int"},
            {"key": "governance_notes", "label_ar": "ملاحظات", "type": "text"},
        ],
    },
    {
        "key": "community",
        "title_ar": "المجتمع والبحث",
        "fields": [
            {"key": "community_events_count", "label_ar": "أنشطة مجتمعية", "type": "int"},
            {"key": "community_beneficiaries_count", "label_ar": "المستفيدون", "type": "int"},
            {"key": "research_outputs_count", "label_ar": "مخرجات بحثية", "type": "int"},
            {"key": "community_notes", "label_ar": "ملاحظات", "type": "text"},
        ],
    },
]

_ALL_FIELD_KEYS = {
    f["key"]
    for sec in MANUAL_SECTIONS
    for f in sec["fields"]
}


def _ensure_manual_tables(conn) -> None:
    from backend.database.database import TABLES_SCHEMA

    for key in ("accreditation_manual_inputs", "accreditation_improvement_plans"):
        if table_exists(conn, key):
            continue
        ddl = TABLES_SCHEMA.get(key)
        if ddl and hasattr(conn, "executescript"):
            conn.executescript(ddl)
            conn.commit()


def _row_dict(row, keys: list[str] | None = None) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    if keys:
        return {keys[i]: row[i] for i in range(min(len(keys), len(row)))}
    return {}


def get_manual_inputs(conn, semester: str, department_id: int | None) -> dict[str, Any]:
    _ensure_manual_tables(conn)
    cur = conn.cursor()
    dept_clause = "department_id IS NULL" if department_id is None else "department_id = ?"
    params: list[Any] = [semester]
    if department_id is not None:
        params.append(int(department_id))
    cur.execute(
        f"SELECT * FROM accreditation_manual_inputs WHERE semester = ? AND {dept_clause}",
        tuple(params),
    )
    row = cur.fetchone()
    data = _row_dict(row, [d[0] for d in (cur.description or ())])
    values = {k: data.get(k) for k in _ALL_FIELD_KEYS}
    sections = []
    for sec in MANUAL_SECTIONS:
        sec_vals = {f["key"]: values.get(f["key"]) for f in sec["fields"]}
        sections.append({**sec, "values": sec_vals})
    return {
        "semester": semester,
        "department_id": department_id,
        "sections": sections,
        "updated_at": data.get("updated_at"),
        "updated_by": data.get("updated_by"),
    }


def save_manual_inputs(
    conn,
    *,
    semester: str,
    department_id: int | None,
    payload: dict[str, Any],
    actor: str,
) -> dict[str, Any]:
    _ensure_manual_tables(conn)
    now = datetime.datetime.utcnow().isoformat()
    vals: dict[str, Any] = {}
    for key in _ALL_FIELD_KEYS:
        if key not in payload:
            continue
        raw = payload[key]
        if raw is None or raw == "":
            vals[key] = None
            continue
        if key.endswith("_notes"):
            vals[key] = str(raw).strip()[:2000]
        elif "rating" in key or "percent" in key or "million" in key:
            vals[key] = float(raw)
        else:
            vals[key] = int(float(raw))

    cur = conn.cursor()
    if department_id is None:
        cur.execute(
            f"DELETE FROM accreditation_manual_inputs WHERE semester = ? AND department_id IS NULL",
            (semester,),
        )
        base_cols = ["semester", "department_id"] + list(vals.keys()) + ["updated_at", "updated_by"]
        cur.execute(
            f"""
            INSERT INTO accreditation_manual_inputs ({", ".join(base_cols)})
            VALUES ({", ".join(["?"] * len(base_cols))})
            """,
            (
                semester,
                None,
                *[vals[k] for k in vals],
                now,
                actor,
            ),
        )
    else:
        if is_postgresql():
            set_parts = [f"{k} = EXCLUDED.{k}" for k in vals]
            set_parts += ["updated_at = EXCLUDED.updated_at", "updated_by = EXCLUDED.updated_by"]
            cur.execute(
                f"""
                INSERT INTO accreditation_manual_inputs
                (semester, department_id, {", ".join(vals.keys())}, updated_at, updated_by)
                VALUES (?, ?, {", ".join(["?"] * len(vals))}, ?, ?)
                ON CONFLICT (semester, department_id) DO UPDATE SET
                {", ".join(set_parts)}
                """,
                (
                    semester,
                    int(department_id),
                    *[vals[k] for k in vals],
                    now,
                    actor,
                ),
            )
        else:
            cur.execute(
                f"""
                INSERT INTO accreditation_manual_inputs
                (semester, department_id, {", ".join(vals.keys())}, updated_at, updated_by)
                VALUES (?, ?, {", ".join(["?"] * len(vals))}, ?, ?)
                ON CONFLICT (semester, department_id) DO UPDATE SET
                {", ".join(f"{k}=excluded.{k}" for k in vals)},
                updated_at=excluded.updated_at,
                updated_by=excluded.updated_by
                """,
                (
                    semester,
                    int(department_id),
                    *[vals[k] for k in vals],
                    now,
                    actor,
                ),
            )
    conn.commit()
    bundle = get_manual_inputs(conn, semester, department_id)
    sync = sync_manual_inputs_to_indicators(
        conn,
        semester=semester,
        department_id=department_id,
        vals=vals,
        actor=actor,
        catalog_version=payload.get("catalog_version"),
    )
    bundle["indicator_sync"] = sync
    return bundle


def list_improvement_plans(
    conn, semester: str, department_id: int | None
) -> list[dict[str, Any]]:
    _ensure_manual_tables(conn)
    cur = conn.cursor()
    dept_clause = "department_id IS NULL" if department_id is None else "department_id = ?"
    params: list[Any] = [semester]
    if department_id is not None:
        params.append(int(department_id))
    cur.execute(
        f"""
        SELECT p.id, p.semester, p.department_id, p.indicator_id, p.title_ar, p.action_ar,
               p.target_date, p.status, p.priority, p.owner_ar, p.notes,
               p.updated_at, p.updated_by, i.code AS indicator_code
        FROM accreditation_improvement_plans p
        LEFT JOIN accreditation_indicators i ON i.id = p.indicator_id
        WHERE p.semester = ? AND {dept_clause} AND COALESCE(p.is_active, 1) = 1
        ORDER BY
            CASE p.status WHEN 'in_progress' THEN 0 WHEN 'planned' THEN 1 WHEN 'done' THEN 2 ELSE 3 END,
            p.id DESC
        """,
        tuple(params),
    )
    rows = cur.fetchall() or []
    keys = [d[0] for d in (cur.description or ())]
    out = []
    for r in rows:
        d = _row_dict(r, keys)
        st = d.get("status") or "planned"
        d["status_label"] = PLAN_STATUS_LABELS.get(st, st)
        pr = d.get("priority") or "medium"
        d["priority_label"] = PLAN_PRIORITY_LABELS.get(pr, pr)
        out.append(d)
    return out


def save_improvement_plan(
    conn,
    *,
    semester: str,
    department_id: int | None,
    plan_id: int | None,
    data: dict[str, Any],
    actor: str,
) -> dict[str, Any]:
    _ensure_manual_tables(conn)
    title = (data.get("title_ar") or "").strip()
    if not title:
        raise ValueError("عنوان الخطة مطلوب")
    status = (data.get("status") or "planned").strip().lower()
    if status not in PLAN_STATUS_LABELS:
        raise ValueError("حالة غير صالحة")
    priority = (data.get("priority") or "medium").strip().lower()
    if priority not in PLAN_PRIORITY_LABELS:
        priority = "medium"
    now = datetime.datetime.utcnow().isoformat()
    iid = data.get("indicator_id")
    indicator_id = int(iid) if iid not in (None, "", 0) else None

    cur = conn.cursor()
    fields = (
        title,
        (data.get("action_ar") or "").strip()[:2000],
        (data.get("target_date") or "").strip()[:32],
        status,
        priority,
        (data.get("owner_ar") or "").strip()[:200],
        (data.get("notes") or "").strip()[:2000],
        now,
        actor,
    )

    if plan_id:
        cur.execute(
            """
            UPDATE accreditation_improvement_plans SET
                indicator_id = ?, title_ar = ?, action_ar = ?, target_date = ?,
                status = ?, priority = ?, owner_ar = ?, notes = ?,
                updated_at = ?, updated_by = ?
            WHERE id = ? AND COALESCE(is_active, 1) = 1
            """,
            (indicator_id, *fields, int(plan_id)),
        )
        if not cur.rowcount:
            raise ValueError("الخطة غير موجودة")
        conn.commit()
        return {"id": int(plan_id)}

    cur.execute(
        """
        INSERT INTO accreditation_improvement_plans (
            semester, department_id, indicator_id, title_ar, action_ar, target_date,
            status, priority, owner_ar, notes, updated_at, updated_by, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (semester, department_id, indicator_id, *fields),
    )
    new_id = int(cur.lastrowid or 0)
    if is_postgresql():
        row = cur.execute(
            "SELECT id FROM accreditation_improvement_plans ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            new_id = int(_row_val(row, 0, "id") or new_id)
    conn.commit()
    return {"id": new_id}


def _indicator_id_by_code(conn, code: str, catalog_version: str) -> int | None:
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT i.id FROM accreditation_indicators i
        INNER JOIN accreditation_standards s ON s.id = i.standard_id
        WHERE i.code = ? AND s.catalog_version = ?
          AND COALESCE(i.is_active, 1) = 1 AND COALESCE(s.is_active, 1) = 1
        """,
        (code.strip().upper(), catalog_version),
    ).fetchone()
    if not row:
        return None
    return int(_row_val(row, 0, "id") or 0) or None


def _upsert_manual_assessment(
    conn,
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
    note = (notes or "")[:2000]
    cur = conn.cursor()
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
            (semester, int(indicator_id), score_percent, compliance_status, note, now, actor),
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
                note,
                now,
                actor,
            ),
        )


def sync_manual_inputs_to_indicators(
    conn,
    *,
    semester: str,
    department_id: int | None,
    vals: dict[str, Any],
    actor: str,
    catalog_version: str | None = None,
) -> list[dict[str, Any]]:
    """ربط حقول هـ-4 بمؤشرات يدوية في الخريطة."""
    cat_ver = resolve_catalog_version(conn, catalog_version)
    actor = actor or "system:manual_sync"
    results: list[dict[str, Any]] = []

    def _sync(code: str, score: float | None, note_ar: str, *, met: float = 70.0, partial: float = 50.0):
        iid = _indicator_id_by_code(conn, code, cat_ver)
        if not iid:
            results.append({"indicator_code": code, "action": "skipped", "reason": "not_in_catalog"})
            return
        status = suggest_compliance_status(score, met=met, partial=partial)
        _upsert_manual_assessment(
            conn,
            semester=semester,
            department_id=department_id,
            indicator_id=iid,
            score_percent=score,
            compliance_status=status,
            notes=f"[من الإدخال اليدوي] {note_ar}"[:2000],
            actor=actor,
        )
        results.append(
            {
                "indicator_code": code,
                "action": "updated",
                "score_percent": score,
                "compliance_status": status,
            }
        )

    rating = vals.get("facilities_rating")
    if rating is not None:
        score = round(float(rating) / 5.0 * 100.0, 1)
        _sync("FF-01-1", score, f"تقييم المرافق {rating}/5")

    budget_pct = vals.get("budget_execution_percent")
    if budget_pct is not None:
        score = min(100.0, max(0.0, float(budget_pct)))
        _sync("FF-02-1", score, f"تنفيذ الميزانية {score}%", met=80.0, partial=60.0)

    events = vals.get("community_events_count")
    if events is not None:
        cnt = int(events)
        score = min(100.0, float(cnt) * 25.0)
        _sync("CR-01-1", score, f"أنشطة مجتمعية: {cnt}", met=75.0, partial=50.0)

    research = vals.get("research_outputs_count")
    if research is not None:
        cnt = int(research)
        score = min(100.0, float(cnt) * 20.0)
        _sync("CR-02-1", score, f"مخرجات بحثية: {cnt}", met=60.0, partial=30.0)

    meetings = vals.get("governance_meetings_count")
    if meetings is not None:
        cnt = int(meetings)
        score = min(100.0, float(cnt) * 25.0)
        _sync("GV-01-1", score, f"اجتماعات حوكمة: {cnt}", met=75.0, partial=50.0)

    if results:
        conn.commit()
    return results


def delete_improvement_plan(conn, plan_id: int) -> bool:
    _ensure_manual_tables(conn)
    cur = conn.cursor()
    cur.execute(
        "UPDATE accreditation_improvement_plans SET is_active = 0 WHERE id = ?",
        (int(plan_id),),
    )
    conn.commit()
    return cur.rowcount > 0
