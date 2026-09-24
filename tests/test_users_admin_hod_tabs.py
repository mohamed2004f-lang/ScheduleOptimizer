"""تبويبات قوالب الأدوار ونقل الصلاحيات مخفية افتراضياً (لا وميض لرئيس القسم)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend" / "templates" / "users_admin.html").read_text(encoding="utf-8")


def test_privileged_tabs_hidden_by_default_in_markup():
    assert 'id="tab-profiles-item"' in HTML
    assert 'id="tab-handover-item"' in HTML
    assert 'id="tab-profiles-item"' in HTML and "d-none" in HTML[
        HTML.find('id="tab-profiles-item"') - 40 : HTML.find('id="tab-profiles-item"') + 20
    ]
    assert "d-none" in HTML[
        HTML.find('id="tab-handover-item"') - 40 : HTML.find('id="tab-handover-item"') + 20
    ]
    assert 'id="tabProfiles"' in HTML
    profiles_snip = HTML[HTML.find('id="tabProfiles"') - 30 : HTML.find('id="tabProfiles"') + 20]
    assert "d-none" in profiles_snip
    handover_snip = HTML[HTML.find('id="tabHandover"') - 30 : HTML.find('id="tabHandover"') + 20]
    assert "d-none" in handover_snip


def test_apply_permissions_reveals_tabs_only_when_privileged():
    assert "tab-profiles-item" in HTML
    assert "tab-handover-item" in HTML
    assert "classList.toggle('d-none', !isPrivileged)" in HTML
    assert "['admin','admin_main','system_admin','college_dean'].includes(role)" in HTML
