from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx


DEFAULT_PROHIBITED_ACTIONS = [
    "删除",
    "支付",
    "购买",
    "发布",
    "发送",
    "授权",
    "delete",
    "pay",
    "purchase",
    "publish",
    "send",
    "permission",
]

_SEMANTIC_CONCEPT_ALIASES = {
    "search": ("搜索", "查询", "检索", "search", "query"),
    "login": ("登录", "登陆", "sign in", "signin", "log in", "login"),
    "username": ("用户名", "账号", "账户", "user name", "username", "account"),
    "password": ("密码", "口令", "password", "passcode"),
    "save": ("保存", "save"),
    "submit": ("提交", "submit"),
    "delete": ("删除", "移除", "delete", "remove"),
    "add": ("新增", "添加", "创建", "add", "create", "new"),
    "edit": ("编辑", "修改", "edit", "modify"),
    "cancel": ("取消", "cancel"),
}

_AUTH_CONCEPTS = {"login", "username", "password"}


def normalize_execution_mode(value: str | None) -> str:
    normalized = (value or "stable").strip().lower()
    return normalized if normalized in {"stable", "adaptive", "explore", "visual"} else "stable"


def url_origin(value: str) -> str:
    parsed = urlparse((value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("UI 用例地址必须是有效的 HTTP 或 HTTPS URL")
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme.lower()}://{parsed.hostname.lower()}{port}"


def build_allowed_origins(target_url: str, project_url: str | None, configured: list | None) -> set[str]:
    origins = {url_origin(target_url)}
    for value in [project_url, *(configured or [])]:
        if not str(value or "").strip():
            continue
        origins.add(url_origin(str(value)))
    return origins


def ensure_allowed_url(value: str, origins: set[str]) -> None:
    if url_origin(value) not in origins:
        raise ValueError(f"导航地址不在允许域名内：{value}")


def semantic_target(step: dict) -> dict:
    nested = step.get("locator")
    nested = nested if isinstance(nested, dict) else {}
    return {
        "target": str(step.get("target") or "").strip(),
        "test_id": str(step.get("test_id") or nested.get("test_id") or "").strip(),
        "role": str(step.get("role") or nested.get("role") or "").strip(),
        "name": str(
            step.get("accessible_name")
            or nested.get("name")
            or step.get("name_hint")
            or ""
        ).strip(),
        "label": str(step.get("label") or nested.get("label") or "").strip(),
        "placeholder": str(step.get("placeholder") or nested.get("placeholder") or "").strip(),
        "text": str(step.get("text") or nested.get("text") or "").strip(),
        "selector": str(step.get("selector") or nested.get("selector") or "").strip(),
    }


def _first_visible(locator):
    if not callable(getattr(locator, "count", None)):
        return locator.first, 1
    count = min(locator.count(), 20)
    for index in range(count):
        candidate = locator.nth(index)
        try:
            if candidate.is_visible():
                return candidate, count
        except Exception:
            continue
    return locator.first, count


def resolve_semantic_locator(page, step: dict, *, require_visible: bool = True):
    target = semantic_target(step)
    attempts: list[tuple[str, object, str]] = []
    if target["test_id"]:
        attempts.append(("test_id", page.get_by_test_id(target["test_id"]), target["test_id"]))
    if target["role"]:
        kwargs = {"name": target["name"]} if target["name"] else {}
        attempts.append(
            ("role_name", page.get_by_role(target["role"], **kwargs), f"{target['role']}:{target['name']}")
        )
    if target["label"]:
        attempts.append(("label", page.get_by_label(target["label"]), target["label"]))
    if target["placeholder"]:
        attempts.append(("placeholder", page.get_by_placeholder(target["placeholder"]), target["placeholder"]))
    text = target["text"] or target["target"]
    if text:
        attempts.append(("visible_text", page.get_by_text(text, exact=False), text))
    if target["selector"]:
        attempts.append(("selector_fallback", page.locator(target["selector"]), target["selector"]))

    errors = []
    for method, locator, query in attempts:
        try:
            if not require_visible and locator.count():
                return locator.first, {
                    "method": method,
                    "query": query,
                    "match_count": locator.count(),
                    "used_ai": False,
                }
            candidate, count = _first_visible(locator)
            if count and (
                not callable(getattr(candidate, "is_visible", None))
                or candidate.is_visible()
            ):
                return candidate, {
                    "method": method,
                    "query": query,
                    "match_count": count,
                    "used_ai": False,
                }
            errors.append(f"{method}=0")
        except Exception as exc:
            errors.append(f"{method}:{str(exc)[:120]}")
    description = target["target"] or target["name"] or target["text"] or target["selector"] or "未命名目标"
    raise LookupError(f"无法定位“{description}”（{'；'.join(errors) or '未提供定位信息'}）")


def collect_interactive_candidates(page, limit: int = 80) -> list[dict]:
    return page.evaluate(
        """
        ({ limit }) => {
          const selector = [
            'button', 'input', 'textarea', 'select', 'a[href]', '[role]',
            '[contenteditable="true"]', '[tabindex]:not([tabindex="-1"])'
          ].join(',');
          const visible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.visibility !== 'hidden' && style.display !== 'none'
              && rect.width > 0 && rect.height > 0;
          };
          return Array.from(document.querySelectorAll(selector))
            .filter(visible)
            .slice(0, limit)
            .map((el, index) => {
              const id = `OMNI-${index + 1}`;
              el.setAttribute('data-omnitest-agent-ref', id);
              const text = (el.innerText || el.value || '').trim().replace(/\\s+/g, ' ').slice(0, 180);
              return {
                candidate_id: id,
                tag: el.tagName.toLowerCase(),
                role: el.getAttribute('role') || '',
                text,
                aria_label: el.getAttribute('aria-label') || '',
                placeholder: el.getAttribute('placeholder') || '',
                name: el.getAttribute('name') || '',
                type: el.getAttribute('type') || '',
                test_id: el.getAttribute('data-testid') || '',
                href: el.href || ''
              };
            });
        }
        """,
        {"limit": limit},
    )


def _semantic_concepts(value: str) -> set[str]:
    normalized = " ".join(str(value or "").lower().split())
    return {
        concept
        for concept, aliases in _SEMANTIC_CONCEPT_ALIASES.items()
        if any(alias in normalized for alias in aliases)
    }


def _candidate_concepts(candidate: dict) -> set[str]:
    return _semantic_concepts(
        " ".join(
            str(candidate.get(key) or "")
            for key in ("text", "aria_label", "placeholder", "name", "type", "role", "test_id")
        )
    )


def _page_context_mismatch(step: dict, candidates: list[dict] | None) -> str | None:
    target = semantic_target(step)
    target_text = " ".join(
        value for key, value in target.items() if key != "selector" and value
    )
    if "search" not in _semantic_concepts(target_text):
        return None
    page_concepts: set[str] = set()
    for item in candidates or []:
        page_concepts.update(_candidate_concepts(item))
    if not _AUTH_CONCEPTS.issubset(page_concepts):
        return None
    target_name = target["target"] or target["name"] or target["text"] or "当前目标"
    return (
        f"当前页面看起来是登录页，无法执行“{target_name}”；"
        "请补充登录前置步骤或会话，或改用正确的业务页面地址"
    )


def validate_healing_candidate(
    step: dict,
    candidate: dict,
    *,
    candidates: list[dict] | None = None,
) -> None:
    action = str(step.get("action") or "").strip().lower()
    tag = str(candidate.get("tag") or "").strip().lower()
    input_type = str(candidate.get("type") or "").strip().lower()
    if action == "fill" and not (
        tag in {"input", "textarea"}
        or str(candidate.get("role") or "").strip().lower() == "textbox"
    ):
        raise ValueError(f"AI 自愈候选不是可输入控件：{tag or 'unknown'}")
    if action == "fill" and input_type in {
        "button",
        "checkbox",
        "file",
        "hidden",
        "image",
        "radio",
        "reset",
        "submit",
    }:
        raise ValueError(f"AI 自愈候选不支持文本输入：input[{input_type}]")

    target = semantic_target(step)
    target_text = " ".join(
        value for key, value in target.items() if key != "selector" and value
    )
    candidate_text = " ".join(
        str(candidate.get(key) or "")
        for key in ("text", "aria_label", "placeholder", "name", "type", "role", "test_id")
    )
    target_concepts = _semantic_concepts(target_text)
    candidate_concepts = _candidate_concepts(candidate)
    conflicting = target_concepts and candidate_concepts and target_concepts.isdisjoint(candidate_concepts)
    if not conflicting:
        return

    target_name = target["target"] or target["name"] or target["text"] or "当前目标"
    mismatch = _page_context_mismatch(step, candidates)
    if mismatch:
        raise ValueError(mismatch)
    raise ValueError(
        f"AI 自愈候选与“{target_name}”语义冲突："
        f"候选内容为“{candidate_text.strip() or '无可识别文本'}”"
    )


def _model_endpoint(base_url: str) -> str:
    normalized = (base_url or "").rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def call_runtime_model(
    *,
    api_key: str,
    model: str,
    base_url: str,
    system_prompt: str,
    user_content: str | list,
    max_tokens: int = 1200,
    timeout_seconds: float = 90,
) -> dict:
    payload = {
        "model": model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": max_tokens,
    }
    try:
        response = httpx.post(
            _model_endpoint(base_url),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if isinstance(content, dict):
            return content
        text = str(content or "").strip()
        start = text.find("{")
        if start < 0:
            raise ValueError("模型未返回 JSON 对象")
        result, _ = json.JSONDecoder().raw_decode(text[start:])
        if not isinstance(result, dict):
            raise ValueError("模型结果不是 JSON 对象")
        return result
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        raise RuntimeError(f"AI 运行时请求失败，HTTP {exc.response.status_code}：{detail}") from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError("AI 运行时响应超时") from exc


def choose_healing_candidate(
    *,
    model_config,
    step: dict,
    candidates: list[dict],
) -> dict:
    if not candidates:
        raise LookupError("当前页面没有可用于自愈的交互元素")
    mismatch = _page_context_mismatch(step, candidates)
    if mismatch:
        raise ValueError(mismatch)
    target = semantic_target(step)
    result = call_runtime_model(
        api_key=model_config.api_key,
        model=model_config.model,
        base_url=model_config.base_url,
        system_prompt=(
            "You resolve one UI target from the supplied candidates. Choose a candidate only when "
            "its business meaning matches the target and action. Never map search/query controls to "
            "login, username, or password controls. If nothing matches, return no_match=true and "
            "candidate_id=null. Never invent a selector or candidate. Return JSON with candidate_id, "
            "no_match, confidence, and reason."
        ),
        user_content=json.dumps(
            {"target": target, "action": step.get("action"), "candidates": candidates},
            ensure_ascii=False,
        ),
    )
    candidate_id = str(result.get("candidate_id") or "")
    if result.get("no_match") is True or candidate_id.strip().upper() in {"NO_MATCH", "NONE", "NULL"}:
        reason = str(result.get("reason") or "").strip()
        raise LookupError(f"AI 自愈未找到与目标语义匹配的元素：{reason or '当前页面没有合适候选'}")
    candidate = next((item for item in candidates if item["candidate_id"] == candidate_id), None)
    if candidate is None:
        raise LookupError("AI 自愈返回了不存在的候选元素")
    try:
        confidence = float(result.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.65:
        raise LookupError(f"AI 自愈候选置信度过低（{confidence:.0%}），已拒绝执行")
    validate_healing_candidate(step, candidate, candidates=candidates)
    return {
        "candidate": candidate,
        "candidate_id": candidate_id,
        "confidence": confidence,
        "reason": str(result.get("reason") or "").strip(),
    }


def prohibited_candidate(candidate: dict, prohibited_actions: list | None) -> str | None:
    haystack = " ".join(str(value or "") for value in candidate.values()).lower()
    for term in [*(prohibited_actions or []), *DEFAULT_PROHIBITED_ACTIONS]:
        normalized = str(term or "").strip().lower()
        if normalized and normalized in haystack:
            return str(term)
    return None


def choose_exploration_action(
    *,
    model_config,
    goal: str,
    history: list[dict],
    candidates: list[dict],
) -> dict:
    return call_runtime_model(
        api_key=model_config.api_key,
        model=model_config.model,
        base_url=model_config.base_url,
        system_prompt=(
            "You are a bounded UI exploration agent. Return one JSON action. "
            "Allowed actions: click, fill, press, finish. For element actions choose a supplied "
            "candidate_id. Use finish when the goal is verified or no safe progress is possible. "
            "Return action, candidate_id, value, finding, reason."
        ),
        user_content=json.dumps(
            {
                "goal": goal,
                "recent_history": history[-6:],
                "candidates": candidates,
            },
            ensure_ascii=False,
        ),
    )


def review_visual_checkpoint(
    *,
    model_config,
    expectation: str,
    screenshot_base64: str,
    page_url: str,
) -> dict:
    result = call_runtime_model(
        api_key=model_config.api_key,
        model=model_config.model,
        base_url=model_config.base_url,
        system_prompt=(
            "Review only the supplied screenshot against the saved visual expectation. "
            "Return JSON: verdict PASS, FAIL, or REVIEW; confidence 0..1; observations array; reason. "
            "Use REVIEW when the image or evidence is insufficient."
        ),
        user_content=[
            {
                "type": "text",
                "text": json.dumps({"expectation": expectation, "page_url": page_url}, ensure_ascii=False),
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"},
            },
        ],
        max_tokens=1200,
    )
    verdict = str(result.get("verdict") or "REVIEW").strip().upper()
    result["verdict"] = verdict if verdict in {"PASS", "FAIL", "REVIEW"} else "REVIEW"
    return result
