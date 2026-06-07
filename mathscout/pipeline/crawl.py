from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from mathscout.config import get_settings
from mathscout.crawler.fetchers import HttpFetcher
from mathscout.db.models import (
    AccessLevel,
    CrawlStatus,
    PipelineStatus,
    SourceDocument,
    SourceSite,
)
from mathscout.parsers.html import html_to_text
from mathscout.parsers.pdf import pdf_to_text

UNSUPPORTED_CONTENT_TYPE_PREFIXES = ("image/", "audio/", "video/", "font/")
UNSUPPORTED_CONTENT_TYPES = {
    "application/octet-stream",
    "application/zip",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/x-zip-compressed",
}
EMPTY_TEXT_MIN_CHARS = 40
BOILERPLATE_TEXT_MAX_CHARS = 240
BOILERPLATE_MARKERS = (
    "enable javascript",
    "please enable javascript",
    "请启用javascript",
    "请启用 javascript",
    "请开启javascript",
    "请开启 javascript",
    "404 not found",
    "page not found",
)


class CrawlPipeline:
    """Phase 1: 抓取 URL，解析文本，写入本地文件，更新 source_documents 表。

    终点是 pipeline_status='crawled'，不调用 AI，不做 reconciliation。
    Phase 2 由 ExtractPipeline 负责，可随时独立触发。
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()
        self.fetcher = HttpFetcher()

    def fetch_and_store(self, url: str) -> dict[str, object]:
        """抓取单个 URL，存文件，返回基本元数据。不做 AI 提取。"""
        result = asyncio.run(self.fetcher.fetch(url))
        site = self._get_or_create_site(result.url)
        text = self._parse_content(result.raw_path, result.content_type)
        text_path = self._write_text(result.checksum, text)

        ct = (result.content_type or "").lower()
        if result.needs_login:
            pipeline_status = PipelineStatus.login_required
            pipeline_error = None
        elif any(ct.startswith(prefix) for prefix in UNSUPPORTED_CONTENT_TYPE_PREFIXES) or ct in UNSUPPORTED_CONTENT_TYPES:
            pipeline_status = PipelineStatus.failed
            pipeline_error = "unsupported content type"
        elif len(text) < EMPTY_TEXT_MIN_CHARS:
            pipeline_status = PipelineStatus.failed
            pipeline_error = "empty or boilerplate page"
        elif any(marker in text[:BOILERPLATE_TEXT_MAX_CHARS].lower() for marker in BOILERPLATE_MARKERS):
            pipeline_status = PipelineStatus.failed
            pipeline_error = "empty or boilerplate page"
        else:
            pipeline_status = PipelineStatus.crawled
            pipeline_error = None
        document = self._upsert_document(
            site=site,
            url=url,
            canonical_url=result.url,
            status_code=result.status_code,
            content_type=result.content_type,
            checksum=result.checksum,
            raw_path=result.raw_path,
            text_path=text_path,
            needs_login=result.needs_login,
            pipeline_status=pipeline_status,
            pipeline_error=pipeline_error,
        )
        self.session.commit()
        return {
            "url": result.url,
            "http_status": result.status_code,
            "document_id": str(document.id),
            "pipeline_status": pipeline_status.value,
            "content_type": result.content_type or "",
            "text_length": len(text),
            "raw_path": str(result.raw_path),
        }

    def _get_or_create_site(self, url: str) -> SourceSite:
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        site = self.session.scalar(select(SourceSite).where(SourceSite.base_url == base_url))
        if site is not None:
            return site
        site = SourceSite(
            name=parsed.netloc,
            base_url=base_url,
            domain=parsed.netloc,
            category="unknown",
            access_level=AccessLevel.public,
        )
        self.session.add(site)
        self.session.flush()
        return site

    def _parse_content(self, raw_path: Path, content_type: str | None) -> str:
        ct = (content_type or "").lower()
        if "pdf" in ct or raw_path.suffix.lower() == ".pdf":
            return pdf_to_text(raw_path)
        raw_bytes = raw_path.read_bytes()
        html = raw_bytes.decode("utf-8", errors="ignore")
        if "html" in ct or raw_path.suffix.lower() in {".html", ".htm"}:
            return html_to_text(html)
        return html

    def _write_text(self, checksum: str, text: str) -> Path:
        text_path = self.settings.text_storage_dir / f"{checksum}.txt"
        text_path.write_text(text, encoding="utf-8")
        return text_path

    def _upsert_document(
        self,
        site: SourceSite,
        url: str,
        canonical_url: str,
        status_code: int,
        content_type: str | None,
        checksum: str,
        raw_path: Path,
        text_path: Path,
        needs_login: bool,
        pipeline_status: PipelineStatus,
        pipeline_error: str | None = None,
    ) -> SourceDocument:
        document = self.session.scalar(
            select(SourceDocument).where(
                SourceDocument.url == url,
                SourceDocument.checksum == checksum,
            )
        )
        if document is None:
            document = SourceDocument(site_id=site.id, url=url)
            self.session.add(document)
        document.canonical_url = canonical_url
        document.content_type = content_type
        document.status = CrawlStatus.blocked if needs_login else CrawlStatus.succeeded
        document.http_status = status_code
        document.needs_login = needs_login
        document.checksum = checksum
        document.raw_path = str(raw_path)
        document.text_path = str(text_path)
        document.pipeline_status = pipeline_status
        document.pipeline_error = pipeline_error
        document.fetched_at = datetime.utcnow()
        self.session.flush()
        return document
