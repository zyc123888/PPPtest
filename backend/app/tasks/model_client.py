from __future__ import annotations

import hashlib
import json
import time

import httpx

from app.tasks.case_generation_runtime import record_model_call
from app.tasks.case_generation_v2_support.async_runtime import shared_http_client


async def call_json_chat_completion(
    *,
    api_key: str,
    model: str,
    base_url: str,
    system_prompt: str,
    user_content: str | list,
    max_tokens: int,
    timeout_seconds: float,
) -> str:
    payload = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": max_tokens,
    }
    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    started = time.perf_counter()
    serialized_user_content = (
        user_content
        if isinstance(user_content, str)
        else json.dumps(user_content, ensure_ascii=False, sort_keys=True, default=str)
    )
    trace_base = {
        "model": model,
        "endpoint": endpoint,
        "max_tokens": max_tokens,
        "system_prompt_sha256": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
        "user_content_sha256": hashlib.sha256(serialized_user_content.encode("utf-8")).hexdigest(),
        "request_chars": len(system_prompt) + len(serialized_user_content),
        "estimated_cost_usd": None,
    }
    try:
        client = await shared_http_client()
        if client is None:
            async with httpx.AsyncClient() as transient_client:
                response = await transient_client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=timeout_seconds,
                )
        else:
            response = await client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=timeout_seconds,
            )
        response.raise_for_status()
        response_payload = response.json()
        choice = response_payload["choices"][0]
        record_model_call(
            {
                **trace_base,
                "status": "success",
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "finish_reason": choice.get("finish_reason"),
                "provider_request_id": response.headers.get("x-request-id") or response.headers.get("request-id"),
                "usage": response_payload.get("usage") or {},
                "response_chars": len(str(choice.get("message", {}).get("content") or "")),
            }
        )
        return choice["message"]["content"]
    except httpx.ReadTimeout as exc:
        record_model_call(
            {
                **trace_base,
                "status": "timeout",
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "retry_reason": "read_timeout",
            }
        )
        raise RuntimeError(f"模型响应超时（>{int(timeout_seconds)}s），请重试或缩小需求范围") from exc
    except httpx.HTTPStatusError as exc:
        try:
            error_payload = exc.response.json().get("error", {})
            message = error_payload.get("message") or str(exc)
        except Exception:
            message = exc.response.text[:500] or str(exc)
        record_model_call(
            {
                **trace_base,
                "status": "http_error",
                "http_status": exc.response.status_code,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "error": message[:500],
                "retry_reason": f"http_{exc.response.status_code}",
            }
        )
        raise RuntimeError(f"OpenAI 请求失败，HTTP {exc.response.status_code}：{message}") from exc
    except Exception as exc:
        record_model_call(
            {
                **trace_base,
                "status": "error",
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "error": str(exc)[:500],
                "retry_reason": type(exc).__name__,
            }
        )
        raise RuntimeError(f"模型请求过程中发生未知错误：{exc}") from exc
