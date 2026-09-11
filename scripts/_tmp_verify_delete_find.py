from backend.database.database import get_connection
from backend.services.schedule import _find_schedule_row_for_write

with get_connection() as conn:
    row, sid = _find_schedule_row_for_write(
        conn,
        {
            "course_name": "ميكانيكا هندسية II",
            "day": "السبت",
            "time": "11:00-13:00",
        },
        0,
    )
    print("find_by_meta", sid, None if row is None else dict(row))
    row2, sid2 = _find_schedule_row_for_write(conn, {}, 1)
    print("find_by_id", sid2, None if row2 is None else dict(row2))
