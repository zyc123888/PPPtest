"""P0 架构收敛与 OpenAPI 规范契约回归测试。"""

from __future__ import annotations

import warnings
from pathlib import Path


def test_openapi_schema_has_tags_summaries_and_unique_operation_ids(client) -> None:
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        schema = client.app.openapi()

    duplicate_warnings = [str(item.message) for item in captured if "Duplicate Operation ID" in str(item.message)]
    assert duplicate_warnings == [], f"存在重复 OpenAPI operationId: {duplicate_warnings}"

    operation_ids: list[str] = []
    for path, methods in schema.get("paths", {}).items():
        if not path.startswith("/api/v1"):
            continue
        for method, op in methods.items():
            assert op.get("tags"), f"{method.upper()} {path} 缺少 OpenAPI tags"
            assert op.get("summary"), f"{method.upper()} {path} 缺少 OpenAPI summary"
            op_id = op.get("operationId")
            assert op_id, f"{method.upper()} {path} 缺少 operationId"
            operation_ids.append(op_id)

    assert len(operation_ids) == len(set(operation_ids)), "存在重复的 OpenAPI operationId"
    declared_tags = {item["name"] for item in schema.get("tags", [])}
    used_tags = {
        tag
        for path, methods in schema.get("paths", {}).items()
        if path.startswith("/api/v1")
        for op in methods.values()
        for tag in (op.get("tags") or [])
    }
    assert used_tags.issubset(declared_tags), f"存在未在 openapi_tags 声明的分组: {used_tags - declared_tags}"


def test_database_module_retires_legacy_ensure_schema() -> None:
    import app.core.database as db_mod

    assert not hasattr(db_mod, "ensure_schema")


def test_api_aggregator_stays_modular() -> None:
    api_path = Path(__file__).resolve().parents[1] / "app" / "api.py"
    line_count = len(api_path.read_text(encoding="utf-8").splitlines())
    assert line_count < 150, f"api.py 应当保持轻量聚合入口，当前 {line_count} 行"
