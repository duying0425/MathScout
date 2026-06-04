from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import httpx

from mathscout.config import get_settings


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    content_type: str | None
    checksum: str
    raw_path: Path
    needs_login: bool = False


class HttpFetcher:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def fetch(self, url: str) -> FetchResult:
        headers = {"User-Agent": self.settings.default_user_agent}
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30) as client:
            response = await client.get(url)

        content = response.content
        checksum = hashlib.sha256(content).hexdigest()
        suffix = self._suffix_from_content_type(response.headers.get("content-type"))
        raw_path = self.settings.raw_storage_dir / f"{checksum}{suffix}"
        raw_path.write_bytes(content)

        return FetchResult(
            url=str(response.url),
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            checksum=checksum,
            raw_path=raw_path,
            needs_login=self._looks_login_gated(response),
        )

    @staticmethod
    def _suffix_from_content_type(content_type: str | None) -> str:
        if not content_type:
            return ".bin"
        if "pdf" in content_type:
            return ".pdf"
        if "html" in content_type:
            return ".html"
        if "json" in content_type:
            return ".json"
        return ".bin"

    @staticmethod
    def _looks_login_gated(response: httpx.Response) -> bool:
        if response.status_code in {401, 403}:
            return True
        text = (
            response.text[:5000].lower()
            if "text" in response.headers.get("content-type", "")
            else ""
        )
        markers = ("登录", "login", "captcha", "验证码")
        return any(marker in text for marker in markers)
