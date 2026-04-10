"""
تحويل استعلامات SQLite إلى صيغة PostgreSQL (عناصر ربط %s و ON CONFLICT).
يُستخدم فقط عند DATABASE_URL=postgresql+...
"""
from __future__ import annotations

import re


def qmarks_to_percent(sql: str) -> str:
    """يحوّل ? إلى %s لـ psycopg (لا يدعم معاملات ?)."""
    return sql.replace("?", "%s")


_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s.strip())


def adapt_sqlite_sql_to_postgres(sql: str) -> str:
    """
    يحوّل أنماط SQLite الشائعة في المشروع إلى PostgreSQL.
    يُفترض أن الاستعلام يستخدم ? للمعاملات؛ الناتج ما زال يحتوي ? حتى يُستدعى qmarks_to_percent.
    """
    s = sql.strip()
    n = _norm(s)

    # --- INSERT OR REPLACE / IGNORE (أنماط محددة أولاً) ---

    if n.startswith(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', ?)"
    ):
        return (
            "INSERT INTO system_settings (key, value) VALUES ('current_term_name', ?) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        )
    if n.startswith(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', ?)"
    ):
        return (
            "INSERT INTO system_settings (key, value) VALUES ('current_term_year', ?) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        )
    if n == _norm("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)"):
        return (
            "INSERT INTO system_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        )

    if n == _norm(
        "INSERT OR REPLACE INTO app_settings (key, value_json, updated_at, updated_by) VALUES (?,?,?,?)"
    ):
        return (
            "INSERT INTO app_settings (key, value_json, updated_at, updated_by) VALUES (?,?,?,?) "
            "ON CONFLICT (key) DO UPDATE SET "
            "value_json = EXCLUDED.value_json, updated_at = EXCLUDED.updated_at, "
            "updated_by = EXCLUDED.updated_by"
        )

    if n == _norm(
        "INSERT OR REPLACE INTO courses (course_name, course_code, units) VALUES (?, ?, ?)"
    ):
        return (
            "INSERT INTO courses (course_name, course_code, units) VALUES (?, ?, ?) "
            "ON CONFLICT (course_name) DO UPDATE SET "
            "course_code = EXCLUDED.course_code, units = EXCLUDED.units"
        )

    if n == _norm(
        "INSERT OR REPLACE INTO grades (student_id, semester, course_name, course_code, units, grade) VALUES (?, ?, ?, ?, ?, ?)"
    ):
        return (
            "INSERT INTO grades (student_id, semester, course_name, course_code, units, grade) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (student_id, semester, course_name) DO UPDATE SET "
            "course_code = EXCLUDED.course_code, units = EXCLUDED.units, grade = EXCLUDED.grade"
        )

    if n == _norm("INSERT OR IGNORE INTO prereqs (course_name, required_course_name) VALUES (?,?)"):
        return (
            "INSERT INTO prereqs (course_name, required_course_name) VALUES (?,?) "
            "ON CONFLICT (course_name, required_course_name) DO NOTHING"
        )

    if n == _norm(
        "INSERT OR IGNORE INTO registrations (student_id, course_name) VALUES (?,?)"
    ):
        return (
            "INSERT INTO registrations (student_id, course_name) VALUES (?,?) "
            "ON CONFLICT (student_id, course_name) DO NOTHING"
        )

    if n == _norm(
        "INSERT OR IGNORE INTO students (student_id, student_name, university_number) VALUES (?,?,?)"
    ):
        return "INSERT INTO students (student_id, student_name, university_number) VALUES (?,?,?) ON CONFLICT (student_id) DO NOTHING"

    if n == _norm("INSERT OR IGNORE INTO students (student_id, student_name) VALUES (?,?)"):
        return (
            "INSERT INTO students (student_id, student_name) VALUES (?,?) "
            "ON CONFLICT (student_id) DO NOTHING"
        )

    if n == _norm("INSERT OR REPLACE INTO students (student_id, student_name) VALUES (?,?)"):
        return (
            "INSERT INTO students (student_id, student_name) VALUES (?,?) "
            "ON CONFLICT (student_id) DO UPDATE SET student_name = EXCLUDED.student_name"
        )

    if n == _norm(
        "INSERT OR IGNORE INTO student_supervisor (student_id, instructor_id) VALUES (?, ?)"
    ):
        return (
            "INSERT INTO student_supervisor (student_id, instructor_id) VALUES (?, ?) "
            "ON CONFLICT (student_id, instructor_id) DO NOTHING"
        )

    if n == _norm(
        "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, 'admin')"
    ):
        return (
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin') "
            "ON CONFLICT (username) DO NOTHING"
        )

    # academic_rules — INSERT OR IGNORE
    if "INSERT OR IGNORE INTO academic_rules" in s and "VALUES (?, ?, ?, ?, ?, ?, 1)" in _norm(s):
        return (
            s.replace("INSERT OR IGNORE INTO academic_rules", "INSERT INTO academic_rules", 1).replace(
                "VALUES (?, ?, ?, ?, ?, ?, 1)",
                "VALUES (?, ?, ?, ?, ?, ?, 1) ON CONFLICT (rule_key) DO NOTHING",
                1,
            )
        )

    # academic_rules — INSERT OR REPLACE
    if "INSERT OR REPLACE INTO academic_rules" in s and "VALUES (?, ?, ?, ?, ?, ?, ?)" in _norm(s):
        return (
            s.replace("INSERT OR REPLACE INTO academic_rules", "INSERT INTO academic_rules", 1).replace(
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (rule_key) DO UPDATE SET "
                "title = EXCLUDED.title, description = EXCLUDED.description, "
                "category = EXCLUDED.category, value_number = EXCLUDED.value_number, "
                "value_text = EXCLUDED.value_text, is_active = EXCLUDED.is_active",
                1,
            )
        )

    # grades_new INSERT OR REPLACE
    if n == _norm(
        "INSERT OR REPLACE INTO grades (student_id, semester, course_name, course_code, units, grade) VALUES (?, ?, ?, ?, ?, ?)"
    ):
        return (
            "INSERT INTO grades (student_id, semester, course_name, course_code, units, grade) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (student_id, semester, course_name) DO UPDATE SET "
            "course_code = EXCLUDED.course_code, units = EXCLUDED.units, grade = EXCLUDED.grade"
        )

    # --- INSERT OR REPLACE INTO students (متعدد الأسطر من core/services) ---
    if "INSERT OR REPLACE INTO students" in s and "join_year" in n:
        return (
            "INSERT INTO students ( student_id, student_name, enrollment_status, status_changed_at, "
            "graduation_plan, join_term, join_year ) VALUES ( ?, ?, COALESCE((SELECT enrollment_status "
            "FROM students WHERE student_id = ?), 'active'), COALESCE((SELECT status_changed_at FROM students "
            "WHERE student_id = ?), CURRENT_TIMESTAMP), ?, ?, ? ) "
            "ON CONFLICT (student_id) DO UPDATE SET student_name = EXCLUDED.student_name, "
            "enrollment_status = EXCLUDED.enrollment_status, status_changed_at = EXCLUDED.status_changed_at, "
            "graduation_plan = EXCLUDED.graduation_plan, join_term = EXCLUDED.join_term, "
            "join_year = EXCLUDED.join_year"
        )
    if "INSERT OR REPLACE INTO students" in s and "graduation_plan" in n and "join_year" not in n:
        return (
            "INSERT INTO students ( student_id, student_name, enrollment_status, status_changed_at, graduation_plan ) "
            "VALUES ( ?, ?, COALESCE((SELECT enrollment_status FROM students WHERE student_id = ?), 'active'), "
            "COALESCE((SELECT status_changed_at FROM students WHERE student_id = ?), CURRENT_TIMESTAMP), ? ) "
            "ON CONFLICT (student_id) DO UPDATE SET student_name = EXCLUDED.student_name, "
            "enrollment_status = EXCLUDED.enrollment_status, status_changed_at = EXCLUDED.status_changed_at, "
            "graduation_plan = EXCLUDED.graduation_plan"
        )
    if "INSERT OR REPLACE INTO students" in s and "enrollment_status" in n and "graduation_plan" not in n:
        return (
            "INSERT INTO students ( student_id, student_name, enrollment_status, status_changed_at ) VALUES ( "
            "?, ?, COALESCE((SELECT enrollment_status FROM students WHERE student_id = ?), 'active'), "
            "COALESCE((SELECT status_changed_at FROM students WHERE student_id = ?), CURRENT_TIMESTAMP) ) "
            "ON CONFLICT (student_id) DO UPDATE SET student_name = EXCLUDED.student_name, "
            "enrollment_status = EXCLUDED.enrollment_status, status_changed_at = EXCLUDED.status_changed_at"
        )

    # INSERT OR REPLACE INTO grades (multiline من core/services)
    if "INSERT OR REPLACE INTO grades" in s and _norm(s).startswith("INSERT OR REPLACE INTO grades"):
        return (
            "INSERT INTO grades (student_id, semester, course_name, course_code, units, grade) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (student_id, semester, course_name) DO UPDATE SET "
            "course_code = EXCLUDED.course_code, units = EXCLUDED.units, grade = EXCLUDED.grade"
        )

    # INSERT OR IGNORE students — قيمة فرعية (grades_new)
    if (
        "INSERT OR IGNORE INTO students (student_id, student_name)" in _norm(s)
        and "COALESCE((SELECT student_name FROM students WHERE student_id = ?)" in _norm(s)
    ):
        return (
            "INSERT INTO students (student_id, student_name) VALUES (?, COALESCE((SELECT student_name "
            "FROM students WHERE student_id = ?), '')) ON CONFLICT (student_id) DO NOTHING"
        )

    # INSERT OR IGNORE students — سطر واحد
    if n == _norm("INSERT OR IGNORE INTO students (student_id, student_name) VALUES (?,?)"):
        return (
            "INSERT INTO students (student_id, student_name) VALUES (?,?) "
            "ON CONFLICT (student_id) DO NOTHING"
        )

    return s
