"""测试计划执行结果的 Webhook 消息通知（飞书/钉钉/企微/自定义）。

任何通知失败仅记录日志，绝不影响执行结果本身。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
import urllib.parse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Environment, Project, ProjectNotificationSetting, TestPlan, TestPlanRun

logger = logging.getLogger(__name__)

NOTIFY_TIMEOUT_SECONDS = 5


def _format_duration(duration_ms: int | None) -> str:
    if not duration_ms:
        return "-"
    seconds = duration_ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m{int(seconds % 60)}s"


def build_plan_run_text(db: Session, plan_run: TestPlanRun) -> str:
    plan = db.get(TestPlan, plan_run.plan_id)
    project = db.get(Project, plan_run.project_id)
    env = db.get(Environment, plan_run.environment_id) if plan_run.environment_id else None
    status_label = "✅ 成功" if plan_run.status == "SUCCESS" else "❌ 失败"
    report_url = f"{settings.frontend_public_url.rstrip('/')}/report"
    lines = [
        "【测试平台】测试计划执行完成",
        f"计划：{plan.name if plan else plan_run.plan_id}",
        f"项目：{project.name if project else plan_run.project_id}",
        f"环境：{env.name if env else '默认'}",
        f"结果：{status_label}",
        f"总计 {plan_run.total_count or 0}，成功 {plan_run.pass_count or 0}，失败 {plan_run.fail_count or 0}",
        f"耗时：{_format_duration(plan_run.duration_ms)}",
        f"报告：{report_url}",
    ]
    if plan_run.status not in {"SUCCESS", "FAILED"} or (plan_run.summary and "异常" in plan_run.summary):
        lines.insert(5, f"摘要：{plan_run.summary}")
    return "\n".join(lines)


def _dingtalk_sign(secret: str) -> str:
    """钉钉加签：返回带 timestamp 与 sign 的 query 字符串。"""
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))
    return f"timestamp={timestamp}&sign={sign}"


def send_webhook_message(setting: ProjectNotificationSetting, text: str) -> bool:
    """按渠道格式化 payload 并 POST 到 webhook，返回是否发送成功。"""
    url = (setting.webhook_url or "").strip()
    if not url:
        return False
    channel = (setting.channel_type or "CUSTOM").upper()
    if channel == "FEISHU":
        payload = {"msg_type": "text", "content": {"text": text}}
    elif channel == "DINGTALK":
        payload = {"msgtype": "text", "text": {"content": text}}
        if setting.secret:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{_dingtalk_sign(setting.secret)}"
    elif channel == "WECOM":
        payload = {"msgtype": "text", "text": {"content": text}}
    else:  # CUSTOM
        payload = {"source": "test-platform", "event": "plan_run_finished", "text": text}
    try:
        response = httpx.post(url, json=payload, timeout=NOTIFY_TIMEOUT_SECONDS)
        if response.status_code >= 400:
            logger.warning("通知发送失败：HTTP %s %s", response.status_code, response.text[:200])
            return False
        return True
    except Exception:
        logger.warning("通知发送异常", exc_info=True)
        return False


def send_plan_run_notification(db: Session, plan_run_id: int) -> None:
    """测试计划执行结束后发送通知；任何失败仅记日志。"""
    try:
        plan_run = db.get(TestPlanRun, plan_run_id)
        if plan_run is None:
            return
        setting = db.scalar(
            select(ProjectNotificationSetting).where(
                ProjectNotificationSetting.project_id == plan_run.project_id
            )
        )
        if setting is None or not setting.enabled:
            return
        if setting.notify_on == "FAIL_ONLY" and plan_run.status == "SUCCESS":
            return
        send_webhook_message(setting, build_plan_run_text(db, plan_run))
    except Exception:
        logger.warning("组装/发送测试计划通知异常", exc_info=True)
