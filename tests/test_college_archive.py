"""اختبارات أرشيف الكلية + المشاركات الموحّدة."""

from backend.core.college_archive_catalog import CABINET_CODES, COLLEGE_CABINETS
from backend.services.archive_shares import (
    SOURCE_COLLEGE,
    SOURCE_DEPT,
    list_shared_item_ids_for_user,
    replace_item_shares,
    user_can_read_shared_item,
)
from backend.services.college_archive import (
    can_read_cabinet,
    can_write_cabinet,
    create_college_archive_item,
    ensure_college_archive_table,
    list_college_archive_items,
    session_cabinet_owner,
)
from backend.services.department_archive import (
    create_archive_item,
    ensure_department_archive_table,
)


def _dept(db_conn) -> int:
    cur = db_conn.cursor()
    row = cur.execute("SELECT id FROM departments WHERE code = ?", ("CARCH",)).fetchone()
    if row:
        return int(row[0] if not hasattr(row, "keys") else row["id"])
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        ("CARCH", "قسم اختبار أرشيف كلية", "College Archive Dept"),
    )
    db_conn.commit()
    return int(cur.execute("SELECT id FROM departments WHERE code = ?", ("CARCH",)).fetchone()[0])


def test_cabinet_titles_and_acl():
    assert "college_quality_dept" in CABINET_CODES
    assert "رئيس قسم جودة بالكلية" in COLLEGE_CABINETS["college_quality_dept"]["title_ar"]
    assert session_cabinet_owner("college_dean") == "dean"
    assert session_cabinet_owner("academic_vice_dean") == "vice_dean"
    assert session_cabinet_owner("instructor", is_college_quality_lead=True) == "college_quality_dept"
    assert can_write_cabinet("dean", "college_dean") is True
    assert can_write_cabinet("dean", "academic_vice_dean") is False
    assert can_read_cabinet("dean", "academic_vice_dean") is False
    assert can_write_cabinet("shared", "college_dean") is True
    assert can_write_cabinet("shared", "head_of_department") is False


def test_create_private_cabinet_and_isolation(db_conn):
    ensure_college_archive_table(db_conn)
    item = create_college_archive_item(
        db_conn,
        cabinet="dean",
        record_type="decision",
        title_ar="قرار عميد سري",
        actor="dean1",
        actor_role="college_dean",
        semester="كلية-1",
        doc_date="2026-08-03",
    )
    assert item["id"]
    assert item["cabinet_code"] == "dean"
    items = list_college_archive_items(db_conn, cabinet="dean", semester="كلية-1")
    assert any(i["id"] == item["id"] for i in items)
    # الوكيل لا يقرأ بدون مشاركة
    assert (
        user_can_read_shared_item(
            db_conn,
            source=SOURCE_COLLEGE,
            item_id=int(item["id"]),
            username="vice1",
            user_role="academic_vice_dean",
        )
        is False
    )


def test_college_share_to_vice_dean(db_conn):
    ensure_college_archive_table(db_conn)
    item = create_college_archive_item(
        db_conn,
        cabinet="dean",
        record_type="minutes",
        title_ar="محضر للمشاركة",
        actor="dean1",
        actor_role="college_dean",
        semester="كلية-2",
    )
    replace_item_shares(
        db_conn,
        source=SOURCE_COLLEGE,
        item_id=int(item["id"]),
        grants=[{"target_kind": "role", "target_role": "academic_vice_dean"}],
        shared_by="dean1",
    )
    assert user_can_read_shared_item(
        db_conn,
        source=SOURCE_COLLEGE,
        item_id=int(item["id"]),
        username="vice1",
        user_role="academic_vice_dean",
    )
    ids = list_shared_item_ids_for_user(
        db_conn,
        source=SOURCE_COLLEGE,
        username="vice1",
        user_role="academic_vice_dean",
    )
    assert int(item["id"]) in ids


def test_dept_share_to_dean_and_instructor(db_conn):
    dept_id = _dept(db_conn)
    ensure_department_archive_table(db_conn)
    # مستخدم عضو تدريس بالقسم
    cur = db_conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO users (username, password_hash, role, department_id, is_active)
            VALUES (?, ?, ?, ?, 1)
            """,
            ("ins_arch", "x", "instructor", dept_id),
        )
    except Exception:
        cur.execute(
            "UPDATE users SET role = ?, department_id = ? WHERE username = ?",
            ("instructor", dept_id, "ins_arch"),
        )
    db_conn.commit()

    item = create_archive_item(
        db_conn,
        department_id=dept_id,
        record_type="minutes",
        title_ar="محضر قسم للمشاركة",
        actor="hod1",
        semester="قسم-شارك-1",
    )
    replace_item_shares(
        db_conn,
        source=SOURCE_DEPT,
        item_id=int(item["id"]),
        grants=[
            {"target_kind": "role", "target_role": "college_dean"},
            {"target_kind": "user", "target_username": "ins_arch"},
            {"target_kind": "dept_all_instructors", "target_department_id": dept_id},
        ],
        shared_by="hod1",
    )
    assert user_can_read_shared_item(
        db_conn,
        source=SOURCE_DEPT,
        item_id=int(item["id"]),
        username="dean1",
        user_role="college_dean",
    )
    assert user_can_read_shared_item(
        db_conn,
        source=SOURCE_DEPT,
        item_id=int(item["id"]),
        username="ins_arch",
        user_role="instructor",
        home_department_id=dept_id,
    )
    # مستخدم خارج القسم بدون منحة مباشرة
    assert (
        user_can_read_shared_item(
            db_conn,
            source=SOURCE_DEPT,
            item_id=int(item["id"]),
            username="outsider",
            user_role="instructor",
            home_department_id=999999,
        )
        is False
    )
