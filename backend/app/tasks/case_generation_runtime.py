from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import (
    CaseGenerationArtifact,
    CaseGenerationAttempt,
    CaseGenerationJob,
    CaseGenerationV2Artifact,
    CaseGenerationV2Attempt,
    CaseGenerationV2Job,
)
from app.tasks.case_generation_v2_support.metrics import build_generation_metrics
from app.timeutil import utc_now_naive


logger = logging.getLogger(__name__)


class SupersededAttemptError(RuntimeError):
    """Raised when an older execution tries to write after a rerun took ownership."""


_ATTEMPT_ID: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "case_generation_attempt_id", default=None
)
_PIPELINE_VERSION: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "case_generation_pipeline_version", default=None
)
_RUN_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "case_generation_run_id", default=None
)
_MODEL_CALLS: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "case_generation_model_calls", default=None
)


def current_attempt_id() -> int | None:
    return _ATTEMPT_ID.get()


def current_pipeline_version() -> str | None:
    return _PIPELINE_VERSION.get()


def current_run_id() -> str | None:
    return _RUN_ID.get()


def record_model_call(item: dict) -> None:
    calls = _MODEL_CALLS.get()
    if calls is not None:
        calls.append(dict(item))


def current_model_calls() -> list[dict]:
    return [dict(item) for item in (_MODEL_CALLS.get() or [])]


@contextlib.contextmanager
def bind_attempt(attempt_id: int, pipeline_version: str, run_id: str | None = None) -> Iterator[None]:
    attempt_token = _ATTEMPT_ID.set(attempt_id)
    pipeline_token = _PIPELINE_VERSION.set(pipeline_version)
    run_token = _RUN_ID.set(run_id)
    calls_token = _MODEL_CALLS.set([])
    try:
        yield
    finally:
        _MODEL_CALLS.reset(calls_token)
        _RUN_ID.reset(run_token)
        _PIPELINE_VERSION.reset(pipeline_token)
        _ATTEMPT_ID.reset(attempt_token)


def _attempt_model(pipeline_version: str):
    return CaseGenerationV2Attempt if pipeline_version == "v2" else CaseGenerationAttempt


def _artifact_model(pipeline_version: str):
    return CaseGenerationV2Artifact if pipeline_version == "v2" else CaseGenerationArtifact


def _job_model(pipeline_version: str):
    return CaseGenerationV2Job if pipeline_version == "v2" else CaseGenerationJob


def create_attempt(
    db,
    job,
    *,
    pipeline_version: str,
    kind: str = "full",
    source_id: str | None = None,
):
    now = utc_now_naive()
    attempt_cls = _attempt_model(pipeline_version)
    job_cls = _job_model(pipeline_version)
    # Serialize ownership changes with any in-flight stage/finalization commit.
    # This makes the active_attempt_id the database source of truth instead of
    # trusting an ORM object that may have been loaded before a rerun.
    with db.no_autoflush:
        previous_attempt_id = db.scalar(
            select(job_cls.active_attempt_id)
            .where(job_cls.id == job.id)
            .with_for_update()
        )
    if previous_attempt_id:
        previous = db.get(attempt_cls, previous_attempt_id)
        if previous is not None and previous.status in {"PENDING", "RUNNING"}:
            previous.status = "SUPERSEDED"
            previous.summary = "执行已被新的重跑取代"
            previous.error_message = None
            previous.task_id = None
            previous.heartbeat_at = now
            previous.finished_at = now
    suffix = uuid.uuid4().hex[:10]
    run_id = f"run_{now.strftime('%Y%m%d_%H%M%S')}_{suffix}"
    attempt = attempt_cls(
        job_id=job.id,
        run_id=run_id,
        execution_token=uuid.uuid4().hex,
        kind=kind,
        source_id=source_id,
        status="PENDING",
        input_payload_json=dict(job.input_payload_json or {}),
        progress_json={"stages": []},
        summary="任务已提交，等待执行",
        heartbeat_at=now,
    )
    db.add(attempt)
    db.flush()
    job.active_attempt_id = attempt.id
    job.status = "PENDING"
    job.task_id = None
    job.started_at = None
    job.finished_at = None
    job.error_message = None
    job.progress_json = {"stages": []}
    db.commit()
    db.refresh(attempt)
    db.refresh(job)
    return attempt


def ensure_attempt(db, job, *, pipeline_version: str, attempt_id: int | None = None):
    attempt_cls = _attempt_model(pipeline_version)
    attempt = db.get(attempt_cls, attempt_id) if attempt_id else None
    if attempt is not None:
        if attempt.job_id != job.id:
            raise SupersededAttemptError("attempt 不属于当前任务")
        return attempt
    if job.active_attempt_id:
        attempt = db.get(attempt_cls, job.active_attempt_id)
        if attempt is not None:
            return attempt
    return create_attempt(db, job, pipeline_version=pipeline_version)


def assert_active_attempt(job, attempt_id: int | None = None, *, db=None) -> int | None:
    expected = attempt_id or current_attempt_id()
    if expected is None:
        return None
    active_attempt_id = getattr(job, "active_attempt_id", None)
    if db is not None:
        job_cls = _job_model(current_pipeline_version() or ("v2" if isinstance(job, CaseGenerationV2Job) else "v1"))
        with db.no_autoflush:
            active_attempt_id = db.scalar(
                select(job_cls.active_attempt_id)
                .where(job_cls.id == job.id)
                .with_for_update()
            )
    if active_attempt_id != expected:
        raise SupersededAttemptError(
            f"attempt #{expected} 已被 attempt #{active_attempt_id or '-'} 取代，停止写入"
        )
    return expected


def mark_attempt_running(db, job, attempt) -> None:
    assert_active_attempt(job, attempt.id, db=db)
    now = utc_now_naive()
    attempt.status = "RUNNING"
    attempt.started_at = attempt.started_at or now
    attempt.finished_at = None
    attempt.error_message = None
    attempt.heartbeat_at = now
    job.status = "RUNNING"
    job.started_at = attempt.started_at
    job.finished_at = None
    job.error_message = None
    db.commit()


def sync_attempt_from_job(db, job) -> None:
    attempt_id = assert_active_attempt(job, db=db)
    if attempt_id is None:
        return
    attempt = db.get(_attempt_model(current_pipeline_version() or "v1"), attempt_id)
    if attempt is None:
        raise SupersededAttemptError(f"attempt #{attempt_id} 不存在")
    attempt.progress_json = dict(job.progress_json or {})
    flag_modified(attempt, "progress_json")
    attempt.summary = job.summary
    attempt.status = job.status
    attempt.task_id = job.task_id
    attempt.heartbeat_at = utc_now_naive()


def _duration_ms_from_iso(started_at: str | None, ended_at: str | None) -> int:
    if not started_at or not ended_at:
        return 0
    try:
        started = datetime.fromisoformat(started_at)
        ended = datetime.fromisoformat(ended_at)
    except ValueError:
        return 0
    return max(int((ended - started).total_seconds() * 1000), 0)


def update_job_stage(db, job, key: str, title: str, status: str, summary: str) -> None:
    assert_active_attempt(job, db=db)
    progress = dict(job.progress_json or {})
    stages = list(progress.get("stages") or [])
    now_iso = utc_now_naive().isoformat()
    updated = False
    for item in stages:
        if item.get("key") != key:
            continue
        started_at = item.get("started_at") or now_iso
        item.update(
            {
                "title": title,
                "status": status,
                "summary": summary,
                "started_at": started_at,
                "updated_at": now_iso,
                "duration_ms": item.get("duration_ms") or 0 if status == "running" else _duration_ms_from_iso(started_at, now_iso),
            }
        )
        updated = True
        break
    if not updated:
        stages.append(
            {
                "key": key,
                "title": title,
                "status": status,
                "summary": summary,
                "started_at": now_iso,
                "updated_at": now_iso,
                "duration_ms": 0,
            }
        )
    progress["stages"] = stages
    job.progress_json = progress
    flag_modified(job, "progress_json")
    job.summary = summary
    sync_attempt_from_job(db, job)
    db.commit()


def mark_last_job_stage_failed(job, *, summary: str) -> None:
    progress = dict(job.progress_json or {})
    stages = list(progress.get("stages") or [])
    if not stages:
        return
    now_iso = utc_now_naive().isoformat()
    current = stages[-1]
    started_at = current.get("started_at") or now_iso
    current.update(
        {
            "status": "failed",
            "summary": summary,
            "updated_at": now_iso,
            "duration_ms": _duration_ms_from_iso(started_at, now_iso),
        }
    )
    progress["stages"] = stages
    job.progress_json = progress
    flag_modified(job, "progress_json")


def raise_if_job_cancelled(db, job_cls, job_id: int) -> None:
    current = db.get(job_cls, job_id)
    if current is None:
        return
    assert_active_attempt(current, db=db)
    if current.status == "CANCELLED":
        raise RuntimeError("任务已取消")


def finish_attempt(
    db,
    job,
    *,
    status: str,
    summary: str,
    error_message: str | None = None,
) -> bool:
    attempt_id = current_attempt_id()
    if attempt_id is None:
        return False
    try:
        assert_active_attempt(job, attempt_id, db=db)
    except SupersededAttemptError:
        db.rollback()
        return False
    attempt = db.get(_attempt_model(current_pipeline_version() or "v1"), attempt_id)
    if attempt is None:
        return False
    now = utc_now_naive()
    attempt.status = status
    attempt.summary = summary
    attempt.error_message = error_message
    attempt.progress_json = dict(job.progress_json or {})
    flag_modified(attempt, "progress_json")
    attempt.heartbeat_at = now
    attempt.finished_at = now
    attempt.task_id = None
    job.status = status
    job.summary = summary
    job.error_message = error_message
    job.task_id = None
    job.finished_at = now
    model_calls = current_model_calls()
    pipeline_version = current_pipeline_version() or "v1"
    artifact_cls = _artifact_model(pipeline_version)
    output_dir = attempt_output_dir(job.id, pipeline_version)
    if model_calls:
        trace_path = os.path.join(output_dir, "model_call_trace.json")
        trace_payload = {
            "run_id": attempt.run_id,
            "attempt_id": attempt.id,
            "call_count": len(model_calls),
            "prompt_tokens": sum(int((item.get("usage") or {}).get("prompt_tokens") or 0) for item in model_calls),
            "completion_tokens": sum(int((item.get("usage") or {}).get("completion_tokens") or 0) for item in model_calls),
            "total_tokens": sum(int((item.get("usage") or {}).get("total_tokens") or 0) for item in model_calls),
            "calls": model_calls,
        }
        Path(trace_path).write_text(json.dumps(trace_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        artifact = db.scalar(
            select(artifact_cls).where(
                artifact_cls.job_id == job.id,
                artifact_cls.attempt_id == attempt.id,
                artifact_cls.artifact_type == "model_call_trace",
            )
        )
        if artifact is None:
            artifact = artifact_cls(
                job_id=job.id,
                attempt_id=attempt.id,
                artifact_type="model_call_trace",
            )
            db.add(artifact)
        artifact.file_name = "model_call_trace.json"
        artifact.file_path = trace_path
        artifact.content_json = trace_payload
        artifact.expired_at = None
    db.flush()
    current_artifacts = list(
        db.scalars(
            select(artifact_cls).where(
                artifact_cls.job_id == job.id,
                artifact_cls.attempt_id == attempt.id,
                artifact_cls.artifact_type != "generation_metrics",
            )
        ).all()
    )
    metrics_payload = build_generation_metrics(
        job=job,
        attempt=attempt,
        artifacts=current_artifacts,
        model_calls=model_calls,
        pipeline_version=pipeline_version,
        status=status,
    )
    metrics_path = os.path.join(output_dir, "generation_metrics.json")
    Path(metrics_path).write_text(json.dumps(metrics_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    metrics_artifact = db.scalar(
        select(artifact_cls).where(
            artifact_cls.job_id == job.id,
            artifact_cls.attempt_id == attempt.id,
            artifact_cls.artifact_type == "generation_metrics",
        )
    )
    if metrics_artifact is None:
        metrics_artifact = artifact_cls(
            job_id=job.id,
            attempt_id=attempt.id,
            artifact_type="generation_metrics",
        )
        db.add(metrics_artifact)
    metrics_artifact.file_name = "generation_metrics.json"
    metrics_artifact.file_path = metrics_path
    metrics_artifact.content_json = metrics_payload
    metrics_artifact.expired_at = None
    db.commit()
    return True


def set_attempt_task_id(db, job, attempt, task_id: str | None) -> None:
    assert_active_attempt(job, attempt.id, db=db)
    attempt.task_id = task_id
    attempt.summary = job.summary
    job.task_id = task_id
    db.commit()


def attempt_output_dir(
    job_id: int,
    pipeline_version: str,
    attempt_id: int | None = None,
) -> str:
    root_dir = settings.report_output_dir
    if not os.path.isabs(root_dir):
        root_dir = os.path.abspath(root_dir)
    family = "case_generation_v2" if pipeline_version == "v2" else "case_generation"
    resolved_attempt_id = attempt_id if attempt_id is not None else current_attempt_id()
    suffix = f"attempt_{resolved_attempt_id}" if resolved_attempt_id is not None else "legacy"
    output_dir = os.path.join(root_dir, family, f"job_{job_id}", suffix)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    if not os.access(output_dir, os.W_OK):
        raise PermissionError(f"目录不可写：{output_dir}")
    return output_dir


class AttemptHeartbeat:
    def __init__(self, attempt_id: int, pipeline_version: str):
        self.attempt_id = attempt_id
        self.pipeline_version = pipeline_version
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _touch(self) -> None:
        db = SessionLocal()
        try:
            attempt = db.get(_attempt_model(self.pipeline_version), self.attempt_id)
            if attempt is None or attempt.status not in {"PENDING", "RUNNING"}:
                self._stop.set()
                return
            job = db.get(_job_model(self.pipeline_version), attempt.job_id)
            if job is None or job.active_attempt_id != attempt.id:
                attempt.status = "SUPERSEDED"
                attempt.summary = "执行已被新的重跑取代"
                attempt.error_message = None
                attempt.task_id = None
                attempt.finished_at = utc_now_naive()
                db.commit()
                self._stop.set()
                return
            attempt.heartbeat_at = utc_now_naive()
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("case generation heartbeat update failed for attempt %s", self.attempt_id)
        finally:
            db.close()

    def _run(self) -> None:
        self._touch()
        while not self._stop.wait(max(2, settings.case_gen_heartbeat_seconds)):
            self._touch()

    def __enter__(self):
        self._thread = threading.Thread(
            target=self._run,
            name=f"case-gen-heartbeat-{self.pipeline_version}-{self.attempt_id}",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)


def _active_celery_task_ids() -> set[str] | None:
    try:
        from app.core.celery_app import celery_app

        inspector = celery_app.control.inspect(timeout=1.0)
        groups = [inspector.active() or {}, inspector.reserved() or {}, inspector.scheduled() or {}]
        return {
            str(item.get("id"))
            for group in groups
            for tasks in group.values()
            for item in tasks or []
            if isinstance(item, dict) and item.get("id")
        }
    except Exception:
        logger.warning("unable to inspect Celery tasks for stale-attempt reconciliation", exc_info=True)
        return None


def reconcile_stale_attempts() -> dict[str, int]:
    now = utc_now_naive()
    active_task_ids = _active_celery_task_ids()
    running_cutoff = now - timedelta(seconds=max(settings.case_gen_attempt_stale_seconds, 60))
    pending_cutoff = now - timedelta(seconds=max(settings.case_gen_dispatch_stale_seconds, 30))
    reconciled = 0
    db = SessionLocal()
    try:
        for pipeline_version in ("v1", "v2"):
            attempt_cls = _attempt_model(pipeline_version)
            job_cls = _job_model(pipeline_version)
            attempts = list(
                db.scalars(
                    select(attempt_cls).where(attempt_cls.status.in_(["PENDING", "RUNNING"]))
                ).all()
            )
            for attempt in attempts:
                reference = attempt.heartbeat_at or attempt.started_at or attempt.created_at or now
                cutoff = running_cutoff if attempt.status == "RUNNING" else pending_cutoff
                if reference >= cutoff:
                    continue
                if active_task_ids is not None and attempt.task_id in active_task_ids:
                    continue
                attempt.status = "LOST"
                attempt.summary = "执行进程已失联"
                attempt.error_message = "任务心跳超时且 Celery 中无活跃执行，请重跑"
                attempt.finished_at = now
                attempt.task_id = None
                job = db.get(job_cls, attempt.job_id)
                if job is not None and job.active_attempt_id == attempt.id:
                    job.status = "FAILED"
                    job.summary = "任务执行进程已失联"
                    job.error_message = attempt.error_message
                    job.task_id = None
                    job.finished_at = now
                reconciled += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return {"reconciled": reconciled}


def _cleanup_output_storage(db, cutoff) -> int:
    root_dir = Path(settings.report_output_dir).resolve()
    removed_dirs = 0
    for pipeline_version, family in (("v1", "case_generation"), ("v2", "case_generation_v2")):
        family_dir = (root_dir / family).resolve()
        if not family_dir.is_dir() or root_dir not in family_dir.parents:
            continue
        artifact_cls = _artifact_model(pipeline_version)
        attempt_cls = _attempt_model(pipeline_version)
        job_cls = _job_model(pipeline_version)
        live_paths = {
            str(Path(path).resolve())
            for path in db.scalars(
                select(artifact_cls.file_path).where(
                    artifact_cls.expired_at.is_(None),
                    artifact_cls.file_path.is_not(None),
                )
            ).all()
            if path
        }
        active_attempt_ids = set(
            db.scalars(
                select(attempt_cls.id).where(attempt_cls.status.in_(["PENDING", "RUNNING"]))
            ).all()
        )
        valid_job_ids = set(db.scalars(select(job_cls.id)).all())
        for job_dir in family_dir.glob("job_*"):
            if not job_dir.is_dir() or job_dir.is_symlink():
                continue
            try:
                job_id = int(job_dir.name.removeprefix("job_"))
            except ValueError:
                continue
            for file_path in job_dir.rglob("*"):
                if not file_path.is_file() or file_path.is_symlink():
                    continue
                attempt_match = file_path.parent.name.removeprefix("attempt_")
                attempt_id = int(attempt_match) if attempt_match.isdigit() else None
                if attempt_id in active_attempt_ids:
                    continue
                try:
                    modified_at = file_path.stat().st_mtime
                except OSError:
                    continue
                if str(file_path.resolve()) not in live_paths and modified_at < cutoff.timestamp():
                    try:
                        file_path.unlink()
                    except OSError as exc:
                        logger.warning("unable to remove orphan case-generation file %s: %s", file_path, exc)
            for candidate in sorted(
                (path for path in job_dir.rglob("*") if path.is_dir() and not path.is_symlink()),
                key=lambda path: len(path.parts),
                reverse=True,
            ):
                try:
                    candidate.rmdir()
                    removed_dirs += 1
                except OSError:
                    pass
            try:
                job_dir.rmdir()
                removed_dirs += 1
            except OSError:
                # A non-empty directory still contains a live artifact or a file
                # newer than the retention cutoff. Keep it for the next sweep,
                # including when its job row has already disappeared.
                pass
    return removed_dirs


def expire_old_artifacts() -> dict[str, int]:
    cutoff = utc_now_naive() - timedelta(days=max(1, settings.case_gen_artifact_retention_days))
    expired = 0
    db = SessionLocal()
    try:
        for pipeline_version in ("v1", "v2"):
            artifact_cls = _artifact_model(pipeline_version)
            artifacts = list(
                db.scalars(
                    select(artifact_cls).where(
                        artifact_cls.expired_at.is_(None),
                        artifact_cls.created_at < cutoff,
                    )
                ).all()
            )
            for artifact in artifacts:
                if artifact.file_path and os.path.isfile(artifact.file_path):
                    live_reference = db.scalar(
                        select(artifact_cls.id).where(
                            artifact_cls.id != artifact.id,
                            artifact_cls.expired_at.is_(None),
                            artifact_cls.file_path == artifact.file_path,
                        ).limit(1)
                    )
                    if live_reference is None:
                        try:
                            os.remove(artifact.file_path)
                        except OSError:
                            continue
                artifact.file_path = None
                artifact.content_json = None
                artifact.expired_at = utc_now_naive()
                expired += 1
        removed_dirs = _cleanup_output_storage(db, cutoff)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return {"expired": expired, "directories_removed": removed_dirs}
