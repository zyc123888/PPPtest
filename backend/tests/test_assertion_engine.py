"""断言引擎与变量提取单元测试"""

import pytest

from app.assertion_engine import (
    JsonPathError,
    ResponseFacts,
    evaluate_assertions,
    resolve_json_path,
    run_extractors,
)


def _facts(**overrides) -> ResponseFacts:
    defaults = dict(
        status_code=200,
        headers={"Content-Type": "application/json", "X-Trace-Id": "trace-123"},
        body_text='{"code": 0, "data": {"token": "abc123", "items": [{"id": 1}, {"id": 2}]}}',
        body_json={"code": 0, "data": {"token": "abc123", "items": [{"id": 1}, {"id": 2}]}},
        duration_ms=120,
    )
    defaults.update(overrides)
    return ResponseFacts(**defaults)


class TestResolveJsonPath:
    def test_nested_key_and_index(self) -> None:
        data = {"data": {"items": [{"id": 1}, {"id": 2}]}}
        assert resolve_json_path(data, "$.data.items[0].id") == 1
        assert resolve_json_path(data, "$.data.items[-1].id") == 2
        assert resolve_json_path(data, "data.items[1]") == {"id": 2}

    def test_quoted_keys(self) -> None:
        data = {"中文键": {"a-b": 7}}
        assert resolve_json_path(data, "$['中文键']['a-b']") == 7
        assert resolve_json_path(data, '$["中文键"]["a-b"]') == 7

    def test_root(self) -> None:
        assert resolve_json_path({"a": 1}, "$") == {"a": 1}

    def test_missing_key_raises(self) -> None:
        with pytest.raises(JsonPathError):
            resolve_json_path({"a": 1}, "$.b")

    def test_index_out_of_range_raises(self) -> None:
        with pytest.raises(JsonPathError):
            resolve_json_path({"a": [1]}, "$.a[5]")

    def test_bad_syntax_raises(self) -> None:
        with pytest.raises(JsonPathError):
            resolve_json_path({"a": 1}, "$..a")

    def test_empty_raises(self) -> None:
        with pytest.raises(JsonPathError):
            resolve_json_path({"a": 1}, "  ")


class TestEvaluateAssertions:
    def test_implicit_status_assertion_added(self) -> None:
        outcome = evaluate_assertions(None, _facts(), expected_status=200)
        assert outcome.passed is True
        assert len(outcome.results) == 1
        assert outcome.results[0]["implicit"] is True

    def test_implicit_status_assertion_failure(self) -> None:
        outcome = evaluate_assertions([], _facts(status_code=500), expected_status=200)
        assert outcome.passed is False
        assert "500" in outcome.summary_text()

    def test_explicit_status_replaces_implicit(self) -> None:
        outcome = evaluate_assertions(
            [{"type": "status_code", "expected": 404}], _facts(status_code=404), expected_status=200
        )
        assert outcome.passed is True
        assert len(outcome.results) == 1

    def test_json_path_eq_and_failure(self) -> None:
        ok = evaluate_assertions(
            [{"type": "json_path", "expression": "$.data.token", "operator": "eq", "expected": "abc123"}],
            _facts(),
            expected_status=200,
        )
        assert ok.passed is True
        bad = evaluate_assertions(
            [{"type": "json_path", "expression": "$.data.token", "expected": "wrong"}],
            _facts(),
            expected_status=200,
        )
        assert bad.passed is False

    def test_json_path_numeric_loose_equal(self) -> None:
        outcome = evaluate_assertions(
            [{"type": "json_path", "expression": "$.code", "expected": "0"}], _facts(), expected_status=200
        )
        assert outcome.passed is True

    def test_json_path_exists_and_not_exists(self) -> None:
        outcome = evaluate_assertions(
            [
                {"type": "json_path", "expression": "$.data.token", "operator": "exists"},
                {"type": "json_path", "expression": "$.data.missing", "operator": "not_exists"},
            ],
            _facts(),
            expected_status=200,
        )
        assert outcome.passed is True

    def test_json_path_length_operator(self) -> None:
        outcome = evaluate_assertions(
            [{"type": "json_path", "expression": "$.data.items", "operator": "length_eq", "expected": 2}],
            _facts(),
            expected_status=200,
        )
        assert outcome.passed is True

    def test_json_path_on_non_json_body(self) -> None:
        outcome = evaluate_assertions(
            [{"type": "json_path", "expression": "$.a", "expected": 1}],
            _facts(body_json=None, body_text="plain"),
            expected_status=200,
        )
        assert outcome.passed is False
        assert "JSON" in outcome.results[-1]["message"]

    def test_body_contains_and_negate(self) -> None:
        outcome = evaluate_assertions(
            [
                {"type": "body_contains", "expected": "abc123"},
                {"type": "body_contains", "expected": "不存在的内容", "negate": True},
            ],
            _facts(),
            expected_status=200,
        )
        assert outcome.passed is True

    def test_body_regex(self) -> None:
        ok = evaluate_assertions(
            [{"type": "body_regex", "expected": r"abc\d+"}], _facts(), expected_status=200
        )
        assert ok.passed is True
        bad = evaluate_assertions(
            [{"type": "body_regex", "expected": "["}], _facts(), expected_status=200
        )
        assert bad.passed is False
        assert "正则无效" in bad.results[-1]["message"]

    def test_header_contains_case_insensitive(self) -> None:
        outcome = evaluate_assertions(
            [{"type": "header", "name": "content-type", "operator": "contains", "expected": "json"}],
            _facts(),
            expected_status=200,
        )
        assert outcome.passed is True

    def test_header_missing(self) -> None:
        outcome = evaluate_assertions(
            [{"type": "header", "name": "x-missing", "expected": "v"}], _facts(), expected_status=200
        )
        assert outcome.passed is False

    def test_response_time(self) -> None:
        ok = evaluate_assertions(
            [{"type": "response_time_ms", "operator": "lte", "expected": 3000}], _facts(), expected_status=200
        )
        assert ok.passed is True
        bad = evaluate_assertions(
            [{"type": "response_time_ms", "operator": "lte", "expected": 10}], _facts(), expected_status=200
        )
        assert bad.passed is False

    def test_unknown_type_fails(self) -> None:
        outcome = evaluate_assertions([{"type": "magic"}], _facts(), expected_status=200)
        assert outcome.passed is False
        assert "不支持的断言类型" in outcome.results[-1]["message"]


class TestRunExtractors:
    def test_json_path_header_regex_status(self) -> None:
        variables, results = run_extractors(
            [
                {"name": "token", "source": "json_path", "expression": "$.data.token"},
                {"name": "trace_id", "source": "header", "expression": "x-trace-id"},
                {"name": "code", "source": "regex", "expression": r'"code":\s*(\d+)'},
                {"name": "http_status", "source": "status_code"},
            ],
            _facts(),
        )
        assert variables == {"token": "abc123", "trace_id": "trace-123", "code": "0", "http_status": 200}
        assert all(item["ok"] for item in results)

    def test_failures_reported_without_raising(self) -> None:
        variables, results = run_extractors(
            [
                {"name": "missing", "source": "json_path", "expression": "$.nope"},
                {"name": "no_header", "source": "header", "expression": "x-nope"},
                {"name": "no_match", "source": "regex", "expression": "zzz(\\d+)"},
                {"name": "", "source": "status_code"},
                {"name": "bad_source", "source": "cookie", "expression": "sid"},
            ],
            _facts(),
        )
        assert variables == {}
        assert all(not item["ok"] for item in results)

    def test_empty_extractors(self) -> None:
        variables, results = run_extractors(None, _facts())
        assert variables == {}
        assert results == []
