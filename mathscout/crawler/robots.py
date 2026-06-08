"""抓取合规：robots.txt 校验与按域限速。

设计为可注入依赖（fetch / sleep / clock），便于在不联网的情况下单元测试。
"""

from __future__ import annotations

import time
import urllib.request
from collections.abc import Callable
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser


def _default_fetch(robots_url: str, user_agent: str, timeout: float = 10.0) -> str | None:
    request = urllib.request.Request(robots_url, headers={"User-Agent": user_agent})  # noqa: S310 - http(s) only
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="ignore")
    except Exception:
        return None


class RobotsChecker:
    """按 origin 缓存 robots.txt，判断某 URL 是否允许抓取。

    遵循"fail-open"约定：没有 robots.txt 或拉取失败时放行——既有的域名启用/
    访问级别等护栏仍在更上层生效。
    """

    def __init__(
        self,
        user_agent: str,
        *,
        fetch: Callable[[str], str | None] | None = None,
    ) -> None:
        self.user_agent = user_agent
        self._fetch = fetch or (lambda url: _default_fetch(url, user_agent))
        self._cache: dict[str, RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return True
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._cache:
            self._cache[origin] = self._load(origin)
        parser = self._cache[origin]
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)

    def _load(self, origin: str) -> RobotFileParser | None:
        content = self._fetch(f"{origin}/robots.txt")
        if content is None:
            return None
        parser = RobotFileParser()
        parser.parse(content.splitlines())
        return parser


class DomainRateLimiter:
    """按域名强制最小请求间隔。

    在单进程顺序执行的作业里用实例级 {域名: 上次请求时刻} 即可。
    """

    def __init__(
        self,
        delay_seconds: float,
        *,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.delay = max(0.0, float(delay_seconds))
        self._sleep = sleep
        self._now = now
        self._last: dict[str, float] = {}

    def wait(self, url: str) -> None:
        if self.delay <= 0:
            return
        domain = urlparse(url).netloc
        if not domain:
            return
        current = self._now()
        last = self._last.get(domain)
        if last is not None and (current - last) < self.delay:
            self._sleep(self.delay - (current - last))
            current = self._now()
        self._last[domain] = current
