from celery import Celery

from app.core.config import settings


celery_app = Celery(
    "test_platform",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_track_started=True,
    timezone="Asia/Shanghai",
    enable_utc=False,
    result_expires=3600,
    imports=("app.tasks.executions",),
)

