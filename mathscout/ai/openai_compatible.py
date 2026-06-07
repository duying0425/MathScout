from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from mathscout.config import Settings, get_settings


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


class OpenAICompatibleClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.ai_api_key:
            raise ValueError("Missing DEEPSEEK_API_KEY or OPENAI_COMPATIBLE_API_KEY.")

    def chat_json(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        url = self.settings.openai_compatible_base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.settings.openai_compatible_model,
            "messages": [message.__dict__ for message in messages],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.settings.ai_api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self.settings.openai_compatible_timeout_seconds) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return self._parse_json_content(content)

    @staticmethod
    def _parse_json_content(content: str) -> dict[str, Any]:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise
            return json.loads(content[start : end + 1])
