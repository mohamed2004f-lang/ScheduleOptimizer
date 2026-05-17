"""إعداد Playwright للاختبارات E2E."""
import os

import pytest


@pytest.fixture(scope="session")
def browser_type_launch_args():
    return {"headless": True}


@pytest.fixture(scope="session")
def base_url():
    return os.environ.get("E2E_BASE_URL", "http://127.0.0.1:5000")


@pytest.fixture
def page(browser, base_url):
    context = browser.new_context(base_url=base_url)
    pg = context.new_page()
    yield pg
    context.close()
