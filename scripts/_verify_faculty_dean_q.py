from backend.services.multi_surveys import ensure_survey_platform_tables, aggregate_template
from backend.services.utilities import get_connection
from backend.services.quality_metrics import term_label_from_conn

with get_connection() as conn:
    ensure_survey_platform_tables(conn)
    sem = term_label_from_conn(conn)
    cur = conn.cursor()
    tid = cur.execute(
        "SELECT id FROM survey_templates WHERE code='faculty_dean'"
    ).fetchone()["id"]
    qs = cur.execute(
        "SELECT id, sort_order, label_ar FROM survey_questions WHERE template_id=%s ORDER BY sort_order",
        (tid,),
    ).fetchall()
    print("QUESTIONS", len(qs))
    for q in qs:
        print(q["sort_order"], q["id"], q["label_ar"][:65])
    agg = aggregate_template(conn, "faculty_dean", semester=sem)
    for q in agg.get("questions") or []:
        if int(q.get("sort_order") or 0) in (20, 25):
            print("SCORE", q.get("sort_order"), q.get("score_percent"), "%")
    internal = [
        q
        for q in agg.get("questions") or []
        if "توزيع موارد" in (q.get("label_ar") or "")
        or "توزيع الموارد" in (q.get("label_ar") or "")
    ]
    print("removed internal in results:", len(internal) == 0)
