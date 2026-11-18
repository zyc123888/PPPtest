"""执行链路幂等与产物清理（S1/S2）回归测试。"""

from datetime import timedelta

from app.core.database import SessionLocal
from app.models import TestRun
from app.services import finalize_run
from app.timeutil import utc_now_naive

TestRun.__test__ = False  # 避免 pytest 将 ORM 模型误收集为测试类


def test_finalize_run_does_not_overwrite_cancelled(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    with SessionLocal() as db:
        run = TestRun(
            project_id=project_id,
            case_type="API",
            case_id=1,
            case_name="取消守卫用例",
            status="CANCELLED",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

        # 模拟执行中已被取消，worker 晚到结果不应覆盖
        finalize_run(db, run, status="SUCCESS", summary="晚到的执行结果")

        db.refresh(run)
        assert run.status == "CANCELLED"
        assert run.finished_at is None

    with SessionLocal() as db:
        record = db.get(TestRun, run_id)
        if record is not None:
            db.delete(record)
            db.commit()


def test_cleanup_execution_artifacts_removes_only_old_terminal_runs(client, monkeypatch, tmp_path) -> None:
    from app.tasks import executions

    project_id = client.get("/projects").json()[0]["id"]

    with SessionLocal() as db:
        old = TestRun(project_id=project_id, case_type="API", case_id=1, case_name="旧终态", status="SUCCESS")
        db.add(old)
        db.commit()
        db.refresh(old)
        old.finished_at = utc_now_naive() - timedelta(days=60)
        db.commit()

        active = TestRun(project_id=project_id, case_type="API", case_id=2, case_name="活动中", status="RUNNING")
        db.add(active)
        db.commit()

        old_id, active_id = old.id, active.id

    monkeypatch.setattr(executions.settings, "report_output_dir", str(tmp_path))
    (tmp_path / f"run_{old_id}").mkdir()
    (tmp_path / f"run_{old_id}" / "artifact.txt").write_text("x")
    (tmp_path / f"run_{active_id}").mkdir()
    (tmp_path / f"run_{active_id}" / "artifact.txt").write_text("x")

    result = executions.cleanup_execution_artifacts()

    assert result["removed"] >= 1
    assert not (tmp_path / f"run_{old_id}").exists()
    assert (tmp_path / f"run_{active_id}").exists()

    with SessionLocal() as db:
        for rid in (old_id, active_id):
            record = db.get(TestRun, rid)
            if record is not None:
                db.delete(record)
        db.commit()
