#!/usr/bin/env python3
"""一键为本地运行的 OminiTest 填充全模块演示数据并触发真实执行。

仅使用 Python 3 标准库，无需安装额外依赖。
默认读取项目根目录 `.env` 中的 INITIAL_ADMIN_PASSWORD，连接本地后端 API。

用法：
    python3 scripts/seed_full_demo.py
    python3 scripts/seed_full_demo.py --skip-runs
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_env_file(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip().strip('"').strip("'")
    return values


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None

    def request(self, method: str, path: str, body: dict | list | None = None, *, timeout: int = 20):
        url = f"{self.base_url}{path}"
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return None
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc


def _iso_utc(delta_days: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=delta_days)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    env_vals = _load_env_file(repo_root / ".env")

    parser = argparse.ArgumentParser(description="填充 OminiTest 全模块演示数据并触发真实执行")
    parser.add_argument(
        "--base-url",
        default=os.getenv("OMINITEST_API_URL", "http://127.0.0.1:8000/api/v1"),
        help="后端 API v1 根地址",
    )
    parser.add_argument("--username", default="admin")
    parser.add_argument(
        "--password",
        default=os.getenv("INITIAL_ADMIN_PASSWORD") or env_vals.get("INITIAL_ADMIN_PASSWORD", ""),
    )
    parser.add_argument("--skip-runs", action="store_true", help="跳过真实异步执行触发")
    parser.add_argument("--check-reports", action="store_true", help="仅检查当前报告中心状态")
    parser.add_argument("--run-plan-now", action="store_true", help="立即以串行模式触发 2 次测试计划并核验成功报告")
    args = parser.parse_args()

    if not args.password:
        print("错误：未找到管理员密码，请在 .env 中配置 INITIAL_ADMIN_PASSWORD 或通过 --password 传入。", file=sys.stderr)
        return 1

    client = ApiClient(args.base_url)

    print(f"[1/9] 连接后端 {args.base_url} 并登录 ({args.username})...")
    health = client.request("GET", "/system/health/live")
    print(f"      后端存活检查: {health}")
    login = client.request("POST", "/auth/login", {"username": args.username, "password": args.password})
    client.token = login["token"]
    admin_id = login["user"]["id"]
    print(f"      登录成功，当前用户 ID={admin_id}")

    if args.check_reports:
        reports = client.request("GET", "/reports")
        print(f"当前报告总数: {len(reports)}")
        for rep in reports[:10]:
            rid = rep.get("id") or rep.get("plan_run_id")
            print(
                f"  - id={rid} plan={rep.get('plan_name')} "
                f"status={rep.get('status')} pass={rep.get('pass_count')}/{rep.get('total_count')} "
                f"duration={rep.get('duration_ms')}ms summary={rep.get('summary')}"
            )
            if rep.get("status") == "RUNNING" and rid:
                detail = client.request("GET", f"/reports/{rid}")
                for tr in detail.get("runs") or detail.get("test_runs") or []:
                    print(f"      * run #{tr['id']} [{tr['case_type']}] {tr['case_name']} -> {tr['status']} ({tr.get('summary')})")
        return 0

    if args.run_plan_now:
        projects = client.request("GET", "/projects")
        proj = next((p for p in projects if p["name"] == "电商核心业务演示项目"), None) or projects[-1]
        proj_id = proj["id"]
        envs = client.request("GET", f"/environments?project_id={proj_id}")
        env_id = envs[0]["id"] if envs else None
        plans = client.request("GET", f"/test-plans?project_id={proj_id}")
        plan = next((p for p in plans if p["name"] == "核心回归测试计划"), None) or plans[0]
        p1 = client.request("POST", f"/test-plans/{plan['id']}/run", {"environment_id": env_id, "concurrency": 1})
        p2 = client.request("POST", f"/test-plans/{plan['id']}/run", {"environment_id": env_id, "concurrency": 1})
        print(f"已触发串行测试计划执行: plan_run=#{p1['id']}, #{p2['id']}，等待 6 秒...")
        time.sleep(6)
        for pid in (p1["id"], p2["id"]):
            detail = client.request("GET", f"/reports/{pid}")
            pr = detail.get("plan_run") or detail
            print(f"  - 报告 #{pid}: status={pr.get('status')} pass={pr.get('pass_count')}/{pr.get('total_count')} duration={pr.get('duration_ms')}ms summary={pr.get('summary')}")
        return 0

    print("[2/9] 调用 /system/bootstrap 初始化基础演示数据...")
    try:
        boot = client.request("POST", "/system/bootstrap", {"seed_demo_data": True})
        print(f"      bootstrap 返回新增资源: {len(boot.get('seeded_resources') or [])} 项")
    except Exception as exc:
        print(f"      bootstrap 提示（将继续通过 REST API 补全）: {exc}")

    print("[3/9] 检查/创建演示工作空间与项目...")
    workspaces = client.request("GET", "/workspaces")
    ws = next((w for w in workspaces if w["name"] == "电商核心业务空间"), None)
    if ws is None:
        ws = client.request(
            "POST",
            "/workspaces",
            {"name": "电商核心业务空间", "description": "覆盖订单、支付、压测与敏捷协作全链路的演示工作空间。"},
        )
    ws_id = ws["id"]

    projects = client.request("GET", "/projects")
    proj = next((p for p in projects if p["name"] == "电商核心业务演示项目"), None)
    if proj is None:
        proj = client.request(
            "POST",
            "/projects",
            {
                "workspace_id": ws_id,
                "name": "电商核心业务演示项目",
                "code": "ECOM-DEMO",
                "description": "包含接口/UI/性能/Mock/测试计划/报告对比/敏捷迭代与 AI 用例生成的全功能示例项目。",
                "base_url": "http://backend:8000",
            },
        )
    proj_id = proj["id"]
    client.request(
        "PUT",
        f"/projects/{proj_id}/variables",
        {
            "variables_json": {
                "api_version": "v1",
                "demo_env": "local",
                "order_id": "ORD-20261119-001",
                "merchant_code": "MCH-8801",
            }
        },
    )
    print(f"      演示项目已就绪: id={proj_id} ({proj['name']})")

    print("[4/9] 检查/创建多环境配置...")
    existing_envs = client.request("GET", f"/environments?project_id={proj_id}")
    env_by_name = {e["name"]: e for e in existing_envs}
    env_defs = [
        (
            "本地联调环境",
            "http://backend:8000",
            {"accept": "application/json", "X-Demo-Env": "local"},
            {"api_version": "v1", "frontend_url": "http://frontend:3000", "order_id": "ORD-20261119-001", "demo_env": "local"},
        ),
        (
            "测试环境 (Staging)",
            "http://backend:8000",
            {"accept": "application/json", "X-Demo-Env": "staging"},
            {"api_version": "v1", "frontend_url": "http://frontend:3000", "order_id": "ORD-20261119-002", "demo_env": "staging"},
        ),
        (
            "Mock 仿真环境",
            f"http://backend:8000/api/v1/mock/{proj_id}",
            {"accept": "application/json", "X-Mock-Client": "OminiTest"},
            {"api_version": "v1", "order_id": "ORD-20261119-001", "demo_env": "mock"},
        ),
    ]
    for name, base_url, headers, variables in env_defs:
        if name not in env_by_name:
            env_by_name[name] = client.request(
                "POST",
                "/environments",
                {
                    "project_id": proj_id,
                    "name": name,
                    "base_url": base_url,
                    "headers_json": headers,
                    "variables_json": variables,
                },
            )
    local_env_id = env_by_name["本地联调环境"]["id"]
    print(f"      环境数量: {len(env_by_name)}（本地联调环境 id={local_env_id}）")

    print("[5/9] 检查/创建 API、UI 与性能压测用例...")
    api_list = client.request("GET", f"/api-cases?project_id={proj_id}")
    api_by_name = {c["name"]: c for c in api_list}
    api_defs = [
        {
            "name": "系统健康状态巡检",
            "folder_path": "系统巡检/基础探针",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P0",
            "tags_json": ["冒烟", "系统巡检"],
            "headers_json": {"accept": "application/json"},
            "assertions_json": [
                {"type": "status_code", "operator": "eq", "expected": 200},
                {"type": "json_path", "expression": "$.app_status", "operator": "eq", "expected": "healthy"},
            ],
            "expected_status": 200,
        },
        {
            "name": "变量模板存活探针",
            "folder_path": "系统巡检/基础探针",
            "method": "GET",
            "path": "/api/{{api_version}}/system/health/live",
            "priority": "P1",
            "tags_json": ["变量模板", "冒烟"],
            "headers_json": {"accept": "application/json", "X-Env": "{{demo_env}}"},
            "assertions_json": [
                {"type": "status_code", "operator": "eq", "expected": 200},
                {"type": "json_path", "expression": "$.status", "operator": "eq", "expected": "alive"},
            ],
            "expected_status": 200,
        },
        {
            "name": "多步骤场景：探针提取与健康校验",
            "folder_path": "订单核心/场景编排",
            "method": "GET",
            "path": "/api/v1/system/health/live",
            "priority": "P0",
            "tags_json": ["场景编排", "回归"],
            "steps_json": [
                {
                    "name": "步骤1：获取服务存活状态",
                    "method": "GET",
                    "path": "/api/{{api_version}}/system/health/live",
                    "expected_status": 200,
                    "assertions": [{"type": "json_path", "expression": "$.status", "operator": "eq", "expected": "alive"}],
                    "extractors": [{"name": "live_status", "source": "json_path", "expression": "$.status"}],
                },
                {
                    "name": "步骤2：携带提取变量校验整体健康",
                    "method": "GET",
                    "path": "/api/{{api_version}}/system/health",
                    "headers_json": {"X-Prev-Live-Status": "{{live_status}}"},
                    "expected_status": 200,
                    "assertions": [{"type": "status_code", "operator": "eq", "expected": 200}],
                },
            ],
            "expected_status": 200,
        },
        {
            "name": "Mock 订单详情查询服务",
            "folder_path": "订单核心/Mock服务",
            "method": "GET",
            "path": "/mock-orders/{id}",
            "priority": "P1",
            "tags_json": ["Mock", "订单"],
            "mock_enabled": True,
            "mock_config_json": {
                "status_code": 200,
                "delay_ms": 60,
                "headers": {"X-Mock-Source": "OminiTest"},
                "body": {
                    "order_id": "ORD-20261119-001",
                    "status": "PAID",
                    "amount": 299.0,
                    "currency": "CNY",
                    "items": [{"sku": "SKU-1001", "name": "无线降噪耳机", "qty": 1}],
                },
            },
            "expected_status": 200,
        },
    ]
    for spec in api_defs:
        if spec["name"] not in api_by_name:
            api_by_name[spec["name"]] = client.request("POST", "/api-cases", {"project_id": proj_id, **spec})
        else:
            existing_id = api_by_name[spec["name"]]["id"]
            api_by_name[spec["name"]] = client.request("PUT", f"/api-cases/{existing_id}", {"project_id": proj_id, **spec})

    ui_list = client.request("GET", f"/ui-cases?project_id={proj_id}")
    ui_by_name = {c["name"]: c for c in ui_list}
    ui_defs = [
        {
            "name": "登录页与核心入口巡检",
            "folder_path": "核心链路/登录鉴权",
            "target_url": "http://frontend:3000",
            "priority": "P0",
            "tags_json": ["Playwright", "冒烟"],
            "steps_json": [
                {"action": "goto", "value": "http://frontend:3000"},
                {"action": "wait_for_text", "value": "登录"},
            ],
            "assertions_json": [{"type": "text_present", "expected": "登录"}],
            "expect_text": "登录",
            "engine": "native",
        },
        {
            "name": "工作台导航与总览巡检（Midscene AI 示例）",
            "folder_path": "AI探索/视觉巡检",
            "target_url": "http://frontend:3000",
            "priority": "P1",
            "tags_json": ["Midscene", "AI视觉"],
            "steps_json": [
                {"action": "goto", "value": "http://frontend:3000"},
                {"action": "wait_for_text", "value": "登录"},
            ],
            "assertions_json": [{"type": "text_present", "expected": "登录"}],
            "expect_text": "登录",
            "engine": "midscene",
            "generation_mode": "ai_skill",
            "execution_mode": "adaptive",
            "self_heal_enabled": True,
            "max_agent_steps": 8,
            "ai_goal": "打开工作台页面并确认核心登录入口和系统标题正常渲染",
        },
    ]
    for spec in ui_defs:
        if spec["name"] not in ui_by_name:
            ui_by_name[spec["name"]] = client.request("POST", "/ui-cases", {"project_id": proj_id, **spec})

    perf_list = client.request("GET", f"/performance-cases?project_id={proj_id}")
    perf_by_name = {c["name"]: c for c in perf_list}
    perf_defs = [
        {
            "name": "健康探针基准压测",
            "folder_path": "基准压测/系统接口",
            "method": "GET",
            "path": "/api/v1/system/health/live",
            "priority": "P1",
            "tags_json": ["基准压测", "P95"],
            "headers_json": {"accept": "application/json"},
            "expected_status": 200,
            "concurrency": 4,
            "total_requests": 20,
            "max_avg_response_ms": 500,
            "max_p95_response_ms": 1000,
            "max_error_rate": 0.05,
        },
        {
            "name": "Mock 订单详情并发吞吐压测",
            "folder_path": "基准压测/订单接口",
            "method": "GET",
            "path": f"/api/v1/mock/{proj_id}/mock-orders/ORD-20261119-001",
            "priority": "P1",
            "tags_json": ["Mock压测", "订单"],
            "headers_json": {"accept": "application/json"},
            "expected_status": 200,
            "concurrency": 6,
            "total_requests": 24,
            "max_avg_response_ms": 800,
            "max_p95_response_ms": 1500,
            "max_error_rate": 0.05,
        },
    ]
    for spec in perf_defs:
        if spec["name"] not in perf_by_name:
            perf_by_name[spec["name"]] = client.request("POST", "/performance-cases", {"project_id": proj_id, **spec})
    print(f"      用例就绪: API={len(api_by_name)}, UI={len(ui_by_name)}, PERF={len(perf_by_name)}")

    print("[6/9] 检查/创建测试计划并绑定用例...")
    plans = client.request("GET", f"/test-plans?project_id={proj_id}")
    plan_by_name = {p["name"]: p for p in plans}
    if "核心回归测试计划" not in plan_by_name:
        plan_by_name["核心回归测试计划"] = client.request(
            "POST",
            "/test-plans",
            {
                "project_id": proj_id,
                "name": "核心回归测试计划",
                "description": "覆盖接口探针、场景编排、基准压测的发版前回归计划。",
            },
        )
    reg_plan_id = plan_by_name["核心回归测试计划"]["id"]
    existing_plan_cases = client.request("GET", f"/test-plans/{reg_plan_id}/cases")
    bound_keys = {(c["case_type"], c["case_id"]) for c in existing_plan_cases}
    desired_bindings = [
        ("API", api_by_name["系统健康状态巡检"]["id"], 1),
        ("API", api_by_name["变量模板存活探针"]["id"], 2),
        ("API", api_by_name["多步骤场景：探针提取与健康校验"]["id"], 3),
        ("PERF", perf_by_name["健康探针基准压测"]["id"], 4),
    ]
    for ctype, cid, order_idx in desired_bindings:
        if (ctype, cid) not in bound_keys:
            client.request(
                "POST",
                f"/test-plans/{reg_plan_id}/cases",
                {"case_type": ctype, "case_id": cid, "order_index": order_idx, "allow_unapproved": True},
            )

    print("[7/9] 检查/创建敏捷协作数据（迭代、需求、追溯矩阵、任务看板、缺陷）...")
    iters = client.request("GET", f"/projects/{proj_id}/iterations")
    iter_by_name = {i["name"]: i for i in iters}
    if "Sprint 12 - 订单支付与自动化基线" not in iter_by_name:
        iter_by_name["Sprint 12 - 订单支付与自动化基线"] = client.request(
            "POST",
            f"/projects/{proj_id}/iterations",
            {
                "name": "Sprint 12 - 订单支付与自动化基线",
                "goal": "完成 Mock 订单仿真、接口变量预览、异步压测引擎与报告历史 Diff 交付。",
                "status": "ACTIVE",
                "start_date": _iso_utc(-7),
                "end_date": _iso_utc(7),
                "capacity_points": 30,
            },
        )
    if "Sprint 13 - AI 用例生成与视觉自愈" not in iter_by_name:
        iter_by_name["Sprint 13 - AI 用例生成与视觉自愈"] = client.request(
            "POST",
            f"/projects/{proj_id}/iterations",
            {
                "name": "Sprint 13 - AI 用例生成与视觉自愈",
                "goal": "推进 Midscene AI 视觉巡检自愈与多源 PRD 可信分片用例生成。",
                "status": "PLANNING",
                "start_date": _iso_utc(8),
                "end_date": _iso_utc(21),
                "capacity_points": 28,
            },
        )
    s12_id = iter_by_name["Sprint 12 - 订单支付与自动化基线"]["id"]
    s13_id = iter_by_name["Sprint 13 - AI 用例生成与视觉自愈"]["id"]

    req_page = client.request("GET", f"/projects/{proj_id}/requirements?page=1&page_size=100")
    req_by_title = {r["title"]: r for r in req_page.get("items", [])}
    req_defs = [
        ("支持订单详情 Mock 仿真与动态延时配置", s12_id, "DONE", "P0", 5, "订单模块", [("API", api_by_name["Mock 订单详情查询服务"]["id"])]),
        ("接口场景编排支持变量提取与悬停预览", s12_id, "DONE", "P1", 8, "自动化平台", [("API", api_by_name["变量模板存活探针"]["id"])]),
        ("性能压测引擎支持 P50/P90/P95/P99 与 QPS 统计", s12_id, "TESTING", "P0", 8, "性能压测", [("PERF", perf_by_name["健康探针基准压测"]["id"])]),
        ("测试报告支持与上次执行结果 Diff 对比", s12_id, "IN_PROGRESS", "P1", 5, "报告中心", [("API", api_by_name["系统健康状态巡检"]["id"])]),
        ("Midscene AI 视觉定位与自愈巡检接入", s13_id, "PLANNING", "P2", 8, "UI自动化", [("UI", ui_by_name["工作台导航与总览巡检（Midscene AI 示例）"]["id"])]),
    ]
    for title, iter_id, target_st, prio, pts, folder, links in req_defs:
        if title not in req_by_title:
            created = client.request(
                "POST",
                f"/projects/{proj_id}/requirements",
                {
                    "iteration_id": iter_id,
                    "title": title,
                    "description": f"<p>业务目标：{title}。</p>",
                    "priority": prio,
                    "type": "FEATURE",
                    "owner_id": admin_id,
                    "story_points": pts,
                    "folder_path": folder,
                    "tags_json": [folder, prio],
                },
            )
            path_map = {
                "PLANNING": ["PLANNING"],
                "IN_PROGRESS": ["PLANNING", "IN_PROGRESS"],
                "TESTING": ["PLANNING", "IN_PROGRESS", "TESTING"],
                "DONE": ["PLANNING", "IN_PROGRESS", "TESTING", "DONE"],
            }
            for step_st in path_map.get(target_st, []):
                created = client.request("PUT", f"/requirements/{created['id']}/status", {"status": step_st})
            req_by_title[title] = created
            for ctype, cid in links:
                try:
                    client.request("POST", f"/requirements/{created['id']}/cases", {"case_type": ctype, "case_id": cid})
                except Exception:
                    pass

    task_page = client.request("GET", f"/projects/{proj_id}/tasks?page=1&page_size=100")
    task_by_title = {t["title"]: t for t in task_page.get("items", [])}
    task_defs = [
        ("编写 Mock 订单接口契约与延时压测用例", "DONE", "P1", 4, 4, "支持订单详情 Mock 仿真与动态延时配置"),
        ("接入 SSE 实时执行日志流与终端着色", "DONE", "P0", 6, 5.5, "测试报告支持与上次执行结果 Diff 对比"),
        ("验证异步压测引擎高并发 P95/P99 误差范围", "REVIEW", "P0", 5, 4, "性能压测引擎支持 P50/P90/P95/P99 与 QPS 统计"),
        ("完善测试报告历史 Diff 卡片与耗时趋势展示", "DOING", "P1", 6, 3, "测试报告支持与上次执行结果 Diff 对比"),
        ("梳理 Midscene AI 视觉自愈提示词模板", "TODO", "P2", 4, 0, "Midscene AI 视觉定位与自愈巡检接入"),
    ]
    for title, target_st, prio, est, spent, req_title in task_defs:
        if title not in task_by_title:
            t = client.request(
                "POST",
                f"/projects/{proj_id}/tasks",
                {
                    "iteration_id": s12_id if target_st != "TODO" else s13_id,
                    "requirement_id": req_by_title[req_title]["id"],
                    "title": title,
                    "priority": prio,
                    "assignee_id": admin_id,
                    "estimate_hours": est,
                    "spent_hours": spent,
                },
            )
            for step_st in {"DOING": ["DOING"], "REVIEW": ["DOING", "REVIEW"], "DONE": ["DOING", "REVIEW", "DONE"]}.get(target_st, []):
                client.request("PUT", f"/tasks/{t['id']}/status", {"status": step_st})

    defect_page = client.request("GET", f"/projects/{proj_id}/defects?page=1&page_size=100")
    defect_by_title = {d["title"]: d for d in defect_page.get("items", [])}
    defect_defs = [
        ("高并发压测下偶发连接池超时导致错误率上升", "NEW", "CRITICAL", "P0", "PERFORMANCE", "压测引擎", "性能压测引擎支持 P50/P90/P95/P99 与 QPS 统计"),
        ("接口变量模板包含嵌套空格时悬停预览未命中", "CONFIRMED", "MAJOR", "P1", "FUNCTION", "接口用例", "接口场景编排支持变量提取与悬停预览"),
        ("测试报告 Diff 在首次执行时应隐藏对比徽标", "IN_PROGRESS", "MINOR", "P2", "UI", "报告中心", "测试报告支持与上次执行结果 Diff 对比"),
        ("Mock 订单路径参数含连字符时正则匹配失败", "RESOLVED", "MAJOR", "P1", "FUNCTION", "Mock服务", "支持订单详情 Mock 仿真与动态延时配置"),
    ]
    for title, target_st, sev, prio, dtype, mod, req_title in defect_defs:
        if title not in defect_by_title:
            d = client.request(
                "POST",
                f"/projects/{proj_id}/defects",
                {
                    "iteration_id": s12_id,
                    "requirement_id": req_by_title[req_title]["id"],
                    "title": title,
                    "description": f"<p>在 <strong>{mod}</strong> 模块回归过程中发现：{title}。</p>",
                    "reproduce_steps": "<ol><li>切换至本地联调环境</li><li>触发对应回归用例</li><li>查看日志与响应</li></ol>",
                    "severity": sev,
                    "priority": prio,
                    "defect_type": dtype,
                    "module": mod,
                    "found_version": "v1.8.0",
                    "assignee_id": admin_id,
                },
            )
            step_map = {
                "CONFIRMED": ["CONFIRMED"],
                "IN_PROGRESS": ["CONFIRMED", "IN_PROGRESS"],
                "RESOLVED": ["CONFIRMED", "IN_PROGRESS", "RESOLVED"],
            }
            for step_st in step_map.get(target_st, []):
                client.request("PUT", f"/project-defects/{d['id']}/status", {"status": step_st})

    try:
        client.request(
            "PUT",
            f"/projects/{proj_id}/notification-setting",
            {"enabled": False, "channel_type": "FEISHU", "webhook_url": None, "notify_on": "FAIL_ONLY"},
        )
    except Exception as exc:
        print(f"      通知配置跳过（若刚拉取新迁移请重启 backend 容器）: {exc}")

    if args.skip_runs:
        print("[8/9] 已跳过真实执行 (--skip-runs)。")
    else:
        print("[8/9] 触发真实异步执行（单接口、性能压测、UI 巡检、批量执行、连续 2 次测试计划）...")
        r_api = client.request(
            "POST",
            f"/executions/api/{api_by_name['多步骤场景：探针提取与健康校验']['id']}/run",
            {"environment_id": local_env_id},
        )
        r_perf = client.request(
            "POST",
            f"/executions/perf/{perf_by_name['健康探针基准压测']['id']}/run",
            {"environment_id": local_env_id},
        )
        r_ui = client.request(
            "POST",
            f"/executions/ui/{ui_by_name['登录页与核心入口巡检']['id']}/run",
            {"environment_id": local_env_id},
        )
        r_batch = client.request(
            "POST",
            "/executions/api/batch-run",
            {
                "case_ids": [
                    api_by_name["系统健康状态巡检"]["id"],
                    api_by_name["变量模板存活探针"]["id"],
                ],
                "environment_id": local_env_id,
            },
        )
        pr1 = pr2 = None
        try:
            pr1 = client.request(
                "POST",
                f"/test-plans/{reg_plan_id}/run",
                {"environment_id": local_env_id, "concurrency": 1},
            )
            time.sleep(2)
            pr2 = client.request(
                "POST",
                f"/test-plans/{reg_plan_id}/run",
                {"environment_id": local_env_id, "concurrency": 1},
            )
        except Exception as exc:
            print(f"      测试计划执行提示（重启 backend/worker 后即可生效）: {exc}")
        print(
            f"      已提交真实执行: api_run=#{r_api['id']}, perf_run=#{r_perf['id']}, ui_run=#{r_ui['id']}, "
            f"batch_run=#{r_batch['id']}"
            + (f", plan_runs=#{pr1['id']}, #{pr2['id']}" if pr1 and pr2 else "")
        )
        # 报告缺陷记录
        try:
            existing_report_defects = client.request("GET", f"/defects?project_id={proj_id}")
            if not existing_report_defects:
                client.request(
                    "POST",
                    "/defects",
                    {
                        "project_id": proj_id,
                        "run_id": r_perf["id"],
                        "plan_run_id": pr1["id"] if pr1 else None,
                        "title": "[健康探针基准压测] 并发连接池超时排查记录",
                        "platform": "GENERIC",
                        "external_key": "BUG-2026-101",
                        "status": "OPEN",
                        "severity": "P1",
                        "summary": "压测演示关联缺陷记录，用于展示测试报告与缺陷追踪闭环。",
                    },
                )
        except Exception as exc:
            print(f"      报告缺陷记录跳过: {exc}")

        print("      等待 6 秒让 Celery Worker 完成异步执行...")
        time.sleep(6)
        for label, rid in [("API场景", r_api["id"]), ("性能压测", r_perf["id"]), ("UI巡检", r_ui["id"])]:
            detail = client.request("GET", f"/executions/runs/{rid}")
            print(
                f"      - {label} (#{rid}): status={detail['status']}, "
                f"duration={detail.get('duration_ms')}ms, summary={detail.get('summary')}"
            )
        try:
            reports = client.request("GET", f"/reports?project_id={proj_id}")
            for rep in reports[:2]:
                print(
                    f"      - 计划报告 (#{rep['plan_run_id']}): status={rep['status']}, "
                    f"pass={rep['pass_count']}/{rep['total_count']}, duration={rep.get('duration_ms')}ms"
                )
        except Exception:
            pass

    print("[9/9] 读取工作台总览核验...")
    summary = client.request("GET", "/dashboard/summary")
    print(
        f"完成！当前平台总计：工作空间 {summary['workspace_count']} / 项目 {summary['project_count']} / "
        f"API 用例 {summary['api_case_count']} / UI 用例 {summary['ui_case_count']} / "
        f"环境 {summary['environment_count']} / 计划 {summary['plan_count']} / "
        f"执行记录 {summary['run_count']} / 报告 {summary['plan_run_count']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
