from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="URLSHORT_")

    redis_url: str = "redis://localhost:6379/0"
    base_url: str = "http://localhost:8000"

    # Rate limiting: N requests per WINDOW_SECONDS, per client (IP).
    rate_limit_requests: int = 20
    rate_limit_window_seconds: int = 60


settings = Settings()
