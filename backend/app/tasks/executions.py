from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import time
from datetime import datetime
from urllib.parse import urljoin
from urllib.parse import urlparse
from xml.sax.saxutils import escape

import httpx
from fastapi.testclient import TestClient
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.models import APICase, Environment, Project, TestPlanRun, TestRun, UICase
from app.services import finalize_run, mark_run_started
from app.timeutil import utc_now_naive


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


def _render_template(value: str, variables: dict | None) -> str:
    if not variables:
        return value
    rendered = value
    for key, val in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(val))
    return rendered


def _resolve_environment(db: Session, project: Project, environment_id: int | None) -> Environment | None:
    if environment_id is None:
        return None
    env = db.get(Environment, environment_id)
    if env is None or env.project_id != project.id:
        return None
    return env


def _execute_api_case_httpx(db: Session, run: TestRun, case: APICase, project: Project) -> dict:
    environment = _resolve_environment(db, project, run.environment_id)
    base_url = environment.base_url if environment else project.base_url
    headers = {}
    if environment and environment.headers_json:
        headers.update(environment.headers_json)
    if case.headers_json:
        headers.update(case.headers_json)

    target_url = urljoin(base_url.rstrip("/") + "/", case.path.lstrip("/"))
    request_payload = {
        "method": case.method,
        "url": target_url,
        "headers": headers,
        "body": case.body_json,
    }

    parsed_url = urlparse(target_url)
    if parsed_url.hostname == "testserver":
        from app.main import app

        with TestClient(app, base_url="http://testserver") as client:
            response = client.request(
                case.method.upper(),
                parsed_url.path,
                headers=headers,
                json=case.body_json,
            )
    else:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.request(
                case.method.upper(),
                target_url,
                headers=headers,
                json=case.body_json,
            )

    status = "SUCCESS" if response.status_code == case.expected_status else "FAILED"
    summary = f"接口返回 {response.status_code}，预期 {case.expected_status}"
    return {
        "status": status,
        "summary": summary,
        "request_payload": request_payload,
        "response_payload": {
            "status_code": response.status_code,
            "body": _safe_json_or_text(response),
        },
    }


def _execute_api_case_pytest(db: Session, run: TestRun, case: APICase, project: Project) -> dict:
    environment = _resolve_environment(db, project, run.environment_id)
    base_url = environment.base_url if environment else project.base_url
    headers = {}
    if environment and environment.headers_json:
        headers.update(environment.headers_json)
    if case.headers_json:
        headers.update(case.headers_json)

    target_url = urljoin(base_url.rstrip("/") + "/", case.path.lstrip("/"))
    request_payload = {
        "method": case.method,
        "url": target_url,
        "headers": headers,
        "body": case.body_json,
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
                "BODY": json.dumps(case.body_json, ensure_ascii=False) if case.body_json else "",
                "EXPECTED_STATUS": str(case.expected_status),
                "TIMEOUT": str(settings.request_timeout_seconds),
                "RESULT_PATH": result_path,
            }
        )

        result = subprocess.run(
            ["pytest", "-q", test_path],
            capture_output=True,
            text=True,
            env=env,
            timeout=settings.request_timeout_seconds + 20,
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

        return {
            "status": status,
            "summary": summary,
            "request_payload": request_payload,
            "response_payload": response_payload,
        }


def _execute_api_case(db: Session, run: TestRun, case: APICase, project: Project) -> dict:
    engine = (settings.execution_engine or "httpx").lower()
    if engine == "pytest":
        return _execute_api_case_pytest(db, run, case, project)
    return _execute_api_case_httpx(db, run, case, project)


def _execute_ui_case(db: Session, run: TestRun, case: UICase, project: Project) -> dict:
    environment = _resolve_environment(db, project, run.environment_id)
    variables = environment.variables_json if environment and environment.variables_json else None

    target_url = _render_template(case.target_url, variables)
    steps = []
    for step in case.steps_json:
        rendered_step = dict(step)
        if "value" in rendered_step and isinstance(rendered_step["value"], str):
            rendered_step["value"] = _render_template(rendered_step["value"], variables)
        if "selector" in rendered_step and isinstance(rendered_step["selector"], str):
            rendered_step["selector"] = _render_template(rendered_step["selector"], variables)
        steps.append(rendered_step)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        for step in steps:
            action = step.get("action")
            if action == "goto":
                page.goto(step["value"], wait_until="networkidle", timeout=30000)
            elif action == "wait_for_text":
                page.locator(f"text={step['value']}").first.wait_for(timeout=20000)
            elif action == "click":
                page.locator(step["selector"]).first.click(timeout=20000)
            elif action == "fill":
                page.locator(step["selector"]).first.fill(step.get("value", ""), timeout=20000)
            elif action == "assert_text":
                page.locator(f"text={step['value']}").first.wait_for(timeout=20000)
            else:
                raise ValueError(f"不支持的步骤类型: {action}")

        expect_text = _render_template(case.expect_text, variables)
        page.locator(f"text={expect_text}").first.wait_for(timeout=15000)
        browser.close()

    summary = "UI 巡检执行成功"
    return {
        "status": "SUCCESS",
        "summary": summary,
        "request_payload": {"target_url": target_url, "steps": steps},
        "response_payload": {"expect_text": case.expect_text},
    }


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
                "duration_ms": run.duration_ms,
                "started_at": _to_iso(run.started_at),
                "finished_at": _to_iso(run.finished_at),
                "request_payload": run.request_payload,
                "response_payload": run.response_payload,
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
            finalize_run(db, run, status="FAILED", summary="关联的项目或接口用例不存在")
            return {"status": "FAILED", "summary": "关联记录不存在"}

        mark_run_started(db, run)
        result = _execute_api_case(db, run, case, project)
        status = result["status"]
        summary = result["summary"]
        finalize_run(
            db,
            run,
            status=status,
            summary=summary,
            duration_ms=int((time.perf_counter() - started_at) * 1000),
            request_payload=result["request_payload"],
            response_payload=result["response_payload"],
        )
        return {"status": status, "summary": summary}
    except Exception as exc:
        run = db.get(TestRun, run_id)
        if run is not None:
            finalize_run(
                db,
                run,
                status="FAILED",
                summary=f"接口执行异常: {exc}",
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
        return {"status": "FAILED", "summary": str(exc)}
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
            finalize_run(db, run, status="FAILED", summary="UI 用例不存在")
            return {"status": "FAILED", "summary": "UI 用例不存在"}

        mark_run_started(db, run)
        project = db.get(Project, run.project_id)
        if project is None:
            finalize_run(db, run, status="FAILED", summary="关联项目不存在")
            return {"status": "FAILED", "summary": "关联项目不存在"}

        result = _execute_ui_case(db, run, case, project)
        summary = result["summary"]
        finalize_run(
            db,
            run,
            status="SUCCESS",
            summary=summary,
            duration_ms=int((time.perf_counter() - started_at) * 1000),
            request_payload=result["request_payload"],
            response_payload=result["response_payload"],
        )
        return {"status": "SUCCESS", "summary": summary}
    except (PlaywrightTimeoutError, Exception) as exc:
        run = db.get(TestRun, run_id)
        if run is not None:
            finalize_run(
                db,
                run,
                status="FAILED",
                summary=f"UI 执行异常: {exc}",
                duration_ms=int((time.perf_counter() - started_at) * 1000),
                request_payload={"target_url": getattr(case, "target_url", None)},
            )
        return {"status": "FAILED", "summary": str(exc)}
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

        runs = (
            db.query(TestRun)
            .filter(TestRun.plan_run_id == plan_run.id)
            .order_by(TestRun.id.asc())
            .all()
        )
        total = len(runs)
        pass_count = 0
        fail_count = 0

        for run in runs:
            case_started_at = time.perf_counter()
            try:
                case = None
                project = db.get(Project, run.project_id)
                if project is None:
                    finalize_run(db, run, status="FAILED", summary="关联项目不存在")
                    fail_count += 1
                    continue

                if run.case_type == "API":
                    case = db.get(APICase, run.case_id)
                    if case is None:
                        finalize_run(db, run, status="FAILED", summary="接口用例不存在")
                        fail_count += 1
                        continue
                    mark_run_started(db, run)
                    result = _execute_api_case(db, run, case, project)
                elif run.case_type == "UI":
                    case = db.get(UICase, run.case_id)
                    if case is None:
                        finalize_run(db, run, status="FAILED", summary="UI 用例不存在")
                        fail_count += 1
                        continue
                    mark_run_started(db, run)
                    result = _execute_ui_case(db, run, case, project)
                else:
                    finalize_run(db, run, status="FAILED", summary="未知用例类型")
                    fail_count += 1
                    continue

                status = result["status"]
                finalize_run(
                    db,
                    run,
                    status=status,
                    summary=result["summary"],
                    duration_ms=int((time.perf_counter() - case_started_at) * 1000),
                    request_payload=result["request_payload"],
                    response_payload=result["response_payload"],
                )
                if status == "SUCCESS":
                    pass_count += 1
                else:
                    fail_count += 1
            except Exception as exc:
                finalize_run(
                    db,
                    run,
                    status="FAILED",
                    summary=f"执行异常: {exc}",
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
            plan_run.summary = f"测试计划执行异常: {exc}"
            plan_run.finished_at = utc_now_naive()
            plan_run.duration_ms = int((time.perf_counter() - started_at) * 1000)
            db.commit()
        return {"status": "FAILED", "summary": str(exc)}
    finally:
        db.close()
