"""اختبارات مرحلة مسار الطالب (ب-1)."""

from backend.boot.phase0 import ensure_phase0_catalog
from backend.core.academic_pathway import PATHWAY_STAGES, normalize_pathway_stage


def test_normalize_pathway_stage():
    assert normalize_pathway_stage("dept_admitted") == "dept_admitted"
    assert normalize_pathway_stage("invalid") == "dept_admitted"
    assert normalize_pathway_stage("specialized") == "specialized"


def test_pathway_stage_update_and_filter(app, db_conn):
    ensure_phase0_catalog(db_conn)
    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO students (student_id, student_name, pathway_stage, track_code)
        VALUES ('PW_TEST_01', 'طالب مسار', 'dept_admitted', NULL)
        """
    )
    db_conn.commit()

    with app.test_client() as c:
        c.post(
            "/auth/login",
            json={"username": "admin-test", "password": "TestP@ssw0rd!"},
        )
        lst = c.get("/students/list?pathway_stage=dept_admitted")
        assert lst.status_code == 200
        items = lst.get_json() or []
        assert any(x.get("student_id") == "PW_TEST_01" for x in items)
        assert all(
            normalize_pathway_stage(x.get("pathway_stage")) == "dept_admitted"
            for x in items
            if x.get("student_id") == "PW_TEST_01"
        )

        upd = c.post(
            "/students/pathway_stage/update",
            json={
                "student_id": "PW_TEST_01",
                "pathway_stage": "specialized",
                "track_code": "PWR",
            },
        )
        assert upd.status_code == 200
        body = upd.get_json() or {}
        assert body.get("pathway_stage") == "specialized"

    row = cur.execute(
        "SELECT pathway_stage, track_code FROM students WHERE student_id = 'PW_TEST_01'"
    ).fetchone()
    assert row[0] == "specialized"
    assert row[1] == "PWR"
