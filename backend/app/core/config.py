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
    auto_bootstrap_on_startup: bool = True
    seed_demo_data_on_bootstrap: bool = False
    bootstrap_max_retries: int = 30
    bootstrap_retry_interval_seconds: int = 2
    initial_admin_password: str = "admin123"
    password_hash_iterations: int = 260000

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
