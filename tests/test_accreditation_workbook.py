"""اختبارات دفتر الاعتماد والاستيراد (هـ-5)."""

import io

import pandas as pd

from backend.core.accreditation_catalog import ensure_accreditation_catalog
from backend.core.accreditation_workbook import frames_for_accreditation_workbook, html_for_accreditation_workbook
from backend.services.accreditation_catalog_import import import_catalog_from_excel
from backend.services.institutional_accreditation import build_compliance_map


def test_workbook_frames(db_conn):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    data = build_compliance_map(db_conn, semester="wb-sem", department_id=None, ensure_seed=False)
    frames = frames_for_accreditation_workbook(data)
    names = [n for n, _ in frames]
    assert "ملخص" in names
    assert "المؤشرات" in names
    ind_df = next(df for n, df in frames if n == "المؤشرات")
    assert len(ind_df) >= 15


def test_workbook_html(db_conn):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    data = build_compliance_map(db_conn, semester="wb-sem", department_id=None, ensure_seed=False)
    html = html_for_accreditation_workbook(data)
    assert "دفتر اعتماد" in html
    assert "wb-sem" in html


def test_import_catalog_from_excel(db_conn):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    rows = [
        {
            "catalog_version": "2099.test",
            "domain_code": "governance",
            "standard_code": "TST-01",
            "standard_title_ar": "معيار اختبار",
            "standard_description": "وصف",
            "weight_percent": 5,
            "indicator_code": "TST-01-1",
            "indicator_title_ar": "مؤشر اختبار",
            "source_type": "manual",
            "target_hint_ar": "هدف",
        }
    ]
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    result = import_catalog_from_excel(db_conn, buf.read(), actor="test")
    assert result["catalog_version"] == "2099.test"
    assert result["indicators_upserted"] >= 1
    cur = db_conn.cursor()
    n = cur.execute(
        "SELECT COUNT(*) FROM accreditation_standards WHERE catalog_version = ?",
        ("2099.test",),
    ).fetchone()[0]
    assert int(n) >= 1


def test_export_xlsx_route(app, db_conn, auth_client):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    r = auth_client.get("/academic_quality/api/accreditation/export/xlsx?semester=exp-sem")
    assert r.status_code == 200
    assert "spreadsheetml" in (r.content_type or "")


def test_import_template_route(app, auth_client):
    r = auth_client.get("/academic_quality/api/accreditation/import_catalog/template")
    assert r.status_code == 200
