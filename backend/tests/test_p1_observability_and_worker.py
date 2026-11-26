"""P1 Worker 并发/队列隔离、心跳恢复与可观测性回归测试。"""

from __future__ import annotations

from datetime import timedelta
import io
import json
import logging
from pathlib import Path
import time
from types import SimpleNamespace

from sqlalchemy import select


def test_celery_beat_and_dynamic_queue_selection(client, reviewer_client, monkeypatch) -> None:
    import app.deps.auth as auth_deps
    from app.core.celery_app import celery_app
    from app.tasks import executions
    from app.tasks.executions import select_queue_for_case_types

    assert select_queue_for_case_types(["API", "API"]) == "execution_fast"
    assert select_queue_for_case_types(["perf"]) == "execution_perf"
    assert select_queue_for_case_types(["UI"]) is None
    assert select_queue_for_case_types(["API", "UI"]) is None
    assert select_queue_for_case_types([]) is None

    beat = celery_app.conf.beat_schedule
    assert beat["scan-scheduled-plans"]["options"]["queue"] == "execution_fast"
    assert beat["reconcile-interrupted-executions"]["options"]["queue"] == "maintenance"
    assert beat["cleanup-execution-artifacts"]["options"]["queue"] == "maintenance"

    project_id = client.get("/projects").json()[0]["id"]
    api_resp = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"动态路由接口_{time.time_ns()}",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P1",
            "status": "ACTIVE",
            "expected_status": 200,
        },
    )
    assert api_resp.status_code == 201
    api_case_id = api_resp.json()["id"]
    assert client.post(f"/api-cases/{api_case_id}/review/submit").status_code == 200

    approve_resp = reviewer_client.post(
        "/cases/batch-review",
        json={"items": [{"case_type": "API", "case_id": api_case_id}], "review_status": "APPROVED"},
    )
    assert approve_resp.status_code == 200

    plan_resp = client.post("/test-plans", json={"project_id": project_id, "name": f"纯API计划_{time.time_ns()}"})
    assert plan_resp.status_code == 201
    plan_id = plan_resp.json()["id"]
    assert (
        client.post(f"/test-plans/{plan_id}/cases", json={"case_type": "API", "case_id": api_case_id}).status_code
        == 201
    )

    dispatched: list[tuple[str, tuple, str | None]] = []

    def fake_dispatch(
        task_func,
        record_id: int,
        *task_args,
        background_inline: bool = False,
        queue: str | None = None,
        context_user_id: int | None = None,
    ):
        dispatched.append((task_func.name, (record_id, *task_args), queue))
        return "mock-task-id", False

    monkeypatch.setattr(auth_deps, "_dispatch_task_or_run_inline", fake_dispatch)

    run_plan = client.post(f"/test-plans/{plan_id}/run", json={"concurrency": 3})
    assert run_plan.status_code == 200
    assert dispatched[-1][0] == executions.run_test_plan.name
    assert dispatched[-1][2] == "execution_fast"

    # Mixed plan should route back to default browser queue (queue=None -> execution_browser)
    ui_resp = client.post(
        "/ui-cases",
        json={
            "project_id": project_id,
            "name": f"混合UI_{time.time_ns()}",
            "target_url": "http://frontend:3000/login",
            "expect_text": "登录",
            "steps_json": [{"action": "goto", "value": "http://frontend:3000/login"}],
            "priority": "P1",
            "status": "ACTIVE",
        },
    )
    assert ui_resp.status_code == 201
    ui_case_id = ui_resp.json()["id"]
    assert client.post(f"/ui-cases/{ui_case_id}/review/submit").status_code == 200
    assert (
        reviewer_client.post(
            "/cases/batch-review",
            json={"items": [{"case_type": "UI", "case_id": ui_case_id}], "review_status": "APPROVED"},
        ).status_code
        == 200
    )
    assert (
        client.post(f"/test-plans/{plan_id}/cases", json={"case_type": "UI", "case_id": ui_case_id}).status_code == 201
    )
    run_mixed = client.post(f"/test-plans/{plan_id}/run", json={"concurrency": 2})
    assert run_mixed.status_code == 200
    assert dispatched[-1][2] is None

    # Batch API run should also route dynamically to execution_fast
    batch_api = client.post(
        "/executions/api/batch-run",
        json={"project_id": project_id, "case_ids": [api_case_id]},
    )
    assert batch_api.status_code in {200, 201}
    assert dispatched[-1][0] == executions.run_ui_batch.name
    assert dispatched[-1][2] == "execution_fast"

    # Clean up fake-dispatched PENDING rows so later tests stay clean
    from app.core.database import SessionLocal
    from app.models import TestPlanRun, TestRun, UIBatchRun

    with SessionLocal() as db:
        for pr_id in (run_plan.json()["id"], run_mixed.json()["id"]):
            pr = db.get(TestPlanRun, pr_id)
            if pr is not None:
                pr.status = "CANCELLED"
        br = db.get(UIBatchRun, batch_api.json()["id"])
        if br is not None:
            br.status = "CANCELLED"
        for child in db.scalars(
            select(TestRun).where(
                (TestRun.plan_run_id.in_([run_plan.json()["id"], run_mixed.json()["id"]]))
                | (TestRun.batch_run_id == batch_api.json()["id"])
            )
        ).all():
            child.status = "CANCELLED"
        db.commit()


def test_dispatch_helper_uses_apply_async_when_queue_specified(monkeypatch) -> None:
    import app.deps.auth as auth_deps
    from app.core.config import settings

    calls: list[tuple[str, tuple, str | None]] = []

    class FakeTask:
        def delay(self, *args):
            calls.append(("delay", args, None))
            return SimpleNamespace(id="delay-id")

        def apply_async(self, *, args=(), queue=None):
            calls.append(("apply_async", args, queue))
            return SimpleNamespace(id="async-id")

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(settings, "backend_internal_url", "http://backend:8000")

    task = FakeTask()
    tid1, inline1 = auth_deps._dispatch_task_or_run_inline(task, 11, 2)
    tid2, inline2 = auth_deps._dispatch_task_or_run_inline(task, 12, 3, queue="execution_fast")
    assert (tid1, inline1) == ("delay-id", False)
    assert (tid2, inline2) == ("async-id", False)
    assert calls == [
        ("delay", (11, 2), None),
        ("apply_async", (12, 3), "execution_fast"),
    ]


def test_execution_heartbeat_renews_running_and_reconciler_recovers_stale(monkeypatch) -> None:
    from app.core.database import SessionLocal
    from app.models import APICase, Project, TestPlan, TestPlanRun, TestRun, UIBatchRun
    from app.tasks import executions
    from app.timeutil import utc_now_naive

    with SessionLocal() as db:
        project = db.scalar(select(Project).limit(1))
        assert project is not None
        case = db.scalar(select(APICase).where(APICase.project_id == project.id).limit(1))
        if case is None:
            case = APICase(
                project_id=project.id,
                name="心跳用例",
                method="GET",
                path="/api/v1/system/health",
                priority="P1",
                status="ACTIVE",
            )
            db.add(case)
            db.commit()
            db.refresh(case)
        plan = db.scalar(select(TestPlan).where(TestPlan.project_id == project.id).limit(1))
        if plan is None:
            plan = TestPlan(project_id=project.id, name="心跳计划")
            db.add(plan)
            db.commit()
            db.refresh(plan)

        now = utc_now_naive()
        stale_hb = now - timedelta(seconds=200)
        fresh_hb = now - timedelta(seconds=10)

        stale_single = TestRun(
            project_id=project.id,
            case_type="API",
            case_id=case.id,
            case_name="心跳超时单条",
            status="RUNNING",
            task_id="dead-celery-task-1",
            started_at=stale_hb,
            heartbeat_at=stale_hb,
        )
        fresh_single = TestRun(
            project_id=project.id,
            case_type="API",
            case_id=case.id,
            case_name="正常心跳单条",
            status="RUNNING",
            started_at=stale_hb,
            heartbeat_at=fresh_hb,
        )
        active_task_single = TestRun(
            project_id=project.id,
            case_type="UI",
            case_id=1,
            case_name="Worker仍活跃单条",
            status="RUNNING",
            task_id="live-celery-task-1",
            started_at=stale_hb,
            heartbeat_at=stale_hb,
        )
        legacy_recent = TestRun(
            project_id=project.id,
            case_type="API",
            case_id=case.id,
            case_name="历史无心跳未超时",
            status="RUNNING",
            started_at=now - timedelta(seconds=300),
            heartbeat_at=None,
        )
        stale_plan = TestPlanRun(
            plan_id=plan.id,
            project_id=project.id,
            status="RUNNING",
            total_count=2,
            pass_count=0,
            fail_count=0,
            started_at=stale_hb,
            heartbeat_at=stale_hb,
        )
        stale_batch = UIBatchRun(
            project_id=project.id,
            case_type="UI",
            status="RUNNING",
            total_count=1,
            started_at=stale_hb,
            heartbeat_at=stale_hb,
        )
        db.add_all([stale_single, fresh_single, active_task_single, legacy_recent, stale_plan, stale_batch])
        db.commit()
        for obj in (stale_single, fresh_single, active_task_single, legacy_recent, stale_plan, stale_batch):
            db.refresh(obj)

        child_done = TestRun(
            project_id=project.id,
            plan_run_id=stale_plan.id,
            case_type="API",
            case_id=case.id,
            case_name="已完成子用例",
            status="SUCCESS",
        )
        child_stuck = TestRun(
            project_id=project.id,
            plan_run_id=stale_plan.id,
            case_type="API",
            case_id=case.id,
            case_name="卡住子用例",
            status="RUNNING",
            task_id="dead-plan-child-task",
            started_at=stale_hb,
            heartbeat_at=stale_hb,
        )
        batch_child = TestRun(
            project_id=project.id,
            batch_run_id=stale_batch.id,
            case_type="UI",
            case_id=1,
            case_name="批量卡住子用例",
            status="PENDING",
            task_id="dead-batch-child-task",
        )
        db.add_all([child_done, child_stuck, batch_child])
        db.commit()

        # Verify ExecutionHeartbeat updates heartbeat_at synchronously via beat_once and thread
        hb = executions.ExecutionHeartbeat(TestRun, fresh_single.id, interval_seconds=1, touch_on_enter=True)
        with hb:
            assert hb.beat_once() is True

        stale_single_id = stale_single.id
        fresh_single_id = fresh_single.id
        active_task_single_id = active_task_single.id
        legacy_recent_id = legacy_recent.id
        stale_plan_id = stale_plan.id
        stale_batch_id = stale_batch.id
        child_stuck_id = child_stuck.id
        batch_child_id = batch_child.id

    monkeypatch.setattr(executions, "_active_execution_celery_task_ids", lambda: {"live-celery-task-1"})
    counts = executions.reconcile_interrupted_executions()
    assert counts["plans"] == 0
    assert counts["batches"] == 0
    assert counts["runs"] >= 1

    with SessionLocal() as db:
        recovered_single = db.get(TestRun, stale_single_id)
        assert recovered_single.status == "ERROR"
        assert recovered_single.error_type == "SYSTEM"
        assert "心跳超时" in recovered_single.summary

        kept_fresh = db.get(TestRun, fresh_single_id)
        assert kept_fresh.status == "RUNNING"
        assert kept_fresh.heartbeat_at > fresh_hb - timedelta(seconds=1)

        kept_active = db.get(TestRun, active_task_single_id)
        assert kept_active.status == "RUNNING"

        kept_legacy = db.get(TestRun, legacy_recent_id)
        assert kept_legacy.status == "RUNNING"

        waiting_plan = db.get(TestPlanRun, stale_plan_id)
        assert waiting_plan.status == "RUNNING"
        waiting_batch = db.get(UIBatchRun, stale_batch_id)
        assert waiting_batch.status == "RUNNING"

    # Recover the parent runs once the inspector confirms there are no active tasks.
    monkeypatch.setattr(executions, "_active_execution_celery_task_ids", lambda: set())
    counts = executions.reconcile_interrupted_executions()
    assert counts["plans"] >= 1
    assert counts["batches"] >= 1
    assert counts["runs"] >= 2

    with SessionLocal() as db:

        recovered_plan = db.get(TestPlanRun, stale_plan_id)
        assert recovered_plan.status == "FAILED"
        assert recovered_plan.total_count == 2
        assert recovered_plan.pass_count == 1
        assert recovered_plan.fail_count == 1
        assert "心跳超时" in recovered_plan.summary

        assert db.get(TestRun, child_stuck_id).status == "ERROR"
        assert db.get(UIBatchRun, stale_batch_id).status == "FAILED"
        assert db.get(TestRun, batch_child_id).status == "ERROR"

        # Clean up test-created RUNNING rows so subsequent tests don't see dangling state
        for run_id in (fresh_single_id, active_task_single_id, legacy_recent_id):
            row = db.get(TestRun, run_id)
            row.status = "CANCELLED"
        db.commit()


def test_structured_json_logging_and_celery_trace_propagation(tmp_path: Path) -> None:
    from celery.signals import before_task_publish, task_postrun, task_prerun

    from app.core.observability import (
        bind_context,
        configure_observability_logging,
        get_logger,
        request_id_var,
        reset_context,
        start_worker_heartbeat_loop,
        stop_worker_heartbeat_loop,
        user_id_var,
    )

    stream = io.StringIO()
    fmt = configure_observability_logging(force_format="json", stream=stream)
    assert fmt == "json"
    try:
        tokens = bind_context(request_id="req-trace-123", user_id=42, run_id=99)
        try:
            obs_logger = get_logger("tests.observability")
            obs_logger.info("sample_structured_event", extra_flag=True)

            # Verify Celery trace propagation across publish -> prerun -> postrun
            headers: dict = {}
            before_task_publish.send(sender="app.tasks.run_api_case", headers=headers, body={})
            assert headers["request_id"] == "req-trace-123"
            assert headers["user_id"] == 42
        finally:
            reset_context(tokens)

        assert request_id_var.get() is None
        assert user_id_var.get() is None

        class _HashableFakeTask:
            def __init__(self, name: str, headers: dict):
                self.name = name
                self.request = SimpleNamespace(headers=headers, request_id="req-trace-123", user_id=42)

        fake_task = _HashableFakeTask("app.tasks.run_api_case", headers)
        task_prerun.send(sender=fake_task, task_id="celery-task-abc", task=fake_task, kwargs={})
        try:
            assert request_id_var.get() == "req-trace-123"
            assert user_id_var.get() == 42
            logging.getLogger("tests.stdlib").warning("stdlib_inside_task")
        finally:
            task_postrun.send(sender=fake_task, task_id="celery-task-abc", task=fake_task, state="SUCCESS")

        assert request_id_var.get() is None
        assert user_id_var.get() is None

        lines = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
        structured = next(item for item in lines if item.get("event") == "sample_structured_event")
        assert structured["request_id"] == "req-trace-123"
        assert structured["user_id"] == 42
        assert structured["run_id"] == 99
        assert structured["extra_flag"] is True
        assert structured["level"] == "info"

        task_log = next(item for item in lines if item.get("event") == "stdlib_inside_task")
        assert task_log["request_id"] == "req-trace-123"
        assert task_log["user_id"] == 42
        assert task_log["task_id"] == "celery-task-abc"
        assert task_log["task_name"] == "app.tasks.run_api_case"
    finally:
        configure_observability_logging(force_format="console")

    hb_file = tmp_path / "worker-heartbeat"
    start_worker_heartbeat_loop(path=str(hb_file), interval_seconds=2)
    try:
        assert hb_file.exists()
        assert int(hb_file.read_text(encoding="utf-8").strip()) > 0
    finally:
        stop_worker_heartbeat_loop()


def test_metrics_endpoint_and_client_error_reporting(client) -> None:
    from fastapi.testclient import TestClient

    from app.core.observability import (
        record_ai_stage_duration,
        record_ai_tokens,
        record_case_execution,
        reset_metrics_for_tests,
    )

    reset_metrics_for_tests()

    with TestClient(client.app, base_url="http://testserver") as root_client:
        # /metrics must remain excluded from OpenAPI schema
        openapi = root_client.get("/openapi.json").json()
        assert "/metrics" not in openapi.get("paths", {})

        # Record sample execution & AI metrics
        record_case_execution(case_type="API", status="SUCCESS", duration_seconds=0.25)
        record_ai_stage_duration(mode="v2", stage="requirement", status="success", duration_seconds=1.5)
        record_ai_tokens(provider="openai", model="gpt-5.5", tokens=1234)

        # Trigger an HTTP endpoint so HTTP metrics populate (client uses /api/v1 base_url)
        health_resp = client.get("/projects")
        assert health_resp.status_code == 200
        assert health_resp.headers.get("X-Request-ID")
        assert health_resp.headers.get("X-Response-Time-Ms") is not None

        # Report valid + unknown-source frontend runtime errors
        err_resp = client.post(
            "/system/client-errors",
            json={
                "source": "vue",
                "message": "TypeError: Cannot read properties of undefined",
                "component": "ExecutionPage",
                "route": "/executions",
                "stack": "Error at line 1",
            },
        )
        assert err_resp.status_code == 200
        assert err_resp.json()["recorded"] is True

        # Unknown source must be normalized to "other" to prevent Prometheus label explosion
        other_err = client.post(
            "/system/client-errors",
            json={"source": "attacker-arbitrary-label", "message": "boom"},
        )
        assert other_err.status_code == 200

        bad_err = client.post("/system/client-errors", json={"source": "vue", "message": ""})
        assert bad_err.status_code == 422

        # Also trigger real inline API execution to verify heartbeat_at & Prometheus execution metrics
        exec_case = client.post(
            "/api-cases",
            json={
                "project_id": health_resp.json()[0]["id"],
                "name": f"指标采集接口_{time.time_ns()}",
                "method": "GET",
                "path": "/api/v1/system/health/live",
                "priority": "P1",
                "status": "ACTIVE",
                "expected_status": 200,
            },
        )
        assert exec_case.status_code == 201
        run_resp = client.post(f"/executions/api/{exec_case.json()['id']}/run", json={})
        assert run_resp.status_code == 200
        run_payload = run_resp.json()
        assert run_payload["heartbeat_at"] is not None

        metrics_resp = root_client.get("/metrics")
        assert metrics_resp.status_code == 200
        assert "text/plain" in metrics_resp.headers.get("content-type", "")
        body = metrics_resp.text

        assert "omnitest_http_requests_total" in body
        assert "omnitest_http_request_duration_seconds" in body
        assert 'omnitest_case_executions_total{case_type="API",error_type="NONE",status="SUCCESS"}' in body
        assert 'omnitest_case_execution_duration_seconds_count{case_type="API",status="SUCCESS"}' in body
        assert 'omnitest_celery_queue_depth{queue="execution_fast"}' in body
        assert 'omnitest_ai_generation_stage_duration_seconds_count{mode="v2",stage="requirement",status="success"} 1.0' in body
        assert 'omnitest_ai_tokens_total{model="gpt-5.5",provider="openai"} 1234.0' in body
        assert 'omnitest_frontend_errors_total{source="vue"} 1.0' in body
        assert 'omnitest_frontend_errors_total{source="other"} 1.0' in body
        assert "attacker-arbitrary-label" not in body


def test_celery_logging_proxy_and_prefork_child_init_preserve_json_logs(monkeypatch) -> None:
    import sys

    from celery.signals import after_setup_logger, after_setup_task_logger, worker_process_init

    import app.core.celery_app  # noqa: F401
    from app.core.config import settings
    from app.core.observability import bind_context, configure_observability_logging, get_logger, reset_context

    class LoggingProxy:
        """Minimal replica of Celery's sys.stderr proxy to verify fallback to sys.__stderr__."""

        def write(self, _data: str) -> int:
            raise AssertionError("StreamHandler must bind sys.__stderr__, not Celery LoggingProxy")

        def flush(self) -> None:
            pass

    fake_real_stderr = io.StringIO()
    task_logger = logging.getLogger("celery.task")
    task_logger.propagate = False
    task_logger.handlers = [logging.StreamHandler(io.StringIO())]

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(settings, "app_env", "docker")
    monkeypatch.setattr(settings, "log_format", "auto")
    monkeypatch.setattr(sys, "stderr", LoggingProxy())
    monkeypatch.setattr(sys, "__stderr__", fake_real_stderr)

    try:
        after_setup_task_logger.send(sender=None, logger=task_logger)
        after_setup_logger.send(sender=None, logger=logging.getLogger())
        worker_process_init.send(sender=None)

        assert task_logger.propagate is True
        assert task_logger.handlers == []

        tokens = bind_context(request_id="req-child-77", user_id=12, task_id="tid-77", task_name="app.tasks.run_ui_case")
        try:
            get_logger("tests.prefork_child").info("child_log_line")
            logging.getLogger("celery.task").info("celery_task_log_line")
        finally:
            reset_context(tokens)

        records = [json.loads(line) for line in fake_real_stderr.getvalue().splitlines() if line.strip()]
        child_rec = next(item for item in records if item.get("event") == "child_log_line")
        task_rec = next(
            (item for item in records if item.get("event") == "celery_task_log_line"),
            {"logger_disabled": task_logger.disabled, "logger_level": task_logger.getEffectiveLevel()},
        )
        assert child_rec["request_id"] == "req-child-77"
        assert child_rec["user_id"] == 12
        assert task_rec["request_id"] == "req-child-77"
        assert task_rec["task_id"] == "tid-77"
    finally:
        monkeypatch.undo()
        configure_observability_logging(force_format="console")


def test_parallel_plan_api_execution_propagates_context_and_reconciler_records_metrics(
    client, reviewer_client, monkeypatch
) -> None:
    from app.core.database import SessionLocal
    from app.core.observability import (
        OMNITEST_REGISTRY,
        bind_context,
        _read_counter_samples,
        request_id_var,
        reset_context,
        reset_metrics_for_tests,
        user_id_var,
    )
    from app.models import TestPlanRun, TestRun
    from app.tasks import executions
    from app.timeutil import utc_now_naive

    project_id = client.get("/projects").json()[0]["id"]
    case_ids = []
    for idx in range(2):
        resp = client.post(
            "/api-cases",
            json={
                "project_id": project_id,
                "name": f"并发上下文接口_{idx}_{time.time_ns()}",
                "method": "GET",
                "path": "/api/v1/system/health/live",
                "priority": "P1",
                "status": "ACTIVE",
                "expected_status": 200,
            },
        )
        assert resp.status_code == 201
        cid = resp.json()["id"]
        assert client.post(f"/api-cases/{cid}/review/submit").status_code == 200
        assert (
            reviewer_client.post(
                "/cases/batch-review",
                json={"items": [{"case_type": "API", "case_id": cid}], "review_status": "APPROVED"},
            ).status_code
            == 200
        )
        case_ids.append(cid)

    plan_resp = client.post("/test-plans", json={"project_id": project_id, "name": f"并发心跳计划_{time.time_ns()}"})
    assert plan_resp.status_code == 201
    plan_id = plan_resp.json()["id"]
    for cid in case_ids:
        assert client.post(f"/test-plans/{plan_id}/cases", json={"case_type": "API", "case_id": cid}).status_code == 201

    observed_contexts: list[tuple[str | None, int | str | None, int | None]] = []
    original_exec = executions._execute_api_case

    def spy_execute(db, run, case, project, deadline=None):
        observed_contexts.append((request_id_var.get(), user_id_var.get(), executions.run_id_var.get()))
        return original_exec(db, run, case, project, deadline=deadline)

    monkeypatch.setattr(executions, "_execute_api_case", spy_execute)

    me_id = client.get("/auth/me").json()["id"]
    plan_run_resp = client.post(
        f"/test-plans/{plan_id}/run",
        json={"concurrency": 3},
        headers={"X-Request-ID": "req-parallel-plan"},
    )
    assert plan_run_resp.status_code == 200

    assert len(observed_contexts) == 2
    assert all(req == "req-parallel-plan" and uid == me_id and rid is not None for req, uid, rid in observed_contexts), observed_contexts

    # Also verify reconciler records ERROR/SYSTEM metric for stale RUNNING test runs
    reset_metrics_for_tests()
    with SessionLocal() as db:
        stale_hb = utc_now_naive() - timedelta(seconds=200)
        crashed = TestRun(
            project_id=project_id,
            case_type="UI",
            case_id=1,
            case_name="崩溃用例",
            status="RUNNING",
            task_id="dead-crashed-task",
            started_at=stale_hb,
            heartbeat_at=stale_hb,
        )
        db.add(crashed)
        db.commit()

    monkeypatch.setattr(executions, "_active_execution_celery_task_ids", lambda: set())
    counts = executions.reconcile_interrupted_executions()
    assert counts["runs"] >= 1
    samples = _read_counter_samples("omnitest_case_executions_total")
    assert samples.get(("UI", "ERROR", "SYSTEM"), 0.0) >= 1.0

    # Clean up test plan runs created for concurrency spy
    with SessionLocal() as db:
        pr = db.get(TestPlanRun, plan_run_resp.json()["id"])
        assert pr is not None
        assert pr.heartbeat_at is not None
