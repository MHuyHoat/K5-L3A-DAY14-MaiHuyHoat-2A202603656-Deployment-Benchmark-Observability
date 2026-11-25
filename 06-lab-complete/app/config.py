"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường.

Không hard-code secret trong code: AGENT_API_KEY, REDIS_URL... đều đọc từ env
(đặt trên nền tảng deploy hoặc trong file .env khi chạy local).
"""
import os
from dataclasses import dataclass, field

DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _budget_from_env() -> tuple[float, str]:
    """Ưu tiên ngân sách ngày; nếu chỉ có MONTHLY_BUDGET_USD thì dùng ngân sách tháng."""
    monthly = os.getenv("MONTHLY_BUDGET_USD")
    daily = os.getenv("DAILY_BUDGET_USD")
    if daily not in (None, ""):
        return _env_float("DAILY_BUDGET_USD", 1.0), "day"
    if monthly not in (None, ""):
        return _env_float("MONTHLY_BUDGET_USD", 10.0), "month"
    return 1.0, "day"


@dataclass
class Settings:
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    environment: str = field(default_factory=lambda: _env("ENVIRONMENT", "development"))
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", DEFAULT_REDIS_URL))
    rate_limit_per_minute: int = field(default_factory=lambda: _env_int("RATE_LIMIT_PER_MINUTE", 10))
    rate_limit_window_seconds: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_WINDOW_SECONDS", 60))
    budget_usd: float = field(default_factory=lambda: _budget_from_env()[0])
    budget_period: str = field(default_factory=lambda: _budget_from_env()[1])
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod", "staging")


settings = Settings()
