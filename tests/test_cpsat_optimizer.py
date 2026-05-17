"""اختبارات محرك CP-SAT (تُتخطى إذا OR-Tools غير مثبت)."""
import pytest

from backend.services.schedule_cpsat import cpsat_available, generate_moves_cpsat
from backend.services.schedule_optimizer import OptimizeParams


pytestmark = pytest.mark.skipif(not cpsat_available(), reason="OR-Tools not installed")


def _insert_schedule(conn, course, day, time, room="", instructor=""):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, semester)
        VALUES (?, ?, ?, ?, ?, '')
        """,
        (course, day, time, room, instructor),
    )
    conn.commit()


class TestCpsatOptimizer:
    def test_cpsat_finds_move_for_room_conflict(self, db_conn):
        _insert_schedule(db_conn, "A", "السبت", "09:00-11:00", room="قاعة_1", instructor="أ1")
        _insert_schedule(db_conn, "B", "السبت", "10:00-12:00", room="قاعة_1", instructor="أ2")
        moves = generate_moves_cpsat(db_conn, OptimizeParams(time_limit_seconds=15))
        assert len(moves) >= 1
