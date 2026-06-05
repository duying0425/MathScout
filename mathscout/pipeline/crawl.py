from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from mathscout.config import get_settings
from mathscout.crawler.fetchers import FetchResult, HttpFetcher
from mathscout.db.models import (
    AccessLevel,
    CandidateItemType,
    CandidateKnowledgeItem,
    CrawlStatus,
    EvidenceSnippet,
    ExtractionRun,
    KnowledgePoint,
    MethodKnowledgePointLink,
    MethodSectionLink,
    ReconciliationAction,
    ReconciliationDecision,
    ReviewStatus,
    Section,
    SourceDocument,
    SourceSite,
    TeachingMethod,
    TeachingMethodVariant,
)
from mathscout.extraction.ai_method_extractor import AIMethodExtractor
from mathscout.extraction.rule_based import RuleBasedMethodExtractor
from mathscout.extraction.schemas import CandidateKnowledgeItemSchema
from mathscout.parsers.html import html_to_text
from mathscout.parsers.pdf import pdf_to_text
from mathscout.runtime import FetchObservation, RuntimeObservation, RuntimeStatus
from mathscout.utils.text import normalize_semantic_key

UNSUPPORTED_CONTENT_TYPE_PREFIXES = ("image/", "audio/", "video/", "font/")
UNSUPPORTED_CONTENT_TYPES = {
    "application/octet-stream",
    "application/zip",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/x-zip-compressed",
}
SUPPORTED_CONTENT_MARKERS = ("html", "pdf", "text", "json", "xml")
SUPPORTED_URL_SUFFIXES = {".html", ".htm", ".pdf", ".txt", ".json", ".xml"}
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


@dataclass(frozen=True)
class ParsedDocument:
    requested_url: str
    fetch_result: FetchResult
    site: SourceSite
    text: str
    text_path: Path
    document: SourceDocument


@dataclass(frozen=True)
class ReconciledCandidateResult:
    candidate: CandidateKnowledgeItem
    method: TeachingMethod
    method_created: bool
    variant_created: bool


@dataclass(frozen=True)
class ExtractionToolResult:
    extraction_run: ExtractionRun
    candidate_count: int
    method_count: int
    variant_count: int
    error: str | None


class CrawlPipeline:
    def __init__(self, session: Session, extractor_mode: str = "auto") -> None:
        self.session = session
        self.settings = get_settings()
        self.fetcher = HttpFetcher()
        self.extractor_mode = extractor_mode

    def crawl_url(self, url: str) -> dict[str, object]:
        result = self.fetch_url(url)
        parsed = self.parse_document(url, result)
        fetch_stop_result = self._after_fetch_check(
            requested_url=parsed.requested_url,
            result=result,
            document=parsed.document,
            text=parsed.text,
            text_path=parsed.text_path,
        )
        if fetch_stop_result is not None:
            self.session.commit()
            return fetch_stop_result

        extraction = self.extract_methods(
            document=parsed.document,
            document_url=result.url,
            text=parsed.text,
        )
        self.session.commit()
        return self._crawl_success_result(parsed, extraction)

    def fetch_url(self, url: str) -> FetchResult:
        return asyncio.run(self.fetcher.fetch(url))

    def parse_document(self, requested_url: str, result: FetchResult) -> ParsedDocument:
        site = self._get_or_create_site(result.url)
        text = self._parse_fetch_result(result.raw_path, result.content_type)
        text_path = self._write_text(result.checksum, text)
        document = self._upsert_document(
            site=site,
            url=requested_url,
            canonical_url=result.url,
            status_code=result.status_code,
            content_type=result.content_type,
            checksum=result.checksum,
            raw_path=result.raw_path,
            text_path=text_path,
            needs_login=result.needs_login,
        )
        return ParsedDocument(
            requested_url=requested_url,
            fetch_result=result,
            site=site,
            text=text,
            text_path=text_path,
            document=document,
        )

    def extract_methods(
        self,
        *,
        document: SourceDocument,
        document_url: str,
        text: str,
    ) -> ExtractionToolResult:
        extractor_name, extractor_version, model_name = self._extractor_metadata()
        extraction_run = ExtractionRun(
            document_id=document.id,
            extractor_name=extractor_name,
            extractor_version=extractor_version,
            model_name=model_name,
            prompt_version="ai_method_extractor_v1" if model_name else None,
            status=CrawlStatus.succeeded,
            output_json={},
        )
        self.session.add(extraction_run)
        self.session.flush()

        candidates, extraction_error = self._extract_candidates(text, document_url)
        created_candidates = 0
        created_methods = 0
        created_variants = 0
        for candidate_schema in candidates:
            reconciled = self.reconcile_candidate(
                document=document,
                extraction_run=extraction_run,
                candidate_schema=candidate_schema,
            )
            created_candidates += 1
            if reconciled.method_created:
                created_methods += 1
            if reconciled.variant_created:
                created_variants += 1

        extraction_run.output_json = {
            "candidate_count": created_candidates,
            "method_count": created_methods,
            "variant_count": created_variants,
            "extractor_mode": self.extractor_mode,
            "error": extraction_error,
        }
        return ExtractionToolResult(
            extraction_run=extraction_run,
            candidate_count=created_candidates,
            method_count=created_methods,
            variant_count=created_variants,
            error=extraction_error,
        )

    def reconcile_candidate(
        self,
        *,
        document: SourceDocument,
        extraction_run: ExtractionRun,
        candidate_schema: CandidateKnowledgeItemSchema,
    ) -> ReconciledCandidateResult:
        evidence = self._create_evidence(document, candidate_schema.evidence[0].snippet or "")
        candidate = CandidateKnowledgeItem(
            document_id=document.id,
            extraction_run_id=extraction_run.id,
            item_type=CandidateItemType.teaching_method,
            title=candidate_schema.title,
            semantic_key=candidate_schema.semantic_key,
            textbook_series=candidate_schema.textbook_series,
            book_code=candidate_schema.book_code,
            chapter_title=candidate_schema.chapter_title,
            section_title=candidate_schema.section_title,
            payload=candidate_schema.payload,
            evidence_ids=[str(evidence.id)],
            confidence=candidate_schema.confidence,
            review_status=ReviewStatus.pending,
        )
        self.session.add(candidate)
        self.session.flush()

        method, method_created = self._upsert_method_from_candidate(candidate, evidence.id)
        variant_created = self._create_variant_from_candidate(
            method=method,
            document=document,
            evidence=evidence,
            candidate=candidate,
        )
        self._record_reconciliation_decision(
            candidate=candidate,
            method=method,
            action=ReconciliationAction.create
            if method_created
            else ReconciliationAction.create_variant
            if variant_created
            else ReconciliationAction.skip,
        )
        return ReconciledCandidateResult(
            candidate=candidate,
            method=method,
            method_created=method_created,
            variant_created=variant_created,
        )

    def _crawl_success_result(
        self,
        parsed: ParsedDocument,
        extraction: ExtractionToolResult,
    ) -> dict[str, object]:
        result = parsed.fetch_result
        document = parsed.document
        observation = RuntimeObservation.success(
            artifact_ids=[str(document.id)],
            metrics={
                "http_status": result.status_code,
                "candidates": extraction.candidate_count,
                "methods": extraction.method_count,
                "variants": extraction.variant_count,
            },
            payload={
                "hook": "crawl_url",
                "url": parsed.requested_url,
                "final_url": result.url,
                "content_type": result.content_type,
                "text_chars": len(parsed.text.strip()),
                "document_id": str(document.id),
                "extraction_run_id": str(extraction.extraction_run.id),
            },
        )
        return {
            "url": result.url,
            "http_status": result.status_code,
            "document_id": str(document.id),
            "status": "succeeded",
            "runtime_status": observation.status.value,
            "artifact_ids": observation.artifact_ids,
            "metrics": observation.metrics,
            "warnings": observation.warnings,
            "error": observation.error,
            "retryable": observation.retryable,
            "requires_review": observation.requires_review,
            "review_reason": observation.review_reason,
            "payload": observation.payload,
            "candidates": extraction.candidate_count,
            "methods": extraction.method_count,
            "variants": extraction.variant_count,
        }

    def _after_fetch_check(
        self,
        *,
        requested_url: str,
        result,
        document: SourceDocument,
        text: str,
        text_path: Path,
    ) -> dict[str, object] | None:
        payload = {
            "hook": "after_fetch",
            "url": requested_url,
            "final_url": result.url,
            "content_type": result.content_type,
            "raw_path": str(result.raw_path),
            "text_path": str(text_path),
            "text_chars": len(text.strip()),
            "document_id": str(document.id),
        }
        if result.needs_login:
            document.status = CrawlStatus.blocked
            reason = "页面需要登录或访问受限，需要人工复核。"
            observation = FetchObservation(
                status=RuntimeStatus.blocked,
                artifact_ids=[str(document.id)],
                error=None,
                retryable=False,
                requires_review=True,
                review_reason=reason,
                payload=payload,
                url=requested_url,
                final_url=result.url,
                http_status=result.status_code,
                content_type=result.content_type,
                raw_path=str(result.raw_path),
                text_path=str(text_path),
                needs_login=True,
            )
            return self._fetch_stop_result(
                observation=observation,
                document=document,
                legacy_status="blocked_login",
                legacy_error=reason,
            )
        if result.status_code >= 400:
            document.status = CrawlStatus.failed
            retryable = result.status_code == 429 or result.status_code >= 500
            error = f"HTTP {result.status_code}，没有可用于抽取的正文。"
            observation = FetchObservation(
                status=RuntimeStatus.failed,
                artifact_ids=[str(document.id)],
                error=error,
                retryable=retryable,
                payload=payload,
                url=requested_url,
                final_url=result.url,
                http_status=result.status_code,
                content_type=result.content_type,
                raw_path=str(result.raw_path),
                text_path=str(text_path),
                needs_login=False,
            )
            return self._fetch_stop_result(
                observation=observation,
                document=document,
                legacy_status="fetch_failed",
                legacy_error=error,
            )
        unsupported_reason = self._unsupported_content_reason(result.url, result.content_type)
        if unsupported_reason is not None:
            document.status = CrawlStatus.failed
            observation = FetchObservation(
                status=RuntimeStatus.failed,
                artifact_ids=[str(document.id)],
                error=unsupported_reason,
                retryable=False,
                warnings=[unsupported_reason],
                payload=payload,
                url=requested_url,
                final_url=result.url,
                http_status=result.status_code,
                content_type=result.content_type,
                raw_path=str(result.raw_path),
                text_path=str(text_path),
                needs_login=False,
            )
            return self._fetch_stop_result(
                observation=observation,
                document=document,
                legacy_status="fetch_failed",
                legacy_error=unsupported_reason,
            )
        text_reason = self._low_value_text_reason(text)
        if text_reason is not None:
            document.status = CrawlStatus.failed
            observation = FetchObservation(
                status=RuntimeStatus.failed,
                artifact_ids=[str(document.id)],
                error=text_reason,
                retryable=False,
                warnings=[text_reason],
                payload=payload,
                url=requested_url,
                final_url=result.url,
                http_status=result.status_code,
                content_type=result.content_type,
                raw_path=str(result.raw_path),
                text_path=str(text_path),
                needs_login=False,
            )
            return self._fetch_stop_result(
                observation=observation,
                document=document,
                legacy_status="fetch_failed",
                legacy_error=text_reason,
            )
        return None

    def _fetch_stop_result(
        self,
        *,
        observation: FetchObservation,
        document: SourceDocument,
        legacy_status: str,
        legacy_error: str,
    ) -> dict[str, object]:
        return {
            "url": observation.final_url or observation.url,
            "http_status": observation.http_status,
            "document_id": str(document.id),
            "status": legacy_status,
            "runtime_status": observation.status.value,
            "artifact_ids": observation.artifact_ids,
            "metrics": observation.metrics,
            "warnings": observation.warnings,
            "error": legacy_error,
            "retryable": observation.retryable,
            "requires_review": observation.requires_review,
            "review_reason": observation.review_reason,
            "payload": observation.payload,
            "content_type": observation.content_type,
            "candidates": 0,
            "methods": 0,
            "variants": 0,
        }

    def _unsupported_content_reason(
        self,
        url: str,
        content_type: str | None,
    ) -> str | None:
        parsed_content_type = (content_type or "").split(";", 1)[0].strip().lower()
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix in SUPPORTED_URL_SUFFIXES:
            return None
        if not parsed_content_type:
            return None
        if parsed_content_type.startswith(UNSUPPORTED_CONTENT_TYPE_PREFIXES):
            return f"不支持抽取该内容类型：{parsed_content_type}。"
        if parsed_content_type in UNSUPPORTED_CONTENT_TYPES:
            return f"不支持抽取该内容类型：{parsed_content_type}。"
        if any(marker in parsed_content_type for marker in SUPPORTED_CONTENT_MARKERS):
            return None
        return f"不支持抽取该内容类型：{parsed_content_type}。"

    def _low_value_text_reason(self, text: str) -> str | None:
        compact_text = " ".join(text.split())
        if len(compact_text) < EMPTY_TEXT_MIN_CHARS:
            return "页面正文过短，没有可用于抽取的内容。"
        lowered = compact_text.lower()
        if len(compact_text) <= BOILERPLATE_TEXT_MAX_CHARS and any(
            marker in lowered or marker in compact_text for marker in BOILERPLATE_MARKERS
        ):
            return "页面正文疑似为空壳或错误提示，没有可用于抽取的内容。"
        return None

    def _extractor_metadata(self) -> tuple[str, str, str | None]:
        if self._should_use_ai():
            return ("AIMethodExtractor", "v1", self.settings.openai_compatible_model)
        return ("RuleBasedMethodExtractor", "v0", None)

    def _extract_candidates(
        self,
        text: str,
        document_url: str,
    ) -> tuple[list[CandidateKnowledgeItemSchema], str | None]:
        if self._should_use_ai():
            try:
                return AIMethodExtractor(settings=self.settings).extract(text, document_url), None
            except Exception as exc:
                if self.extractor_mode in {"deepseek", "ai"}:
                    raise
                rule_result = RuleBasedMethodExtractor().extract(text, document_url=document_url)
                return (
                    rule_result.candidates,
                    f"AI 抽取失败，已回退到规则抽取器：{exc}",
                )

        rule_result = RuleBasedMethodExtractor().extract(text, document_url=document_url)
        return rule_result.candidates, None

    def _should_use_ai(self) -> bool:
        if self.extractor_mode in {"rule", "rules"}:
            return False
        if self.extractor_mode in {"deepseek", "ai"}:
            return True
        ai_provider_enabled = self.settings.ai_provider.lower() in {
            "deepseek",
            "openai-compatible",
            "ai",
        }
        return ai_provider_enabled and bool(self.settings.ai_api_key)

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

    def _parse_fetch_result(self, raw_path: Path, content_type: str | None) -> str:
        content_type = (content_type or "").lower()
        if "pdf" in content_type or raw_path.suffix.lower() == ".pdf":
            return pdf_to_text(raw_path)
        raw_bytes = raw_path.read_bytes()
        html = raw_bytes.decode("utf-8", errors="ignore")
        if "html" in content_type or raw_path.suffix.lower() in {".html", ".htm"}:
            return html_to_text(html)
        return html

    def _write_text(self, checksum: str, text: str) -> Path:
        text_path = self.fetcher.settings.text_storage_dir / f"{checksum}.txt"
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
        document.fetched_at = datetime.utcnow()
        self.session.flush()
        return document

    def _create_evidence(self, document: SourceDocument, snippet: str) -> EvidenceSnippet:
        evidence = EvidenceSnippet(
            document_id=document.id,
            text=snippet,
            confidence=0.55,
        )
        self.session.add(evidence)
        self.session.flush()
        return evidence

    def _upsert_method_from_candidate(
        self,
        candidate: CandidateKnowledgeItem,
        evidence_id,
    ) -> tuple[TeachingMethod, bool]:
        semantic_key = candidate.semantic_key or normalize_semantic_key(candidate.title)
        method = self.session.scalar(
            select(TeachingMethod).where(TeachingMethod.semantic_key == semantic_key)
        )
        if method is not None:
            method.source_count += 1
            method.last_seen_at = datetime.utcnow()
            return method, False

        payload = candidate.payload or {}
        method = TeachingMethod(
            title=candidate.title,
            semantic_key=semantic_key,
            method_type=payload.get("method_type", "解题技巧"),
            canonical_scope="knowledge_point",
            summary=payload.get("summary", candidate.title),
            steps=payload.get("steps", []),
            applicable_patterns=payload.get("applicable_patterns", []),
            prerequisites=payload.get("prerequisites", []),
            common_misconceptions=payload.get("common_misconceptions", []),
            aliases=[],
            evidence_id=evidence_id,
            confidence=candidate.confidence,
            source_count=1,
            last_seen_at=datetime.utcnow(),
            review_status=ReviewStatus.pending,
        )
        self.session.add(method)
        self.session.flush()
        return method, True

    def _create_variant_from_candidate(
        self,
        method: TeachingMethod,
        document: SourceDocument,
        evidence: EvidenceSnippet,
        candidate: CandidateKnowledgeItem,
    ) -> bool:
        payload = candidate.payload or {}
        existing = self.session.scalar(
            select(TeachingMethodVariant).where(
                TeachingMethodVariant.method_id == method.id,
                TeachingMethodVariant.source_document_id == document.id,
                TeachingMethodVariant.summary == payload.get("summary", candidate.title),
            )
        )
        if existing is not None:
            return False
        variant = TeachingMethodVariant(
            method_id=method.id,
            title=candidate.title,
            source_teacher=payload.get("source_teacher"),
            source_org=payload.get("source_org"),
            source_region=payload.get("source_region"),
            explanation_style=payload.get("explanation_style"),
            summary=payload.get("summary", candidate.title),
            steps=payload.get("steps", []),
            applicable_patterns=payload.get("applicable_patterns", []),
            classroom_warnings=payload.get("classroom_warnings", []),
            example_patterns=payload.get("example_patterns", []),
            source_document_id=document.id,
            evidence_id=evidence.id,
            confidence=candidate.confidence,
            review_status=ReviewStatus.pending,
        )
        self.session.add(variant)
        self.session.flush()
        self._link_method_to_best_section(method, candidate)
        return True

    def _link_method_to_best_section(
        self,
        method: TeachingMethod,
        candidate: CandidateKnowledgeItem,
    ) -> None:
        payload = candidate.payload or {}
        text = f"{candidate.title} {payload.get('summary', '')}"
        points = self.session.scalars(select(KnowledgePoint)).all()
        best_point = None
        for point in points:
            if len(point.title) >= 3 and point.title in text:
                best_point = point
                break
        if best_point is None:
            return

        existing_point_link = self.session.scalar(
            select(MethodKnowledgePointLink).where(
                MethodKnowledgePointLink.method_id == method.id,
                MethodKnowledgePointLink.knowledge_point_id == best_point.id,
                MethodKnowledgePointLink.relation_type == "primary",
            )
        )
        if existing_point_link is None:
            self.session.add(
                MethodKnowledgePointLink(
                    method_id=method.id,
                    knowledge_point_id=best_point.id,
                    relation_type="primary",
                    confidence=0.55,
                )
            )

        section = self.session.get(Section, best_point.section_id)
        if section is None:
            return
        existing_section_link = self.session.scalar(
            select(MethodSectionLink).where(
                MethodSectionLink.method_id == method.id,
                MethodSectionLink.section_id == section.id,
                MethodSectionLink.relation_type == "inferred_from_knowledge_point",
            )
        )
        if existing_section_link is None:
            self.session.add(
                MethodSectionLink(
                    method_id=method.id,
                    section_id=section.id,
                    relation_type="inferred_from_knowledge_point",
                    confidence=0.55,
                )
            )

    def _record_reconciliation_decision(
        self,
        candidate: CandidateKnowledgeItem,
        method: TeachingMethod,
        action: ReconciliationAction,
    ) -> None:
        decision = ReconciliationDecision(
            candidate_id=candidate.id,
            action=action,
            matched_table="teaching_methods",
            matched_id=method.id,
            matched_ids=[str(method.id)],
            rationale="第一版规则调和：根据语义键判断教学方法候选项的创建、变体或跳过。",
            proposed_patch={
                "method_id": str(method.id),
                "candidate_id": str(candidate.id),
                "action": action.value,
            },
            confidence=candidate.confidence,
            auto_applied=True,
            review_status=ReviewStatus.pending,
        )
        self.session.add(decision)
