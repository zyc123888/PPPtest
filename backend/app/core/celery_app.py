from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.core.observability import setup_celery_observability


celery_app = Celery(
    "test_platform",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=6900,
    task_time_limit=7200,
    timezone="Asia/Shanghai",
    enable_utc=False,
    result_expires=3600,
    imports=("app.tasks.executions", "app.tasks.case_generation", "app.tasks.case_generation_v2"),
    task_routes={
        "app.tasks.case_generation.*": {"queue": "case_generation"},
        "app.tasks.case_generation_v2.*": {"queue": "case_generation"},
        "app.tasks.run_api_case": {"queue": "execution_fast"},
        "app.tasks.run_ui_case": {"queue": "execution_browser"},
        "app.tasks.run_ui_batch": {"queue": "execution_browser"},
        "app.tasks.run_performance_case": {"queue": "execution_perf"},
        "app.tasks.run_test_plan": {"queue": "execution_browser"},
        "app.tasks.scan_scheduled_plans": {"queue": "execution_fast"},
        "app.tasks.reconcile_interrupted_executions": {"queue": "maintenance"},
        "app.tasks.cleanup_execution_artifacts": {"queue": "maintenance"},
        "app.tasks.executions.*": {"queue": "execution_browser"},
    },
    broker_transport_options={"visibility_timeout": 7500},
    beat_schedule={
        "scan-scheduled-plans": {
            "task": "app.tasks.scan_scheduled_plans",
            "schedule": 60.0,
            "options": {"queue": "execution_fast"},
        },
        "reconcile-interrupted-executions": {
            "task": "app.tasks.reconcile_interrupted_executions",
            "schedule": 60.0,
            "options": {"queue": "maintenance"},
        },
        "cleanup-execution-artifacts": {
            "task": "app.tasks.cleanup_execution_artifacts",
            "schedule": crontab(hour=4, minute=0),
            "options": {"queue": "maintenance"},
        },
    },
)

setup_celery_observability(celery_app)
