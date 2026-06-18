"""تشخيص استبيان faculty_dean لأستاذ محدد."""
from backend.services.utilities import get_connection
from backend.services.quality_metrics import term_label_from_conn

INSTRUCTOR_ID = 2
TEMPLATE = "faculty_dean"


def main() -> None:
    with get_connection() as conn:
        cur = conn.cursor()
        sem = term_label_from_conn(conn)
        inst = cur.execute(
            "SELECT id, name FROM instructors WHERE id = %s", (INSTRUCTOR_ID,)
        ).fetchone()
        print("INSTRUCTOR:", dict(inst))
        print("SEMESTER:", sem)

        tpl = cur.execute(
            "SELECT id, code, title_ar, respondent_role FROM survey_templates WHERE code = %s",
            (TEMPLATE,),
        ).fetchone()
        print("TEMPLATE:", dict(tpl))

        rows = cur.execute(
            """
            SELECT r.id, r.template_code, r.semester, r.respondent_role, r.respondent_id,
                   r.subject_type, r.subject_id, r.department_id, r.submitted_at, r.submitted_by
            FROM survey_responses r
            WHERE r.template_code = %s
              AND r.respondent_id = %s
            ORDER BY r.submitted_at DESC
            """,
            (TEMPLATE, str(INSTRUCTOR_ID)),
        ).fetchall()
        print("RESPONSES (instructor_id key):", len(rows))
        for r in rows:
            d = dict(r)
            ans_n = cur.execute(
                "SELECT COUNT(*) AS c FROM survey_response_answers WHERE response_id = %s",
                (d["id"],),
            ).fetchone()["c"]
            d["answer_count"] = ans_n
            print(d)

        users = cur.execute(
            "SELECT username, role, instructor_id FROM users WHERE instructor_id = %s",
            (INSTRUCTOR_ID,),
        ).fetchall()
        print("USERS:", [dict(u) for u in users])
        for u in users:
            uname = u["username"]
            rows2 = cur.execute(
                """
                SELECT r.id, r.semester, r.respondent_id, r.submitted_at
                FROM survey_responses r
                WHERE r.template_code = %s AND r.respondent_id = %s
                """,
                (TEMPLATE, uname),
            ).fetchall()
            if rows2:
                print("By username", uname, ":", [dict(x) for x in rows2])


if __name__ == "__main__":
    main()
