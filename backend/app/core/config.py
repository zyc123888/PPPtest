from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "自动化测试平台"
    app_version: str = "1.1.0"
    app_env: str = "local"
    api_v1_prefix: str = "/api/v1"

    database_url: str = "sqlite:///./test.db"
    redis_url: str = "redis://127.0.0.1:6379/0"
    celery_broker_url: str = "redis://127.0.0.1:6379/0"
    celery_result_backend: str = "redis://127.0.0.1:6379/0"
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000,http://frontend:3000"
    )
    backend_internal_url: str = "http://backend:8000"
    frontend_internal_url: str = "http://frontend:3000"
    backend_public_url: str = "http://127.0.0.1:8000"
    frontend_public_url: str = "http://127.0.0.1:3000"
    request_timeout_seconds: int = 30
    execution_engine: str = "pytest"
    report_output_dir: str = "reports"
    case_generation_rules_dir: str = ""
    case_generation_unified_rules_dir: str = ""
    ui_case_skill_dir: str = "ui_case_skills"
    ui_case_ai_timeout_seconds: float = 120.0
    ui_case_ai_max_tokens: int = 5000
    auto_bootstrap_on_startup: bool = True
    seed_demo_data_on_bootstrap: bool = False
    bootstrap_max_retries: int = 30
    bootstrap_retry_interval_seconds: int = 2
    initial_admin_password: str = "admin123"
    password_hash_iterations: int = 260000
    app_encryption_key: str = ""
    normalize_mysql_charset_on_bootstrap: bool = False

    # —— 用例生成（case generation）可调参数 ——
    # 支持通过环境变量覆盖（大写字段名，如 CASE_GEN_DEFAULT_MODEL），无需改源码重建镜像。
    case_gen_default_model: str = "gpt-5.5"
    case_gen_openai_base_url: str = "https://api.openai.com/v1"
    case_gen_bailian_base_url: str = "https://coding.dashscope.aliyuncs.com/v1"
    case_gen_qwen_compatible_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    case_gen_qwen_coding_intl_base_url: str = "https://coding-intl.dashscope.aliyuncs.com/v1"
    case_gen_image_analysis_batch_size: int = 8
    # —— 输入侧上限：利用大上下文模型（~1M token），尽量保留章节完整正文 ——
    # section/total 控制“喂给模型的输入文本量”，输入便宜故放宽；
    # batch_text_limit + batch_max_sections 控制“每批规模”，真正保护的是 8K 输出不被截断。
    case_gen_requirement_section_text_limit: int = 6000
    case_gen_requirement_total_text_limit: int = 200000
    case_gen_requirement_batch_text_limit: int = 6000
    case_gen_requirement_batch_max_sections: int = 4
    case_gen_requirement_batch_concurrency: int = 2
    # 输出侧上限：模型单次输出硬限，分批就是为了让每批输出 JSON 能完整闭合，勿随意调大
    case_gen_requirement_max_tokens: int = 8000
    case_gen_pending_confirmation_limit: int = 12
    case_gen_pending_confirmation_text_limit: int = 220
    case_gen_function_point_text_limit: int = 320
    case_gen_testcase_fp_batch_size: int = 5
    case_gen_testcase_repair_max_rounds: int = 2
    case_gen_max_concurrency: int = 4
    # V2 trusted source shards call the model once per source. Keep this conservative
    # because some providers reject concurrent requests with 429 concurrency quota errors.
    case_gen_trusted_shard_concurrency: int = 2
    # Scope index uses model calls per document batch. Keep this separate from
    # testcase shard concurrency so long documents can be indexed faster while
    # still staying below provider concurrency quota.
    case_gen_scope_index_concurrency: int = 2
    case_gen_scope_index_two_phase_trigger_sections: int = 16
    case_gen_scope_index_two_phase_trigger_text: int = 48000
    # Unified trusted-gate is deterministic by default. Enable only when you
    # explicitly want an additional model review after backend gate passes.
    case_gen_trusted_model_gate_enabled: bool = False
    case_gen_trusted_shard_max_attempts: int = 2
    case_gen_max_ai_retries: int = 2
    case_gen_default_chat_timeout_seconds: float = 240.0
    case_gen_long_chat_timeout_seconds: float = 420.0
    case_gen_heartbeat_seconds: int = 15
    case_gen_watchdog_enabled: bool = True
    case_gen_attempt_stale_seconds: int = 900
    case_gen_dispatch_stale_seconds: int = 120
    case_gen_watchdog_interval_seconds: int = 30
    case_gen_artifact_retention_days: int = 30
    case_gen_artifact_content_preview_bytes: int = 131072
    case_gen_max_source_download_bytes: int = 10 * 1024 * 1024
    case_gen_max_image_download_bytes: int = 12 * 1024 * 1024
    case_gen_allow_private_urls: bool = False
    case_gen_trusted_min_evidence_coverage_rate: float = 0.80
    case_gen_trusted_max_weak_expected_rate: float = 0.10
    case_gen_trusted_max_weak_step_rate: float = 0.10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def database_backend(self) -> str:
        return self.database_url.split(":", 1)[0]

    @property
    def database_name(self) -> str | None:
        if self.database_backend.startswith("sqlite"):
            return self.database_url.replace("sqlite:///", "", 1) or None
        if "/" not in self.database_url:
            return None
        return self.database_url.rsplit("/", 1)[-1] or None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
