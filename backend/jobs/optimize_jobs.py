"""
تشغيل تحسين الجدول في الخلفية (خيط محلي أو Celery+Redis).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

def get_connection():
    from backend.services import utilities

    return utilities.get_connection()

logger = logging.getLogger(__name__)

OPTIMIZE_ASYNC_THRESHOLD = int(os.environ.get("OPTIMIZE_ASYNC_THRESHOLD", "50"))
USE_CELERY = bool((os.environ.get("CELERY_BROKER_URL") or "").strip())


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_job_table(conn) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS optimize_jobs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'pending',
            params_json TEXT,
            result_json TEXT,
            error_message TEXT,
            created_at TEXT,
            started_at TEXT,
            finished_at TEXT
        )
        """
    )
    conn.commit()


def create_optimize_job(params_dict: dict) -> str:
    job_id = uuid.uuid4().hex
    with get_connection() as conn:
        _ensure_job_table(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO optimize_jobs (id, status, params_json, created_at)
            VALUES (?, 'pending', ?, ?)
            """,
            (job_id, json.dumps(params_dict or {}, ensure_ascii=False), _now_iso()),
        )
        conn.commit()
    _dispatch_job(job_id)
    return job_id


def _dispatch_job(job_id: str) -> None:
    if os.environ.get("FLASK_ENV") == "testing" or os.environ.get("PYTEST_CURRENT_TEST"):
        _run_job_sync(job_id)
        return
    if USE_CELERY:
        try:
            from backend.celery_app import run_optimize_job_task

            run_optimize_job_task.delay(job_id)
            return
        except Exception as exc:
            logger.warning("Celery dispatch failed, using thread: %s", exc)
    t = threading.Thread(target=_run_job_sync, args=(job_id,), daemon=True)
    t.start()


def _run_job_sync(job_id: str) -> None:
    from backend.services.schedule_optimizer import OptimizeParams, optimize_with_move_suggestions

    try:
        with get_connection() as conn:
            _ensure_job_table(conn)
            cur = conn.cursor()
            row = cur.execute(
                "SELECT params_json FROM optimize_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if not row:
                return
            params_raw = row[0] if isinstance(row, (list, tuple)) else row["params_json"]
            params = OptimizeParams.from_dict(json.loads(params_raw or "{}"))
            cur.execute(
                "UPDATE optimize_jobs SET status = 'running', started_at = ? WHERE id = ?",
                (_now_iso(), job_id),
            )
            conn.commit()

            stats = optimize_with_move_suggestions(conn, params, sync_optimized=True)
            cur.execute(
                """
                UPDATE optimize_jobs
                SET status = 'completed', result_json = ?, finished_at = ?, error_message = NULL
                WHERE id = ?
                """,
                (json.dumps(stats, ensure_ascii=False), _now_iso(), job_id),
            )
            conn.commit()
    except Exception as exc:
        logger.exception("optimize job %s failed", job_id)
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE optimize_jobs
                    SET status = 'failed', error_message = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (str(exc), _now_iso(), job_id),
                )
                conn.commit()
        except Exception:
            pass


def get_optimize_job(job_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        _ensure_job_table(conn)
        cur = conn.cursor()
        row = cur.execute("SELECT * FROM optimize_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        out = {
            "job_id": d.get("id"),
            "status": d.get("status"),
            "created_at": d.get("created_at"),
            "started_at": d.get("started_at"),
            "finished_at": d.get("finished_at"),
            "error_message": d.get("error_message"),
        }
        if d.get("result_json"):
            try:
                out["result"] = json.loads(d["result_json"])
            except json.JSONDecodeError:
                out["result"] = None
        return out


def should_run_async(params_dict: dict, section_count: int) -> bool:
    if params_dict.get("async") in (True, "true", "1", 1):
        return True
    if params_dict.get("async") in (False, "false", "0", 0):
        return False
    return section_count >= OPTIMIZE_ASYNC_THRESHOLD
