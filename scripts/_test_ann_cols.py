from backend.services.utilities import get_connection

with get_connection() as conn:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, COALESCE(title,''), COALESCE(body,''), COALESCE(announcement_type,'general'),
               COALESCE(lecture_date,''), COALESCE(published_to_students,1), COALESCE(created_at,'')
        FROM faculty_course_announcements
        WHERE section_id = ? AND instructor_id = ?
        ORDER BY id DESC LIMIT 3
        """,
        (21, 2),
    )
    rows = cur.fetchall()
    print("description:", [d[0] for d in (cur.description or [])])
    for i, r in enumerate(rows):
        print(f"row {i}:", [r[j] for j in range(len(r))])
