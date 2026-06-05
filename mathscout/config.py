from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    environment: str = Field(default="development", alias="MATHSCOUT_ENV")
    database_url: str = "postgresql+psycopg://mathscout:mathscout@localhost:5432/mathscout"
    redis_url: str = "redis://localhost:6379/0"
    raw_storage_dir: Path = Path(".data/raw")
    text_storage_dir: Path = Path(".data/text")
    cookie_storage_dir: Path = Path(".data/cookies")
    default_user_agent: str = "MathScout/0.1 (+local research crawler)"
    crawl_default_delay_seconds: int = 3
    crawl_max_concurrency: int = 4
    ai_provider: str = Field(default="rule", alias="AI_PROVIDER")
    deepseek_api_key: str | None = Field(default=None, alias="DEEPSEEK_API_KEY")
    openai_compatible_api_key: str | None = Field(
        default=None, alias="OPENAI_COMPATIBLE_API_KEY"
    )
    openai_compatible_base_url: str = Field(
        default="https://api.deepseek.com",
        alias="OPENAI_COMPATIBLE_BASE_URL",
    )
    openai_compatible_model: str = Field(
        default="deepseek-chat",
        alias="OPENAI_COMPATIBLE_MODEL",
    )
    openai_compatible_timeout_seconds: int = Field(
        default=90,
        alias="OPENAI_COMPATIBLE_TIMEOUT_SECONDS",
    )
    ai_max_text_chars: int = Field(default=12000, alias="AI_MAX_TEXT_CHARS")
    display_timezone: str = Field(default="Asia/Shanghai", alias="MATHSCOUT_DISPLAY_TIMEZONE")

    @property
    def ai_api_key(self) -> str | None:
        return self.deepseek_api_key or self.openai_compatible_api_key


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.raw_storage_dir.mkdir(parents=True, exist_ok=True)
    settings.text_storage_dir.mkdir(parents=True, exist_ok=True)
    settings.cookie_storage_dir.mkdir(parents=True, exist_ok=True)
    return settings
