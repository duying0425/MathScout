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
    Figure,
    KnowledgePoint,
    Problem,
    ProblemSectionLink,
    ReconciliationAction,
    ReconciliationDecision,
    ReviewItem,
    ReviewStatus,
    Section,
    Solution,
    SolutionTechniqueLink,
    SourceDocument,
    TeachingMethod,
)
from mathscout.extraction.problem_rule_based import RuleBasedProblemExtractor
from mathscout.extraction.schemas import ExtractedFigure, ExtractedProblem, ExtractedSolution
from mathscout.utils.text import normalize_semantic_key


class ProblemReconciler:
    """Phase C：把抽取出的题目/解答（`ExtractedProblem`）调和进 canonical 事实层。

    复用既有"候选 → reconciliation → canonical"三段式：
    - 题目/解答/配图：自动建 canonical（按内容去重；复核状态 pending），与教学方法管线一致。
    - 题目↔小节（弱关联）：能从教材线索定位到小节就建软链接。
    - 解答↔技巧（用到）：只链接到**已有** canonical 技巧（按语义键匹配），匹配不到不新建，
      避免一题一技巧污染技巧库。
    - 题目↔知识点（考察）：**不自动写链接**，改为生成一条 ReviewItem 请人工确认
      （AI 的考察标注置信度低）。
    """

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    def ingest(
        self, problems: list[ExtractedProblem], document: SourceDocument
    ) -> dict[str, int]:
        stats = {
            "candidates": 0,
            "problems": 0,
            "solutions": 0,
            "figures": 0,
            "section_links": 0,
            "technique_links": 0,
            "kp_reviews": 0,
        }
        for extracted in problems:
            evidence = self._create_evidence(document, extracted)
            candidate = self._create_candidate(document, extracted, evidence)
            stats["candidates"] += 1

            problem, created = self._upsert_problem(extracted, document, evidence)
            if created:
                stats["problems"] += 1
            stats["figures"] += self._attach_figures(extracted.figures, "problem", problem.id)

            for extracted_solution in extracted.solutions:
                solution, solution_created = self._upsert_solution(
                    problem, extracted_solution, document, evidence
                )
                if solution_created:
                    stats["solutions"] += 1
                stats["figures"] += self._attach_figures(
                    extracted_solution.figures, "solution", solution.id
                )
                stats["technique_links"] += self._link_solution_techniques(
                    solution, extracted_solution
                )

            stats["section_links"] += self._link_problem_section(problem, extracted)
            stats["kp_reviews"] += self._queue_knowledge_point_review(problem, extracted)
            self._record_reconciliation(candidate, problem, created)

        self.session.commit()
        return stats

    # ------------------------------------------------------------------ #
    # 候选与证据                                                            #
    # ------------------------------------------------------------------ #

    def _create_evidence(
        self, document: SourceDocument, extracted: ExtractedProblem
    ) -> EvidenceSnippet:
        snippet = extracted.evidence[0].snippet if extracted.evidence else None
        evidence = EvidenceSnippet(
            document_id=document.id,
            text=snippet or extracted.stem[:500],
            confidence=self.settings.evidence_default_confidence,
        )
        self.session.add(evidence)
        self.session.flush()
        return evidence

    def _create_candidate(
        self,
        document: SourceDocument,
        extracted: ExtractedProblem,
        evidence: EvidenceSnippet,
    ) -> CandidateKnowledgeItem:
        candidate = CandidateKnowledgeItem(
            document_id=document.id,
            item_type=CandidateItemType.problem,
            title=extracted.stem[:300],
            semantic_key=self._problem_key(extracted),
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

    # ------------------------------------------------------------------ #
    # canonical 题目 / 解答                                                 #
    # ------------------------------------------------------------------ #

    def _problem_key(self, extracted: ExtractedProblem) -> str:
        return extracted.semantic_key or normalize_semantic_key(extracted.stem)

    def _upsert_problem(
        self,
        extracted: ExtractedProblem,
        document: SourceDocument,
        evidence: EvidenceSnippet,
    ) -> tuple[Problem, bool]:
        key = self._problem_key(extracted)
        problem = self.session.scalar(select(Problem).where(Problem.semantic_key == key))
        if problem is not None:
            problem.source_count += 1
            problem.last_seen_at = datetime.utcnow()
            if extracted.has_answer and not problem.has_answer:
                problem.has_answer = True
            return problem, False

        problem = Problem(
            stem=extracted.stem,
            problem_type=extracted.problem_type,
            difficulty=extracted.difficulty,
            source_type=extracted.source_type,
            source_document_id=document.id,
            has_answer=extracted.has_answer,
            semantic_key=key,
            evidence_id=evidence.id,
            confidence=extracted.confidence,
            source_count=1,
            last_seen_at=datetime.utcnow(),
            review_status=ReviewStatus.pending,
        )
        self.session.add(problem)
        self.session.flush()
        return problem, True

    def _upsert_solution(
        self,
        problem: Problem,
        extracted: ExtractedSolution,
        document: SourceDocument,
        evidence: EvidenceSnippet,
    ) -> tuple[Solution, bool]:
        for existing in self.session.scalars(
            select(Solution).where(Solution.problem_id == problem.id)
        ).all():
            if self._same_solution(existing, extracted):
                return existing, False

        solution = Solution(
            problem_id=problem.id,
            approach_label=extracted.approach_label,
            steps=extracted.steps,
            final_answer=extracted.final_answer,
            complexity=extracted.complexity,
            source_teacher=extracted.source_teacher,
            source_org=extracted.source_org,
            source_region=extracted.source_region,
            source_document_id=document.id,
            evidence_id=evidence.id,
            confidence=extracted.confidence,
            review_status=ReviewStatus.pending,
        )
        self.session.add(solution)
        self.session.flush()
        return solution, True

    def _same_solution(self, existing: Solution, extracted: ExtractedSolution) -> bool:
        label = (extracted.approach_label or "").strip()
        if label and (existing.approach_label or "").strip() == label:
            return True
        if not label and not (existing.approach_label or "").strip():
            return (existing.steps or []) == (extracted.steps or [])
        return False

    def _attach_figures(
        self, figures: list[ExtractedFigure], owner_type: str, owner_id
    ) -> int:
        created = 0
        for position, figure in enumerate(figures, start=1):
            self.session.add(
                Figure(
                    owner_type=owner_type,
                    owner_id=owner_id,
                    figure_kind=figure.figure_kind,
                    image_path=figure.image_path,
                    tikz_code=figure.tikz_code,
                    caption=figure.caption,
                    position=position,
                    origin=figure.origin,
                    confidence=figure.confidence,
                )
            )
            created += 1
        self.session.flush()
        return created

    # ------------------------------------------------------------------ #
    # 链接                                                                  #
    # ------------------------------------------------------------------ #

    def _link_solution_techniques(
        self, solution: Solution, extracted: ExtractedSolution
    ) -> int:
        created = 0
        for title in extracted.technique_titles:
            key = normalize_semantic_key(title)
            if not key:
                continue
            method = self.session.scalar(
                select(TeachingMethod).where(TeachingMethod.semantic_key == key)
            )
            if method is None:
                continue  # 不新建技巧，避免一题一技巧污染技巧库
            exists = self.session.scalar(
                select(SolutionTechniqueLink).where(
                    SolutionTechniqueLink.solution_id == solution.id,
                    SolutionTechniqueLink.method_id == method.id,
                )
            )
            if exists is not None:
                continue
            self.session.add(
                SolutionTechniqueLink(
                    solution_id=solution.id,
                    method_id=method.id,
                    relation_type="primary",
                    confidence=self.settings.extraction_match_confidence,
                )
            )
            created += 1
        self.session.flush()
        return created

    def _link_problem_section(self, problem: Problem, extracted: ExtractedProblem) -> int:
        section = self._find_section(
            extracted.book_code, extracted.chapter_title, extracted.section_title
        )
        if section is None:
            return 0
        exists = self.session.scalar(
            select(ProblemSectionLink).where(
                ProblemSectionLink.problem_id == problem.id,
                ProblemSectionLink.section_id == section.id,
            )
        )
        if exists is not None:
            return 0
        self.session.add(
            ProblemSectionLink(
                problem_id=problem.id,
                section_id=section.id,
                relation_type="exercise_of",
                confidence=self.settings.extraction_match_confidence,
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

    def _queue_knowledge_point_review(
        self, problem: Problem, extracted: ExtractedProblem
    ) -> int:
        titles = [t.strip() for t in extracted.knowledge_point_titles if t and t.strip()]
        if not titles:
            return 0
        existing = self.session.scalar(
            select(ReviewItem).where(
                ReviewItem.item_type == "problem_knowledge_point",
                ReviewItem.target_id == problem.id,
                ReviewItem.status == ReviewStatus.pending,
            )
        )
        if existing is not None:
            return 0
        proposed = []
        for title in titles:
            match = self.session.scalar(
                select(KnowledgePoint).where(
                    KnowledgePoint.semantic_key == normalize_semantic_key(title)
                )
            )
            proposed.append(
                {"title": title, "matched_knowledge_point_id": str(match.id) if match else None}
            )
        self.session.add(
            ReviewItem(
                item_type="problem_knowledge_point",
                target_table="problems",
                target_id=problem.id,
                status=ReviewStatus.pending,
                reason="题目考察的知识点由 AI 标注，需人工确认后再建立链接。",
                payload={"problem_id": str(problem.id), "proposed": proposed},
            )
        )
        self.session.flush()
        return 1

    def _record_reconciliation(
        self, candidate: CandidateKnowledgeItem, problem: Problem, created: bool
    ) -> None:
        action = ReconciliationAction.create if created else ReconciliationAction.skip
        self.session.add(
            ReconciliationDecision(
                candidate_id=candidate.id,
                action=action,
                matched_table="problems",
                matched_id=problem.id,
                matched_ids=[str(problem.id)],
                rationale="Phase C 规则调和：按语义键判断题目的创建或跳过；解答与链接随题目写入。",
                proposed_patch={
                    "problem_id": str(problem.id),
                    "candidate_id": str(candidate.id),
                    "action": action.value,
                },
                confidence=candidate.confidence,
                auto_applied=True,
                review_status=ReviewStatus.pending,
            )
        )
        self.session.flush()


def extract_and_reconcile_problems(
    session: Session,
    document: SourceDocument,
    text: str,
    settings: Settings | None = None,
) -> dict[str, int]:
    """便捷入口：规则抽取 + 调和——清洗文本 → canonical 题目/解答/链接。

    AI 抽取器（后续切片）只要产出同一 `ExtractedProblem` 契约即可替换 extractor。
    """
    problems = RuleBasedProblemExtractor().extract(text, document.url).problems
    return ProblemReconciler(session, settings).ingest(problems, document)
