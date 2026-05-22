"""
اختبارات واجهة كتالوج الأقسام والخطط (إداري).
"""


class TestCollegeCatalogApi:
    def test_departments_unauthorized(self, client):
        resp = client.get(
            "/college/catalog/departments",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    def test_departments_student_forbidden(self, student_auth_client):
        resp = student_auth_client.get(
            "/college/catalog/departments",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 403

    def test_departments_admin_ok(self, auth_client):
        resp = auth_client.get(
            "/college/catalog/departments",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("status") == "ok"
        assert isinstance(data.get("items"), list)

    def test_department_save_roundtrip(self, auth_client):
        code = "TSTCAT_ROUND"
        resp = auth_client.post(
            "/college/catalog/department/save",
            json={
                "code": code,
                "name_ar": "قسم اختبار",
                "name_en": "Test dept",
                "is_active": True,
            },
        )
        assert resp.status_code == 200
        assert resp.get_json().get("status") == "ok"

        lst = auth_client.get(
            "/college/catalog/departments",
            headers={"Accept": "application/json"},
        )
        assert lst.status_code == 200
        rows = lst.get_json().get("items") or []
        assert any(r.get("code") == code for r in rows)


def test_pathway_meta_and_requirement_scope(auth_client):
    meta = auth_client.get("/college/catalog/pathway_meta")
    assert meta.status_code == 200
    body = meta.get_json() or {}
    assert body.get("operating_mode") == "dept_only"
    scopes = [s["value"] for s in (body.get("requirement_scopes") or [])]
    assert "dept_common" in scopes
    assert "college_general" in scopes

    progs = auth_client.get("/college/catalog/programs")
    items = (progs.get_json() or {}).get("items") or []
    if not items:
        return
    pid = items[0]["id"]
    save = auth_client.post(
        "/college/catalog/program_course/save",
        json={
            "program_id": pid,
            "course_master_title_ar": "مقرر مسار اختبار",
            "course_code": "PATH_TST_01",
            "requirement_scope": "pre_track",
            "level_no": 2,
        },
    )
    assert save.status_code == 200
    lst = auth_client.get(f"/college/catalog/program_courses?program_id={pid}")
    rows = (lst.get_json() or {}).get("items") or []
    hit = next((r for r in rows if r.get("course_code") == "PATH_TST_01"), None)
    assert hit is not None
    assert hit.get("requirement_scope") == "pre_track"


def test_pathway_regulations_list_and_save(auth_client, db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en) VALUES ('GENERAL', 'القسم العام', 'General')"
    )
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en) VALUES ('MECH', 'ميكانيك', 'Mech')"
    )
    db_conn.commit()
    from backend.services.pathway_regulations import ensure_pathway_regulation_defaults

    ensure_pathway_regulation_defaults(db_conn)
    mech_id = cur.execute("SELECT id FROM departments WHERE code = 'MECH'").fetchone()[0]
    lst = auth_client.get(f"/college/catalog/pathway_regulations?department_id={mech_id}")
    assert lst.status_code == 200
    body = lst.get_json() or {}
    assert body.get("status") == "ok"
    assert len(body.get("items") or []) >= 1
    save = auth_client.post(
        "/college/catalog/pathway_regulation/save",
        json={
            "department_id": mech_id,
            "rule_key": "custom_test_rule",
            "title": "بند اختبار",
            "value_number": 25,
            "category": "other",
        },
    )
    assert save.status_code == 200


def _first_program_id(auth_client):
    progs = auth_client.get("/college/catalog/programs")
    items = (progs.get_json() or {}).get("items") or []
    if not items:
        return None
    return items[0]["id"]


def test_phase_a_classification_bulk_suggest_sync(auth_client, db_conn):
    """المرحلة أ: ملخص التصنيف، تعيين جماعي، اقتراح من المستوى، مزامنة وحدات التخرج."""
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en) VALUES ('MECH', 'ميكانيك', 'Mech')"
    )
    db_conn.commit()
    from backend.services.pathway_regulations import ensure_pathway_regulation_defaults

    ensure_pathway_regulation_defaults(db_conn)
    mech_id = cur.execute("SELECT id FROM departments WHERE code = 'MECH'").fetchone()[0]

    pid = _first_program_id(auth_client)
    if pid is None:
        cur.execute(
            """
            INSERT INTO programs (department_id, code, name_ar, min_total_units, is_active)
            VALUES (?, 'MECH_TST', 'برنامج اختبار', 99, 1)
            """,
            (mech_id,),
        )
        db_conn.commit()
        pid = cur.lastrowid

    codes = [
        ("PA_LV0", 0, "dept_common"),
        ("PA_LV3", 3, "dept_common"),
        ("PA_LV5", 5, "dept_common"),
    ]
    pc_ids = []
    for code, lv, _ in codes:
        r = auth_client.post(
            "/college/catalog/program_course/save",
            json={
                "program_id": pid,
                "course_master_title_ar": f"مقرر {code}",
                "course_code": code,
                "requirement_scope": "dept_common",
                "level_no": lv,
            },
        )
        assert r.status_code == 200
        lst = auth_client.get(f"/college/catalog/program_courses?program_id={pid}")
        hit = next(
            (x for x in (lst.get_json() or {}).get("items") or [] if x.get("course_code") == code),
            None,
        )
        assert hit is not None
        pc_ids.append(hit["id"])

    summary = auth_client.get(
        f"/college/catalog/program_courses/classification_summary?program_id={pid}"
    )
    assert summary.status_code == 200
    sb = summary.get_json() or {}
    assert sb.get("status") == "ok"
    assert sb.get("total", 0) >= 3
    assert "dept_common" in (sb.get("by_scope") or {})

    bulk = auth_client.post(
        "/college/catalog/program_courses/bulk_requirement_scope",
        json={
            "program_id": pid,
            "program_course_ids": [pc_ids[0]],
            "requirement_scope": "track",
        },
    )
    assert bulk.status_code == 200
    assert bulk.get_json().get("requirement_scope") == "track"

    one = auth_client.get(f"/college/catalog/program_courses?program_id={pid}")
    row0 = next(x for x in (one.get_json() or {}).get("items") or [] if x["id"] == pc_ids[0])
    assert row0.get("requirement_scope") == "track"

    suggest = auth_client.post(
        "/college/catalog/program_courses/apply_suggested_scope",
        json={"program_id": pid, "program_course_ids": pc_ids[1:]},
    )
    assert suggest.status_code == 200
    assert suggest.get_json().get("updated") == 2

    after = auth_client.get(f"/college/catalog/program_courses?program_id={pid}")
    by_code = {r["course_code"]: r for r in (after.get_json() or {}).get("items") or []}
    assert by_code["PA_LV3"]["requirement_scope"] == "pre_track"
    assert by_code["PA_LV5"]["requirement_scope"] == "track"

    cur.execute(
        """
        UPDATE pathway_regulation_items SET value_number = 155
        WHERE department_id = ? AND rule_key = 'dept_graduation_min_units'
        """,
        (mech_id,),
    )
    cur.execute("UPDATE programs SET min_total_units = 1 WHERE id = ?", (pid,))
    db_conn.commit()
    sync = auth_client.post(
        "/college/catalog/program/sync_graduation_units",
        json={"program_id": pid},
    )
    assert sync.status_code == 200
    body = sync.get_json() or {}
    assert body.get("status") == "ok"
    assert body.get("min_total_units") == 155
    assert body.get("previous_min_total_units") == 1


def test_department_course_catalog_merges_courses_and_plans(auth_client, db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en) VALUES ('MECH', 'ميكانيك', 'Mech')"
    )
    db_conn.commit()
    mech_id = cur.execute("SELECT id FROM departments WHERE code = 'MECH'").fetchone()[0]
    cur.execute(
        """
        INSERT INTO programs (department_id, code, name_ar, min_total_units, is_active)
        VALUES (?, 'MECH_A', 'مسار أ', 160, 1)
        """,
        (mech_id,),
    )
    prog_a = cur.lastrowid
    cur.execute(
        """
        INSERT INTO programs (department_id, code, name_ar, min_total_units, is_active)
        VALUES (?, 'MECH_B', 'مسار ب', 160, 1)
        """,
        (mech_id,),
    )
    prog_b = cur.lastrowid
    cur.execute(
        """
        INSERT INTO courses (course_name, course_code, units, owning_department_id, is_archived)
        VALUES ('احصاء DeptCat', 'STAT-01', 2, ?, 0)
        """,
        (mech_id,),
    )
    cur.execute(
        "INSERT INTO course_master (title_ar, default_units) VALUES ('مقرر خطة ب', 3)"
    )
    cm_b = cur.lastrowid
    cur.execute(
        """
        INSERT INTO program_courses (program_id, course_master_id, course_code, level_no, is_active)
        VALUES (?, ?, 'MECHB01', 4, 1)
        """,
        (prog_b, cm_b),
    )
    db_conn.commit()

    resp = auth_client.get(
        f"/college/catalog/department_course_catalog?program_id={prog_a}"
    )
    assert resp.status_code == 200
    body = resp.get_json() or {}
    assert body.get("status") == "ok"
    assert body.get("department_id") == mech_id
    groups = body.get("groups") or {}
    reg = groups.get("courses") or []
    pln = groups.get("plan") or []
    assert any(
        (x.get("operational_course_name") or x.get("title_ar")) == "احصاء DeptCat"
        for x in reg
    )
    assert any(x.get("course_code") == "MECHB01" for x in pln)

    save = auth_client.post(
        "/college/catalog/program_course/save",
        json={
            "program_id": prog_a,
            "operational_course_name": "احصاء DeptCat",
            "course_code": "STAT-01-A",
            "requirement_scope": "dept_common",
            "level_no": 1,
        },
    )
    assert save.status_code == 200
    row = cur.execute(
        "SELECT course_master_id FROM courses WHERE course_name = 'احصاء DeptCat'"
    ).fetchone()
    assert row and row[0] is not None


from backend.services.college_catalog import infer_level_from_course_code, suggest_requirement_scope_for_level


def test_department_program_tracks_api(auth_client, db_conn):
    from backend.boot.phase0 import ensure_phase0_catalog

    ensure_phase0_catalog(db_conn)
    resp = auth_client.get(
        "/college/catalog/department_program_tracks?department_code=MECH&ensure=1"
    )
    assert resp.status_code == 200
    body = resp.get_json() or {}
    assert body.get("status") == "ok"
    codes = {p.get("code") for p in (body.get("items") or [])}
    assert "MECH" in codes
    assert "MECH-PWR" in codes


def test_department_program_tracks_civil_templates(auth_client, db_conn):
    from backend.boot.phase0 import ensure_phase0_catalog
    from backend.core.program_tracks import ensure_department_track_programs

    ensure_phase0_catalog(db_conn)
    ensure_department_track_programs(db_conn, "CIVIL")
    db_conn.commit()
    resp = auth_client.get(
        "/college/catalog/department_program_tracks?department_code=CIVIL"
    )
    assert resp.status_code == 200
    body = resp.get_json() or {}
    tgroups = {t.get("track_group") for t in (body.get("track_templates") or [])}
    assert "STR" in tgroups
    assert "PWR" not in tgroups
    assert body.get("base_program_code") in ("CIVIL", "PROG_MAJOR")


def test_ensure_preserves_customized_program_names(db_conn):
    from backend.boot.phase0 import ensure_phase0_catalog
    from backend.core.program_tracks import (
        ensure_department_track_programs,
        merge_catalog_rules,
    )

    ensure_phase0_catalog(db_conn)
    ensure_department_track_programs(db_conn, "MECH", graduation_units=155)
    cur = db_conn.cursor()
    cur.execute(
        "SELECT id FROM programs WHERE code = 'MECH-PWR' ORDER BY id LIMIT 1"
    )
    row = cur.fetchone()
    assert row
    pid = row[0]
    custom_name = "هندسة ميكانيكية — شعبة طاقة مخصصة"
    rules = merge_catalog_rules("", names_customized=True)
    cur.execute(
        "UPDATE programs SET name_ar = ?, rules_json = ? WHERE id = ?",
        (custom_name, rules, pid),
    )
    db_conn.commit()
    ensure_department_track_programs(db_conn, "MECH", graduation_units=155)
    cur.execute("SELECT name_ar, rules_json FROM programs WHERE id = ?", (pid,))
    after = cur.fetchone()
    assert after[0] == custom_name
    assert "names_customized" in (after[1] or "")


def test_ensure_mech_track_program_templates(db_conn):
    from backend.boot.phase0 import ensure_phase0_catalog
    from backend.core.program_tracks import ensure_department_track_programs

    ensure_phase0_catalog(db_conn)
    body = ensure_department_track_programs(db_conn, "MECH", graduation_units=155)
    assert body.get("status") == "ok"
    codes = {p["program_code"] for p in (body.get("programs") or [])}
    assert "MECH" in codes
    assert "MECH-PWR" in codes
    assert "MECH-MFG" in codes
    cur = db_conn.cursor()
    rows = cur.execute(
        """
        SELECT p.code, p.track_group, COALESCE(p.is_active, 1) AS is_active
        FROM programs p
        JOIN departments d ON d.id = p.department_id
        WHERE d.code = 'MECH'
        ORDER BY p.code
        """
    ).fetchall()
    by_code = {r[0]: r for r in rows}
    assert by_code["MECH"][1] in ("", None) or str(by_code["MECH"][1]).strip() == ""
    assert by_code["MECH-PWR"][1] == "PWR"
    assert int(by_code["MECH-PWR"][2]) == 0


def test_infer_level_and_scope_from_course_code():
    assert infer_level_from_course_code("GE 102") == 1
    assert infer_level_from_course_code("ME201") == 2
    assert infer_level_from_course_code("PL-150") == 1
    assert infer_level_from_course_code("") == 0
    assert suggest_requirement_scope_for_level(1) == "college_general"
    assert suggest_requirement_scope_for_level(2) == "pre_track"
    assert suggest_requirement_scope_for_level(5) == "track"


def test_college_general_scope_in_plan(auth_client, db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en) VALUES ('MECH', 'ميكانيك', 'Mech')"
    )
    db_conn.commit()
    mech_id = cur.execute("SELECT id FROM departments WHERE code = 'MECH'").fetchone()[0]
    cur.execute(
        """
        INSERT INTO programs (department_id, code, name_ar, min_total_units, is_active)
        VALUES (?, 'MECH_GEN', 'اختبار عام', 155, 1)
        """,
        (mech_id,),
    )
    pid = cur.lastrowid
    save = auth_client.post(
        "/college/catalog/program_course/save",
        json={
            "program_id": pid,
            "course_master_title_ar": "احصاء اتجاه عام",
            "course_code": "PL-GEN-01",
            "requirement_scope": "college_general",
            "level_no": 0,
            "units_override": 3,
        },
    )
    assert save.status_code == 200
    summary = auth_client.get(
        f"/college/catalog/program_courses/classification_summary?program_id={pid}"
    )
    sb = summary.get_json() or {}
    assert sb.get("units_by_scope", {}).get("college_general") == 3
    assert sb.get("college_general_units_in_plan") == 3
