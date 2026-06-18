from backend.services.utilities import get_connection
from backend.services.multi_surveys import get_template_by_code, list_template_questions, aggregate_template
from backend.services.quality_metrics import term_label_from_conn

with get_connection() as conn:
    sem = term_label_from_conn(conn)
    tpl = get_template_by_code(conn, "faculty_dean")
    qs = list_template_questions(conn, int(tpl["id"]))
    print("QUESTIONS:", len(qs))
    for q in qs:
        print(q["sort_order"], q["id"], q["label_ar"][:70])
    cur = conn.cursor()
    n = cur.execute(
        "SELECT COUNT(*) AS c FROM survey_responses WHERE template_code='faculty_dean' AND semester=%s",
        (sem,),
    ).fetchone()["c"]
    print("responses this sem:", n)
    agg = aggregate_template(conn, "faculty_dean", semester=sem)
    print("overall:", agg.get("overall_score_percent"))
    for item in agg.get("items") or []:
        if int(item.get("sort_order") or 0) in (20, 25, 30):
            print("item", item.get("sort_order"), item.get("score_percent"), item.get("label_ar", "")[:50])
