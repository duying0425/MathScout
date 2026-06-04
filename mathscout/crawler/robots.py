from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser


class RobotsChecker:
    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent
        self._cache: dict[str, RobotFileParser] = {}

    def can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._cache.get(base)
        if parser is None:
            parser = RobotFileParser()
            parser.set_url(f"{base}/robots.txt")
            parser.read()
            self._cache[base] = parser
        return parser.can_fetch(self.user_agent, url)
