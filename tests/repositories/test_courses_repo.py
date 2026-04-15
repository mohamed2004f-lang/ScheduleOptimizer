from backend.repositories import courses_repo
from backend.services.utilities import get_connection


def test_find_course_name_duplicate_ci_finds_seed():
    with get_connection() as conn:
        cur = conn.cursor()
        one = cur.execute("SELECT course_name FROM courses LIMIT 1").fetchone()
        assert one is not None, "البذور يجب أن تضيف مقررات في جدول courses"
        name = one[0]
        row = courses_repo.find_course_name_duplicate_ci(conn, name)
    assert row is not None
    assert row[0] == name


def test_find_course_code_duplicate_ci_finds_seed():
    with get_connection() as conn:
        cur = conn.cursor()
        one = cur.execute(
            "SELECT course_name, course_code FROM courses WHERE COALESCE(course_code,'') <> '' LIMIT 1"
        ).fetchone()
        assert one is not None
        code = one[1]
        row = courses_repo.find_course_code_duplicate_ci(conn, code)
    assert row is not None
    assert row[0] == one[0]


def test_find_course_name_duplicate_ci_empty_returns_none():
    with get_connection() as conn:
        row = courses_repo.find_course_name_duplicate_ci(conn, "")
    assert row is None
