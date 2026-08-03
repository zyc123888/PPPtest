import asyncio
import hashlib
import json
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select, text


def test_system_health(client) -> None:
    response = client.get("/system/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["app_status"] in {"healthy", "degraded"}
    assert payload["database"] == "healthy"
    assert payload["redis"] in {"healthy", "unhealthy"}


def test_system_info_and_bootstrap(client) -> None:
    info_response = client.get("/system/info")
    assert info_response.status_code == 200
    info_payload = info_response.json()
    assert info_payload["app_name"] == "自动化测试平台"
    assert info_payload["database_backend"] in {"sqlite", "mysql+pymysql", "mysql"}
    assert info_payload["backend_public_url"].startswith("http")

    bootstrap_response = client.post("/system/bootstrap", json={"seed_demo_data": True})
    assert bootstrap_response.status_code == 200
    bootstrap_payload = bootstrap_response.json()
    assert bootstrap_payload["success"] is True
    assert isinstance(bootstrap_payload["created_tables"], list)
    assert isinstance(bootstrap_payload["schema_changes"], list)
    assert isinstance(bootstrap_payload["seeded_resources"], list)


def test_protected_system_endpoints_require_login(client) -> None:
    with TestClient(client.app, base_url="http://testserver/api/v1") as anonymous_client:
        assert anonymous_client.get("/system/info").status_code == 401
        assert anonymous_client.post("/system/bootstrap", json={"seed_demo_data": False}).status_code == 401


def test_api_case_body_modes_build_request_kwargs() -> None:
    from app.tasks.executions import _build_request_body_kwargs

    raw_json = _build_request_body_kwargs({"mode": "raw", "raw_type": "json", "raw": '{"name":"ppp"}'})
    assert raw_json == {"json": {"name": "ppp"}}

    form = _build_request_body_kwargs(
        {
            "mode": "form-data",
            "form_data": [
                {"enabled": True, "key": "token", "value": "abc", "type": "text"},
                {"enabled": False, "key": "ignored", "value": "nope", "type": "text"},
            ],
        }
    )
    assert form == {"files": {"token": (None, "abc")}}

    urlencoded = _build_request_body_kwargs(
        {"mode": "x-www-form-urlencoded", "urlencoded": [{"enabled": True, "key": "page", "value": "1"}]}
    )
    assert urlencoded == {"data": {"page": "1"}}

    graphql = _build_request_body_kwargs(
        {"mode": "graphql", "graphql": {"query": "query Viewer { viewer { id } }", "variables": {"id": 1}}}
    )
    assert graphql == {"json": {"query": "query Viewer { viewer { id } }", "variables": {"id": 1}}}

    binary = _build_request_body_kwargs({"mode": "binary", "binary": {"content": "aGVsbG8=", "encoding": "base64"}})
    assert binary == {"content": b"hello"}


def test_case_generation_payload_masks_openai_key() -> None:
    from app.tasks.case_generation import sanitize_case_generation_payload

    payload = sanitize_case_generation_payload({"openai_api_key": "sk-test-secret", "name": "demo"})
    assert payload["openai_api_key"] == "***已提供***"
    assert payload["name"] == "demo"

    cleaned = sanitize_case_generation_payload({"openai_api_key": "sk-test-secret"}, cleanup_secret=True)
    assert cleaned["openai_api_key"] is None


def test_case_generation_v2_pipeline_mode_schema_defaults_and_rejects_invalid() -> None:
    from app import schemas

    payload = schemas.CaseGenerationV2JobCreate(
        project_id=1,
        name="V2 默认模式",
        markdown_text="# 登录\n- 支持用户名密码登录",
    )
    assert payload.pipeline_mode == "lite"
    assert payload.generation_density == "balanced"

    for mode in ("clone", "trusted_v2", "lite", "trusted"):
        mode_payload = schemas.CaseGenerationV2JobCreate(
            project_id=1,
            name=f"V2 {mode} 模式",
            pipeline_mode=mode,
            markdown_text="# 登录\n- 支持用户名密码登录",
        )
        assert mode_payload.pipeline_mode == mode

    try:
        schemas.CaseGenerationV2JobCreate(
            project_id=1,
            name="V2 非法模式",
            pipeline_mode="bad-mode",
            markdown_text="# 登录\n- 支持用户名密码登录",
        )
    except Exception as exc:
        assert "pipeline_mode" in str(exc)
    else:
        raise AssertionError("invalid pipeline_mode should fail validation")

    for density in ("concise", "balanced", "exhaustive"):
        density_payload = schemas.CaseGenerationV2JobCreate(
            project_id=1,
            name=f"V2 {density} 密度",
            generation_density=density,
            markdown_text="# 登录\n- 支持用户名密码登录",
        )
        assert density_payload.generation_density == density

    try:
        schemas.CaseGenerationV2JobCreate(
            project_id=1,
            name="V2 非法密度",
            generation_density="unlimited",
            markdown_text="# 登录\n- 支持用户名密码登录",
        )
    except Exception as exc:
        assert "generation_density" in str(exc)
    else:
        raise AssertionError("invalid generation_density should fail validation")


def test_case_generation_v2_pipeline_mode_normalization_and_dispatch(monkeypatch) -> None:
    import app.tasks.case_generation_v2 as v2
    from contextlib import nullcontext

    assert v2._normalize_pipeline_mode("clone") == "lite"
    assert v2._normalize_pipeline_mode("trusted_v2") == "trusted"
    assert v2._normalize_pipeline_mode("lite") == "lite"
    assert v2._normalize_pipeline_mode("trusted") == "trusted"

    calls: list[str] = []

    class FakeDb:
        def __init__(self, mode: str, resume_from_stage: str = "", status: str = "PENDING"):
            self.job = SimpleNamespace(input_payload_json={
                "pipeline_mode": mode,
                "trusted_resume_from_stage": resume_from_stage,
            }, id=11, active_attempt_id=91, status=status)

        def get(self, model, job_id):
            return self.job

        def close(self):
            return None

        def commit(self):
            return None

    attempt = SimpleNamespace(id=91, run_id="run-test", task_id=None)

    monkeypatch.setattr(v2, "_run_clone_pipeline", lambda job_id: calls.append(f"lite:{job_id}"))
    monkeypatch.setattr(v2, "_run_trusted_v2_pipeline", lambda job_id: calls.append(f"trusted:{job_id}"))
    monkeypatch.setattr(v2, "_resume_trusted_v2_from_testcase_gate", lambda job_id: calls.append(f"resume:{job_id}"))
    monkeypatch.setattr(v2, "ensure_attempt", lambda *args, **kwargs: attempt)
    monkeypatch.setattr(v2, "mark_attempt_running", lambda *args, **kwargs: None)
    monkeypatch.setattr(v2, "bind_attempt", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(v2, "AttemptHeartbeat", lambda *args, **kwargs: nullcontext())

    monkeypatch.setattr(v2, "SessionLocal", lambda: FakeDb("lite"))
    v2.run_case_generation_v2_job.run(11)
    monkeypatch.setattr(v2, "SessionLocal", lambda: FakeDb("trusted"))
    v2.run_case_generation_v2_job.run(12)
    monkeypatch.setattr(v2, "SessionLocal", lambda: FakeDb("clone"))
    v2.run_case_generation_v2_job.run(13)
    monkeypatch.setattr(v2, "SessionLocal", lambda: FakeDb("trusted_v2"))
    v2.run_case_generation_v2_job.run(14)
    monkeypatch.setattr(v2, "SessionLocal", lambda: FakeDb("trusted", "testcase_gate"))
    v2.run_case_generation_v2_job.run(15)
    monkeypatch.setattr(v2, "SessionLocal", lambda: FakeDb("trusted", status="CANCELLED"))
    v2.run_case_generation_v2_job.run(16)

    assert calls == ["lite:11", "trusted:12", "lite:13", "trusted:14", "resume:15"]


def _trusted_scope_fixture(source_ids=("SRC-001",), *, method="equivalence", must_cover="登录"):
    source_blocks = []
    shards = []
    for index, source_id in enumerate(source_ids, start=1):
        title_path = f"2.{index} {must_cover}"
        source_blocks.append(
            {
                "block_id": source_id,
                "title": must_cover,
                "title_path": title_path,
                "module": "账户",
                "scene": must_cover,
                "source_order": f"2.{index}",
                "source_location": title_path,
                "source_type": "prd_text",
                "xmind_source_node": f"{source_id}｜{title_path}",
            }
        )
        shards.append(
            {
                "shard_id": f"SHARD-{source_id}",
                "direct_testcase_source": source_id,
                "source_order": f"2.{index}",
                "title_path": title_path,
                "module": "账户",
                "scene": must_cover,
                "xmind_source_node": f"{source_id}｜{title_path}",
                "assigned_primary_sources": [source_id],
                "assigned_dependency_sources": [],
                "rule_clusters": [],
                "test_design_profile": {
                    "applicable_methods": [method],
                    "risk_signals": [],
                    "must_cover": [must_cover],
                    "merge_allowed": [],
                    "not_applicable": [],
                    "coverage_budget": {"guidance": "按风险和 must_cover 覆盖，不设固定条数"},
                },
            }
        )
    return {
        "source_blocks": source_blocks,
        "scope_classification": [],
        "shards": shards,
        "dependency_bindings": [],
        "coverage_check": {},
        "expected_source_list": list(source_ids),
    }


def _trusted_method_consumption(source_id="SRC-001", case_ids=None, *, method="equivalence"):
    return [
        {
            "source_id": source_id,
            "method": method,
            "consumption_result": "covered_by_case",
            "case_refs": case_ids or ["TC-001"],
            "reason": "",
        }
    ]


def test_case_generation_v2_requirement_handoff_batches_large_scope(monkeypatch) -> None:
    import json
    import threading
    import app.tasks.case_generation_v2 as v2

    calls = []
    state = {"running": 0, "max_running": 0}
    lock = threading.Lock()

    def fake_call_openai_json(**kwargs):
        payload = json.loads(kwargs["user_content"])
        sources = payload["scope_index"]["direct_testcase_sources"]
        with lock:
            state["running"] += 1
            state["max_running"] = max(state["max_running"], state["running"])
        time.sleep(0.02)
        with lock:
            state["running"] -= 1
        calls.append([item["source_id"] for item in sources])
        function_points = []
        consumptions = []
        for index, source in enumerate(sources, start=1):
            fp_id = f"FP-{index:03d}"
            source_id = source["source_id"]
            function_points.append(
                {
                    "fp_id": fp_id,
                    "source_id": source_id,
                    "shard_id": source["shard_id"],
                    "source_order": source["source_order"],
                    "title_path": source["title_path"],
                    "source_title": source["title"],
                    "title": source["title"],
                    "description": source["scene"],
                    "rules": ["覆盖核心规则"],
                    "test_hints": ["按可观察结果验证"],
                    "priority_hint": "P1",
                    "coverage_intent": "positive",
                    "merge_allowed": False,
                    "source_refs": [source["title_path"]],
                }
            )
            consumptions.append(
                {
                    "source_id": source_id,
                    "result": "converted_to_function_points",
                    "fp_ids": [fp_id],
                    "note": "",
                }
            )
        return {
            "scope_index_consumption": consumptions,
            "function_points": function_points,
            "pending_confirmations": [],
        }

    monkeypatch.setattr(v2, "_REQUIREMENT_BATCH_CONCURRENCY", 2)
    monkeypatch.setattr(v2, "_call_openai_json", fake_call_openai_json)
    # Requirement batching now starts only above ten sources; smaller inputs use
    # one complete model pass to avoid merge overhead and context loss.
    scope_index = _trusted_scope_fixture(tuple(f"SRC-{index:03d}" for index in range(1, 13)))
    progress_messages: list[str] = []

    handoff = v2._build_trusted_requirement_handoff(
        scope_index,
        "# 登录\n支持用户名密码登录\n# 权限\n不同角色展示不同菜单",
        [],
        api_key="sk-test",
        model="test-model",
        base_url="http://example.invalid/v1",
        progress_callback=progress_messages.append,
    )

    assert sorted(calls) == sorted([
        ["SRC-001", "SRC-002", "SRC-003", "SRC-004"],
        ["SRC-005", "SRC-006", "SRC-007", "SRC-008"],
        ["SRC-009", "SRC-010", "SRC-011", "SRC-012"],
    ])
    assert state["max_running"] <= 2
    assert state["max_running"] > 1
    assert [fp["fp_id"] for fp in handoff["function_points"]] == [f"FP-{index:03d}" for index in range(1, 13)]
    assert [
        item["fp_ids"] for item in handoff["scope_index_consumption"]
    ] == [[f"FP-{index:03d}"] for index in range(1, 13)]
    assert any("需求分析策略：source_batches_full" in item for item in progress_messages)
    assert any("需求分析 source 批次 1/3 已提交" in item for item in progress_messages)
    assert any("需求分析批次 3/3 已完成" in item for item in progress_messages)
    assert v2._validate_trusted_requirement_handoff(scope_index, handoff)["passed"] is True


def test_case_generation_v2_unified_schema_loading_and_fallback(tmp_path, monkeypatch) -> None:
    import app.tasks.case_generation_v2 as v2

    unified = tmp_path / "unified"
    legacy = tmp_path / "legacy"
    (unified / "schemas" / "lite").mkdir(parents=True)
    (unified / "schemas" / "trusted").mkdir(parents=True)
    (unified / "skills" / "scope-indexer").mkdir(parents=True)
    (legacy / "schemas").mkdir(parents=True)
    (legacy / "skills" / "testcase-designer").mkdir(parents=True)

    (unified / "README.md").write_text("UNIFIED_README", encoding="utf-8")
    (unified / "schemas" / "trusted" / "scope_index.template.yaml").write_text("TRUSTED_SCOPE_INDEX", encoding="utf-8")
    (unified / "schemas" / "trusted" / "gate_report.template.yaml").write_text("TRUSTED_GATE", encoding="utf-8")
    (unified / "skills" / "scope-indexer" / "SKILL.md").write_text("SCOPE_SKILL", encoding="utf-8")
    (legacy / "schemas" / "testcase_package.template.yaml").write_text("LEGACY_TESTCASE_PACKAGE", encoding="utf-8")

    monkeypatch.setattr(v2.settings, "case_generation_unified_rules_dir", str(unified))
    monkeypatch.setattr(v2.settings, "case_generation_rules_dir", str(legacy))

    assert v2._load_skill_template("scope-indexer", "trusted") == "TRUSTED_SCOPE_INDEX"
    assert v2._load_skill_template("trusted-gate", "lite") == ""
    assert "UNIFIED_README" in v2._load_claw_skill_context("scope-indexer", "trusted")
    assert "SCOPE_SKILL" in v2._load_claw_skill_context("scope-indexer", "trusted")

    monkeypatch.setattr(v2.settings, "case_generation_unified_rules_dir", str(tmp_path / "missing-unified"))
    assert v2._load_skill_template("testcase-designer", "lite") == "LEGACY_TESTCASE_PACKAGE"


def test_case_generation_v2_requirement_gate_rejects_unconsumed_source_and_orphan_fp() -> None:
    from app.tasks.case_generation_v2 import _validate_trusted_requirement_handoff

    scope_index = _trusted_scope_fixture(("SRC-001", "SRC-002"))
    handoff = {
        "scope_index_consumption": [{"source_id": "SRC-001", "result": "converted_to_function_points", "fp_ids": ["FP-001", "FP-404"]}],
        "function_points": [{"fp_id": "FP-001", "source_id": ""}, {"fp_id": "FP-002", "source_id": "SRC-999"}],
    }
    gate = _validate_trusted_requirement_handoff(scope_index, handoff)
    codes = {item["code"] for item in gate["issues"]}
    assert gate["passed"] is False
    assert "SOURCE_NOT_CONSUMED" in codes
    assert "FP_MISSING_SOURCE" in codes
    assert "FP_UNKNOWN_SOURCE" in codes
    assert "CONSUMPTION_UNKNOWN_FP_ID" in codes


def test_case_generation_v2_requirement_gate_rejects_cross_source_fp_receipt() -> None:
    from app.tasks.case_generation_v2 import _normalize_trusted_requirement_handoff, _validate_trusted_requirement_handoff

    scope_index = _trusted_scope_fixture(("SRC-001", "SRC-002"))
    handoff = _normalize_trusted_requirement_handoff(
        scope_index,
        {
            "scope_index_consumption": [
                {"source_id": "SRC-001", "result": "converted_to_function_points", "fp_ids": ["FP-002"]},
                {"source_id": "SRC-002", "result": "converted_to_function_points", "fp_ids": ["FP-002"]},
            ],
            "function_points": [
                {"fp_id": "FP-001", "source_id": "SRC-001", "title": "来源一"},
                {"fp_id": "FP-002", "source_id": "SRC-002", "title": "来源二"},
            ],
        },
    )

    gate = _validate_trusted_requirement_handoff(scope_index, handoff)

    assert gate["passed"] is False
    assert "CONSUMPTION_FP_SOURCE_MISMATCH" in {item["code"] for item in gate["issues"]}


def test_case_generation_v2_repairs_historical_converted_fp_receipts() -> None:
    import app.tasks.case_generation_v2 as v2

    handoff = {
        "scope_index_consumption": [
            {"source_id": "SRC-001", "result": "converted_to_function_points", "fp_ids": ["FP-002"]},
            {"source_id": "SRC-002", "result": "converted_to_function_points", "fp_ids": ["FP-002"]},
        ],
        "function_points": [
            {"fp_id": "FP-001", "source_id": "SRC-001"},
            {"fp_id": "FP-002", "source_id": "SRC-002"},
        ],
    }

    repaired = v2._repair_converted_requirement_consumption(handoff)

    assert repaired["scope_index_consumption"][0]["fp_ids"] == ["FP-001"]
    assert repaired["scope_index_consumption"][1]["fp_ids"] == ["FP-002"]
    assert repaired["normalization_notes"][0]["code"] == "CONSUMPTION_FP_REFS_REPAIRED"


def test_case_generation_v2_requirement_handoff_inherits_and_validates_source_metadata() -> None:
    from app.tasks.case_generation_v2 import _normalize_trusted_requirement_handoff, _validate_trusted_requirement_handoff

    scope_index = _trusted_scope_fixture(("SRC-001",), must_cover="账户登录")
    raw = {
        "scope_index_consumption": [{"source_id": "SRC-001", "result": "converted_to_function_points", "fp_ids": ["FP-001"]}],
        "function_points": [{"fp_id": "FP-001", "source_id": "SRC-001", "title": "密码登录"}],
    }

    normalized = _normalize_trusted_requirement_handoff(scope_index, raw)
    fp = normalized["function_points"][0]

    assert fp["shard_id"] == "SHARD-SRC-001"
    assert fp["title_path"] == "2.1 账户登录"
    assert fp["source_order"] == "2.1"
    assert fp["module"] == "账户"
    assert _validate_trusted_requirement_handoff(scope_index, normalized)["passed"] is True

    invalid = {
        "scope_index_consumption": [{"source_id": "SRC-001", "result": "converted_to_function_points", "fp_ids": ["FP-001"]}],
        "function_points": [
            {
                "fp_id": "FP-001",
                "source_id": "SRC-001",
                "shard_id": "SHARD-WRONG",
                "title_path": "错误路径",
                "source_order": "99",
            }
        ],
    }
    gate = _validate_trusted_requirement_handoff(scope_index, invalid)
    codes = {item["code"] for item in gate["issues"]}
    assert gate["passed"] is False
    assert "FP_SHARD_MISMATCH" in codes
    assert "FP_TITLE_PATH_MISMATCH" in codes
    assert "FP_SOURCE_ORDER_MISMATCH" in codes


def test_case_generation_v2_scope_index_gate_rejects_incomplete_source_and_orphan_dependency() -> None:
    from app.tasks.case_generation_v2 import _validate_trusted_scope_index

    scope_index = _trusted_scope_fixture(("SRC-001",))
    scope_index["shards"][0]["assigned_primary_sources"] = []
    scope_index["shards"][0]["test_design_profile"] = {
        "applicable_methods": [],
        "risk_signals": [],
        "must_cover": [],
        "merge_allowed": [],
        "not_applicable": [],
        "coverage_budget": {"min": 1, "target": 2, "max": 3},
    }
    scope_index["dependency_bindings"] = [{"source_id": "SRC-404", "section": "字段表"}]

    gate = _validate_trusted_scope_index(scope_index)
    codes = {item["code"] for item in gate["issues"]}
    assert gate["passed"] is False
    assert "PRIMARY_SECTIONS_MISSING" in codes
    assert "TEST_DESIGN_METHODS_MISSING" in codes
    assert "MUST_COVER_MISSING" in codes
    assert "COVERAGE_BUDGET_HAS_FIXED_COUNT" in codes
    assert "ORPHAN_DEPENDENCY_BINDING" in codes


def test_case_generation_v2_scope_index_retries_when_json_is_truncated(monkeypatch) -> None:
    import app.tasks.case_generation_v2 as v2

    calls: list[dict] = []

    def fake_call_openai_json(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise v2.ModelJSONParseError(
                "模型输出 JSON 对象不完整，可能因 max_tokens 或模型响应中断被截断",
                raw_text='{"direct_testcase_sources": [',
            )
        return _trusted_scope_fixture(("SRC-001",))

    monkeypatch.setattr(v2, "_call_openai_json", fake_call_openai_json)

    result = v2._build_trusted_scope_index(
        "# 登录\n支持账号密码登录",
        [],
        api_key="sk-test",
        model="test-model",
        base_url="http://example.invalid/v1",
    )

    assert len(calls) == 2
    assert calls[0]["max_tokens"] == 9000
    assert calls[1]["max_tokens"] == 13500
    assert result["direct_testcase_sources"][0]["source_id"] == "SRC-001"
    assert any(item["code"] == "SCOPE_INDEX_RETRY_USED" for item in result["normalization_notes"])


def test_case_generation_v2_scope_index_batches_large_document(monkeypatch) -> None:
    import json
    import app.tasks.case_generation_v2 as v2

    calls: list[list[str]] = []

    def fake_call_openai_json(**kwargs):
        payload = json.loads(kwargs["user_content"])
        section_titles = [item["title"] for item in payload["sections"]]
        calls.append(section_titles)
        source_ids = tuple(f"SRC-{index:03d}" for index in range(1, len(section_titles) + 1))
        fixture = _trusted_scope_fixture(source_ids, must_cover="批次功能")
        for index, title in enumerate(section_titles):
            fixture["source_blocks"][index]["title"] = title
            fixture["source_blocks"][index]["title_path"] = title
            fixture["source_blocks"][index]["xmind_source_node"] = f"{fixture['source_blocks'][index]['block_id']}｜{title}"
            fixture["shards"][index]["title_path"] = title
            fixture["shards"][index]["xmind_source_node"] = f"{fixture['shards'][index]['direct_testcase_source']}｜{title}"
        return fixture

    monkeypatch.setattr(v2, "_call_openai_json", fake_call_openai_json)

    markdown = "\n".join(
        f"## 功能 {index}\n支持规则 {index} " + ("规则详情" * 700)
        for index in range(1, 11)
    )
    progress_messages: list[str] = []
    result = v2._build_trusted_scope_index(
        markdown,
        [],
        api_key="sk-test",
        model="test-model",
        base_url="http://example.invalid/v1",
        progress_callback=progress_messages.append,
    )

    assert len(calls) == 4
    assert [item["source_id"] for item in result["direct_testcase_sources"]] == [f"SRC-{index:03d}" for index in range(1, 11)]
    assert [item["shard_id"] for item in result["shards"]] == [f"SHARD-{index:03d}" for index in range(1, 11)]
    assert any(item["code"] == "SCOPE_INDEX_SECTION_BATCH_USED" for item in result["normalization_notes"])
    assert result["execution_strategy"]["mode"] == "section_batches_full"
    assert result["execution_strategy"]["batch_count"] == 4
    assert any("范围索引策略：section_batches_full" in item for item in progress_messages)
    assert any("范围索引分批 1/4 已提交" in item for item in progress_messages)
    assert any("范围索引分批 4/4 已完成" in item for item in progress_messages)
    assert v2._validate_trusted_scope_index(result)["passed"] is True


def test_case_generation_v2_scope_index_lightweight_batches_and_concurrency(monkeypatch) -> None:
    import json
    import threading
    import app.tasks.case_generation_v2 as v2

    state = {"running": 0, "max_running": 0}
    lock = threading.Lock()
    calls: list[dict] = []

    def fake_call_openai_json(**kwargs):
        payload = json.loads(kwargs["user_content"])
        with lock:
            state["running"] += 1
            state["max_running"] = max(state["max_running"], state["running"])
        time.sleep(0.02)
        with lock:
            state["running"] -= 1
        calls.append(payload)
        section_titles = [item["title"] for item in payload["sections"]]
        fixture = _trusted_scope_fixture(
            tuple(f"SRC-{index:03d}" for index in range(1, len(section_titles) + 1)),
            must_cover="长文档功能",
        )
        fixture["shards"] = []
        for index, title in enumerate(section_titles):
            fixture["source_blocks"][index]["title"] = title
            fixture["source_blocks"][index]["title_path"] = title
        return fixture

    monkeypatch.setattr(v2, "_SCOPE_INDEX_CONCURRENCY", 2)
    monkeypatch.setattr(v2, "_call_openai_json", fake_call_openai_json)

    markdown = "\n".join(f"## 功能 {index}\n" + ("规则 " * 1000) for index in range(1, 18))
    progress_messages: list[str] = []
    result = v2._build_trusted_scope_index(
        markdown,
        [],
        api_key="sk-test",
        model="test-model",
        base_url="http://example.invalid/v1",
        progress_callback=progress_messages.append,
    )

    assert len(calls) == 6
    assert state["max_running"] <= 2
    assert state["max_running"] > 1
    assert all(call["batch_policy"]["lightweight_discovery"] is True for call in calls)
    assert all("shards" not in call["schema"] for call in calls)
    assert result["execution_strategy"]["mode"] == "section_batches_lightweight"
    assert result["execution_strategy"]["concurrency"] == 2
    assert len(result["direct_testcase_sources"]) == 17
    assert len(result["shards"]) == 17
    assert any(item["code"] == "SCOPE_INDEX_LIGHTWEIGHT_DISCOVERY_USED" for item in result["normalization_notes"])
    assert any(item["code"] == "MISSING_SHARDS_REBUILT" for item in result["normalization_notes"])
    assert all(item.get("severity") != "warning" for item in result["normalization_notes"] if item.get("code") == "MISSING_SHARDS_REBUILT")
    assert any("并发 2" in item for item in progress_messages)
    assert v2._validate_trusted_scope_index(result)["passed"] is True


def test_case_generation_v2_canonical_gate_report_does_not_fail_on_warning() -> None:
    from app.tasks.case_generation_v2 import _canonical_gate_report_for_validator

    report = _canonical_gate_report_for_validator(
        {
            "passed": True,
            "status": "warning",
            "issues": [{"severity": "warning", "code": "BATCHED_INDEX"}],
            "blocking_issues": [],
        }
    )

    assert report["passed"] is True
    assert report["status"] == "pass"


def test_case_generation_v2_canonical_gate_report_keeps_blocking_failure() -> None:
    from app.tasks.case_generation_v2 import _canonical_gate_report_for_validator

    report = _canonical_gate_report_for_validator(
        {
            "passed": False,
            "status": "warning",
            "issues": [{"severity": "blocker", "code": "SOURCE_MISSING"}],
            "blocking_issues": [{"severity": "blocker", "code": "SOURCE_MISSING"}],
        }
    )

    assert report["passed"] is False
    assert report["status"] == "fail"


def test_case_generation_v2_canonical_gate_report_finds_blocker_in_issues() -> None:
    from app.tasks.case_generation_v2 import _canonical_gate_report_for_validator

    report = _canonical_gate_report_for_validator(
        {
            "passed": True,
            "status": "warning",
            "issues": [{"severity": "blocker", "code": "SOURCE_MISSING"}],
            "blocking_issues": [],
        }
    )

    assert report["passed"] is False
    assert report["status"] == "fail"
    assert report["blocking_issues"][0]["code"] == "SOURCE_MISSING"


def test_case_generation_v2_scope_index_flattens_nested_shards() -> None:
    import app.tasks.case_generation_v2 as v2

    raw = _trusted_scope_fixture(("SRC-001", "SRC-002"), must_cover="嵌套 shard")
    raw["shards"] = [[raw["shards"][0]], [raw["shards"][1]]]

    result = v2._normalize_trusted_scope_index(raw)

    assert [item["direct_testcase_source"] for item in result["shards"]] == ["SRC-001", "SRC-002"]
    assert any(item["code"] == "SHARDS_NESTED_LIST_FLATTENED" for item in result["normalization_notes"])
    assert v2._validate_trusted_scope_index(result)["passed"] is True


def test_case_generation_v2_scope_index_rebuilds_invalid_or_missing_shards() -> None:
    import app.tasks.case_generation_v2 as v2

    raw = _trusted_scope_fixture(("SRC-001", "SRC-002"), must_cover="补齐 shard")
    raw["shards"] = [raw["shards"][0], "SRC-002", None]

    result = v2._normalize_trusted_scope_index(raw)

    assert [item["direct_testcase_source"] for item in result["shards"]] == ["SRC-001", "SRC-002"]
    assert any(item["code"] == "SHARDS_INVALID_ITEMS_IGNORED" for item in result["normalization_notes"])
    assert any(item["code"] == "MISSING_SHARDS_REBUILT" for item in result["normalization_notes"])
    assert v2._validate_trusted_scope_index(result)["passed"] is True


def test_case_generation_v2_scope_index_timeout_falls_back_to_batches(monkeypatch) -> None:
    import json
    import app.tasks.case_generation_v2 as v2

    calls: list[dict] = []

    def fake_call_openai_json(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("模型响应超时（>420s），请重试或缩小需求范围")
        payload = json.loads(kwargs["user_content"])
        source_ids = tuple(f"SRC-{index:03d}" for index in range(1, len(payload["sections"]) + 1))
        return _trusted_scope_fixture(source_ids, must_cover="超时后分批")

    monkeypatch.setattr(v2, "_call_openai_json", fake_call_openai_json)

    result = v2._build_trusted_scope_index(
        "## 登录\n支持账号密码登录\n## 权限\n不同角色显示不同菜单",
        [],
        api_key="sk-test",
        model="test-model",
        base_url="http://example.invalid/v1",
    )

    assert len(calls) == 2
    assert result["direct_testcase_sources"][0]["source_id"] == "SRC-001"
    assert any(item["code"] == "SCOPE_INDEX_SECTION_BATCH_USED" for item in result["normalization_notes"])


def test_case_generation_v2_testcase_gate_rejects_missing_fp_and_method_consumption() -> None:
    from app.tasks.case_generation_v2 import _validate_trusted_testcase_handoff

    scope_index = _trusted_scope_fixture(("SRC-001",))
    requirement_handoff = {
        "function_points": [
            {"fp_id": "FP-001", "source_id": "SRC-001"},
            {"fp_id": "FP-002", "source_id": "SRC-001"},
        ]
    }
    testcase_handoff = {
        "feature_point_consumption": [
            {"fp_id": "FP-001", "source_id": "SRC-001", "result": "covered_by_case", "case_ids": ["TC-001", "TC-002", "TC-404"]},
        ],
        "testcases": [
            {"case_id": "TC-001", "source_id": "SRC-001", "shard_id": "SHARD-001", "fp_id": "FP-001", "fp_ids": ["FP-001"]},
            {"case_id": "TC-002", "source_id": "SRC-001", "shard_id": "SHARD-001", "fp_id": "FP-001", "fp_ids": ["FP-001"]},
        ],
        "xmind_grouping_contract": {"required_tree": "模块 -> 场景 -> SRC -> FP -> TC"},
    }
    gate = _validate_trusted_testcase_handoff(scope_index, requirement_handoff, testcase_handoff)
    codes = {item["code"] for item in gate["issues"]}
    assert gate["passed"] is False
    assert "FP_NOT_CONSUMED" in codes
    assert "METHOD_NOT_CONSUMED" in codes
    assert "FP_CONSUMPTION_UNKNOWN_CASE_ID" in codes


def test_case_generation_v2_source_shard_contract_rejects_claimed_coverage_without_cases() -> None:
    import pytest
    import app.tasks.case_generation_v2 as v2

    source = v2._trusted_scope_source_items(_trusted_scope_fixture(("SRC-002",)))[0]
    source["test_design_profile"]["applicable_methods"] = ["ui_check"]
    function_points = [{"fp_id": "FP-002", "source_id": "SRC-002"}]
    shard = {
        "feature_point_consumption": [
            {"fp_id": "FP-002", "source_id": "SRC-002", "consumption_result": "covered_by_case", "case_refs": ["TC-001"]}
        ],
        "method_consumption": [
            {"source_id": "SRC-002", "method": "ui_check", "consumption_result": "covered_by_case", "case_refs": ["TC-001"]}
        ],
        "testcases": [],
    }

    with pytest.raises(Exception, match="没有 testcases"):
        v2._validate_trusted_source_shard_contract(source, function_points, shard)


def test_case_generation_v2_renumber_drops_unmapped_source_local_case_refs() -> None:
    from app.tasks.case_generation_v2 import _renumber_trusted_shard_cases

    result = _renumber_trusted_shard_cases([
        {
            "source_id": "SRC-002",
            "testcases": [],
            "feature_point_consumption": [
                {"fp_id": "FP-002", "source_id": "SRC-002", "consumption_result": "covered_by_case", "case_ids": ["TC-001"]}
            ],
            "method_consumption": [
                {"source_id": "SRC-002", "method": "ui_check", "consumption_result": "covered_by_case", "case_refs": ["TC-001"]}
            ],
        }
    ])

    assert result["feature_point_consumption"][0]["case_ids"] == []
    assert result["method_consumption"][0]["case_refs"] == []


def test_case_generation_v2_replace_shard_relocalizes_existing_global_case_ids() -> None:
    from app.tasks.case_generation_v2 import _replace_trusted_testcase_shard

    existing = {
        "testcase_shards": [
            {
                "source_id": "SRC-001",
                "testcases": [{"case_id": "TC-001", "source_id": "SRC-001", "fp_id": "FP-001", "fp_ids": ["FP-001"]}],
                "feature_point_consumption": [{"fp_id": "FP-001", "source_id": "SRC-001", "result": "covered_by_case", "case_ids": ["TC-001"]}],
                "method_consumption": [{"source_id": "SRC-001", "method": "equivalence", "result": "covered_by_case", "case_refs": ["TC-001"]}],
            },
            {
                "source_id": "SRC-002",
                "testcases": [],
                "feature_point_consumption": [{"fp_id": "FP-002", "source_id": "SRC-002", "result": "covered_by_case", "case_ids": ["TC-001"]}],
                "method_consumption": [{"source_id": "SRC-002", "method": "ui_check", "result": "covered_by_case", "case_refs": ["TC-001"]}],
            },
            {
                "source_id": "SRC-003",
                "testcases": [
                    {"case_id": "TC-005", "source_id": "SRC-003", "fp_id": "FP-003", "fp_ids": ["FP-003"], "title": "SRC-003 用例 A"},
                    {"case_id": "TC-006", "source_id": "SRC-003", "fp_id": "FP-003", "fp_ids": ["FP-003"], "title": "SRC-003 用例 B"},
                ],
                "feature_point_consumption": [{"fp_id": "FP-003", "source_id": "SRC-003", "result": "covered_by_case", "case_ids": ["TC-001", "TC-002"]}],
                "method_consumption": [{"source_id": "SRC-003", "method": "equivalence", "result": "covered_by_case", "case_refs": ["TC-001"]}],
            },
        ]
    }
    replacement = {
        "source_id": "SRC-002",
        "testcases": [{"case_id": "TC-001", "source_id": "SRC-002", "fp_id": "FP-002", "fp_ids": ["FP-002"], "title": "SRC-002 用例"}],
        "feature_point_consumption": [{"fp_id": "FP-002", "source_id": "SRC-002", "result": "covered_by_case", "case_ids": ["TC-001"]}],
        "method_consumption": [{"source_id": "SRC-002", "method": "ui_check", "result": "covered_by_case", "case_refs": ["TC-001"]}],
    }

    result = _replace_trusted_testcase_shard(existing, replacement)

    by_fp = {item["fp_id"]: item["case_ids"] for item in result["feature_point_consumption"]}
    assert by_fp["FP-001"] == ["TC-001"]
    assert by_fp["FP-002"] == ["TC-002"]
    assert by_fp["FP-003"] == ["TC-003", "TC-004"]
    assert [(case["case_id"], case["source_id"]) for case in result["testcases"]] == [
        ("TC-001", "SRC-001"),
        ("TC-002", "SRC-002"),
        ("TC-003", "SRC-003"),
        ("TC-004", "SRC-003"),
    ]


def test_case_generation_v2_testcase_gate_rejects_cross_source_consumption_refs() -> None:
    from app.tasks.case_generation_v2 import _validate_trusted_testcase_handoff

    scope_index = _trusted_scope_fixture(("SRC-001", "SRC-002"))
    requirement_handoff = {
        "function_points": [
            {"fp_id": "FP-001", "source_id": "SRC-001"},
            {"fp_id": "FP-002", "source_id": "SRC-002"},
        ]
    }
    testcase_handoff = {
        "feature_point_consumption": [
            {"fp_id": "FP-001", "source_id": "SRC-001", "result": "covered_by_case", "case_ids": ["TC-001"]},
            {"fp_id": "FP-002", "source_id": "SRC-002", "result": "covered_by_case", "case_ids": ["TC-001"]},
        ],
        "method_consumption": [
            {"source_id": "SRC-002", "method": "equivalence", "result": "covered_by_case", "case_refs": ["TC-001"]},
        ],
        "testcases": [
            {"case_id": "TC-001", "source_id": "SRC-001", "shard_id": "SHARD-001", "fp_id": "FP-001", "fp_ids": ["FP-001"]},
        ],
        "xmind_grouping_contract": {"required_tree": "模块 -> 场景 -> SRC -> FP -> TC"},
    }

    gate = _validate_trusted_testcase_handoff(scope_index, requirement_handoff, testcase_handoff)
    codes = {item["code"] for item in gate["issues"]}
    assert "FP_CONSUMPTION_CASE_SOURCE_MISMATCH" in codes
    assert "METHOD_CONSUMPTION_CASE_SOURCE_MISMATCH" in codes


def test_case_generation_v2_testcase_gate_reports_failed_source_shard_before_missing_fp() -> None:
    from app.tasks.case_generation_v2 import _validate_trusted_testcase_handoff

    scope_index = _trusted_scope_fixture(("SRC-001", "SRC-002"))
    requirement_handoff = {
        "function_points": [
            {"fp_id": "FP-001", "source_id": "SRC-001"},
            {"fp_id": "FP-002", "source_id": "SRC-002"},
        ]
    }
    testcase_handoff = {
        "testcase_shards": [
            {"source_id": "SRC-001", "status": "failed", "error": "HTTP 500"},
            {
                "source_id": "SRC-002",
                "status": "success",
                "feature_point_consumption": [{"fp_id": "FP-002", "source_id": "SRC-002", "result": "covered_by_case", "case_ids": ["TC-001"]}],
                "testcases": [],
            },
        ],
        "shard_failures": [{"source_id": "SRC-001", "error": "HTTP 500"}],
        "feature_point_consumption": [{"fp_id": "FP-002", "source_id": "SRC-002", "result": "covered_by_case", "case_ids": ["TC-001"]}],
        "method_consumption": _trusted_method_consumption("SRC-002"),
            "testcases": [{
                "case_id": "TC-001",
                "source_id": "SRC-002",
                "shard_id": "SHARD-SRC-002",
                "fp_id": "FP-002",
                "fp_ids": ["FP-002"],
                "title": "登录功能验证",
                "steps": [{"step_no": 1, "action": "提交登录信息"}],
                "expected_results": ["页面显示登录成功状态"],
                "evidence_refs": ["2.2 登录"],
                "design_method": "equivalence",
                "scenario_dimensions": ["positive"],
                "must_cover_refs": ["登录"],
            }],
        "xmind_grouping_contract": {"required_tree": "模块 -> 场景 -> SRC -> FP -> TC"},
    }

    gate = _validate_trusted_testcase_handoff(scope_index, requirement_handoff, testcase_handoff)
    codes = {item["code"] for item in gate["issues"]}

    assert gate["passed"] is False
    assert "SOURCE_SHARD_FAILED" in codes
    assert "FP_NOT_CONSUMED" not in codes
    assert "MUST_COVER_NOT_COVERED" not in codes
    assert "METHOD_NOT_CONSUMED" not in codes
    assert gate["recovery_plan"]["rerun_scope"]["source_ids"] == ["SRC-001"]
    assert gate["recovery_plan"]["rerun_scope"]["fp_ids"] == ["FP-001"]


def test_case_generation_v2_shard_finalize_backfills_case_contract_fields() -> None:
    from app.tasks.case_generation_v2 import _finalize_trusted_testcase_shards, _validate_trusted_testcase_handoff

    scope_index = _trusted_scope_fixture(("SRC-001",))
    requirement_handoff = {
        "function_points": [
            {"fp_id": "FP-001", "source_id": "SRC-001"},
        ]
    }
    testcase_handoff = _finalize_trusted_testcase_shards(
        [
            {
                "source_id": "SRC-001",
                "status": "success",
                "feature_point_consumption": [
                    {"fp_id": "FP-001", "source_id": "SRC-001", "result": "covered_by_case", "case_ids": ["LOCAL-1"]}
                ],
                "method_consumption": [
                    {"source_id": "SRC-001", "method": "equivalence", "result": "covered_by_case", "case_ids": ["LOCAL-1"]}
                ],
                "testcases": [
                        {
                            "case_id": "LOCAL-1",
                            "source_id": "SRC-001",
                            "fp_id": "FP-001",
                            "title": "登录功能验证",
                            "steps": [{"step_no": 1, "action": "提交有效登录信息"}],
                            "expected_results": ["页面显示登录成功状态"],
                            "evidence_refs": ["2.1 登录"],
                            "design_method": "equivalence",
                            "scenario_dimensions": ["positive"],
                            "must_cover_refs": ["登录"],
                            "traceability": {"function_points": ["FP-001"], "source_id": "SRC-001"},
                        }
                ],
            }
        ]
    )

    case = testcase_handoff["testcases"][0]
    assert case["case_id"] == "TC-001"
    assert case["shard_id"] == "SHARD-SRC-001"
    assert case["fp_ids"] == ["FP-001"]
    gate = _validate_trusted_testcase_handoff(scope_index, requirement_handoff, testcase_handoff)
    assert gate["passed"] is True


def test_case_generation_v2_source_shards_report_progress_and_concurrency(monkeypatch) -> None:
    import app.tasks.case_generation_v2 as v2

    async def fake_build_source_shard(source, function_points, **kwargs):
        source_id = source["source_id"]
        return {
            "feature_point_consumption": [
                {"fp_id": function_points[0]["fp_id"], "source_id": source_id, "result": "covered_by_case", "case_ids": [f"{source_id}-TC-1"]}
            ],
            "method_consumption": [
                {"source_id": source_id, "method": "equivalence", "result": "covered_by_case", "case_refs": [f"{source_id}-TC-1"]}
            ],
            "testcases": [
                {
                    "case_id": f"{source_id}-TC-1",
                    "source_id": source_id,
                    "shard_id": source["shard_id"],
                    "fp_id": function_points[0]["fp_id"],
                        "fp_ids": [function_points[0]["fp_id"]],
                        "title": f"{source_id} 用例",
                        "steps": [{"step_no": 1, "action": "执行"}],
                        "expected_results": ["页面显示执行成功状态"],
                        "evidence_refs": [source["title_path"]],
                        "design_method": "equivalence",
                        "scenario_dimensions": ["positive"],
                        "must_cover_refs": list(source["test_design_profile"]["must_cover"]),
                    }
            ],
        }

    monkeypatch.setattr(v2, "_TRUSTED_SHARD_CONCURRENCY", 2)
    monkeypatch.setattr(v2, "_build_trusted_testcase_source_shard_async", fake_build_source_shard)
    messages: list[str] = []
    scope_index = _trusted_scope_fixture(("SRC-001", "SRC-002"))
    requirement_handoff = {
        "function_points": [
            {"fp_id": "FP-001", "source_id": "SRC-001"},
            {"fp_id": "FP-002", "source_id": "SRC-002"},
        ]
    }

    result = v2._build_trusted_testcase_handoff(
        scope_index,
        requirement_handoff,
        api_key="sk-test",
        model="test-model",
        base_url="http://example.invalid/v1",
        progress_callback=messages.append,
    )

    assert result["shard_progress_summary"]["concurrency"] == 2
    assert result["shard_progress_summary"]["success_count"] == 2
    assert result["testcase_shards"][0]["duration_ms"] >= 0
    assert any("第 1/2" in message and "并发 2" in message for message in messages)
    assert any("已完成 2/2" in message and "本分片耗时" in message for message in messages)


def test_case_generation_v2_source_shard_retries_transient_error(monkeypatch) -> None:
    import app.tasks.case_generation_v2 as v2

    attempts = {"count": 0}

    async def fake_build_source_shard(source, function_points, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("OpenAI 请求失败，HTTP 500：InternalError.Algo STOP_FROM_ENGINE")
        source_id = source["source_id"]
        fp_id = function_points[0]["fp_id"]
        return {
            "feature_point_consumption": [
                {"fp_id": fp_id, "source_id": source_id, "result": "covered_by_case", "case_ids": [f"{source_id}-TC-1"]}
            ],
            "method_consumption": [
                {"source_id": source_id, "method": "equivalence", "result": "covered_by_case", "case_refs": [f"{source_id}-TC-1"]}
            ],
            "testcases": [
                    {
                        "case_id": f"{source_id}-TC-1",
                        "source_id": source_id,
                        "shard_id": source["shard_id"],
                        "fp_id": fp_id,
                        "fp_ids": [fp_id],
                        "title": "登录功能验证",
                        "steps": [{"step_no": 1, "action": "提交有效登录信息"}],
                        "expected_results": ["页面显示登录成功状态"],
                        "evidence_refs": [source["title_path"]],
                        "design_method": "equivalence",
                        "scenario_dimensions": ["positive"],
                        "must_cover_refs": list(source["test_design_profile"]["must_cover"]),
                    }
            ],
        }

    monkeypatch.setattr(v2, "_TRUSTED_SHARD_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(v2, "_build_trusted_testcase_source_shard_async", fake_build_source_shard)
    messages: list[str] = []
    result = v2._build_trusted_testcase_handoff(
        _trusted_scope_fixture(("SRC-001",)),
        {"function_points": [{"fp_id": "FP-001", "source_id": "SRC-001"}]},
        api_key="sk-test",
        model="test-model",
        base_url="http://example.invalid/v1",
        progress_callback=messages.append,
    )

    assert attempts["count"] == 2
    assert result["shard_progress_summary"]["success_count"] == 1
    assert result["shard_failures"] == []
    assert result["feature_point_consumption"][0]["fp_id"] == "FP-001"
    assert any("正在重试 SRC-001" in message and "第 2/2 次" in message for message in messages)


def test_case_generation_v2_shard_failure_message_clarifies_model_concurrency() -> None:
    from app.tasks.case_generation_v2 import _trusted_shard_failure_message

    message = _trusted_shard_failure_message(
        {
            "shard_failures": [
                {
                    "source_id": "SRC-006",
                    "error": "OpenAI 请求失败，HTTP 429：concurrency allocated quota exceeded. please try again later.",
                }
            ]
        }
    )

    assert "模型并发配额不足" in message
    assert "SRC-006" in message


def test_case_generation_v2_combined_gate_blocks_when_model_review_returns_failure() -> None:
    from app.tasks.case_generation_v2 import _combine_trusted_gate

    deterministic_gate = {"gate": "requirement_gate", "passed": True, "issues": [], "source_count": 1}
    model_gate = {
        "review_stage": "requirement_gate",
        "passed": False,
        "decision": "return",
        "checked_items": [{"item": "source consumption", "result": "fail", "note": "SRC-001 missing rules"}],
        "blocking_issues": [{"source_id": "SRC-001", "message": "功能点未覆盖关键规则"}],
        "return_to": "requirement",
        "return_reason": "补齐规则消费回执",
    }

    gate = _combine_trusted_gate(deterministic_gate, model_gate)

    assert gate["passed"] is False
    assert gate["status"] == "fail"
    assert gate["issue_counts"]["blocker"] == 1
    assert gate["issue_counts"]["warning"] == 0
    assert gate["deterministic_passed"] is True
    assert gate["model_passed"] is False
    assert gate["model_gate_applied"] is True
    assert gate["model_return_to"] == "requirement"
    assert gate["issues"][0]["code"] == "MODEL_HANDOFF_REVIEW_BLOCKER"
    assert gate["issues"][0]["severity"] == "blocker"
    assert gate["recovery_plan"]["return_to"] == "requirement"
    assert gate["recovery_plan"]["rerun_scope"]["source_ids"] == ["SRC-001"]


def test_case_generation_v2_combined_gate_skips_model_when_backend_gate_fails() -> None:
    from app.tasks.case_generation_v2 import _run_trusted_combined_gate

    deterministic_gate = {
        "gate": "scope_index_gate",
        "passed": False,
        "issues": [{"severity": "blocker", "code": "NO_DIRECT_TESTCASE_SOURCE", "message": "direct_testcase_sources 为空"}],
    }
    gate, model_gate = _run_trusted_combined_gate(
        review_stage="scope_index_gate",
        deterministic_gate=deterministic_gate,
        scope_index={"direct_testcase_sources": []},
        api_key="sk-test",
        model="test-model",
        base_url="http://example.invalid/v1",
    )

    assert model_gate is None
    assert gate["passed"] is False
    assert gate["status"] == "fail"
    assert gate["deterministic_passed"] is False
    assert gate["model_gate_applied"] is False


def test_case_generation_v2_combined_gate_skips_model_by_default(monkeypatch) -> None:
    import app.tasks.case_generation_v2 as v2

    called = False

    def fake_model_gate(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("model gate should be disabled by default")

    monkeypatch.setattr(v2, "_TRUSTED_MODEL_GATE_ENABLED", False)
    monkeypatch.setattr(v2, "_build_trusted_model_handoff_gate", fake_model_gate)
    gate, model_gate = v2._run_trusted_combined_gate(
        review_stage="scope_index_gate",
        deterministic_gate={"gate": "scope_index_gate", "passed": True, "issues": []},
        scope_index={"direct_testcase_sources": [{"source_id": "SRC-001"}]},
        api_key="sk-test",
        model="test-model",
        base_url="http://example.invalid/v1",
    )

    assert called is False
    assert model_gate is None
    assert gate["passed"] is True
    assert gate["model_gate_applied"] is False


def test_case_generation_v2_evidence_pending_is_merged_into_scope_index() -> None:
    from app.tasks.case_generation_v2 import _build_trusted_evidence_artifact, _merge_evidence_risks_into_scope_index

    evidence = _build_trusted_evidence_artifact(
        "# 登录\n![登录图](img.png)",
        ["img.png"],
        [{"image_id": "IMG-001", "download_status": "success", "local_path": "/tmp/img.png"}],
        [],
    )
    assert evidence["vision_failed_count"] == 1
    assert evidence["pending_confirmations"][0]["ref_id"] == "IMG-001"

    scope_index = {"direct_testcase_sources": [{"source_id": "SRC-001"}], "index_risks": []}
    merged = _merge_evidence_risks_into_scope_index(scope_index, evidence)
    assert merged["index_risks"][0]["code"] == "IMAGE_EVIDENCE_PENDING"
    assert merged["index_risks"][0]["ref_id"] == "IMG-001"


def test_case_generation_v2_evidence_trace_gate_requires_tool_status_and_pending_failures() -> None:
    from app.tasks.case_generation_v2 import _build_trusted_evidence_artifact, _validate_trusted_evidence_trace

    evidence = _build_trusted_evidence_artifact(
        "![图](https://example.com/a.png)",
        ["https://example.com/a.png"],
        [{"image_id": "IMG-001", "url": "https://example.com/a.png", "download_status": "success"}],
        [],
    )
    gate = _validate_trusted_evidence_trace(evidence)
    assert gate["passed"] is True
    assert evidence["images"][0]["download_tool"] == "httpx"
    assert evidence["images"][0]["vision_tool"] == "model_vision"

    broken = {
        "image_link_count": 1,
        "images": [{"image_id": "IMG-001", "download_status": "success", "vision_status": "skipped"}],
        "failed_images": [],
        "pending_confirmations": [],
    }
    gate = _validate_trusted_evidence_trace(broken)
    codes = {item["code"] for item in gate["issues"]}
    assert gate["passed"] is False
    assert "EVIDENCE_IMAGE_MISSING_DOWNLOAD_TOOL" in codes
    assert "EVIDENCE_SUCCESS_DOWNLOAD_SKIPPED_VISION" in codes


def test_case_generation_v2_recovery_plan_uses_local_rerun_scope() -> None:
    from app.tasks.case_generation_v2 import _trusted_gate_recovery_plan

    plan = _trusted_gate_recovery_plan(
        "testcase_gate",
        [{"message": "SRC-014 / FP-007 / TC-009 需要重跑"}],
    )

    assert plan["strategy"] == "local_rerun"
    assert plan["return_to"] == "testcase_by_source_shard"
    assert plan["rerun_scope"]["source_ids"] == ["SRC-014"]
    assert plan["rerun_scope"]["shard_ids"] == ["SHARD-SRC-014"]
    assert plan["rerun_scope"]["fp_ids"] == ["FP-007"]
    assert plan["rerun_scope"]["case_ids"] == ["TC-009"]


def test_case_generation_v2_model_handoff_gate_uses_model_review(monkeypatch) -> None:
    import app.tasks.case_generation_v2 as v2

    def fake_call_skill_with_gate(**kwargs):
        assert kwargs["skill_name"] == "review-pipeline-handoff"
        assert kwargs["task_payload"]["review_stage"] == "testcase_gate"
        result = {
            "metadata": {"reviewer": "review-pipeline-handoff", "version": "trusted-v2"},
            "review_stage": "testcase_gate",
            "passed": True,
            "decision": "pass",
            "expected_sources": ["SRC-001"],
            "completed_sources": ["SRC-001"],
            "missing_sources": [],
            "duplicate_sources": [],
            "checked_items": [{"item": "fp consumption", "result": "pass", "note": ""}],
            "blocking_issues": [],
            "return_to": "",
            "return_reason": "",
        }
        return kwargs["validator"](result)

    monkeypatch.setattr(v2, "_TRUSTED_MODEL_GATE_ENABLED", True)
    monkeypatch.setattr(v2, "_call_skill_with_gate", fake_call_skill_with_gate)
    scope_index = _trusted_scope_fixture(("SRC-001",))
    requirement_handoff = {"function_points": [{"fp_id": "FP-001", "source_id": "SRC-001"}]}
    testcase_handoff = {
        "feature_point_consumption": [
            {"fp_id": "FP-001", "source_id": "SRC-001", "result": "covered_by_case", "case_ids": ["TC-001"]}
        ],
        "method_consumption": _trusted_method_consumption("SRC-001"),
        "testcases": [{
            "case_id": "TC-001",
            "source_id": "SRC-001",
            "shard_id": "SHARD-001",
            "fp_id": "FP-001",
            "fp_ids": ["FP-001"],
            "title": "登录功能验证",
            "steps": [{"step_no": 1, "action": "提交有效登录信息"}],
            "expected_results": ["页面显示登录成功状态"],
            "evidence_refs": ["2.1 登录"],
            "design_method": "equivalence",
            "scenario_dimensions": ["positive"],
            "must_cover_refs": ["登录"],
        }],
        "xmind_grouping_contract": {"required_tree": "模块 -> 场景 -> SRC -> FP -> TC"},
    }
    deterministic_gate = v2._validate_trusted_testcase_handoff(scope_index, requirement_handoff, testcase_handoff)

    gate, model_gate = v2._run_trusted_combined_gate(
        review_stage="testcase_gate",
        deterministic_gate=deterministic_gate,
        scope_index=scope_index,
        requirement_handoff=requirement_handoff,
        testcase_handoff=testcase_handoff,
        api_key="sk-test",
        model="test-model",
        base_url="http://example.invalid/v1",
    )

    assert model_gate is not None
    assert gate["passed"] is True
    assert gate["model_passed"] is True
    assert gate["model_checked_item_count"] == 1


def test_case_generation_v2_model_handoff_issue_remains_blocker() -> None:
    import app.tasks.case_generation_v2 as v2

    deterministic_gate = {"gate": "testcase_gate", "passed": True, "issues": []}
    model_gate = {
        "passed": False,
        "decision": "return",
        "blocking_issues": [{"source_id": "SRC-001", "severity": "blocker", "message": "语义覆盖建议补强"}],
        "checked_items": [],
    }

    gate = v2._combine_trusted_gate(deterministic_gate, model_gate)

    assert gate["passed"] is False
    assert gate["status"] == "fail"
    assert gate["issue_counts"]["blocker"] == 1
    assert gate["issue_counts"]["warning"] == 0
    assert gate["issues"][0]["code"] == "MODEL_HANDOFF_REVIEW_BLOCKER"
    assert gate["issues"][0]["severity"] == "blocker"


def test_case_generation_v2_testcase_gate_method_gap_blocks_delivery() -> None:
    import app.tasks.case_generation_v2 as v2

    scope_index = _trusted_scope_fixture(("SRC-001",), method="boundary", must_cover="登录")
    requirement_handoff = {"function_points": [{"fp_id": "FP-001", "source_id": "SRC-001"}]}
    testcase_handoff = {
        "feature_point_consumption": [
            {"fp_id": "FP-001", "source_id": "SRC-001", "result": "covered_by_case", "case_ids": ["TC-001"]}
        ],
        "method_consumption": [],
        "testcases": [{"case_id": "TC-001", "source_id": "SRC-001", "shard_id": "SHARD-001", "fp_id": "FP-001", "fp_ids": ["FP-001"], "title": "登录"}],
        "xmind_grouping_contract": {"required_tree": "模块 -> 场景 -> SRC -> FP -> TC"},
    }
    deterministic_gate = v2._validate_trusted_testcase_handoff(scope_index, requirement_handoff, testcase_handoff)
    assert deterministic_gate["passed"] is False
    assert any(item["code"] == "METHOD_NOT_CONSUMED" for item in deterministic_gate["issues"])

    gate = v2._combine_trusted_gate(deterministic_gate, None)

    assert gate["passed"] is False
    assert gate["status"] == "fail"
    assert gate["issue_counts"]["blocker"] >= 1


def test_case_generation_v2_renumbers_source_shard_cases_and_rewrites_receipts() -> None:
    from app.tasks.case_generation_v2 import _renumber_trusted_shard_cases

    result = _renumber_trusted_shard_cases(
        [
            {
                "source_id": "SRC-001",
                "feature_point_consumption": [
                    {"fp_id": "FP-001", "source_id": "SRC-001", "result": "covered_by_case", "case_ids": ["A-1"]}
                ],
                "testcases": [{"case_id": "A-1", "source_id": "SRC-001", "fp_id": "FP-001"}],
            },
            {
                "source_id": "SRC-002",
                "feature_point_consumption": [
                    {"fp_id": "FP-002", "source_id": "SRC-002", "result": "covered_by_case", "case_ids": ["A-1"]}
                ],
                "testcases": [{"case_id": "A-1", "source_id": "SRC-002", "fp_id": "FP-002"}],
            },
        ]
    )

    assert result["generation_strategy"] == "source_shard"
    assert [case["case_id"] for case in result["testcases"]] == ["TC-001", "TC-002"]
    assert result["feature_point_consumption"][0]["case_ids"] == ["TC-001"]
    assert result["feature_point_consumption"][1]["case_ids"] == ["TC-002"]


def test_case_generation_v2_merges_duplicate_cases_and_rewrites_consumption() -> None:
    from app.tasks.case_generation_v2 import _merge_trusted_duplicate_cases

    handoff = {
        "feature_point_consumption": [
            {"fp_id": "FP-001", "source_id": "SRC-001", "result": "covered_by_case", "case_ids": ["TC-001"]},
            {"fp_id": "FP-002", "source_id": "SRC-001", "result": "covered_by_case", "case_ids": ["TC-002"]},
        ],
        "testcases": [
            {
                "case_id": "TC-001",
                "source_id": "SRC-001",
                "fp_id": "FP-001",
                "title": "保存成功",
                "category": "functional",
                "steps": [{"step_no": 1, "action": "点击保存"}],
                "expected_results": ["保存成功"],
                "traceability": {"function_points": ["FP-001"], "source_id": "SRC-001"},
            },
            {
                "case_id": "TC-002",
                "source_id": "SRC-001",
                "fp_id": "FP-002",
                "title": "保存成功",
                "category": "functional",
                "steps": [{"step_no": 1, "action": "点击保存"}],
                "expected_results": ["保存成功"],
                "traceability": {"function_points": ["FP-002"], "source_id": "SRC-001"},
            },
        ],
    }

    result = _merge_trusted_duplicate_cases(handoff)
    assert len(result["testcases"]) == 1
    assert result["duplicate_case_count"] == 1
    assert result["feature_point_consumption"][1]["case_ids"] == ["TC-001"]
    assert result["feature_point_consumption"][1]["result"] == "merged_into_case"
    assert set(result["testcases"][0]["traceability"]["function_points"]) == {"FP-001", "FP-002"}


def test_case_generation_v2_finalizes_failed_shards_without_dropping_partial_results() -> None:
    from app.tasks.case_generation_v2 import _finalize_trusted_testcase_shards

    result = _finalize_trusted_testcase_shards(
        [
            {
                "source_id": "SRC-001",
                "status": "success",
                "feature_point_consumption": [
                    {"fp_id": "FP-001", "source_id": "SRC-001", "result": "covered_by_case", "case_ids": ["A-1"]}
                ],
                "testcases": [{"case_id": "A-1", "source_id": "SRC-001", "fp_id": "FP-001"}],
            },
            {
                "source_id": "SRC-002",
                "status": "failed",
                "error": "HTTP 429",
                "feature_point_consumption": [],
                "testcases": [],
            },
        ]
    )

    assert result["testcases"][0]["case_id"] == "TC-001"
    assert result["shard_failures"] == [{"source_id": "SRC-002", "error": "HTTP 429"}]
    assert result["testcase_shards"][1]["status"] == "failed"


def test_case_generation_v2_replaces_single_source_shard_and_rebuilds_summary() -> None:
    from app.tasks.case_generation_v2 import _replace_trusted_testcase_shard

    original = {
        "testcase_shards": [
            {
                "source_id": "SRC-001",
                "status": "success",
                "feature_point_consumption": [
                    {"fp_id": "FP-001", "source_id": "SRC-001", "result": "covered_by_case", "case_ids": ["A-1"]}
                ],
                "testcases": [{"case_id": "A-1", "source_id": "SRC-001", "fp_id": "FP-001"}],
            },
            {"source_id": "SRC-002", "status": "failed", "error": "HTTP 429", "feature_point_consumption": [], "testcases": []},
        ]
    }
    replacement = {
        "source_id": "SRC-002",
        "status": "success",
        "feature_point_consumption": [
            {"fp_id": "FP-002", "source_id": "SRC-002", "result": "covered_by_case", "case_ids": ["B-1"]}
        ],
        "testcases": [{"case_id": "B-1", "source_id": "SRC-002", "fp_id": "FP-002"}],
    }

    result = _replace_trusted_testcase_shard(original, replacement)

    assert result["shard_failures"] == []
    assert [case["case_id"] for case in result["testcases"]] == ["TC-001", "TC-002"]
    assert result["feature_point_consumption"][1]["case_ids"] == ["TC-002"]


def test_case_generation_v2_reuses_valid_source_shard_on_full_rerun(monkeypatch) -> None:
    import app.tasks.case_generation_v2 as v2

    async def fail_if_model_called(*args, **kwargs):
        raise AssertionError("valid existing shard should be reused")

    monkeypatch.setattr(v2, "_build_trusted_testcase_source_shard_async", fail_if_model_called)

    scope_index = _trusted_scope_fixture(("SRC-001",))
    requirement_handoff = {
        "function_points": [
            {
                "fp_id": "FP-001",
                "source_id": "SRC-001",
                "title": "登录",
                "rules": ["支持用户名密码登录"],
                "test_hints": ["验证登录成功"],
            }
        ]
    }
    existing_handoff = {
        "testcase_shards": [
            {
                "source_id": "SRC-001",
                "status": "success",
                "feature_point_consumption": [
                    {"fp_id": "FP-001", "source_id": "SRC-001", "result": "covered_by_case", "case_ids": ["TC-009"]}
                ],
                "method_consumption": _trusted_method_consumption("SRC-001", ["TC-009"]),
                "testcases": [
                    {
                        "case_id": "TC-009",
                        "source_id": "SRC-001",
                        "fp_id": "FP-001",
                            "fp_ids": ["FP-001"],
                            "title": "登录成功",
                            "steps": [{"step_no": 1, "action": "提交有效用户名和密码"}],
                            "expected_results": ["页面显示登录成功状态"],
                            "evidence_refs": ["2.1 登录"],
                            "design_method": "equivalence",
                            "scenario_dimensions": ["positive"],
                            "must_cover_refs": ["登录"],
                        }
                ],
            }
        ]
    }
    monkeypatch.setattr(v2, "_unified_rules_sha256", lambda: "rules-sha")
    from app.tasks.case_generation_v2_support.cache import build_shard_cache_metadata

    existing_handoff["testcase_shards"][0]["cache_metadata"] = build_shard_cache_metadata(
        v2._trusted_scope_source_items(scope_index)[0],
        requirement_handoff["function_points"],
        rules_sha256="rules-sha",
        model="test-model",
        generation_contract_version=v2._TRUSTED_GENERATION_CONTRACT_VERSION,
        generation_density="balanced",
    )
    progress_messages: list[str] = []

    result = v2._build_trusted_testcase_handoff(
        scope_index,
        requirement_handoff,
        api_key="sk-test",
        model="test-model",
        base_url="http://example.invalid/v1",
        progress_callback=progress_messages.append,
        existing_testcase_handoff=existing_handoff,
    )

    assert result["shard_progress_summary"]["reused_count"] == 1
    assert result["testcase_shards"][0]["reused_from_previous_run"] is True
    assert result["testcases"][0]["case_id"] == "TC-001"
    assert any("复用 SRC-001" in item for item in progress_messages)


def test_case_generation_v2_converts_lite_package_to_trusted_handoff() -> None:
    import app.tasks.case_generation_v2 as v2

    scope_index = _trusted_scope_fixture(("SRC-001",), method="equivalence", must_cover="登录")
    requirement_handoff = {
        "function_points": [
            {
                "fp_id": "FP-001",
                "source_id": "SRC-001",
                "shard_id": "SHARD-SRC-001",
                "title": "登录",
                "source_refs": ["2.1 登录"],
            }
        ],
        "pending_confirmations": [],
    }
    lite_package = {
        "testcases": [
            {
                "case_id": "TC-001-001",
                "fp_id": "FP-001",
                "title": "用户名密码登录成功",
                "category": "functional",
                "priority": "P1",
                "steps": [{"step_no": 1, "action": "打开登录页"}, {"step_no": 2, "action": "输入有效账号密码并提交"}],
                "expected_results": ["登录成功并进入首页"],
                "generation_basis": {"method": "equivalence", "rationale": "有效等价类"},
                "traceability": {"function_points": ["FP-001"], "sources": ["2.1 登录"]},
            }
        ]
    }

    handoff = v2._build_trusted_testcase_handoff_from_lite_package(scope_index, requirement_handoff, lite_package)
    gate = v2._validate_trusted_testcase_handoff(scope_index, requirement_handoff, handoff)

    assert handoff["generation_strategy"] == "lite_review"
    assert handoff["testcases"][0]["source_id"] == "SRC-001"
    assert handoff["feature_point_consumption"][0]["case_ids"] == ["TC-001"]
    assert handoff["method_consumption"][0]["method"] == "equivalence"
    assert gate["passed"] is True


def test_case_generation_v2_lite_conversion_removes_cross_source_fp_ids_without_claiming_semantic_pass() -> None:
    import app.tasks.case_generation_v2 as v2

    scope_index = _trusted_scope_fixture(("SRC-001", "SRC-002"), method="equivalence", must_cover="核心路径")
    requirement_handoff = {
        "function_points": [
            {"fp_id": "FP-001", "source_id": "SRC-001", "shard_id": "SHARD-SRC-001", "title": "来源一"},
            {"fp_id": "FP-002", "source_id": "SRC-002", "shard_id": "SHARD-SRC-002", "title": "来源二"},
        ],
        "pending_confirmations": [],
    }
    lite_package = {
        "testcases": [
            {
                "case_id": "TC-001",
                "fp_id": "FP-001",
                "fp_ids": ["FP-001", "FP-002"],
                "title": "来源一用例",
                "steps": [{"step_no": 1, "action": "执行来源一操作"}],
                "expected_results": ["来源一结果正确"],
                "traceability": {"function_points": ["FP-001", "FP-002"], "sources": ["SRC-002"]},
            },
            {
                "case_id": "TC-002",
                "fp_id": "FP-002",
                "fp_ids": ["FP-002"],
                "title": "来源二用例",
                "steps": [{"step_no": 1, "action": "执行来源二操作"}],
                "expected_results": ["来源二结果正确"],
            },
        ]
    }

    handoff = v2._build_trusted_testcase_handoff_from_lite_package(scope_index, requirement_handoff, lite_package)
    first_case = handoff["testcases"][0]
    gate = v2._validate_trusted_testcase_handoff(scope_index, requirement_handoff, handoff)

    assert first_case["fp_ids"] == ["FP-001"]
    assert first_case["traceability"]["function_points"] == ["FP-001"]
    assert "SRC-001" in first_case["traceability"]["sources"]
    assert first_case["normalization_notes"][0]["code"] == "CROSS_SOURCE_FP_IDS_REMOVED"
    assert gate["passed"] is False
    assert any(item["code"] == "MUST_COVER_NOT_COVERED" for item in gate["issues"])


def test_case_generation_v2_compacts_list_test_hints_from_trusted_requirement() -> None:
    import app.tasks.case_generation_v2 as v2
    import app.tasks.case_generation as original

    compacted = v2._compact_function_points_for_ai(
        [
            {
                "fp_id": "FP-001",
                "title": "登录",
                "rules": ["支持有效账号登录"],
                "test_hints": ["有效账号登录成功", "密码错误提示", "账号为空校验"],
            }
        ]
    )

    assert compacted[0]["test_hints"]["positive"] == ["有效账号登录成功", "密码错误提示", "账号为空校验"]
    assert compacted[0]["test_hints"]["boundary"] == []

    original_compacted = original._compact_function_points_for_ai(
        [
            {
                "fp_id": "FP-001",
                "title": "登录",
                "rules": ["支持有效账号登录"],
                "test_hints": ["有效账号登录成功", "密码错误提示", "账号为空校验"],
            }
        ]
    )
    assert original_compacted[0]["test_hints"]["positive"] == ["有效账号登录成功", "密码错误提示", "账号为空校验"]


def test_case_generation_v2_trusted_standard_views_support_quality_and_xmind() -> None:
    from app.tasks.case_generation_v2 import (
        _build_case_generation_quality_summary,
        _build_trusted_review_report,
        _build_xmindmark,
        _trusted_standard_function_points,
        _trusted_standard_testcase_package,
    )

    class Job:
        source_document_name = "需求.md"
        name = "可信任务"

    scope_index = _trusted_scope_fixture(("SRC-001",), must_cover="登录模块")
    scope_index["source_blocks"][0]["module"] = "账户体系"
    scope_index["source_blocks"][0]["scene"] = "登录"
    scope_index["source_blocks"][0]["title_path"] = "2.1 登录模块"
    scope_index["source_blocks"][0]["xmind_source_node"] = "SRC-001｜2.1 登录模块"
    scope_index["shards"][0]["module"] = "账户体系"
    scope_index["shards"][0]["scene"] = "登录"
    scope_index["shards"][0]["title_path"] = "2.1 登录模块"
    scope_index["shards"][0]["xmind_source_node"] = "SRC-001｜2.1 登录模块"
    requirement_handoff = {
        "function_points": [
            {
                "fp_id": "FP-001",
                "source_id": "SRC-001",
                "source_title": "登录",
                "title": "用户名密码登录",
                "description": "支持用户名密码登录",
                "rules": ["输入正确用户名和密码后登录成功"],
            },
            {
                "fp_id": "FP-002",
                "source_id": "SRC-001",
                "source_title": "登录",
                "title": "首次登录验证码",
                "description": "首次登录需要验证码",
                "rules": ["首次登录需要验证码"],
            },
        ],
        "pending_confirmations": [],
    }
    testcase_handoff = {
        "testcases": [
            {
                "case_id": "TC-001",
                "source_id": "SRC-001",
                "shard_id": "SHARD-001",
                "fp_id": "FP-001",
                "fp_ids": ["FP-001", "FP-002"],
                "module": "不应保留",
                "scene": "不应保留",
                "source_order": "不应保留",
                "title": "用户名密码登录成功",
                "category": "functional",
                "priority": "P0",
                "steps": [{"step_no": 1, "action": "输入正确用户名和密码并点击登录"}],
                "expected_results": ["登录成功"],
            }
        ],
        "feature_point_consumption": [
            {"fp_id": "FP-001", "source_id": "SRC-001", "result": "covered_by_case", "case_ids": ["TC-001"]},
            {"fp_id": "FP-002", "source_id": "SRC-001", "result": "covered_by_case", "case_ids": ["TC-001"]},
        ],
        "method_consumption": _trusted_method_consumption("SRC-001"),
    }
    function_points = _trusted_standard_function_points(scope_index, requirement_handoff)
    testcase_package = _trusted_standard_testcase_package(requirement_handoff, testcase_handoff)
    quality = _build_case_generation_quality_summary(function_points, testcase_package)
    review = _build_trusted_review_report(
        scope_index,
        requirement_handoff,
        testcase_handoff,
        {"passed": True, "issues": []},
        {"passed": True, "issues": []},
        {"passed": True, "issues": [], "covered_fp_count": 2, "covered_source_count": 1, "source_case_count": {"SRC-001": 1}},
        semantic_review={"summary": {"release_readiness": "conditional_pass", "ambiguous_step_count": 1, "unverifiable_expectation_count": 1, "duplicate_count": 0, "overall_score": 70}, "method_coverage": {"equivalence": "covered"}, "dimension_matrix": {}, "findings": []},
        quality_summary=quality,
    )
    xmindmark = _build_xmindmark(Job(), function_points, testcase_package, {
        "summary": {"source_count": 1, "function_point_count": 2, "testcase_count": 1},
        "review_conclusion": "通过",
        "quality_summary": quality,
        "pending_confirmations": [
            {"id": "PC-001", "topic": "Tooltip 触发方式", "description": "需要确认使用悬浮还是点击触发"},
            {"id": "PC-002", "question": "名称包含冒号时是否需要转义？", "impact": "影响解析正确性"},
            {"pending_id": "PC-003", "message": "旧结构仍应正常导出"},
        ],
    })

    assert function_points["function_points"][0]["module"] == "账户体系"
    assert function_points["function_points"][0]["scene"] == "登录"
    assert function_points["function_points"][0]["source_node_title"] == "SRC-001｜2.1 登录模块"
    assert testcase_package["xmind_grouping_contract"]["required_tree"] == "模块 -> 场景 -> SRC -> FP -> TC"
    assert testcase_package["testcases"][0]["shard_id"] == "SHARD-001"
    assert testcase_package["testcases"][0]["fp_ids"] == ["FP-001", "FP-002"]
    assert "module" not in testcase_package["testcases"][0]
    assert "scene" not in testcase_package["testcases"][0]
    assert "source_order" not in testcase_package["testcases"][0]
    assert testcase_package["testcases"][0]["generation_basis"]["method"] == "equivalence"
    assert review["summary"]["weak_expected_count"] == 0
    assert review["summary"]["ambiguous_step_count"] == 1
    assert review["summary"]["source_count"] == 1
    assert review["summary"]["function_point_consumption_rate"] == 1
    assert review["standard_review_report"]["summary"]["release_readiness"] == "conditional_pass"
    assert review["method_coverage"]["equivalence"] == "covered"
    assert review["gates"][2]["source_case_count"] == {"SRC-001": 1}
    assert review["sources_detail"][0]["source_id"] == "SRC-001"
    assert "需求测试用例" in xmindmark
    assert "  - 直接测试对象数：1" in xmindmark
    assert "  - 用例总数：1" in xmindmark
    assert "  - 待确认项数量：3" in xmindmark
    assert "    - PC-001：Tooltip 触发方式：需要确认使用悬浮还是点击触发" in xmindmark
    assert "    - PC-002：名称包含冒号时是否需要转义？" in xmindmark
    assert "    - PC-003：旧结构仍应正常导出" in xmindmark
    assert "\n    - -\n" not in xmindmark
    assert "    - SRC-001｜2.1 登录模块" in xmindmark
    assert "      - FP-001：用户名密码登录" in xmindmark
    assert "      - FP-002：首次登录验证码" in xmindmark
    assert xmindmark.count("        - TC-001-用户名密码登录成功") == 1
    assert "合并覆盖：该功能点由同源已展开用例覆盖" in xmindmark
    assert "弱预期数量" in xmindmark


def test_case_generation_v2_final_delivery_gate_validates_artifacts(tmp_path, monkeypatch) -> None:
    import app.tasks.case_generation_v2 as v2
    from app.tasks.case_generation_common import write_xmind_archive

    xmind_path = tmp_path / "trusted.xmind"
    valid_xmindmark = "\n".join(
        [
            "需求测试用例",
            "- 模块：登录",
            "  - 场景：登录",
            "    - SRC-001｜登录",
            "      - FP-001：用户名密码登录",
            "        - TC-001-登录成功",
            "      - FP-002：未覆盖功能点",
            "        - TC-001-登录成功",
        ]
    )
    testcase_package = {
        "xmind_grouping_contract": {"required_tree": "模块 -> 场景 -> SRC -> FP -> TC"},
        "testcases": [{"case_id": "TC-001", "source_id": "SRC-001", "shard_id": "SHARD-001", "fp_id": "FP-001", "fp_ids": ["FP-001", "FP-002"]}],
    }
    review_report = {"summary": {
        "source_count": 1,
        "function_point_count": 2,
        "testcase_count": 1,
        "semantic_release_readiness": "pass",
        "must_cover_gap_count": 0,
        "evidence_coverage_rate": 1.0,
        "weak_expected_count": 0,
        "weak_step_count": 0,
    }}
    write_xmind_archive(str(xmind_path), valid_xmindmark)

    records = {
        "xmindmark": SimpleNamespace(content_json={"text": valid_xmindmark}, file_path=str(tmp_path / "trusted.xmindmark")),
        "xmind": SimpleNamespace(content_json=None, file_path=str(xmind_path)),
        "scope_index": SimpleNamespace(content_json={"direct_testcase_sources": [{"source_id": "SRC-001"}]}, file_path=None),
        "function_points": SimpleNamespace(content_json={"function_points": [{"fp_id": "FP-001", "source_id": "SRC-001"}, {"fp_id": "FP-002", "source_id": "SRC-001"}]}, file_path=None),
    }
    monkeypatch.setattr(v2, "_trusted_artifact_record", lambda db, job_id, artifact_type: records.get(artifact_type))
    gate = v2._build_final_delivery_gate(None, 1, testcase_package, review_report)
    assert gate["passed"] is True
    assert gate["xmindmark_testcase_count"] == 1
    assert gate["xmindmark_function_point_count"] == 2

    conditional_report = json.loads(json.dumps(review_report))
    conditional_report["summary"]["semantic_release_readiness"] = "conditional_pass"
    gate = v2._build_final_delivery_gate(None, 1, testcase_package, conditional_report)
    assert gate["passed"] is True
    assert gate["status"] == "warning"
    assert any(item["code"] == "SEMANTIC_REVIEW_CONDITIONAL" for item in gate["issues"])

    weak_quality_report = json.loads(json.dumps(review_report))
    weak_quality_report["summary"]["weak_expected_count"] = 1
    weak_quality_report["summary"]["weak_step_count"] = 1
    gate = v2._build_final_delivery_gate(None, 1, testcase_package, weak_quality_report)
    assert gate["passed"] is True
    assert gate["status"] == "warning"
    assert {item["code"] for item in gate["issues"]} >= {
        "WEAK_EXPECTED_RATE_TOO_HIGH",
        "WEAK_STEP_RATE_TOO_HIGH",
    }
    assert all(item["severity"] == "warning" for item in gate["issues"])

    semantic_defect_report = json.loads(json.dumps(review_report))
    semantic_defect_report["summary"].update({
        "assertion_basis_rate": 1.0,
        "unsupported_assertion_count": 1,
    })
    gate = v2._build_final_delivery_gate(None, 1, testcase_package, semantic_defect_report)
    assert gate["passed"] is False
    assert "UNSUPPORTED_ASSERTIONS_REMAIN" in {item["code"] for item in gate["issues"]}

    state_semantic_defect_report = json.loads(json.dumps(review_report))
    state_semantic_defect_report["summary"]["current_state_as_expected_count"] = 1
    gate = v2._build_final_delivery_gate(None, 1, testcase_package, state_semantic_defect_report)
    assert gate["passed"] is False
    assert "CURRENT_STATE_AS_EXPECTED_REMAINS" in {item["code"] for item in gate["issues"]}

    records.pop("xmindmark")
    gate = v2._build_final_delivery_gate(None, 1, testcase_package, review_report)
    assert gate["passed"] is False
    assert {item["code"] for item in gate["issues"]} >= {"XMINDMARK_MISSING"}

    records["xmindmark"] = SimpleNamespace(content_json={"text": "需求测试用例\n\n- 模块：登录"}, file_path=None)
    gate = v2._build_final_delivery_gate(None, 1, testcase_package, review_report)
    assert "XMINDMARK_BLANK_LINE" in {item["code"] for item in gate["issues"]}

    records["xmindmark"] = SimpleNamespace(content_json={"text": "需求测试用例\n- 模块：登录\n  - TC-001-登录成功"}, file_path=None)
    gate = v2._build_final_delivery_gate(None, 1, testcase_package, review_report)
    assert "TRUSTED_SOURCE_NODE_MISSING" in {item["code"] for item in gate["issues"]}

    records["xmindmark"] = SimpleNamespace(content_json={"text": valid_xmindmark + "\n        - TC-002-重复节点"}, file_path=None)
    gate = v2._build_final_delivery_gate(None, 1, testcase_package, review_report)
    assert "TESTCASE_COUNT_MISMATCH" in {item["code"] for item in gate["issues"]}


def test_case_generation_v2_quality_summary_does_not_treat_concise_content_as_weak() -> None:
    import app.tasks.case_generation_v2 as v2

    function_points = {"function_points": [{"fp_id": "FP-001", "source_id": "SRC-001"}]}
    testcase_package = {
        "testcases": [
            {
                "case_id": "TC-001",
                "fp_ids": ["FP-001"],
                "steps": ["打开筛选菜单", "选择 Offline Ads"],
                "expected_results": ["选项列表中不再显示 Offline Ads 选项"],
                "assertion_basis": [{"expected_result": "选项列表中不再显示 Offline Ads 选项", "basis_type": "text", "basis_ref": "DOC-001", "source_quote": "移除 Offline Ads"}],
            },
            {
                "case_id": "TC-002",
                "fp_ids": ["FP-001"],
                "steps": ["进入对应页面"],
                "expected_results": ["系统正常"],
            },
        ]
    }

    summary = v2._build_case_generation_quality_summary(function_points, testcase_package)

    assert summary["weak_expected_count"] == 1
    assert summary["weak_step_count"] == 1
    assert summary["assertion_basis_rate"] == 0.5


def test_case_generation_v2_section_evidence_binds_images_by_document_section() -> None:
    import app.tasks.case_generation_v2 as v2

    markdown = """# 模块\n## 字段名修改\n旧字段改为新字段\n![](https://img.example/b.png)\n## 标签问题\n全选时仅显示大标签\n![](https://img.example/a.png)\n"""
    image_links = v2._extract_image_links(markdown)
    assert image_links == ["https://img.example/a.png", "https://img.example/b.png"]

    catalog = v2._section_evidence_catalog(markdown, image_links)

    field_section = next(item for item in catalog if item["title"] == "字段名修改")
    label_section = next(item for item in catalog if item["title"] == "标签问题")
    assert field_section["image_refs"] == ["IMG-002"]
    assert label_section["image_refs"] == ["IMG-001"]
    assert label_section["title_path"] == "模块/标签问题"


def test_case_generation_v2_requirement_gate_requires_exact_source_quotes() -> None:
    import app.tasks.case_generation_v2 as v2

    scope = _trusted_scope_fixture(("SRC-001",), must_cover="收起菜单可见性")
    scope["source_blocks"][0].update({
        "source_doc_id": "DOC-001",
        "source_excerpt": "现有效果位于底部靠左，希望提高可见性。",
        "source_content_sha256": "sha",
        "evidence_refs": ["DOC-001"],
    })
    scope["shards"][0].update(scope["source_blocks"][0])
    scope["section_evidence_catalog"] = []
    handoff = {
        "scope_index_consumption": [{"source_id": "SRC-001", "result": "converted_to_function_points", "fp_ids": ["FP-001"]}],
        "function_points": [{"fp_id": "FP-001", "source_id": "SRC-001", "source_quotes": ["增加按钮边框"]}],
    }

    normalized = v2._normalize_trusted_requirement_handoff(scope, handoff)
    gate = v2._validate_trusted_requirement_handoff(scope, normalized)

    assert gate["passed"] is False
    assert "FP_SOURCE_QUOTE_NOT_FOUND" in {item["code"] for item in gate["issues"]}


def test_case_generation_v2_requirement_quotes_restore_exact_source_punctuation() -> None:
    import app.tasks.case_generation_v2 as v2

    scope = _trusted_scope_fixture(("SRC-001",), must_cover="状态文案")
    source = {
        "source_doc_id": "DOC-001",
        "source_excerpt": "状态设置为“测试”，系统将提供更多优势。",
        "source_content_sha256": "sha",
        "evidence_refs": ["DOC-001"],
    }
    scope["source_blocks"][0].update(source)
    scope["shards"][0].update(source)
    scope["section_evidence_catalog"] = []
    handoff = {
        "scope_index_consumption": [
            {"source_id": "SRC-001", "result": "converted_to_function_points", "fp_ids": ["FP-001"]}
        ],
        "function_points": [
            {"fp_id": "FP-001", "source_id": "SRC-001", "source_quotes": ['状态设置为"测试"，系统将提供更多优势。']}
        ],
    }

    normalized = v2._normalize_trusted_requirement_handoff(scope, handoff)
    gate = v2._validate_trusted_requirement_handoff(scope, normalized)

    assert normalized["function_points"][0]["source_quotes"] == ["状态设置为“测试”，系统将提供更多优势。"]
    assert gate["passed"] is True


def test_case_generation_v2_source_shard_contract_enforces_evidence_data_and_baseline() -> None:
    import app.tasks.case_generation_v2 as v2

    source = {
        "source_id": "SRC-001",
        "shard_id": "SHARD-001",
        "source_doc_id": "DOC-001",
        "source_excerpt": "上传 111x111 图片时显示尺寸警告。",
        "image_refs": [],
        "evidence_refs": ["DOC-001"],
        "test_design_profile": {"must_cover": ["111x111尺寸警告"], "applicable_methods": ["boundary_value"]},
    }
    function_points = [{"fp_id": "FP-001", "source_id": "SRC-001"}]
    shard = {
        "feature_point_consumption": [{"fp_id": "FP-001", "source_id": "SRC-001", "result": "covered_by_case", "case_refs": ["TC-001"]}],
        "method_consumption": [{"source_id": "SRC-001", "method": "boundary_value", "result": "covered_by_case", "case_refs": ["TC-001"]}],
        "testcases": [{
            "case_id": "TC-001",
            "source_id": "SRC-001",
            "shard_id": "SHARD-001",
            "fp_id": "FP-001",
            "fp_ids": ["FP-001"],
            "design_method": "boundary_value",
            "steps": [{"step_no": 1, "action": "上传 111x111 图片"}],
            "expected_results": ["显示尺寸警告"],
            "must_cover_refs": ["111x111尺寸警告"],
            "assertion_basis": [{"expected_result": "显示尺寸警告", "basis_type": "text", "basis_ref": "DOC-001", "source_quote": "上传 111x111 图片时显示尺寸警告。"}],
            "test_data": [{"name": "图片尺寸", "value": "111x111"}],
            "baseline_candidate": True,
        }],
    }

    v2._validate_trusted_source_shard_contract(source, function_points, shard)
    shard["testcases"][0]["test_data"] = []
    try:
        v2._validate_trusted_source_shard_contract(source, function_points, shard)
    except v2.ModelContractError as exc:
        assert "test_data" in str(exc)
    else:
        raise AssertionError("boundary source shard without test data should fail")


def test_case_generation_v2_test_data_requirement_distinguishes_navigation_from_business_data() -> None:
    import app.tasks.case_generation_v2 as v2

    assert v2._case_requires_executable_test_data({
        "design_method": "ui_display",
        "steps": [{"step_no": 1, "action": "选择 Ad Set Tab，检查字段是否隐藏"}],
    }) is False
    assert v2._case_requires_executable_test_data({
        "design_method": "equivalence",
        "steps": [{"step_no": 1, "action": "选择 Country 值"}],
    }) is True
    assert v2._case_requires_executable_test_data({
        "design_method": "equivalence",
        "category": "ui",
        "steps": [{"step_no": 1, "action": "进入 Ad Set 页面，检查字段名称"}],
    }) is False
    assert v2._case_requires_executable_test_data({
        "design_method": "equivalence",
        "category": "ui",
        "steps": [{"step_no": 1, "action": "进入 Campaign 页面，查看筛选栏字段"}],
    }) is False
    assert v2._case_requires_executable_test_data({
        "design_method": "ui_display",
        "steps": [{"step_no": 1, "action": "在 Country 输入框中搜索 US"}],
    }) is True


def test_case_generation_v2_binds_current_and_target_evidence_roles() -> None:
    import app.tasks.case_generation_v2 as v2

    old_url = "https://example.test/old.png"
    new_url = "https://example.test/new.png"
    catalog = v2._section_evidence_catalog(
        "# 菜单优化\n+ 现有效果：按钮位于左下\n![](https://example.test/old.png)\n+ 优化效果\n![](https://example.test/new.png)",
        [old_url, new_url],
        [
            {"image_id": "IMG-001", "summary": "按钮位于左下"},
            {"image_id": "IMG-002", "summary": "按钮位于底部中央"},
        ],
    )

    section = catalog[0]
    semantics = section["source_state_semantics"]
    assert semantics["has_state_transition"] is True
    assert semantics["current_image_refs"] == ["IMG-001"]
    assert semantics["target_image_refs"] == ["IMG-002"]
    assert [item["evidence_role"] for item in section["image_evidence"]] == ["current", "target"]

    updated_copy_catalog = v2._section_evidence_catalog(
        "# Tooltip\n- Type 字段（更新旧版内容）\n- Tooltip 展示新的 Default / Splash 说明",
        [],
        [],
    )
    updated_copy_semantics = updated_copy_catalog[0]["source_state_semantics"]
    assert "Tooltip 展示新的 Default / Splash 说明" in updated_copy_semantics["target_text"]
    assert "Tooltip 展示新的 Default / Splash 说明" not in updated_copy_semantics["current_text"]


def test_case_generation_v2_requirement_gate_rejects_current_only_target_claim() -> None:
    import app.tasks.case_generation_v2 as v2

    scope = _trusted_scope_fixture(("SRC-001",), method="ui_display", must_cover="菜单优化")
    scope = v2._attach_scope_evidence(
        scope,
        "# 菜单优化\n+ 现有效果：按钮位于左下\n![](https://example.test/old.png)\n+ 优化效果\n![](https://example.test/new.png)",
        ["https://example.test/old.png", "https://example.test/new.png"],
        [
            {"image_id": "IMG-001", "summary": "按钮位于左下"},
            {"image_id": "IMG-002", "summary": "按钮位于底部中央"},
        ],
    )
    requirement = v2._normalize_trusted_requirement_handoff(scope, {
        "scope_index_consumption": [{"source_id": "SRC-001", "result": "converted_to_function_points", "fp_ids": ["FP-001"]}],
        "function_points": [{
            "fp_id": "FP-001",
            "source_id": "SRC-001",
            "title": "菜单位置",
            "description": "菜单位于左下",
            "rules": ["菜单位于左下"],
            "source_quotes": ["现有效果：按钮位于左下", "优化效果"],
            "target_evidence_refs": [],
        }],
        "pending_confirmations": [],
    })

    gate = v2._validate_trusted_requirement_handoff(scope, requirement)
    assert gate["passed"] is False
    assert "FP_TARGET_EVIDENCE_MISSING" in {item["code"] for item in gate["issues"]}

    requirement["function_points"][0]["target_evidence_refs"] = ["IMG-002"]
    gate = v2._validate_trusted_requirement_handoff(scope, requirement)
    assert gate["passed"] is False
    assert "FP_CURRENT_STATE_CONTRADICTS_TARGET" in {item["code"] for item in gate["issues"]}
    assert v2._source_requirement_needs_state_repair(
        v2._source_by_id(scope, "SRC-001"),
        requirement["function_points"],
    ) is True


def test_case_generation_v2_requirement_gate_accepts_mixed_quote_with_full_target_text() -> None:
    import app.tasks.case_generation_v2 as v2

    current_text = "目前交互方式：按钮关闭时会清空历史限制值"
    target_text = "优化后的交互方式：按钮关闭时不修改限制，保存其他修改且不弹出二次确认框"
    mixed_quote = f"{current_text}\n{target_text}"
    scope = _trusted_scope_fixture(("SRC-001",), method="decision_table", must_cover="系统版本限制开关")
    source_evidence = {
        "source_doc_id": "DOC-001",
        "source_excerpt": mixed_quote,
        "source_content_sha256": "sha",
        "evidence_refs": ["DOC-001"],
        "source_state_semantics": {
            "has_state_transition": True,
            "current_text": current_text,
            "target_text": target_text,
            "current_image_refs": [],
            "target_image_refs": [],
            "image_role_by_id": {},
        },
    }
    scope["source_blocks"][0].update(source_evidence)
    scope["shards"][0].update(source_evidence)
    requirement = v2._normalize_trusted_requirement_handoff(scope, {
        "scope_index_consumption": [{
            "source_id": "SRC-001",
            "result": "converted_to_function_points",
            "fp_ids": ["FP-028"],
        }],
        "function_points": [{
            "fp_id": "FP-028",
            "source_id": "SRC-001",
            "title": "系统版本限制开关交互优化",
            "description": target_text,
            "rules": ["按钮关闭时保存其他修改且不弹出二次确认框"],
            "test_hints": ["验证关闭分支"],
            "source_quotes": [mixed_quote],
            "target_evidence_refs": [],
        }],
        "pending_confirmations": [],
    })

    source = v2._source_by_id(scope, "SRC-001")
    gate = v2._validate_trusted_requirement_handoff(scope, requirement)

    assert v2._source_evidence_role(source, basis_type="text", source_quote=mixed_quote) == "unspecified"
    assert v2._source_quote_contains_target_evidence(source, mixed_quote) is True
    assert gate["passed"] is True
    assert "FP_TARGET_EVIDENCE_MISSING" not in {item["code"] for item in gate["issues"]}

    requirement["function_points"][0]["source_quotes"] = [current_text]
    gate = v2._validate_trusted_requirement_handoff(scope, requirement)
    assert gate["passed"] is False
    assert "FP_TARGET_EVIDENCE_MISSING" in {item["code"] for item in gate["issues"]}


def test_case_generation_v2_state_repair_converges_old_position_to_target_evidence() -> None:
    import app.tasks.case_generation_v2 as v2

    source = {
        "source_id": "SRC-007",
        "title": "新建时 More 菜单可见性优化",
        "source_state_semantics": {
            "has_state_transition": True,
            "current_text": "现有效果：More 按钮位置底部靠左",
            "target_text": "优化效果",
            "current_image_refs": ["IMG-014"],
            "target_image_refs": ["IMG-015"],
        },
        "image_evidence": [
            {"image_id": "IMG-014", "evidence_role": "current", "summary": "More 按钮位于底部靠左"},
            {"image_id": "IMG-015", "evidence_role": "target", "summary": "More 按钮位于底部中央位置"},
        ],
    }
    raw = {
        "smoke_test_scope_note": "验证 More 菜单可见性",
        "test_design_profile": {"must_cover": ["More 按钮位于底部靠左"]},
        "function_points": [{
            "fp_id": "FP-021",
            "source_id": "SRC-007",
            "title": "More 菜单可见性提升",
            "description": "调整 More 菜单位置和样式",
            "rules": [
                "当前问题：More 菜单位置底部靠左",
                "目标样式以 IMG-015 为准",
            ],
            "test_hints": ["验证 More 菜单功能正常"],
            "source_quotes": ["现有效果：More 按钮位置底部靠左"],
            "target_evidence_refs": ["IMG-015"],
        }],
    }

    repaired = v2._converge_state_repair_output(source, raw)
    fp = repaired["function_points"][0]
    candidate = "\n".join([fp["title"], fp["description"], *fp["rules"], *fp["test_hints"]])

    assert all("底部靠左" not in item for item in fp["rules"])
    assert "目标行为：More 按钮位于底部中央位置" in fp["rules"]
    assert repaired["test_design_profile"]["must_cover"] == ["More 按钮位于底部中央位置"]
    assert fp["source_quotes"] == ["现有效果：More 按钮位置底部靠左"]
    assert v2._state_target_conflicts(source, candidate) == []


def test_case_generation_v2_state_repair_does_not_guess_without_target_state() -> None:
    import app.tasks.case_generation_v2 as v2

    source = {
        "source_state_semantics": {
            "has_state_transition": True,
            "current_text": "现有效果：按钮位于底部靠左",
            "target_text": "优化效果",
        },
        "image_evidence": [],
    }
    raw = {
        "function_points": [{"rules": ["按钮位于底部靠左"]}],
        "test_design_profile": {"must_cover": ["按钮位于底部靠左"]},
    }

    assert v2._converge_state_repair_output(source, raw) == raw


def test_case_generation_v2_allows_retained_current_behavior_only_for_partial_selection() -> None:
    import app.tasks.case_generation_v2 as v2

    source = {
        "source_state_semantics": {
            "has_state_transition": True,
            "current_text": "无论是否全选，均展示小标签而不展示大标签",
            "target_text": "全选时自动收起小标签，仅展示所属的大标签",
        },
        "image_evidence": [],
    }
    expected = "Source intr_placement 输入框展示实际选中的小标签 tag，不展示大标签名称"
    current_quote = "无论是否全选，均展示小标签而不展示大标签"

    assert v2._current_state_expectation_is_allowed(
        source,
        expected,
        current_quote,
        "Manual Select 非全选时展示逻辑正确",
    ) is True
    assert v2._current_state_expectation_is_allowed(source, expected, current_quote) is False
    assert v2._current_state_expectation_is_allowed(
        source,
        expected,
        current_quote,
        "Manual Select 全选标签",
    ) is False


def test_case_generation_v2_full_requirement_path_converges_state_conflicts() -> None:
    import app.tasks.case_generation_v2 as v2

    scope = _trusted_scope_fixture(("SRC-007",), method="ui_display", must_cover="提升 More 菜单可见性")
    scope["source_blocks"][0].update({
        "title": "新建时 More 菜单可见性优化",
        "source_state_semantics": {
            "has_state_transition": True,
            "current_text": "现有效果：More 按钮位置底部靠左",
            "target_text": "优化效果",
            "current_image_refs": ["IMG-014"],
            "target_image_refs": ["IMG-015"],
            "image_role_by_id": {"IMG-014": "current", "IMG-015": "target"},
        },
        "image_refs": ["IMG-014", "IMG-015"],
        "image_evidence": [
            {"image_id": "IMG-014", "evidence_role": "current", "summary": "More 按钮位于底部靠左"},
            {"image_id": "IMG-015", "evidence_role": "target", "summary": "More 按钮位于底部中央"},
        ],
    })
    source = v2._source_by_id(scope, "SRC-007")
    requirement = v2._normalize_trusted_requirement_handoff(scope, {
        "scope_index_consumption": [{
            "source_id": "SRC-007",
            "result": "converted_to_function_points",
            "fp_ids": ["FP-023"],
        }],
        "function_points": [{
            "fp_id": "FP-023",
            "source_id": "SRC-007",
            "title": "More 菜单位置优化",
            "description": "提升 More 菜单可见性",
            "rules": ["More 菜单从底部靠左调整至更明显位置"],
            "test_hints": ["验证 More 菜单位置"],
            "source_quotes": ["现有效果：More 按钮位置底部靠左"],
            "target_evidence_refs": ["IMG-015"],
        }],
        "pending_confirmations": [],
    })

    repaired, source_ids = v2._converge_requirement_handoff_state_conflicts(scope, requirement)
    fp = repaired["function_points"][0]
    candidate = "\n".join([fp["title"], fp["description"], *fp["rules"], *fp["test_hints"]])

    assert source_ids == ["SRC-007"]
    assert all("底部靠左" not in rule for rule in fp["rules"])
    assert "目标行为：More 按钮位于底部中央" in fp["rules"]
    assert v2._state_target_conflicts(source, candidate) == []


def test_case_generation_v2_repairs_and_validates_pending_confirmation_fp_refs() -> None:
    import app.tasks.case_generation_v2 as v2

    scope = _trusted_scope_fixture(("SRC-001",), method="ui_display", must_cover="菜单优化")
    requirement = v2._normalize_trusted_requirement_handoff(scope, {
        "scope_index_consumption": [{
            "source_id": "SRC-001",
            "result": "converted_to_function_points",
            "fp_ids": ["FP-001"],
        }],
        "function_points": [{
            "fp_id": "FP-001",
            "source_id": "SRC-001",
            "title": "菜单优化",
            "description": "菜单优化",
            "rules": [],
            "source_quotes": [],
        }],
        "pending_confirmations": [{
            "source_id": "SRC-001",
            "related_fp_ids": ["FP-001-001"],
            "question": "确认菜单文案",
        }],
    })

    assert requirement["pending_confirmations"][0]["related_fp_ids"] == ["FP-001"]
    requirement["pending_confirmations"][0]["related_fp_ids"] = ["FP-001-001"]
    v2._repair_converted_requirement_consumption(requirement)
    assert requirement["pending_confirmations"][0]["related_fp_ids"] == ["FP-001"]
    requirement["pending_confirmations"][0]["related_fp_ids"] = ["FP-999"]
    gate = v2._validate_trusted_requirement_handoff(scope, requirement)
    assert "PENDING_UNKNOWN_FP_ID" in {item["code"] for item in gate["issues"]}


def test_case_generation_v2_source_gate_rejects_current_state_as_positive_expected() -> None:
    import app.tasks.case_generation_v2 as v2

    source = {
        "source_id": "SRC-001",
        "shard_id": "SHARD-001",
        "source_doc_id": "DOC-001",
        "source_excerpt": "+ 现有效果：按钮位于左下\n+ 优化效果",
        "image_refs": ["IMG-001", "IMG-002"],
        "image_evidence": [
            {"image_id": "IMG-001", "evidence_role": "current", "summary": "按钮位于底部靠左"},
            {"image_id": "IMG-002", "evidence_role": "target", "summary": "按钮位于底部中央"},
        ],
        "evidence_refs": ["DOC-001", "IMG-001", "IMG-002"],
        "source_state_semantics": {
            "has_state_transition": True,
            "current_text": "+ 现有效果：按钮位于左下",
            "target_text": "+ 优化效果",
            "current_image_refs": ["IMG-001"],
            "target_image_refs": ["IMG-002"],
            "image_role_by_id": {"IMG-001": "current", "IMG-002": "target"},
        },
        "test_design_profile": {"must_cover": [], "applicable_methods": []},
    }
    function_points = [{"fp_id": "FP-001", "source_id": "SRC-001"}]
    case = {
        "case_id": "TC-001",
        "source_id": "SRC-001",
        "shard_id": "SHARD-001",
        "fp_id": "FP-001",
        "fp_ids": ["FP-001"],
        "steps": [{"step_no": 1, "action": "观察菜单位置"}],
        "expected_results": ["按钮位于左下"],
        "assertion_basis": [{
            "expected_result": "按钮位于左下",
            "basis_type": "text",
            "basis_ref": "DOC-001",
            "source_quote": "按钮位于左下",
        }],
        "baseline_candidate": True,
    }
    shard = {
        "feature_point_consumption": [{"fp_id": "FP-001", "source_id": "SRC-001", "result": "covered_by_case", "case_refs": ["TC-001"]}],
        "method_consumption": [],
        "testcases": [case],
    }
    normalized = v2._normalize_trusted_testcase_handoff(shard, "SRC-001", source=source)

    try:
        v2._validate_trusted_source_shard_contract(source, function_points, normalized)
    except v2.ModelContractError as exc:
        assert "current 旧状态" in str(exc)
    else:
        raise AssertionError("positive expected result backed only by current state should fail")

    normalized["testcases"][0]["assertion_basis"][0].update({
        "basis_type": "image",
        "basis_ref": "IMG-002",
        "source_quote": "",
    })
    try:
        v2._validate_trusted_source_shard_contract(source, function_points, normalized)
    except v2.ModelContractError as exc:
        assert "与 target 证据冲突" in str(exc)
    else:
        raise AssertionError("target image reference must not authorize a contradictory expected result")

    normalized["testcases"][0]["expected_results"] = ["按钮不再位于左下"]
    normalized["testcases"][0]["assertion_basis"][0]["expected_result"] = "按钮不再位于左下"
    v2._validate_trusted_source_shard_contract(source, function_points, normalized)


def test_case_generation_v2_source_builder_repairs_current_only_assertion_basis(monkeypatch) -> None:
    import app.tasks.case_generation_v2 as v2

    source = {
        "source_id": "SRC-001",
        "shard_id": "SHARD-001",
        "source_doc_id": "DOC-001",
        "source_excerpt": "+ 现有效果：按钮为图标+文本，位于左下\n+ 优化效果",
        "image_refs": ["IMG-001", "IMG-002"],
        "image_evidence": [
            {"image_id": "IMG-001", "evidence_role": "current", "summary": "按钮位于底部靠左"},
            {"image_id": "IMG-002", "evidence_role": "target", "summary": "按钮为图标+文本，位于底部中央"},
        ],
        "evidence_refs": ["DOC-001", "IMG-001", "IMG-002"],
        "source_state_semantics": {
            "has_state_transition": True,
            "current_text": "+ 现有效果：按钮为图标+文本，位于左下",
            "target_text": "+ 优化效果",
            "current_image_refs": ["IMG-001"],
            "target_image_refs": ["IMG-002"],
            "image_role_by_id": {"IMG-001": "current", "IMG-002": "target"},
        },
        "test_design_profile": {"must_cover": [], "applicable_methods": []},
    }
    function_points = [{"fp_id": "FP-001", "source_id": "SRC-001"}]

    def shard_with_basis(basis_type: str, basis_ref: str, source_quote: str) -> dict:
        return {
            "feature_point_consumption": [{
                "fp_id": "FP-001",
                "source_id": "SRC-001",
                "consumption_result": "covered_by_case",
                "case_refs": ["TC-001"],
            }],
            "method_consumption": [],
            "testcases": [{
                "case_id": "TC-001",
                "source_id": "SRC-001",
                "shard_id": "SHARD-001",
                "fp_id": "FP-001",
                "fp_ids": ["FP-001"],
                "title": "检查按钮样式",
                "steps": [{"step_no": 1, "action": "观察按钮样式"}],
                "expected_results": ["按钮为图标+文本"],
                "assertion_basis": [{
                    "expected_result": "按钮为图标+文本",
                    "basis_type": basis_type,
                    "basis_ref": basis_ref,
                    "source_quote": source_quote,
                }],
                "baseline_candidate": True,
            }],
        }

    responses = [
        shard_with_basis("text", "DOC-001", "按钮为图标+文本"),
        shard_with_basis("image", "IMG-002", ""),
    ]
    seen_payloads: list[dict] = []

    async def fake_call(**kwargs):
        seen_payloads.append(kwargs["payload"])
        return responses[len(seen_payloads) - 1]

    monkeypatch.setattr(v2, "_call_trusted_skill_json_async", fake_call)
    result = asyncio.run(v2._build_trusted_testcase_source_shard_async(
        source,
        function_points,
        api_key="sk-test",
        model="gpt-test",
        base_url="https://example.test/v1",
    ))

    assert len(seen_payloads) == 2
    assert "current 旧状态" in seen_payloads[1]["deterministic_contract_error"]
    assert result["testcases"][0]["assertion_basis"][0]["basis_ref"] == "IMG-002"


def test_case_generation_v2_reclassifies_image_derived_text_basis_without_weakening_text_gate() -> None:
    import app.tasks.case_generation_v2 as v2

    source = {
        "source_id": "SRC-007",
        "shard_id": "SHARD-007",
        "source_doc_id": "DOC-012",
        "source_excerpt": "+ 现有效果：位置底部靠左\n+ 优化效果",
        "image_refs": ["IMG-014", "IMG-015"],
        "image_evidence": [
            {"image_id": "IMG-014", "evidence_role": "current", "summary": "More 按钮位于底部靠左"},
            {
                "image_id": "IMG-015",
                "evidence_role": "target",
                "summary": "More 按钮位于底部中央位置",
                "requirement_hints": ["与旧图相比 More 按钮位置已调整"],
            },
        ],
        "evidence_refs": ["DOC-012", "IMG-014", "IMG-015"],
        "source_state_semantics": {
            "has_state_transition": True,
            "current_text": "+ 现有效果：位置底部靠左",
            "target_text": "+ 优化效果",
            "current_image_refs": ["IMG-014"],
            "target_image_refs": ["IMG-015"],
            "image_role_by_id": {"IMG-014": "current", "IMG-015": "target"},
        },
        "test_design_profile": {"must_cover": [], "applicable_methods": []},
    }
    function_points = [{"fp_id": "FP-015", "source_id": "SRC-007"}]

    def raw_shard(claim: str) -> dict:
        return {
            "feature_point_consumption": [{
                "fp_id": "FP-015",
                "source_id": "SRC-007",
                "consumption_result": "covered_by_case",
                "case_refs": ["TC-001"],
            }],
            "method_consumption": [],
            "testcases": [{
                "case_id": "TC-001",
                "source_id": "SRC-007",
                "shard_id": "SHARD-007",
                "fp_id": "FP-015",
                "fp_ids": ["FP-015"],
                "title": "检查 More 按钮目标位置",
                "steps": [{"step_no": 1, "action": "进入页面并观察 More 按钮"}],
                "expected_results": [claim],
                "assertion_basis": [{
                    "expected_result": claim,
                    "basis_type": "text",
                    "basis_ref": "DOC-012",
                    "source_quote": claim,
                }],
                "baseline_candidate": True,
            }],
        }

    supported = v2._normalize_trusted_testcase_handoff(
        raw_shard("More按钮位置调整到底部中央"),
        "SRC-007",
        source=source,
    )
    supported_basis = supported["testcases"][0]["assertion_basis"][0]
    assert supported_basis["basis_type"] == "image"
    assert supported_basis["basis_ref"] == "IMG-015"
    assert supported_basis["evidence_role"] == "target"
    v2._validate_trusted_source_shard_contract(source, function_points, supported)

    unsupported = v2._normalize_trusted_testcase_handoff(
        raw_shard("More按钮颜色改为红色"),
        "SRC-007",
        source=source,
    )
    assert unsupported["testcases"][0]["assertion_basis"][0]["basis_type"] == "text"
    try:
        v2._validate_trusted_source_shard_contract(source, function_points, unsupported)
    except v2.ModelContractError as exc:
        assert "文本依据不在需求原文中" in str(exc)
    else:
        raise AssertionError("unsupported image claim must remain blocked")


def test_case_generation_v2_allows_explicit_retained_non_full_selection_branch() -> None:
    import app.tasks.case_generation_v2 as v2

    current_quote = "选择 Manual Select 的广告位时，无论是否全选，均展示小标签而不展示大标签"
    source = {
        "source_id": "SRC-001",
        "shard_id": "SHARD-001",
        "source_doc_id": "DOC-001",
        "source_excerpt": f"+ 问题场景：{current_quote}\n+ 正确场景：全选时自动收起小标签，仅展示所属的大标签",
        "image_refs": [],
        "source_state_semantics": {
            "has_state_transition": True,
            "current_text": f"+ 问题场景：{current_quote}",
            "target_text": "+ 正确场景：全选时自动收起小标签，仅展示所属的大标签",
            "current_image_refs": [],
            "target_image_refs": [],
            "image_role_by_id": {},
        },
        "test_design_profile": {"must_cover": [], "applicable_methods": []},
    }
    function_points = [{"fp_id": "FP-001", "source_id": "SRC-001"}]
    raw = {
        "feature_point_consumption": [{
            "fp_id": "FP-001",
            "source_id": "SRC-001",
            "consumption_result": "covered_by_case",
            "case_refs": ["TC-001"],
        }],
        "method_consumption": [],
        "testcases": [{
            "case_id": "TC-001",
            "source_id": "SRC-001",
            "shard_id": "SHARD-001",
            "fp_id": "FP-001",
            "fp_ids": ["FP-001"],
            "title": "检查非全选分支",
            "test_data": [{"name": "选择范围", "value": "Casual Games 下任意 1 个小标签"}],
            "steps": [{"step_no": 1, "action": "仅选择部分小标签"}],
            "expected_results": ["非全选时输入框展示已选的小标签名称"],
            "assertion_basis": [{
                "expected_result": "非全选时输入框展示已选的小标签名称",
                "basis_type": "text",
                "basis_ref": "DOC-001",
                "source_quote": current_quote,
            }],
            "baseline_candidate": True,
        }],
    }

    normalized = v2._normalize_trusted_testcase_handoff(raw, "SRC-001", source=source)
    v2._validate_trusted_source_shard_contract(source, function_points, normalized)


def test_case_generation_v2_normalizes_multi_method_receipts_into_cases() -> None:
    import app.tasks.case_generation_v2 as v2

    raw = {
        "feature_point_consumption": [],
        "method_consumption": [{
            "source_id": "SRC-001",
            "method": "equivalence",
            "consumption_result": "covered_by_case",
            "case_refs": ["TC-001"],
        }],
        "testcases": [{
            "case_id": "TC-001",
            "source_id": "SRC-001",
            "design_method": "ui_display",
            "steps": [],
        }],
    }

    normalized = v2._normalize_trusted_testcase_handoff(raw, "SRC-001")

    assert normalized["testcases"][0]["design_method"] == "ui_display"
    assert normalized["testcases"][0]["design_methods"] == ["ui_display", "equivalence"]


def test_case_generation_v2_localizes_persisted_global_shard_receipts() -> None:
    import app.tasks.case_generation_v2 as v2

    localized = v2._localize_trusted_shard_case_ids({
        "source_id": "SRC-004",
        "testcases": [{"case_id": "TC-001"}],
        "feature_point_consumption": [{"case_refs": ["TC-004-001"]}],
        "method_consumption": [{"case_refs": ["TC-004-001"]}],
    })

    assert localized["testcases"][0]["case_id"] == "TC-001"
    assert localized["feature_point_consumption"][0]["case_refs"] == ["TC-001"]
    assert localized["method_consumption"][0]["case_refs"] == ["TC-001"]


def test_case_generation_v2_normalizes_authoritative_shard_id_everywhere() -> None:
    import app.tasks.case_generation_v2 as v2

    normalized = v2._normalize_trusted_testcase_handoff(
        {
            "feature_point_consumption": [{"source_id": "SRC-004", "shard_id": "SHARD-SRC-004"}],
            "method_consumption": [{"source_id": "SRC-004", "shard_id": "SHARD-SRC-004"}],
            "testcases": [{"case_id": "TC-001", "source_id": "SRC-004", "shard_id": "SHARD-SRC-004"}],
        },
        "SRC-004",
        source={"source_id": "SRC-004", "shard_id": "SHARD-004"},
    )

    assert normalized["shard_id"] == "SHARD-004"
    assert normalized["feature_point_consumption"][0]["shard_id"] == "SHARD-004"
    assert normalized["method_consumption"][0]["shard_id"] == "SHARD-004"
    assert normalized["testcases"][0]["shard_id"] == "SHARD-004"


def test_case_generation_v2_semantic_review_blocks_unsupported_assertions(monkeypatch) -> None:
    import app.tasks.case_generation_v2 as v2

    async def fake_review(**kwargs):
        return {
            "summary": {"release_readiness": "conditional_pass", "overall_score": 80},
            "coverage": {"fp_covered": 1, "fp_total": 1, "uncovered_fp_ids": []},
            "method_coverage": {"ui_display": "covered"},
            "dimension_matrix": {"functional": "covered"},
            "semantic_consistency": [{"case_id": "TC-001", "source_id": "SRC-001", "status": "unsupported"}],
            "findings": [{"finding_id": "F-001", "severity": "high", "type": "unsupported_assertion", "source_id": "SRC-001", "case_id": "TC-001", "fp_id": "FP-001", "message": "需求未要求增加边框", "suggestion": "移除无依据预期"}],
            "repair_tasks": [],
        }

    monkeypatch.setattr(v2, "_call_skill_with_gate_async", fake_review)
    review = v2._build_trusted_semantic_review(
        {"image_link_count": 0, "status": "complete"},
        {"function_points": [{"fp_id": "FP-001", "source_id": "SRC-001", "source_excerpt": "提高可见性", "source_quotes": ["提高可见性"]}]},
        {"testcases": [{"case_id": "TC-001", "source_id": "SRC-001", "priority": "P1"}]},
        [],
        api_key="sk-test",
        model="test-model",
        base_url="http://example.invalid/v1",
    )

    assert review["summary"]["release_readiness"] == "fail"
    assert review["summary"]["unsupported_assertion_count"] == 1


def test_case_generation_v2_semantic_review_allows_partial_selection_current_branch(monkeypatch) -> None:
    """回归：改造只针对全选分支时，部分选中用例引用 current 图片证据不应被判为旧状态误作预期。"""
    import app.tasks.case_generation_v2 as v2

    async def fake_review(**kwargs):
        return {
            "summary": {"release_readiness": "pass", "overall_score": 90},
            "coverage": {"fp_covered": 1, "fp_total": 1, "uncovered_fp_ids": []},
            "method_coverage": {"ui_display": "covered"},
            "dimension_matrix": {"functional": "covered"},
            "semantic_consistency": [{"case_id": "TC-001", "source_id": "SRC-001", "status": "supported"}],
            # 即便模型误报，交付检测器也应按场景维度放行
            "findings": [{
                "finding_id": "F-001", "severity": "critical", "type": "current_state_as_expected",
                "source_id": "SRC-001", "case_id": "TC-001", "fp_id": "FP-001",
                "message": "旧状态被写成预期", "suggestion": "改用 target",
            }],
            "repair_tasks": [],
        }

    monkeypatch.setattr(v2, "_call_skill_with_gate_async", fake_review)
    function_points = {"function_points": [{
        "fp_id": "FP-001",
        "source_id": "SRC-001",
        "source_excerpt": "Manual Select 无论是否全选均展示小标签；全选时应收起小标签仅展示大标签",
        "source_quotes": [],
        "source_state_semantics": {
            "has_state_transition": True,
            "current_text": "选择 Manual Select 时，无论是否全选，均展示小标签而不展示大标签",
            "target_text": "全选时自动收起小标签，仅展示所属的大标签",
            "image_role_by_id": {"IMG-001": "current"},
        },
    }]}
    testcase_package = {"testcases": [{
        "case_id": "TC-001",
        "source_id": "SRC-001",
        "fp_id": "FP-001",
        "priority": "P1",
        "title": "Manual Select 部分选中时展示实际选中的小标签",
        "scenario_dimensions": ["非全选状态"],
        "expected_results": ["输入框展示实际选中的小标签，不展示大标签名称"],
        "assertion_basis": [{
            "expected_result": "输入框展示实际选中的小标签，不展示大标签名称",
            "basis_type": "image",
            "basis_ref": "IMG-001",
            "source_quote": "底部展示实际选中的小标签",
            "evidence_role": "current",
        }],
    }]}
    review = v2._build_trusted_semantic_review(
        {"image_link_count": 0, "status": "complete"},
        function_points,
        testcase_package,
        [],
        api_key="sk-test",
        model="test-model",
        base_url="http://example.invalid/v1",
    )

    assert review["summary"]["current_state_as_expected_count"] == 0
    assert review["summary"]["release_readiness"] != "fail"


def test_case_generation_v2_json_parser_prefers_final_complete_object() -> None:
    import app.tasks.case_generation_v2 as v2

    assert v2._json_from_model_text.__module__.endswith("case_generation_v2_pipeline.engine")
    parsed = v2._json_from_model_text(
        '<thinking>{"draft": true}</thinking>\n'
        '{"requirements_input_consumption": [], "feature_point_consumption": [], '
        '"method_consumption": [], "testcases": []}'
    )

    assert parsed == {
        "requirements_input_consumption": [],
        "feature_point_consumption": [],
        "method_consumption": [],
        "testcases": [],
    }


def test_case_generation_v2_reuses_stable_scope_and_requirement_only_when_contract_matches() -> None:
    import app.tasks.case_generation_v2 as v2

    scope = _trusted_scope_fixture(("SRC-001",), must_cover="登录")
    scope["generation_contract_version"] = v2._TRUSTED_GENERATION_CONTRACT_VERSION
    requirement = {
        "generation_contract_version": v2._TRUSTED_GENERATION_CONTRACT_VERSION,
        "scope_fingerprint": v2._trusted_scope_fingerprint(scope),
    }
    manifest = {"content_sha256": "doc-sha", "unified_rules_sha256": "rules-sha"}

    assert v2._can_reuse_trusted_scope_index(scope, manifest, dict(manifest), {"passed": True}) is True
    assert v2._can_reuse_trusted_requirement(requirement, scope, {"passed": True}) is True

    changed_manifest = {**manifest, "content_sha256": "changed"}
    assert v2._can_reuse_trusted_scope_index(scope, manifest, changed_manifest, {"passed": True}) is False
    scope["shards"][0]["test_design_profile"]["must_cover"] = ["登录", "验证码"]
    assert v2._can_reuse_trusted_requirement(requirement, scope, {"passed": True}) is False


def test_case_generation_v2_source_shard_cache_requires_full_fingerprint() -> None:
    from app.tasks.case_generation_v2_support.cache import build_shard_cache_metadata, shard_cache_mismatch

    source = {
        "source_id": "SRC-001",
        "source_content_sha256": "source-v1",
        "source_excerpt": "支持用户名密码登录",
        "title_path": "账户 / 登录",
        "primary_sections": ["2.1"],
        "dependency_sections": ["字段表"],
        "rule_clusters": ["登录规则"],
        "test_design_profile": {"applicable_methods": ["equivalence"], "must_cover": ["登录"]},
    }
    function_points = [{"fp_id": "FP-001", "source_id": "SRC-001", "title": "登录", "rules": ["密码必填"]}]
    base_kwargs = {
        "rules_sha256": "rules-v1",
        "model": "test-model",
        "generation_contract_version": "contract-v1",
        "generation_density": "balanced",
    }
    metadata = build_shard_cache_metadata(source, function_points, **base_kwargs)
    assert shard_cache_mismatch({"cache_metadata": metadata}, metadata) == []
    assert shard_cache_mismatch({}, metadata) == ["missing_cache_metadata"]

    changed_inputs = [
        ({**source, "source_excerpt": "支持手机号登录"}, function_points, base_kwargs),
        (source, [{**function_points[0], "rules": ["密码和验证码必填"]}], base_kwargs),
        (source, function_points, {**base_kwargs, "rules_sha256": "rules-v2"}),
        (source, function_points, {**base_kwargs, "model": "other-model"}),
        (source, function_points, {**base_kwargs, "generation_density": "exhaustive"}),
    ]
    for changed_source, changed_fps, changed_kwargs in changed_inputs:
        expected = build_shard_cache_metadata(changed_source, changed_fps, **changed_kwargs)
        assert shard_cache_mismatch({"cache_metadata": metadata}, expected)


def test_case_generation_v2_density_changes_test_design_guidance() -> None:
    from app.tasks.case_generation_v2_support.density import (
        apply_generation_density,
        reset_generation_density,
        set_generation_density,
    )

    token = set_generation_density("exhaustive")
    try:
        profile = apply_generation_density({"merge_allowed": ["旧规则"], "coverage_budget": {}})
    finally:
        reset_generation_density(token)
    assert profile["generation_density"] == "exhaustive"
    assert profile["coverage_budget"]["coverage_depth"] == "full_risk_and_method_matrix"
    assert profile["merge_allowed"] == ["仅允许语义、步骤、预期与风险完全一致的重复用例"]


def test_case_generation_v2_async_runtime_reuses_one_event_loop() -> None:
    from app.tasks.case_generation_v2_support.async_runtime import AsyncRuntime

    runtime = AsyncRuntime()

    async def loop_identity():
        return id(asyncio.get_running_loop())

    try:
        assert runtime.run(loop_identity()) == runtime.run(loop_identity())
    finally:
        runtime.close()


def test_case_generation_metrics_are_derived_from_artifacts_and_model_calls() -> None:
    from datetime import datetime, timedelta

    from app.tasks.case_generation_v2_support.metrics import build_generation_metrics, compare_generation_metrics

    started = datetime(2026, 7, 15, 10, 0, 0)
    job = SimpleNamespace(
        id=7,
        input_payload_json={"pipeline_mode": "trusted", "generation_density": "balanced"},
        started_at=started,
        finished_at=started + timedelta(seconds=30),
    )
    attempt = SimpleNamespace(
        id=9,
        started_at=started,
        finished_at=started + timedelta(seconds=30),
        progress_json={"stages": [{"key": "scope_index", "duration_ms": 5000}]},
    )
    artifacts = [
        SimpleNamespace(id=1, artifact_type="scope_index", content_json={"direct_testcase_sources": [{"source_id": "SRC-001"}]}),
        SimpleNamespace(id=2, artifact_type="function_points", content_json={"function_points": [{"fp_id": "FP-001"}]}),
        SimpleNamespace(
            id=3,
            artifact_type="testcase_package",
            content_json={
                "testcases": [{"case_id": "TC-001"}, {"case_id": "TC-002"}],
                "source_case_summary": [{"source_id": "SRC-001", "coverage_status": "covered"}],
                "shard_progress_summary": {"reused_count": 1, "cache_invalidated_count": 2},
            },
        ),
        SimpleNamespace(
            id=4,
            artifact_type="trusted_review_report",
            content_json={
                "summary": {
                    "source_count": 1,
                    "function_point_count": 1,
                    "covered_function_point_count": 1,
                    "testcase_count": 2,
                    "duplicate_count": 1,
                    "weak_expected_count": 1,
                },
                "pending_confirmations": [{"pending_id": "PC-001"}],
            },
        ),
    ]
    metrics = build_generation_metrics(
        job=job,
        attempt=attempt,
        artifacts=artifacts,
        model_calls=[{"status": "success", "duration_ms": 1200, "usage": {"total_tokens": 800}}],
        pipeline_version="v2",
        status="CONDITIONAL",
    )
    assert metrics["duration_ms"] == 30000
    assert metrics["source_coverage_rate"] == 1.0
    assert metrics["function_point_coverage_rate"] == 1.0
    assert metrics["duplicate_rate"] == 0.5
    assert metrics["weak_expected_rate"] == 0.5
    assert metrics["total_tokens"] == 800
    assert metrics["shard_cache_invalidated_count"] == 2
    comparison = compare_generation_metrics({"testcase_count": 3}, metrics)
    assert comparison["delta"]["testcase_count"] == -1


def test_case_generation_v2_final_delivery_gate_uses_unified_validator(tmp_path, monkeypatch) -> None:
    import app.tasks.case_generation_v2 as v2

    job = SimpleNamespace(id=1, name="可信任务", source_document_name="需求.md")
    testcase_package = {"testcases": []}
    review_report = {"summary": {"source_count": 0, "function_point_count": 0, "testcase_count": 0}}
    writes = []
    persisted = []

    monkeypatch.setattr(v2, "_build_final_delivery_gate", lambda db, job_id, package, report: {"passed": True, "status": "pass", "issues": [], "blocking_issues": []})
    monkeypatch.setattr(v2, "_write_trusted_canonical_files", lambda *args, **kwargs: writes.append(args))
    monkeypatch.setattr(v2, "_persist_trusted_artifact", lambda *args, **kwargs: persisted.append(args) or str(tmp_path / "final_delivery_gate.json"))

    monkeypatch.setattr(v2, "_run_unified_trusted_validator", lambda output_dir: {"passed": True, "issues": [], "metrics": {}})
    gate = v2._run_final_delivery_gate(None, job, str(tmp_path), testcase_package, review_report)
    assert gate["passed"] is True
    assert len(writes) == 2
    assert persisted[-1][3] == "final_delivery_gate"

    def failing_validator(output_dir):
        return {
            "passed": False,
            "issues": [{"severity": "blocker", "code": "missing_xmindmark", "message": "No main .xmindmark found"}],
            "metrics": {},
        }

    monkeypatch.setattr(v2, "_run_unified_trusted_validator", failing_validator)
    try:
        v2._run_final_delivery_gate(None, job, str(tmp_path), testcase_package, review_report)
    except ValueError as exc:
        assert "No main .xmindmark found" in str(exc)
    else:
        raise AssertionError("validator failure should fail final_delivery_gate")
    failed_gate = persisted[-1][5]
    assert failed_gate["passed"] is False
    assert failed_gate["failure_code"] == "missing_xmindmark"
    assert failed_gate["failure_message"] == "No main .xmindmark found"
    assert failed_gate["return_to"] == "export"


def test_case_generation_v2_canonical_gate_report_converts_passed_warning_status() -> None:
    import app.tasks.case_generation_v2 as v2

    gate = {
        "gate": "scope_index_gate",
        "passed": True,
        "status": "warning",
        "issues": [{"severity": "warning", "code": "INFO_ONLY", "message": "提示"}],
        "blocking_issues": [],
        "warning_issues": [{"severity": "warning", "code": "INFO_ONLY", "message": "提示"}],
    }

    report = v2._canonical_gate_report_for_validator(gate)

    assert report["passed"] is True
    assert report["status"] == "pass"
    assert gate["status"] == "warning"


def test_case_generation_v2_xmind_archive_has_xmind_schema(tmp_path) -> None:
    from app.tasks.case_generation_v2 import _write_xmind_archive

    xmindmark = "\n".join(
        [
            "需求测试用例",
            "- 统计信息",
            "  - 用例总数：1",
            "- 模块：登录",
            "  - 场景：登录成功",
            "    - FP-001：用户名密码登录",
            "      - TC-001-登录成功",
            "        - 优先级：P0｜类型：功能",
            "        - 操作步骤",
            "          - 步骤1：输入账号密码并提交",
        ]
    )
    xmind_path = tmp_path / "trusted.xmind"

    _write_xmind_archive(str(xmind_path), xmindmark)

    with zipfile.ZipFile(xmind_path) as archive:
        assert sorted(archive.namelist()) == ["content.json", "manifest.json", "metadata.json"]
        content = json.loads(archive.read("content.json"))
        manifest = json.loads(archive.read("manifest.json"))
        metadata = json.loads(archive.read("metadata.json"))

    sheet = content[0]
    root = sheet["rootTopic"]
    assert manifest == {"file-entries": {"content.json": {}, "metadata.json": {}}}
    assert metadata == {
        "creator": {"name": "OmniTest deterministic exporter", "version": "1"},
        "format": "xmind-zen-json",
    }
    assert sheet["title"] == "需求测试用例"
    assert "theme" in sheet
    assert "extensions" in sheet
    assert root["title"] == "需求测试用例"
    assert root["structureClass"] == "org.xmind.ui.logic.right"
    assert root["children"]["attached"][0]["title"] == "统计信息"


def test_case_generation_image_link_extraction() -> None:
    from app.tasks.case_generation import _extract_image_links

    markdown = """
    # 需求
    ![原型](https://example.com/prototype.png)
    <img src="https://example.com/detail.jpg" />
    ![重复](https://example.com/prototype.png)
    """
    assert _extract_image_links(markdown) == [
        "https://example.com/detail.jpg",
        "https://example.com/prototype.png",
    ]


def test_case_generation_batch_image_recognition(monkeypatch) -> None:
    from app.tasks import case_generation

    state = {"count": 0, "running": 0, "max_running": 0}

    async def fake_call_openai_json_async(**kwargs):
        state["count"] += 1
        state["running"] += 1
        state["max_running"] = max(state["max_running"], state["running"])
        await asyncio.sleep(0.01)
        image_ids = [item["text"].split("图片 ID: ", 1)[1].split("，", 1)[0] for item in kwargs["user_content"] if item.get("type") == "text" and item.get("text", "").startswith("图片 ID: ")]
        if image_ids and image_ids[0] == "IMG-001":
            result = {
                "images": [
                    {"image_id": f"IMG-{i:03d}", "summary": f"batch1 img {i}", "ui_elements": [], "requirement_hints": [], "risk_or_unclear": []}
                    for i in range(1, 9)
                ]
            }
        else:
            result = {
                "images": [
                    {"image_id": f"IMG-{i:03d}", "summary": f"batch2 img {i}", "ui_elements": [], "requirement_hints": [], "risk_or_unclear": []}
                    for i in range(9, 13)
                ]
            }
        state["running"] -= 1
        return result

    monkeypatch.setattr(case_generation, "_call_openai_json_async", fake_call_openai_json_async)
    monkeypatch.setattr(case_generation, "_image_to_data_url", lambda path: "data:image/png;base64,fake")

    downloaded = []
    for i in range(1, 13):
        downloaded.append({
            "image_id": f"IMG-{i:03d}",
            "url": f"https://example.com/img{i}.png",
            "file_name": f"image_{i:02d}.png",
            "file_path": f"/tmp/images/image_{i:02d}.png",
            "download_status": "success",
        })

    results = case_generation._analyze_images("sk-test", "gpt-4.1", None, downloaded)
    assert len(results["images"]) == 12
    assert results["skipped"] == []
    assert state["count"] == 2
    assert state["max_running"] >= 2
    observed_ids = {item["image_id"] for item in results["images"]}
    for i in range(1, 13):
        assert f"IMG-{i:03d}" in observed_ids


def test_case_generation_xmindmark_stable_format() -> None:
    from app.tasks.case_generation import _validate_xmindmark

    valid = "项目测试用例\n- 统计信息\n  - 用例总数：1\n- 模块：登录\n  - 场景：登录\n"
    _validate_xmindmark(valid)

    invalid = "# 项目测试用例\n\n## 模块\n"
    try:
        _validate_xmindmark(invalid)
    except ValueError as exc:
        assert "为空行" in str(exc) or "标准列表节点" in str(exc)
    else:
        raise AssertionError("invalid xmindmark should fail")


def test_case_generation_skill_gate_rejects_invalid_output(monkeypatch) -> None:
    from app.tasks import case_generation

    calls = {"count": 0}

    def fake_call_openai_json(**kwargs):
        calls["count"] += 1
        return {"function_points": []}

    def always_fail(result):
        raise ValueError("门禁失败")

    monkeypatch.setattr(case_generation, "_call_openai_json", fake_call_openai_json)
    try:
        case_generation._call_skill_with_gate(
            api_key="sk-test",
            model="gpt-4.1",
            skill_name="requirement-analyzer",
            task_payload={"demo": True},
            output_contract="{}",
            validator=always_fail,
            max_tokens=100,
        )
    except ValueError as exc:
        assert "多次重试后仍未通过门禁" in str(exc)
    else:
        raise AssertionError("invalid skill output should fail")
    assert calls["count"] == 3


def test_case_generation_repairs_invalid_json_before_retry(monkeypatch) -> None:
    from app.tasks import case_generation

    calls = {"main": 0, "repair": 0}

    async def fake_call_openai_json_async(**kwargs):
        calls["main"] += 1
        raise case_generation.ModelJSONParseError("bad json", raw_text='{"function_points": [')

    async def fake_repair_model_json_async(**kwargs):
        calls["repair"] += 1
        return {"function_points": [{"fp_id": "FP-001"}]}

    monkeypatch.setattr(case_generation, "_call_openai_json_async", fake_call_openai_json_async)
    monkeypatch.setattr(case_generation, "_repair_model_json_async", fake_repair_model_json_async)

    result = asyncio.run(
        case_generation._call_skill_with_gate_async(
            api_key="sk-test",
            model="gpt-4.1",
            skill_name="requirement-analyzer",
            task_payload={"demo": True},
            output_contract='{"function_points":[]}',
            validator=lambda value: None,
            max_tokens=100,
        )
    )

    assert result["function_points"][0]["fp_id"] == "FP-001"
    assert calls == {"main": 1, "repair": 1}


def test_case_generation_retries_incomplete_json_before_repair(monkeypatch) -> None:
    from app.tasks import case_generation

    calls = {"main": 0, "repair": 0}
    seen_max_tokens = []

    async def fake_call_openai_json_async(**kwargs):
        calls["main"] += 1
        seen_max_tokens.append(kwargs["max_tokens"])
        if calls["main"] == 1:
            raise case_generation.ModelJSONParseError(
                "模型输出 JSON 对象不完整，可能因 max_tokens 或模型响应中断被截断",
                raw_text='{"function_points": [',
            )
        return {"function_points": [{"fp_id": "FP-002"}]}

    async def fake_repair_model_json_async(**kwargs):
        calls["repair"] += 1
        return {"function_points": [{"fp_id": "FP-REPAIR"}]}

    monkeypatch.setattr(case_generation, "_call_openai_json_async", fake_call_openai_json_async)
    monkeypatch.setattr(case_generation, "_repair_model_json_async", fake_repair_model_json_async)

    result = asyncio.run(
        case_generation._call_skill_with_gate_async(
            api_key="sk-test",
            model="gpt-4.1",
            skill_name="requirement-analyzer",
            task_payload={"demo": True},
            output_contract='{"function_points":[]}',
            validator=lambda value: None,
            max_tokens=100,
        )
    )

    assert result["function_points"][0]["fp_id"] == "FP-002"
    assert calls == {"main": 2, "repair": 0}
    assert seen_max_tokens == [100, 150]


def test_case_generation_passes_through_ai_steps_without_python_strengthening(monkeypatch) -> None:
    # Phase 1 起移除 Python 代笔强化（_build_specific_steps 等）：步骤/标题由 AI 原样输出，
    # 质量交由 prompt 约束 + quality-reviewer 把关，后端只做结构规整与字段形态对齐（Phase 3）。
    from app.tasks import case_generation

    async def fake_skill_with_gate_async(**kwargs):
        result = {
            "testcases": [
                {
                    "case_id": "TC-TEMP-001",
                    "fp_id": "FP-001",
                    "title": "正常流程验证",
                    "category": "functional",
                    "priority": "P1",
                    "preconditions": [],
                    "test_data": ["开始日期: 2026-04-01"],
                    "steps": [
                        {"step_no": 1, "action": "进入对应页面"},
                        {"step_no": 2, "action": "执行 正常流程验证"},
                    ],
                    "expected_results": ["符合预期"],
                    "traceability": {"function_points": ["FP-001"], "sources": ["text"]},
                    "generation_basis": {},
                    "scenario_dimensions": ["functional"],
                    "baseline_candidate": True,
                }
            ]
        }
        kwargs["validator"](result)
        return result

    monkeypatch.setattr(case_generation, "_call_skill_with_gate_async", fake_skill_with_gate_async)

    result = case_generation._build_testcase_package(
        {
            "function_points": [
                {
                    "fp_id": "FP-001",
                    "module": "登录模块",
                    "scene": "验证码登录",
                    "title": "验证码过期后允许重新获取并登录",
                    "description": "验证码过期后用户可重新获取验证码完成登录",
                    "source_refs": ["需求正文"],
                    "rules": ["旧验证码失效，新验证码可登录"],
                    "test_hints": {
                        "positive": ["重新获取验证码后登录成功"],
                        "boundary": ["验证码刚过期时提交"],
                        "negative": ["输入旧验证码时登录失败"],
                    },
                    "priority_hint": "P1",
                    "source_order": 1,
                }
            ]
        },
        [],
        "sk-test",
        "gpt-4.1",
    )

    case = result["testcases"][0]
    steps_text = " ".join(case_generation._step_to_text(item) for item in case["steps"])
    # 不再做 Python 强化/改写：标题与步骤按 AI 原样保留
    assert case["title"] == "正常流程验证"
    assert "进入对应页面" in steps_text
    # Phase 3 字段形态：test_data 为 [{name, value}] 对象数组，review_flags 补全
    assert case["test_data"] == [{"name": "开始日期", "value": "2026-04-01"}]
    assert case["review_flags"]["executable_risk"] in {"low", "medium", "high"}
    assert case["review_flags"]["ambiguity_risk"] in {"low", "medium", "high"}


def test_case_generation_requirement_allows_empty_intermediate_batches(monkeypatch) -> None:
    from app.tasks import case_generation

    monkeypatch.setattr(
        case_generation,
        "_build_requirement_section_batches",
        lambda sections: [[sections[0]], [sections[1]]],
    )

    async def fake_skill_with_gate_async(**kwargs):
        batch_index = kwargs["task_payload"]["batch"]["index"]
        if batch_index == 1:
            return {
                "evidence_trace": {"image_summary": "背景说明", "images": [], "pending_confirmations": []},
                "function_points": {"function_points": []},
            }
        return {
            "evidence_trace": {"image_summary": "功能说明", "images": [], "pending_confirmations": []},
            "function_points": {
                "function_points": [
                    {
                        "fp_id": "FP-TEMP-001",
                        "module": "登录模块",
                        "scene": "验证码登录",
                        "requirement_group_id": "RG-001",
                        "requirement_group_title": "登录优化",
                        "title": "验证码过期后允许重新获取并登录",
                        "type": "functional",
                        "description": "验证码过期后用户可重新获取验证码完成登录",
                        "source_refs": ["功能说明"],
                        "rules": ["旧验证码失效，新验证码可登录"],
                        "test_hints": {
                            "positive": ["重新获取验证码后登录成功"],
                            "boundary": ["验证码刚过期时提交"],
                            "negative": ["输入旧验证码时登录失败"],
                        },
                        "priority_hint": "P1",
                        "atomicity_check": "可独立验证",
                        "source_distribution": "text_only",
                        "source_order": 2,
                    }
                ]
            },
        }

    monkeypatch.setattr(case_generation, "_call_skill_with_gate_async", fake_skill_with_gate_async)

    result = case_generation._build_requirement_analysis(
        job=type("Job", (), {"source_document_name": "demo.md"})(),
            markdown_text="# 登录说明\n这里只是登录上下文\n# 功能说明\n验证码过期后需要重新获取",
        downloaded_images=[],
        image_analysis=[],
        api_key="sk-test",
        model="gpt-4.1",
    )

    fps = result["function_points"]["function_points"]
    assert len(fps) == 1
    assert fps[0]["title"] == "验证码过期后允许重新获取并登录"


def test_case_generation_gather_limited_respects_limit() -> None:
    from app.tasks import case_generation

    state = {"running": 0, "max_running": 0}

    async def unit(index: int) -> int:
        state["running"] += 1
        state["max_running"] = max(state["max_running"], state["running"])
        await asyncio.sleep(0.01)
        state["running"] -= 1
        return index

    result = asyncio.run(case_generation._gather_limited([unit(index) for index in range(8)], limit=3))

    assert result == list(range(8))
    assert state["max_running"] <= 3


def test_case_generation_update_stage_records_duration(monkeypatch) -> None:
    from app.tasks import case_generation
    from app.tasks import case_generation_runtime

    class DummyDB:
        def commit(self):
            return None

    job = type("Job", (), {"progress_json": {"stages": []}, "summary": ""})()
    db = DummyDB()
    monkeypatch.setattr(case_generation_runtime, "flag_modified", lambda *args, **kwargs: None)

    case_generation._update_stage(job, db, "collect", "收集输入", "running", "开始收集")
    case_generation._update_stage(job, db, "collect", "收集输入", "success", "收集完成")

    stage = job.progress_json["stages"][0]
    assert stage["key"] == "collect"
    assert stage["status"] == "success"
    assert "started_at" in stage
    assert "updated_at" in stage
    assert isinstance(stage.get("duration_ms"), int)


def test_case_generation_non_retryable_error_fails_fast(monkeypatch) -> None:
    from app.tasks import case_generation

    calls = {"count": 0}

    async def fake_call_openai_json_async(**kwargs):
        calls["count"] += 1
        raise RuntimeError("OpenAI 请求失败，HTTP 401：invalid_api_key")

    monkeypatch.setattr(case_generation, "_call_openai_json_async", fake_call_openai_json_async)

    try:
        asyncio.run(
            case_generation._call_skill_with_gate_async(
                api_key="sk-test",
                model="gpt-4.1",
                skill_name="requirement-analyzer",
                task_payload={"demo": True},
                output_contract='{"function_points":[]}',
                validator=lambda value: None,
                max_tokens=100,
            )
        )
    except ValueError as exc:
        assert "不可重试错误" in str(exc)
    else:
        raise AssertionError("non-retryable error should fail fast")

    assert calls["count"] == 1


def test_case_generation_review_fail_blocks_export(monkeypatch) -> None:
    from app.tasks import case_generation

    async def fake_skill_with_gate_async(**kwargs):
        return {
            "summary": {"release_readiness": "fail"},
            "coverage": {},
            "method_coverage": {},
            "dimension_matrix": {},
            "evidence_trace": {},
            "execution_proof": {},
            "findings": [{"message": "覆盖不足"}],
        }

    monkeypatch.setattr(case_generation, "_call_skill_with_gate_async", fake_skill_with_gate_async)
    try:
        case_generation._build_review_report(
            evidence_trace={"downloaded_images": []},
            function_points={"function_points": [{"fp_id": "FP-001"}]},
            testcase_package={"testcases": [{"priority": "P1"}]},
            pending_confirmations=[],
            api_key="sk-test",
            model="gpt-4.1",
        )
    except ValueError as exc:
        assert "禁止导出 XMind" in str(exc)
    else:
        raise AssertionError("review fail should block export")


def test_case_generation_no_hard_gate_on_generic_titles(monkeypatch) -> None:
    # Phase 1 起移除「模板标题硬门禁」：generic 标题不再由 Python 抛错拦截，
    # 改由 prompt 约束 + quality-reviewer 评判。后端只做结构校验与字段形态对齐。
    from app.tasks import case_generation

    async def fake_skill_with_gate_async(**kwargs):
        result = {
            "testcases": [
                {
                    "case_id": "TC-001-001",
                    "fp_id": "FP-001",
                    "title": "正常流程验证",
                    "category": "functional",
                    "priority": "P1",
                    "preconditions": ["已登录"],
                    "test_data": [],
                    "steps": ["进入页面", "点击提交"],
                    "expected_results": ["系统正常"],
                    "traceability": {"function_points": ["FP-001"]},
                    "generation_basis": {"method": "equivalence"},
                    "scenario_dimensions": ["functional"],
                    "baseline_candidate": True,
                }
            ]
        }
        kwargs["validator"](result)
        return result

    monkeypatch.setattr(case_generation, "_call_skill_with_gate_async", fake_skill_with_gate_async)
    result = case_generation._build_testcase_package(
        {
            "function_points": [
                {
                    "fp_id": "FP-001",
                    "module": "登录模块",
                    "scene": "账号登录",
                    "title": "支持账号密码登录",
                    "description": "用户输入账号密码后完成登录",
                    "rules": ["密码错误时提示错误原因"],
                }
            ]
        },
        [],
        "sk-test",
        "gpt-4.1",
    )

    case = result["testcases"][0]
    # 不再硬门禁：generic 标题原样透传
    assert case["title"] == "正常流程验证"
    # Phase 3 字段形态：review_flags 补全为对象、test_data 为列表
    assert set(case["review_flags"]) == {"executable_risk", "ambiguity_risk"}
    assert isinstance(case["test_data"], list)


def test_case_generation_requires_skill_execution_proof() -> None:
    from app.tasks.case_generation import _assert_required_skill_execution

    try:
        _assert_required_skill_execution([
            {"skill": "requirement-analyzer", "status": "passed"},
            {"skill": "testcase-designer", "status": "passed"},
        ])
    except ValueError as exc:
        assert "quality-reviewer" in str(exc)
    else:
        raise AssertionError("missing required skill proof should fail")

    _assert_required_skill_execution([
        {"skill": "requirement-analyzer", "status": "passed"},
        {"skill": "testcase-designer", "status": "passed"},
        {"skill": "quality-reviewer", "status": "passed"},
    ])


def test_case_generation_job_response_masks_openai_key(client, monkeypatch) -> None:
    from app import api as api_module
    from app.core.database import SessionLocal
    from app.models import CaseGenerationJob

    def fake_run_case_generation_job(job_id: int, attempt_id: int | None = None) -> None:
        return None

    monkeypatch.setattr(api_module, "run_case_generation_job", fake_run_case_generation_job)
    with SessionLocal() as db:
        for job in db.query(CaseGenerationJob).filter(CaseGenerationJob.status.in_(["PENDING", "RUNNING"])).all():
            job.status = "CANCELLED"
            job.task_id = None
        db.commit()
    project_id = client.get("/projects").json()[0]["id"]
    response = client.post(
        "/case-generation/jobs",
        json={
            "project_id": project_id,
            "name": f"用例生成_{time.time_ns()}",
            "source_type": "PASTE",
            "markdown_text": "# 登录\n- 支持账号密码登录",
            "openai_api_key": "sk-test-secret",
            "openai_model": "gpt-4.1",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["input_payload_json"]["openai_api_key"] == "***已提供***"

    detail = client.get(f"/case-generation/jobs/{payload['id']}")
    assert detail.status_code == 200
    assert detail.json()["job"]["input_payload_json"]["openai_api_key"] == "***已提供***"


def test_admin_can_manage_users(client) -> None:
    username = f"tester_{time.time_ns()}"
    create_response = client.post(
        "/users",
        json={
            "username": username,
            "password": "tester123",
            "display_name": "测试用户",
            "role": "tester",
        },
    )
    assert create_response.status_code == 201
    user_id = create_response.json()["id"]

    with TestClient(client.app, base_url="http://testserver/api/v1") as anonymous_client:
        login_response = anonymous_client.post("/auth/login", json={"username": username, "password": "tester123"})
        assert login_response.status_code == 200
        assert login_response.json()["user"]["username"] == username

    update_response = client.put(
        f"/users/{user_id}",
        json={"status": "DISABLED", "role": "viewer", "password": "tester456"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "DISABLED"
    assert update_response.json()["role"] == "viewer"
    assert "默认空间" in update_response.json()["workspaces"]

    with TestClient(client.app, base_url="http://testserver/api/v1") as anonymous_client:
        disabled_login = anonymous_client.post("/auth/login", json={"username": username, "password": "tester456"})
        assert disabled_login.status_code == 403
        assert "账号已停用" in disabled_login.json()["detail"]


def test_disabled_user_old_token_rejected(client) -> None:
    username = f"disable_token_{time.time_ns()}"
    create_response = client.post(
        "/users",
        json={"username": username, "password": "token123", "role": "tester"},
    )
    assert create_response.status_code == 201
    user_id = create_response.json()["id"]

    with TestClient(client.app, base_url="http://testserver/api/v1") as user_client:
        login_response = user_client.post("/auth/login", json={"username": username, "password": "token123"})
        assert login_response.status_code == 200
        user_client.headers.update({"Authorization": f"Bearer {login_response.json()['token']}"})
        assert user_client.get("/auth/me").status_code == 200

        disable_response = client.put(f"/users/{user_id}", json={"status": "DISABLED"})
        assert disable_response.status_code == 200

        assert user_client.get("/auth/me").status_code == 401


def test_create_user_status_and_field_validation(client) -> None:
    username = f"disabled_create_{time.time_ns()}"
    create_response = client.post(
        "/users",
        json={"username": username, "password": "secret123", "role": "viewer", "status": "DISABLED"},
    )
    assert create_response.status_code == 201
    assert create_response.json()["status"] == "DISABLED"

    with TestClient(client.app, base_url="http://testserver/api/v1") as anonymous_client:
        login_response = anonymous_client.post("/auth/login", json={"username": username, "password": "secret123"})
        assert login_response.status_code == 403

    duplicate_response = client.post(
        "/users",
        json={"username": username, "password": "secret123", "role": "viewer"},
    )
    assert duplicate_response.status_code == 400

    invalid_role = client.post(
        "/users",
        json={"username": f"bad_role_{time.time_ns()}", "password": "secret123", "role": "superuser"},
    )
    assert invalid_role.status_code == 422

    invalid_status = client.post(
        "/users",
        json={"username": f"bad_status_{time.time_ns()}", "password": "secret123", "status": "PAUSED"},
    )
    assert invalid_status.status_code == 422

    missing_password = client.post("/users", json={"username": f"no_pwd_{time.time_ns()}"})
    assert missing_password.status_code == 422


def test_admin_cannot_disable_demote_or_delete_self(client) -> None:
    me = client.get("/auth/me")
    assert me.status_code == 200
    admin_id = me.json()["id"]

    disable_self = client.put(f"/users/{admin_id}", json={"status": "DISABLED"})
    assert disable_self.status_code == 400

    demote_self = client.put(f"/users/{admin_id}", json={"role": "tester"})
    assert demote_self.status_code == 400

    delete_self = client.delete(f"/users/{admin_id}")
    assert delete_self.status_code == 400


def test_change_password_flow(client) -> None:
    username = f"chpwd_{time.time_ns()}"
    create_response = client.post(
        "/users",
        json={"username": username, "password": "oldpass123", "role": "tester"},
    )
    assert create_response.status_code == 201

    first_client = TestClient(client.app, base_url="http://testserver/api/v1")
    first_login = first_client.post("/auth/login", json={"username": username, "password": "oldpass123"})
    assert first_login.status_code == 200
    first_client.headers.update({"Authorization": f"Bearer {first_login.json()['token']}"})

    second_client = TestClient(client.app, base_url="http://testserver/api/v1")
    second_login = second_client.post("/auth/login", json={"username": username, "password": "oldpass123"})
    assert second_login.status_code == 200
    second_client.headers.update({"Authorization": f"Bearer {second_login.json()['token']}"})

    wrong_old = first_client.post(
        "/auth/change-password",
        json={"old_password": "wrongpass", "new_password": "newpass123"},
    )
    assert wrong_old.status_code == 400

    change_response = first_client.post(
        "/auth/change-password",
        json={"old_password": "oldpass123", "new_password": "newpass123"},
    )
    assert change_response.status_code == 204

    # 当前 token 保留，其他 token 被吊销
    assert first_client.get("/auth/me").status_code == 200
    assert second_client.get("/auth/me").status_code == 401

    with TestClient(client.app, base_url="http://testserver/api/v1") as anonymous_client:
        old_login = anonymous_client.post("/auth/login", json={"username": username, "password": "oldpass123"})
        assert old_login.status_code == 401
        new_login = anonymous_client.post("/auth/login", json={"username": username, "password": "newpass123"})
        assert new_login.status_code == 200


def test_delete_user_revokes_access_and_requires_admin(client) -> None:
    username = f"delete_me_{time.time_ns()}"
    create_response = client.post(
        "/users",
        json={"username": username, "password": "delete123", "role": "tester"},
    )
    assert create_response.status_code == 201
    user_id = create_response.json()["id"]

    victim_client = TestClient(client.app, base_url="http://testserver/api/v1")
    victim_login = victim_client.post("/auth/login", json={"username": username, "password": "delete123"})
    assert victim_login.status_code == 200
    victim_client.headers.update({"Authorization": f"Bearer {victim_login.json()['token']}"})

    # 非 admin 无权调用用户管理接口
    assert victim_client.get("/users").status_code == 403
    assert victim_client.delete(f"/users/{user_id}").status_code == 403

    # 被删用户创建过业务数据（created_by 外键引用），删除用户后数据应保留且引用置空
    project_response = victim_client.post(
        "/projects",
        json={"name": f"待删用户项目_{time.time_ns()}", "base_url": "http://example.com"},
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]
    assert project_response.json()["created_by"] == user_id

    delete_response = client.delete(f"/users/{user_id}")
    assert delete_response.status_code == 204

    projects = client.get("/projects")
    assert projects.status_code == 200
    orphan_project = next(item for item in projects.json() if item["id"] == project_id)
    assert orphan_project["created_by"] is None
    assert orphan_project["updated_by"] is None

    assert victim_client.get("/auth/me").status_code == 401
    users = client.get("/users")
    assert users.status_code == 200
    assert all(user["id"] != user_id for user in users.json())

    with TestClient(client.app, base_url="http://testserver/api/v1") as anonymous_client:
        deleted_login = anonymous_client.post("/auth/login", json={"username": username, "password": "delete123"})
        assert deleted_login.status_code == 401


def test_legacy_password_hash_upgrades_on_login(client) -> None:
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import User
    from app.services import hash_password

    legacy_username = f"legacy_{time.time_ns()}"
    legacy_password = "legacy123"
    legacy_hash = hash_password("unused")
    assert legacy_hash.startswith("pbkdf2_sha256$")

    with SessionLocal() as db:
        user = User(
            username=legacy_username,
            display_name="旧哈希用户",
            role="tester",
            status="ACTIVE",
            password_hash=hashlib.sha256(legacy_password.encode("utf-8")).hexdigest(),
        )
        db.add(user)
        db.commit()

    with TestClient(client.app, base_url="http://testserver/api/v1") as anonymous_client:
        login_response = anonymous_client.post(
            "/auth/login",
            json={"username": legacy_username, "password": legacy_password},
        )
        assert login_response.status_code == 200

    with SessionLocal() as db:
        upgraded_user = db.scalar(select(User).where(User.username == legacy_username))
        assert upgraded_user is not None
        assert upgraded_user.password_hash is not None
        assert upgraded_user.password_hash.startswith("pbkdf2_sha256$")


def test_role_based_access_boundaries(client) -> None:
    viewer_username = f"viewer_{time.time_ns()}"
    tester_username = f"tester_role_{time.time_ns()}"
    for username, role in ((viewer_username, "viewer"), (tester_username, "tester")):
        response = client.post(
            "/users",
            json={
                "username": username,
                "password": "role123",
                "display_name": username,
                "role": role,
            },
        )
        assert response.status_code == 201

    def login_as(username: str) -> TestClient:
        role_client = TestClient(client.app, base_url="http://testserver/api/v1")
        login_response = role_client.post("/auth/login", json={"username": username, "password": "role123"})
        assert login_response.status_code == 200
        token = login_response.json()["token"]
        role_client.headers.update({"Authorization": f"Bearer {token}"})
        return role_client

    projects = client.get("/projects").json()
    project_id = next(project["id"] for project in projects if project["name"] == "平台自检项目")

    with login_as(viewer_username) as viewer_client:
        viewer_projects = viewer_client.get("/projects")
        assert viewer_projects.status_code == 200
        assert all("variables_json" not in project for project in viewer_projects.json())
        assert viewer_client.get(f"/projects/{project_id}/variables").status_code == 403
        assert viewer_client.post(
            "/projects",
            json={"name": f"viewer_project_{time.time_ns()}", "base_url": "http://example.com"},
        ).status_code == 403
        assert viewer_client.post("/system/bootstrap", json={"seed_demo_data": False}).status_code == 403
        assert viewer_client.delete(f"/projects/{project_id}").status_code == 403

    with login_as(tester_username) as tester_client:
        create_response = tester_client.post(
            "/projects",
            json={"name": f"tester_project_{time.time_ns()}", "base_url": "http://example.com"},
        )
        assert create_response.status_code == 201
        created_project_id = create_response.json()["id"]
        assert tester_client.post("/system/bootstrap", json={"seed_demo_data": False}).status_code == 403
        assert tester_client.delete(f"/projects/{created_project_id}").status_code == 403


def test_workspace_membership_isolates_project_data(client) -> None:
    isolated_workspace = client.post(
        "/workspaces",
        json={"name": f"隔离空间_{time.time_ns()}", "description": "membership isolation"},
    )
    assert isolated_workspace.status_code == 201
    workspace_id = isolated_workspace.json()["id"]

    isolated_project = client.post(
        "/projects",
        json={
            "workspace_id": workspace_id,
            "name": f"隔离项目_{time.time_ns()}",
            "base_url": "http://example.com",
        },
    )
    assert isolated_project.status_code == 201
    isolated_project_id = isolated_project.json()["id"]

    username = f"isolated_{time.time_ns()}"
    user_response = client.post(
        "/users",
        json={"username": username, "password": "role123", "display_name": username, "role": "tester"},
    )
    assert user_response.status_code == 201
    user_id = user_response.json()["id"]

    member_client = TestClient(client.app, base_url="http://testserver/api/v1")
    login_response = member_client.post("/auth/login", json={"username": username, "password": "role123"})
    assert login_response.status_code == 200
    member_client.headers.update({"Authorization": f"Bearer {login_response.json()['token']}"})

    projects_before = member_client.get("/projects")
    assert projects_before.status_code == 200
    assert all(project["id"] != isolated_project_id for project in projects_before.json())
    assert member_client.get(f"/projects?workspace_id={workspace_id}").status_code == 403
    assert member_client.post(
        "/projects",
        json={
            "workspace_id": workspace_id,
            "name": f"越权项目_{time.time_ns()}",
            "base_url": "http://example.com",
        },
    ).status_code == 403

    add_member = client.post(
        f"/workspaces/{workspace_id}/members",
        json={"user_id": user_id, "role": "member"},
    )
    assert add_member.status_code == 201

    update_member = client.put(
        f"/workspaces/{workspace_id}/members/{add_member.json()['id']}",
        json={"role": "owner"},
    )
    assert update_member.status_code == 200
    assert update_member.json()["role"] == "owner"

    users = client.get("/users")
    assert users.status_code == 200
    isolated_user = next(user for user in users.json() if user["id"] == user_id)
    assert "默认空间" in isolated_user["workspaces"]
    assert any(name.startswith("隔离空间_") for name in isolated_user["workspaces"])

    projects_after = member_client.get("/projects")
    assert projects_after.status_code == 200
    assert any(project["id"] == isolated_project_id for project in projects_after.json())
    assert member_client.get(f"/projects?workspace_id={workspace_id}").status_code == 200


def test_workspace_owner_guard_prevents_removing_last_owner(client) -> None:
    workspace_response = client.post(
        "/workspaces",
        json={"name": f"owner_guard_{time.time_ns()}", "description": "owner guard"},
    )
    assert workspace_response.status_code == 201
    workspace_id = workspace_response.json()["id"]

    owner_members = client.get(f"/workspaces/{workspace_id}/members")
    assert owner_members.status_code == 200
    admin_member = next(member for member in owner_members.json() if member["role"] == "owner")

    downgrade_response = client.put(
        f"/workspaces/{workspace_id}/members/{admin_member['id']}",
        json={"role": "member"},
    )
    assert downgrade_response.status_code == 400
    assert "Owner" in downgrade_response.json()["detail"]

    delete_response = client.delete(f"/workspaces/{workspace_id}/members/{admin_member['id']}")
    assert delete_response.status_code == 400
    assert "Owner" in delete_response.json()["detail"]


def test_user_payload_includes_workspace_memberships(client) -> None:
    me_response = client.get("/auth/me")
    assert me_response.status_code == 200
    payload = me_response.json()
    assert "workspace_memberships" in payload
    assert any(item["workspace_name"] == "默认空间" for item in payload["workspace_memberships"])


def test_tools_endpoints(client) -> None:
    json_response = client.post("/tools/json/format", json={"payload": '{"name":"平台","type":"测试"}'})
    assert json_response.status_code == 200
    assert '"name": "平台"' in json_response.json()["result"]

    cron_response = client.post("/tools/cron/preview", json={"payload": "0 2 * * *"})
    assert cron_response.status_code == 200
    cron_lines = cron_response.json()["result"].splitlines()
    assert len(cron_lines) == 5
    assert all("02:00:00" in line for line in cron_lines)

    bad_cron_response = client.post("/tools/cron/preview", json={"payload": "not a cron"})
    assert bad_cron_response.status_code == 400

    hash_response = client.post("/tools/hash/digest", json={"payload": "hello"})
    assert hash_response.status_code == 200
    hash_result = hash_response.json()["result"]
    assert "MD5:    5d41402abc4b2a76b9719d911017c592" in hash_result
    assert "SHA256: 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824" in hash_result


def test_environment_update_and_variables_api(client) -> None:
    projects_response = client.get("/projects")
    assert projects_response.status_code == 200
    project_id = projects_response.json()[0]["id"]

    create_response = client.post(
        "/environments",
        json={
            "project_id": project_id,
            "name": f"env_{time.time_ns()}",
            "base_url": "http://backend:8000",
            "headers_json": {"accept": "application/json"},
            "variables_json": {"token": "abc"},
            "auth_config_json": {"header_name": "Authorization", "token_prefix": "Bearer", "token": "{{token}}"},
        },
    )
    assert create_response.status_code == 201
    env_id = create_response.json()["id"]

    update_response = client.put(
        f"/environments/{env_id}",
        json={
            "name": "updated env",
            "base_url": "http://testserver",
            "headers_json": {"x-env": "test"},
            "variables_json": {"token": "xyz"},
            "auth_config_json": {"header_name": "Authorization", "token": "{{token}}"},
        },
    )
    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["name"] == "updated env"
    assert payload["base_url"] == "http://testserver"
    assert payload["variables_json"]["token"] == "xyz"

    variables_response = client.get(f"/environments/{env_id}/variables")
    assert variables_response.status_code == 200
    assert variables_response.json()["headers_json"]["x-env"] == "test"

    validate_response = client.get(f"/environments/{env_id}/validate")
    assert validate_response.status_code == 200
    assert validate_response.json()["environment_id"] == env_id
    assert validate_response.json()["is_valid"] is True
    assert validate_response.json()["summary"] == "未发现缺失变量"
    assert validate_response.json()["scope_counts"] == {}
    assert validate_response.json()["missing_variables"] == []

    draft_validate_response = client.post(
        "/environments/validate-draft",
        json={
            "project_id": project_id,
            "name": "draft env",
            "base_url": "http://testserver",
            "headers_json": {"x-env": "{{draft_token}}"},
            "variables_json": {"token": "xyz"},
            "auth_config_json": {"header_name": "Authorization", "token": "{{token}}"},
        },
    )
    assert draft_validate_response.status_code == 200
    assert draft_validate_response.json()["environment_id"] == 0
    assert draft_validate_response.json()["is_valid"] is False
    assert "draft_token" in draft_validate_response.json()["missing_variables"]
    assert draft_validate_response.json()["scope_counts"]["environment"] >= 1
    assert any("headers_json.x-env" == item["field"] for item in draft_validate_response.json()["issues"])

    variables_update_response = client.put(
        f"/environments/{env_id}/variables",
        json={
            "headers_json": {"x-env": "changed"},
            "variables_json": {"token": "final"},
            "auth_config_json": {"header_name": "Authorization", "token_prefix": "Bearer", "token": "{{missing_token}}"},
        },
    )
    assert variables_update_response.status_code == 200
    assert variables_update_response.json()["variables_json"]["token"] == "final"

    validate_fail_response = client.get(f"/environments/{env_id}/validate")
    assert validate_fail_response.status_code == 200
    assert validate_fail_response.json()["is_valid"] is False
    assert "missing_token" in validate_fail_response.json()["missing_variables"]
    assert validate_fail_response.json()["summary"].startswith("存在缺失变量：")
    assert any("auth_config_json.token" == item["field"] for item in validate_fail_response.json()["issues"])

    encoded = client.post("/tools/base64/encode", json={"payload": "hello-test"}).json()["result"]
    decoded = client.post("/tools/base64/decode", json={"payload": encoded}).json()["result"]
    assert decoded == "hello-test"

    timestamp_result = client.post(
        "/tools/timestamp/convert",
        json={"payload": "2026-03-09T09:30:00+08:00"},
    )
    assert timestamp_result.status_code == 200
    assert "时间戳" in timestamp_result.json()["result"]


def test_seeded_resources_exist(client) -> None:
    workspaces = client.get("/workspaces")
    projects = client.get("/projects")
    api_cases = client.get("/api-cases")
    ui_cases = client.get("/ui-cases")
    performance_cases = client.get("/performance-cases")
    environments = client.get("/environments")
    plans = client.get("/test-plans")

    assert workspaces.status_code == 200
    assert projects.status_code == 200
    assert api_cases.status_code == 200
    assert ui_cases.status_code == 200
    assert performance_cases.status_code == 200
    assert environments.status_code == 200
    assert plans.status_code == 200

    assert any(workspace["name"] == "默认空间" for workspace in workspaces.json())
    assert any(project["name"] == "平台自检项目" for project in projects.json())
    assert any(case["name"] == "示例健康检查接口" for case in api_cases.json())
    assert any(case["name"] == "示例前端首页巡检" for case in ui_cases.json())
    assert any(case["name"] == "示例健康检查压测" for case in performance_cases.json())
    assert any(env["name"] == "本地环境" for env in environments.json())
    assert any(plan["name"] == "演示回归计划" for plan in plans.json())


def test_environment_variables_and_auth_config_api(client) -> None:
    environments = client.get("/environments").json()
    environment_id = next(env["id"] for env in environments if env["name"] == "本地环境")

    get_response = client.get(f"/environments/{environment_id}/variables")
    assert get_response.status_code == 200
    assert "variables_json" in get_response.json()

    put_response = client.put(
        f"/environments/{environment_id}/variables",
        json={
            "variables_json": {"frontend_url": "http://frontend:3000", "token": "demo-token"},
            "headers_json": {"accept": "application/json"},
            "auth_config_json": {"header_name": "Authorization", "token_prefix": "Bearer", "token": "{{token}}"},
        },
    )
    assert put_response.status_code == 200
    assert put_response.json()["auth_config_json"]["token"] == "{{token}}"

    from app.core.database import SessionLocal
    from app.models import Environment
    with SessionLocal() as db:
        stored_environment = db.get(Environment, environment_id)
        assert stored_environment._legacy_variables_json is None
        assert stored_environment.variables_encrypted
        assert "demo-token" not in stored_environment.variables_encrypted


def test_api_case_run(client) -> None:
    api_cases = client.get("/api-cases").json()
    case_id = next(case["id"] for case in api_cases if case["name"] == "示例健康检查接口")
    trigger = client.post(f"/executions/api/{case_id}/run", json={"timeout_seconds": 7, "max_retries": 2})
    assert trigger.status_code == 200
    run_id = trigger.json()["id"]

    final_payload = None
    for _ in range(40):
        final_payload = client.get(f"/executions/runs/{run_id}").json()
        if final_payload["status"] in {"SUCCESS", "FAILED"}:
            break
        time.sleep(2)

    assert final_payload is not None
    assert final_payload["status"] == "SUCCESS", final_payload
    assert final_payload["timeout_seconds"] == 7
    assert final_payload["max_retries"] == 2
    assert final_payload["stdout_text"] is not None
    assert isinstance(final_payload["artifacts_json"], list)

    log_payload = client.get(f"/executions/runs/{run_id}/logs")
    assert log_payload.status_code == 200
    assert "stdout_text" in log_payload.json()
    steps_payload = client.get(f"/executions/runs/{run_id}/steps")
    assert steps_payload.status_code == 200
    assert len(steps_payload.json()) >= 1
    assert steps_payload.json()[0]["run_id"] == run_id

    artifacts_payload = client.get(f"/executions/runs/{run_id}/artifacts")
    assert artifacts_payload.status_code == 200
    assert len(artifacts_payload.json()["artifacts"]) >= 1
    artifact_download = client.get(f"/executions/runs/{run_id}/artifacts/0/download")
    assert artifact_download.status_code == 200

    from sqlalchemy import func, select

    from app.core.database import SessionLocal
    from app.models import ExecutionArtifact, ExecutionLog, ExecutionStep

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ExecutionLog).where(ExecutionLog.run_id == run_id)) >= 1
        assert db.scalar(
            select(func.count()).select_from(ExecutionArtifact).where(ExecutionArtifact.run_id == run_id)
        ) >= 1
        assert db.scalar(select(func.count()).select_from(ExecutionStep).where(ExecutionStep.run_id == run_id)) >= 1

    rerun_response = client.post(f"/executions/runs/{run_id}/rerun")
    assert rerun_response.status_code == 200
    assert rerun_response.json()["retry_count"] >= 1

    plans = client.get("/test-plans").json()
    plan_id = next(plan["id"] for plan in plans if plan["name"] == "演示回归计划")
    plan_precheck = client.get(f"/test-plans/{plan_id}/precheck")
    assert plan_precheck.status_code == 200
    assert "summary" in plan_precheck.json()
    assert "scope_counts" in plan_precheck.json()
    assert "missing_variables" in plan_precheck.json()


def test_api_case_debug_request_returns_response_preview(client) -> None:
    api_case = next(case for case in client.get("/api-cases").json() if case["name"] == "示例健康检查接口")
    response = client.post(
        "/api-cases/debug",
        json={
            "project_id": api_case["project_id"],
            "name": "调试健康检查",
            "method": "GET",
            "path": "/api/v1/system/health",
            "headers_json": {"accept": "application/json"},
            "body_json": None,
            "assertions_json": [{"type": "status_code", "expected": 200}],
            "expected_status": 200,
            "timeout_seconds": 5,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["request"]["method"] == "GET"
    assert payload["response"]["status_code"] == 200
    assert payload["duration_ms"] >= 0


def test_api_case_debug_returns_assertion_and_extractor_results(client) -> None:
    api_case = next(case for case in client.get("/api-cases").json() if case["name"] == "示例健康检查接口")
    response = client.post(
        "/api-cases/debug",
        json={
            "project_id": api_case["project_id"],
            "name": "调试断言引擎",
            "method": "GET",
            "path": "/api/v1/system/health",
            "headers_json": {"accept": "application/json"},
            "assertions_json": [
                {"type": "json_path", "expression": "$.app_status", "operator": "regex", "expected": "healthy|degraded"},
                {"type": "body_contains", "expected": "database"},
                {"type": "header", "name": "content-type", "operator": "contains", "expected": "json"},
            ],
            "extractors_json": [
                {"name": "health_status", "source": "json_path", "expression": "$.app_status"},
                {"name": "http_code", "source": "status_code"},
            ],
            "expected_status": 200,
            "timeout_seconds": 5,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["assertion_passed"] is True, payload["assertion_results"]
    assert len(payload["assertion_results"]) >= 3
    assert all(item["ok"] for item in payload["assertion_results"])
    assert payload["extracted_variables"]["health_status"] in {"healthy", "degraded"}
    assert payload["extracted_variables"]["http_code"] == "200"
    assert all(item["ok"] for item in payload["extractor_results"])


def test_api_case_debug_reports_assertion_failure(client) -> None:
    api_case = next(case for case in client.get("/api-cases").json() if case["name"] == "示例健康检查接口")
    response = client.post(
        "/api-cases/debug",
        json={
            "project_id": api_case["project_id"],
            "name": "调试断言失败",
            "method": "GET",
            "path": "/api/v1/system/health",
            "assertions_json": [
                {"type": "json_path", "expression": "$.app_status", "expected": "__绝不可能的值__"},
            ],
            "expected_status": 200,
            "timeout_seconds": 5,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["assertion_passed"] is False
    failed = [item for item in payload["assertion_results"] if not item["ok"]]
    assert failed and failed[0]["type"] == "json_path"


def _wait_for_run(client, run_id: int) -> dict:
    final_payload = None
    for _ in range(40):
        final_payload = client.get(f"/executions/runs/{run_id}").json()
        if final_payload["status"] in {"SUCCESS", "FAILED"}:
            break
        time.sleep(2)
    assert final_payload is not None
    return final_payload


def test_api_case_run_fails_on_assertion(client) -> None:
    api_case = next(case for case in client.get("/api-cases").json() if case["name"] == "示例健康检查接口")
    created = client.post(
        "/api-cases",
        json={
            "project_id": api_case["project_id"],
            "name": "断言失败演示用例",
            "method": "GET",
            "path": "/api/v1/system/health",
            "assertions_json": [
                {"type": "json_path", "expression": "$.app_status", "expected": "__绝不可能的值__"},
            ],
            "expected_status": 200,
        },
    )
    assert created.status_code == 201
    case_id = created.json()["id"]

    trigger = client.post(f"/executions/api/{case_id}/run", json={"timeout_seconds": 7})
    assert trigger.status_code == 200
    final_payload = _wait_for_run(client, trigger.json()["id"])

    assert final_payload["status"] == "FAILED", final_payload
    assert final_payload["error_type"] == "ASSERTION"
    assertion_results = (final_payload["response_payload"] or {}).get("assertion_results") or []
    assert any(not item["ok"] and item["type"] == "json_path" for item in assertion_results)
    assert "[FAIL]" in (final_payload["stdout_text"] or "")

    client.delete(f"/api-cases/{case_id}")


def test_api_case_run_passes_with_rich_assertions(client) -> None:
    api_case = next(case for case in client.get("/api-cases").json() if case["name"] == "示例健康检查接口")
    created = client.post(
        "/api-cases",
        json={
            "project_id": api_case["project_id"],
            "name": "多类型断言演示用例",
            "method": "GET",
            "path": "/api/v1/system/health",
            "assertions_json": [
                {"type": "status_code", "expected": 200},
                {"type": "json_path", "expression": "$.app_status", "operator": "regex", "expected": "healthy|degraded"},
                {"type": "body_contains", "expected": "redis"},
                {"type": "header", "name": "content-type", "operator": "contains", "expected": "json"},
                {"type": "response_time_ms", "operator": "lte", "expected": 60000},
            ],
            "extractors_json": [
                {"name": "health_status", "source": "json_path", "expression": "$.app_status"},
            ],
            "expected_status": 200,
        },
    )
    assert created.status_code == 201
    case_id = created.json()["id"]

    trigger = client.post(f"/executions/api/{case_id}/run", json={"timeout_seconds": 15})
    assert trigger.status_code == 200
    final_payload = _wait_for_run(client, trigger.json()["id"])

    assert final_payload["status"] == "SUCCESS", final_payload
    response_payload = final_payload["response_payload"] or {}
    assert all(item["ok"] for item in response_payload.get("assertion_results") or [])
    assert response_payload.get("extracted_variables", {}).get("health_status") in {"healthy", "degraded"}

    client.delete(f"/api-cases/{case_id}")


def test_api_scenario_run_with_variable_extraction(client) -> None:
    api_case = next(case for case in client.get("/api-cases").json() if case["name"] == "示例健康检查接口")
    created = client.post(
        "/api-cases",
        json={
            "project_id": api_case["project_id"],
            "name": "多步骤场景演示用例",
            "method": "GET",
            "path": "/api/v1/system/health",
            "expected_status": 200,
            "steps_json": [
                {
                    "name": "查询系统健康",
                    "method": "GET",
                    "path": "/api/v1/system/health",
                    "expected_status": 200,
                    "assertions": [
                        {"type": "json_path", "expression": "$.app_status", "operator": "regex", "expected": "healthy|degraded"},
                    ],
                    "extractors": [
                        {"name": "health_status", "source": "json_path", "expression": "$.app_status"},
                    ],
                },
                {
                    "name": "引用提取变量再次校验",
                    "method": "GET",
                    "path": "/api/v1/system/health",
                    "headers_json": {"x-prev-status": "{{health_status}}"},
                    "expected_status": 200,
                    "assertions": [
                        {"type": "body_contains", "expected": "database"},
                    ],
                },
            ],
        },
    )
    assert created.status_code == 201
    case_id = created.json()["id"]

    trigger = client.post(f"/executions/api/{case_id}/run", json={"timeout_seconds": 20})
    assert trigger.status_code == 200
    final_payload = _wait_for_run(client, trigger.json()["id"])

    assert final_payload["status"] == "SUCCESS", final_payload
    steps = final_payload["step_results_json"] or []
    assert len(steps) == 2
    assert all(step["status"] == "SUCCESS" for step in steps)
    extracted = (final_payload["response_payload"] or {}).get("extracted_variables") or {}
    assert extracted.get("health_status") in {"healthy", "degraded"}
    artifacts = final_payload["artifacts_json"] or []
    assert any("step_01_" in str(item) for item in artifacts)

    client.delete(f"/api-cases/{case_id}")


def test_api_scenario_run_stops_and_skips_after_failed_step(client) -> None:
    api_case = next(case for case in client.get("/api-cases").json() if case["name"] == "示例健康检查接口")
    created = client.post(
        "/api-cases",
        json={
            "project_id": api_case["project_id"],
            "name": "场景失败中断演示用例",
            "method": "GET",
            "path": "/api/v1/system/health",
            "expected_status": 200,
            "steps_json": [
                {
                    "name": "必然失败的步骤",
                    "method": "GET",
                    "path": "/api/v1/system/health",
                    "expected_status": 200,
                    "assertions": [{"type": "body_contains", "expected": "__绝不可能的内容__"}],
                },
                {
                    "name": "应被跳过的步骤",
                    "method": "GET",
                    "path": "/api/v1/system/health",
                    "expected_status": 200,
                },
            ],
        },
    )
    assert created.status_code == 201
    case_id = created.json()["id"]

    trigger = client.post(f"/executions/api/{case_id}/run", json={"timeout_seconds": 20})
    assert trigger.status_code == 200
    final_payload = _wait_for_run(client, trigger.json()["id"])

    assert final_payload["status"] == "FAILED", final_payload
    steps = final_payload["step_results_json"] or []
    assert len(steps) == 2
    assert steps[0]["status"] == "FAILED"
    assert steps[1]["status"] == "SKIPPED"

    client.delete(f"/api-cases/{case_id}")


def test_api_case_debug_request_returns_400_when_environment_variables_missing(client) -> None:
    from app.core.database import SessionLocal
    from app.models import Environment

    with SessionLocal() as db:
        environment = db.get(Environment, 1)
        environment.variables_json = {}
        environment.auth_config_json = {
            "header_name": "Authorization",
            "token_prefix": "Bearer",
            "token": "{{token}}",
        }
        db.commit()

    response = client.post(
        "/api-cases/debug",
        json={
            "project_id": 1,
            "name": "调试健康检查",
            "method": "GET",
            "path": "/api/v1/system/health",
            "headers_json": {"accept": "application/json"},
            "body_json": None,
            "assertions_json": [{"type": "status_code", "expected": 200}],
            "expected_status": 200,
            "environment_id": 1,
            "timeout_seconds": 5,
        },
    )
    assert response.status_code == 400
    assert "环境变量缺失" in response.json()["detail"]


def test_cancel_pending_execution(client) -> None:
    from app.core.database import SessionLocal
    from app.models import APICase
    from app.services import create_test_run

    api_cases = client.get("/api-cases").json()
    case_id = next(case["id"] for case in api_cases if case["name"] == "示例健康检查接口")

    with SessionLocal() as db:
        case = db.get(APICase, case_id)
        run = create_test_run(
            db,
            project_id=case.project_id,
            environment_id=None,
            case_type="API",
            case_id=case.id,
            case_name=case.name,
        )
        run_id = run.id

    cancel_response = client.post(f"/executions/runs/{run_id}/cancel")
    assert cancel_response.status_code == 200
    payload = cancel_response.json()
    assert payload["status"] == "CANCELLED"
    assert payload["error_type"] == "CANCELLED"

    second_cancel = client.post(f"/executions/runs/{run_id}/cancel")
    assert second_cancel.status_code == 400


def test_ui_case_run(client) -> None:
    ui_cases = client.get("/ui-cases").json()
    case_id = next(case["id"] for case in ui_cases if case["name"] == "示例前端首页巡检")
    trigger = client.post(f"/executions/ui/{case_id}/run")
    assert trigger.status_code == 200
    run_id = trigger.json()["id"]

    final_payload = None
    for _ in range(50):
        final_payload = client.get(f"/executions/runs/{run_id}").json()
        if final_payload["status"] in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT"}:
            break
        time.sleep(2)

    assert final_payload is not None
    assert final_payload["status"] in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT"}, final_payload
    assert final_payload["summary"]


def test_ui_case_collects_trace_and_step_artifacts(client, monkeypatch) -> None:
    from app.tasks import executions

    class FakeLocator:
        def __init__(self, page):
            self.page = page
            self.first = self

        def wait_for(self, timeout=None):
            return None

        def click(self, timeout=None):
            self.page.url = f"{self.page.url}#clicked"

        def fill(self, value="", timeout=None):
            self.page.filled_value = value

    class FakePage:
        def __init__(self):
            self.url = "http://frontend:3000/"
            self.filled_value = ""

        def goto(self, value, wait_until=None, timeout=None):
            self.url = value

        def locator(self, selector):
            return FakeLocator(self)

        def screenshot(self, full_page=True, **kwargs):
            return b"fake-png"

    class FakeTracing:
        def start(self, screenshots=True, snapshots=True, sources=True):
            return None

        def stop(self, path):
            with open(path, "wb") as handle:
                handle.write(b"trace")

    class FakeContext:
        def __init__(self):
            self.tracing = FakeTracing()
            self.page = FakePage()

        def new_page(self):
            return self.page

        def close(self):
            return None

    class FakeBrowser:
        def new_context(self, viewport=None):
            return FakeContext()

        def close(self):
            return None

    class FakePlaywrightManager:
        def __enter__(self):
            chromium = type("FakeChromium", (), {"launch": lambda self, headless=True: FakeBrowser()})()
            return type("FakePlaywright", (), {"chromium": chromium})()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(executions, "sync_playwright", lambda: FakePlaywrightManager())

    ui_cases = client.get("/ui-cases").json()
    case_id = next(case["id"] for case in ui_cases if case["name"] == "示例前端首页巡检")
    trigger = client.post(f"/executions/ui/{case_id}/run")
    assert trigger.status_code == 200
    run_payload = client.get(f"/executions/runs/{trigger.json()['id']}").json()
    assert run_payload["status"] == "SUCCESS"
    artifact_names = [item["name"] for item in run_payload["artifacts_json"]]
    assert "ui-trace.zip" in artifact_names
    assert "ui-success.png" in artifact_names
    assert any(name.startswith("step-01-") for name in artifact_names)
    assert any(step["detail"].get("page_url") for step in run_payload["step_results_json"])
    assert any(step["detail"].get("screenshot") for step in run_payload["step_results_json"])


def test_ui_case_rejects_unsupported_workflow_action(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    response = client.post(
        "/ui-cases",
        json={
            "project_id": project_id,
            "name": f"非法 UI 步骤_{time.time_ns()}",
            "target_url": "http://frontend:3000",
            "steps_json": [{"action": "execute_script", "value": "alert(1)"}],
            "expect_text": "登录",
        },
    )

    assert response.status_code == 422
    assert "步骤类型不支持" in response.text


def test_ui_case_schema_accepts_semantic_target_and_execution_modes() -> None:
    from app import schemas

    for mode in ("stable", "adaptive", "explore", "visual"):
        payload = schemas.UICaseCreate(
            project_id=1,
            name=f"语义 UI 用例 {mode}",
            target_url="https://example.com",
            expect_text="完成",
            execution_mode=mode,
            self_heal_enabled=mode == "adaptive",
            steps_json=[
                {
                    "action": "click",
                    "target": "登录按钮",
                    "role": "button",
                    "accessible_name": "登录",
                }
            ],
            assertions_json=[
                {
                    "type": "visual",
                    "target": "登录表单",
                    "value": "表单完整可见且没有遮挡",
                }
            ],
        )
        assert payload.execution_mode == mode


def test_ui_case_runtime_origin_and_prohibited_action_guards() -> None:
    import pytest

    from app.ui_case_runtime import (
        build_allowed_origins,
        ensure_allowed_url,
        prohibited_candidate,
    )

    origins = build_allowed_origins(
        "https://example.com/login",
        "https://example.com",
        ["https://static.example.com"],
    )
    ensure_allowed_url("https://example.com/dashboard", origins)
    ensure_allowed_url("https://static.example.com/help", origins)
    with pytest.raises(ValueError, match="不在允许域名"):
        ensure_allowed_url("https://evil.example.net", origins)
    assert prohibited_candidate({"text": "删除账号"}, []) == "删除"


def test_ui_case_runtime_rejects_semantically_wrong_healing_candidates() -> None:
    import pytest

    from app.ui_case_runtime import validate_healing_candidate

    login_candidates = [
        {
            "candidate_id": "OMNI-1",
            "tag": "input",
            "placeholder": "Username",
            "text": "",
            "type": "text",
        },
        {
            "candidate_id": "OMNI-2",
            "tag": "input",
            "placeholder": "Password",
            "text": "",
            "type": "password",
        },
        {
            "candidate_id": "OMNI-3",
            "tag": "button",
            "placeholder": "",
            "text": "Login",
            "type": "submit",
        },
    ]
    with pytest.raises(ValueError, match="当前页面看起来是登录页"):
        validate_healing_candidate(
            {"action": "fill", "target": "搜索框"},
            login_candidates[0],
            candidates=login_candidates,
        )
    with pytest.raises(ValueError, match="当前页面看起来是登录页"):
        validate_healing_candidate(
            {"action": "click", "target": "查询按钮"},
            login_candidates[2],
            candidates=login_candidates,
        )

    validate_healing_candidate(
        {"action": "fill", "target": "搜索框"},
        {
            "candidate_id": "OMNI-4",
            "tag": "input",
            "placeholder": "Search",
            "text": "",
            "type": "text",
        },
    )


def test_ui_case_runtime_rejects_non_text_fill_candidate() -> None:
    import pytest

    from app.ui_case_runtime import validate_healing_candidate

    with pytest.raises(ValueError, match="不是可输入控件"):
        validate_healing_candidate(
            {"action": "fill", "target": "搜索框"},
            {"candidate_id": "OMNI-1", "tag": "button", "text": "Search"},
        )


def test_ui_case_runtime_rejects_login_page_before_model_call(monkeypatch) -> None:
    import pytest

    import app.ui_case_runtime as runtime

    def unexpected_model_call(**kwargs):
        raise AssertionError("login context mismatch should not call the model")

    monkeypatch.setattr(runtime, "call_runtime_model", unexpected_model_call)
    with pytest.raises(ValueError, match="当前页面看起来是登录页"):
        runtime.choose_healing_candidate(
            model_config=SimpleNamespace(api_key="x", model="x", base_url="https://example.com"),
            step={"action": "fill", "target": "搜索框"},
            candidates=[
                {"candidate_id": "OMNI-1", "tag": "input", "placeholder": "Username"},
                {"candidate_id": "OMNI-2", "tag": "input", "placeholder": "Password"},
                {"candidate_id": "OMNI-3", "tag": "button", "text": "Login"},
            ],
        )


def test_ui_case_ai_skill_generates_reviewable_draft_and_persists_source(client, monkeypatch) -> None:
    from app import schemas
    from app.core.database import SessionLocal
    from app.models import AIModelConfig, Project
    import app.api as api_module

    project_id = client.get("/projects").json()[0]["id"]
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        config = AIModelConfig(
            workspace_id=project.workspace_id,
            provider="OPENAI",
            name=f"UI AI 测试配置_{time.time_ns()}",
            base_url="https://api.openai.com/v1",
            model="gpt-test-ui",
            api_key="sk-test-ui-case-designer",
            is_active=1,
            created_by=1,
            updated_by=1,
        )
        db.add(config)
        db.commit()
        db.refresh(config)
        config_id = config.id

    async def fake_generate(payload, **kwargs):
        assert payload.goal == "搜索 OmniTest 并验证结果"
        assert kwargs["model"] == "gpt-test-ui"
        return schemas.UICaseAIGenerateResponse(
            draft=schemas.UICaseCreate(
                project_id=payload.project_id,
                name="Google 搜索 OmniTest",
                folder_path="AI生成/搜索",
                target_url=payload.target_url,
                priority="P1",
                tags_json=["AI生成", "ui-case-designer"],
                steps_json=[
                    {"action": "fill", "selector": "textarea[name=q]", "value": "OmniTest"},
                    {"action": "press", "selector": "textarea[name=q]", "value": "Enter"},
                ],
                assertions_json=[{"type": "url_contains", "value": "search"}],
                expect_text="OmniTest",
                generation_mode="ai_skill",
                ai_goal=payload.goal,
                skill_name="ui-case-designer",
                skill_version="1.0.0",
                generation_meta_json={"model": kwargs["model"], "warnings": []},
            ),
            skill_name="ui-case-designer",
            skill_version="1.0.0",
            model=kwargs["model"],
        )

    monkeypatch.setattr(api_module, "generate_ui_case_draft", fake_generate)
    try:
        generated = client.post(
            "/ui-cases/ai/generate",
            json={
                "project_id": project_id,
                "target_url": "https://www.google.com",
                "goal": "搜索 OmniTest 并验证结果",
                "max_steps": 8,
            },
        )
        assert generated.status_code == 200
        draft = generated.json()["draft"]
        assert draft["generation_mode"] == "ai_skill"
        assert draft["review_status"] == "DRAFT"
        assert draft["skill_name"] == "ui-case-designer"

        created = client.post("/ui-cases", json=draft)
        assert created.status_code == 201
        created_payload = created.json()
        assert created_payload["ai_goal"] == "搜索 OmniTest 并验证结果"
        assert created_payload["generation_meta_json"]["model"] == "gpt-test-ui"

        exported = client.get(f"/cases/export?case_type=UI&project_id={project_id}").json()["items"]
        exported_case = next(item for item in exported if item["case_id"] == created_payload["id"])
        assert exported_case["generation_mode"] == "ai_skill"
        assert exported_case["skill_version"] == "1.0.0"
        client.delete(f"/ui-cases/{created_payload['id']}")
    finally:
        with SessionLocal() as db:
            stored = db.get(AIModelConfig, config_id)
            if stored is not None:
                db.delete(stored)
                db.commit()


def test_ui_case_ai_gate_rejects_cross_origin_navigation() -> None:
    from app import schemas
    from app.ui_case_ai import _gate_generated_payload

    request = schemas.UICaseAIGenerateRequest(
        project_id=1,
        target_url="https://www.google.com",
        goal="搜索 OmniTest 并验证结果",
    )
    payload = {
        "name": "越权跳转用例",
        "folder_path": "AI生成",
        "target_url": "https://www.google.com",
        "priority": "P1",
        "expect_text": "OmniTest",
        "tags_json": [],
        "steps_json": [{"action": "goto", "value": "https://evil.example/collect"}],
        "assertions_json": [],
        "design_notes": [],
        "warnings": [],
    }
    try:
        _gate_generated_payload(payload, request, project_base_url="https://www.google.com")
    except ValueError as exc:
        assert "未授权域名" in str(exc)
    else:
        raise AssertionError("cross-origin AI navigation should be rejected")


def test_ui_case_ai_gate_fills_missing_text_values_from_expect_text() -> None:
    from app import schemas
    from app.ui_case_ai import _gate_generated_payload

    request = schemas.UICaseAIGenerateRequest(
        project_id=1,
        target_url="https://example.com",
        goal="等待并验证成功文案",
    )
    payload = {
        "name": "文本等待补全",
        "folder_path": "AI生成",
        "target_url": "https://example.com",
        "priority": "P2",
        "expect_text": "操作成功",
        "tags_json": [],
        "steps_json": [
            {"action": "goto", "value": "https://example.com"},
            {"action": "wait_for_text", "name": "等待结果出现"},
        ],
        "assertions_json": [{"type": "text_visible", "name": "结果可见"}],
        "design_notes": [],
        "warnings": [],
    }

    gated, warnings, _ = _gate_generated_payload(
        payload,
        request,
        project_base_url="https://example.com",
    )

    assert gated["steps_json"][1]["value"] == "操作成功"
    assert gated["assertions_json"][0]["value"] == "操作成功"
    assert len([item for item in warnings if "已使用期望文本" in item]) == 2
    schemas.UICaseCreate(**gated)


def test_ui_case_ai_skill_cannot_bypass_supported_action_schema(monkeypatch) -> None:
    from app import schemas
    import app.ui_case_ai as ui_case_ai

    async def fake_model_call(**kwargs):
        del kwargs
        return json.dumps(
            {
                "name": "非法模型步骤",
                "folder_path": "AI生成",
                "target_url": "https://www.google.com",
                "priority": "P1",
                "expect_text": "OmniTest",
                "tags_json": [],
                "steps_json": [{"action": "execute_script", "value": "alert(1)"}],
                "assertions_json": [],
                "design_notes": [],
                "warnings": [],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(ui_case_ai, "call_json_chat_completion", fake_model_call)
    request = schemas.UICaseAIGenerateRequest(
        project_id=1,
        target_url="https://www.google.com",
        goal="搜索 OmniTest 并验证结果",
    )
    try:
        asyncio.run(
            ui_case_ai.generate_ui_case_draft(
                request,
                project_name="测试项目",
                project_base_url="https://www.google.com",
                model="gpt-test",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
            )
        )
    except ValueError as exc:
        assert "步骤类型不支持" in str(exc)
    else:
        raise AssertionError("unsupported AI action should fail the existing UI case schema")


def test_ui_case_precheck_includes_assertion_variables(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    created = client.post(
        "/ui-cases",
        json={
            "project_id": project_id,
            "name": f"断言变量预检_{time.time_ns()}",
            "target_url": "http://frontend:3000",
            "steps_json": [],
            "assertions_json": [{"type": "text_visible", "value": "{{missing_ui_text}}"}],
            "expect_text": "登录",
        },
    )
    assert created.status_code == 201

    precheck = client.get(f"/executions/ui/{created.json()['id']}/precheck")
    assert precheck.status_code == 200
    assert precheck.json()["is_valid"] is False
    assert "missing_ui_text" in precheck.json()["missing_variables"]


def test_ui_case_auto_navigates_executes_assertions_and_filters_runs(client, monkeypatch) -> None:
    from app.tasks import executions

    observed = {"goto": [], "filled": [], "wait_for_function": []}

    class FakeLocator:
        def __init__(self, selector):
            self.selector = selector
            self.first = self

        def wait_for(self, timeout=None, state=None):
            return None

        def fill(self, value="", timeout=None):
            observed["filled"].append((self.selector, value))

    class FakePage:
        def __init__(self):
            self.url = "about:blank"

        def goto(self, value, wait_until=None, timeout=None):
            observed["goto"].append(value)
            self.url = value

        def locator(self, selector):
            return FakeLocator(selector)

        def wait_for_function(self, expression, *, arg=None, timeout=None):
            observed["wait_for_function"].append((expression, arg, timeout))
            assert arg in self.url

        def screenshot(self, full_page=True, **kwargs):
            return b"fake-image"

    class FakeContext:
        def new_page(self):
            return FakePage()

        def close(self):
            return None

    class FakeBrowser:
        def new_context(self, viewport=None):
            return FakeContext()

        def close(self):
            return None

    class FakeManager:
        def __enter__(self):
            chromium = type("FakeChromium", (), {"launch": lambda self, headless=True: FakeBrowser()})()
            return type("FakePlaywright", (), {"chromium": chromium})()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(executions, "sync_playwright", lambda: FakeManager())

    project_id = client.get("/projects").json()[0]["id"]
    created = client.post(
        "/ui-cases",
        json={
            "project_id": project_id,
            "name": f"结构化 UI 用例_{time.time_ns()}",
            "target_url": "http://frontend:3000/login",
            "steps_json": [{"action": "fill", "selector": "#username", "value": "tester"}],
            "assertions_json": [
                {"type": "selector_visible", "selector": "#username"},
                {"type": "url_contains", "value": "frontend:3000"},
            ],
            "expect_text": "登录",
        },
    )
    assert created.status_code == 201
    case_id = created.json()["id"]
    assert client.get(f"/ui-cases/{case_id}").status_code == 200
    exported = client.get(f"/cases/export?case_type=UI&project_id={project_id}").json()["items"]
    exported_case = next(item for item in exported if item["case_id"] == case_id)
    assert exported_case["steps_json"] == [
        {"action": "fill", "selector": "#username", "value": "tester"}
    ]
    assert exported_case["assertions_json"] == [
        {"type": "selector_visible", "selector": "#username"},
        {"type": "url_contains", "value": "frontend:3000"},
    ]
    assert exported_case["expect_text"] == "登录"

    trigger = client.post(f"/executions/ui/{case_id}/run")
    assert trigger.status_code == 200
    run = client.get(f"/executions/runs/{trigger.json()['id']}").json()
    assert run["status"] == "SUCCESS"
    assert observed["goto"] == ["http://frontend:3000/login"]
    assert observed["filled"] == [("#username", "tester")]
    assert len(observed["wait_for_function"]) == 1
    expression, argument, timeout = observed["wait_for_function"][0]
    assert expression == "expected => window.location.href.includes(expected)"
    assert argument == "frontend:3000"
    assert timeout > 0
    assert any(step["detail"].get("kind") == "assertion" for step in run["step_results_json"])

    filtered = client.get(f"/executions/runs?case_type=UI&case_id={case_id}&limit=10")
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [run["id"]]


def test_performance_case_run_and_rerun(client) -> None:
    performance_cases = client.get("/performance-cases").json()
    case_id = next(case["id"] for case in performance_cases if case["name"] == "示例健康检查压测")

    precheck_response = client.get(f"/executions/perf/{case_id}/precheck")
    assert precheck_response.status_code == 200
    assert precheck_response.json()["target_type"] == "PERF"

    trigger = client.post(f"/executions/perf/{case_id}/run", json={"timeout_seconds": 30})
    assert trigger.status_code == 200
    run_id = trigger.json()["id"]

    run_payload = client.get(f"/executions/runs/{run_id}").json()
    assert run_payload["case_type"] == "PERF"
    assert run_payload["status"] in {"SUCCESS", "FAILED"}
    assert run_payload["response_payload"]["avg_response_ms"] >= 0
    assert run_payload["response_payload"]["p95_response_ms"] >= 0
    assert "throughput_rps" in run_payload["response_payload"]
    artifact_names = [item["name"] for item in run_payload["artifacts_json"]]
    assert "performance-summary.json" in artifact_names
    assert "performance-results.json" in artifact_names
    assert any(step["name"] == "performance_summary" for step in run_payload["step_results_json"])

    rerun_response = client.post(f"/executions/runs/{run_id}/rerun")
    assert rerun_response.status_code == 200
    assert rerun_response.json()["case_type"] == "PERF"


def test_defect_record_can_link_report_and_failure_run(client) -> None:
    plans = client.get("/test-plans").json()
    plan_id = next(plan["id"] for plan in plans if plan["name"] == "演示回归计划")
    trigger = client.post(f"/test-plans/{plan_id}/run", json={"timeout_seconds": 9})
    assert trigger.status_code == 200
    plan_run_id = trigger.json()["id"]

    report_payload = client.get(f"/reports/{plan_run_id}").json()
    failure_run_id = next((item["id"] for item in report_payload["test_runs"] if item["status"] != "SUCCESS"), report_payload["test_runs"][0]["id"])
    project_id = report_payload["plan_run"]["project_id"]

    create_response = client.post(
        "/defects",
        json={
            "project_id": project_id,
            "plan_run_id": plan_run_id,
            "run_id": failure_run_id,
            "title": "登录页失败缺陷",
            "platform": "JIRA",
            "external_key": "QA-123",
            "external_url": "https://jira.example.com/browse/QA-123",
            "status": "OPEN",
            "severity": "P1",
            "summary": "执行失败，需排查"
        },
    )
    assert create_response.status_code == 201
    defect_id = create_response.json()["id"]

    list_response = client.get(f"/defects?plan_run_id={plan_run_id}")
    assert list_response.status_code == 200
    assert any(item["id"] == defect_id for item in list_response.json())

    report_response = client.get(f"/reports/{plan_run_id}")
    assert report_response.status_code == 200
    assert any(item["id"] == defect_id for item in report_response.json()["defects"])


def test_plan_run_report(client) -> None:
    from sqlalchemy import select, update

    from app.core.database import SessionLocal
    from app.models import TestPlanRun

    plans = client.get("/test-plans").json()
    plan_id = next(plan["id"] for plan in plans if plan["name"] == "演示回归计划")
    trigger = client.post(f"/test-plans/{plan_id}/run", json={"timeout_seconds": 9, "max_retries": 1})
    assert trigger.status_code == 200
    plan_run_id = trigger.json()["id"]

    report_payload = None
    for _ in range(60):
        report_payload = client.get(f"/reports/{plan_run_id}").json()
        if report_payload["plan_run"]["status"] in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT"}:
            break
        time.sleep(2)

    assert report_payload is not None
    assert report_payload["plan_run"]["status"] in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT"}, report_payload
    total = report_payload["plan_run"]["total_count"]
    pass_count = report_payload["plan_run"]["pass_count"]
    fail_count = report_payload["plan_run"]["fail_count"]
    assert total == pass_count + fail_count
    with SessionLocal() as db:
        from app.models import TestRun

        child_runs = db.scalars(select(TestRun).where(TestRun.plan_run_id == plan_run_id)).all()
        assert child_runs
        assert all(run.timeout_seconds == 9 for run in child_runs)
        assert all(run.max_retries == 1 for run in child_runs)
        db.execute(update(TestPlanRun).where(TestPlanRun.id == plan_run_id).values(retry_count=None))
        db.commit()

    list_response = client.get("/reports")
    assert list_response.status_code == 200
    list_item = next(item for item in list_response.json() if item["id"] == plan_run_id)
    assert isinstance(list_item["failure_reason_counts"], dict)
    assert isinstance(list_item["failure_reason_summary"], list)

    insights_response = client.get("/reports/insights")
    assert insights_response.status_code == 200
    insights_payload = insights_response.json()
    assert insights_payload["report_count"] >= 1
    assert "recent_trend" in insights_payload
    assert "plan_histories" in insights_payload
    assert any(item["plan_run_id"] == plan_run_id for item in insights_payload["recent_trend"])
    assert any(item["plan_id"] == plan_id for item in insights_payload["plan_histories"])

    refreshed_report_payload = client.get(f"/reports/{plan_run_id}").json()
    assert "recent_history" in refreshed_report_payload
    assert any(item["plan_run_id"] == plan_run_id for item in refreshed_report_payload["recent_history"])

    download_json = client.get(f"/reports/{plan_run_id}/download?format=json")
    assert download_json.status_code == 200
    assert download_json.headers.get("content-type", "").startswith("application/json")
    download_junit = client.get(f"/reports/{plan_run_id}/download?format=junit")
    assert download_junit.status_code == 200
    assert download_junit.headers.get("content-type", "").startswith("application/xml")


def test_api_case_auto_retry_until_success(client, monkeypatch) -> None:
    from app.tasks import executions

    api_cases = client.get("/api-cases").json()
    case_id = next(case["id"] for case in api_cases if case["name"] == "示例健康检查接口")
    call_count = {"value": 0}

    def flaky_execute(db, run, case, project, deadline=None):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return {
                "status": "FAILED",
                "summary": "首次失败",
                "error_type": "ASSERTION",
                "exit_code": 1,
                "stdout_text": "attempt-1",
                "stderr_text": "boom",
                "artifacts_json": [],
                "step_results_json": [],
                "request_payload": {"attempt": 1},
                "response_payload": {"ok": False},
            }
        return {
            "status": "SUCCESS",
            "summary": "第二次成功",
            "exit_code": 0,
            "stdout_text": "attempt-2",
            "stderr_text": "",
            "artifacts_json": [],
            "step_results_json": [],
            "request_payload": {"attempt": 2},
            "response_payload": {"ok": True},
        }

    monkeypatch.setattr(executions, "_execute_api_case", flaky_execute)

    trigger = client.post(f"/executions/api/{case_id}/run", json={"max_retries": 1})
    assert trigger.status_code == 200
    payload = client.get(f"/executions/runs/{trigger.json()['id']}").json()
    assert payload["status"] == "SUCCESS"
    assert payload["retry_count"] == 1
    assert payload["max_retries"] == 1
    assert "重试轨迹" in payload["summary"]


def test_api_case_auto_retry_exhausted(client, monkeypatch) -> None:
    from app.tasks import executions

    api_cases = client.get("/api-cases").json()
    case_id = next(case["id"] for case in api_cases if case["name"] == "示例健康检查接口")
    call_count = {"value": 0}

    def always_fail(db, run, case, project, deadline=None):
        call_count["value"] += 1
        return {
            "status": "FAILED",
            "summary": f"失败-{call_count['value']}",
            "error_type": "ASSERTION",
            "exit_code": 1,
            "stdout_text": f"attempt-{call_count['value']}",
            "stderr_text": "failed",
            "artifacts_json": [],
            "step_results_json": [],
            "request_payload": {"attempt": call_count["value"]},
            "response_payload": {"ok": False},
        }

    monkeypatch.setattr(executions, "_execute_api_case", always_fail)

    trigger = client.post(f"/executions/api/{case_id}/run", json={"max_retries": 2})
    assert trigger.status_code == 200
    payload = client.get(f"/executions/runs/{trigger.json()['id']}").json()
    assert payload["status"] == "FAILED"
    assert payload["retry_count"] == 2
    assert payload["max_retries"] == 2
    assert "第1次FAILED" in payload["summary"]
    assert "第2次FAILED" in payload["summary"]


def test_api_case_pytest_timeout_honors_run_timeout(client, monkeypatch) -> None:
    from app.core.config import settings
    from app.tasks import executions

    api_cases = client.get("/api-cases").json()
    case_id = next(case["id"] for case in api_cases if case["name"] == "示例健康检查接口")
    original_engine = settings.execution_engine
    settings.execution_engine = "pytest"

    observed = {}

    class DummyResult:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_subprocess_run(*args, **kwargs):
        observed["timeout"] = kwargs.get("timeout")
        # 新版 pytest 引擎约定：脚本把响应事实写入 RESULT_PATH，断言由父进程求值
        result_path = (kwargs.get("env") or {}).get("RESULT_PATH")
        if result_path:
            with open(result_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {"status_code": 200, "headers": {}, "duration_ms": 5, "body_text": "{}"},
                    handle,
                )
        return DummyResult()

    monkeypatch.setattr(executions.subprocess, "run", fake_subprocess_run)
    try:
        trigger = client.post(f"/executions/api/{case_id}/run", json={"timeout_seconds": 3})
        assert trigger.status_code == 200
        payload = client.get(f"/executions/runs/{trigger.json()['id']}").json()
        assert payload["status"] == "SUCCESS"
        assert observed["timeout"] <= 3.0
        assert observed["timeout"] > 0
    finally:
        settings.execution_engine = original_engine


def test_ui_case_timeout_uses_total_deadline(client, monkeypatch) -> None:
    from app.tasks import executions

    ui_cases = client.get("/ui-cases").json()
    case_id = next(case["id"] for case in ui_cases if case["name"] == "示例前端首页巡检")
    observed = {"timeouts": []}

    class DummyLocator:
        def __init__(self, timeout_log):
            self.timeout_log = timeout_log
            self.first = self

        def wait_for(self, timeout=None, state=None):
            if timeout is not None:
                self.timeout_log.append(timeout)

        def click(self, timeout=None):
            if timeout is not None:
                self.timeout_log.append(timeout)

        def fill(self, value="", timeout=None):
            if timeout is not None:
                self.timeout_log.append(timeout)

    class DummyPage:
        def __init__(self, timeout_log):
            self.timeout_log = timeout_log

        def goto(self, value, wait_until=None, timeout=None):
            if timeout is not None:
                self.timeout_log.append(timeout)
            time.sleep(0.7)

        def locator(self, selector):
            return DummyLocator(self.timeout_log)

        def screenshot(self, full_page=True, **kwargs):
            return b"fake-image"

    class DummyContext:
        def __init__(self, timeout_log):
            self.timeout_log = timeout_log

        def new_page(self):
            return DummyPage(self.timeout_log)

        def close(self):
            return None

    class DummyBrowser:
        def __init__(self, timeout_log):
            self.timeout_log = timeout_log

        def new_context(self, viewport=None):
            return DummyContext(self.timeout_log)

        def close(self):
            return None

    class DummyPlaywright:
        def __init__(self, timeout_log):
            self.chromium = self
            self.timeout_log = timeout_log

        def launch(self, headless=True):
            return DummyBrowser(self.timeout_log)

    class DummyManager:
        def __init__(self, timeout_log):
            self.timeout_log = timeout_log

        def __enter__(self):
            return DummyPlaywright(self.timeout_log)

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(executions, "sync_playwright", lambda: DummyManager(observed["timeouts"]))

    trigger = client.post(f"/executions/ui/{case_id}/run", json={"timeout_seconds": 1})
    assert trigger.status_code == 200
    payload = client.get(f"/executions/runs/{trigger.json()['id']}").json()
    assert payload["status"] in {"SUCCESS", "TIMEOUT", "ERROR"}
    assert observed["timeouts"]
    assert max(observed["timeouts"]) <= 1000


def test_api_case_missing_template_variable_fails_with_clear_message(client) -> None:
    from app.core.database import SessionLocal
    from app.models import APICase, Environment

    api_cases = client.get("/api-cases").json()
    case_id = next(case["id"] for case in api_cases if case["name"] == "示例健康检查接口")
    environments = client.get("/environments").json()
    environment_id = next(env["id"] for env in environments if env["name"] == "本地环境")

    with SessionLocal() as db:
        case = db.get(APICase, case_id)
        env = db.get(Environment, environment_id)
        assert case is not None
        assert env is not None
        original_path = case.path
        original_variables = env.variables_json
        original_auth_config = env.auth_config_json
        case.path = "/api/v1/{{missing_token}}/health"
        env.variables_json = {"frontend_url": "http://frontend:3000"}
        env.auth_config_json = None
        db.commit()

    try:
        precheck = client.get(f"/executions/api/{case_id}/precheck?environment_id={environment_id}")
        assert precheck.status_code == 200
        assert precheck.json()["is_valid"] is False
        assert "missing_token" in precheck.json()["missing_variables"]
        trigger = client.post(f"/executions/api/{case_id}/run", json={"environment_id": environment_id})
        assert trigger.status_code == 400
        assert trigger.json()["detail"] == "执行预检失败：存在缺失变量：1 个API 用例"
    finally:
        with SessionLocal() as db:
            case = db.get(APICase, case_id)
            env = db.get(Environment, environment_id)
            assert case is not None
            assert env is not None
            case.path = original_path
            env.variables_json = original_variables
            env.auth_config_json = original_auth_config
            db.commit()


def test_api_case_precheck_blocks_trigger_when_environment_variables_missing(client) -> None:
    from app.core.database import SessionLocal
    from app.models import APICase, Environment

    api_cases = client.get("/api-cases").json()
    case_id = next(case["id"] for case in api_cases if case["name"] == "示例健康检查接口")
    environments = client.get("/environments").json()
    environment_id = next(env["id"] for env in environments if env["name"] == "本地环境")

    with SessionLocal() as db:
        case = db.get(APICase, case_id)
        env = db.get(Environment, environment_id)
        assert case is not None
        assert env is not None
        original_path = case.path
        original_variables = env.variables_json
        original_auth_config = env.auth_config_json
        case.path = "/api/v1/{{missing_from_precheck}}/health"
        env.variables_json = {"frontend_url": "http://frontend:3000"}
        env.auth_config_json = None
        db.commit()

    try:
        precheck_response = client.get(f"/executions/api/{case_id}/precheck?environment_id={environment_id}")
        assert precheck_response.status_code == 200
        assert precheck_response.json()["is_valid"] is False
        trigger = client.post(f"/executions/api/{case_id}/run", json={"environment_id": environment_id})
        assert trigger.status_code == 400
        assert "执行预检失败" in trigger.json()["detail"]
    finally:
        with SessionLocal() as db:
            case = db.get(APICase, case_id)
            env = db.get(Environment, environment_id)
            assert case is not None
            assert env is not None
            case.path = original_path
            env.variables_json = original_variables
            env.auth_config_json = original_auth_config
            db.commit()


def test_api_case_rerun_is_blocked_when_environment_variables_missing(client) -> None:
    from app.core.database import SessionLocal
    from app.models import APICase, Environment

    api_cases = client.get("/api-cases").json()
    case_id = next(case["id"] for case in api_cases if case["name"] == "示例健康检查接口")
    trigger = client.post(f"/executions/api/{case_id}/run")
    assert trigger.status_code == 200
    run_id = trigger.json()["id"]

    environments = client.get("/environments").json()
    environment_id = next(env["id"] for env in environments if env["name"] == "本地环境")

    with SessionLocal() as db:
        case = db.get(APICase, case_id)
        env = db.get(Environment, environment_id)
        assert case is not None
        assert env is not None
        original_path = case.path
        original_variables = env.variables_json
        original_auth_config = env.auth_config_json
        case.path = "/api/v1/{{rerun_missing}}/health"
        env.variables_json = {"frontend_url": "http://frontend:3000"}
        env.auth_config_json = None
        db.commit()

    try:
        with SessionLocal() as db:
            from app.models import TestRun

            run = db.get(TestRun, run_id)
            assert run is not None
            run.environment_id = environment_id
            db.commit()

        rerun_response = client.post(f"/executions/runs/{run_id}/rerun")
        assert rerun_response.status_code == 400
        assert "执行预检失败" in rerun_response.json()["detail"]
    finally:
        with SessionLocal() as db:
            case = db.get(APICase, case_id)
            env = db.get(Environment, environment_id)
            assert case is not None
            assert env is not None
            case.path = original_path
            env.variables_json = original_variables
            env.auth_config_json = original_auth_config
            db.commit()


def test_plan_precheck_aggregates_multiple_case_issues(client) -> None:
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import APICase, Environment, UICase

    plans = client.get("/test-plans").json()
    plan_id = next(plan["id"] for plan in plans if plan["name"] == "演示回归计划")
    environments = client.get("/environments").json()
    environment_id = next(env["id"] for env in environments if env["name"] == "本地环境")

    with SessionLocal() as db:
        api_case = db.scalar(select(APICase).where(APICase.name == "示例健康检查接口"))
        ui_case = db.scalar(select(UICase).where(UICase.name == "示例前端首页巡检"))
        env = db.get(Environment, environment_id)
        assert api_case is not None
        assert ui_case is not None
        assert env is not None
        original_api_path = api_case.path
        original_ui_target = ui_case.target_url
        original_variables = env.variables_json
        original_auth_config = env.auth_config_json
        api_case.path = "/api/v1/{{plan_api_missing}}/health"
        ui_case.target_url = "{{plan_ui_missing}}"
        env.variables_json = {"frontend_url": "http://frontend:3000"}
        env.auth_config_json = None
        db.commit()

    try:
        response = client.get(f"/test-plans/{plan_id}/precheck?environment_id={environment_id}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["is_valid"] is False
        assert payload["issue_count"] >= 2
        assert payload["scope_counts"]["api_case"] >= 1
        assert payload["scope_counts"]["ui_case"] >= 1
        assert "plan_api_missing" in payload["missing_variables"]
        assert "plan_ui_missing" in payload["missing_variables"]
    finally:
        with SessionLocal() as db:
            api_case = db.scalar(select(APICase).where(APICase.name == "示例健康检查接口"))
            ui_case = db.scalar(select(UICase).where(UICase.name == "示例前端首页巡检"))
            env = db.get(Environment, environment_id)
            assert api_case is not None
            assert ui_case is not None
            assert env is not None
            api_case.path = original_api_path
            ui_case.target_url = original_ui_target
            env.variables_json = original_variables
            env.auth_config_json = original_auth_config
            db.commit()


def test_unified_case_center_lists_and_filters_cases(client) -> None:
    create_response = client.post(
        "/api-cases",
        json={
            "project_id": client.get("/projects").json()[0]["id"],
            "name": f"统一中心筛选_{time.time_ns()}",
            "folder_path": "冒烟测试/登录模块",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P1",
            "status": "ACTIVE",
            "tags_json": ["smoke", "login"],
            "expected_status": 200,
        },
    )
    assert create_response.status_code == 201

    response = client.get("/cases")
    assert response.status_code == 200
    payload = response.json()
    assert any(item["case_type"] == "API" for item in payload)
    assert any(item["case_type"] == "UI" for item in payload)

    api_only = client.get("/cases?case_type=API")
    assert api_only.status_code == 200
    assert api_only.json()
    assert all(item["case_type"] == "API" for item in api_only.json())

    active_cases = client.get("/cases?status=ACTIVE")
    assert active_cases.status_code == 200
    assert active_cases.json()
    assert all(item["status"] == "ACTIVE" for item in active_cases.json())

    folder_cases = client.get("/cases?folder_path=登录模块")
    assert folder_cases.status_code == 200
    assert folder_cases.json()
    assert any(item["folder_path"] == "冒烟测试/登录模块" for item in folder_cases.json())

    any_tag_cases = client.get("/cases?tags=smoke,not_exists&tag_mode=ANY")
    assert any_tag_cases.status_code == 200
    assert any(item["name"] == create_response.json()["name"] for item in any_tag_cases.json())

    all_tag_cases = client.get("/cases?tags=smoke,login&tag_mode=ALL")
    assert all_tag_cases.status_code == 200
    assert any(item["name"] == create_response.json()["name"] for item in all_tag_cases.json())


def test_case_folder_tree_lists_nested_paths(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    create_response = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"目录树用例_{time.time_ns()}",
            "folder_path": "核心回归/登录/短信登录",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "APPROVED",
            "expected_status": 200,
        },
    )
    assert create_response.status_code == 201

    response = client.get(f"/cases/folders?project_id={project_id}&case_type=API")
    assert response.status_code == 200
    payload = response.json()
    assert payload
    root = next((item for item in payload if item["path"] == "核心回归"), None)
    assert root is not None
    assert root["count"] >= 1
    child = next((item for item in root["children"] if item["path"] == "核心回归/登录"), None)
    assert child is not None
    leaf = next((item for item in child["children"] if item["path"] == "核心回归/登录/短信登录"), None)
    assert leaf is not None
    assert leaf["count"] >= 1


def test_case_export_and_import_json(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    imported_ui_name = f"导入UI_{time.time_ns()}"
    exported = client.get(f"/cases/export?project_id={project_id}&case_type=API")
    assert exported.status_code == 200
    payload = exported.json()
    assert "items" in payload

    imported = client.post(
        "/cases/import",
        json={
            "items": [
                {
                    "case_type": "API",
                    "project_id": project_id,
                    "name": f"导入接口_{time.time_ns()}",
                    "method": "GET",
                    "path": "/api/v1/system/health",
                    "priority": "P1",
                    "status": "ACTIVE",
                    "review_status": "APPROVED",
                    "expected_status": 200,
                },
                {
                    "case_type": "UI",
                    "project_id": project_id,
                    "name": imported_ui_name,
                    "target_url": "http://frontend:3000/login",
                    "steps_json": [{"action": "goto", "value": "http://frontend:3000/login"}],
                    "expect_text": "登录",
                    "engine": "midscene",
                    "priority": "P2",
                    "status": "ACTIVE",
                    "review_status": "DRAFT",
                },
            ]
        },
    )
    assert imported.status_code == 200
    assert imported.json()["affected_count"] == 2
    imported_ui = next(
        item for item in client.get("/ui-cases", params={"project_id": project_id}).json()
        if item["name"] == imported_ui_name
    )
    assert imported_ui["engine"] == "midscene"


def test_case_batch_move_folder_records_history(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    create_response = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"移动目录用例_{time.time_ns()}",
            "folder_path": "旧目录",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "APPROVED",
            "expected_status": 200,
        },
    )
    assert create_response.status_code == 201
    case_id = create_response.json()["id"]

    moved = client.post(
        "/cases/batch-move-folder",
        json={
            "items": [{"case_type": "API", "case_id": case_id}],
            "folder_path": "新目录/登录",
        },
    )
    assert moved.status_code == 200
    assert moved.json()["affected_count"] == 1

    listed = client.get("/cases?folder_path=新目录/登录")
    assert listed.status_code == 200
    assert any(item["case_type"] == "API" and item["case_id"] == case_id for item in listed.json())

    history = client.get(f"/cases/API/{case_id}/history")
    assert history.status_code == 200
    assert history.json()[0]["action"] == "MOVE_FOLDER"


def test_case_duplicate_detection_groups_matching_entries(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    duplicate_path = f"/api/v1/duplicate-{time.time_ns()}"
    for index in range(2):
        response = client.post(
            "/api-cases",
            json={
                "project_id": project_id,
                "name": f"重复检测用例_{index}_{time.time_ns()}",
                "method": "GET",
                "path": duplicate_path,
                "priority": "P1",
                "status": "ACTIVE",
                "review_status": "APPROVED",
                "expected_status": 200,
            },
        )
        assert response.status_code == 201

    detected = client.get(f"/cases/duplicates?project_id={project_id}&case_type=API")
    assert detected.status_code == 200
    groups = detected.json()
    group = next((item for item in groups if item["duplicate_key"] == f"get {duplicate_path}"), None)
    assert group is not None
    assert group["count"] == 2
    assert {item["case_type"] for item in group["items"]} == {"API"}


def test_case_center_batch_update_and_add_to_plan(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    create_response = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"批量用例_{time.time_ns()}",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P2",
            "status": "ACTIVE",
            "review_status": "APPROVED",
            "expected_status": 200,
        },
    )
    assert create_response.status_code == 201
    api_case_id = create_response.json()["id"]

    batch_update = client.post(
        "/cases/batch-update",
        json={
            "items": [{"case_type": "API", "case_id": api_case_id}],
            "status": "DISABLED",
            "add_tags": ["batch", "core"],
        },
    )
    assert batch_update.status_code == 200
    assert batch_update.json()["affected_count"] == 1

    updated_case = next(item for item in client.get("/cases?case_type=API").json() if item["case_id"] == api_case_id)
    assert updated_case["status"] == "DISABLED"
    assert "batch" in (updated_case["tags_json"] or [])

    plan_id = next(plan["id"] for plan in client.get("/test-plans").json() if plan["project_id"] == project_id)
    batch_add = client.post(
        f"/test-plans/{plan_id}/cases/batch",
        json={
            "items": [{"case_type": "API", "case_id": api_case_id}],
            "order_start": 50,
        },
    )
    assert batch_add.status_code == 200
    assert batch_add.json()["affected_count"] == 1

    plan_cases = client.get(f"/test-plans/{plan_id}/cases")
    assert plan_cases.status_code == 200
    assert any(item["case_id"] == api_case_id and item["case_type"] == "API" for item in plan_cases.json())

    batch_review = client.post(
        "/cases/batch-review",
        json={
            "items": [{"case_type": "API", "case_id": api_case_id}],
            "review_status": "APPROVED",
            "review_note": "批量评审通过",
        },
    )
    assert batch_review.status_code == 200
    assert batch_review.json()["affected_count"] == 1

    reviewed_cases = client.get("/cases?review_status=APPROVED")
    assert reviewed_cases.status_code == 200
    assert any(
        item["case_id"] == api_case_id
        and item["review_status"] == "APPROVED"
        and item["review_note"] == "批量评审通过"
        for item in reviewed_cases.json()
    )


def test_plan_case_review_gate_requires_override_and_records_creator(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    create_response = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"待评审计划用例_{time.time_ns()}",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "IN_REVIEW",
            "version_no": "1.0.0",
            "review_note": "等待计划准入评审",
            "expected_status": 200,
        },
    )
    assert create_response.status_code == 201
    api_case_id = create_response.json()["id"]

    plan_id = next(plan["id"] for plan in client.get("/test-plans").json() if plan["project_id"] == project_id)

    blocked = client.post(
        f"/test-plans/{plan_id}/cases",
        json={
            "case_type": "API",
            "case_id": api_case_id,
            "order_index": 88,
        },
    )
    assert blocked.status_code == 400
    assert "用例未通过评审" in blocked.json()["detail"]

    allowed = client.post(
        f"/test-plans/{plan_id}/cases",
        json={
            "case_type": "API",
            "case_id": api_case_id,
            "order_index": 88,
            "allow_unapproved": True,
        },
    )
    assert allowed.status_code == 201
    payload = allowed.json()
    assert payload["created_by"] is not None

    plan_cases = client.get(f"/test-plans/{plan_id}/cases")
    assert plan_cases.status_code == 200
    created = next(item for item in plan_cases.json() if item["case_id"] == api_case_id and item["case_type"] == "API")
    assert created["created_by"] == payload["created_by"]
    assert created["case_snapshot_json"]["review_status"] == "IN_REVIEW"
    assert created["case_snapshot_json"]["review_note"] == "等待计划准入评审"


def test_plan_cases_reorder_updates_order_index(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    plan_id = next(plan["id"] for plan in client.get("/test-plans").json() if plan["project_id"] == project_id)

    first = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"重排用例A_{time.time_ns()}",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "APPROVED",
            "expected_status": 200,
        },
    )
    second = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"重排用例B_{time.time_ns()}",
            "method": "GET",
            "path": "/api/v1/system/info",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "APPROVED",
            "expected_status": 200,
        },
    )
    assert first.status_code == 201
    assert second.status_code == 201
    first_case_id = first.json()["id"]
    second_case_id = second.json()["id"]

    add_first = client.post(
        f"/test-plans/{plan_id}/cases",
        json={"case_type": "API", "case_id": first_case_id, "order_index": 10},
    )
    add_second = client.post(
        f"/test-plans/{plan_id}/cases",
        json={"case_type": "API", "case_id": second_case_id, "order_index": 20},
    )
    assert add_first.status_code == 201
    assert add_second.status_code == 201

    reorder = client.post(
        f"/test-plans/{plan_id}/cases/reorder",
        json={
            "items": [
                {"id": add_first.json()["id"], "order_index": 2},
                {"id": add_second.json()["id"], "order_index": 1},
            ]
        },
    )
    assert reorder.status_code == 200
    assert reorder.json()["affected_count"] == 2

    listed = client.get(f"/test-plans/{plan_id}/cases")
    assert listed.status_code == 200
    latest = [
        item for item in listed.json() if item["id"] in {add_first.json()["id"], add_second.json()["id"]}
    ]
    assert [item["id"] for item in latest] == [add_second.json()["id"], add_first.json()["id"]]


def test_case_history_tracks_create_update_and_review(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    create_response = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"历史用例_{time.time_ns()}",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P2",
            "status": "ACTIVE",
            "review_status": "DRAFT",
            "version_no": "1.0.0",
            "expected_status": 200,
        },
    )
    assert create_response.status_code == 201
    case_id = create_response.json()["id"]

    update_response = client.put(
        f"/api-cases/{case_id}",
        json={
            "project_id": project_id,
            "name": create_response.json()["name"],
            "folder_path": "历史追踪/接口",
            "method": "GET",
            "path": "/api/v1/system/info",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "IN_REVIEW",
            "version_no": "1.0.0",
            "review_note": "提交评审",
            "tags_json": ["history"],
            "headers_json": None,
            "body_json": None,
            "assertions_json": None,
            "expected_status": 200,
        },
    )
    assert update_response.status_code == 200

    batch_review = client.post(
        "/cases/batch-review",
        json={
            "items": [{"case_type": "API", "case_id": case_id}],
            "review_status": "APPROVED",
            "review_note": "评审通过",
        },
    )
    assert batch_review.status_code == 200

    history_response = client.get(f"/cases/API/{case_id}/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert [item["action"] for item in history[:3]] == ["BATCH_REVIEW", "UPDATE", "CREATE"]
    assert history[0]["review_status"] == "APPROVED"
    assert history[0]["review_note"] == "评审通过"
    assert history[1]["version_no"] == "1.0.1"


def test_api_case_update_bumps_version_and_review_status(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    create_response = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"编辑用例_{time.time_ns()}",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P2",
            "status": "ACTIVE",
            "review_status": "DRAFT",
            "version_no": "1.0.0",
            "expected_status": 200,
        },
    )
    assert create_response.status_code == 201
    case_id = create_response.json()["id"]

    update_response = client.put(
        f"/api-cases/{case_id}",
        json={
            "project_id": project_id,
            "name": create_response.json()["name"],
            "folder_path": "核心回归/系统接口",
            "method": "GET",
            "path": "/api/v1/system/info",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "IN_REVIEW",
            "version_no": "1.0.0",
            "review_note": "接口字段已调整，等待复核",
            "tags_json": ["core"],
            "headers_json": None,
            "body_json": None,
            "assertions_json": None,
            "expected_status": 200,
        },
    )
    assert update_response.status_code == 200
    payload = update_response.json()
    # 评审状态不再允许通过 PUT 直接写入
    assert payload["review_status"] == "DRAFT"
    assert payload["version_no"] == "1.0.1"
    assert payload["path"] == "/api/v1/system/info"


def test_ui_case_update_bumps_version_and_review_status(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    create_response = client.post(
        "/ui-cases",
        json={
            "project_id": project_id,
            "name": f"UI编辑用例_{time.time_ns()}",
            "target_url": "http://frontend:3000",
            "review_status": "DRAFT",
            "version_no": "1.0.0",
            "expect_text": "自动化测试平台",
            "steps_json": [{"action": "goto", "value": "http://frontend:3000"}],
        },
    )
    assert create_response.status_code == 201
    case_id = create_response.json()["id"]

    update_response = client.put(
        f"/ui-cases/{case_id}",
        json={
            "project_id": project_id,
            "name": create_response.json()["name"],
            "folder_path": "UI回归/首页",
            "target_url": "http://frontend:3000/login",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "APPROVED",
            "version_no": "1.0.0",
            "tags_json": ["ui"],
            "assertions_json": None,
            "steps_json": [{"action": "goto", "value": "http://frontend:3000/login"}],
            "expect_text": "登录",
        },
    )
    assert update_response.status_code == 200
    payload = update_response.json()
    # 评审状态不再允许通过 PUT 直接写入
    assert payload["review_status"] == "DRAFT"
    assert payload["version_no"] == "1.0.1"
    assert payload["target_url"].endswith("/login")


def test_performance_case_update_bumps_version_and_review_status(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    create_response = client.post(
        "/performance-cases",
        json={
            "project_id": project_id,
            "name": f"性能编辑用例_{time.time_ns()}",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P2",
            "status": "ACTIVE",
            "review_status": "DRAFT",
            "version_no": "1.0.0",
            "expected_status": 200,
            "concurrency": 5,
            "total_requests": 20,
            "max_avg_response_ms": 1500,
            "max_p95_response_ms": 2500,
            "max_error_rate": 0.1,
        },
    )
    assert create_response.status_code == 201
    case_id = create_response.json()["id"]

    update_response = client.put(
        f"/performance-cases/{case_id}",
        json={
            "project_id": project_id,
            "name": create_response.json()["name"],
            "folder_path": "性能基线/系统接口",
            "method": "POST",
            "path": "/api/v1/system/info",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "IN_REVIEW",
            "version_no": "1.0.0",
            "tags_json": ["perf"],
            "headers_json": None,
            "body_json": None,
            "expected_status": 200,
            "concurrency": 8,
            "total_requests": 30,
            "max_avg_response_ms": 1200,
            "max_p95_response_ms": 2200,
            "max_error_rate": 0.05,
        },
    )
    assert update_response.status_code == 200
    payload = update_response.json()
    # 评审状态不再允许通过 PUT 直接写入
    assert payload["review_status"] == "DRAFT"
    assert payload["version_no"] == "1.0.1"
    assert payload["method"] == "POST"


def test_case_generation_model_registry_is_backend_owned(client) -> None:
    response = client.get("/case-generation/model-options")
    assert response.status_code == 200
    options = response.json()
    assert any(item["value"] == "gpt-5.5" for item in options)
    assert any(item["value"] == "custom-openai-compatible" for item in options)
    assert all(set(item) == {"provider", "label", "value", "base_url"} for item in options)


def test_case_generation_get_detail_is_read_only(client) -> None:
    from app.core.database import SessionLocal
    from app.models import CaseGenerationJob, Project

    with SessionLocal() as db:
        project = db.query(Project).first()
        job = CaseGenerationJob(
            workspace_id=project.workspace_id,
            project_id=project.id,
            name=f"只读详情_{time.time_ns()}",
            mode="MARKDOWN",
            status="RUNNING",
            progress_json={"stages": [{"key": "testcase", "status": "running"}]},
            input_payload_json={"markdown_text": "# 登录\n支持登录"},
            summary="保持运行中",
            error_message="sentinel-error",
            created_by=1,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    response = client.get(f"/case-generation/jobs/{job_id}")
    assert response.status_code == 200
    with SessionLocal() as db:
        persisted = db.get(CaseGenerationJob, job_id)
        assert persisted.status == "RUNNING"
        assert persisted.summary == "保持运行中"
        assert persisted.error_message == "sentinel-error"


def test_case_generation_new_attempt_supersedes_old_and_prevents_late_write() -> None:
    from app.core.database import SessionLocal
    from app.models import CaseGenerationAttempt, CaseGenerationJob, Project
    from app.tasks.case_generation_runtime import bind_attempt, create_attempt, finish_attempt, mark_attempt_running

    with SessionLocal() as db:
        project = db.query(Project).first()
        job = CaseGenerationJob(
            workspace_id=project.workspace_id,
            project_id=project.id,
            name=f"attempt所有权_{time.time_ns()}",
            mode="MARKDOWN",
            status="PENDING",
            progress_json={"stages": []},
            input_payload_json={"markdown_text": "# 登录\n支持登录"},
            summary="初始任务",
            created_by=1,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        first = create_attempt(db, job, pipeline_version="v1")
        mark_attempt_running(db, job, first)
        second = create_attempt(db, job, pipeline_version="v1")
        first_id, second_id, job_id = first.id, second.id, job.id

    with SessionLocal() as db, bind_attempt(first_id, "v1", "old-run"):
        stale_job = db.get(CaseGenerationJob, job_id)
        stale_job.summary = "旧 attempt 晚返回覆盖"
        assert finish_attempt(db, stale_job, status="SUCCESS", summary=stale_job.summary) is False

    with SessionLocal() as db:
        persisted_job = db.get(CaseGenerationJob, job_id)
        persisted_first = db.get(CaseGenerationAttempt, first_id)
        assert persisted_job.active_attempt_id == second_id
        assert persisted_job.status == "PENDING"
        assert persisted_job.summary != "旧 attempt 晚返回覆盖"
        assert persisted_first.status == "SUPERSEDED"
        assert persisted_first.error_message is None


def test_case_generation_watchdog_respects_heartbeat_and_celery_activity(monkeypatch) -> None:
    from datetime import timedelta

    import app.tasks.case_generation_runtime as runtime
    from app.core.database import SessionLocal
    from app.models import CaseGenerationAttempt, CaseGenerationJob, Project
    from app.timeutil import utc_now_naive

    monkeypatch.setattr(runtime.settings, "case_gen_attempt_stale_seconds", 900)
    with SessionLocal() as db:
        project = db.query(Project).first()
        job = CaseGenerationJob(
            workspace_id=project.workspace_id,
            project_id=project.id,
            name=f"watchdog_{time.time_ns()}",
            mode="MARKDOWN",
            status="RUNNING",
            progress_json={"stages": []},
            input_payload_json={"markdown_text": "# 登录\n支持登录"},
            summary="模型调用中",
            created_by=1,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        attempt = runtime.create_attempt(db, job, pipeline_version="v1")
        runtime.mark_attempt_running(db, job, attempt)
        attempt.task_id = "celery-task-live"
        job.task_id = attempt.task_id
        attempt.heartbeat_at = utc_now_naive() - timedelta(minutes=12)
        db.commit()
        attempt_id, job_id = attempt.id, job.id

    monkeypatch.setattr(runtime, "_active_celery_task_ids", lambda: set())
    runtime.reconcile_stale_attempts()
    with SessionLocal() as db:
        assert db.get(CaseGenerationAttempt, attempt_id).status == "RUNNING"

    with SessionLocal() as db:
        attempt = db.get(CaseGenerationAttempt, attempt_id)
        attempt.heartbeat_at = utc_now_naive() - timedelta(minutes=16)
        db.commit()
    monkeypatch.setattr(runtime, "_active_celery_task_ids", lambda: {"celery-task-live"})
    runtime.reconcile_stale_attempts()
    with SessionLocal() as db:
        assert db.get(CaseGenerationAttempt, attempt_id).status == "RUNNING"

    monkeypatch.setattr(runtime, "_active_celery_task_ids", lambda: set())
    assert runtime.reconcile_stale_attempts()["reconciled"] >= 1
    with SessionLocal() as db:
        assert db.get(CaseGenerationAttempt, attempt_id).status == "LOST"
        lost_job = db.get(CaseGenerationJob, job_id)
        assert lost_job.status == "FAILED"
        assert "心跳超时" in lost_job.error_message


def test_secure_fetch_rejects_private_redirect_and_oversized_response(monkeypatch) -> None:
    import socket

    import httpx
    import app.tasks.secure_fetch as secure_fetch

    real_client = httpx.Client

    def fake_getaddrinfo(hostname, *args, **kwargs):
        address = "93.184.216.34" if hostname == "public.example" else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    monkeypatch.setattr(secure_fetch.socket, "getaddrinfo", fake_getaddrinfo)
    redirect_transport = httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"location": "http://localhost/private"}, request=request)
    )
    monkeypatch.setattr(secure_fetch.httpx, "Client", lambda **kwargs: real_client(transport=redirect_transport, timeout=kwargs.get("timeout")))
    try:
        secure_fetch.fetch_resource(
            "https://public.example/start",
            max_bytes=100,
            accepted_prefixes=("text/",),
            timeout_seconds=1,
        )
        assert False, "private redirect must be rejected"
    except secure_fetch.UnsafeURL:
        pass

    large_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * 11, request=request)
    )
    monkeypatch.setattr(secure_fetch.httpx, "Client", lambda **kwargs: real_client(transport=large_transport, timeout=kwargs.get("timeout")))
    try:
        secure_fetch.fetch_resource(
            "https://public.example/large",
            max_bytes=10,
            accepted_prefixes=("text/",),
            timeout_seconds=1,
        )
        assert False, "oversized response must be rejected"
    except secure_fetch.DownloadTooLarge:
        pass


def test_ai_model_config_encrypts_key_at_rest() -> None:
    from app.core.database import SessionLocal
    from app.models import AIModelConfig, Workspace

    secret = f"sk-secret-{time.time_ns()}"
    with SessionLocal() as db:
        workspace = db.query(Workspace).first()
        config = AIModelConfig(
            workspace_id=workspace.id,
            provider="OPENAI",
            name=f"密文配置_{time.time_ns()}",
            base_url="https://api.openai.com/v1",
            model="gpt-5.5",
            api_key=secret,
            is_active=0,
        )
        db.add(config)
        db.commit()
        db.refresh(config)
        config_id = config.id
        assert config._legacy_api_key is None
        assert secret not in config.api_key_encrypted
        assert config.api_key == secret

    with SessionLocal() as db:
        persisted = db.get(AIModelConfig, config_id)
        assert persisted._legacy_api_key is None
        assert persisted.api_key == secret


def test_case_generation_v2_local_rerun_copies_inherited_artifacts(tmp_path, monkeypatch) -> None:
    import app.tasks.case_generation_runtime as runtime
    from app.api import _inherit_case_generation_v2_artifacts
    from app.core.database import SessionLocal
    from app.models import CaseGenerationV2Artifact, CaseGenerationV2Job, Project

    monkeypatch.setattr(runtime.settings, "report_output_dir", str(tmp_path))
    with SessionLocal() as db:
        project = db.query(Project).first()
        job = CaseGenerationV2Job(
            workspace_id=project.workspace_id,
            project_id=project.id,
            name=f"inherit_{time.time_ns()}",
            mode="MARKDOWN",
            status="PENDING",
            progress_json={"stages": []},
            input_payload_json={"pipeline_mode": "trusted"},
            summary="等待执行",
            created_by=1,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        first_attempt = runtime.create_attempt(db, job, pipeline_version="v2")
        first_dir = tmp_path / "case_generation_v2" / f"job_{job.id}" / f"attempt_{first_attempt.id}"
        first_dir.mkdir(parents=True)
        source_file = first_dir / "scope_index.json"
        source_file.write_text('{"source":"old"}', encoding="utf-8")
        db.add(
            CaseGenerationV2Artifact(
                job_id=job.id,
                attempt_id=first_attempt.id,
                artifact_type="scope_index",
                file_name="scope_index.json",
                file_path=str(source_file),
                content_json={"source": "old"},
            )
        )
        db.commit()

        second_attempt = runtime.create_attempt(
            db,
            job,
            pipeline_version="v2",
            kind="source_shard",
            source_id="SRC-001",
        )
        _inherit_case_generation_v2_artifacts(db, job_id=job.id, attempt_id=second_attempt.id)
        inherited = db.scalar(
            select(CaseGenerationV2Artifact).where(
                CaseGenerationV2Artifact.attempt_id == second_attempt.id,
                CaseGenerationV2Artifact.artifact_type == "scope_index",
            )
        )

        assert inherited is not None
        assert inherited.file_path != str(source_file)
        expected_dir = tmp_path / "case_generation_v2" / f"job_{job.id}" / f"attempt_{second_attempt.id}" / "inherited"
        assert Path(inherited.file_path).parent == expected_dir
        assert "legacy" not in Path(inherited.file_path).parts
        assert Path(inherited.file_path).read_text(encoding="utf-8") == '{"source":"old"}'
        assert source_file.exists()


def test_case_generation_retention_expires_content_and_removes_orphans(tmp_path, monkeypatch) -> None:
    import os
    from datetime import timedelta

    import app.tasks.case_generation_runtime as runtime
    from app.core.database import SessionLocal
    from app.models import CaseGenerationArtifact, CaseGenerationJob, Project
    from app.timeutil import utc_now_naive

    monkeypatch.setattr(runtime.settings, "report_output_dir", str(tmp_path))
    monkeypatch.setattr(runtime.settings, "case_gen_artifact_retention_days", 30)
    old_time = utc_now_naive() - timedelta(days=31)
    with SessionLocal() as db:
        project = db.query(Project).first()
        job = CaseGenerationJob(
            workspace_id=project.workspace_id,
            project_id=project.id,
            name=f"retention_{time.time_ns()}",
            mode="MARKDOWN",
            status="SUCCESS",
            progress_json={"stages": []},
            input_payload_json={},
            summary="完成",
            created_by=1,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        attempt = runtime.create_attempt(db, job, pipeline_version="v1")
        artifact_dir = tmp_path / "case_generation" / f"job_{job.id}" / f"attempt_{attempt.id}"
        artifact_dir.mkdir(parents=True)
        artifact_file = artifact_dir / "old.json"
        artifact_file.write_text("{}", encoding="utf-8")
        os.utime(artifact_file, (old_time.timestamp(), old_time.timestamp()))
        artifact = CaseGenerationArtifact(
            job_id=job.id,
            attempt_id=attempt.id,
            artifact_type="review_report",
            file_name="old.json",
            file_path=str(artifact_file),
            content_json={"old": True},
            created_at=old_time,
        )
        db.add(artifact)
        db.commit()
        db.refresh(artifact)
        artifact_id = artifact.id

    orphan = tmp_path / "case_generation" / "job_999999" / "attempt_999999" / "orphan.tmp"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("orphan", encoding="utf-8")
    os.utime(orphan, (old_time.timestamp(), old_time.timestamp()))

    fresh_orphan = tmp_path / "case_generation" / "job_999998" / "attempt_999998" / "fresh.tmp"
    fresh_orphan.parent.mkdir(parents=True)
    fresh_orphan.write_text("fresh", encoding="utf-8")

    result = runtime.expire_old_artifacts()
    assert result["expired"] >= 1
    assert not artifact_file.exists()
    assert not orphan.exists()
    assert fresh_orphan.exists()
    with SessionLocal() as db:
        expired = db.get(CaseGenerationArtifact, artifact_id)
        assert expired.expired_at is not None
        assert expired.file_path is None
        assert expired.content_json is None


def test_case_generation_artifact_detail_is_metadata_only_until_requested(client, tmp_path) -> None:
    from app.core.database import SessionLocal
    from app.models import CaseGenerationArtifact, CaseGenerationJob, Project
    from app.tasks.case_generation_runtime import create_attempt

    with SessionLocal() as db:
        project = db.query(Project).first()
        job = CaseGenerationJob(
            workspace_id=project.workspace_id,
            project_id=project.id,
            name=f"artifact懒加载_{time.time_ns()}",
            mode="MARKDOWN",
            status="SUCCESS",
            progress_json={"stages": []},
            input_payload_json={},
            summary="完成",
            created_by=1,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        attempt = create_attempt(db, job, pipeline_version="v1")
        artifact_file = tmp_path / "review.json"
        artifact_file.write_text('{"ok": true}', encoding="utf-8")
        artifact = CaseGenerationArtifact(
            job_id=job.id,
            attempt_id=attempt.id,
            artifact_type="review_report",
            file_name="review.json",
            file_path=str(artifact_file),
            content_json={"ok": True},
        )
        db.add(artifact)
        db.commit()
        db.refresh(artifact)
        job_id, artifact_id = job.id, artifact.id

    detail = client.get(f"/case-generation/jobs/{job_id}")
    assert detail.status_code == 200
    metadata = next(item for item in detail.json()["artifacts"] if item["id"] == artifact_id)
    assert metadata["content_json"] is None
    assert "file_path" not in metadata

    content = client.get(f"/case-generation/jobs/{job_id}/artifacts/{artifact_id}")
    assert content.status_code == 200
    assert content.json()["content_json"] == {"ok": True}
    assert "file_path" not in content.json()


def test_case_generation_v2_list_filters_pipeline_mode_and_cursor(client) -> None:
    from app.core.database import SessionLocal
    from app.models import CaseGenerationV2Job, Project

    with SessionLocal() as db:
        project = db.query(Project).first()
        created_ids = []
        for pipeline_mode in ("lite", "trusted", "trusted_v2"):
            job = CaseGenerationV2Job(
                workspace_id=project.workspace_id,
                project_id=project.id,
                name=f"过滤_{pipeline_mode}_{time.time_ns()}",
                mode="MARKDOWN",
                status="SUCCESS",
                progress_json={"stages": []},
                input_payload_json={"pipeline_mode": pipeline_mode},
                summary="完成",
                created_by=1,
            )
            db.add(job)
            db.flush()
            created_ids.append(job.id)
        db.commit()
        project_id = project.id

    response = client.get(
        "/case-generation-v2/jobs",
        params={"project_id": project_id, "pipeline_mode": "trusted", "status": "SUCCESS", "limit": 100},
    )
    assert response.status_code == 200
    filtered_ids = {item["id"] for item in response.json()}
    assert created_ids[1] in filtered_ids
    assert created_ids[2] in filtered_ids
    assert created_ids[0] not in filtered_ids

    cursor_response = client.get(
        "/case-generation-v2/jobs",
        params={"project_id": project_id, "before_id": max(created_ids), "limit": 100},
    )
    assert cursor_response.status_code == 200
    assert all(item["id"] < max(created_ids) for item in cursor_response.json())


def test_trusted_source_manifest_records_reproducibility_fields() -> None:
    import hashlib

    from app.tasks.case_generation_runtime import bind_attempt
    from app.tasks.case_generation_v2 import _build_trusted_source_manifest

    markdown = "# 登录\n支持用户名密码登录"
    with bind_attempt(42, "v2", "run-reproducible"):
        manifest = _build_trusted_source_manifest(
            markdown,
            ["https://example.test/login.png"],
            source_url="https://example.test/prd.md",
            model="test-model",
        )

    assert manifest["run_id"] == "run-reproducible"
    assert manifest["attempt_id"] == 42
    assert manifest["content_sha256"] == hashlib.sha256(markdown.encode()).hexdigest()
    assert manifest["content_bytes"] == len(markdown.encode())
    assert manifest["parser_version"]
    assert manifest["model"] == "test-model"
    assert manifest["unified_rules_sha256"]


def test_case_generation_v2_task_failure_is_visible_to_db_and_celery() -> None:
    import pytest

    from app.core.database import SessionLocal
    from app.models import CaseGenerationV2Attempt, CaseGenerationV2Job, Project
    from app.tasks.case_generation_runtime import create_attempt
    from app.tasks.case_generation_v2 import run_case_generation_v2_job

    with SessionLocal() as db:
        project = db.query(Project).first()
        job = CaseGenerationV2Job(
            workspace_id=project.workspace_id,
            project_id=project.id,
            name=f"失败传播_{time.time_ns()}",
            mode="MARKDOWN",
            status="PENDING",
            progress_json={"stages": []},
            input_payload_json={"pipeline_mode": "lite", "markdown_text": ""},
            summary="等待执行",
            created_by=1,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        attempt = create_attempt(db, job, pipeline_version="v2")
        job_id, attempt_id = job.id, attempt.id

    with pytest.raises(ValueError, match="请提供需求文本"):
        run_case_generation_v2_job.run(job_id, attempt_id)

    with SessionLocal() as db:
        failed_job = db.get(CaseGenerationV2Job, job_id)
        failed_attempt = db.get(CaseGenerationV2Attempt, attempt_id)
        assert failed_job.status == "FAILED"
        assert failed_attempt.status == "FAILED"
        assert failed_job.error_message
    assert run_case_generation_v2_job.acks_late is True
    assert run_case_generation_v2_job.reject_on_worker_lost is True


def test_celery_routes_named_execution_tasks_to_execution_queue() -> None:
    from app.core.celery_app import celery_app

    router = celery_app.amqp.Router()
    task_names = (
        "app.tasks.run_api_case",
        "app.tasks.run_ui_case",
        "app.tasks.run_performance_case",
        "app.tasks.run_test_plan",
    )
    for task_name in task_names:
        route = router.route({}, task_name)
        assert route["queue"].name == "execution"


def test_execution_retry_result_preserves_ui_error_and_has_complete_shape() -> None:
    from app.tasks.executions import _execute_case_with_retries

    class FakeDb:
        def commit(self):
            return None

        def refresh(self, run):
            return None

    run = SimpleNamespace(
        id=9876,
        case_type="UI",
        timeout_seconds=30,
        max_retries=0,
        retry_count=0,
    )
    payload = {
        "error": "登录按钮未在超时时间内显示",
        "status": "FAILED",
        "error_type": "ASSERTION",
        "artifacts": [{"name": "ui-failure.png", "path": "/tmp/ui-failure.png", "type": "png"}],
        "steps": [{"name": "登录按钮可见", "status": "FAILED"}],
    }

    def raise_ui_error(deadline):
        raise RuntimeError(json.dumps(payload, ensure_ascii=False))

    result = _execute_case_with_retries(
        FakeDb(),
        run,
        raise_ui_error,
    )

    assert result["status"] == "FAILED"
    assert result["summary"] == "执行失败: 登录按钮未在超时时间内显示"
    assert result["error_type"] == "ASSERTION"
    assert result["request_payload"] is None
    assert result["response_payload"] is None
    assert result["exit_code"] == 1
    assert result["artifacts_json"] == payload["artifacts"]
    assert result["step_results_json"] == payload["steps"]

    timeout_payload = {
        "error": "Command 'ui-case' timed out after 30 seconds",
        "status": "TIMEOUT",
        "error_type": "TIMEOUT",
        "artifacts": [],
        "steps": [],
    }

    def raise_ui_timeout(deadline):
        raise RuntimeError(json.dumps(timeout_payload))

    timeout_result = _execute_case_with_retries(FakeDb(), run, raise_ui_timeout)
    assert timeout_result["status"] == "TIMEOUT"
    assert timeout_result["error_type"] == "TIMEOUT"
    assert timeout_result["exit_code"] == 124

def _make_ui_case_payload(project_id: int, name: str, folder_path: str | None = None) -> dict:
    return {
        "project_id": project_id,
        "name": name,
        "folder_path": folder_path,
        "target_url": "http://frontend:3000",
        "expect_text": "自动化测试平台",
        "steps_json": [{"action": "goto", "value": "http://frontend:3000"}],
    }


def test_ui_case_folder_tree_and_rename(client) -> None:
    project = client.post(
        "/projects",
        json={"name": f"UI目录项目_{time.time_ns()}", "base_url": "http://example.com"},
    ).json()
    project_id = project["id"]
    for name, folder in (
        ("树用例A", "登录/核心流程"),
        ("树用例B", "登录/核心流程/边界"),
        ("树用例C", "商品"),
        ("树用例D", None),
    ):
        response = client.post("/ui-cases", json=_make_ui_case_payload(project_id, f"{name}_{time.time_ns()}", folder))
        assert response.status_code == 201

    tree = client.get(f"/ui-cases/folders?project_id={project_id}")
    assert tree.status_code == 200
    payload = tree.json()
    assert payload["total"] == 4
    assert payload["ungrouped"] == 1
    login_node = next(node for node in payload["folders"] if node["name"] == "登录")
    assert login_node["case_count"] == 2
    core_node = next(child for child in login_node["children"] if child["name"] == "核心流程")
    assert core_node["case_count"] == 2
    assert core_node["children"][0]["name"] == "边界"
    assert core_node["children"][0]["case_count"] == 1

    rename = client.post(
        "/ui-cases/folders/rename",
        json={"project_id": project_id, "old_path": "登录/核心流程", "new_path": "登录/主流程"},
    )
    assert rename.status_code == 200
    assert rename.json()["affected"] == 2
    renamed = client.get(
        f"/ui-cases?project_id={project_id}&page=1&page_size=50&folder=登录/主流程"
    ).json()
    assert renamed["total"] == 2
    assert {item["folder_path"] for item in renamed["items"]} == {"登录/主流程", "登录/主流程/边界"}


def test_ui_cases_pagination_and_filters(client) -> None:
    project_id = client.post(
        "/projects",
        json={"name": f"UI分页项目_{time.time_ns()}", "base_url": "http://example.com"},
    ).json()["id"]
    marker = f"分页标记{time.time_ns()}"
    for index in range(3):
        payload = _make_ui_case_payload(project_id, f"{marker}_用例{index}", "分页/组一" if index < 2 else "分页/组二")
        if index == 0:
            payload["priority"] = "P0"
        response = client.post("/ui-cases", json=payload)
        assert response.status_code == 201

    paged = client.get(f"/ui-cases?project_id={project_id}&page=1&page_size=2")
    assert paged.status_code == 200
    payload = paged.json()
    assert payload["total"] == 3
    assert len(payload["items"]) == 2

    page2 = client.get(f"/ui-cases?project_id={project_id}&page=2&page_size=2").json()
    assert len(page2["items"]) == 1

    folder_filtered = client.get(f"/ui-cases?project_id={project_id}&page=1&page_size=10&folder=分页/组一").json()
    assert folder_filtered["total"] == 2
    parent_filtered = client.get(f"/ui-cases?project_id={project_id}&page=1&page_size=10&folder=分页").json()
    assert parent_filtered["total"] == 3

    priority_filtered = client.get(f"/ui-cases?project_id={project_id}&page=1&page_size=10&priority=P0").json()
    assert priority_filtered["total"] == 1

    keyword_filtered = client.get(f"/ui-cases?project_id={project_id}&page=1&page_size=10&keyword={marker}_用例0").json()
    assert keyword_filtered["total"] == 1

    legacy = client.get(f"/ui-cases?project_id={project_id}")
    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)
    assert len(legacy.json()) == 3


def test_ui_case_batch_update_and_delete(client) -> None:
    project_id = client.post(
        "/projects",
        json={"name": f"UI批量属性项目_{time.time_ns()}", "base_url": "http://example.com"},
    ).json()["id"]
    case_ids = []
    for index in range(3):
        response = client.post("/ui-cases", json=_make_ui_case_payload(project_id, f"批量属性用例{index}_{time.time_ns()}"))
        assert response.status_code == 201
        case_ids.append(response.json()["id"])

    empty_patch = client.put("/ui-cases/batch", json={"case_ids": case_ids, "patch": {}})
    assert empty_patch.status_code == 400

    batch_update = client.put(
        "/ui-cases/batch",
        json={"case_ids": case_ids, "patch": {"folder_path": "批量/迁移", "priority": "P0"}},
    )
    assert batch_update.status_code == 200
    assert batch_update.json()["affected"] == 3
    updated = client.get(f"/ui-cases/{case_ids[0]}").json()
    assert updated["folder_path"] == "批量/迁移"
    assert updated["priority"] == "P0"

    batch_delete = client.request("DELETE", "/ui-cases/batch", json={"case_ids": case_ids})
    assert batch_delete.status_code == 200
    assert batch_delete.json()["affected"] == 3
    assert client.get(f"/ui-cases/{case_ids[0]}").status_code == 404


def test_ui_case_review_flow_blocks_self_review(client) -> None:
    username = f"review_tester_{time.time_ns()}"
    create_user = client.post(
        "/users",
        json={"username": username, "password": "review123", "display_name": username, "role": "tester"},
    )
    assert create_user.status_code == 201

    tester_client = TestClient(client.app, base_url="http://testserver/api/v1")
    login_response = tester_client.post("/auth/login", json={"username": username, "password": "review123"})
    assert login_response.status_code == 200
    tester_client.headers.update({"Authorization": f"Bearer {login_response.json()['token']}"})

    project_id = tester_client.post(
        "/projects",
        json={"name": f"评审项目_{time.time_ns()}", "base_url": "http://example.com"},
    ).json()["id"]
    case = tester_client.post(
        "/ui-cases", json=_make_ui_case_payload(project_id, f"评审用例_{time.time_ns()}")
    ).json()
    case_id = case["id"]

    premature_decide = client.post(f"/ui-cases/{case_id}/review/decide", json={"result": "APPROVED"})
    assert premature_decide.status_code == 400

    submit = tester_client.post(f"/ui-cases/{case_id}/review/submit")
    assert submit.status_code == 200
    assert submit.json()["review_status"] == "IN_REVIEW"
    assert submit.json()["submitted_review_at"]

    self_decide = tester_client.post(f"/ui-cases/{case_id}/review/decide", json={"result": "APPROVED"})
    assert self_decide.status_code == 403
    assert "不能评审自己创建的用例" in self_decide.text

    decide = client.post(
        f"/ui-cases/{case_id}/review/decide", json={"result": "APPROVED", "note": "步骤覆盖完整"}
    )
    assert decide.status_code == 200
    payload = decide.json()
    assert payload["review_status"] == "APPROVED"
    assert payload["review_note"] == "步骤覆盖完整"
    assert payload["reviewed_by"]
    assert payload["reviewed_at"]

    update = client.put(
        f"/ui-cases/{case_id}",
        json={
            "project_id": project_id,
            "name": case["name"],
            "target_url": "http://frontend:3000/changed",
            "expect_text": case["expect_text"],
            "steps_json": case["steps_json"],
        },
    )
    assert update.status_code == 200
    reset_payload = update.json()
    assert reset_payload["review_status"] == "DRAFT"
    assert reset_payload["reviewed_by"] is None
    assert reset_payload["reviewed_at"] is None

    resubmit = client.post(f"/ui-cases/{case_id}/review/submit")
    assert resubmit.status_code == 200
    assert resubmit.json()["review_status"] == "IN_REVIEW"

    reject = tester_client.post  # noqa: F841  (作者不可评审，改由 admin 拒绝)
    rejected = client.post(f"/ui-cases/{case_id}/review/decide", json={"result": "REJECTED", "note": "断言不足"})
    assert rejected.status_code == 200
    assert rejected.json()["review_status"] == "REJECTED"
    tester_client.close()


def test_ui_batch_run_and_rerun_failed(client, monkeypatch) -> None:
    from app.tasks import executions

    def fake_execute_ui_case(db, run, case, project, deadline=None):
        status = "FAILED" if "失败" in case.name else "SUCCESS"
        return {
            "status": status,
            "summary": "模拟执行",
            "error_type": None if status == "SUCCESS" else "ASSERTION",
            "exit_code": 0 if status == "SUCCESS" else 1,
            "stdout_text": None,
            "stderr_text": None,
            "artifacts_json": [],
            "step_results_json": [],
            "request_payload": None,
            "response_payload": None,
        }

    monkeypatch.setattr(executions, "_execute_ui_case", fake_execute_ui_case)

    project_id = client.post(
        "/projects",
        json={"name": f"UI批量执行项目_{time.time_ns()}", "base_url": "http://example.com"},
    ).json()["id"]
    ok_case = client.post("/ui-cases", json=_make_ui_case_payload(project_id, f"批量成功用例_{time.time_ns()}")).json()
    bad_case = client.post("/ui-cases", json=_make_ui_case_payload(project_id, f"批量失败用例_{time.time_ns()}")).json()

    other_project_id = client.post(
        "/projects",
        json={"name": f"UI批量他项目_{time.time_ns()}", "base_url": "http://example.com"},
    ).json()["id"]
    other_case = client.post("/ui-cases", json=_make_ui_case_payload(other_project_id, f"跨项目用例_{time.time_ns()}")).json()
    cross_project = client.post(
        "/executions/ui/batch-run", json={"case_ids": [ok_case["id"], other_case["id"]]}
    )
    assert cross_project.status_code == 400
    assert "同一项目" in cross_project.text

    inactive_patch = client.put(
        "/ui-cases/batch", json={"case_ids": [other_case["id"]], "patch": {"status": "INACTIVE"}}
    )
    assert inactive_patch.status_code == 200
    inactive_run = client.post("/executions/ui/batch-run", json={"case_ids": [other_case["id"]]})
    assert inactive_run.status_code == 400
    assert "未启用" in inactive_run.text

    trigger = client.post(
        "/executions/ui/batch-run", json={"case_ids": [ok_case["id"], bad_case["id"]]}
    )
    assert trigger.status_code == 201
    batch = trigger.json()
    assert batch["status"] == "FAILED"
    assert batch["total_count"] == 2
    assert batch["pass_count"] == 1
    assert batch["fail_count"] == 1

    listing = client.get(f"/executions/ui/batch-runs?project_id={project_id}")
    assert listing.status_code == 200
    assert any(item["id"] == batch["id"] for item in listing.json())

    detail = client.get(f"/executions/ui/batch-runs/{batch['id']}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert len(detail_payload["runs"]) == 2
    assert {run["status"] for run in detail_payload["runs"]} == {"SUCCESS", "FAILED"}
    assert all(run["batch_run_id"] == batch["id"] for run in detail_payload["runs"])

    latest = client.get(
        f"/executions/runs/latest?case_type=UI&case_ids={ok_case['id']},{bad_case['id']}"
    )
    assert latest.status_code == 200
    latest_map = {run["case_id"]: run for run in latest.json()}
    assert latest_map[ok_case["id"]]["status"] == "SUCCESS"
    assert latest_map[bad_case["id"]]["status"] == "FAILED"

    rerun = client.post(f"/executions/ui/batch-runs/{batch['id']}/rerun-failed")
    assert rerun.status_code == 201
    rerun_payload = rerun.json()
    assert rerun_payload["total_count"] == 1
    assert rerun_payload["fail_count"] == 1

    all_success = client.post("/executions/ui/batch-run", json={"case_ids": [ok_case["id"]]})
    assert all_success.status_code == 201
    assert all_success.json()["status"] == "SUCCESS"
    no_failed = client.post(f"/executions/ui/batch-runs/{all_success.json()['id']}/rerun-failed")
    assert no_failed.status_code == 400

    stats = client.get(f"/ui-cases/stats?project_id={project_id}")
    assert stats.status_code == 200
    stats_payload = stats.json()
    assert stats_payload["total"] == 2
    assert stats_payload["active"] == 2
    assert stats_payload["recent_success_rate"] is not None


def _make_api_case_payload(project_id: int, name: str, folder_path: str | None = None) -> dict:
    return {
        "project_id": project_id,
        "name": name,
        "folder_path": folder_path,
        "method": "GET",
        "path": "/api/v1/system/health",
        "expected_status": 200,
    }


def test_api_case_folder_tree_and_rename(client) -> None:
    project = client.post(
        "/projects",
        json={"name": f"API目录项目_{time.time_ns()}", "base_url": "http://example.com"},
    ).json()
    project_id = project["id"]
    for name, folder in (
        ("树用例A", "登录/核心流程"),
        ("树用例B", "登录/核心流程/边界"),
        ("树用例C", "商品"),
        ("树用例D", None),
    ):
        response = client.post("/api-cases", json=_make_api_case_payload(project_id, f"{name}_{time.time_ns()}", folder))
        assert response.status_code == 201

    tree = client.get(f"/api-cases/folders?project_id={project_id}")
    assert tree.status_code == 200
    payload = tree.json()
    assert payload["total"] == 4
    assert payload["ungrouped"] == 1
    login_node = next(node for node in payload["folders"] if node["name"] == "登录")
    assert login_node["case_count"] == 2
    core_node = next(child for child in login_node["children"] if child["name"] == "核心流程")
    assert core_node["case_count"] == 2
    assert core_node["children"][0]["name"] == "边界"
    assert core_node["children"][0]["case_count"] == 1

    rename = client.post(
        "/api-cases/folders/rename",
        json={"project_id": project_id, "old_path": "登录/核心流程", "new_path": "登录/主流程"},
    )
    assert rename.status_code == 200
    assert rename.json()["affected"] == 2
    renamed = client.get(
        f"/api-cases?project_id={project_id}&page=1&page_size=50&folder=登录/主流程"
    ).json()
    assert renamed["total"] == 2
    assert {item["folder_path"] for item in renamed["items"]} == {"登录/主流程", "登录/主流程/边界"}


def test_api_cases_pagination_and_filters(client) -> None:
    project_id = client.post(
        "/projects",
        json={"name": f"API分页项目_{time.time_ns()}", "base_url": "http://example.com"},
    ).json()["id"]
    marker = f"分页标记{time.time_ns()}"
    for index in range(3):
        payload = _make_api_case_payload(project_id, f"{marker}_用例{index}", "分页/组一" if index < 2 else "分页/组二")
        if index == 0:
            payload["priority"] = "P0"
        if index == 1:
            payload["method"] = "POST"
        response = client.post("/api-cases", json=payload)
        assert response.status_code == 201

    paged = client.get(f"/api-cases?project_id={project_id}&page=1&page_size=2")
    assert paged.status_code == 200
    payload = paged.json()
    assert payload["total"] == 3
    assert len(payload["items"]) == 2

    page2 = client.get(f"/api-cases?project_id={project_id}&page=2&page_size=2").json()
    assert len(page2["items"]) == 1

    folder_filtered = client.get(f"/api-cases?project_id={project_id}&page=1&page_size=10&folder=分页/组一").json()
    assert folder_filtered["total"] == 2
    parent_filtered = client.get(f"/api-cases?project_id={project_id}&page=1&page_size=10&folder=分页").json()
    assert parent_filtered["total"] == 3

    priority_filtered = client.get(f"/api-cases?project_id={project_id}&page=1&page_size=10&priority=P0").json()
    assert priority_filtered["total"] == 1

    method_filtered = client.get(f"/api-cases?project_id={project_id}&page=1&page_size=10&method=POST").json()
    assert method_filtered["total"] == 1

    keyword_filtered = client.get(f"/api-cases?project_id={project_id}&page=1&page_size=10&keyword={marker}_用例0").json()
    assert keyword_filtered["total"] == 1

    legacy = client.get(f"/api-cases?project_id={project_id}")
    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)
    assert len(legacy.json()) == 3


def test_api_case_batch_update_and_delete(client) -> None:
    project_id = client.post(
        "/projects",
        json={"name": f"API批量属性项目_{time.time_ns()}", "base_url": "http://example.com"},
    ).json()["id"]
    case_ids = []
    for index in range(3):
        response = client.post("/api-cases", json=_make_api_case_payload(project_id, f"批量属性用例{index}_{time.time_ns()}"))
        assert response.status_code == 201
        case_ids.append(response.json()["id"])

    empty_patch = client.put("/api-cases/batch", json={"case_ids": case_ids, "patch": {}})
    assert empty_patch.status_code == 400

    batch_update = client.put(
        "/api-cases/batch",
        json={"case_ids": case_ids, "patch": {"folder_path": "批量/迁移", "priority": "P0"}},
    )
    assert batch_update.status_code == 200
    assert batch_update.json()["affected"] == 3
    listed = client.get(f"/api-cases?project_id={project_id}&page=1&page_size=10&folder=批量/迁移").json()
    assert listed["total"] == 3
    assert all(item["priority"] == "P0" for item in listed["items"])

    batch_delete = client.request("DELETE", "/api-cases/batch", json={"case_ids": case_ids})
    assert batch_delete.status_code == 200
    assert batch_delete.json()["affected"] == 3
    remaining = client.get(f"/api-cases?project_id={project_id}&page=1&page_size=10").json()
    assert remaining["total"] == 0


def test_api_case_review_flow_blocks_self_review(client) -> None:
    username = f"api_review_tester_{time.time_ns()}"
    create_user = client.post(
        "/users",
        json={"username": username, "password": "review123", "display_name": username, "role": "tester"},
    )
    assert create_user.status_code == 201

    tester_client = TestClient(client.app, base_url="http://testserver/api/v1")
    login_response = tester_client.post("/auth/login", json={"username": username, "password": "review123"})
    assert login_response.status_code == 200
    tester_client.headers.update({"Authorization": f"Bearer {login_response.json()['token']}"})

    project_id = tester_client.post(
        "/projects",
        json={"name": f"API评审项目_{time.time_ns()}", "base_url": "http://example.com"},
    ).json()["id"]
    case = tester_client.post(
        "/api-cases", json=_make_api_case_payload(project_id, f"评审用例_{time.time_ns()}")
    ).json()
    case_id = case["id"]

    premature_decide = client.post(f"/api-cases/{case_id}/review/decide", json={"result": "APPROVED"})
    assert premature_decide.status_code == 400

    submit = tester_client.post(f"/api-cases/{case_id}/review/submit")
    assert submit.status_code == 200
    assert submit.json()["review_status"] == "IN_REVIEW"
    assert submit.json()["submitted_review_at"]

    self_decide = tester_client.post(f"/api-cases/{case_id}/review/decide", json={"result": "APPROVED"})
    assert self_decide.status_code == 403
    assert "不能评审自己创建的用例" in self_decide.text

    decide = client.post(
        f"/api-cases/{case_id}/review/decide", json={"result": "APPROVED", "note": "断言覆盖完整"}
    )
    assert decide.status_code == 200
    payload = decide.json()
    assert payload["review_status"] == "APPROVED"
    assert payload["review_note"] == "断言覆盖完整"
    assert payload["reviewed_by"]
    assert payload["reviewed_at"]

    update = client.put(
        f"/api-cases/{case_id}",
        json={
            "project_id": project_id,
            "name": case["name"],
            "method": "GET",
            "path": "/api/v1/system/info",
            "expected_status": 200,
        },
    )
    assert update.status_code == 200
    reset_payload = update.json()
    assert reset_payload["review_status"] == "DRAFT"
    assert reset_payload["reviewed_by"] is None
    assert reset_payload["reviewed_at"] is None

    resubmit = client.post(f"/api-cases/{case_id}/review/submit")
    assert resubmit.status_code == 200
    assert resubmit.json()["review_status"] == "IN_REVIEW"

    rejected = client.post(f"/api-cases/{case_id}/review/decide", json={"result": "REJECTED", "note": "断言不足"})
    assert rejected.status_code == 200
    assert rejected.json()["review_status"] == "REJECTED"
    tester_client.close()


def test_api_batch_run_and_rerun_failed(client, monkeypatch) -> None:
    from app.tasks import executions

    def fake_execute_api_case(db, run, case, project, deadline=None):
        status = "FAILED" if "失败" in case.name else "SUCCESS"
        return {
            "status": status,
            "summary": "模拟执行",
            "error_type": None if status == "SUCCESS" else "ASSERTION",
            "exit_code": 0 if status == "SUCCESS" else 1,
            "stdout_text": None,
            "stderr_text": None,
            "artifacts_json": [],
            "step_results_json": [],
            "request_payload": None,
            "response_payload": None,
        }

    monkeypatch.setattr(executions, "_execute_api_case", fake_execute_api_case)

    project_id = client.post(
        "/projects",
        json={"name": f"API批量执行项目_{time.time_ns()}", "base_url": "http://example.com"},
    ).json()["id"]
    ok_case = client.post("/api-cases", json=_make_api_case_payload(project_id, f"批量成功用例_{time.time_ns()}")).json()
    bad_case = client.post("/api-cases", json=_make_api_case_payload(project_id, f"批量失败用例_{time.time_ns()}")).json()

    other_project_id = client.post(
        "/projects",
        json={"name": f"API批量他项目_{time.time_ns()}", "base_url": "http://example.com"},
    ).json()["id"]
    other_case = client.post("/api-cases", json=_make_api_case_payload(other_project_id, f"跨项目用例_{time.time_ns()}")).json()
    cross_project = client.post(
        "/executions/api/batch-run", json={"case_ids": [ok_case["id"], other_case["id"]]}
    )
    assert cross_project.status_code == 400
    assert "同一项目" in cross_project.text

    trigger = client.post(
        "/executions/api/batch-run", json={"case_ids": [ok_case["id"], bad_case["id"]]}
    )
    assert trigger.status_code == 201
    batch = trigger.json()
    assert batch["case_type"] == "API"
    assert batch["status"] == "FAILED"
    assert batch["total_count"] == 2
    assert batch["pass_count"] == 1
    assert batch["fail_count"] == 1

    listing = client.get(f"/executions/api/batch-runs?project_id={project_id}")
    assert listing.status_code == 200
    assert any(item["id"] == batch["id"] for item in listing.json())

    # API 批次不会出现在 UI 批次列表中
    ui_listing = client.get(f"/executions/ui/batch-runs?project_id={project_id}")
    assert all(item["id"] != batch["id"] for item in ui_listing.json())

    detail = client.get(f"/executions/api/batch-runs/{batch['id']}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert len(detail_payload["runs"]) == 2
    assert {run["status"] for run in detail_payload["runs"]} == {"SUCCESS", "FAILED"}
    assert all(run["case_type"] == "API" for run in detail_payload["runs"])

    rerun = client.post(f"/executions/api/batch-runs/{batch['id']}/rerun-failed")
    assert rerun.status_code == 201
    rerun_payload = rerun.json()
    assert rerun_payload["case_type"] == "API"
    assert rerun_payload["total_count"] == 1
    assert rerun_payload["fail_count"] == 1

    stats = client.get(f"/api-cases/stats?project_id={project_id}")
    assert stats.status_code == 200
    stats_payload = stats.json()
    assert stats_payload["total"] == 2
    assert stats_payload["active"] == 2
    assert stats_payload["recent_success_rate"] is not None


def test_project_workspace_full_flow(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]

    # --- iteration ---
    iteration_resp = client.post(
        f"/projects/{project_id}/iterations",
        json={"name": f"迭代_{time.time_ns()}", "goal": "首个迭代", "status": "PLANNING"},
    )
    assert iteration_resp.status_code == 201, iteration_resp.text
    iteration_id = iteration_resp.json()["id"]

    # --- requirement CRUD ---
    req_resp = client.post(
        f"/projects/{project_id}/requirements",
        json={"title": f"需求_{time.time_ns()}", "priority": "P1", "iteration_id": iteration_id},
    )
    assert req_resp.status_code == 201, req_resp.text
    requirement = req_resp.json()
    requirement_id = requirement["id"]
    assert requirement["status"] == "PENDING"

    # list with pagination
    list_resp = client.get(f"/projects/{project_id}/requirements?page=1&page_size=10")
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 1

    # --- state machine: valid + illegal (422) ---
    ok_status = client.put(f"/requirements/{requirement_id}/status", json={"status": "PLANNING"})
    assert ok_status.status_code == 200
    assert ok_status.json()["status"] == "PLANNING"

    bad_status = client.put(f"/requirements/{requirement_id}/status", json={"status": "DONE"})
    assert bad_status.status_code == 422, bad_status.text

    # --- rank (kanban move) ---
    rank_resp = client.put(
        f"/requirements/{requirement_id}/rank",
        json={"order_index": 500.0, "status": "IN_PROGRESS"},
    )
    assert rank_resp.status_code == 200
    assert rank_resp.json()["order_index"] == 500.0
    assert rank_resp.json()["status"] == "IN_PROGRESS"

    # --- link a real API case (traceability) ---
    case_resp = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"追溯用例_{time.time_ns()}",
            "method": "GET",
            "path": "/api/v1/system/health",
            "expected_status": 200,
        },
    )
    assert case_resp.status_code == 201
    case_id = case_resp.json()["id"]

    link_resp = client.post(
        f"/requirements/{requirement_id}/cases",
        json={"case_type": "API", "case_id": case_id},
    )
    assert link_resp.status_code in (200, 201), link_resp.text
    link_id = link_resp.json()["id"]

    cases_resp = client.get(f"/requirements/{requirement_id}/cases")
    assert cases_resp.status_code == 200
    assert any(c["case_id"] == case_id for c in cases_resp.json())

    # reverse: case -> requirements
    reverse_resp = client.get(f"/cases/API/{case_id}/requirements")
    assert reverse_resp.status_code == 200
    assert any(r["id"] == requirement_id for r in reverse_resp.json())

    # --- task ---
    task_resp = client.post(
        f"/projects/{project_id}/tasks",
        json={"title": f"任务_{time.time_ns()}", "requirement_id": requirement_id},
    )
    assert task_resp.status_code == 201, task_resp.text
    task_id = task_resp.json()["id"]
    assert task_resp.json()["status"] == "TODO"

    task_bad = client.put(f"/tasks/{task_id}/status", json={"status": "DONE"})
    assert task_bad.status_code == 422
    task_ok = client.put(f"/tasks/{task_id}/status", json={"status": "DOING"})
    assert task_ok.status_code == 200

    # --- defect ---
    defect_resp = client.post(
        f"/projects/{project_id}/defects",
        json={"title": f"缺陷_{time.time_ns()}", "severity": "CRITICAL", "requirement_id": requirement_id},
    )
    assert defect_resp.status_code == 201, defect_resp.text
    defect_id = defect_resp.json()["id"]
    assert defect_resp.json()["status"] == "NEW"

    defect_bad = client.put(f"/project-defects/{defect_id}/status", json={"status": "CLOSED"})
    assert defect_bad.status_code == 422
    defect_ok = client.put(f"/project-defects/{defect_id}/status", json={"status": "CONFIRMED"})
    assert defect_ok.status_code == 200

    # --- comment ---
    comment_resp = client.post(
        f"/requirement/{requirement_id}/comments",
        json={"content": "这是一条评论"},
    )
    assert comment_resp.status_code in (200, 201), comment_resp.text
    comments = client.get(f"/requirement/{requirement_id}/comments")
    assert comments.status_code == 200
    assert any(c["content"] == "这是一条评论" for c in comments.json())

    # --- activities ---
    activities = client.get(f"/projects/{project_id}/activities")
    assert activities.status_code == 200
    assert isinstance(activities.json(), list)

    # --- overview ---
    overview = client.get(f"/projects/{project_id}/overview")
    assert overview.status_code == 200
    ov = overview.json()
    assert ov["project_id"] == project_id
    assert ov["requirement_total"] >= 1
    assert ov["defect_total"] >= 1
    assert "case_coverage_rate" in ov

    # --- trace matrix ---
    trace = client.get(f"/projects/{project_id}/trace")
    assert trace.status_code == 200
    trace_payload = trace.json()
    rows = trace_payload.get("rows", trace_payload if isinstance(trace_payload, list) else [])
    assert any(row.get("requirement_id") == requirement_id or row.get("id") == requirement_id for row in rows)

    # --- burndown ---
    burndown = client.get(f"/iterations/{iteration_id}/burndown")
    assert burndown.status_code == 200

    # --- unlink + delete cleanup ---
    unlink = client.delete(f"/requirements/{requirement_id}/cases/{link_id}")
    assert unlink.status_code == 204
    assert client.delete(f"/project-defects/{defect_id}").status_code == 204
    assert client.delete(f"/tasks/{task_id}").status_code == 204
    assert client.delete(f"/requirements/{requirement_id}").status_code == 204
    assert client.delete(f"/iterations/{iteration_id}").status_code == 204


def test_plan_schedule_config_and_validation(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    plan_resp = client.post("/test-plans", json={"project_id": project_id, "name": f"调度配置计划_{time.time_ns()}"})
    assert plan_resp.status_code == 201
    plan_id = plan_resp.json()["id"]

    invalid_cron = client.put(
        f"/test-plans/{plan_id}/schedule",
        json={"schedule_enabled": True, "schedule_cron": "not a cron"},
    )
    assert invalid_cron.status_code == 422

    missing_cron = client.put(f"/test-plans/{plan_id}/schedule", json={"schedule_enabled": True})
    assert missing_cron.status_code == 422

    enabled = client.put(
        f"/test-plans/{plan_id}/schedule",
        json={"schedule_enabled": True, "schedule_cron": "0 2 * * *", "schedule_max_retries": 1},
    )
    assert enabled.status_code == 200
    payload = enabled.json()
    assert payload["schedule_enabled"] is True
    assert payload["schedule_cron"] == "0 2 * * *"
    assert payload["schedule_max_retries"] == 1
    assert payload["next_run_at"] is not None

    wrong_env = client.put(
        f"/test-plans/{plan_id}/schedule",
        json={"schedule_enabled": True, "schedule_cron": "0 2 * * *", "schedule_environment_id": 999999},
    )
    assert wrong_env.status_code == 400

    disabled = client.put(f"/test-plans/{plan_id}/schedule", json={"schedule_enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["schedule_enabled"] is False
    assert disabled.json()["schedule_cron"] is None
    assert disabled.json()["next_run_at"] is None

    assert client.delete(f"/test-plans/{plan_id}").status_code == 204


def test_scan_scheduled_plans_triggers_and_defers(client, monkeypatch) -> None:
    from datetime import timedelta

    from sqlalchemy import select as sa_select

    from app.core.database import SessionLocal
    from app.models import TestPlan, TestPlanRun
    from app.tasks import executions
    from app.timeutil import utc_now_naive

    project_id = client.get("/projects").json()[0]["id"]
    case_resp = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"定时触发用例_{time.time_ns()}",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "APPROVED",
            "expected_status": 200,
        },
    )
    assert case_resp.status_code == 201
    case_id = case_resp.json()["id"]

    plan_resp = client.post("/test-plans", json={"project_id": project_id, "name": f"定时触发计划_{time.time_ns()}"})
    assert plan_resp.status_code == 201
    plan_id = plan_resp.json()["id"]
    added = client.post(
        f"/test-plans/{plan_id}/cases",
        json={"case_type": "API", "case_id": case_id, "order_index": 1},
    )
    assert added.status_code == 201

    enabled = client.put(
        f"/test-plans/{plan_id}/schedule",
        json={"schedule_enabled": True, "schedule_cron": "*/5 * * * *"},
    )
    assert enabled.status_code == 200

    delayed: list[int] = []
    monkeypatch.setattr(executions.run_test_plan, "delay", lambda run_id: delayed.append(run_id))

    with SessionLocal() as db:
        db_plan = db.get(TestPlan, plan_id)
        db_plan.next_run_at = utc_now_naive() - timedelta(minutes=1)
        db.commit()

    result = executions.scan_scheduled_plans()
    assert plan_id in result["triggered"]
    assert len(delayed) == 1

    with SessionLocal() as db:
        runs = db.scalars(sa_select(TestPlanRun).where(TestPlanRun.plan_id == plan_id)).all()
        assert len(runs) == 1
        assert runs[0].status == "PENDING"
        db_plan = db.get(TestPlan, plan_id)
        assert db_plan.next_run_at is not None
        assert db_plan.next_run_at > utc_now_naive()
        assert db_plan.last_triggered_at is not None
        # 再次到期：已有 PENDING run，只顺延不重复触发
        db_plan.next_run_at = utc_now_naive() - timedelta(minutes=1)
        db.commit()

    result_again = executions.scan_scheduled_plans()
    assert plan_id in result_again["skipped"]
    assert len(delayed) == 1

    with SessionLocal() as db:
        runs = db.scalars(sa_select(TestPlanRun).where(TestPlanRun.plan_id == plan_id)).all()
        assert len(runs) == 1
        db_plan = db.get(TestPlan, plan_id)
        assert db_plan.next_run_at > utc_now_naive()
        # 清理：关闭调度并结束 run，避免影响其它用例
        db_plan.schedule_enabled = False
        db_plan.next_run_at = None
        runs[0].status = "SUCCESS"
        db.commit()


def test_notification_setting_crud_and_test_endpoint(client, monkeypatch) -> None:
    from app import notifications

    project_id = client.get("/projects").json()[0]["id"]

    default = client.get(f"/projects/{project_id}/notification-setting")
    assert default.status_code == 200
    assert default.json()["enabled"] is False

    invalid_url = client.put(
        f"/projects/{project_id}/notification-setting",
        json={"enabled": True, "channel_type": "FEISHU", "webhook_url": "not-a-url", "notify_on": "ALL"},
    )
    assert invalid_url.status_code == 422

    invalid_channel = client.put(
        f"/projects/{project_id}/notification-setting",
        json={"enabled": False, "channel_type": "SMS", "notify_on": "ALL"},
    )
    assert invalid_channel.status_code == 422

    saved = client.put(
        f"/projects/{project_id}/notification-setting",
        json={
            "enabled": True,
            "channel_type": "DINGTALK",
            "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=x",
            "secret": "SEC123",
            "notify_on": "FAIL_ONLY",
        },
    )
    assert saved.status_code == 200
    payload = saved.json()
    assert payload["channel_type"] == "DINGTALK"
    assert payload["notify_on"] == "FAIL_ONLY"

    fetched = client.get(f"/projects/{project_id}/notification-setting")
    assert fetched.json()["enabled"] is True

    captured = {}

    class _FakeResponse:
        status_code = 200
        text = "ok"

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr(notifications.httpx, "post", fake_post)

    test_resp = client.post(
        f"/projects/{project_id}/notification-setting/test",
        json={
            "enabled": True,
            "channel_type": "DINGTALK",
            "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=x",
            "secret": "SEC123",
            "notify_on": "ALL",
        },
    )
    assert test_resp.status_code == 200
    assert test_resp.json()["success"] is True
    # 钉钉加签：URL 带 timestamp/sign，payload 为 text 格式
    assert "timestamp=" in captured["url"] and "sign=" in captured["url"]
    assert captured["json"]["msgtype"] == "text"

    missing_url = client.post(
        f"/projects/{project_id}/notification-setting/test",
        json={"enabled": False, "channel_type": "CUSTOM", "notify_on": "ALL"},
    )
    assert missing_url.status_code == 400

    # 还原：关闭通知，避免影响其它执行用例
    restore = client.put(
        f"/projects/{project_id}/notification-setting",
        json={"enabled": False, "channel_type": "FEISHU", "notify_on": "ALL"},
    )
    assert restore.status_code == 200


def test_notification_channel_payload_formats(monkeypatch) -> None:
    from app import notifications
    from app.models import ProjectNotificationSetting

    calls = []

    class _FakeResponse:
        status_code = 200
        text = "ok"

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        return _FakeResponse()

    monkeypatch.setattr(notifications.httpx, "post", fake_post)

    feishu = ProjectNotificationSetting(
        project_id=1, enabled=True, channel_type="FEISHU", webhook_url="https://open.feishu.cn/hook/x"
    )
    assert notifications.send_webhook_message(feishu, "hello") is True
    assert calls[-1][1] == {"msg_type": "text", "content": {"text": "hello"}}

    wecom = ProjectNotificationSetting(
        project_id=1, enabled=True, channel_type="WECOM", webhook_url="https://qyapi.weixin.qq.com/hook/x"
    )
    assert notifications.send_webhook_message(wecom, "hello") is True
    assert calls[-1][1] == {"msgtype": "text", "text": {"content": "hello"}}

    custom = ProjectNotificationSetting(
        project_id=1, enabled=True, channel_type="CUSTOM", webhook_url="https://example.com/hook"
    )
    assert notifications.send_webhook_message(custom, "hello") is True
    assert calls[-1][1] == {"source": "test-platform", "event": "plan_run_finished", "text": "hello"}

    empty = ProjectNotificationSetting(project_id=1, enabled=True, channel_type="FEISHU", webhook_url=None)
    assert notifications.send_webhook_message(empty, "hello") is False

    class _ErrorResponse:
        status_code = 500
        text = "boom"

    monkeypatch.setattr(notifications.httpx, "post", lambda *args, **kwargs: _ErrorResponse())
    assert notifications.send_webhook_message(feishu, "hello") is False


def test_plan_run_notification_fail_only_filter(client, monkeypatch) -> None:
    from sqlalchemy import select as sa_select

    from app import notifications
    from app.core.database import SessionLocal
    from app.models import ProjectNotificationSetting, TestPlan, TestPlanRun

    calls = []
    monkeypatch.setattr(notifications, "send_webhook_message", lambda setting, text: calls.append(text) or True)

    with SessionLocal() as db:
        plan = db.scalars(sa_select(TestPlan)).first()
        setting = db.scalar(
            sa_select(ProjectNotificationSetting).where(ProjectNotificationSetting.project_id == plan.project_id)
        )
        if setting is None:
            setting = ProjectNotificationSetting(project_id=plan.project_id)
            db.add(setting)
        setting.enabled = True
        setting.channel_type = "CUSTOM"
        setting.webhook_url = "https://example.com/hook"
        setting.notify_on = "FAIL_ONLY"
        success_run = TestPlanRun(plan_id=plan.id, project_id=plan.project_id, status="SUCCESS", total_count=1, pass_count=1)
        failed_run = TestPlanRun(plan_id=plan.id, project_id=plan.project_id, status="FAILED", total_count=1, fail_count=1)
        db.add_all([success_run, failed_run])
        db.commit()
        success_id, failed_id = success_run.id, failed_run.id

        notifications.send_plan_run_notification(db, success_id)
        assert calls == []
        notifications.send_plan_run_notification(db, failed_id)
        assert len(calls) == 1
        assert "失败" in calls[0]

        setting.notify_on = "ALL"
        db.commit()
        notifications.send_plan_run_notification(db, success_id)
        assert len(calls) == 2

        # 清理：关闭通知并删除临时 run
        setting.enabled = False
        db.delete(db.get(TestPlanRun, success_id))
        db.delete(db.get(TestPlanRun, failed_id))
        db.commit()


def test_api_token_lifecycle(client) -> None:
    created = client.post("/api-tokens", json={"name": "ci-token", "expires_days": 30})
    assert created.status_code == 201
    token_payload = created.json()
    full_token = token_payload["token"]
    assert full_token.startswith("pt_")
    assert token_payload["expires_at"] is not None
    token_id = token_payload["id"]

    with TestClient(client.app, base_url="http://testserver/api/v1") as token_client:
        token_client.headers.update({"Authorization": f"Bearer {full_token}"})
        me = token_client.get("/auth/me")
        assert me.status_code == 200

        listing = client.get("/api-tokens")
        assert listing.status_code == 200
        item = next(entry for entry in listing.json() if entry["id"] == token_id)
        assert item["token_prefix"].endswith("****")
        assert "token" not in item
        assert full_token not in json.dumps(listing.json())

        deleted = client.delete(f"/api-tokens/{token_id}")
        assert deleted.status_code == 204
        assert token_client.get("/auth/me").status_code == 401

    assert client.delete(f"/api-tokens/{token_id}").status_code == 404


def test_api_token_expiry_and_disabled_user(client) -> None:
    from datetime import timedelta

    from sqlalchemy import select as sa_select

    from app.core.database import SessionLocal
    from app.models import ApiToken
    from app.timeutil import utc_now_naive

    username = f"citok_{time.time_ns()}"
    create_user = client.post("/users", json={"username": username, "password": "secret123", "role": "tester"})
    assert create_user.status_code == 201
    user_id = create_user.json()["id"]

    user_client = TestClient(client.app, base_url="http://testserver/api/v1")
    login = user_client.post("/auth/login", json={"username": username, "password": "secret123"})
    assert login.status_code == 200
    user_client.headers.update({"Authorization": f"Bearer {login.json()['token']}"})

    created = user_client.post("/api-tokens", json={"name": "expiring"})
    assert created.status_code == 201
    assert created.json()["expires_at"] is None
    token_value = created.json()["token"]

    api_client = TestClient(client.app, base_url="http://testserver/api/v1")
    api_client.headers.update({"Authorization": f"Bearer {token_value}"})
    assert api_client.get("/auth/me").status_code == 200

    with SessionLocal() as db:
        record = db.scalar(sa_select(ApiToken).where(ApiToken.token == token_value))
        record.expires_at = utc_now_naive() - timedelta(minutes=1)
        db.commit()
    assert api_client.get("/auth/me").status_code == 401

    with SessionLocal() as db:
        record = db.scalar(sa_select(ApiToken).where(ApiToken.token == token_value))
        record.expires_at = None
        db.commit()
    assert api_client.get("/auth/me").status_code == 200

    disable = client.put(f"/users/{user_id}", json={"status": "DISABLED"})
    assert disable.status_code == 200
    assert api_client.get("/auth/me").status_code == 401

    # 非本人不可删除对方 token：管理员删除属于 tester 的 token 应 404
    with SessionLocal() as db:
        record = db.scalar(sa_select(ApiToken).where(ApiToken.token == token_value))
        token_id = record.id
    assert client.delete(f"/api-tokens/{token_id}").status_code == 404


def test_list_runs_server_side_filter_and_pagination(client) -> None:
    from app.core.database import SessionLocal
    from app.models import APICase
    from app.services import create_test_run

    api_cases = client.get("/api-cases").json()
    case = next(item for item in api_cases if item["name"] == "示例健康检查接口")
    case_id = case["id"]

    created_ids: list[int] = []
    specs = [
        {"status": "SUCCESS", "error_type": None, "case_name": "分页用例甲", "summary": "关键字命中ALPHA"},
        {"status": "FAILED", "error_type": "ASSERTION", "case_name": "分页用例乙", "summary": "断言失败"},
        {"status": "ERROR", "error_type": "RUNTIME", "case_name": "分页用例丙", "summary": "运行异常"},
        {"status": "RUNNING", "error_type": None, "case_name": "分页用例丁", "summary": "执行中"},
    ]
    with SessionLocal() as db:
        db_case = db.get(APICase, case_id)
        project_id = db_case.project_id
        for spec in specs:
            run = create_test_run(
                db,
                project_id=project_id,
                environment_id=None,
                case_type="API",
                case_id=db_case.id,
                case_name=spec["case_name"],
            )
            run.status = spec["status"]
            run.error_type = spec["error_type"]
            run.summary = spec["summary"]
            db.add(run)
            db.flush()
            created_ids.append(run.id)
        db.commit()

    # 兼容模式：不带 page 参数仍返回裸列表
    legacy = client.get("/executions/runs")
    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)

    # 分页模式：返回带 total 与统计的对象
    paged = client.get("/executions/runs", params={"page": 1, "page_size": 2})
    assert paged.status_code == 200
    body = paged.json()
    assert set(["items", "total", "running", "failed", "retryable"]).issubset(body.keys())
    assert len(body["items"]) == 2
    assert body["total"] >= 4
    assert body["items"][0]["id"] > body["items"][1]["id"]  # 按 id 倒序

    # 状态过滤
    failed_only = client.get("/executions/runs", params={"page": 1, "page_size": 50, "status": "FAILED"}).json()
    assert all(item["status"] == "FAILED" for item in failed_only["items"])
    assert any(item["id"] in created_ids for item in failed_only["items"])

    # 失败原因过滤
    assertion_only = client.get(
        "/executions/runs", params={"page": 1, "page_size": 50, "error_type": "ASSERTION"}
    ).json()
    assert all(item["error_type"] == "ASSERTION" for item in assertion_only["items"])

    # 关键字过滤（命中 summary）
    keyword_hit = client.get(
        "/executions/runs", params={"page": 1, "page_size": 50, "keyword": "ALPHA"}
    ).json()
    assert keyword_hit["total"] >= 1
    assert all("ALPHA" in (item["summary"] or "") or "ALPHA" in (item["case_name"] or "") for item in keyword_hit["items"])

    # 统计口径：全量（不受当前 status 过滤影响）
    stats = client.get("/executions/runs", params={"page": 1, "page_size": 1, "status": "SUCCESS"}).json()
    assert stats["failed"] >= 2  # FAILED + ERROR
    assert stats["running"] >= 1  # RUNNING

    # 非法状态 400
    assert client.get("/executions/runs", params={"status": "NOPE"}).status_code == 400

    # 清理
    with SessionLocal() as db:
        from app.models import TestRun

        for run_id in created_ids:
            obj = db.get(TestRun, run_id)
            if obj is not None:
                db.delete(obj)
        db.commit()



def _create_project_for_feature(client, label: str) -> tuple[int, int]:
    """创建独立空间与项目，返回 (workspace_id, project_id)。"""
    workspace = client.post(
        "/workspaces",
        json={"name": f"{label}空间_{time.time_ns()}", "description": label},
    )
    assert workspace.status_code == 201
    workspace_id = workspace.json()["id"]
    project = client.post(
        "/projects",
        json={
            "workspace_id": workspace_id,
            "name": f"{label}项目_{time.time_ns()}",
            "base_url": "http://example.com",
        },
    )
    assert project.status_code == 201
    return workspace_id, project.json()["id"]


def test_project_variable_pool_crud(client) -> None:
    _, project_id = _create_project_for_feature(client, "变量池")

    empty = client.get(f"/projects/{project_id}/variables")
    assert empty.status_code == 200
    assert empty.json()["variables_json"] == {}

    updated = client.put(
        f"/projects/{project_id}/variables",
        json={"variables_json": {"base_url": "https://api.demo", "token": "abc"}},
    )
    assert updated.status_code == 200
    assert updated.json()["variables_json"]["base_url"] == "https://api.demo"

    from app.core.database import SessionLocal
    from app.models import Project
    with SessionLocal() as db:
        stored_project = db.get(Project, project_id)
        assert stored_project._legacy_variables_json is None
        assert stored_project.variables_encrypted
        assert "https://api.demo" not in stored_project.variables_encrypted

    refetch = client.get(f"/projects/{project_id}/variables")
    assert refetch.status_code == 200
    assert refetch.json()["variables_json"] == {"base_url": "https://api.demo", "token": "abc"}

    cleared = client.put(f"/projects/{project_id}/variables", json={"variables_json": None})
    assert cleared.status_code == 200
    assert cleared.json()["variables_json"] == {}


def test_legacy_variable_pools_are_migrated_to_encrypted_storage(client) -> None:
    _, project_id = _create_project_for_feature(client, "变量迁移")
    from app.core.database import SessionLocal, engine, ensure_schema
    from app.models import Project

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE projects SET variables_json = :variables, variables_encrypted = NULL "
                "WHERE id = :project_id"
            ),
            {"variables": json.dumps({"token": "legacy-secret"}), "project_id": project_id},
        )

    changes = ensure_schema(engine)
    assert any(change.startswith("projects.variables_encrypted:migrated(") for change in changes)
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        assert project.variables_json == {"token": "legacy-secret"}
        assert project._legacy_variables_json is None
        assert "legacy-secret" not in project.variables_encrypted


def test_project_member_management_and_isolation(client) -> None:
    _, project_id = _create_project_for_feature(client, "项目成员")

    username = f"proj_member_{time.time_ns()}"
    user_response = client.post(
        "/users",
        json={"username": username, "password": "role123", "display_name": username, "role": "tester"},
    )
    assert user_response.status_code == 201
    user_id = user_response.json()["id"]

    member_client = TestClient(client.app, base_url="http://testserver/api/v1")
    login_response = member_client.post("/auth/login", json={"username": username, "password": "role123"})
    assert login_response.status_code == 200
    member_client.headers.update({"Authorization": f"Bearer {login_response.json()['token']}"})

    # 尚未加入的用户既非项目成员也非空间成员，被隔离
    assert member_client.get(f"/projects/{project_id}/variables").status_code == 403

    add_member = client.post(
        f"/projects/{project_id}/members",
        json={"user_id": user_id, "role": "member"},
    )
    assert add_member.status_code == 201
    member_id = add_member.json()["id"]

    members = client.get(f"/projects/{project_id}/members")
    assert members.status_code == 200
    assert any(m["user_id"] == user_id for m in members.json())

    update_member = client.put(
        f"/projects/{project_id}/members/{member_id}",
        json={"role": "manager"},
    )
    assert update_member.status_code == 200
    assert update_member.json()["role"] == "manager"

    # 成为成员后可以访问项目变量
    assert member_client.get(f"/projects/{project_id}/variables").status_code == 200

    delete_member = client.delete(f"/projects/{project_id}/members/{member_id}")
    assert delete_member.status_code == 204

    # 移除后再次被隔离
    assert member_client.get(f"/projects/{project_id}/variables").status_code == 403


def test_api_spec_import_openapi_dry_run_and_persist(client) -> None:
    _, project_id = _create_project_for_feature(client, "OpenAPI导入")

    openapi_doc = json.dumps(
        {
            "openapi": "3.0.0",
            "info": {"title": "Demo", "version": "1.0.0"},
            "paths": {
                "/pets": {
                    "get": {"summary": "列出宠物", "operationId": "listPets"},
                    "post": {"summary": "创建宠物", "operationId": "createPet"},
                },
                "/pets/{petId}": {
                    "get": {"summary": "获取宠物", "operationId": "getPet"},
                },
            },
        }
    )

    dry_run = client.post(
        "/api-cases/import-spec",
        json={
            "project_id": project_id,
            "source_type": "openapi",
            "content": openapi_doc,
            "folder_path": "导入/宠物",
            "dry_run": True,
        },
    )
    assert dry_run.status_code == 200
    dry_payload = dry_run.json()
    assert dry_payload["detected_count"] == 3
    assert dry_payload["created_count"] == 0
    assert all(item["folder_path"].startswith("导入/宠物") for item in dry_payload["items"])

    persisted = client.post(
        "/api-cases/import-spec",
        json={
            "project_id": project_id,
            "source_type": "openapi",
            "content": openapi_doc,
            "folder_path": "导入/宠物",
            "dry_run": False,
        },
    )
    assert persisted.status_code == 200
    assert persisted.json()["created_count"] == 3

    cases = client.get(f"/api-cases?project_id={project_id}")
    assert cases.status_code == 200
    case_items = cases.json()
    items = case_items["items"] if isinstance(case_items, dict) else case_items
    assert len(items) >= 3


def test_api_spec_import_rejects_invalid_content(client) -> None:
    _, project_id = _create_project_for_feature(client, "非法导入")
    response = client.post(
        "/api-cases/import-spec",
        json={
            "project_id": project_id,
            "source_type": "openapi",
            "content": "not-a-valid-spec",
            "dry_run": True,
        },
    )
    assert response.status_code == 400


def test_data_driven_and_mock_config_roundtrip(client) -> None:
    _, project_id = _create_project_for_feature(client, "数据驱动Mock")

    created = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"mock_case_{time.time_ns()}",
            "method": "GET",
            "path": "/mock-demo",
            "expected_status": 200,
            "datasets_json": [{"name": "alice"}, {"name": "bob"}],
            "mock_enabled": True,
            "mock_config_json": {
                "status_code": 201,
                "headers": {"X-Mock": "1"},
                "body": {"ok": True},
                "delay_ms": 0,
            },
        },
    )
    assert created.status_code == 201
    case_id = created.json()["id"]
    assert created.json()["datasets_json"] == [{"name": "alice"}, {"name": "bob"}]
    assert created.json()["mock_enabled"] is True

    anon_client = TestClient(client.app, base_url="http://testserver/api/v1")
    mock_response = anon_client.get(f"/mock/{project_id}/mock-demo")
    assert mock_response.status_code == 201
    assert mock_response.headers.get("X-Mock") == "1"
    assert mock_response.json() == {"ok": True}

    missing = anon_client.get(f"/mock/{project_id}/not-configured")
    assert missing.status_code == 404

    client.delete(f"/api-cases/{case_id}")


def test_report_share_link_public_access(client) -> None:
    plans = client.get("/test-plans").json()
    plan_id = next(plan["id"] for plan in plans if plan["name"] == "演示回归计划")
    trigger = client.post(f"/test-plans/{plan_id}/run", json={"timeout_seconds": 9})
    assert trigger.status_code == 200
    plan_run_id = trigger.json()["id"]

    enable = client.post(f"/reports/{plan_run_id}/share")
    assert enable.status_code == 200
    share_payload = enable.json()
    assert share_payload["enabled"] is True
    token = share_payload["share_token"]
    assert token
    assert share_payload["share_url"].endswith(token)

    anon_client = TestClient(client.app, base_url="http://testserver/api/v1")
    public_report = anon_client.get(f"/public/reports/{token}")
    assert public_report.status_code == 200
    public_payload = public_report.json()
    assert public_payload["plan_run"]["id"] == plan_run_id
    assert "share_token" not in public_payload["plan_run"]
    assert "report_json_path" not in public_payload["plan_run"]
    assert "report_junit_path" not in public_payload["plan_run"]
    assert "defects" not in public_payload
    for run in public_payload["test_runs"]:
        assert "stdout_text" not in run
        assert "stderr_text" not in run
        assert "request_payload" not in run
        assert "response_payload" not in run
        assert "artifacts_json" not in run
        assert "step_results_json" not in run

    disable = client.delete(f"/reports/{plan_run_id}/share")
    assert disable.status_code == 200
    assert disable.json()["enabled"] is False

    assert anon_client.get(f"/public/reports/{token}").status_code == 404
