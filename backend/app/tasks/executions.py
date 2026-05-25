from __future__ import annotations

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
from app.services import finalize_run, mark_run_started
from app.timeutil import utc_now_naive


_TEMPLATE_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class MissingTemplateVariableError(ValueError):
    def __init__(self, field_name: str, missing_keys: list[str]):
        joined = ", ".join(missing_keys)
        super().__init__(f"环境变量缺失: {joined}（字段: {field_name}）")
        self.field_name = field_name
        self.missing_keys = missing_keys


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


def _render_template(value: str, variables: dict | None, field_name: str = "value") -> str:
    missing_keys = sorted({key for key in _TEMPLATE_VAR_PATTERN.findall(value) if not variables or key not in variables})
    if missing_keys:
        raise MissingTemplateVariableError(field_name, missing_keys)
    if not variables:
        return value
    rendered = value
    for key, val in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(val))
    return rendered


def _render_data(value, variables: dict | None, field_name: str = "value"):
    if isinstance(value, str):
        return _render_template(value, variables, field_name)
    if isinstance(value, dict):
        return {key: _render_data(val, variables, f"{field_name}.{key}") for key, val in value.items()}
    if isinstance(value, list):
        return [_render_data(item, variables, f"{field_name}[{index}]") for index, item in enumerate(value)]
    return value


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
            artifacts, step_results = _normalize_exception_artifacts(run.id, exc)
            last_result = {
                "status": "ERROR",
                "summary": f"执行异常: {exc}",
                "error_type": "SYSTEM",
                "stderr_text": traceback.format_exc(),
                "artifacts_json": artifacts,
                "step_results_json": step_results,
            }

        run.retry_count = base_retry_count + attempt_index
        db.commit()
        db.refresh(run)
        if not _retryable_status(last_result["status"]) or attempt_index >= max_retries:
            if attempt_index > 0:
                last_result["summary"] = _append_retry_trace(last_result["summary"], attempts)
            return last_result

        attempts.append(f"第{attempt_index + 1}次{last_result['status']}")

    return last_result or {"status": "ERROR", "summary": "执行结果为空"}


def _build_runtime_headers(environment: Environment | None, case_headers: dict | None, variables: dict | None) -> dict:
    headers = {}
    if environment and environment.headers_json:
        headers.update(_render_data(environment.headers_json, variables, "environment.headers_json"))
    if environment and environment.auth_config_json and isinstance(environment.auth_config_json, dict):
        auth_config = _render_data(environment.auth_config_json, variables, "environment.auth_config_json")
        token = auth_config.get("token")
        if token:
            header_name = auth_config.get("header_name", "Authorization")
            token_prefix = auth_config.get("token_prefix", "Bearer")
            headers[header_name] = f"{token_prefix} {token}".strip()
    if case_headers:
        headers.update(_render_data(case_headers, variables, "case.headers_json"))
    return headers


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


def _normalize_exception_artifacts(run_id: int, exc: Exception) -> tuple[list[dict], list[dict]]:
    payload = None
    if isinstance(exc, RuntimeError):
        try:
            payload = json.loads(str(exc))
        except Exception:
            payload = None
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
        "selector": selector,
        "value": value,
        "page_url": page_url,
    }
    if error:
        detail["error"] = error
    if screenshot:
        detail["screenshot"] = screenshot
    return detail


def _execute_api_case_httpx(
    db: Session, run: TestRun, case: APICase, project: Project, deadline: float | None = None
) -> dict:
    environment = _resolve_environment(db, project, run.environment_id)
    variables = environment.variables_json if environment and environment.variables_json else None
    base_url = _render_template(environment.base_url if environment else project.base_url, variables, "base_url")
    headers = _build_runtime_headers(environment, case.headers_json, variables)
    rendered_path = _render_template(case.path, variables, "case.path")
    rendered_body = _render_data(case.body_json, variables, "case.body_json")

    target_url = urljoin(base_url.rstrip("/") + "/", rendered_path.lstrip("/"))
    request_payload = {
        "method": case.method,
        "url": target_url,
        "headers": headers,
        "body": rendered_body,
    }

    parsed_url = urlparse(target_url)
    if parsed_url.hostname == "testserver":
        from app.main import app

        with TestClient(app, base_url="http://testserver") as client:
            response = client.request(
                case.method.upper(),
                parsed_url.path,
                headers=headers,
                json=rendered_body,
            )
    else:
        timeout_seconds = _remaining_timeout_seconds_or_raise(run, deadline) if deadline else _run_timeout_seconds(run)
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.request(
                case.method.upper(),
                target_url,
                headers=headers,
                json=rendered_body,
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
        "stdout_text": f"HTTP {case.method.upper()} {target_url}\nstatus={response.status_code}",
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
    base_url = _render_template(environment.base_url if environment else project.base_url, variables, "base_url")
    headers = _build_runtime_headers(environment, case.headers_json, variables)
    rendered_path = _render_template(case.path, variables, "case.path")
    rendered_body = _render_data(case.body_json, variables, "case.body_json")
    target_url = urljoin(base_url.rstrip("/") + "/", rendered_path.lstrip("/"))
    request_payload = {
        "method": case.method,
        "url": target_url,
        "headers": headers,
        "body": rendered_body,
    }

    test_code = textwrap.dedent(
        """
        import json
        import os
        import httpx

        def test_api_case():
            url = os.environ["TARGET_URL"]
            method = os.environ["METHOD"]
            headers = json.loads(os.environ.get("HEADERS", "{}"))
            body_raw = os.environ.get("BODY")
            body = json.loads(body_raw) if body_raw else None
            expected = int(os.environ.get("EXPECTED_STATUS", "200"))
            timeout = float(os.environ.get("TIMEOUT", "30"))

            response = httpx.request(method, url, headers=headers, json=body, timeout=timeout)
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
                "TARGET_URL": target_url,
                "METHOD": case.method.upper(),
                "HEADERS": json.dumps(headers, ensure_ascii=False),
                "BODY": json.dumps(rendered_body, ensure_ascii=False) if rendered_body else "",
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
    base_url = _render_template(environment.base_url if environment else project.base_url, variables, "base_url")
    headers = _build_runtime_headers(environment, case.headers_json, variables)
    rendered_path = _render_template(case.path, variables, "case.path")
    rendered_body = _render_data(case.body_json, variables, "case.body_json")
    target_url = urljoin(base_url.rstrip("/") + "/", rendered_path.lstrip("/"))

    total_requests = max(case.total_requests or 1, 1)
    concurrency = max(1, min(case.concurrency or 1, total_requests))
    request_payload = {
        "method": case.method,
        "url": target_url,
        "headers": headers,
        "body": rendered_body,
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
        parsed_url = urlparse(target_url)
        response_status = 0
        response_body = None
        error = None
        try:
            if parsed_url.hostname == "testserver":
                from app.main import app

                with TestClient(app, base_url="http://testserver") as client:
                    response = client.request(case.method.upper(), parsed_url.path, headers=headers, json=rendered_body)
                response_status = response.status_code
                response_body = response.text[:500]
            else:
                timeout_seconds = _remaining_timeout_seconds_or_raise(run, deadline) if deadline else _run_timeout_seconds(run)
                with httpx.Client(timeout=timeout_seconds) as client:
                    response = client.request(case.method.upper(), target_url, headers=headers, json=rendered_body)
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
                "target_url": target_url,
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
    steps = []
    for step in case.steps_json:
        rendered_step = dict(step)
        if "value" in rendered_step and isinstance(rendered_step["value"], str):
            rendered_step["value"] = _render_template(rendered_step["value"], variables, "case.steps_json.value")
        if "selector" in rendered_step and isinstance(rendered_step["selector"], str):
            rendered_step["selector"] = _render_template(
                rendered_step["selector"], variables, "case.steps_json.selector"
            )
        steps.append(rendered_step)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        step_results = []
        artifacts: list[dict] = []
        trace_path = os.path.join(_ensure_run_dir(run.id), "ui-trace.zip")

        def step_timeout(seconds: int) -> int:
            return _playwright_timeout_ms_from_deadline(run, deadline, seconds) if deadline else _playwright_timeout_ms(run, seconds)

        def capture_step_screenshot(index: int, action: str, suffix: str = "") -> dict | None:
            filename = f"step-{index + 1:02d}-{action}{suffix}.png"
            try:
                content = page.screenshot(full_page=True)
            except Exception:
                return None
            artifact = _write_run_artifact(run.id, filename, content, binary=True)
            artifacts.append(artifact)
            return artifact

        try:
            for index, step in enumerate(steps):
                action = step.get("action")
                started_at = time.perf_counter()
                selector = step.get("selector")
                value = step.get("value")
                try:
                    if action == "goto":
                        page.goto(step["value"], wait_until="networkidle", timeout=step_timeout(30))
                    elif action == "wait_for_text":
                        page.locator(f"text={step['value']}").first.wait_for(timeout=step_timeout(20))
                    elif action == "click":
                        page.locator(step["selector"]).first.click(timeout=step_timeout(20))
                    elif action == "fill":
                        page.locator(step["selector"]).first.fill(step.get("value", ""), timeout=step_timeout(20))
                    elif action == "assert_text":
                        page.locator(f"text={step['value']}").first.wait_for(timeout=step_timeout(20))
                    else:
                        raise ValueError(f"不支持的步骤类型: {action}")
                    screenshot_artifact = capture_step_screenshot(index, action or "step")
                    step_results.append(
                        {
                            "name": action,
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
                            "name": action or f"step_{index + 1}",
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

            expect_text = _render_template(case.expect_text, variables, "case.expect_text")
            final_started_at = time.perf_counter()
            page.locator(f"text={expect_text}").first.wait_for(timeout=step_timeout(15))
            final_screenshot = capture_step_screenshot(len(steps), "assert-expect-text")
            step_results.append(
                {
                    "name": "assert_expect_text",
                    "status": "SUCCESS",
                    "duration_ms": int((time.perf_counter() - final_started_at) * 1000),
                    "detail": {
                        "expect_text": expect_text,
                        "page_url": page.url,
                        "screenshot": final_screenshot["name"] if final_screenshot else None,
                    },
                }
            )
            summary_screenshot = page.screenshot(full_page=True)
            success_artifact = _write_run_artifact(run.id, "ui-success.png", summary_screenshot, binary=True)
            artifacts.append(success_artifact)
            context.tracing.stop(path=trace_path)
            if os.path.exists(trace_path):
                artifacts.append({"name": "ui-trace.zip", "path": trace_path, "type": "zip"})
            return {
                "status": "SUCCESS",
                "summary": "UI 巡检执行成功",
                "error_type": None,
                "exit_code": 0,
                "stdout_text": f"UI case visited {target_url}\nfinal_url={page.url}",
                "stderr_text": "",
                "artifacts_json": artifacts,
                "request_payload": {"target_url": target_url, "steps": steps},
                "response_payload": {"expect_text": expect_text, "final_url": page.url},
                "step_results_json": step_results,
            }
        except Exception:
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
            try:
                context.tracing.stop(path=trace_path)
                if os.path.exists(trace_path):
                    artifacts.append({"name": "ui-trace.zip", "path": trace_path, "type": "zip"})
            except Exception:
                pass
            raise RuntimeError(
                json.dumps(
                    {
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
