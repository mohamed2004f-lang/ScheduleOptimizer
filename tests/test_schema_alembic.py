"""مخطط التشغيل: Alembic على PostgreSQL، وليس SQLite عند الإقلاع."""
import pytest

from backend.database.database import (
    allow_ensure_tables,
    assert_schema_ready,
    require_postgres_url,
)


def test_assert_schema_ready_is_noop_under_pytest():
    assert_schema_ready()


def test_allow_ensure_tables_default_off(monkeypatch):
    monkeypatch.delenv("ALLOW_ENSURE_TABLES", raising=False)
    assert allow_ensure_tables() is False
    monkeypatch.setenv("ALLOW_ENSURE_TABLES", "1")
    assert allow_ensure_tables() is True


def test_require_postgres_url_accepts_psycopg():
    url = "postgresql+psycopg://u:p@localhost:5432/db"
    assert require_postgres_url(url) == url


def test_require_postgres_url_rejects_sqlite():
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        require_postgres_url("sqlite:///backend/database/mechanical.db")
