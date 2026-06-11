from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from mathscout.config import Settings, get_settings
from mathscout.db.models import (
    Book,
    CandidateItemType,
    CandidateKnowledgeItem,
    Chapter,
    EvidenceSnippet,
    KnowledgePoint,
    ReconciliationAction,
    ReconciliationDecision,
    ReviewStatus,
    Section,
    SectionKnowledgePointLink,
    SourceDocument,
)
from mathscout.extraction.schemas import ExtractedKnowledgePoint
from mathscout.utils.text import normalize_semantic_key


class KnowledgePointReconciler:
    """Phase 知识点：把抽取出的知识点（`ExtractedKnowledgePoint`）调和进 canonical。

    复用既有"候选 → reconciliation → canonical"三段式，并与教材导入共用 canonical 化口径：
    - 知识点按【内容（标题归一化）】去重——同一知识点跨版本/来源只存一条（与导入一致）。
    - 抽取出的知识点 `source_type='extracted'`、`review_status=pending`，等待人工复核。
    - 能从教材线索（册/章/节）定位到小节时，建 `section_knowledge_point_links`（覆盖）。
    """

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    def ingest(
        self, points: list[ExtractedKnowledgePoint], document: SourceDocument
    ) -> dict[str, int]:
        stats = {
            "candidates": 0,
            "knowledge_points": 0,
            "section_links": 0,
            "skipped": 0,
        }
        for extracted in points:
            evidence = self._create_evidence(document, extracted)
            candidate = self._create_candidate(document, extracted, evidence)
            stats["candidates"] += 1

            point, created = self._upsert_knowledge_point(extracted, evidence)
            if created:
                stats["knowledge_points"] += 1
            else:
                stats["skipped"] += 1
            stats["section_links"] += self._link_section(point, extracted, evidence)
            self._record_reconciliation(candidate, point, created)

        self.session.commit()
        return stats

    # ------------------------------------------------------------------ #

    def _create_evidence(
        self, document: SourceDocument, extracted: ExtractedKnowledgePoint
    ) -> EvidenceSnippet:
        snippet = extracted.evidence[0].snippet if extracted.evidence else None
        evidence = EvidenceSnippet(
            document_id=document.id,
            text=snippet or (extracted.description or extracted.title)[:500],
            confidence=self.settings.evidence_default_confidence,
        )
        self.session.add(evidence)
        self.session.flush()
        return evidence

    def _create_candidate(
        self,
        document: SourceDocument,
        extracted: ExtractedKnowledgePoint,
        evidence: EvidenceSnippet,
    ) -> CandidateKnowledgeItem:
        candidate = CandidateKnowledgeItem(
            document_id=document.id,
            item_type=CandidateItemType.knowledge_point,
            title=extracted.title[:300],
            semantic_key=normalize_semantic_key(extracted.title),
            textbook_series=extracted.textbook_series,
            book_code=extracted.book_code,
            chapter_title=extracted.chapter_title,
            section_title=extracted.section_title,
            payload=extracted.model_dump(),
            evidence_ids=[str(evidence.id)],
            confidence=extracted.confidence,
            review_status=ReviewStatus.pending,
        )
        self.session.add(candidate)
        self.session.flush()
        return candidate

    def _upsert_knowledge_point(
        self, extracted: ExtractedKnowledgePoint, evidence: EvidenceSnippet
    ) -> tuple[KnowledgePoint, bool]:
        key = normalize_semantic_key(extracted.title)
        point = self.session.scalar(
            select(KnowledgePoint).where(KnowledgePoint.semantic_key == key)
        )
        if point is not None:
            point.source_count += 1
            point.last_seen_at = datetime.utcnow()
            if not point.description and extracted.description:
                point.description = extracted.description
            return point, False

        point = KnowledgePoint(
            title=extracted.title,
            description=extracted.description,
            semantic_key=key,
            source_type="extracted",
            evidence_id=evidence.id,
            confidence=extracted.confidence,
            source_count=1,
            last_seen_at=datetime.utcnow(),
            review_status=ReviewStatus.pending,
        )
        self.session.add(point)
        self.session.flush()
        return point, True

    def _link_section(
        self,
        point: KnowledgePoint,
        extracted: ExtractedKnowledgePoint,
        evidence: EvidenceSnippet,
    ) -> int:
        section = self._find_section(
            extracted.book_code, extracted.chapter_title, extracted.section_title
        )
        if section is None:
            return 0
        exists = self.session.scalar(
            select(SectionKnowledgePointLink).where(
                SectionKnowledgePointLink.section_id == section.id,
                SectionKnowledgePointLink.knowledge_point_id == point.id,
                SectionKnowledgePointLink.relation_type == "introduce",
            )
        )
        if exists is not None:
            return 0
        self.session.add(
            SectionKnowledgePointLink(
                section_id=section.id,
                knowledge_point_id=point.id,
                relation_type="introduce",
                confidence=self.settings.extraction_match_confidence,
                evidence_id=evidence.id,
            )
        )
        self.session.flush()
        return 1

    def _find_section(
        self, book_code: str | None, chapter_title: str | None, section_title: str | None
    ) -> Section | None:
        title = (section_title or "").strip()
        if not title:
            return None
        stmt = (
            select(Section)
            .join(Chapter, Section.chapter_id == Chapter.id)
            .join(Book, Chapter.book_id == Book.id)
        )
        if (book_code or "").strip():
            stmt = stmt.where(Book.book_code == book_code.strip())
        if (chapter_title or "").strip():
            stmt = stmt.where(Chapter.title == chapter_title.strip())
        exact = self.session.scalar(stmt.where(Section.title == title))
        if exact is not None:
            return exact
        return self.session.scalar(stmt.where(Section.title.contains(title)))

    def _record_reconciliation(
        self, candidate: CandidateKnowledgeItem, point: KnowledgePoint, created: bool
    ) -> None:
        action = ReconciliationAction.create if created else ReconciliationAction.skip
        self.session.add(
            ReconciliationDecision(
                candidate_id=candidate.id,
                action=action,
                matched_table="knowledge_points",
                matched_id=point.id,
                matched_ids=[str(point.id)],
                rationale="知识点调和：按内容语义键判断创建或跳过；命中教材线索时建小节覆盖链接。",
                proposed_patch={
                    "knowledge_point_id": str(point.id),
                    "candidate_id": str(candidate.id),
                    "action": action.value,
                },
                confidence=candidate.confidence,
                auto_applied=True,
                review_status=ReviewStatus.pending,
            )
        )
        self.session.flush()


def _use_ai(extractor_mode: str, settings: Settings) -> bool:
    if extractor_mode in {"rule", "rules"}:
        return False
    if extractor_mode in {"deepseek", "ai"}:
        return True
    return settings.ai_provider.lower() in {"deepseek", "openai-compatible", "ai"} and bool(
        settings.ai_api_key
    )


def extract_and_reconcile_knowledge_points(
    session: Session,
    document: SourceDocument,
    text: str,
    settings: Settings | None = None,
    extractor_mode: str = "auto",
) -> dict[str, int]:
    """便捷入口：AI 知识点抽取 + 调和——清洗文本 → canonical 知识点 + 小节覆盖链接。

    知识点抽取目前只有 AI 版（规则版对知识点意义不大）；未配置 AI 时抛出明确错误。
    """
    settings = settings or get_settings()
    if not _use_ai(extractor_mode, settings):
        raise ValueError("知识点抽取需要配置 AI（DEEPSEEK_API_KEY / OPENAI_COMPATIBLE_API_KEY）。")
    from mathscout.extraction.ai_knowledge_extractor import AIKnowledgeExtractor

    points = AIKnowledgeExtractor(settings=settings).extract(text, document.url)
    return KnowledgePointReconciler(session, settings).ingest(points, document)
