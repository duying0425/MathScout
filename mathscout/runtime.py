from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, Field


class RuntimeStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    blocked = "blocked"
    paused = "paused"
    cancelled = "cancelled"


LEGACY_STATUS_TO_RUNTIME_STATUS = {
    "succeeded": RuntimeStatus.succeeded,
    "failed": RuntimeStatus.failed,
    "blocked": RuntimeStatus.blocked,
    "fetch_failed": RuntimeStatus.failed,
    "blocked_login": RuntimeStatus.blocked,
    "pending": RuntimeStatus.pending,
    "running": RuntimeStatus.running,
    "paused": RuntimeStatus.paused,
    "cancelled": RuntimeStatus.cancelled,
}

TASK_METRIC_KEYS = {
    "http_status",
    "selected_count",
    "created_tasks",
    "candidates",
    "methods",
    "variants",
}


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

    @classmethod
    def success(
        cls,
        *,
        artifact_ids: list[str] | None = None,
        metrics: dict[str, int | float | str | bool | None] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Self:
        return cls(
            status=RuntimeStatus.succeeded,
            artifact_ids=artifact_ids or [],
            metrics=metrics or {},
            payload=payload or {},
        )

    @classmethod
    def failure(
        cls,
        error: str,
        *,
        retryable: bool = True,
        payload: dict[str, Any] | None = None,
    ) -> Self:
        return cls(
            status=RuntimeStatus.failed,
            error=error,
            retryable=retryable,
            payload=payload or {},
        )

    @classmethod
    def blocked_review(
        cls,
        reason: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> Self:
        return cls(
            status=RuntimeStatus.blocked,
            requires_review=True,
            review_reason=reason,
            retryable=False,
            payload=payload or {},
        )


class FetchObservation(RuntimeObservation):
    url: str
    final_url: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    raw_path: str | None = None
    text_path: str | None = None
    needs_login: bool = False


class DiscoveryObservation(RuntimeObservation):
    seed_url: str
    selected_count: int = 0
    created_tasks: int = 0
    selected_links: list[dict[str, Any]] = Field(default_factory=list)
    fallback_used: bool = False


class ExtractionObservation(RuntimeObservation):
    document_id: str | None = None
    candidate_count: int = 0
    method_count: int = 0
    variant_count: int = 0
    extractor_name: str | None = None
    model_name: str | None = None


class ReconciliationObservation(RuntimeObservation):
    candidate_id: str | None = None
    action: str | None = None
    matched_ids: list[str] = Field(default_factory=list)
    decision_id: str | None = None
    auto_applied: bool = False


class MonitorObservation(RuntimeObservation):
    action: str | None = None
    strategy_patch: dict[str, Any] = Field(default_factory=dict)


class ReviewObservation(RuntimeObservation):
    target_table: str | None = None
    target_id: str | None = None
    action: str | None = None
    manual_edit_log_id: str | None = None


def normalize_task_result(result: dict[str, Any]) -> dict[str, Any]:
    """Add stable observation fields while preserving legacy task result keys."""
    normalized = dict(result)
    runtime_status = _runtime_status_for_result(normalized)
    normalized["runtime_status"] = runtime_status.value
    normalized.setdefault("artifact_ids", _artifact_ids_for_result(normalized))
    normalized.setdefault("metrics", _metrics_for_result(normalized))
    normalized.setdefault("warnings", [])
    normalized.setdefault("error", normalized.get("error"))
    normalized.setdefault("retryable", True)
    normalized.setdefault("requires_review", runtime_status == RuntimeStatus.blocked)
    normalized.setdefault(
        "review_reason",
        _review_reason_for_result(normalized, runtime_status),
    )
    payload = normalized.get("payload")
    normalized["payload"] = payload if isinstance(payload, dict) else {}
    return normalized


def _runtime_status_for_result(result: dict[str, Any]) -> RuntimeStatus:
    explicit_status = result.get("runtime_status")
    if explicit_status is not None:
        return _parse_runtime_status(str(explicit_status))
    legacy_status = str(result.get("status") or "")
    return _parse_runtime_status(legacy_status)


def _parse_runtime_status(value: str) -> RuntimeStatus:
    status = LEGACY_STATUS_TO_RUNTIME_STATUS.get(value)
    if status is not None:
        return status
    return RuntimeStatus.failed


def _artifact_ids_for_result(result: dict[str, Any]) -> list[str]:
    artifact_ids = result.get("artifact_ids")
    if isinstance(artifact_ids, list):
        return [str(item) for item in artifact_ids]
    document_id = result.get("document_id")
    return [str(document_id)] if document_id else []


def _metrics_for_result(result: dict[str, Any]) -> dict[str, int | float | str | bool | None]:
    metrics = result.get("metrics")
    if isinstance(metrics, dict):
        return {
            str(key): value
            for key, value in metrics.items()
            if isinstance(value, int | float | str | bool) or value is None
        }
    return {
        key: result[key]
        for key in TASK_METRIC_KEYS
        if key in result
        and (isinstance(result.get(key), int | float | str | bool) or result.get(key) is None)
    }


def _review_reason_for_result(
    result: dict[str, Any],
    runtime_status: RuntimeStatus,
) -> str | None:
    if runtime_status != RuntimeStatus.blocked:
        return None
    if result.get("review_reason"):
        return str(result["review_reason"])
    if result.get("error"):
        return str(result["error"])
    if result.get("status") == "blocked_login":
        return "页面需要登录或访问受限，需要人工复核。"
    return "任务执行结果需要人工复核。"
