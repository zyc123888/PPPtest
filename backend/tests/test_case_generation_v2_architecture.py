from __future__ import annotations

from pathlib import Path


def test_v2_public_task_module_is_a_thin_compatibility_entrypoint() -> None:
    import app.tasks.case_generation_v2 as public_module

    module_path = Path(public_module.__file__)
    assert len(module_path.read_text(encoding="utf-8").splitlines()) < 80
    assert public_module.run_case_generation_v2_job.name == "app.tasks.case_generation_v2.run_case_generation_v2_job"
    assert public_module.rerun_case_generation_v2_source_shard.name == (
        "app.tasks.case_generation_v2.rerun_case_generation_v2_source_shard"
    )


def test_v2_stage_implementations_do_not_fall_back_into_the_engine() -> None:
    import app.tasks.case_generation_v2 as public_module

    assert public_module._normalize_trusted_scope_index.__module__.endswith("stages.scope_impl")
    assert public_module._normalize_trusted_requirement_handoff.__module__.endswith("stages.requirement_impl")
    assert public_module._validate_trusted_testcase_handoff.__module__.endswith("stages.testcase_impl")
    assert public_module._build_final_delivery_gate.__module__.endswith("stages.delivery_impl")

    engine_path = Path(public_module._engine.__file__)
    assert len(engine_path.read_text(encoding="utf-8").splitlines()) < 6000


def test_pipeline_mode_normalizer_keeps_historical_aliases() -> None:
    from app.tasks.case_generation_v2_pipeline.normalizers import normalize_pipeline_mode

    assert normalize_pipeline_mode("clone") == "lite"
    assert normalize_pipeline_mode("trusted_v2") == "trusted"
    assert normalize_pipeline_mode("lite") == "lite"
    assert normalize_pipeline_mode("trusted") == "trusted"


def test_relative_rules_directories_resolve_from_backend_root(monkeypatch) -> None:
    from app.tasks.case_generation_v2_pipeline import engine

    backend_root = Path(engine.__file__).resolve().parents[3]
    monkeypatch.setattr(engine.settings, "case_generation_unified_rules_dir", "claw_5skill_unified")

    assert engine._BACKEND_ROOT == backend_root
    assert engine._resolve_unified_rules_dir() == backend_root / "claw_5skill_unified"

    monkeypatch.setattr(engine.settings, "case_generation_unified_rules_dir", "")
    monkeypatch.setattr(engine.settings, "case_generation_rules_dir", "")
    assert engine._resolve_unified_rules_dir() == backend_root / "claw_5skill_unified"


def test_typed_stage_boundaries_return_counts() -> None:
    from app.tasks.case_generation_v2_pipeline.stages import (
        RequirementStageInput,
        ScopeStageInput,
        TestcaseStageInput,
        run_requirement_stage,
        run_scope_stage,
        run_testcase_stage,
    )

    scope_result = run_scope_stage(
        ScopeStageInput("# 登录", [], "key", "model", "https://example.test"),
        build_scope_index=lambda *args, **kwargs: {
            "direct_testcase_sources": [{"source_id": "SRC-001"}]
        },
    )
    assert scope_result.source_count == 1

    requirement_result = run_requirement_stage(
        RequirementStageInput(scope_result.scope_index, "# 登录", [], "key", "model", "https://example.test"),
        build_requirement_handoff=lambda *args, **kwargs: {
            "function_points": [{"fp_id": "FP-001", "source_id": "SRC-001"}]
        },
    )
    assert requirement_result.function_point_count == 1

    testcase_result = run_testcase_stage(
        TestcaseStageInput(
            scope_result.scope_index,
            requirement_result.requirement_handoff,
            "key",
            "model",
            "https://example.test",
        ),
        build_testcase_handoff=lambda *args, **kwargs: {
            "testcases": [{"case_id": "TC-001"}],
            "failed_sources": [],
        },
    )
    assert testcase_result.testcase_count == 1
    assert testcase_result.failed_source_count == 0


def test_orchestration_dispatches_normalized_modes() -> None:
    from app.tasks.case_generation_v2_pipeline.orchestration import PipelineDispatchInput, dispatch_pipeline

    calls: list[tuple[str, int]] = []
    runners = {
        "run_lite": lambda job_id: calls.append(("lite", job_id)),
        "run_trusted": lambda job_id: calls.append(("trusted", job_id)),
        "resume_trusted_from_testcase_gate": lambda job_id: calls.append(("resume", job_id)),
    }

    dispatch_pipeline(PipelineDispatchInput(1, "clone"), **runners)
    dispatch_pipeline(PipelineDispatchInput(2, "trusted_v2"), **runners)
    dispatch_pipeline(PipelineDispatchInput(3, "trusted", "testcase_gate"), **runners)

    assert calls == [("lite", 1), ("trusted", 2), ("resume", 3)]


def test_deterministic_xmindmark_validator_and_counters() -> None:
    from app.tasks.case_generation_v2_pipeline.validators import (
        count_xmindmark_function_point_nodes,
        count_xmindmark_source_nodes,
        count_xmindmark_testcase_nodes,
        validate_xmindmark,
    )

    text = "\n".join(
        [
            "登录测试用例",
            "- 模块：登录",
            "  - SRC-001：登录",
            "    - FP-001：账号登录",
            "      - TC-001-登录成功",
        ]
    )
    validate_xmindmark(text)
    assert count_xmindmark_source_nodes(text) == 1
    assert count_xmindmark_function_point_nodes(text) == 1
    assert count_xmindmark_testcase_nodes(text) == 1
