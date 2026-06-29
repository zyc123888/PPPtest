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
    auto_bootstrap_on_startup: bool = True
    seed_demo_data_on_bootstrap: bool = False
    bootstrap_max_retries: int = 30
    bootstrap_retry_interval_seconds: int = 2
    initial_admin_password: str = "admin123"
    password_hash_iterations: int = 260000
    normalize_mysql_charset_on_bootstrap: bool = False

    # —— 用例生成（case generation）可调参数 ——
    # 支持通过环境变量覆盖（大写字段名，如 CASE_GEN_DEFAULT_MODEL），无需改源码重建镜像。
    case_gen_default_model: str = "gpt-5.5"
    case_gen_openai_base_url: str = "https://api.openai.com/v1"
    case_gen_bailian_base_url: str = "https://coding.dashscope.aliyuncs.com/v1"
    case_gen_qwen_compatible_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    case_gen_qwen_coding_intl_base_url: str = "https://coding-intl.dashscope.aliyuncs.com/v1"
    case_gen_image_analysis_batch_size: int = 8
    case_gen_requirement_section_text_limit: int = 1200
    case_gen_requirement_total_text_limit: int = 36000
    case_gen_requirement_batch_text_limit: int = 700
    case_gen_requirement_max_tokens: int = 8000
    case_gen_pending_confirmation_limit: int = 12
    case_gen_pending_confirmation_text_limit: int = 220
    case_gen_function_point_text_limit: int = 320
    case_gen_testcase_fp_batch_size: int = 5
    case_gen_min_cases_per_function_point: int = 5
    case_gen_testcase_repair_max_rounds: int = 2
    case_gen_max_concurrency: int = 4
    case_gen_max_ai_retries: int = 2
    case_gen_default_chat_timeout_seconds: float = 240.0
    case_gen_long_chat_timeout_seconds: float = 420.0
    case_gen_stale_seconds_with_task: int = 300
    case_gen_stale_seconds_inline: int = 30

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
