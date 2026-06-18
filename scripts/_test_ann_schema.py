from backend.services.utilities import get_connection

with get_connection() as conn:
    cur = conn.cursor()
    cols = cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='faculty_course_announcements' ORDER BY ordinal_position"
    ).fetchall()
    print("schema:", cols)
    rows = cur.execute("SELECT * FROM faculty_course_announcements WHERE section_id=21 LIMIT 2").fetchall()
    print("raw rows:", rows)
    if cur.description:
        print("cols order:", [d[0] for d in cur.description])
