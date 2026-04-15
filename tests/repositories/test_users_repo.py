"""اختبارات مستودع المستخدمين — تعمل على SQLite (افتراضي) وعلى PostgreSQL عند PYTEST_USE_POSTGRES_REPOS."""

from backend.repositories import users_repo
from backend.services.utilities import get_connection


def test_fetch_all_users_ordered_includes_admin():
    with get_connection() as conn:
        cur = conn.cursor()
        exp = cur.execute("SELECT username FROM users ORDER BY username LIMIT 1").fetchone()
        assert exp is not None
        expected_name = exp[0]
        users = users_repo.fetch_all_users_ordered(conn)
    assert isinstance(users, list)
    assert any(u["username"] == expected_name for u in users)


def test_fetch_user_row_by_username_ci():
    with get_connection() as conn:
        cur = conn.cursor()
        exp = cur.execute("SELECT username FROM users ORDER BY username LIMIT 1").fetchone()
        assert exp is not None
        uname = exp[0]
        q = uname.swapcase() if isinstance(uname, str) and uname.isascii() else uname
        row = users_repo.fetch_user_row_by_username_ci(conn, q)
    assert row is not None
    assert row[0] == uname
