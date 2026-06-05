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
from mathscout.utils.text import normalize_semantic_key


class CrawlPipeline:
    def __init__(self, session: Session, extractor_mode: str = "auto") -> None:
        self.session = session
        self.settings = get_settings()
        self.fetcher = HttpFetcher()
        self.extractor_mode = extractor_mode

    def crawl_url(self, url: str) -> dict[str, int | str | bool]:
        result = asyncio.run(self.fetcher.fetch(url))
        site = self._get_or_create_site(result.url)
        text = self._parse_fetch_result(result.raw_path, result.content_type)
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
        )
        if result.status_code >= 400 and not result.needs_login:
            document.status = CrawlStatus.failed
            self.session.commit()
            return {
                "url": result.url,
                "http_status": result.status_code,
                "document_id": str(document.id),
                "status": "fetch_failed",
                "error": f"HTTP {result.status_code}，没有可用于抽取的正文。",
                "retryable": result.status_code == 429 or result.status_code >= 500,
                "candidates": 0,
                "methods": 0,
                "variants": 0,
            }
        if result.needs_login:
            self.session.commit()
            return {
                "url": result.url,
                "http_status": result.status_code,
                "document_id": str(document.id),
                "status": "blocked_login",
                "candidates": 0,
                "methods": 0,
                "variants": 0,
            }

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

        candidates, extraction_error = self._extract_candidates(text, result.url)
        created_candidates = 0
        created_methods = 0
        created_variants = 0
        for candidate_schema in candidates:
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
            created_candidates += 1

            method, method_created = self._upsert_method_from_candidate(candidate, evidence.id)
            if method_created:
                created_methods += 1
            variant_created = self._create_variant_from_candidate(
                method=method,
                document=document,
                evidence=evidence,
                candidate=candidate,
            )
            if variant_created:
                created_variants += 1
            self._record_reconciliation_decision(
                candidate=candidate,
                method=method,
                action=ReconciliationAction.create
                if method_created
                else ReconciliationAction.create_variant
                if variant_created
                else ReconciliationAction.skip,
            )

        extraction_run.output_json = {
            "candidate_count": created_candidates,
            "method_count": created_methods,
            "variant_count": created_variants,
            "extractor_mode": self.extractor_mode,
            "error": extraction_error,
        }
        self.session.commit()
        return {
            "url": result.url,
            "http_status": result.status_code,
            "document_id": str(document.id),
            "status": "succeeded",
            "candidates": created_candidates,
            "methods": created_methods,
            "variants": created_variants,
        }

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
