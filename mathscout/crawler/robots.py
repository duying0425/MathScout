from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser


class RobotsChecker:
    def __init__(self, user_agent: str, timeout_seconds: int = 5) -> None:
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self._cache: dict[str, RobotFileParser] = {}

    def can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._cache.get(base)
        if parser is None:
            parser = RobotFileParser()
            parser.set_url(f"{base}/robots.txt")
            self._read(parser)
            self._cache[base] = parser
        return parser.can_fetch(self.user_agent, url)

    def _read(self, parser: RobotFileParser) -> None:
        request = Request(parser.url, headers={"User-Agent": self.user_agent})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                lines = response.read().decode("utf-8", errors="ignore").splitlines()
        except HTTPError as exc:
            if exc.code in {401, 403}:
                parser.disallow_all = True
            else:
                parser.allow_all = True
            return
        except URLError:
            parser.allow_all = True
            return
        parser.parse(lines)
