"""تعطيل استيراد كشف الدرجات واستيراد الجدول."""


def test_transcript_import_api_disabled(auth_client):
    r = auth_client.post("/grades/import/transcript", data={})
    assert r.status_code == 410
    body = r.get_json() or {}
    assert body.get("code") == "IMPORT_DISABLED"


def test_semester_import_api_disabled(auth_client):
    r = auth_client.post("/grades/import/semester", data={})
    assert r.status_code == 410
    body = r.get_json() or {}
    assert body.get("code") == "IMPORT_DISABLED"


def test_schedule_import_api_disabled(auth_client):
    r = auth_client.post("/schedule/import/excel", data={})
    assert r.status_code == 410
    body = r.get_json() or {}
    assert body.get("code") == "IMPORT_DISABLED"


def test_admin_transcript_page_has_no_import_ui(auth_client):
    page = auth_client.get("/transcript_page")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "استيراد كشف درجات لطالب محدد" not in html
    assert 'id="btnImportTranscript"' not in html
    assert 'id="importFile"' not in html
    assert "استيراد نتيجة فصل كاملة" not in html


def test_schedule_page_has_no_import_ui(auth_client):
    page = auth_client.get("/schedule_form")
    if page.status_code == 404:
        page = auth_client.get("/schedule")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "استيراد جدول (Excel)" not in html
    assert 'id="btnImportSchedule"' not in html
