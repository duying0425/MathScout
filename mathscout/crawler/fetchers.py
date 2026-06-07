from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from scrapling.fetchers import AsyncFetcher
from scrapling.parser import Adaptor

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
        response = await AsyncFetcher.get(
            url,
            impersonate="chrome",
            stealthy_headers=True,
            follow_redirects=True,
            timeout=30,
        )

        raw = response.body

        content_type = response.headers.get("Content-Type") or response.headers.get("content-type")
        checksum = hashlib.sha256(raw).hexdigest()
        suffix = self._suffix_from_content_type(content_type)
        raw_path = self.settings.raw_storage_dir / f"{checksum}{suffix}"
        raw_path.write_bytes(raw)

        return FetchResult(
            url=str(response.url),
            status_code=response.status,
            content_type=content_type,
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
    def _looks_login_gated(response) -> bool:
        if response.status in {401, 403}:
            return True

        # Check if the final URL path matches a login-related pattern.
        final_path = urlparse(str(response.url)).path.lower()
        if re.search(r"(^|/)(login|signin|passport|auth)(/|\.|$)", final_path):
            return True

        content_type = response.headers.get("Content-Type", "") or ""
        if "text" not in content_type:
            return False

        raw = response.body
        text = raw.decode(response.encoding or "utf-8", errors="ignore")
        sample = text[:20000]
        lowered = sample.lower()

        # Precise multi-word phrases that strongly indicate a login wall.
        # Broad single-character terms like '登录' alone are intentionally excluded
        # to reduce false positives on pages that merely mention login.
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

        # Parse the HTML once with Scrapling's Adaptor (no BeautifulSoup dependency).
        if not sample:
            return False
        page = Adaptor(sample.encode("utf-8"), url=str(response.url), encoding="utf-8")

        # Sparse-page heuristic: very few visible characters + very few links
        # is a strong signal that the real content is hidden behind a login wall.
        visible_text = page.get_all_text()
        link_count = len(page.css("a[href]"))
        if len(visible_text) < 500 and link_count < 5:
            return True

        # A password input on a page with an auth-related title and thin content
        # is the classic login-form fingerprint.
        has_password_input = bool(page.css('input[type="password"]'))
        if not has_password_input:
            return False

        title_els = page.css("title")
        title = title_els[0].text.lower() if title_els else ""
        auth_title = any(
            kw in title for kw in ("登录", "login", "signin", "sign in", "验证")
        )
        return auth_title and len(visible_text) < 2000 and link_count < 20
