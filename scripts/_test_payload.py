from backend.services.utilities import get_connection
from backend.services.schedule import _course_admin_payload

with get_connection() as conn:
    cur = conn.cursor()
    try:
        payload = _course_admin_payload(cur, 2, 21)
        print("OK", payload.get("announcements"))
    except Exception as e:
        print("FAIL", e)
        import traceback
        traceback.print_exc()
