"""运行时观测类型。

目前仅 `review.py` 使用 `ReviewObservation` / `RuntimeStatus` 来返回统一的复核
结果。`RuntimeObservation` 作为各阶段观测的公共基类保留，便于后续把 crawl /
extract / reconcile 的结果也收敛到同一形状（详见 development-status.md 的待办）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RuntimeStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    blocked = "blocked"
    paused = "paused"
    cancelled = "cancelled"


class RuntimeObservation(BaseModel):
    status: RuntimeStatus
    artifact_ids: list[str] = Field(default_factory=list)
    metrics: dict[str, int | float | str | bool | None] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    retryable: bool = True
    requires_review: bool = False
    review_reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ReviewObservation(RuntimeObservation):
    target_table: str | None = None
    target_id: str | None = None
    action: str | None = None
    manual_edit_log_id: str | None = None
