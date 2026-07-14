#!/usr/bin/env python3
"""Validate claw_5skill_unified trusted output directories.

This checker intentionally validates generated artifacts rather than model
claims. It verifies the ID reference chain, XMindMark structure/statistics,
and the actual delivered XMind archive produced by the deterministic exporter.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


REQUIRED_FILES = [
    "SourceManifest.yaml",
    "EvidenceTrace.yaml",
    "ScopeIndex.yaml",
    "ScopeIndexGateReport.yaml",
    "FunctionPoints.yaml",
    "RequirementGateReport.yaml",
    "TestcasePackage.yaml",
    "TestcaseGateReport.yaml",
    "ReviewReport.yaml",
    "DeliverySummary.md",
    "FinalDeliveryGateReport.yaml",
]

ID_PATTERNS = {
    "SRC": re.compile(r"\bSRC-\d{3}\b"),
    "FP": re.compile(r"\bFP-\d{3}\b"),
    "TC": re.compile(r"\bTC-\d{3}\b"),
}

STATS_PATTERNS = {
    "source_count": re.compile(r"直接测试对象数：(\d+)"),
    "function_point_count": re.compile(r"功能点总数：(\d+)"),
    "testcase_count": re.compile(r"用例总数：(\d+)"),
    "p0_count": re.compile(r"P0 数量：(\d+)"),
    "p1_count": re.compile(r"P1 数量：(\d+)"),
    "p2_count": re.compile(r"P2 数量：(\d+)"),
    "p3_count": re.compile(r"P3 数量：(\d+)"),
}


@dataclass
class Issue:
    severity: str
    code: str
    message: str


@dataclass
class ValidationResult:
    output_dir: str
    status: str = "pass"
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def add_error(self, code: str, message: str) -> None:
        self.errors.append(Issue("error", code, message))
        self.status = "fail"

    def add_warning(self, code: str, message: str) -> None:
        self.warnings.append(Issue("warning", code, message))
        if self.status == "pass":
            self.status = "pass_with_warnings"


def load_yaml(path: Path, result: ValidationResult) -> Any:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        result.add_error("missing_file", f"Missing required file: {path.name}")
    except Exception as exc:  # noqa: BLE001 - validator should report all parse failures
        result.add_error("yaml_parse_failed", f"Cannot parse {path.name}: {exc}")
    return {}


def listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def collect_ids_from_text(text: str, prefix: str) -> list[str]:
    return ID_PATTERNS[prefix].findall(text)


def find_main_xmindmark(output_dir: Path, source_manifest: dict[str, Any]) -> Path | None:
    basename = source_manifest.get("output_basename") or source_manifest.get("project")
    if basename:
        candidate = output_dir / f"{basename}.xmindmark"
        if candidate.exists():
            return candidate

    candidates = sorted(
        p
        for p in output_dir.glob("*.xmindmark")
        if not p.name.startswith("_") and ".before_" not in p.name
    )
    if candidates:
        return candidates[0]
    return None


def parse_xmindmark(path: Path) -> tuple[list[str], dict[str, int], dict[str, list[int]], dict[str, int]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    stats: dict[str, int] = {}
    occurrences: dict[str, list[int]] = defaultdict(list)
    priority_counts = Counter()

    for idx, line in enumerate(lines, start=1):
        for key, pattern in STATS_PATTERNS.items():
            match = pattern.search(line)
            if match:
                stats[key] = int(match.group(1))
        for prefix in ("SRC", "FP", "TC"):
            for item_id in collect_ids_from_text(line, prefix):
                occurrences[item_id].append(idx)
        priority_match = re.search(r"优先级：(P[0-3])", line)
        if priority_match:
            priority_counts[priority_match.group(1)] += 1
    return lines, stats, occurrences, dict(priority_counts)


def validate_yaml_chain(output_dir: Path, result: ValidationResult) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name in REQUIRED_FILES:
        path = output_dir / name
        if not path.exists():
            result.add_error("missing_file", f"Missing required file: {name}")
            continue
        if name.endswith(".yaml"):
            data[name] = load_yaml(path, result)
        else:
            data[name] = {"path": str(path)}
    if result.errors:
        return data

    scope = data["ScopeIndex.yaml"]
    fps = data["FunctionPoints.yaml"]
    pkg = data["TestcasePackage.yaml"]
    review = data["ReviewReport.yaml"]

    source_blocks = scope.get("source_blocks") or []
    source_ids = [x.get("block_id") for x in source_blocks if isinstance(x, dict)]
    expected_sources = scope.get("expected_source_list") or source_ids
    shard_ids = {
        x.get("shard_id")
        for x in scope.get("shards", [])
        if isinstance(x, dict) and x.get("shard_id")
    }

    fp_items = fps.get("function_points") or []
    fp_ids = [x.get("fp_id") for x in fp_items if isinstance(x, dict)]
    fp_source_ids = [x.get("source_id") for x in fp_items if isinstance(x, dict)]
    fp_shard_ids = [x.get("shard_id") for x in fp_items if isinstance(x, dict)]

    case_items = pkg.get("testcases") or []
    case_ids = [x.get("case_id") for x in case_items if isinstance(x, dict)]
    case_source_ids = [x.get("source_id") for x in case_items if isinstance(x, dict)]
    case_shard_ids = [x.get("shard_id") for x in case_items if isinstance(x, dict)]

    result.metrics.update(
        {
            "yaml_source_count": len(set(source_ids)),
            "yaml_expected_source_count": len(set(expected_sources)),
            "yaml_function_point_count": len(set(fp_ids)),
            "yaml_testcase_count": len(set(case_ids)),
        }
    )

    for label, ids in (("source", source_ids), ("function_point", fp_ids), ("testcase", case_ids)):
        dupes = sorted(k for k, count in Counter(ids).items() if k and count > 1)
        if dupes:
            result.add_error("duplicate_yaml_id", f"Duplicate {label} IDs in YAML: {', '.join(dupes)}")

    missing_sources = sorted(set(expected_sources) - set(source_ids))
    if missing_sources:
        result.add_error("expected_source_missing", f"expected_source_list has missing source_blocks: {missing_sources}")

    unknown_fp_sources = sorted(set(fp_source_ids) - set(source_ids))
    if unknown_fp_sources:
        result.add_error("unknown_fp_source", f"FunctionPoints reference unknown source_id: {unknown_fp_sources}")

    unknown_fp_shards = sorted(set(fp_shard_ids) - shard_ids)
    if unknown_fp_shards:
        result.add_error("unknown_fp_shard", f"FunctionPoints reference unknown shard_id: {unknown_fp_shards}")

    unknown_case_sources = sorted(set(case_source_ids) - set(source_ids))
    if unknown_case_sources:
        result.add_error("unknown_case_source", f"Testcases reference unknown source_id: {unknown_case_sources}")

    unknown_case_shards = sorted(set(case_shard_ids) - shard_ids)
    if unknown_case_shards:
        result.add_error("unknown_case_shard", f"Testcases reference unknown shard_id: {unknown_case_shards}")

    fp_id_set = set(fp_ids)
    covered_fp_ids: set[str] = set()
    for case in case_items:
        if not isinstance(case, dict):
            continue
        for fp_id in listify(case.get("fp_ids")):
            if fp_id not in fp_id_set:
                result.add_error("unknown_case_fp", f"{case.get('case_id')} references unknown fp_id: {fp_id}")
            else:
                covered_fp_ids.add(fp_id)

    uncovered = sorted(fp_id_set - covered_fp_ids)
    if uncovered:
        result.add_error("uncovered_fp", f"Function points not covered by any testcase: {uncovered}")

    source_with_cases = set(case_source_ids)
    sources_without_cases = sorted(set(expected_sources) - source_with_cases)
    if sources_without_cases:
        result.add_error("source_without_case", f"Expected sources without testcases: {sources_without_cases}")

    if "xmind_grouping_contract" not in pkg:
        result.add_error("missing_xmind_grouping_contract", "TestcasePackage.yaml lacks xmind_grouping_contract")

    for gate_name in ("ScopeIndexGateReport.yaml", "RequirementGateReport.yaml", "TestcaseGateReport.yaml", "FinalDeliveryGateReport.yaml"):
        status = data[gate_name].get("status")
        if status != "pass":
            result.add_error("gate_not_pass", f"{gate_name} status is {status!r}, expected 'pass'")

    summary = review.get("summary") or {}
    expected_summary = {
        "source_count": len(set(expected_sources)),
        "function_point_count": len(set(fp_ids)),
        "testcase_count": len(set(case_ids)),
    }
    for key, expected in expected_summary.items():
        actual = summary.get(key)
        if actual is not None and actual != expected:
            result.add_error("review_summary_mismatch", f"ReviewReport summary.{key}={actual}, expected {expected}")

    return data


def validate_xmindmark(output_dir: Path, data: dict[str, Any], result: ValidationResult, skip_roundtrip: bool) -> None:
    source_manifest = data.get("SourceManifest.yaml") or {}
    xmindmark = find_main_xmindmark(output_dir, source_manifest)
    if not xmindmark:
        result.add_error("missing_xmindmark", "No main .xmindmark found")
        return

    lines, stats, occurrences, priority_counts = parse_xmindmark(xmindmark)
    result.metrics["xmindmark_file"] = xmindmark.name

    if not lines:
        result.add_error("empty_xmindmark", f"{xmindmark.name} is empty")
        return

    if lines[0].startswith("-") or not lines[0].strip():
        result.add_error("invalid_central_topic", "Line 1 must be a non-list central topic")

    for idx, line in enumerate(lines, start=1):
        leading = len(line) - len(line.lstrip(" "))
        if "\t" in line:
            result.add_error("tab_indent", f"Line {idx} contains a tab")
        if leading % 2 != 0:
            result.add_error("odd_indent", f"Line {idx} has odd leading spaces")
        content = line.lstrip(" ")
        if idx > 1 and content and not content.startswith("- "):
            result.add_error("xmindmark_line_not_list", f"Line {idx} is not a list node")
        if content.startswith(("- **", "- *")) or "**" in content:
            result.add_error("markdown_markup", f"Line {idx} contains Markdown emphasis markup")
        if "[" in content or "]" in content:
            result.add_error("xmindmark_metachar", f"Line {idx} contains '[' or ']'")

    for item_id, line_numbers in sorted(occurrences.items()):
        if item_id.startswith("TC-") and len(line_numbers) > 1:
            result.add_error("duplicate_xmindmark_tc", f"{item_id} appears on multiple xmindmark lines: {line_numbers}")

    x_counts = {
        "source_count": len({k for k in occurrences if k.startswith("SRC-")}),
        "function_point_count": len({k for k in occurrences if k.startswith("FP-")}),
        "testcase_count": len({k for k in occurrences if k.startswith("TC-")}),
        "p0_count": priority_counts.get("P0", 0),
        "p1_count": priority_counts.get("P1", 0),
        "p2_count": priority_counts.get("P2", 0),
        "p3_count": priority_counts.get("P3", 0),
    }
    result.metrics.update({f"xmindmark_{k}": v for k, v in x_counts.items()})

    for key, actual in x_counts.items():
        declared = stats.get(key)
        if declared is None:
            result.add_error("missing_xmindmark_stat", f"Missing xmindmark statistic: {key}")
        elif declared != actual:
            result.add_error("xmindmark_stat_mismatch", f"{key} declared {declared}, actual {actual}")

    yaml_expected = {
        "source_count": result.metrics.get("yaml_expected_source_count"),
        "function_point_count": result.metrics.get("yaml_function_point_count"),
        "testcase_count": result.metrics.get("yaml_testcase_count"),
    }
    for key, expected in yaml_expected.items():
        if expected is not None and x_counts[key] != expected:
            result.add_error("yaml_xmindmark_count_mismatch", f"{key}: YAML expected {expected}, xmindmark has {x_counts[key]}")

    validate_tree_shape(lines, result)

    if not skip_roundtrip:
        validate_delivered_xmind(output_dir, source_manifest, x_counts, result)


def validate_tree_shape(lines: list[str], result: ValidationResult) -> None:
    stack: dict[int, str] = {}
    for idx, line in enumerate(lines, start=1):
        if idx == 1:
            stack[0] = "ROOT"
            continue
        stripped = line.lstrip(" ")
        if not stripped.startswith("- "):
            continue
        depth = (len(line) - len(stripped)) // 2 + 1
        node = stripped[2:]
        if node.startswith("模块："):
            node_type = "MODULE"
        elif node.startswith("场景："):
            node_type = "SCENE"
        elif node.startswith("SRC-"):
            node_type = "SRC"
        elif node.startswith("FP-"):
            node_type = "FP"
        elif node.startswith("TC-"):
            node_type = "TC"
        elif node == "统计信息" or "数量：" in node or "总数：" in node or node.startswith("审查结论") or node.startswith("结论原因"):
            node_type = "STATS"
        else:
            node_type = "DETAIL"
        parent_type = stack.get(depth - 1)
        stack[depth] = node_type
        for stale_depth in list(stack):
            if stale_depth > depth:
                del stack[stale_depth]

        if node_type == "SRC" and parent_type != "SCENE":
            result.add_error("invalid_tree_shape", f"Line {idx} SRC node parent is {parent_type}, expected SCENE")
        elif node_type == "FP" and parent_type != "SRC":
            result.add_error("invalid_tree_shape", f"Line {idx} FP node parent is {parent_type}, expected SRC")
        elif node_type == "TC" and parent_type != "FP":
            result.add_error("invalid_tree_shape", f"Line {idx} TC node parent is {parent_type}, expected FP")


def validate_delivered_xmind(
    output_dir: Path,
    source_manifest: dict[str, Any],
    expected_counts: dict[str, int],
    result: ValidationResult,
) -> None:
    basename = source_manifest.get("output_basename") or source_manifest.get("project")
    candidate = output_dir / f"{basename}.xmind" if basename else None
    if candidate is None or not candidate.exists():
        candidates = sorted(path for path in output_dir.glob("*.xmind") if not path.name.startswith("."))
        if len(candidates) != 1:
            result.add_error("delivered_xmind_missing", "Expected exactly one visible delivered .xmind file")
            return
        candidate = candidates[0]
    try:
        with zipfile.ZipFile(candidate, "r") as archive:
            names = set(archive.namelist())
            missing = {"content.json", "manifest.json", "metadata.json"} - names
            if missing:
                result.add_error("delivered_xmind_missing_entries", f"XMind missing entries: {sorted(missing)}")
                return
            content = json.loads(archive.read("content.json").decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - validator should report malformed archives
        result.add_error("delivered_xmind_invalid", f"Cannot parse delivered XMind: {exc}")
        return
    if not isinstance(content, list) or not content or not isinstance(content[0], dict):
        result.add_error("delivered_xmind_empty", "Delivered XMind has no worksheet")
        return
    root = content[0].get("rootTopic")
    if not isinstance(root, dict) or not str(root.get("title") or "").strip():
        result.add_error("delivered_xmind_empty_root", "Delivered XMind root topic is blank")
        return
    titles: list[str] = []

    def walk(topic: dict[str, Any]) -> None:
        title = str(topic.get("title") or "").strip()
        if title:
            titles.append(title)
        children = ((topic.get("children") or {}).get("attached") or [])
        for child in children:
            if isinstance(child, dict):
                walk(child)

    walk(root)
    actual_counts = {
        "source_count": len({item for title in titles for item in collect_ids_from_text(title, "SRC")}),
        "function_point_count": len({item for title in titles for item in collect_ids_from_text(title, "FP")}),
        "testcase_count": len({item for title in titles for item in collect_ids_from_text(title, "TC")}),
    }
    result.metrics.update({f"delivered_xmind_{key}": value for key, value in actual_counts.items()})
    for key, expected in expected_counts.items():
        if key not in actual_counts:
            continue
        actual = actual_counts[key]
        if actual != expected:
            result.add_error(
                "delivered_xmind_count_mismatch",
                f"{key}: XMindMark expected {expected}, delivered XMind has {actual}",
            )
    if not result.errors:
        result.metrics["delivered_xmind_validation"] = "pass"


def emit(result: ValidationResult, output_format: str) -> None:
    payload = {
        "output_dir": result.output_dir,
        "status": result.status,
        "metrics": result.metrics,
        "errors": [issue.__dict__ for issue in result.errors],
        "warnings": [issue.__dict__ for issue in result.warnings],
    }
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(f"trusted output validation: {result.status}")
    print(f"output_dir: {result.output_dir}")
    if result.metrics:
        print("metrics:")
        for key in sorted(result.metrics):
            print(f"  {key}: {result.metrics[key]}")
    if result.errors:
        print("errors:")
        for issue in result.errors:
            print(f"  - [{issue.code}] {issue.message}")
    if result.warnings:
        print("warnings:")
        for issue in result.warnings:
            print(f"  - [{issue.code}] {issue.message}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate a claw_5skill_unified trusted output directory.")
    parser.add_argument("output_dir", type=Path, help="Path to outputs/<project>/trusted")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--skip-xmindmark-roundtrip", action="store_true", help="Skip delivered XMind archive verification")
    args = parser.parse_args(argv)

    output_dir = args.output_dir.resolve()
    result = ValidationResult(output_dir=str(output_dir))
    if not output_dir.is_dir():
        result.add_error("missing_output_dir", f"Output dir does not exist: {output_dir}")
        emit(result, args.format)
        return 1

    data = validate_yaml_chain(output_dir, result)
    validate_xmindmark(output_dir, data, result, args.skip_xmindmark_roundtrip)
    emit(result, args.format)
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
