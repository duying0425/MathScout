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
from mathscout.parsers.convert import (
    DocumentConverter,
    MarkItDownNotInstalledError,
    OcrNotConfiguredError,
)
from mathscout.parsers.detect import DocumentKind, detect_document_kind

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
    """Phase 1: 抓取 URL，识别类型并转换为文本/Markdown，写入本地文件，更新 source_documents。

    终点是 pipeline_status='crawled'，不调用 AI，不做 reconciliation。
    Phase 2 由 ExtractPipeline 负责，可随时独立触发。
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()
        self.fetcher = HttpFetcher()
        self.converter = DocumentConverter(self.settings)

    def fetch_and_store(self, url: str) -> dict[str, object]:
        """抓取单个 URL，识别类型、转换、存文件，返回基本元数据。不做 AI 提取。"""
        result = asyncio.run(self.fetcher.fetch(url))
        site = self._get_or_create_site(result.url)

        if result.needs_login:
            text, kind, converter = "", DocumentKind.unknown, ""
            pipeline_status, pipeline_error = PipelineStatus.login_required, None
        else:
            kind = detect_document_kind(result.raw_path, result.content_type, result.url)
            text, pipeline_status, pipeline_error, converter = self._convert(result.raw_path, kind)

        text_path = self._write_text(result.checksum, text)
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
            "document_kind": kind.value,
            "converter": converter,
            "text_length": len(text),
            "raw_path": str(result.raw_path),
        }

    def _convert(
        self, raw_path: Path, kind: DocumentKind
    ) -> tuple[str, PipelineStatus, str | None, str]:
        """按识别出的类型转换内容，返回（文本, 流水线状态, 错误信息, 转换器名）。"""
        try:
            conv = self.converter.convert(raw_path, kind)
        except OcrNotConfiguredError as exc:
            return "", PipelineStatus.needs_ocr, str(exc), ""
        except MarkItDownNotInstalledError as exc:
            return "", PipelineStatus.failed, str(exc), ""
        except ValueError:
            return "", PipelineStatus.failed, f"不支持的内容类型：{kind.value}", ""
        except Exception as exc:  # noqa: BLE001 - 任何转换异常都降级为失败并记录
            return "", PipelineStatus.failed, f"转换失败：{exc}", ""

        text = conv.text
        if len(text) < EMPTY_TEXT_MIN_CHARS or any(
            marker in text[:BOILERPLATE_TEXT_MAX_CHARS].lower() for marker in BOILERPLATE_MARKERS
        ):
            return text, PipelineStatus.failed, "页面为空或仅样板内容", conv.converter
        return text, PipelineStatus.crawled, None, conv.converter

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

    def _write_text(self, checksum: str, text: str) -> Path:
        text_path = self.settings.text_storage_dir / f"{checksum}.md"
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
