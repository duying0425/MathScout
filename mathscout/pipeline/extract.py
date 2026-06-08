from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from mathscout.config import get_settings
from mathscout.db.models import (
    Book,
    CandidateItemType,
    CandidateKnowledgeItem,
    Chapter,
    CrawlStatus,
    EvidenceSnippet,
    ExtractionRun,
    KnowledgePoint,
    MethodKnowledgePointLink,
    MethodSectionLink,
    PipelineStatus,
    ReconciliationAction,
    ReconciliationDecision,
    ReviewStatus,
    Section,
    SourceDocument,
    TeachingMethod,
    TeachingMethodVariant,
)
from mathscout.extraction.ai_method_extractor import AIMethodExtractor
from mathscout.extraction.rule_based import RuleBasedMethodExtractor
from mathscout.extraction.schemas import CandidateKnowledgeItemSchema
from mathscout.utils.text import normalize_semantic_key


class ExtractPipeline:
    """Phase 2: 从本地文本文件提取候选知识点，写入 DB，更新 pipeline_status='extracted'。

    可对任意 pipeline_status='crawled' 的文档独立运行，不需要重新抓取网络。
    改 Prompt 或换模型后，把目标文档 pipeline_status 改回 'crawled'，重跑此 pipeline 即可。
    """

    def __init__(self, session: Session, extractor_mode: str = "auto") -> None:
        self.session = session
        self.settings = get_settings()
        self.extractor_mode = extractor_mode

    # ------------------------------------------------------------------ #
    # 公共接口                                                              #
    # ------------------------------------------------------------------ #

    def extract_pending(self, limit: int = 100) -> dict[str, int]:
        """批量处理所有 pipeline_status='crawled' 的文档。"""
        docs = self.session.scalars(
            select(SourceDocument)
            .where(SourceDocument.pipeline_status == PipelineStatus.crawled)
            .limit(limit)
        ).all()

        processed = candidates = methods = variants = errors = 0
        for doc in docs:
            try:
                result = self.extract_document(doc)
                processed += 1
                candidates += result["candidates"]
                methods += result["methods"]
                variants += result["variants"]
            except Exception as exc:
                errors += 1
                doc.pipeline_status = PipelineStatus.failed
                doc.pipeline_error = str(exc)
                self.session.commit()
        return {
            "processed": processed,
            "candidates": candidates,
            "methods": methods,
            "variants": variants,
            "errors": errors,
        }

    def extract_by_document_id(self, document_id: str) -> dict[str, object]:
        """对单个文档 ID 运行提取。"""
        doc = self.session.get(SourceDocument, uuid.UUID(document_id))
        if doc is None:
            raise ValueError(f"找不到文档: {document_id}")
        return self.extract_document(doc)

    def extract_document(self, document: SourceDocument) -> dict[str, object]:
        """对单个 SourceDocument 运行 AI/规则提取 + reconciliation。"""
        if document.needs_login:
            return {"document_id": str(document.id), "candidates": 0, "methods": 0, "variants": 0}

        text = self._read_text(document)
        if not text.strip():
            document.pipeline_status = PipelineStatus.failed
            document.pipeline_error = "text_path 为空，无法提取"
            self.session.commit()
            return {"document_id": str(document.id), "candidates": 0, "methods": 0, "variants": 0}

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

        candidates_list, extraction_error = self._run_extractors(text, document.url or "")
        created_candidates = created_methods = created_variants = 0

        for candidate_schema in candidates_list:
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

            method, method_created = self._upsert_method(candidate, evidence.id)
            if method_created:
                created_methods += 1
            variant_created = self._upsert_variant(method, document, evidence, candidate)
            if variant_created:
                created_variants += 1
            self._record_reconciliation(candidate, method, method_created, variant_created)

        extraction_run.output_json = {
            "candidate_count": created_candidates,
            "method_count": created_methods,
            "variant_count": created_variants,
            "extractor_mode": self.extractor_mode,
            "error": extraction_error,
        }
        document.pipeline_status = PipelineStatus.extracted
        document.pipeline_error = extraction_error
        self.session.commit()
        return {
            "document_id": str(document.id),
            "candidates": created_candidates,
            "methods": created_methods,
            "variants": created_variants,
        }

    # ------------------------------------------------------------------ #
    # 内部方法                                                              #
    # ------------------------------------------------------------------ #

    def _read_text(self, document: SourceDocument) -> str:
        if not document.text_path:
            return ""
        from pathlib import Path
        path = Path(document.text_path)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def _extractor_metadata(self) -> tuple[str, str, str | None]:
        if self._use_ai():
            return ("AIMethodExtractor", "v1", self.settings.openai_compatible_model)
        return ("RuleBasedMethodExtractor", "v0", None)

    def _use_ai(self) -> bool:
        if self.extractor_mode in {"rule", "rules"}:
            return False
        if self.extractor_mode in {"deepseek", "ai"}:
            return True
        return self.settings.ai_provider.lower() in {"deepseek", "openai-compatible", "ai"} and bool(
            self.settings.ai_api_key
        )

    def _run_extractors(
        self, text: str, document_url: str
    ) -> tuple[list[CandidateKnowledgeItemSchema], str | None]:
        if self._use_ai():
            try:
                return AIMethodExtractor(settings=self.settings).extract(text, document_url), None
            except Exception as exc:
                if self.extractor_mode in {"deepseek", "ai"}:
                    raise
                rule_result = RuleBasedMethodExtractor().extract(text, document_url=document_url)
                return rule_result.candidates, f"AI 抽取失败，已回退到规则抽取器：{exc}"
        rule_result = RuleBasedMethodExtractor().extract(text, document_url=document_url)
        return rule_result.candidates, None

    def _create_evidence(self, document: SourceDocument, snippet: str) -> EvidenceSnippet:
        evidence = EvidenceSnippet(
            document_id=document.id,
            text=snippet,
            confidence=self.settings.evidence_default_confidence,
        )
        self.session.add(evidence)
        self.session.flush()
        return evidence

    def _upsert_method(
        self, candidate: CandidateKnowledgeItem, evidence_id: uuid.UUID
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

    def _upsert_variant(
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
        self._link_method_to_section(method, candidate)
        return True

    def _link_method_to_section(
        self, method: TeachingMethod, candidate: CandidateKnowledgeItem
    ) -> None:
        """把方法映射到教材小节与知识点。

        优先用候选自身抽取出的 book_code/chapter_title/section_title 精确定位小节
        （高置信度）；定位不到时再退回"知识点标题子串匹配"的兜底逻辑（低置信度，
        且最多链接前若干个，而非只取第一个）。
        """
        section = self._find_section_for_candidate(candidate)
        if section is not None:
            self._link_section(method, section, "matched_from_candidate_fields")
            self._link_knowledge_points_in_section(method, candidate, section)
            return
        self._link_by_text_match(method, candidate)

    def _find_section_for_candidate(self, candidate: CandidateKnowledgeItem) -> Section | None:
        section_title = (candidate.section_title or "").strip()
        if not section_title:
            return None
        stmt = (
            select(Section)
            .join(Chapter, Section.chapter_id == Chapter.id)
            .join(Book, Chapter.book_id == Book.id)
        )
        book_code = (candidate.book_code or "").strip()
        if book_code:
            stmt = stmt.where(Book.book_code == book_code)
        chapter_title = (candidate.chapter_title or "").strip()
        if chapter_title:
            stmt = stmt.where(Chapter.title == chapter_title)
        exact = self.session.scalar(stmt.where(Section.title == section_title))
        if exact is not None:
            return exact
        return self.session.scalar(stmt.where(Section.title.contains(section_title)))

    def _link_knowledge_points_in_section(
        self, method: TeachingMethod, candidate: CandidateKnowledgeItem, section: Section
    ) -> None:
        payload = candidate.payload or {}
        raw_titles = payload.get("knowledge_point_titles") or []
        titles = {t.strip() for t in raw_titles if t and t.strip()}
        if not titles:
            return
        for point in self.session.scalars(
            select(KnowledgePoint).where(KnowledgePoint.section_id == section.id)
        ).all():
            if point.title in titles:
                self._link_knowledge_point(
                    method, point, self.settings.extraction_match_confidence
                )

    def _link_by_text_match(
        self, method: TeachingMethod, candidate: CandidateKnowledgeItem
    ) -> None:
        payload = candidate.payload or {}
        text = f"{candidate.title} {payload.get('summary', '')}"
        linked = 0
        for point in self.session.scalars(select(KnowledgePoint)).all():
            if len(point.title) >= 3 and point.title in text:
                self._link_knowledge_point(
                    method, point, self.settings.evidence_default_confidence
                )
                section = self.session.get(Section, point.section_id)
                if section is not None:
                    self._link_section(method, section, "inferred_from_knowledge_point")
                linked += 1
                if linked >= 3:
                    break

    def _link_knowledge_point(
        self, method: TeachingMethod, point: KnowledgePoint, confidence: float
    ) -> None:
        if self.session.scalar(
            select(MethodKnowledgePointLink).where(
                MethodKnowledgePointLink.method_id == method.id,
                MethodKnowledgePointLink.knowledge_point_id == point.id,
            )
        ):
            return
        self.session.add(
            MethodKnowledgePointLink(
                method_id=method.id,
                knowledge_point_id=point.id,
                relation_type="primary",
                confidence=confidence,
            )
        )

    def _link_section(self, method: TeachingMethod, section: Section, relation: str) -> None:
        confidence = (
            self.settings.extraction_match_confidence
            if relation == "matched_from_candidate_fields"
            else self.settings.evidence_default_confidence
        )
        if self.session.scalar(
            select(MethodSectionLink).where(
                MethodSectionLink.method_id == method.id,
                MethodSectionLink.section_id == section.id,
            )
        ):
            return
        self.session.add(
            MethodSectionLink(
                method_id=method.id,
                section_id=section.id,
                relation_type=relation,
                confidence=confidence,
            )
        )

    def _record_reconciliation(
        self,
        candidate: CandidateKnowledgeItem,
        method: TeachingMethod,
        method_created: bool,
        variant_created: bool,
    ) -> None:
        action = (
            ReconciliationAction.create
            if method_created
            else ReconciliationAction.create_variant
            if variant_created
            else ReconciliationAction.skip
        )
        self.session.add(
            ReconciliationDecision(
                candidate_id=candidate.id,
                action=action,
                matched_table="teaching_methods",
                matched_id=method.id,
                matched_ids=[str(method.id)],
                rationale="Phase 2 规则调和：根据语义键判断教学方法的创建、变体或跳过。",
                proposed_patch={
                    "method_id": str(method.id),
                    "candidate_id": str(candidate.id),
                    "action": action.value,
                },
                confidence=candidate.confidence,
                auto_applied=True,
                review_status=ReviewStatus.pending,
            )
        )
