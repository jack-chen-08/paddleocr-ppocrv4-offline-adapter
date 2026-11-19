"""应用配置：全部从环境变量读，代码里不留密钥。"""
import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    app_name: str = os.getenv("APP_NAME", "member-space-module")
    env: str = os.getenv("APP_ENV", "local")
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://app:app@localhost:5432/app"
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    # 外部依赖未就绪时统一走桩：README 必须标注对接点与切换开关（验收项要求）
    mock_mode: bool = _bool("MOCK_MODE", True)
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    extra: dict = field(default_factory=dict)


settings = Settings()
