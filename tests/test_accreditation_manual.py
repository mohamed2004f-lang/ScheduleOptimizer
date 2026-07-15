"""اختبارات الإدخالات اليدوية وخطط التحسين (هـ-4)."""

from backend.core.accreditation_catalog import ensure_accreditation_catalog
from backend.services.accreditation_manual import (
    delete_improvement_plan,
    get_manual_inputs,
    list_improvement_plans,
    save_improvement_plan,
    save_manual_inputs,
)


def test_manual_inputs_save_and_load(db_conn):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    save_manual_inputs(
        db_conn,
        semester="h4-sem",
        department_id=None,
        payload={
            "classrooms_count": 12,
            "labs_count": 4,
            "facilities_rating": 4.5,
            "annual_budget_million": 2.5,
            "governance_meetings_count": 6,
            "community_events_count": 3,
        },
        actor="tester",
    )
    bundle = get_manual_inputs(db_conn, "h4-sem", None)
    fac = next(s for s in bundle["sections"] if s["key"] == "facilities")
    assert fac["values"]["classrooms_count"] == 12
    assert fac["values"]["facilities_rating"] == 4.5


def test_improvement_plan_crud(db_conn):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    ind_id = db_conn.cursor().execute(
        "SELECT id FROM accreditation_indicators ORDER BY id LIMIT 1"
    ).fetchone()[0]
    created = save_improvement_plan(
        db_conn,
        semester="h4-sem",
        department_id=None,
        plan_id=None,
        data={
            "title_ar": "تحسين المرافق",
            "action_ar": "صيانة المعامل",
            "indicator_id": int(ind_id),
            "status": "planned",
            "priority": "high",
            "target_date": "1448-06-01",
            "owner_ar": "منسق الجودة",
        },
        actor="tester",
    )
    pid = created["id"]
    items = list_improvement_plans(db_conn, "h4-sem", None)
    assert any(int(x["id"]) == int(pid) for x in items)

    save_improvement_plan(
        db_conn,
        semester="h4-sem",
        department_id=None,
        plan_id=pid,
        data={"title_ar": "تحسين المرافق — محدّث", "status": "in_progress"},
        actor="tester",
    )
    items2 = list_improvement_plans(db_conn, "h4-sem", None)
    row = next(x for x in items2 if int(x["id"]) == int(pid))
    assert row["status"] == "in_progress"
    assert delete_improvement_plan(db_conn, pid)


def test_manual_sync_updates_indicators(db_conn):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    save_manual_inputs(
        db_conn,
        semester="sync-sem",
        department_id=None,
        payload={
            "facilities_rating": 4,
            "budget_execution_percent": 85,
            "community_events_count": 4,
            "research_outputs_count": 2,
            "governance_meetings_count": 5,
            "catalog_version": "2026.1",
        },
        actor="tester",
    )
    cur = db_conn.cursor()
    for code in ("FF-01-1", "FF-02-1", "CR-01-1", "CR-02-1"):
        row = cur.execute(
            """
            SELECT a.compliance_status, a.score_percent
            FROM accreditation_assessments a
            JOIN accreditation_indicators i ON i.id = a.indicator_id
            WHERE a.semester = ? AND i.code = ?
            """,
            ("sync-sem", code),
        ).fetchone()
        assert row is not None, code
        assert row[1] is not None


def test_manual_and_plans_api(app, db_conn, auth_client):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    save = auth_client.post(
        "/academic_quality/api/accreditation/manual_inputs/save",
        json={"semester": "api-h4", "classrooms_count": 8, "finance_notes": "ملاحظة"},
    )
    assert save.status_code == 200
    get = auth_client.get("/academic_quality/api/accreditation/manual_inputs?semester=api-h4")
    assert get.status_code == 200

    plan = auth_client.post(
        "/academic_quality/api/accreditation/improvement_plans/save",
        json={"semester": "api-h4", "title_ar": "خطة API", "status": "planned"},
    )
    assert plan.status_code == 200
    lst = auth_client.get("/academic_quality/api/accreditation/improvement_plans?semester=api-h4")
    assert lst.status_code == 200
    assert len((lst.get_json() or {}).get("items") or []) >= 1
