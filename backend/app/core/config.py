from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "自动化测试平台"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "mysql+pymysql://tester:tester123@mysql:3306/test_platform"
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/0"
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
