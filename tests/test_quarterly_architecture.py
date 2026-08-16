"""سطح الاستيراد بعد تقسيم الربع السنوي — السلوك العام لا يتغيّر."""
from __future__ import annotations

from backend.core.auth import (
    SESSION_KEY,
    _normalize_role,
    compute_capabilities,
    hash_password,
    instructor_blocked_student_portal_path,
    is_supervisor_effective_session,
    student_portal_path_allowed,
    verify_password,
)
from backend.core.auth_capabilities import compute_capabilities as compute_from_module
from backend.core.auth_roles import _normalize_role as normalize_from_roles
from backend.database.database import (
    SCHEMA,
    TABLES_SCHEMA,
    fetch_table_columns,
    get_connection,
    is_postgresql,
)
from backend.repositories.schedule_repo import group_assigned_tuples_by_course
from backend.services.schedule import _assigned_section_rows, _group_assigned_tuples_by_course


def test_database_facade_reexports_schema():
    assert SCHEMA is TABLES_SCHEMA
    assert "students" in TABLES_SCHEMA
    assert "schedule" in TABLES_SCHEMA
    assert callable(get_connection)
    assert callable(fetch_table_columns)
    assert callable(is_postgresql)


def test_auth_public_symbols_still_from_auth_module():
    assert _normalize_role("admin") == "admin_main"
    assert _normalize_role("رئيس قسم") == "head_of_department"
    assert normalize_from_roles("hod") == "head_of_department"
    assert SESSION_KEY == "authenticated"
    hashed = hash_password("TestP@ssw0rd!")
    assert verify_password("TestP@ssw0rd!", hashed) is True
    assert student_portal_path_allowed("/my_portal") is True
    assert instructor_blocked_student_portal_path("/my_portal") is True
    assert is_supervisor_effective_session("supervisor", 0, None) is True
    assert compute_capabilities is compute_from_module
    caps = compute_capabilities("instructor", 0)
    assert caps["nav_my_assigned_courses"] is True
    assert caps["is_student"] is False


def test_schedule_helpers_delegate_to_repo():
    rows = [
        (2, "فيزياء 1", "الأحد", "08:00-09:30", "قاعة 1", "أستاذ", "خريف 44-45"),
        (5, "فيزياء 1", "الاثنين", "10:00-11:30", "قاعة 2", "أستاذ", "خريف 44-45"),
    ]
    grouped = _group_assigned_tuples_by_course(rows)
    assert len(grouped) == 1
    assert grouped[0]["section_id"] == 2
    assert grouped[0]["section_ids"] == [2, 5]
    assert group_assigned_tuples_by_course(rows)[0]["course_name"] == "فيزياء 1"
    assert callable(_assigned_section_rows)
