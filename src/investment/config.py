"""全局配置（读 .env + 默认值）。

用法：
    from investment.config import get_settings
    settings = get_settings()
    print(settings.okx_base_url)

设计要点：
- pydantic-settings 自动从 .env 读取，case_insensitive。
- get_settings() lru_cache 单例，全进程一份。
- 任何模块只能从这里读配置，禁止直接 os.environ.get。
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === OKX ===
    okx_base_url: str = Field(default="https://www.okx.com")
    okx_request_timeout: float = Field(default=10.0)
    okx_max_retries: int = Field(default=3)
    okx_retry_backoff_sec: float = Field(default=0.5)

    # === Feishu（阶段 5 用） ===
    feishu_app_id: str = Field(default="")
    feishu_app_secret: str = Field(default="")
    feishu_chat_id: str = Field(default="")
    feishu_dry_run: bool = Field(default=True)

    # === Logging ===
    log_level: str = Field(default="INFO")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
