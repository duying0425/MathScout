from mathscout.crawler.robots import DomainRateLimiter, RobotsChecker

ROBOTS = """
User-agent: *
Disallow: /private/
Allow: /
""".strip()


def test_robots_allows_and_disallows():
    checker = RobotsChecker("MathScout/0.1", fetch=lambda url: ROBOTS)
    assert checker.allowed("https://example.com/lesson/youlishu.html")
    assert not checker.allowed("https://example.com/private/secret.html")


def test_robots_fail_open_when_no_robots():
    # fetch 返回 None（无 robots.txt 或拉取失败）→ 一律放行。
    checker = RobotsChecker("MathScout/0.1", fetch=lambda url: None)
    assert checker.allowed("https://example.com/private/secret.html")


def test_robots_caches_per_origin():
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        return ROBOTS

    checker = RobotsChecker("MathScout/0.1", fetch=fetch)
    checker.allowed("https://example.com/a")
    checker.allowed("https://example.com/b")
    assert calls == ["https://example.com/robots.txt"]  # 仅拉取一次


def test_rate_limiter_sleeps_for_same_domain():
    slept: list[float] = []
    clock = {"t": 100.0}
    limiter = DomainRateLimiter(
        3.0,
        sleep=lambda s: slept.append(s),
        now=lambda: clock["t"],
    )
    limiter.wait("https://example.com/a")  # 首次：不等待
    limiter.wait("https://example.com/b")  # 同域、零间隔 → 等待约 3s
    assert slept and abs(slept[0] - 3.0) < 0.001


def test_rate_limiter_independent_domains():
    slept: list[float] = []
    limiter = DomainRateLimiter(3.0, sleep=lambda s: slept.append(s), now=lambda: 100.0)
    limiter.wait("https://a.com/x")
    limiter.wait("https://b.com/y")  # 不同域 → 不等待
    assert slept == []


def test_rate_limiter_zero_delay_never_sleeps():
    slept: list[float] = []
    limiter = DomainRateLimiter(0, sleep=lambda s: slept.append(s), now=lambda: 0.0)
    limiter.wait("https://a.com/x")
    limiter.wait("https://a.com/y")
    assert slept == []
