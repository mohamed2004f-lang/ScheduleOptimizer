"""تشخيص تقييم مقرر لطالب محدد — استخدام مؤقت."""
from backend.services.utilities import get_connection
from backend.services.quality_metrics import term_label_from_conn
from backend.services.course_evaluations import (
    _student_evaluable_sections,
    list_pending_course_evaluations,
)

SID = "3409"
COURSE_HINT = "مقاومة مواد"


def main() -> None:
    with get_connection() as conn:
        cur = conn.cursor()
        sem = term_label_from_conn(conn)
        print("=== CURRENT SEMESTER ===", sem)

        st = cur.execute(
            "SELECT student_id, student_name FROM students WHERE student_id = ?",
            (SID,),
        ).fetchall()
        print("=== STUDENT ===")
        for r in st:
            print(dict(r))

        regs = cur.execute(
            """
            SELECT student_id, course_name, teaching_group_id, program_course_id
            FROM registrations
            WHERE student_id = ?
            ORDER BY course_name
            """,
            (SID,),
        ).fetchall()
        print("=== ALL REGISTRATIONS ===")
        for r in regs:
            print(dict(r))

        regs_match = cur.execute(
            """
            SELECT student_id, course_name, teaching_group_id, program_course_id
            FROM registrations
            WHERE student_id = ?
              AND lower(trim(course_name)) LIKE lower(?)
            """,
            (SID, f"%{COURSE_HINT}%"),
        ).fetchall()
        print("=== REGISTRATIONS (matching course hint) ===")
        for r in regs_match:
            print(dict(r))

        sch = cur.execute(
            """
            SELECT id, course_name, instructor, instructor_id, semester
            FROM schedule
            WHERE lower(trim(course_name)) LIKE lower(?)
            ORDER BY course_name, instructor
            LIMIT 20
            """,
            (f"%{COURSE_HINT}%",),
        ).fetchall()
        print("=== SCHEDULE (sample) ===")
        for r in sch:
            print(dict(r))

        try:
            tg = cur.execute(
                """
                SELECT tg.id, tg.semester, tg.course_name, tg.instructor_id, i.name AS instructor_name
                FROM teaching_groups tg
                LEFT JOIN instructors i ON i.id = tg.instructor_id
                WHERE lower(trim(tg.course_name)) LIKE lower(?)
                ORDER BY tg.semester DESC, tg.id
                LIMIT 20
                """,
                (f"%{COURSE_HINT}%",),
            ).fetchall()
            print("=== TEACHING GROUPS ===")
            for r in tg:
                print(dict(r))
        except Exception as exc:
            print("TG error:", exc)
            try:
                conn.rollback()
            except Exception:
                pass

        ev_all = cur.execute(
            """
            SELECT id, student_id, section_id, teaching_group_id, course_name,
                   instructor_id, semester, created_at
            FROM course_evaluations
            WHERE student_id = ?
            ORDER BY created_at DESC
            """,
            (SID,),
        ).fetchall()
        print("=== ALL COURSE EVALUATIONS (student) ===")
        for r in ev_all:
            print(dict(r))

        ev = cur.execute(
            """
            SELECT *
            FROM course_evaluations
            WHERE student_id = ?
              AND lower(trim(course_name)) LIKE lower(?)
            ORDER BY created_at DESC
            """,
            (SID, f"%{COURSE_HINT}%"),
        ).fetchall()
        print("=== COURSE EVALUATIONS ===")
        for r in ev:
            print(dict(r))

        sections = _student_evaluable_sections(conn, SID, sem)
        match_secs = [
            s
            for s in sections
            if COURSE_HINT.lower() in (s.get("course_name") or "").lower()
        ]
        print("=== EVALUABLE SECTIONS (current sem) ===")
        for s in match_secs:
            print(s)

        pending = list_pending_course_evaluations(conn, SID, semester=sem)
        match_pending = [
            p
            for p in pending
            if COURSE_HINT.lower()
            in (p.get("course_name") or p.get("title_ar") or "").lower()
        ]
        print("=== PENDING (matching course) ===")
        for p in match_pending:
            print(p.get("title_ar"), "|", p.get("fill_url"))
        print("=== TOTAL PENDING ===", len(pending))

        for row in ev:
            eid = row["id"]
            ans = cur.execute(
                """
                SELECT q.label_ar, q.legacy_key, a.rating
                FROM evaluation_survey_answers a
                JOIN evaluation_survey_questions q ON q.id = a.question_id
                WHERE a.evaluation_id = ?
                ORDER BY q.sort_order
                """,
                (eid,),
            ).fetchall()
            print(f"=== ANSWERS for eval id {eid} ===")
            for a in ans:
                print(dict(a))


if __name__ == "__main__":
    main()
