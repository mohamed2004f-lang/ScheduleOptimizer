"""
اختبارات E2E دخانية — تتطلب خادماً يعمل و Playwright.
تشغيل: E2E_BASE_URL=http://127.0.0.1:5000 pytest tests/e2e -m e2e
"""
import os

import pytest

pytestmark = pytest.mark.e2e


@pytest.mark.skipif(
    not os.environ.get("E2E_BASE_URL"),
    reason="عيّن E2E_BASE_URL لتشغيل اختبارات المتصفح",
)
def test_login_page_loads(page, base_url):
    page.goto(f"{base_url}/login")
    assert page.locator("text=تسجيل الدخول").first.is_visible()


@pytest.mark.skipif(
    not os.environ.get("E2E_BASE_URL"),
    reason="عيّن E2E_BASE_URL لتشغيل اختبارات المتصفح",
)
def test_index_redirects_unauthenticated(page, base_url):
    page.goto(f"{base_url}/")
    assert "login" in page.url.lower() or page.locator("input#username").count() > 0
