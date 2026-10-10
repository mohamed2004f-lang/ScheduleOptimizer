"""تقييد تشغيل العميد/الوكيل + مفاتيح اللوحة."""

from backend.core.capability_gates import (
    DEPT_OPS_EDIT_KEYS,
    apply_explicit_permission_overrides,
    apply_leadership_ops_defaults,
    panel_effective_keys_for_profile,
)
from backend.core.permissions import resolve_capabilities_for_user


def test_leadership_defaults_view_only_ops():
    base = {"v": 1, "can_manage_schedule_edit": True, "can_manage_students": True}
    out = apply_leadership_ops_defaults(base, role="college_dean")
    for k in DEPT_OPS_EDIT_KEYS:
        assert out.get(k) is False, k
    assert out.get("can_manage_academic_calendar_edit") is True
    assert out.get("can_manage_term_ops_college") is True
    assert out.get("can_migrate_registrations_to_transcript") is False
    assert out.get("students_data_view_only") is True


def test_explicit_grant_unlocks_schedule_edit():
    caps = apply_leadership_ops_defaults({"v": 1}, role="academic_vice_dean")
    caps = apply_explicit_permission_overrides(
        caps,
        profile_keys=set(),
        grants={"can_manage_schedule_edit"},
        denies=set(),
    )
    assert caps["can_manage_schedule_edit"] is True
    assert caps["can_manage_exam_schedule_edit"] is False
    # منح تعديل الجدول لا يلغي عرض-فقط لبيانات الطلبة
    assert caps.get("students_data_view_only") is True
    assert caps.get("can_manage_students") is False


def test_explicit_grant_students_clears_view_only():
    caps = apply_leadership_ops_defaults({"v": 1}, role="college_dean")
    caps = apply_explicit_permission_overrides(
        caps,
        profile_keys={"can_manage_students"},
        grants=set(),
        denies=set(),
    )
    assert caps["can_manage_students"] is True
    assert caps["students_data_view_only"] is False


def test_panel_effective_keys_leadership():
    stored = {"nav_users_admin", "can_manage_users"}
    eff = panel_effective_keys_for_profile("college_dean", stored)
    assert "can_manage_term_ops_college" in eff
    assert "can_manage_academic_calendar_edit" in eff
    assert "nav_view_class_schedule" in eff
    assert "can_transfer_student_department" in eff
    assert "can_manage_students" not in eff
    assert "can_manage_schedule_edit" not in eff


def test_resolve_dean_defaults(app):
    with app.app_context():
        caps = resolve_capabilities_for_user(
            role="college_dean",
            is_supervisor_val=0,
            active_mode="dean",
        )
        assert caps.get("can_manage_schedule_edit") is False
        assert caps.get("can_manage_registrations_edit") is False
        assert caps.get("can_manage_exam_schedule_edit") is False
        assert caps.get("can_manage_courses_edit") is False
        assert caps.get("can_manage_enrollment_plans_edit") is False
        assert caps.get("can_manage_transcript_admin") is False
        assert caps.get("can_manage_students") is False
        assert caps.get("students_data_view_only") is True
        assert caps.get("can_transfer_student_department") is True
        assert caps.get("can_manage_academic_calendar_edit") is True
        assert caps.get("can_manage_term_ops_college") is True
        assert caps.get("can_migrate_registrations_to_transcript") is False
        assert caps.get("nav_view_registrations") is True


def test_resolve_dean_ignores_stale_profile_dept_ops(app, db_conn):
    """منح قديم في القالب لا يُفترض أن يفتح تشغيل القسم إلا إن بقي في keys — هنا نختبر resolve بلا منح."""
    with app.app_context():
        caps = resolve_capabilities_for_user(
            role="college_dean",
            is_supervisor_val=0,
            active_mode="dean",
            role_profile_code="college_dean",
            conn=db_conn,
        )
        assert caps.get("can_manage_schedule_edit") is False
        assert caps.get("can_manage_transcript_admin") is False
        assert caps.get("can_manage_enrollment_plans_edit") is False


def test_load_profile_keys_prefers_db_over_seed(app, db_conn):
    from backend.boot.role_profiles_seed import (
        sanitize_leadership_profile_permissions,
        seed_role_profiles,
    )
    from backend.core.permissions import load_profile_permission_keys

    seed_role_profiles(db_conn)
    cur = db_conn.cursor()
    row = cur.execute("SELECT id FROM role_profiles WHERE code = 'college_dean' LIMIT 1").fetchone()
    assert row
    pid = int(row[0] if not hasattr(row, "keys") else row["id"])
    # محاكاة منح قديم خاطئ
    for k in ("can_manage_schedule_edit", "can_manage_students", "can_manage_transcript_admin"):
        cur.execute(
            """
            INSERT INTO role_profile_permissions (profile_id, permission_key, granted)
            VALUES (?, ?, 1)
            ON CONFLICT(profile_id, permission_key) DO UPDATE SET granted = 1
            """,
            (pid, k),
        )
    db_conn.commit()
    by_code = load_profile_permission_keys(db_conn, None, "college_dean")
    assert "can_manage_schedule_edit" in by_code
    sanitize_leadership_profile_permissions(db_conn)
    db_conn.commit()
    cleaned = load_profile_permission_keys(db_conn, None, "college_dean")
    assert "can_manage_schedule_edit" not in cleaned
    assert "can_manage_students" not in cleaned
    assert "can_manage_transcript_admin" not in cleaned
    caps = resolve_capabilities_for_user(
        role="college_dean",
        is_supervisor_val=0,
        active_mode="dean",
        role_profile_id=pid,
        role_profile_code="college_dean",
        conn=db_conn,
    )
    assert caps.get("can_manage_schedule_edit") is False
    assert caps.get("can_manage_students") is False
    assert caps.get("can_manage_transcript_admin") is False
    assert caps.get("students_data_view_only") is True


def test_resolve_vice_dean_students_view_only(app):
    with app.app_context():
        caps = resolve_capabilities_for_user(
            role="academic_vice_dean",
            is_supervisor_val=0,
            active_mode="vice_dean",
        )
        assert caps.get("can_manage_students") is False
        assert caps.get("students_data_view_only") is True
        assert caps.get("can_transfer_student_department") is True


def test_resolve_hod_keeps_schedule_edit(app):
    with app.app_context():
        caps = resolve_capabilities_for_user(
            role="head_of_department",
            is_supervisor_val=0,
            active_mode="head",
        )
        assert caps.get("can_manage_schedule_edit") is True
        assert caps.get("can_manage_exam_schedule_edit") is True
        assert caps.get("can_manage_registrations_edit") is True
        assert caps.get("can_manage_students") is True
        assert caps.get("can_manage_academic_calendar_edit") is False
        assert caps.get("can_migrate_registrations_to_transcript") is False


def test_admin_permissions_page(auth_client):
    page = auth_client.get("/admin/permissions")
    assert page.status_code == 200
    assert "لوحة الصلاحيات".encode("utf-8") in page.data


def test_permissions_catalog_api(auth_client):
    api = auth_client.get("/role_profiles/catalog")
    assert api.status_code == 200
    body = api.get_json() or {}
    groups = body.get("groups") or []
    keys = {it["key"] for g in groups for it in (g.get("items") or [])}
    assert "can_manage_exam_schedule_edit" in keys
    assert "can_migrate_registrations_to_transcript" in keys
    assert "can_manage_term_ops_college" in keys


def test_profile_detail_panel_permissions(auth_client):
    api = auth_client.get("/role_profiles/detail/college_dean")
    assert api.status_code == 200
    body = api.get_json() or {}
    panel = set(body.get("panel_permissions") or [])
    stored = set(body.get("permissions") or [])
    assert body.get("leadership_defaults_applied") is True
    assert "can_manage_term_ops_college" in panel
    assert "nav_view_class_schedule" in panel
    if "can_manage_students" not in stored:
        assert "can_manage_students" not in panel
    if "can_manage_schedule_edit" not in stored:
        assert "can_manage_schedule_edit" not in panel
