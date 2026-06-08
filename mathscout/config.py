from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    environment: str = Field(default="development", alias="MATHSCOUT_ENV")
    database_url: str = "postgresql+psycopg://mathscout:mathscout@localhost:5432/mathscout"
    raw_storage_dir: Path = Path(".data/raw")
    text_storage_dir: Path = Path(".data/text")
    cookie_storage_dir: Path = Path(".data/cookies")
    default_user_agent: str = "MathScout/0.1 (+local research crawler)"
    crawl_default_delay_seconds: int = 3
    crawl_max_concurrency: int = 4
    # 是否遵守目标站点的 robots.txt（按域缓存；拉取失败时 fail-open 放行）。
    respect_robots: bool = Field(default=True, alias="RESPECT_ROBOTS")
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

    # 抽取阶段置信度：证据/兜底文本匹配用较低值，命中候选自身教材字段用较高值。
    evidence_default_confidence: float = Field(default=0.55, alias="EVIDENCE_DEFAULT_CONFIDENCE")
    extraction_match_confidence: float = Field(default=0.75, alias="EXTRACTION_MATCH_CONFIDENCE")

    # 文档转换 / OCR：扫描版 PDF 与图片走 Azure 文档智能。留空则不启用 OCR，
    # 相关文档会被标记为 needs_ocr，等待人工处理或后续配置。
    azure_doc_intel_endpoint: str | None = Field(default=None, alias="AZURE_DOC_INTEL_ENDPOINT")
    azure_doc_intel_key: str | None = Field(default=None, alias="AZURE_DOC_INTEL_KEY")

    # 附件下载：链接发现阶段识别并入队 PDF/Office 附件（课件/教案/学案常在附件里）。
    download_attachments: bool = Field(default=True, alias="DOWNLOAD_ATTACHMENTS")

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
