from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AgentStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    blocked = "blocked"


@dataclass
class AgentResult:
    status: AgentStatus
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
