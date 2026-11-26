from __future__ import annotations

from collections import defaultdict
from contextvars import ContextVar, Token
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI
from prometheus_client import CollectorRegistry
from prometheus_client.metrics_core import (
    CounterMetricFamily,
    GaugeMetricFamily,
    HistogramMetricFamily,
)
from prometheus_fastapi_instrumentator import Instrumentator, metrics as pfi_metrics
import redis
import structlog

from app.core.config import settings

# ---------------------------------------------------------------------------
# ContextVars for request / execution / Celery correlation
# ---------------------------------------------------------------------------

request_id_var: ContextVar[str | None] = ContextVar("omnitest_request_id", default=None)
user_id_var: ContextVar[int | str | None] = ContextVar("omnitest_user_id", default=None)
run_id_var: ContextVar[int | None] = ContextVar("omnitest_run_id", default=None)
task_id_var: ContextVar[str | None] = ContextVar("omnitest_task_id", default=None)
task_name_var: ContextVar[str | None] = ContextVar("omnitest_task_name", default=None)


def bind_context(
    *,
    request_id: str | None = None,
    user_id: int | str | None = None,
    run_id: int | None = None,
    task_id: str | None = None,
    task_name: str | None = None,
) -> dict[ContextVar, Token]:
    tokens: dict[ContextVar, Token] = {}
    if request_id is not None:
        tokens[request_id_var] = request_id_var.set(request_id)
    if user_id is not None:
        tokens[user_id_var] = user_id_var.set(user_id)
    if run_id is not None:
        tokens[run_id_var] = run_id_var.set(run_id)
    if task_id is not None:
        tokens[task_id_var] = task_id_var.set(task_id)
    if task_name is not None:
        tokens[task_name_var] = task_name_var.set(task_name)
    return tokens


def reset_context(tokens: dict[ContextVar, Token]) -> None:
    for var, token in reversed(list(tokens.items())):
        try:
            var.reset(token)
        except ValueError:
            pass


def _inject_observability_context(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    context_fields = {
        "request_id": request_id_var.get(),
        "user_id": user_id_var.get(),
        "run_id": run_id_var.get(),
        "task_id": task_id_var.get(),
        "task_name": task_name_var.get(),
    }
    for key, value in context_fields.items():
        if value is not None and key not in event_dict:
            event_dict[key] = value
    return event_dict


# ---------------------------------------------------------------------------
# Structlog + stdlib logging configuration
# ---------------------------------------------------------------------------

_OBSERVABILITY_HANDLER_ATTR = "_omnitest_observability_handler"


def resolve_log_format(force_format: str | None = None) -> str:
    fmt = (force_format or settings.log_format or "auto").strip().lower()
    if fmt in {"json", "console"}:
        return fmt
    if settings.app_env.strip().lower() in {"production", "prod", "staging", "docker"} and not os.getenv(
        "PYTEST_CURRENT_TEST"
    ):
        return "json"
    return "console"


def configure_observability_logging(
    *,
    force_format: str | None = None,
    force_level: str | None = None,
    stream: Any = None,
) -> str:
    chosen_format = resolve_log_format(force_format)
    level_name = (force_level or settings.log_level or "INFO").strip().upper()
    numeric_level = getattr(logging, level_name, logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _inject_observability_context,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if chosen_format == "json":
        renderer: Any = structlog.processors.JSONRenderer(ensure_ascii=False)
        pre_chain_processors = [
            *shared_processors,
            structlog.processors.format_exc_info,
        ]
        structlog_processors = [
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ]
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)
        pre_chain_processors = list(shared_processors)
        structlog_processors = [
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ]

    structlog.configure(
        processors=structlog_processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=pre_chain_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    target_stream = stream
    if target_stream is None and getattr(type(sys.stderr), "__name__", "") == "LoggingProxy":
        # Celery's redirect_stdouts replaces sys.stderr with LoggingProxy; binding
        # StreamHandler to it causes recursive emission into celery.redirected and drops logs.
        target_stream = sys.__stderr__

    handler = logging.StreamHandler(stream=target_stream)
    handler.setFormatter(formatter)
    handler.setLevel(numeric_level)
    setattr(handler, _OBSERVABILITY_HANDLER_ATTR, True)

    root_logger = logging.getLogger()
    preserved_handlers = [
        existing
        for existing in list(root_logger.handlers)
        if not getattr(existing, _OBSERVABILITY_HANDLER_ATTR, False)
        and existing.__class__.__module__.startswith("_pytest.")
    ]
    root_logger.handlers = [*preserved_handlers, handler]
    root_logger.setLevel(numeric_level)

    for noisy_logger in ("uvicorn.access", "celery.task", "celery.redirected"):
        logging.getLogger(noisy_logger).propagate = True

    return chosen_format


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


# ---------------------------------------------------------------------------
# Worker & Beat lightweight healthcheck heartbeat file
# ---------------------------------------------------------------------------

_heartbeat_stop_event: threading.Event | None = None
_heartbeat_thread: threading.Thread | None = None
_heartbeat_lock = threading.Lock()


def touch_worker_heartbeat(path: str | None = None) -> Path:
    target = Path(path or settings.worker_heartbeat_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{int(time.time())}\n", encoding="utf-8")
    return target


def start_worker_heartbeat_loop(
    path: str | None = None,
    interval_seconds: int | None = None,
) -> None:
    global _heartbeat_stop_event, _heartbeat_thread
    target_path = path or settings.worker_heartbeat_path
    interval = max(int(interval_seconds or settings.worker_heartbeat_interval_seconds or 15), 2)
    with _heartbeat_lock:
        if _heartbeat_thread is not None and _heartbeat_thread.is_alive():
            return
        touch_worker_heartbeat(target_path)
        stop_event = threading.Event()
        _heartbeat_stop_event = stop_event

        def _beat() -> None:
            while not stop_event.wait(interval):
                try:
                    touch_worker_heartbeat(target_path)
                except Exception:
                    pass

        thread = threading.Thread(
            target=_beat,
            name="omnitest-worker-heartbeat",
            daemon=True,
        )
        thread.start()
        _heartbeat_thread = thread


def stop_worker_heartbeat_loop() -> None:
    global _heartbeat_stop_event, _heartbeat_thread
    with _heartbeat_lock:
        if _heartbeat_stop_event is not None:
            _heartbeat_stop_event.set()
        _heartbeat_stop_event = None
        _heartbeat_thread = None


# ---------------------------------------------------------------------------
# Celery signal hooks (trace propagation + worker/beat healthcheck)
# ---------------------------------------------------------------------------

_celery_signals_configured = False
_celery_task_tokens: dict[tuple[str, int], dict[ContextVar, Token]] = {}
_celery_tokens_lock = threading.Lock()


def _extract_trace_headers(task: Any, kwargs: dict[str, Any] | None = None) -> tuple[str | None, Any]:
    request = getattr(task, "request", None)
    headers = getattr(request, "headers", None) if request is not None else None
    headers = headers if isinstance(headers, dict) else {}
    kw = kwargs or {}
    req_id = (
        getattr(request, "request_id", None)
        or headers.get("request_id")
        or kw.get("request_id")
    )
    uid = (
        getattr(request, "user_id", None)
        if getattr(request, "user_id", None) is not None
        else headers.get("user_id")
    )
    if uid is None:
        uid = kw.get("user_id")
    return (str(req_id) if req_id else None), uid


def setup_celery_observability(_celery_app: Any = None) -> None:
    global _celery_signals_configured
    if _celery_signals_configured:
        return
    _celery_signals_configured = True

    from celery.signals import (
        after_setup_logger,
        after_setup_task_logger,
        beat_init,
        before_task_publish,
        task_postrun,
        task_prerun,
        worker_process_init,
        worker_ready,
        worker_shutdown,
        worker_shutting_down,
    )

    obs_logger = get_logger("app.celery")

    @after_setup_logger.connect(weak=False)
    def _on_after_setup_logger(logger: logging.Logger | None = None, **_kw: Any) -> None:
        configure_observability_logging()

    @after_setup_task_logger.connect(weak=False)
    def _on_after_setup_task_logger(logger: logging.Logger | None = None, **_kw: Any) -> None:
        if logger is not None:
            logger.handlers = []
            logger.propagate = True
            logger.setLevel(logging.NOTSET)
            logger.disabled = False
        configure_observability_logging()

    @worker_process_init.connect(weak=False)
    def _on_worker_process_init(**_kw: Any) -> None:
        configure_observability_logging()

    @before_task_publish.connect(weak=False)
    def _propagate_trace_headers(headers: dict | None = None, **_kwargs: Any) -> None:
        if headers is None:
            return
        req_id = request_id_var.get()
        uid = user_id_var.get()
        if req_id and not headers.get("request_id"):
            headers["request_id"] = req_id
        if uid is not None and headers.get("user_id") is None:
            headers["user_id"] = uid

    @task_prerun.connect(weak=False)
    def _on_task_prerun(
        task_id: str | None = None,
        task: Any = None,
        kwargs: dict[str, Any] | None = None,
        **_kw: Any,
    ) -> None:
        req_id, uid = _extract_trace_headers(task, kwargs)
        task_name = getattr(task, "name", None)
        tokens = bind_context(
            request_id=req_id,
            user_id=uid,
            task_id=task_id,
            task_name=task_name,
        )
        key = (task_id or "", threading.get_ident())
        with _celery_tokens_lock:
            _celery_task_tokens[key] = tokens
        try:
            touch_worker_heartbeat()
        except Exception:
            pass
        obs_logger.info("celery_task_started", task_id=task_id, task_name=task_name)

    @task_postrun.connect(weak=False)
    def _on_task_postrun(
        task_id: str | None = None,
        task: Any = None,
        state: str | None = None,
        **_kw: Any,
    ) -> None:
        task_name = getattr(task, "name", None)
        obs_logger.info("celery_task_finished", task_id=task_id, task_name=task_name, state=state)
        key = (task_id or "", threading.get_ident())
        with _celery_tokens_lock:
            tokens = _celery_task_tokens.pop(key, None)
        if tokens:
            reset_context(tokens)
        try:
            touch_worker_heartbeat()
        except Exception:
            pass

    @worker_ready.connect(weak=False)
    def _on_worker_ready(**_kw: Any) -> None:
        configure_observability_logging()
        start_worker_heartbeat_loop()
        obs_logger.info("celery_worker_ready")

    @worker_shutting_down.connect(weak=False)
    def _on_worker_shutting_down(**_kw: Any) -> None:
        stop_worker_heartbeat_loop()

    @worker_shutdown.connect(weak=False)
    def _on_worker_shutdown(**_kw: Any) -> None:
        stop_worker_heartbeat_loop()

    @beat_init.connect(weak=False)
    def _on_beat_init(**_kw: Any) -> None:
        configure_observability_logging()
        start_worker_heartbeat_loop()
        obs_logger.info("celery_beat_ready")


# ---------------------------------------------------------------------------
# Prometheus metrics (in-process + Redis cross-container aggregation)
# ---------------------------------------------------------------------------

EXECUTION_DURATION_BUCKETS: tuple[float, ...] = (
    0.1,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
    600.0,
)
AI_STAGE_DURATION_BUCKETS: tuple[float, ...] = (
    0.1,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
)
CELERY_MONITORED_QUEUES: tuple[str, ...] = (
    "execution_fast",
    "execution_browser",
    "execution_perf",
    "case_generation",
    "maintenance",
    "celery",
)

_REDIS_COUNTER_PREFIX = "omnitest:prom:counter:"
_REDIS_HIST_PREFIX = "omnitest:prom:hist:"

OMNITEST_REGISTRY = CollectorRegistry()
_metrics_lock = threading.Lock()
_counters: dict[str, dict[tuple[str, ...], float]] = defaultdict(lambda: defaultdict(float))
_hist_buckets: dict[str, dict[tuple[str, ...], list[int]]] = defaultdict(dict)
_hist_sums: dict[str, dict[tuple[str, ...], float]] = defaultdict(lambda: defaultdict(float))
_hist_counts: dict[str, dict[tuple[str, ...], int]] = defaultdict(lambda: defaultdict(int))


_redis_pools: dict[str, redis.ConnectionPool] = {}
_redis_pool_lock = threading.Lock()


def _is_unit_test_env() -> bool:
    return bool(os.getenv("PYTEST_CURRENT_TEST")) or settings.backend_internal_url.startswith(
        "http://testserver"
    )


def _get_pooled_redis(url: str) -> redis.Redis | None:
    try:
        with _redis_pool_lock:
            pool = _redis_pools.get(url)
            if pool is None:
                pool = redis.ConnectionPool.from_url(
                    url,
                    decode_responses=True,
                    socket_connect_timeout=0.3,
                    socket_timeout=0.3,
                    max_connections=16,
                )
                _redis_pools[url] = pool
        return redis.Redis(connection_pool=pool)
    except Exception:
        return None


def _get_metrics_redis(url: str | None = None) -> redis.Redis | None:
    if _is_unit_test_env():
        return None
    return _get_pooled_redis(url or settings.redis_url)


def _encode_labels(labels: tuple[str, ...]) -> str:
    return json.dumps(list(labels), separators=(",", ":"), ensure_ascii=False)


def _decode_labels(encoded: str) -> tuple[str, ...] | None:
    try:
        parsed = json.loads(encoded)
        if isinstance(parsed, list):
            return tuple(str(item) for item in parsed)
    except Exception:
        pass
    return None


def _increment_counter(metric_name: str, labels: tuple[str, ...], amount: float = 1.0) -> None:
    with _metrics_lock:
        _counters[metric_name][labels] += amount
    client = _get_metrics_redis()
    if client is not None:
        try:
            client.hincrbyfloat(
                f"{_REDIS_COUNTER_PREFIX}{metric_name}",
                _encode_labels(labels),
                float(amount),
            )
        except Exception:
            pass


def _observe_histogram(
    metric_name: str,
    labels: tuple[str, ...],
    buckets: tuple[float, ...],
    value: float,
) -> None:
    val = max(float(value), 0.0)
    with _metrics_lock:
        bucket_counts = _hist_buckets[metric_name].get(labels)
        if bucket_counts is None or len(bucket_counts) != len(buckets):
            bucket_counts = [0] * len(buckets)
            _hist_buckets[metric_name][labels] = bucket_counts
        for idx, upper in enumerate(buckets):
            if val <= upper:
                bucket_counts[idx] += 1
        _hist_counts[metric_name][labels] += 1
        _hist_sums[metric_name][labels] += val

    client = _get_metrics_redis()
    if client is not None:
        try:
            label_key = _encode_labels(labels)
            hash_key = f"{_REDIS_HIST_PREFIX}{metric_name}"
            pipe = client.pipeline()
            for upper in buckets:
                if val <= upper:
                    pipe.hincrby(hash_key, f"{label_key}|{upper}", 1)
            pipe.hincrby(hash_key, f"{label_key}|+Inf", 1)
            pipe.hincrbyfloat(hash_key, f"{label_key}|_sum", val)
            pipe.execute()
        except Exception:
            pass


def _read_counter_samples(metric_name: str) -> dict[tuple[str, ...], float]:
    client = _get_metrics_redis()
    if client is not None:
        try:
            raw = client.hgetall(f"{_REDIS_COUNTER_PREFIX}{metric_name}")
            if raw:
                parsed: dict[tuple[str, ...], float] = {}
                for field, value in raw.items():
                    labels = _decode_labels(field)
                    if labels is not None:
                        parsed[labels] = float(value)
                return parsed
        except Exception:
            pass
    with _metrics_lock:
        return dict(_counters.get(metric_name, {}))


def _read_histogram_samples(
    metric_name: str,
    buckets: tuple[float, ...],
) -> dict[tuple[str, ...], tuple[list[tuple[str, float]], float]]:
    client = _get_metrics_redis()
    if client is not None:
        try:
            raw = client.hgetall(f"{_REDIS_HIST_PREFIX}{metric_name}")
            if raw:
                grouped: dict[tuple[str, ...], dict[str, float]] = defaultdict(dict)
                for field, val in raw.items():
                    label_key, sep, suffix = field.rpartition("|")
                    if not sep:
                        continue
                    labels = _decode_labels(label_key)
                    if labels is None:
                        continue
                    grouped[labels][suffix] = float(val)
                parsed: dict[tuple[str, ...], tuple[list[tuple[str, float]], float]] = {}
                for labels, parts in grouped.items():
                    bucket_list = [(str(upper), float(parts.get(str(upper), 0.0))) for upper in buckets]
                    inf_count = float(parts.get("+Inf", 0.0))
                    bucket_list.append(("+Inf", inf_count))
                    parsed[labels] = (bucket_list, float(parts.get("_sum", 0.0)))
                return parsed
        except Exception:
            pass

    with _metrics_lock:
        result: dict[tuple[str, ...], tuple[list[tuple[str, float]], float]] = {}
        for labels, counts in _hist_buckets.get(metric_name, {}).items():
            bucket_list = [(str(upper), float(counts[idx])) for idx, upper in enumerate(buckets)]
            bucket_list.append(("+Inf", float(_hist_counts[metric_name].get(labels, 0))))
            result[labels] = (bucket_list, float(_hist_sums[metric_name].get(labels, 0.0)))
        return result


def infer_provider_from_endpoint(endpoint_or_model: str | None) -> str:
    raw = (endpoint_or_model or "").strip().lower()
    if not raw:
        return "unknown"
    if "://" in raw:
        host = (urlparse(raw).hostname or "").lower()
    else:
        host = raw
    if "dashscope" in host or "aliyun" in host or "qwen" in host:
        return "dashscope"
    if "openai" in host or host.startswith("gpt-"):
        return "openai"
    if "anthropic" in host or "claude" in host:
        return "anthropic"
    if "deepseek" in host:
        return "deepseek"
    return host.split(".", 1)[0] or "custom"


def record_case_execution(
    *,
    case_type: str,
    status: str,
    error_type: str | None = None,
    duration_seconds: float | None = None,
) -> None:
    normalized_type = (case_type or "UNKNOWN").upper()
    normalized_status = (status or "UNKNOWN").upper()
    normalized_error = (error_type or "NONE").upper()
    _increment_counter(
        "omnitest_case_executions_total",
        (normalized_type, normalized_status, normalized_error),
        1.0,
    )
    if duration_seconds is not None and duration_seconds >= 0:
        _observe_histogram(
            "omnitest_case_execution_duration_seconds",
            (normalized_type, normalized_status),
            EXECUTION_DURATION_BUCKETS,
            duration_seconds,
        )


def record_ai_stage_duration(
    *,
    mode: str,
    stage: str,
    status: str,
    duration_seconds: float | None = None,
) -> None:
    if duration_seconds is None or duration_seconds < 0:
        return
    _observe_histogram(
        "omnitest_ai_generation_stage_duration_seconds",
        ((mode or "unknown").lower(), (stage or "unknown").lower(), (status or "unknown").lower()),
        AI_STAGE_DURATION_BUCKETS,
        duration_seconds,
    )


def record_ai_tokens(*, provider: str, model: str, tokens: int) -> None:
    if tokens <= 0:
        return
    _increment_counter(
        "omnitest_ai_tokens_total",
        ((provider or "unknown").lower(), model or "unknown"),
        float(tokens),
    )


def record_frontend_error(*, source: str = "vue") -> None:
    _increment_counter(
        "omnitest_frontend_errors_total",
        ((source or "vue").strip().lower() or "vue",),
        1.0,
    )


def fetch_celery_queue_depths() -> dict[str, int]:
    depths = {queue: 0 for queue in CELERY_MONITORED_QUEUES}
    if _is_unit_test_env():
        return depths
    try:
        client = _get_pooled_redis(settings.celery_broker_url)
        if client is None:
            return depths
        pipe = client.pipeline()
        for queue in CELERY_MONITORED_QUEUES:
            pipe.llen(queue)
        values = pipe.execute()
        for queue, val in zip(CELERY_MONITORED_QUEUES, values):
            depths[queue] = int(val or 0)
    except Exception:
        pass
    return depths


def reset_metrics_for_tests() -> None:
    with _metrics_lock:
        _counters.clear()
        _hist_buckets.clear()
        _hist_sums.clear()
        _hist_counts.clear()


class OmniTestMetricsCollector:
    """Custom Prometheus collector bridging worker/backend metrics and Celery queue depths."""

    def collect(self):
        exec_counter = CounterMetricFamily(
            "omnitest_case_executions_total",
            "Total number of executed test cases by type, status, and error_type.",
            labels=["case_type", "status", "error_type"],
        )
        for labels, val in _read_counter_samples("omnitest_case_executions_total").items():
            exec_counter.add_metric(list(labels), val)
        yield exec_counter

        exec_hist = HistogramMetricFamily(
            "omnitest_case_execution_duration_seconds",
            "Duration of test case executions in seconds.",
            labels=["case_type", "status"],
        )
        for labels, (buckets, total_sum) in _read_histogram_samples(
            "omnitest_case_execution_duration_seconds",
            EXECUTION_DURATION_BUCKETS,
        ).items():
            exec_hist.add_metric(list(labels), buckets=buckets, sum_value=total_sum)
        yield exec_hist

        queue_gauge = GaugeMetricFamily(
            "omnitest_celery_queue_depth",
            "Number of queued messages in Celery Redis broker queues.",
            labels=["queue"],
        )
        for queue, depth in fetch_celery_queue_depths().items():
            queue_gauge.add_metric([queue], float(depth))
        yield queue_gauge

        ai_stage_hist = HistogramMetricFamily(
            "omnitest_ai_generation_stage_duration_seconds",
            "Duration of AI case generation stages in seconds.",
            labels=["mode", "stage", "status"],
        )
        for labels, (buckets, total_sum) in _read_histogram_samples(
            "omnitest_ai_generation_stage_duration_seconds",
            AI_STAGE_DURATION_BUCKETS,
        ).items():
            ai_stage_hist.add_metric(list(labels), buckets=buckets, sum_value=total_sum)
        yield ai_stage_hist

        ai_tokens = CounterMetricFamily(
            "omnitest_ai_tokens_total",
            "Total AI completion/prompt tokens consumed by provider and model.",
            labels=["provider", "model"],
        )
        for labels, val in _read_counter_samples("omnitest_ai_tokens_total").items():
            ai_tokens.add_metric(list(labels), val)
        yield ai_tokens

        fe_errors = CounterMetricFamily(
            "omnitest_frontend_errors_total",
            "Total unhandled frontend runtime errors reported via /system/client-errors.",
            labels=["source"],
        )
        for labels, val in _read_counter_samples("omnitest_frontend_errors_total").items():
            fe_errors.add_metric(list(labels), val)
        yield fe_errors


_collector_registered = False
_instrumentator: Instrumentator | None = None
_metrics_setup_lock = threading.Lock()


def setup_metrics(app: FastAPI) -> None:
    global _collector_registered, _instrumentator
    with _metrics_setup_lock:
        if not _collector_registered:
            OMNITEST_REGISTRY.register(OmniTestMetricsCollector())
            _collector_registered = True

        if getattr(app.state, "omnitest_metrics_configured", False):
            return

        if _instrumentator is None:
            inst = Instrumentator(
                should_group_status_codes=False,
                should_ignore_untemplated=False,
                should_exclude_streaming_duration=True,
                excluded_handlers=["/metrics", r"/api/v1/system/health.*"],
                registry=OMNITEST_REGISTRY,
            )
            inst.add(
                pfi_metrics.requests(
                    metric_name="http_requests_total",
                    metric_namespace="omnitest",
                    registry=OMNITEST_REGISTRY,
                )
            )
            inst.add(
                pfi_metrics.latency(
                    metric_name="http_request_duration_seconds",
                    metric_namespace="omnitest",
                    should_exclude_streaming_duration=True,
                    registry=OMNITEST_REGISTRY,
                )
            )
            _instrumentator = inst

        _instrumentator.instrument(app).expose(
            app,
            endpoint="/metrics",
            include_in_schema=False,
        )
        app.state.omnitest_metrics_configured = True
