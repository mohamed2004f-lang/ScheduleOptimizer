"""
تهيئة ابتدائية (تجريبية) لعدة أقسام + برنامج القسم العام + برامج التخصص،
ومثال لمقرر مشترك (course_master واحد) بأكواد مختلفة عبر program_courses.

تشغيل (من جذر المشروع، مع DATABASE_URL لـ PostgreSQL):
  python scripts/seed_departments_programs_demo.py

آمن للتكرار: يستخدم ON CONFLICT / OR IGNORE حيث يناسب.
"""
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.database.database import ensure_tables, get_connection, is_postgresql  # noqa: E402

# معرّف ثابت للتمييز عند إعادة التشغيل
DEMO_THERMO_TITLE_AR = "الثيرموديناميك الهندسي (مثال مشترك بين الأقسام)"

# (code, name_ar, name_en)
DEPARTMENTS = [
    ("GENERAL", "القسم العام (كلية الهندسة)", "General Year"),
    ("MECH", "الهندسة الميكانيكية", "Mechanical Engineering"),
    ("CIVIL", "الهندسة المدنية", "Civil Engineering"),
    ("ELEC", "الهندسة الكهربائية", "Electrical Engineering"),
    ("RENEW", "هندسة الطاقات المتجددة", "Renewable Energy Engineering"),
]

# (dept_code, program_code, name_ar, phase, min_total_units, rules_json)
PROGRAMS = [
    (
        "GENERAL",
        "PROG_U1",
        "المرحلة التأسيسية / القسم العام",
        "general",
        0,
        '{"note_ar":"مثال: بعد استيفاء شروط التخصص (مثلاً 22 من 36 وحدة) ينتقل الطالب لبرنامج قسم علمي."}',
    ),
    ("MECH", "PROG_MAJOR", "بكالوريوس الهندسة الميكانيكية", "major", 160, ""),
    ("CIVIL", "PROG_MAJOR", "بكالوريوس الهندسة المدنية", "major", 160, ""),
    ("ELEC", "PROG_MAJOR", "بكالوريوس الهندسة الكهربائية", "major", 160, ""),
    ("RENEW", "PROG_MAJOR", "بكالوريوس هندسة الطاقات المتجددة", "major", 160, ""),
]

# (dept_code للبرنامج, program_code, course_code, level_no, units_override أو None)
# نفس course_master يظهر بأكواد ومستويات مختلفة حسب الخطة
PROGRAM_COURSE_ROWS = [
    ("GENERAL", "PROG_U1", "EN201", 2, 3),
    ("MECH", "PROG_MAJOR", "ME201", 2, 3),
    ("CIVIL", "PROG_MAJOR", "CE301", 3, 3),
    ("ELEC", "PROG_MAJOR", "EE214", 3, 3),
    ("RENEW", "PROG_MAJOR", "RE220", 2, 3),
]


def _row_id(row) -> int:
    if row is None:
        raise RuntimeError("row is None")
    if isinstance(row, (list, tuple)):
        return int(row[0])
    return int(row["id"])


def _ensure_department(cur, code: str, name_ar: str, name_en: str, pg: bool) -> int:
    if pg:
        cur.execute(
            """
            INSERT INTO departments (code, name_ar, name_en)
            VALUES (%s, %s, %s)
            ON CONFLICT (code) DO UPDATE
            SET name_ar = EXCLUDED.name_ar, name_en = EXCLUDED.name_en
            RETURNING id
            """,
            (code, name_ar, name_en),
        )
        r = cur.fetchone()
        return _row_id(r)
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en) VALUES (?, ?, ?)",
        (code, name_ar, name_en),
    )
    cur.execute("SELECT id FROM departments WHERE code = ?", (code,))
    return _row_id(cur.fetchone())


def _ensure_program(
    cur,
    department_id: int,
    code: str,
    name_ar: str,
    phase: str,
    min_total_units: int,
    rules_json: str,
    pg: bool,
) -> int:
    if pg:
        cur.execute(
            """
            INSERT INTO programs (department_id, code, name_ar, phase, min_total_units, rules_json)
            VALUES (%s, %s, %s, %s, %s, NULLIF(%s, ''))
            ON CONFLICT (department_id, code) DO UPDATE
            SET name_ar = EXCLUDED.name_ar,
                phase = EXCLUDED.phase,
                min_total_units = EXCLUDED.min_total_units,
                rules_json = EXCLUDED.rules_json
            RETURNING id
            """,
            (department_id, code, name_ar, phase, min_total_units, rules_json or ""),
        )
        return _row_id(cur.fetchone())
    cur.execute(
        """
        INSERT OR IGNORE INTO programs
        (department_id, code, name_ar, phase, min_total_units, rules_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (department_id, code, name_ar, phase, min_total_units, rules_json or None),
    )
    cur.execute(
        "SELECT id FROM programs WHERE department_id = ? AND code = ?",
        (department_id, code),
    )
    return _row_id(cur.fetchone())


def _ensure_course_master(cur, pg: bool) -> int:
    cur.execute("SELECT id FROM course_master WHERE title_ar = ?", (DEMO_THERMO_TITLE_AR,))
    r = cur.fetchone()
    if r:
        return _row_id(r)
    if pg:
        cur.execute(
            """
            INSERT INTO course_master
            (title_ar, title_en, description, default_units, grading_mode, assessment_type)
            VALUES (%s, %s, %s, %s, 'partial_final', 'theoretical')
            RETURNING id
            """,
            (
                DEMO_THERMO_TITLE_AR,
                "Engineering Thermodynamics (shared demo)",
                "مثال تهيئة: نفس المحتوى الأكاديمي بأكواد ومستويات مختلفة في كل خطة.",
                3,
            ),
        )
        return _row_id(cur.fetchone())
    cur.execute(
        """
        INSERT INTO course_master
        (title_ar, title_en, description, default_units, grading_mode, assessment_type)
        VALUES (?, ?, ?, ?, 'partial_final', 'theoretical')
        """,
        (
            DEMO_THERMO_TITLE_AR,
            "Engineering Thermodynamics (shared demo)",
            "مثال تهيئة: نفس المحتوى الأكاديمي بأكواد ومستويات مختلفة في كل خطة.",
            3,
        ),
    )
    cur.execute("SELECT id FROM course_master WHERE title_ar = ?", (DEMO_THERMO_TITLE_AR,))
    return _row_id(cur.fetchone())


def _ensure_program_course(
    cur,
    program_id: int,
    course_master_id: int,
    course_code: str,
    level_no: int,
    units_override: int | None,
    pg: bool,
) -> None:
    if pg:
        cur.execute(
            """
            INSERT INTO program_courses
            (program_id, course_master_id, course_code, level_no, units_override, category)
            VALUES (%s, %s, %s, %s, %s, 'required')
            ON CONFLICT (program_id, course_code) DO UPDATE
            SET course_master_id = EXCLUDED.course_master_id,
                level_no = EXCLUDED.level_no,
                units_override = EXCLUDED.units_override
            """,
            (program_id, course_master_id, course_code, level_no, units_override),
        )
    else:
        cur.execute(
            """
            INSERT INTO program_courses
            (program_id, course_master_id, course_code, level_no, units_override, category)
            VALUES (?, ?, ?, ?, ?, 'required')
            ON CONFLICT (program_id, course_code) DO UPDATE SET
                course_master_id = excluded.course_master_id,
                level_no = excluded.level_no,
                units_override = excluded.units_override
            """,
            (program_id, course_master_id, course_code, level_no, units_override),
        )


def main() -> None:
    ensure_tables()
    pg = is_postgresql()
    with get_connection() as conn:
        cur = conn.cursor()
        dept_ids: dict[str, int] = {}
        for code, name_ar, name_en in DEPARTMENTS:
            did = _ensure_department(cur, code, name_ar, name_en, pg)
            dept_ids[code] = did
            print(f"[ok] department {code} -> id={did}")

        prog_ids: dict[tuple[str, str], int] = {}
        for dept_code, pcode, name_ar, phase, min_u, rules in PROGRAMS:
            d_id = dept_ids[dept_code]
            pid = _ensure_program(cur, d_id, pcode, name_ar, phase, min_u, rules, pg)
            prog_ids[(dept_code, pcode)] = pid
            print(f"[ok] program {dept_code}/{pcode} -> id={pid}")

        cm_id = _ensure_course_master(cur, pg)
        print(f"[ok] course_master demo -> id={cm_id} ({DEMO_THERMO_TITLE_AR})")

        for dept_code, pcode, ccode, level_no, u in PROGRAM_COURSE_ROWS:
            p_id = prog_ids[(dept_code, pcode)]
            _ensure_program_course(cur, p_id, cm_id, ccode, level_no, u, pg)
            print(
                f"[ok] program_courses program_id={p_id} ({dept_code}/{pcode}) "
                f"code={ccode} level={level_no} master_id={cm_id}"
            )

        conn.commit()

    print("\nDone. جرّب الاستعلام:")
    print(
        "  SELECT d.code, p.code, pc.course_code, pc.level_no, cm.title_ar\n"
        "  FROM program_courses pc\n"
        "  JOIN programs p ON p.id = pc.program_id\n"
        "  JOIN departments d ON d.id = p.department_id\n"
        "  JOIN course_master cm ON cm.id = pc.course_master_id\n"
        "  WHERE cm.title_ar LIKE '%مثال مشترك%'\n"
        "  ORDER BY d.code, pc.course_code;"
    )


if __name__ == "__main__":
    if not os.environ.get("DATABASE_URL"):
        print("تنبيه: لم يُضبط DATABASE_URL — سيُستخدم الإعداد الافتراضي من config/.env", file=sys.stderr)
    main()
