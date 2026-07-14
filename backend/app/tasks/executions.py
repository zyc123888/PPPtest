from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import textwrap
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urljoin, urlparse
from xml.sax.saxutils import escape

import httpx
from fastapi.testclient import TestClient
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.models import APICase, Environment, PerformanceCase, Project, TestPlanRun, TestRun, UICase
from app.execution_runtime import (
    MissingTemplateVariableError,
    build_request_kwargs,
    build_runtime_headers,
    prepare_http_request,
    render_data,
    render_template,
)
from app.services import finalize_run, mark_run_started
from app.timeutil import utc_now_naive


# Backward-compatible aliases: old private names now delegate to the shared module.
_render_template = render_template
_render_data = render_data
_build_runtime_headers = build_runtime_headers
_build_request_body_kwargs = build_request_kwargs


def _safe_json_or_text(response: httpx.Response) -> dict:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        return {"data": payload}
    except Exception:
        return {"text": response.text[:2000]}


def _open_db() -> Session:
    return SessionLocal()


def _resolve_environment(db: Session, project: Project, environment_id: int | None) -> Environment | None:
    if environment_id is None:
        return None
    env = db.get(Environment, environment_id)
    if env is None or env.project_id != project.id:
        return None
    return env


def _run_timeout_seconds(run: TestRun) -> int:
    return run.timeout_seconds or settings.request_timeout_seconds


def _run_deadline(started_at: float, run: TestRun) -> float:
    return started_at + float(_run_timeout_seconds(run))


def _remaining_timeout_seconds(deadline: float) -> float:
    return max(0.0, deadline - time.perf_counter())


def _remaining_timeout_seconds_or_raise(run: TestRun, deadline: float) -> float:
    remaining = _remaining_timeout_seconds(deadline)
    if remaining <= 0:
        raise subprocess.TimeoutExpired(cmd=f"{run.case_type.lower()}-case", timeout=_run_timeout_seconds(run))
    return remaining


def _playwright_timeout_ms(run: TestRun, fallback_seconds: int | None = None) -> int:
    seconds = fallback_seconds or _run_timeout_seconds(run)
    return max(1, seconds) * 1000


def _playwright_timeout_ms_from_deadline(run: TestRun, deadline: float, fallback_seconds: int | None = None) -> int:
    remaining = _remaining_timeout_seconds_or_raise(run, deadline)
    if fallback_seconds is not None:
        remaining = min(remaining, float(fallback_seconds))
    return max(1, int(remaining * 1000))


def _retryable_status(status: str) -> bool:
    return status in {"FAILED", "ERROR", "TIMEOUT"}


def _append_retry_trace(summary: str, attempts: list[str]) -> str:
    if not attempts:
        return summary
    return f"{summary}（重试轨迹: {'；'.join(attempts)}）"


def _normalize_execution_result(result: dict | None) -> dict:
    normalized = {
        "status": "ERROR",
        "summary": "执行结果为空",
        "error_type": "SYSTEM",
        "exit_code": 1,
        "stdout_text": "",
        "stderr_text": "",
        "artifacts_json": [],
        "step_results_json": [],
        "request_payload": None,
        "response_payload": None,
    }
    if result:
        normalized.update(result)
    if normalized["status"] == "SUCCESS":
        normalized["error_type"] = None
        normalized["exit_code"] = 0 if normalized["exit_code"] is None else normalized["exit_code"]
    elif normalized["status"] == "TIMEOUT" and normalized["exit_code"] in (None, 1):
        normalized["exit_code"] = 124
    return normalized


def _execute_case_with_retries(db: Session, run: TestRun, execute_once) -> dict:
    attempts: list[str] = []
    max_retries = max(run.max_retries or 0, 0)
    base_retry_count = max(run.retry_count or 0, 0)
    last_result: dict | None = None

    for attempt_index in range(max_retries + 1):
        deadline = _run_deadline(time.perf_counter(), run)
        try:
            last_result = execute_once(deadline)
        except subprocess.TimeoutExpired as exc:
            artifacts, step_results = _normalize_exception_artifacts(run.id, exc)
            last_result = {
                "status": "TIMEOUT",
                "summary": f"接口执行超时: {exc}",
                "error_type": "TIMEOUT",
                "timeout_seconds": _run_timeout_seconds(run),
                "stderr_text": traceback.format_exc(),
                "artifacts_json": artifacts,
                "step_results_json": step_results,
            }
        except PlaywrightTimeoutError as exc:
            artifacts, step_results = _normalize_exception_artifacts(run.id, exc)
            last_result = {
                "status": "TIMEOUT",
                "summary": f"UI 执行超时: {exc}",
                "error_type": "TIMEOUT",
                "timeout_seconds": _run_timeout_seconds(run),
                "stderr_text": traceback.format_exc(),
                "artifacts_json": artifacts,
                "step_results_json": step_results,
            }
        except MissingTemplateVariableError as exc:
            last_result = {
                "status": "FAILED",
                "summary": str(exc),
                "error_type": "CONFIG",
                "exit_code": 1,
                "stdout_text": "",
                "stderr_text": str(exc),
                "artifacts_json": [],
                "step_results_json": [],
                "request_payload": None,
                "response_payload": None,
            }
        except Exception as exc:
            exception_payload = _exception_payload(exc) or {}
            status = exception_payload.get("status")
            if status not in {"FAILED", "ERROR", "TIMEOUT"}:
                status = "ERROR"
            artifacts, step_results = _normalize_exception_artifacts(run.id, exc)
            last_result = {
                "status": status,
                "summary": f"执行异常: {_exception_message(exc)}",
                "error_type": exception_payload.get("error_type") or "SYSTEM",
                "stderr_text": traceback.format_exc(),
                "artifacts_json": artifacts,
                "step_results_json": step_results,
            }

        last_result = _normalize_execution_result(last_result)

        run.retry_count = base_retry_count + attempt_index
        db.commit()
        db.refresh(run)
        if not _retryable_status(last_result["status"]) or attempt_index >= max_retries:
            if attempt_index > 0:
                last_result["summary"] = _append_retry_trace(last_result["summary"], attempts)
            return last_result

        attempts.append(f"第{attempt_index + 1}次{last_result['status']}")

    return _normalize_execution_result(last_result)


def _ensure_run_dir(run_id: int) -> str:
    root_dir = settings.report_output_dir
    if not os.path.isabs(root_dir):
        root_dir = os.path.abspath(root_dir)
    run_dir = os.path.join(root_dir, f"run_{run_id}")
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


def _write_run_artifact(run_id: int, filename: str, content, *, binary: bool = False) -> dict:
    run_dir = _ensure_run_dir(run_id)
    path = os.path.join(run_dir, filename)
    if binary:
        with open(path, "wb") as handle:
            handle.write(content)
    else:
        with open(path, "w", encoding="utf-8") as handle:
            if isinstance(content, str):
                handle.write(content)
            else:
                json.dump(content, handle, ensure_ascii=False, indent=2)
    return {
        "name": filename,
        "path": path,
        "type": os.path.splitext(filename)[1].lstrip(".") or "file",
    }


def _exception_payload(exc: Exception) -> dict | None:
    if isinstance(exc, RuntimeError):
        try:
            payload = json.loads(str(exc))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None
    return None


def _exception_message(exc: Exception) -> str:
    payload = _exception_payload(exc)
    if payload and payload.get("error"):
        return str(payload["error"])
    return str(exc) or exc.__class__.__name__


def _normalize_exception_artifacts(run_id: int, exc: Exception) -> tuple[list[dict], list[dict]]:
    payload = _exception_payload(exc)
    artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
    steps = payload.get("steps") if isinstance(payload, dict) else None
    if artifacts is None:
        artifacts = [_write_run_artifact(run_id, "error.txt", traceback.format_exc())]
    return artifacts, steps or []


def _ui_step_detail(
    step: dict,
    *,
    page_url: str | None,
    selector: str | None = None,
    value: str | None = None,
    error: str | None = None,
    screenshot: str | None = None,
) -> dict:
    detail = {
        "action": step.get("action"),
        "kind": step.get("_kind", "step"),
        "selector": selector,
        "value": value,
        "page_url": page_url,
    }
    for key in ("duration_ms", "width", "height", "state", "wait_until"):
        if step.get(key) is not None:
            detail[key] = step[key]
    if error:
        detail["error"] = error
    if screenshot:
        detail["screenshot"] = screenshot
    return detail


def _ui_assertion_as_step(assertion: dict) -> dict:
    assertion_type = assertion.get("type")
    value = assertion.get("value", assertion.get("expected"))
    action_map = {
        "text_present": "assert_text",
        "text_visible": "assert_text",
        "text_hidden": "assert_text_hidden",
        "selector_visible": "assert_visible",
        "selector_hidden": "assert_hidden",
        "url_contains": "assert_url_contains",
        "title_contains": "assert_title_contains",
    }
    return {
        **assertion,
        "action": action_map.get(assertion_type, assertion_type),
        "value": value,
        "name": assertion.get("name") or f"断言：{assertion_type}",
        "_kind": "assertion",
    }


def _execute_ui_step(page, step: dict, timeout_ms: int) -> None:
    action = step.get("action")
    selector = step.get("selector")
    value = step.get("value")

    if action == "goto":
        page.goto(
            str(value),
            wait_until=step.get("wait_until") or "domcontentloaded",
            timeout=timeout_ms,
        )
    elif action == "wait_for_text":
        if selector:
            page.locator(selector).filter(has_text=str(value)).first.wait_for(
                state="visible", timeout=timeout_ms
            )
        else:
            page.locator(f"text={value}").first.wait_for(timeout=timeout_ms)
    elif action == "wait_for_selector":
        page.locator(selector).first.wait_for(
            state=step.get("state") or "visible", timeout=timeout_ms
        )
    elif action == "click":
        page.locator(selector).first.click(timeout=timeout_ms)
    elif action == "fill":
        page.locator(selector).first.fill(str(value or ""), timeout=timeout_ms)
    elif action == "press":
        page.locator(selector).first.press(str(value), timeout=timeout_ms)
    elif action == "select_option":
        page.locator(selector).first.select_option(value, timeout=timeout_ms)
    elif action == "check":
        page.locator(selector).first.check(timeout=timeout_ms)
    elif action == "uncheck":
        page.locator(selector).first.uncheck(timeout=timeout_ms)
    elif action == "hover":
        page.locator(selector).first.hover(timeout=timeout_ms)
    elif action == "wait":
        duration_ms = int(step.get("duration_ms") or 0)
        if duration_ms > timeout_ms:
            raise TimeoutError("等待时间超过本次执行剩余时间")
        page.wait_for_timeout(duration_ms)
    elif action == "set_viewport":
        page.set_viewport_size({"width": int(step["width"]), "height": int(step["height"])})
    elif action == "assert_text":
        if selector:
            locator = page.locator(selector).filter(has_text=str(value)).first
            locator.wait_for(state="visible", timeout=timeout_ms)
        else:
            page.locator(f"text={value}").first.wait_for(timeout=timeout_ms)
    elif action == "assert_text_hidden":
        if selector:
            page.locator(selector).filter(has_text=str(value)).first.wait_for(
                state="hidden", timeout=timeout_ms
            )
        else:
            page.locator(f"text={value}").first.wait_for(state="hidden", timeout=timeout_ms)
    elif action == "assert_visible":
        page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
    elif action == "assert_hidden":
        page.locator(selector).first.wait_for(state="hidden", timeout=timeout_ms)
    elif action == "assert_url_contains":
        page.wait_for_function(
            "expected => window.location.href.includes(expected)",
            str(value),
            timeout=timeout_ms,
        )
    elif action == "assert_title_contains":
        page.wait_for_function(
            "expected => document.title.includes(expected)",
            str(value),
            timeout=timeout_ms,
        )
    else:
        raise ValueError(f"不支持的步骤类型: {action}")


def _execute_api_case_httpx(
    db: Session, run: TestRun, case: APICase, project: Project, deadline: float | None = None
) -> dict:
    environment = _resolve_environment(db, project, run.environment_id)
    variables = environment.variables_json if environment and environment.variables_json else None
    prepared = prepare_http_request(
        method=case.method,
        project=project,
        environment=environment,
        case_path=case.path,
        case_headers=case.headers_json,
        case_body=case.body_json,
        variables=variables,
    )

    request_payload = {
        "method": prepared.method,
        "url": prepared.url,
        "headers": prepared.headers,
        "body": prepared.body,
    }

    parsed_url = urlparse(prepared.url)
    if parsed_url.hostname == "testserver":
        from app.main import app

        with TestClient(app, base_url="http://testserver") as client:
            response = client.request(
                prepared.method,
                parsed_url.path,
                headers=prepared.headers,
                **prepared.kwargs(),
            )
    else:
        timeout_seconds = _remaining_timeout_seconds_or_raise(run, deadline) if deadline else _run_timeout_seconds(run)
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.request(
                prepared.method,
                prepared.url,
                headers=prepared.headers,
                **prepared.kwargs(),
            )

    status = "SUCCESS" if response.status_code == case.expected_status else "FAILED"
    summary = f"接口返回 {response.status_code}，预期 {case.expected_status}"
    response_payload = {
        "status_code": response.status_code,
        "body": _safe_json_or_text(response),
    }
    artifacts = [
        _write_run_artifact(run.id, "request.json", request_payload),
        _write_run_artifact(run.id, "response.json", response_payload),
    ]
    return {
        "status": status,
        "summary": summary,
        "error_type": None if status == "SUCCESS" else "ASSERTION",
        "exit_code": 0 if status == "SUCCESS" else 1,
        "stdout_text": f"HTTP {prepared.method} {prepared.url}\nstatus={response.status_code}",
        "stderr_text": "" if status == "SUCCESS" else summary,
        "artifacts_json": artifacts,
        "request_payload": request_payload,
        "response_payload": response_payload,
        "step_results_json": [{"name": "send_request", "status": status, "detail": summary}],
    }


def _execute_api_case_pytest(
    db: Session, run: TestRun, case: APICase, project: Project, deadline: float | None = None
) -> dict:
    environment = _resolve_environment(db, project, run.environment_id)
    variables = environment.variables_json if environment and environment.variables_json else None
    prepared = prepare_http_request(
        method=case.method,
        project=project,
        environment=environment,
        case_path=case.path,
        case_headers=case.headers_json,
        case_body=case.body_json,
        variables=variables,
    )

    request_payload = {
        "method": prepared.method,
        "url": prepared.url,
        "headers": prepared.headers,
        "body": prepared.body,
    }

    test_code = textwrap.dedent(
        """
        import json
        import os
        import base64
        import httpx

        def enabled_pairs(rows):
            return {
                str(item.get("key")): item.get("value", "")
                for item in rows or []
                if item.get("enabled", True) and str(item.get("key", "")).strip()
            }

        def request_body_kwargs(body):
            if not body:
                return {}
            if not isinstance(body, dict) or "mode" not in body:
                return {"json": body}
            mode = body.get("mode")
            if mode == "none":
                return {}
            if mode == "form-data":
                return {"files": {key: (None, value) for key, value in enabled_pairs(body.get("form_data")).items()}}
            if mode == "x-www-form-urlencoded":
                return {"data": enabled_pairs(body.get("urlencoded"))}
            if mode == "graphql":
                graphql = body.get("graphql") or {}
                return {"json": {"query": graphql.get("query", ""), "variables": graphql.get("variables") or {}}}
            if mode == "binary":
                binary = body.get("binary") or {}
                content = binary.get("content") or binary.get("content_base64") or ""
                if binary.get("encoding") == "base64":
                    return {"content": base64.b64decode(content) if content else b""}
                return {"content": str(content).encode("utf-8")}
            if mode == "raw":
                raw = body.get("raw", "")
                if body.get("raw_type", "json") == "json":
                    try:
                        return {"json": json.loads(raw) if isinstance(raw, str) else raw}
                    except Exception:
                        return {"content": raw}
                return {"content": raw}
            return {"json": body}

        def test_api_case():
            url = os.environ["TARGET_URL"]
            method = os.environ["METHOD"]
            headers = json.loads(os.environ.get("HEADERS", "{}"))
            body_raw = os.environ.get("BODY")
            body = json.loads(body_raw) if body_raw else None
            expected = int(os.environ.get("EXPECTED_STATUS", "200"))
            timeout = float(os.environ.get("TIMEOUT", "30"))

            response = httpx.request(method, url, headers=headers, timeout=timeout, **request_body_kwargs(body))
            result = {
                "status_code": response.status_code,
                "body_text": response.text[:2000],
            }
            result_path = os.environ.get("RESULT_PATH")
            if result_path:
                with open(result_path, "w", encoding="utf-8") as handle:
                    json.dump(result, handle, ensure_ascii=False)

            assert response.status_code == expected
        """
    ).strip()

    with tempfile.TemporaryDirectory(prefix="api_case_") as temp_dir:
        test_path = os.path.join(temp_dir, "test_api_case.py")
        result_path = os.path.join(temp_dir, "result.json")
        with open(test_path, "w", encoding="utf-8") as handle:
            handle.write(test_code)

        env = os.environ.copy()
        env.update(
            {
                "TARGET_URL": prepared.url,
                "METHOD": prepared.method,
                "HEADERS": json.dumps(prepared.headers, ensure_ascii=False),
                "BODY": json.dumps(prepared.body, ensure_ascii=False) if prepared.body else "",
                "EXPECTED_STATUS": str(case.expected_status),
                "TIMEOUT": str(_run_timeout_seconds(run)),
                "RESULT_PATH": result_path,
            }
        )

        timeout_seconds = _remaining_timeout_seconds_or_raise(run, deadline) if deadline else _run_timeout_seconds(run)

        result = subprocess.run(
            ["pytest", "-q", test_path],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_seconds,
        )

        response_payload = {}
        if os.path.exists(result_path):
            try:
                with open(result_path, "r", encoding="utf-8") as handle:
                    response_payload = json.load(handle)
            except Exception:
                response_payload = {}

        status = "SUCCESS" if result.returncode == 0 else "FAILED"
        summary = "pytest 执行成功" if status == "SUCCESS" else "pytest 执行失败"
        if status == "FAILED" and result.stderr:
            summary = f"{summary}: {result.stderr.strip()[-200:]}"

        artifacts = [
            _write_run_artifact(run.id, "request.json", request_payload),
            _write_run_artifact(run.id, "pytest.stdout.log", result.stdout or ""),
            _write_run_artifact(run.id, "pytest.stderr.log", result.stderr or ""),
        ]
        if response_payload:
            artifacts.append(_write_run_artifact(run.id, "response.json", response_payload))

        return {
            "status": status,
            "summary": summary,
            "error_type": None if status == "SUCCESS" else "ASSERTION",
            "exit_code": result.returncode,
            "stdout_text": result.stdout,
            "stderr_text": result.stderr,
            "artifacts_json": artifacts,
            "request_payload": request_payload,
            "response_payload": response_payload,
            "step_results_json": [{"name": "pytest_execution", "status": status, "detail": summary}],
        }


def _execute_api_case(
    db: Session, run: TestRun, case: APICase, project: Project, deadline: float | None = None
) -> dict:
    engine = (settings.execution_engine or "httpx").lower()
    if engine == "pytest":
        return _execute_api_case_pytest(db, run, case, project, deadline=deadline)
    return _execute_api_case_httpx(db, run, case, project, deadline=deadline)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((percentile / 100) * (len(ordered) - 1)))))
    return ordered[index]


def _execute_performance_case(
    db: Session, run: TestRun, case: PerformanceCase, project: Project, deadline: float | None = None
) -> dict:
    environment = _resolve_environment(db, project, run.environment_id)
    variables = environment.variables_json if environment and environment.variables_json else None
    prepared = prepare_http_request(
        method=case.method,
        project=project,
        environment=environment,
        case_path=case.path,
        case_headers=case.headers_json,
        case_body=case.body_json,
        variables=variables,
    )

    total_requests = max(case.total_requests or 1, 1)
    concurrency = max(1, min(case.concurrency or 1, total_requests))
    request_payload = {
        "method": prepared.method,
        "url": prepared.url,
        "headers": prepared.headers,
        "body": prepared.body,
        "expected_status": case.expected_status,
        "concurrency": concurrency,
        "total_requests": total_requests,
        "thresholds": {
            "max_avg_response_ms": case.max_avg_response_ms,
            "max_p95_response_ms": case.max_p95_response_ms,
            "max_error_rate": case.max_error_rate,
        },
    }

    def perform_request(index: int) -> dict:
        started_at = time.perf_counter()
        parsed_url = urlparse(prepared.url)
        response_status = 0
        response_body = None
        error = None
        try:
            if parsed_url.hostname == "testserver":
                from app.main import app

                with TestClient(app, base_url="http://testserver") as client:
                    response = client.request(prepared.method, parsed_url.path, headers=prepared.headers, **prepared.kwargs())
                response_status = response.status_code
                response_body = response.text[:500]
            else:
                timeout_seconds = _remaining_timeout_seconds_or_raise(run, deadline) if deadline else _run_timeout_seconds(run)
                with httpx.Client(timeout=timeout_seconds) as client:
                    response = client.request(prepared.method, prepared.url, headers=prepared.headers, **prepared.kwargs())
                response_status = response.status_code
                response_body = response.text[:500]
        except Exception as exc:
            error = str(exc)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        success = error is None and response_status == case.expected_status
        return {
            "index": index + 1,
            "status": "SUCCESS" if success else "FAILED",
            "status_code": response_status,
            "duration_ms": duration_ms,
            "error": error,
            "response_sample": response_body,
        }

    started_at = time.perf_counter()
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_map = {executor.submit(perform_request, index): index for index in range(total_requests)}
        for future in as_completed(future_map):
            results.append(future.result())

    results.sort(key=lambda item: item["index"])
    duration_values = [float(item["duration_ms"]) for item in results]
    success_count = sum(1 for item in results if item["status"] == "SUCCESS")
    failure_count = total_requests - success_count
    error_rate = round(failure_count / total_requests, 4)
    avg_response_ms = round(sum(duration_values) / len(duration_values), 1) if duration_values else 0.0
    p95_response_ms = round(_percentile(duration_values, 95), 1) if duration_values else 0.0
    throughput = round(total_requests / max(time.perf_counter() - started_at, 0.001), 2)

    threshold_errors = []
    if case.max_avg_response_ms is not None and avg_response_ms > case.max_avg_response_ms:
        threshold_errors.append(f"平均响应 {avg_response_ms}ms 超过阈值 {case.max_avg_response_ms}ms")
    if case.max_p95_response_ms is not None and p95_response_ms > case.max_p95_response_ms:
        threshold_errors.append(f"P95 {p95_response_ms}ms 超过阈值 {case.max_p95_response_ms}ms")
    if case.max_error_rate is not None and error_rate > case.max_error_rate:
        threshold_errors.append(f"错误率 {round(error_rate * 100, 2)}% 超过阈值 {round(case.max_error_rate * 100, 2)}%")

    step_results = [
        {
            "name": f"request_{item['index']}",
            "status": item["status"],
            "duration_ms": item["duration_ms"],
            "detail": {
                "status_code": item["status_code"],
                "error": item["error"],
                "response_sample": item["response_sample"],
                "target_url": prepared.url,
            },
        }
        for item in results
    ]
    step_results.append(
        {
            "name": "performance_summary",
            "status": "SUCCESS" if not threshold_errors else "FAILED",
            "detail": {
                "avg_response_ms": avg_response_ms,
                "p95_response_ms": p95_response_ms,
                "error_rate": error_rate,
                "throughput_rps": throughput,
                "success_count": success_count,
                "failure_count": failure_count,
                "threshold_errors": threshold_errors,
            },
        }
    )

    response_payload = {
        "avg_response_ms": avg_response_ms,
        "p95_response_ms": p95_response_ms,
        "error_rate": error_rate,
        "throughput_rps": throughput,
        "success_count": success_count,
        "failure_count": failure_count,
        "results": results,
    }
    artifacts = [
        _write_run_artifact(run.id, "performance-request.json", request_payload),
        _write_run_artifact(run.id, "performance-summary.json", response_payload),
        _write_run_artifact(run.id, "performance-results.json", results),
    ]
    summary = (
        f"压测完成：成功 {success_count}/{total_requests}，平均 {avg_response_ms}ms，"
        f"P95 {p95_response_ms}ms，错误率 {round(error_rate * 100, 2)}%"
    )
    if threshold_errors:
        summary = f"{summary}；阈值未通过"
    return {
        "status": "SUCCESS" if not threshold_errors and failure_count == 0 else "FAILED",
        "summary": summary,
        "error_type": None if not threshold_errors and failure_count == 0 else "ASSERTION",
        "exit_code": 0 if not threshold_errors and failure_count == 0 else 1,
        "stdout_text": json.dumps(response_payload, ensure_ascii=False, indent=2),
        "stderr_text": "\n".join(threshold_errors),
        "artifacts_json": artifacts,
        "request_payload": request_payload,
        "response_payload": response_payload,
        "step_results_json": step_results,
    }


def _execute_ui_case(
    db: Session, run: TestRun, case: UICase, project: Project, deadline: float | None = None
) -> dict:
    environment = _resolve_environment(db, project, run.environment_id)
    variables = environment.variables_json if environment and environment.variables_json else None

    target_url = _render_template(case.target_url, variables, "case.target_url")
    steps = _render_data(case.steps_json or [], variables, "case.steps_json")
    assertions = _render_data(case.assertions_json or [], variables, "case.assertions_json")
    expect_text = _render_template(case.expect_text, variables, "case.expect_text")

    checkpoints: list[dict] = []
    if not steps or steps[0].get("action") != "goto":
        checkpoints.append(
            {
                "action": "goto",
                "value": target_url,
                "name": "打开目标页面",
                "_kind": "navigation",
            }
        )
    checkpoints.extend({**step, "_kind": "step"} for step in steps)
    checkpoints.extend(_ui_assertion_as_step(assertion) for assertion in assertions)
    checkpoints.append(
        {
            "action": "assert_text",
            "value": expect_text,
            "name": "最终文本断言",
            "_kind": "final_assertion",
        }
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        tracing = getattr(context, "tracing", None)
        if tracing and hasattr(tracing, "start"):
            tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        step_results = []
        artifacts: list[dict] = []
        screenshot_warnings: list[dict] = []
        trace_path = os.path.join(_ensure_run_dir(run.id), "ui-trace.zip")

        def step_timeout(seconds: int) -> int:
            return _playwright_timeout_ms_from_deadline(run, deadline, seconds) if deadline else _playwright_timeout_ms(run, seconds)

        def capture_step_screenshot(index: int, action: str, suffix: str = "") -> dict | None:
            filename = f"step-{index + 1:02d}-{action}{suffix}.png"
            try:
                content = page.screenshot(
                    full_page=False,
                    timeout=step_timeout(5),
                    animations="disabled",
                    caret="hide",
                )
            except Exception as exc:
                screenshot_warnings.append(
                    {
                        "checkpoint": index + 1,
                        "action": action,
                        "file_name": filename,
                        "error": str(exc) or exc.__class__.__name__,
                    }
                )
                return None
            artifact = _write_run_artifact(run.id, filename, content, binary=True)
            artifacts.append(artifact)
            return artifact

        def append_screenshot_warnings() -> None:
            if screenshot_warnings:
                artifacts.append(
                    _write_run_artifact(run.id, "ui-evidence-warnings.json", screenshot_warnings)
                )
                screenshot_warnings.clear()

        try:
            for index, step in enumerate(checkpoints):
                action = step.get("action")
                started_at = time.perf_counter()
                selector = step.get("selector")
                value = step.get("value")
                try:
                    _execute_ui_step(page, step, step_timeout(30 if action == "goto" else 20))
                    screenshot_artifact = capture_step_screenshot(index, action or "step")
                    step_results.append(
                        {
                            "name": step.get("name") or action,
                            "status": "SUCCESS",
                            "duration_ms": int((time.perf_counter() - started_at) * 1000),
                            "detail": _ui_step_detail(
                                step,
                                page_url=page.url,
                                selector=selector,
                                value=value if isinstance(value, str) else None,
                                screenshot=screenshot_artifact["name"] if screenshot_artifact else None,
                            ),
                        }
                    )
                except Exception as exc:
                    screenshot_artifact = capture_step_screenshot(index, action or "step", "-failure")
                    step_results.append(
                        {
                            "name": step.get("name") or action or f"step_{index + 1}",
                            "status": "FAILED",
                            "duration_ms": int((time.perf_counter() - started_at) * 1000),
                            "detail": _ui_step_detail(
                                step,
                                page_url=page.url if hasattr(page, "url") else None,
                                selector=selector,
                                value=value if isinstance(value, str) else None,
                                error=str(exc),
                                screenshot=screenshot_artifact["name"] if screenshot_artifact else None,
                            ),
                        }
                    )
                    raise
            summary_screenshot = page.screenshot(
                full_page=True,
                timeout=step_timeout(10),
                animations="disabled",
                caret="hide",
            )
            success_artifact = _write_run_artifact(run.id, "ui-success.png", summary_screenshot, binary=True)
            artifacts.append(success_artifact)
            append_screenshot_warnings()
            if tracing and hasattr(tracing, "stop"):
                tracing.stop(path=trace_path)
                if os.path.exists(trace_path):
                    artifacts.append({"name": "ui-trace.zip", "path": trace_path, "type": "zip"})
            return {
                "status": "SUCCESS",
                "summary": f"UI 用例执行成功，共 {len(step_results)} 个检查点",
                "error_type": None,
                "exit_code": 0,
                "stdout_text": f"UI case visited {target_url}\nfinal_url={page.url}",
                "stderr_text": "",
                "artifacts_json": artifacts,
                "request_payload": {
                    "target_url": target_url,
                    "steps": steps,
                    "assertions": assertions,
                },
                "response_payload": {
                    "expect_text": expect_text,
                    "final_url": page.url,
                    "checkpoint_count": len(step_results),
                },
                "step_results_json": step_results,
            }
        except Exception as exc:
            if isinstance(exc, (subprocess.TimeoutExpired, PlaywrightTimeoutError, TimeoutError)):
                failure_status, failure_error_type = "TIMEOUT", "TIMEOUT"
            elif isinstance(exc, AssertionError):
                failure_status, failure_error_type = "FAILED", "ASSERTION"
            elif isinstance(exc, ValueError):
                failure_status, failure_error_type = "FAILED", "CONFIG"
            else:
                failure_status, failure_error_type = "ERROR", "SYSTEM"
            failure_artifact = capture_step_screenshot(len(step_results), "ui", "-failure")
            if failure_artifact is None:
                try:
                    screenshot = page.screenshot(full_page=True)
                    failure_artifact = _write_run_artifact(run.id, "ui-failure.png", screenshot, binary=True)
                    artifacts.append(failure_artifact)
                except Exception:
                    failure_artifact = None
            error_text_artifact = _write_run_artifact(run.id, "ui-error.txt", traceback.format_exc())
            artifacts.append(error_text_artifact)
            append_screenshot_warnings()
            try:
                if tracing and hasattr(tracing, "stop"):
                    tracing.stop(path=trace_path)
                    if os.path.exists(trace_path):
                        artifacts.append({"name": "ui-trace.zip", "path": trace_path, "type": "zip"})
            except Exception:
                pass
            raise RuntimeError(
                json.dumps(
                    {
                        "error": str(exc) or exc.__class__.__name__,
                        "error_class": exc.__class__.__name__,
                        "status": failure_status,
                        "error_type": failure_error_type,
                        "artifacts": artifacts,
                        "steps": step_results,
                    },
                    ensure_ascii=False,
                )
            )
        finally:
            context.close()
            browser.close()


def _to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _write_plan_report_files(plan_run: TestPlanRun, runs: list[TestRun]) -> tuple[str, str]:
    root_dir = settings.report_output_dir
    if not os.path.isabs(root_dir):
        root_dir = os.path.abspath(root_dir)
    plan_dir = os.path.join(root_dir, f"plan_run_{plan_run.id}")
    os.makedirs(plan_dir, exist_ok=True)

    summary_path = os.path.join(plan_dir, "summary.json")
    junit_path = os.path.join(plan_dir, "junit.xml")

    summary_payload = {
        "plan_run": {
            "id": plan_run.id,
            "plan_id": plan_run.plan_id,
            "project_id": plan_run.project_id,
            "environment_id": plan_run.environment_id,
            "status": plan_run.status,
            "summary": plan_run.summary,
            "error_type": plan_run.error_type,
            "retry_count": plan_run.retry_count,
            "total_count": plan_run.total_count,
            "pass_count": plan_run.pass_count,
            "fail_count": plan_run.fail_count,
            "duration_ms": plan_run.duration_ms,
            "started_at": _to_iso(plan_run.started_at),
            "finished_at": _to_iso(plan_run.finished_at),
            "created_at": _to_iso(plan_run.created_at),
            "updated_at": _to_iso(plan_run.updated_at),
        },
        "test_runs": [
            {
                "id": run.id,
                "case_type": run.case_type,
                "case_id": run.case_id,
                "case_name": run.case_name,
                "status": run.status,
                "summary": run.summary,
                "error_type": run.error_type,
                "duration_ms": run.duration_ms,
                "started_at": _to_iso(run.started_at),
                "finished_at": _to_iso(run.finished_at),
                "request_payload": run.request_payload,
                "response_payload": run.response_payload,
                "artifacts_json": run.artifacts_json,
                "step_results_json": run.step_results_json,
            }
            for run in runs
        ],
    }
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary_payload, handle, ensure_ascii=False, indent=2)

    testcases = []
    total_seconds = 0.0
    failures = 0
    for run in runs:
        case_time = float((run.duration_ms or 0) / 1000)
        total_seconds += case_time
        case_name = escape(run.case_name or f"{run.case_type}-{run.case_id}")
        class_name = escape(run.case_type or "CASE")
        if run.status != "SUCCESS":
            failures += 1
            message = escape(run.summary or "执行失败")
            testcase = (
                f'<testcase classname="{class_name}" name="{case_name}" time="{case_time:.3f}">'
                f'<failure message="{message}">{message}</failure>'
                "</testcase>"
            )
        else:
            testcase = f'<testcase classname="{class_name}" name="{case_name}" time="{case_time:.3f}"></testcase>'
        testcases.append(testcase)

    suite_name = f"test-plan-{plan_run.id}"
    testsuite = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<testsuite name="{escape(suite_name)}" tests="{len(runs)}" failures="{failures}" '
        f'errors="0" skipped="0" time="{total_seconds:.3f}">'
        + "".join(testcases)
        + "</testsuite>"
    )
    with open(junit_path, "w", encoding="utf-8") as handle:
        handle.write(testsuite)

    return summary_path, junit_path


@celery_app.task(name="app.tasks.run_api_case")
def run_api_case(run_id: int) -> dict:
    db = _open_db()
    started_at = time.perf_counter()
    try:
        run = db.get(TestRun, run_id)
        if run is None:
            return {"status": "FAILED", "summary": f"执行记录 {run_id} 不存在"}

        case = db.get(APICase, run.case_id)
        project = db.get(Project, run.project_id)
        if case is None or project is None:
            finalize_run(db, run, status="FAILED", summary="关联的项目或接口用例不存在", error_type="SYSTEM")
            return {"status": "FAILED", "summary": "关联记录不存在"}

        if not mark_run_started(db, run):
            return {"status": "CANCELLED", "summary": "执行已取消"}
        result = _execute_case_with_retries(
            db, run, lambda deadline: _execute_api_case(db, run, case, project, deadline=deadline)
        )
        status = result["status"]
        summary = result["summary"]
        finalize_run(
            db,
            run,
            status=status,
            summary=summary,
            error_type=result.get("error_type"),
            exit_code=result.get("exit_code"),
            stdout_text=result.get("stdout_text"),
            stderr_text=result.get("stderr_text"),
            artifacts_json=result.get("artifacts_json"),
            step_results_json=result.get("step_results_json"),
            duration_ms=int((time.perf_counter() - started_at) * 1000),
            request_payload=result["request_payload"],
            response_payload=result["response_payload"],
        )
        return {"status": status, "summary": summary}
    except Exception as exc:
        run = db.get(TestRun, run_id)
        if run is not None:
            artifacts, step_results = _normalize_exception_artifacts(run.id, exc)
            finalize_run(
                db,
                run,
                status="ERROR",
                summary=f"执行异常: {exc}",
                error_type="SYSTEM",
                stderr_text=traceback.format_exc(),
                artifacts_json=artifacts,
                step_results_json=step_results,
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
        return {"status": "ERROR", "summary": str(exc)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.run_ui_case")
def run_ui_case(run_id: int) -> dict:
    db = _open_db()
    started_at = time.perf_counter()
    case = None
    try:
        run = db.get(TestRun, run_id)
        if run is None:
            return {"status": "FAILED", "summary": f"执行记录 {run_id} 不存在"}

        case = db.get(UICase, run.case_id)
        if case is None:
            finalize_run(db, run, status="FAILED", summary="UI 用例不存在", error_type="SYSTEM")
            return {"status": "FAILED", "summary": "UI 用例不存在"}

        if not mark_run_started(db, run):
            return {"status": "CANCELLED", "summary": "执行已取消"}
        project = db.get(Project, run.project_id)
        if project is None:
            finalize_run(db, run, status="FAILED", summary="关联项目不存在", error_type="SYSTEM")
            return {"status": "FAILED", "summary": "关联项目不存在"}

        result = _execute_case_with_retries(
            db, run, lambda deadline: _execute_ui_case(db, run, case, project, deadline=deadline)
        )
        summary = result["summary"]
        finalize_run(
            db,
            run,
            status=result["status"],
            summary=summary,
            error_type=result.get("error_type"),
            exit_code=result.get("exit_code"),
            stdout_text=result.get("stdout_text"),
            stderr_text=result.get("stderr_text"),
            artifacts_json=result.get("artifacts_json"),
            step_results_json=result.get("step_results_json"),
            duration_ms=int((time.perf_counter() - started_at) * 1000),
            request_payload=result["request_payload"],
            response_payload=result["response_payload"],
        )
        return {"status": result["status"], "summary": summary}
    except Exception as exc:
        run = db.get(TestRun, run_id)
        if run is not None:
            artifacts, step_results = _normalize_exception_artifacts(run.id, exc)
            finalize_run(
                db,
                run,
                status="ERROR",
                summary=f"执行异常: {exc}",
                error_type="SYSTEM",
                stderr_text=traceback.format_exc(),
                artifacts_json=artifacts,
                step_results_json=step_results,
                duration_ms=int((time.perf_counter() - started_at) * 1000),
                request_payload={"target_url": getattr(case, "target_url", None)},
            )
        return {"status": "ERROR", "summary": str(exc)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.run_performance_case")
def run_performance_case(run_id: int) -> dict:
    db = _open_db()
    started_at = time.perf_counter()
    try:
        run = db.get(TestRun, run_id)
        if run is None:
            return {"status": "FAILED", "summary": f"执行记录 {run_id} 不存在"}

        case = db.get(PerformanceCase, run.case_id)
        if case is None:
            finalize_run(db, run, status="FAILED", summary="性能用例不存在", error_type="SYSTEM")
            return {"status": "FAILED", "summary": "性能用例不存在"}

        if not mark_run_started(db, run):
            return {"status": "CANCELLED", "summary": "执行已取消"}
        project = db.get(Project, run.project_id)
        if project is None:
            finalize_run(db, run, status="FAILED", summary="关联项目不存在", error_type="SYSTEM")
            return {"status": "FAILED", "summary": "关联项目不存在"}

        result = _execute_case_with_retries(
            db, run, lambda deadline: _execute_performance_case(db, run, case, project, deadline=deadline)
        )
        finalize_run(
            db,
            run,
            status=result["status"],
            summary=result["summary"],
            error_type=result.get("error_type"),
            exit_code=result.get("exit_code"),
            stdout_text=result.get("stdout_text"),
            stderr_text=result.get("stderr_text"),
            artifacts_json=result.get("artifacts_json"),
            step_results_json=result.get("step_results_json"),
            duration_ms=int((time.perf_counter() - started_at) * 1000),
            request_payload=result["request_payload"],
            response_payload=result["response_payload"],
        )
        return {"status": result["status"], "summary": result["summary"]}
    except Exception as exc:
        run = db.get(TestRun, run_id)
        if run is not None:
            artifacts, step_results = _normalize_exception_artifacts(run.id, exc)
            finalize_run(
                db,
                run,
                status="ERROR",
                summary=f"执行异常: {exc}",
                error_type="SYSTEM",
                stderr_text=traceback.format_exc(),
                artifacts_json=artifacts,
                step_results_json=step_results,
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
        return {"status": "ERROR", "summary": str(exc)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.run_test_plan")
def run_test_plan(plan_run_id: int) -> dict:
    db = _open_db()
    started_at = time.perf_counter()
    try:
        plan_run = db.get(TestPlanRun, plan_run_id)
        if plan_run is None:
            return {"status": "FAILED", "summary": f"测试计划执行 {plan_run_id} 不存在"}

        plan_run.status = "RUNNING"
        plan_run.summary = "测试计划执行中"
        plan_run.started_at = utc_now_naive()
        db.commit()
        db.refresh(plan_run)

        runs = db.query(TestRun).filter(TestRun.plan_run_id == plan_run.id).order_by(TestRun.id.asc()).all()
        total = len(runs)
        pass_count = 0
        fail_count = 0

        for run in runs:
            case_started_at = time.perf_counter()
            try:
                project = db.get(Project, run.project_id)
                if project is None:
                    finalize_run(db, run, status="FAILED", summary="关联项目不存在", error_type="SYSTEM")
                    fail_count += 1
                    continue

                if run.case_type == "API":
                    case = db.get(APICase, run.case_id)
                    if case is None:
                        finalize_run(db, run, status="FAILED", summary="接口用例不存在", error_type="SYSTEM")
                        fail_count += 1
                        continue
                    if not mark_run_started(db, run):
                        fail_count += 1
                        continue
                    result = _execute_case_with_retries(
                        db, run, lambda deadline: _execute_api_case(db, run, case, project, deadline=deadline)
                    )
                elif run.case_type == "UI":
                    case = db.get(UICase, run.case_id)
                    if case is None:
                        finalize_run(db, run, status="FAILED", summary="UI 用例不存在", error_type="SYSTEM")
                        fail_count += 1
                        continue
                    if not mark_run_started(db, run):
                        fail_count += 1
                        continue
                    result = _execute_case_with_retries(
                        db, run, lambda deadline: _execute_ui_case(db, run, case, project, deadline=deadline)
                    )
                else:
                    finalize_run(db, run, status="FAILED", summary="未知用例类型", error_type="SYSTEM")
                    fail_count += 1
                    continue

                finalize_run(
                    db,
                    run,
                    status=result["status"],
                    summary=result["summary"],
                    error_type=result.get("error_type"),
                    exit_code=result.get("exit_code"),
                    stdout_text=result.get("stdout_text"),
                    stderr_text=result.get("stderr_text"),
                    artifacts_json=result.get("artifacts_json"),
                    step_results_json=result.get("step_results_json"),
                    duration_ms=int((time.perf_counter() - case_started_at) * 1000),
                    request_payload=result["request_payload"],
                    response_payload=result["response_payload"],
                )
                if result["status"] == "SUCCESS":
                    pass_count += 1
                else:
                    fail_count += 1
            except Exception as exc:
                artifacts, step_results = _normalize_exception_artifacts(run.id, exc)
                finalize_run(
                    db,
                    run,
                    status="ERROR",
                    summary=f"执行异常: {exc}",
                    error_type="SYSTEM",
                    stderr_text=traceback.format_exc(),
                    artifacts_json=artifacts,
                    step_results_json=step_results,
                    duration_ms=int((time.perf_counter() - case_started_at) * 1000),
                )
                fail_count += 1

        plan_status = "SUCCESS" if fail_count == 0 else "FAILED"
        plan_run.status = plan_status
        plan_run.summary = f"总计 {total}，成功 {pass_count}，失败 {fail_count}"
        plan_run.total_count = total
        plan_run.pass_count = pass_count
        plan_run.fail_count = fail_count
        plan_run.finished_at = utc_now_naive()
        plan_run.duration_ms = int((time.perf_counter() - started_at) * 1000)
        summary_path, junit_path = _write_plan_report_files(plan_run, runs)
        plan_run.report_json_path = summary_path
        plan_run.report_junit_path = junit_path
        plan_run.report_generated_at = utc_now_naive()
        db.commit()
        db.refresh(plan_run)

        return {"status": plan_status, "summary": plan_run.summary}
    except Exception as exc:
        plan_run = db.get(TestPlanRun, plan_run_id)
        if plan_run is not None:
            plan_run.status = "FAILED"
            plan_run.error_type = "SYSTEM"
            plan_run.summary = f"测试计划执行异常: {exc}"
            plan_run.finished_at = utc_now_naive()
            plan_run.duration_ms = int((time.perf_counter() - started_at) * 1000)
            db.commit()
        return {"status": "FAILED", "summary": str(exc)}
    finally:
        db.close()
