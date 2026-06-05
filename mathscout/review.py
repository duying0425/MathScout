from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mathscout.db.models import (
    CandidateKnowledgeItem,
    ManualEditAction,
    ManualEditLog,
    ReconciliationDecision,
    ReviewItem,
    ReviewStatus,
    TeachingMethod,
    TeachingMethodVariant,
)
from mathscout.runtime import ReviewObservation, RuntimeStatus


class ReviewActionError(ValueError):
    pass


class ReviewService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def apply_candidate_action(
        self,
        candidate_id: str,
        action: str,
        *,
        reason: str = "",
        editor: str = "admin",
    ) -> ReviewObservation:
        candidate = self._get_candidate(candidate_id)
        new_status = self._review_status_for_action(action)
        decisions = self.session.scalars(
            select(ReconciliationDecision).where(
                ReconciliationDecision.candidate_id == candidate.id
            )
        ).all()
        primary_decision = decisions[0] if decisions else None
        before_payload = self._candidate_review_payload(candidate, primary_decision)

        candidate.review_status = new_status
        for decision in decisions:
            decision.review_status = new_status
        if new_status in {ReviewStatus.approved, ReviewStatus.rejected}:
            self._set_related_canonical_review_status(candidate, decisions, new_status)

        log = ManualEditLog(
            target_table="candidate_knowledge_items",
            target_id=candidate.id,
            action=self._manual_action_for_review(action),
            before_payload=before_payload,
            after_payload=self._candidate_review_payload(candidate, primary_decision),
            reason=reason.strip() or None,
            editor=editor,
            related_decision_id=primary_decision.id if primary_decision is not None else None,
            can_rollback=False,
        )
        self.session.add(log)
        self.session.flush()
        return ReviewObservation(
            status=RuntimeStatus.succeeded,
            target_table="candidate_knowledge_items",
            target_id=str(candidate.id),
            action=action,
            manual_edit_log_id=str(log.id),
            artifact_ids=[str(candidate.id)],
            payload={
                "review_status": new_status.value,
                "candidate_id": str(candidate.id),
                "decision_id": str(primary_decision.id) if primary_decision is not None else None,
            },
        )

    def apply_review_item_action(
        self,
        item_id: str,
        action: str,
        *,
        reason: str = "",
        editor: str = "admin",
    ) -> ReviewObservation:
        item = self._get_review_item(item_id)
        before_payload = self._review_item_payload(item)
        new_status = self._review_status_for_action(action)
        item.status = new_status
        log = ManualEditLog(
            target_table=item.target_table or "review_items",
            target_id=item.target_id or item.id,
            action=self._manual_action_for_review(action),
            before_payload=before_payload,
            after_payload=self._review_item_payload(item),
            reason=reason.strip() or item.reason,
            editor=editor,
            related_review_item_id=item.id,
            can_rollback=False,
        )
        self.session.add(log)
        self.session.flush()
        return ReviewObservation(
            status=RuntimeStatus.succeeded,
            target_table=item.target_table or "review_items",
            target_id=str(item.target_id or item.id),
            action=action,
            manual_edit_log_id=str(log.id),
            artifact_ids=[str(item.id)],
            payload={
                "review_status": new_status.value,
                "review_item_id": str(item.id),
                "item_type": item.item_type,
            },
        )

    def _get_candidate(self, candidate_id: str) -> CandidateKnowledgeItem:
        try:
            parsed_id = uuid.UUID(candidate_id)
        except ValueError as exc:
            raise ReviewActionError("找不到候选项。") from exc
        candidate = self.session.get(CandidateKnowledgeItem, parsed_id)
        if candidate is None:
            raise ReviewActionError("找不到候选项。")
        return candidate

    def _get_review_item(self, item_id: str) -> ReviewItem:
        try:
            parsed_id = uuid.UUID(item_id)
        except ValueError as exc:
            raise ReviewActionError("找不到复核项。") from exc
        item = self.session.get(ReviewItem, parsed_id)
        if item is None:
            raise ReviewActionError("找不到复核项。")
        return item

    def _review_status_for_action(self, action: str) -> ReviewStatus:
        if action == "approve":
            return ReviewStatus.approved
        if action == "reject":
            return ReviewStatus.rejected
        if action == "needs-edit":
            return ReviewStatus.needs_edit
        raise ReviewActionError("未知复核操作。")

    def _manual_action_for_review(self, action: str) -> ManualEditAction:
        if action == "approve":
            return ManualEditAction.approve_ai_change
        if action == "reject":
            return ManualEditAction.reject_ai_change
        if action == "needs-edit":
            return ManualEditAction.update
        raise ReviewActionError("未知复核操作。")

    def _candidate_review_payload(
        self,
        candidate: CandidateKnowledgeItem,
        decision: ReconciliationDecision | None,
    ) -> dict[str, Any]:
        return {
            "candidate_id": str(candidate.id),
            "title": candidate.title,
            "review_status": candidate.review_status.value,
            "document_id": str(candidate.document_id),
            "confidence": candidate.confidence,
            "decision_id": str(decision.id) if decision is not None else None,
            "decision_status": decision.review_status.value if decision is not None else None,
        }

    def _review_item_payload(self, item: ReviewItem) -> dict[str, Any]:
        return {
            "review_item_id": str(item.id),
            "item_type": item.item_type,
            "target_table": item.target_table,
            "target_id": str(item.target_id) if item.target_id is not None else None,
            "review_status": item.status.value,
            "reason": item.reason,
        }

    def _set_related_canonical_review_status(
        self,
        candidate: CandidateKnowledgeItem,
        decisions: list[ReconciliationDecision],
        status: ReviewStatus,
    ) -> None:
        evidence_ids = self._candidate_evidence_ids(candidate)
        for decision in decisions:
            if decision.matched_table != "teaching_methods" or decision.matched_id is None:
                continue
            method = self.session.get(TeachingMethod, decision.matched_id)
            if method is None:
                continue
            if status == ReviewStatus.approved and method.review_status == ReviewStatus.pending:
                method.review_status = status
            elif status == ReviewStatus.rejected and method.evidence_id in evidence_ids:
                method.review_status = status

        variants = self.session.scalars(
            select(TeachingMethodVariant).where(
                TeachingMethodVariant.source_document_id == candidate.document_id
            )
        ).all()
        for variant in variants:
            if variant.evidence_id in evidence_ids or variant.title == candidate.title:
                variant.review_status = status

    def _candidate_evidence_ids(self, candidate: CandidateKnowledgeItem) -> set[uuid.UUID]:
        evidence_ids: set[uuid.UUID] = set()
        for raw_id in candidate.evidence_ids or []:
            try:
                evidence_ids.add(uuid.UUID(str(raw_id)))
            except ValueError:
                continue
        return evidence_ids
