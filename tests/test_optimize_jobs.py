"""اختبارات مهام التحسين في الخلفية."""
import time

from backend.jobs.optimize_jobs import create_optimize_job, get_optimize_job
from backend.services.schedule_optimizer import _load_sections


def _insert_schedule(conn, n=3):
    cur = conn.cursor()
    for i in range(n):
        cur.execute(
            """
            INSERT INTO schedule (course_name, day, time, room, instructor, semester)
            VALUES (?, 'السبت', '09:00-11:00', ?, 'أستاذ', '')
            """,
            (f"c_{i}", f"r_{i}"),
        )
    conn.commit()


class TestOptimizeJobs:
    def test_async_job_completes(self, db_conn):
        _insert_schedule(db_conn, 2)
        job_id = create_optimize_job({"max_alternatives_per_section": 2, "move_cost": 1.0})
        assert job_id
        for _ in range(50):
            job = get_optimize_job(job_id)
            assert job is not None
            if job["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)
        assert job["status"] == "completed"
        assert job.get("result", {}).get("schedule_rows", 0) >= 2
