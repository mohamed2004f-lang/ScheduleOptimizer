"""اختبارات محرك اقتراح نقل المقررات."""
import pytest

from backend.services.schedule_optimizer import (
    OptimizeParams,
    _room_conflict_section_ids,
    generate_proposed_moves,
    optimize_with_move_suggestions,
)


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
    return cur.lastrowid


class TestScheduleOptimizer:
    def test_room_conflict_detection(self, db_conn):
        sections = [
            {
                "section_id": 1,
                "course_name": "A",
                "day": "السبت",
                "time": "09:00-11:00",
                "room": "101",
                "instructor": "د. أ",
                "start_min": 9 * 60,
                "end_min": 11 * 60,
            },
            {
                "section_id": 2,
                "course_name": "B",
                "day": "السبت",
                "time": "10:00-12:00",
                "room": "101",
                "instructor": "د. ب",
                "start_min": 10 * 60,
                "end_min": 12 * 60,
            },
        ]
        ids = _room_conflict_section_ids(sections)
        assert 2 in ids

    def test_generate_moves_on_room_conflict(self, db_conn):
        _insert_schedule(db_conn, "ميكانيكا_1", "السبت", "09:00-11:00", room="قاعة_1", instructor="أستاذ_1")
        _insert_schedule(db_conn, "ميكانيكا_2", "السبت", "10:00-12:00", room="قاعة_1", instructor="أستاذ_2")
        moves = generate_proposed_moves(db_conn, OptimizeParams(max_alternatives_per_section=2))
        assert len(moves) >= 1
        assert moves[0]["new_day"] and moves[0]["new_time"]

    def test_optimize_with_move_suggestions(self, db_conn):
        _insert_schedule(db_conn, "مادة_1", "الأحد", "09:00-11:00", room="R1")
        stats = optimize_with_move_suggestions(db_conn, OptimizeParams())
        assert stats["schedule_rows"] >= 1
        assert "conflict_count" in stats
        assert stats.get("optimizer") in ("rule_based_slots", "cp_sat")
