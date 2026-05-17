"""
تطبيق Celery اختياري — يُفعَّل عند تعيين CELERY_BROKER_URL.
تشغيل العامل: celery -A backend.celery_app worker --loglevel=info
"""
from __future__ import annotations

import os

_broker = (os.environ.get("CELERY_BROKER_URL") or "").strip()
_backend = (os.environ.get("CELERY_RESULT_BACKEND") or _broker or "").strip()

if _broker:
    from celery import Celery

    celery_app = Celery("schedule_optimizer", broker=_broker, backend=_backend)
    celery_app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
    )

    @celery_app.task(name="schedule.run_optimize_job")
    def run_optimize_job_task(job_id: str) -> str:
        from backend.jobs.optimize_jobs import _run_job_sync

        _run_job_sync(job_id)
        return job_id
else:
    celery_app = None

    def run_optimize_job_task(job_id: str) -> None:  # noqa: F811
        from backend.jobs.optimize_jobs import _run_job_sync

        _run_job_sync(job_id)
