from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

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
        final_path = urlparse(str(response.url)).path.lower()
        if re.search(r"(^|/)(login|signin|passport|auth)(/|\.|$)", final_path):
            return True
        text = (
            response.text[:20000]
            if "text" in response.headers.get("content-type", "")
            else ""
        )
        lowered = text.lower()
        protected_markers = (
            "请先登录",
            "请登录后",
            "登录后查看",
            "登录后才能",
            "需要登录",
            "未登录",
            "无权访问",
            "访问受限",
            "login required",
            "please log in",
            "please sign in",
            "unauthorized",
            "access denied",
        )
        if any(marker in lowered for marker in protected_markers):
            return True

        soup = BeautifulSoup(text, "html.parser") if text else None
        if soup is None:
            return False
        has_password_input = soup.find("input", {"type": re.compile("^password$", re.I)})
        if has_password_input is None:
            return False
        title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
        visible_text = soup.get_text(" ", strip=True)
        link_count = len(soup.find_all("a", href=True))
        auth_title = any(keyword in title for keyword in ("登录", "login", "signin", "sign in"))
        return auth_title and len(visible_text) < 2000 and link_count < 20
