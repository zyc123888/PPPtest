from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from app.tasks import executions


def test_midscene_runner_path_prefers_explicit_configuration(monkeypatch, tmp_path) -> None:
    runner = tmp_path / "runner.js"
    runner.write_text("", encoding="utf-8")
    monkeypatch.setenv("MIDSCENE_RUNNER_PATH", str(runner))

    assert executions._midscene_runner_path() == str(runner)


def test_midscene_child_env_uses_allowlist(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql://secret")
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "top-secret")
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://secret")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(executions, "_midscene_node_path", lambda _runner: None)

    child_env = executions._build_midscene_child_env(
        runner_path=str(tmp_path / "runner.js"),
        model_base_url="https://model.example.com/v1",
        model_api_key="model-key",
        model_name="vision-model",
        run_dir=str(tmp_path),
    )

    assert child_env["PATH"] == "/usr/bin:/bin"
    assert child_env["HOME"] == os.path.expanduser("~")
    assert child_env["MIDSCENE_MODEL_API_KEY"] == "model-key"
    assert "DATABASE_URL" not in child_env
    assert "APP_ENCRYPTION_KEY" not in child_env
    assert "CELERY_BROKER_URL" not in child_env


@pytest.mark.parametrize(
    ("engine", "expected"),
    [("native", "native"), ("midscene", "midscene"), (None, "native")],
)
def test_ui_case_engine_dispatch(monkeypatch, engine, expected) -> None:
    calls = []
    result = {"status": "SUCCESS", "summary": expected}

    def native(*args, **kwargs):
        calls.append("native")
        return result

    def midscene(*args, **kwargs):
        calls.append("midscene")
        return result

    monkeypatch.setattr(executions, "_execute_ui_case", native)
    monkeypatch.setattr(executions, "_execute_ui_case_midscene", midscene)

    actual = executions._execute_ui_case_by_engine(
        object(), object(), SimpleNamespace(engine=engine), object(), deadline=123.0
    )

    assert actual is result
    assert calls == [expected]


def test_midscene_job_includes_assertions_and_prohibited_actions(monkeypatch, tmp_path) -> None:
    runner = tmp_path / "runner.js"
    runner.write_text("", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    captured = {}

    def fake_process(args, *, cwd, env, timeout, max_bytes=executions._MIDSCENE_LOG_MAX_BYTES):
        captured["job"] = json.loads((tmp_path / "run" / "ui-midscene-job.json").read_text(encoding="utf-8"))
        (run_dir / "midscene-result.json").write_text(
            json.dumps({"status": "SUCCESS", "summary": "ok", "steps": []}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(executions, "_ensure_run_dir", lambda _run_id: str(run_dir))
    monkeypatch.setattr(executions, "_midscene_runner_path", lambda: str(runner))
    monkeypatch.setattr(executions, "_resolve_node_binary", lambda: sys.executable)
    monkeypatch.setattr(executions, "_run_process_with_limited_output", fake_process)
    monkeypatch.setattr(executions, "_resolve_environment", lambda *args: None)
    monkeypatch.setattr(executions, "build_variable_context", lambda *args: {})

    class FakeDb:
        def scalar(self, _statement):
            return SimpleNamespace(
                api_key="model-key",
                model="vision-model",
                base_url="https://model.example.com/v1",
            )

    case = SimpleNamespace(
        target_url="https://example.com",
        expect_text="ready",
        steps_json=[],
        execution_mode="ai",
        allowed_origins_json=None,
        assertions_json=[{"type": "text_contains", "value": "ready"}],
        prohibited_actions_json=["delete account"],
    )
    project = SimpleNamespace(base_url="https://example.com", workspace_id=1)
    run = SimpleNamespace(id=7, environment_id=None)

    result = executions._execute_ui_case_midscene(FakeDb(), run, case, project)

    assert result["status"] == "SUCCESS"
    assert captured["job"]["assertions_json"] == case.assertions_json
    assert captured["job"]["prohibited_actions_json"] == case.prohibited_actions_json


def test_limited_process_output_is_drained_and_truncated(tmp_path) -> None:
    script = "import sys; print('x' * 5000); print('y' * 5000, file=sys.stderr)"
    completed = executions._run_process_with_limited_output(
        [sys.executable, "-c", script],
        cwd=str(tmp_path),
        env={"PATH": os.environ.get("PATH", os.defpath)},
        timeout=5,
        max_bytes=256,
    )

    assert completed.returncode == 0
    assert len(completed.stdout) < 400
    assert len(completed.stderr) < 400
    assert "output truncated" in completed.stdout
    assert "output truncated" in completed.stderr


def test_limited_process_timeout_preserves_bounded_output_and_stops_quickly(tmp_path) -> None:
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        executions._run_process_with_limited_output(
            [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(30)"],
            cwd=str(tmp_path),
            env={"PATH": os.environ.get("PATH", os.defpath)},
            timeout=1,
            max_bytes=256,
        )

    assert time.monotonic() - started < 5
    assert "started" in str(caught.value.output)
