from mathscout.runtime import (
    DiscoveryObservation,
    RuntimeObservation,
    RuntimeStatus,
    normalize_task_result,
)


def test_runtime_observation_success_shape_is_stable() -> None:
    observation = RuntimeObservation.success(
        artifact_ids=["doc-1"],
        metrics={"methods": 2},
        payload={"url": "https://example.com"},
    )

    data = observation.model_dump(mode="json")

    assert data == {
        "status": "succeeded",
        "artifact_ids": ["doc-1"],
        "metrics": {"methods": 2},
        "warnings": [],
        "error": None,
        "retryable": True,
        "requires_review": False,
        "review_reason": None,
        "payload": {"url": "https://example.com"},
    }


def test_runtime_observation_failure_and_blocked_review() -> None:
    failed = RuntimeObservation.failure("HTTP 400", retryable=False)
    blocked = RuntimeObservation.blocked_review(
        "需要人工提供访问凭据。",
        payload={"url": "https://example.com/private"},
    )

    assert failed.status == RuntimeStatus.failed
    assert failed.error == "HTTP 400"
    assert failed.retryable is False
    assert blocked.status == RuntimeStatus.blocked
    assert blocked.requires_review is True
    assert blocked.retryable is False
    assert blocked.review_reason == "需要人工提供访问凭据。"


def test_discovery_observation_extends_base_runtime_shape() -> None:
    observation = DiscoveryObservation(
        status=RuntimeStatus.succeeded,
        seed_url="https://example.com",
        selected_count=1,
        created_tasks=1,
        selected_links=[{"url": "https://example.com/math"}],
    )

    data = observation.model_dump(mode="json")

    assert data["status"] == "succeeded"
    assert data["seed_url"] == "https://example.com"
    assert data["selected_count"] == 1
    assert data["created_tasks"] == 1
    assert data["selected_links"] == [{"url": "https://example.com/math"}]


def test_normalize_task_result_preserves_legacy_fields_and_adds_observation_shape() -> None:
    result = normalize_task_result(
        {
            "status": "fetch_failed",
            "http_status": 500,
            "document_id": "doc-1",
            "error": "HTTP 500",
            "retryable": True,
            "candidates": 0,
            "methods": 0,
        }
    )

    assert result["status"] == "fetch_failed"
    assert result["runtime_status"] == "failed"
    assert result["artifact_ids"] == ["doc-1"]
    assert result["metrics"] == {
        "http_status": 500,
        "candidates": 0,
        "methods": 0,
    }
    assert result["warnings"] == []
    assert result["requires_review"] is False
    assert result["payload"] == {}


def test_normalize_task_result_marks_blocked_results_for_review() -> None:
    result = normalize_task_result(
        {
            "status": "blocked_login",
            "error": "需要登录。",
            "http_status": 200,
        }
    )

    assert result["runtime_status"] == "blocked"
    assert result["requires_review"] is True
    assert result["review_reason"] == "需要登录。"
