"""إظهار حقول الربط (طالب/أستاذ) حسب الدور فقط."""

from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "frontend" / "templates" / "users_admin.html").read_text(
    encoding="utf-8"
)


def test_link_fields_hidden_by_default():
    stu = HTML[HTML.find('id="studentIdWrap"') - 40 : HTML.find('id="studentIdWrap"') + 30]
    inst = HTML[HTML.find('id="instructorIdWrap"') - 40 : HTML.find('id="instructorIdWrap"') + 30]
    assert "d-none" in stu
    assert "d-none" in inst
    assert "function syncRoleLinkFields" in HTML
    assert "role === 'student'" in HTML


def test_role_change_wires_link_sync():
    assert "syncRoleLinkFields()" in HTML
    assert "syncRoleHeadHints" in HTML
